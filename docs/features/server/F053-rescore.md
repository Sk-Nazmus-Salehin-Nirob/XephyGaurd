# F53. Rescore

- **Component:** server
- **Area:** 9. Scoring, reports and research
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **Trigger:** `POST /reports/{session}/rescore`.
- **Code:** `ReportController::rescore` → `ScoreSession` job; audit. The personal baseline reuses the features
  stored with earlier practice sessions' v1 scores; only unscored ones are recomputed (`features.baseline`).
- **Status:** unclear (no test).
- **Test:** 1. Click Rescore. 2. The report's "scored at" time updates.
