import io
import json

import pytest
from conftest import SCHEMA, LabBuilder

from xg_analysis import service
from xg_analysis.db import Db
from xg_analysis.service import Handler, authorized, listen_address

TOKEN = "analysis-token-1234"


def test_binds_loopback_by_default(monkeypatch):
    monkeypatch.delenv("XG_ANALYSIS_BIND", raising=False)
    monkeypatch.delenv("XG_ANALYSIS_PORT", raising=False)
    assert listen_address() == ("127.0.0.1", 8090)          # not 0.0.0.0 under host networking (I-ANALYSIS-1)
    monkeypatch.setenv("XG_ANALYSIS_BIND", "  ")
    assert listen_address() == ("127.0.0.1", 8090)
    monkeypatch.setenv("XG_ANALYSIS_BIND", "10.0.0.5")
    monkeypatch.setenv("XG_ANALYSIS_PORT", "9000")
    assert listen_address() == ("10.0.0.5", 9000)


def test_main_listens_on_the_configured_address(monkeypatch):
    bound = []

    class FakeServer:
        def __init__(self, addr, handler):
            bound.append((addr, handler))

        def serve_forever(self):
            pass

    monkeypatch.setattr(service, "ThreadingHTTPServer", FakeServer)
    monkeypatch.delenv("XG_ANALYSIS_BIND", raising=False)
    monkeypatch.delenv("XG_ANALYSIS_PORT", raising=False)
    service.main()
    assert bound == [(("127.0.0.1", 8090), Handler)]


def test_score_endpoint_accepts_only_the_analysis_token(monkeypatch):
    monkeypatch.setenv("XG_ANALYSIS_TOKEN", "analysis-token-1234")
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "internal-token-5678")
    assert authorized("Bearer analysis-token-1234")
    assert not authorized("Bearer internal-token-5678")   # the proxy's token (I-ANALYSIS-17)
    assert not authorized("Bearer ")
    assert not authorized("")


def test_unset_analysis_token_refuses_everyone(monkeypatch):
    monkeypatch.delenv("XG_ANALYSIS_TOKEN", raising=False)
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "internal-token-5678")
    assert not authorized("Bearer internal-token-5678")
    assert not authorized("Bearer ")


# --- Characterization of the HTTP handler (I-ANALYSIS-26) ---------------------------------------
# The real Handler parses a raw HTTP request from a fake socket, so no port or thread is needed and
# a body larger than the read cap cannot end in a connection reset.

class FakeSocket:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.out = bytearray()

    def makefile(self, mode, *args, **kwargs):
        return io.BytesIO(self.raw)

    def sendall(self, data):
        self.out += data

    def settimeout(self, t):
        pass


def call(method: str, path: str, body: bytes = b"", token: str | None = TOKEN, headers: dict | None = None):
    hdrs = {"Host": "127.0.0.1:8090", **({"Authorization": f"Bearer {token}"} if token is not None else {}),
            **({"Content-Length": str(len(body))} if body else {}), **(headers or {})}
    raw = f"{method} {path} HTTP/1.1\r\n".encode() + b"".join(f"{k}: {v}\r\n".encode() for k, v in hdrs.items()) + b"\r\n" + body
    sock = FakeSocket(raw)
    Handler(sock, ("127.0.0.1", 50000), None)
    head, _, payload = bytes(sock.out).partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, (json.loads(payload) if payload else None)


@pytest.fixture
def service_db(tmp_path, monkeypatch):
    """A file database the handler opens itself through XG_DB_URL, with one scorable session (id 10)."""
    url = f"sqlite:///{(tmp_path / 'xg.sqlite').as_posix()}"
    d = Db(url)
    d.conn.executescript(SCHEMA)
    lab = LabBuilder(d)
    lab.session(10, "test")
    pc = lab.pc(10, "A1")
    lab.student(1, "alice")
    lab.typing(10, pc, "alice", 1, 5)
    d.conn.commit()
    monkeypatch.setenv("XG_DB_URL", url)
    monkeypatch.setenv("XG_ANALYSIS_TOKEN", TOKEN)
    monkeypatch.setenv("XG_SCORING_V2", "0")
    yield d
    d.conn.close()


def test_score_without_or_with_wrong_token_is_401(service_db, monkeypatch):
    monkeypatch.setenv("XG_INTERNAL_TOKEN", "internal-token-5678")
    body = b'{"session_id": 10}'
    assert call("POST", "/score", body, token=None) == (401, {"error": "unauthorized"})
    assert call("POST", "/score", body, token="wrong")[0] == 401
    assert call("POST", "/score", body, token="internal-token-5678")[0] == 401
    assert call("POST", "/nope", body, token=None)[0] == 401          # token is checked before the path
    assert service_db.conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 0


def test_score_with_token_scores_the_session(service_db):
    status, out = call("POST", "/score", b'{"session_id": 10}')
    assert status == 200
    assert out == {"session_id": 10, "scored": 1, "flagged": []}
    assert service_db.conn.execute("SELECT count(*) FROM scores WHERE lab_session_id = 10").fetchone()[0] == 1


def test_unknown_paths_and_sessions_are_404(service_db):
    assert call("POST", "/other", b'{"session_id": 10}') == (404, {"error": "not found"})
    assert call("GET", "/score") == (404, {"error": "not found"})
    status, out = call("POST", "/score", b'{"session_id": 99}')
    assert status == 404 and "session 99 not found" in out["error"]
    # Current behaviour: a missing session_id is the same KeyError, so also 404 (Step 16 makes it 422).
    assert call("POST", "/score", b'{}')[0] == 404
    assert call("POST", "/score", b"")[0] == 404


@pytest.mark.parametrize("body", [b"{not json", b'{"session_id": "abc"}', b'{"session_id": null}', b"[10]"])
def test_malformed_body_is_422(service_db, body):
    status, out = call("POST", "/score", body)
    assert status == 422 and out["error"]
    assert service_db.conn.execute("SELECT count(*) FROM scores").fetchone()[0] == 0


def test_body_is_read_up_to_64_kib_only(service_db):
    head = b'{"session_id": 10}'
    # Everything after byte 65536 is never read: valid JSON padded to the cap still scores ...
    assert call("POST", "/score", head + b" " * (65536 - len(head)) + b"trailing junk")[0] == 200
    # ... and JSON that only ends after the cap is cut off, so it does not parse.
    status, _ = call("POST", "/score", b'{"session_id": 10, "pad": "' + b"x" * 70000 + b'"}')
    assert status == 422


def test_health_needs_no_token_and_reports_the_db(service_db, monkeypatch):
    assert call("GET", "/health", token=None) == (200, {"ok": True})
    assert call("GET", "/health", token="wrong") == (200, {"ok": True})
    # A connection whose query fails is reported as 503.
    monkeypatch.setattr(Db, "ping", lambda self: False)
    assert call("GET", "/health", token=None) == (503, {"ok": False})


def test_health_when_the_db_cannot_be_opened_sends_no_response(tmp_path, monkeypatch):
    # Current behaviour: Db() raises before ping(), so the handler raises and the server drops the
    # connection without any status (no 503). Step 15 reworks /health.
    monkeypatch.setenv("XG_DB_URL", f"sqlite:///{(tmp_path / 'missing' / 'xg.sqlite').as_posix()}")
    with pytest.raises(Exception, match="unable to open database file"):
        call("GET", "/health", token=None)
