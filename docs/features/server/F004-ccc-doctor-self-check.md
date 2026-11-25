# F4. CCC doctor (self-check)

- **Component:** server (also: ccc-deploy)
- **Area:** 1. CCC setup and operations
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** checks the CCC (DB, CA, signatures, network state file, proxy and DNS ports, gateway firewall sets,
  proxy event delivery, disk, analysis service, job backlog, PCs reporting, agent certificates, PC clocks) and explains problems
  in plain language. "Gateway firewall sets" reads netpolicy's `health.json` next to state.json (`XG_NET_HEALTH`; error while
  `nft -f` fails, with nft's message and since when); "Proxy event delivery" reads the proxy's `proxy-stats.json`
  (`XG_PROXY_STATS`, default `storage/logs/proxy/`, host `/var/log/xephyguard/proxy`; warning when events were lost or refused
  or the counters are older than 5 minutes). Both are read-only, counts only (S-63, `sidecar_health_and_proxy_counters_are_shown`). Reverb and the other containers are checked only by `xephyguard-ccc doctor`.
- **Trigger:** `php artisan xephyguard:doctor [--json]`; `xephyguard-ccc doctor` ([F113](../ccc-deploy/F113-xephyguard-ccc-admin-cli.md)); shown on the
  Health page ([F103](F103-health-page.md)) with the same rows (S-55).
- **Code:** `S/Console/Commands/DoctorCommand.php`, `S/Services/HealthChecks.php::run`.
- **In/out/side effects:** read-only checks; prints a list or JSON (`check`, `ok`, `level`, `detail`,
  `fix`); exit 1 when any row is `error`. A check that throws becomes an `error` row ("Check could not
  run") and the rest still run.
- **Status:** working (`HealthChecksTest`).
- **Test:** 1. `php artisan xephyguard:doctor`. 2. Stop the analysis service and run it again; it should report it.
