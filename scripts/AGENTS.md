# AGENTS.md — `scripts/`

Gilt für Helfer unter `scripts/` (Web-GUI-Chaos, Userflow, Session-Token, Commit/Push, Builds). Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

## GUI-Tests · Token

Nie Token aus Logs greppen. Session-JSON `tmp/satsage-gui-session.json` bzw. Zeile `SATSAGE_SESSION {…}`; Helfer `scripts/webgui_test_ready.py spawn|attach|url`; Protokoll [`../doc/gui-test-protokoll.md`](../doc/gui-test-protokoll.md). Chaos: `--spawn`.

## Playwright und Docker

Nur auf **macOS, Linux und Grok-Bots**. Dort: `.venv/bin/python`, mitgeliefertes Chromium, `p.chromium.launch(headless=True)` **ohne** `channel` (Userflow: `scripts/webgui_userflow.py --spawn`). Docker/Regtest-Lab dort hochfahren ist der Prüfweg. **Windows (dieser Rechner):** kein Playwright, kein Docker hochfahren, kein Node/Browser-Setup durch den Assistenten. GUI-Kosmetik testet der Nutzer selbst; der Assistent ändert nach bestem Wissen und lässt Infrastruktur dem Nutzer. Vor dem Merge nach `main` testet der Assistent wieder selbst — auf macOS, Linux oder einem Grok-Bot, nicht indem er auf Windows Playwright oder Docker startet.

## Web-GUI-Stabilität (Rumgeklicke)

Protokoll [`../doc/testprotokoll-webgui-stabilitaet.md`](../doc/testprotokoll-webgui-stabilitaet.md); halbautomatisch `scripts/webgui_chaos_run.py` + `scripts/webgui_chaos_harness.js` (optional Playwright).

## Datenquellen-Wechsel während Scan

Protokoll [`../doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md`](../doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md) — P2P vs Electrum, Job-Snapshot, Cache-Flags, Queue. Fachregeln der Priorität: [`../core/AGENTS.md`](../core/AGENTS.md).

## Commit und Push

Helfer: `scripts/commit.sh`|`.bat`, `scripts/push.sh`|`.bat` (brechen bei Identitäts-Abweichung ab; `--fix-identity` setzt name/email/hooks). Identität, Branches und Remote-Pflicht stehen in [`../githooks/AGENTS.md`](../githooks/AGENTS.md).

- **Windows `.bat`:** echte `cmd.exe`-Dateien — **CRLF**-Zeilenenden (LF-only zerlegt CMD in Müll-Befehle), `REM`/`::` statt `#`, kein Bash-Syntax. Nach dem Schreiben Bytes prüfen (`\r\n`, kein UTF-16/NUL). `.sh` bleibt LF/Bash.
- Commit-Default der Maintainer-Skripte: getrackte + untracked **Text** auto; untracked **Binär** nach Nachfrage (`-A` alles, `-u` nur getrackt).
- Temporäre Skripte `_patch_*.py`, `_test_*.py`, `_profile_*.py` sind Entwicklungs-Hilfen — nicht committen.
- Kein Auto-Increment der `VERSION` in Scripts/CI.

## Builds

StartOS: `./scripts/build_startos_s9pk` (x86_64). PyInstaller: `scripts/build_satsage_macos` → `dist/satsage-macos`, `build_satsage_linux` → `dist/satsage-linux`, `build_satsage_win.bat` → `dist/satsage-windows.exe`. Regeln: [`../packaging/AGENTS.md`](../packaging/AGENTS.md).

Umfangreiche Läufe (Chaos, Playwright, langer Verbindungstest): erst den Nutzer das Ziel prüfen lassen (Root-HART), dann nur auf Angebot starten.
