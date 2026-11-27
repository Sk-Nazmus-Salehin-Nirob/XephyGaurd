# shellcheck shell=bash
# Reads a KEY=VALUE env file (.env, .env.local) into exported variables WITHOUT running it as shell
# (I-CCC-21): no $(...), backticks or $VAR in a value is ever expanded, and a line that is not
# KEY=VALUE is skipped. One pair of matching outer quotes ('…' or "…") is removed, as Docker Compose does;
# nothing inside is unescaped. Used by install.sh, xephyguard-ccc and bootstrap-local.sh.
xg_env_load() {
  local line key val
  [ -r "$1" ] || { echo "cannot read $1" >&2; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case $line in '' | '#'*) continue ;; esac
    key=${line%%=*}
    val=${line#*=}
    [[ $line == *=* && $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case $val in
      \'*\' | \"*\") val=${val:1:${#val}-2} ;;
    esac
    export "$key=$val"
  done < "$1"
}
