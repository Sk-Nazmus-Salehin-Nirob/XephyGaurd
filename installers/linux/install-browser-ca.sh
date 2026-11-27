#!/bin/sh
# Adds a CA to the per-user NSS databases used by Chromium-based browsers (Firefox uses the enterprise
# policy instead). Runs at install and is re-run by the agent for the proxy's interception CA.
#   install-browser-ca.sh                      the lab CA (/etc/xephyguard/ca.crt, "XephyGuard Lab CA")
#   install-browser-ca.sh CERT NICKNAME        another CA, e.g. the interception CA (agent Step 41)
#   install-browser-ca.sh --remove NICKNAME    deletes that nickname from every database
REMOVE=
if [ "$1" = --remove ]; then
  REMOVE=1; NICK=${2:?nickname}
else
  CA=${1:-/etc/xephyguard/ca.crt}; NICK=${2:-XephyGuard Lab CA}
  [ -f "$CA" ] || { echo "$CA not found" >&2; exit 1; }
fi
command -v certutil >/dev/null || { echo "libnss3-tools not installed; skipping NSS"; exit 0; }
for home in /home/* /etc/skel; do
  db="$home/.pki/nssdb"
  if [ -n "$REMOVE" ]; then
    [ -f "$db/cert9.db" ] && certutil -d "sql:$db" -D -n "$NICK" >/dev/null 2>&1
    continue
  fi
  mkdir -p "$db"
  [ -f "$db/cert9.db" ] || certutil -d "sql:$db" -N --empty-password
  certutil -d "sql:$db" -D -n "$NICK" >/dev/null 2>&1 || true
  certutil -d "sql:$db" -A -t "C,," -n "$NICK" -i "$CA"
  [ "$home" = /etc/skel ] || chown -R "$(stat -c %U "$home")": "$home/.pki"
done
exit 0
