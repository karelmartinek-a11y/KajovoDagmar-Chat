# Realtime protokol v1

WebSocket `/api/v1/realtime` přijímá jednorázový ticket. Každá JSON událost má verzi, typ, event ID, session ID, sequence a volitelný idempotency key/cursor. Server potvrzuje přijetí a odmítne mezeru, duplicitu s jiným obsahem nebo nekompatibilní verzi.

Audio je PCM16 mono, 24 kHz, 20 ms/480 vzorků v binárních rámcích. Klient vědomě zahajuje relaci, může mikrofon pozastavit, přerušit syntézu, poslat text a ukončit relaci. Průběžný přepis je dočasný; pouze finální přepis tvoří kanonickou repliku.
