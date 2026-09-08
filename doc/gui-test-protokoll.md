# GUI-Test-Protokoll (Token & Session)

**Für:** KI-Assistenten und halbautomatische Browser-Tests (Playwright, Chaos, manuell).  
**Ziel:** Zuverlässig die Web-GUI öffnen **ohne** Token aus Logs zu greppen.

---

## Das Problem

| Alter Weg | Warum er scheitert |
|-----------|-------------------|
| `server.py` starten, Log nach `?t=` scannen | stdout gepuffert; Header-Jobs dazwischen; Timing |
| Fester Port 8730 + altes Token | Neustart → neues Token; zweiter Prozess tot |
| Produktions-`.env` im Test | Seiteneffekte, echte XPUBs, flaky Netzzugriff |

Das Token ist absichtlich nur lokal und pro Prozess — gut für Sicherheit, schlecht für „Log lesen und hoffen“.

---

## Goldene Regel

**Token nie aus Freitext-Logs parsen.**  
Immer eine dieser Quellen:

1. **Session-JSON** (`tmp/satsage-gui-session.json`)
2. **Stdout-Zeile** `SATSAGE_SESSION {…}` (eine JSON-Zeile, flush)
3. **Hilfsskript** `scripts/webgui_test_ready.py` (spawn/attach/url)
4. **In-Process:** `starte_im_hintergrund()` → `.url` / `.token` (Chaos-Runner, Unit-Tests)

---

## Session-Datei

Beim CLI-Start (`server.py` / Binary) nach erfolgreichem Bind:

- Datei: `{app_dir}/tmp/satsage-gui-session.json` (mode `0600`)
- Override: `SATSAGE_SESSION_FILE=/pfad/session.json`
- Zusätzlich eine Zeile auf stdout:

```text
SATSAGE_SESSION {"schema":1,"url":"http://127.0.0.1:8730/?t=…","token":"…","port":8730,…}
```

Felder: `url`, `token`, `port`, `bind`, `pid`, `env_path`, `ts`.

Beim Beenden wird die Datei gelöscht. `tmp/` ist gitignored.

Modul: `core/gui_session.py`.

---

## Assistenten-Ablauf (kurz)

### A · Isolierter Test (empfohlen)

```bash
# Terminal 1 — blockiert, Server lebt
.venv/bin/python scripts/webgui_test_ready.py spawn --json
```

Stdout (eine Zeile JSON) enthält `url` und `token`. Playwright:

```text
page.goto(session["url"])
```

Oder Chaos:

```bash
.venv/bin/python scripts/webgui_chaos_run.py --spawn --rounds 100 --seed 42
```

(`--spawn` braucht **kein** externes Token-Grep.)

### B · Bereits laufender Dev-Server

```bash
# Server normal gestartet → Session-Datei existiert
.venv/bin/python scripts/webgui_test_ready.py attach --json
# oder
.venv/bin/python scripts/webgui_test_ready.py url
```

`attach` wartet bis `/api/config` mit dem Token 200 liefert (Timeout default 20 s).

### C · Smoke ohne Browser

```bash
.venv/bin/python scripts/webgui_test_ready.py spawn --once --json   # start+API+stop
.venv/bin/python scripts/webgui_test_ready.py config --json          # bei laufender Session
```

---

## Playwright-Checkliste

1. Session holen (`spawn` oder `attach` → JSON).
2. `page.goto(url)` mit **vollständigem** `?t=…`.
3. Dialoge dismissen (`#einrichtung-spaeter`, On-Chain-OK, …).
4. Harness: **`page.evaluate(harnessSrc)`**, nicht `add_script_tag` (CSP).
5. Nie hardcodiertes Token; nie Port 8730 annehmen ohne Session-Check.

---

## CSP & Splash (Kurz)

- Inline-Script-Tags sind blockiert → Chaos-Harness per CDP/`evaluate`.
- macOS: kein PyInstaller-Splash; optional Tk (`core/splash_ui.py`). Tests: `SATSAGE_NO_SPLASH=1`.

---

## Anti-Patterns

| Nicht | Stattdessen |
|-------|-------------|
| `grep '?t=' server.log` | `webgui_test_ready.py url` / Session-JSON |
| Token aus Screenshot/OCR | Session-API |
| Zwei Server auf 8730 raten | `spawn --port 0` oder Session `port` |
| Produktions-Caches mutieren | `--spawn` / Temp-`.env` |

---

## Bezug

- Stabilitäts-Chaos: `doc/testprotokoll-webgui-stabilitaet.md`
- Runner: `scripts/webgui_chaos_run.py`, `scripts/webgui_chaos_harness.js`
- Session-Helfer: `scripts/webgui_test_ready.py`
- Core: `core/gui_session.py`
