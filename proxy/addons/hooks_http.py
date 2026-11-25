"""XephyGuard addon: plaintext HTTP and inspected HTTPS requests/responses. Moved from xephyguard_addon.py."""
from __future__ import annotations

from mitmproxy import http

from xg_netpolicy.proxy_logic import (
    EventShipper,
    PolicyCache,
    block_page,
    extract_nonce,
    google_search_rewrite,
    hide_css_text,
    inject_css,
    loggable_path,
    observed_path,
    relax_style_csp,
)


class HttpHooks:
    cache: PolicyCache | None
    events: EventShipper | None

    # ------------------------------------------------- HTTP and inspected HTTPS requests/responses
    def request(self, flow: http.HTTPFlow) -> None:
        assert self.cache and self.events
        ip = flow.client_conn.peername[0] if flow.client_conn.peername else None
        host = flow.request.pretty_host
        path = flow.request.path
        d = self.cache.decide_http(ip, host, path)
        if d.action == "block":
            flow.response = http.Response.make(403, block_page(host, d.reason), {"Content-Type": "text/html; charset=utf-8"})
            self.events.emit(client_ip=ip, host=host, path=loggable_path(path, 256),
                             layer="http" if flow.request.scheme == "http" else "path", action="blocked",
                             category=d.category, matched=d.matched, reason=d.reason)
            return
        if self.cache.wants_google_rewrite(ip):
            clean_path = path.split("?", 1)[0]
            if self.cache.search_ai.is_ai_path(host, path):   # e.g. Google /async/folwr (data/network/proxy.yaml)
                flow.response = http.Response.make(204, b"", {"Cache-Control": "no-store"})
                self.events.emit(client_ip=ip, host=host, path=clean_path[:256], layer="search-ai",
                                 action="blocked", category="search_ai")
                return
            new_q = google_search_rewrite(host, path, list(flow.request.query.items(multi=True)), self.cache.search_ai)
            if new_q is not None:
                flow.request.query.clear()
                for k, v in new_q:
                    flow.request.query.add(k, v)
                flow.metadata["xg_rewritten"] = True
                self.events.emit(client_ip=ip, host=host, path="/search", layer="search-ai", action="rewritten",
                                 category="search_ai")
        ai_match = self.cache.match_ai_domain(host) or self.cache.match_ai_path(host, path)
        if ai_match and self.cache.records_observed(ip) and self.events.should_emit_observed(ip, ai_match[0]):
            # log_urls on and in a session only; first path segment only (I-PROXY-10)
            self.events.emit(client_ip=ip, host=host, path=observed_path(path),
                             layer="http" if flow.request.scheme == "http" else "path",
                             action="observed", category=ai_match[1], matched=ai_match[0])
        if self.cache.state.log_urls.get("enabled") and not ai_match:
            # host + path only; the query (search terms) is never shipped (an old document's log_urls.query is ignored)
            self.events.emit(client_ip=ip, host=host, path=loggable_path(flow.request.path), layer="http",
                             action="allowed")

    def response(self, flow: http.HTTPFlow) -> None:
        assert self.cache
        ip = flow.client_conn.peername[0] if flow.client_conn.peername else None
        if not self.cache.wants_google_rewrite(ip) or not flow.response:
            return
        ctype = flow.response.headers.get("content-type", "")
        if "text/html" not in ctype:
            return
        selectors = self.cache.state.google.get("hide_selectors", [])
        host = flow.request.pretty_host.lower()
        if selectors and self.cache.search_ai.wants_css(host):
            html = flow.response.get_text(strict=False) or ""
            nonce = extract_nonce(html)
            new = inject_css(html, selectors, nonce=nonce)
            if new:
                flow.response.set_text(new)
                # only the injected style's hash is added; the site's own CSP otherwise stays (I-PROXY-27)
                text = hide_css_text(selectors)
                for hname in ("content-security-policy", "content-security-policy-report-only"):
                    if vals := flow.response.headers.get_all(hname):  # every header is enforced
                        flow.response.headers.set_all(hname, [relax_style_csp(v, text, nonce) for v in vals])
                if flow.metadata.get("xg_rewritten"):
                    flow.response.headers["Cache-Control"] = "no-store, private"
