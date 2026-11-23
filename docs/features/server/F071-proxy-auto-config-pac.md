# F71. Proxy auto-config (PAC)

- **Component:** server (also: agent)
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** PAC file pointing PCs at the CCC proxy, used in proxy_only mode.
- **Trigger:** `GET https://<ccc>/proxy.pac` (public, HTTPS only); pushed to PCs as `proxy_pac_url` (`https://`).
- **Code:** `PublicController::proxyPac`; agent/helper writes it to the OS ([F91](../agent/F091-browser-policies-and-dns-settings-on-the-pc.md));
  the agent ignores a non-HTTPS or foreign-host URL (`trusted_pac_url`).
- **Status:** working (`proxy_pac_reflects_network_mode_and_policy_carries_pac_url`,
  `proxy_pac_has_no_direct_fallback_for_pcs_in_a_test_session`, `proxy_pac_is_refused_over_plain_http_and_linked_as_https`,
  `agent pushes proxy_pac_url to helper in proxy_only mode`). Since S-52 plain HTTP gets 404 (nginx :80 redirects to
  :443); a PC in a Test session or isolated gets no `DIRECT` fallback; other PCs keep `; DIRECT`.
- **Test:** 1. `curl --cacert ca.crt https://<ccc>/proxy.pac`. 2. `curl http://<ccc>/proxy.pac` → 301 to HTTPS.
