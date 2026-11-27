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
- **Code:** `new_setup_scripts/` (`setup-server-docker.sh`, `setup-server-native.sh`,
  `install-agent.sh`, `setup-server.ps1/.bat`, `deploy-agents.ps1`), `start_server/` (`start-server`,
  `stop-server`, `status-server` for Linux and Windows), `ccc-deploy/bootstrap-local.sh`,
  `ccc-deploy/docker-compose.local.yml`, `ccc-deploy/import-sqlite-to-local.php`.
- **Status:** unclear (no tests; syntax-checked only for the `.sh` files).
- **Test:** 1. `start_server/linux/status-server.sh`. 2. It reports which services run.
