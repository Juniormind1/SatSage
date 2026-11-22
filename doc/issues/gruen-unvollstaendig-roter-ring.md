# Issue: Grün, aber unvollständig — roter Ring bleibt nach Electrs stehen

**Status:** offen · Designfrage · kein Blocker für 1.0.2 (2026-11-22)
**Ort:** `core/steuer_fenster.py` (`klaeren_keys`), Knöpfe Grau/Lot-Grau/Gelb, `lab/regtest/scripts/verify_quellen_inventar.py` (Quelle 4, `electrs_nach_klaeren_ok`)

## Befund

Regtest-Labor vor Release 1.0.2, Quellen-Inventar, Quelle 4 „Bitcoin-P2P · Compact Filter“. Nach dem Electrs-Klären blieben auf einer Zufallskette zwei rote Ringe stehen („nach Electrs noch 2 rote Ringe“), zusätzlich zum erwarteten Sammel-Bündel.

- Betroffen: die zwei eigenen Outputs einer WabiSabi-artigen Tx (16 Eingänge, 16 Ausgänge, Szenario „Wabisabi-like“, Wallet Lab Alpha).
- P2P konnte einen Vorgänger nicht laden. Ein Eingang stammt aus einer eigenen Tx um Block 111; deren Vorgänger blieb ein Fehlerknoten „Vorgänger-Tx nicht ladbar … keine Blockhöhe bekannt (P2P-Tx: Peer hat die Transaktion nicht)“. Das ist die bekannte Grenze aus [`p2p-herkunft.md`](p2p-herkunft.md).
- Der Baum ist damit unvollständig (`vollstaendig: false`, Zeile `unvollstaendig`, roter Ring). Steuerlich ist das UTXO trotzdem grün: `geprueft`, `erfuellt`, `herkunft_offen`, `sats_ohne_datum = 0`, `sats_grau = 0`, Anschaffung „jüngste“ = Datum des jüngsten bekannten Zuflusses.
- Steuerlich korrekt: Der offene Zweig liegt vor der eigenen Tx um Block 111 und kann nur ein älteres Datum liefern. Das jüngste Datum ändert sich nicht.
- Die Knöpfe wählen nach `klaeren_keys`: Gelb = geprüft und Frist offen oder undatierte Anteile, Grau = ungeprüft in der Frist, Lot-Grau = geprüft mit grauen oder undatierten Anteilen. Ein grünes, aber unvollständiges UTXO fällt in keine Gruppe. Electrs verfolgt es deshalb nie neu, der Ring bleibt rot, obwohl Electrs den Baum vollständig liefern könnte (Quelle 1 „Eigener Electrum-Server“ allein ist auf derselben Kette grün).

Tritt nur bei bestimmten Zufallsketten auf: In vier Labor-Läufen (zwei mit Core v31.1, zwei mit Core 27.0 wie im CI-Image) war es genau einmal rot. Dieselbe Kette scheitert auch auf `00c35f8`, also vor den libbitcoin-Fixes; mit 1.0.2 hat es nichts zu tun. Im CI war das Labor auf `6322871` grün.

## Designfrage

Soll Gelb (oder ein eigener Schritt) auch grüne UTXOs mit unvollständigem Baum neu klären, sobald eine Quelle mit voller Herkunft (Electrs, Core mit `txindex`) verbunden ist?

- **Ja:** Der rote Ring verschwindet, sobald es möglich ist. Kostet zusätzliche Walks für UTXOs, deren Ergebnis sich steuerlich nicht ändert (bei „jüngste“). Bei „älteste“ kann der offene Zweig das Datum dagegen noch verschieben.
- **Nein:** Dann ist der Ring hier nur ein Hinweis, und die Labor-Prüfung muss grüne, unvollständige UTXOs nach dem Electrs-Klären dulden oder getrennt zählen (nicht stillschweigend, mit Begründung).

Vorschlag: In `klaeren_keys` eine Gruppe für `geprueft` und Baum unvollständig ergänzen, die Gelb mitnimmt, wenn die aktive Quelle die volle Herkunft liefern kann. Test in `tests/test_steuer_fenster.py`, Labor-Prüfung unverändert streng.

## Reproduktion (nur Regtest, keine echten Daten)

1. Regtest-Labor frisch aufsetzen (`lab/regtest`, Workflow `regtest-lab.yml` bzw. nativ mit `generate_scenarios.py --native`), Szenarien und Sanktions-Szenarien erzeugen.
2. `python3 lab/regtest/scripts/verify_quellen_inventar.py` laufen lassen. Die Kette ist zufällig; bei Rot steht in Quelle 4 „nach Electrs noch N rote Ringe“.
3. Auf derselben Kette die Schlüssel der roten Ringe nach `_buendel_offen_ausnehmen` ausgeben und den Steuer-Eintrag dazu ansehen: `erfuellt` und `herkunft_offen` sind beide wahr, der P2P-Baum unter `quellen-inventar/bip158/immutable_cache/utxo_trace/` enthält einen Knoten `type: error` („Vorgänger-Tx nicht ladbar“).
