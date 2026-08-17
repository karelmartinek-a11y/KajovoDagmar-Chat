#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly KEY_FILE="${VOICE_SERVICE_KEY_FILE:-/srv/hcasc/kajovodagmar-chat/shared/secrets/voice-service-api-key}"

usage() {
  echo "usage: $0 check|generate|revoke" >&2
  exit 64
}

check_key() {
  test -f "$KEY_FILE" || { echo "voice-service-key=absent"; return 1; }
  local mode owner size
  mode=$(stat -c '%a' "$KEY_FILE")
  owner=$(stat -c '%U:%G' "$KEY_FILE")
  size=$(stat -c '%s' "$KEY_FILE")
  if [[ $mode != 600 || $owner != root:root || $size -lt 32 ]]; then
    echo "voice-service-key=invalid mode=$mode owner=$owner size=$size" >&2
    return 1
  fi
  echo "voice-service-key=present mode=$mode owner=$owner size=$size"
}

generate_key() {
  local directory temporary
  directory=$(dirname "$KEY_FILE")
  install -d -o root -g root -m 700 "$directory"
  temporary=$(mktemp "$directory/.voice-service-api-key.XXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  openssl rand -base64 48 | tr -d '\n' >"$temporary"
  chown root:root "$temporary"
  chmod 600 "$temporary"
  mv -f -- "$temporary" "$KEY_FILE"
  trap - EXIT
  check_key
}

revoke_key() {
  if [[ -f $KEY_FILE ]]; then
    mv -f -- "$KEY_FILE" "$KEY_FILE.revoked.$(date -u +%Y%m%dT%H%M%SZ)"
    chmod 600 "$KEY_FILE.revoked."* 2>/dev/null || true
  fi
  echo "voice-service-key=revoked"
}

case "${1:-}" in
  check) check_key ;;
  generate) generate_key ;;
  revoke) revoke_key ;;
  *) usage ;;
esac
