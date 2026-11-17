# Agent ↔ CCC protocol (v1)

All agent traffic is **outbound** from the PC to the CCC on TCP 8443 (nginx, TLS 1.3). No port is
opened on student PCs. Source of truth for field names: `agent/core/include/xg/protocol.hpp`,
`agent/core/include/xg/event.hpp`, `server/app/Services/EventIngestor.php`.

## Discovery (UDP 47474, optional)
Agent broadcasts `{"probe":"XEPHYGUARD_DISCOVER","v":1}`; the CCC answers
`{"service":"xephyguard-ccc","host":"192.168.10.2","api_port":8443,"ca_fingerprint":"<sha256>","lab":"Lab 3"}`.
The reply is unauthenticated, so the agent uses it only for `host`/`api_port`. It never trusts the reply's
`ca_fingerprint`: the CA is pinned from `--ca-fingerprint` (installers, Add-a-PC page) or, only when the admin
passes `--trust-on-first-use`, from the first download. Every later TLS connection is verified against that CA.

## Enrollment ("approve, don't configure")
| Step | Request | Auth |
|---|---|---|
| 1 | `GET http://<ccc>/ca.crt` (only if the CA is not installed yet; fingerprint must match) | none |
| 2 | `POST /api/agent/v1/enroll` `{enroll_key, hostname, os, os_version, macs[], agent_version, csr_pem}` → `201 {enrollment_id, poll_token, status:"pending"}` | lab key (rotatable), rate-limited |
| 3 | `GET /api/agent/v1/enroll/{id}?poll_token=…` → `pending` \| `approved {pc_id, name, token, cert_pem, ca_pem}` \| `rejected` \| `collected` | poll token |

The CSR key is EC P-256, generated on the PC (private key 0600, never leaves the PC). The CCC signs a
client certificate (`extendedKeyUsage=clientAuth`, 825 days) and issues a 64-character bearer token
(stored hashed). Token and certificate are handed out **once**. Re-enrolling a PC with a known MAC
keeps its history and revokes the old credentials.

## Authenticated requests
Every request after enrollment carries the client certificate (verified by nginx against the lab CA)
**and** `Authorization: Bearer <token>`. Laravel checks that the certificate fingerprint equals the
one issued with that token (`AuthenticateAgent`). Per-agent rate limit: 120 requests/min.

### `GET /api/agent/v1/policy`
```json
{ "policy": { "version": 509072055, "mode": "test", "session_id": 12, "profile": "Test: AI blocked",
              "title_capture": "app_only", "collect": {"window": true, "...": true},
              "intervals": {"heartbeat_s": 5, "...": 0}, "actions": {"default": {}, "rules": {"proc.ollama": ["log","warn","kill","alert"]}},
              "disabled_rules": [], "work_dirs": ["~/lab"], "signatures_version": "2026.11.01-…", "notice_text": "…" },
  "signatures": { "version": "…", "bundle": "<canonical JSON text>", "signature": "<base64 ECDSA-SHA256 by the CA key>" },
  "realtime": { "app_key": "…", "port": 8443, "channel": "private-pc.12", "auth_path": "/api/agent/v1/broadcasting/auth" } }
```
`policy.version` is a deterministic CRC of the policy. Agents refuse signature bundles whose signature
does not verify against the lab CA and report a `tamper/signature_invalid` event.

`policy.screen.privacy_rules` (optional, at most 128 entries) lists windows the live screen view must never show:
`[{"process": "keepassxc", "title_regex": "bank|incognito"}]`. A window matches an entry when every field that is set
matches (`process` = executable name, case-insensitive; `title_regex` = case-insensitive regex search over the first
512 bytes of the title); an entry needs at least one field, strings are at most 256 bytes. A malformed list rejects
the whole policy. The service passes the list to the helper in `config` as `screen.privacy_rules`; the helper keeps
the focused window in memory only to decide the mask and never sends it for this purpose. While the focused window is
unknown, a rule does not compile, or the list is malformed, the helper masks the screen (a `MASKED` placeholder
frame, no pixels). The server reads the list from `data/screen/privacy_rules.yaml` (`rules:` entries with `process`/`title_regex`),
drops entries that would make the agent reject the policy (bad type, over 256 bytes, no field, invalid regex), keeps at most
128, and omits `privacy_rules` when the list is empty or unreadable (and `screen` when nothing else is in it).

`policy.screen.codec` (`"jpeg"` | `"webp"`, default `jpeg`), `policy.screen.quality` (integer 10..100, default 85) and
`policy.screen.webp_method` (integer 0..6, default 1; WebP only) set how screen tiles are encoded (cost only, not what is
shown; measured in docs/EVALUATION.md M4-5). All optional; a missing or invalid value keeps the default and never rejects
the policy. The service passes them to the helper in `config.screen`; a view in progress keeps its settings. The server
does not send them yet (agent defaults apply).
`policy.screen.cpu_budget_pct` (number 1..100, default 8, optional, invalid keeps the default) is the CPU budget of the
helper's capture/encode thread in percent of one core; the governor lowers fps (floor 2) then quality to stay under it.
Passed in `config.screen` like the above, applied at once (also to a running view). The server sends it only after an
admin set it on the Settings page (`Setting` `screen.cpu_budget_pct`, integer 1..100); otherwise the agent default applies.

`policy.network_lock` (`off` | `observe` | `strict`, default `off`, DECISIONS #23) is applied only when
`proxy_mode` is `proxy_only` and the mode is not `always_on`. `observe` drops QUIC (UDP 443) to public
addresses; `strict` drops every public destination except the CCC. If the local rules disappear the agent
re-applies them and reports `tamper/network_lock_removed`.

### `POST /api/agent/v1/events`
```json
{ "v": 1, "pc_id": "12",
  "heartbeat": { "agent_version": "0.1.0", "mode": "test", "user": "alice", "local_time_ms": 1793500000000,
                 "policy_version": 509072055, "signatures_version": "…", "queue_depth": 0, "helpers": 1,
                 "capabilities": {"keys": true, "...": true}, "usage": {"cpu_pct": 0.4, "rss_kb": 14744, "bytes_up": 17385} },
  "events": [ { "seq": 1041, "ts": 1793500000123, "type": "rule_hit", "data": { "...": "..." } } ] }
```
Response: `{ack_seq, server_time_ms, policy_version, signatures_version, isolated}`.

* Max 500 events / 1 MB per batch, 64 kB per event; malformed batches are rejected with 422.
* `seq` is monotonic per installation and survives restarts and acknowledgements (SQLite queue).
  The CCC ignores `seq <= agents.last_seq` and has a unique `(agent_id, seq)` index, so a batch
  re-sent after a lost acknowledgement is harmless.
* Clock: the CCC corrects event times by `server_now - local_time_ms` (the CCC is the time authority)
  and the agent computes its own offset from `server_time_ms` (reported in heartbeats).
* A changed `policy_version`/`signatures_version` in the ack makes the agent re-fetch the policy.
* `heartbeat.core_dropped` (diagnostic counter, no personal data): internal messages the agent core dropped
  because its bounded mailbox was full (DECISIONS #22). Non-zero means some local observations may be missing.
* `heartbeat.network_lock`: the session network lock that is really installed on the PC (`off` / `observe` /
  `strict`). It differs from the session setting while the rules cannot be applied.

### Event types
| type | data (numbers and names only — never typed text, clipboard text or screen content) |
|---|---|
| `heartbeat` | carried in the batch envelope (see above), every 5 s (15 s in Always-on) |
| `agent_started` | `version, previous_exit (clean\|unclean), os, hostname` |
| `agent_stopping` | `reason, uptime_s` (clean shutdown announcement) |
| `process_start` / `process_stop` | `pid, ppid, exe, user, rss_mb, rule_id` — only for processes matching signatures; no command lines |
| `process_snapshot` | `hash, count, added[], removed[]` (executable names), `list[]` (`pid, ppid, exe, name, user, rss_mb, cpu_pct, net_kbps, net_conns, start, rule_id`; `start` = OS start tick that identifies the process together with `pid`) |
| `rule_hit` | `rule_id, severity, category, description, subject, actions[], result, context, mode, session_id, user`. Tunnel flags (`category: tunnel`, rule id from `web.tunnel`, sessions only): context `process, pid, remote_ip, remote_port, signal: tcp_destination`, never closed by the agent |
| `listening_port` | `port, address, process, pid, rule_id, probed` |
| `window_focus` | `app, title` (title filtered by policy: off / app_only / full) |
| `paste` / `copy` | `chars, lines, code, score, src, dst, user` |
| `key_stats` | per 5 s window: `keys, backspaces, iki_mean/median/p90/std, bursts, max_pause, paste_chords` |
| `net_adapter` | `change, name, driver, description, mac, addresses[], up, wireless, virtual, default_route, kind` |
| `device` | `action, subsystem, class, vendor, product, model, serial_hash` |
| `extension_scan` | `count, hash, ai[], added[], removed[]` |
| `artifact_scan` | `count, files_visited, truncated, found[{path, size_mb, rule_id}]` |
| `file_activity` | per work folder / 10 s: `saves, created, deleted, bytes_delta, total_bytes, exts[]` |
| `gpu_sample` | `util_pct, mem_used_mb, mem_total_mb` (only spikes) |
| `tamper` | `kind` ∈ binary_hash_mismatch, binary_changed, helper_binary_missing, config_changed, ca_removed, ca_changed, clock_change, helper_missing, signature_invalid, isolation_rule_removed, network_lock_removed |
| `helper_status` | `connected, user, session, caps` |
| `command_result` | `command_id, status, detail` |

### Actions (policy per mode)
`log` (always) → `warn` (notice on the PC) → `kill` (opt-in per rule) → `alert` (CCC raises an alert) →
`isolate` (CCC moves the PC to the isolated nftables set). Default Test mode: log + warn + alert.

## Commands (CCC → agent)
Reverb (Pusher protocol 7) over `wss://<ccc>:8443/app/<key>`, mTLS required. The agent subscribes to
`private-pc.<id>`; the subscription is signed by `POST /api/agent/v1/broadcasting/auth`
(`{socket_id, channel_name}` → `{auth: "<key>:<hmac-sha256(secret, socket_id:channel)>"}`), which only
signs the agent's own channel. Event name `command`, data `{id, type, args}`:

| type | args | effect |
|---|---|---|
| `policy_updated` | – | re-fetch policy/signatures now (mode switch, override, publish) |
| `message` | `text, title?, urgent?` | notification in the user session |
| `kill` | `pid` (+ optional `start_time` from `process_snapshot.list[].start`) or `exe` | terminate (exempt system processes are never killed); with `start_time` only that exact process, never a reused pid |
| `isolate_notice` | `isolated` | tell the student network access was paused/restored |
| `rescan` | `what` ∈ extensions, artifacts, processes, all | immediate scan |
| `ping`, `flush` | – | flush the queue now |
| `screen_lease` | `ttl_s` (1..120) | the CCC has a live-view lease on this PC for `ttl_s` more seconds; sent with every screen token and every renewal. The agent captures the screen only while a lease is active (screen Step 15) |

Every command is acknowledged with a `command_result` event.

## Screen relay (agent → CCC)
`wss://<ccc>:8443/screen-gw/agent`, mTLS required (403 without a verified client cert). Opened by the
root service only (DECISIONS #24); frames are the screen protocol in `xephyguard-screen/core/protocol.h`.
nginx drops any client-sent `X-Agent-Cert-Fingerprint` / `X-Agent-Token` and passes `X-SSL-Client-Verify`
and `X-SSL-Client-Cert` (URL-escaped PEM) to the gateway on 127.0.0.1:8082, which takes the agent identity
as the SHA-256 of that certificate (same value as `agents.cert_fingerprint`); it accepts no other agent
credential (no shared token, `X-Agent-Token` / `agent_token` are ignored). The policy response has no `screen`
object (no gateway address or token; the agent uses this fixed URL). The dashboard port 443
never forwards these headers and serves only `/screen-gw/view` and `/screen-gw/health` (agent path 404). The gateway binds the connection to the PC of that certificate (internal lookup below):
`?stream_id` naming another PC is refused with 403, and frames whose header `stream_id` is not that PC are
dropped; an unenrolled or revoked certificate gets 401. The service opens it (`?stream_id=<pc_id>`, numeric only) while a helper of the
active session streams over IPC (`screen_caps.ipc_stream`), relays helper frames up unchanged (queue capped at
8 MiB, excess dropped) and gateway messages down as `screen_rx`; reconnect backoff 1 s doubling to 30 s.
Messages from the gateway are capped at 64 KiB per WebSocket message (fragments included) and 1 KiB per relayed message.

## Screen view lease (dashboard → gateway)
`POST /api/screen/pc/{pc}/token`, `POST /api/screen/{student}/token` and `POST /api/screen/{audit}/renew` return an
HS256 JWT (30 s) with `iss`, `aud`, `sub` (user who opened the view, kept on renewal), `audit_id`, `pc_id`, `stream_id`, `student_id`, `lab_session_id`, `mode`,
`iat`, `nbf`, `exp`, `jti`. `stream_id` is always the PC's id (the stream the agent opens) and is set by the server;
a client-sent `stream_id` is ignored. A renewed token keeps the audit's `pc_id`; an audit without one is not renewed.
The gateway rejects (401) a token without `exp`, with a zero `stream_id` or `pc_id`, with `pc_id != stream_id`, or
with a `mode` other than `live`, `snapshot`, `wall` (no `student_id` fallback). A `snapshot` viewer gets one keyframe,
then the gateway closes the socket (1000 "snapshot delivered").
The socket closes at the lease `exp` (4001 "lease expired") unless the viewer renews in band: it sends the text
message `{"type":"renew","token":"<jwt from /renew>"}` (≤ 4 KiB); the new token must be valid, unused and grant the same
`stream_id`, `pc_id` and `mode`; the gateway extends the lease and answers `{"type":"lease","expires_at":<unix>}`.
Any other text message, or a refused renewal, closes the socket (1008). Binary viewer messages reach the agent only
if they are exactly 28 bytes with the screen magic and version and type `Ack` (3) or `KeyframeReq` (4); the gateway
sets their `stream_id` to the viewer's stream and drops everything else. A viewer message over 4 KiB closes the socket (1009).
A browser `Origin` must be the request host (nginx forwards the dashboard `Host`) or match `-allowed-origins`
(`SCREEN_GATEWAY_ALLOWED_ORIGINS`, comma-separated `host[:port]` patterns), else the upgrade gets 403.
The gateway keeps the agent's last keyframe for at most 5 s and replays a copy to a new viewer with frame flag
`CACHED` (64, `core/protocol.h`; never sent by agents). Any frame flagged `MASKED` (8) or `SECURE` (16) clears the
cache, and such keyframes are never cached. The renewal must also keep `sub` and `audit_id`.

Gateway → agent `Status` (type 5, 28-byte header, sent whenever the viewer set changes and before the `KeyframeReq`
that a new viewer triggers): `flags` and `width` = number of viewers (0 = nobody watches, stop capturing), and the
reserved header field at bytes 26-27 (u16 LE) = the view mode the agent must serve: `0` none/not stated, `1` live,
`2` snapshot, `3` wall. With several viewers the most demanding mode wins (live > snapshot > wall). A viewer count above
0 with mode `0` means live. Agents that do not read the field behave as before.

Wall mode (agent → viewer): one 320 px wide keyframe thumbnail per period (5 s), sent only when the downscaled
image changed. Otherwise the agent sends an "unchanged" Frame: the 28-byte header alone, `flags` 0, no tiles,
`seq` = `base_seq` = the last thumbnail's `seq`. Viewers draw nothing for it; the gateway forwards it and does not cache it.
A `KeyframeReq`, a lifted mask, a secure-desktop pause or a reconnect makes the next thumbnail a full one.

Pauses (agent → viewer): a `MASKED` (8) or `SECURE` (16) placeholder frame (header only) is sent once when the pause
begins and again for each `KeyframeReq` during it; nothing else is sent until it ends. `SECURE` covers the Windows
secure desktop (lock screen, UAC) and, on X11, a blanked display (DPMS standby/suspend/off; not checked more than 4 times/s).

Server → gateway revoke (CCC-internal, loopback only, never proxied by nginx): `POST http://127.0.0.1:8082/internal/revoke`
with `Authorization: Bearer $XG_INTERNAL_TOKEN` and JSON `{"audit_id":N}`, `{"user_id":N}` and/or `{"lab_session_id":N}`
(any non-zero field matches the lease's `audit_id`, `sub`, `lab_session_id`). Matching viewers are closed (4003 "lease
revoked") and tokens issued at or before the revoke are refused on connect and renewal for 1 h. Answer `{"closed":N}`.
The server calls it (best effort, 2 s timeout, `SCREEN_GATEWAY_INTERNAL_URL`, default `http://127.0.0.1:8082`) on view stop
(`audit_id`), logout and on deactivating or demoting a user below instructor (`user_id`), and on session end (`lab_session_id`).

Gateway → server (CCC-internal, loopback): `GET /api/internal/screen/agent/{sha256 fingerprint}` with
`Authorization: Bearer $XG_INTERNAL_TOKEN` returns `{"pc_id": N}` for an enrolled, unrevoked agent on a
non-retired PC, else 404. The gateway uses it to bind an agent connection to stream `pc_id`.

## Helper ↔ service IPC
JSON lines over `/run/xephyguard/helper.sock` (Linux, peer checked with `SO_PEERCRED` + `/proc/<pid>/exe`)
or `\\.\pipe\XephyGuardHelper` (Windows, client image path + session id checked). See
`agent/core/include/xg/ipc_messages.hpp`.

Helper → service also carries binary **screen frame** records (`agent/core/include/xg/ipc_framing.hpp`,
DECISIONS #24): `0x00`, type `0x01`, payload length (4 bytes, big-endian, 1 .. 4 MiB), payload = one encoded
screen-protocol message. A JSON line never starts with `0x00`. The service checks type and length only, never
decodes the payload, and closes the connection on an unknown type, an empty or an oversize record. Records are
accepted only on connections that passed the helper peer check above, and relayed only from the helper the
service chose as source: one that sent `{"t":"screen_caps",...,"ipc_stream":true}` from the active session.
Service → helper: `{"t":"screen_rx","data":"<base64 gateway message>"}`, and `{"t":"screen_lease","ttl_s":N}`
(1..120) while the CCC holds a live-view lease (CCC command `screen_lease`, granted with every screen token and renewal;
the service sends it to the source helper on each grant and when a helper becomes the source). Without a lease the
service drops helper frames and sends no `screen_rx`; it keeps the newest gateway Status/KeyframeReq seen for 10 s
and replays it once when a lease arrives (the viewer's request can beat the command). The helper starts capturing
only inside a lease, stops by itself when `ttl_s` lapses or the service link drops, and a gateway request alone never
starts it (screen Step 15).
`screen_rx` data is one gateway message. The helper's `config` carries only
`screen.enabled`, `screen.privacy_rules` (mask rules, see the policy section) and `screen.codec`/`quality`/`webp_method`/`cpu_budget_pct`: no gateway address, port or token reaches the student session (screen Step 61); the helper opens
no network connection for the screen.

## Proxy → CCC (internal)
`POST http://127.0.0.1:8000/api/internal/net-events` with `Authorization: Bearer $XG_INTERNAL_TOKEN`,
`{events:[{client_ip, host, path?, layer: sni|http|path|search-ai, action: blocked|allowed|rewritten, category?, matched?, ts}]}`.
