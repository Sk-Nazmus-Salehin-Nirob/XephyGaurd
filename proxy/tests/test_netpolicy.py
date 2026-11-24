import json

import pytest

from xg_netpolicy import generate
from xg_netpolicy.domains import DomainSet, PathRules, normalize_domain, parse_list
from xg_netpolicy.proxy_logic import PolicyCache, google_search_rewrite, inject_css, refused_destination
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


def test_state_rejects_foreign_ip(state_dict):
    state_dict["groups"]["test"].append("10.0.0.5")
    with pytest.raises(ValueError):
        State.from_dict(state_dict)


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
    assert "add element inet xephyguard test_clients { 192.168.10.21, 192.168.10.22 }" in nft
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
    assert seen == [{"192.168.10.21", "192.168.10.22", "192.168.10.40"}, {"192.168.10.50"}]


def _live_json(sets):
    """nft -j list table output: one set object per name, like nftables 1.0."""
    objs = [{"metainfo": {"version": "1.0.6", "json_schema_version": 1}},
            {"table": {"family": "inet", "name": "xephyguard", "handle": 7}}]
    for name, elem in sets.items():
        st = {"family": "inet", "name": name, "table": "xephyguard", "type": "ipv4_addr", "handle": 1}
        if elem:
            st["elem"] = elem
        objs.append({"set": st})
    return json.dumps({"nftables": objs})


def _in_sync_sets():
    return {"test_clients": ["192.168.10.22", "192.168.10.21"], "block_ai_clients": ["192.168.10.30"],
            "isolated_clients": ["192.168.10.40"], "exempt_clients": [{"elem": {"val": "192.168.10.22"}}],
            "resolver_ips": [{"range": ["1.1.1.1", "1.1.1.1"]}, {"prefix": {"addr": "8.8.8.8", "len": 32}}],
            "resolver_ips6": ["2001:4860:4860::8888"]}


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
    live = dict(_in_sync_sets(), test_clients=["192.168.10.21"])
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
    assert len(calls[0][1]) == 3  # first pass
    restricted = {"192.168.10.21", "192.168.10.22", "192.168.10.40"}
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
    {"lan_if": 7},                          # AttributeError in validate
    {"groups": {"test": [5]}},              # TypeError/ValueError from ipaddress
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
                      {"192.168.10.21", "192.168.10.22", "192.168.10.40"})]
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
