# Vývojové prostředí

Použijte přesně Python 3.12, uv a Node 22 uvedené v manifestu. `make bootstrap` provede `uv sync --frozen` nad `backend/uv.lock` a `npm ci` nad `web/package-lock.json`. Testovací databáze musí mít explicitní testovací název a nesmí používat produkční URL. Vývojové tajemství vytvářejte skriptem; nikdy je necommitujte.
