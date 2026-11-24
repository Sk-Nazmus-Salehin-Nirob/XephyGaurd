# F70. Observe allowed AI/IDE traffic ⚠PRIV

- **Component:** proxy (also: server)
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** when AI is allowed, the proxy still records host + path of AI/IDE requests and raises
  alerts.
  Events carry the path without the query string or fragment (`proxy_logic.loggable_path`), so typed search terms are never shipped; this also holds for `log_urls` "allowed" events, whatever `log_urls.query` (`/settings` "Include search terms") says (`allowed_and_observed_events_never_carry_the_query`, `loggable_path_drops_query_and_fragment`).
- **Code:** addon `tls_clienthello`, `request`; `S/Http/Controllers/Internal/NetEventsController.php`.
- **Side effects:** `POST /api/internal/net-events` (internal token from the proxy container's env `XG_INTERNAL_TOKEN`; `proxy.json` no longer holds it, I-PROXY-13) → `net_events`, `alerts`.
- **Status:** working (`tls_clienthello_observes_allowed_ai_and_ide_traffic`,
  `observed_ai_and_ide_net_events_raise_alert_and_surface_in_dashboard`). Logs even when `log_urls`
  is off, and raises high-severity alerts while AI is allowed.
- **Test:** 1. Practice: AI allowed. 2. Open chatgpt.com on a PC. 3. A net event shows in the inspector.
