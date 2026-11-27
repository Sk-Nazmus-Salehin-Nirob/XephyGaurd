# F14. Agent enrollment request

- **Component:** agent (also: server)
- **Area:** 3. Enrollment and PC management
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** a lab PC asks to join the lab with the enrollment key and a CSR.
- **Trigger:** agent `xephyguard-agent enroll --key <key> [--ccc host] [--ca-fingerprint] [--trust-on-first-use] [--no-wait] [--timeout]`
  → `POST /api/agent/v1/enroll` (30/min), then polls `GET /api/agent/v1/enroll/{enrollment}` (120/min).
- **Code:** agent `A/apps/agent_main.cpp`, `A/core/src/enroll.cpp`; server
  `S/Http/Controllers/Agent/EnrollController.php`, `S/Services/EnrollmentService.php` (`register`, `poll`).
- **In/out/side effects:** writes `enrollments` (hostname, MACs, machine_uid, OS, CSR, IP);
  supersedes older pending requests for the same host. On approval the agent receives its cert,
  token and CA and stores them in its data dir.
  After enrollment the policy response can carry the web proxy's interception CA (`interception_ca`, named by
  `policy.interception_ca_sha256`; server S-75). The agent installs it only when the PEM's SHA-256 matches and it
  is a CA: Linux `/usr/local/share/ca-certificates/xephyguard-interception-ca.crt` + `update-ca-certificates` +
  `install-browser-ca.sh` (NSS), Windows the Local Machine Root store; it keeps a copy as
  `interception-ca.crt` next to `ca_file`, replaces it when the hash changes and removes it when the field goes
  away. The agent's own TLS keeps trusting only the lab CA (agent Step 41).
- **Status:** working (`approve_dont_configure_flow`, `enroll_api_rejects_malformed_machine_uid`).
- **Test:** 1. On a PC: `sudo xephyguard-agent enroll --key <key> --ccc <ip>`. 2. It appears on `/enroll`.
