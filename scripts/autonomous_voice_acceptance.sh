#!/bin/bash
set -Eeuo pipefail
umask 077
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PYTHON_BIN=${PYTHON_BIN:-backend/.venv/bin/python}

iterations=${ITERATIONS:-5}
project="kajovodagmar-acceptance-${RANDOM}-$$"
evidence="${AUTONOMOUS_EVIDENCE_DIR:-release/evidence/generated/autonomous-voice}"
mkdir -p "$evidence"
export COMPOSE_PROJECT_NAME="$project"
export APP_IMAGE="${APP_IMAGE:-kajovodagmar:release-candidate}"
export PUBLIC_DOMAIN=localhost HTTP_PORT=18080 HTTPS_PORT=18443
export KAJOVODAGMAR_ENVIRONMENT=test KAJOVODAGMAR_PUBLIC_ORIGIN=https://localhost:18443
export ACME_EMAIL=ci@example.invalid
export POSTGRES_PASSWORD="acceptance-$(openssl rand -hex 24)"
export PGBACKREST_REPO1_CIPHER_PASS="acceptance-backup-$(openssl rand -hex 24)"
export KAJOVODAGMAR_ROOT_ENCRYPTION_KEY="$($PYTHON_BIN -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
export E2E_INITIALIZATION_SECRET="acceptance-init-$(openssl rand -hex 24)"
export E2E_PASSWORD="Acceptance-$(openssl rand -hex 32)-synthetic"
export E2E_USERNAME="acceptance-$(openssl rand -hex 8)"
export E2E_DETERMINISTIC_PROVIDER=true
export KAJOVODAGMAR_INITIALIZATION_SECRET_HASH="$(PYTHONPATH=backend/src "$PYTHON_BIN" -c 'import os; from kajovodagmar.security.crypto import token_digest; print(token_digest(os.environ["E2E_INITIALIZATION_SECRET"], "initialization"))')"

cleanup() {
  docker compose -f deployment/compose.yaml down -v --remove-orphans >"$evidence/compose-down.log" 2>&1 || true
}
trap cleanup EXIT

docker compose -f deployment/compose.yaml up -d --wait db pgbackrest
docker compose -f deployment/compose.yaml run --rm web alembic upgrade head
docker compose -f deployment/compose.yaml up -d --wait
docker compose -f deployment/compose.yaml exec -T web kajovodagmar bootstrap-instance >/dev/null
docker compose -f deployment/compose.yaml exec -T web kajovodagmar acceptance-seed-provider

for iteration in $(seq 1 "$iterations"); do
  seed="${AUTONOMOUS_SEED:-$((20260731 + iteration))}"
  echo "iteration=$iteration seed=$seed"
  ITERATION_SEED="$seed" npm --prefix web run e2e -- --project=mobile-chromium --trace=retain-on-failure \
    >"$evidence/iteration-${iteration}.log" 2>&1 || {
      docker compose -f deployment/compose.yaml ps -a >"$evidence/compose-ps-${iteration}.txt" || true
      docker compose -f deployment/compose.yaml logs --no-color --tail=300 web caddy >"$evidence/compose-logs-${iteration}.txt" || true
      exit 1
    }
done

if [[ "${RUN_WEBKIT:-false}" == "true" ]]; then
  npm --prefix web run e2e -- --project=webkit --trace=retain-on-failure \
    >"$evidence/webkit.log" 2>&1
fi

docker compose -f deployment/compose.yaml exec -T web kajovodagmar diagnostics-voice-live-probe \
  >"$evidence/provider-contract-probe.json"

if command -v adb >/dev/null 2>&1 && adb devices | awk 'NR > 1 && $2 == "device" { found=1 } END { exit(found ? 0 : 1) }'; then
  BACKGROUND_SECONDS="${BACKGROUND_SECONDS:-10}" ./scripts/android_voice_acceptance.sh \
    >"$evidence/android-lifecycle.log" 2>&1
elif [[ "${ANDROID_EMULATOR_REQUIRED:-false}" == "true" ]]; then
  echo "Android emulator/device is required but unavailable." >&2
  exit 1
fi

echo "Autonomous voice acceptance PASS: iterations=$iterations"
