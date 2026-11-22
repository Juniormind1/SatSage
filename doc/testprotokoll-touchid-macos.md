# Testprotokoll: Touch ID am Mac

**Stand:** 2026-11-22  
**Für:** Nutzer mit einem Mac mit Touch ID (eingebaut oder Magic Keyboard mit Touch ID).  
**Zweck:** Prüfen, ob der Touch-ID-Login im echten Build läuft. Zuerst kommen die offenen Punkte aus dem Spike (M0), die sich auf Linux nicht prüfen lassen. Danach folgt der Ablauf in der Web-GUI.

**Verwandt:** Handbuch Abschnitt 11.1 „Touch ID am Mac“, [`logging-richtlinie.md`](logging-richtlinie.md) (Abschnitt Touch ID), `packaging/macos/satsage-touchid.swift`, `scripts/touchid_selftest_macos.py`, `scripts/build_satsage_macos`.

**Daten:** Für den Test reicht ein frischer Datenordner mit Testpasswort. Echte XPUBs und Börsen-CSVs braucht es nicht. Was zurückgeschickt wird, steht in Abschnitt 5.

---

## 0. Umgebung

| Feld | Wert |
|------|------|
| Datum / Uhrzeit (Europe/Berlin) | |
| Mac-Modell, Chip (Intel / Apple Silicon) | |
| macOS-Version (`sw_vers -productVersion`) | |
| Touch ID: eingebaut / Magic Keyboard | |
| Deckel offen / zugeklappt (Clamshell) | |
| Xcode-Befehlszeilenwerkzeuge (`swiftc --version`, erste Zeile) | |
| Git-Stand (`git rev-parse --short HEAD`) | |

---

## 1. Selbsttest des Hilfsprogramms (M0-Spike)

```bash
xcode-select --install          # einmalig, falls swiftc fehlt
python3 scripts/touchid_selftest_macos.py
```

Der Selbsttest baut das Hilfsprogramm nach `build/touchid-selftest/` und nutzt einen eigenen Test-Eintrag (Account = SHA-256 von „satsage-touchid-selftest“). Das zufällige Testpasswort zeigt er nie an. Am Ende entfernt er den Eintrag wieder.

| Nr. | Prüfpunkt | Erwartung | Ergebnis (OK / FEHLER / HINWEIS + Code) |
|-----|-----------|-----------|------------------------------------------|
| S1 | argv wird abgelehnt | OK | |
| S2 | `probe`: available, biometry | `available=True biometry=touchid` | |
| S3 | Python-Backend `available()` | OK | |
| S4 | enroll: Touch-ID-Dialog erscheint aus einem Kindprozess ohne .app | Dialog kommt, Finger → OK | |
| S5 | Dialogtext lesbar („… den SatSage-Selbsttest zu bestätigen“) | ja | |
| S6 | unlock liefert dasselbe Passwort | OK | |
| S7 | kein zusätzlicher Schlüsselbund-Dialog beim selben Programm | kein Dialog | |
| S8 | Abbrechen wird als `cancelled` erkannt (`la_name=userCancel`) | OK | |
| S9 | unlock aus kopiertem Programm (wie PyInstaller-`_MEI`-Ordner) | OK, **kein** Schlüsselbund-Dialog | |
| S10 | unlock nach Neubau (andere cdhash, wie nach einem Update) | Notieren: Schlüsselbund-Dialog ja/nein | |
| S11 | remove, Eintrag weg | OK | |

Bei S9 oder S10 kann macOS einen Schlüsselbund-Dialog zeigen („satsage-touchid möchte auf … zugreifen“). Dann bitte festhalten, welche Knöpfe er hat und was nach „Immer erlauben“ beim nächsten Lauf passiert. Davon hängt ab, ob der Onefile-Build ohne Zusatzdialog auskommt.

### 1a. Sonderfälle (optional, wenn Zeit ist)

| Nr. | Prüfpunkt | Erwartung | Ergebnis |
|-----|-----------|-----------|----------|
| S12 | Deckel zu, externes Display, ohne Magic Keyboard mit Touch ID | `probe` → `available=False`, Code `not_available`, LAError z. B. `biometryNotAvailable(-6)` | |
| S13 | Aufruf über SSH (`ssh mac python3 scripts/touchid_selftest_macos.py`) | `not_available` oder Dialog am Mac, kein Hängen | |
| S14 | Fünfmal falscher Finger | Code `locked_out`, LAError `biometryLockout(-8)` | |

---

## 2. Build

```bash
./scripts/build_satsage_macos
```

| Nr. | Prüfpunkt | Erwartung | Ergebnis |
|-----|-----------|-----------|----------|
| B1 | Build-Ausgabe zeigt „ok: build/touchid/satsage-touchid (ad-hoc signiert)“ und am Ende „TouchID: mit Touch ID (…)“ | ja | |
| B2 | Ohne `swiftc` (z. B. `SATSAGE_SKIP_TOUCHID=1`) baut er trotzdem, mit Warnung | ja | |
| B3 | Hilfsprogramm im Onefile gebündelt: nach dem Start existiert `$TMPDIR/_MEI…/bin/satsage-touchid` mit x-Bit (`ls -l`) | ja | |
| B4 | Signatur nach PyInstaller: `codesign -dv "$TMPDIR"/_MEI*/bin/satsage-touchid` zeigt `Signature=adhoc` | ja (sonst Ausgabe notieren) | |

---

## 3. Web-GUI

`dist/satsage-macos` starten (Terminal offen lassen). Im Browser geht es über `http://127.0.0.1:…`, nicht über eine LAN-Adresse.

| Nr. | Schritt | Erwartung | Ergebnis |
|-----|---------|-----------|----------|
| W1 | Passwort einrichten (Testpasswort), abmelden | Login-Seite zeigt Kästchen „Nach der Anmeldung Touch ID für diesen Mac aktivieren“ | |
| W2 | Mit Passwort anmelden, Kästchen an | Touch-ID-Dialog, danach angemeldet. Einstellungen · Passwort zeigt bei Touch ID „An. …“ | |
| W3 | Abmelden | Login-Seite zeigt Knopf „Mit Touch ID entsperren“ und das Passwortfeld | |
| W4 | Knopf → Finger | angemeldet, Konfiguration entsperrt (keine zweite Passwortabfrage) | |
| W5 | Knopf → Abbrechen | Meldung „Touch ID abgebrochen. Bitte Passwort eingeben.“, Passwortfeld bleibt nutzbar | |
| W6 | Knopf → falscher Finger bis Fehler | Meldung „nicht erkannt“. Danach geht das Passwort noch | |
| W7 | Einstellungen: Passwort ändern | Touch ID ist danach aus (Login-Seite zeigt wieder das Kästchen) | |
| W8 | Touch ID wieder aktivieren, dann in Systemeinstellungen einen Fingerabdruck hinzufügen oder löschen, abmelden, Knopf | Meldung „Fingerabdrücke wurden geändert“, Touch ID ist aus | |
| W9 | Einstellungen: „Touch ID deaktivieren“ | aus, Schlüsselbund-Eintrag „SatSage Touch ID“ weg (Schlüsselbundverwaltung) | |
| W10 | Aufruf von einem zweiten Gerät im LAN (falls freigegeben) | kein Touch-ID-Knopf, nur Passwort | |
| W11 | Zwei Tabs, in beiden gleichzeitig den Knopf drücken | ein Dialog, der zweite Tab meldet „läuft bereits“ | |

---

## 4. Logs: was drinsteht

Touch ID schreibt eine Zeile pro Ereignis nach `logs/touchid.log` neben der Executable, also neben `dist/satsage-macos`. Warnungen erscheinen zusätzlich im Terminal. In den Zeilen stehen nur Codes:

| Feld | Bedeutung |
|------|-----------|
| `backend verfuegbar=ja/nein grund=…` | Ergebnis von `probe` (z. B. `not_available`, `helper_missing`). Wird nur bei einer Änderung geschrieben. |
| `helper vorhanden=ja quelle=bundle datei=bin/satsage-touchid onefile_temp=ja` | Wo das Hilfsprogramm gefunden wurde. Steht ohne Ordnerpfad und ohne Benutzernamen. |
| `helper_call cmd=… ergebnis=… dauer_ms=… exit=…` | Aufruf des Hilfsprogramms. |
| `la_name=userCancel la_code=-2` | LAError von macOS. |
| `osstatus=-25300` | Keychain-OSStatus (−25300 = Eintrag nicht gefunden, −25293 = Authentisierung fehlgeschlagen). |
| `domain_changed=ja/nein` | Ob sich die Fingerabdrücke seit dem Aktivieren geändert haben. |
| `ergebnis=timeout timeout_s=60` | Dialog nicht beantwortet. |
| `gate route=login entscheidung=ok/remote/not_available loopback=ja/nein` | Gate-Entscheidung. |
| `route route=login ergebnis=… http=… dauer_ms=…` | Ergebnis der Anfrage. |
| `rate_limit=ja` | Sperre nach zu vielen Fehlversuchen. |
| `invalidiert grund=passwort_gesetzt/passwort_entfernt/stale/unlock_invalidated` | Warum Touch ID abgeschaltet wurde. |
| `konto=1a2b3c4d…` | Nur die ersten 8 Zeichen des Account-Hashes. |

Nie im Log: das Passwort oder seine Länge, Schlüsselbund-Inhalt, DomainState-Bytes, der volle Account-Hash und Pfade mit Benutzernamen. Das prüfen `tests/test_touchid_log.py` und die Tests in `tests/test_touchid.py`.

---

## 5. Zurückschicken

1. Die Zusammenfassung am Ende von `scripts/touchid_selftest_macos.py` (Abschnitt 1).
2. `build/touchid-selftest/touchid-selftest.log`
3. `logs/touchid.log` neben `dist/satsage-macos` (Abschnitte 2 und 3).
4. Die ausgefüllten Tabellen oben, bei Schlüsselbund-Dialogen mit Wortlaut der Knöpfe.

Vor dem Senden kurz durchsehen. Es sollten nur Codes, Zahlen und `ja`/`nein` drinstehen. Bitte keine `.env`, keine `.satsage-password` und keine Börsen-CSV mitschicken.
