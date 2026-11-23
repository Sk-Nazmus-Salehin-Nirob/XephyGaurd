"""HTTP service used by the CCC (ScoreSession job).

    POST /score   {"session_id": 12}   (Authorization: Bearer $XG_ANALYSIS_TOKEN)
    GET  /health

XG_ANALYSIS_TOKEN is this service's own secret, shared only with the CCC (I-ANALYSIS-17). The
proxy's XG_INTERNAL_TOKEN is never accepted here.

Listens on XG_ANALYSIS_BIND (default 127.0.0.1) : XG_ANALYSIS_PORT (default 8090). The CCC runs with
host networking, so 0.0.0.0 would expose the service to the lab LAN (I-ANALYSIS-1).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .db import Db, db_url
from .features import scoring_lists
from .pipeline import score_session

log = logging.getLogger("xg-analysis")


def authorized(header: str) -> bool:
    """True when the Authorization header carries XG_ANALYSIS_TOKEN (unset token = nobody)."""
    token = os.environ.get("XG_ANALYSIS_TOKEN", "").strip()
    given = header.removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(token.encode(), given.encode())


class Handler(BaseHTTPRequestHandler):
    server_version = "xephyguard-analysis/0.1"

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            ok = Db().ping()
            self._send(200 if ok else 503, {"ok": ok})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not authorized(self.headers.get("Authorization", "")):
            return self._send(401, {"error": "unauthorized"})
        if self.path != "/score":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
            sid = int(body["session_id"])
            self._send(200, score_session(Db(), sid))
        except KeyError as e:
            self._send(404, {"error": str(e)})
        except (ValueError, TypeError) as e:
            self._send(422, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("scoring failed")
            self._send(500, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)


def listen_address() -> tuple[str, int]:
    """(host, port) to bind: XG_ANALYSIS_BIND (unset or empty = 127.0.0.1) and XG_ANALYSIS_PORT."""
    host = os.environ.get("XG_ANALYSIS_BIND", "").strip() or "127.0.0.1"
    return host, int(os.environ.get("XG_ANALYSIS_PORT", "8090"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host, port = listen_address()
    try:
        db_url()
        scoring_lists()          # data/analysis/scoring.yaml: fail now, not on the first /score
    except RuntimeError as e:
        raise SystemExit(f"xg-analysis: {e}") from None
    if not os.environ.get("XG_ANALYSIS_TOKEN", "").strip():
        log.warning("XG_ANALYSIS_TOKEN is not set: every /score request is refused")
    log.info("analysis service on %s:%d", host, port)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
