# Bezpečnostní model

Produkce používá HTTPS, HSTS, CSP, zákaz framingu, kontrolu originu, Secure HttpOnly SameSite=Strict cookies a serverové zneplatnění relací. Hesla jsou Argon2id, 14–128 znaků, porovnávaná s lokálním seznamem kompromitovaných hodnot. Resetovací a ověřovací tokeny jsou náhodné, jednorázové, expirované a uložené pouze jako účelově oddělený digest.

API klíče a SMTP hesla jsou AES-256-GCM šifrována kořenovým tajemstvím mimo databázi. Tajemství se nevrací z API, nepatří do auditů, exportů, promptů ani logů. Rate limit a progresivní dočasné omezení jsou serverové. Při selhání kryptografie, úložiště relací nebo autorizace systém odmítne přístup.

Ověření poskytovatele načítá katalog pouze autentizovaným požadavkem a synchronizuje jej transakčně. Neúspěšný nebo neúplný refresh ponechá poslední funkční katalog beze změny; modely, které z nového úspěšného katalogu zmizí, jsou označeny jako nedostupné. Audit ukládá pouze výsledek, počet modelů a verzi politiky, nikdy klíč ani jeho významnou část.

Prompt injection se považuje za nedůvěryhodný obsah. Model nemůže přímo měnit data; návrh nástroje validuje orchestrátor a stavovou operaci provede autorizovaný use case s potvrzením a idempotencí.
