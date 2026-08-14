# Oprava všech odchylek z `audit14082026.md`

## 0. Účel dokumentu

Tento dokument je implementační zadání pro úplné odstranění **všech 241 odchylek** evidovaných v `audit14082026.md`. Je určen pro paralelní práci více seniorních programátorů. Každý auditní identifikátor níže má vlastní cílový stav, požadovanou implementaci a akceptační kritéria; programátor nemusí znát celý původní audit ani ostatní pracovní balíky, pouze musí respektovat zde uvedené závislosti.

### Normativní pravidla

1. Neodstraňovat funkcionalitu, nepřepisovat problém placeholderem, mockem, skrytým filtrem ani potlačením výjimky.
2. Oprava je uzavřena pouze tehdy, když je odstraněna kořenová příčina, existuje regresní test a projdou relevantní quality gates.
3. Při změně veřejného API zachovat zpětnou kompatibilitu, pokud konkrétní úkol výslovně nevyžaduje změnu kontraktu. Pokud je změna kontraktu nutná, upravit backend, frontend i contract tests atomicky.
4. Databázové změny provádět novou forward-only Alembic migrací; neupravovat již publikované migrace zpětně.
5. Failure/expired/denied stavy se nesmí „opravovat“ ručním `session.commit()` rozesetým po services. Použít jednotnou transakční semantiku definovanou ve Foundation F2.
6. Search/index lifecycle se nesmí opravovat pouze filtrem při čtení. Kanonická data, `SearchDocument` a aktuální `SearchEmbedding` musí mít explicitní lifecycle a hard purge musí odstranit odvozený obsah.
7. Model capability se nesmí odvozovat jako množina klíčů dictu. Použít jediný typovaný kontrakt z Foundation F1.
8. Každý worker smí claimovat pouze job kinds, pro které má handler.
9. Auditní hash chain musí být serializovaný napříč webem, workerem i backup-agentem stejným databázovým lockem.
10. Pro UI chyby musí být chybová zpráva viditelná uživateli a neúspěšná operace nesmí zahodit uživatelský vstup.

## 1. Povinné ověření po implementaci

Repo používá Python 3.12, Node 22.23.2, npm 10.9.8, pytest, Ruff, mypy, Vitest a Playwright. Každý pracovní balík musí spustit alespoň relevantní cílené testy. Před finálním merge celé opravy musí projít:

```bash
make bootstrap
make source-check format-check lint typecheck test test-contract
docker compose -f deployment/compose.test.yaml up -d --wait
KAJOVODAGMAR_DATABASE_URL=postgresql+asyncpg://kajovodagmar:test-only-password@127.0.0.1:55432/kajovodagmar_test \
KAJOVODAGMAR_TEST_DATABASE_URL=postgresql+asyncpg://kajovodagmar:test-only-password@127.0.0.1:55432/kajovodagmar_test \
make migrate test-integration test-security test-ai
make release-check
```

Pro změny realtime hlasu navíc:

```bash
make test-voice-browser
```

Pro změny UI navíc relevantní Vitest/Playwright testy; pro změny security `make test-security`; pro backup/restore `make backup-check restore-check` v prostředí s požadovanými službami.

## 2. Paralelní orchestrace

### Foundation fáze — musí být sloučena před navazujícími balíky

- **F1 Provider capability contract** — vlastník P1. Primární soubory: `providers/contracts.py`, `providers/model_roles.py`, `providers/openai_compatible.py`, `orchestration/service.py`, `worker.py`. Zavře CHAT-001 až CHAT-006 a vytvoří kontrakt pro další provider úkoly.
- **F2 Durable failure transactions** — vlastník P2. Primární soubory: `db/session.py`, `errors.py`, orchestration/identity/provider/notification call-sites. Zavede jediný mechanismus „commit state + return error“ bez commitů uvnitř services.
- **F3 Search lifecycle + vector invariant** — vlastník P3. Primární soubory: `db/models.py`, nová migrace, `worker.py`, `search/service.py`. Zavře SEARCH-001/002, RET-001/002 a VECTOR-001/002 a vytvoří API pro ostatní search opravy.
- **F4 Job ownership** — vlastník P4. Primární soubory: `jobs/service.py`, `worker.py`, `deployment/backup_agent.py`. Každý consumer claimuje explicitní allow-list.
- **F5 Audit chain serialization** — vlastník P5. Primární soubory: `audit/service.py`, nová migrace nebo společný advisory-lock mechanismus, `deployment/backup_agent.py`.

### Paralelní fáze A — po Foundation

- **P6 Realtime/Voice**: VOICE-001 až VOICE-032.
- **P7 Orchestrace a confirmation state machine**: TX-002 až TX-005, ORCH-001 až ORCH-016.
- **P8 Memory + conversation canonical API**: MEM-001 až MEM-022, CONV-001 až CONV-006.
- **P9 Settings/model recommendations**: SET-001 až SET-020.
- **P10 History**: HIST-001 až HIST-017.
- **P11 Auth/security/notifications**: AUTH-001 až AUTH-016, SEC-001 až SEC-004, AUDIT-003 až AUDIT-007.
- **P12 Jobs/backup/export/operations**: JOB-001 až JOB-011, BACKUP-002/003, EXPORT-001 až EXPORT-003, OPS-001 až OPS-005.
- **P13 Shared frontend UX**: TEXT-001, CHAT-022/023, API-001/002, UI-001 až UI-023.

### Paralelní fáze B — integrační stabilizace

Po merge předchozích balíků jeden integrační vlastník provede full gates, odstraní konflikty bez redukce scope, ověří auditní coverage 241/241 a nepřijme „known issue“ jako uzavření nálezu.

## 3. Přesná zadání po jednotlivých auditních odchylkách

### 1. CHAT-001 — canonical capability name
**Implementace:** Vytvořit jediný typovaný capability kontrakt. Schopnost strukturovaného JSON schema výstupu se musí jmenovat stejně v katalogu, `ChatRequest` i provideru; doporučený kanonický název `structured_outputs`. `OpenAICompatibleProvider.chat()` nesmí kontrolovat neexistující `json_schema` klíč.
**Akceptace:** model se `structured_outputs=true` odešle s `text.format.type=json_schema`; model bez této schopnosti je odmítnut před orchestration call, nikoli až po parsování odpovědi.

### 2. CHAT-002 — boolean capabilities nesmí být množina klíčů
**Implementace:** Nahradit `frozenset(model.capabilities or {})` převodem pouze enabled capabilities nebo lépe typovaným objektem/mapou `dict[str,bool]`. Stejný helper používat v orchestration i workeru.
**Akceptace:** capability s hodnotou `false` se nikdy nechová jako aktivní; regression test se smíšeným dict `{"structured_outputs": true, "temperature": false}`.

### 3. CHAT-003 — schema request a parser musí být atomický kontrakt
**Implementace:** Pokud orchestrace očekává `ModelDecision`, provider musí povinně použít schema-capable cestu. Neprovádět `json.loads` na běžném free-text výstupu. Při modelu bez strukturovaných výstupů vrátit `CapabilityUnavailableError` před HTTP call.
**Akceptace:** free-text provider odpověď nemůže způsobit náhodný `provider_invalid_structure` v cestě, kde nebylo schema vyžádáno.

### 4. VOICE-001 — reset klientské event sequence
**Implementace:** Při úplném ukončení nezávislé session resetovat `VoiceClient.sequence=0`. Rozlišit full end od reconnect/resume, kde se sekvence zachovává.
**Akceptace:** dvě po sobě jdoucí voice sessions v jedné SPA posílají první `session.start` vždy se sequence 1.

### 5. VOICE-002 — reset server cursoru klienta
**Implementace:** Při full end resetovat `lastServerSequence=0`; při resume jej zachovat.
**Akceptace:** první `connection.ready` nové session se sequence 1 není ignorován jako duplicate.

### 6. VOICE-003 — reset audio frame sequence
**Implementace:** Při full end resetovat `frameSequence=0` a timestamp posledního audio rámce. Reconnect stejné session musí zachovat hodnotu potřebnou pro resume.
**Akceptace:** první audio frame druhé session má frame sequence 1 a server nevydá `audio_sequence_gap`.

### 7. TX-001 — jednotná durable failure transakce
**Implementace:** Zavést v `errors.py`/DB UoW explicitní typ chyby nebo výsledek, který dovolí uložit diagnostický/bezpečnostní stav a teprve potom vrátit HTTP error. Services nesmí samy commitovat. Pro operace s potenciálními částečnými side effects použít savepoint: side effect rollbacknout, poté mimo savepoint uložit `failed/expired/denied` a durable audit.
**Akceptace:** test pro každou níže uvedenou failure cestu potvrzuje, že HTTP/API chyba nastane a současně je stav/audit po nové DB session viditelný.

### 8. AUTH-001 — login counter musí přežít 401
**Implementace:** Neplatné heslo musí atomicky zvýšit `failed_login_count`, spočítat `restricted_until`, přidat audit a změny durable uložit před vrácením 401 podle F2.
**Akceptace:** pět po sobě jdoucích chybných loginů zvyšuje counter v DB a aktivuje restriction; správný login podle politiky counter resetuje.

### 9. SEARCH-001 — pouze jeden aktuální embedding na dokument/model
**Implementace:** V F3 změnit upsert tak, aby po úspěšné tvorbě nového embeddingu staré embeddingy stejného `document_id/model_id` byly odstraněny v téže transakci. Preferovat unikátní constraint `(document_id, model_id)` a update-in-place; `source_hash` ponechat jako metadata aktuálního vstupu.
**Akceptace:** po třech změnách memory existuje pro aktuální model právě jeden embedding.

### 10. SEARCH-002 — search používá jen aktuální embedding
**Implementace:** Semantic query smí joinovat pouze aktuální embedding odpovídající dokumentu. Pokud F3 používá unikátní `(document_id,model_id)`, query zjednodušit; jinak explicitně svázat se současným source hash/version.
**Akceptace:** stará verze textu po update neovlivní ranking.

### 11. RET-001 — hard purge musí odstranit SearchDocument
**Implementace:** Protože polymorfní `owner_id` nemůže mít jednoduchý FK na dvě tabulky, vytvořit explicitní purge lifecycle: před/ve stejné transakci jako hard delete memory/conversation smazat `SearchDocument` podle `owner_type+owner_id`. Centralizovat do search index service/repository.
**Akceptace:** po hard purge neexistuje odpovídající `SearchDocument`.

### 12. RET-002 — hard purge musí odstranit embeddingy
**Implementace:** Zajistit, že odstranění dokumentu cascade smaže všechny `SearchEmbedding`; nová migrace ověří FK `ON DELETE CASCADE` a purge test ověří nulový počet embeddings.
**Akceptace:** po hard purge není v DB původní `embedding_text` ani vector.

### 13. VECTOR-001 — runtime dimenzní invariant
**Implementace:** Zavést sdílenou konstantu/konfiguraci `SEARCH_VECTOR_DIMENSIONS=1536` používanou migrací/runtime validací. Před zápisem i query castem ověřit přesnou dimenzi; nekompatibilní provider vrátí řízenou capability/configuration chybu a dokument zůstane `stale=true`.
**Akceptace:** 1535/1537 vektor se nikdy neposílá do PostgreSQL castu a nevznikne raw DB error.

### 14. VECTOR-002 — deterministic provider 1536
**Implementace:** `DeterministicProvider.embed()` změnit na přesně 1536 dimenzí a sdílet invariant s F3.
**Akceptace:** deterministic indexing projde reálným pgvector schématem.

### 15. BACKUP-001 — oddělit job namespaces
**Implementace:** `JobService.claim()` musí přijmout povinný allow-list kinds. Běžný worker předá `set(self.handlers)`. Backup-agent zachová explicitní backup allow-list. Nikdo nesmí claimnout nepodporovaný kind.
**Akceptace:** souběžný worker + backup-agent: backup job může claimnout pouze backup-agent.

### 16. AUDIT-001 — serializovat web/worker audit append
**Implementace:** Před čtením posledního hash získat transakční PostgreSQL advisory lock se stabilním klíčem pro audit chain, nebo zamknout singleton chain-head row. Vložit event a uvolnit lock až commitem.
**Akceptace:** concurrency test s desítkami paralelních appendů vytvoří lineární chain a `verify_chain` vrátí true.

### 17. AUDIT-002 — backup-agent používá stejný lock
**Implementace:** `deployment/backup_agent.py::append_audit` musí před read-last/insert použít přesně stejný DB lock/protokol jako AUDIT-001.
**Akceptace:** paralelní audit z SQLAlchemy procesu a backup-agent psycopg procesu nevytvoří fork.

### 18. TEXT-001 — nezahazovat chybu ani draft
**Implementace:** `ChatPage.submitText()` musí `await` request v try/catch, zobrazit `Feedback`/snapshot error a vymazat textarea pouze po potvrzeném přijetí turnu. Během requestu blokovat duplicate submit.
**Akceptace:** simulovaný 500 zachová text v textarea a zobrazí chybu.

### 19. CHAT-004 — summary worker používá F1 capabilities
**Implementace:** `Worker.conversation_finalize()` musí používat stejný helper/typovaný capability kontrakt jako hlavní orchestrace, nikdy `frozenset(dict)`.
**Akceptace:** disabled capability není považována za aktivní v summary requestu.

### 20. CHAT-005 — primary model vyžaduje všechny potřebné schopnosti
**Implementace:** `_primary_model()` ověřuje konkrétní potřebné schopnosti pro zvolenou provider cestu: conversation endpoint + structured output. Nepoužívat neprázdný průnik.
**Akceptace:** model pouze s `responses=true` a bez structured outputs je odmítnut před voláním.

### 21. CHAT-006 — neodvozovat structured support jen z názvu modelu
**Implementace:** `classify_model()` smí z názvu inferovat pouze roli, nikoli neověřenou endpoint capability. Capability musí pocházet z advertised katalogu nebo z explicitního provider probe provedeného při verify.
**Akceptace:** neznámý model rodiny GPT bez advertised/probed structured support nemá automaticky `structured_outputs=true`.

### 22. CHAT-007 — kompatibilní provider bez Responses API
**Implementace:** Při verify zjistit podporovanou chat transport cestu. `openai_compatible` musí podporovat alespoň `responses` nebo `chat_completions`; runtime zvolí implementaci podle uložené capability. Pro chat-completions implementovat JSON schema/response_format mapování nebo model odmítnout jako neschopný strukturované odpovědi.
**Akceptace:** provider s pouze `/chat/completions` může projít, pokud umí požadované schema; jinak verify jasně označí chybějící capability.

### 23. CHAT-008 — normalizovat network errors list_models
**Implementace:** Zachytit `httpx.TimeoutException`, `NetworkError/RequestError` a převést na stabilní `DomainError` s capability `model_catalog`, bezpečnými details a correlation/request informací bez secretů.
**Akceptace:** timeout nepropadne jako raw exception.

### 24. CHAT-009 — normalizovat network errors chat
**Implementace:** Stejný mapper použít pro `/responses`/chat transport.
**Akceptace:** connection error vrátí řízenou 502/503 doménovou chybu a durable failed orchestration stav.

### 25. CHAT-010 — normalizovat network errors transcribe
**Implementace:** Stejný mapper pro transcription upload.
**Akceptace:** timeout transkripce vytvoří řízený realtime `error` event.

### 26. CHAT-011 — normalizovat network errors synthesize
**Implementace:** Ošetřit chyby při navázání i během streamu speech synthesis; převést na doménovou chybu, aniž by se ztratila již dostupná textová odpověď.
**Akceptace:** TTS výpadek vede na `assistant.audio.error`, text zůstává.

### 27. CHAT-012 — normalizovat network errors embed
**Implementace:** Embedding RequestError/Timeout převést na capability/search chybu; search cesta musí podle CHAT-017 fallbacknout na text search.
**Akceptace:** embedding outage neznefunkční textový chat.

### 28. CHAT-013 — validace catalog payload
**Implementace:** `list_models()` validovat přes Pydantic/explicitní parser; chybějící `id` nebo špatný typ vrátí `provider_invalid_response` s bezpečným detail count/index.
**Akceptace:** žádný raw `KeyError`.

### 29. CHAT-014 — validace transcription payload
**Implementace:** Ověřit, že `text` existuje a je string; jinak řízená `provider_invalid_response`.
**Akceptace:** malformed JSON body je doménová chyba.

### 30. CHAT-015 — validace embedding payload
**Implementace:** Ověřit `data`, pořadí, každý `embedding`, numeric hodnoty a dimenzi F3.
**Akceptace:** malformed embedding odpověď nezpůsobí KeyError/DB error.

### 31. CHAT-016 — robustní Responses text parser
**Implementace:** Implementovat parser podporující dokumentované validní textové struktury provider transportu a odmítnout pouze skutečně chybějící text; parser oddělit a unit-testovat varianty.
**Akceptace:** všechny podporované response shapes vrátí stejný text; neznámý shape dává stabilní error.

### 32. CHAT-017 — embedding failure fallback
**Implementace:** `_query_embedding()` zachytí všechny normalizované provider chyby z CHAT-027 a vrátí `(None,None)` s metrikou/logem; nikdy neskrývat programátorskou chybu typu AssertionError.
**Akceptace:** vypnutý embedding provider stále umožní full-text memory/history search a chat odpověď.

### 33. CHAT-018 — tvrdý context character budget
**Implementace:** `_context_messages()` musí vždy dodržet `max_characters`; pokud jediná zpráva limit překračuje, deterministicky ji oříznout bezpečným způsobem nebo ji vynechat podle explicitní politiky. Zvolenou politiku testovat.
**Akceptace:** součet předaných znaků nikdy nepřesáhne limit.

### 34. CHAT-019 — validace tool limit
**Implementace:** Modelové argumenty read tools validovat Pydantic schématem před použitím; `limit` musí být integer v 1..20. Neprovádět nechráněné `int()` nad libovolným objektem.
**Akceptace:** string/array/object limit vrátí `tool_arguments_invalid`.

### 35. CHAT-020 — validace UUID tool arguments
**Implementace:** Pro každý state tool vytvořit typované argument schema s UUID/versions; `_normalize_action` dostává již validovaný objekt.
**Akceptace:** neplatné UUID nikdy nevyvolá raw `ValueError`.

### 36. CHAT-021 — skutečná idempotence user turn
**Implementace:** K idempotency key uložit/porovnat request hash minimálně z normalized content/input_mode/language. Stejný key + stejný hash vrátí existing; stejný key + jiný hash vrátí 409 idempotency conflict.
**Akceptace:** regression test obou variant.

### 37. CHAT-022 — text turn mutex
**Implementace:** Chat UI zavede `textBusy`; submit button/textarea submit se zablokuje po dobu requestu. Serverovou idempotenci ponechat jako druhou ochranu.
**Akceptace:** dvojklik vytvoří právě jeden turn.

### 38. CHAT-023 — koordinace text vs voice state
**Implementace:** Definovat povolenou tabulku stavů. Během `processing/responding/reconnecting` zakázat nový textový turn, nebo jej explicitně queueovat jedním mechanismem; preferováno zakázat s viditelným stavem, aby se nemíchaly turny.
**Akceptace:** UI nedovolí souběžně poslat text během běžící hlasové odpovědi.

### 39. API-001 — bezpečné parsování non-JSON odpovědi
**Implementace:** API wrapper čte content-type; u JSON parse JSON, jinak text. Pro non-2xx non-JSON vytvoří `ApiError` s generickou zprávou, statusem a correlation ID z headeru; nikdy nevyhodí `SyntaxError` z `response.json()`.
**Akceptace:** HTML 500 se zobrazí jako stabilní `ApiError`.

### 40. API-002 — normalizovat fetch/network errors
**Implementace:** Zachytit `TypeError`/AbortError z fetch, mapovat na `ApiError('network_error',...)`; zachovat cause pro diagnostiku, ne pro UI secret output.
**Akceptace:** všechny stránky dostávají stejný error typ.

### 41. VOICE-004 — reset transcriptu nové session
**Implementace:** Full session reset nastaví `transcript=[]`; reconnect stejné session ho zachová.
**Akceptace:** druhý nový rozhovor začíná prázdným transcript panelem.

### 42. VOICE-005 — reset partial transcript
**Implementace:** Full end/start vyčistí `partialTranscript`; reconnect používá serverový partial state.
**Akceptace:** partial z předchozí session se nezobrazí v nové.

### 43. VOICE-006 — reset lastAssistantText
**Implementace:** Full end nastaví `lastAssistantText=null` a `audioRetryAvailable=false`.
**Akceptace:** retry po nové session nikdy nepřehrává starou odpověď.

### 44. VOICE-007 — reset generation při novém rozhovoru
**Implementace:** Full end nastaví generation na počáteční hodnotu; increment jen při resume stejné session.
**Akceptace:** nový session start neposílá zděděnou generation.

### 45. VOICE-008 — korektně ukončit text-only conversation
**Implementace:** `VoiceClient.end()`/nová conversation controller vrstva při existujícím `conversationId` bez open websocketu zavolá `POST /conversations/{id}/end` s `user_ended`; end musí být idempotentní.
**Akceptace:** text-only chat po „Ukončit rozhovor“ má DB state completed.

### 46. VOICE-009 — text-only close spustí finalizaci
**Implementace:** Ukončení z VOICE-008 musí jít přes `ConversationService.end`, aby vznikl `conversation.closed` outbox a finalization/index jobs.
**Akceptace:** po close vznikne summary/index pipeline stejně jako u voice session.

### 47. VOICE-010 — bezpečný websocket JSON parser
**Implementace:** `onMessage` obalit parse/validate schématem; malformed server event přepne spojení do řízeného error/resync stavu, ne unhandled rejection.
**Akceptace:** neplatný frame nezabije event loop.

### 48. VOICE-011 — cleanup po částečně neúspěšném startu
**Implementace:** `start()` musí při catch zavolat interní idempotentní cleanup: stop tracks, disconnect nodes, close newly-created context/socket, release wake lock, clear timers.
**Akceptace:** po start failure nezůstane live microphone track.

### 49. VOICE-012 — lifecycle track listenerů
**Implementace:** Uchovávat reference listenerů a při rebind/end je odstranit, nebo používat `onended/onmute/onunmute` properties s explicitním resetem.
**Akceptace:** po 5 start/end cyklech každý track event vyvolá handler jednou.

### 50. VOICE-013 — zotavení z klientského hard backpressure
**Implementace:** Zavést monitor `bufferedAmount`/polling; po poklesu pod soft threshold explicitně nabídnout/automaticky provést resume podle bezpečné state machine, znovu enable track a změnit state.
**Akceptace:** hard backpressure není permanentní pause bez cesty návratu.

### 51. VOICE-014 — zotavení ze server flow_control hard
**Implementace:** Definovat server event pro uvolnění flow control nebo klientský explicitní resume handshake. Server po stabilizaci přijme `microphone.resume`; klient má viditelné tlačítko/cestu a track znovu zapne.
**Akceptace:** flow-control hard lze obnovit bez restartu celé session.

### 52. VOICE-015 — sjednotit onerror/onclose state machine
**Implementace:** `onerror` nesmí provést terminální fail, pokud `onclose` bude reconnectovat. Jeden centralizovaný connection-loss handler rozhodne reconnect vs terminal error.
**Akceptace:** při simulovaném socket error+close nevznikají protichůdné stavy.

### 53. VOICE-016 — shared resume state nebo single-process invariant
**Implementace:** Produkční řešení nesmí záviset na process-local dict bez explicitního invariant. Preferováno uložit resume metadata do sdíleného backendu (Redis/DB) nebo routing sticky/session ownership; pokud architektura garantuje jednu web repliku, v deploymentu/readiness to vynutit a zabránit scale-out bez shared store.
**Akceptace:** definovaný deployment má deterministické resume i při podporovaném počtu replik; test/release gate invariant kontroluje.

### 54. VOICE-017 — unexpected websocket exception suspend/cleanup
**Implementace:** V `handle_realtime` zachytit očekávané provozní `Exception` na boundary, zalogovat bezpečně, suspendovat aktivní conversation stejně jako disconnect, poté korektně uzavřít socket. `CancelledError` nepřevádět.
**Akceptace:** simulovaná runtime chyba zachová resume state nebo conversation bezpečně ukončí.

### 55. VOICE-018 — unexpected process_text_turn errors
**Implementace:** Po normalizaci provider errors doplnit boundary catch, který odešle generický `error` event s correlation ID a uloží failed orchestration. Programátorské chyby logovat s exception, ne posílat detail klientovi.
**Akceptace:** klient vždy dostane terminální/obnovitelný event.

### 56. VOICE-019 — unexpected process_audio_turn errors
**Implementace:** Stejná boundary politika jako VOICE-018 v audio cestě a vždy reset `turn_finalizing`.
**Akceptace:** audio turn se po chybě nezasekne permanentně finalizing.

### 57. VOICE-020 — partial transcription task error handling
**Implementace:** Zachytit normalizované provider network errors, inkrementovat metriku unavailable a task ukončit bez unhandled exception.
**Akceptace:** výpadek partial transcription neovlivní final transcription.

### 58. VOICE-021 — realtime text respektuje language session
**Implementace:** `ConnectionState` musí uchovat language při `session.start`; `process_text_turn` používá tento jazyk pro `UserTurn`.
**Akceptace:** en/de session nevytváří user turn s `cs`.

### 59. VOICE-022 — TTS používá session language
**Implementace:** `process_text_turn` předá skutečný state language do `synthesize`.
**Akceptace:** language argument TTS odpovídá conversation.

### 60. VOICE-023 — audio retry používá session language
**Implementace:** retry TTS čte language ze state, ne hardcoded `cs`.
**Akceptace:** retry v `de` session zůstává `de`.

### 61. VOICE-024 — max-duration finalization language
**Implementace:** `receive_audio`/state musí předat skutečný language do `finalize_audio_turn` i při max duration.
**Akceptace:** transcriber dostane session language.

### 62. VOICE-025 — VAD finalization language
**Implementace:** stejné pro server VAD ukončení.
**Akceptace:** žádný hardcoded `cs` v finalize call-sites.

### 63. VOICE-026 — partial transcription language
**Implementace:** partial task používá session language.
**Akceptace:** code search v realtime flow nenajde hardcoded `"cs"` tam, kde má být state language.

### 64. VOICE-027 — finishTurn language
**Implementace:** klient ukládá aktivní language a `finishTurn()` jej posílá.
**Akceptace:** request payload odpovídá start language.

### 65. VOICE-028 — HTTP sendText language
**Implementace:** `VoiceClient`/ChatPage používá effective conversation language, ne literal `cs`.
**Akceptace:** HTTP turn v EN conversation nese `en`.

### 66. VOICE-029 — server reset při novém session.start na stejném socketu
**Implementace:** Po `session.end` resetovat session-scoped audio sequence/timestamps/partial/vad/last assistant a před novým `session.start` inicializovat čistý session state; connection event sequence může zůstat socket-scoped jen pokud klientský protokol to explicitně definuje.
**Akceptace:** start→end→start na jednom websocketu funguje.

### 67. VOICE-030 — server-initiated session ended provede klientský resource cleanup
**Implementace:** Handler `session.ended` musí zavolat resource cleanup variantu bez opětovného odeslání `session.end`.
**Akceptace:** po server end jsou všechny microphone tracks stopped.

### 68. VOICE-031 — navigace z chatu ukončí/pozastaví hlas dle explicitní politiky
**Implementace:** Odstranit nekontrolovaný application singleton lifecycle. Při unmount `/chat` aktivní session bezpečně ukončit, nebo pokud má pokračovat napříč route, zobrazit persistentní globální call UI a explicitní indikaci mikrofonu. Pro současný UX zvolit ukončení na unmount.
**Akceptace:** navigace `/chat`→`/memory` zastaví microphone a websocket.

### 69. VOICE-032 — confirmAction error feedback
**Implementace:** `confirmAction` chybu propaguje do snapshot/page error; při 409 expired refreshnout action/run detail a odstranit neaktuální pending UI.
**Akceptace:** failed/expired confirmation není silent promise rejection.

### 70. TX-002 — failed orchestration run musí být durable
**Implementace:** Podle F2 persistovat user message, run a attempt lifecycle; při provider/orchestration chybě rollbacknout pouze nehotové side effects, uložit `run.state=failed`, `error_code`, `completed_at` a audit, pak vrátit error.
**Akceptace:** po 502 existuje failed run dohledatelný podle source message.

### 71. TX-003 — failed OrchestrationAttempt musí být durable
**Implementace:** Attempt musí přežít chybu model callu včetně latency/error_code; napojit na F2 transaction boundary.
**Akceptace:** failed attempt existuje po nové DB session.

### 72. TX-004 — expired action musí být durable
**Implementace:** Při confirm po expiraci uložit `state=expired`, `version++`, timestamp pokud model doplní, audit a pak vrátit 409 commit-on-error cestou F2.
**Akceptace:** opakované GET run vrací expired, ne pending.

### 73. TX-005 — failed action musí být durable bez partial side effects
**Implementace:** Vlastní state action spustit v savepointu. Při chybě savepoint rollbacknout, potom action označit failed a durable commitnout audit/error.
**Akceptace:** target data se při chybě nezmění, action=failed zůstane.

### 74. ORCH-001 — completed_at pouze pro terminální stav
**Implementace:** Při `awaiting_confirmation` nenastavovat `completed_at`. Přidat/udržet `started_at`; completed_at až completed/failed/cancelled/expired run.
**Akceptace:** pending run má completed_at null.

### 75. ORCH-002 — completed_at po posledním potvrzení
**Implementace:** Když poslední action dokončí run, nastav `run.completed_at=utc_now()` v tom okamžiku.
**Akceptace:** timestamp je >= confirmed/completed action time.

### 76. ORCH-003 — terminální neúspěšné actions neblokují run neurčitě
**Implementace:** Definovat run aggregate state pravidla: pokud některá action failed/expired/cancelled a žádná neběží, run přejde do odpovídajícího terminálního/partial state; nepoužívat `state != completed` jako jedinou podmínku.
**Akceptace:** run nikdy nezůstane awaiting_confirmation, když nemá pending action.

### 77. ORCH-004 — background expiry pending actions
**Implementace:** Přidat periodický job, který `pending_confirmation` s `expires_at<=now()` převádí na expired a přepočte run state.
**Akceptace:** akce expiruje i bez kliknutí uživatele.

### 78. ORCH-005 — confirm expired využívá stejnou state transition
**Implementace:** Ruční confirm po deadline volá tutéž idempotentní expire funkci jako background job.
**Akceptace:** oba vstupy mají shodný state/audit.

### 79. ORCH-006 — explicitní reject action
**Implementace:** Přidat backend endpoint/service `reject` s expected_version, state `rejected/cancelled`, audit a UI tlačítko „Odmítnout“ u každé pending action.
**Akceptace:** uživatel může návrh odmítnout bez čekání na timeout.

### 80. ORCH-007 — zpřístupnit cancel run
**Implementace:** ChatPage zobrazí cancel pro run s více pending actions nebo odpovídající globální odmítnutí; po cancel aktualizuje actions a stav.
**Akceptace:** endpoint není dead UI functionality.

### 81. ORCH-008 — respektovat memory.suggestions_enabled
**Implementace:** `_create_actions` načte effective setting. Pokud false, ignoruje `memory_proposal` a `memory_create` vzniklý pouze jako assistant suggestion; explicitní uživatelský `memory_create` tool command zůstává povolen.
**Akceptace:** setting false nevytvoří assistant suggestion action.

### 82. ORCH-009 — správná provenance memory proposal
**Implementace:** `decision.memory_proposal` ukládat s `origin_type="assistant_suggestion"`; explicitní uživatelský příkaz zůstává `explicit_command`.
**Akceptace:** MemoryPage zobrazuje správný původ.

### 83. ORCH-010 — ignorovat expired active memories
**Implementace:** Context query aktivních memories doplnit `valid_until IS NULL OR valid_until>=now()`.
**Akceptace:** expirovaná memory se neobjeví v promptu ani source manifestu.

### 84. ORCH-011 — respektovat valid_from
**Implementace:** Context query doplnit `valid_from IS NULL OR valid_from<=now()`.
**Akceptace:** budoucí memory nevstupuje před datem platnosti.

### 85. ORCH-012 — fallback pokud ranked IDs po filtrování nic nedají
**Implementace:** Pokud ranked list existuje, ale výsledná aktivní/valid memory sada je prázdná, provést stejný fallback na posledních 6 validních aktivních položek.
**Akceptace:** stale ranked IDs nezpůsobí prázdný memory context.

### 86. ORCH-013 — transcript correction vytvoří nový orchestration run
**Implementace:** Reprocess nesmí použít stejný idempotency identity pouze podle source_message_id. Přidej source message version/revision do uniqueness/idempotency nebo explicitně invaliduj a vytvoř nový run navázaný na revision.
**Akceptace:** correction + request_new_answer generuje novou assistant odpověď.

### 87. ORCH-014 — korekce invaliduje starou odpověď/index
**Implementace:** Při reprocess označit předchozí response/run jako superseded, vytvořit novou odpověď/revision dle datového modelu a reindexovat až nový canonical transcript.
**Akceptace:** historie/search používá novou korekci a novou odpověď, ne starou.

### 88. ORCH-015 — merge zachová časová metadata
**Implementace:** Při `memory_merge` definovat deterministickou merge politiku pro event_at/valid_from/valid_until; preview musí ukázat výsledné hodnoty. Pokud zdroje konfliktují a model nedodá rozhodnutí, vyžádat novou explicitní hodnotu místo tichého vynechání.
**Akceptace:** merge neztratí temporal metadata bez viditelného rozhodnutí.

### 89. ORCH-016 — plná validace action payload před confirmation
**Implementace:** Všechny action argumenty validovat a normalizovat při creation preview, ne až při execute. Persistovaná `ToolAction.arguments` musí být již kanonická.
**Akceptace:** potvrzení validní pending action neselže na syntaktické validaci payloadu.

### 90. MEM-001 — implementovat cursor pagination
**Implementace:** Definovat opaque cursor stabilně z order keys (např. `updated_at,id`) a použít jej v `MemoryService.search`; API musí vracet `next_cursor`.
**Akceptace:** stránkování bez duplicit/vynechání při stabilních datech.

### 91. MEM-002 — MemoryPage načte více než 100
**Implementace:** UI použije `next_cursor` a „Načíst další“/infinite paging; filtr resetuje cursor.
**Akceptace:** 150 položek je dosažitelných přes UI.

### 92. MEM-003 — nullable field patch semantics
**Implementace:** `MemoryUpdate` rozlišuje absent vs explicit null pomocí `model_fields_set`; service při explicitním null datum vymaže, při absent ponechá.
**Akceptace:** lze odstranit event_at/valid_from/valid_until.

### 93. MEM-004 — whitespace create zakázat po normalizaci
**Implementace:** Pydantic field validator trim/NFC a odmítne prázdný výsledek; service už dostane kanonický content.
**Akceptace:** "   " vrátí 422.

### 94. MEM-005 — whitespace update zakázat
**Implementace:** stejný normalizátor pro update content.
**Akceptace:** whitespace update je 422.

### 95. MEM-006 — duplicate check nad kanonickým textem
**Implementace:** Normalizovat content před duplicate query a uložením; query musí používat stejnou normalizační reprezentaci.
**Akceptace:** `text` a ` text ` jsou duplicate.

### 96. MEM-007 — sjednotit Unicode/case normalization
**Implementace:** Zavést `normalized_content` nebo deterministický normalizační helper (NFC + whitespace collapse + casefold). Pro DB duplicate enforcement používat uložený hash/normalized sloupec, ne mix `lower` vs Python casefold.
**Akceptace:** Unicode ekvivalentní varianty se detekují konzistentně.

### 97. MEM-008 — duplicate guard při update
**Implementace:** Při změně contentu zkontrolovat aktivní/pending jiné memory se stejným normalized content; vlastní ID vyloučit.
**Akceptace:** update na duplicate vrátí 409.

### 98. MEM-009 — DB ochrana concurrent duplicate create
**Implementace:** Nová migrace přidá databázový mechanismus proti souběžným duplicitám aktivních/pending memories (např. normalized hash + partial unique index podle podporované state policy).
**Akceptace:** dva souběžné create stejného contentu skončí jedním success a jedním conflict.

### 99. MEM-010 — delete stale/delete search document
**Implementace:** Soft delete musí přes search lifecycle API okamžitě odstranit nebo označit dokument tak, aby nebyl searchable; preferováno `stale=true` do retenční obnovy, hard purge ho smaže.
**Akceptace:** soft-deleted memory se okamžitě nevrací z search.

### 100. MEM-011 — merge odstraní zdroje z aktivního indexu
**Implementace:** Každou source memory přepnutou na merged označit search document stale; merged target se indexuje.
**Akceptace:** search vrací pouze target, ne merged source jako aktivní hit.

### 101. MEM-012 — confirm lifecycle synchronizuje index
**Implementace:** Po pending→active enqueue `memory.index_requested` nebo synchronně aktualizuj lifecycle flag, aby index přesně odpovídal current state.
**Akceptace:** confirmed memory je search-ready, pending není používána jako aktivní.

### 102. MEM-013 — purge source_excerpt podle retention semantics
**Implementace:** Při hard purge zdrojové conversation/message anonymizovat/odstranit `MemorySource.source_excerpt`, pokud pochází z purgovaného zdroje, a zachovat pouze bezpečnou provenance bez původního textu.
**Akceptace:** hard-purged transcript není rekonstruovatelný z MemorySource excerptu.

### 103. MEM-014 — robustnější secret policy
**Implementace:** Oddělit detekci „uživatel mluví o hesle“ od pokusu uložit secret. Zavést strukturovanou policy pro známé credential patterns a explicitní uživatelská potvrzení; minimálně nepovažovat prostý výskyt slova za úplnou ochranu. Citlivé hodnoty odmítnout před persistence a auditovat pouze redigovaně.
**Akceptace:** testy pro token-like/API-key/password hodnoty i benigní věty.

### 104. MEM-015 — UI trim/validation create
**Implementace:** MemoryPage trimuje/normalizuje před submit a button disabled pro whitespace-only.
**Akceptace:** whitespace request se z UI vůbec neodešle.

### 105. MEM-016 — error handling markOutdated
**Implementace:** try/catch `ApiError`, setError, neměnit selected/items při failure.
**Akceptace:** 409 version conflict je viditelný.

### 106. MEM-017 — error handling remove
**Implementace:** stejné.
**Akceptace:** failure delete nezobrazuje falešný success.

### 107. MEM-018 — error handling restore
**Implementace:** stejné.
**Akceptace:** expired restore vrátí viditelnou chybu.

### 108. MEM-019 — při search failure nezobrazovat staré výsledky jako nové
**Implementace:** Udržovat `lastSuccessfulQuery`/loading state; při failure označit stávající items jako staré nebo je skrýt. Preferováno zachovat je s jasným „Výsledky nebyly obnoveny“.
**Akceptace:** uživatel pozná, že nový dotaz selhal.

### 109. MEM-020 — revalidovat selected po search
**Implementace:** Po úspěšném search selected buď nahradit čerstvou verzí stejného ID z výsledku, nebo zrušit, pokud už není dostupný.
**Akceptace:** edit nepoužije stale version z předchozího search.

### 110. MEM-021 — create busy guard
**Implementace:** Přidat `busy` pro create a disable button do ukončení requestu.
**Akceptace:** dvojklik nevytvoří dva requesty.

### 111. MEM-022 — nahradit window.prompt edit formulářem
**Implementace:** Inline/modal formulář řízený React stavem, validation + cancel + Feedback, stejný design system.
**Akceptace:** edit je přístupný klávesnicí a nezávisí na browser promptu.

### 112. CONV-001 — whitespace user turn
**Implementace:** `UserTurn.content` normalizovat Pydantic validátorem po trim/NFC a zakázat prázdný výsledek.
**Akceptace:** whitespace turn se nepersistuje.

### 113. CONV-002 — whitespace transcript correction
**Implementace:** Totéž pro `TranscriptCorrection.corrected_content`.
**Akceptace:** prázdná korekce 422.

### 114. CONV-003 — user_turn_finalized musí mít consumer nebo nemá vznikat
**Implementace:** Určit skutečný účel eventu. Pokud má spouštět downstream processing, přidat explicitní handler; pokud nemá žádný side effect, odstranit jeho produkci i contract. Nenechávat dead event.
**Akceptace:** žádný event type není produkován bez definovaného consumeru.

### 115. CONV-004 — unknown outbox event nesmí být published
**Implementace:** `dispatch_outbox` nastaví `published_at` pouze po úspěšné obsluze známého eventu. Neznámý event dostane `last_error_code=unsupported_event_type`, attempts++, zůstane unpublished/parked podle policy.
**Akceptace:** unknown event je dohledatelný a nezmizí.

### 116. CONV-005 — assistant turn ownership guard
**Implementace:** `add_assistant_turn` přijme `account_id` a query conversation musí obsahovat account guard; všechny call-sites upravit.
**Akceptace:** cizí conversation ID nelze přes service změnit ani interním chybným call-sitem.

### 117. CONV-006 — EndRequest reason enum
**Implementace:** `reason` změnit na `Literal`/enum podporovaných hodnot a service mapování explicitně pro každý.
**Akceptace:** neznámý reason 422, nikoli tiché `interrupted`.

### 118. SEARCH-003 — starý memory embedding_text odstranit
**Implementace:** Je pokryto F3 upsert-in-place/delete-old. Regression test ověří, že původní text není v žádném SearchEmbedding po update.
**Akceptace:** DB grep/query nenajde starou hodnotu v search_embedding.

### 119. SEARCH-004 — starý conversation embedding_text odstranit
**Implementace:** Stejný lifecycle pro conversation index.
**Akceptace:** po reindexu existuje pouze aktuální embedding text.

### 120. SEARCH-005 — orphan memory searchable_text purge
**Implementace:** RET-001 lifecycle test pro owner_type memory.
**Akceptace:** po hard purge není původní text v search_document.

### 121. SEARCH-006 — orphan conversation transcript purge
**Implementace:** RET-001 lifecycle test pro owner_type conversation a celý transcript.
**Akceptace:** hard purge odstraní title/summary/transcript z search layer.

### 122. SEARCH-007 — orphan embeddings nesmí zabírat ranking
**Implementace:** F3 fyzicky odstraní orphany; navíc reindex/maintenance může detekovat owner bez kanonického row a dokument smazat.
**Akceptace:** semantic candidate set neobsahuje orphan owner IDs.

### 123. SEARCH-008 — reindex_all čistí orphany/lifecycle-invalid docs
**Implementace:** `search_reindex_all` před reindexem ověří owner existenci/state; neexistující hard smaže, soft-deleted/merged ponechá stale, aktivní reindexuje.
**Akceptace:** maintenance job konverguje index ke kanonickým datům.

### 124. SEARCH-009 — restore embedding setting spustí reindex
**Implementace:** `SettingsService.restore_revision()` musí pro `models.embedding_model` použít stejný side-effect helper jako `update_area`: mark stale + enqueue exactly-one reindex job.
**Akceptace:** restore modelu vytvoří reindex request.

### 125. SEARCH-010 — ModelRecommendationService nesmí obejít SettingsService
**Implementace:** `_set_setting` odstranit/omezit a doporučení zapisovat přes společnou settings mutation service, která validuje model a provádí side effects.
**Akceptace:** každá změna embedding_model vede stejnou cestou.

### 126. SEARCH-011 — provider save + recommended embedding reindex
**Implementace:** Po refaktoru SEARCH-010 automatická/explicitní apply cesta používá standard settings mutation.
**Akceptace:** pokud se embedding ID změnil při save, documents jsou stale a job queued.

### 127. SEARCH-012 — provider verify + recommended embedding reindex
**Implementace:** Stejné pro verify; následně SET-015/016 automatickou aplikaci z verify odstraní, takže reindex nastane jen při explicitní změně.
**Akceptace:** žádná skrytá změna modelu bez reindex.

### 128. SEARCH-013 — source_hash z přesného embedded textu
**Implementace:** Vytvořit proměnnou `embedding_text = searchable[:120000]`; hash počítat přesně z ní a stejnou hodnotu uložit.
**Akceptace:** hash odpovídá uloženému embedding_text byte-for-byte.

### 129. SEARCH-014 — pravdivá full-text konfigurace
**Implementace:** Nepoužívat config jménem `czech`, který je pouze kopie `simple`. V nové migraci přejmenovat/standardizovat na explicitní `simple` policy a aplikační language metadata oddělit od PostgreSQL config. Pokud se zavádí Czech stemming, musí být skutečně provisioned a testovaný; bez něj se nesmí tak nazývat.
**Akceptace:** DB config název pravdivě odpovídá použitému parseru a migrace je deterministická.

### 130. SEARCH-015 — query a document používají stejný FTS config
**Implementace:** `websearch_to_tsquery` nesmí mít hardcoded jiný config než dokument. Ulož/odvoď search_config deterministicky a použij stejný při to_tsvector i tsquery.
**Akceptace:** integration test potvrzuje shodné chování index/query.

### 131. SEARCH-016 — dimensions validovat před insert/update
**Implementace:** F3 validace se provede dřív než serialization/ORM write a uložené `dimensions` musí být vždy canonical value.
**Akceptace:** invalid vector nevytvoří/nezmění SearchEmbedding.

### 132. SEARCH-017 — ORM typ odpovídá pgvector fyzickému typu
**Implementace:** Přidat podporovaný SQLAlchemy pgvector typ/dependency nebo vlastní TypeDecorator; model nesmí deklarovat `Text` pro fyzický vector sloupec. Migrace a queries používat stejný typ.
**Akceptace:** mypy/runtime model odpovídá DB a nejsou potřeba implicitní text→vector casty pro běžný CRUD.

### 133. RET-003 — scheduler enqueue purge_expired
**Implementace:** Přidat periodický scheduler v worker/system scheduler vrstvě, který idempotentně enqueueuje `purge_expired` nejméně denně; použít dedup/lease tak, aby více workerů nevytvořilo nekontrolované duplicity.
**Akceptace:** bez ručního zásahu vzniká purge job.

### 134. RET-004 — memory hard purge automaticky
**Implementace:** Scheduler + handler musí skutečně odstranit memory po `purge_after`, včetně F3 search lifecycle.
**Akceptace:** integration test s minulým purge_after konverguje na neexistující row + index.

### 135. RET-005 — conversation hard purge automaticky
**Implementace:** totéž pro conversation.
**Akceptace:** canonical row/messages i search derived content odstraněny podle FK/lifecycle.

### 136. RET-006 — export expiry purge automaticky
**Implementace:** stejný scheduler spouští `ExportService.purge_expired`; soubor i DB stav jsou cleanupnuty idempotentně.
**Akceptace:** expired export file po scheduler run neexistuje.

### 137. SET-001 — ui_language musí mít runtime efekt
**Implementace:** Buď dokončit lokalizační vrstvu pro `cs/en` a načítat effective `general.ui_language` po loginu, nebo pokud druhý jazyk není implementovatelný v tomto scope, nepovolovat nefunkční volbu. Požadovaný cílový stav tohoto projektu: implementovat `cs` a `en` přes existující i18n modul a všechny user-facing labels migrovat na překlady.
**Akceptace:** přepnutí na en po deklarované effect boundary změní UI texty.

### 138. SET-002 — timezone používat při formátování
**Implementace:** Vytvořit shared date formatter/context používající effective `general.timezone`/profile timezone podle jedné precedence policy; nahradit raw `toLocaleString` v UI.
**Akceptace:** změna timezone změní zobrazení stejných UTC timestamps.

### 139. SET-003 — conversation.language skutečně řídit chat
**Implementace:** ChatPage/VoiceClient načte effective language a předává jej start/turnům; server uloží conversation language a všechny downstream VOICE úkoly ho používají.
**Akceptace:** nové conversation po změně setting mají nový language.

### 140. SET-004 — idle warning runtime timer
**Implementace:** Voice session controller načte `idle_warning_seconds` při startu a resetuje timer na skutečné user activity. Po timeoutu zobrazí/emitne warning bez ukončení session.
**Akceptace:** configurable warning nastane přesně podle hodnoty v testu s fake timers.

### 141. SET-005 — idle end runtime timer
**Implementace:** Server musí být autoritativní: při neaktivitě po `idle_end_seconds` ukončit conversation definovaným reason, emit session.ended a vytvořit close outbox. Klientský timer může pouze UX doplněk.
**Akceptace:** opuštěná voice session se automaticky uzavře.

### 142. SET-006 — output_volume napojit na GainNode
**Implementace:** Effective 0..100 převést na gain 0..1, aktualizovat immediate bez restartu session.
**Akceptace:** změna settingu mění `gain.gain.value`.

### 143. SET-007 — barge_in vynutit klientem i serverem
**Implementace:** Při false nezobrazovat interrupt control a server odmítne `assistant.interrupt` pro session s barge_in false. Snapshot setting při session start.
**Akceptace:** client bypass nemůže přerušit, pokud false.

### 144. SET-008 — memory suggestion switch
**Implementace:** realizovat ORCH-008 a settings integration test.
**Akceptace:** false = žádné assistant suggestion actions.

### 145. SET-009 — automatic_summary switch
**Implementace:** `conversation_finalize` načte setting; při false nevytváří AI summary/title, ale musí conversation korektně finalizovat/indexovat transcript bez AI summary.
**Akceptace:** summary provider není volán při false.

### 146. SET-010 — diagnostics.retention_days consumer
**Implementace:** Logging/diagnostic retention musí mít cleanup mechanismus používající effective value; pokud filesystem logs rotují velikostí, přidat časový cleanup pro diagnostické artefakty odpovídající nastavení.
**Akceptace:** starší diagnostika je odstraněna dle dní bez obsahu konverzací.

### 147. SET-011 — diagnostics.level consumer
**Implementace:** Mapovat minimal/standard/enhanced na konkrétní logging/metric verbosity a reload boundary; nikdy nepřidávat private conversation content.
**Akceptace:** level mění množinu technických událostí v testu.

### 148. SET-012 — backups.schedule skutečně plánuje backup
**Implementace:** System scheduler načte cron, validuje jej při save a idempotentně enqueueuje `backup_create`. Změna se projeví dle effect boundary bez ručního job insertu.
**Akceptace:** test scheduleru pro známý cron vytvoří job jednou.

### 149. SET-013 — restore model setting validuje model
**Implementace:** `restore_revision` u area models volá stejnou `_validate_model_selection` před zápisem.
**Akceptace:** revize s unavailable/wrong-role modelem nelze obnovit.

### 150. SET-014 — restore embedding model reindex
**Implementace:** viz SEARCH-009, společný mutation helper.
**Akceptace:** stale count + queued reindex audit.

### 151. SET-015 — provider save nesmí automaticky apply recommended
**Implementace:** `PUT /providers` provede save + verify/catalog refresh, ale model selections nemění. Vrátí recommendations pouze jako návrh.
**Akceptace:** existující model setting IDs se po save nezmění.

### 152. SET-016 — provider verify nesmí automaticky apply recommended
**Implementace:** `POST /providers/{id}/verify` rovněž pouze ověří a vrátí recommendations. Změna modelů pouze `/apply-recommended-models` nebo explicitní settings save.
**Akceptace:** verify je side-effect-free vůči model settings.

### 153. SET-017 — oddělení verify a apply v UI
**Implementace:** SettingsPage po verify zobrazí doporučenou sestavu a samostatné tlačítko Apply; texty jasně rozliší operace.
**Akceptace:** klik na Ověřit nikdy nezmění select hodnoty uložené na serveru.

### 154. SET-018 — provider-specific apply nesmí nečekaně přepsat jiné provider volby
**Implementace:** Apply preview musí vypsat každou roli current→recommended a vyžádat explicitní confirmation. Role, které uživatel nechce měnit, lze zachovat; server přijme explicitní role list/expected versions.
**Akceptace:** žádný globální model setting se nezmění bez zahrnutí v potvrzeném preview.

### 155. SET-019 — zabránit tiché smíšené sestavě
**Implementace:** Recommendation response musí u každé role uvést current provider a proposed provider; pokud provider nemá kandidáta, označit `unchanged_missing_candidate` a UI to zřetelně zobrazí před apply.
**Akceptace:** uživatel přesně vidí výslednou sestavu.

### 156. SET-020 — returned options po apply musí být čerstvé
**Implementace:** Po zápisu recommendations znovu načíst `model_options` nebo aktualizovat selected IDs z persisted výsledků.
**Akceptace:** response `selected_model_id` odpovídá DB po operaci.

### 157. AUTH-002 — audit neexistujícího loginu durable
**Implementace:** Podle F2 uložit `identity.login_failed` i když account neexistuje; neukládat username/password do details.
**Akceptace:** 401 a audit event současně.

### 158. AUTH-003 — restricted login audit durable
**Implementace:** `identity.login_restricted` commit-on-error podle F2.
**Akceptace:** restricted attempt je v audit chain.

### 159. AUTH-004 — invalid initialization audit durable
**Implementace:** neplatné initialization secret uloží denied audit před 401 bez secret value.
**Akceptace:** event přežije rollback běžných změn.

### 160. AUTH-005 — odstranit dead rate-limit API nebo jej použít
**Implementace:** Konsolidovat login policy do jediného helperu. `evaluate_login_attempt` musí být používán v authenticate a `restriction_until` nesmí duplikovat jinou logiku; případně jeden z helperů odstranit.
**Akceptace:** jedna testovaná funkce definuje threshold/backoff.

### 161. AUTH-006 — auth/state neprozrazuje účet
**Implementace:** Před autentizací vracet pouze `instance_state` a generický bootstrap hint; existující username nevracet. Frontend login použije lokální/default username pouze pokud je produkt explicitně single-user, nikoli server enumeration.
**Akceptace:** response initialized instance neobsahuje account username.

### 162. AUTH-007 — sessions endpoint filtruje expiraci
**Implementace:** Query doplnit `expires_at>now` a `absolute_expires_at>now`; volitelně lazy cleanup expired rows.
**Akceptace:** expired session se nezobrazuje jako aktivní.

### 163. AUTH-008 — CSRF bootstrap pro novou kartu
**Implementace:** Přihlášená cookie session musí umožnit bezpečně získat nový/stejný CSRF token přes authenticated same-site GET endpoint, který neprozradí session secret; token lze rotovat a digest atomicky uložit. AuthProvider při `/auth/me` success a chybějícím sessionStorage tokenu provede bootstrap.
**Akceptace:** nová karta se stejnou auth cookie může provést mutaci bez reloginu.

### 164. AUTH-009 — AuthProvider refresh vždy ukončí loading
**Implementace:** `refresh()` obalit top-level try/finally; network/state chyby nastaví explicitní auth error state, loading=false.
**Akceptace:** failed `/auth/state` nenechá nekonečný spinner.

### 165. AUTH-010 — rozlišit 401 od technické chyby /auth/me
**Implementace:** Pouze status 401/403 znamená unauthenticated; network/5xx nastaví recoverable auth error a neodhlásí tiše uživatele.
**Akceptace:** simulované 503 nezobrazí login jako by session neexistovala.

### 166. AUTH-011 — revoke session error feedback
**Implementace:** try/catch + Feedback, optimistic state nepoužívat bez rollbacku.
**Akceptace:** 409/500 viditelný.

### 167. AUTH-012 — sjednotit password minimum
**Implementace:** Zvolit jednu policy; vzhledem k existujícímu UI použít minimum **14** i v backend `password_policy_errors`, initialize/change/reset i hints. Aktualizovat tests.
**Akceptace:** 8–13 znaků backend odmítne stejně jako UI.

### 168. AUTH-013 — ForgotPassword catch
**Implementace:** Přidat error state, ale zachovat anti-enumeration generický text pro accepted i neexistující účet. Technická chyba při requestu se zobrazí jako dočasný problém bez citlivého detailu.
**Akceptace:** promise rejection není unhandled.

### 169. AUTH-014 — failed NotificationDelivery durable
**Implementace:** SMTP send proběhne uvnitř savepointu/oddělené delivery state machine; při exception uložit delivery failed/error_code durable podle F2, job může retry podle explicitní policy.
**Akceptace:** po SMTP failure existuje failed delivery row.

### 170. AUTH-015 — revoke starý SMTP secret
**Implementace:** Při password replacement uložit old_secret_id a po připojení nového nastavit starému `revoked_at`. Stejná politika jako ProviderService.save API key.
**Akceptace:** pouze aktuální SMTP secret není revoked.

### 171. AUTH-016 — email change + SMTP failure konzistence
**Implementace:** Rozdělit state machine: vytvořit pending email/token durable, delivery zvlášť. Pokud send selže, pending stav zůstane s možností resend nebo se explicitně rollbackne samostatnou kompenzací; audit nesmí zmizet. Preferováno pending + failed delivery + resend.
**Akceptace:** SMTP outage je diagnostikovatelný a UI umožní znovu odeslat.

### 172. SEC-001 — validovat X-Correlation-ID
**Implementace:** Přijmout jen bezpečný formát/délku <=64 (např. `[A-Za-z0-9._:-]{1,64}`); neplatný header nahradit serverovým UUID, nikoli vracet 500.
**Akceptace:** 10k znakový header neovlivní DB.

### 173. SEC-002 — DB correlation_id nikdy nepřeteče
**Implementace:** Všechny AuditContext/BackgroundJob vstupy používají normalizovaný correlation ID z middleware/helperu; defense-in-depth truncate/reject v audit service před model write.
**Akceptace:** žádný audit insert nemůže selhat na varchar(64).

### 174. SEC-003 — trusted_proxy_cidrs používat
**Implementace:** `network_context()` musí odlišit přímého peer a forwarded client pouze pokud peer patří do configured trusted proxy CIDR. Implementovat bezpečný parser IP.
**Akceptace:** spoofed forwarded header od nedůvěryhodného peeru se ignoruje.

### 175. SEC-004 — uvicorn proxy trust nesmí být wildcard
**Implementace:** `deployment/compose.yaml`/command nastaví forwarded allow IPs na skutečnou interní Caddy síť/known proxy, ne `*`; sladit se SEC-003.
**Akceptace:** release config nemá `--forwarded-allow-ips=*`.

### 176. AUDIT-003 — rekurzivní sanitizace
**Implementace:** `_sanitize` musí rekurzivně projít dict/list/tuple a redigovat forbidden key names v libovolné hloubce; omezit délku stringů i nested hodnot.
**Akceptace:** nested `{meta:{token:"x"}}` uloží `[redacted]`.

### 177. AUDIT-004 — denied identity audity přežijí chybu
**Implementace:** F2 + AUTH-002/003/004 regression suite.
**Akceptace:** všechny denied identity cesty jsou lineárně v audit chain.

### 178. AUDIT-005 — failed orchestration audity přežijí
**Implementace:** F2 + TX-002.
**Akceptace:** orchestration.failed viditelný po 5xx.

### 179. AUDIT-006 — provider verification failure state/audit durable
**Implementace:** `ProviderService.verify` při katalog/network/empty failure uloží `catalog_state`, `verification_state` podle state machine a failed audit durable, poté vrátí error.
**Akceptace:** GET provider po failed verify ukáže stale_error/empty, ne starý ready.

### 180. AUDIT-007 — immutable trigger + serialized append
**Implementace:** Zachovat no-update/no-delete trigger a doplnit F5 locking. `verify_chain` testovat po concurrency.
**Akceptace:** chain je současně append-only i lineární.

### 181. HIST-001 — stav recovered sjednotit
**Implementace:** Rozhodnout jediný canonical restore stav. Pro zachování existujícího UI nastavovat po restore `state="recovered"` a history query jej podporuje; při novém pokračování/uzavření se použijí standardní stavy podle lifecycle.
**Akceptace:** restore endpoint vrátí recovered a UI label „Obnoveno“.

### 182. HIST-002 — whitespace title
**Implementace:** MetadataUpdate validator trim/NFC a min length po trim.
**Akceptace:** whitespace title 422.

### 183. HIST-003 — whitespace summary
**Implementace:** totéž.
**Akceptace:** whitespace summary 422.

### 184. HIST-004 — metadata update reindex
**Implementace:** Po úspěšné změně title/summary enqueue `conversation_index`; deduplicate podle conversation/version.
**Akceptace:** search document obsahuje nový title/summary.

### 185. HIST-005 — soft delete vyřadí search doc
**Implementace:** Search lifecycle API nastaví conversation document stale při soft delete.
**Akceptace:** deleted conversation se nevrací semantic/text search.

### 186. HIST-006 — restore reindex
**Implementace:** Po restore enqueue conversation index a dokument znovu aktivovat až po úspěšné indexaci.
**Akceptace:** restored conversation je po jobu searchable.

### 187. HIST-007 — continue response ID nezahazovat
**Implementace:** UI uloží `conversation_id` z continue response a předá jej ChatPage přes route state/query nebo conversation controller.
**Akceptace:** kliknutí „Navázat“ používá přesně backendem vytvořenou conversation.

### 188. HIST-008 — ChatPage attach k continuation conversation
**Implementace:** ChatPage umí inicializovat existující active conversation ID bez vytvoření další. Ověřit ownership/state serverem.
**Akceptace:** continue vytvoří právě jednu novou conversation.

### 189. HIST-009 — continue error handling
**Implementace:** try/catch + busy state + Feedback; redirect až po success.
**Akceptace:** 500 nezmění location.

### 190. HIST-010 — continue input_mode není natvrdo voice
**Implementace:** Continue endpoint přijme požadovaný `input_mode` nebo vytvoří neutrální active conversation a první turn určí mode; preferováno request field `input_mode: text|voice` z UI.
**Akceptace:** textové pokračování není v DB označeno voice.

### 191. HIST-011 — saveMetadata error handling
**Implementace:** try/catch + Feedback + busy.
**Akceptace:** version conflict zobrazen.

### 192. HIST-012 — remove error handling
**Implementace:** stejné.
**Akceptace:** failure nemění lokální state na deleted.

### 193. HIST-013 — history pagination
**Implementace:** UI implementuje offset/cursor paging; preferováno přejít na cursor stabilní podle `last_activity_at,id`. Pokud API zůstane offset, přidat Load more a reset při query změně.
**Akceptace:** >50 conversations dostupných.

### 194. HIST-014 — restore deleted history v UI
**Implementace:** Přidat filtr „Zobrazit odstraněné“, API search podporu deleted v bezpečné cestě a restore button do retention deadline.
**Akceptace:** soft-deleted conversation lze běžným UI obnovit.

### 195. HIST-015 — metadata edit zakázat pro deleted
**Implementace:** Service update_metadata vyžaduje editable state a `deleted_at IS NULL`.
**Akceptace:** deleted metadata update 409.

### 196. HIST-016 — account scope v matching_messages
**Implementace:** Subquery joinne Conversation a filtruje account_id nebo koreluje s outer account; zabránit zbytečnému scan cross-account messages.
**Akceptace:** SQL/integration test pro dva účty a query plan scope.

### 197. HIST-017 — display_name místo Karel
**Implementace:** HistoryPage načte auth profile/context a používá `display_name`.
**Akceptace:** změna profilu se projeví v transcript labelu.

### 198. JOB-001 — běžný worker neclaimuje backup_create
**Implementace:** F4 allow-list `self.handlers.keys()`; backup kind není v něm.
**Akceptace:** worker claim test.

### 199. JOB-002 — běžný worker neclaimuje backup_verify
**Implementace:** stejné.
**Akceptace:** worker claim test.

### 200. JOB-003 — běžný worker neclaimuje backup_restore_test
**Implementace:** stejné.
**Akceptace:** worker claim test.

### 201. JOB-004 — odstranění race worker vs backup-agent
**Implementace:** Integration test se dvěma connection/consumers současně; každý dostane pouze vlastní kinds.
**Akceptace:** žádný backup job není failed `unsupported_job_kind` kvůli běžnému workeru.

### 202. JOB-005 — zkrátit transaction scope batch processing
**Implementace:** Claim může být batch, ale každý job musí mít vlastní commit/transaction po claim lease; nedržet jednu outer transakci přes zpracování 10 externích operací. Implementovat claim IDs/lease, pak per-job UoW.
**Akceptace:** pád jobu 10 nevrátí completed state jobů 1–9.

### 203. JOB-006 — worker healthcheck funkční
**Implementace:** Worker publikuje heartbeat v DB nebo lightweight health endpoint/state s timestampem posledního successful poll; compose healthcheck ověřuje čerstvost heartbeat, ne jen proces+TCP.
**Akceptace:** zablokovaný worker je unhealthy.

### 204. JOB-007 — operations status používá heartbeat
**Implementace:** `/operations/status` vyhodnotí worker readiness podle heartbeat age + queue oldest age, ne pouze queue size.
**Akceptace:** mrtvý worker s nulovou queue není hlášen ready.

### 205. JOB-008 — empty conversation finalization verzovat stejně
**Implementace:** Empty branch zvýší conversation version a vytvoří `ConversationSummary` revision stejně jako non-empty, pokud vytváří title/summary.
**Akceptace:** obě větve mají konzistentní audit/version history.

### 206. JOB-009 — automatic_summary false
**Implementace:** realizovat SET-009.
**Akceptace:** summary provider call count=0 při false.

### 207. JOB-010 — corrected reprocess invalidace
**Implementace:** realizovat ORCH-013/014; worker dostává konkrétní message revision a nevytáhne completed old run.
**Akceptace:** nový run ID.

### 208. JOB-011 — unknown outbox event parking
**Implementace:** realizovat CONV-004, navíc operations diagnostics ukáže count parked/unsupported events.
**Akceptace:** event není published a je viditelný.

### 209. BACKUP-002 — backup audit sanitizace
**Implementace:** Backup-agent musí používat stejný sanitizační algoritmus/contract jako app. Protože nemá import aplikačního runtime v DB image, vyčlenit malý shared pure-Python modul dostupný oběma images nebo implementovat identické testované serialization rules z jednoho zdroje při buildu.
**Akceptace:** nested sensitive detail je redacted i z backup auditu.

### 210. BACKUP-003 — runtime scheduler backupů
**Implementace:** realizovat SET-012; pgbackrest sleeper není scheduler. Scheduler tvoří pouze `backup_create` job, samotnou práci dělá backup-agent.
**Akceptace:** cron trigger→queued job→backup-agent claim.

### 211. EXPORT-001 — scheduled export cleanup
**Implementace:** realizovat RET-003/006.
**Akceptace:** expired export odstraněn bez manuálního enqueue.

### 212. EXPORT-002 — filesystem/DB atomicity
**Implementace:** Generovat do temporary path, fsync/close, spočítat digest, DB record update commit; po úspěšném commitu atomicky publish/rename nebo použít recovery cleanup marker. Při DB failure temp soubor cleanupnout v finally; nikdy nenechat final file s ne-completed record.
**Akceptace:** simulovaný DB commit failure nezanechá publikovaný orphan export.

### 213. EXPORT-003 — scope skutečně aplikovat
**Implementace:** Každý export kind musí validovat a aplikovat `ExportRecord.scope` na query. Pokud kind podporuje pouze full account export, schema musí scope explicitně omezit na `{type:"all"}` a nepředstírat granularitu.
**Akceptace:** požadovaný subset export neobsahuje data mimo scope.

### 214. UI-001 — ChatPage display_name
**Implementace:** Použít `useAuth().user.profile.display_name`, fallback generický „Vy“.
**Akceptace:** není hardcoded `Karel`.

### 215. UI-002 — HistoryPage display_name
**Implementace:** realizovat HIST-017.
**Akceptace:** není hardcoded `Karel`.

### 216. UI-003 — quick settings jazyk dynamicky
**Implementace:** Quick settings čte effective conversation language a lokalizovaný label.
**Akceptace:** EN zobrazí English/angličtina dle UI language.

### 217. UI-004 — ChatPage načítá effective settings
**Implementace:** Vytvořit hook/context pro effective chat settings (language, voice, verbosity, output volume, barge-in) s loading/error state; ChatPage quick summary i VoiceClient start používají stejný snapshot.
**Akceptace:** zobrazené hodnoty jsou totožné s runtime použitými hodnotami.

### 218. UI-005 — MemoryPage bez native prompt/confirm pro edit/delete
**Implementace:** Edit a destructive confirmation přes přístupný app modal/dialog s explicitními tlačítky, focus managementem a error feedback.
**Akceptace:** žádné `window.prompt` pro memory; destructive confirm může být app dialog.

### 219. UI-006 — History metadata jeden formulář
**Implementace:** Nahradit dvojici promptů jedním formulářem title+summary, draft zachovat do save/cancel.
**Akceptace:** zrušení nezpůsobí skrytou ztrátu již napsaného druhého pole.

### 220. UI-007 — model-options chyby nezamlčet
**Implementace:** SettingsPage nesmí `.catch(()=>null)` bez UI. U každého provideru zobrazit stav model catalog load error s retry a correlation ID.
**Akceptace:** failed model-options je viditelné.

### 221. UI-008 — reload nesmí přepsat dirty drafts
**Implementace:** Settings drafts mají dirty flags po area/key. Background/reload aktualizuje pouze pristine fields; při konfliktu nabídne explicitní reload/keep draft.
**Akceptace:** ověření provideru nesmaže rozpracovanou jinou sekci.

### 222. UI-009 — provider_type selector
**Implementace:** Provider form umožní `openai` i `openai_compatible`, s vysvětlením base URL a capability verify.
**Akceptace:** oba backend-supported typy lze vytvořit/editovat UI.

### 223. UI-010 — edit provider bez povinného nového API key
**Implementace:** Při existujícím `secret_present` password field prázdný znamená „ponechat stávající“; placeholder nesmí obsahovat secret hint jako hodnotu. Nový key pouze explicitně nahrazuje.
**Akceptace:** edit display name/base URL bez key zachová secret.

### 224. UI-011 — multi-provider editor
**Implementace:** Explicitní seznam/provider selector a oddělený edit state podle provider ID; žádná implicitní preference prvního row.
**Akceptace:** dva providery lze nezávisle editovat a ověřit.

### 225. UI-012 — lokalizovat technické enumy
**Implementace:** Vytvořit mapy pro provider/job/audit/backup states a event labels; raw identifier ponechat jen v diagnostickém detailu.
**Akceptace:** běžné UI nezobrazuje `stale_error`, `pending_confirmation` apod. bez lidského labelu.

### 226. UI-013 — human-readable backup size
**Implementace:** Shared formatter B/KiB/MiB/GiB s raw bytes v accessible title/detail.
**Akceptace:** 1048576 se zobrazí jako 1 MiB.

### 227. UI-014 — audit pagination
**Implementace:** Použít API cursor/limit a „Načíst další“, zachovat filtry. Pokud API cursor chybí, doplnit serverovou stabilní pagination.
**Akceptace:** lze projít více než první stránku auditů.

### 228. UI-015 — audit result enum sjednotit
**Implementace:** Backend definovat canonical result enum (`success`, `failure`, `denied` nebo jiný explicitní set) a migrovat `failed`→`failure` pro nové eventy; UI filtry mapovat všechny historické hodnoty při přechodu.
**Akceptace:** filtr „Neúspěšné“ najde failure/denied podle definované UX politiky.

### 229. UI-016 — ProfilePage timezone formatter
**Implementace:** Použít shared formatter ze SET-002.
**Akceptace:** session dates respektují configured timezone.

### 230. UI-017 — MemoryPage timezone formatter
**Implementace:** totéž.
**Akceptace:** memory timestamps respektují configured timezone.

### 231. UI-018 — HistoryPage timezone formatter
**Implementace:** totéž.
**Akceptace:** history timestamps respektují configured timezone.

### 232. UI-019 — success feedback markOutdated
**Implementace:** Po success nastavit notice s konkrétní operací; při error notice neukazovat.
**Akceptace:** UX konzistentní s edit/delete/restore.

### 233. UI-020 — úplný action preview
**Implementace:** Backend pro každý ToolAction poskytuje typovaný display preview se seznamem změn old→new a rizik/impact; frontend renderuje všechny definované položky, ne pouze čtyři volné klíče.
**Akceptace:** žádná state-changing hodnota není před confirmation skrytá.

### 234. UI-021 — completed action feedback konkrétní
**Implementace:** Zobrazit localized action name + výsledek (`Paměť byla uložena`, `Konverzace byla obnovena`), ne generický text.
**Akceptace:** completed feedback identifikuje operaci.

### 235. UI-022 — voice start top-level error boundary
**Implementace:** `client.start()` promise error musí skončit v snapshot/page Feedback i pro unexpected rejection; tlačítko má busy state a retry.
**Akceptace:** rejection startu není unhandled.

### 236. UI-023 — sjednotit async action helper
**Implementace:** Zavést malý reusable hook/pattern `useAsyncAction` nebo konzistentní try/catch/busy/error convention a migrovat settings/operations/profile/history/memory akce. Nezavádět globální catch, který skryje domain detail.
**Akceptace:** žádná user-triggered API promise ve zmíněných stránkách není fire-and-forget bez error path.

### 237. OPS-001 — readiness ověřuje conversation model
**Implementace:** `/health/ready` ověří, že je vybrán validní available conversation model, jeho provider je enabled+verified a model má F1 required capabilities. Nevolat externí provider při každém healthchecku; použít uložený verified state.
**Akceptace:** bez conversation modelu readiness != ready.

### 238. OPS-002 — readiness worker heartbeat
**Implementace:** Použít JOB-006 heartbeat a readiness webu/operations signalizuje degraded/not-ready podle definované tolerance, pokud background funkcionalita je povinná.
**Akceptace:** zastavený worker se projeví.

### 239. OPS-003 — readiness vector compatibility
**Implementace:** Při readiness/config verify kontrolovat selected embedding model metadata/probe dimensions proti F3 canonical dimension. Pokud není embedding nastaven, stav může být degraded dle produktu, ale nesmí tvrdit ready search, pokud je nekompatibilní.
**Akceptace:** 3072-only model při 1536 invariant není označen ready.

### 240. OPS-004 — diagnostics settings napojit na infrastrukturu
**Implementace:** SET-010/011 propojí aplikační settings s runtime logging policy; `/operations/status` vrátí effective diagnostics mode/retention bez secretů.
**Akceptace:** uložené nastavení není dead config.

### 241. OPS-005 — security headers i při unexpected error
**Implementace:** Security headers middleware musí obalit i exception cestu. Přesunout security-header aplikaci do nejvzdálenější ASGI middleware vrstvy nebo catch/finally vytvořit bezpečnou 500 response a poté přidat headers; nezobrazovat exception detail.
**Akceptace:** simulovaná unexpected 500 obsahuje CSP, nosniff, frame deny, referrer policy a correlation ID.

## 4. Povinná cross-reference coverage

Před uzavřením projektu musí integrační vlastník mechanicky ověřit, že každý identifikátor z `audit14082026.md` má v tomto dokumentu implementovaný a otestovaný closure. Minimální očekávané rozsahy:

- CHAT-001..CHAT-023
- API-001..API-002
- TEXT-001
- VOICE-001..VOICE-032
- TX-001..TX-005
- ORCH-001..ORCH-016
- MEM-001..MEM-022
- CONV-001..CONV-006
- SEARCH-001..SEARCH-017
- RET-001..RET-006
- VECTOR-001..VECTOR-002
- SET-001..SET-020
- AUTH-001..AUTH-016
- SEC-001..SEC-004
- AUDIT-001..AUDIT-007
- HIST-001..HIST-017
- JOB-001..JOB-011
- BACKUP-001..BACKUP-003
- EXPORT-001..EXPORT-003
- UI-001..UI-023
- OPS-001..OPS-005

Žádná položka nesmí být uzavřena statusem „won't fix“, „acceptable“, „cosmetic only“ nebo pouhou změnou dokumentace. Cosmetic nálezy jsou plnohodnotná součást scope.

## 5. Definition of Done celé opravy

1. Všech 241 položek má implementační commit/PR a regresní důkaz.
2. Neexistují nové raw exception cesty v provider/realtime/API boundary pro auditované scénáře.
3. Druhý a další hlasový rozhovor funguje bez reloadu stránky.
4. Textový chat při backend chybě zachová draft a zobrazí chybu.
5. Chybné login pokusy skutečně akumulují rate limit a denied audit je durable.
6. Failure/expired orchestration/action/delivery/provider states přežijí návrat error response.
7. Search obsahuje pouze aktuální embeddingy; hard purge odstraní kanonická i odvozená data.
8. Embedding dimenze je jednotně validována a odpovídá pgvector schématu.
9. Worker a backup-agent nikdy neclaimují cizí job kind.
10. Audit chain zůstává lineární při souběžných append operacích napříč procesy.
11. Každé deklarované nastavení má skutečný runtime consumer a odpovídající effect boundary.
12. History/memory mají funkční pagination a restore cesty v UI.
13. Všechny user-triggered async UI akce mají busy + error path.
14. `make source-check format-check lint typecheck test test-contract`, integrační/security/AI gates a `make release-check` projdou bez výjimek a bez potlačení testů.
