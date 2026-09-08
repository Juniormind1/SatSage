# Issue: Korrekte Herkunftsverfolgung durch CoinJoins

**Status:** offen (GitHub Issues-PAT fehlt Schreibrecht — lokal getrackt)  
**Branch:** `master-dev-hh-regtest-bot`

## Ziel
Herkunft (`trace`) korrekt und nachvollziehbar durch CoinJoins:

- Wasabi Classic
- WabiSabi
- Whirlpool
- JoinMarket

## Lab
Zwei CJ-ähnliche Regtest-Txs (24 in / 28 out) in `/workspace/satsage-lab` (`CJ-Runde-1`, `CJ-Runde-2`).

## Akzeptanz
- [ ] Erkennung/Klassifikation der CJ-Struktur
- [ ] Trace-Verhalten dokumentiert (Anonymitäts-Set vs. verknüpfbare Edges)
- [ ] Regtest-Szenario + Test/Protokoll
