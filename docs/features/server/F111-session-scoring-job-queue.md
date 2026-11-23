# F111. Session scoring job (queue)

- **Component:** server
- **Area:** 18. Background jobs
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

**Area context:**

> Run by `php artisan schedule:work` (Docker service `scheduler`) and `queue:work` (service `worker`).
> Defined in `server/routes/console.php`.

**Feature:**

- `S/Jobs/ScoreSession.php`, see [F48](../analysis/F048-session-scoring-v1-rules-v2-isolation-forest.md). Status: working (`ScoreSessionRetryTest`).
- Calls the analysis service with its own `XG_ANALYSIS_TOKEN` (never the internal token). Transient errors
  (unreachable, timeout, 5xx, 429, no JSON) are retried after 30 s, 2 min and 10 min (4 tries, 75 s per
  call, job timeout 85 s < queue `retry_after` 90 s); a refused call (401/404/422, token unset, short or equal
  to `XG_INTERNAL_TOKEN`) fails at once and the session report shows `failed` with the reason (S-54).
