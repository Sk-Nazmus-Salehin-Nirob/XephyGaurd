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
- **Status:** working (`generate_outputs`, `state_groups`, `domain_suffix_matching`,
  `unbound_control_is_unix_socket_only`).
- **Test:** 1. Start a Test session. 2. On the PC `nslookup chatgpt.com <ccc-ip>` is blocked.
