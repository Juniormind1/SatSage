# Strike · Account-Statement-CSV

**Stand:** 2026-11-22. SatSage importiert nur **Account Statements**
(monatlich oder jährlich als CSV), nicht den Activity-Export.
**offiziell**, [Transaction history](https://strike.me/support/where-can-i-find-my-transaction-history/):
Statement und Activity-Export dürfen nicht für denselben Zeitraum gemischt
werden, weil Duplikate sonst nicht erkennbar sind. Das folgt Entscheidung
**E11**, änderbar.

## Export

Im Web unter *Documents*, in der App unter *Account* → *Documents*.
Monatsauszüge erscheinen nach Monatsende, Jahresauszüge im Januar des
Folgejahres, jeweils PDF oder CSV. Über *Activity* lassen sich Vorgänge
zwar auch exportieren — SatSage liest diese Datei nicht.
**offiziell**, dieselbe Hilfeseite.

Strike veröffentlicht das Spaltenlayout **nicht**. Kopf, Typen und
Zahlenformat sind deshalb **sekundär**, soweit nicht anders vermerkt.

## Kopf

Typische Spalten, Kontowährung steckt im Namen der Fiat-Spalten
(`Amount EUR` oder `Amount USD`):

```
Reference,Date & Time (UTC),Transaction Type,Amount EUR,Fee EUR,Amount BTC,Fee BTC,BTC Price,Cost Basis (EUR),Destination,Description,Transaction Hash,Note
```

**sekundär**, u. a. Kassiber-Testdateien
(Commit [`7bf8dbbc`](https://github.com/bitcoinaustria/kassiber/blob/7bf8dbbc/tests/test_cli_smoke.py),
nur als Beobachtung, Quelltext nicht übernommen) und
[Ghostfolio #330](https://github.com/dickwolff/Export-To-Ghostfolio/issues/330).

Ältere Fassungen mit getrennten Datums- und Zeitspalten sind möglich
(**unbestätigt**). Ein unbekannter Kopf wird abgelehnt, nicht geraten.

| Spalte | Bedeutung | Status |
|---|---|---|
| `Reference` | eindeutige Zeilen-ID, Duplikatschlüssel | **sekundär** |
| `Date & Time (UTC)` | Zeitpunkt, UTC laut Spaltenname. Format typisch `Jan 15 2026 10:30:00` (`%b %d %Y %H:%M:%S`, englische Monatsnamen) | **sekundär** (Zeitzone im Namen; das Datumsformat selbst ist Beobachtung) |
| `Transaction Type` | siehe unten | **sekundär** |
| `Amount EUR` / `Amount USD` | Fiat-Betrag | **sekundär** |
| `Fee EUR` / `Fee USD` | Fiat-Gebühr | **sekundär** |
| `Amount BTC` | Bitcoin-Menge. Vorzeichen bei Käufen ist widersprüchlich dokumentiert (Kassiber positiv, Ghostfolio #330 negativ) — **unbestätigt**, Richtung zusätzlich aus dem Typ ableiten | **sekundär** |
| `Fee BTC` | Bitcoin-Gebühr. On-Chain geht typisch `Amount BTC` raus, `Fee BTC` kommt obendrauf | **sekundär** (Kassiber) |
| `BTC Price` | Kurs | **sekundär** |
| `Cost Basis (EUR)` bzw. USD | von Strike geführte Anschaffungskosten, von SatSage nicht als eigene Buchhaltung übernommen | **sekundär** |
| `Destination` | On-Chain-Adresse oder Lightning-Rechnung (`lnbc…`) | **sekundär** |
| `Description` / `Note` | Freitext | **sekundär** |
| `Transaction Hash` | nur bei On-Chain die TxID. Bei Lightning ist das der **Payment-Hash**, keine TxID | **sekundär**. Der bisherige Import in `exchange_reports.py` verwechselt das; der neue Parser darf einen LN-Hash nicht als Chain-Hop werten |

Zahlenspalten können den Platzhalter `-` enthalten (**sekundär**). Der
Parser behandelt `-` und eine leere Zelle als fehlenden Wert, nicht als
null.

## Typen

Alle Typen **sekundär**. Nur Bitcoin gegen Euro oder US-Dollar.

| Typ | SatSage |
|---|---|
| `Purchase`, `Buy` | **Kauf**. Richtung aus dem Typ, nicht allein aus dem Vorzeichen von `Amount BTC` |
| `Sell` | **Verkauf** |
| `Receive` | **Einzahlung**, wenn On-Chain |
| `Send` | **Auszahlung**, wenn On-Chain. Die TxID steht in `Transaction Hash`, Zuordnung kann exakt sein |
| Fiat-`Deposit` / `Withdrawal` | Fiat-Eingang bzw. -Ausgang, kein BTC-Los |
| P2P-Typen | **Quarantäne** (nicht eindeutig auf Kauf/Verkauf gegen EUR/USD abbildbar) |
| Lightning-`Send` / `Receive` (`Destination` beginnt mit `lnbc`) | Erklärung ohne Chain-Hop, **keine** Auszahlung in die xpub-Welt |
| unbekannter Typ | **Quarantäne**, nicht geraten |

## Regeln für den Parser

- Nur Statement-CSV. Eine Datei, die wie ein Activity-Export aussieht (anderer Kopf), wird abgelehnt.
- `Transaction Hash` wird nur dann als TxID gelesen, wenn `Destination` eine On-Chain-Adresse ist und der Wert wie eine 64-stellige Hex-TxID aussieht.
- Eine Lightning-Zeile bleibt Lücke, kein erfundener Zugang.
- Synthetische Fixtures nutzen `STSYN…` als `Reference`, BIP-Testvektor-Adressen, `txid()` für On-Chain und ein erkennbares Payment-Hash-Muster für Lightning, das keine gültige TxID ist.
