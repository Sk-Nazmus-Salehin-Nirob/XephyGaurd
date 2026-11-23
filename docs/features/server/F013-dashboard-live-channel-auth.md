# F13. Dashboard live channel auth

- **Component:** server
- **Area:** 2. Staff accounts and access
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** dashboard users subscribe to the lab's live channel; nobody but the agent may join a
  PC channel.
- **Trigger:** Reverb private channel `lab.{labId}`; `pc.{pcId}` always denied for users.
- **Code:** `server/routes/channels.php`.
- **Status:** working (`broadcast_auth_only_for_own_channel` covers the agent side). Since S-51 Reverb
  accepts a browser WebSocket only from the `APP_URL` host or a host in `REVERB_ALLOWED_ORIGINS`
  (`App\Support\ReverbOrigins`, `ReverbOriginTest`).
- **Test:** 1. Open the dashboard with dev tools. 2. The WebSocket subscribes to `private-lab.1`.
  3. Open it by a name that is not in `APP_URL`/`REVERB_ALLOWED_ORIGINS`: the socket closes with "Origin not allowed".
