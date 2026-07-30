# Matice dohledatelnosti

Soubor `requirements.json` obsahuje 1000 číslovaných požadavků kapitol 0 až 20
vytěžených z kanonického SSOT. Každý požadavek má vazbu na implementační oblast,
konkrétní ověřovací testy a čerstvé artefakty úplné release brány.

Strukturální kontrola probíhá už na začátku release procesu. Závěrečná kontrola
uzná pouze stav `implemented_verified`, existující deklarované důkazy z právě
probíhajícího běhu, úspěšné JUnit sady, závazné backendové i frontendové coverage,
backup s izolovaným restore testem, SBOM a bezpečnostní/vulnerability výsledky.
