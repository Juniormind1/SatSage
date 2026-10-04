# AGENTS.md — SatSage

Verfassung für KI-Assistenten. Bereichswissen liegt in der `AGENTS.md` des jeweiligen Verzeichnisses.

## HART · Geheimnisse und Doxxing (nie brechen)

**Niemals Geheimnisse pushen oder persönliche Daten doxxen.**

Gilt für **Commit, Push, PR, Issue, Changelog, Log-Ausgabe, Screenshot, Chat-Antwort und Tool-Output** — ohne Ausnahme, ohne „nur kurz / Test / Worktree / schon lokal“. Diese Regel steht über Bequemlichkeit und Task-Tempo.

**Geheimnisse** (Beispiele, nicht abschließend):

- `.env`, `.env.backup*`, scrambled `.env`, `.satsage-password` (+ `.tmp`)
- RPC-/API-Keys, App-Passwörter **und** Passwort-Hashes, Session-Token, SMTP/LLM-Keys
- Seed / Mnemonic / xprv / WIF; volle XPUBs/Deskriptoren in Commits oder öffentlichem Text
- Heim-Node-Credentials, Tor-Control-Passwörter, private Onion-URLs mit Auth

**Persönliche Daten / Doxxing** (Beispiele):

- Klarnamen, Anschrift, Telefon, private E-Mails (außer der freigegebenen Maintainer-Git-ID)
- Persönliche Wallet-Namen, reale Mainnet-Adressen/TxIDs des Nutzers in Issues, PRs, Doku, Changelogs
- Screenshots oder Logs, die Obiges erkennbar machen

**Pflicht vor jedem Commit und vor jedem Push:**

1. `git status` und den staged Diff lesen.
2. Trifft ein Pfad oder Diff-Inhalt die Listen oben → **abbrechen**, nicht committen/pushen.
3. Versehentlich gestaged: `git rm --cached -- <pfad>`, Eintrag in `.gitignore`, Commit nur der Bereinigung.
4. Versehentlich remote: History bereinigen (filter) + Force-Push nur mit Auftrag; betroffene Secrets **rotieren**.

Technische Riegel: `.gitignore`, `githooks/pre-commit` (Secret-Pfade), Dealbreaker **S1** in [`doc/merge-dealbreakers.md`](doc/merge-dealbreakers.md). Hooks ersetzen diese Prüfung nicht — Agents prüfen den Diff selbst.

## HART · Nutzer prüft das Ziel, bevor der Assistent groß testet

**Bevor der Assistent umfangreiche Tests selbst fährt, bittet er den Nutzer, kurz zu prüfen, ob sein Ziel erreicht ist.**

Umfangreich heißt: Testsuite, Regtest-Labor, Playwright, Chaos-Lauf, langer Verbindungstest, Browser-Durchklick über mehrere Ansichten. Ein einzelner, kurzer Syntax- oder JSON-Check zählt nicht.

Ablauf:

1. Änderung fertig erklären — was der Nutzer sehen oder tun soll.
2. Den Nutzer bitten, das Ziel kurz selbst zu prüfen.
3. Umfangreiche Tests auf unerwünschte Seiteneffekte **nur anbieten**. Nicht starten, nicht „ich teste das jetzt noch“.
4. Erst wenn der Nutzer das Angebot annimmt, die Tests fahren.

## HART · Nur der Worktree

**Arbeiten nur im aktuellen Worktree und darunter.**

Der Worktree ist der Ordner, in dem die Sitzung geöffnet ist (`git rev-parse --show-toplevel` dieses Clones). Lesen, Schreiben, Bauen, Testen und Logs bleiben in diesem Baum, inklusive `dist/`, `logs/`, `tmp/`.

Nicht erlaubt, auch nicht kurz und auch nicht, weil dort die laufende GUI, ihre Caches oder ein älteres Binary liegen:

- Dateien außerhalb des Worktrees anlegen, ändern, löschen oder dorthin kopieren (Home, Desktop, andere Projektordner)
- Binaries, Logs oder Caches dorthin schreiben
- Prozesse außerhalb des Worktrees starten, deren Dateien lesen oder sie samplen, um eine Aufgabe zu erledigen

Läuft die GUI woanders, sagt der Assistent nur, welche Datei aus diesem Worktree der Nutzer wohin kopiert. Das Kopieren macht der Nutzer. Die App darf danach ihre eigene Log-Datei neben der Executable schreiben; der Assistent liest sie nur, wenn der Nutzer sie in den Worktree legt oder den Inhalt hier einfügt.

## HART · Missverständliche Prompts nachfragen

**Ist ein Auftrag mehrdeutig, klärt der Assistent ihn mit dem Nutzer durch konkrete Rückfragen. Er rät nicht.**

Mehrdeutig heißt: ein Wort lässt mehrere Umsetzungen zu, eine Grenze oder ein Sonderfall ist nicht gesagt, oder der Assistent müsste wählen, was der Nutzer „wohl gemeint“ hat.

- Fragen, bevor Code, Tests oder Doku daraus entstehen.
- Jede Frage nennt die konkreten Varianten. Kein Raten in der Frage verstecken.
- Keine Heuristik, die eine Lesart still zur Regel macht (Fallback, „näher an heute“, „was üblich wäre“, Sonderfall selbst ausgedacht).
- Erst umsetzen, wenn die Antwort die Wahl festlegt.

## HART · Core-RPC nur aus der Allowlist

Dealbreaker **T14**. Jeder bitcoind-Aufruf geht durch `BitcoinRpcClient.call` in `core/bitcoind_rpc.py`; erlaubt sind nur `RPC_KERN` (lesend), `RPC_WALLET_IMPORT` (`listdescriptors` nur ohne private Schlüssel) und `RPC_LAB_REGTEST` (nur `NETWORK=regtest`). Keine wallet-schreibenden/signierenden RPCs, kein Roh-JSON-RPC, kein `bitcoin-cli` im Produktivcode. `RpcAllowlistError` nie in einen Fallback verschlucken (`except RpcAllowlistError: raise` vor `except Exception`). Neue Methode = Maintainer-Freigabe + Doku (`.env.example`, Handbuch „Bitcoin Core absichern“, README) + Tests `tests/test_rpc_allowlist*.py`. Jeder Pull Request nach `main` prüft Allowlist und die Hinweise „rpcwhitelist?“ / „disablewallet?“ zusätzlich am Regtest-Node (`lab/regtest/scripts/verify_rpc_allowlist.py`, Dealbreaker Q6).

## Zweck

**SatSage – know your sats** zeigt, woher Sats kamen und wann sie ein xPub-Wallet betraten oder verließen (Haltedauer, Stichtage). Signiert nicht. Einstieg: `server.py` (Web), `main.py` (CLI-Fallback).

## Context-Laden

- Immer: diese Datei (Root).
- Zusätzlich nur die `AGENTS.md` der Verzeichnisse, deren Dateien du änderst oder liest.
- Nie alle nested `AGENTS.md` auf einmal laden.
- Bereichsregeln gelten zusätzlich zur Root-Verfassung; bei Konflikt gewinnt Root-HART.

Root-Fassaden (`main.py`, `analyze.py`, `server.py`, …) haben keine eigene Datei. Deren Regeln stehen in `core/AGENTS.md`, `httpserver/AGENTS.md` und `web/AGENTS.md` und gelten mit, sobald du diese Fassaden anfasst.

## Bereichsindex

| Pfad | Wofür |
|------|--------|
| [`core/AGENTS.md`](core/AGENTS.md) | Engine, Datenquellen, Caches, `.env`, Modulgrenzen; gilt auch für `main.py` und `analyze.py` |
| [`web/AGENTS.md`](web/AGENTS.md) | Oberfläche, Locales, UI-Leitbilder |
| [`httpserver/AGENTS.md`](httpserver/AGENTS.md) | HTTP-API; gilt auch für `server.py` |
| [`specter_plugin/AGENTS.md`](specter_plugin/AGENTS.md) | Specter-Extension |
| [`packaging/AGENTS.md`](packaging/AGENTS.md) | PyInstaller, StartOS, Umbrel |
| [`lab/AGENTS.md`](lab/AGENTS.md) | Regtest-Labor |
| [`tests/AGENTS.md`](tests/AGENTS.md) | Suite ohne echte Wallet-Daten |
| [`scripts/AGENTS.md`](scripts/AGENTS.md) | GUI-Chaos, Userflow, Token, Commit-Skripte |
| [`doc/AGENTS.md`](doc/AGENTS.md) | Handbuch, Design, Changelog pflegen |
| [`githooks/AGENTS.md`](githooks/AGENTS.md) | Identität, Branches, Remote-Stand, Secret-Pfade |

## Cross-Cutting

- Kein Secret-Commit, kein Secret-Push. Vor jedem Commit und Push den staged Diff gegen **HART · Geheimnisse und Doxxing** halten.
- Mainnet-Adressen, TxIDs, Wallet-Namen und XPUBs des Nutzers nicht in Issues, PRs, Changelogs, Doku oder Logs.
- Tests, Fixtures und Beispiele nicht mit echten XPUBs, Seeds, xprv oder WIF.
- Keine Seed-/xprv-/WIF-Eingabe (Dealbreaker **T1**). Lern-URLs nur Bitcoin-only (**T13**). Keine Telemetrie, kein Remote-JS (**T3/T6**).
- Merge-Kriterien: [`doc/merge-dealbreakers.md`](doc/merge-dealbreakers.md). UI-Sprache Deutsch. `VERSION` bumpt nur der Maintainer. Nicht automatisch committen oder pushen.
- Nutzerprofil: seltener Gast, Wissen nur aus Mainchain-Traces der xpubs und Fremdwallet-Exporten. Caches sparen Electrs-Abfragen, sie sind keine Buchhaltung. Verlangt ein Feature mehr (Extremfall: eigene Los-Buchhaltung), das als Regelbruch sagen und [`doc/user-profile-ux.md`](doc/user-profile-ux.md) erst ändern lassen.
