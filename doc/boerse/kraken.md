# Kraken · CSV-Export

**Stand:** 2026-11-22. SatSage importiert *Ledgers* und *Trades* als CSV
(TSV aus der API hat dieselben Spalten). PDF, *Balances* und *Account
Statement* werden nicht gelesen.

## Export

Profilsymbol → *Documents* → *Exports* → *Create Export*. Typ *Ledgers*
oder *Trades*, Zeitraum, Format CSV. Die Verarbeitung kann dauern; es
gibt keine E-Mail, wenn die Datei fertig ist.
**offiziell**, [Export](https://support.kraken.com/articles/208267878-how-to-export-your-account-history)
(Stand 29.05.2026). Felder lassen sich abwählen. Ohne `refid` ist keine
Paarung möglich — das ist ein Fehler mit Hinweis, kein stilles
Weiterarbeiten.

API-Export (`AddExport`, CSV oder TSV) nennt dieselben wählbaren Spalten.
SatSage importiert keine API-Daten, die Feldliste gilt trotzdem.
**offiziell**, [AddExport](https://docs.kraken.com/api-reference/account-data/request-export-report).

## Ledgers

Kopf, typische Reihenfolge, Felder optional:

```
"txid","refid","time","type","subtype","aclass","subclass","asset","wallet","amount","fee","balance"
```

Werte sind gequotet (**sekundär**, typisches CSV der Website).

| Spalte | Bedeutung | Status |
|---|---|---|
| `txid` | Ledger-ID (`L…-…-…`), stabil, Duplikatschlüssel | **offiziell**, [Ledger-Felder](https://support.kraken.com/articles/360001169383-how-to-interpret-ledger-history-fields) (Stand 06.10.2026) |
| `refid` | verbindet zusammengehörige Zeilen; bei `trade` die Gegenzeile und der Eintrag in `trades.csv` | **offiziell**, [Ledger vs. Trades](https://support.kraken.com/articles/115000302707-differences-between-ledger-and-trades-history) und AddExport-Feldliste |
| `time` | Datum und Zeit in **UTC**, Format `YYYY-MM-DD HH:MM:SS` mit Bruchteilen | **offiziell** (Zeitzone in den Ledger-Feldern; das Format mit Mikrosekunden in den [Trades-Feldern](https://support.kraken.com/articles/360001184886-how-to-interpret-trades-history-fields), `YYYY-MM-DD HH:MM:SS.0000`) |
| `type` | siehe unten | **offiziell**, Ledger-Felder |
| `subtype` | siehe unten | **offiziell**, Ledger-Felder |
| `aclass` | immer `currency`, ohne Bedeutung | **offiziell**, Ledger-Felder |
| `subclass` | etwa `fiat` / `crypto` | **unbestätigt** (nicht in der offiziellen Feldliste, nur in einzelnen Exporten gesehen) |
| `asset` | Vermögenswert der Zeile; Betrag, Gebühr und Saldo sind dieselbe Einheit | **offiziell**, Ledger-Felder |
| `wallet` | etwa `spot / main`, `earn / flexible`; in älteren Exporten oft fehlend | **offiziell** als wählbares Feld in AddExport; die Bezeichnungen selbst sind **sekundär** |
| `amount` | mit Vorzeichen, Belastung negativ | **offiziell**, Ledger-Felder |
| `fee` | in derselben Einheit wie die Zeile | **offiziell**, Ledger-Felder |
| `balance` | Saldo danach: `alt ± amount − fee` | **offiziell**, Ledger-Felder |

Kontinuitätsprüfung je `(asset, wallet)`, fehlendes `wallet` als eine
gemeinsame Tasche. Eine Lücke im Saldo bedeutet einen unvollständigen
Export (Zeitraumfilter), keinen stillen Ausgleich.

### Typen (Ledger)

Alle Typen **offiziell** (Ledger-Felder, Stand 06.10.2026). SatSage
ordnet nur BTC gegen EUR oder USD zu; alles andere wird Quarantäne oder
ignoriert, nie geraten.

| `type` | Bedeutung laut Kraken | SatSage |
|---|---|---|
| `trade` | Tausch ohne Margin | Mit Fiat-Gegenzeile gleicher `refid`: **Kauf** oder **Verkauf**. Ohne Fiat-Gegenzeile (BTC gegen Krypto): **Quarantäne** |
| `spend` / `receive` | Kauf über *Buy Crypto* oder die App; `spend` belastet, `receive` schreibt gut | Wie ein Trade, Paarung über `refid`. Bei Kartenzahlung kommt zusätzlich `deposit` in Fiat für den vollen Kartenbetrag (**offiziell**) |
| `deposit` | Einzahlung, inkl. Kartenkauf und Zukunfts-Wallet | BTC: **Einzahlung**. EUR/USD: Fiat-Eingang, kein BTC-Los |
| `withdrawal` | Auszahlung aus dem Kraken-Konto | BTC: **Auszahlung**. Im Ledger steht **keine** Blockchain-TxID (**sekundär**, bestätigt durch die offizielle Feldliste: es gibt keine Tx-Hash-Spalte). Zuordnung zur Chain nur über Betrag und Zeit, als Vorschlag |
| `transfer` / `earn` | intern, inkl. Earn/Staking und Futures | Spot↔Earn/Staking-Subtypen mit gleicher `refid`: **intern**, Bestand und Lose bleiben. `spottofutures` / `spotfromfutures`: **Quarantäne** |
| `staking` | vor allem Staking-Erträge | **Quarantäne** (kein Kauf gegen Fiat) |
| `margin trade`, `rollover`, `settled` | Margin | **Quarantäne** |
| `adjustment` | Umwandlung außerhalb des Handels | **Quarantäne** |
| `invite bonus` | Empfehlungsprämie | **Quarantäne** |
| `sale` | nur Filter in der Oberfläche, nicht im Export | kommt nicht vor |

### Subtypen

**offiziell**, Ledger-Felder. Für SatSage relevant:

- Spot↔Earn: `allocation`, `deallocation`, `autoallocate`
- älteres Staking: `spottostaking`, `stakingfromspot`, `stakingtospot`, `spotfromstaking`
- `migration`: interne Umbuchung, Portfolio unverändert → **intern**
- `reward`: Ertrag → **Quarantäne**
- `spottofutures`, `spotfromfutures` → **Quarantäne**

## Trades

Kopf:

```
"txid","ordertxid","pair","time","type","ordertype","price","cost","fee","vol","margin","misc","ledgers"
```

In der offiziellen Tabelle heißt die Auftragsspalte `order-type`, in der
AddExport-Liste `ordertype`. Beide Namen werden erkannt.
**offiziell**, [Trades-Felder](https://support.kraken.com/articles/360001184886-how-to-interpret-trades-history-fields) (Stand 06.10.2026) und AddExport.

| Spalte | Bedeutung | Status |
|---|---|---|
| `txid` | Ausführungs-ID; eine Order kann mehrere Ausführungen haben | **offiziell** |
| `ordertxid` | Order-ID, bei Teilausführungen gleich | **offiziell** |
| `pair` | Basis + Quote | **offiziell** |
| `time` | UTC, `YYYY-MM-DD HH:MM:SS.0000` | **offiziell**. Excel zeigt oft nur die Uhrzeit; die Daten stehen in der Datei |
| `type` | `buy` oder `sell` | **offiziell** |
| `ordertype` / `order-type` | `limit`, `market`, `touched market`, `stop market`, `liquidation market` | **offiziell** |
| `price` | Quote je einer Einheit Basis | **offiziell** |
| `cost` | `price × vol`, **ohne** Gebühr | **offiziell** |
| `fee` | immer in der Quote-Währung, auch wenn sie in der Basis abgezogen wurde | **offiziell**. Was wirklich abgezogen wurde, zeigt nur das Ledger |
| `vol` | Menge der Basis | **offiziell** |
| `margin` | eingesetzte Margin in Quote; `0` = kein Margin-Handel | **offiziell** |
| `misc` | u. a. `closing`, `initiated` | **offiziell** |
| `ledgers` | zugehörige Ledger-IDs (Basis und Quote, bei Margin ggf. mehr) | **offiziell** |

Das Ledger ist maßgeblich für Sats und Gebühren. `trades.csv` liefert
Kurs und Paar. Fehlt `trades.csv`, wird der Kurs aus der Fiat-Gegenzeile
im Ledger gerechnet (Fiat-Betrag ÷ BTC-Betrag, gleiche `refid`). Das ist
Entscheidung **E9**, änderbar.

## Asset-Codes

`XXBT` und `XBT` sind Bitcoin, `ZEUR` ist Euro, `ZUSD` ist US-Dollar.
**offiziell**, [XBT vs. BTC](https://support.kraken.com/articles/360001206766-bitcoin-currency-code-xbt-vs-btc)
(Stand 02.11.2026). Suffixe wie `.M`, `.S`, `.F`, `.HOLD` kommen in der
Asset-Liste vor (**offiziell** als existierende Codes in der
[API-Symbol-Doku](https://support.kraken.com/articles/360000920306-api-symbols-and-tickers));
die genaue Bedeutung im Ledger-Export ist **sekundär**. BTC-Varianten
zählen zum Bitcoin-Bestand desselben Kontos, sobald der Code erkennbar
Bitcoin ist. Unbekannte Suffixe ohne klare BTC-Zuordnung: **Quarantäne**.

## Regeln für den Parser

- Unbekannter `type` oder unbekannter Kopf: nicht raten, Quarantäne bzw. Ablehnung mit den Spaltennamen (ohne Werte).
- Zeilen ohne Bitcoin und ohne EUR/USD bleiben draußen.
- Eine Zeile ohne passende Fiat- oder BTC-Gegenzeile wird kein Kauf und kein Verkauf.
- Teilausführungen in derselben Sekunde (`ordertxid` wiederholt sich) bleiben einzelne Buchungen und werden über die Ledger-IDs zusammengehalten.
- IDs in synthetischen Fixtures tragen das Präfix `LSYN` bzw. `TSYN`.
