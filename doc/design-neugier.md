# Designrichtlinie: Unwissend, lernfaul, neugierig

**Verankert in:** [`AGENTS.md`](../AGENTS.md) (UI-Konventionen)  
**Ergänzung zu:** [`design-fluchtigkeit.md`](design-fluchtigkeit.md) (Eile / Fehlerverhinderung)

## Ausgangslage

Wir gehen von einem Nutzer aus, der **unwissend und lernfaul**, aber **neugierig** ist: Er liest keine Handbücher und mag keine Tutorials — entdeckt aber gern Zusammenhänge, wenn sie sich von selbst zeigen.

Wenn die Oberfläche ihn **ohne Lernaufwand** schlauer machen kann, nutzen wir das. Die Hinweise müssen der **minimalistischen Funktion nicht im Weg stehen**.

## Bevorzugte Methode: Tooltips („Wo ist Walter?“)

**Native `title`-Tooltips** (und wo nötig kurze `aria-label`/`data-i18n-title`) sind das Mittel der Wahl:

- Der **Eilige** sieht sie nicht — er klickt durch, ohne Hover/Long-Press.
- Der **Neugierige** kann die GUI absichtlich abtasten: Elemente anfahren, Titel lesen, Zusammenhänge entdecken — leichte Gamification, kein Kurs.

Kein Pflicht-„?“-Tour-Modus. Entdecken ist optional und belohnt Aufmerksamkeit.

## Prinzipien

1. **Entdecken statt belehren.** Kein Modal „Wussten Sie schon?“, kein Pflicht-Walkthrough. Wissen entsteht nebenbei beim Benutzen — vor allem per Tooltip.
2. **Tooltip vor Dauertext.** Was nur der Neugierige braucht, gehört in den `title`, nicht in die immer sichtbare Fläche. Sichtbare Labels bleiben kurz und handlungsleitend.
3. **Funktion zuerst.** Wenn ein Hinweis die Hauptaktion verlangsamt, stört oder Fläche frisst, weglassen oder in den Tooltip verschieben. Minimalismus schlägt Pädagogik.
4. **Wahrheit in einem Blick.** Zustand so darstellen, dass die richtige Schlussfolgerung naheliegt (Pille, Farbe, Quelle) — Tooltip liefert den „warum“, nicht den Ersatz für Absicherung.
5. **Tiefe auf Abruf.** Neugierige: Tooltip → ggf. Handbuch. Uninteressierte: null Aufwand.
6. **Kein Widerspruch zur Flüchtigkeit.** Hinweise ersetzen keine Absicherung ([`design-fluchtigkeit.md`](design-fluchtigkeit.md)).
7. **Bitcoin-Mechanismen, keine SatSage-Internals.** Lernstoff richtet sich an den lernfaulen Pleb: Was ist ein UTXO, XPUB, bc1 — nicht „wie SatSage scantxoutset aufruft“. Dealbreaker T13: nur Bitcoin-only-URLs; Shitcoins/Eth im Zweifel warnen, nicht durchwinken ([`merge-dealbreakers.md`](merge-dealbreakers.md), [`lernhinweise-kuratierung.md`](lernhinweise-kuratierung.md)).

## Beispiele (Richtung, keine Pflichtliste)

| Ort | Sichtbar | Tooltip / Entdeckung |
|-----|-----------|----------------------|
| Empfangs-QR · Quelle | Kurzlabel Cache/Electrs | Warum die Quelle zählt / wann nachziehen |
| Skripttyp | „Automatisch (Empfang bc1q)“ | Was auto bei xpub bedeutet |
| Privatsphäre-Pille | Farbe + Kurzlabel | Was „hoch/mittel“ hier konkret heißt |
| Steuerjahr-Zeitstrahl | Grün/orange + Achse | Haltefrist in einem Satz |
| Read-only | Kein QR + eine Zeile | Wozu „Nur lesen“ gedacht ist |
| Knöpfe allgemein | Icon/kurzer Text | `data-i18n-title` / `title` — Wo-ist-Walter-Fläche |

## Abgrenzung

- Node-Anbindung: [`design-node-anbindung.md`](design-node-anbindung.md)
- Log-Sparsamkeit: [`logging-richtlinie.md`](logging-richtlinie.md) — auch dort: klar, nicht geschwätzig
- Dealbreaker (Seed, Remote-JS, …): [`merge-dealbreakers.md`](merge-dealbreakers.md)

Bei neuen UI-Elementen fragen: *Kann ein Neugieriger hier etwas Wichtiges mitbekommen, ohne dass ein Eiliger gestört oder gefährdet wird?*
