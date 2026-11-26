# Adding Linux lab PCs (Ubuntu / Debian)

**One PC:** on the dashboard open **Add a PC**, copy the command (it holds the real CA fingerprint), run it on the PC:
```bash
curl -fsSL -o xg-ca.crt http://192.168.10.2/ca.crt &&   { openssl x509 -in xg-ca.crt -noout -fingerprint -sha256 | cut -d= -f2 | tr -d : | tr A-F a-f | grep -qx <FINGERPRINT> || { echo "CA fingerprint mismatch: stop" >&2; false; }; } &&   curl -fsSL --cacert xg-ca.crt https://192.168.10.2/install/linux.sh | sudo bash -s -- --key XG-XXXXXX-XXXXXX-XXXXXX --ca-fingerprint <FINGERPRINT>
```
It checks the lab CA against the fingerprint you copied before anything runs as root, then fetches the script and
the `.deb` over HTTPS with that CA, installs, enrolls, and waits. Compare the fingerprint with the CCC console
(`sudo xephyguard-ccc doctor`) if you did not open the dashboard over HTTPS.
The PC appears as **Pending** on the dashboard → click **Approve** → name the seat on the seat map.

**Manual:** `sudo apt install ./xephyguard-agent_<ver>_amd64.deb` then
`sudo xephyguard-agent enroll --key <KEY> --ca-fingerprint <sha256> [--ccc 192.168.10.2]` (fingerprint from the
Add-a-PC page; without it enrollment stops unless you pass `--trust-on-first-use` on a network you trust).

**Many PCs:** `installers/ansible` (one inventory file):
```bash
ansible-playbook -i inventory.ini installers/ansible/site.yml \
  -e xephyguard_enroll_key=XG-... -e xephyguard_ca_fingerprint=<sha256>
```
Tip: enable **auto-approve** for the lab's MAC addresses (Add a PC page) before a mass rollout.

## What gets installed
| Path | Purpose |
|---|---|
| `/usr/lib/xephyguard/xephyguard-agent` (root, 0755) | the service, `xephyguard-agent.service` (`Restart=always`, `WatchdogSec=30`) |
| `/usr/lib/xephyguard/xephyguard-helper` | per-session helper (systemd user unit, enabled globally, + XDG autostart) |
| `/etc/xephyguard/agent.toml` (root, 0600) | configuration; edits raise a tamper alert |
| `/etc/xephyguard/manifest.sha256` | expected binary hashes (tamper check) |
| `/var/lib/xephyguard/queue.db` | offline event buffer |
| `/var/log/xephyguard/agent.log` | log |
| system CA store, Chromium NSS, Firefox policy | lab CA trust |
| `/etc/opt/chrome/…`, `/etc/opt/edge/…`, `/etc/firefox/policies/` | managed browser policies (AI features + DoH off) |

## Session type
X11 sessions give full window and clipboard visibility. On **Wayland** the compositor hides other
windows and the clipboard; key timing still works (the root service reads evdev). The dashboard shows
what each PC can and cannot see (detail drawer → "Can see"). For labs, prefer X11 (the Ansible role
sets `WaylandEnable=false` for GDM).

## Lab hardening (recommended)
* Students are standard users without sudo.
* VS Code from a root-owned extensions directory (`--extensions-dir /opt/xephyguard/vscode-extensions`).
* Docker/Podman not available to students (or monitored: `vm.container` rule); no `ollama` package.
* No unmanaged package installs; BIOS password and fixed boot order.

## Check
`sudo xephyguard-agent status` · `systemctl status xephyguard-agent` · `sudo xephyguard-agent scan`
(one-shot local scan that prints what would be flagged).
