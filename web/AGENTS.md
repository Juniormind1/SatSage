# AGENTS.md — `web/`

Gilt für `web/` (Oberfläche, Locales, `app.js`, Views) **und** für gerenderte API-Daten, die diese Oberfläche zeigt. Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

Modulgrenzen (wo neue UI-Logik hingehört) stehen in [`../core/AGENTS.md`](../core/AGENTS.md).

## UI-Konventionen

- **Sprache:** UI, Prompts und Nutzerkommunikation auf **Deutsch**
- **Node verbinden:** Leitbild in [`../doc/design-node-anbindung.md`](../doc/design-node-anbindung.md) — dem Nutzer den Node so einfach wie möglich machen; typische Heimnetz-/TLS-/Port-Fallen selbst abfangen; Härte nur wo nötig (Clearnet, Opt-in), nicht als Kollateralschaden auf Desktop-LAN oder Start9-Bridge.
- **Flüchtigkeit / Eile:** Leitbild in [`../doc/design-fluchtigkeit.md`](../doc/design-fluchtigkeit.md) — von unaufmerksamem, eiligem Nutzer ausgehen; gefährliche Zwischenzustände unmöglich machen (nicht nur beschriften). Beispiel Empfangs-QR: bei Wallet-Wechsel sofort entwerten, erst wieder zeigen wenn die Adresse des neuen Wallets feststeht.
- **Neugier / Lernen nebenbei:** Leitbild in [`../doc/design-neugier.md`](../doc/design-neugier.md) — Tooltips (`title` / `data-i18n-title`); Kuratierung [`../doc/lernhinweise-kuratierung.md`](../doc/lernhinweise-kuratierung.md). **Pflicht:** Jede vom Maintainer angegebene Pleb-Lern-URL sofort in `web/lernhinweise.json` **und** Handbuch-FAQ §14 ([`../doc/handbuch.html`](../doc/handbuch.html), DE+EN) nachziehen. Kein Widerspruch zur Flüchtigkeit. Lern-URLs nur Bitcoin-only (Dealbreaker **T13**, Root-Verfassung).
- **Verbose:** Default `nein` (`VERBOSE` in `.env` oder Einstellungen [4]); gekürzte TxIDs/Adressen
- **Beträge:** `format_sats` — ≤100 000 sats als sats, darüber BTC mit 2 Dezimalstellen
- **Log-Bereich (Web):** Sparsam, wenn Verbindungen stehen und das Tool arbeitsbereit ist; gesprächig bei Hochfahren, Problemen, Verbindungsabbrüchen unter kritische Werte (z. B. < 3 Compact-Filter-Peers) oder Privatsphäre-Änderung. Eine Zeile kündigt den nächsten Schritt an, **bevor** er losläuft (Erwartungsmanagement, z. B. Tor) — Ergebnis danach. Gleicher Strom (`on_log` / NDJSON); nach ~10 s Stille: „Moment noch“. Wallet-Aktionen: Name nach der Uhrzeit. Richtlinie: [`../doc/logging-richtlinie.md`](../doc/logging-richtlinie.md).
- **Web-UI prüfen:** Änderungen an `web/` oder gerenderten API-Daten im Browser durchklicken, nicht nur am Render festhalten. Ausnahme: kleine GUI-Kosmetik auf dem Windows-Rechner testet der Nutzer selbst (Playwright/Docker: [`../scripts/AGENTS.md`](../scripts/AGENTS.md)). Vor dem Merge nach `main` wieder selbst prüfen, auf macOS, Linux oder einem Grok-Bot.
- **Keine Telemetrie / kein XPUB-Upload an Fremde; Web-UI ohne Remote-JS** (Dealbreaker T3/T6). Vendor-JS nur lokal unter `web/vendor/`.

## Wohin neue Oberfläche kommt

- View nach `web/views/<domäne>.js` oder in die bestehende View.
- `web/app.js` nur anfassen, solange der Rest-Ballast (Kurs, Chat, Sync) noch dort liegt.
- Weiteres Entkernen des `app.js`-Ballasts ist eine eigene Aufgabe mit eigenem Commit.
