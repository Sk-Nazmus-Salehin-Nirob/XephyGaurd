#!/usr/bin/env bash
# XephyGuard agent installer for Debian/Ubuntu lab PCs, served by the CCC over HTTPS only.
# Copy the full command from the CCC's Downloads or "Add a PC" page: it checks ca.crt against the fingerprint
# you copied, then runs this script as
#   curl -fsSL --cacert xg-ca.crt https://{{ $ccc }}/install/linux.sh | sudo bash -s -- --key <ENROLLMENT KEY> --ca-fingerprint <SHA-256>
set -euo pipefail
CCC="{{ $ccc }}"
CA_FP="{{ $fingerprint }}"
KEY=""
PIN=""
while [ $# -gt 0 ]; do case "$1" in --key) KEY="$2"; shift 2;; --ccc) CCC="$2"; shift 2;; --ca-fingerprint) PIN="$2"; shift 2;; *) echo "unknown option $1"; exit 2;; esac; done
[ -n "$KEY" ] || { echo "usage: linux.sh --key <enrollment key> --ca-fingerprint <sha-256 of the lab CA>"; exit 2; }
# The pin comes from the operator (copied from the CCC page or console), never only from this script.
PIN=$(printf '%s' "$PIN" | tr -d ': ' | tr 'A-F' 'a-f')
[ -n "$PIN" ] || { echo "missing --ca-fingerprint: copy the full install command from the CCC Downloads page"; exit 2; }
[ "$PIN" = "$CA_FP" ] || { echo "the CA fingerprint you gave does not match this CCC's CA - aborting"; exit 3; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
echo "==> Fetching CA certificate and verifying fingerprint"
curl -fsSL "http://$CCC/ca.crt" -o "$tmp/ca.crt"
got=$(openssl x509 -in "$tmp/ca.crt" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')
[ "$got" = "$PIN" ] || { echo "CA fingerprint mismatch ($got) - aborting"; exit 3; }
echo "==> Downloading agent package (HTTPS, verified against the lab CA)"
arch=$(dpkg --print-architecture)
deb="xephyguard-agent_latest_${arch}.deb"   # scripts/release.sh publishes this alias
curl -fsSL --cacert "$tmp/ca.crt" "https://$CCC/downloads/$deb" -o "$tmp/agent.deb"
install -d -m 0755 /etc/xephyguard && install -m 0644 "$tmp/ca.crt" /etc/xephyguard/ca.crt
apt-get install -y "$tmp/agent.deb"
echo "==> Enrolling with the CCC (approve this PC on the dashboard)"
xephyguard-agent enroll --key "$KEY" --ccc "$CCC" --ca-fingerprint "$PIN" --timeout 600
systemctl restart xephyguard-agent
echo "==> Done. Status:"; xephyguard-agent status
