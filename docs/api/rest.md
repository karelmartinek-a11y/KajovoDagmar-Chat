# REST API v1

Kanonický kontrakt je generován z běžící FastAPI aplikace na `/api/v1/openapi.json`. Všechny běžné chráněné endpointy vyžadují serverovou relaci; stavové změny navíc hlavičku `X-CSRF-Token`. Výjimkou je `POST /api/v1/realtime/ticket`, který může použít i serverový bearer key se scope `voice.realtime.test`. Chyba má stabilní `code`, české `message`, volitelné `details` a `correlation_id`.

Skupiny: inicializace a autentizace, profil a relace, konverzace, historie, paměť, nastavení, poskytovatelé/modely, e-mail, exporty, diagnostika, zálohy a realtime ticket. Vygenerované TypeScript typy se ověřují v kontraktační bráně.

Servisní voice key je dlouhodobý, ale ručně revokovatelný. Je uložen mimo checkout v produkčním secret store; plaintext se nevrací z API. Každé jeho použití se zapíše do auditního řetězce a vytvoří neacknowledged upozornění pro účet `Karmar78`.
