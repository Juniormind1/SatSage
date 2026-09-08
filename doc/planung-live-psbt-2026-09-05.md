# SatSage (xPubQuery) — Planung 2026-09-05 (Live-PSBT, Mempool-Timing)

Status: Spezifikation. Umsetzung auf dem MacBook (`master-dev-hh`).
SatSage broadcastet nie. **Aktuell: Pfad Q.**

Siehe Index: [PLAN-LIVE-TESTFLOW.md](PLAN-LIVE-TESTFLOW.md) und UX [satsage-test-send-ui-ux.md](satsage-test-send-ui-ux.md).

## B1 Testprotokoll

Neue Datei später `doc/testprotokoll-live-psbt.md` (Stil wie Web-GUI-Stabilität).

Szenarien: L1 intern · L2 Testziel-fremd · L3 RBF · L4 Drop nur Signet/Regtest · L5 Block ohne Tx · L6 offene Ansicht · L7 consolidate-PSBT · L8 Multisig optional.

Dust 5 000–50 000 sats. Keine Secrets ins Git. 0-conf keine stille Steuer-Veräußerung.

## B2 Kein Remote-Broadcast durch Assistenten

Kein mempool.space. Messung nur eigener Node + `testmempoolaccept` + Flag `--broadcast`.

## B3 Timing-Harness (Pfad M, später)

`scripts/live_broadcast_timing.py` — Dry-Run default. Core: `.env` User/Pass, sonst Cookie. Ohne Core kein Broadcast.

T0 `sendraw` · T1 Pending-API · T2 1-conf. Report `tmp/live-timing-*.json`.

## B4 Pending-API

Erst vorhandenen JSON-Pfad lesen; Endpunkt nur bei Lücke.

## B5 Ablage

`tmp/live-psbt/` gitignoren.

## B7 Test-fremde XPUB

`SATSAGE_TEST_FREMD=1`, `TEST_FREMD_0_*`. Adressen kennen, kein Saldo/Steuer/meins. Badge „bekanntes Testziel“.

## B8 Test-Send-UI

Nav „Test senden“. Wizard 4 Schritte. Empfänger = Testziel. QR `ur:crypto-psbt` für BlueWallet.

**Pfad Q (jetzt):** BlueWallet signiert und sendet. T0 weich.
**Pfad M (später):** Signatur zurück, Senden Sparrow/Harness.

Leiste nennt den aktiven Pfad.

## Nicht anfassen

Verlaufsscan-Priorität (lokal auf dem Mac oft schon uncommitted). Harness/UI in eigenen Dateien, API nur additiv.

## Entscheidungen Nutzer

1 Core `.env` dann Cookie · 2 Pending erst lesen · 3 L4 Signet/Regtest · 4 Name SatSage (xPubQuery) · 5 Testziel nicht als Wallet.

## Reihenfolge MacBook

0 git diff (Verlauf) · 1 diese Docs sind schon da · 2 AGENTS-Satz · 3 gitignore · 4 B7+B8 Pfad Q · 5 Harness/Pfad M später
