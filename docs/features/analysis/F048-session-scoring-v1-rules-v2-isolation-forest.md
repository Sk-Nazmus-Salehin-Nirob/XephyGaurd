# F48. Session scoring (v1 rules + v2 Isolation Forest)

- **Component:** analysis (also: server)
- **Area:** 9. Scoring, reports and research
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** after a session, each student gets an explainable score with ranked reasons (v1) and an
  anomaly score (v2) as flags for human review. Exempt students get no v2 score and are left out of
  the v2 cohort. An OS login that matches several roster students is still scored, not linked to a
  student, with a not-observable line saying so (behaviour ignored if any match is exempt).
- **Trigger:** session stop → job `ScoreSession`; `POST /reports/{session}/rescore`; CLI
  `python -m xg_analysis score`.
- **Code:** `S/Jobs/ScoreSession.php`, `S/Services/AnalysisClient.php`, `analysis/xg_analysis/scoring.py`, `features.py`;
  IDE/terminal apps and AI alert categories in `data/analysis/scoring.yaml`.
- **In/out/side effects:** HTTP call to the analysis service; writes `scores`, `reports`.
- **Status:** working (`v1_scores_are_explained_and_ranked`, `v2_isolation_forest_alongside_v1`,
  `personal_baseline_z_scores`, `exempt_student_behavior_signals_ignored`, `v2_leaves_exempt_students_out`,
  `duplicate_login_is_scored_unlinked_with_a_reason`).
- **Test:** 1. Run a short Test session with some AI use. 2. Stop it. 3. `/reports` shows scores with reasons.
