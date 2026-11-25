# F65. DNS sinkhole with per-PC views (Unbound)

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** PCs in a blocking session get NXDOMAIN/sinkhole for blocklisted domains; others resolve
  normally.
- **Trigger:** Docker service `netpolicy`; reads net state.
- **Code:** `proxy/xg_netpolicy/` (`generate.py`, `domains.py`, `state.py`), `proxy/dns/unbound.conf`,
  `ccc-deploy/docker/netpolicy-run.sh`. Unbound remote control listens only on the unix socket
  `/run/xephyguard-unbound/unbound.ctl` inside the netpolicy container (no TCP port, no keys);
  `generate --apply` reloads with `unbound-control -c $XG_UNBOUND_CONF reload`, and deletes the conntrack entries
  of PCs that newly joined test/isolated after the nft sets are loaded (needs the `conntrack` binary; without it a warning is logged).
  The `--watch` loop survives any error in one iteration (invalid document, OSError, failed tool): it logs and counts it and keeps the previous configuration (`watch_survives_*`).
  A group IP or `google.udm14_clients` entry that is not an IPv4 address in `lab_subnet` (IPv6, a second NIC, not a string) is dropped with a warning and the rest of the document is used (`state_skips_bad_group_entries_and_keeps_the_rest`, `watch_applies_document_with_one_bad_ip`); wrong types (a group that is not a list) and a bad `ccc_ip`/`lab_subnet`/interface name still reject it; every other field is type-checked too ([F64](F064-gateway-or-proxy-only-network-mode.md)).
  A new `unbound-xephyguard.conf` is first written as `.check` and run through `unbound-checkconf` (included from a minimal main config without chroot/user); only when it passes does it replace the old file and get reloaded. A rejected config is logged with the checker's message and the old file stays in force (no reload; the nft sets and proxy.json still update). Without `unbound-checkconf` installed the check is skipped with one warning per process (`unbound_config_is_checked_before_it_replaces_the_old_one`, `unbound_check_skipped_with_one_warning_without_binary`).
  The resolver IPs (`doh_ips`) blocked next to the DoH domains are collapsed before they reach nft, and a failed `nft -f` is flagged in `health.json` ([F66](F066-nftables-gateway-rules.md)).
- **Status:** working (`generate_outputs`, `state_groups`, `domain_suffix_matching`,
  `unbound_control_is_unix_socket_only`; `unbound_checkconf_accepts_generated_views` runs `unbound-checkconf` where it is installed, skipped otherwise).
- **Test:** 1. Start a Test session. 2. On the PC `nslookup chatgpt.com <ccc-ip>` is blocked.
