"""XephyGuard addon: TLS ClientHello decisions and upstream connection checks. Moved from xephyguard_addon.py."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket

from mitmproxy import tls
from mitmproxy.proxy import server_hooks

from xg_netpolicy.proxy_logic import EventShipper, PolicyCache, refused_destination

log = logging.getLogger("xephyguard")


class TlsHooks:
    cache: PolicyCache | None
    events: EventShipper | None
    blocked_conns: set[str]

    # ---------------------------------------------------------------- TLS (no decryption needed)
    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        assert self.cache and self.events
        client = data.context.client
        ip = client.peername[0] if client.peername else None
        sni = data.client_hello.sni
        d = self.cache.decide_tls(ip, sni)
        if d.action == "block":
            data.ignore_connection = True          # do not decrypt ...
            self.blocked_conns.add(client.id)      # ... and refuse the upstream connection below
            self.events.emit(client_ip=ip, host=sni or "", layer="sni", action="blocked", category=d.category,
                             matched=d.matched, reason=d.reason)
        elif d.action == "pass":
            data.ignore_connection = True
            if sni:
                ai_match = self.cache.match_ai_domain(sni)
                if ai_match:
                    if self.events.should_emit_observed(ip, ai_match[0]):
                        self.events.emit(client_ip=ip, host=sni, layer="sni", action="observed",
                                         category=ai_match[1], matched=ai_match[0])
                elif self.cache.state.log_urls.get("enabled"):
                    self.events.emit(client_ip=ip, host=sni, layer="sni", action="allowed")
        # "inspect": let mitmproxy intercept with the lab CA

    async def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        if data.client.id in self.blocked_conns:
            data.server.error = "blocked by XephyGuard"
            return
        assert self.cache
        why = await self._refused_upstream(data.server)
        if why:
            data.server.error = f"blocked by XephyGuard: {why}"
            ip = data.client.peername[0] if data.client.peername else None
            log.warning("refused upstream %s for %s: %s", data.server.address, ip, why)

    async def _refused_upstream(self, server) -> str | None:
        """Destination check for every client (I-PROXY-1). Hostnames are resolved here and the
        connection is pinned to the checked address, so a later lookup cannot point elsewhere."""
        if not server.address:
            return "no destination"
        host, port = server.address[0], server.address[1]
        own = (self.cache.state.ccc_ip,)
        if why := refused_destination(host, port, own):
            return why
        try:
            ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
            return None
        except ValueError:
            pass
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            return f"cannot resolve {host}: {e}"
        addrs = [i[4][0] for i in infos]
        for a in addrs:
            if why := refused_destination(a, port, own):
                return f"{host} resolves to {why}"
        if not addrs:
            return f"cannot resolve {host}"
        if server.sni is None:
            server.sni = host
        server.address = (addrs[0], port)
        return None

    def client_disconnected(self, client) -> None:
        self.blocked_conns.discard(client.id)
