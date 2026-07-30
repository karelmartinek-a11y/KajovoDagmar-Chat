# Observability

Logy jsou strukturované, korelované a centrálně redigované. Audit zachycuje
bezpečnostní a stavové změny v ověřitelném hashovém řetězci. Obsah promptů,
konverzací, přepisů, zvuku a paměti nesmí být metrický label ani provozní log.

Prometheus endpoint `/api/v1/metrics` lze skrýt bearer tokenem. Kardinalita je
omezena na konečné katalogy metod, normalizovaných tras, tříd stavů, schopností
a výsledků. Metriky pokrývají HTTP, realtime, STT/TTS, orchestraci,
poskytovatele, joby, hledání, oznámení, exporty a zálohy. OTLP trasy nesou
identitu služby, verzi `1.0.0`, prostředí, komponentu a revizi SSOT `v0021`;
instrumentované hranice zahrnují HTTP, databázovou transakci, realtime relaci,
orchestraci, externího poskytovatele a worker.

Kanonický 30denní katalog SLI/SLO je v
`deployment/observability/slo.json`. Závazná pravidla rychlého a pomalého
vyčerpání error budgetu jsou v
`deployment/observability/prometheus-rules.yaml`. Každý alert má stabilní
název, závažnost, SLO nebo schopnost a konkrétní runbook. Deduplikaci,
seskupení, ztišení plánované údržby a doručení zajišťuje provozní Alertmanager;
jeho cílové adresy a přístupové údaje jsou výhradně environmentální tajemství
a nejsou součástí repozitáře.

Liveness ověřuje proces, startup identitu sestavení a readiness databázi i stav
instance. Administrátorský provozní přehled rozlišuje `ready`, `limited`,
`unknown` a doplňuje dopad a nápravnou akci. Incident začíná prvním
nepotlačeným kritickým alertem, časová osa používá correlation ID a auditní
události a uzavírá se až po obnovení SLI, ověření integrity a zapsání příčiny
podle `docs/runbooks/incident.md`.
