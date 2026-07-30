# Datový model

Všechny doménové identifikátory jsou UUID, časy se ukládají v UTC a měnitelné agregáty mají `version` pro optimistické zamykání. Alembic migrace jsou jediným zdrojem schématu.

Hlavní agregáty: instance; administrátorský účet, profil, credential, relace a bezpečnostní tokeny; poskytovatelé, šifrovaná tajemství, katalog modelů a nastavení; konverzace, zprávy, revize, vazby a shrnutí; paměťové položky, verze a provenience; vyhledávací dokumenty a embeddingy; idempotence, joby, outbox, doručení oznámení; audit; zálohy a exporty.

Měkké odstranění zachovává auditovatelný stav do `purge_after`; definitivní mazání vykonává worker podle retence. Obnova respektuje stav zálohy a nesmí neoznačeně oživit odstraněná data.
