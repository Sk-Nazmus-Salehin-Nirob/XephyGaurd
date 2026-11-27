#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.local"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.local.yml"

if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE" >&2
    exit 1
fi

# Parsed, not sourced: a value is never run as shell (I-CCC-21).
# shellcheck source=ccc-deploy/bin/xg-env.sh
. "$DEPLOY_DIR/bin/xg-env.sh"
xg_env_load "$ENV_FILE"

dc() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}
# MYSQL_PWD from the mysql container's own env, inside its shell: no password in any argv (I-CCC-20).
# shellcheck disable=SC2016  # expanded by the container's sh, on purpose
mysql_root() { dc exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec "$@"' sh "$@"; }
# shellcheck disable=SC2016
mysql_app() { dc exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec "$@"' sh "$@"; }

RESEED="${1:-}"

echo "[1/6] Starting MySQL..."
dc up -d mysql
for _ in $(seq 60); do
    if mysql_root mysqladmin ping -h 127.0.0.1 -uroot >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if ! mysql_root mysqladmin ping -h 127.0.0.1 -uroot >/dev/null 2>&1; then   # I-CCC-16: a clear stop
    echo "MySQL did not start within 2 minutes; see: docker compose -f $COMPOSE_FILE logs mysql" >&2
    exit 1
fi

# The proxy's own interception CA, made on this host from the lab ca.crt only; the lab ca.key never goes to
# the proxy and there is no fallback to it (I-CCC-3, I-CCC-15). Written before the CA volume is seeded so the
# server can publish interception-ca.crt (S-75). install.sh's excluded names plus the loopback ones.
CA_SRC="$REPO_ROOT/server/storage/app/private/ca"
MITM_SRC="$REPO_ROOT/server/storage/app/private/mitmproxy"
ica_names=("IP:127.0.0.1" "DNS:localhost" "DNS:xephyguard-ccc")
[ -n "${XG_CCC_IP:-}" ] && ica_names+=("IP:$XG_CCC_IP")
ica=$(bash "$DEPLOY_DIR/bin/xg-interception-ca.sh" "$MITM_SRC" "$CA_SRC" "${ica_names[@]}") || {
    echo "Could not create the proxy's interception CA (needs openssl and $CA_SRC/ca.crt)" >&2
    exit 1
}
echo "Proxy interception CA: $ica"

echo "[2/6] Seeding CA, mitmproxy CA, and downloadable artifacts into Compose volumes..."
dc run --rm -T --no-deps --entrypoint sh \
    -v "$REPO_ROOT/server/storage/app/private/ca:/src/ca:ro" \
    -v "$REPO_ROOT/server/storage/app/public/downloads:/src/downloads:ro" \
    web -eu -c '
        mkdir -p /var/lib/xephyguard/ca /var/www/html/storage/app/public/downloads /var/www/html/storage/app/private/ca /var/www/html/storage/app/net
        cp -a /src/ca/. /var/lib/xephyguard/ca/
        chmod 0711 /var/lib/xephyguard/ca
        chmod 0644 /var/lib/xephyguard/ca/*.crt /var/lib/xephyguard/ca/*.pem 2>/dev/null || true
        chown 33:33 /var/lib/xephyguard/ca/*.key 2>/dev/null || true
        chmod 0600 /var/lib/xephyguard/ca/*.key 2>/dev/null || true

        if [ -w /var/www/html/storage/app/public/downloads ]; then
            cp -a /src/downloads/. /var/www/html/storage/app/public/downloads/
            chown -R 33:33 /var/www/html/storage/app/public/downloads
        fi
        chown -R 33:33 /var/www/html/storage/app/private /var/www/html/storage/app/net 2>/dev/null || true
    '

dc run --rm -T --no-deps --user 0:0 --entrypoint sh \
    -v "$MITM_SRC:/src/mitm:ro" \
    proxy -eu -c '
        mkdir -p /home/mitmproxy/.mitmproxy
        # Only the interception CA is mounted here, never the lab CA directory (I-CCC-15).
        rm -f /home/mitmproxy/.mitmproxy/mitmproxy-ca.p12 /home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.p12 /home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.cer
        cp /src/mitm/mitmproxy-ca.pem /src/mitm/mitmproxy-ca-cert.pem /home/mitmproxy/.mitmproxy/
        chown -R 1500:1500 /home/mitmproxy/.mitmproxy
        chmod 0700 /home/mitmproxy/.mitmproxy
        chmod 0600 /home/mitmproxy/.mitmproxy/mitmproxy-ca.pem
        chmod 0644 /home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem
    '

echo "[3/6] Running Laravel migrations on MySQL..."
dc run --rm -T --no-deps migrate   # the one-shot migrate service (I-CCC-24)

USER_COUNT=$(mysql_app mysql -N -B -u"$DB_USERNAME" "$DB_DATABASE" -e "SELECT COUNT(*) FROM users;")
if [ "$RESEED" = "--reseed" ] || [ "$USER_COUNT" -eq 0 ]; then
    echo "[4/6] Importing server/database/database.sqlite into MySQL..."
    dc run --rm -T --no-deps \
        -v "$REPO_ROOT/server/database/database.sqlite:/tmp/import.sqlite:ro" \
        -v "$DEPLOY_DIR/import-sqlite-to-local.php:/tmp/import-sqlite-to-local.php:ro" \
        --entrypoint php web /tmp/import-sqlite-to-local.php /tmp/import.sqlite
else
    echo "[4/6] MySQL already contains $USER_COUNT user(s); skipping SQLite import (pass --reseed to overwrite)."
fi

echo "[5/6] Generating network policy state..."
dc run --rm -T --no-deps web artisan xephyguard:net:write
dc run --rm -T --no-deps --entrypoint sh web -c 'chown -R 33:33 /var/lib/xephyguard/net'

echo "[6/6] Starting full proxy_only + screen-gateway stack..."
dc up -d
dc ps
