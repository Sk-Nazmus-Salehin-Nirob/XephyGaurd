# F70. Observe allowed AI/IDE traffic ⚠PRIV

- **Component:** proxy (also: server)
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** when AI is allowed, the proxy still records host + path of AI/IDE requests and raises
  alerts.
  Events carry the path without the query string or fragment (`proxy_logic.loggable_path`), so typed search terms are never shipped; this also holds for `log_urls` "allowed" events, whatever `log_urls.query` (`/settings` "Include search terms") says (`allowed_and_observed_events_never_carry_the_query`, `loggable_path_drops_query_and_fragment`).
- **Code:** addon `tls_clienthello` (`hooks_tls.py`), `request` (`hooks_http.py`), event shipper set up in `hooks_shipper.py`; `S/Http/Controllers/Internal/NetEventsController.php`.
  The event format (actions `blocked|allowed|rewritten|observed`, which layer sends which) is in [PROTOCOL.md](../../PROTOCOL.md#proxy--ccc-internal); `protocol_lists_every_emitted_action_and_layer` keeps that list, the addon's `emit` calls and `NetEventsController`'s accepted actions equal.
  Before an event is queued, `host` (the client's Host header or SNI) and `path` lose every non-printable character (control characters, mitmproxy's surrogates for undecodable bytes) and are cut to 255 / 512 characters, the CCC's limits, so one crafted Host header can't get a whole 500-event batch rejected (`event_text_drops_non_printable_and_truncates`, `shipper_cleans_host_and_path_before_queueing`, `event_limits_match_net_events_controller`).
- **Side effects:** `POST /api/internal/net-events` (internal token from the proxy container's env `XG_INTERNAL_TOKEN`; `proxy.json` no longer holds it, I-PROXY-13) → `net_events`, `alerts`.
- **Status:** working (`tls_clienthello_observes_allowed_ai_and_ide_traffic`,
  `observed_ai_and_ide_net_events_raise_alert_and_surface_in_dashboard`). Logs even when `log_urls`
  is off, and raises high-severity alerts while AI is allowed.
- **Test:** 1. Practice: AI allowed. 2. Open chatgpt.com on a PC. 3. A net event shows in the inspector.
