"""Runs the real checkers on generated files: `nft -c -f` on xephyguard.nft + sets.nft and
`unbound-checkconf` on unbound-xephyguard.conf. Each test is skipped (with the reason) when its
binary is missing or may not run here, e.g. on Windows or without CAP_NET_ADMIN."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from xg_netpolicy import generate

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLACEHOLDERS = {"LAN_IF": "lan_if", "WAN_IF": "wan_if", "CCC_IP": "ccc_ip", "LAB_SUBNET": "lab_subnet",
                "PROXY_PORT": "proxy_port", "AGENT_PORT": "agent_port"}


def _generated(state_dict, tmp_path):
    # every group and both resolver families filled, so each set gets an "add element" line
    state_dict["groups"]["block_ai"] = ["192.168.10.30", "192.168.10.31"]
    state_dict["doh_ips"] = ["8.8.8.8", "1.1.1.0/24", "2001:4860:4860::8888", "2606:4700::/32"]
    state = tmp_path / "state.json"
    state.write_text(json.dumps(state_dict))
    out = tmp_path / "net"
    generate.generate(state, out)
    return out


def _ruleset(state_dict):
    text = (ROOT / "proxy/nftables/xephyguard.nft").read_text()
    for ph, key in PLACEHOLDERS.items():
        text = text.replace(f"@{ph}@", str(state_dict.get(key, "")))
    return text


def test_ruleset_placeholders_are_all_known(state_dict):
    # runs everywhere: the tests below (and CI, install.sh) substitute exactly these names
    rendered = _ruleset(state_dict)
    assert not re.findall(r"@[A-Z_]+@", rendered)
    assert '"enp2s0"' in rendered and '"enp1s0"' in rendered


def _run_checker(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except OSError as e:
        pytest.skip(f"{cmd[0]} could not run: {e}")
    msg = (r.stderr or r.stdout).strip()
    if r.returncode and re.search(r"Operation not permitted|Permission denied|cache initialization failed", msg):
        pytest.skip(f"{cmd[0]} needs privileges here: {msg[:200]}")
    return r.returncode, msg


@pytest.mark.skipif(not shutil.which("nft"), reason="nft not installed (CI deploy-config checks the ruleset alone)")
def test_nft_accepts_ruleset_with_generated_sets(state_dict, tmp_path):
    out = _generated(state_dict, tmp_path)
    combined = tmp_path / "xephyguard-with-sets.nft"
    combined.write_text(_ruleset(state_dict) + "\n" + (out / "sets.nft").read_text() + (out / "resolver-sets.nft").read_text())
    code, msg = _run_checker(["nft", "-c", "-f", str(combined)])
    assert code == 0, msg


@pytest.mark.skipif(not shutil.which("unbound-checkconf"), reason="unbound-checkconf not installed")
def test_unbound_checkconf_accepts_generated_views(state_dict, tmp_path):
    out = _generated(state_dict, tmp_path)
    # a minimal main config around the generated include (like proxy/dns/unbound.conf, without the
    # chroot, user and control socket of the container)
    main = tmp_path / "unbound.conf"
    main.write_text("server:\n"
                    '    chroot: ""\n'
                    '    username: ""\n'
                    f'    directory: "{tmp_path.as_posix()}"\n'
                    '    pidfile: ""\n'
                    "    interface: 127.0.0.1\n"
                    "    port: 53530\n"
                    f'    include: "{(out / "unbound-xephyguard.conf").as_posix()}"\n')
    code, msg = _run_checker(["unbound-checkconf", str(main)])
    assert code == 0, msg


def test_requirements_mitmproxy_range_matches_image_pin():
    """I-PROXY-32: proxy/requirements.txt bounds mitmproxy below the next major after the image's
    `FROM mitmproxy/mitmproxy:<major>`, so a local install can't pull a major the addon (tls,
    server_hooks APIs) was never run against; the installed mitmproxy is in that range."""
    import mitmproxy.version
    pin = re.search(r"^FROM mitmproxy/mitmproxy:(\d+)\b", (ROOT / "ccc-deploy/docker/proxy.Dockerfile").read_text(), re.M)
    assert pin, "proxy.Dockerfile no longer pins a mitmproxy major"
    major = int(pin.group(1))
    req = [ln.strip() for ln in (ROOT / "proxy/requirements.txt").read_text().splitlines() if ln.strip().startswith("mitmproxy")]
    m = re.fullmatch(r"mitmproxy>=(\d+),<(\d+)", req[0]) if len(req) == 1 else None
    assert m, f"expected one 'mitmproxy>=N,<M' line, got {req}"
    low, high = int(m.group(1)), int(m.group(2))
    assert low <= major and high == major + 1, (low, high, major)
    installed = int(mitmproxy.version.VERSION.split(".")[0])
    assert low <= installed < high, f"installed mitmproxy {mitmproxy.version.VERSION} outside >={low},<{high}"
