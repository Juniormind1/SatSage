# AGENTS.md — Specter Desktop Plugin

**Pfad:** `specter_plugin/` — editierbares Package `satsage.specterext.satsage`  
**Nutzer-Doku:** `specter_plugin/README.md` und Abschnitt in `README.md`  
**Nicht** `main.py` als CLI in der Plugin-Runtime starten — Specter hostet die Extension (Flask).

Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

## Zweck

Specter liefert **Wallets/XPUBs**, den **aktiven Node** und **UTXOs/Txs** in-process. Die Extension baut daraus denselben Analyse-Stack wie die CLI (`WalletContext`, BIP-158/Fetchers, `analyze_*`) und zeigt die Ausgabe im Browser.

## Modul-Übersicht

| Datei (unter `src/satsage/specterext/satsage/`) | Verantwortung |
|----------------------------------------------------|---------------|
| `service.py` | Extension-Metadaten (`id=satsage`, `devstatus=alpha`, Blueprint) |
| `bridge.py` | `build_context(specter)` → `SatSageContext` (Wallets, Keys/XPUBs; kein Core-RPC mehr) |
| `specter_session.py` | Session-Lifecycle: Path zu Repo-Root, `build_wallet_context`, Seed aus Specter, `_setup_blockchain_client` / `_build_blockchain_fetchers`, `run_analyze_*` |
| `controller.py` | Flask-Routes: `/`, `/wallets`, `/wallet/<alias>`, `/analyze`, `/context.json`, `/reload` |
| `config.py` | Extension-Keys `SATSAGE_SHOW_SENSITIVE`, `SATSAGE_PREVIEW_LIMIT` (nicht in Server-Config duplizieren) |
| `app_config.py` | `DevConfig` / `ProdLikeConfig`: `EXTENSION_LIST`, API an, `SERVICES_LOAD_FROM_CWD=False` |
| `templates/satsage/*.jinja` | UI (Übersicht, Wallets, Analyse-Formulare, Ergebnis-Plaintext) |

## Anbindung an SatSage-Core (`main.py` / `analyze.py`)

`specter_session.py` setzt `sys.path` auf das **Repo-Root** (`parents[5]` von der Session-Datei) und importiert:

- `main._load_dotenv`, `build_wallet_context`, `seed_wallet_addresses_*`, `init_external_address_cache`
- `main._setup_blockchain_client`, `_build_blockchain_fetchers`, `privacy_notice_for_source`
- `main.save_xpub_utxo_cache`, `list_top_wallet_utxos`
- `analyze.analyze_tx`, `analyze_address_utxos`, `trace_known_utxos`

Ablauf Session-Setup:

1. `bridge.build_context` → XPUBs + Node
2. `_merged_env`: Repo-`.env` als Basis, Specter-`env_like` überschreibt; bei Core-Node `BITCOIN_BIP158=1`
3. `build_wallet_context` + Seed Adressen/UTXOs aus Specter + UTXO-/Resolution-Cache
4. Blockchain-Client (Auto: eigener Electrum-Server, sonst P2P-BIP-158)
5. Specter-UTXOs → `save_xpub_utxo_cache` (Light-Seed, kein Full-Rescan)
6. Cache unter Repo-Root: `utxo_cache/`, `immutable_cache/`

Session ist **gecacht** (`context_fingerprint` aus Node+Wallets); UTXOs werden bei Reuse frisch aus Specter geholt. Force: Route `/reload`.

## UI-Routen

| Route | Funktion |
|-------|----------|
| `/svc/satsage/gui` | Volle Web-GUI (`server.py`+`web/`) per iframe; Specter-Wallets via `gui_server.py` |
| `/svc/satsage/` | Übersicht + Session-Info |
| `/svc/satsage/wallets` | Wallet-Liste |
| `/svc/satsage/wallet/<alias>` | Detail (UTXO/Tx-Preview) |
| `/svc/satsage/analyze` | Formulare: `mode=tx\|utxo\|rank\|trace_top` (Legacy-Plaintext) |
| `/svc/satsage/context.json` | JSON-Export des Bridge-Kontexts |
| `/svc/satsage/reload` | Session neu aufbauen |

Analyse-Ausgabe: stdout von `analyze_*` wird per `capture_output` abgefangen und als Text in `analyze_result.jinja` gerendert (kein interaktives Menü).

## Dev-Start

```bash
cd specter_plugin
./scripts/setup_dev.sh          # venv, cryptoadvance.specter, pip install -e .
./scripts/run_bitcoind_regtest.sh   # optional
./scripts/run_specter.sh        # http://127.0.0.1:25441
```

Scripts: `unit_bridge.py` (offline), `probe_api.py` (REST JWT). Daten: `specter_plugin/.specter_dev/` (gitignore).

## Konventionen Plugin

- **Sprache:** UI-Texte Deutsch (wie CLI)
- **Keine Secrets** in Templates/Logs; `to_dict(include_secrets=…)` default maskiert
- `SERVICES_LOAD_FROM_CWD=False` + Extension nur über `EXTENSION_LIST` — sonst doppelte Blueprint-Registrierung
- Extension-Config-Keys **nur** in `config.py`, nicht in `app_config.DevConfig` (Specter verbietet Override bestehender Keys)
- Core-Änderungen an Analyse/Fetchers in `main.py`/`analyze.py` — Plugin nur Adapter; bei API-Break der `main._*`-Internals Session anpassen
- **Nicht** automatisiert committen; `.specter_dev/`, `.venv/`, `.run/` lokal
- Bridge (`bridge.py`) für neuen Specter-Kontext; Session (`specter_session.py`) für Runtime; UI in `controller.py` + Jinja; Core-API stabil halten (`build_wallet_context`, `_setup_blockchain_client`, `analyze_*`)
