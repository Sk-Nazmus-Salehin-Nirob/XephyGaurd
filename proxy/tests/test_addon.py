"""Exercises the mitmproxy addon with mitmproxy's own test helpers (recorded-style flows)."""
import pathlib

import pytest

mitmproxy = pytest.importorskip("mitmproxy")
from mitmproxy.test import taddons, tflow, tutils  # noqa: E402

from xg_netpolicy import generate  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def addon(state_file, tmp_path):
    import importlib.util
    import pathlib

    generate.generate(state_file, tmp_path / "net")
    spec = importlib.util.spec_from_file_location(
        "xephyguard_addon", pathlib.Path(__file__).resolve().parent.parent / "addons" / "xephyguard_addon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a = mod.XephyGuard()
    with taddons.context(a) as tctx:
        tctx.configure(a, xg_policy=str(tmp_path / "net" / "proxy.json"),
                       xg_events_fallback=str(tmp_path / "events.jsonl"))
        yield a
    a.done()


def _flow(ip, host, path, scheme="https"):
    f = tflow.tflow()
    f.client_conn.peername = (ip, 50000)
    f.request.host = host
    f.request.headers["Host"] = host
    f.request.scheme = scheme
    f.request.port = 443 if scheme == "https" else 80
    f.request.path = path
    return f


def test_google_search_forced_to_web_results(addon):
    f = _flow("192.168.10.21", "www.google.com", "/search?q=quicksort+in+python")
    addon.request(f)
    assert f.request.query.get("udm") == "14"
    assert f.response is None


def test_google_not_rewritten_without_session(addon):
    f = _flow("192.168.10.99", "www.google.com", "/search?q=quicksort")
    addon.request(f)
    assert "udm" not in f.request.query


def test_plain_http_blocked_domain(addon):
    f = _flow("192.168.10.21", "chat.openai.com", "/", scheme="http")
    addon.request(f)
    assert f.response.status_code == 403
    assert b"blocked" in f.response.content


def test_path_rule_blocked(addon):
    f = _flow("192.168.10.21", "huggingface.co", "/chat/")
    addon.request(f)
    assert f.response.status_code == 403


def test_tls_clienthello_blocks_without_decryption(addon):
    from mitmproxy import tls
    from mitmproxy.proxy import context

    client = tutils.tclient_conn() if hasattr(tutils, "tclient_conn") else tflow.tclient_conn()
    client.peername = ("192.168.10.21", 40000)
    ctx = context.Context(client, None)
    ch = tls.ClientHello(_client_hello_bytes("claude.ai"))
    data = tls.ClientHelloData(ctx, ch)
    addon.tls_clienthello(data)
    assert data.ignore_connection is True
    assert client.id in addon.blocked_conns


def test_response_css_injection(addon):
    from mitmproxy import http

    f = _flow("192.168.10.21", "www.google.com", "/search?q=x&udm=14")
    f.response = http.Response.make(200, b"<html><head></head><body>r</body></html>", {"content-type": "text/html"})
    addon.response(f)
    assert b'id="xephyguard"' in f.response.content


def test_tls_clienthello_observes_allowed_ai_and_ide_traffic(addon):
    from mitmproxy import tls
    from mitmproxy.proxy import context

    # Drain queue synchronously by reading emitted events after draining worker or inspecting queue before flush
    emitted = []
    orig_emit = addon.events.emit
    addon.events.emit = lambda **kw: emitted.append(kw) or orig_emit(**kw)

    def send_sni(ip, sni):
        client = tutils.tclient_conn() if hasattr(tutils, "tclient_conn") else tflow.tclient_conn()
        client.peername = (ip, 40000)
        ctx = context.Context(client, None)
        ch = tls.ClientHello(_client_hello_bytes(sni))
        data = tls.ClientHelloData(ctx, ch)
        addon.tls_clienthello(data)
        return data

    # 192.168.10.30 is in block_ai (blocks "ai", allows "ide"): Copilot backend passes but is observed!
    d1 = send_sni("::ffff:192.168.10.30", "api.individual.githubcopilot.com")
    assert d1.ignore_connection is True
    # Second hit within window is deduplicated for the same (client_ip, matched)
    send_sni("192.168.10.30", "api.individual.githubcopilot.com")
    # Unrelated non-AI domain produces nothing when log_urls.enabled is False
    send_sni("192.168.10.30", "github.com")
    # Practice / no-session PC reaching ChatGPT is also observed
    send_sni("192.168.10.99", "chat.openai.com")

    assert len(emitted) == 2
    assert emitted[0]["action"] == "observed"
    assert emitted[0]["category"] == "ide"
    assert emitted[0]["matched"] == "githubcopilot.com"
    assert emitted[1]["action"] == "observed"
    assert emitted[1]["category"] == "ai"
    assert emitted[1]["matched"] == "openai.com"


def test_http_request_observes_allowed_ai_path(addon):
    emitted = []
    orig_emit = addon.events.emit
    addon.events.emit = lambda **kw: emitted.append(kw) or orig_emit(**kw)

    # Exempt / non-session PC browsing duckduckgo AI chat via inspected/HTTP proxy
    f = _flow("192.168.10.99", "duckduckgo.com", "/aichat?q=hi")
    addon.request(f)
    assert f.response is None
    assert len(emitted) == 1
    assert emitted[0]["action"] == "observed"
    assert emitted[0]["category"] == "ai"
    assert emitted[0]["matched"] == "duckduckgo.com/aichat"


@pytest.mark.parametrize("log_urls", [{"enabled": True, "query": False}, {"enabled": True, "query": True}])
def test_allowed_and_observed_events_never_carry_the_query(addon, log_urls):
    emitted = []
    addon.events.emit = lambda **kw: emitted.append(kw)
    addon.cache.reload(force=True)
    addon.cache.state.log_urls = log_urls
    addon.request(_flow("192.168.10.99", "example.com", "/docs/page?q=my+exam+answer&x=1#frag"))
    addon.request(_flow("192.168.10.99", "duckduckgo.com", "/aichat?q=write+my+essay"))
    addon.request(_flow("192.168.10.99", "example.org", "?q=only"))
    assert [(e["action"], e["host"], e["path"]) for e in emitted] == [
        ("allowed", "example.com", "/docs/page"),
        ("observed", "duckduckgo.com", "/aichat"),
        ("allowed", "example.org", "/"),
    ]
    assert not any("q=" in e["path"] or "?" in e["path"] for e in emitted)


def _client_hello_bytes(sni: str) -> bytes:
    """Builds a minimal TLS 1.2 ClientHello handshake body with an SNI extension."""
    import struct

    name = sni.encode()
    sni_ext_data = struct.pack("!H", len(name) + 3) + b"\x00" + struct.pack("!H", len(name)) + name
    ext = struct.pack("!HH", 0, len(sni_ext_data)) + sni_ext_data
    body = (b"\x03\x03" + b"\x00" * 32 + b"\x00" + struct.pack("!H", 2) + b"\x13\x01" + b"\x01\x00"
            + struct.pack("!H", len(ext)) + ext)
    return body


def _server_data(ip, address):
    from mitmproxy import connection
    from mitmproxy.proxy import server_hooks

    client = tflow.tclient_conn()
    client.peername = (ip, 40001)
    server = connection.Server(address=address)
    return server_hooks.ServerConnectionHookData(client=client, server=server)


@pytest.mark.parametrize("address", [
    ("127.0.0.1", 443), ("127.0.0.1", 8953), ("localhost", 443), ("::1", 443), ("::ffff:127.0.0.1", 443),
    ("169.254.169.254", 80), ("fe80::1", 443), ("192.168.10.2", 443), ("0.0.0.0", 80),
    ("93.184.215.14", 22), ("93.184.215.14", 8080),
])
def test_server_connect_refuses_internal_and_odd_ports(addon, address):
    import asyncio

    for ip in ("192.168.10.21", "192.168.10.22", "192.168.10.99"):   # test, exempt, no group
        data = _server_data(ip, address)
        asyncio.run(addon.server_connect(data))
        assert data.server.error and "blocked by XephyGuard" in data.server.error


def test_server_connect_allows_public_web(addon):
    import asyncio

    for address in (("93.184.215.14", 443), ("93.184.215.14", 80)):
        data = _server_data("192.168.10.99", address)
        asyncio.run(addon.server_connect(data))
        assert data.server.error is None


def test_server_connect_pins_resolved_name(addon, monkeypatch):
    import asyncio
    import socket

    answers = {"example.org": "93.184.215.14", "evil.example": "127.0.0.1"}

    async def fake_getaddrinfo(self, host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers[host], port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    ok = _server_data("192.168.10.99", ("example.org", 443))
    asyncio.run(addon.server_connect(ok))
    assert ok.server.error is None
    assert ok.server.address == ("93.184.215.14", 443) and ok.server.sni == "example.org"

    bad = _server_data("192.168.10.99", ("evil.example", 443))
    asyncio.run(addon.server_connect(bad))
    assert "loopback" in bad.server.error


def test_addon_hooks_split_into_modules_and_load_as_script():
    """Step 16: the hooks live in hooks_shipper/hooks_tls/hooks_http; mitmproxy -s still loads one file."""
    import pathlib

    from mitmproxy.addons import script

    path = pathlib.Path(__file__).resolve().parent.parent / "addons" / "xephyguard_addon.py"
    mod = script.load_script(str(path))
    assert mod is not None and len(mod.addons) == 1
    a = mod.addons[0]
    where = {"load": "hooks_shipper", "configure": "hooks_shipper", "done": "hooks_shipper",
             "tls_clienthello": "hooks_tls", "server_connect": "hooks_tls", "client_disconnected": "hooks_tls",
             "request": "hooks_http", "response": "hooks_http"}
    for hook, module in where.items():
        assert getattr(type(a), hook).__module__ == module, hook
    assert a.cache is None and a.events is None and a.blocked_conns == set()


# -- Step 19 (I-PROXY-31): docs/PROTOCOL.md lists every action/layer the addon emits --

def _emitted_pairs():
    """(action, layer) of every events.emit(...) in the hook modules; a conditional layer gives both."""
    import ast

    pairs = set()
    for name in ("hooks_http.py", "hooks_tls.py", "hooks_shipper.py"):
        tree = ast.parse((ROOT / "proxy/addons" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "emit":
                kw = {k.arg: k.value for k in node.keywords}
                layers = [kw["layer"].body, kw["layer"].orelse] if isinstance(kw["layer"], ast.IfExp) else [kw["layer"]]
                for layer in layers:
                    pairs.add((kw["action"].value, layer.value))
    return pairs


def test_protocol_lists_every_emitted_action_and_layer():
    import re

    proto = (ROOT / "docs/PROTOCOL.md").read_text(encoding="utf-8")
    section = proto.split("## Proxy → CCC (internal)", 1)[1].split("\n## ", 1)[0]
    head = re.search(r"layer: ([\w|-]+), action: ([\w|]+)", section)
    doc_layers, doc_actions = set(head[1].split("|")), set(head[2].split("|"))
    table = set()
    for action, layers in re.findall(r"^\| `(\w+)` \| ([^|]+) \|", section, re.M):
        table |= {(action, la) for la in re.findall(r"`([\w-]+)`", layers)}
    emitted = _emitted_pairs()
    assert emitted and table == emitted
    assert {a for a, _ in emitted} == doc_actions and {la for _, la in emitted} == doc_layers
    ctrl = (ROOT / "server/app/Http/Controllers/Internal/NetEventsController.php").read_text(encoding="utf-8")
    assert set(re.search(r"'events\.\*\.action' => 'required\|in:([\w,]+)'", ctrl)[1].split(",")) == doc_actions
