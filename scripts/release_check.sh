#!/bin/bash
set -eu -o pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"
export COMPOSE_PROJECT_NAME="kajovodagmar-release-check-${RANDOM}-$$"
if command -v brew >/dev/null 2>&1; then
  NODE22_PREFIX=$(brew --prefix node@22 2>/dev/null || true)
  if [ -n "$NODE22_PREFIX" ] && [ -x "$NODE22_PREFIX/bin/node" ]; then
    export PATH="$NODE22_PREFIX/bin:$PATH"
  fi
fi
PYTHON312=$(uv python find 3.12)
RESULT="$ROOT/release/evidence/generated/release-check-results.json"
rm -rf "$ROOT/release/evidence/generated"
mkdir -p "$(dirname "$RESULT")"
printf '{}\n' > "$RESULT"
RECORD_PY=backend/.venv/bin/python
if [ ! -x "$RECORD_PY" ]; then RECORD_PY=python3; fi
record(){ "$RECORD_PY" scripts/write_check_result.py "$RESULT" "$1" "$2"; }
run(){ local name=$1; shift; echo "==> $name"; if "$@"; then record "$name" pass; else record "$name" fail; echo "Kritická brána $name selhala." >&2; exit 1; fi; }
export KAJOVODAGMAR_ROOT_ENCRYPTION_KEY="${KAJOVODAGMAR_ROOT_ENCRYPTION_KEY:-AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8}"
export KAJOVODAGMAR_INITIALIZATION_SECRET_HASH="${KAJOVODAGMAR_INITIALIZATION_SECRET_HASH:-87a559183b8458084db697d3e6f7e05da1b0e6e807ea2ee9f0cc6b94c650e126}"
run toolchain "$PYTHON312" scripts/check_toolchain.py
run bootstrap make bootstrap
run source make source-check
run format make format-check
run lint make lint
run typecheck make typecheck
run unit make test
run contract make test-contract
run integration_db_reset docker compose -f deployment/compose.test.yaml down -v
run integration_db docker compose -f deployment/compose.test.yaml up -d --wait
trap 'docker compose -f deployment/compose.test.yaml down -v >/dev/null 2>&1 || true; docker compose -f deployment/compose.yaml down -v >/dev/null 2>&1 || true' EXIT
export KAJOVODAGMAR_DATABASE_URL="postgresql+asyncpg://kajovodagmar:test-only-password@127.0.0.1:55432/kajovodagmar_test"
export KAJOVODAGMAR_TEST_DATABASE_URL="$KAJOVODAGMAR_DATABASE_URL"
run integration_migrations make migrate
run integration make test-integration
run backend_coverage_db_reset docker compose -f deployment/compose.test.yaml down -v
run backend_coverage_db_start docker compose -f deployment/compose.test.yaml up -d --wait
run backend_coverage_migrations make migrate
run backend_coverage make test-backend-coverage
run ai_eval make test-ai
run security make test-security
run frontend_build npm --prefix web run build
run image_build docker build --pull --tag kajovodagmar:release-candidate --file deployment/Dockerfile .
run backup_image_build docker build --pull --tag kajovodagmar-postgres:17-pgbackrest-2.59.0 --file deployment/Dockerfile.postgres .
IMAGE_ID=$(docker image inspect kajovodagmar:release-candidate --format='{{.Id}}')
case "$IMAGE_ID" in sha256:*) export APP_IMAGE_DIGEST="$IMAGE_ID";; *) record image_digest fail; echo "Obraz nemá SHA-256 digest." >&2; exit 1;; esac
export APP_IMAGE="kajovodagmar:release-candidate"
export PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-localhost}"
export HTTP_PORT="${HTTP_PORT:-18080}"
export HTTPS_PORT="${HTTPS_PORT:-18443}"
export KAJOVODAGMAR_ENVIRONMENT=production
export KAJOVODAGMAR_PUBLIC_ORIGIN="https://localhost:${HTTPS_PORT}"
export E2E_INITIALIZATION_SECRET="${E2E_INITIALIZATION_SECRET:-e2e-$(openssl rand -hex 24)}"
export E2E_PASSWORD="${E2E_PASSWORD:-E2E-$(openssl rand -hex 32)-synthetic}"
export E2E_USERNAME="${E2E_USERNAME:-acceptance-$(openssl rand -hex 8)}"
export KAJOVODAGMAR_INITIALIZATION_SECRET_HASH="$(PYTHONPATH=backend/src "$RECORD_PY" -c 'import os; from kajovodagmar.security.crypto import token_digest; print(token_digest(os.environ["E2E_INITIALIZATION_SECRET"], "initialization"))')"
export ACME_EMAIL="${ACME_EMAIL:-ci@example.invalid}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-synthetic-release-check-password}"
export PGBACKREST_REPO1_CIPHER_PASS="${PGBACKREST_REPO1_CIPHER_PASS:-synthetic-release-check-backup-encryption-passphrase}"
run compose_stack_reset docker compose -f deployment/compose.yaml down -v --remove-orphans
run compose_database docker compose -f deployment/compose.yaml up -d --wait db pgbackrest
run backup_stanza docker compose -f deployment/compose.yaml exec -T --user postgres db pgbackrest --stanza=kajovodagmar stanza-create
run migrations docker compose -f deployment/compose.yaml run --rm web alembic upgrade head
run compose_up docker compose -f deployment/compose.yaml up -d --wait
run compose_frontend_readiness bash -c '
  for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --insecure --connect-timeout 2 "https://localhost:${HTTPS_PORT}/" \
      | grep -q "<div id=\"root\"></div>"; then
      exit 0
    fi
    sleep 1
  done
  echo "Testovací frontend endpoint nebyl připraven: https://localhost:${HTTPS_PORT}/" >&2
  docker compose -f deployment/compose.yaml ps -a >&2 || true
  docker compose -f deployment/compose.yaml logs --no-color --tail=120 caddy web >&2 || true
  exit 1
'
run instance_bootstrap docker compose -f deployment/compose.yaml exec -T web kajovodagmar bootstrap-instance
run e2e make test-e2e
run accessibility make test-accessibility
run visual make test-visual
run performance make test-performance
run backup make backup-check
run restore make restore-check
run compose_runtime make compose-runtime-check
run sbom make sbom
run vulnerability_gate make vulnerability-gate
run acceptance make acceptance
run traceability make traceability
run release_manifest backend/.venv/bin/python scripts/build_release_manifest.py
record release_check pass
backend/.venv/bin/python - <<'PY'
import json
from pathlib import Path
p=Path('release/evidence/generated/release-check-results.json')
data=json.loads(p.read_text())
if set(data.values())!={'pass'}:
    raise SystemExit('Ne všechny release kontroly prošly.')
print(f"Release-check PASS: {len(data)} bran.")
PY
