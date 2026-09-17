# Designrichtlinie: Flüchtigkeit / Eilige Nutzer

**Verankert in:** [`AGENTS.md`](../AGENTS.md) (UI-Konventionen)

## Ausgangslage

Wir gehen von einem Nutzer aus, der **maximal in Eile und unaufmerksam** ist: tippt falsch, scannt den falschen QR, bestätigt ohne zu lesen, wechselt die Ansicht mitten in einem Ladevorgang.

Kleine Hinweistexte („Bitte prüfen…“) reichen dafür **nicht**. Was schiefgehen kann, muss die Oberfläche **unmöglich machen** oder so absichern, dass der Fehler keine Folgen hat.

## Prinzipien

1. **Ungültigen Zustand sichtbar entwerten.** Wechselt der Kontext (Wallet, Adresse, Modus), darf die alte Darstellung nicht weiter bedienbar wirken — sofort leer, ausgegraut oder gesperrt, nicht „noch kurz die alte Wahrheit“.
2. **Erst zeigen, wenn fest.** Empfangsadresse, QR, Beträge, die zu einer Auswahl gehören: erst einblenden, wenn sie zu **genau dieser** Auswahl gehören. Kein spekulatives Vorzeigen aus Cache anderer Wallets oder veralteter Antworten.
3. **Aktionen an Kontext binden.** Kopieren, Senden, Bestätigen nur, wenn der zugehörige Zustand aktuell und gültig ist; sonst Kontrolle deaktivieren.
4. **Race Conditions annehmen.** Späte API-Antworten einer früheren Auswahl dürfen die UI nicht überschreiben (Generationszähler / Abbruch bei Wallet-Wechsel).
5. **Hinweise sind Ergänzung, keine Absicherung.** Text erklärt; Verhinderung schützt.

## Beispiel: Empfangs-QR

Beim Wallet-Wechsel:

1. QR und Adresse **sofort** entfernen bzw. ungültig machen (kein Scan der alten Adresse mehr möglich).
2. Optional neutraler Ladezustand („wird ermittelt…“) — **ohne** scannbaren QR und ohne klickbare alte Adresse.
3. QR und Adresse erst wieder zeigen, wenn die Antwort für das **neu gewählte** Wallet vorliegt.

Nicht: alten QR stehen lassen, bis die neue Adresse da ist; nicht: Cache eines anderen Wallets „zur Überbrückung“ zeigen.

## Abgrenzung

- Node-Anbindung und ruhiges Log: [`design-node-anbindung.md`](design-node-anbindung.md), [`logging-richtlinie.md`](logging-richtlinie.md).
- Trust/Seed/Remote-JS: [`merge-dealbreakers.md`](merge-dealbreakers.md).

Bei neuen UI-Flows (Zahlungsziel, Wallet-Wechsel, gefährliche Bestätigungen): diese Richtlinie prüfen, bevor man „kurz den alten Wert stehen lässt“.
