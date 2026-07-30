#!/bin/sh
set -eu

for container in \
  kajovodagmar-db-1 \
  kajovodagmar-web-1 \
  kajovodagmar-worker-1 \
  kajovodagmar-backup-agent-1 \
  kajovodagmar-caddy-1
do
  state=$(docker inspect "$container" --format '{{.State.Status}} {{.RestartCount}}')
  if [ "$state" != "running 0" ]; then
    echo "$container má nepřijatelný runtime stav: $state" >&2
    exit 1
  fi
  echo "$container: running, restarts=0"
done

if docker logs kajovodagmar-db-1 2>&1 |
  grep -Eq 'all server processes terminated; reinitializing|server process .* exited with exit code'; then
  echo "PostgreSQL log dokládá neočekávaný restart serverových procesů." >&2
  exit 1
fi

if docker logs kajovodagmar-worker-1 2>&1 |
  grep -Eq 'Traceback|job\.failed|worker\.stopped'; then
  echo "Worker log obsahuje pád nebo nezpracovaný job." >&2
  exit 1
fi

echo "PostgreSQL a worker logy neobsahují pád runtime."
