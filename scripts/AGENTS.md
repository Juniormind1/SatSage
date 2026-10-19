# AGENTS.md — `scripts/`

Gilt für Helfer unter `scripts/` (Web-GUI-Chaos, Userflow, Session-Token, Commit/Push, Builds). Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

## GUI-Tests · Token

Nie Token aus Logs greppen. Session-JSON `tmp/satsage-gui-session.json` bzw. Zeile `SATSAGE_SESSION {…}`; Helfer `scripts/webgui_test_ready.py spawn|attach|url`; Protokoll [`../doc/gui-test-protokoll.md`](../doc/gui-test-protokoll.md). Chaos: `--spawn`.

## Playwright und Docker

**macOS** ist der vorgesehene Rechner für alle Userflow-Tests, für Playwright und für das installierte Chrome (`channel="chrome"`, `scripts/webgui_userflow.py --spawn`). Der Merge-Schritt ist der Job `gui` im Workflow `Regtest-Labor`: dort Linux mit gebündeltem Chromium ohne `channel`, lokal auf dem Mac dieselben Läufe im installierten Chrome. **Windows:** kein Playwright und kein Docker durch den Assistenten. GUI-Kosmetik testet der Nutzer selbst.

## Web-GUI-Stabilität (Rumgeklicke)

Protokoll [`../doc/testprotokoll-webgui-stabilitaet.md`](../doc/testprotokoll-webgui-stabilitaet.md). Q6-Schritt: `scripts/webgui_chaos_run.py --spawn --rounds 200 --seed 42` mit `scripts/webgui_chaos_harness.js`.

## Datenquellen-Wechsel während Scan

Protokoll [`../doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md`](../doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md) — P2P vs Electrum, Job-Snapshot, Cache-Flags, Queue. Fachregeln der Priorität: [`../core/AGENTS.md`](../core/AGENTS.md).

## Scan-Abbruch und Cache

Protokoll [`../doc/testprotokoll-scan-abbruch-cache.md`](../doc/testprotokoll-scan-abbruch-cache.md). Runner und Proxy liegen im Labor (`lab/regtest/scripts/verify_scan_abort_cache.py`, `electrs_delay_proxy.py`), nicht hier. Windows: kein Docker starten.

## P2P nicht testen

P2P ist keine ausreichende Datenquelle. `verify_p2p_traces.py` nicht starten. Im Scan-Abbruch `Q-START-P2P` und `Q-START-KILL` nicht mitlaufen lassen. Grund: [`../doc/issues/p2p-herkunft.md`](../doc/issues/p2p-herkunft.md). Suite: [`../doc/test-inventar.md`](../doc/test-inventar.md). Frühestens 2027-01-08.

## Commit und Push

Helfer: `scripts/commit.sh`|`.bat`, `scripts/push.sh`|`.bat` (brechen bei Identitäts-Abweichung ab; `--fix-identity` setzt name/email/hooks). Identität, Branches und Remote-Pflicht stehen in [`../githooks/AGENTS.md`](../githooks/AGENTS.md).

- **Windows `.bat`:** echte `cmd.exe`-Dateien — **CRLF**-Zeilenenden (LF-only zerlegt CMD in Müll-Befehle), `REM`/`::` statt `#`, kein Bash-Syntax. Nach dem Schreiben Bytes prüfen (`\r\n`, kein UTF-16/NUL). `.sh` bleibt LF/Bash.
- Commit-Default der Maintainer-Skripte: getrackte + untracked **Text** auto; untracked **Binär** nach Nachfrage (`-A` alles, `-u` nur getrackt).
- Temporäre Skripte `_patch_*.py`, `_test_*.py`, `_profile_*.py` sind Entwicklungs-Hilfen — nicht committen.
- Kein Auto-Increment der `VERSION` in Scripts/CI.

## Builds

StartOS: `./scripts/build_startos_s9pk` (x86_64). PyInstaller: `scripts/build_satsage_macos` → `dist/satsage-macos`, `build_satsage_linux` → `dist/satsage-linux`, `build_satsage_win.bat` → `dist/satsage-windows.exe`. Regeln: [`../packaging/AGENTS.md`](../packaging/AGENTS.md).

Umfangreiche Läufe (Chaos, Playwright, langer Verbindungstest): erst den Nutzer das Ziel prüfen lassen (Root-HART), dann nur auf Angebot starten.
