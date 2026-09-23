# ADR · Modularisierung SatSage

**Status:** akzeptiert · Slice 1+2 weitgehend · Shared-Kern/CLI-Schnitte 1–6 erledigt  
**Stand:** 2026-09-23 (Nachzug UI 1–4 + Server 5–6)  
**Branch-Basis:** `dev-juniormind` @ `6dc7174` (letzter Commit vor Modularisierungs-Refaktorierung)  
**Arbeitsbranch:** `refactor/modular-engine` (tip nach Docs-Commit; UI/Server-Schnitte 1–6)  
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
- Implementierung Slice 1 + Slice 2: siehe **Abschlussmemo** unten.

## Offene Punkte (Stand Memo)

- Package-Pfad: **geschlossen** → `httpserver/api/` (HTTP-Handler), Business in `core/`. `server/api/` unbrauchbar (Kollision mit `server.py`).
- `_api`-Dispatch: weiter if-/Fassade in `server.py`; Tabellen-`ROUTES` optional später (Specter/OpenAPI).
- Verbleibend: Laden-Ballast in `app.js` (Kurs/Chat/Sync-UI); optional `build_state` / Header-Vorab / Handler-Feinschnitt; später `main.py` / `analyze.py`.

## Nachtrag 2026-09-23 · Package-Pfad

`server/api/` ist wegen Kollision mit dem Modul `server.py` **nicht** nutzbar. Slice-1-Handler liegen unter **`httpserver/api/`** (Einstieg bleibt `server.py`).

---

## Abschlussmemo 2026-09-23 · Slice 1 + Slice 2

### Kurzfazit

Slice 1 (`server.py` nach Domänen) ist **weitgehend erledigt**: alle extrahierten `api_*`-Handler liegen unter `httpserver/api/`, Domänen-Helfer und Handler-Mixins unter `httpserver/`, `AppState` ist ausgelagert. Nach Sync-/CLI-Extraktion liegt `server.py` bei **~62 KB** (Done-Check ≪ 100 KB weiter erfüllt).

Slice 2 (`web/app.js`) ist **weitgehend erledigt**: Domänen-Views, Einrichtung, Adress-Labels sowie Chrome/Nav/Bootstrap sind ausgelagert. Darauf folgten UI-Schnitte 1–4 (API/State/Mempool-Links/Format) und Server 5–6 (Wallet-Sync, Splash/`main_cli`). `app.js` ~90 KB (Laden-Ballast), `server.py` ~62 KB.

### Messwerte

| Datei | vor Modularisierung (ADR-Entwurf) | Stand Memo |
| --- | ---: | ---: |
| `server.py` | ~389 KB | **~62 KB** |
| `web/app.js` | ~583 KB | **~90 KB** |

### Package-Entscheidung (geschlossen)

Pfad: **`httpserver/`** und **`httpserver/api/`**. Einstieg bleibt `server.py` mit Re-Export-Fassade (`from httpserver… import …`), damit Tests und Late-Imports weiter `from server import …` nutzen können. Symbol-Identität bleibt erhalten (`server.AppState is httpserver.app_state.AppState`).

### Slice 1 · was gelandet ist

**API-Domänen** unter `httpserver/api/`:

| Modul | Domäne |
| --- | --- |
| `jobs.py` | Jobs / Cancel |
| `source.py` | Datenquellen |
| `wallets.py` | Wallets / UTXO-API |
| `trace.py` | Herkunft / Trace |
| `tax.py` | Steuer / Selbstanzeige |
| `auth_session.py` | Login / Session |
| `config_ui.py` | Config / UI |
| `labels_sanctions_exchange.py` | Labels / Sanktionen / Börse |
| `price_llm_lab.py` | Kurs / LLM / Lab |
| `utxos_cache.py` | UTXO-Cache |
| `health.py` | Health |

**Helfer / Surface** unter `httpserver/`:

| Modul | Inhalt |
| --- | --- |
| `wallet_export.py` | Export / Indexer-Warte |
| `empfang.py` | Empfang / Mempool / Fulcrum-Clients |
| `steuer.py` | Steuer-Grundlage / Selbstanzeige-Report |
| `trace_helpers.py` | Trace-Orchestrierungshelfer |
| `handler_auth.py`, `handler_static.py`, `handler_download.py`, `handler_sse.py` | Handler-Mixins |
| `import_payload.py`, `historie_nachzug.py`, `tls_p2p.py` | Import, Historie, TLS/P2P |
| `local_core.py` | Local-bitcoind / Managed-Hints |
| `scramble.py` | Env-Scramble |
| `app_state.py` | `AppState` + Managed-Konstanten |

**Muster:** Bodies im Domänenmodul; `server.py` nur Fassade; gegen Import-Zyklen Late-`from server import …` in den Modulen. Charakterisierungstests nach jedem Schnitt.

### Slice 2 · Stand (Nachzug)

**Views** unter `web/views/`: `steuerjahr.js`, `herkunft.js`, `wallets.js`, `datenquellen.js`, `einstellungen.js`, `sanktionen.js`, `einrichtung.js`, `adress_labels.js`.

**Chrome / Bootstrap:** `web/chrome_nav.js` (Nav, Ansichtswechsel, Job-Leiste), `web/chrome.js` (`ladeConfig`, `start`, Fußzeile, Shell-Listener). Einstieg weiter `web/boot.js` → `start();`.

**Nach Slice 2 + UI 1–4:** Shared-Module `web/api.js`, `state.js`, `format.js`, `mempool_links.js`. **Noch in `web/app.js` (~90 KB):** vor allem Laden-Ballast (Kurs-Pipeline, Chat/LLM, Header-/Wallet-Sync-UI) und restliche Orchestrierung — keine Domänen-View, kein Token/API/Format/Zustand mehr.

### Done-Check Slice 1 (ehrlich)

| Kriterium | Lage |
| --- | --- |
| `server.py` ≪ 100 KB | **ja** (~62 KB) |
| Domänen wallets / source / trace / tax getrennt | **ja** |
| Rückblick: Sparrow-Import vs. Steuerjahr-Trace ohne gemeinsame Handler-Datei | **ja** (API) |
| Kein neues God-File | **ja** (viele mittelgroße Module) |
| Specter/PyInstaller / genannte Tests | Charakterisierungsläufe je Slice grün; kein Full-Suite-Gate in diesem Memo behauptet |
| Abschlussmemo + Merge-Einschätzung | **dieses Kapitel** |

### Merge-Lage (Einschätzung)

- **API:** spürbar besser — typische Features (Wallets vs. Steuer vs. Source vs. Auth) können API-seitig in getrennten Dateien landen.
- **UI:** deutlich besser — Domänen-Views, Shell (Nav/Start) und Shared-Kern (API/State/Format/Mempool-Links) sind eigene Dateien. Rest-Hotspot ~90 KB Laden-Ballast in `app.js`.
- **Server:** Splash/`main_cli`, Wallet-/Electrs-Sync ausgelagert; `server.py` ~62 KB. Rest: `Handler`, `build_state`, eingebetteter Server, Header-Vorab, dünne Fassade.

### Bewusst offen / nächste Schnitte

1. Laden-Ballast in `app.js` häppchenweise (Kurs, Chat/LLM, Sync-UI) — nur mit klarer Grenze.
2. Optional Server: `build_state`, `starte_header_vorab`, weiteren Handler-Feinschnitt.
3. Später laut ADR: `main.py` / `analyze.py` / Adapter-Feinschnitt (Slices 3–5).
4. Arbeitsregeln in `AGENTS.md` nachziehen.


### Nachzug · UI 1–4 + Server 5–6 (2026-09-23)

Je Ziffer ein Commit (lokal, später gepusht):

| # | Commit-Thema | Modul |
| --- | --- | --- |
| 1 | Token/API | `web/api.js` |
| 2 | Zustand | `web/state.js` |
| 3 | Mempool-Verweise | `web/mempool_links.js` |
| 4 | Formatierung | `web/format.js` |
| 5 | Electrs-/Wallet-Sync | `httpserver/wallet_sync.py` |
| 6 | Splash / `main_cli` | `httpserver/splash.py`, `httpserver/main_cli.py` |

`server.py` behält dünnen `if __name__ == "__main__"`-Einstieg und Re-Export-Fassaden.

### Arbeitsregeln (Branch)

- Commits auf `refactor/modular-engine` lokal ok; **Push nur nach explizitem OK**.
- Kein Prod-`.env` / Secrets / Home-Node / Mainnet durch den Bot.
- Refactor-Slices eigene Commits, keine Drive-bys in Feature-PRs.
