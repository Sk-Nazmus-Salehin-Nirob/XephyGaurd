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


@pytest.mark.parametrize("path", ["/%63hat", "//chat", "/chat;x", "/x/../chat/new"])
def test_path_rule_blocks_disguised_paths(addon, path):
    """I-PROXY-16: the 403 also applies to encoded/duplicated/;param forms of the rule path."""
    f = _flow("192.168.10.21", "huggingface.co", path)
    addon.request(f)
    assert f.response is not None and f.response.status_code == 403


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


def _capture(addon, log_urls=None, session_clients=None):
    emitted = []
    addon.events.emit = lambda **kw: emitted.append(kw)
    addon.cache.reload(force=True)
    if log_urls is not None:
        addon.cache.state.log_urls = log_urls
    if session_clients is not None:
        addon.cache.state.session_clients = session_clients
    return emitted


def _send_sni(addon, ip, sni):
    from mitmproxy import tls
    from mitmproxy.proxy import context

    client = tutils.tclient_conn() if hasattr(tutils, "tclient_conn") else tflow.tclient_conn()
    client.peername = (ip, 40000)
    ctx = context.Context(client, None)
    data = tls.ClientHelloData(ctx, tls.ClientHello(_client_hello_bytes(sni)))
    addon.tls_clienthello(data)
    return data


def test_tls_clienthello_observes_allowed_ai_and_ide_traffic(addon):
    emitted = _capture(addon, log_urls={"enabled": True})
    # 192.168.10.30 is in block_ai (blocks "ai", allows "ide"): Copilot backend passes but is observed
    d1 = _send_sni(addon, "::ffff:192.168.10.30", "api.individual.githubcopilot.com")
    assert d1.ignore_connection is True
    # second hit within the window is deduplicated for the same (client_ip, matched)
    _send_sni(addon, "192.168.10.30", "api.individual.githubcopilot.com")
    # exempt PC (accommodation, in a session) reaching ChatGPT is observed too
    _send_sni(addon, "192.168.10.22", "chat.openai.com")
    observed = [e for e in emitted if e["action"] == "observed"]
    assert [(e["client_ip"].removeprefix("::ffff:"), e["category"], e["matched"]) for e in observed] == [
        ("192.168.10.30", "ide", "githubcopilot.com"),
        ("192.168.10.22", "ai", "openai.com"),
    ]


def test_observed_events_need_log_urls_and_a_session(addon):
    """I-PROXY-10: no `observed` event with log_urls off, nor for a PC outside a session."""
    emitted = _capture(addon)                                  # log_urls off (conftest)
    _send_sni(addon, "192.168.10.30", "api.githubcopilot.com")  # block_ai, in a session
    addon.request(_flow("192.168.10.22", "duckduckgo.com", "/aichat"))
    assert emitted == []
    assert addon.events.stats["deduped_observed"] == 0
    emitted = _capture(addon, log_urls={"enabled": True})
    _send_sni(addon, "192.168.10.99", "chat.openai.com")       # in no group: no session
    addon.request(_flow("192.168.10.99", "duckduckgo.com", "/aichat?q=hi"))
    assert emitted == []
    # with a session_clients list from the server, that list decides
    emitted = _capture(addon, log_urls={"enabled": True}, session_clients=["192.168.10.99"])
    _send_sni(addon, "192.168.10.99", "chat.openai.com")
    _send_sni(addon, "192.168.10.30", "api.githubcopilot.com")  # in block_ai but not listed
    assert [(e["client_ip"], e["matched"]) for e in emitted] == [("192.168.10.99", "openai.com")]


def test_http_request_observes_allowed_ai_path(addon):
    emitted = _capture(addon, log_urls={"enabled": True})
    # exempt PC (in a session) using duckduckgo AI chat over plain HTTP / inspected HTTPS
    f = _flow("192.168.10.22", "duckduckgo.com", "/aichat?q=hi")
    addon.request(f)
    assert f.response is None
    assert len(emitted) == 1
    assert emitted[0]["action"] == "observed"
    assert emitted[0]["category"] == "ai"
    assert emitted[0]["matched"] == "duckduckgo.com/aichat"


def test_observed_path_keeps_only_the_first_segment(addon):
    from xg_netpolicy.proxy_logic import observed_path

    assert observed_path("/search/how-do-i-write-quicksort-AbC?q=x#f") == "/search"
    assert observed_path("/aichat?q=hi") == "/aichat"
    assert observed_path("/") == "/" and observed_path("?q=only") == "/" and observed_path("") == "/"
    emitted = _capture(addon, log_urls={"enabled": True})
    addon.request(_flow("192.168.10.22", "huggingface.co", "/chat/conversation/my-exam-question"))
    assert [(e["action"], e["path"]) for e in emitted] == [("observed", "/chat")]


def test_allowed_events_only_during_a_session(addon):
    """Server S-66 (ETHICS.md "Visited hosts/paths of allowed sites": always-on "–"): with log_urls on,
    `allowed` SNI and HTTP events are recorded only for PCs in a running session, like `observed`."""
    emitted = _capture(addon, log_urls={"enabled": True}, session_clients=["192.168.10.21"])
    for ip in ("192.168.10.21", "192.168.10.99", "192.168.10.22"):   # in session; none; exempt but not listed
        _send_sni(addon, ip, "example.com")
        addon.request(_flow(ip, "example.org", "/docs"))
    assert [(e["client_ip"], e["layer"], e["action"]) for e in emitted] == [
        ("192.168.10.21", "sni", "allowed"), ("192.168.10.21", "http", "allowed")]
    assert addon.events.stats["deduped_allowed"] == 0   # suppressed before the dedup, not counted as repeats
    emitted.clear()
    addon.cache.state.session_clients = None          # older CCC: the group fallback decides (exempt counts)
    _send_sni(addon, "192.168.10.22", "example.net")
    _send_sni(addon, "192.168.10.99", "example.net")
    assert [e["client_ip"] for e in emitted] == ["192.168.10.22"]
    emitted.clear()
    addon.cache.state.log_urls = {"enabled": False}
    _send_sni(addon, "192.168.10.21", "example.info")
    assert emitted == []


@pytest.mark.parametrize("log_urls", [{"enabled": True, "query": False}, {"enabled": True, "query": True}])
def test_allowed_and_observed_events_never_carry_the_query(addon, log_urls):
    # in-session PCs: allowed events are recorded only during a session (server S-66)
    emitted = _capture(addon, log_urls=log_urls, session_clients=["192.168.10.99", "192.168.10.22"])
    addon.request(_flow("192.168.10.99", "example.com", "/docs/page?q=my+exam+answer&x=1#frag"))
    addon.request(_flow("192.168.10.22", "duckduckgo.com", "/aichat?q=write+my+essay"))
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
             "request": "hooks_http", "response": "hooks_http", "running": "hooks_live"}
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



# -- Step 20 (I-PROXY-15): tls_clienthello always leaves a decision; an error blocks --

def _hello(ip, sni):
    from mitmproxy import tls
    from mitmproxy.proxy import context

    client = tflow.tclient_conn()
    client.peername = (ip, 40002)
    return client, tls.ClientHelloData(context.Context(client, None), tls.ClientHello(_client_hello_bytes(sni)))


def test_tls_clienthello_fails_closed_on_error(addon, monkeypatch, caplog):
    import asyncio

    def boom(ip, sni):
        raise TypeError("broken policy")

    monkeypatch.setattr(addon.cache, "decide_tls", boom)
    client, data = _hello("192.168.10.99", "example.com")
    addon.tls_clienthello(data)
    assert data.ignore_connection is True and client.id in addon.blocked_conns
    assert "tls_clienthello failed, blocking the connection" in caplog.text
    up = _server_data("192.168.10.99", ("93.184.215.14", 443))
    up.client = client
    asyncio.run(addon.server_connect(up))
    assert up.server.error == "blocked by XephyGuard"


def test_tls_clienthello_blocks_before_any_policy_loaded(addon, tmp_path):
    from xg_netpolicy.proxy_logic import PolicyCache

    addon.cache = PolicyCache(tmp_path / "missing.json")
    client, data = _hello("192.168.10.99", "example.com")
    addon.tls_clienthello(data)
    assert data.ignore_connection is True and client.id in addon.blocked_conns


def test_xg_policy_change_moves_event_shipper_to_new_policy(addon, state_file, state_dict, tmp_path, monkeypatch):
    """I-PROXY-25: after xg_policy changes, events go to the new policy's events_url and token, and
    the shipper (its queue and counters) is the same one."""
    import json

    from mitmproxy import ctx

    monkeypatch.delenv("XG_INTERNAL_TOKEN", raising=False)
    state_dict.update(events_url="http://new.example/api/internal/net-events")
    state_file.write_text(json.dumps(state_dict))
    generate.generate(state_file, tmp_path / "net2")
    pj = tmp_path / "net2" / "proxy.json"   # legacy token (older generator), read when the env var is unset
    pj.write_text(json.dumps(dict(json.loads(pj.read_text()), events_token="new-token")))
    shipper, old_cache = addon.events, addon.cache
    shipper.stats["spilled"] = 3
    ctx.options.xg_policy = str(tmp_path / "net2" / "proxy.json")
    addon.configure({"xg_policy"})
    assert addon.cache is not old_cache and addon.events is shipper
    assert shipper.cache is addon.cache and shipper.stats["spilled"] == 3
    seen = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=5):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"))
        return _Resp()

    monkeypatch.setattr("xg_netpolicy.proxy_logic.urllib.request.urlopen", fake_urlopen)
    assert shipper._post([{"layer": "proxy", "action": "blocked"}]) == 200
    assert seen == {"url": "http://new.example/api/internal/net-events", "auth": "Bearer new-token"}


def test_tls_clienthello_dedups_allowed_sni_per_client_host_per_minute(addon, monkeypatch):
    from mitmproxy import tls
    from mitmproxy.proxy import context

    from xg_netpolicy import proxy_logic

    addon.cache.state.log_urls = {"enabled": True}
    addon.cache.state.session_clients = ["192.168.10.99", "192.168.10.98"]   # allowed only in a session (S-66)
    emitted = []
    addon.events.emit = lambda **kw: emitted.append(kw)
    clock = [1000.0]
    monkeypatch.setattr(proxy_logic.time, "monotonic", lambda: clock[0])

    def send_sni(ip, sni):
        client = tutils.tclient_conn() if hasattr(tutils, "tclient_conn") else tflow.tclient_conn()
        client.peername = (ip, 40000)
        data = tls.ClientHelloData(context.Context(client, None), tls.ClientHello(_client_hello_bytes(sni)))
        addon.tls_clienthello(data)

    for _ in range(5):  # a browser opens several TLS connections per page
        send_sni("192.168.10.99", "example.com")
    send_sni("::ffff:192.168.10.99", "EXAMPLE.com")  # same client and host
    send_sni("192.168.10.98", "example.com")         # another client
    send_sni("192.168.10.99", "example.org")         # another host
    clock[0] += 59.0
    send_sni("192.168.10.99", "example.com")
    clock[0] += 1.5                                  # a minute after the first event
    send_sni("192.168.10.99", "example.com")

    got = [(e["client_ip"], e["host"]) for e in emitted]
    assert got == [("192.168.10.99", "example.com"), ("192.168.10.98", "example.com"),
                   ("192.168.10.99", "example.org"), ("192.168.10.99", "example.com")]
    assert all(e["action"] == "allowed" for e in emitted)
    assert addon.events.stats["deduped_allowed"] == 6


# -- Step 30 (I-PROXY-22): a new policy closes live connections it now blocks or inspects --

def _repolicy(addon, state_file, tmp_path, **groups):
    import json

    d = json.loads(state_file.read_text())
    d["groups"].update(groups)
    d["version"] += 1
    state_file.write_text(json.dumps(d))
    generate.generate(state_file, tmp_path / "net")
    addon.cache.reload(force=True)


class _Handler:
    def __init__(self):
        self.client = object()
        self.closed = []

    def close_connection(self, conn):
        self.closed.append(conn)


def test_policy_change_closes_tightened_live_connections(addon, state_file, tmp_path):
    passed = _send_sni(addon, "192.168.10.99", "claude.ai")            # unassigned PC: passed through
    inspected = _send_sni(addon, "192.168.10.30", "huggingface.co")    # block_ai: inspected
    other = _send_sni(addon, "192.168.10.99", "example.org")           # stays allowed
    ids = {n: d.context.client.id for n, d in (("p", passed), ("i", inspected), ("o", other))}
    assert set(addon.live_conns) == set(ids.values())
    handlers = {cid: _Handler() for cid in ids.values()}
    addon._handler = handlers.get
    assert addon.check_live() == []                    # first check: same decisions, nothing closed
    assert addon.check_live() == []                    # no new policy: not rechecked
    # session starts for .99 (block_ai), .30 is isolated
    _repolicy(addon, state_file, tmp_path, block_ai=["192.168.10.99"], isolated=["192.168.10.40", "192.168.10.30"])
    assert sorted(addon.check_live()) == sorted([ids["p"], ids["i"]])
    assert handlers[ids["p"]].closed == [handlers[ids["p"]].client] and handlers[ids["i"]].closed
    assert handlers[ids["o"]].closed == [] and set(addon.live_conns) == {ids["o"]}


def test_policy_change_inspect_for_passed_connection_and_loosened_kept(addon, state_file, tmp_path):
    passed = _send_sni(addon, "192.168.10.99", "huggingface.co")       # unassigned: passed
    inspected = _send_sni(addon, "192.168.10.30", "huggingface.co")    # block_ai: inspected
    handlers = {d.context.client.id: _Handler() for d in (passed, inspected)}
    addon._handler = handlers.get
    addon.check_live()
    _repolicy(addon, state_file, tmp_path, block_ai=["192.168.10.99"])  # .99 now inspected
    assert addon.check_live() == [passed.context.client.id]
    # .30 becomes exempt: inspect -> pass loosens, the connection is kept
    _repolicy(addon, state_file, tmp_path, block_ai=["192.168.10.99"], exempt=["192.168.10.22", "192.168.10.30"])
    assert addon.check_live() == [] and inspected.context.client.id in addon.live_conns


def test_live_connection_forgotten_on_disconnect_and_missing_handler(addon, state_file, tmp_path):
    d = _send_sni(addon, "192.168.10.99", "claude.ai")
    addon.client_disconnected(d.context.client)
    assert addon.live_conns == {}
    d = _send_sni(addon, "192.168.10.99", "claude.ai")
    addon._handler = lambda cid: None                  # already gone in mitmproxy: logged, not raised
    addon.check_live()
    _repolicy(addon, state_file, tmp_path, isolated=["192.168.10.40", "192.168.10.99"])
    assert addon.check_live() == [d.context.client.id] and addon.live_conns == {}


def test_blocked_connection_not_tracked_as_live(addon):
    _send_sni(addon, "192.168.10.21", "claude.ai")
    assert addon.live_conns == {}


def test_live_close_uses_existing_mitmproxy_api():
    """hooks_live closes via Proxyserver.connections[client.id].close_connection(handler.client)."""
    import inspect

    from mitmproxy.addons.proxyserver import Proxyserver
    from mitmproxy.proxy import mode_servers, server

    assert Proxyserver().connections == {}
    assert "register_connection(handler.layer.context.client.id" in inspect.getsource(mode_servers)
    assert "self.client = context.client" in inspect.getsource(server.ConnectionHandler.__init__)
    assert list(inspect.signature(server.ConnectionHandler.close_connection).parameters)[:2] == ["self", "connection"]
