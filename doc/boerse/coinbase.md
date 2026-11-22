# Coinbase · CSV-Statement

**Stand:** 2026-11-22. SatSage importiert nur das **eigene transaktionsbezogene
CSV-Statement** (*Generate custom statement*), nicht die Steuerzentrale, nicht
Gain/Loss und nicht den Fills-Export von Coinbase Advanced (kommt später,
Entscheidung **E11**, änderbar).

## Export

Profil → *Settings* → *Accounts* → *Statements*, oder unmittelbar
[accounts.coinbase.com/statements](https://accounts.coinbase.com/statements).
*Generate custom statement*: Asset *All*, Transaction type *All*, Zeitraum,
Format CSV.
**offiziell**, [Account statements](https://help.coinbase.com/en/coinbase/taxes/tools/statements).
Coinbase veröffentlicht das Spaltenlayout **nicht**. Alle Spalten, die
Präambel und die Typen sind deshalb **sekundär**, soweit nicht anders
vermerkt.

## Präambel und Kopf

Über dem Kopf stehen typischerweise drei Zeilen, der Kopf in Zeile 4:
eine Leerzeile oder der Titel `Transactions`, dann `User,<Name>,<UUID>`.
Die Präambel enthält den **Klarnamen**. Leak-Scan und Anonymisierer müssen
sie behandeln. **sekundär**, u. a. [cryptotaxcheck.uk](https://cryptotaxcheck.uk/supported-exchanges/coinbase)
(geprüft 27.09.2026) und übliche Testdateien.

Ein unbekannter Kopf wird abgelehnt (*Format nicht erkannt*), es wird nicht
geraten. Erkennung über die exakte Kopfzeile (Spaltenmenge). Ob der Kopf
englisch bleibt, wenn die Oberfläche deutsch ist, ist **unbestätigt**.

| Variante | Kopf | Status |
|---|---|---|
| 2024+ | `ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),Fees and/or Spread,Notes` (optional `Sender Address`, `Recipient Address`) | **sekundär** |
| 2024 ohne `ID` | dasselbe ohne die erste Spalte | **sekundär** |
| 2023 | `Timestamp,…,Spot Price Currency,Spot Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),Fees and/or Spread,Notes` | **sekundär** |
| 2021–22 | `…,Subtotal,Total (inclusive of fees),Fees,Notes` | **sekundär** |
| 2019–20 | Fiat-Präfix in den Wertspalten, z. B. `EUR Spot Price at Transaction`, `EUR Subtotal`, `EUR Total (inclusive of fees)`, `EUR Fees` | **sekundär** |

Quellen der Varianten: [cryptotaxcheck.uk](https://cryptotaxcheck.uk/supported-exchanges/coinbase),
[cryptact](https://grid.cryptact.com/exchanges/coinbase), [BittyTax #390](https://github.com/BittyTax/BittyTax/issues/390).

## Spalten

| Spalte | Bedeutung | Status |
|---|---|---|
| `ID` | eindeutige Zeilen-ID, Duplikatschlüssel; fehlt in manchen 2024er Dateien | **sekundär**. Ohne ID gilt ein Hash aus Zeit, Typ, Menge und Subtotal |
| `Timestamp` | Zeitpunkt, offenbar UTC, oft mit Suffix ` UTC` | **sekundär** / Zeitzone **unbestätigt** |
| `Transaction Type` | siehe unten | **sekundär** |
| `Asset` | `BTC` und andere Kürzel | **sekundär** |
| `Quantity Transacted` | Menge. Ob bei *Send* die Netzwerkgebühr enthalten ist, ist **unbestätigt** | **sekundär** |
| `Price Currency` / `Spot Price Currency` | Kontowährung, für SatSage nur EUR oder USD | **sekundär** |
| `Price at Transaction` / `Spot Price at Transaction` | Kurs | **sekundär** |
| `Subtotal` | Wert ohne Gebühr, in der Kontowährung | **sekundär** |
| `Total (inclusive of fees and/or spread)` bzw. ältere `Total (inclusive of fees)` | Wert inkl. Gebühr/Spread | **sekundär** |
| `Fees and/or Spread` bzw. ältere `Fees` | Mischwert aus Gebühr und Spread, nicht getrennt | **sekundär** |
| `Notes` | Freitext: Zieladresse bei *Send* („… to bc1…“), Gegen-Asset bei *Convert* | **sekundär** |
| `Sender Address` / `Recipient Address` | optional ab 2024+ | **sekundär** |

Geldspalten können Währungssymbol und Tausendertrenner enthalten
(`€1,234.56`, `-€…`). **unbestätigt**, der Zahlenparser muss beides und
eine leere Zelle vertragen.

## Typen

Alle Typen **sekundär**. Nur BTC gegen EUR oder USD.

| Typ | SatSage |
|---|---|
| `Buy`, `Advanced Trade Buy` | **Kauf** |
| `Sell`, `Advanced Trade Sell` | **Verkauf** |
| `Send` | **Auszahlung**. Oft keine TxID; Adresse in `Notes` oder `Recipient Address`. Zuordnung zur Chain über Adresse, sonst Betrag und Zeit als Vorschlag |
| `Receive` | **Einzahlung** |
| `Deposit`, `Withdrawal` (Fiat) | Fiat-Eingang bzw. -Ausgang, kein BTC-Los |
| `Convert` | **Quarantäne** (BTC gegen Krypto, Gegen-Asset nur in `Notes`) |
| `Rewards Income`, `Staking Income`, `Learning Reward` | **Quarantäne** (kein Kauf gegen Fiat, Bewertung offen) |
| `Pro Deposit`, `Pro Withdrawal`, `Exchange Deposit`, `Exchange Withdrawal` | **intern** (Bewegung innerhalb von Coinbase/Pro) |
| unbekannter Typ | **Quarantäne**, nicht geraten |

## Regeln für den Parser

- Nur dieser Statement-CSV. Advanced-Fills und Steuer-Reports werden abgelehnt.
- Zeilen ohne Bitcoin und ohne EUR/USD bleiben draußen.
- *Send* ohne passenden Chain-Hop wird kein Zugang und kein Anschaffungsdatum.
- Synthetische Fixtures nutzen erfundene IDs (`CBSYN…`), BIP-Testvektor-Adressen und `txid()`-Muster. Die Präambel enthält nur Platzhalter, niemals einen Klarnamen.
