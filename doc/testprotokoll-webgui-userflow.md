# Web-GUI · Userflow-Testframe

**Ziel:** Ein fiktiver Nutzer klickt die Hauptmenüs durch. Das Ergebnis muss **akzeptabel** sein. Der Assistent führt den Lauf aus; **Exit 0** = freigabefähig.

## Was zählt als akzeptabel

| Kriterium | OK | Nicht OK |
|-----------|----|----------|
| Start | `#app` sichtbar, Token-Sperre weg | `#token-fehlt` |
| Navigation | Jede Kernansicht sichtbar nach Klick | Section bleibt `hidden` |
| Laden | „Lade aus Cache…“ verschwindet ≤ ~30 s | Hängt minutenlang |
| Inhalt | Marker-Elemente existieren (auch leere Listen) | Fehlermeldung „Interner Serverfehler“ / „Auswertung fehlgeschlagen“ |
| Sprache | EN, dann zurück nach DE. Sichtbare Texte sind die der gewählten Sprache, keine Roh-Schlüssel (`settings.password.title`) | Umschalter ohne Wirkung, deutscher Text bleibt in EN stehen, Schlüssel sichtbar |
| Console | Keine schweren `pageerror` | Uncaught Exceptions |

## Kern-Schritte (Reihenfolge)

1. Wallet  
2. Herkunft tracen  
3. Steuerjahr  
4. Sanktionen  
5. Wallets (Verwaltung)  
6. Einstellungen  
7. Datenquellen  
8. Sprache EN → DE, danach Prüfung auf Roh-Schlüssel und Texte der anderen Sprache (`scripts/webgui_i18n_check.py`). Das Log bleibt ausgenommen.  
9. Steuerjahr: Report HTML ohne Auswahl (Warnung, kein Crash)
10. Nur bei `--spawn`: Passwort setzen, ändern und löschen, je für Desktop, Specter und Umbrel (`scripts/webgui_passwort_flow.py`). `--url` und `--attach` lassen die echte Sitzung in Ruhe.

## Aufruf

Strategie nach Betriebssystem, eine pro Umgebung. Details und die verbotenen Alternativen: `doc/gui-test-protokoll.md` (Abschnitt „Playwright · eine Strategie pro Betriebssystem“).

```bash
# macOS und Linux — mitgeliefertes Chromium, ohne --channel
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/webgui_userflow.py --spawn
.venv/bin/python scripts/webgui_userflow.py --attach
.venv/bin/python scripts/webgui_userflow.py --url 'http://127.0.0.1:8730/?t=…'

# Windows — installiertes Chrome (Fernsteuer-Zustimmung)
py -3 scripts/webgui_userflow.py --spawn --channel chrome
py -3 scripts/webgui_userflow.py --attach --channel chrome
```

## Report

`tmp/webgui-userflow-report.json` — `ok`, `schritte[]`, `dauer_s`, `console_errors`.

## Abgrenzung

| Tool | Zweck |
|------|--------|
| **userflow** | Deterministischer Happy-Path durch Menüs |
| **chaos** (`webgui_chaos_run.py`) | Zufalls-Rumgeklicke, Stabilität |
| **gui-test-protokoll** | Token/Session, kein Log-Grep |

## Assistenten-Regel

Nach GUI-relevanten Fixes: **Userflow grün fahren**, bevor „fertig“ gemeldet wird. Bei Fail: Report-Schritte lesen, Fix, erneut.
