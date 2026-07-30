# Bezpečnost

Bezpečnostní vady oznamujte neveřejným kanálem provozovateli instance. Do hlášení nevkládejte hesla, API klíče, resetovací tokeny, úplné přepisy ani zálohy. Kritická zranitelnost blokuje vydání. Podporovaná je pouze aktuální produkční větev a poslední vydaná verze.

## Povinné zásady

- produkce výhradně přes HTTPS;
- tajemství pouze v šifrovaném úložišti a kořenové infrastrukturní konfiguraci;
- žádná tajemství v repozitáři, logu, URL, localStorage ani exportu;
- serverová autorizace každého chráněného požadavku;
- bezpečné odmítnutí při neověřitelném stavu;
- audit bezpečnostně významných událostí bez soukromého obsahu.
