"""Unit tests for per-PC udm14_clients, search rewriting, /async/folwr blocking, and CSP-safe CSS injection."""
import json
import pathlib
import pytest

from xg_netpolicy import state as netstate
from xg_netpolicy.proxy_logic import (
    PolicyCache,
    extract_nonce,
    google_search_rewrite,
    hide_css,
    inject_css,
    relax_style_csp,
)


def test_state_validates_udm14_clients(state_dict):
    state_dict["google"]["udm14_clients"] = ["192.168.10.21", "192.168.10.22"]
    netstate.State.from_dict(state_dict).validate()

    bad = dict(state_dict)
    bad["google"] = dict(state_dict["google"], udm14_clients=["10.99.0.5", "192.168.10.21", "2001:db8::1"])
    s = netstate.State.from_dict(bad)
    assert s.google["udm14_clients"] == ["192.168.10.21"]  # bad entries skipped, not the document
    assert [x.split(" (")[0] for x in s.skipped] == ["udm14_clients: '10.99.0.5'", "udm14_clients: '2001:db8::1'"]
    bad["google"] = dict(state_dict["google"], udm14_clients="192.168.10.21")
    with pytest.raises(ValueError, match="udm14_clients"):
        netstate.State.from_dict(bad)


def test_always_on_udm14_client_inspects_google_only(tmp_path, state_dict):
    # Empty test/block_ai groups (always_on), but 192.168.10.21 wants udm14 suppression
    state_dict["groups"] = {"test": [], "block_ai": [], "isolated": [], "exempt": ["192.168.10.25"]}
    state_dict["inspect_hosts"] = ["google.com", "www.google.com", "google.co.uk", "huggingface.co"]
    state_dict["google"]["force_udm14"] = True
    state_dict["google"]["udm14_clients"] = ["192.168.10.21", "192.168.10.25"]
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state_dict))

    c = PolicyCache(p)
    assert c.wants_google_rewrite("192.168.10.21") is True
    assert c.wants_google_rewrite("192.168.10.99") is False
    assert c.wants_google_rewrite("192.168.10.25") is False  # exempt wins

    assert c.decide_tls("192.168.10.21", "www.google.com").action == "inspect"
    assert c.decide_tls("192.168.10.21", "google.co.uk").action == "inspect"
    assert c.decide_tls("192.168.10.21", "huggingface.co").action == "pass"
    assert c.decide_tls("192.168.10.21", "github.com").action == "pass"
    assert c.decide_tls("192.168.10.99", "www.google.com").action == "pass"
    assert c.decide_tls("192.168.10.25", "www.google.com").action == "pass"


def test_google_search_rewrite_sets_udm14_replaces_udm50_and_strips_aep():
    q = google_search_rewrite("www.google.com", "/search", [("q", "binary search"), ("aep", "1")])
    assert q is not None
    assert dict(q) == {"q": "binary search", "udm": "14"}

    q2 = google_search_rewrite("google.co.uk", "/search", [("q", "dp"), ("udm", "50")])
    assert q2 is not None and dict(q2) == {"q": "dp", "udm": "14"}

    # Already udm=14 without aep -> unchanged (None)
    assert google_search_rewrite("www.google.com", "/search", [("q", "dp"), ("udm", "14")]) is None
    # Non-AI verticals like images (udm=2) stay untouched
    assert google_search_rewrite("www.google.com", "/search", [("q", "cat"), ("udm", "2")]) is None


def test_csp_nonce_and_style_relaxation():
    html = '<!doctype html><html><head><script nonce="n0nc3==">1</script></head><body><div id="app">hi</div></body></html>'
    nonce = extract_nonce(html)
    assert nonce == "n0nc3=="

    selectors = ['div[jsname="txosbe"]', "#xg-ai-overview"]
    out = inject_css(html, selectors, nonce=nonce)
    assert out is not None
    assert 'nonce="n0nc3=="' in out
    assert hide_css(selectors, nonce=nonce).startswith('<style id="xephyguard" nonce="n0nc3==">')

    csp = "default-src 'self'; script-src 'nonce-abc'; style-src 'self' 'nonce-xyz'"
    relaxed = relax_style_csp(csp)
    assert "'unsafe-inline'" in relaxed
    assert "'nonce-xyz'" not in relaxed


def test_addon_blocks_folwr_and_relaxes_csp(tmp_path, state_dict):
    mitm_http = pytest.importorskip("mitmproxy.http")
    from mitmproxy.test import tflow
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "addons"))
    import xephyguard_addon as mod
    from xg_netpolicy.proxy_logic import EventShipper

    state_dict["groups"] = {"test": [], "block_ai": [], "isolated": [], "exempt": []}
    state_dict["google"]["force_udm14"] = True
    state_dict["google"]["udm14_clients"] = ["192.168.10.21"]
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state_dict))

    addon = mod.XephyGuard()
    addon.cache = PolicyCache(p)
    addon.events = EventShipper(addon.cache, fallback=str(tmp_path / "ev.jsonl"))
    try:
        # /async/folwr should be blocked with 204
        flow = tflow.tflow()
        flow.client_conn.peername = ("192.168.10.21", 50000)
        flow.request.host = "www.google.com"
        flow.request.port = 443
        flow.request.scheme = "https"
        flow.request.path = "/async/folwr?q=test"
        addon.request(flow)
        assert flow.response is not None
        assert flow.response.status_code == 204

        # Search request gets udm=14, injected CSS, relaxed CSP, and Cache-Control no-store
        f2 = tflow.tflow()
        f2.client_conn.peername = ("192.168.10.21", 50001)
        f2.request.host = "www.google.com"
        f2.request.port = 443
        f2.request.scheme = "https"
        f2.request.path = "/search?q=test"
        addon.request(f2)
        assert "udm=14" in f2.request.path

        f2.response = mitm_http.Response.make(
            200,
            b"<html><head></head><body><div id='xg-ai-overview'></div></body></html>",
            {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Security-Policy": "style-src 'self' 'nonce-xyz'",
            },
        )
        addon.response(f2)
        csp = f2.response.headers.get("Content-Security-Policy", "")
        assert "'unsafe-inline'" in csp and "'nonce-xyz'" not in csp
        assert b'id="xephyguard"' in f2.response.content
    finally:
        addon.events.stop()


# -- Step 14 (I-PROXY-21): AI-endpoint signatures come from data/network/proxy.yaml via the policy --

def test_builtin_signatures_equal_data_yaml():
    yaml = pytest.importorskip("yaml")
    from xg_netpolicy.proxy_logic import SEARCH_AI_DEFAULTS

    seed = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "data" / "network" / "proxy.yaml").read_text())
    assert seed["google_search_hosts"] == SEARCH_AI_DEFAULTS["search_hosts"]
    assert seed["google_ai_paths"] == SEARCH_AI_DEFAULTS["ai_paths"]
    assert seed["search_css_hosts"] == SEARCH_AI_DEFAULTS["css_hosts"]


def test_search_ai_signatures_defaults_and_bad_entries(caplog):
    from xg_netpolicy.proxy_logic import search_ai_signatures

    d = search_ai_signatures({})
    assert d.is_search_host("www.google.co.uk") and not d.is_search_host("google.evil.example")
    assert d.is_ai_path("www.google.com", "/async/folwr?x=1") and not d.is_ai_path("www.bing.com", "/async/folwr")
    assert d.wants_css("www.bing.com") and d.wants_css("www.google.de") and not d.wants_css("example.com")
    with caplog.at_level("WARNING", logger="xg-proxy"):
        bad = search_ai_signatures({"search_hosts": ["(", 5, " "], "ai_paths": "nope", "css_hosts": []})
    assert bad == d   # every bad or empty key falls back to the built-in list
    assert len(caplog.records) == 4


def test_signatures_from_policy_replace_builtin(tmp_path, state_dict):
    from xg_netpolicy import generate
    from xg_netpolicy.proxy_logic import PolicyCache, google_search_rewrite

    state_dict["google"] = {**state_dict.get("google", {}), "force_udm14": True,
                            "search_hosts": [r"^search\.example$"], "ai_paths": ["/ai/stream"],
                            "css_hosts": ["other.example"]}
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps(state_dict))
    generate.generate(sp, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    sig = c.search_ai
    assert sig.is_ai_path("search.example", "/ai/stream/1") and not sig.is_ai_path("www.google.com", "/async/folwr")
    assert sig.wants_css("www.other.example") and not sig.wants_css("www.bing.com")
    assert google_search_rewrite("search.example", "/search", [("q", "x")], sig) == [("q", "x"), ("udm", "14")]
    assert google_search_rewrite("www.google.com", "/search", [("q", "x")], sig) is None


# -- Step 15 (I-PROXY-26): hide selectors can't break out of the rule or the <style> element --

@pytest.mark.parametrize("sel", [
    "a}body{display:none", "a;color:red", "@import url(x)", "a{", "</style><script>", "a/*x*/",
    "a\7d b", 'div[x="unclosed]', "div[x", "a:not(b", "a)", "", "   ", None, 5, "a" * 257,
])
def test_hide_css_rejects_breakouts(sel):
    from xg_netpolicy.proxy_logic import valid_selector

    assert not valid_selector(sel)
    assert hide_css([sel]) == ""


def test_hide_css_keeps_seed_and_common_selectors():
    yaml = pytest.importorskip("yaml")
    from xg_netpolicy.proxy_logic import valid_selector

    seed = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "data" / "network" / "proxy.yaml").read_text())
    common = ["div > span.x", "a[href^='https://'] + b", "li:not(.ad)", "x ~ y", "[data-a|=\"en\"]", "g-ai-overview"]
    for s in seed["google_hide_selectors"] + common:
        assert valid_selector(s), s
    out = hide_css(["#ok", "a}b{", " .x "])
    assert out == '<style id="xephyguard">#ok,.x{display:none!important}</style>'


# -- Step 31 (I-PROXY-23): CSS hosts match the entry or a subdomain, not a look-alike --

@pytest.mark.parametrize("host,wanted", [
    ("bing.com", True), ("www.bing.com", True), ("WWW.Bing.COM", True), ("cn.bing.com", True),
    ("notbing.com", False), ("evilbing.com", False), ("bing.com.evil.net", False), ("xbing.com", False),
])
def test_css_hosts_match_entry_or_subdomain_only(host, wanted):
    from xg_netpolicy.proxy_logic import SearchAi

    assert SearchAi().wants_css(host) is wanted
