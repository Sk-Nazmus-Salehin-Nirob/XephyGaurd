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
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .db import Db, db_url
from .features import SessionNotFound, scoring_lists
from .pipeline import score_session

log = logging.getLogger("xg-analysis")


def authorized(header: str) -> bool:
    """True when the Authorization header carries XG_ANALYSIS_TOKEN (unset token = nobody)."""
    token = os.environ.get("XG_ANALYSIS_TOKEN", "").strip()
    given = header.removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(token.encode(), given.encode())


class HealthCheck:
    """GET /health without a token: one reused DB connection and at most one check per CACHE_S, so
    repeated calls cannot use up MySQL connections (I-ANALYSIS-6)."""

    CACHE_S = 5.0

    def __init__(self, connect: Callable[[], Db] = Db, clock: Callable[[], float] = time.monotonic):
        self._connect = connect
        self._clock = clock
        self._lock = threading.Lock()
        self._db: Db | None = None
        self._ok = False
        self._checked_at: float | None = None

    def ok(self) -> bool:
        with self._lock:
            if self._checked_at is None or self._clock() - self._checked_at >= self.CACHE_S:
                self._ok = self._check()
                self._checked_at = self._clock()
            return self._ok

    def _check(self) -> bool:
        for _ in range(2):   # a connection the server dropped (e.g. wait_timeout) gets one fresh retry
            if self._db is None:
                try:
                    self._db = self._connect()
                except Exception as e:  # noqa: BLE001
                    log.warning("health: cannot open the database: %s", e)
                    return False
            if self._db.ping():
                return True
            self._close()
        return False

    def _close(self) -> None:
        try:
            self._db.conn.close()
        except Exception:  # noqa: BLE001
            pass
        self._db = None


HEALTH = HealthCheck()


class Handler(BaseHTTPRequestHandler):
    server_version = "xephyguard-analysis/0.1"
    # Seconds per socket read/write: a client that trickles its headers or body is dropped instead of
    # holding a thread forever (I-ANALYSIS-5). Scoring time itself is not limited by this.
    timeout = 10
    MAX_BODY = 65536

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            ok = HEALTH.ok()
            self._send(200 if ok else 503, {"ok": ok})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not authorized(self.headers.get("Authorization", "")):
            return self._send(401, {"error": "unauthorized"})
        if self.path != "/score":
            return self._send(404, {"error": "not found"})
        # The token and path are checked before any body byte is read. A negative length would make
        # rfile.read(-1) read until EOF (I-ANALYSIS-15), so only plain non-negative integers are accepted.
        length = self.headers.get("Content-Length", "0").strip()
        if not (length.isascii() and length.isdigit()):
            return self._send(400, {"error": "invalid Content-Length"})
        # 422 only for a bad request; once scoring starts, any error (KeyError, ValueError, ...) is a bug or
        # an outage and answers 500, except an unknown session (404) (I-ANALYSIS-14).
        try:
            body = json.loads(self.rfile.read(min(int(length), self.MAX_BODY)) or b"{}")
            if not isinstance(body, dict) or "session_id" not in body:
                return self._send(422, {"error": "session_id is required"})
            sid = int(body["session_id"])
        except (ValueError, TypeError) as e:
            return self._send(422, {"error": str(e)})
        try:
            self._send(200, score_session(Db(), sid))
        except SessionNotFound as e:
            self._send(404, {"error": str(e)})
        except Exception:  # noqa: BLE001
            # Driver errors can name the DB user and host: the details stay in the log, the caller gets an
            # id to find them (I-ANALYSIS-16).
            error_id = uuid.uuid4().hex[:12]
            log.exception("scoring session %d failed (error_id=%s)", sid, error_id)
            self._send(500, {"error": "internal error", "error_id": error_id})

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
