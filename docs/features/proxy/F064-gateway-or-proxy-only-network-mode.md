# F64. Gateway or proxy-only network mode

- **Component:** proxy (also: server, ccc-deploy)
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** the CCC is either the lab's router (gateway: DNS + nftables + transparent proxy) or only a
  proxy reached by PAC (proxy_only).
- **Trigger:** setting `network_mode` ([F104](../server/F104-settings.md)), `XG_NETWORK_MODE`; installer question.
- **Code:** `NetworkPolicyWriter`, `proxy/xg_netpolicy/generate.py`, `ccc-deploy/docker/proxy-entrypoint.sh`.
  The `--watch` loop survives any error in one iteration (invalid document, OSError, failed tool): it logs and counts it and keeps the previous configuration (`watch_survives_*`).
  A group IP or `google.udm14_clients` entry that is not an IPv4 address in `lab_subnet` (IPv6, a second NIC, not a string) is dropped with a warning and the rest of the document is used (`state_skips_bad_group_entries_and_keeps_the_rest`, `watch_applies_document_with_one_bad_ip`); wrong types (a group that is not a list) and a bad `ccc_ip`/`lab_subnet`/interface name still reject it.
  The watcher reads the state document once per change and takes the generated files and the applied `network_mode` from that one read (`State.network_mode`); when the document has no or a null `network_mode`, `XG_NETWORK_MODE` decides (`watch_reads_state_once_and_uses_its_network_mode`).
- **Status:** partly working (tests pass; gateway mode never run on a real two-NIC host).
- **Test:** 1. Set proxy_only. 2. `curl --cacert ca.crt https://<ccc>/proxy.pac` returns a PAC pointing at the CCC.
