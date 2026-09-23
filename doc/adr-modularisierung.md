# ADR · Modularisierung SatSage

**Status:** Entwurf · **Stand:** 2026-09-23  
**Branch-Basis:** `dev-juniormind` @ `6dc7174` (letzter Commit vor Modularisierungs-Refaktorierung)  
**Arbeitsbranch (vorgesehen):** `refactor/modular-engine`  
**Bezug:** [`ISSUES.md` · Architektur · Modularisierung](../ISSUES.md), [`doc/issues/modularisiere_prompt.txt`](issues/modularisiere_prompt.txt)

## Kontext

God-Files blockieren parallele Feature-Arbeit: fast jedes nutzerwirksame Feature berührt `server.py` und/oder `web/app.js`. Merge-Konflikte und Rebase-Schmerz sind die Folge — nicht nur „unschöner Code“.

Messbare Größen (Arbeitsbaum `6dc7174`):

| Datei | ~Bytes |
| --- | ---: |
| `web/app.js` | 583 KB |
| `server.py` | 389 KB |
| `main.py` | 250 KB |
| `analyze.py` | 143 KB |
| `fulcrum.py` / `bip158_scanner.py` | ~86 KB / ~84 KB |

`core/` ist bereits teilweise modular (`config`, `jobs`, `tax`, `trace`, `source`, `wallets`, `utxos`, neu: `wallet_discover`, `wallet_export_import`, `env_scramble`, …), wird aber von den Root-Monolithen umgangen oder verdoppelt. `server.py` allein enthält **~72 `api_*`-Handler** plus eine große `_api`-Dispatch-Liste und die HTTP-Klasse.

## Leitprinzip für diesen ADR

Vergangene Commits mit **für den Benutzer spürbarer** neuer Funktionalität hätten **weitgehend parallel** entwickelt werden können — wenn API- und UI-Schnitte nach **Änderungsdomäne** getrennt wären.

Der Done-Check je Slice lautet deshalb nicht nur „Tests grün“, sondern:

> Zwei typische Features aus der jüngsten Historie hätten weitgehend **ohne dieselbe Datei** landen können.

Kosmetisches Umschieben in ein neues God-File (`core/mega_api.py`) gilt als **ungenügend**.

## Ist-Schichten (kurz)

- **Surfaces:** `server.py` (HTTP + fast alle `api_*`), `web/app.js` (UI-Monolith), Legacy-CLI in `main.py`/`menu.py`, Specter-Plugin.
- **Engine/Orchestrierung:** große Teile von `main.py` (Ableitung, Scan-Steuerung, Cache-Flags), `analyze.py` (Trace-Pipeline).
- **Daten/Fach:** `core/*` (teilweise), vermischt mit API-Logik noch in `server.py`.
- **Adapter:** `fulcrum.py`, `bip158_scanner.py`, P2P/Core-Helfer unter `core/`.

## Soll-Schichten (pragmatisch)

1. **engine** — Ableitung, Caches, Datenquellenwahl, Trace-Orchestrierung (heute oft `main`/`analyze`).
2. **core** — Daten-APIs, Jobs, Steuer, Config, Wallet-Modelle; **kein** `print()`.
3. **adapters** — Fulcrum/Electrum, BIP-158/P2P, bitcoind-RPC, Sanctioned.
4. **surfaces** — dünnes `server.py` (Bind, Auth-Shell, Static, Dispatch), `web/*` nach Views, CLI-Einstieg.

## Rückblick · Feature-Paare (warum Domänenschnitte)

Beispiele aus `dev-juniormind` (Sep 2026), die **gleichzeitig** hätten laufen können, aber heute an denselben Hotspots kollidieren:

| Domäne A (Beispiel-Commits) | Domäne B | Heutiger Konflikt-Hotspot |
| --- | --- | --- |
| Steuerjahr-Viz / Trace-UI (`2854571`, `e0824c5`, `63e38f0`, `10ab8d9`) | Wallet-Import Sparrow/Wasabi (`6f24998`…`8ffea27`) | `server.py` + `web/app.js` |
| Datenquellen / Tor-Batch / Pillen (`ca2f90d`, `51686c0`, `776f240`) | Empfang-QR / Tip-Sync / Animation (`a6467c0`, `2446146`, `7f794dc`) | `server.py` + `web/app.js` (+ teils `main`) |
| Börsen-CSV (`1e93c94`) | Passwort-/Env-Scramble (`32f410e`, `6dc7174`) | `server.py` + `web/app.js` |
| Kurs-Cache USD/EUR (`f486d99`) | Herkunft-Filter Datum/Betrag (`7c4c376`) | `main.py` vs `web/app.js` — schon besser, aber API oft noch über `server.py` |

**Schluss:** Slice 1 muss **`server.py` nach API-Domänen** schneiden (nicht alphabetisch, nicht „obere/untere Hälfte“). Parallel dazu (Slice 2) `web/app.js` nach denselben Domänennamen — dann greift der Done-Check.

## Slice 1 (fest) · `server.py`

### Zielbild

- `server.py` bleibt **Einstieg**: Bind (`127.0.0.1` / Managed), Token/Session, Static/Login, `main_cli`, Specter-Kompatibilität, dünne HTTP-Klasse.
- Routing: `_verarbeite` / `_api` bleiben dünn — Delegation an Domänen-Module.
- Handler-Logik wandert nach Domäne, z. B. unter `core/api/` oder `httphttpserver/api/` (Name im Slice festlegen; Preferenz: **`core/api_*` nur wenn kein HTTP**, sonst **`httpserver/api/<domäne>.py`** mit reinen Request→Dict-Handlern).

Empfohlene Modulgrenzen (an bestehenden `api_*`-Namen orientiert):

| Modul (Vorschlag) | Inhalt (Beispiele) | Parallele Features, die entkoppelt werden |
| --- | --- | --- |
| `httpserver/api/auth_session.py` | Login/Setup/Password, unlock-env, CSRF/Host-Helfer die nur Auth betreffen | Passwort-Dialog, Env-Scramble-UI |
| `httpserver/api/config_ui.py` | `api_config`, UI-Lang/Theme, Lernhinweise, Status-Mail, LLM-Save | Umbrel/i18n, Settings-Kosmetik |
| `httpserver/api/source.py` | `api_save_source`, clear, electrum laden, source status, öffentliche Electrum, local-core accept, rescan, header-vorab | Datenquellen, Tor-Batch-Config |
| `httpserver/api/wallets.py` | save wallets, probe, deskriptor, sparrow/wasabi/export-import, discover-Pfade, tip-sync, empfang | Wallet-Import, lokale Suche |
| `httpserver/api/utxos_cache.py` | wallet/alle utxos, cache-* | Tip-Sync-Bestand, Cache löschen |
| `httpserver/api/trace_verlauf.py` | `api_trace*`, `api_verlauf` | Herkunft-Baum, AML-Trace |
| `httpserver/api/tax.py` | `api_tax`, selbstanzeige, exports/downloads | Steuerjahr, Selbstanzeige |
| `httpserver/api/jobs.py` | jobs/job/cancel | Job-Cancel-Reliabilität |
| `httpserver/api/labels_sanctions_exchange.py` | labels, sanctions, exchange-reports | Börsen-CSV, Sanktionscheck |
| `httpserver/api/price_llm_lab.py` | price*, llm status/chat/context, lab faucet | Kurs-Anreicherung, Assistent |

Fassaden: alte Symbolnamen (`api_trace`, …) per Re-Export in `server.py` oder `httpserver/api/__init__.py` vorhalten, bis Imports/Tests umgestellt sind.

### Charakterisierung / Tests (vor dem ersten Move)

Mindestens: `tests/test_api.py`, `tests/test_eingebetteter_server.py`, `tests/test_gui_session.py`, `tests/test_jobs.py`, plus neu berührte Import-/Export-Tests.

### Done-Check Slice 1

- `server.py` ≪ 100 KB (Orientierung aus Prompt; sonst weiter schneiden).
- Mindestens die Domänen **wallets**, **source**, **trace_verlauf**, **tax** liegen in getrennten Dateien.
- Rückblick-Test: „Sparrow-Import“ und „Steuerjahr-Trace“ hätten API-seitig ohne gemeinsame Handler-Datei landen können.
- Kein neues God-File; Specter/PyInstaller starten; genannte Tests grün.
- Kurzes Abschlussmemo + Einschätzung Merge-Lage (ehrlich: kosmetisch vs. Domänentrennung).

### Explizit nicht Slice 1

- `web/app.js` umschreiben (folgt Slice 2, gleiche Domänennamen).
- `main.py` / `analyze.py` entkernen.
- Features, UI-Redesign, neue Dependencies, FastAPI-Rewrite.
- Secrets / `.env` / XPUBs anfassen oder loggen.

## Weitere Extraktionen (priorisiert)

| # | Slice | Nutzen | Risiko | Merge-Gewinn |
| --- | --- | --- | --- | --- |
| 0 | Dieser ADR | Orientierung | niedrig | indirekt |
| **1** | **`server.py` → Domänen-API** | testbare API, sofort weniger Konflikte | mittel (viele Imports) | **hoch** |
| 2 | `web/app.js` → Views (`wallets`, `utxos`, `herkunft`, `steuerjahr`, `settings`, `datenquellen`, `assistant`, Bootstrap) | größter Klumpen | mittel (Globals) | **hoch**, erst wirksam mit Slice 1 |
| 3 | `main.py` → stabile Engine-Funktionen (Ableitung, Cache-Flags, Quellenwahl) | CLI/Specter/Packaging entlasten | höher | mittel |
| 4 | `analyze.py` → Trace-Module, Orchestrierung dünn | Trace parallel zu Steuer/Wallet | mittel | mittel |
| 5 | Adapter-Feinschnitt `fulcrum.py` / `bip158_scanner.py` | klar abgegrenzt | niedriger | niedriger (weniger Feature-Hotspot) |

`sanctioned.py` / `menu.py` sind kleiner — nachziehen bei Bedarf, nicht als eigener Epic.

## Arbeitsregeln (in `AGENTS.md` nachziehen, sobald Slice 1 landet)

- Neue Logik nicht an Root-God-Files anhängen.
- `server.py` / `main.py` bleiben dünne Einstiege.
- Datei > ~80–100 KB oder Funktion > ~80 Zeilen → Split-Kandidat.
- Refactor-Slices sind eigene Aufgaben, keine Drive-bys in Feature-PRs.
- Modularisierungs-Branch: kurze Lebensdauer, oft auf `dev-juniormind` rebasen.

## Entscheidung

- **Slice 1 = `server.py`**, Domänenschnitt wie oben.
- Erfolg bemisst sich an **paralleler Entwickelbarkeit** (Rückblick auf spürbare Features), nicht an Zeilenzahl allein.
- Nächster Implementierungs-Prompt: Characterization-Tests → Extraktion wallets/source/trace/tax zuerst (höchster Hotspot laut Historie) → restliche Domänen → Memo.

## Offene Punkte vor Code

- Exact package path: `httphttpserver/api/` vs. `core/api/` — Empfehlung **`httphttpserver/api/`** (HTTP-Handler), Business bleibt in `core/`.
- Ob `_api`-Dispatch als Tabelle (`ROUTES`) oder als if-Kette pro Modul — beides ok; Tabelle erleichtert spätere Specter/OpenAPI-Doku.

## Nachtrag 2026-09-23 · Package-Pfad

`server/api/` ist wegen Kollision mit dem Modul `server.py` **nicht** nutzbar. Slice-1-Handler liegen unter **`httpserver/api/`** (Einstieg bleibt `server.py`).
