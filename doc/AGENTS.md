# AGENTS.md — `doc/`

Wie Agents Doku pflegen. Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

Keine zweite Agent-Verfassung hier ablegen. Bereichswissen bleibt in der `AGENTS.md` des jeweiligen Verzeichnisses.

## Handbuch und Design

- Nutzerhandbuch: `doc/handbuch.html`. Änderungshistorie: `CHANGELOG.md`. Offene Punkte: `ISSUES.md`.
- **Design · Node-Anbindung:** `doc/design-node-anbindung.md` — schick, minimalistisch, fehlertolerant; Konfigurationsfehler möglichst von der App abfangen (nicht vom Nutzer)
- **Design · Flüchtigkeit:** `doc/design-fluchtigkeit.md` — Nutzer in Eile/unaufmerksam; Fehlerverhinderung statt Hinweistext (z. B. Empfangs-QR beim Wallet-Wechsel sofort ungültig)
- **Design · Neugier:** `doc/design-neugier.md` / `doc/lernhinweise-kuratierung.md` — Pleb-Lern-URLs; **bei jeder Kuratierung Handbuch §14 (`doc/handbuch.html`) mitziehen**, und `web/lernhinweise.json`. Lern-URLs nur Bitcoin-only (Dealbreaker **T13**).
- **Nutzerprofil:** `doc/user-profile-ux.md` — seltener Gast unter Steuerdruck; Wissen nur aus Mainchain-Traces der xpubs und Fremdwallet-Exporten. Keine eigene Buchhaltung. Ein Feature, das mehr verlangt, erst als Regelbruch benennen.
- Protokolle für Agents, die GUI oder Datenquellen prüfen: `doc/testprotokoll-webgui-stabilitaet.md`, `doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md`, `doc/testprotokoll-scan-abbruch-cache.md`, `doc/testprotokoll-p2p-traces.md`, `doc/gui-test-protokoll.md`, `doc/logging-richtlinie.md`. Die Ausführungsregeln stehen in [`../scripts/AGENTS.md`](../scripts/AGENTS.md), [`../lab/AGENTS.md`](../lab/AGENTS.md) und [`../web/AGENTS.md`](../web/AGENTS.md).
- Modularisierung: `doc/adr-modularisierung.md`. Die Arbeitsregeln dazu stehen in [`../core/AGENTS.md`](../core/AGENTS.md) (Modulgrenzen).
- Packaging-Anleitungen: `doc/START9-packaging.md`, `doc/UMBREL-packaging.md`. Agent-Regeln: [`../packaging/AGENTS.md`](../packaging/AGENTS.md).

## Changelog und Release Notes

- `CHANGELOG.md` bei nennenswerten Änderungen nachziehen — spätestens zusammen mit dem Commit. Neue Punkte unter [Unveröffentlicht]. Sprache Deutsch, Nutzerwirkung vor Implementierungsdetail.
- **Release Notes:** Nicht bei jedem Push auf dev-juniormind. Nur bei **Version-Bump** / Merge nach **main** / **Git-Tag** (StartOS-Tag eingeschlossen): Abschnitt [Unveröffentlicht] als datierten Block setzen und leeren; optional GitHub-Release-Body = dieser Abschnitt (Inhalt = Changelog seit dem letzten Release). StartOS: wie `doc/START9-packaging.md` + `publish_startos_release`.
- **Bump:** nur Maintainer entscheiden und `VERSION` ändern; kein Auto-Increment in Scripts/CI. Changelog-Eintrag zum Bump mitziehen.

## Was nicht in Doku gehört

Mainnet-Adressen, TxIDs, Wallet-Namen, XPUBs, Seeds und Heim-Node-Daten des Nutzers gehören nicht in Issues, PRs, Handbuch, Changelog oder Protokolle. Dealbreaker: [`merge-dealbreakers.md`](merge-dealbreakers.md).
