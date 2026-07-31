# HANDOFF

## Stav

Repozitářová, CI a produkční etapa je **PASS**. Billing omezení původního runu
`30503011395` bylo odstraněno; hosted run `30600855499` poprvé dokončil všechny
tři povinné CI joby. Produkční run `30603571733` poté úspěšně nasadil izolovaný
stack a následný automatický run `30604131291` ověřil další push i deployment
přesného commitu.

## Ověřené provozní důkazy

- Lokální `make release-check` končí `0` a uzavírá 39 z 39 bran.
- `source-and-unit`, `integration`, `release-gate` a `deploy-production`
  skutečně běžely na GitHub hosted runnerech a skončily `success`.
- `chat.hcasc.cz` používá platné TLS, HTTP přesměrování na HTTPS a samostatný
  Nginx server block s loopback upstreamem `127.0.0.1:18180`.
- PostgreSQL není publikovaný na hostiteli; Compose projekt, sítě, volumes,
  uživatelé, klíče, logy a zálohy jsou oddělené.
- Produkční diferenciální backup, pgBackRest check a izolovaný restore drill
  prošly. Restore ověřil PostgreSQL 17.10, pgvector 0.8.6 a revizi v0021.
- Rollback z automaticky nasazeného commitu na předchozí funkční release i
  následný návrat dopředu prošly se zachováním databázového stavu a health.
- `dagmar.hcasc.cz` zůstalo během intake, deploymentu, restore a rollbacku
  funkční.

## Administrátorský krok

Aplikace je záměrně ve stavu `uninitialized`. Oprávněný administrátor může
inicializační tajemství přečíst pouze přímo na serveru:

```bash
sudo cat /srv/hcasc/kajovodagmar-chat/shared/secrets/initialization-secret
```

Hodnota není v Git historii, GitHub secrets výpisu ani Actions logu.
