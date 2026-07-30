#!/bin/sh
set -eu
cd "$(dirname "$0")/../deployment"
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar stanza-create >/dev/null
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar --type=full backup >/dev/null
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar check >/dev/null
docker compose exec -T --user postgres db pgbackrest --stanza=kajovodagmar info --output=json
