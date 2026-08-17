#!/bin/sh
set -eu

secret=/run/secrets/voice-service-api-key
runtime_secret=/tmp/kajovodagmar-voice-service-api-key

if [ -r "$secret" ]; then
  cp "$secret" "$runtime_secret"
  chown 10001:10001 "$runtime_secret"
  chmod 0400 "$runtime_secret"
  export KAJOVODAGMAR_VOICE_SERVICE_API_KEY_FILE="$runtime_secret"
fi

exec su-exec 10001:10001 "$@"
