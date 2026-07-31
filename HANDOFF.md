# HANDOFF

## Stav

Produkční stav je stabilní, ale celkový verdikt je **BLOCKER** kvůli jediné
výslovné akceptační podmínce. Původní run `30503011395` ani při rerun attempt 4
nedostal GitHub-hosted runner: job `source-and-unit` skončil před spuštěním
jakéhokoliv kroku s billing/spending-limit anotací, integrační a release job byly
přeskočeny. Příkaz
`gh run watch 30503011395 --repo karelmartinek-a11y/KajovoDagmar-Chat --exit-status`
skončil návratovým kódem `1`.

Novější hosted runy přitom skutečně běžely. Run `30604831976` dokončil
`source-and-unit`, `integration`, `release-gate` i `deploy-production` úspěšně
a nasadil přesný commit `cb65f33a476ea7936ce036a2349fe7c45f409cd1`.
Požadavek však dovoluje `PASS` pouze tehdy, když runner dostane i rerun původního
runu, proto není tento platformní rozpor označen falešným PASS.

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

## Potřebný externí krok

GitHub Billing nebo GitHub Support musí odstranit billing gate, který nadále
postihuje historický run soukromého repozitáře. Poté je nutné znovu spustit
`30503011395` a ověřit, že `source-and-unit`, `integration` a `release-gate`
skutečně dostaly runner a nebyly přeskočeny. Do té doby zůstává aktivní poslední
ověřený produkční release; není nutný ani bezpečný žádný zásah do serveru.
