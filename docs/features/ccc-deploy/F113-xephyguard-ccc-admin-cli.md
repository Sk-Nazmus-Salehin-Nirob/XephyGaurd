# F113. `xephyguard-ccc` admin CLI

- **Component:** ccc-deploy
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** `doctor`, `status`, `logs [svc]`, `enroll-key`, `backup DIR` (DB dump + CA + settings),
  `update` (build, migrate, restart), `artisan …`.
  `doctor` also prints the lab CA SHA-256 fingerprint to compare with the install command (ccc-deploy Step 6).
  `doctor` probes the proxy on `$XG_CCC_IP:8080` (it no longer listens on loopback) and, in proxy_only mode,
  checks that the `inet xephyguard_input` table is loaded (ccc-deploy Step 3).
- **Code:** `ccc-deploy/bin/xephyguard-ccc`.
- **Status:** unclear (only syntax-checked).
- **Test:** 1. `xephyguard-ccc status`. 2. `xephyguard-ccc backup /tmp/xg-backup` and check the files.
