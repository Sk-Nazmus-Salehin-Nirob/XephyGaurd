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
  `install.sh`, `bootstrap-local.sh` and `docker/*.sh` are shellcheck clean (0.10.0, ccc-deploy Step 8).
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
- **Trigger:** `sudo ccc-deploy/install.sh`; `docker compose -f ccc-deploy/docker-compose.yml up -d`.
- **Code:** `ccc-deploy/install.sh`, `docker-compose.yml`, `docker/*.Dockerfile`, `nginx/xephyguard.conf`.
- **Status:** partly working (compose config valid; `install.sh` never run on a real two-NIC host).
- **Test:** 1. `docker compose -f ccc-deploy/docker-compose.yml config -q`. 2. On a spare VM, run `install.sh`.
