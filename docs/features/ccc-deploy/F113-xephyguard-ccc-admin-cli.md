# F113. `xephyguard-ccc` admin CLI

- **Component:** ccc-deploy
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** `doctor`, `status`, `logs [svc]`, `enroll-key`, `backup DIR` (DB dump + CA + settings),
  `update` (build, migrate, restart), `artisan …`.
  `doctor` also prints the lab CA SHA-256 fingerprint to compare with the install command (ccc-deploy Step 6).
  `doctor` probes the proxy on `$XG_CCC_IP:8080` (it no longer listens on loopback) and, in proxy_only mode,
  checks that the `inet xephyguard_input` table is loaded (ccc-deploy Step 3).
  `backup` runs with `set -e` and `umask 077` (directory 0700, files 0600 from creation), checks that
  `mysqldump` exists in the mysql container, and reports "Backup written" only after a dump that passes `gzip -t`
  and ends with mysqldump's `-- Dump completed` line; any failed step prints what failed and exits 1, and a
  failed dump is deleted (ccc-deploy Step 4, I-CCC-5, I-CCC-8). Shellcheck clean (ccc-deploy Step 8).
  `mysqldump` gets the root password as `MYSQL_PWD` inside the mysql container, not as `-p…` (ccc-deploy Step 12).
  It reads `.env` with `xg_env_load` from `$XG_DEPLOY/bin/xg-env.sh` (parsed, never sourced; ccc-deploy Step 13).
  `doctor` takes the network mode from state.json (ccc-deploy Step 14) and checks IP forwarding only in gateway
  mode (ccc-deploy Step 15).
  `update` is `build` then `up -d`: compose runs the one-shot `migrate` service first and starts the app roles only
  if it succeeds (ccc-deploy Step 21).
  `doctor`'s "netpolicy running" now also means the policy watcher runs: the container exits when it does
  (ccc-deploy Step 25).
  The dashboard check verifies TLS with the lab CA (`--cacert`, `--resolve xephyguard-ccc:443:127.0.0.1`, `-f`),
  never `curl -k`; the DoH check passes only on an NXDOMAIN for `dns.google` and fails when the resolver gives no
  answer (ccc-deploy Step 26, I-CCC-22, I-CCC-23).
  `artisan …`, `enroll-key` and doctor's `xephyguard:doctor` run as `www-data` in the web container
  (`docker compose exec -u www-data`), so they never leave root-owned app files (ccc-deploy Step 28, I-CCC-10).
- **Code:** `ccc-deploy/bin/xephyguard-ccc`.
- **Status:** unclear (only syntax-checked).
- **Test:** 1. `xephyguard-ccc status`. 2. `xephyguard-ccc backup /tmp/xg-backup` and check the files.
