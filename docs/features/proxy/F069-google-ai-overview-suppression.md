# F69. Google AI Overview suppression

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** forces Google Search to web results (`udm=14`), strips AI elements with CSS, sets
  browser policies on PCs.
  A hide selector is used only if it passes `proxy_logic.valid_selector` (names, `#id`, `.class`, `[attr op "value"]`, combinators, `:pseudo(...)`; no `{ } ; @ <`, backslash or comment, balanced quotes/brackets, at most 256 characters); any other is left out, so a setting can't inject CSS or close the `<style>` (I-PROXY-26).
  The CSS is injected on a search host or on a `search_css_hosts` entry or its subdomain: `bing.com` covers `bing.com` and `www.bing.com`, not `notbing.com` (I-PROXY-23, `css_hosts_match_entry_or_subdomain_only`).
  The site's CSP is kept: only the injected `<style>`'s own `'sha256-…'` hash is added, to the directive that governs `<style>` elements (`style-src-elem`, else `style-src`, else a new `style-src-elem` copied from `default-src`), in every CSP and CSP-Report-Only header; Google's nonces and hashes stay and no `'unsafe-inline'` is added. The header is unchanged when the style is already allowed (no such directive, plain `'unsafe-inline'`, or the page nonce reused on the style is listed) (I-PROXY-27, `csp_keeps_site_policy_and_adds_only_the_style_hash`, `csp_unchanged_when_style_already_allowed`).
  Only the Google hosts listed exactly in `inspect_hosts` are covered (the seed lists `google.<cc>` and `www.google.<cc>` for com, co.uk, ca, com.au, co.in, de, fr); another country domain must be added on `/settings`. Google sign-in, Gmail and Docs are never decrypted.
- **Code:** addon `request`/`response` (CSS injection, CSP hash for the injected style),
  `proxy_logic.py`; agent browser policy writer ([F91](../agent/F091-browser-policies-and-dns-settings-on-the-pc.md)); setting `google_hide_selectors` (default list in
  `data/network/proxy.yaml`, S-53; the proxy's AI-endpoint signatures, Google search-host regex, `/async/folwr` and `bing.com`, are `google_search_hosts`/`google_ai_paths`/`search_css_hosts` in the same file, read by the proxy from the policy's `google` object, with built-in copies kept equal by a test until the server sends them; proxy Step 14).
- **Status:** working (`google_search_rewrite_sets_udm14_…`, `response_css_injection`,
  `csp_nonce_and_style_relaxation`, `addon_blocks_folwr_and_relaxes_csp`, `css_hosts_match_entry_or_subdomain_only`). `eval/live_checks/google_ai_overview.py` checks it against the live site.
- **Test:** 1. In a session, search Google on a PC. 2. The URL gets `udm=14` and no AI Overview shows.
