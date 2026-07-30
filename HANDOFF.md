# HANDOFF

## Stav

Repozitářová etapa je **PASS**: závazný `make release-check` prošel všemi kritickými branami. Produkční nasazení je samostatná budoucí etapa; tento handoff neopravňuje měnit produkční tajemství, DNS, Nginx ani existující serverové služby.

## Reprodukovatelné ověření

1. Připravit přesný toolchain uvedený v `GENERATION_MANIFEST.json`.
2. Spustit `make release-check`.
3. Ověřit, že všech 39 hodnot v `release/evidence/generated/release-check-results.json` je `pass`.
4. Ověřit `release/RELEASE_MANIFEST.json`, čerstvé důkazy a čistý pracovní strom.

## Stav důkazů

- Lock soubory jsou uzamčené a frozen bootstrap prochází.
- Backendová a frontendová coverage překračují nezměněné prahy.
- PostgreSQL 17/pgvector integrace, Alembic, Compose, Playwright, backup a izolovaný restore procházejí.
- Source/image SBOM, secret scan a vulnerability gate procházejí.
- Matice dohledatelnosti uzavírá 1000 z 1000 požadavků konkrétní implementací, testem a čerstvým release důkazem.

## Bezpečnost

Do repozitáře nejsou vloženy produkční klíče, hesla, tokeny, runtime databáze, zálohy ani uživatelská data. Syntetické hodnoty jsou omezené na testovací a CI prostředí.
