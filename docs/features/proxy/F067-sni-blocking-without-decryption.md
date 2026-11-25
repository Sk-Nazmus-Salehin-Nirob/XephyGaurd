# F67. SNI blocking without decryption

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** the proxy closes TLS connections to blocked hosts from the ClientHello alone.
  Fail closed (I-PROXY-15): an error inside `tls_clienthello` blocks that connection (not decrypted, upstream refused) instead of leaving it to be intercepted with no policy; until a valid `proxy.json` has loaded once, every connection is blocked (category `no_policy`); a later broken `proxy.json` (bad JSON, wrong types, anything that fails to load) is logged once and the last good policy stays in force (`tls_clienthello_fails_closed_on_error`, `policy_reload_keeps_last_good_on_any_error`, `policy_fails_closed_until_a_valid_policy_loads`).
  The SNI shipped in `blocked`/`observed`/`allowed` events is cleaned and cut to 255 characters like every event host ([F70](F070-observe-allowed-ai-ide-traffic.md)). `blocked` events the CCC could not take are kept in the spill file and replayed after the next successful POST; they are purged at the raw-event retention age (F70, I-PROXY-12). `blocked` SNI events are not de-duplicated; `log_urls` `allowed` SNI events are, once per (client, host) per minute, and dropped events are counted in `proxy-stats.json` (F70, I-PROXY-30).
- **Code:** `proxy/addons/hooks_tls.py::tls_clienthello` (loaded through `xephyguard_addon.py`); `server_connect` also refuses, for every client and both listeners, upstream ports other than 80/443 and loopback, link-local, unspecified, multicast and CCC (`ccc_ip`) destinations (`proxy_logic.refused_destination`). Hostnames are resolved there and the connection is pinned to the checked address.
- **Status:** working (`tls_clienthello_blocks_without_decryption`, `server_connect_refuses_internal_and_odd_ports`, `server_connect_pins_resolved_name`).
- **Test:** 1. In a Test session, `curl https://chatgpt.com` via the proxy fails at TLS. 2. From any lab PC, `curl -x http://<ccc>:8085 https://127.0.0.1:8953` (gateway mode; 8080 in proxy_only) is refused.
