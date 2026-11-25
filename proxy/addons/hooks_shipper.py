"""XephyGuard addon: options and lifecycle (policy cache + event shipper). Moved from xephyguard_addon.py."""
from __future__ import annotations

from mitmproxy import ctx

from xg_netpolicy.proxy_logic import EventShipper, PolicyCache


class ShipperHooks:
    cache: PolicyCache | None
    events: EventShipper | None

    def load(self, loader) -> None:
        loader.add_option("xg_policy", str, "/var/lib/xephyguard/net/proxy.json", "XephyGuard proxy policy file")
        loader.add_option("xg_events_fallback", str, "/var/log/xephyguard/proxy-events.jsonl", "JSONL fallback")

    def configure(self, updated) -> None:
        if "xg_policy" in updated or self.cache is None:
            self.cache = PolicyCache(ctx.options.xg_policy)
            if self.events is None:
                self.events = EventShipper(self.cache, ctx.options.xg_events_fallback)

    def done(self) -> None:
        if hasattr(self, "stop_live"):
            self.stop_live()
        if self.events:
            self.events.stop()
