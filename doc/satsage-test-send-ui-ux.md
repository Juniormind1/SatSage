# SatSage (xPubQuery) — UX Test-Send-UI (L2-Testflow)

Status: Spezifikation. Flag `SATSAGE_TEST_FREMD=1`. Produktion ohne Flag = unsichtbar.
Gilt nur für Live-Protokoll L2: eigenes Wallet → Test-fremde XPUB.

**Aktuell gefragt: Pfad Q** (BlueWallet signiert und darf senden).
Index: [PLAN-LIVE-TESTFLOW.md](PLAN-LIVE-TESTFLOW.md).

## Was das ist / nicht ist

**Ist:** Lauf „PSBT schreiben → extern signieren → beobachten“.
**Nicht:** allgemeine Send-UI, eingebetteter Signer, SatSage-Broadcast.

### Zwei Pfade — UI nennt den aktiven

| | **Q qualitativ (jetzt)** | **M Messung (später)** |
|--|--------------------------|------------------------|
| Signieren | BlueWallet, QR `crypto-psbt` oder Datei | egal |
| Broadcast | BlueWallet Senden | Sparrow / Harness am eigenen Node |
| T0 | Tap am Phone | lokales `sendraw` |
| Zweck | Pending, Badge, Settle | T0→T1→T2 |

Leiste: `Testflow L2 · Pfad Q · BlueWallet sendet — kein Timing`.

Empfänger immer Testziel. Sender wählt der Nutzer.

## Sichtbarkeit

Nav **Test senden** nur wenn Flag an, ≥1 `TEST_FREMD_*`, ≥1 eigenes Wallet mit Cache.
Platz: Verwaltung, neben Wallets.
Gelbe Leiste: Ziel zählt nicht zum Bestand. SatSage signiert nicht.

## Wizard

1 Sender → 2 Betrag → 3 PSBT → 4 Signatur und Beobachten

### 1 Sender
Dropdown eigene Wallets. Empfänger starr: Testziel + gekürzte Receive + Index. Kein Adressfeld.

### 2 Betrag
Vorgabe 20 000 sats (Warnung außerhalb 5k–50k). Fee sat/vB, RBF. Kleinstes passendes UTXO. Change zurück in Sender-Wallet.

### 3 PSBT schreiben
Zusammenfassung, Knopf unsignierte PSBT. Datei `tmp/live-psbt/<lauf-id>/unsigned.psbt`, Base64, Download, optional animierter QR `ur:crypto-psbt`.
Kein Broadcast-Knopf. Hinweis: BlueWallet = Sender-Wallet mit Key, nicht Watch-only. Pfad Q: nach Signatur auf dem Phone senden. Pfad M: Datei zurück, nicht in BlueWallet senden.

### 4 Nach Signatur
Pfad Q: Beobachtung starten auch ohne signed-Import, sobald Nutzer „auf dem Phone gesendet“ bestätigt (TxID optional).
Pfad M: signed PSBT prüfen (final, gleiche Inputs, Output = Testziel), dann warten auf lokalen Broadcast.

OK → Ansicht Sender-Wallet. 0-conf: pending + Badge bekanntes Testziel. 1-conf: bestätigt + Befund.

## Semantik Testziel

Ableiten ja. Kein Saldo, keine Steuer, kein „meins“, kein Self-Transfer. `.env`: `TEST_FREMD_0_NAME` / `_XPUB` / `_SCRIPT`.

## API (additiv, Flag sonst 404)

- `GET /api/testflow/meta`
- `POST /api/testflow/psbt`
- `POST /api/testflow/signed`
- `GET /api/testflow/lauf/:id`

Reuse `consolidate.py` generalisieren. Verlaufsscan nicht anfassen.

## Nicht in v1

Freie Empfängeradresse, GUI-`sendrawtransaction`, Seed, Multisig-Cosign in der GUI.
