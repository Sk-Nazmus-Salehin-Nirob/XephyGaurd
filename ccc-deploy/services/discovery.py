#!/usr/bin/env python3
"""Answers agent auto-discovery broadcasts on UDP 47474.

Request : {"probe":"XEPHYGUARD_DISCOVER","v":1}
Response: {"service":"xephyguard-ccc","host":"192.168.10.2","api_port":8443,"ca_fingerprint":"<sha256 hex>","lab":"Lab 3"}

The reply is unauthenticated; agents therefore pin the CA fingerprint shown on the Add-a-PC page when one
is given (--ca-fingerprint), and every later connection is TLS-verified against that CA.

Any datagram from the LAN is untrusted: anything that is not a JSON object with the probe is ignored, an
unreadable or malformed ca.crt gives an empty fingerprint, and no single datagram can stop the loop (I-CCC-12).

Only the lab is answered (I-CCC-19): sources outside XG_LAB_SUBNET get nothing, the socket is bound to
XG_LAN_IF where the kernel allows it without privileges (SO_BINDTODEVICE, Linux 5.7+), and each source
gets at most BURST replies, then one per 1/RATE seconds. The reply is still larger than the probe; with the
subnet filter and the rate limit that amplification is accepted (it would need a padded probe in the agent).
"""
import hashlib
import ipaddress
import json
import logging
import os
import socket
import ssl
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("xephyguard.discovery")
PORT = int(os.environ.get("XG_DISCOVERY_PORT", "47474"))
CA = os.environ.get("XG_CA_DIR", "/var/lib/xephyguard/ca") + "/ca.crt"


def fingerprint() -> str:
    try:
        with open(CA) as f:
            der = ssl.PEM_cert_to_DER_cert(f.read())
        return hashlib.sha256(der).hexdigest()
    except (OSError, ValueError, UnicodeDecodeError):   # missing, unreadable or not a PEM certificate
        return ""


def reply_for(data: bytes) -> bytes | None:
    """The reply to one datagram, or None when it is not a discovery probe."""
    try:
        req = json.loads(data)
    except ValueError:   # also UnicodeDecodeError
        return None
    if not isinstance(req, dict) or req.get("probe") != "XEPHYGUARD_DISCOVER":
        return None
    reply = {"service": "xephyguard-ccc", "host": os.environ.get("XG_CCC_IP", ""),
             "api_port": int(os.environ.get("XG_AGENT_PORT", "8443")),
             "ca_fingerprint": fingerprint(), "lab": os.environ.get("XG_LAB_NAME", "")}
    return json.dumps(reply).encode()


SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)   # 25 on Linux; the name is missing elsewhere
RATE, BURST, MAX_SOURCES = 0.5, 5, 4096                     # replies per second per source, bucket size


class RateLimiter:
    """Token bucket per source address; the oldest sources are forgotten beyond MAX_SOURCES."""

    def __init__(self, rate: float = RATE, burst: int = BURST, max_sources: int = MAX_SOURCES):
        self.rate, self.burst, self.max_sources = rate, burst, max_sources
        self.buckets: dict[str, tuple[float, float]] = {}   # ip -> (tokens, last time)

    def allow(self, ip: str, now: float) -> bool:
        tokens, last = self.buckets.pop(ip, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - last) * self.rate)
        ok = tokens >= 1.0
        self.buckets[ip] = (tokens - 1.0 if ok else tokens, now)   # re-inserted: most recent last
        while len(self.buckets) > self.max_sources:
            del self.buckets[next(iter(self.buckets))]
        return ok


def lab_network() -> ipaddress.IPv4Network | None:
    """XG_LAB_SUBNET as a network; None (answer every source, with a warning) when unset."""
    raw = os.environ.get("XG_LAB_SUBNET", "").strip()
    if not raw:
        log.warning("XG_LAB_SUBNET unset: answering every source")
        return None
    return ipaddress.IPv4Network(raw, strict=False)   # a bad value stops the service at start


def bind_lab_interface(s: socket.socket) -> None:
    ifname = os.environ.get("XG_LAN_IF", "").strip()
    if not ifname:
        return
    try:
        s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, ifname.encode())
        log.info("discovery bound to interface %s", ifname)
    except OSError as e:   # older kernel or no permission: the subnet filter still applies
        log.warning("cannot bind to interface %s (%s); filtering by source subnet only", ifname, e)


def main() -> None:
    network = lab_network()
    limiter = RateLimiter()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_lab_interface(s)
    s.bind(("0.0.0.0", PORT))   # broadcasts reach only a wildcard bind; XG_LAN_IF and the filter limit it
    log.info("discovery responder on udp/%d", PORT)
    while True:
        try:
            data, addr = s.recvfrom(2048)
            if network is not None and ipaddress.ip_address(addr[0]) not in network:
                continue
            if not limiter.allow(addr[0], time.monotonic()):
                continue
            out = reply_for(data)
            if out is not None:
                s.sendto(out, addr)
                log.info("answered %s", addr[0])
        except Exception:   # keep answering whatever one datagram did; logged with its traceback
            log.exception("discovery: datagram skipped")


if __name__ == "__main__":
    main()
