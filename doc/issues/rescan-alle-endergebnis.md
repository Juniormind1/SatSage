# Issue: Endergebnis von „Alle Wallets scannen“ ohne UTXOs je Wallet

**Status:** offen · niedrige Priorität, kein Blocker für 1.0.0 (2026-10-12)
**Ort:** `httpserver/api/source.py` (`api_rescan_alle`), Job-Status `result.utxo_je_wallet`

## Befund

Seit `452fb2c` zählt der Job `rescan-alle` die UTXOs je Wallet in den Zwischenständen live hoch (`result.utxo_je_wallet`). Im Endergebnis (Status `done`) fehlt das Feld; dort steht nur die Meldung „n UTXOs in m Wallets“.

## Auswirkung

Heute keine. Die Nav-Pille merkt sich den letzten Zwischenstand, und nach dem Scan zeigt die GUI ohnehin `utxo_count` aus `/api/config`.

Relevant würde es erst, wenn jemand den Job-Status nach dem Ende abfragt: Skripte oder API-Clients, oder eine Seite, die während bzw. kurz nach dem Scan neu geladen wird und nur noch den fertigen Job sieht.

## Fix-Vorschlag

In `api_rescan_alle` `utxo_je_wallet` aus den gefundenen UTXOs auch ins Endergebnis schreiben. Test in den Job-Tests ergänzen (Endergebnis enthält die Zahlen je Wallet, Summe = `utxo_count`).
