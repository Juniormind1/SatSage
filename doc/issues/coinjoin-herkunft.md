# Issue: Korrekte Herkunftsverfolgung durch CoinJoins

**Status:** MVP umgesetzt (2026-09-11) · Klassifikation + Soft-Label + Own-only-Walk  
**Lab:** `lab/regtest/` — Wasabi-classic / WabiSabi / Whirlpool 5×5 / JoinMarket / PayJoin / Fan-Out / Exchange-Batch; Verify `scripts/verify_tx_classify.py`  
**Folge:** Whirlpool-Ketten (Remix × n); Einstellungen A/B/C

## Ziel

Herkunft (`trace`) korrekt und nachvollziehbar:

- Klassifikation n:m-Tx mit weichem Hinweis („Wahrscheinlich …“)
- Bei erkanntem CoinJoin: nur **eigene** Inputs weiterverfolgen (Hybrid-Walk)
- Wasabi Classic / WabiSabi / Whirlpool / JoinMarket
- Abgrenzung: Fan-Out (eigen), PayJoin, Exchange-Batch — **kein** CJ

## Klassifikation · Eigentum zuerst

Vor Formheuristik: **alle** `vin`/`vout` gegen konfigurierte XPUBs/Deskriptoren matchen (sonst kein Exchange-/PayJoin-Label). Billig zuerst Outs; bei Fan-out-Form und ≥1 eigenem Out die Input-Prevouts nachladen.

| Label | Eigene Inputs | Eigene Outputs | Form / Hinweis |
|--------|---------------|----------------|----------------|
| **Fan-Out (eigen)** | **alle** Ins eigen | 0 oder nur Change | du zahlst aus; viele Outs möglich |
| **PayJoin** | gemischt, **übersichtlich** viele Ins; **wenige** Fremd-Ins (typisch 1, selten 2) | Sender oft Change; Empfänger oft 1 Netto-Out | kollaborative Zahlung, **kein** Mix |
| **Exchange-Batch** | **0** eigen | genau 1 (selten mehr) | nur Empfang aus fremdem Fan-out |
| **Bisq-Payout** | **0** eigen | 1 von 2 | Escrow-Auszahlung; Deposit-Verhältnis; OP_RETURN am Deposit-Prevout verstärkt |
| **Bisq-Deposit** | egal | Escrow + `OP_RETURN` | v1-Escrow-Funding (≥2 Ins) |
| **CoinJoin** (Wasabi / Whirlpool / JM) | ≥1 eigen | ≥1 eigen | Anonymitätsmenge; Peers = Rauschen |

### Abgrenzung

- **Fan-Out vs. PayJoin:** Fan-Out = 0 Fremd-Ins; PayJoin = ≥1 Fremd-In, aber klein (Richtwert: Gesamt-Ins ≈ ≤5–8, Fremd-Ins ≤2).
- **Exchange-Batch vs. CJ:** ohne eigenen Input kein CoinJoin — Risiko der Verwechslung gering, sobald Input-Eigentum vollständig geklärt ist.
- **PayJoin vs. CJ:** keine große Peer-Menge / keine typischen Mix-Equal-Outs; PayJoin **nicht** in CJ-Stop-/Auflös-Optionen.
- Labels soft: „Wahrscheinlich …“ — keine forensische Sicherheit.

### Detektor-Reihenfolge

1. Eigentum aller Ins/Outs klären (soweit nötig)  
2. **0 eigene Ins** + eigene Outs → Exchange-Batch (bei Fan-out-Form)  
3. **alle Ins eigen** → Fan-Out (eigen) / normale Spende  
4. **wenige Ins, wenige Fremd** → PayJoin  
5. sonst Whirlpool → Wasabi/WabiSabi → JoinMarket → unklar/Sammel  

## Trace bei CoinJoin (erster Walk)

Semantik: CJ ist **kein** externer Zufluss; Anschaffung nur über **eigene** Vorfahren. Fremde Inputs nie auflösen.

| Stufe | Wann | Vorgehen |
|-------|------|----------|
| **1 · Index** | Verlauf/`spent_txid` brauchbar | eigene Outpoints mit `spent_txid == C` |
| **2 · Lücke** | Index unvollständig | `get_tx(C)` + Outpoint∩eigene / Adressraum∩vins; Prevouts nur für Treffer |

## Lab / Akzeptanz

- [x] Erkennung/Klassifikation (Tabelle oben) inkl. Fan-Out / PayJoin / Exchange-Batch / Bisq (`core/tx_classify.py`)  
- [x] Soft-Labels in Trace-UI (`web/app.js` + locales)  
- [x] Own-Input-Walk bei erkanntem CJ  
- [x] Regtest-Fixtures pro Typ (Wasabi-classic, WabiSabi, Whirlpool 5×5, JM, PayJoin, Fan-out, Exchange)  
- [ ] Trace-Verhalten dokumentiert (Anonymitäts-Set vs. verknüpfbare Edges) — Handbuch-Nachzug  
- [ ] Whirlpool-Ketten (Remix × n) — Folgepunkt, nicht MVP  

