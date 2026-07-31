#!/bin/sh
set -eu

PROJECT=${COMPOSE_PROJECT_NAME:-kajovodagmar}
compose_container(){
  docker compose -p "$PROJECT" -f deployment/compose.yaml ps -q "$1"
}

for service in db web worker backup-agent caddy
do
  container=$(compose_container "$service")
  state=$(docker inspect "$container" --format '{{.State.Status}} {{.RestartCount}}')
  if [ "$state" != "running 0" ]; then
    echo "$service ($container) má nepřijatelný runtime stav: $state" >&2
    exit 1
  fi
  echo "$service ($container): running, restarts=0"
done

DB_CONTAINER=$(compose_container db)
WORKER_CONTAINER=$(compose_container worker)
if docker logs "$DB_CONTAINER" 2>&1 |
  grep -Eq 'all server processes terminated; reinitializing|server process .* exited with exit code'; then
  echo "PostgreSQL log dokládá neočekávaný restart serverových procesů." >&2
  exit 1
fi

if docker logs "$WORKER_CONTAINER" 2>&1 |
  grep -Eq 'Traceback|job\.failed|worker\.stopped'; then
  echo "Worker log obsahuje pád nebo nezpracovaný job." >&2
  exit 1
fi

echo "PostgreSQL a worker logy neobsahují pád runtime."
