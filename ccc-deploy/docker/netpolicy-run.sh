#!/bin/bash
# Starts Unbound and keeps DNS + nftables in sync with /var/lib/xephyguard/net/state.json.
set -e
OUT=/var/lib/xephyguard/net
mkdir -p "$OUT"
[ -f "$OUT/unbound-xephyguard.conf" ] || echo "# waiting for first policy state" > "$OUT/unbound-xephyguard.conf"
cd /opt/xephyguard/proxy
python3 -m xg_netpolicy.generate --state "$OUT/state.json" --out "$OUT" || true
# Unbound listens on the lab-side CCC address and loopback only, never 0.0.0.0 (I-CCC-4). Template: the
# local stack mounts docker/unbound-local.conf, the image carries proxy/dns/unbound.conf.
TMPL=/etc/unbound/unbound-local.conf.tmpl
[ -f "$TMPL" ] || TMPL=/etc/unbound/xephyguard.conf.tmpl
CCC_IP="${XG_CCC_IP:-}"
if [ -z "$CCC_IP" ] && [ -f "$OUT/state.json" ]; then
  CCC_IP=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("ccc_ip") or "")' "$OUT/state.json" 2>/dev/null || true)
fi
case "$CCC_IP" in
  *[!0-9.]*) echo "netpolicy: XG_CCC_IP '$CCC_IP' is not an IPv4 address" >&2; exit 1 ;;
esac
IF_LINES="    interface: 127.0.0.1"
if [ -z "$CCC_IP" ]; then
  echo "netpolicy: XG_CCC_IP unset and no ccc_ip in state.json; Unbound answers on 127.0.0.1 only (lab PCs get no DNS)" >&2
elif [ "$CCC_IP" != "127.0.0.1" ]; then
  IF_LINES="    interface: ${CCC_IP}\n${IF_LINES}"
fi
python3 -c 'import sys; t=open(sys.argv[1]).read(); open(sys.argv[2],"w").write(t.replace("__INTERFACE_LINES__", sys.argv[3].replace("\\n","\n")))' \
  "$TMPL" "$OUT/unbound.conf" "$IF_LINES"
UNBOUND_CONF="$OUT/unbound.conf"
# Unbound remote control socket lives here (container-private, not a volume)
install -d -m 0750 -o root -g root /run/xephyguard-unbound
export XG_UNBOUND_CONF="$UNBOUND_CONF"
unbound-checkconf "$UNBOUND_CONF"
unbound -d -c "$UNBOUND_CONF" &
UNBOUND=$!
python3 -m xg_netpolicy.generate --state "$OUT/state.json" --out "$OUT" --watch --apply &
WATCH=$!
# Both must run (I-CCC-11): when either Unbound or the policy watcher exits, stop the other and exit non-zero,
# so Docker restarts the container instead of leaving DNS running on a policy that no longer updates.
trap 'kill "$UNBOUND" "$WATCH" 2>/dev/null; wait; exit 0' TERM INT
set +e
wait -n "$UNBOUND" "$WATCH"
rc=$?
echo "netpolicy: unbound or the policy watcher exited (status $rc); stopping so Docker restarts the container" >&2
kill "$UNBOUND" "$WATCH" 2>/dev/null
wait
exit 1
