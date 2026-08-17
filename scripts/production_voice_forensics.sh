#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly ROOT=/srv/hcasc/kajovodagmar-chat
readonly CURRENT=$ROOT/current
readonly SHARED=$ROOT/shared
readonly ENV_FILE=$SHARED/env/production.env
readonly KEY_FILE=$SHARED/secrets/voice-service-api-key
readonly EVIDENCE_DIR=$SHARED/logs/voice-forensics

test -L "$CURRENT" || { echo "active release symlink is missing" >&2; exit 78; }
test -f "$ENV_FILE" || { echo "production env file is missing" >&2; exit 78; }
test -f "$KEY_FILE" || { echo "voice service key is missing" >&2; exit 78; }
test "$(stat -c '%a' "$KEY_FILE")" = 600 || { echo "voice service key must be 0600" >&2; exit 78; }
test "$(stat -c '%U:%G' "$KEY_FILE")" = root:root || { echo "voice service key owner must be root:root" >&2; exit 78; }

mkdir -p "$EVIDENCE_DIR"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
report="$EVIDENCE_DIR/$timestamp.json"

docker compose --project-name kajovodagmar-chat \
  --env-file "$ENV_FILE" \
  --file "$CURRENT/deployment/compose.yaml" \
  --file "$CURRENT/deployment/production/compose.yaml" \
  exec -T --user root web kajovodagmar voice-forensics >"$report"

chmod 600 "$report"
echo "voice-forensics=pass report=$report"
