# Produkční nasazení

Cíl je `chat.hcasc.cz`. Caddy je jediný veřejný vstup 80/443; web, worker, PostgreSQL a pgBackRest zůstávají v interních sítích. Kořenové šifrovací tajemství, inicializační digest, heslo databáze, ACME e-mail a zálohovací klíče se injektují z provozního secret store.

1. Ověřte image digest, SBOM, release manifest a PASS protokol stejného commitu.
2. Připravte oddělené volumes a pgBackRest repository.
3. Spusťte migrace jednorázovým krokem, poté web a worker.
4. Ověřte `/health/live`, `/health/ready`, přihlášení a provozní status.
5. Teprve poté přepněte provoz; zachovejte předaktualizační bod a postup rollbacku.
