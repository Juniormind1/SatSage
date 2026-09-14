# Web-GUI · Userflow-Testframe

**Ziel:** Ein fiktiver Nutzer klickt die Hauptmenüs durch. Das Ergebnis muss **akzeptabel** sein. Der Assistent führt den Lauf aus; **Exit 0** = freigabefähig.

## Was zählt als akzeptabel

| Kriterium | OK | Nicht OK |
|-----------|----|----------|
| Start | `#app` sichtbar, Token-Sperre weg | `#token-fehlt` |
| Navigation | Jede Kernansicht sichtbar nach Klick | Section bleibt `hidden` |
| Laden | „Lade aus Cache…“ verschwindet ≤ ~30 s | Hängt minutenlang |
| Inhalt | Marker-Elemente existieren (auch leere Listen) | Fehlermeldung „Interner Serverfehler“ / „Auswertung fehlgeschlagen“ |
| Sprache | EN/DE-Umschalter wechselt `lang` | Klick ohne Wirkung |
| Console | Keine schweren `pageerror` | Uncaught Exceptions |

## Kern-Schritte (Reihenfolge)

1. Wallet  
2. Herkunft tracen  
3. Steuerjahr  
4. Sanktionen  
5. Wallets (Verwaltung)  
6. Einstellungen  
7. Datenquellen  
8. Sprache EN → DE  
9. Steuerjahr: Report HTML ohne Auswahl (Warnung, kein Crash)

## Aufruf

```bash
# Isoliert (Temp-Wallets) — CI / Assistent ohne Prod-.env
.venv/bin/python scripts/webgui_userflow.py --spawn

# Laufender Dev-Server (tmp/satsage-gui-session.json)
.venv/bin/python scripts/webgui_userflow.py --attach

# Explizit
.venv/bin/python scripts/webgui_userflow.py --url 'http://127.0.0.1:8730/?t=…'
```

Voraussetzung: Playwright

```bash
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
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
