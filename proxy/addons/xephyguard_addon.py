"""mitmproxy addon implementing XephyGuard's proxy layers.

Run (transparent mode, gateway):
    mitmdump --mode transparent --listen-port 8080 --showhost \
             --set confdir=/var/lib/xephyguard/mitmproxy \
             -s /opt/xephyguard/proxy/addons/xephyguard_addon.py \
             --set xg_policy=/var/lib/xephyguard/net/proxy.json

Behaviour per TLS connection (decided at ClientHello, before any decryption):
  * blocked domain for this client's group  -> connection refused (SNI filter, no decryption)
  * selective-inspection host (e.g. Google search) for a restricted client -> intercepted
  * everything else -> passed through untouched (never decrypted)
"""
from __future__ import annotations

import logging
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, ".."))   # xg_netpolicy
sys.path.insert(0, _here)                       # hooks_*.py (mitmproxy -s and importlib don't add it)
from hooks_http import HttpHooks  # noqa: E402
from hooks_shipper import ShipperHooks  # noqa: E402
from hooks_tls import TlsHooks  # noqa: E402

from xg_netpolicy.proxy_logic import EventShipper, PolicyCache  # noqa: E402

log = logging.getLogger("xephyguard")


class XephyGuard(ShipperHooks, TlsHooks, HttpHooks):
    """The hooks live in hooks_shipper.py (options, lifecycle), hooks_tls.py (ClientHello, upstream
    checks) and hooks_http.py (requests, responses); this class only holds the shared state."""

    def __init__(self) -> None:
        self.cache: PolicyCache | None = None
        self.events: EventShipper | None = None
        self.blocked_conns: set[str] = set()


addons = [XephyGuard()]
