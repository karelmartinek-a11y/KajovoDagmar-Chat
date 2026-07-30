#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
WORK=${TMPDIR:-/tmp}/kajovodagmar-restore-check-$$
cleanup(){ docker compose -f "$ROOT/deployment/compose.restore-check.yaml" down -v >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT INT TERM
mkdir -p "$WORK"
cd "$ROOT/deployment"
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar check
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar info --output=json > "$WORK/backup-info.json"
BACKUP_REPOSITORY_VOLUME=$(docker volume ls \
  --filter label=com.docker.compose.project=kajovodagmar \
  --filter label=com.docker.compose.volume=backup_repository \
  --format '{{.Name}}')
[ -n "$BACKUP_REPOSITORY_VOLUME" ]
export BACKUP_REPOSITORY_VOLUME
docker compose -f compose.restore-check.yaml up -d --wait restore-db
docker compose -f compose.restore-check.yaml run --rm restore-verifier
docker compose -f compose.restore-check.yaml exec -T restore-db \
  psql -U kajovodagmar -d kajovodagmar -Atc \
  "select specification_revision || ':' || state from system_instance where singleton_key='primary'" \
  > "$WORK/restored-instance.txt"
grep -Eq '^v0021:(uninitialized|active)$' "$WORK/restored-instance.txt"
cp "$WORK/backup-info.json" "$ROOT/release/evidence/generated/restore-backup-info.json"
cp "$WORK/restored-instance.txt" "$ROOT/release/evidence/generated/restored-instance.txt"
