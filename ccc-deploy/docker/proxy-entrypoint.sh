#!/bin/sh
set -eu

STATE_FILE="/var/lib/xephyguard/net/state.json"

# One source for the mode (I-CCC-9): network_mode in state.json (Settings, F64/F104) wins; XG_NETWORK_MODE
# (.env, the installer's answer) is only the default before the server has written state.json. Read here as
# root, before gosu (state.json is 0640). A change takes effect when the proxy restarts.
MODE=""
if [ -f "$STATE_FILE" ]; then
  MODE=$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("network_mode") or "").strip())' "$STATE_FILE" 2>/dev/null || true)
fi
[ -n "$MODE" ] || MODE="${XG_NETWORK_MODE:-gateway}"
echo "proxy: network mode $MODE" >&2

# Listen on the lab-side CCC address only, never 0.0.0.0 (I-CCC-4): XG_CCC_IP from .env, else ccc_ip in
# state.json. In gateway mode the nft redirect delivers to the LAN interface's address, which is XG_CCC_IP.
LISTEN="${XG_CCC_IP:-}"
if [ -z "$LISTEN" ] && [ -f "$STATE_FILE" ]; then
  LISTEN=$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("ccc_ip") or "").strip())' "$STATE_FILE" 2>/dev/null || true)
fi
case "$LISTEN" in
  "") echo "proxy: XG_CCC_IP unset and no ccc_ip in $STATE_FILE; listening on 127.0.0.1 only (lab PCs get no proxy)" >&2
      LISTEN=127.0.0.1 ;;
  *[!0-9.]*) echo "proxy: XG_CCC_IP '$LISTEN' is not an IPv4 address" >&2; exit 1 ;;
esac

if [ "$MODE" = "proxy_only" ]; then
  MODE_ARGS="--mode regular@${LISTEN}:8080 --mode transparent@${LISTEN}:8085"
else
  MODE_ARGS="--mode transparent@${LISTEN}:8080 --mode regular@${LISTEN}:8085"
fi

CONFDIR="/home/mitmproxy/.mitmproxy"

# shellcheck disable=SC2086
set -- mitmdump \
  $MODE_ARGS \
  --showhost \
  --set "confdir=${CONFDIR}" \
  --set block_global=true \
  --set connection_strategy=lazy \
  --set termlog_verbosity=warn \
  -s /opt/xephyguard/proxy/addons/xephyguard_addon.py \
  --set xg_policy=/var/lib/xephyguard/net/proxy.json

if [ "$(id -u)" -eq 0 ] && command -v gosu >/dev/null 2>&1; then
  chown -R mitmproxy:mitmproxy /var/log/xephyguard 2>/dev/null || true
  exec env HOME=/home/mitmproxy gosu mitmproxy "$@"
fi

export HOME=/home/mitmproxy
exec "$@"
