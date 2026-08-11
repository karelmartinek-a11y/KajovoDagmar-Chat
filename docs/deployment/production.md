# Produkční nasazení

Produkční doména je `chat.hcasc.cz`. Hostitelský Nginx ukončuje TLS a jako jediný
proxyuje na `127.0.0.1:18180`. PostgreSQL nemá publikovaný port. Produkční
Compose projekt se vždy jmenuje `kajovodagmar-chat`; nepoužívá projekt, síť,
volume, port ani server block jiné aplikace.

## Rozložení hostitele

```text
/srv/hcasc/kajovodagmar-chat/
├── repo/                         # bare mirror s read-only deploy key
├── releases/<40-char-sha>/       # neměnné checkouty
├── current -> releases/<sha>
└── shared/
    ├── env/production.env        # root:root 0600
    ├── secrets/                  # root:root 0600
    ├── data/
    ├── backups/pgbackrest/
    ├── logs/
    └── tools/
```

Runtime uživatel je `kajovodagmar-chat`; SSH deploy uživatel
`deploy-kajovodagmar-chat` smí přes forced command spustit pouze
`/usr/local/sbin/deploy-kajovodagmar-chat <SHA>`. Server používá jiný,
read-only GitHub deploy key než GitHub Actions.

## Kanonický deployment

Workflow nasazuje pouze po úspěchu jobu `release-gate`, z GitHub Environment
`production`, a předává přesný `${{ github.sha }}`. Serverový entrypoint:

1. validuje 40znakový SHA a získá `flock`;
2. ověří disk, GitHub host key, read-only přístup a příslušnost SHA do `main`;
3. vytvoří neměnný release a exact-SHA image;
4. vytvoří source i image SBOM a provede High/Critical vulnerability gate;
5. vytvoří a ověří šifrovaný předmigrační pgBackRest backup;
6. provede Alembic migrace;
7. spustí pouze projekt `kajovodagmar-chat`;
8. ověří interní i veřejný health, branding a `dagmar.hcasc.cz`;
9. atomicky přepne `current` a zapíše aktivní SHA;
10. při kritické chybě obnoví předchozí zachovaný release.

Po spuštění nové verze workflow synchronizuje heslo účtu `Karmar78` s aktuální
hodnotou Environment secretu `PASS`. Tajemství jde do deploy procesu pouze přes
standardní vstup, není součástí příkazové řádky ani logu. Synchronizace zruší
existující přihlášené relace a obnoví případné omezení po chybných pokusech.
Chybějící hodnota nebo heslo mimo politiku 8–128 znaků celý deploy zastaví.

Neurčité `latest`, `git pull`, checkout `main`, vypnutá TLS validace a globální
Compose operace nejsou součástí postupu.

## Zálohy, restore a rollback

`kajovodagmar-chat-backup.timer` spouští denní diferenciální backup, kontrolu
pgBackRest repository a kontrolu volného místa. Retence je definována
verzovanou pgBackRest konfigurací.

Skutečný izolovaný restore drill:

```bash
sudo /usr/local/sbin/restore-drill-kajovodagmar-chat
```

Drill obnovuje do jednorázového Compose projektu a samostatného volume, ověří
integritu instance, konverzací, paměti a auditu a testovací stack odstraní.
Živou databázi nepřepisuje.

Rollback na zachovaný kompatibilní release:

```bash
sudo /usr/local/sbin/rollback-kajovodagmar-chat <40-char-sha>
```

Rollback znovu vytvoří ověřený předmigrační bod. Pokud starší release není
kompatibilní s aktuálním schématem, automatický návrat se nesmí vydávat za
databázový downgrade; použije se roll-forward nebo ověřený předmigrační restore.

Inicializační tajemství je uloženo mimo checkout. Oprávněný administrátor je
čte přímo na serveru:

```bash
sudo cat /srv/hcasc/kajovodagmar-chat/shared/secrets/initialization-secret
```

## Ověření aktivního release

Po každém automatickém nasazení operátor porovná všechny tři nezávislé
identifikátory. GitHub `headSha`, obsah
`shared/data/active-release-sha` a cíl symlinku `current` musí být shodné:

```bash
sudo cat /srv/hcasc/kajovodagmar-chat/shared/data/active-release-sha
sudo readlink -f /srv/hcasc/kajovodagmar-chat/current
sudo docker ps \
  --filter label=cz.hcasc.application=kajovodagmar-chat \
  --format '{{.Names}} {{.Status}} {{.Ports}}'
```

Veřejná a izolační kontrola nesmí používat inicializační tajemství:

```bash
curl -fsS https://chat.hcasc.cz/api/v1/health/ready
curl -fsS https://dagmar.hcasc.cz/ >/dev/null
sudo ss -lnt | grep '127.0.0.1:18180'
```

Ready odpověď může před prvním přihlášením oprávněného administrátora uvádět
stav `uninitialized`. PostgreSQL nesmí být mezi hostitelskými listening porty
a všechny kontejnery projektu musí mít nulový počet restartů.
