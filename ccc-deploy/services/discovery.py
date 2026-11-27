#!/usr/bin/env python3
"""Answers agent auto-discovery broadcasts on UDP 47474.

Request : {"probe":"XEPHYGUARD_DISCOVER","v":1}
Response: {"service":"xephyguard-ccc","host":"192.168.10.2","api_port":8443,"ca_fingerprint":"<sha256 hex>","lab":"Lab 3"}

The reply is unauthenticated; agents therefore pin the CA fingerprint shown on the Add-a-PC page when one
is given (--ca-fingerprint), and every later connection is TLS-verified against that CA.

Any datagram from the LAN is untrusted: anything that is not a JSON object with the probe is ignored, an
unreadable or malformed ca.crt gives an empty fingerprint, and no single datagram can stop the loop (I-CCC-12).
"""
import hashlib
import json
import logging
import os
import socket
import ssl

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


def main() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))
    log.info("discovery responder on udp/%d", PORT)
    while True:
        try:
            data, addr = s.recvfrom(2048)
            out = reply_for(data)
            if out is not None:
                s.sendto(out, addr)
                log.info("answered %s", addr[0])
        except Exception:   # keep answering whatever one datagram did; logged with its traceback
            log.exception("discovery: datagram skipped")


if __name__ == "__main__":
    main()
