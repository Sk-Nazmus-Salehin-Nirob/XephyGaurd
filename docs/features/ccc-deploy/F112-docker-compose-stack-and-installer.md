# F112. Docker Compose stack and installer

- **Component:** ccc-deploy
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** one-command CCC install on Ubuntu: asks for interfaces, mode, IPs; writes `.env`, state
  dirs, CA; starts `mysql`, `web` (nginx + php-fpm, ports 80/443/8443), `reverb`, `worker`,
  `scheduler`, `netpolicy`, `proxy`, `analysis`, `discovery`.
  nginx :80 serves only `/ca.crt`, `/notice` and `/build/`; the install script, `/downloads` and the PAC are
  HTTPS only (redirected to :443, ccc-deploy Step 6, I-CCC-2). The install summary prints the CA fingerprint
  and points lab PCs to the pinned install command on `/enroll` (server S-74).
  The screen gateway listens on `127.0.0.1:8082` only; agents reach it through `wss://<ccc>:8443/screen-gw/agent`
  (mTLS), browsers through `wss://<ccc>/screen-gw/view`. `SCREEN_GATEWAY_URL` stays empty so the viewer URL
  follows the HTTPS dashboard host (ccc-deploy Step 2, I-CCC-1).
  `proxy` and `netpolicy` get `XG_CCC_IP` and listen there only (Unbound also on 127.0.0.1); in proxy_only mode
  install.sh loads the input filter `/etc/nftables.d/xephyguard-proxy-only.nft` (proxy and DNS for the lab subnet
  only) (ccc-deploy Step 3, I-CCC-4).
  `install.sh`, `bootstrap-local.sh` and `docker/*.sh` are shellcheck clean (0.10.0, ccc-deploy Step 8);
  CI's deploy-config job runs `bash -n` and `shellcheck -x` on them and checks both nftables files with
  `nft -c` (ccc-deploy Step 10).
  Only the Laravel containers (`web`, `reverb`, `worker`, `scheduler`) read the whole `.env`, with
  `DB_ROOT_PASSWORD` blanked; every other service lists its own variables (discovery: `XG_CCC_IP`, `XG_LAB_NAME`),
  so no non-app container sees `APP_KEY` or the root password (ccc-deploy Step 11, I-CCC-13).
  No MySQL password is on a command line: the healthcheck and install.sh run `mysqladmin`/`mysql` through the
  mysql container's shell with `MYSQL_PWD` from its own `MYSQL_ROOT_PASSWORD`/`MYSQL_PASSWORD` (ccc-deploy Step 12, I-CCC-20).
  install.sh refuses an answer that is not a plain value (IPv4 address, IPv4/prefix subnet, interface name,
  gateway|proxy_only, a lab name without quotes, `$`, backticks, backslashes or control characters; non-ASCII is
  fine), writes the lab name single-quoted, and reads `.env` with `xg_env_load` (`ccc-deploy/bin/xg-env.sh`), which
  parses KEY=VALUE instead of running the file as shell (ccc-deploy Step 13, I-CCC-21).
  The proxy takes `network_mode` from state.json; `XG_NETWORK_MODE` is only its default (ccc-deploy Step 14, I-CCC-9).
  IP forwarding (`/etc/sysctl.d/60-xephyguard.conf`) is set only in gateway mode; a proxy_only install removes that
  file and leaves the running value alone (ccc-deploy Step 15, I-CCC-29).
  The proxy resolves through Unbound (127.0.0.1) only; a fallback resolver is used only if `XG_DNS_FALLBACK` is
  set in `.env` (ccc-deploy Step 16, I-CCC-28).
  `/etc/docker/daemon.json` is merged by `ccc-deploy/bin/xg-docker-daemon.py`: `iptables`/`ip6tables` false, log
  rotation only if no `log-driver` is set, every other key kept; a backup `daemon.json.xephyguard-<time>.bak` first,
  Docker restarted only if the file changed, invalid JSON stops the install untouched (ccc-deploy Step 17, I-CCC-17).
  `discovery` and `screen-gateway` (both `nobody`) run with `cap_drop: [ALL]`, `no-new-privileges`, a read-only root
  and a `/tmp` tmpfs; `proxy` with `cap_drop: [ALL]` plus `CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID` (root
  entrypoint until gosu) and `no-new-privileges`, not read-only (ccc-deploy Step 18, I-CCC-30).
  `analysis` gets `XG_ANALYSIS_BIND: 127.0.0.1` in both compose files (ccc-deploy Step 19, I-CCC-18).
  Every base image (`docker/*.Dockerfile`, `mysql` in both compose files) is pinned as `name:exact-tag@sha256:…`,
  and the gateway build uses `GOTOOLCHAIN=local` (ccc-deploy Step 20, I-CCC-14; updating them is Step 32).
  Migrations run only in the one-shot `migrate` service (`artisan migrate --force`, `restart: "no"`); web, reverb,
  worker and scheduler start after it completes successfully; the web entrypoint no longer migrates
  (ccc-deploy Step 21, I-CCC-24).
  If MySQL does not answer within about 2 minutes, install.sh (and bootstrap-local.sh) stop with "MySQL did not
  start" and the `logs mysql` command, instead of failing later in migrate (ccc-deploy Step 24, I-CCC-16).
  `netpolicy` exits (and Docker restarts it) when either Unbound or the `--watch --apply` policy watcher exits, so
  "netpolicy running" means both run; SIGTERM stops both with status 0 (ccc-deploy Step 25, I-CCC-11).
  For a partitioned `events` table, `mysql/partition-maintenance.sql` (run once, repeatable) adds the procedure
  `xg_extend_event_partitions(n)` and a monthly MySQL event that keeps partitions three months ahead, so events
  never pile up in `pmax` (ccc-deploy Step 31, I-CCC-27).
  mitmproxy signs with its own interception CA, never the lab root: install.sh runs `bin/xg-interception-ca.sh`
  (self-signed EC P-256, `pathlen:0`, name constraints excluding `XG_CCC_IP`, `xephyguard-ccc` and the host
  name), which writes `/var/lib/xephyguard/mitmproxy/mitmproxy-ca.pem` (0600, uid 1500) and the certificate to
  `/var/lib/xephyguard/ca/interception-ca.crt` for the server to publish; it keeps a valid one and replaces a
  lab-root bundle from an older install, a non-CA, one near expiry or one with other excluded names
  (ccc-deploy Step 7, I-CCC-3, DECISIONS #31).
- **Trigger:** `sudo ccc-deploy/install.sh`; `docker compose -f ccc-deploy/docker-compose.yml up -d`.
- **Code:** `ccc-deploy/install.sh`, `docker-compose.yml`, `docker/*.Dockerfile`, `nginx/xephyguard.conf`.
- **Status:** partly working (compose config valid; `install.sh` never run on a real two-NIC host).
- **Test:** 1. `docker compose -f ccc-deploy/docker-compose.yml config -q`. 2. On a spare VM, run `install.sh`.
