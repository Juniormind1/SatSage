# Issue: P2P reicht als Datenquelle nicht

**Status:** offen · P2P abgeklemmt (2026-10-08)
**Ort:** `core/p2p.py` (`p2p_gesperrt`), Datenquellen, Kopf-Pille
**Nächste Prüfung:** frühestens 2027-01-08

## Befund

P2P ohne Electrs ist keine ausreichende Datenquelle für einen sinnvollen Betrieb von SatSage.

Der UTXO-Bestand über BIP-158 Compact Filter funktioniert. Die Herkunft nicht. Bitcoin Core beantwortet `getdata` TX nur aus dem Mempool und dem zuletzt angehängten Block. `-txindex` ändert daran nichts. Eine bestätigte Vorgänger-Transaktion kommt als `notfound`. Das gilt im Labor und im Mainnet.

Was im Labor grün war, war Beifang: der Scan hatte den Block schon wegen eines eigenen Scripts geladen. Der Normalfall ist ein fremder Vorgänger, dessen Block nie geladen wurde. Ohne Betrag, Adresse und Datum des Zuflusses fehlen Haltefrist und Stichtag.

Ein Script-Nachlauf bis zur Ausgabehöhe würde SegWit-Vorgänger mit einem Block je unbekanntem Script schließen. Key-Path-Taproot fällt dabei aus, und das ist heute der übliche Empfang. Dafür bräuchte es eine Txid-zu-Block-Abbildung. Die baut Electrs. P2P hat sie nicht.

## Bis die Einschränkung fällt

- Jeder P2P-Socket bleibt zu (`P2pGesperrt` in `_oeffne_socket`). Das gilt auch für den Port-8333-Check, den Header-Vorab und den Check-P2P-Job.
- Die Zeile „Bitcoin-P2P · Compact Filter“ bleibt aus den Datenquellen.
- Die P2P-Pille bleibt aus der Kopfzeile.
- `BIP158_P2P=1` schaltet den Verkehr nicht wieder ein.

Labor-Prüfer, die P2P absichtlich gegen den Regtest-Node fahren, sind von dieser Betriebssperre mit betroffen. Die Testsuite startet sie nicht: `verify_p2p_traces.py` sowie im Scan-Abbruch `Q-START-P2P` und `Q-START-KILL` (`doc/test-inventar.md`). Sie laufen erst wieder, wenn die Sperre fällt.

## Wann neu prüfen

Frühestens am 2027-01-08. Dann nur, ob sich an der P2P-Schnittstelle etwas Substanzielles geändert hat, das diese Einschränkung aufhebt: historische Transaktionen per `getdata`, oder eine andere Abbildung von Txid auf Block, die Key-Path-Taproot einschließt.

Ein Protokoll-Hinweis allein hebt die Sperre nicht. Aufheben heißt: den Befund gegen den Labor-Node und gegen einen Mainnet-Peer erneut prüfen, dann `p2p_gesperrt()` auf falsch setzen und Zeile sowie Pille wieder zeigen.
