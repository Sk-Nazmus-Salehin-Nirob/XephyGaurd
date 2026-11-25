import json
import pathlib
import time

import pytest

from xg_netpolicy import generate
from xg_netpolicy.domains import NEVER_INSPECT, DomainSet, InspectHosts, PathRules, normalize_domain, parse_list
from xg_netpolicy.proxy_logic import PolicyCache, google_search_rewrite, inject_css, loggable_path, refused_destination
from xg_netpolicy.state import State


def test_normalize_and_parse():
    assert normalize_domain("https://Chat.OpenAI.com/c/123") == "chat.openai.com"
    assert normalize_domain("*.claude.ai") == "claude.ai"
    assert normalize_domain("8.8.8.8") is None
    assert normalize_domain("# comment") is None
    doms, paths = parse_list("openai.com [chat]\n0.0.0.0 bad.example\n# x\nhuggingface.co/chat [chat]\n")
    assert doms == ["bad.example", "openai.com"]
    assert paths == ["huggingface.co/chat"]


def test_domain_suffix_matching():
    ds = DomainSet.of(["openai.com", "x.ai"])
    assert ds.matches("api.openai.com") == "openai.com"
    assert ds.matches("OPENAI.COM.") == "openai.com"
    assert ds.matches("notopenai.com") is None
    assert ds.matches("grok.x.ai") == "x.ai"
    assert ds.matches("max.ai") is None


def test_path_rules():
    pr = PathRules.of(["huggingface.co/chat"])
    assert pr.matches("huggingface.co", "/chat/conversation/1")
    assert pr.matches("huggingface.co", "/chat?x=1")
    assert not pr.matches("huggingface.co", "/models")
    assert not pr.matches("huggingface.co", "/chatterbox")


@pytest.mark.parametrize("path", [
    "/%63hat", "/%63%68%61%74/x", "//chat", "/chat;jsessionid=1", "/chat;x/conversation", "/x/../chat",
    "/./chat", "\\chat", "/CHAT", "/%2563hat", "/%2Fchat", "///chat//new", "/chat/", "/chat#frag", "/%63hat?q=1",
])
def test_path_rules_match_normalised_paths(path):
    """I-PROXY-16: percent-encoding, duplicate slashes, ;params, dot segments and case no longer
    get past a path rule."""
    assert PathRules.of(["huggingface.co/chat"]).matches("huggingface.co", path) == "huggingface.co/chat"


@pytest.mark.parametrize("path", ["/chatterbox", "/%63hatterbox", "/models;chat", "/models/chat", "/chat/../models", "/"])
def test_path_rules_normalising_does_not_widen_rules(path):
    assert PathRules.of(["huggingface.co/chat"]).matches("huggingface.co", path) is None


def test_normalize_path():
    from xg_netpolicy.domains import normalize_path

    assert normalize_path("") == "/" and normalize_path("?q=1") == "/" and normalize_path("/") == "/"
    assert normalize_path("//a//b;p=1/./c/../D?x#y") == "/a/b/d"
    assert normalize_path("/../../etc") == "/etc"
    assert normalize_path("/%zz") == "/%zz"                     # invalid escapes kept as they are
    assert PathRules.of(["huggingface.co//Chat/"]).rules == [("huggingface.co", "/chat")]


def test_state_groups(state_dict):
    s = State.from_dict(state_dict)
    assert s.group_of("192.168.10.21") == "test"
    assert s.group_of("192.168.10.22") == "exempt"            # override wins
    assert s.group_of("::ffff:192.168.10.30") == "block_ai"
    assert s.group_of("192.168.10.99") is None
    assert s.blocked_domains_for_group("test").matches("api.githubcopilot.com")
    assert not s.blocked_domains_for_group("block_ai").matches("githubcopilot.com")
    assert s.blocked_domains_for_group(None).matches("dns.google")  # DoH always blocked
    assert not s.blocked_domains_for_group("exempt").matches("openai.com")


BAD_PC_ENTRIES = ["10.0.0.5", "2001:db8::5", "fe80::1", "::ffff:192.168.10.23", "not-an-ip", "", 5, None,
                  ["192.168.10.24"]]


def test_state_skips_bad_group_entries_and_keeps_the_rest(state_dict, caplog):
    state_dict["groups"]["test"] += BAD_PC_ENTRIES + [" 192.168.10.26 "]
    with caplog.at_level("WARNING", logger="xg-netpolicy.state"):
        s = State.from_dict(state_dict)
    assert s.groups["test"] == ["192.168.10.21", "192.168.10.26"]
    assert s.groups["block_ai"] == ["192.168.10.30"] and s.groups["isolated"] == ["192.168.10.40"]
    assert len(s.skipped) == len(BAD_PC_ENTRIES) and all(x.startswith("groups.test: ") for x in s.skipped)
    assert "'10.0.0.5' (outside the lab subnet 192.168.10.0/24)" in s.skipped[0]
    assert "(not IPv4)" in s.skipped[1] and "(not a string (int))" in s.skipped[6]
    assert caplog.text.count("groups.test: skipping") == len(BAD_PC_ENTRIES)
    assert s.group_of("192.168.10.21") == "test" and s.group_of("10.0.0.5") is None


@pytest.mark.parametrize("bad", [
    {"groups": ["192.168.10.21"]},
    {"groups": {"test": "192.168.10.21"}},
    {"groups": {"test": None}},
    {"google": ["udm14"]},
    {"google": {"udm14_clients": "192.168.10.21"}},
    {"ccc_ip": "ccc"},
    {"lab_subnet": "lab"},
    {"lan_if": "lan0; flush ruleset"},
    {"lab_subnet": 3232238080},
    {"ccc_ip": 3232238082},
])
def test_state_still_rejects_structural_errors(state_dict, bad):
    with pytest.raises(ValueError):
        State.from_dict(dict(state_dict, **bad))


def test_generate_and_proxy_enforce_other_pcs_when_one_ip_is_bad(state_dict, tmp_path):
    state_dict["groups"]["test"] += ["10.0.0.5", "2001:db8::5"]
    state_dict["groups"]["isolated"].append(7)
    state_dict["google"]["udm14_clients"] = ["192.168.10.21", "fe80::1"]
    state = tmp_path / "state.json"
    state.write_text(json.dumps(state_dict))
    out = tmp_path / "net"
    generate.generate(state, out)
    sets = (out / "sets.nft").read_text()
    assert "add element inet xephyguard test_clients { 192.168.10.21 }" in sets
    assert "add element inet xephyguard isolated_clients { 192.168.10.40 }" in sets
    unbound = (out / "unbound-xephyguard.conf").read_text()
    assert "access-control-view: 192.168.10.21/32 xg_test" in unbound
    assert "10.0.0.5" not in unbound + sets and "2001:db8" not in unbound + sets
    proxy = json.loads((out / "proxy.json").read_text())
    assert proxy["groups"]["test"] == ["192.168.10.21"]
    assert proxy["google"]["udm14_clients"] == ["192.168.10.21"]
    assert state_dict["google"]["udm14_clients"] == ["192.168.10.21", "fe80::1"]  # input not mutated

    # the proxy also validates what it reads (a hand-edited or older proxy.json): one bad IP
    # must not keep the previous policy for every PC
    pj = out / "proxy.json"
    pj.write_text(json.dumps(dict(state_dict, version=8)))
    c = PolicyCache(pj)
    assert c.state.version == 8
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"
    assert c.decide_tls("192.168.10.40", "example.com").action == "block"
    assert c.decide_tls("10.0.0.5", "chatgpt.com").action == "pass"
    assert c.wants_google_rewrite("192.168.10.21") is True


def test_watch_applies_document_with_one_bad_ip(state_file, state_dict, tmp_path, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        calls.append((json.loads((out / "proxy.json").read_text())["version"], set(flush_ips))))
    out = tmp_path / "net"

    def on_sleep(n):
        if n == 1:  # a new Test session; one PC reported from an address outside the lab subnet
            groups = dict(state_dict["groups"], test=state_dict["groups"]["test"] + ["192.168.10.50", "10.0.0.5"])
            state_file.write_text(json.dumps(dict(state_dict, version=6, groups=groups)))
        return n < 3

    with caplog.at_level("WARNING"):
        _run_watch(state_file, out, monkeypatch, on_sleep)
    assert [v for v, _ in calls] == [5, 6]
    assert calls[1][1] == {"192.168.10.50"}  # conntrack flushed for the new PC only (Step 4)
    assert "invalid state document" not in caplog.text
    assert "groups.test: skipping '10.0.0.5', outside the lab subnet" in caplog.text


def test_generate_outputs(state_file, tmp_path):
    out = tmp_path / "net"
    changed = generate.generate(state_file, out)
    assert all(changed.values())
    unbound = (out / "unbound-xephyguard.conf").read_text()
    assert 'local-zone: "dns.google." always_nxdomain' in unbound
    assert "access-control-view: 192.168.10.21/32 xg_test" in unbound
    assert 'name: "xg_test"' in unbound
    test_view = unbound.split('name: "xg_test"')[1].split("view:")[0]
    assert 'local-zone: "openai.com." always_nxdomain' in test_view
    assert 'local-zone: "githubcopilot.com." always_nxdomain' in test_view
    block_ai_view = unbound.split('name: "xg_block_ai"')[1].split("view:")[0]
    assert "githubcopilot.com" not in block_ai_view
    nft = (out / "sets.nft").read_text()
    assert "add element inet xephyguard test_clients { 192.168.10.21 }" in nft
    assert "resolver_ips6 { 2001:4860:4860::8888 }" in nft
    proxy = json.loads((out / "proxy.json").read_text())
    assert proxy["version"] == 5
    # unchanged input -> nothing rewritten
    assert not any(generate.generate(state_file, out).values())


def test_tls_decisions(state_file, tmp_path):
    generate.generate(state_file, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"
    assert c.decide_tls("192.168.10.21", "chatgpt.com").category == "ai"
    assert c.decide_tls("192.168.10.21", "www.google.com").action == "inspect"
    assert c.decide_tls("192.168.10.21", "github.com").action == "pass"
    assert c.decide_tls("192.168.10.21", None).action == "block"        # no SNI in Test mode
    assert c.decide_tls("192.168.10.99", "chatgpt.com").action == "pass"  # no session for this PC
    assert c.decide_tls("192.168.10.99", "dns.google").action == "block"  # DoH always blocked
    assert c.decide_tls("192.168.10.22", "chatgpt.com").action == "pass"  # exempt PC
    assert c.decide_tls("192.168.10.40", "example.com").action == "block"  # isolated
    assert c.decide_http("192.168.10.21", "huggingface.co", "/chat/x").action == "block"
    assert c.decide_http("192.168.10.21", "huggingface.co", "/datasets").action == "pass"


def test_path_rule_block_has_category_of_matched_rule(state_file, state_dict, tmp_path):
    """I-PROXY-24: a path-rule block names the category whose rule list matched, not always "ai"."""
    state_dict["path_rules"] = {"ai": ["huggingface.co/chat"], "ide": ["aws.amazon.com/q"]}
    state_file.write_text(json.dumps(state_dict))
    generate.generate(state_file, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    d = c.decide_http("192.168.10.21", "aws.amazon.com", "/q/chat")
    assert (d.action, d.category, d.matched, d.reason) == ("block", "ide", "aws.amazon.com/q", "path rule")
    d = c.decide_http("192.168.10.21", "huggingface.co", "/chat")
    assert (d.action, d.category, d.matched) == ("block", "ai", "huggingface.co/chat")
    # block_ai blocks only "ai": the IDE rule does not apply there, the AI one does
    assert c.decide_http("192.168.10.30", "aws.amazon.com", "/q").action == "pass"
    assert c.decide_http("192.168.10.30", "huggingface.co", "/chat").category == "ai"
    assert c.decide_http("192.168.10.22", "aws.amazon.com", "/q").action == "pass"  # exempt


def test_inspect_hosts_match_exactly_with_opt_in_wildcard():
    h = InspectHosts.of(["Google.com", "www.google.com.", "*.example.org", "*.google.com", "bad host", 7])
    assert h.matches("google.com") and h.matches("WWW.Google.com") and h.matches("www.google.com.")
    assert not h.matches("google.com.evil.net") and not h.matches("notgoogle.com")
    assert h.matches("a.example.org") and h.matches("a.b.example.org")
    assert not h.matches("example.org")                    # "*." is subdomains only
    assert h.matches("news.google.com")                    # opted in via *.google.com
    for host in ("accounts.google.com", "mail.google.com", "docs.google.com", "drive.google.com",
                 "x.mail.google.com", "login.live.com", "login.microsoftonline.com", "outlook.office.com"):
        assert not h.matches(host), host                   # never decrypted, wildcard or not
    assert not InspectHosts.of(sorted(NEVER_INSPECT)).matches("accounts.google.com")
    assert not h.matches(None) and not h.matches("")


def test_seed_inspect_hosts_cover_search_but_not_google_accounts(state_dict, tmp_path):
    # the seed is a plain YAML list; read it without PyYAML (not a proxy dependency)
    text = (pathlib.Path(__file__).resolve().parents[2] / "data/network/proxy.yaml").read_text()
    block = text.split("\ninspect_hosts:\n", 1)[1].split("\n\n", 1)[0]
    state_dict["inspect_hosts"] = [ln.strip()[2:] for ln in block.splitlines() if ln.strip().startswith("- ")]
    assert "www.google.com" in state_dict["inspect_hosts"]
    p = tmp_path / "proxy.json"
    p.write_text(json.dumps(state_dict))
    c = PolicyCache(p)
    for host in ("www.google.com", "google.com", "www.google.co.uk", "www.bing.com", "huggingface.co",
                 "duckduckgo.com", "search.brave.com"):
        assert c.decide_tls("192.168.10.21", host).action == "inspect", host
    for host in ("accounts.google.com", "mail.google.com", "docs.google.com", "drive.google.com",
                 "login.live.com", "maps.google.com", "cdn.huggingface.co", "copilot.bing.com.evil.net"):
        assert c.decide_tls("192.168.10.21", host).action == "pass", host
    assert c.decide_tls("192.168.10.99", "www.google.com").action == "pass"  # no session


def test_loggable_path_drops_query_and_fragment():
    assert loggable_path("/search?q=answer+to+q3") == "/search"
    assert loggable_path("/a/b#x?y") == "/a/b"
    assert loggable_path("?q=x") == "/" and loggable_path("") == "/"
    assert loggable_path("/" + "a" * 600) == "/" + "a" * 511
    assert loggable_path("/p?q=1", 2) == "/p"


def test_google_rewrite():
    q = google_search_rewrite("www.google.com", "/search", [("q", "binary search in c")])
    assert q == [("q", "binary search in c"), ("udm", "14")]
    assert google_search_rewrite("www.google.co.uk", "/search", [("q", "x")])[-1] == ("udm", "14")
    assert google_search_rewrite("www.google.com", "/search", [("q", "x"), ("udm", "14")]) is None
    assert google_search_rewrite("www.google.com", "/search", [("q", "x"), ("udm", "50")])[-1] == ("udm", "14")
    assert google_search_rewrite("www.google.com", "/search", [("q", "x"), ("tbm", "isch")]) is None
    assert google_search_rewrite("www.google.com", "/maps", [("q", "x")]) is None
    assert google_search_rewrite("evilgoogle.com", "/search", [("q", "x")]) is None


def test_css_injection():
    html = "<html><head><title>x</title></head><body></body></html>"
    out = inject_css(html, ["#ai", "div[data-x]"])
    assert '<style id="xephyguard">#ai,div[data-x]{display:none!important}</style></head>' in out
    assert inject_css(html, ["</style><script>"]) is None


def test_ai_observation_matching_and_dedup(state_file, tmp_path):
    from xg_netpolicy import generate
    from xg_netpolicy.proxy_logic import EventShipper, PolicyCache

    generate.generate(state_file, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    assert c.match_ai_domain("api.openai.com") == ("openai.com", "ai")
    assert c.match_ai_domain("api.individual.githubcopilot.com") == ("githubcopilot.com", "ide")
    assert c.match_ai_domain("github.com") is None
    assert c.match_ai_path("duckduckgo.com", "/aichat?q=1") == ("duckduckgo.com/aichat", "ai")
    assert c.match_ai_path("duckduckgo.com", "/") is None

    shipper = EventShipper(c, fallback=str(tmp_path / "ev.jsonl"))
    try:
        assert shipper.should_emit_observed("::ffff:192.168.10.30", "githubcopilot.com", window_s=30.0) is True
        assert shipper.should_emit_observed("192.168.10.30", "githubcopilot.com", window_s=30.0) is False
        assert shipper.should_emit_observed("192.168.10.31", "githubcopilot.com", window_s=30.0) is True
        shipper.emit(client_ip="::ffff:192.168.10.30", host="api.githubcopilot.com", layer="sni", action="observed")
        ev = shipper.q.get(timeout=1.0)
        assert ev["client_ip"] == "192.168.10.30"
    finally:
        shipper.stop()


def test_apply_skips_nft_in_proxy_only_or_without_table(state_file, tmp_path, monkeypatch):
    out = tmp_path / "net"
    changed = generate.generate(state_file, out)
    calls = []

    class Res:
        def __init__(self, code=0, stdout="", stderr=""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[:3] == ["nft", "list", "table"]:
            return Res(1, "", "No such file or directory")
        return Res(0, "", "")

    monkeypatch.setattr(generate.subprocess, "run", fake_run)

    # proxy_only skips nft entirely and still reloads unbound
    monkeypatch.delenv("XG_UNBOUND_CONF", raising=False)
    generate.apply(out, changed, network_mode="proxy_only")
    assert all(c[0] != "nft" for c in calls)
    assert ["unbound-control", "-c", "/etc/unbound/unbound.conf", "reload"] in calls

    # the run script exports the config actually in use (proxy_only renders its own)
    calls.clear()
    monkeypatch.setenv("XG_UNBOUND_CONF", str(out / "unbound.conf"))
    generate.apply(out, changed, network_mode="proxy_only")
    assert ["unbound-control", "-c", str(out / "unbound.conf"), "reload"] in calls
    monkeypatch.delenv("XG_UNBOUND_CONF")

    # missing inet xephyguard table in gateway mode skips nft -f sets.nft cleanly
    calls.clear()
    generate.apply(out, changed, network_mode="gateway")
    assert ["nft", "list", "table", "inet", "xephyguard"] in calls
    assert not any(c[:2] == ["nft", "-f"] for c in calls)

    # existing table invokes nft -f sets.nft
    calls.clear()
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: (calls.append(cmd) or Res(0)))
    generate.apply(out, changed, network_mode="gateway")
    assert ["nft", "-f", str(out / "sets.nft")] in calls


def test_refused_destination():
    own = ("192.168.10.2",)
    for host, port in [("127.0.0.1", 443), ("127.8.9.1", 80), ("LOCALHOST.", 443), ("a.localhost", 80),
                       ("[::1]", 443), ("::ffff:127.0.0.1", 443), ("169.254.169.254", 80), ("fe80::1%eth0", 443),
                       ("0.0.0.0", 443), ("224.0.0.1", 80), ("192.168.10.2", 443), ("8.8.8.8", 8953),
                       ("example.org", 22)]:
        assert refused_destination(host, port, own), (host, port)
    for host, port in [("93.184.215.14", 443), ("example.org", 80), ("2606:2800:21f:cb07::1", 443),
                       ("192.168.10.30", 443)]:
        assert refused_destination(host, port, own) is None, (host, port)


@pytest.mark.parametrize("rel", ["proxy/dns/unbound.conf", "ccc-deploy/docker/unbound-local.conf"])
def test_unbound_control_is_unix_socket_only(rel):
    import pathlib

    conf = (pathlib.Path(__file__).resolve().parents[2] / rel).read_text()
    rc = conf.split("remote-control:", 1)[1]
    ifaces = [ln.split(":", 1)[1].strip() for ln in rc.splitlines() if ln.strip().startswith("control-interface:")]
    assert ifaces == ["/run/xephyguard-unbound/unbound.ctl"]
    assert "control-port" not in rc


def _nft_chain(text, name):
    body = text.split(f"chain {name} {{", 1)[1].split("\n    }", 1)[0]
    return [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_wan_input_accepts_only_established_and_required_ports():
    import pathlib

    nft = (pathlib.Path(__file__).resolve().parents[2] / "proxy/nftables/xephyguard.nft").read_text()
    inp = _nft_chain(nft, "input")
    # the WAN jump comes first, so no later input rule can accept WAN traffic
    assert inp[1] == 'iifname "@WAN_IF@" jump wan_input'
    wan = _nft_chain(nft, "wan_input")
    assert wan[0] == "ct state established,related accept"
    assert wan[-1].startswith("counter drop")
    accepts = [ln for ln in wan if " accept" in ln]
    assert accepts == [
        "ct state established,related accept",
        "meta l4proto { icmp, ipv6-icmp } accept",
        'udp sport 67 udp dport 68 accept comment "DHCPv4 client"',
        'udp sport 547 udp dport 546 accept comment "DHCPv6 client"',
        'tcp dport 22 accept comment "SSH administration"',
    ]
    for port in ("53", "80", "443", "8080", "8085", "@PROXY_PORT@", "@AGENT_PORT@"):
        assert not any(f"dport {port} " in ln or f"dport {{ {port}" in ln for ln in accepts), port


def test_forward_restricted_drops_come_before_established():
    import pathlib

    nft = (pathlib.Path(__file__).resolve().parents[2] / "proxy/nftables/xephyguard.nft").read_text()
    fwd = _nft_chain(nft, "forward")
    est = fwd.index("ct state established,related accept")
    for rule in ('iifname "@LAN_IF@" ip saddr @isolated_clients counter drop',
                 'iifname "@LAN_IF@" ip saddr @test_clients counter drop comment "Test mode: proxy path only"',
                 'oifname "@LAN_IF@" ip daddr @isolated_clients counter drop',
                 'oifname "@LAN_IF@" ip daddr @test_clients counter drop'):
        assert fwd.index(rule) < est, rule
    # only the general lab accept follows; nothing accepts restricted PCs before their drops
    assert not any(" accept" in ln for ln in fwd[:est])


class _Res:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def test_apply_flushes_conntrack_after_sets(state_file, tmp_path, monkeypatch):
    out = tmp_path / "net"
    changed = generate.generate(state_file, out)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "conntrack":
            # conntrack-tools exits 1 when nothing matched
            return _Res(1, "", "conntrack v1.4.7 (conntrack-tools): 0 flow entries have been deleted.")
        return _Res(0)

    monkeypatch.setattr(generate.subprocess, "run", fake_run)
    generate.apply(out, changed, network_mode="gateway", flush_ips={"192.168.10.40", "192.168.10.21"})
    nft_i = calls.index(["nft", "-f", str(out / "sets.nft")])
    flushes = [i for i, c in enumerate(calls) if c[0] == "conntrack"]
    assert [calls[i] for i in flushes] == [["conntrack", "-D", "-s", "192.168.10.21"],
                                           ["conntrack", "-D", "-s", "192.168.10.40"]]
    assert all(i > nft_i for i in flushes)

    # unchanged sets still flush (sets are already loaded), but never in proxy_only mode
    calls.clear()
    generate.apply(out, {}, network_mode="gateway", flush_ips={"192.168.10.40"})
    assert ["conntrack", "-D", "-s", "192.168.10.40"] in calls
    calls.clear()
    generate.apply(out, changed, network_mode="proxy_only", flush_ips={"192.168.10.40"})
    assert not any(c[0] in ("nft", "conntrack") for c in calls)

    # a failed nft -f leaves the old sets: flushing would only let flows reopen unrestricted
    calls.clear()
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or _Res(1 if cmd[:2] == ["nft", "-f"] else 0))
    generate.apply(out, changed, network_mode="gateway", flush_ips={"192.168.10.40"})
    assert not any(c[0] == "conntrack" for c in calls)


def test_flush_conntrack_without_binary_warns(monkeypatch, caplog):
    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(generate.subprocess, "run", missing)
    with caplog.at_level("WARNING", logger="xg-netpolicy"):
        generate.flush_conntrack({"192.168.10.40"})
    assert "conntrack not installed" in caplog.text


def test_watch_flushes_only_newly_restricted_ips(state_file, state_dict, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        seen.append(set(flush_ips)))

    class Stop(Exception):
        pass

    def fake_sleep(_):
        if len(seen) == 1:
            state_dict["groups"]["test"].append("192.168.10.50")  # joins a Test session
            state_dict["groups"]["isolated"] = []                  # released
            state_dict["version"] += 1
            state_file.write_text(json.dumps(state_dict))
        else:
            raise Stop

    monkeypatch.setattr(generate.time, "sleep", fake_sleep)
    with pytest.raises(Stop):
        generate.main(["--state", str(state_file), "--out", str(tmp_path / "net"), "--watch", "--apply"])
    # first pass: every restricted IP (connections from before the watcher started); then only the new one
    assert seen == [{"192.168.10.21", "192.168.10.40"}, {"192.168.10.50"}]


def _live_json(sets):
    """nft -j list table output: one set object per name, like nftables 1.0."""
    objs = [{"metainfo": {"version": "1.0.6", "json_schema_version": 1}},
            {"table": {"family": "inet", "name": "xephyguard", "handle": 7}}]
    for name, elem in sets.items():
        typ = "inet_service" if name.startswith("vpn_") else "ipv4_addr"
        st = {"family": "inet", "name": name, "table": "xephyguard", "type": typ, "handle": 1}
        if elem:
            st["elem"] = elem
        objs.append({"set": st})
    return json.dumps({"nftables": objs})


def _in_sync_sets():
    return {"test_clients": ["192.168.10.21"], "block_ai_clients": ["192.168.10.30"],
            "isolated_clients": ["192.168.10.40"], "exempt_clients": [{"elem": {"val": "192.168.10.22"}}],
            "resolver_ips": [{"range": ["1.1.1.1", "1.1.1.1"]}, {"prefix": {"addr": "8.8.8.8", "len": 32}}],
            "resolver_ips6": ["2001:4860:4860::8888"],
            "vpn_tcp_ports": [1723, 22, 1194], "vpn_udp_ports": [51820, 1194, {"range": [500, 500]}, 4500, 1701]}


def test_sets_out_of_sync_compares_live_elements(state_file, monkeypatch):
    s = generate.State.load(state_file)

    class Res:
        def __init__(self, code, out=""):
            self.returncode, self.stdout, self.stderr = code, out, ""

    live = _in_sync_sets()
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: Res(0, _live_json(live)))
    assert not generate.sets_out_of_sync(s)  # ranges/prefixes/wrapped elements normalised

    live = {k: [] for k in _in_sync_sets()}  # table reloaded by xephyguard.nft: sets empty
    assert generate.sets_out_of_sync(s)
    live = dict(_in_sync_sets(), test_clients=["192.168.10.21", "192.168.10.22"])
    assert generate.sets_out_of_sync(s)
    live = dict(_in_sync_sets(), vpn_udp_ports=[51820])  # the port sets are compared too (Step 18)
    assert generate.sets_out_of_sync(s)
    live = _in_sync_sets()
    del live["vpn_tcp_ports"]  # a ruleset from before Step 18 has no port sets
    assert generate.sets_out_of_sync(s)

    # no table / no nft: nothing to re-apply to
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: Res(1))
    assert not generate.sets_out_of_sync(s)

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(generate.subprocess, "run", missing)
    assert not generate.sets_out_of_sync(s)


def test_watch_applies_sets_on_start_even_if_files_unchanged(state_file, tmp_path, monkeypatch):
    out = tmp_path / "net"
    generate.generate(state_file, out)  # netpolicy-run.sh pre-generates the files before the watcher
    seen = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        seen.append(dict(changed)))
    generate.main(["--state", str(state_file), "--out", str(out), "--apply"])
    assert seen and seen[0]["nft"] is True and seen[0]["unbound"] is False


@pytest.mark.parametrize("mode,in_sync,reapplied", [("gateway", True, False), ("gateway", False, True),
                                                    ("proxy_only", False, False)])
def test_watch_reapplies_sets_when_live_table_differs(state_file, state_dict, tmp_path, monkeypatch,
                                                       mode, in_sync, reapplied):
    state_dict["network_mode"] = mode
    state_file.write_text(json.dumps(state_dict))
    calls = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        calls.append((dict(changed), set(flush_ips))))
    checks = []
    monkeypatch.setattr(generate, "sets_out_of_sync", lambda s: checks.append(s) or not in_sync)

    class Stop(Exception):
        pass

    sleeps = []

    def fake_sleep(_):
        sleeps.append(1)
        if len(sleeps) > 2:
            raise Stop

    monkeypatch.setattr(generate.time, "sleep", fake_sleep)
    with pytest.raises(Stop):
        generate.main(["--state", str(state_file), "--out", str(tmp_path / "net"), "--watch", "--apply",
                       "--resync", "0"])
    assert len(calls[0][1]) == 2  # first pass
    restricted = {"192.168.10.21", "192.168.10.40"}
    if reapplied:
        # same digest, but the live sets were emptied: re-apply and flush every restricted PC again
        assert calls[1:] == [({"nft": True}, restricted)] * 2
    else:
        assert calls[1:] == []
    assert bool(checks) == (mode != "proxy_only")


class _Stop(Exception):
    pass


def _run_watch(state_file, out, monkeypatch, on_sleep, extra=()):
    """Run the watcher until on_sleep(n) returns False (n = 1-based sleep count)."""
    sleeps = []

    def fake_sleep(_):
        sleeps.append(1)
        if not on_sleep(len(sleeps)):
            raise _Stop

    monkeypatch.setattr(generate.time, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        generate.main(["--state", str(state_file), "--out", str(out), "--watch", "--apply", *extra])
    return len(sleeps)


@pytest.mark.parametrize("bad", [
    {"groups": None},                       # AttributeError in from_dict
    {"lan_if": 7},                          # not a valid interface name
    {"groups": {"test": "192.168.10.21"}},  # a group that is not a list (one bad IP is only skipped)
    {"network_mode": 3},                    # non-str mode would break apply
    "not json",
    [1, 2],                                 # not an object
])
def test_watch_survives_invalid_documents(state_file, state_dict, tmp_path, monkeypatch, caplog, bad):
    calls = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        calls.append(state_version()))
    out = tmp_path / "net"

    def state_version():
        return json.loads((out / "proxy.json").read_text())["version"]

    def on_sleep(n):
        if n == 1:  # the CCC writes a broken document
            doc = bad if isinstance(bad, (str, list)) else dict(state_dict, **bad)
            state_file.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        elif n == 3:  # then a good one
            state_file.write_text(json.dumps(dict(state_dict, version=9)))
        return n < 5

    with caplog.at_level("ERROR", logger="xg-netpolicy"):
        _run_watch(state_file, out, monkeypatch, on_sleep)
    assert calls == [5, 9]  # previous config kept while broken, new one applied afterwards
    # the broken document is reported once, not re-parsed every second
    assert caplog.text.count("invalid state document (failure 1, 1 in a row)") == 1
    assert "failure 2" not in caplog.text


def test_watch_survives_oserror_and_retries_everything(state_file, tmp_path, monkeypatch, caplog):
    calls = []
    real_write = generate._write

    def flaky_write(path, text):
        if len(calls) == 0 and path.name == "sets.nft" and not getattr(flaky_write, "failed", 0) >= 2:
            flaky_write.failed = getattr(flaky_write, "failed", 0) + 1
            raise PermissionError(13, "Permission denied", str(path))
        return real_write(path, text)

    monkeypatch.setattr(generate, "_write", flaky_write)
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        calls.append((dict(changed), set(flush_ips))))
    with caplog.at_level("INFO", logger="xg-netpolicy"):
        _run_watch(state_file, tmp_path / "net", monkeypatch, lambda n: n < 4)
    # unbound-xephyguard.conf was written before the failure; the retry must still apply it
    assert calls == [({"unbound": True, "nft": True, "proxy": True},
                      {"192.168.10.21", "192.168.10.40"})]
    assert "watch iteration failed (failure 1, 1 in a row)" in caplog.text
    assert "failure 2, 2 in a row" in caplog.text
    assert "recovered after 2 failed iteration(s)" in caplog.text


def test_watch_survives_failing_resync_check_and_apply(state_file, tmp_path, monkeypatch, caplog):
    calls = []

    def apply(out, changed, network_mode=None, flush_ips=frozenset()):
        calls.append(dict(changed))
        if len(calls) == 2:
            raise OSError("nft: Operation not permitted")

    monkeypatch.setattr(generate, "apply", apply)
    checks = []

    def out_of_sync(s):
        checks.append(1)
        if len(checks) == 1:
            raise RuntimeError("unexpected nft -j output")
        return True

    monkeypatch.setattr(generate, "sets_out_of_sync", out_of_sync)
    with caplog.at_level("ERROR", logger="xg-netpolicy"):
        n = _run_watch(state_file, tmp_path / "net", monkeypatch, lambda n: n < 5, extra=("--resync", "0"))
    assert n == 5  # still looping
    # first pass, then: check raised, re-apply raised, re-apply, re-apply
    assert len(checks) == 4 and calls[1:] == [{"nft": True}] * 3
    assert "RuntimeError" in caplog.text and "nft: Operation not permitted" in caplog.text


def test_one_shot_exit_code_reports_failure(state_file, tmp_path):
    out = tmp_path / "net"
    assert generate.main(["--state", str(state_file), "--out", str(out)]) == 0
    state_file.write_text('{"groups": null}')
    assert generate.main(["--state", str(state_file), "--out", str(out)]) == 1


# -- Step 13 (I-PROXY-13): events_token never in proxy.json, the proxy reads env XG_INTERNAL_TOKEN --

def test_proxy_json_has_no_events_token(state_dict, tmp_path):
    st = State.from_dict({**state_dict, "events_url": "http://127.0.0.1:8000/api/internal/net-events",
                          "events_token": "secret-internal-token"})
    generate.generate_state(st, tmp_path / "net")
    text = (tmp_path / "net" / "proxy.json").read_text()
    assert "secret-internal-token" not in text and "events_token" not in text
    assert json.loads(text)["events_url"].endswith("/net-events")


def _ship_and_capture(tmp_path, monkeypatch, doc_token, env_token):
    from xg_netpolicy import proxy_logic
    from xg_netpolicy.proxy_logic import EventShipper

    p = tmp_path / "proxy.json"
    doc = {"events_url": "http://127.0.0.1:8000/api/internal/net-events"}
    if doc_token is not None:
        doc["events_token"] = doc_token
    p.write_text(json.dumps(doc))
    if env_token is None:
        monkeypatch.delenv("XG_INTERNAL_TOKEN", raising=False)
    else:
        monkeypatch.setenv("XG_INTERNAL_TOKEN", env_token)
    sent = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent.append(req.get_header("Authorization"))
        return Resp()

    monkeypatch.setattr(proxy_logic.urllib.request, "urlopen", fake_urlopen)
    shipper = EventShipper(PolicyCache(p), fallback=str(tmp_path / "ev.jsonl"))
    shipper.stop()  # no background thread racing the direct call below
    shipper._ship([{"action": "blocked", "host": "openai.com"}])
    return sent


def test_shipper_uses_env_token(tmp_path, monkeypatch):
    assert _ship_and_capture(tmp_path, monkeypatch, None, "env-token-1234") == ["Bearer env-token-1234"]
    # env wins over a token left in an older proxy.json
    assert _ship_and_capture(tmp_path, monkeypatch, "file-token", "env-token-1234") == ["Bearer env-token-1234"]


def test_shipper_falls_back_to_old_proxy_json_token(tmp_path, monkeypatch, caplog):
    with caplog.at_level("WARNING", logger="xg-proxy"):
        assert _ship_and_capture(tmp_path, monkeypatch, "file-token", None) == ["Bearer file-token"]
    assert any("XG_INTERNAL_TOKEN is not set" in r.message for r in caplog.records)
    assert _ship_and_capture(tmp_path, monkeypatch, None, "  ") == ["Bearer "]


def test_compose_passes_internal_token_to_proxy():
    import re

    compose = (pathlib.Path(__file__).resolve().parents[2] / "ccc-deploy" / "docker-compose.yml").read_text()
    proxy = re.search(r"\n  proxy:.*?(?=\n  \w)", compose, re.S).group(0)
    assert "XG_INTERNAL_TOKEN: ${XG_INTERNAL_TOKEN}" in proxy


# -- Step 17 (I-PROXY-29): network_mode comes from the parsed State, the document is read once per digest --

@pytest.mark.parametrize("doc_mode,expected", [("proxy_only", "proxy_only"), ("gateway", "gateway"),
                                               (None, None), ("missing", None)])
def test_watch_reads_state_once_and_uses_its_network_mode(state_file, state_dict, tmp_path, monkeypatch,
                                                          doc_mode, expected):
    doc = dict(state_dict)
    doc.pop("network_mode", None)
    if doc_mode != "missing":
        doc["network_mode"] = doc_mode
    state_file.write_text(json.dumps(doc))
    modes = []
    monkeypatch.setattr(generate, "apply", lambda out, changed, network_mode=None, flush_ips=frozenset():
                        modes.append(network_mode))
    reads = []
    real_bytes, real_text = pathlib.Path.read_bytes, pathlib.Path.read_text

    def count_bytes(self):
        if self == state_file:
            reads.append("bytes")
        return real_bytes(self)

    def count_text(self, *a, **k):
        if self == state_file:
            reads.append("text")
        return real_text(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_bytes", count_bytes)
    monkeypatch.setattr(pathlib.Path, "read_text", count_text)
    assert generate.main(["--state", str(state_file), "--out", str(tmp_path / "net"), "--apply"]) == 0
    assert reads == ["bytes"]   # hashed and parsed from one read (was three: digest, State.load, mode)
    assert modes == [expected]  # None: apply falls back to env XG_NETWORK_MODE, as before


def test_state_network_mode_default_and_type_check(state_dict):
    doc = dict(state_dict)
    doc.pop("network_mode", None)
    assert State.from_dict(doc).network_mode is None
    assert State.from_dict({**doc, "network_mode": "proxy_only"}).network_mode == "proxy_only"
    with pytest.raises(ValueError, match="network_mode"):
        State.from_dict({**doc, "network_mode": 3})


# -- Step 18 (I-PROXY-18): block_ai PCs may not reach VPN/tunnel ports; ports from data/ YAML --

def test_builtin_vpn_ports_equal_data_yaml():
    yaml = pytest.importorskip("yaml")
    from xg_netpolicy.state import VPN_PORTS_DEFAULTS

    seed = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "data/network/proxy.yaml").read_text())
    assert seed["vpn_ports"] == VPN_PORTS_DEFAULTS
    assert State.from_dict({"vpn_ports": seed["vpn_ports"]}).vpn_ports == VPN_PORTS_DEFAULTS


def test_state_vpn_ports_defaults_and_bad_entries(state_dict, caplog):
    from xg_netpolicy.state import VPN_PORTS_DEFAULTS

    assert State.from_dict(state_dict).vpn_ports == VPN_PORTS_DEFAULTS  # today's state.json has none
    for unusable in (None, "22/tcp", {"22": "tcp"}, [], ["nope", 5]):
        assert State.from_dict(dict(state_dict, vpn_ports=unusable)).vpn_ports == VPN_PORTS_DEFAULTS, unusable
    caplog.clear()
    s = State.from_dict(dict(state_dict, vpn_ports=[" 51820/UDP ", "22/tcp", "22/tcp", "0/tcp", "65536/udp",
                                                     "53/icmp", "x/tcp", "²/tcp", 1194, "8443"]))
    assert s.vpn_ports == ["51820/udp", "22/tcp"]
    assert s.vpn_port_numbers("tcp") == [22] and s.vpn_port_numbers("udp") == [51820]
    assert len([r for r in caplog.records if "vpn_ports: skipping" in r.getMessage()]) == 7
    assert len([x for x in s.skipped if x.startswith("vpn_ports:")]) == 7
    assert State().vpn_port_numbers("tcp") == [22, 1194, 1723]  # not validated yet: defaults too


def test_sets_nft_fills_vpn_port_sets(state_dict, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps(state_dict))
    out = tmp_path / "net"
    generate.generate(state, out)
    nft = (out / "sets.nft").read_text().splitlines()
    i = nft.index("flush set inet xephyguard vpn_tcp_ports")
    assert nft[i + 1] == "add element inet xephyguard vpn_tcp_ports { 22, 1194, 1723 }"
    j = nft.index("flush set inet xephyguard vpn_udp_ports")
    assert nft[j + 1] == "add element inet xephyguard vpn_udp_ports { 500, 1194, 1701, 4500, 51820 }"
    # a list from the state replaces the built-in one; an emptied proto still flushes its set
    state_dict["vpn_ports"] = ["443/udp"]
    state.write_text(json.dumps(state_dict))
    assert generate.generate(state, out)["nft"]
    nft = (out / "sets.nft").read_text()
    assert "flush set inet xephyguard vpn_tcp_ports\nflush set inet xephyguard vpn_udp_ports\n" in nft
    assert nft.endswith("add element inet xephyguard vpn_udp_ports { 443 }\n")
    assert generate.desired_sets(State.load(state))["vpn_udp_ports"] == [443]


def test_forward_drops_vpn_ports_for_block_ai_before_established():
    nft = (pathlib.Path(__file__).resolve().parents[2] / "proxy/nftables/xephyguard.nft").read_text()
    assert "set vpn_tcp_ports    { type inet_service; }" in nft
    assert "set vpn_udp_ports    { type inet_service; }" in nft
    fwd = _nft_chain(nft, "forward")
    est = fwd.index("ct state established,related accept")
    for proto in ("tcp", "udp"):
        rule = (f'iifname "@LAN_IF@" ip saddr @block_ai_clients {proto} dport @vpn_{proto}_ports '
                'counter drop comment "block_ai: VPN/tunnel"')
        assert fwd.index(rule) < est, rule
    # Steps 3-4 order kept: test/isolated drops first, nothing accepted before the established rule
    assert fwd.index('oifname "@LAN_IF@" ip daddr @test_clients counter drop') < fwd.index(rule)
    assert not any(" accept" in ln for ln in fwd[:est])
    # exempt_clients stays a filled set that no rule reads (documented in the ruleset)
    assert not any("@exempt_clients" in ln for ln in nft.splitlines() if not ln.strip().startswith("#"))


# -- Step 20 (I-PROXY-15): reload never replaces the last good policy; no policy yet = fail closed --

def _rewrite(path, text, mtime):
    import os

    path.write_text(text)
    os.utime(path, (mtime, mtime))


@pytest.mark.parametrize("bad", ["[]", "{not json", '"policy"', '{"groups": null}', '{"categories": {"ai": 5}}',
                                 '{"path_rules": {"ai": 7}}', '{"inspect_hosts": 3}', '{"google": []}',
                                 '{"categories": ["ai"]}', '{"lab_subnet": 12}', '{"ccc_ip": 3232238082}',
                                 '{"version": "5"}', '{"always_block": [1]}'])
def test_policy_reload_keeps_last_good_on_any_error(state_file, tmp_path, caplog, bad):
    out = tmp_path / "net"
    generate.generate(state_file, out)
    pj = out / "proxy.json"
    _rewrite(pj, pj.read_text(), 1_000_000)
    c = PolicyCache(pj)
    assert c.loaded and c.state.version == 5
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"
    caplog.clear()
    _rewrite(pj, bad, 1_000_100)
    c.reload(force=True)
    c.reload(force=True)
    assert c.loaded and c.state.version == 5  # previous policy kept, still enforced
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"
    assert c.decide_tls("192.168.10.21", "example.com").action == "pass"
    assert c.decide_http("192.168.10.21", "huggingface.co", "/chat").action == "block"
    errors = [r for r in caplog.records if "invalid, keeping v5" in r.getMessage()]
    assert len(errors) == 1  # the same broken document is logged (and parsed) once


def test_policy_fails_closed_until_a_valid_policy_loads(state_file, tmp_path):
    out = tmp_path / "net"
    pj = out / "proxy.json"
    c = PolicyCache(pj, interval=0)  # not written yet
    assert not c.loaded
    for ip in ("192.168.10.21", "192.168.10.22", "192.168.10.99", None):
        d = c.decide_tls(ip, "example.com")
        assert (d.action, d.category) == ("block", "no_policy"), ip
        assert c.decide_http(ip, "example.com", "/").action == "block"
    out.mkdir()
    _rewrite(pj, '{"groups": []}', 1_000_000)  # invalid first document: still closed
    assert c.decide_tls("192.168.10.99", "example.com").action == "block" and not c.loaded
    generate.generate(state_file, out)
    _rewrite(pj, pj.read_text(), 1_000_100)
    assert c.decide_tls("192.168.10.99", "example.com").action == "pass" and c.loaded
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"


def test_policy_reload_retries_unreadable_file(state_file, tmp_path, monkeypatch, caplog):
    out = tmp_path / "net"
    generate.generate(state_file, out)
    pj = out / "proxy.json"
    c = PolicyCache(pj)
    doc = json.loads(pj.read_text())
    _rewrite(pj, json.dumps(dict(doc, version=6)), 1_000_100)
    real = pathlib.Path.read_text

    def flaky(self, *a, **kw):
        raise PermissionError("replaced mid-read")

    monkeypatch.setattr(pathlib.Path, "read_text", flaky)
    c.reload(force=True)
    assert c.state.version == 5 and "unreadable, keeping previous" in caplog.text
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    c.reload()  # same mtime, not marked as failed: read again at the next check
    c._checked = 0.0
    c.reload()
    assert c.state.version == 6


# -- Step 21 (I-PROXY-11): client-controlled host/path cleaned and cut before queueing --

def test_event_text_drops_non_printable_and_truncates():
    from xg_netpolicy.proxy_logic import event_text

    assert event_text("chatgpt.com", 255) == "chatgpt.com"
    assert event_text("a\x00b\r\nc\td\x7fe\x1b[31m", 255) == "abcde[31m"
    assert event_text("bad\udc80host​.com", 255) == "badhost.com"  # surrogateescape byte, zero-width space
    assert event_text("x" * 1000, 255) == "x" * 255
    assert event_text("\x00" * 300 + "ok", 255) == "ok"  # cleaned first, then cut
    assert event_text("ünïcode.example", 255) == "ünïcode.example"
    assert event_text(None, 255) is None and event_text(5, 255) == 5


def test_shipper_cleans_host_and_path_before_queueing(state_file, tmp_path):
    from xg_netpolicy.proxy_logic import EventShipper

    generate.generate(state_file, tmp_path / "net")
    shipper = EventShipper(PolicyCache(tmp_path / "net" / "proxy.json"), fallback=str(tmp_path / "ev.jsonl"))
    shipper.stop()  # no worker taking events from the queue
    shipper.emit(client_ip="192.168.10.21", host="h" * 300 + "\x00\n", path="/p\x00a\udc80th" + "y" * 600,
                 layer="http", action="blocked")
    shipper.emit(client_ip="192.168.10.21", host=None, layer="sni", action="blocked")
    ev = shipper.q.get_nowait()
    assert ev["host"] == "h" * 255 and ev["path"] == ("/path" + "y" * 600)[:512]
    json.dumps({"events": [ev]}).encode("utf-8")  # encodable: no lone surrogates left
    ev = shipper.q.get_nowait()
    assert ev["host"] is None and "path" not in ev  # absent or non-string fields stay as they are


def test_event_limits_match_net_events_controller():
    """The cut follows the server's validation (host max 255, path max 512), so the batch is accepted."""
    import re

    from xg_netpolicy.proxy_logic import EVENT_HOST_MAX, EVENT_PATH_MAX

    ctrl = (pathlib.Path(__file__).resolve().parents[2] / "server/app/Http/Controllers/Internal/NetEventsController.php").read_text(encoding="utf-8")
    assert int(re.search(r"'events\.\*\.host' => '[^']*max:(\d+)'", ctrl)[1]) == EVENT_HOST_MAX
    assert int(re.search(r"'events\.\*\.path' => '[^']*max:(\d+)'", ctrl)[1]) == EVENT_PATH_MAX


# -- Step 22 (I-PROXY-19): every state field type-checked; generated Unbound config checked before reload --

@pytest.mark.parametrize("bad", [
    {"version": "5"}, {"version": True}, {"version": None}, {"proxy_port": "8080"}, {"agent_port": 8443.0},
    {"ccc_ip": None}, {"lab_subnet": ["192.168.10.0/24"]}, {"wan_if": 0},
    {"events_url": 5}, {"events_token": ["t"]},
    {"always_block": "doh"}, {"always_block": [None]}, {"inspect_hosts": {"google.com": 1}},
    {"doh_ips": "8.8.8.8"},
    {"categories": ["ai"]}, {"categories": {"ai": "openai.com"}}, {"categories": {"ai": [5]}},
    {"path_rules": {"ai": None}}, {"group_categories": {"test": "ai"}}, {"group_categories": None},
    {"log_urls": True}, {"log_urls": []}, {"google": "on"}, {"groups": []},
])
def test_state_type_checks_every_field(state_dict, bad):
    with pytest.raises(ValueError, match=next(iter(bad))):
        State.from_dict(dict(state_dict, **bad))


def test_state_renders_canonical_addresses_and_reads_php_empty_arrays(state_dict, caplog):
    doc = dict(state_dict, lab_subnet="192.168.10.7/24", ccc_ip="192.168.10.2",
               categories=[], path_rules=[], group_categories=[], events_token=None,
               doh_ips=["8.8.8.8", " 45.90.28.0/24 ", "45.90.28.1/24", "2001:4860:4860::8888/128", "dns", 5, "1.1.1.1/33"])
    with caplog.at_level("WARNING", logger="xg-netpolicy.state"):
        s = State.from_dict(doc)
    assert s.lab_subnet == "192.168.10.0/24" and s.ccc_ip == "192.168.10.2"
    assert (s.categories, s.path_rules, s.group_categories, s.events_token) == ({}, {}, {}, "")
    assert s.doh_ips == ["8.8.8.8", "45.90.28.0/24", "45.90.28.0/24", "2001:4860:4860::8888"]
    assert [x.split(" (")[0] for x in s.skipped] == ["doh_ips: 'dns'", "doh_ips: 5", "doh_ips: '1.1.1.1/33'"]
    assert caplog.text.count("doh_ips: skipping") == 3
    assert "access-control: 192.168.10.0/24 allow" in generate.unbound_conf(s)


def test_proxy_loads_policy_with_php_empty_path_rules(state_file, tmp_path):
    out = tmp_path / "net"
    generate.generate(state_file, out)
    pj = out / "proxy.json"
    pj.write_text(json.dumps(dict(json.loads(pj.read_text()), path_rules=[])))
    c = PolicyCache(pj)
    assert c.loaded and c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"


class _Res:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def test_unbound_config_is_checked_before_it_replaces_the_old_one(state_file, state_dict, tmp_path, monkeypatch,
                                                                  caplog):
    out = tmp_path / "net"
    calls = []
    verdict = {"code": 0}

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[0].endswith("unbound-checkconf"):
            main = pathlib.Path(cmd[1])
            assert main.name == "unbound-xephyguard.conf.check.main"
            assert f'include: "{(out / "unbound-xephyguard.conf.check").as_posix()}"' in main.read_text()
            assert (out / "unbound-xephyguard.conf.check").exists()
            return _Res(verdict["code"], "", "syntax error line 3")
        return _Res(0)

    monkeypatch.setattr(generate.shutil, "which", lambda name: "/usr/sbin/" + name)
    monkeypatch.setattr(generate.subprocess, "run", fake_run)
    assert generate.generate(state_file, out)["unbound"] is True
    good = (out / "unbound-xephyguard.conf").read_text()
    assert calls == [["/usr/sbin/unbound-checkconf", str(out / "unbound-xephyguard.conf.check.main")]]
    assert sorted(f.name for f in out.iterdir()) == ["proxy.json", "sets.nft", "unbound-xephyguard.conf"]

    # a rejected config keeps the old file, is not reloaded, and the nft/proxy files still update
    verdict["code"] = 1
    state_file.write_text(json.dumps(dict(state_dict, version=6)))
    with caplog.at_level("ERROR", logger="xg-netpolicy"):
        changed = generate.generate(state_file, out)
    assert changed == {"unbound": False, "nft": True, "proxy": True}
    assert (out / "unbound-xephyguard.conf").read_text() == good
    assert sorted(f.name for f in out.iterdir()) == ["proxy.json", "sets.nft", "unbound-xephyguard.conf"]
    assert "unbound-checkconf rejected the generated config, keeping the previous one: syntax error line 3" in caplog.text
    calls.clear()
    generate.apply(out, changed, network_mode="proxy_only")
    assert not any("unbound-control" in c[0] for c in calls)

    # accepted again: replaced and reloaded
    verdict["code"] = 0
    assert generate.generate(state_file, out)["unbound"] is True
    assert "state version 6" in (out / "unbound-xephyguard.conf").read_text()


def test_unbound_check_skipped_with_one_warning_without_binary(state_file, state_dict, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(generate.shutil, "which", lambda name: None)
    monkeypatch.setattr(generate, "_checkconf_missing_warned", False)
    out = tmp_path / "net"
    with caplog.at_level("WARNING", logger="xg-netpolicy"):
        assert generate.generate(state_file, out)["unbound"] is True
        state_file.write_text(json.dumps(dict(state_dict, version=6)))
        assert generate.generate(state_file, out)["unbound"] is True
    assert caplog.text.count("unbound-checkconf not installed") == 1
    assert not (out / "unbound-xephyguard.conf.check").exists()


# -- Step 23 (I-PROXY-14): doh_ips collapsed; a failed nft -f is a health flag, not only a log line --

def test_sets_nft_collapses_overlapping_resolver_ips(state_dict):
    doc = dict(state_dict, doh_ips=["45.90.28.0/24", "45.90.28.1", "8.8.8.8", "8.8.8.8", "8.8.4.0/25", "8.8.4.128/25",
                                    "2001:4860:4860::8888", "2001:4860:4860::/48", "1.1.1.1"])
    s = State.from_dict(doc)
    nft = generate.nft_sets(s)
    assert "add element inet xephyguard resolver_ips { 1.1.1.1, 8.8.4.0/24, 8.8.8.8, 45.90.28.0/24 }" in nft
    assert "add element inet xephyguard resolver_ips6 { 2001:4860:4860::/48 }" in nft
    # the resync check compares the same collapsed elements, so it does not re-apply forever
    want = generate.desired_sets(s)
    assert [str(n) for n in want["resolver_ips"]] == ["1.1.1.1/32", "8.8.4.0/24", "8.8.8.8/32", "45.90.28.0/24"]
    assert [str(n) for n in want["resolver_ips6"]] == ["2001:4860:4860::/48"]


def test_apply_writes_nft_health_flag(state_file, tmp_path, monkeypatch, caplog):
    out = tmp_path / "net"
    changed = generate.generate(state_file, out)
    result = {"code": 1}
    clock = iter(["2026-11-25T10:00:00Z", "2026-11-25T10:00:10Z", "2026-11-25T10:00:20Z", "2026-11-25T10:00:30Z"])
    monkeypatch.setattr(generate, "_now", lambda: next(clock))
    monkeypatch.setattr(generate, "_nft_table_present", lambda: True)
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, **kw: _Res(result["code"], "", "Error: interval overlaps" if result["code"] else ""))

    def health():
        return json.loads((out / "health.json").read_text())

    with caplog.at_level("ERROR", logger="xg-netpolicy"):
        generate.apply(out, changed, network_mode="gateway")
    assert "nft failed: Error: interval overlaps" in caplog.text  # still logged
    assert health() == {"nft_ok": False, "nft_error": "Error: interval overlaps", "nft_skipped": None,
                        "nft_failed_since": "2026-11-25T10:00:00Z", "nft_checked_at": "2026-11-25T10:00:00Z"}
    generate.apply(out, {"nft": True}, network_mode="gateway")  # e.g. the resync re-apply fails again
    assert health()["nft_failed_since"] == "2026-11-25T10:00:00Z"
    assert health()["nft_checked_at"] == "2026-11-25T10:00:10Z"
    result["code"] = 0
    generate.apply(out, {"nft": True}, network_mode="gateway")
    assert health() == {"nft_ok": True, "nft_error": None, "nft_skipped": None, "nft_failed_since": None,
                        "nft_checked_at": "2026-11-25T10:00:20Z"}
    generate.apply(out, {"nft": True}, network_mode="proxy_only")
    assert health()["nft_ok"] is None and health()["nft_skipped"] == "proxy_only mode"
    # nothing to load (sets.nft unchanged): the last result stays
    generate.apply(out, {"unbound": True}, network_mode="gateway")
    assert health()["nft_checked_at"] == "2026-11-25T10:00:30Z"


def test_conntrack_not_flushed_when_nft_fails(state_file, tmp_path, monkeypatch):
    out = tmp_path / "net"
    changed = generate.generate(state_file, out)
    calls = []
    monkeypatch.setattr(generate, "_nft_table_present", lambda: True)
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, **kw: (calls.append(cmd) or _Res(1 if cmd[0] == "nft" else 0, "", "bad")))
    generate.apply(out, changed, network_mode="gateway", flush_ips={"192.168.10.21"})
    assert not any(c[0] == "conntrack" for c in calls)
    assert json.loads((out / "health.json").read_text())["nft_ok"] is False


# -- Step 24 (I-PROXY-28): groups are disjoint; exempt wins, then isolated, test, block_ai --

def test_state_makes_groups_disjoint_exempt_wins(state_dict, caplog):
    state_dict["groups"] = {"test": ["192.168.10.21", "192.168.10.22", "192.168.10.41", "192.168.10.21"],
                            "block_ai": ["192.168.10.30", "192.168.10.31", "192.168.10.21"],
                            "isolated": ["192.168.10.40", "192.168.10.41", "192.168.10.42"],
                            "exempt": ["192.168.10.22", "192.168.10.31", "192.168.10.42"]}
    with caplog.at_level("WARNING", logger="xg-netpolicy.state"):
        s = State.from_dict(state_dict)
    assert s.groups == {"test": ["192.168.10.21"], "block_ai": ["192.168.10.30"],
                        "isolated": ["192.168.10.40", "192.168.10.41"],
                        "exempt": ["192.168.10.22", "192.168.10.31", "192.168.10.42"]}
    assert sorted(s.skipped) == sorted([
        "groups.isolated: '192.168.10.42' (also in exempt, exempt wins)",
        "groups.test: '192.168.10.22' (also in exempt, exempt wins)",
        "groups.test: '192.168.10.41' (also in isolated, isolated wins)",
        "groups.block_ai: '192.168.10.31' (also in exempt, exempt wins)",
        "groups.block_ai: '192.168.10.21' (also in test, test wins)"])  # the repeated .21 is only de-duplicated
    assert caplog.text.count("keeping it only in") == 5
    for ip, g in (("192.168.10.22", "exempt"), ("192.168.10.31", "exempt"), ("192.168.10.41", "isolated"),
                  ("192.168.10.21", "test")):
        assert s.group_of(ip) == g


def test_gateway_dns_and_proxy_agree_on_an_ip_in_two_groups(state_dict, tmp_path):
    # exempt + test used to get the test DNS view and test_clients drops while the proxy let it pass;
    # exempt + block_ai used to be dropped towards VPN ports (Step 18)
    state_dict["groups"] = {"test": ["192.168.10.21", "192.168.10.22"], "block_ai": ["192.168.10.30", "192.168.10.31"],
                            "isolated": [], "exempt": ["192.168.10.22", "192.168.10.31"]}
    out = tmp_path / "net"
    generate.generate_state(State.from_dict(state_dict), out)
    unbound = (out / "unbound-xephyguard.conf").read_text()
    assert "192.168.10.22/32" not in unbound and "192.168.10.31/32" not in unbound
    assert "access-control-view: 192.168.10.21/32 xg_test" in unbound
    sets = (out / "sets.nft").read_text()
    assert "add element inet xephyguard test_clients { 192.168.10.21 }" in sets
    assert "add element inet xephyguard block_ai_clients { 192.168.10.30 }" in sets
    assert "add element inet xephyguard exempt_clients { 192.168.10.22, 192.168.10.31 }" in sets
    assert generate.restricted_ips(State.from_dict(state_dict)) == {"192.168.10.21"}
    c = PolicyCache(out / "proxy.json")
    assert json.loads((out / "proxy.json").read_text())["groups"]["test"] == ["192.168.10.21"]
    for ip in ("192.168.10.22", "192.168.10.31"):
        assert c.decide_tls(ip, "chatgpt.com").action == "pass"
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "block"


def test_session_clients_validated_and_copied_to_proxy_json(state_dict, tmp_path):
    """I-PROXY-10: optional session_clients list; bad PCs dropped like a group entry, a non-list
    rejects the document, None falls back to test/block_ai/exempt, and proxy.json carries it."""
    s = State.from_dict(state_dict)
    assert s.session_clients is None
    assert s.in_session("::ffff:192.168.10.30") and s.in_session("192.168.10.22") and s.in_session("192.168.10.21")
    assert not s.in_session("192.168.10.99") and not s.in_session("192.168.10.40") and not s.in_session(None)
    s = State.from_dict({**state_dict, "session_clients": ["192.168.10.99", 7, "10.0.0.1"]})
    assert s.session_clients == ["192.168.10.99"]
    assert any(x.startswith("session_clients: 7") for x in s.skipped)
    assert s.in_session("192.168.10.99") and not s.in_session("192.168.10.30")
    with pytest.raises(ValueError, match="session_clients"):
        State.from_dict({**state_dict, "session_clients": "192.168.10.99"})
    p = tmp_path / "state.json"
    p.write_text(json.dumps({**state_dict, "session_clients": ["192.168.10.99"]}))
    generate.generate(p, tmp_path / "net")
    assert json.loads((tmp_path / "net" / "proxy.json").read_text())["session_clients"] == ["192.168.10.99"]


def test_server_shaped_document_with_session_clients(tmp_path):
    """I-PROXY-10 CROSS (server S-58): a document as NetworkPolicyWriter::build writes it, Practice with
    AI allowed. The session PCs block nothing, so every group but isolated is empty ([] from PHP), and
    only session_clients says they are in a session; isolated and non-session PCs are not observed."""
    doc = {
        "version": 12, "generated_at": "2026-11-25T10:00:00+00:00", "network_mode": "gateway",
        "ccc_ip": "192.168.10.2", "lab_subnet": "192.168.10.0/24", "lan_if": "enp2s0", "wan_if": "enp1s0",
        "proxy_port": 3128, "agent_port": 8443,
        "groups": {"test": [], "block_ai": [], "isolated": ["192.168.10.23"], "exempt": []},
        "categories": {"ai": ["chatgpt.com"], "doh": ["dns.google"]},
        "path_rules": [],                                  # PHP json_encode of an empty array
        "group_categories": {"test": [], "block_ai": []},
        "always_block": ["doh"], "doh_ips": [],
        "google": {"force_udm14": False, "udm14_clients": [], "hide_selectors": ["g-ai-overview"],
                   "search_hosts": [r"^(?:www\.|encrypted\.)?google\.[a-z]{2,6}(?:\.[a-z]{2})?$"],
                   "ai_paths": ["/async/folwr"], "css_hosts": ["bing.com"]},
        "inspect_hosts": ["www.google.com"],
        "session_clients": ["192.168.10.21", "192.168.10.22"],
        "log_urls": {"enabled": True},
        "events_url": "http://127.0.0.1:8080/api/internal/net-events", "events_token": "x" * 32,
    }
    p = tmp_path / "state.json"
    p.write_text(json.dumps(doc))
    generate.generate(p, tmp_path / "net")
    assert json.loads((tmp_path / "net" / "proxy.json").read_text())["session_clients"] == ["192.168.10.21", "192.168.10.22"]
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    assert c.state.group_of("192.168.10.21") is None                  # in no group ...
    assert c.records_observed("192.168.10.21") and c.records_observed("::ffff:192.168.10.22")   # ... but in the session
    assert not c.records_observed("192.168.10.23")                    # isolated
    assert not c.records_observed("192.168.10.99")                    # not in the session
    assert c.decide_tls("192.168.10.21", "chatgpt.com").action == "pass"   # AI allowed in this profile
    without = {k: v for k, v in doc.items() if k != "session_clients"}       # an older CCC: group fallback
    assert not State.from_dict(without).in_session("192.168.10.21")


# -- I-PROXY-20: per-request lookups stay cheap with large imported lists --------------------------
def _big_policy(state_dict, n=5000):
    """5,000 domains spread over five categories and 5,000 path rules (ai and ide)."""
    cats = ["ai", "ide", "marketplace", "vpn", "doh"]
    state_dict["categories"] = {c: [f"host{i}.{c}-list.example" for i in range(k, n, len(cats))]
                                for k, c in enumerate(cats)}
    state_dict["path_rules"] = {"ai": [f"site{i}.example/chat{i}" for i in range(0, n, 2)],
                                "ide": [f"site{i}.example/q{i}" for i in range(1, n, 2)]}
    return state_dict


def _best_of(fn, runs=3):
    best = float("inf")
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t)
    return best


def test_lookups_on_5000_domains_fit_timing_budget(state_file, state_dict, tmp_path):
    """category_of, path_rules_for_group and path_rule_match run on every blocked or inspected request
    inside mitmproxy's event loop. Budget: 2,000 lookups each in 0.25 s (precomputed at reload they
    take a few ms; rebuilding the lists per call took seconds)."""
    state_file.write_text(json.dumps(_big_policy(state_dict)))
    generate.generate(state_file, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    s = c.state
    hosts = [f"www.host{i}.vpn-list.example" for i in range(3, 5000, 5)][:1000] + [f"miss{i}.example" for i in range(1000)]
    assert s.category_of("www.host3.vpn-list.example") == "vpn" and s.category_of("miss.example") is None

    def cats():
        for h in hosts:
            s.category_of(h)

    def group_rules():
        for i in range(2000):
            s.path_rules_for_group("test" if i % 2 else "block_ai")

    def rule_match():
        for i in range(2000):
            s.path_rule_match("test", f"site{i}.example", f"/chat{i}/x" if i % 2 == 0 else f"/q{i}")

    assert s.path_rule_match("test", "a.site7.example", "/q7/x") == ("site7.example/q7", "ide")
    assert s.path_rule_match("block_ai", "site7.example", "/q7") is None
    for name, fn in (("category_of", cats), ("path_rules_for_group", group_rules), ("path_rule_match", rule_match)):
        took = _best_of(fn)
        assert took < 0.25, f"{name}: 2,000 calls took {took:.3f} s"


def test_precomputed_lookups_keep_first_match_order():
    """The indexes from Step 35 return what the old linear scans returned: the first category in
    document order listing the domain or a parent, and the first matching path rule in list order."""
    s = State.from_dict({"categories": {"ai": ["Example.com", "x.org"], "ide": ["a.example.com", "x.org"]},
                         "path_rules": {"ai": ["b.x.com/a"], "ide": ["x.com/a"]},
                         "group_categories": {"test": ["ide", "ai"], "block_ai": ["ai"]}})
    assert s.category_of("a.example.com") == "ai" and s.category_of("X.ORG.") == "ai"
    assert s.category_of("z.a.example.com") == "ai" and s.category_of("example.net") is None
    assert s.category_of("") is None
    assert s.path_rule_match("test", "b.x.com", "/a/1") == ("x.com/a", "ide")     # group order: ide first
    assert s.path_rule_match("block_ai", "b.x.com", "/a") == ("b.x.com/a", "ai")
    assert s.path_rule_match("block_ai", "x.com", "/a") is None
    assert PathRules.of(["x.com/a", "b.x.com/a"]).matches("b.x.com", "/a") == "x.com/a"
    assert PathRules.of(["b.x.com/a", "x.com/a"]).matches("B.X.com.", "/A/") == "b.x.com/a"
    assert s.path_rules_for_group("test").matches("b.x.com", "/a") == "x.com/a"
    assert s.path_rules_for_group("exempt").rules == [] and s.path_rules_for_group("nope").rules == []
    # a document key named like the private index is ignored, and validate() drops a stale index
    assert State.from_dict({"_index": "x"})._index is None
    s.categories = {"vpn": ["example.com"]}
    s.validate()
    assert s.category_of("example.com") == "vpn"


def test_path_rule_hosts_are_inspected_for_their_group(state_file, state_dict, tmp_path):
    """I-PROXY-17: a rule host missing from inspect_hosts (hf.co/chat, aws.amazon.com/q) is still
    decrypted for a group whose rules name it, so the rule applies over HTTPS. Exact host only, never
    a NEVER_INSPECT host, never for a group the rule does not apply to."""
    state_dict["path_rules"] = {"ai": ["hf.co/chat", "huggingface.co/chat", "accounts.google.com/x"],
                                "ide": ["aws.amazon.com/q"]}
    state_file.write_text(json.dumps(state_dict))
    generate.generate(state_file, tmp_path / "net")
    c = PolicyCache(tmp_path / "net" / "proxy.json")
    test, block_ai, exempt, none = "192.168.10.21", "192.168.10.30", "192.168.10.22", "192.168.10.99"
    for host in ("hf.co", "HF.CO.", "aws.amazon.com"):
        d = c.decide_tls(test, host)
        assert (d.action, d.reason) == ("inspect", "path rule host"), host
    assert c.decide_http(test, "hf.co", "/chat/x").action == "block"
    assert c.decide_http(test, "aws.amazon.com", "/q").category == "ide"
    assert c.decide_tls(block_ai, "hf.co").action == "inspect"
    assert c.decide_tls(block_ai, "aws.amazon.com").action == "pass"     # ide rules don't apply to block_ai
    for ip in (exempt, none):
        assert c.decide_tls(ip, "hf.co").action == "pass", ip
    for host in ("cdn.hf.co", "console.aws.amazon.com", "amazon.com", "accounts.google.com", "hf.co.evil.net"):
        assert c.decide_tls(test, host).action == "pass", host
    assert c.decide_tls(test, "huggingface.co").reason == "selective inspection host"   # already listed
