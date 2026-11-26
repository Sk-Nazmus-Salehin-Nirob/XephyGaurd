# F99. Downloads and install commands ⚠SEC

- **Component:** server
- **Area:** 16. Public pages
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

**Area context:**

> No login needed for any of these.

**Feature:**

- **What:** lists installers in `storage/app/public/downloads` with sizes and ready-to-copy install
  commands with a `<ENROLL_KEY>` placeholder and the CA fingerprint plus check instructions (S-15:
  the key and one-time tokens are only on the authenticated `/enroll` page). The Linux command (built by
  `InstallCommand::linux`, the same one `/enroll` shows) fetches `ca.crt`, stops unless its SHA-256 matches the
  fingerprint shown, then runs the script over HTTPS with that CA and pin (S-74). Files are served on :443 only
  (nginx, ccc-deploy Step 6).
- **Trigger:** `GET /downloads` (+ `.html`), `GET /downloads/{file}` (`.deb .rpm .msi .exe .sha256 .bat`).
- **Code:** `PublicController::downloadsIndex`, `download`; `resources/views/public/downloads.blade.php`;
  `S/Services/InstallCommand.php`.
- **Status:** working (`downloads_layout_handles_guest_no_rail_and_kb_sizes`,
  `downloads_serves_deb_and_generates_pinned_https_linux_installer_command`, `download_allows_bat_scripts`).
- **Test:** 1. Open `https://<ccc>/downloads` logged out. 2. No enrollment key is shown; the Linux command
  contains the fingerprint and `https://…/install/linux.sh`.
