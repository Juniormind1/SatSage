# ADR · Modularisierung SatSage

**Status:** akzeptiert · Slice 1+2 weitgehend · **Slice 3 `main.py` erledigt** · **Slice 4 `analyze.py` Plan** · Shared-Kern/CLI-Schnitte 1–6 erledigt  
**Stand:** 2026-09-23 (Slice-4-Plan)  
**Branch-Basis:** `dev-juniormind` @ `6dc7174` (letzter Commit vor Modularisierungs-Refaktorierung)  
**Arbeitsbranch:** `refactor/modular-engine` (lokal ahead; Slice-3 erledigt; Slice-4-Plan; nicht gepusht)  
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
- **Slice 3 = `main.py`:** erledigt (siehe Abschlussmemo).
- **Slice 4 = `analyze.py`:** detaillierter Plan unten (Inventar 2026-09-23); Umsetzung nach Freigabe, Commits je Domäne.

## Offene Punkte (Stand Memo)

- Package-Pfad: **geschlossen** → `httpserver/api/` (HTTP-Handler), Business in `core/`. `server/api/` unbrauchbar (Kollision mit `server.py`).
- `_api`-Dispatch: weiter if-/Fassade in `server.py`; Tabellen-`ROUTES` optional später (Specter/OpenAPI).
- Verbleibend: Laden-Ballast in `app.js` (Kurs/Chat/Sync-UI); optional `build_state` / Header-Vorab / Handler-Feinschnitt; **Slice 3 `main.py` erledigt**; **Slice 4 `analyze.py` Plan** (Umsetzung ausstehend).

## Nachtrag 2026-09-23 · Package-Pfad

`server/api/` ist wegen Kollision mit dem Modul `server.py` **nicht** nutzbar. Slice-1-Handler liegen unter **`httpserver/api/`** (Einstieg bleibt `server.py`).

---


---

## Slice 3 (fest) · `main.py` — Plan 2026-09-23

**Status:** **erledigt / akzeptiert** (2026-09-23) — siehe Abschlussmemo unten  
**Ist (nach Extraktion):** `main.py` ~23 KB — nur `main()` + Re-Export-Fassade (+ `set_chain_network` / `MAX_TRACE_*`).  
**Ist (Inventar vor Slice 3):** `main.py` ~250 KB / ~7487 Zeilen / ~212 Top-Level-Symbole.

### Inventar (Kurz)

**Rollen heute:** Ableitung, UTXO-/Verlauf-Caches, Datenquellen-Aufbau (Fulcrum/Onion/BIP-158/bitcoind), Tip-Sync, Sanktions-Pools, `WalletContext`, plus CLI-`main()`.

**Größte Brocken (Zeilen ≈):**

| Symbol | ~Z. | Domäne |
| --- | ---: | --- |
| `main` | 381 | CLI-Einstieg |
| `sync_xpub_zum_tip` | 280 | Sync |
| `_build_blockchain_fetchers` | 256 | Quellen |
| `_mempool_pending_nach_prune` | 193 | Cache/Mempool |
| `_scan_xpub_utxos` | 178 | Sync/Scan |
| `resolve_sanctions_clearnet_pool` | 134 | Sanktionen |
| `open_env_file_in_editor` | 130 | CLI/Report |
| `_setup_bip158_client` | 129 | Quellen |
| `resolve_wallet_utxos` | 127 | Sync-Fassade |
| … | | ~200 weitere |

**Domänen-Cluster (heuristisch):** Ableitung ~2,0 kZ · Quellen ~1,6 kZ · Cache ~1,3 kZ · misc/Resolve ~1,5 kZ · Sanktionen ~0,3 kZ · CLI `main` ~0,4 kZ.

**Kopplung (wer importiert `main`):**

| Verbraucher | typische Symbole |
| --- | --- |
| `menu.py` | viele Caches/Sync/Resolve |
| `httpserver/*` (`wallet_sync`, `api/wallets`, `app_state`, `empfang`, …) | Cache, Ableitung, `build_wallet_context`, `_setup_blockchain_client`, Fetchers |
| `core/*` (`wallets`, `source`, `utxos`, `tax`, `trace`, …) | Ableitung, Cache-Pfade, Normalize — **Problem:** `core` hängt an Root-`main` |
| Specter-Plugin | `_load_dotenv`, Cache save/load, `build_wallet_context`, Seed-Helfer, `_setup_blockchain_client`, Fetchers, `list_top_wallet_utxos` |
| `analyze.py` / `trace_engine.py` | `WalletContext`, Cache-Dirs |
| Tests | breit (API, Sync, Derivation, BIP-158, Tax, …) |

**Schluss:** Slice 3 muss die **Abhängigkeitsrichtung umdrehen**: `core`/`httpserver`/Specter importieren Engine-Module — nicht länger `main`. `main.py` wird Fassade + dünner CLI-Einstieg (wie `server.py` nach Slice 1).

### Zielbild

- `main.py` bleibt **Einstieg**: `main()` (CLI), Re-Exports für alte `from main import …` / `import main as xq_main`.
- Fachcode wandert nach **`core/`** (bereits Datenschicht; keine parallele `engine/`-Hierarchie ohne Not).
- Kein neues God-File: Domänen ≤ ~80–100 KB, Funktionen weiter teilen wenn > ~80 Zeilen.
- Verhalten 1:1; Specter-/Test-Signaturen nur über Fassade.

### Empfohlene Modulgrenzen

| Modul (Vorschlag) | Inhalt (Beispiele) | Entkoppelt u. a. |
| --- | --- | --- |
| `core/derivation.py` | `derive_addresses`, `derive_address_at_index`, `derive_descriptor_addresses`, `_hdkey_for_xpub`, `_encoders_for_xpub`, `normalize_script_type`, Gap/Max-Adress-Konstanten | Wallet-Import, Multisig, Export, Specter-Seed |
| `core/xpub_cache.py` | `load_`/`save_xpub_utxo_cache`, Verlauf-Cache, Ingress-Cache, Pfad/Key-Helfer (`_xpub_cache_key`, Alter-Pfad), Prune/Verify, `settle_gezielte_spends_im_cache`, Immutable-Dirs | Tip-Sync, Trace, Tax, Specter-Cache |
| `core/chain_sources.py` | `_build_blockchain_fetchers`, `_setup_blockchain_client`, Fulcrum/Electrum/Onion-Rotation, Priority-Chains, BIP-158-Setup, Latenz-Gates | Source-API, Wallet-Watch, Trace-Jobs |
| `core/wallet_sync_engine.py` | `sync_xpub_zum_tip`, `sync_wallets_zum_tip`, `_scan_xpub_utxos`, Tip anheben, light rescan, scantxoutset-Helfer, `resolve_wallet_utxos` / `resolve_wallet_verlauf` | `httpserver/wallet_sync`, Start-Sync, Menu |
| `core/sanctions_pool.py` | `resolve_sanctions_*_pool`, Own-Node-Pool, Clearnet-Probe-Limits | Sanktionscheck-API/Jobs |
| `core/wallet_context.py` | `WalletContext`, `build_wallet_context`, Address-Seed aus Caches (`seed_wallet_addresses_*`, `init_external_address_cache`) | Specter-Session, Trace, Tax |
| `core/env_bootstrap.py` (klein) | `_load_dotenv`, `ENV_FILE`, Editor-Öffnen falls eng an CLI | server/menu/Specter Env-Read |
| `main.py` | `main()` + Re-Export-Fassade aller bisherigen öffentlichen Namen | — |

Namensnotiz: `wallet_sync_engine` bewusst nicht `httpserver/wallet_sync` (HTTP-Orchestrierung bleibt getrennt).

### Extraktions-Reihenfolge (je eigener Commit, lokal bis Abschnitt OK)

1. **`derivation`** — blattnah, stark genutzt, wenig I/O-Orchestrierung.  
2. **`wallet_context`** + Address-Seed — baut auf Ableitung/Caches-Schnittstellen.  
3. **`xpub_cache`** — viele Importe; Fassade sofort.  
4. **`env_bootstrap`** — klein, Specter/server.  
5. **`chain_sources`** — Fetchers/Clients (höheres Risiko, Netz).  
6. **`sanctions_pool`** — abgegrenzt.  
7. **`wallet_sync_engine`** — größte Verhaltensfläche; zuletzt unter den Domänen.  
8. **`main()` glätten** — nur CLI übrig, Imports aus `core.*`.

Zwischen jedem Commit: Characterization-Tests der berührten Domäne + Smoke Specter-Bridge-Imports (`python -c "import main"` / Plugin-Pfad).

### Charakterisierung / Tests (vor/während)

Mindestens: `tests/test_ableitung.py` (o. ä.), `tests/test_start_sync.py`, `tests/test_api.py` (Wallet/Cache), `tests/test_verlauf_*`, `tests/test_bip158_*`, `tests/test_wallet_alter.py`, Tax/Trace-Caches; plus Import-Smoke Specter (`build_wallet_context`, Cache save/load, `_setup_blockchain_client`).

### Done-Check Slice 3

- `main.py` ≪ 100 KB (Orientierung; Ideal: nur CLI + Fassade, eher ≪ 40 KB).  
- Domänen **derivation**, **xpub_cache**, **chain_sources**, **wallet_sync_engine** in getrennten Dateien.  
- **`core` importiert nicht mehr `main`** für diese Domänen (Richtung umgekehrt).  
- Specter-Plugin und `httpserver/wallet_sync` laufen über Fassade oder Direktimport `core.*` ohne Verhaltensbruch.  
- Genannte Tests grün; kein neues God-File > ~100 KB in `core/`.  
- Kurzes Abschlussmemo + Merge-Einschätzung.

### Explizit nicht Slice 3

- `analyze.py` / Trace-Pipeline (Slice 4).  
- Adapter-Feinschnitt `fulcrum.py` / `bip158_scanner.py` (Slice 5) — außer unvermeidbare Import-Umleitungen.  
- Features, neue Sync-Strategien, Cache-Format-Migration.  
- Secrets / `.env`-Inhalte loggen oder ändern.

### Parallel-Dev-Nutzen (Rückblick-Test)

Nach Slice 3 sollten z. B. „Ableitung/Multisig-Fix“ und „Tip-Sync/Cache-Prune“ ohne gemeinsame `main.py`-Datei landen können — analog Sparrow vs. Steuerjahr bei Slice 1.


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
3. Laut ADR: **Slice 3 `main.py` erledigt**; als Nächstes `analyze.py` (Slice 4) / Adapter-Feinschnitt (Slice 5).
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



## Abschlussmemo 2026-09-23 · Slice 3 (`main.py`)

### Kurzfazit

Slice 3 ist **erledigt**: Engine-Domänen und restliche CLI-Helfer liegen unter `core/*`; `main.py` ist dünner CLI-Einstieg (`main()`) plus Re-Export-Fassade (Symbol-Identität für Tests/Specter/Menu). Verhalten 1:1; kein Push, kein Merge auf `dev-juniormind` in diesem Schritt.

### Messwerte

| Datei | vor Slice 3 (ADR-Inventar) | Stand Abschluss |
| --- | ---: | ---: |
| `main.py` | ~250 KB | **~23 KB** |

### Module gelandet (Extraktions-Reihenfolge)

| Modul | Inhalt (kurz) |
| --- | --- |
| `core/derivation.py` | Ableitung / Skripttypen / Deskriptoren |
| `core/wallet_context.py` | `WalletContext`, Address-Seed / External-Cache |
| `core/xpub_cache.py` | UTXO-/Verlauf-/Ingress-Caches, Genesis-Konstanten |
| `core/env_bootstrap.py` | `.env`-Pfad, `_load_dotenv`, Editor |
| `core/chain_sources.py` | Fetchers / Clients / Priority-Chains / BIP-158-Setup |
| `core/sanctions_pool.py` | Sanktions-Pools / Clearnet-Probe |
| `core/wallet_sync_engine.py` | Tip-Sync, Scan, `resolve_wallet_*` |
| `core/env_wallets.py` | XPUB-/Wallet-Env-Parser, Start-Sync-Flags, `UNLESBAR_HINWEIS` |
| `core/receive_address.py` | Gap-Limit / nächste Empfangsadresse (Fulcrum) |
| `core/utxo_report.py` | CLI-UTXO-/Ingress-Berichte, Tx-Output-Helfer |
| `core/launch_checks.py` | `launch_check_fulcrum_tor_external` |

`main.py` behält bewusst: `main()`, Fassade, `set_chain_network` (Caches über mehrere Module + Fulcrum-Header), `MAX_TRACE_DEPTH` / `MAX_TRACE_ADDRESS_SEARCH` (Analyze-/Specter-Façade).

### Done-Check Slice 3 (ehrlich)

| Kriterium | Lage |
| --- | --- |
| `main.py` ≪ 100 KB (Ideal ≪ 40 KB) | **ja** (~23 KB) |
| Domänen derivation / xpub_cache / chain_sources / wallet_sync_engine getrennt | **ja** |
| `core` importiert nicht mehr `main` *für diese Domänen* | **weitgehend ja** — Env-Wallet-/UTXO-Report-Helfer retargetet; Rest siehe unten |
| Specter / `httpserver/wallet_sync` über Fassade oder `core.*` | **ja** (Façade + Direktimports wo retargetet) |
| Kein neues God-File > ~100 KB in `core/` | **ja** (größtes Slice-3-Modul `xpub_cache` ~60 KB) |
| Genannte Tests | Import-Smoke + façade identity; `test_derivation`, `test_config`/`env*`, `test_start_sync`, `test_utxo_ranking`, `test_tx_formats`, `test_wallet_bloecke` grün |
| Abschlussmemo + Merge-Einschätzung | **dieses Kapitel** |

**Verbleibende CLI-Helfer in `main.py`:** nur `set_chain_network`, Trace-Konstanten, `main()` (+ Re-Exports).

**`core` → `main` Leftovers** (Stand `rg`/grep nach Slice 3): u. a. `env_bootstrap` → `set_chain_network`; `trace`/`tx_classify`/`tax`/`wallets`/… noch für Fassaden-Symbole (`_normalize_txid`, …) bzw. Late-Import — **nicht** mehr für die extrahierten Env-/Receive-/UTXO-Report-Domänen. Weitere Entkopplung = Feinschliff, nicht Slice-3-Blocker.

### Merge-Lage

- Lokal: `refactor/modular-engine` ist **Fast-Forward von `dev-juniormind`** (gemeinsamer Tip vor Slice-3-Abschluss-Commits war `c87f8e0`); **nicht gepusht**, **nicht** nach `dev-juniormind` gemerged.
- Parallel-Dev-Nutzen: Ableitung/Multisig vs. Tip-Sync/Cache-Prune können ohne gemeinsame `main.py`-Bodies landen (Done-Check Rückblick-Test erfüllt).

### Explizit nicht erledigt / als Nächstes

- **Slice 4:** `analyze.py` / Trace-Pipeline — Plan unten; Umsetzung ausstehend.
- Adapter-Feinschnitt `fulcrum.py` / `bip158_scanner.py` (Slice 5).
- Optional: weitere `core`→`main`-Late-Imports auf Direktimport `core.*` umbiegen; `set_chain_network` näher an `derivation` nur mit Cache-Clear-Vertrag.

### Arbeitsregeln (Branch)

- Commits auf `refactor/modular-engine` lokal ok; **Push nur nach explizitem OK**.
- Kein Prod-`.env` / Secrets / Home-Node / Mainnet durch den Bot.
- Refactor-Slices eigene Commits, keine Drive-bys in Feature-PRs.


## Slice 4 (fest) · `analyze.py` — Plan 2026-09-23

**Status:** Plan / bereit zur Umsetzung (noch keine Code-Moves)  
**Ist (Inventar 2026-09-23):** `analyze.py` **142 797 B / 4 214 Zeilen / 74 Top-Level-Defs** (73 Funktionen/Klassen + `_main`).  
**Nachbarschaft:** Root-`trace_engine.py` (~15 KB, Walk-Primitives) bleibt; `core/trace.py` (~32 KB) flatten’t den Origin-Baum für die UI und **importiert heute `analyze`** (Zyklus-Risiko).

### Inventar (Kurz)

**Rollen heute:** Fassade + Orchestrierung für Herkunfts-Walk, Vertiefung/Lücken/Steuer-Horizont, Ingress-Persistenz, CLI-Tx/UTXO-Analyse, Sanktions-Hop-Scan und Wallet-/Listen-UTXO-Sanktionsläufe (inkl. Report-`print`s). Interaktive Prompts liegen bewusst in `interact.py` / `menu.py`.

**Größte Brocken (Zeilen ≈):**

| Symbol | ~Z. | Domäne |
| --- | ---: | --- |
| `trace_utxo_origin` | 411 | Origin-Walk |
| `_pruefe_ein_utxo` | 243 | Wallet-Sanktionscheck |
| `vertiefe_herkunft_luecken` | 222 | Vertiefung/Lücken |
| `analyze_tx` | 224 | CLI Tx-Analyse |
| `scan_sanctioned_address_utxos` | 166 | Listen-UTXO-Scan |
| `scan_external_sanction_hops` | 131 | Sanktions-Hops |
| `_events_aus_origin_tree` / `_sammle_sanction_events_live` | 131 / 128 | Sanktions-Events |
| `_trace_sanctioned_outputs_by_entity_parallel` | 119 | Entity-Output-Trace |
| `check_wallet_utxos_sanctions` | 116 | Wallet-Sanktions-Orchestrierung |
| `analyze_address_utxos` / `trace_known_utxos` | 105 / 102 | CLI UTXO-Batch |
| … | | ~60 weitere |

**Domänen-Cluster (heuristisch, Bodies):**

| Cluster | ~Zeilen Bodies | ~KB Chunk | Inhalt |
| --- | ---: | ---: | --- |
| Prelude/Helfer | ~80 | ~3 | Contexts, Parse, Own-Addr, `_EphemeralProgress` |
| Origin-Walk | ~410 | ~15 | `trace_utxo_origin` |
| Vertiefe/Horizont/Lücken | ~400 | ~14 | `vertiefe_*`, `_hat_tax_horizon`, `hat_brauchbaren_teilfortschritt`, … |
| Print/Persist/Followups | ~635 | ~23 | Ingress-Collect, `persist_utxo_ingress`, Followups |
| CLI Tx/UTXO | ~440 | ~14 | `analyze_tx`, `analyze_address_utxos`, `trace_known_utxos` |
| Sanction-Hops | ~250 | ~9 | `scan_external_sanction_hops` |
| Wallet-Sanktionscheck | ~840 | ~29 | `check_wallet_utxos_sanctions` + Live-Walk |
| Listen-UTXO + Entity-Trace | ~970 | ~33 | `scan_sanctioned_address_utxos`, `trace_sanctioned_outputs_*` |

**Kopplung (wer importiert `analyze` / `analyze.*`):**

| Verbraucher | typische Symbole |
| --- | --- |
| `core/trace.py` | `trace_utxo_origin`, `vertiefe_herkunft_luecken`, `hat_brauchbaren_teilfortschritt`, `_hat_tax_horizon`, `_origin_hat_luecken`, `_youngest_*`, `persist_utxo_ingress`, `MAX_TRACE_DEPTH` — **Problem:** `core` hängt am Root-`analyze` |
| `httpserver/trace_helpers.py`, `httpserver/api/trace.py` | Walk/Vertiefe/Teilfortschritt, Followups |
| `httpserver/api/labels_sanctions_exchange.py` | `check_wallet_utxos_sanctions` |
| `interact.py`, Specter `specter_session.py` | `analyze_tx`, `analyze_address_utxos`, `trace_known_utxos`, Contexts, `_parse_utxo_ref` |
| `menu.py` | Sanktionscheck + Listen-UTXO-Scan/Reports |
| `server.py` | `import analyze` (Bindung/Packaging-Sichtbarkeit) |
| `pack_release.py` | Datei in Bundle-Liste |
| Tests | `test_trace*`, `test_sanction_hops`, `test_sanctions_quelle`, `test_jobs`, `test_tx_classify`, `test_exchange_reports` |
| Lab | `verify_sanctions_hops`, Szenario-Generator (Hop-Semantik) |

**Öffentliche / von außen genutzte API (Union):**  
`trace_utxo_origin`, `vertiefe_herkunft_luecken`, `hat_brauchbaren_teilfortschritt`, `persist_utxo_ingress`, `_hat_tax_horizon`, `_origin_hat_luecken`, `_youngest_external_ingress`, `_youngest_tax_horizon`, `_youngest_wallet_ingress`, `_collect_internal_creator_txs`, `_run_tx_oriented_followups`, `analyze_tx`, `analyze_address_utxos`, `trace_known_utxos`, `TxFollowupContext`, `UtxoFollowupContext`, `_parse_utxo_ref`, `scan_external_sanction_hops`, `check_wallet_utxos_sanctions`, `print_sanction_check_report`, `scan_sanctioned_address_utxos`, `print_sanctioned_utxo_findings`, `print_sanctioned_utxo_scan_report`, `MAX_TRACE_DEPTH` (Re-Export aus `trace_engine`).

**Fassade / Zyklen heute:**

- `analyze` → `trace_engine` (Primitives); Late-`_main()` → `main` (Format/Cache/Fulcrum-Helfer); `core.trace_cache` lokal.
- `core.trace` → **`import analyze`** (nicht umgekehrt) — Richtung nach Slice 4 umdrehen: `core.trace` → `core.utxo_origin` (o. ä.), `analyze.py` nur noch Re-Export.
- Kein `analyze` ↔ `core.trace`-Importzyklus *im Code*, aber **logischer Zyklus-Risiko**, sobald Origin-Walk nach `core/` wandert und versehentlich wieder `core.trace` zieht.

**Schluss:** Slice 4 macht `analyze.py` zur **dünnen Fassade + Orchestrierungsrest**; Domänen landen unter **`core/`** (SatSage-Namenskonvention wie Slice 3). Keine parallele `analyze_*`-Hierarchie nötig — optional nur, falls ein Cut klar CLI-only bleibt.

### Zielbild

- `analyze.py` bleibt **Einstieg/Fassade**: Re-Exports aller bisherigen öffentlichen Namen (`from analyze import …` / `import analyze` behalten Symbol-Identität).
- Fachcode → **`core/*`**; `print()`-Reports analog `core/utxo_report.py` (CLI-Helfer) toleriert, nicht in HTTP-Pfade ziehen.
- Kein neues God-File: Domänen ≤ ~80–100 KB.
- Verhalten 1:1; Tests/Specter/Menu/HTTP weiter über Fassade oder gezielten Direktimport `core.*`.
- **Kein Domänen-Zyklus `analyze` ↔ `core`:** Bodies in `core`; Fassade importiert `core`, nicht umgekehrt für extrahierte Domänen.

### Empfohlene Modulgrenzen

| Modul (Vorschlag) | Inhalt (Beispiele) | ~KB Bodies | Entkoppelt u. a. |
| --- | --- | ---: | --- |
| `core/utxo_origin.py` | `trace_utxo_origin`, `vertiefe_tax_horizon`, `vertiefe_herkunft_luecken`, `hat_brauchbaren_teilfortschritt`, `_hat_tax_horizon`, `_origin_hat_luecken`, `_seed_memo_*`, Own-Addr/Parse-Helfer, `_EphemeralProgress` | ~31 | `core/trace`, HTTP-Trace, Tax-Horizont-Tests |
| `core/utxo_ingress_report.py` | Collect/Youngest/Oldest, `persist_utxo_ingress`, Print-Summaries, `_analyze_utxo_funding`, `_collect_internal_creator_txs`, `_run_tx_oriented_followups`, `TxFollowupContext` / `UtxoFollowupContext` | ~24 | Trace-Persistenz, Followups (interact/HTTP/Jobs) |
| `core/tx_utxo_analyze.py` | `analyze_tx`, `analyze_address_utxos`, `trace_known_utxos`, Batch-Progress | ~14 | CLI `interact`, Specter-Session |
| `core/sanction_hops.py` | `scan_external_sanction_hops`, CoinJoin-Merge-Helfer, `SanctionHitFound` | ~9 | Lab-Hop-Semantik, Wallet-Check |
| `core/wallet_sanctions_check.py` | Live-Event-Sammlung, `_pruefe_ein_utxo`, Parallel-Check, `check_wallet_utxos_sanctions`, `print_sanction_check_report` | ~29 | Menu, HTTP Sanktionen, Lab-Verify |
| `core/sanctioned_address_utxos.py` | `scan_sanctioned_address_utxos` (+ parallel/Fulcrum-Sync), Findings-Reports | ~18 | Menu Listen-Scan |
| `core/sanctioned_output_trace.py` | `trace_sanctioned_outputs_since` / `_by_entity`, Entity-Reports | ~15 | Entity-Trace-Reports |
| `analyze.py` | Re-Export-Fassade + ggf. `_main()`-Shim bis Late-Imports auf `core.*`/`main`-Fassade bereinigt | ≪ 20 | — |

Namensnotiz: bewusst **nicht** `core/trace.py` erweitern (das bleibt UI-Flattening). `core/sanctions.py` bleibt Listen-Abgleich Oberfläche — Hop-/Walk-Logik heißt `sanction_hops` / `wallet_sanctions_check`, nicht in denselben Topf.

### Extraktions-Reihenfolge (je eigener Commit, lokal bis Abschnitt OK)

1. **`core/utxo_origin.py`** — Kern-Walk + Vertiefe; Fassade sofort; `core/trace` Ideal: Direktimport (Zyklus vermeiden).  
2. **`core/utxo_ingress_report.py`** — Persist/Collect/Followups (hängt an Origin-Baumform).  
3. **`core/tx_utxo_analyze.py`** — CLI/Specter-Einstiege.  
4. **`core/sanction_hops.py`** — blattnah für Lab/Tests.  
5. **`core/wallet_sanctions_check.py`** — nutzt Hops + Origin.  
6. **`core/sanctioned_address_utxos.py`** — Listen-Scan.  
7. **`core/sanctioned_output_trace.py`** — Entity-Output-Traces.  
8. **`analyze.py` glätten** — nur Fassade/`_main`-Shim; Smoke `import analyze`.

Zwischen jedem Commit: Characterization der berührten Domäne + Import-Smoke (`python -c "import analyze; import core.trace"`).

### Charakterisierung / Tests (vor/während)

Mindestens: `tests/test_trace.py`, `tests/test_trace_resume_luecken.py`, `tests/test_trace_steuer_horizon.py`, `tests/test_sanction_hops.py`, `tests/test_sanctions_quelle.py`, `tests/test_tx_classify.py`, `tests/test_jobs.py` (Followups), `tests/test_exchange_reports.py`; plus Import-Smoke Specter/Menu-Pfade und `httpserver.trace_helpers`.

### Done-Check Slice 4

- `analyze.py` ≪ 40 KB (Ideal: nur Fassade/`_main`-Shim, eher ≪ 20 KB).  
- Domänen **utxo_origin**, **utxo_ingress_report**, **tx_utxo_analyze**, **sanction_hops**, **wallet_sanctions_check** in getrennten Dateien unter `core/`.  
- **Kein Domänen-Zyklus:** extrahierte `core/*`-Module importieren nicht `analyze` für ihre Bodies; `core/trace` nutzt Direktimport `core.utxo_origin` (Fassade optional parallel).  
- Kein neues God-File > ~100 KB in `core/`.  
- Genannte Tests grün; Symbol-Identität der Fassade (`analyze.trace_utxo_origin is core.utxo_origin.trace_utxo_origin`).  
- Kurzes Abschlussmemo + Merge-Einschätzung.

### Merge-Ritual (wie Slice 3)

- Arbeitscommits nur auf `refactor/modular-engine`; **Push nur nach explizitem OK**.  
- Vor jedem Fast-Forward / Merge nach `dev-juniormind`: Playwright-**Web-GUI-Userflow** grün (`scripts/webgui_userflow.py`, siehe `doc/testprotokoll-webgui-userflow.md`).  
- Kein Prod-`.env` / Secrets / Home-Node / Mainnet durch den Bot.

### Explizit nicht Slice 4

- Weitere Schnitte an `main.py` / Adapter `fulcrum.py` / `bip158_scanner.py` (Slice 5).  
- Umbau `trace_engine.py` oder Merge mit `core/trace.py` (Flattening).  
- Neue Trace-/Sanktions-Features, Semantik-Änderungen, Cache-Format-Migration.  
- Entfernen der `analyze`-Fassade (Kompatibilität bleibt).  
- Secrets / `.env`-Inhalte loggen oder ändern.

### Parallel-Dev-Nutzen (Rückblick-Test)

Nach Slice 4 sollten z. B. „Herkunft-Lücken/Steuer-Horizont“ und „Wallet-Sanktions-Hop-Check“ ohne gemeinsame `analyze.py`-Bodies landen können — und Listen-UTXO-Scan parallel zu Entity-Output-Trace.
