# F66. nftables gateway rules

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** forwards lab traffic, redirects HTTP(S) to the proxy, blocks DoH/DoT IPs and VPN ports.
  On the WAN card the CCC accepts only replies to its own connections, ICMP, DHCP replies and SSH (22); the proxy listeners, Unbound, the dashboard and every other host port are lab-side only (`wan_input` chain).
  In `forward`, the drops for test and isolated PCs (both directions) come before `ct state established,related accept`, so a VPN/SSH tunnel opened before a Test session or isolation stops; `xg_netpolicy` also runs `conntrack -D -s <ip>` for PCs that newly joined those sets (all of them when the watcher starts).
- **Code:** `proxy/nftables/xephyguard.nft`, `xg_netpolicy` (`apply_skips_nft_in_proxy_only_or_without_table`, `forward_restricted_drops_come_before_established`, `apply_flushes_conntrack_after_sets`, `watch_flushes_only_newly_restricted_ips`).
- **Status:** partly working (ruleset syntax checked in CI; never run on a real gateway).
- **Test:** 1. On the CCC: `sudo nft list ruleset | grep xephyguard`.
