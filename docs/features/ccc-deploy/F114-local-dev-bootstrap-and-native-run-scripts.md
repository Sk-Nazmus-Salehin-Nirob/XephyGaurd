# F114. Local dev bootstrap and native run scripts

- **Component:** ccc-deploy
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** setup scripts for a new teacher server or lab PC (Docker or native, Linux and Windows),
  and daily start/stop/status scripts.
  The Docker stack's screen gateway binds `127.0.0.1:8082` only (`-addr` flag in `docker-compose.local.yml`,
  `SCREEN_GATEWAY_ADDR=127.0.0.1:8082` in a new or re-run `.env.local`); the LAN reaches it only through nginx
  `/screen-gw/` (ccc-deploy Step 2, I-CCC-1). The native no-nginx "direct HTTP" mode still serves it on `:<gateway port>`.
  The status scripts name `https://<ccc>/downloads` (HTTPS only since server S-74; Windows also the direct
  `http://<ip>:<app port>/downloads`), point to `/enroll` for the Linux install command (Linux) or to `/ca.crt` to
  compare (Windows), and print the CA SHA-256 as lower-case hex without colons, the form the install command,
  `/downloads` and `xephyguard-ccc doctor` use.
  `docker-compose.local.yml` gives `.env.local` only to the Laravel containers (with `DB_ROOT_PASSWORD` blanked);
  netpolicy, proxy, discovery and screen-gateway get explicit variables as in production (ccc-deploy Step 11).
  `bootstrap-local.sh` and `setup-server-docker.sh` reach MySQL through `mysql_root`/`mysql_app` (`MYSQL_PWD` from
  the container's env), so no password is on a command line (ccc-deploy Step 12).
  `import-sqlite-to-local.php` (`bootstrap-local.sh --reseed`) imports every table in one transaction with
  `DELETE FROM` instead of `TRUNCATE`; an error or a row-count mismatch rolls it all back and MySQL keeps its data
  (ccc-deploy Step 27, I-CCC-31).
  `install-agent.sh` requires `--cafp` (stops before anything else without it, and on a mismatch), then downloads
  the `.deb` only from `https://<ccc>[:--https-port]/downloads` with `curl --proto =https --cacert` the pinned CA;
  a native CCC without Nginx has no HTTPS, so there `--deb` is needed (server S-74 follow-up).
  `setup-server-docker.sh` refuses a lab name with quotes, `$`, backticks, backslashes or control characters and
  writes it single-quoted into `.env.local`, as install.sh does (ccc-deploy Step 13 follow-up).
- **Code:** `new_setup_scripts/` (`setup-server-docker.sh`, `setup-server-native.sh`,
  `install-agent.sh`, `setup-server.ps1/.bat`, `deploy-agents.ps1`), `start_server/` (`start-server`,
  `stop-server`, `status-server` for Linux and Windows), `ccc-deploy/bootstrap-local.sh`,
  `ccc-deploy/docker-compose.local.yml`, `ccc-deploy/import-sqlite-to-local.php`.
- **Status:** unclear (no tests; syntax-checked only for the `.sh` files).
- **Test:** 1. `start_server/linux/status-server.sh`. 2. It reports which services run.
