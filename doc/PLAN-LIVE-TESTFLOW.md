# SatSage — Live-PSBT-Testflow (Spezifikation 2026-09-05)

**Status:** Spezifikation, noch kein Produktcode.  
**Regtest-Bot: Pfad R** (selbst bauen/signieren/broadcasten). Pfad Q (BlueWallet) und Pfad M bleiben für Mainnet/Signet.

SatSage-App broadcastet **nie**. Der Regtest-Harness (`lab/regtest/scripts/live_psbt_regtest_timing.py`) darf Core `sendrawtransaction` nur im Lab.

## Dateien

| Datei | Inhalt |
|-------|--------|
| [planung-live-psbt-2026-09-05.md](planung-live-psbt-2026-09-05.md) | Beschlüsse B1–B8, Entscheidungen, Reihenfolge |
| [satsage-test-send-ui-ux.md](satsage-test-send-ui-ux.md) | Wizard „Test senden“, Test-fremde XPUB, QR |
| [testprotokoll-webgui-stabilitaet.md](testprotokoll-webgui-stabilitaet.md) | bestehend, anderes Thema |

## Pfade

| | Q qualitativ (jetzt) | M Messung (später) |
|--|----------------------|---------------------|
| Signieren | BlueWallet, QR `ur:crypto-psbt` oder Datei | egal |
| Broadcast | BlueWallet Senden | Sparrow / Harness `--broadcast` eigener Node |
| T0 | Tap am Phone | lokales `sendraw` |
| Zweck | Pending, Badge Testziel, Settle | T0→T1→T2 |

## Kern

- Flag `SATSAGE_TEST_FREMD=1`, Keys `TEST_FREMD_0_*` (nicht `WALLET_n`).
- Empfänger = Testziel (adressbekannt, nicht eigen). Sender = Nutzer wählt Wallet.
- Dust 5k–50k sats. Dateien unter `tmp/live-psbt/` (gitignore).
- Nav nur mit Flag: **Test senden**. Vier Schritte: Sender → Betrag → unsigned PSBT → Signatur prüfen / beobachten.
- Leiste immer z. B. `Testflow L2 · Pfad Q · BlueWallet sendet — kein Timing`.
