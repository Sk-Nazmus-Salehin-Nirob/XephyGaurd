# Server: implementation order (bug steps and alternatives merged)

What: one run order for [server.md](server.md). It merges the bug steps (Steps 4-52) with the alternative-architecture table, so that no code is patched first and replaced later.
Why: many bug fixes in server.md would be rewritten when an alternative lands (e.g. Step 12 title default, Step 48 policy cache and Step 49 writer queries all live in the planned PolicyService). Here each such bug is fixed while building the target shape.
IDs: `S-n` = this file. `(was n)` = server.md step. `[O]` = security step, use Opus high. Everything else uses Sonnet high (remind the owner to `/model`).
Owner pre-approved the [APPROVAL] steps and the alternatives (2026-11-17). Written 2026-11-18. Nothing run yet.

## Start a new chat with
> Read CLAUDE.md, docs/DECISIONS.md, docs/plan/server.md and docs/plan/server-implementation.md. Continue with the first unchecked S-step. One step per commit; tick it here and the matching step in server.md.

## Rules for each step
- Same as [screen-implementation.md](screen-implementation.md) "Rules for each step" (branch `improve`, one step = one commit, <300 lines, test in the same commit, moves never mixed with logic).
- Run `cd server && APP_KEY="base64:$(openssl rand -base64 32)" php artisan test` and `./vendor/bin/pint --test <touched files>`.
- `declare(strict_types=1)` on every PHP file a step touches (replaces server.md Step 21. Larastan stays deferred because it is a new dependency).
- Query-budget steps add the failing `DB::listen` count test (or `EXPLAIN`) first, then the fix in the same commit.

## Alternatives: what is adopted
Adopted. The bug steps listed are done inside them:
- **PolicyService** (F5, F32, F33, F104): one resolver, typed privacy settings, a resolved-policy row per `(pc_id, version)`, event invalidation. Absorbs was 11, 12, 22, 27, 42, 48, 49.
- **Ingest schema** (F39, F72, F75): a validator per event type with an allow-list, length limits and a `title_capture` filter. Absorbs was 31, 33, 34.
- **Enrollment** (F14-F17, F19, F99): a one-time per-PC token or a staff click, `machine_uid` required. The CSR flow stays (already used). Absorbs was 8, 9, 10, 25 part.
- **Agent auth** (F20): mTLS only, and the bearer token is bound to the cert fingerprint. Absorbs was 7.
- **Alerts and audit** (F39-F41, F105): `alert_reviews` rows are append-only and the audit log is hash-chained. Absorbs was 29, 32, 37, 38, 47.
- **Retention registry** (F109, F34, F46): one class lists every table and its retention class. Absorbs was 43.
- **ReportModel DTO** (F49-F51): HTML, PDF and CSV are rendered from one model. Absorbs was 41, 50.
- **One research export** (F52, F55, F57): always pseudonymised, server-side only. Absorbs was 13, 51 [CROSS analysis].
- **InspectorQueries + AgentHealthClassifier** (F24, F25, F108). Absorbs was 28, 30, 44.
- **Per-type command validators** in CommandBus (F35, F37). Absorbs was 35.
- F102 is kept, instructor-only, and labelled with the real user name (was 4, 5). F46 is kept, but only inside an audited live view, stored as hash + encrypted blob with a short retention (was 14, 15).
- Demo is only available when `APP_ENV=local` (F23). A shared HealthChecks class serves both Doctor and the health page (F4, F103). There is a separate analysis token with retry (F106, F111).

Adapted: **signatures** (F7, F58-F61, F110). DB editing stays (F60). Publish and activate become one transaction (was 39). `importSeed` keeps edits (was 40). YAML-as-source is not adopted because it would remove dashboard editing.

Deferred (not scheduled, ask again later):
- offline root + intermediate CA and a separate interception CA (F3, DECISIONS #11, cross proxy)
- immutable profile versions (F27-F31)
- command outbox ack/expiry (needs agent + PROTOCOL)
- roster preview UI
- 2FA
- Larastan

## M0: groundwork (no behaviour change)
- [x] S-1 Baseline: run server tests and `pint --test` on the whole tree and record the pass/fail counts here. No code.
  Result (2026-11-18, PHP 8.3.6, Pint 1.32.1, commit ddca73b):
  - `php artisan test`: 128 passed, 0 failed, 859 assertions. That includes 33 tests (301 assertions) in the untracked `tests/Feature/FeatureAdminTest.php` and `FeatureSessionsTest.php`. Committed tests only: 95 passed, 558 assertions.
  - `pint --test`: 53 of 154 tracked PHP files fail. By directory: app/Models 25, app/Console 6, app/Events 4, app/Services 4, app/Http/Controllers/Web 3, app/Http/Controllers/Agent 1, app/Http/Middleware 1, app/Jobs 1, bootstrap 1, database 1, routes 1, tests 5.
  - Gap: S-4 to S-6 cover only 16 of these. app/Models, app/Console, app/Events, app/Http/Controllers/Agent and bootstrap (37 files) are in no Pint step, so S-7 (blocking CI) would fail. They need an extra Pint-only step before S-7.
- [x] S-2 Docs only: DECISIONS #26 PolicyService (effective `title_capture` = the stricter of profile and mode setting, `off` < `app_only` < `full`), #27 ingest schema, #28 enrollment token, #29 append-only alert reviews + audit chain. FEATURES.md notes for F16, F46, F102.
- [x] S-3 `composer test` / `composer lint` scripts (was 16)
  Done: `test` drops `@no_additional_args` (unsupported by local Composer 2.7.1, so the old script failed) and sets a random `APP_KEY` when unset; `lint` = `pint --test`. `composer test` 128 passed.
- [x] S-4 Pint only: `app/Http/Controllers/Web` (was 17)
  Done: 3 files (Alert, Dashboard, Profile controllers), inline FQCNs became `use` imports. No `strict_types` added (Pint-only steps stay formatting-only). 128 tests pass.
- [ ] S-5 Pint only: `app/Services`, `app/Jobs`, `app/Http/Middleware` (was 18)
- [ ] S-6 Pint only: `routes`, `config`, `database`, `tests` (was 19)
- [ ] S-7 CI pint job blocking (was 20)

Formatting goes first so that every later diff is logic only.

## M1: critical access fixes (small, no new structure)
- [ ] S-8 [O] `/share` routes move into `auth` + `role:instructor`. The label becomes the real user name with no anonymous "Instructor" (was 4, 5).
- [ ] S-9 [O] The setup wizard needs `XG_SETUP_TOKEN` (env) or localhost (was 6) [CROSS ccc-deploy I-CCC-6, same day]
- [ ] S-10 [O] Remove `XG_REQUIRE_MTLS=false`. Always require `X-SSL-Client-Verify=SUCCESS` and a fingerprint match. Fix the tests that rely on the flag (was 7). THREAT_MODEL.md.
- [ ] S-11 [O] The agent bearer token is valid only with the cert fingerprint it was issued to (alternative F20). THREAT_MODEL.md.
- [ ] S-12 [O] Evidence screenshots: instructor+ only, accepted only during an audited screen view, and every `show` is audited (was 14).
- [ ] S-13 [O] Evidence is stored as sha256 + a `Crypt`-encrypted blob (built into Laravel, no new dependency). Its retention entry is added in S-37 (was 15).

## M2: enrollment (was 8, 9, 10, 25 part)
- [ ] S-14 [O] One-time per-PC enrollment token: migration, model, and creation on the authenticated `/enroll` page. `register` with the token auto-approves. With only the lab key, the PC stays pending. PROTOCOL.md [CROSS agent/installers: pass the token].
- [ ] S-15 [O] Public `/downloads` shows only the CA cert and fingerprint-check instructions. The enrollment key is removed from it (was 8; reverses part of e9ded61) [CROSS ccc-deploy I-CCC-2 HTTPS].
- [ ] S-16 [O] Remove MAC auto-approve. Approval comes only from a valid token or a staff click (was 9; changes F16).
- [ ] S-17 [O] An existing PC is adopted only by `machine_uid` or an explicit staff choice. Conflicts are flagged and never merged silently (was 10).
- [ ] S-18 [O] Rotating the key (F17) also invalidates unused tokens.

## M3: PolicyService (was 11, 12, 22, 27, 42, 48, 49)
- [ ] S-19 Move only: rename `PolicyBuilder` to `PolicyService` and update its callers. Behaviour is identical.
- [ ] S-20 [O] Typed `PrivacySettings` with safe defaults (`title_capture` off/app_only). Effective value = the stricter of profile and setting, per DECISIONS #26 (was 12).
- [ ] S-21 [O] Built-in profiles in `Bootstrap` match the ETHICS table (was 11; changes F30).
- [ ] S-22 `switchProfile` / `setOverride` reject non-active sessions (was 42).
- [ ] S-23 The resolved policy is stored per `(pc_id, version)` and invalidated on profile, rule, session, setting and override changes. Query-budget test (was 48).
- [ ] S-24 `NetworkPolicyWriter` reads resolved policies in memory with a fixed query count. Atomic write, mode 0640 (was 22, 49) [CROSS proxy I-PROXY-13].
- [ ] S-25 The notice text is generated from the enabled features (live view, screenshots) and served to the agent (was 27) [CROSS agent Step 38 uses this text].

## M4: ingest schema and commands (was 31, 33, 34, 35)
- [ ] S-26 Docs: PROTOCOL.md documents the `observed` action and the `network/ports/devices` rescan (was 31). The allow-lists below come from this.
- [ ] S-27 Move only: `validate()` and the heartbeat checks move from `EventIngestor` into `Ingest\BatchValidator`.
- [ ] S-28 [O] Per-event-type schema: field allow-list, plus type and length limits for heartbeat strings, `description` and `subject` (was 33, 34 part).
- [ ] S-29 [O] Titles that the effective `title_capture` from PolicyService does not allow are dropped (was 34).
- [ ] S-30 [O] Per-type command validators in CommandBus. `kill` needs `pid` `integer|min:2` and the pid must be in the latest snapshot (was 35).

## M5: alerts, audit, retention (was 29, 32, 37, 38, 43, 47)
- [ ] S-31 New `alert_reviews` table. Acknowledging appends a review row, skips alerts that are already acknowledged, and scopes batch IDs to the lab (was 38).
- [ ] S-32 Index on `alerts.acknowledged_at`, checked with `EXPLAIN` (was 47).
- [ ] S-33 Move only: the unacknowledged-alert count moves into a view composer (was 29).
- [ ] S-34 [O] When `Audit::log` fails, the action fails (was 32).
- [ ] S-35 The audit log records that an exemption changed, not the reason (was 37).
- [ ] S-36 [O] Audit hash chain: a `prev_hash` column plus an `xg:audit-verify` command.
- [ ] S-37 Retention registry: purge covers alerts, scores, commands, screen_view_audits, student_pc_assignments, evidence and messages (was 43).

## M6: reports and export (was 13, 36, 41, 50, 51)
- [ ] S-38 Move only: `ReportController::data` is extracted into `ReportModel`.
- [ ] S-39 HTML, PDF and CSV are all rendered from `ReportModel`, showing score/points as stored, with a not-observable column (was 41).
- [ ] S-40 `Student::forLogin` is resolved once into a map. Query-budget test (was 50).
- [ ] S-41 [O] One research export: pseudonym always, consent filtered in SQL, `lazy()` streaming (was 13, 51) [CROSS analysis "unify export", same day].
- [ ] S-42 `RosterImport` validator: `array_search !== false` and row-length checks (was 36).

## M7: inspector, health, signatures, small bugs (was 28, 30, 39, 40, 44, 45, 46)
- [ ] S-43 Move only: the inspector queries move into `InspectorQueries` (was 28).
- [ ] S-44 `browser_tabs` limited to the session window, and the score refresh moves out of the GET (was 44).
- [ ] S-45 `AgentHealthClassifier` runs in `detectSilent` and its reasons go into the alert details (was 30).
- [ ] S-46 Fix the `ended_at` / `started_at` `diffInSeconds` order (was 45).
- [ ] S-47 Index on `events (pc_id, type, seq)`, checked with `EXPLAIN` (was 46).
- [ ] S-48 [O] Signatures: sign first, then switch the active version in a locked transaction. Same for `activate` (was 39).
- [ ] S-49 `importSeed` inserts only missing rules, and an `edited` flag protects dashboard edits (was 40).
- [ ] S-50 Demo routes only when `APP_ENV=local` (F23).

## M8: config, network, upkeep (was 23, 24, 26, 52)
- [ ] S-51 [O] Reverb `allowed_origins` comes from the dashboard origin in config (was 23).
- [ ] S-52 [O] PAC served over HTTPS, with no `DIRECT` fallback in Test mode (was 24) [CROSS ccc-deploy nginx].
- [ ] S-53 Inspect hosts, Google selectors and port-probe paths move into `data/` YAML and are seeded (was 26) [CROSS data/, proxy I-PROXY-21].
- [ ] S-54 [O] Separate analysis token, and `ScoreSession` retries with backoff (F106, F111) [CROSS analysis I-ANALYSIS-17, ccc-deploy env].
- [ ] S-55 One `HealthChecks` class used by both `Doctor` and the health page (F4, F103).
- [ ] S-56 Caret ranges for dompdf, php-jwt and symfony/yaml matching `composer.lock` (was 52).

## Coverage
Every server.md step 4-52 maps to an S-step above. Steps 1-3 are done. The screen follow-ups (token `mode`, fresh token on reconnect) stay in plan/screen.md.
