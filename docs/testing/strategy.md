# Testovací strategie

Release sada odděluje unit, integration, contract, E2E, accessibility, visual, AI eval, performance, security, backup/restore a acceptance. Kritické scénáře mají pozitivní i negativní variantu. Backend coverage má hranici 90 %, AI eval 95 % a nulové kritické selhání. Playwright pokrývá desktop i mobil, přístupnost a klíčové vizuální stavy. `make release-check` zastaví vydání při prvním kritickém neúspěchu a nikdy jej nepřepíše ručním PASS.
