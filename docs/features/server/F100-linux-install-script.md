# F100. Linux install script

- **Component:** server (also: installers)
- **Area:** 16. Public pages
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

**Area context:**

> No login needed for any of these.

**Feature:**

- **What:** a shell script that installs the agent and enrolls it. Run only through the command on
  `/downloads` or `/enroll`: `curl --cacert xg-ca.crt https://… | sudo bash -s -- --key K --ca-fingerprint FP`
  after that command checked `ca.crt` against the fingerprint the operator copied (S-74). The script needs
  `--ca-fingerprint` (exit 2 without it), refuses a pin that differs from its CA (exit 3), checks the downloaded
  CA against the pin and fetches the `.deb` over HTTPS with that CA.
- **Trigger:** `GET /install/linux.sh` (nginx :443 only, ccc-deploy Step 6).
- **Code:** `PublicController::linuxInstaller`, `resources/views/public/install-linux.blade.php`.
- **Status:** working (`linux_install_script_needs_the_operator_pin_and_fetches_over_https`; the pin checks
  were run with bash, the full install was not run on a lab PC).
- **Test:** 1. Copy the Linux command from `/enroll` and run it on a PC. 2. Change one character of the
  fingerprint: it stops with "CA fingerprint mismatch".
