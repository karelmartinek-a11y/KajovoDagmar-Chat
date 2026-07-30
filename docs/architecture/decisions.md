# Architektonická rozhodnutí

1. **ADR-001:** modulární monolit, protože SSOT zakazuje paralelní aplikace a mikroslužby.
2. **ADR-002:** PostgreSQL 17 + pgvector jako jediný autoritativní stav; indexy jsou obnovitelné.
3. **ADR-003:** FastAPI/SQLAlchemy/asyncpg a React/TypeScript/Vite v přesně verzovaném toolchainu.
4. **ADR-004:** databázová fronta a transactional outbox; externí volání probíhají mimo dlouhé transakce.
5. **ADR-005:** OpenAI-compatible provider adapter je konfigurovatelný přes UI a bez ověřeného klíče nevytváří fiktivní výsledek.
6. **ADR-006:** jeden realtime protokol s verzovanou obálkou, sekvencí, potvrzením, idempotencí a obnovovacím kurzorem.
7. **ADR-007:** audit je append-only hash chain; provozní logy neobsahují tajemství ani plný soukromý obsah.
