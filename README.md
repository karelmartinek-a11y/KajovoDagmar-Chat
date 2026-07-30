# KájovoDagmar

> **Stav repozitářové akceptace: PASS.** Produkční nasazení je záměrně mimo tuto etapu. Viz `RUN_STATUS.json`, `BLOCKERS.json` a `AUDIT_FINDINGS.md`.

KájovoDagmar je jediný modulární monolit osobní hlasové virtuální asistentky pro jednoho administrátora `Karmar78`. Tento repozitář je čistou implementací kanonického SSOT revize v0021.

## Architektura

- **Web:** React 19, TypeScript strict, Vite; jediný aplikační shell a sekce Chat, Historie, Paměť, Nastavení a Profil.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, asyncpg, Alembic; verzované REST `/api/v1` a realtime WebSocket `/api/v1/realtime`.
- **Data:** PostgreSQL 17 s pgvector je jediný autoritativní stav. Worker používá databázové joby a transactional outbox.
- **Provoz:** jeden aplikační obraz s rolemi web/worker/CLI, Caddy TLS hranou a pgBackRest/WAL zálohami.

## Požadavky

Python 3.12.13, uv 0.12.0, Node.js 22.23.2, npm 10.x, Docker Engine s Compose v2, GNU Make a OpenSSL. Požadované verze jsou v `GENERATION_MANIFEST.json` a všechny závislosti jsou uzamčeny v lock souborech.

## První lokální průchod

```bash
cp deployment/.env.example deployment/.env
python3 scripts/generate_initialization_secret.py --env-file deployment/.env
make bootstrap
make compose-up
make migrate
```

Otevřete `https://localhost`, vložte jednorázové inicializační tajemství z bezpečného výstupu skriptu, ponechte uživatele `Karmar78` a vytvořte heslo o délce 14–128 znaků. Pro produkční doménu použijte `chat.hcasc.cz` a skutečné hodnoty infrastruktury podle `docs/deployment/production.md`.

## Vývoj

```bash
make dev
make format
make lint
make typecheck
make test
make test-integration
make test-e2e
make test-ai
make test-security
```

## Build, migrace a provoz

```bash
make build
make migrate
make compose-up
make backup-check
make restore-check
make release-check
make compose-down
```

`make release-check` je závazná neobejitelná brána. Končí nenulově při prvním kritickém selhání a ukládá výsledky do `release/evidence/generated/`.

## Dokumentace

- [Architektura](docs/architecture/modular-monolith.md)
- [Datový model](docs/data-model.md)
- [REST API](docs/api/rest.md) a [realtime protokol](docs/api/realtime.md)
- [Bezpečnost](docs/security/model.md)
- [Testování](docs/testing/strategy.md)
- [Produkční nasazení](docs/deployment/production.md)
- [Runbooky](docs/runbooks/README.md)
- [Uživatelská příručka](docs/user/guide.md)
- [Administrátorská příručka](docs/admin/guide.md)
