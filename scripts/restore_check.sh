#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
WORK=${TMPDIR:-/tmp}/kajovodagmar-restore-check-$$
PROJECT=${COMPOSE_PROJECT_NAME:-kajovodagmar}
dc(){ docker compose -p "$PROJECT" "$@"; }
cleanup(){ dc -f "$ROOT/deployment/compose.restore-check.yaml" down -v >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT INT TERM
mkdir -p "$WORK"
cd "$ROOT/deployment"
dc exec -T --user postgres db pgbackrest --stanza=kajovodagmar check
dc exec -T --user postgres db pgbackrest --stanza=kajovodagmar info --output=json > "$WORK/backup-info.json"
BACKUP_REPOSITORY_VOLUME=$(docker volume ls \
  --filter label=com.docker.compose.project="$PROJECT" \
  --filter label=com.docker.compose.volume=backup_repository \
  --format '{{.Name}}')
[ -n "$BACKUP_REPOSITORY_VOLUME" ]
export BACKUP_REPOSITORY_VOLUME
dc -f compose.restore-check.yaml up -d --wait restore-db
dc -f compose.restore-check.yaml run --rm restore-verifier
dc -f compose.restore-check.yaml exec -T restore-db \
  psql -U kajovodagmar -d kajovodagmar -Atc \
  "select specification_revision || ':' || state from system_instance where singleton_key='primary'" \
  > "$WORK/restored-instance.txt"
grep -Eq '^v0021:(uninitialized|active)$' "$WORK/restored-instance.txt"
cp "$WORK/backup-info.json" "$ROOT/release/evidence/generated/restore-backup-info.json"
cp "$WORK/restored-instance.txt" "$ROOT/release/evidence/generated/restored-instance.txt"
