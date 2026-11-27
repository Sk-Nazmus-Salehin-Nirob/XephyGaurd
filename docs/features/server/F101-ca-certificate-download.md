# F101. CA certificate download

- **Component:** server
- **Area:** 16. Public pages
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

**Area context:**

> No login needed for any of these.

**Feature:**

- **Trigger:** `GET /ca.crt`.
- **Code:** `PublicController::caCert`.
- **Status:** working. Still served on plain HTTP :80 (a PC needs it before it can check TLS); it is trusted
  only after its SHA-256 matches the fingerprint the operator copied (S-74).
  `GET /interception-ca.crt` serves the proxy's interception CA the same way (404 while there is none; S-75).
- **Test:** see [F3](F003-internal-certificate-authority.md).
