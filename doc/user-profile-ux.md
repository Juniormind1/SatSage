# Nutzerprofil · UX (Maintainer-Hinweise an Assistenten)

**Stand:** 2026-11-22

## Seltener Gast

Die meisten öffnen SatSage nicht aus Spaß. Das Finanzamt stresst sie, und sie müssen Herkunftsnetze produzieren. Die Hauptwallets bleiben die Companions oder Sparrow, Wasabi, Specter oder eine andere Wallet-Software. SatSage ist der seltene Gast.

Alles On-Chain, was SatSage wissen muss, kommt aus Mainchain-Traces der xpubs und gegebenenfalls aus Fremdwallet-Importen, also deren Export-Dateien. Daran ändert sich nichts. Caches sparen nur teure Electrs-Abfragen; sie sind keine Buchhaltung. Eine eigene Los-Buchhaltung für On-Chain-Bewegungen gibt es nicht.

## Börse · FIFO aus dem Export

Für Börsentransaktionen, die nicht on-chain sind, darf SatSage aus dem CSV-Export einer zentralen Handelsplattform eine strikte FIFO-Kaufhistorie je Börsenkonto ableiten, zurück bis zum Kauf auf der Börse selbst. Börsenbestand und Börsen-Lose werden jedes Mal aus den Importfakten neu berechnet, nicht als eigene Buchhaltung gespeichert.

Das ist begründbar mit dem BMF-Schreiben vom 6. März 2025, Einzelfragen zur ertragsteuerrechtlichen Behandlung bestimmter Kryptowerte (GZ IV C 1 - S 2256/00042/064/043). SatSage erteilt keine Steuerberatung; die Randnummern rechtfertigen nur, warum diese Dokumentation zulässig ist:

- Rn. 20: Der gespeicherte Zu- und Abgang in der Blockchain muss nicht mit dem ertragsteuerrechtlich relevanten Anschaffungs- oder Veräußerungszeitpunkt übereinstimmen. Für den Handel über eine zentrale Handelsplattform ist der Zeitpunkt des Handels über die Plattform ausschlaggebend, nicht der spätere Zu- oder Abgang in der eigenen Wallet.
- Rn. 61: Zuerst gilt die Einzelbetrachtung. Ist sie nicht möglich, gelten für die Haltefrist die zuerst angeschafften Kryptowerte einer Handelsbezeichnung als veräußert. Für die Wertermittlung gilt die Durchschnittsmethode; aus Vereinfachungsgründen darf auch dafür FIFO unterstellt werden. SatSage wendet diese FIFO-Lesart an.
- Rn. 62: Die Betrachtung ist walletbezogen. Die gewählte Methode bleibt je Wallet und Handelsbezeichnung bestehen, bis der Bestand dieser Handelsbezeichnung in dieser Wallet vollständig veräußert ist. Ein Börsenkonto gilt hier als eigene Wallet.
- Rn. 102 und 103: Nachvollziehbar festzuhalten sind unter anderem Anschaffungszeitpunkt, Menge, Art des Vorgangs, genutzte Handelsplattform, die gewählte Verwendungsreihenfolge je Wallet (Einzelbetrachtung, Durchschnitt oder FIFO) und Umschichtungen innerhalb von Wallets. SatSage kennzeichnet solche Angaben im Bericht als Börsenbeleg.

Diese Ausnahme ist eng begrenzt:

- Nur Bitcoin gegen Euro oder US-Dollar und nur aus Börsen-Exporten. Keine API, keine Secrets.
- FIFO ist strikt je Börsenkonto. SatSage bietet kein Wahlrecht, kein LIFO und kein Aussuchen einzelner Lose.
- Eine Börsen-Auszahlung wird nur mit passendem Chain-Hop zum Zugang in der Trace-Welt: über die Transaktions-ID exakt oder als vom Nutzer bestätigter Vorschlag. Ohne Hop bleibt sie eine Lücke, kein erfundener Zugang.
- Im Bericht ist das als Börsenbeleg gekennzeichnet. Die Chain-Lesart (Blockzeit des Zugangs) bleibt als sichere Untergrenze sichtbar.

Weitere Erweiterungen über diese Ausnahme hinaus — insbesondere eine allgemeine Los-Buchhaltung, eine eigene Steuerrechnung oder das Überschreiben der Chain-Herkunft — brauchen weiterhin eine Änderung dieses Profils. Braucht ein Feature darüber hinaus Zusatzinformationen, ausdrücklich darauf hinweisen, dass diese Regel verletzt wird. Sie muss erst geändert werden, bevor das zulässig ist.

## Anfänger und fehleranfällige Interaktionen

Für Anfänger sind viele Software-Schritte **oft fehlerbehaftet** (Node verbinden, TLS ja/nein, Datenquelle wechseln, erste Scans). Solche Momente sollen bei **Erfolg belohnt** werden — z. B. mit einer kurzen, freudigen Animation (Staub-Konfetti ohne große Scheine), nicht mit Belehrung oder Streak-Gamification.

- Leitbild Node: `design-node-anbindung.md` Prinzip 8  
- Umsetzung: `jubelDatenquelleErfolg()` / `EmpfangPuls.flashStaubBelohnung` nach grünem Datenquellen-Test  
- Neugier: `design-neugier.md` (Entdecken belohnen, nicht erzwingen)

Weitere Belohnungen nur, wo der Nutzer **bewusst** etwas Schwieriges geschafft hat — nicht bei jedem Poll oder Hintergrund-Sync.
