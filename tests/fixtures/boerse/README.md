# Synthetische Börsen-Fixtures

Hier liegen nur **synthetische** oder vollständig anonymisierte CSV-Dateien
für Kraken, Coinbase und Strike. Echte Exporte und xpubs gehören nicht ins
Repository und nicht auf die Agenten-Box; sie bleiben auf dem Rechner des
Maintainers (siehe Plan M0, `SATSAGE_DATA_DIR` / `~/SatSage-private`).

Jede CSV braucht eine Begleitdatei `<name>.csv.herkunft.md` mit einer der
Angaben:

- `synthetisch`
- `anonymisiert mit Skript-Version …, geprüft von Juniormind1 am …`

Ohne Herkunftsdatei blockiert `scripts/leak_scan.py` den Commit (sobald der
Hook freigegeben ist) und den Unit-Test `tests/test_leak_scan.py`.
