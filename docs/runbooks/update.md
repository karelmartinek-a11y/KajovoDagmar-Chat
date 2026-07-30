# Runbook: update

## Předpoklady
Ověřený release manifest, oprávněný provozovatel, záloha před změnou, dostupné korelační ID a bezpečný přístup k infrastruktuře.

## Postup
1. Zaznamenejte verzi, čas, důvod a výchozí stav.
2. Proveďte pouze kanonický příkaz nebo krok popsaný v README/deployment konfiguraci; změny konfigurace aplikace dělejte přes UI.
3. Sledujte health, audit, frontu, chybovost a stav databáze; při nejistém stavu operaci zastavte.

## Ověření
Ověřte připravenost, přihlášení, integritu dat, worker/outbox, poslední zálohu a relevantní funkční smoke scénář. U obnovy ověřte cílový čas a auditní konzistenci.

## Návrat
Použijte předchozí neměnný image digest a kompatibilní databázový bod; pokud migrace není zpětně kompatibilní, proveďte roll-forward nebo obnovu předaktualizačního bodu. Výsledek zdokumentujte jako incident/provozní událost.
