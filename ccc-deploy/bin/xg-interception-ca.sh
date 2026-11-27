#!/usr/bin/env bash
# xg-interception-ca.sh MITM_DIR CA_DIR [IP:a.b.c.d | DNS:name]...
# Gives mitmproxy its own self-signed interception CA, so the lab root ca.key never enters the proxy
# container (I-CCC-3, I-CCC-15). The lab root cannot sign an intermediate (pathlen:0), so this is a
# separate root; agents install it from the policy (server S-75, agent Step 41) and their own TLS keeps
# trusting only the lab CA. Every IP:/DNS: argument becomes an excluded name constraint (the CCC's own
# names), so clients that honour constraints on a root also refuse a CCC certificate minted with it.
# Writes MITM_DIR/mitmproxy-ca.pem (key + cert, 0600), MITM_DIR/mitmproxy-ca-cert.pem and
# CA_DIR/interception-ca.crt (0644, what the server publishes). Keeps a valid existing CA
# ("unchanged"); replaces one that is the lab root, not a CA, unreadable, within 30 days of expiry or
# excluding other names than asked (e.g. a new CCC IP) ("created"). The caller sets the owner (mitmproxy
# runs as uid 1500). Agents pick a new one up with the next policy.
set -euo pipefail
[ $# -ge 2 ] || { echo "usage: $0 MITM_DIR CA_DIR [IP:addr|DNS:name]..." >&2; exit 2; }
MITM=$1 CA_DIR=$2
shift 2
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
[ -r "$CA_DIR/ca.crt" ] || { echo "$CA_DIR/ca.crt not found (create the lab CA first)" >&2; exit 1; }

excluded="" want=""
for n in "$@"; do
  case $n in
    IP:*) ip=${n#IP:}
          [[ $ip =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || { echo "not an IPv4 address: $n" >&2; exit 2; }
          excluded+=",excluded;IP:$ip/255.255.255.255"; want+="IP:$ip/255.255.255.255"$'\n' ;;
    DNS:*) d=${n#DNS:}
           [[ $d =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$ ]] || { echo "not a DNS name: $n" >&2; exit 2; }
           excluded+=",excluded;DNS:$d"; want+="DNS:$d"$'\n' ;;
    *) echo "expected IP:addr or DNS:name, got: $n" >&2; exit 2 ;;
  esac
done
want=$(printf '%s' "$want" | sort -u)

pub_of_cert() { openssl x509 -in "$1" -noout -pubkey 2>/dev/null; }
pub_of_key()  { openssl pkey -in "$1" -pubout 2>/dev/null; }
# The excluded names in a certificate, one per line, in the form of $want.
excluded_of() { openssl x509 -in "$1" -noout -ext nameConstraints 2>/dev/null | grep -E '^[[:space:]]+(IP|DNS):' | tr -d ' \t\r' | sort -u; }

umask 077
mkdir -p "$MITM" && chmod 0700 "$MITM"
bundle=$MITM/mitmproxy-ca.pem
if [ -s "$bundle" ] \
   && key_pub=$(pub_of_key "$bundle") && cert_pub=$(pub_of_cert "$bundle") \
   && [ "$key_pub" = "$cert_pub" ] \
   && [ "$key_pub" != "$(pub_of_cert "$CA_DIR/ca.crt")" ] \
   && openssl x509 -in "$bundle" -noout -text 2>/dev/null | grep -q 'CA:TRUE' \
   && openssl x509 -in "$bundle" -noout -checkend $((30 * 86400)) >/dev/null 2>&1 \
   && [ "$(excluded_of "$bundle")" = "$want" ]; then
  state=unchanged
else
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  cat > "$tmp/ext.cnf" <<EOF
[req]
prompt = no
distinguished_name = dn
[dn]
O = XephyGuard
CN = XephyGuard Interception CA
[ica]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
EOF
  [ -z "$excluded" ] || echo "nameConstraints = critical${excluded}" >> "$tmp/ext.cnf"
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$tmp/key.pem" 2>/dev/null
  # The subject is in the config, not -subj: Git Bash would rewrite "/O=..." as a Windows path (bootstrap-local).
  openssl req -x509 -new -key "$tmp/key.pem" -sha256 -days 3650 -config "$tmp/ext.cnf" -extensions ica \
    -out "$tmp/cert.pem" 2>/dev/null
  cat "$tmp/key.pem" "$tmp/cert.pem" > "$tmp/bundle.pem"
  mv -f "$tmp/bundle.pem" "$bundle"
  # Files mitmproxy may have generated next to an old bundle; the .p12 would hold the old (lab root) key.
  rm -f "$MITM/mitmproxy-ca.p12" "$MITM/mitmproxy-ca-cert.p12" "$MITM/mitmproxy-ca-cert.cer"
  state=created
fi
chmod 0600 "$bundle"
openssl x509 -in "$bundle" -out "$MITM/mitmproxy-ca-cert.pem"
chmod 0644 "$MITM/mitmproxy-ca-cert.pem"
openssl x509 -in "$bundle" -out "$CA_DIR/interception-ca.crt"
chmod 0644 "$CA_DIR/interception-ca.crt"
echo "$state"
