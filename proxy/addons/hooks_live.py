"""XephyGuard addon: closes live TLS connections whose decision a new policy tightened (I-PROXY-22).

Decisions are made at ClientHello, so a passed-through TLS/H2/WebSocket connection opened before a
session started or before the PC was isolated would otherwise keep working for its lifetime. Every
connection that was passed or inspected is remembered by client id; whenever a new policy loads
(PolicyCache.generation changes, checked every LIVE_CHECK_S) each one is decided again and those
now blocked, or now inspected while passed through, are closed. Nothing is decrypted to do this.
"""
from __future__ import annotations

import asyncio
import logging

from mitmproxy import ctx

from xg_netpolicy.proxy_logic import PolicyCache

log = logging.getLogger("xephyguard")

LIVE_CHECK_S = 2.0


class LiveHooks:
    cache: PolicyCache | None
    live_conns: dict[str, tuple[str | None, str | None, str]]
    live_gen: int
    live_task: asyncio.Task | None

    def running(self) -> None:
        if self.live_task is None:
            self.live_task = asyncio.get_running_loop().create_task(self._watch_live())

    async def _watch_live(self) -> None:
        while True:
            await asyncio.sleep(LIVE_CHECK_S)
            try:
                self.check_live()
            except Exception:
                log.exception("live connection recheck failed")

    def check_live(self) -> list[str]:
        """Closes the live connections a newly loaded policy tightened; returns their client ids."""
        if self.cache is None:
            return []
        self.cache.reload()
        if self.cache.generation == self.live_gen:
            return []
        self.live_gen = self.cache.generation
        ids = self.cache.recheck_live(self.live_conns)
        for cid in ids:
            ip, sni, old = self.live_conns.pop(cid)
            closed = self._close(cid)
            log.info("policy v%s: %s live connection of %s to %s (was %s)", self.cache.state.version,
                     "closed" if closed else "could not close", ip, sni, old)
        return ids

    def _handler(self, cid: str):
        server = ctx.master.addons.get("proxyserver")
        return getattr(server, "connections", {}).get(cid) if server is not None else None

    def _close(self, cid: str) -> bool:
        try:
            handler = self._handler(cid)
            if handler is None:
                return False
            handler.close_connection(handler.client)   # tears down the client and its server side
            return True
        except Exception:
            log.exception("closing live connection %s failed", cid)
            return False

    def stop_live(self) -> None:
        if self.live_task is not None:
            self.live_task.cancel()
            self.live_task = None
