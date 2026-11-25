# F5. Network state writer

- **Component:** server (also: proxy)
- **Area:** 1. CCC setup and operations
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** regenerates the JSON state the DNS, nftables and proxy containers read (groups, PC
  IPs, blocklists, inspect hosts, proxy mode).
- **Trigger:** `php artisan xephyguard:net:write`; automatically after saving settings, profiles,
  blocklists, retiring a PC, setup.
- **Code:** `S/Console/Commands/NetWrite.php`, `S/Services/NetworkPolicyWriter.php` (`build`, `write`).
- **In/out/side effects:** writes `XG_NET_STATE` (default `storage/app/net/state.json`) atomically
  (unique temp file + rename), mode 0640 (lab IPs and policy; no secret since S-60: `events_token` is no longer written, the proxy reads env `XG_INTERNAL_TOKEN`, `state_json_holds_no_events_token`); the sidecars read it as root.
  All PCs are resolved with a fixed query count (`PolicyService::effectiveMany`, S-24).
  `inspect_hosts` and `google.hide_selectors` come from `data/network/proxy.yaml` unless an admin saved a
  different list on `/settings` (`NetworkSeed`, S-53).
- **Status:** working (`blocklist_edit_hot_reloads_network_state`,
  `always_on_udm14_populates_udm14_clients_and_saving_profile_writes_net_state`, `NetworkPolicyWriterTest`).
- **Test:** 1. `php artisan xephyguard:net:write`. 2. `jq . storage/app/net/state.json | head`.
