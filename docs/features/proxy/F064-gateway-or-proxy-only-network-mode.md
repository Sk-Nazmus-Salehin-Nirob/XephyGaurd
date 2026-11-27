# F64. Gateway or proxy-only network mode

- **Component:** proxy (also: server, ccc-deploy)
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** the CCC is either the lab's router (gateway: DNS + nftables + transparent proxy) or only a
  proxy reached by PAC (proxy_only).
  In both modes mitmproxy (8080/8085) and Unbound (53) listen on `XG_CCC_IP` (Unbound also on 127.0.0.1), never
  `0.0.0.0`, and mitmproxy runs with `block_global=true`, so clients with a public address are refused (a lab on a
  public subnet needs that changed). proxy_only loads `proxy/nftables/xephyguard-proxy-only.nft` (table
  `inet xephyguard_input`): 53/8080/8085 answer only `XG_LAB_SUBNET` and loopback (ccc-deploy Step 3, I-CCC-4).
- **Trigger:** setting `network_mode` ([F104](../server/F104-settings.md)), `XG_NETWORK_MODE`; installer question.
- **Code:** `NetworkPolicyWriter`, `proxy/xg_netpolicy/generate.py`, `ccc-deploy/docker/proxy-entrypoint.sh`.
  The `--watch` loop survives any error in one iteration (invalid document, OSError, failed tool): it logs and counts it and keeps the previous configuration (`watch_survives_*`).
  A group IP or `google.udm14_clients` entry that is not an IPv4 address in `lab_subnet` (IPv6, a second NIC, not a string) is dropped with a warning and the rest of the document is used (`state_skips_bad_group_entries_and_keeps_the_rest`, `watch_applies_document_with_one_bad_ip`); wrong types (a group that is not a list) and a bad `ccc_ip`/`lab_subnet`/interface name still reject it.
  Every field is type-checked (I-PROXY-19): `version`/`proxy_port`/`agent_port` integers (not bool), `ccc_ip`/`lab_subnet`/`lan_if`/`wan_if` strings (an integer IP such as `"lab_subnet": 3232238080` is rejected, it used to be rendered as `3232238080/32`), `events_url`/`events_token` strings or null, `always_block`/`inspect_hosts` lists of strings, `categories`/`path_rules`/`group_categories` objects of string lists (an empty `[]`, which PHP writes for an empty map, reads as `{}`), `groups`/`google`/`log_urls` objects; a wrong type rejects the document. `ccc_ip` and `lab_subnet` are rendered as `ipaddress` prints them; a `doh_ips` entry that is not an IP or network is dropped with a warning (`state_type_checks_every_field`, `state_renders_canonical_addresses_and_reads_php_empty_arrays`).
  Groups are made disjoint (I-PROXY-28): an IP listed in several groups is kept only in the first of exempt, isolated, test, block_ai (**exempt wins**, the order the proxy's `group_of` always used), with a warning and an entry in `skipped`; a repeat within one group is kept once. So Unbound views, the nft sets and the proxy treat that PC the same way (before, exempt + test got the test DNS view and test drops while the proxy let it pass). The server puts each PC in one group, so this only happens when two PC records share an IP (e.g. a stale DHCP address) or the document is edited by hand; then an exempt record also wins over an isolated one (`state_makes_groups_disjoint_exempt_wins`, `gateway_dns_and_proxy_agree_on_an_ip_in_two_groups`).
  The watcher reads the state document once per change and takes the generated files and the applied `network_mode` from that one read (`State.network_mode`); when the document has no or a null `network_mode`, `XG_NETWORK_MODE` decides (`watch_reads_state_once_and_uses_its_network_mode`).
- **Status:** partly working (tests pass; gateway mode never run on a real two-NIC host).
- **Test:** 1. Set proxy_only. 2. `curl --cacert ca.crt https://<ccc>/proxy.pac` returns a PAC pointing at the CCC.
