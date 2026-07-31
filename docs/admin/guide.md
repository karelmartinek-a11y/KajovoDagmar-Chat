# Administrátorská příručka

Novou instanci inicializujte jednorázovým tajemstvím a účtem `Karmar78`. V Profilu ověřte e-mail a stav obnovy. V Nastavení vložte poskytovatelský klíč do zabezpečeného pole. Uložení klíč ihned ověří, načte živý `/v1/models` katalog a nastaví doporučenou sestavu; tlačítko `Znovu ověřit klíč a nabídku modelů` slouží k ručnímu obnovení. Klíč se ukládá pouze šifrovaně a nikdy se nevrací klientovi.

## Modelové role

Dagmar používá pět samostatných rolí: `conversation_model` je mozek živého rozhovoru, `transcription_model` převádí mikrofon na text, `speech_model` převádí text na hlas, `embedding_model` hledá významově související informace v paměti a `summary_model` vytváří názvy a shrnutí uzavřených rozhovorů. `voice_id` není model; je to samostatná barva hlasu.

Backend katalog klasifikuje podle ID modelu, verzovaných pravidel rodin a bezpečného denylistu. Frontend nedopočítává kompatibilitu a každá karta dostává pouze možnosti své role. Doporučovací politika má verzi `2026-07-31.v1`: preferuje `gpt-5-mini`, `gpt-4o-transcribe`, `gpt-4o-mini-tts`, `text-embedding-3-large` a `gpt-5-mini`; pokud nejsou dostupné, použije deterministický fallback stejné role. Ruční výběr zůstává možný.

Při změně embedding modelu se aktivní vyhledávací dokumenty označí jako zastaralé a reindexace se auditovaně vyžádá. Vektory se vždy identifikují modelem a rozměrem; během přechodu se nesmí míchat starý a nový index.

Pokud nový klíč neposkytuje model pro některou roli, textový chat může zůstat funkční, ale dotčená hlasová nebo paměťová schopnost se zobrazí jako nepřipravená s konkrétním důvodem.

Diagnostika zobrazuje health, frontu, poskytovatele, poslední zálohu a korelační identifikátory bez soukromého obsahu. Exporty poskytují lidsky čitelný i strukturovaný formát bez tajemství. Zálohu a obnovu spouštějte pouze řízeným postupem a výsledek ověřte restore testem.
