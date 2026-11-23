# F103. Health page

- **Component:** server
- **Area:** 17. Admin: health, settings, audit
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **Trigger:** `GET /health` (+ `/health.html`, `/admin-health.html`). Admin only.
- **Code:** `AdminController::health` (uses `HealthChecks`: the check rows, active PCs and disk numbers).
- **Status:** working (`HealthChecksTest`: same check names, details and fixes as `xephyguard:doctor`).
  Before S-55 the page read keys the checks never sent, so every row was titled "Check" and no fix was shown.
- **Test:** 1. Open `/health`. 2. Each check shows green (ok), amber (warning) or red (error), and a failing one shows its fix.
