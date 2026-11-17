# Screen: implementation order (handoff for a fresh chat)

What: the run order for every step in [screen.md](screen.md), with the cross steps from the other plans placed where they must land.
Why: the step list in screen.md is grouped by kind; this file is the order to build it in. Step numbers below are screen.md IDs unless prefixed (`agent-`, `server-`, `ccc-`, `eval-`).
Architecture is fixed by docs/DECISIONS.md #24 (helper captures, root service relays over mTLS) and #25 (retire xgagent). Written 2026-11-17; nothing built or run yet.

## Start a new chat with
> Read CLAUDE.md, docs/DECISIONS.md #24-#25, docs/plan/screen.md and docs/plan/screen-implementation.md. Continue with the first unchecked milestone step in screen-implementation.md. One step per commit; tick the step in screen.md and here when done.

## Rules for each step (from CLAUDE.md and owner memory)
- Branch `improve`. Plain commit messages, no attribution lines. Never commit CLAUDE.md, build/, *.zip.
- One step = one commit, one component, < 300 changed lines, test in the same commit. Moves and logic changes never in one commit.
- Wire change → docs/PROTOCOL.md in the same commit. Security change → docs/THREAT_MODEL.md. New data → docs/ETHICS.md check.
- Run the tests and lint of the touched component; report "not run" or "compile-checked only" honestly (all Windows code is compile-checked only).
- No new dependencies, sudo, Docker stack runs or pushes without asking. [APPROVAL] steps are pre-approved by the owner.
- 8 GB machine: builds in `systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 nice ... -j6`, never bare `-j`, one heavy build at a time.

## Commands
Existing ones are in CLAUDE.md. Screen commands (to be written into docs/DEVELOPMENT.md in M0-1):
- Gateway: `cd xephyguard-screen/gateway && go vet ./... && go test -race ./...`
- Core/capture: `cmake -S xephyguard-screen -B xephyguard-screen/build && systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 nice cmake --build xephyguard-screen/build -j6 && ctest --test-dir xephyguard-screen/build --output-on-failure`
- Viewer: `cd xephyguard-screen && node --test viewer`
- Agent (embedded streamer links xephyguard-screen): the agent command in CLAUDE.md.

## Other plans to correct first (DECISIONS #24 changes them)
Done as part of M0-4, docs only:
- server Step 3 (per-PC agent JWT) → becomes "stop sending `agent_secret` in the policy; the agent needs no screen credential, only the `wss://<ccc>:8443/screen-gw/agent` URL".
- agent Step 10 (helper asks for a stream token) → becomes "helper gets no gateway token at all" (done by screen Step 61).
- agent Step 9 (TLS only) → satisfied by screen Step 60 (the service always uses the mTLS WSS client).

## M0: groundwork (no behaviour change)
- [x] M0-1 Step 17 + commands: `go mod tidy`, document the three screen commands in docs/DEVELOPMENT.md; run all three and record the pass/fail baseline
- [x] M0-2 Step 18: remove tracked `gateway/gateway.exe`, ignore `*.exe`
- [x] M0-3 Step 42: split `gateway/relay.go` into `stream.go`, `agent_handler.go`, `viewer_handler.go` (move only; most later gateway steps touch it)
- [x] M0-4 docs: apply the corrections above to plan/server.md and plan/agent.md

## M1: Phase 0 architecture (order matters: old path keeps working until Step 62)
- [x] M1-1 Step 43: retire xgagent (program + CMake target only), update docs/FEATURES.md F47
- [x] M1-2 ccc-1: screen-gateway on `127.0.0.1:8082` in production compose; nginx `/screen-gw/` is the only public path
- [x] M1-3 ccc nginx: `/screen-gw/agent` verifies the client cert, strips client `X-Agent-Cert-Fingerprint`, passes the verified PEM as `X-SSL-Client-Cert` (owner chose PEM over SHA-1; pairs with M1-4)
- [x] M1-4 Step 1: gateway trusts `X-SSL-Client-Verify`/`X-SSL-Client-Cert` only from `-trusted-proxy` loopback, hashes the PEM to SHA-256, ignores `X-Agent-Cert-Fingerprint`
- [x] M1-5 Step 59 [agent]: helper→service "screen frame" IPC message (opaque, 4 MB cap, peer check), PROTOCOL.md "Helper ↔ service IPC"
- [x] M1-6 Step 60 [agent]: service relays to the gateway over the realtime mTLS WSS client; check fragment handling and size cap there
- [x] M1-7 Step 61 [agent]: helper drops its WinHTTP/WS client and `X-Agent-Token`
- [x] M1-8 Step 62 [screen]: gateway removes `-agent-secret` / `X-Agent-Token`; then nginx 443 `/screen-gw/` stops proxying the agent path (ccc)
- [x] M1-9 server-3 (revised): policy stops sending `agent_secret`; tick agent-9 and agent-10 as covered
- [x] M1-10 [agent]: drop the unused screen port/path/tls/token settings (`agent.toml [screen]`, `XG_SCREEN_PORT/PATH/TLS/TOKEN`, policy `screen.*` reads); keep `screen.enabled`. The relay always uses `:8443/screen-gw/agent`
- [x] M1-11 [server]: policy `screen` object stops sending `port`/`path`/`tls` (unread after M1-10)
- [x] M1-12 [ccc]: install.sh stops generating `SCREEN_GATEWAY_AGENT_SECRET`
- [x] M1-13 [setup scripts]: `start_server/*`, `new_setup_scripts/*` stop generating and passing `SCREEN_GATEWAY_AGENT_SECRET` (Windows .ps1 not run)
- [x] M1-14 [server] [owner approved]: drop the screen-stream `.bat` for the retired xgagent (`PublicController::dynamicScreenStreamBat`)

## M2: Phase 1 security and bugs
- [x] M2-1 server-1, server-2: `stream_id` derived server-side, `pc_id` in every viewer JWT; instructor-only screen routes
- [x] M2-2 Step 3: agent connection bound to its cert's PC stream; mismatching frames dropped
- [x] M2-3 Step 4: `AuthViewer` returns `{stream_id, mode, exp, pc_id}`, no `student_id` fallback, enforce `mode`
- [x] M2-4 Step 5: close viewers at lease expiry; loopback `POST /internal/revoke`
- [x] M2-5 server: call revoke on stop, logout, session end (server plan cross of Step 5)
- [x] M2-6 Step 6: viewer→agent allow-list (`Ack`, `KeyframeReq`, 28 bytes), 4 KB read limit
- [x] M2-7 Step 7: Origin check, remove `InsecureSkipVerify`
- [x] M2-8 Step 8: `HandleAgent` data race (done in M2-2)
- [x] M2-9 Step 9: keyframe cache TTL 5 s, cleared on MASKED/SECURE
- [x] M2-10 Step 10: X11 shm 0600 + `IPC_RMID`
- [x] M2-11 Step 11 [agent]: privacy filter in the embedded streamer, fail-safe mask; ETHICS.md wording (agent side only: policy `screen.privacy_rules` -> helper; the rule list in data/ and the server delivery are M2-11b)
- [x] M2-11b [data/server]: `data/` YAML list of masked windows (password managers, banking, private windows), server sends it as policy `screen.privacy_rules`; PROTOCOL.md already describes the field
- [x] M2-12 Step 12: viewer ordered frame queue
- [x] M2-13 Step 13 → Step 14: gateway sends `mode` in `Status`; streamer honours wall/snapshot/live
- [x] M2-14 Step 15 [agent]: helper starts only on service command with lease expiry (also a server commit: CCC command `screen_lease` sent with every token/renewal)

## M3: Phase 2 measurement (needed before any performance step)
- [x] M3-1 Step 19: CI jobs for Go, viewer, `xgtests`
- [x] M3-2 Step 21: gateway `/metrics`, viewer debug stats overlay
- [x] M3-3 Step 20a: `bench/stream_bench.cpp` (`xgstreambench`): real streamer loop on synthetic 1080p workloads (idle, static, typing, scrolling, drag, video), CPU/wake-ups, pinned-core use via `taskset -c 0`; smoke ctest
- [x] M3-3b1 Step 20b: `xgstreambench --stdio` sends every wire message with its capture time on stdout and takes gateway messages on stdin (one workload per run, row on stderr)
- [x] M3-3b2 Step 20b: `gateway/cmd/screenbench` bridges that to the real gateway (`-dev-insecure`) and a headless viewer (parses, checks tile signatures, ACKs; no pixel decode): latency p50/p95, viewer frames, drops
- [x] M3-3b3 Step 20b: CPU-only profile: the bench against the real X11 capture on Xvfb (software rendering), pinned core
- [x] M3-3c `screenbench` flags `-capture synthetic|x11` and `-cpu N` (taskset on the streamer only), needed by the eval wrapper
- [x] M3-4 eval-10: `eval/harness/screen_bench.py` wrapper
- [x] M3-5 Step 22: baseline numbers into docs/EVALUATION.md
- [x] M3-6 Step 23 / eval-11: screen red-team scenarios

## M4: Phase 3a low power (each step records before/after from the bench)
- [x] M4-1a Step 50 [agent]: `WebSocketClient::receive(timeout, interruptible)` blocks in one poll instead of 50 ms slices (measured 10 wake-ups per 0.5 s idle before, <= 3 after) and `interrupt()` ends it from another thread
- [x] M4-1b Step 50 [agent]: `ScreenRelay` uses it (receive loop, `wait_ms`, `send_loop` wait on the condition variable, `set_source`/shutdown interrupt the link) so a connected idle relay costs no polling
- [x] M4-2a Step 31: X11 capture reads Damage events (rectangles), skips the screen read when none (safety re-read every 1 s), copies only damaged rectangles into a shadow frame with opaque alpha, reports `dirty` rectangles; `ScreenCapture::wait_for_change` / `interrupt_wait` (X11: poll on the X connection + eventfd). Bench x11/Xvfb static: 21 % -> 3.4 % of a core (capture still polled every 20 ms)
- [x] M4-2b Step 51: `agent_state` capture loop blocks in `capture_->wait_for_change(250)` instead of `sleep_for(20 ms)` on NoChange; stop and keyframe requests interrupt the wait; a viewer that needs a picture of a static screen gets it through `request_full()`. Bench static (Xvfb): 21 % / 138 wake-ups/s -> 2.7 % / 7.4
- [x] M4-3a Step 55: wall thumbnail encoded and sent only when the downscaled image changed, else a 28-byte "unchanged" frame (PROTOCOL.md); the wall pause is one condition-variable wait (stop and `KeyframeReq` end it) instead of 50 x 100 ms sleeps
- [x] M4-3b Step 55: static screen nearly free: the 1 s safety re-read compares the screen with the shadow and reports only changed rows (none: NoChange). Bench static (Xvfb, 30 s): 1.2 % / 6.5 wake-ups/s -> 0.9 % / 5.5
- [x] M4-3c Step 55: pause while the display is blanked (X11 DPMS, Xext already linked) or on the secure desktop (Windows lock); the placeholder goes out once per pause plus once per `KeyframeReq` (was every 100 ms), the pause is an interruptible 250 ms wait. DPMS test skips on Xvfb (no DPMS): X11 blank path not run. Linux lock screen detection (logind `LockedHint`) needs D-Bus, a new dependency: owner decision, not done
- [x] M4-4 Step 53 [agent]: idle priority for capture/encode threads: `core/thread_priority` (Linux `SCHED_IDLE`, fallback nice 19 per thread; Windows background mode, fallback below normal) called at the top of the capture loop. Bench typing on a core with a busy loop: 4.8 -> 0.2 fps (yields fully; check against the 2 fps floor in M4-6). Windows branch not compiled locally (no MinGW here), CI MSVC job builds it
- [x] M4-5a Step 54: encoder `webp_method` (advanced WebP API), bench `--codec/--quality/--webp-method`; measured in docs/EVALUATION.md (JPEG 4-6x cheaper than WebP on moving content)
- [x] M4-5b Step 54 [agent]: JPEG q85 default in the helper (was WebP method 4); optional policy `screen.codec`/`quality`/`webp_method` (invalid keeps the default) passed to the helper in `config`, applied from the next view (PROTOCOL.md). Server does not send them yet
- [ ] M4-6 Step 52: CPU governor (budget 8 %, floor 2 fps); server setting + PROTOCOL.md policy field
- [ ] M4-7 Step 56: Windows dirty-rect copy, right adapter, GDI cap 5 fps (compile-checked only)
- [ ] M4-8 Step 57 [agent]: streaming cost in heartbeat; ETHICS.md check
- [ ] M4-9 Step 58: acceptance run (idle < 2 wake-ups/s, live <= 8 % of one core)

## M5: Phase 3 smoothness (stop and re-plan if two steps in a row do not improve the metric)
- [ ] M5-1 Step 24: pacing without the 200 ms floor, byte-based in-flight window
- [ ] M5-2 Step 25: per-viewer catch-up, keyframe requests limited to 1/s
- [ ] M5-3 Step 26 → 27 → 28: v2 rectangles in core (v1 decode kept), viewer draws v2, encoder merges tiles
- [ ] M5-4 Step 29: encoder worker pool, reused codec state, capture/encode overlap
- [ ] M5-5 Step 30: progressive text refinement when the governor has budget
- [ ] M5-6 Step 32: viewer draw path (index loop; OffscreenCanvas only if the bench shows jank)
- [ ] M5-7 Step 33: viewer auto-reconnect with fresh token callback
- [ ] M5-8 Step 34 [agent]: cursor at up to 30 Hz, viewer overlay
- [ ] M5-9 Step 35 → 36: multi-monitor frames and selector; Windows all outputs (compile-checked only)
- [ ] M5-10 Step 37 [server]: dashboard wall uses real `mode=wall` streams; F26 demo stays
- [ ] M5-11 Step 38: re-run bench against targets; decide the H.264 gate (needs owner, new dependency)

## M6: remaining fixes
- [ ] M6-1 Step 39 + ccc-2: gateway loopback default, `-dev-insecure` loopback only; install.sh stops opening :8082
- [ ] M6-2 Step 40: viewer token in the first WebSocket message (server page code cross)
- [ ] M6-3 Step 41: pin libwebp / libjpeg-turbo by commit
- [ ] M6-4 Step 44: timeouts, ping/pong 10 s, "agent offline" status
- [ ] M6-5 Step 45: viewer error reporting and counters
- [ ] M6-6 Step 47: remove idle streams after 60 s
- [ ] M6-7 Step 48: Wayland decision (owner)
- [ ] M6-8 Step 49: dependency version report only

## Needs the owner (do not start alone)
H.264 gate after M5-11 (new dependency) · Wayland path in M6-7 · any full Docker stack run · pushing the branch · real Windows and integrated-GPU benchmark runs.
