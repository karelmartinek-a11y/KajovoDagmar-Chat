# Bezpečnostní model

Produkce používá HTTPS, HSTS, CSP, zákaz framingu, kontrolu originu, Secure HttpOnly SameSite=Strict cookies a serverové zneplatnění relací. Hesla jsou Argon2id, 14–128 znaků, porovnávaná s lokálním seznamem kompromitovaných hodnot. Resetovací a ověřovací tokeny jsou náhodné, jednorázové, expirované a uložené pouze jako účelově oddělený digest.

API klíče a SMTP hesla jsou AES-256-GCM šifrována kořenovým tajemstvím mimo databázi. Tajemství se nevrací z API, nepatří do auditů, exportů, promptů ani logů. Rate limit a progresivní dočasné omezení jsou serverové. Při selhání kryptografie, úložiště relací nebo autorizace systém odmítne přístup.

Prompt injection se považuje za nedůvěryhodný obsah. Model nemůže přímo měnit data; návrh nástroje validuje orchestrátor a stavovou operaci provede autorizovaný use case s potvrzením a idempotencí.
