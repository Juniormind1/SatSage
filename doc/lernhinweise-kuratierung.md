# Lernhinweise für Plebs — Kuratierung

Experiment zur Richtlinie [`design-neugier.md`](design-neugier.md).  
**Daten:** [`web/lernhinweise.json`](../web/lernhinweise.json) (Status `vorschlag` | `ok` | `verworfen`).

## Qualitätsregel (hart)

- Nur **Bitcoin**. Keine Shitcoins, keine Altcoins, kein Ethereum, kein „Crypto“-Gemischtwarenladen. Dealbreaker **T13**: im Zweifel warnen/blocken, nicht durchwinken.
- Inhalt: **Bitcoin-Mechanismen** für den lernfaulen Pleb — nicht SatSage-Implementierung, nicht IT-Ops („wie der Gap-Scan in SatSage läuft“).
- Wortlaut im Tooltip: **„Geeignete Quelle für einen Einstieg in diesen Kaninchenbau“** (nicht „beste Quelle“).
- Default: Einstellung **aus** → UI unverändert, Empfangs-QR nur Adressen.

## DE-Priorität (vom Maintainer)

1. [Aprycot Media](https://aprycot.media/) / [Mediathek](https://aprycot.media/thek/) / **[Blog](https://aprycot.media/blog/)** (viele EN→DE-Übersetzungen — ideale „deutsche Quelle zu englischen Texten“)
2. [Blocktrainer](https://www.blocktrainer.de/)
3. [Einundzwanzig](https://einundzwanzig.space/)

EN-Fallback: bitcoin.org, learnmeabitcoin.com, nakamotoinstitute.org, bitcoinops.org, bitcoin-only.com — ebenfalls Bitcoin-only prüfen.

### Aprycot-Blog (Übersetzungen) — Mapping-Beispiele

| Thema-ID | DE (Aprycot) | EN-Original / Pendant |
|----------|--------------|------------------------|
| `node` | [/blog/node-weltordnung/](https://aprycot.media/blog/node-weltordnung/) | Goldstein / bitcoin.org full-node |
| `selbstverwahrung` | [/blog/liebe-familie-liebe-freunde/](https://aprycot.media/blog/liebe-familie-liebe-freunde/) | Gigi „Dear family…“ |
| `utxo` | [/blog/1-die-innovation-basierend-auf-grundprinzipien/](https://aprycot.media/blog/1-die-innovation-basierend-auf-grundprinzipien/) | Farrington / learnmeabitcoin UTXO |
| `geld` | [/blog/die-natur-des-wertes/](https://aprycot.media/blog/die-natur-des-wertes/) | Nakamoto Institute |

## Pflege

1. URL in `web/lernhinweise.json` setzen oder ersetzen.
2. `status` auf `ok` oder `verworfen`.
3. `data-lern="<id>"` an passende UI-Elemente (Tooltip-Träger) hängen — nur wenn Einstellung an.

## Verhalten (wenn an)

- Tooltip: bestehender Text + Kaninchenbau-Zeile + URL.
- Empfangs-Pane: bei aktivem Lern-Thema QR = URL, Label **„Lernstoff für …“**; Klick kopiert und öffnet neuen Tab.
- Ohne aktives Thema: weiterhin Empfangsadresse.
