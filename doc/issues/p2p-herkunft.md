# Issue: P2P reicht als Herkunft nicht

**Status:** offen · Herkunft und Verlauf bleiben zu (2026-10-10)
**Ort:** `core/p2p.py` (`p2p_gesperrt`, `p2p_nur_utxo_entdeckung`), Datenquellen
**Nächste Prüfung:** frühestens 2027-01-08

## Befund

P2P ohne Electrs ist keine ausreichende Datenquelle für Herkunft, Haltefrist und Stichtag.

Der UTXO-Bestand über BIP-158 Compact Filter funktioniert. Die Herkunft nicht. Bitcoin Core beantwortet `getdata` TX nur aus dem Mempool und dem zuletzt angehängten Block. `-txindex` ändert daran nichts. Eine bestätigte Vorgänger-Transaktion kommt als `notfound`. Das gilt im Labor und im Mainnet.

Was im Labor grün war, war Beifang: der Scan hatte den Block schon wegen eines eigenen Scripts geladen. Der Normalfall ist ein fremder Vorgänger, dessen Block nie geladen wurde. Ohne Betrag, Adresse und Datum des Zuflusses fehlen Haltefrist und Stichtag.

Ein Script-Nachlauf bis zur Ausgabehöhe würde SegWit-Vorgänger mit einem Block je unbekanntem Script schließen. Key-Path-Taproot fällt dabei aus, und das ist heute der übliche Empfang. Dafür bräuchte es eine Txid-zu-Block-Abbildung. Die baut Electrs. P2P hat sie nicht.

## Was wieder an ist

Die UTXO-Suche darf Compact Filter benutzen, und nur dann:

- `BIP158_P2P` ist nicht aus.
- Der eigene Electrum-Server (LAN oder eigenes Onion, nicht die öffentliche Rotation) ist nicht verbunden.
- scantxoutset ist nicht verbunden. Das ist der Pruned-Node-Slot, sonst der Lookup-Core. Verbunden heißt: `getblockchaininfo` antwortet. Beim Pruned Node ohne `txindex`. Ein Scan, der nach dem Handshake scheitert, bleibt verbunden — dann kein P2P.

Sockets öffnet nur `p2p_nur_utxo_entdeckung`. Schlägt die Suche fehl, bleibt der bisherige Fallback (öffentlicher Gap-Scan, wenn die Sitzung den hat).

Die Zeile „Bitcoin-P2P · Compact Filter“ ist wieder in den Datenquellen. Die Kopf-Pille zählt Peers nur, wenn diese Suche wirklich prüft. Ist Electrs oder scantxoutset verbunden, bleibt die Peer-Probe aus.

## Was zu bleibt

- Herkunft, Verlauf und `get_tx` über P2P.
- Header-Vorab (`starte_header_vorab` / `vorab_block_header`).
- `POST /api/p2p/walk-abgleich` antwortet 403 und schreibt den Electrs-Cache nicht an.
- `p2p_gesperrt()` bleibt wahr. Es wird nicht pauschal falsch.

Labor-Prüfer, die P2P als Herkunft fahren, starten weiter nicht: `verify_p2p_traces.py`, im Scan-Abbruch `Q-START-P2P` und `Q-START-KILL`. Sie laufen erst, wenn `p2p_gesperrt()` falsch wird (`doc/test-inventar.md`). Der Bestands-Schritt in `verify_quellen_inventar.py` ist davon getrennt: Compact Filter und das erwartete rote Klären öffnen Sockets nur in `p2p_nur_utxo_entdeckung`, danach klärt Electrs denselben Cache.

## Wann neu prüfen

Frühestens am 2027-01-08. Dann nur, ob sich an der P2P-Schnittstelle etwas Substanzielles geändert hat, das die Herkunfts-Lücke aufhebt: historische Transaktionen per `getdata`, oder eine andere Abbildung von Txid auf Block, die Key-Path-Taproot einschließt.

Ein Protokoll-Hinweis allein hebt die Sperre nicht. Aufheben heißt: den Befund gegen den Labor-Node und gegen einen Mainnet-Peer erneut prüfen, dann `p2p_gesperrt()` auf falsch setzen.
