# ADR-001: Modulární monolit

**Stav:** přijaté. **Rozhodnutí:** jediný deployovatelný produkt s jedním package, databází a webem; procesní role nejsou samostatné aplikace. **Důsledek:** sdílené transakce, audit, konfigurace, outbox a observability; modul nesmí obcházet veřejné use cases jiného modulu.
