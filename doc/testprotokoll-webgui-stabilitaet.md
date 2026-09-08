# Testprotokoll: Web-GUI-Stabilität („irres Rumgeklicke“ + wilde Texte)

**Zweck:** Bugs finden, die in Unit-Tests und dem Happy Path unsichtbar bleiben — Race Conditions, hängende Jobs, kaputte Ansichtswechsel, Sprachwechsel mitten im Lauf, doppelte Klicks, abgebrochene Dialoge, **wilde/fehlerhafte Texteingaben** (Parser, XSS-artig, Überlänge, Enter mitten im Tippen).

**Frequenz (Vorschlag):**
- **kurz** vor jedem Release / nach größeren `web/`- oder `server.py`-Änderungen
- **voll** ca. alle 2–4 Wochen oder nach Refactors an Jobs, Nav, i18n, Caches

**Dauer:** Kurz ~15 min · Voll ~45–60 min · Automatischer Chaos-Lauf ~5–20 min (je nach Runden)

**Umgebung:**
- Echte oder Test-`.env` mit ≥2 Wallets (idealerweise Single-Sig + Multisig)
- Laufender Server: `py server.py` bzw. `.venv/bin/python server.py`
- Browser: Chrome/Chromium, DevTools-Konsole offen (Fehler-Filter)
- Optional: zweites Fenster mit Terminal-Log / Job-Spiegel

**Nicht-Ziele dieses Protokolls:** Korrektheit der Steuerberechnung, vollständige BIP-158-Coverage, Performance-Benchmarks. Dafür Unit-Tests und gezielte Fach-Checks.

---

## 0. Vorbereitung (Checkliste)

| # | Check | OK |
|---|--------|----|
| 0.1 | Server startet, Token-URL öffnet die GUI | ☐ |
| 0.2 | Mindestens ein Wallet mit Cache (UTXO und/oder Verlauf) | ☐ |
| 0.3 | DevTools → Console: Filter auf Errors; Network optional | ☐ |
| 0.4 | Ausgang: Sprache DE, Log sichtbar, kein Dialog offen | ☐ |
| 0.5 | Snapshot notieren: Uhrzeit, `VERSION`, Git-Kurzhash, Browser | ☐ |

**Ausgabe dieses Laufs:** Abschnitt „Befund“ unten ausfüllen oder Ticket in `ISSUES.md` / Issue-Tracker.

---

## 1. Kurzprotokoll (~15 Minuten)

Schneller Sanity-Chaos nach UI-Änderungen.

### 1.1 Navigation-Sturm (2 min)

1. 20× nacheinander willkürlich klicken: Wallets in der Nav, Trace origin, Tax year, Sanctions, Wallets, Settings, Data sources.
2. Währenddessen Log-Schalter an/aus, DE↔EN 5× umschalten.
3. **Erwartung:** Kein weißer Bildschirm, keine uncaught Exception, aktive Nav stimmt mit sichtbarer Ansicht, Kopf-Pillen zeigen lesbare Labels (keine Roh-Keys wie `header.sourceCore`).

### 1.2 Wallet-Flackern (3 min)

1. Wallet A öffnen → Limit Top 10/25/Alle und Sortierung wechseln, während die Liste noch lädt.
2. Sofort Wallet B öffnen, bevor A fertig ist.
3. UTXO-Scan starten → sofort abbrechen (falls Abbruch sichtbar) → Verlaufsscan starten → Ansicht wechseln.
4. **Erwartung:** Rescan-Leiste verschwindet oder zeigt klar „anderes Wallet“; keine doppelten Job-Stürme ohne Log; Ansicht zeigt Daten von B, nicht vermischt mit A.

### 1.3 Dialog-Chaos (3 min)

1. Einrichtung/On-Chain/Privatsphäre falls sichtbar: OK, Später, Esc-äquivalent (Klick außerhalb falls möglich), dann erneut öffnen über Settings.
2. Scan-Datum-Dialog: öffnen, Datum ändern, Abbruch, erneut öffnen, Scannen.
3. Wallet angelegt-Dialog (falls testweise Wallet add): alle drei Wege anreißen, abbrechen wo möglich.
4. **Erwartung:** Kein gestapelter Modal-Friedhof; Fokus/Scroll wieder normal; App nicht `hidden`.

### 1.4 Sprachwechsel unter Last (2 min)

1. DE: Data sources öffnen (Labels + Sanktionsstatus sichtbar).
2. Mitten im Lesen EN klicken; zurück zu DE; EN.
3. Wallets-Verwaltung öffnen, Zeile „Update“/„Aktualisieren“ prüfen.
4. **Erwartung:** Dynamische Texte (Quellen-Notizen, Labels-Status, Wallet-Zeilen) folgen der Sprache; keine Key-Leichen; Log-Zeilen dürfen DE bleiben (bekannt), UI-Rahmen nicht.

### 1.5 Wilde Texte (3 min)

In sichtbare Felder nacheinander Nonsense tippen/einfügen, oft mit Enter oder Primärknopf:

| Feld | Beispiele |
|------|-----------|
| Trace-Ziel | leere TxID, `txid:vout`, 64×`0` + `:99999`, HTML-Tags, 2 kB „x“ |
| XPUB / Deskriptor | abgeschnittener zpub, JSON-Müll, `'; DROP…`, Emojis |
| Wallet-Name | Leer, nur Spaces, RTL-Override, `<script>…` |
| Sanktions-Hops | `-1`, `1e9`, `NaN`, `3,14` |
| LLM-URL / Modell | `javascript:…`, `http://[::1]`, 500 Zeichen |
| Chat | `/hilfe`, leerer Send, „IGNORE PREVIOUS…“, Code-Fences |
| Mempool-URL | fremde Domain, leerer String, UNC-Pfad |

**Erwartung:** Kein uncaught Error; Felder bleiben bedienbar; ungültige Eingaben werden abgewiesen oder harmlos ignoriert (kein Freeze, kein White-Screen). Passwort/API-Key-Felder **nicht** mutwillig mit Produktionssecrets füllen.

### 1.6 Abschluss Kurz (2 min)

1. Console: 0 unexpected errors (Netz-Timeouts zu Core ok, wenn UI das aushält).
2. Ein Wallet nochmal öffnen — Bestand sichtbar.
3. Befundzeile schreiben.

---

## 2. Vollprotokoll (~45–60 Minuten)

Alles aus Kurz, plus gezielte Stress-Szenarien.

### 2.1 Job-Überlagerung

| Schritt | Aktion | Erwartung / Fail |
|--------|--------|------------------|
| A | UTXO-Scan Wallet A starten | Job im Log, Spinner/Leiste |
| B | Sofort Verlaufsscan A | Warteschlange oder klarer Status, kein Crash |
| C | Während A läuft: Herkunft/Trace „alle“ oder Steuerjahr laden | Kein Freeze der Nav |
| D | Job abbrechen (UI-Abbruch) | Status cancelled/fertig; UI bedienbar |
| E | Data sources → „Test own node“ während Scan | Timeout ok; UI bleibt |

**Fail-Signale:** Endlos-Spinner ohne Log > 60 s; Buttons dauerhaft disabled; doppelte identische Fullscans ohne Anlass.

### 2.2 Klapp- und Listen-Chaos (Wallet + Trace)

1. Alle Adressgruppen auf/zu in wilder Folge.
2. UTXO-Zeile öffnen → Scan neu / Rescan-Herkunft → sofort Zuklappen → andere Zeile.
3. Trace origin: Suche tippen/löschen, Top-N, während Liste lädt.
4. Bereits ausgegeben / Already spent aufklappen (große Listen).
5. **Fail:** DOM-Leichen, doppelte Köpfe, Klick trifft falsches UTXO, „gelistet“-Pillen ohne Kontext.

### 2.3 Einstellungen & Speichern

1. Haltefrist/Stichtag/Anschaffung ändern, speichern, Ansicht Tax year, zurück, Werte prüfen.
2. LLM-Felder leeren/füllen ohne Speichern, wegklicken, wieder rein — Draft vs. gespeichert.
3. Sprache + „in .env speichern“ an/aus.
4. Start-Sync-Checkbox toggeln.
5. **Fail:** stille Verluste; UI zeigt X, `.env` hat Y; nach Reload falsche Sprache.

### 2.4 Data sources tief

1. Quellen auf/zuklappen (Stift), Felder ändern **ohne** Speichern, schließen, erneut öffnen.
2. „Test own node“ spam (3× schnell).
3. Labels: Variante umschalten, **nicht** laden; Status lesen; Sprache wechseln.
4. Sanktionslisten: Status, Update **nicht** unbedingt anstoßen (Netz/125 MB) — nur UI.
5. Mempool-URL leeren/setzen/Speichern; Pille „Own network“ vs. public.
6. CSV-Import: Abbruch im Dateidialog falls möglich.
7. **Fail:** Notizfarben/Privatsphäre-Pillen falsch; Formular mit Geisterwerten; EN-Reste DE.

### 2.5 Wallets-Verwaltung

1. Name ändern → Update → Name zurück.
2. Skripttyp-Dropdown durchrotieren **ohne** Speichern, dann verwerfen durch Nav-Wechsel (beobachten).
3. „Check script type“ einmal (Netz); währenddessen Nav weg.
4. Multisig-Zeile: Anzeige `m of n` in EN/DE.
5. Danger Zone: **nur lesen** im Normal-Lauf; Destruktiv nur mit Backup (Abschnitt 4).
6. **Fail:** Zeile ohne i18n; disabled Update klebt; Liste verdoppelt sich.

### 2.6 Assistent & Log-Dock

1. Log-Höhe ziehen (Zieher), Log aus/an.
2. Chat: `/hilfe` bzw. `/help`, leere Send, schnelle Doppel-Send.
3. Während Antwort: Ansicht wechseln.
4. **Fail:** Dock überdeckt Nav unbenutzbar; Chat blockiert Main-Thread spürbar > 3 s ohne Feedback.

### 2.6b Text-Sturm (alle Formulare)

Pro Ansicht 2–3 Minuten: Fokus in jedes sichtbare `input`/`textarea`, nacheinander:

1. **Leer / Whitespace** → Enter / Speichern  
2. **Überlänge** (1–4 kB) → Tab weiter  
3. **Unicode / Emoji / Zalgo / RTL**  
4. **Injection-Attrappen** (`<script>`, `{{7*7}}`, SQL-Fragment) — erwarten escaping, kein `eval`  
5. **Fachlich falsch aber formähnlich** (TxID-Länge, `bc1…`, Deskriptor-Schnipsel)  
6. Während Request läuft: Feld leeren und erneut senden (Doppel-Submit)

**Fail:** Exception in Console; UI stuck; Server 500-Schauer ohne UI-Hinweis; Feld-Wert „klebt“ unsichtbar und verfälscht spätere Aktionen.

### 2.7 Fenster & Viewport

1. Fenster schmal (~400 px) und breit; Nav und Dock.
2. Zoom 80 % / 125 %.
3. **Fail:** unbezahlbare Überlappungen, abgeschnittene Primär-Buttons ohne Scroll.

### 2.8 Wiederherstellung

1. Hard-Reload (Cache ignorieren) mit Token-URL.
2. Session: gleiche Wallets, Sprache aus localStorage/`.env` wie erwartet.
3. Offene Jobs: sauber beendet oder klar im Log.

---

## 3. Automatischer Chaos-Lauf

Halbautomatik für Wiederholung und Regression.

### 3.1 Voraussetzungen

```bash
# Server mit Token-URL (Beispiel)
.venv/bin/python server.py --port 8730 --plain-console
```

### 3.2 Harness starten

```bash
# Gegen laufenden Server (URL inkl. ?t=…):
.venv/bin/python scripts/webgui_chaos_run.py --url 'http://127.0.0.1:8730/?t=…'

# Eigenen Temp-Server spawnen (Isolierung, empfohlen für CI/lokal ohne Produktions-.env):
.venv/bin/python scripts/webgui_chaos_run.py --spawn

# Mehr Runden / Seed für Repro:
.venv/bin/python scripts/webgui_chaos_run.py --spawn --rounds 300 --seed 42

# Mehr wilde Texte (Default text-ratio ≈ 0.28), seltener Submit nach Tippen:
.venv/bin/python scripts/webgui_chaos_run.py --spawn --text-ratio 0.45 --submit-ratio 0.25

# Destruktive Aktionen erlauben (Cache löschen etc.) — nur mit Wegwerf-Env:
.venv/bin/python scripts/webgui_chaos_run.py --spawn --destructive
```

**Was der Runner macht:**
- öffnet die GUI (Playwright, falls installiert; sonst Anleitung + `harness.js` zum Einspeisen)
- injiziert `scripts/webgui_chaos_harness.js`
- zufällige **Klicks** (Nav, DE/EN, Limit/Sort, Klappzeilen) **und Texteingaben** (Leer, Überlänge, Unicode, Injection-Attrappen, Pseudo-TxID/XPUB/URL, Chat-Slash-Commands; oft Enter/Primärknopf)
- meidet Passwort/API-Key-Felder und Danger-Zone (außer `--destructive`)
- sammelt `window.onerror`, `unhandledrejection`
- schreibt Report nach `tmp/webgui-chaos-report-*.json` (bzw. `--report`)

**Exit-Code:** `0` = keine gesammelten Errors · `1` = Errors oder Harness-Fail.

### 3.3 Playwright optional

```bash
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

Ohne Playwright: Report-Schema und manuelle Injektion bleiben nutzbar (Browser-Konsole: Harness laden).

---

## 4. Destruktive Szenarien (opt-in, selten)

Nur mit Kopie der Caches / Wegwerf-`.env`.

| # | Aktion | Nachher prüfen |
|---|--------|----------------|
| D1 | Danger Zone: Cache eines Wallets löschen | Wallet leer/Hinweis; First-seen/Alter bleibt |
| D2 | Gesamten Analyse-Cache löschen | Nav/Wallet konsistent; nächster Scan möglich |
| D3 | Wallet entfernen + speichern | Nav ohne Leiche; Trace/Steuer ohne Crash |
| D4 | Labels verwerfen | Herkunft ohne Labels, kein Exception-Sturm |

---

## 5. Bekannte erlaubte „Störgeräusche“

Nicht als Fail werten, sofern UI stabil bleibt:

- Log-Zeilen auf Deutsch bei EN-UI (teilweise Backend)
- Electrum/Core-Timeouts, Tor-Hinweise
- „Moment noch“ / Still working bei langen Jobs
- Kurs-API Timeout beim Start

**Immer Fail:**
- Uncaught exception in Console
- Komplett leere `#app` trotz Token
- i18n-Rohkeys sichtbar (`header.*`, `privacy.*`, `cli.*`)
- Nicht beendbare disabled-Primärbuttons
- Nav-Ansicht und Inhalt dauerhaft asynchron

---

## 6. Befund-Vorlage (pro Lauf kopieren)

```text
Datum:
VERSION / Git:
Browser:
Modus: kurz | voll | chaos-auto
Seed (auto):
Runden (auto):

Console-Errors (Anzahl / Top-3):
UI-Fails:
Text/Parser-Auffälligkeiten (Feld + Payload-Skizze):
Job-Auffälligkeiten:
i18n-Auffälligkeiten:
Sonstiges:

Ergebnis: grün | gelb | rot
Ticket/ISSUES:
```

---

## 7. Pflege dieses Protokolls

- Nach neuen Hauptflächen (Nav-Eintrag, Dialog, Job-Art): Zeile in Abschnitt 2 ergänzen.
- Chaos-Harness: Selektoren in `scripts/webgui_chaos_harness.js` anpassen, wenn IDs/Klassen sich ändern.
- Einmal pro Quartal: Vollprotokoll + Chaos mit neuem Seed.
