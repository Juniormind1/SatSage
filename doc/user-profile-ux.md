# Nutzerprofil · UX (Maintainer-Hinweise an Assistenten)

**Stand:** 2026-09-15

## Anfänger und fehleranfällige Interaktionen

Für Anfänger sind viele Software-Schritte **oft fehlerbehaftet** (Node verbinden, TLS ja/nein, Datenquelle wechseln, erste Scans). Solche Momente sollen bei **Erfolg belohnt** werden — z. B. mit einer kurzen, freudigen Animation (Staub-Konfetti ohne große Scheine), nicht mit Belehrung oder Streak-Gamification.

- Leitbild Node: `design-node-anbindung.md` Prinzip 8  
- Umsetzung: `jubelDatenquelleErfolg()` / `EmpfangPuls.flashStaubBelohnung` nach grünem Datenquellen-Test  
- Neugier: `design-neugier.md` (Entdecken belohnen, nicht erzwingen)

Weitere Belohnungen nur, wo der Nutzer **bewusst** etwas Schwieriges geschafft hat — nicht bei jedem Poll oder Hintergrund-Sync.
