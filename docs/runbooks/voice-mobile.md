# Mobilní hlasový chat a diagnostika providerů

## Co web garantuje

Při zahájeném rozhovoru na viditelné stránce aplikace požádá o Screen Wake Lock,
pokud jej prohlížeč podporuje. Změna route ani přechod do jiné aplikace neposílá
`session.end`; serverový turn pokračuje a po návratu se replayují uložené události.

Mobilní operační systém může mikrofon nebo Web Audio pozastavit při skrytí stránky,
zamčení obrazovky, telefonním hovoru nebo změně audio zařízení. Čistý web proto
nemůže garantovat nepřetržité snímání při zamčeném telefonu. Po návratu se stav
tracku a AudioContextu ověří; obnova proběhne automaticky, případně jedním
uživatelským gestem přes **Obnovit mikrofon**. Aplikace nezobrazuje „naslouchá“,
dokud skutečně nepřicházejí čerstvé PCM rámce.

## Diagnostika

Každý provider failure se třídí podle capability (`transcription`, `conversation_model`,
`speech_synthesis`, `embeddings`), endpointu, modelu a HTTP statusu. Auditní detail
může obsahovat pouze status, provider request ID, typ/kód chyby a bezpečný parametr;
nikdy prompt, audio, Authorization, cookie ani tajemství. Korelaci hledej podle
serverového `correlation_id` a provider request ID.

Typické kódy:

- `provider_invalid_parameter`: nekompatibilní payload nebo model;
- `provider_rate_limited`: rate limit;
- `provider_quota`: kvóta/billing;
- `provider_timeout`: timeout;
- `provider_error`: jiná provider 5xx nebo síťová chyba.

Chyba TTS je degradovatelná: textová odpověď zůstává v přepisu a lze použít
**Zkusit přehrát hlas znovu**. Retry posílá pouze retry audio událost a nevytváří
nový textový turn.

## Manuální mobilní protokol

Na Android Chrome a iOS Safari ověř: zahájení hovoru, přepnutí na jinou aplikaci
na 10 a 60 sekund, zamknutí/odemknutí, telefonní přerušení, Bluetooth připojení a
odpojení. Zaznamenej, zda se po návratu zobrazí pravdivý stav, zda se nezduplikují
zprávy a zda je třeba tlačítko obnovy. Emulace Playwrightu nenahrazuje fyzické
zařízení; bez fyzického zařízení se manuální test označuje jako neprovedený.
