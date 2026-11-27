# F3. Internal certificate authority

- **Component:** server
- **Area:** 1. CCC setup and operations
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** creates the lab CA, issues the CCC server certificate (SANs = IPs + DNS names) and
  later signs agent client certificates and signature bundles.
- **Trigger:** `php artisan xephyguard:ca:init [--cn=] [--server-ip=*] [--server-dns=*] [--force]`;
  used automatically by enrollment ([F15](F015-approve-or-reject-enrollments.md)) and publishing ([F61](F061-publish-and-roll-back-signature-bundles.md)).
- **Code:** `S/Console/Commands/CaInit.php`, `S/Services/CertificateAuthority.php`
  (`create`, `issueServerCert`, `signClientCsr`, `signData`, `verifyData`, `fingerprint`).
- **In/out/side effects:** writes the CA key and cert to `XG_CA_DIR` (default
  `storage/app/private/ca`), server cert/key files.
- **Status:** working (used by the enrollment and signature tests). ⚠SEC the same CA key also
  signs bundles and sits in the proxy container (`docs/HISTORY.md`, batch 5).
  The proxy's own interception CA (`XG_CA_DIR/interception-ca.crt`, certificate only, a separate self-signed root
  because the lab CA's `pathlen:0` allows no intermediate) is published when present: `interception_ca_sha256` in
  the agent policy, its PEM as `interception_ca` in the policy response, `GET /interception-ca.crt`, and its
  fingerprint on Downloads; a file that is not a CA certificate counts as none (S-75). The proxy still uses the lab
  CA until ccc-deploy Step 7 creates that file and switches mitmproxy to it.
- **Test:** 1. `php artisan xephyguard:ca:init --server-ip=127.0.0.1`. 2. `curl -s localhost:8000/ca.crt | openssl x509 -noout -subject -fingerprint -sha256`.
