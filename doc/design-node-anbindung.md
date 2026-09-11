# Designhinweis — Node-Anbindung

**Stand:** 2026-09-07  
**Gilt für:** Desktop-Web-GUI, CLI-Setup, Specter-Bridge, Start9-Sideload  
**Leitbild:** so einfach wie möglich den eigenen Node verbinden — schick, minimalistisch, fehlertolerant, robust (Apple-Niveau, nicht Enterprise-Wizard).

## Ziel

Der Nutzer soll **seinen** Bitcoin-Node (Electrs/Fulcrum, Core-RPC, ggf. P2P) mit möglichst wenig Nachdenken an SatSage hängen. Konfiguration darf existieren; **Konfigurationsfehler sollen ihn so wenig wie möglich ausbaden lassen.** Die App kompensiert, rät, probiert und erklärt — statt den Nutzer in `.env`-Flags und TLS-Semantik zu schicken.

## Prinzipien

1. **Wenige richtige Defaults.** Auto-Priorität der Datenquellen, sinnvolle Ports, LAN vor Clearnet. Der Happy Path braucht keine Experten-Schalter.
2. **Fehler der Umgebung schlucken, wo sicher.** Self-Signed im Heimnetz, TLS an/aus am falschen Port, kurzzeitige Peer-Abbrüche: erkennen, umschalten, weiter — nicht mit roter Wand stoppen, wenn ein robuster Fallback existiert.
3. **Hinweise statt Hausaufgaben.** Wenn etwas scheitert: eine klare Ursache und **einen** nächsten Schritt. Kein Katalog aus fünf Env-Variablen, die der Nutzer erst googeln muss.
4. **Produktpfade trennen.** Start9-Sideload (Bridge, managed, oft ohne TLS) und Desktop-`.env` (LAN-IP, Self-Signed) dürfen unterschiedlich verdrahtet sein. Härte und Spezialwege gehören in den jeweiligen Build/Modus — nicht als Kollateralschaden auf den Desktop-Alltag.
5. **Sicherheit ohne Reibungstheater.** Echte Risiken (öffentliches Clearnet, Opt-in, Secrets) bleiben hart. Typische Heimnetz-Realität (privates LAN, Onion, Loopback) bleibt bedienbar, ohne „Labor-Flag setzen“.
6. **Minimal sichtbare Komplexität.** Interne Retry-, Probe- und Fallback-Logik darf reich sein; UI und Log bleiben ruhig, verständlich, ohne Forensik-Lärm — Details: [`logging-richtlinie.md`](logging-richtlinie.md).
7. **Vertrauen durch Vorhersehbarkeit.** Eine Zeile kündigt den nächsten Schritt an, bevor er startet; Ergebnis kommt danach. Kein stummes Hängen, kein „du hast etwas falsch konfiguriert“ ohne Beleg. Erstnutzer brauchen sichtbare Erfolge; im stabilen Betrieb sparsam, bei Störungen wieder gesprächig.

## Konkret (Beispiele)

| Situation | Erwünscht | Nicht erwünscht |
|-----------|-----------|-----------------|
| Start9-LAN, Self-Signed-TLS | Verbinden; Zertifikat im privaten Netz nicht als Blocker | Nutzer muss `SATSAGE_TLS_INSECURE=1` setzen |
| Port spricht kein TLS / doch TLS | Automatisch oder mit einem klaren Umschalt-Hinweis | Nur `CERTIFICATE_VERIFY_FAILED` / `WRONG_VERSION_NUMBER` roh |
| Electrs kurz weg, P2P noch da | Fallback nach Priorität, später wieder Preferenz | Dauerhaft auf schlechterer Quelle kleben ohne Erklärung |
| Start9-Package | Bridge-Hosts, SSL aus, UI-Felder gesperrt | Dieselbe TLS-Härtung wie öffentliches Clearnet auf die Bridge legen |
| Öffentliches Clearnet | Opt-in + echte Zertifikatsprüfung | Still `CERT_NONE` „weil bequemer“ |

## Abgrenzung

- **Nicht** gemeint: Sicherheitsfeatures abschalten, damit „irgendwas geht“.
- **Nicht** gemeint: stille Datenlecks oder öffentliche Server ohne Bestätigung.
- **Gemeint:** die App trägt die Komplexität; der Nutzer trägt Host, grobe Absicht und Vertrauen in sein Heimnetz.

## Für Assistenten / Reviews

Bei Änderungen an Verbindung, TLS, Datenquellenwahl, Start9 vs. Desktop:

1. Fragt: **Muss der Nutzer etwas Neues wissen oder setzen?** Wenn ja — geht es auch ohne?
2. Ist der neue harte Default nur für einen Modus nötig (z. B. Sideload)? Dann **nicht** global.
3. Scheitert der Happy Path an einem typischen Heimnetz-Detail, ist das ein **Produktbug**, kein „User-Error“.

Siehe auch: Datenquellen-Priorität in `AGENTS.md`, Start9-Modus in `doc/START9-hardening.md`, TLS-Policy in `outbound_policy.py`.
