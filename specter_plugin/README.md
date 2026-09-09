# SatSage ↔ Specter Desktop (Testumgebung)

SatSage als **Specter-Plugin**. Phase A ist umgesetzt: Specter läuft, Plugin liest den **Config-Kontext** (Node, XPUBs, UTXOs/Txs) und optional die **Specter REST-API**. Die eigentliche Analyse aus `main.py` / `analyze.py` kommt danach.

SatSage rekonstruiert aus der Blockchain, wann Sats diese Wallet-Adressen erreicht oder verlassen haben. Das ist ein On-Chain-Beleg, kein vollständiger Anschaffungsnachweis. Börsenhistorien, Kaufbelege, Kontoauszüge und ähnliche Unterlagen ersetzt das nicht — es kann sie nur ergänzen. Ob ein Stichtag oder eine Haltefrist greift, prüft nicht dieses Programm.

Offizielle Extension-Doku: [Specter Extensions Intro](https://github.com/cryptoadvance/specter-desktop/blob/master/docs/extensions/intro.md) · [API](https://github.com/cryptoadvance/specter-desktop/blob/master/docs/api/README.md)

## Architektur

```
Specter Desktop (Flask)
 ├── app.specter.node          → Bitcoin Core RPC / Spectrum / Electrum
 ├── app.specter.wallet_manager → Wallets, Keys/XPUBs, UTXOs, Txs
 └── Extension satsage
      ├── bridge.py      # in-process: Specter → SatSageContext
      ├── gui_server.py  # startet server.py im Hintergrund (Daemon-Thread)
      ├── controller.py  # /svc/satsage/ — iframe „Oberfläche“ + Legacy-Tabs
      └── specter_session.py  # Analyse-Backend (Plaintext-Fallback)
```

**Oberfläche:** Unter `/svc/satsage/gui` läuft dieselbe Web-GUI wie `py server.py`
(iframe auf `http://127.0.0.1:<port>/?t=…`). Specter-Wallets werden in
`specter_plugin/.specter_dev/satsage.env` gespiegelt (nicht die Repo-`.env`).
Falls der Browser das iframe blockiert: Link „In neuem Tab öffnen“.

| Quelle | Was SatSage braucht | Wie geholt |
|--------|----------------------|------------|
| Specter-Wallets | XPUBs, Namen | `wallet.keys` / Deskriptoren via `bridge.py` |
| Aktiver Node | Host, Port, RPC-Auth, Chain | `app.specter.node` → `NETWORK`; Core → `BIP158_P2P=1` + RPC, Electrum/Spectrum → `FULCRUM_HOST`/`PORT`/`SSL` |
| Wallet-Objekte | UTXOs, Tx-Liste | `wallet.full_utxo` / `txlist` (in-process) |
| REST API | dasselbe remote | `/api/v1alpha/specter`, `/api/v1alpha/wallets/<alias>` |

**Managed-GUI:** `GET /api/config` meldet `managed_by=specter`; Wallets und Datenquelle sind in der GUI schreibgeschützt/ausgeblendet. Mempool bleibt unter Einstellungen editierbar; Steuer, LLM, Mail und Sprache bleiben lokal änderbar.

**Cache-Seed:** Beim GUI-Start schreibt `specter_seed.py` Specter-`full_utxo` in den UTXO-Cache, merged Receive-Historie in den Verlaufs-Cache, übernimmt Adress-Labels (`specter_address_labels.json`) und setzt `max_addresses` / `scan_end_index` aus Specters Adressindizes.

**Privatsphäre:** Im Plugin laufen Abfragen **in-process** über Specters Node — kein Extra-Leak an öffentliche Esplora/Fulcrum-Server, solange Specter selbst auf deinen Node zeigt.

## Schnellstart (macOS)

```bash
cd specter_plugin
chmod +x scripts/*.sh
./scripts/setup_dev.sh

# Optional: Regtest-Node
./scripts/run_bitcoind_regtest.sh

# Specter + Plugin
./scripts/run_specter.sh
```

Browser: **http://127.0.0.1:25441**

1. Node verbinden (Regtest: `localhost:18443`, User `bitcoin`, Pass `secret`)
2. Device + Watch-Only-Wallet mit XPUB anlegen (oder Hot-Wallet im Regtest)
3. **Plugins → SatSage** aktivieren
4. Sidebar → **SatSage** → **Oberfläche** (volle Web-GUI per iframe; mind. 640px hoch, damit Log und Assistent unten Platz haben)
5. Optional: Übersicht / Wallets / klassische Analyse / `context.json`
6. API-Probe: `./.venv/bin/python scripts/probe_api.py`

Offline-Check der Bridge:

```bash
./.venv/bin/python scripts/unit_bridge.py
```

## Verzeichnis

```
specter_plugin/
├── docker-compose.regtest.yml
├── pyproject.toml
├── README.md
├── scripts/
│   ├── setup_dev.sh
│   ├── run_specter.sh
│   ├── run_bitcoind_regtest.sh
│   ├── probe_api.py
│   └── unit_bridge.py
└── src/satsage/specterext/satsage/
    ├── app_config.py   # DevConfig / ProdLikeConfig
    ├── bridge.py       # Specter → SatSageContext
    ├── gui_server.py   # eingebettete Web-GUI (server.py)
    ├── controller.py
    ├── specter_session.py
    ├── service.py
    ├── config.py
    ├── static/…
    └── templates/…
```

Daten der Testinstanz liegen unter `specter_plugin/.specter_dev/` (gitignore).

## Plugin aktivieren

- **Development (`DevConfig`):** Extension ist in `EXTENSION_LIST`, `devstatus=alpha`, API an.
- UI: „Choose plugins“ / Plugins → **SatSage**.
- URL-Prefix (Specter-Default): `/svc/satsage/`

## REST-API (optional)

In Dev standardmäßig aktiv (`SPECTER_API_ACTIVE=True`).

```bash
# Token (BasicAuth)
curl -u admin:admin -X POST http://127.0.0.1:25441/api/v1alpha/token \
  -H 'Content-Type: application/json' \
  -d '{"jwt_token_description":"satsage","jwt_token_life":"1 days"}'

# Instanz + Wallets
curl -H "Authorization: Bearer <JWT>" http://127.0.0.1:25441/api/v1alpha/specter
curl -H "Authorization: Bearer <JWT>" http://127.0.0.1:25441/api/v1alpha/wallets/<alias>
```

## Analyse-Integration (Phase 2)

Modul `specter_session.py`:

1. Liest XPUBs/Node aus Specter (`bridge.py`)
2. Merged mit SatSage-`.env` (Specter-Node überschreibt)
3. Startet Backend (BIP-158/Core bevorzugt)
4. Seedet Adress-Mapping + UTXO-Cache aus Specter
5. Ruft `analyze.analyze_tx` / `analyze_address_utxos` / `list_top_wallet_utxos` / `trace_known_utxos` auf
6. Fängt stdout und zeigt es unter **Analyse** in der UI

UI: `/svc/satsage/analyze` — Tx-Trace, UTXO-Trace, Rangfolge, Top-N-Trace.

Optional später: JWT-CLI (`--specter-url`), reichere HTML-Reports statt Plaintext.

## Hinweise

- **Nicht** `main.py` für die Plugin-Runtime starten — Specter hostet die Extension.
- Secrets/XPUBs nicht committen; `.specter_dev/`, `.venv/`, `.run/` sind lokal.
- Python: Specter historisch 3.9/3.10; 3.11/3.12 oft ok, bei Installationsfehlern 3.10-venv nutzen.
- Production-Binaries laden fremde Extensions **nicht** aus CWD; nur per `EXTENSION_LIST` + installiertem Package (siehe `ProdLikeConfig`).

Ausführlicher Testplan (Übernahme Wallets/Verbindungen, ausgeblendete Settings): [`../doc/testplan-specter-plugin.md`](../doc/testplan-specter-plugin.md).

Für ein portables Docker-Regtest-Labor mit Szenarien siehe [`../lab/regtest/README.md`](../lab/regtest/README.md).
