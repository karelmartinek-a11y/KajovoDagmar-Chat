# HANDOFF

## Stav

Repozitářová implementace a lokální release brána jsou **PASS**, ale celková etapa je **BLOCKER**. GitHub Actions run `30503011395` ani v attemptu 3 nedostal hosted runner kvůli aktivnímu billing/spending-limit omezení. Proto nebyla bezpečně otevřena produkční fáze.

## Reprodukovatelné ověření

1. Připravit přesný toolchain uvedený v `GENERATION_MANIFEST.json`.
2. Spustit `make release-check`.
3. Ověřit, že všech 39 hodnot v `release/evidence/generated/release-check-results.json` je `pass`.
4. Ověřit `release/RELEASE_MANIFEST.json`, čerstvé důkazy a čistý pracovní strom.

## Přesný blocker

- Příkaz: `gh run watch 30503011395 --repo karelmartinek-a11y/KajovoDagmar-Chat --exit-status`
- Návratový kód: `1`
- Attempt: `3`
- Job: `source-and-unit`, ID `91059463074`
- Runner: nepřidělen (`runner_id: 0`)
- Spuštěné kroky: `0`
- GitHub annotation: `The job was not started because recent account payments have failed or your spending limit needs to be increased.`

Pro pokračování musí GitHub Billing & plans umožnit hosted Actions pro private repozitář. Poté je nutné znovu spustit původní run, prokázat úspěch všech tří jobů a teprve následně provést read-only serverový intake.

## Stav důkazů

- Lock soubory jsou uzamčené a frozen bootstrap prochází.
- Backendová a frontendová coverage překračují nezměněné prahy.
- PostgreSQL 17/pgvector integrace, Alembic, Compose, Playwright, backup a izolovaný restore procházejí.
- Source/image SBOM, secret scan a vulnerability gate procházejí.
- Matice dohledatelnosti uzavírá 1000 z 1000 požadavků konkrétní implementací, testem a čerstvým release důkazem.
- Produkční server, DNS, Nginx, jiné služby, GitHub Environment a produkční secrets zůstaly beze změny.

## Bezpečnost

Do repozitáře nejsou vloženy produkční klíče, hesla, tokeny, runtime databáze, zálohy ani uživatelská data. Syntetické hodnoty jsou omezené na testovací a CI prostředí.
