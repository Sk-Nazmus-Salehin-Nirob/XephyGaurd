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
- **Trigger:** `sudo ccc-deploy/install.sh`; `docker compose -f ccc-deploy/docker-compose.yml up -d`.
- **Code:** `ccc-deploy/install.sh`, `docker-compose.yml`, `docker/*.Dockerfile`, `nginx/xephyguard.conf`.
- **Status:** partly working (compose config valid; `install.sh` never run on a real two-NIC host).
- **Test:** 1. `docker compose -f ccc-deploy/docker-compose.yml config -q`. 2. On a spare VM, run `install.sh`.
