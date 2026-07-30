# Modulární monolit

KájovoDagmar je jeden produkt, jeden backend, jedna databáze a jeden webový klient. Procesní role `web`, `worker` a `CLI` používají tentýž Python package, schéma a release artefakt. Doménové moduly jsou `identity`, `conversations`, `memory`, `history`, `settings`, `providers`, `notifications`, `audit`, `files`, `jobs` a `operations`; komunikují přes veřejné use cases a transakční hranice, nikoli přes paralelní služby.

PostgreSQL je autoritativní. Vyhledávací dokumenty, embeddingy, cache, metriky a exporty jsou odvozené nebo provozní artefakty. Externí AI a e-mailové služby jsou adaptéry za porty. Stav měnící operace vždy končí v serverovém use case, auditu a podle potřeby outboxu.

Frontend neuchovává relace ani soukromý obsah v dlouhodobém browser storage. Relace je serverová Secure/HttpOnly/SameSite=Strict cookie; CSRF token je krátkodobý klientský údaj svázaný s relací.
