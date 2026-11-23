# F21. Agent channel auth (Reverb)

- **Component:** server
- **Area:** 3. Enrollment and PC management
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** an agent may subscribe only to its own `private-pc.<id>` command channel.
- **Trigger:** `POST /api/agent/v1/broadcasting/auth`.
- **Code:** `S/Http/Controllers/Agent/AgentController.php::broadcastAuth`.
- **Status:** working (`broadcast_auth_only_for_own_channel`). Since S-51 nginx sets
  `Origin: https://xg-agent.invalid` on the mTLS-only `:8443 /app/` path (agents send no `Origin`), and
  Reverb allows that marker; an agent reaching Reverb without nginx is refused.
- **Test:** covered by the test; by hand, request another PC's channel and expect 403.
