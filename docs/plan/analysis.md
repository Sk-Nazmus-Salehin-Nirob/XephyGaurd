# Plan: analysis/ (v1 rules, v2 Isolation Forest, research export, HTTP service)

Sources: [audit/analysis.md](../audit/analysis.md) (I-ANALYSIS-1..26), [features/analysis/](../features/analysis/README.md) (F9, F48; F52/F53 shared with server).
Plan written 2026-11-17. Nothing run while planning.

Rules for every step: one component, <300 changed lines, one kind of change, test in the same step, then
`python3 -m pytest -q analysis/tests` and `ruff check analysis --select E,F,W --ignore E501,E731`.
**[APPROVAL]** = changes a documented feature; **[CROSS]** = another component's plan has the matching step. Every score keeps traceable reasons (invariant).

## Phase 1: Critical/High security and bugs
- [x] Step 1: Characterization tests for `service.py` (token missing/wrong, 404, 422, body size, `/health`) so later fixes are safe (fixes I-ANALYSIS-26; touches F9)
  Done 2026-11-23: 7 handler tests in `tests/test_service.py` drive the real `Handler` through a fake socket (raw HTTP in, raw HTTP out; no port, no thread) against a file SQLite DB set by `XG_DB_URL`. Pinned: 401 for no/wrong/proxy token, checked before the path; 200 + `scores` row for a valid call; 404 for unknown path, unknown session and (today) missing `session_id` (Step 16 → 422); 422 for bad JSON / non-int id / list body; body read only up to 64 KiB; `/health` needs no token, 200 or 503 on a failing ping. Found: when the DB cannot be opened, `Db()` raises before `ping()`, so `/health` drops the connection with no 503 (pinned; for Step 15). No code change. 19 tests pass, ruff clean (scratch venv with pytest 9.2 and ruff 0.17).
- [x] Step 2: Bind to `XG_ANALYSIS_BIND` default `127.0.0.1` (fixes I-ANALYSIS-1; touches F9) [CROSS: ccc-deploy compose sets it explicitly, I-CCC-18]
  Done 2026-11-23: new `service.listen_address()`: `XG_ANALYSIS_BIND` (unset/blank = `127.0.0.1`) and `XG_ANALYSIS_PORT`; `main()` binds it and logs host:port. Safe for every deployment: both compose files run analysis with host networking and the CCC calls `http://127.0.0.1:8090`. 2 tests (default/blank/override; `main()` binds the address, server stubbed). F9 and FEATURES.md env list mention `XG_ANALYSIS_BIND`. Compose not touched: setting it explicitly and fixing the comment is ccc-deploy Step 19. 21 tests pass, ruff clean.
- [x] Step 3: Skip v2 scoring (no stored v2 score) for exempt students (fixes I-ANALYSIS-2; touches F48, F56)
  Done 2026-11-23: `score_session` marks each row's exemption once and runs `score_v2` only over the non-exempt rows, so an exempt student gets no `v2` row and their behaviour no longer shifts the cohort mean/SD or min-max for the others (the ≥ 6 cohort minimum now counts non-exempt students). v1 unchanged (still stored, behaviour reasons dropped). New `test_v2_leaves_exempt_students_out` (7 students + 1 extreme exempt: 7 v2 rows, equal to scoring the 7 alone; fails on the old code). F48/F56 text updated. 22 tests pass, ruff clean.
- [x] Step 4: Duplicate `students.login` no longer raises; ambiguous login is reported as a result with a reason, never a 422 for the whole session (fixes I-ANALYSIS-3; touches F48)
  Done 2026-11-23: new `pipeline._match_student()` returns the student only when exactly one roster row has that login. With several matches the row is still scored (v1, and v2 if not exempt) with `student_id` NULL, a first not-observable line "student identity: OS login … matches N roster students; score not linked to a student", and an entry in the new `ambiguous` list of the `/score` result (the server reads only `scored`/`flagged`, so no server change). If any match is exempt, behaviour is ignored, with a generic text that does not name the student or reason. Confidence unchanged. The student is resolved once per row and reused for v2. 2 new tests (fail on the old code with the pandas ValueError); the Step 1 test now expects `"ambiguous": []`. Seat-first matching is Step 24. 24 tests pass, ruff clean.
- [x] Step 5: Research export pseudonym handling is a server fix (Server Step 13); here only add a test that the CLI export never includes `student_number` (fixes I-ANALYSIS-4 part; touches F52) [CROSS]
  Done 2026-11-18: `test_research_export_never_has_student_number_name_or_login` (CSV and Parquet: no `student_number`/`name`/`login`/`student_id`/`user` column, no such value in any cell). Server part was S-41. Passes on current code. 18 tests pass; ruff not installed locally, not run.

## Phase 2: Tooling
- [x] Step 6: Ruff baseline clean for `analysis/` (no behavior change) (fixes none; touches F9, F48)
  Done 2026-11-23, no code change: the plan/CI gate `ruff check analysis --select E,F,W --ignore E501,E731` was already clean before Steps 1-4 (ruff 0.17.6) and still is. Not adopted: plain `ruff check analysis` on 0.17 uses wider defaults and reports 24 style findings (7 RUF100 unused `noqa`, 3 B023 on the `sel` lambda in `features.compute`, which runs inside its own loop iteration so the hit is a false positive, UP017 `timezone.utc`, I001 import order, C408, RUF059/RUF046, UP034/UP035, C417). CI installs an unpinned ruff but passes the explicit selection, so new default rules cannot break it.
- [x] Step 7: Schema test that `FEATURES` equals the features computed and stored (will fail until Step 20) (fixes none; touches F48)
  Done 2026-11-23: `test_stored_features_are_exactly_FEATURES` (passes: every `scores.features` row has exactly the `FEATURES` keys) and `test_FEATURES_covers_every_computed_and_scored_feature` (scalar `compute()` columns == `FEATURES`; every key `score_v1` reads, recorded through a dict subclass, and `V2_FEATURES` ⊆ `FEATURES`). The second is `xfail(strict=True, raises=AssertionError)`, so the suite stays green and fails only on `net_flags`. Checked: adding `net_flags` to `FEATURES` turns it into a strict XPASS failure, so Step 20 must remove the marker. List-valued `alert_titles`/`categories` are left out (removed in Step 11). 25 passed + 1 xfailed, ruff clean.

## Phase 3: Config and secrets
- [x] Step 8: Separate `XG_ANALYSIS_TOKEN` for the scoring endpoint, not `XG_INTERNAL_TOKEN` (fixes I-ANALYSIS-17; touches F9) [CROSS: server `AnalysisClient`, ccc-deploy env]
  Done 2026-11-23 with server S-54 (same commit): `service.authorized()` accepts only `XG_ANALYSIS_TOKEN`; unset = every `/score` refused (warning at startup). New `tests/test_service.py` (2 tests); pytest/pandas not installed here, so run with the DB and pipeline modules stubbed.
- [x] Step 9: No silent SQLite fallback: missing `XG_DB_URL` is a startup error unless `XG_ALLOW_SQLITE=1` (tests set it) (fixes I-ANALYSIS-23; touches F9)
  Done 2026-11-23: new `db.db_url()`: `XG_DB_URL` (blank counts as unset), else `sqlite:///xephyguard.sqlite` only with `XG_ALLOW_SQLITE=1`, else `RuntimeError`. `Db()` uses it; `service.main()` checks it before binding and exits with the message (checked by hand: `python -m xg_analysis serve` without the env stops at once). An explicit URL, `sqlite://` included, never needs the opt-in, so the tests (which pass their own URL) did not need `XG_ALLOW_SQLITE`. Only the `main()` test now sets `XG_DB_URL`. Compose, RUNNING_THE_SERVER.md and guide_setup.md already set `XG_DB_URL`; F9, FEATURES.md and DEVELOPMENT.md updated. 2 new tests. 27 passed + 1 xfailed, ruff clean.
- [ ] Step 10: IDE/terminal app allow-list and AI category set loaded from `data/` YAML (fixes I-ANALYSIS-21; touches F48) [CROSS: data/]

## Phase 4: Structure (moves only)
No move-only items in the audit.

## Phase 5: Duplication and dead code
- [ ] Step 11: Remove `alert_titles`, `categories`, `BURST_WINDOW_S`, `ScoreResult.features`, unused `sp.student_id`, `source_app`, `target_app` loads (fixes I-ANALYSIS-24; touches F48)
- [ ] Step 12: Use `IDLE_GAP_S` in the reason label (fixes I-ANALYSIS-19; touches F48)
- [x] Step 13: One research export implementation: the CLI calls the same column list and pseudonym rule as the server, or the CLI is removed (decide) (fixes I-ANALYSIS-22; touches F52) [APPROVAL; CROSS: server Step 13]
  Done 2026-11-18: decided **remove** (DECISIONS #30). `export.py` and the `export` subcommand are gone; the server `ResearchExport` (S-41) is the only export. Reason: the CLI had no role check and no audit row, and auditing from Python would duplicate the audit hash chain. Lost: Parquet output (convert the CSV). Test change (needs your OK): the two CLI export tests (incl. Step 5's) are deleted with the code; their checks (consent order, withdrawal, no number/name/login) live in server `ResearchExportTest`. New `test_cli_has_no_research_export`. pyarrow now unused (Step 27). 17 tests pass; ruff not run (not installed).

## Phase 6: Errors, logging, validation
- [ ] Step 14: `ThreadingHTTPServer` handler `timeout`, check token before reading body, negative `Content-Length` rejected (fixes I-ANALYSIS-5, I-ANALYSIS-15; touches F9)
- [ ] Step 15: `/health` reuses one connection (pool) and closes it; rate-limited (fixes I-ANALYSIS-6; touches F9)
- [ ] Step 16: Distinguish `KeyError` for missing `session_id` (422) from internal errors (500) (fixes I-ANALYSIS-14; touches F9)
- [ ] Step 17: 500 responses return a generic message plus an error id; details only in the log (fixes I-ANALYSIS-16; touches F9)
- [ ] Step 18: `load_session` selects only needed student columns, never the real `name` (fixes I-ANALYSIS-20; touches F48) [update ETHICS.md note]

## Phase 7: Medium/Low bugs
- [ ] Step 19: Late large paste is not halved/labelled "early": compare the late paste, not the early total (fixes I-ANALYSIS-8; touches F48)
- [ ] Step 20: Add `net_flags` to `FEATURES` so stored features and export match scored values (fixes I-ANALYSIS-18; touches F48, F52)
- [ ] Step 21: Count a code insertion once in `idle_then_burst` (paste or folder growth, not both); update the "bob" fixture expectation with the reason text (fixes I-ANALYSIS-9; touches F48)
- [ ] Step 22: Include alerts with `user` NULL for the PC when a user filter is applied (fixes I-ANALYSIS-10; touches F48)
- [ ] Step 23: `blocked_attempts` counted per user when several logins share a PC (fixes I-ANALYSIS-12; touches F48)
- [ ] Step 24: Match students by seat assignment `sp.student_id` first, then login; shared/generic logins are flagged (fixes I-ANALYSIS-13; touches F48)
- [ ] Step 25: v2: score relative to a stored cohort baseline (not min-max per session); keep reasons for any score above threshold (fixes I-ANALYSIS-7; touches F48) [APPROVAL: changes scoring behavior]

## Phase 8: Measured performance
- [ ] Step 26: Build a 20-session fixture, time `baseline()` against the 120 s `AnalysisClient` timeout; then cache session features and load the `students` table once (fixes I-ANALYSIS-11; touches F48, F53)

## Phase 9: Dependency updates
- [ ] Step 27: Upper bounds (`<next major`) in `requirements.txt`; hashes only if you approve a lock file (fixes I-ANALYSIS-25; touches F9, F48)

