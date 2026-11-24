# F69. Google AI Overview suppression

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** forces Google Search to web results (`udm=14`), strips AI elements with CSS, sets
  browser policies on PCs.
  Only the Google hosts listed exactly in `inspect_hosts` are covered (the seed lists `google.<cc>` and `www.google.<cc>` for com, co.uk, ca, com.au, co.in, de, fr); another country domain must be added on `/settings`. Google sign-in, Gmail and Docs are never decrypted.
- **Code:** addon `request`/`response` (CSS injection, CSP nonce relaxation),
  `proxy_logic.py`; agent browser policy writer ([F91](../agent/F091-browser-policies-and-dns-settings-on-the-pc.md)); setting `google_hide_selectors` (default list in
  `data/network/proxy.yaml`, S-53; the proxy's own host/path signatures are proxy plan Step 14).
- **Status:** working (`google_search_rewrite_sets_udm14_…`, `response_css_injection`,
  `csp_nonce_and_style_relaxation`). `eval/live_checks/google_ai_overview.py` checks it against the live site.
- **Test:** 1. In a session, search Google on a PC. 2. The URL gets `udm=14` and no AI Overview shows.
