# F67. SNI blocking without decryption

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** the proxy closes TLS connections to blocked hosts from the ClientHello alone.
- **Code:** `proxy/addons/xephyguard_addon.py::tls_clienthello`; `server_connect` also refuses, for every client and both listeners, upstream ports other than 80/443 and loopback, link-local, unspecified, multicast and CCC (`ccc_ip`) destinations (`proxy_logic.refused_destination`). Hostnames are resolved there and the connection is pinned to the checked address.
- **Status:** working (`tls_clienthello_blocks_without_decryption`, `server_connect_refuses_internal_and_odd_ports`, `server_connect_pins_resolved_name`).
- **Test:** 1. In a Test session, `curl https://chatgpt.com` via the proxy fails at TLS. 2. From any lab PC, `curl -x http://<ccc>:8085 https://127.0.0.1:8953` (gateway mode; 8080 in proxy_only) is refused.
