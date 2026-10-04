# Nutzerprofil · UX (Maintainer-Hinweise an Assistenten)

**Stand:** 2026-10-04

## Seltener Gast

Die meisten öffnen SatSage nicht aus Spaß. Das Finanzamt stresst sie, und sie müssen Herkunftsnetze produzieren. Die Hauptwallets bleiben die Companions oder Sparrow, Wasabi, Specter oder eine andere Wallet-Software. SatSage ist der seltene Gast.

Alles, was SatSage wissen muss, kommt aus Mainchain-Traces der xpubs und gegebenenfalls aus Fremdwallet-Importen, also deren Export-Dateien. Keine eigene Buchhaltung. Caches sparen nur teure Electrs-Abfragen.

Braucht ein vom Entwickler gewünschtes Feature darüber hinaus Zusatzinformationen (Extremfall: eigene Los-Buchhaltung), ausdrücklich darauf hinweisen, dass diese Regel verletzt wird. Sie muss erst geändert werden, bevor das zulässig ist.

## Anfänger und fehleranfällige Interaktionen

Für Anfänger sind viele Software-Schritte **oft fehlerbehaftet** (Node verbinden, TLS ja/nein, Datenquelle wechseln, erste Scans). Solche Momente sollen bei **Erfolg belohnt** werden — z. B. mit einer kurzen, freudigen Animation (Staub-Konfetti ohne große Scheine), nicht mit Belehrung oder Streak-Gamification.

- Leitbild Node: `design-node-anbindung.md` Prinzip 8  
- Umsetzung: `jubelDatenquelleErfolg()` / `EmpfangPuls.flashStaubBelohnung` nach grünem Datenquellen-Test  
- Neugier: `design-neugier.md` (Entdecken belohnen, nicht erzwingen)

Weitere Belohnungen nur, wo der Nutzer **bewusst** etwas Schwieriges geschafft hat — nicht bei jedem Poll oder Hintergrund-Sync.
