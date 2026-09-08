# Start9-Backup-Umfang

Die folgenden Dateien und Verzeichnisse gehören in das App-Volume-Backup:

- `.env` einschließlich der automatischen `.env.bak` (Wallet-Konfiguration und Outbound-Einstellungen).
- `.satsage-password` bzw. die konfigurierte Passwortdatei (Passwort-Hash).
- `utxo_cache/`, `immutable_cache/`, `label_cache/` und `sanctioned_cache/`, soweit ein schneller Restore gewünscht ist.

Große abgeleitete Caches können optional ausgeschlossen und nach dem Restore neu aufgebaut werden; dadurch verlängert sich der erste Scan. Seed- oder Private-Key-Dateien gehören nicht in SatSage und werden nicht durch diese Doku erzeugt.

Die spätere Start9-Wrapper-Datei `instructions.md` muss diesen Umfang und den Restore-Ablauf in die Package-Anleitung übernehmen. Das Wrapper-Repo selbst ist nicht Teil dieser Phase.
