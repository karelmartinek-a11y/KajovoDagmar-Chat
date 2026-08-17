# Realtime protokol v1

WebSocket `/api/v1/realtime` přijímá jednorázový ticket. Každá JSON událost má verzi, typ, event ID, session ID, sequence a volitelný idempotency key/cursor. Server potvrzuje přijetí a odmítne mezeru, duplicitu s jiným obsahem nebo nekompatibilní verzi.

Ticket lze získat běžnou administrátorskou relací s CSRF ochranou nebo serverovým `Authorization: Bearer` klíčem se scope `voice.realtime.test`. Bearer klíč je určen pouze pro interní forenzní runner; jeho platnost není časově omezena, ale je ručně revokovatelný.

Audio je PCM16 mono, 24 kHz, 20 ms/480 vzorků v binárních rámcích. Klient vědomě zahajuje relaci, může mikrofon pozastavit, přerušit syntézu, poslat text a ukončit relaci. Průběžný přepis je dočasný; pouze finální přepis tvoří kanonickou repliku.
