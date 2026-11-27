"""Tests for helper scripts in ccc-deploy/bin (run with the proxy suite, as CI does)."""
import importlib.util
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


daemon = _load("xg_docker_daemon", "ccc-deploy/bin/xg-docker-daemon.py")
discovery = _load("xg_discovery", "ccc-deploy/services/discovery.py")


# -- ccc-deploy Step 22 (I-CCC-12): the discovery responder ignores junk and never stops --

PROBE = b'{"probe":"XEPHYGUARD_DISCOVER","v":1}'


@pytest.mark.parametrize("data", [b"[]", b"1", b'"x"', b"null", b"{", b"\xff\xfe", b"", b'{"probe":"other"}'])
def test_discovery_ignores_what_is_not_a_probe_object(data):
    assert discovery.reply_for(data) is None


def test_discovery_answers_a_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CA", str(tmp_path / "missing.crt"))
    monkeypatch.setenv("XG_CCC_IP", "192.168.10.2")
    monkeypatch.setenv("XG_LAB_NAME", "Lab 3")
    reply = json.loads(discovery.reply_for(PROBE))
    assert reply == {"service": "xephyguard-ccc", "host": "192.168.10.2", "api_port": 8443,
                     "ca_fingerprint": "", "lab": "Lab 3"}


@pytest.mark.parametrize("content", [b"not a certificate", b"\xff\xfe\x00", b""])
def test_discovery_fingerprint_is_empty_for_a_malformed_ca(monkeypatch, tmp_path, content):
    (tmp_path / "ca.crt").write_bytes(content)
    monkeypatch.setattr(discovery, "CA", str(tmp_path / "ca.crt"))
    assert discovery.fingerprint() == ""


def test_discovery_fingerprint_of_a_real_certificate(monkeypatch, tmp_path):
    import datetime
    import hashlib
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lab CA")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (tmp_path / "ca.crt").write_bytes(pem)
    monkeypatch.setattr(discovery, "CA", str(tmp_path / "ca.crt"))
    assert discovery.fingerprint() == hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode())).hexdigest()


def _fake_socket(queue, sent, opts=None, bind_error=None):
    class FakeSocket:
        def __init__(self, *a):
            self.queue = list(queue)

        def setsockopt(self, level, opt, value):
            if opt == discovery.SO_BINDTODEVICE:
                if bind_error:
                    raise bind_error
                if opts is not None:
                    opts.append(value)

        def bind(self, addr):
            pass

        def recvfrom(self, n):
            if not self.queue:
                raise KeyboardInterrupt
            return self.queue.pop(0)

        def sendto(self, data, addr):
            sent.append(addr[0])

    return FakeSocket


# -- ccc-deploy Step 23 (I-CCC-19): only the lab, bound to its interface, rate-limited per source --

def test_discovery_answers_only_the_lab_subnet_and_binds_the_lab_interface(monkeypatch):
    monkeypatch.setenv("XG_LAB_SUBNET", "192.168.10.0/24")
    monkeypatch.setenv("XG_LAN_IF", "enp2s0")
    sent, opts = [], []
    queue = [(PROBE, ("203.0.113.9", 1)), (PROBE, ("192.168.10.21", 1)), (PROBE, ("192.168.11.5", 1))]
    monkeypatch.setattr(discovery.socket, "socket", _fake_socket(queue, sent, opts))
    with pytest.raises(KeyboardInterrupt):
        discovery.main()
    assert sent == ["192.168.10.21"] and opts == [b"enp2s0"]


def test_discovery_without_interface_permission_still_filters(monkeypatch, caplog):
    monkeypatch.setenv("XG_LAB_SUBNET", "10.0.0.0/8")
    monkeypatch.setenv("XG_LAN_IF", "eth0")
    sent = []
    queue = [(PROBE, ("10.1.2.3", 1)), (PROBE, ("8.8.4.4", 1))]
    monkeypatch.setattr(discovery.socket, "socket", _fake_socket(queue, sent, bind_error=PermissionError(1, "nope")))
    with pytest.raises(KeyboardInterrupt):
        discovery.main()
    assert sent == ["10.1.2.3"] and "filtering by source subnet only" in caplog.text


def test_discovery_bad_subnet_stops_at_start(monkeypatch):
    monkeypatch.setenv("XG_LAB_SUBNET", "not-a-subnet")
    with pytest.raises(ValueError):
        discovery.main()


def test_rate_limiter_burst_then_refill_per_source():
    rl = discovery.RateLimiter(rate=0.5, burst=3)
    assert [rl.allow("10.0.0.1", 0.0) for _ in range(4)] == [True, True, True, False]
    assert rl.allow("10.0.0.2", 0.0) is True       # other sources are not affected
    assert rl.allow("10.0.0.1", 1.0) is False      # half a token after 1 s
    assert rl.allow("10.0.0.1", 2.0) is True       # one token after 2 s
    assert rl.allow("10.0.0.1", 2.0) is False


def test_rate_limiter_memory_is_capped():
    rl = discovery.RateLimiter(rate=0.5, burst=1, max_sources=3)
    for i in range(10):
        rl.allow(f"10.0.0.{i}", 0.0)
    assert list(rl.buckets) == ["10.0.0.7", "10.0.0.8", "10.0.0.9"]


def test_discovery_loop_survives_bad_datagrams_and_send_errors(monkeypatch):
    monkeypatch.delenv("XG_LAB_SUBNET", raising=False)
    monkeypatch.delenv("XG_LAN_IF", raising=False)
    sent = []

    class FakeSocket:
        def __init__(self, *a):
            self.queue = [(b"[]", ("10.0.0.5", 1)), (PROBE, ("10.0.0.6", 1)), (PROBE, ("10.0.0.7", 1))]

        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            pass

        def recvfrom(self, n):
            if not self.queue:
                raise KeyboardInterrupt   # ends the test; not caught by the loop
            return self.queue.pop(0)

        def sendto(self, data, addr):
            if addr[0] == "10.0.0.6":
                raise OSError("network unreachable")
            sent.append(addr[0])

    monkeypatch.setattr(discovery.socket, "socket", FakeSocket)
    with pytest.raises(KeyboardInterrupt):
        discovery.main()
    assert sent == ["10.0.0.7"]   # the send error on .6 did not stop the loop


# -- ccc-deploy Step 20 (I-CCC-14): base images pinned by exact tag and digest, no toolchain download --

PINNED = re.compile(r"^[\w./-]+:[\w.-]*\d[\w.-]*@sha256:[0-9a-f]{64}$")


def test_every_base_image_is_pinned_by_tag_and_digest():
    images = []
    for f in sorted((ROOT / "ccc-deploy/docker").glob("*.Dockerfile")):
        images += [(f.name, ln.split()[1]) for ln in f.read_text().splitlines() if ln.startswith("FROM ")]
    for f in sorted((ROOT / "ccc-deploy").glob("docker-compose*.yml")):
        images += [(f.name, ln.split("image:", 1)[1].strip()) for ln in f.read_text().splitlines()
                   if ln.strip().startswith("image:") and "xephyguard/" not in ln]
    assert len(images) >= 11
    assert [i for i in images if not PINNED.match(i[1])] == []


def test_go_builds_never_download_a_toolchain():
    text = (ROOT / "ccc-deploy/docker/screen-gateway.Dockerfile").read_text()
    assert "ENV GOTOOLCHAIN=local" in text and "GOTOOLCHAIN=auto" not in text


# -- ccc-deploy Step 17 (I-CCC-17): daemon.json is merged, never overwritten --

def test_daemon_merge_into_nothing_adds_required_and_log_defaults():
    assert daemon.merge("") == {"iptables": False, "ip6tables": False, "log-driver": "json-file",
                                "log-opts": {"max-size": "20m", "max-file": "5"}}


def test_daemon_merge_keeps_the_admins_settings():
    text = json.dumps({"registry-mirrors": ["https://mirror.example"], "log-driver": "journald",
                       "iptables": True, "data-root": "/srv/docker"})
    assert daemon.merge(text) == {"registry-mirrors": ["https://mirror.example"], "log-driver": "journald",
                                  "iptables": False, "ip6tables": False, "data-root": "/srv/docker"}


@pytest.mark.parametrize("text", ["{ not json", "[1, 2]", '"x"'])
def test_daemon_merge_rejects_what_is_not_an_object(text):
    with pytest.raises((ValueError, TypeError)):
        daemon.merge(text)


def test_daemon_main_backs_up_writes_and_is_idempotent(tmp_path, capsys):
    path = tmp_path / "daemon.json"
    path.write_text('{"registry-mirrors": ["https://mirror.example"]}')
    assert daemon.main(str(path)) == 0 and capsys.readouterr().out.strip() == "changed"
    backups = list(tmp_path.glob("daemon.json.xephyguard-*.bak"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == {"registry-mirrors": ["https://mirror.example"]}
    merged = json.loads(path.read_text())
    assert merged["iptables"] is False and merged["registry-mirrors"] == ["https://mirror.example"]
    assert daemon.main(str(path)) == 0 and capsys.readouterr().out.strip() == "unchanged"
    assert len(list(tmp_path.glob("daemon.json.xephyguard-*.bak"))) == 1   # no backup when nothing changes
    assert not list(tmp_path.glob(".daemon.json.*"))                      # no temp file left


def test_daemon_main_creates_a_missing_file_without_backup(tmp_path, capsys):
    path = tmp_path / "daemon.json"
    assert daemon.main(str(path)) == 0 and capsys.readouterr().out.strip() == "changed"
    assert json.loads(path.read_text())["ip6tables"] is False
    assert not list(tmp_path.glob("*.bak"))


def test_daemon_main_leaves_invalid_json_alone(tmp_path, capsys):
    path = tmp_path / "daemon.json"
    path.write_text("{ broken")
    assert daemon.main(str(path)) == 1
    assert path.read_text() == "{ broken" and not list(tmp_path.glob("*.bak"))
    assert "not changed" in capsys.readouterr().err
