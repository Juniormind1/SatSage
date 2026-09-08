# Testprotokoll — Live-PSBT Pfad R (Regtest-Bot)

Datum: 2026-09-06 · Branch `master-dev-hh-regtest-bot` · Lab tip vor Lauf 221

## Harness

`lab/regtest/scripts/live_psbt_regtest_timing.py` — baut/signiert/broadcastet Dust Alpha→Beta, pollt:

- `GET /api/wallets/{id}/utxos` (Alpha, Beta)
- `GET /api/utxos`
- `GET /api/config`

## Lauf A (Index 30 Empfang, Report `tmp/live-timing-regtest.json`)

| Phase | Ergebnis | Dauer |
|-------|----------|-------|
| T0→Mempool Pending Spend (Alpha / Alle) | OK (`spending_pending=1`) | ~5 ms |
| Mempool Pending Receive (Beta) | **nicht** sichtbar | — |
| T0→1-conf + Tip-Nachzug | Alpha UTXO/Sats aktualisiert; Beta Empfang **nicht** im Cache | ~7 ms nach Mine für Alpha-Seite |
| Electrs nach 1-conf | Empfangsadresse hat 10 000 sats @ Höhe 222 | OK |

### Bewertung

- **Zuverlässig:** Mempool-Überlagerung für **ausgehende** Spends auf bereits gecachten UTXOs (Alpha, Alle-UTXOs).
- **Lücke:** `receive_pending` für neuen Empfang auf Beta fehlte in der Mempool-Phase.
- **Lücke:** Tip-Nachzug hat den bestätigten Empfang auf einer höheren Empfangsadresse (Index 30, nach Lücken 12–15) nicht in den UTXO-Cache übernommen — Electrs kannte ihn. Für Pfad-R-Messungen Empfangsadressen innerhalb der Gap-Scan-Reichweite wählen (nächste freie ab 0); ggf. Fullscan nach Mine.

## Nächster Lauf

Harness wählt jetzt die erste freie Empfangsadresse ohne Electrs-History (Gap-freundlich).

## Lauf B (Gap-freundlicher Index 12, `--after-mine rescan-beta`)

| Phase | Ergebnis | Dauer |
|-------|----------|-------|
| T0→Mempool Pending | **Timeout** — kein `spending_pending`/`receive_pending` in 120 s | — |
| Nach 1-conf + Beta-Fullscan | OK (`confirmed_ok`) | ~8 ms nach Mine |

Vermutung Mempool-Miss: Input war nach Lauf A nicht mehr zuverlässig im Alpha-UTXO-Cache, daher keine Spend-Überlagerung; Empfang weiter ohne `receive_pending`. Fullscan nach Bestätigung findet den Empfang.

## Fazit für UTXO-Ansichten

| Ansicht | Mempool-Spend | Mempool-Receive | 1-conf nach Tip-Sync | 1-conf nach Fullscan |
|---------|---------------|-----------------|----------------------|----------------------|
| Wallet-UTXOs Sender | meist ja, wenn Input gecacht | — | Sender-Saldo oft ja | ja |
| Wallet-UTXOs Empfänger | — | oft nein | oft nein | ja |
| Alle-UTXOs | wie Sender | schwach | gemischt | ja |
| Config-Salden | unverändert bis Sync/Scan | unverändert | Sender eher | Empfänger mit Fullscan |


## Lauf C (Finale Verifikation, Gap-Fenster, `tmp/live-timing-regtest.json`)

| Phase | Ergebnis | Dauer |
|-------|----------|-------|
| Mempool (Alpha/Beta/Alle) | **OK**: `spending_pending=1`, `receive_pending` Alpha 1 / Beta 1 / Alle 2 | `mempool_ok=true`, 5 ms |
| 1-conf + Tip-Sync, Beta Index 15 | **OK**: Beta-Cache enthält den neuen `bcrt1`-Output ohne Fullscan | `confirmed_ok=true`, 7 ms ab Mine |

Der erste Warmup-Lauf lag auf Index 13 unterhalb des damaligen 100er-Rückwärtsfensters; für die reproduzierbare Gap-Prüfung wurde der reine Regtest-Beta-Cache auf Scan-Ende 25 gesetzt. Der finale Lauf traf Index 15 im Fenster `[0, 25)`.
