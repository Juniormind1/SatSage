# Lernhinweise für Plebs — Kuratierung

Experiment zur Richtlinie [`design-neugier.md`](design-neugier.md).  
**Daten:** [`web/lernhinweise.json`](../web/lernhinweise.json) (Status `vorschlag` | `ok` | `verworfen`).  
**Dealbreaker:** T13 in [`merge-dealbreakers.md`](merge-dealbreakers.md).

## Qualitätsregel (hart)

1. Nur **Bitcoin**. Keine Shitcoins, keine Altcoins, kein Ethereum, kein „Crypto“-Gemischtwarenladen. Im Zweifel **warnen/blocken**, nicht durchwinken.
2. **Nur konkrete Inhalte zum jeweiligen Thema.**  
   Nie: Anbieter-Startseite, Mediathek-Index, Podcast-Übersicht, Shop, „Buch kaufen“, generische „Learn“-Landingpages.  
   Immer: ein bestimmter Artikel, Blogpost, BIP, Whitepaper-PDF, klar benannte Folge.
3. Inhalt: **Bitcoin-Mechanismen** für den lernfaulen Pleb — nicht SatSage-Implementierung, nicht IT-Ops.
4. Wortlaut im Tooltip: **„Geeignete Quelle für einen Einstieg in diesen Kaninchenbau“** (nicht „beste Quelle“).
5. Default: Einstellung **aus** → UI unverändert, Empfangs-QR nur Adressen.

Wenn ein Link schiefgeht (z. B. Aprycot landet im Shop statt im Artikel): sofort `verworfen` oder URL ersetzen — nicht stehen lassen.

## DE-Quellen (bevorzugt, aber immer Artikel-URL)

- [Aprycot Blog](https://aprycot.media/blog/) — EN→DE-Übersetzungen; **nicht** `aprycot.media/` oder `/thek/` allein  
- [Blocktrainer](https://www.blocktrainer.de/) — konkrete `/blog/…` oder `/wissen/…`-Seiten  
- [Einundzwanzig](https://einundzwanzig.space/) — konkrete Folge/Artikel, **nicht** die Podcast-Startseite  

EN-Fallback nur mit konkretem Pfad: bitcoin.org-Unterseiten, learnmeabitcoin-Artikel, nakamotoinstitute-Essays, bitcoinops-Topics, BIPs.

## Pflege

1. URL in `web/lernhinweise.json` setzen (konkreter Inhalt!).
2. `status` auf `ok` oder `verworfen`.
3. Handbuch-FAQ (§14) nachziehen / regenerieren.
4. `data-lern="<id>"` nur an passende UI-Elemente.

## Verhalten (wenn an)

- Tooltip erst nach ~1 s Hover (wie nativer `title`); dann Lern-QR mit derselben URL.
- Klick auf QR/URL: kopieren + neuer Tab.
- „Zurück zur Empfangsadresse“ stellt den Empfangs-QR wieder her.
