# REST API v1

Kanonický kontrakt je generován z běžící FastAPI aplikace na `/api/v1/openapi.json`. Všechny chráněné endpointy vyžadují serverovou relaci; stavové změny navíc hlavičku `X-CSRF-Token`. Chyba má stabilní `code`, české `message`, volitelné `details` a `correlation_id`.

Skupiny: inicializace a autentizace, profil a relace, konverzace, historie, paměť, nastavení, poskytovatelé/modely, e-mail, exporty, diagnostika, zálohy a realtime ticket. Vygenerované TypeScript typy se ověřují v kontraktační bráně.
