# F39. Alert creation from events

- **Component:** server
- **Area:** 7. Alerts and review
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** rule hits, tamper events, paste over a size threshold, network events and machine
  silence become alerts, deduplicated.
- **Trigger:** agent `POST /api/agent/v1/events` (batches); proxy `POST /api/internal/net-events`.
- **Code:** `S/Services/EventIngestor.php::ingest`, `refreshLiveScore`; `S/Models/Alert.php`.
- **In/out/side effects:** writes `events`, `alerts`, `key_stats`, `paste_events`, `net_events`;
  updates `pcs` live score; broadcasts `AlertRaised`/`PcUpdated`; deletes older scan snapshots.
  Each event and its alert go to the session running at the event's time (agent clock corrected; for agent events
  only a session with the PC on its roster), not the one active on arrival, so a batch sent after a later session started
  stays in its own session (S-61 net events, S-67 agent events); the live score uses the session active now.
  A `rule_hit` with an `isolate` action that belongs to a session that has ended is filed (event, alert) but does
  not isolate the PC now (S-70); a hit in the running session, or outside any session, isolates as before.
- **Status:** working (`batch_ingest_alerts_dedup_and_ack`,
  `test_mode_extension_and_local_model_rule_hits_create_alerts`).
- **Test:** 1. Start a Test session. 2. Open an AI app on a PC. 3. An alert appears on `/alerts`.
