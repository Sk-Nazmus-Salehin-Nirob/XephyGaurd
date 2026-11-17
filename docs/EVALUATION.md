# Research and evaluation

All tools live in `eval/` and write into `eval/results/<run>/` (git-ignored).

| Metric (spec §12) | Tool | Output |
|---|---|---|
| Bypass rate per layer and overall, time-to-detect | `eval/harness/redteam.py run` + `table` | `results.csv`, `bypass_table.md/.tex`, `summary.json` |
| Detection sensitivity / specificity, false-positive rate on honest sessions, ROC-AUC | `eval/export/metrics.py detection --labels labels.csv` | `detection.json` |
| Agent CPU / RAM / uplink | `eval/harness/agent_overhead.sh` (on a PC) and `metrics.py overhead` (all PCs) | JSON vs. targets (CPU < 1 %, RSS < 30 MB, < 5 MB/h) |
| Load: 100 PCs, events < 1 s | `eval/simulator/fake_agents.py --n 100` | p50/p95/max ingest latency |
| Google AI Overview still suppressed | `eval/live_checks/google_ai_overview.py` (weekly cron) | exit code |
| Research data export | dashboard *Reports → Research export*, or `python -m xg_analysis export` | pseudonymized CSV/Parquet, consenting students only |
| Results table for the paper | `eval/export/metrics.py table --out eval/results/<run>` | `results_table.md` |

## Red-team run
On the CCC, with a **Test** session active and SSH access to a prepared target PC (standard student
account, agent installed):
```bash
export XG_INTERNAL_TOKEN=$(grep XG_INTERNAL_TOKEN /opt/xephyguard/ccc-deploy/.env | cut -d= -f2)
python3 eval/harness/redteam.py run --target student@192.168.10.21 --scenarios eval/scenarios/linux.yaml --out eval/results/run1
python3 eval/harness/redteam.py record --out eval/results/run1 behavior.phone_hotspot detected   # manual scenarios
python3 eval/harness/redteam.py table --out eval/results/run1
```
Outcome per scenario: **blocked** (the attempt failed on the PC), **detected** (the CCC recorded a
matching alert or blocked network event within `--wait` seconds), **missed** (bypass). Times have
1-second resolution.

*Development smoke run (agent-only scenarios on the build machine, no gateway):* 6/6 agent scenarios
detected in < 1 s; the network scenarios were reported as bypasses, as expected without the gateway.

## Experiment mode
Sessions carry `experiment_condition` (baseline / treatment) and `experiment_group`; they are part of
every research export. Label honest vs. AI-assisted sessions according to the study protocol in a
CSV `session_id,user,label` for `metrics.py detection`.

## Python prototype comparison (optional)
For the overhead section, run an equivalent polling prototype (e.g. psutil-based) next to the agent and
measure both with `agent_overhead.sh` (pass the prototype's PID by editing the `pgrep` line).

## Screen streaming baseline (before any performance step)
Numbers only, no fixes; later steps (docs/plan/screen.md Phases 3a and 3) quote these as "before". Recorded 2026-11-18 (screen Step 22).
Setup: Intel i3-1220P (12 threads), Linux 6.8, **Release** build (`-O3`) of `xephyguard-screen` (an earlier Debug-build run was discarded),
`python3 eval/harness/screen_bench.py --seconds 10 [--profile xvfb]`: streamer pinned to CPU 0 (`taskset -c 0`), real gateway on loopback
(`-dev-insecure`), headless viewer, 1920x1080, one 10 s run per workload. Latency = capture return to viewer receipt through the gateway
(tile diff + encode + relay); it excludes browser decode and paint. The viewer ACKs each frame. Drops = frames sent minus frames received: 0 in every run.
CPU % is the streamer's own share of one core. Native = synthetic capture (full copy per call like the X11 capture). Xvfb = real X11 capture
(SHM + Damage) on Xvfb with software rendering, the CPU-only worst case; a forked painter draws the workload.

| Workload | Profile | fps | kB/s | Latency p50 / p95 ms | CPU % of a core | Wake-ups/s |
|---|---|---|---|---|---|---|
| static | native | 0.1 | 18 | 139 / 139 | 23.1 | 86 |
| static | Xvfb | 0.2 | 22 | 142 / 142 | 21.3 | 138 |
| typing | native | 4.9 | 37 | 2.9 / 4.3 | 4.5 | 100 |
| typing | Xvfb | 4.9 | 25 | 6.2 / 10.9 | 4.6 | 102 |
| scrolling | native | 3.8 | 531 | 130 / 141 | 48.3 | 61 |
| scrolling | Xvfb | 3.6 | 393 | 140 / 157 | 44.7 | 60 |
| window drag | native | 4.8 | 29 | 5.3 / 10.3 | 4.5 | 99 |
| window drag | Xvfb | 0.8 | 20 | 11 / 168 | 20.7 | 127 |
| video-like | native | 3.9 | 1572 | 119 / 133 | 46.0 | 80 |
| video-like | Xvfb | 3.7 | 1454 | 138 / 149 | 43.2 | 77 |

Reading it against the targets (docs/plan/screen.md, not yet met):
- **Smoothness:** 3.6 to 4.9 fps on every moving workload, far below p95 >= 15 fps. The ceiling is the gateway/agent pacing (Step 24), not the CPU: typing and drag use 4.5 % of a core.
- **Static screen:** about 21 to 23 % of a core and 86 to 138 wake-ups/s with nothing changing, against a target of ~0 % and < 2 wake-ups/s. The capture runs a full copy and diff on a timer (Steps 50, 51, 55).
- **Heavy motion (scrolling, video-like):** 43 to 48 % of a core, against the 8 % budget (Steps 52, 54, 26 to 29).
- **Idle (nobody viewing):** 0.0 to 0.1 % CPU. The 10 wake-ups/s in the idle row come from the bench's own stdin poll in `--stdio` mode; plain `xgstreambench --workload idle` shows 0.2/s.
- **Xvfb drag:** 0.8 fps is limited by the painter pushing a full 1080p image to Xvfb, not by the streamer; treat that cell as a bench limit.
- Not measured: integrated-GPU PC, real Windows capture, browser decode and paint lag (use the viewer `?debug=1` overlay), several viewers or PCs at once.
