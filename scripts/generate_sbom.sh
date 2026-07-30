#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUT="$ROOT/release/evidence/generated"
mkdir -p "$OUT"
if ! command -v syft >/dev/null 2>&1; then
  echo "Nástroj syft je povinný pro release SBOM." >&2
  exit 1
fi
if [ -z "${DOCKER_HOST:-}" ] && command -v docker >/dev/null 2>&1; then
  DOCKER_HOST=$(docker context inspect "$(docker context show)" \
    --format '{{.Endpoints.docker.Host}}')
  export DOCKER_HOST
fi
syft dir:"$ROOT/backend" \
  --exclude './.venv/**' \
  -o cyclonedx-json="$OUT/sbom-backend-source.cdx.json"
syft dir:"$ROOT/web" \
  --exclude './node_modules/**' \
  --exclude './dist/**' \
  -o cyclonedx-json="$OUT/sbom-frontend-source.cdx.json"
: "${APP_IMAGE:?APP_IMAGE with immutable digest is required}"
syft "$APP_IMAGE" -o cyclonedx-json="$OUT/sbom-image.cdx.json"
