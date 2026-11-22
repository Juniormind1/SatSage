# Börsen-Exporte · Specs

Eine Datei je Börse, **vor** dem Parser. Spalten, Zeilentypen, Zeitzone und
Zahlenformat kommen aus der Dokumentation der Börse, nicht aus einem
fremden Importer. Unbekannte Zeilentypen und unbekannte Köpfe werden nicht
geraten.

Status je Angabe:

- **offiziell** — Hilfeseite oder API-Doku der Börse, geprüft am angegebenen Stand
- **sekundär** — Doku von Steuer-Tools oder Beobachtungen Dritter
- **unbestätigt** — am eigenen Export prüfen, Ergebnis nur als Aggregat

Nur Bitcoin gegen Euro oder US-Dollar. Nur der CSV-Export, keine API.
Echte Exporte und xpubs gehören nicht ins Repository
(`tests/fixtures/boerse/`, `SATSAGE_DATA_DIR`).
