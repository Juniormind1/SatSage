# AGENTS.md — `core/` und Root-Fassaden

Gilt für alles unter `core/` **und** für die Root-Fassaden, die denselben Stoff halten:

`../main.py`, `../analyze.py`, `../trace_engine.py`, `../menu.py`, `../interact.py`, `../display.py`, `../sanctioned.py`, `../consolidate.py`, `../fulcrum.py`, `../bip158_scanner.py`, `../outbound_policy.py`, `../check_fulcrum_tor.py`.

`../server.py` bleibt Bind, Sitzung, Static, dünner Dispatch und Re-Export — HTTP-Regeln in [`../httpserver/AGENTS.md`](../httpserver/AGENTS.md).

Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

Wissen nur aus Mainchain-Traces der xpubs und Fremdwallet-Exporten. Caches sparen Electrs-Abfragen. Eine eigene Buchhaltung (Extremfall: Losregister) verletzt [`../doc/user-profile-ux.md`](../doc/user-profile-ux.md) — das sagen, bevor es gebaut wird.

## Einstieg

- **Hauptprogramm:** `main.py`
- **Web-Oberfläche:** `server.py` (localhost `127.0.0.1:8730`, Sitzungs-Token) — UI in `web/`; Terminal-Steuerung in `core/terminal_steuerung.py` (Browser darf zu; Job-Log wird gespiegelt)
- **Standardmodus (CLI):** interaktives Menü (ohne `--txid`, `--address`, `--cli`) — **Legacy/Fallback**; empfohlen ist `server.py` (Web)
- **Direktmodi:** `--txid`, `--address`, `--cli` (Einmal-Analysen, weiterhin sinnvoll)
- **Konfiguration:** `.env` (Vorlage: `.env.example`) — niemals Secrets, XPUBs oder persönliche Wallet-Namen committen

Wallets stehen in `.env` als Block je Wallet (`WALLET_0_NAME`, `WALLET_0_XPUB`, `WALLET_0_SCRIPT`, `WALLET_0_MAX_ADDRESSES`), fortlaufend ab 0 und ohne Lücke; Multisig über `WALLET_n_DESC` (Output-Deskriptor, kanonische Form — deckt wsh/sh-wsh, Taproot `multi_a` und Miniscript-Policies ab; abgeleitet wird über `embit.descriptor`). `WALLET_n_M` + `WALLET_n_XPUBS` bleibt als Eingabe-Kurzform und wird beim Schreiben in einen Deskriptor übersetzt. Einzige Quelle ist `core.config.read_wallets` — die alten Schreibweisen (`XPUBS`, `XPUB_0` …) werden nur noch gelesen. Ohne CLI-Angabe und ohne `WALLET_NAMES` nutzt `main.py` einen **SHA256-Hex** des XPUB als Anzeigename.

```bash
py server.py
py main.py
py main.py --xpubs zpub6... --wallet-names "Mein Wallet"
py main.py --bip158 --cli --xpubs zpub6...
py main.py --txid <txid> --xpubs zpub6...
```

## Architektur

| Modul | Verantwortung |
|-------|---------------|
| `main.py` | CLI, `.env`-Laden (`_xpubs_from_env`, `_wallet_names_from_env`), Datenquellenwahl (inkl. Auto-Priorität), Caches, `WalletContext`, Adressableitung, Adress-Auflösungs-Cache, Sanktions-Clearnet-Pool |
| `server.py` | Web-GUI (stdlib HTTP, nur 127.0.0.1), API, Hintergrund-Jobs |
| `web/` | Oberfläche (`app.js`, `index.html`, `style.css`) |
| `menu.py` | Interaktives Hauptmenü (**Legacy/Fallback**), Einstellungen, Session-State, Sanktionsmenü |
| `interact.py` | Prompts (`j/N`), Analyse-Orchestrierung, Top-UTXO-Auswahl |
| `analyze.py` | Tx/UTXO-Herkunftsanalyse, Trace, Sanktions-UTXO-Checks (ohne interaktive Prompts) |
| `trace_engine.py` | Fassade. Der Rückwärts-Walk liegt in `core/trace.py` |
| `display.py` | `format_sats`, Verbose-Modus, `cancellable_output` (q-Abbruch langer Listen) |
| `sanctioned.py` | Multi-Source-Sanktionslisten, Cache, Überblick, Online-Aktualitätsprüfung |
| `bip158_scanner.py` | BIP-158 über Bitcoin-P2P (Compact Filter, TurboSync); Matcher `_CoreBasicFilterMatcher` |
| `core/p2p.py` | Bitcoin-P2P: Handshake, Header, `cfilter`, Block-Download |
| `fulcrum.py` | Fulcrum/Electrum-Protokoll, Onion-Rotation |
| `core/jobs.py` | Hintergrund-Vorgänge (Scan, Verlauf, Herkunft) mit Log und Abbruch |
| `core/tax.py` | Haltefrist, Stichtag, Steuerjahr-Auswertung |
| `core/llm_anbindung.py` / `llm_client.py` / `llm_context.py` | Assistent: Einstufung, Chat-Loop (Loopback/LAN; Remote nur Opt-in), Cache-Reader. Kein Job-Start. Key nie im Status. |
| `core/tor.py` | SOCKS erkennen, lokales `tor` ohne Browser-Fenster starten |
| `consolidate.py` | Dust-Konsolidierung, PSBT-Erzeugung |
| `check_fulcrum_tor.py` | Fulcrum/Tor-Verbindungstest, Vorschläge für `.env`, `electrum_servers.json` |
| `specter_plugin/` | Specter-Desktop-Extension: Bridge + Session + Flask-UI — Regeln in [`../specter_plugin/AGENTS.md`](../specter_plugin/AGENTS.md) |

### Datenquellen (Privatsphäre absteigend)

**Automatische Priorität** (Default beim Start, wenn weder CLI noch manuelle Menüwahl) — allgemeine Datenquelle:

1. **Eigener Electrum-Server** (`FULCRUM_HOST` / `FULCRUM_TOR`, electrs/Fulcrum) — Privatsphäre **hoch**
2. **Bitcoin-P2P Compact Filter** — `--bip158` (kein Core-RPC)
3. **Clearnet-Fulcrum** — öffentliche Server ohne Tor (`electrum_servers.json`), nur nach Bestätigung
4. **Öffentliche Fulcrum-Onions** — `FULCRUM_TOR_0`…`9`, nur nach Bestätigung und nur wenn Clearnet nicht erreichbar (dann Tor; bei Clearnet-Treffer wird öffentliches Onion/Tor-Autostart gelöst)

**UTXO-Bestand** (zusätzlich, in `_utxo_scan_scantxoutset_vorrang` / `_try_scantxoutset_xpub`):

1. Electrs/Fulcrum **im LAN** (Gap-Scan) — typisch am schnellsten
2. Core `scantxoutset` — bevorzugt `UTXO_RPC_*` (lokaler Node), sonst Lookup-`NODE_IP` (z. B. Start9)
3. Electrs **Onion**
4. BIP-158
5. öffentliche Electrum (schlechtere Privatsphäre)

Mit Electrs-LAN entfällt `scantxoutset`. Ohne LAN-Electrs: lokaler pruned Node (`UTXO_RPC_*`) vor remote Lookup-Core.

**Tx/Block-Lookup** (Herkunft ohne Electrs bzw. Electrs-Ausnahme):

1. Lokaler Core (`UTXO_RPC_*`), solange Höhe > `pruneheight` (sonst Block weg)
2. Lookup-Core (`NODE_IP`, archival / Start9)
3. P2P `getdata` / Block bei bekannter Höhe

Mit Electrs bleibt Electrs primär für `get_tx`; Core nur wenn Electrs die Tx nicht liefert.

**Verlaufsscan** (`_try_verlauf_priority_chain` / `_setup_verlauf_client`) — eigene Kette, Core liefert keinen Verlauf:

1. Electrs/Fulcrum **LAN** (`get_history`)
2. Electrs/Fulcrum **Onion**
3. BIP-158 Compact Filter (Blockwalk/Cache)
4. öffentliche Electrum (nach Bestätigung)

Öffentliche Electrum-Server erst nach User-Bestätigung: Web-Dialog, `--oeffentliche-electrum` oder `OEFFENTLICHE_ELECTRUM=1` in `.env`. Sanktions-Scans bleiben Clearnet (Listen-Adressen, nicht Wallet-XPUBs).

Explizit nur per **CLI** (`--bip158`, `--rpc-only`) oder **Einstellungen → Datenquelle wählen**. `BIP158_P2P=1` in `.env` allein erzwingt **keine** Datenquelle — die Auto-Priorität bleibt aktiv.

Einzelmodi:

- **Bitcoin-P2P Compact Filter** — Peers mit `NODE_COMPACT_FILTERS` (`peerblockfilters=1`)
  - Filter lokal matchen, Block nur bei Treffer
  - TurboSync: ungenutzte Keys nur im jüngsten Fenster (`TURBO_WINDOW`), Historie nur already-used
  - Peer-Reihenfolge: Host im LAN (`FULCRUM_HOST`, P2P-Port 8333), dann gemerkte Filter-Peers, dann `BIP158_PEERS`, dann DNS-Seeds mit `x40.` (NODE_COMPACT_FILTERS). Ohne Compact Filter am eigenen Node kein Sprung zu öffentlichen Electrum-Servern. LAN-IPs nicht über Tor. Vor dem DNS-Rundlauf: drei parallele TCP-Prüfungen auf 8333; lauter Timeouts = Firewall, Clearnet entfällt. Scheitert Clearnet, folgt Tor: laufender Browser (9150) oder Autostart des `tor`-Binary (`stelle_tor_socks_bereit`, wie beim eigenen Onion-Node).
  - Scan: bis zu 4 Peers parallel für `getcfilters` / Trefferblöcke; Header-Sync auf Peer 0; UTXO-Stand in Höhenreihenfolge
  - `server.py` startet `starte_header_vorab`: Header ab SegWit in `p2p_headers.bin`, Job `headers` für das Log
  - Mitgeliefertes Archiv `data/p2p_headers_segwit.bin.gz` wird ausgelegt, wenn der lokale Cache fehlt oder hinter dem Archiv-Tip liegt; P2P holt nur den Rest bis zum Tip
  - Matcher: `_CoreBasicFilterMatcher` (nicht `chiabip158`)
  - UTXO-Scan schreibt den Verlaufs-Cache mit (Empfang/Ausgabe aus dem Blockwalk); Merge, kein Überschreiben durch Turbo-Pässe
- **Fulcrum** — `--rpc-only` oder Auto-Kette; eigener Node vs. öffentliche Rotation (`FULCRUM_TOR_0`…`9`) nur nach Bestätigung

**Sanktions-Scans** (Wallet-Check, UTXO-Scan auf Listen-Adressen): immer **Clearnet-Fulcrum** über `build_sanctions_fulcrum_fetchers()` / `resolve_sanctions_clearnet_pool()` — unabhängig von der Wallet-Datenquelle. Optional `FULCRUM_SANCTIONS_HOST` in `.env`, sonst paralleler Probe aus `electrum_servers.json`.

### Caches

| Verzeichnis | Art | Inhalt |
|-------------|-----|--------|
| `utxo_cache/` | veränderlich | UTXOs pro XPUB, `scan_end_index`, `scanned_addresses`, `external_addresses.json` |
| `utxo_cache/{hash}_alter.json` | First-seen | Wallet-Alter; überlebt Danger-Zone-/Cache-Löschen |
| `immutable_cache/` | unveränderlich | `tx/`, `block_header/`, `utxo_ingress/` |
| `sanctioned_cache/` | veränderlich | OFAC/OpenSanctions/Scam-Adressen, Entitäten, Metadaten |

Caches sind Flatfile-JSON. Beim UTXO-Cache: optional Salden-Check, Light-/Full-Rescan. Die Altersdatei nicht mit dem UTXO-Bestand löschen.

**Adress-Auflösungs-Cache** (`external_addresses.json` in `--cache-dir`): globale externe Adressen, XPUB-Negative und verifizierte Wallet-Treffer; invalidiert bei anderem XPUB-Set oder kleinerem `max_index`. Verwaltung in `main.py` (`init_external_address_cache`, `WalletContext.resolve_address`).

**Plattenplatz:** `cache_disk_write_allowed()` stoppt Cache-Schreibvorgänge nur, wenn **unter 5 % frei und unter 2 GiB** frei (`MIN_FREE_DISK_RATIO` + `MIN_FREE_DISK_BYTES`). `save_xpub_utxo_cache` wirft dann `CacheDiskFullError` statt still nichts zu schreiben.

**Sanktions-Cache** (`sanctioned.py`): `sanctioned_addresses_XBT.json`, `sanctioned_entities_XBT.json`, `sanctioned_address_index.json`, `.meta.json`, optional `sdn_advanced.xml`. Quellen: OFAC 0xB10C, OFAC SDN-XML, OpenSanctions (Israel NBCTF, FBI Lazarus, ransomwhe.re), Badd-Boyz. Israel NBCTF als eine zusammengefasste Entität (`group_mode: collapsed`).

### Adressableitung

Pro XPUB ab Index #0 (Receive + Change), abhängig vom SLIP-132-Präfix:

- `zpub` / `vpub` → Native SegWit (BIP84)
- `xpub` / `tpub` → Legacy + Taproot
- `ypub` / `upub` → Nested SegWit

Bibliothek: `embit` (`HDKey`, `script`). Pro XPUB individuelles Scan-Limit über `--max-addresses-per-xpub`.

## Konfiguration (`.env`)

Wichtige Variablen:

```env
WALLET_0_XPUB=zpub6...               # ein Block je Wallet, fortlaufend ab 0
WALLET_NAMES=Wallet A|Wallet B       # pipe-getrennt; oder WALLET_NAME_0 …

# BIP158_P2P=1                 # Compact Filter über P2P (kein Core)
# BIP158_START_HEIGHT=481824   # SegWit
# BIP158_PEERS=                # optional host:port je Zeile

FULCRUM_HOST=...
FULCRUM_TOR=....onion
FULCRUM_PORT=50002
FULCRUM_SSL=true
FULCRUM_TOR_PROXY=127.0.0.1:9150   # nur für .onion-Verbindungen

FULCRUM_TOR_0=....onion      # öffentliche Server-Rotation (max. 10)
# OEFFENTLICHE_ELECTRUM=1    # öffentliche Electrum-Server erlauben
FULCRUM_SANCTIONS_HOST=...   # optional; sonst electrum_servers.json
# VERBOSE=1                                # volle TxIDs/Adressen (Default: aus)
# WALLETS_IMMER_AKTUELL=1                 # Dauer-Watch (Electrs-Subscribe) + Tip-Nachzug beim Start
# WALLETS_BEIM_START_AKTUALISIEREN=1     # Legacy-Alias für WALLETS_IMMER_AKTUELL
# WALLETS_NUR_BEKANNTE_UTXOS=1           # Tip-Nachzug nur bekannte UTXOs (kein Gap; neue Adressen → UTXO-Scan)
# STEUER_HALTEFRIST_JAHRE=1                # Vorgabe 1 (DE); 0 = keine Frist
# STEUER_STICHTAG=                         # leer = Frist für alle Anschaffungen
```

**Tor-Proxy-Regel:** `FULCRUM_TOR_PROXY` gilt nur für `.onion`-Hosts (RPC und Fulcrum). Bei LAN-IPs (`192.168.x.x`) wird direkt verbunden. Fehlt ein laufender SOCKS, startet `core.tor.stelle_tor_socks_bereit` ein gefundenes `tor`-Binary (Tor-Browser-Ordner oder `TOR_BINARY`) ohne Browser-UI. `TOR_AUTOSTART=0` unterbindet das.

## Modulgrenzen

Hintergrund: [`../doc/adr-modularisierung.md`](../doc/adr-modularisierung.md). Slice 1–5 sind geschnitten; diese Regeln gelten für neue Arbeit.

**Wohin neue Logik kommt**

- HTTP-Handler nach `httpserver/api/<domäne>.py` oder in den passenden Helfer unter `httpserver/`. `server.py` bleibt Bind, Sitzung, Static, dünner Dispatch und Re-Export.
- Oberfläche nach `web/views/<domäne>.js` oder in die bestehende View. `web/app.js` nur anfassen, solange der Rest-Ballast (Kurs, Chat, Sync) noch dort liegt.
- Fachlogik nach `core/<domäne>.py`. `main.py` und `analyze.py` bleiben Einstieg plus Re-Export-Fassade.
- Fulcrum, BIP158, Electrum-Liste und Outbound-Policy in den bestehenden `core/fulcrum_*`, `core/bip158_*`, `core/electrum_servers.py`, `core/outbound_policy.py`. Die Root-Dateien `fulcrum.py`, `bip158_scanner.py`, `outbound_policy.py` und `check_fulcrum_tor.py` bleiben Fassade bzw. Diagnose-CLI.

**Imports**

- Neuer Code in `core/` und `httpserver/` importiert `core.*` direkt. Root-Fassaden bleiben für Tests, Specter und Packaging. Eine Fassade in einem Feature-Commit nicht löschen.
- `core` importiert für Fachcode nicht `main`, `server`, `analyze`, `fulcrum`, `bip158_scanner`, `outbound_policy` oder `check_fulcrum_tor`. Brauchen sich zwei `core`-Module gegenseitig, liegt der gemeinsame Zustand im unteren Modul, der Aufruf darüber als später Import in der Funktion.

**Größe**

- Eine Datei über etwa 80–100 KB ist ein Split nach Domäne, kein Umzug in eine neue große Datei.
- Eine Funktion über etwa 80 Zeilen ist ein Split-Kandidat nur in dem Change, der sie ohnehin anfasst. Kein Aufräumen langer Funktionen nebenbei.

**Refactor und Feature**

- Weiteres Entkernen (`app.js`-Ballast, Fassaden entfernen) ist eine eigene Aufgabe mit eigenem Commit. Ein Feature landet in der bestehenden Domänendatei und schneidet Nachbarmodule nicht mit um.
- Wenn ein Symbol das Modul wechselt, zeigen Tests auf das Modul, in dem der Name nachgeschlagen wird. Die Fassade behält die Symbol-Identität (`fulcrum.X is core.fulcrum_*.X`).

## Typische Aufgaben (Engine)

- **Neue Analyse-Funktion:** Logik in `core/` (z. B. `tx_utxo_analyze`, `utxo_origin`), Prompts in `interact.py`, Menüpunkt in `menu.py`; Web: Route in `httpserver/api/` + View in `web/views/`; `analyze.py` und `server.py` nur Fassade/Dispatch. Im Plugin optional `specter_session.run_*` + Route/Template in `controller.py`
- **Neues Backend:** Fetcher in Backend-Modul, Anbindung in `core.chain_sources` (`_setup_blockchain_client` / `_build_blockchain_fetchers`, über die `main`-Fassade erreichbar)
- **BIP-158:** P2P in `core/p2p.py`, Scan in `core/bip158_scan.py`, Wallet-API in `core/bip158_wallet.py`; `bip158_scanner.py` bleibt Fassade. Kein Core-RPC. Turbo-Pässe in `plane_filter_passes`
- **Steuerjahr:** `core/tax.py`; Einstellungen `STEUER_HALTEFRIST_JAHRE` / `STEUER_STICHTAG`; Web-Ansicht in `web/views/`
- **Fulcrum/Tor:** Fachcode in `core/fulcrum_*` und `core/electrum_servers.py`; `fulcrum.py` und `check_fulcrum_tor.py` bleiben Fassade bzw. Diagnose-CLI. `.env`-Variablen, `electrum_servers.json`
- **Adress-Auflösung:** `WalletContext`, `external_addresses.json` in `main.py`
- **Sanktionslisten:** `sanctioned.py` (Quellen, Parser, `update_sanctioned_lists`), Menü in `menu.py` (Punkt 6); Überblick mit `print_sanctions_overview`, danach `check_sanctions_source_updates` + j/N-Aktualisierung

## Anzeige (CLI, gilt mit für Web)

- **Verbose:** Default `nein` (`VERBOSE` in `.env` oder Einstellungen [4]); gekürzte TxIDs/Adressen
- **Beträge:** `format_sats` — ≤100 000 sats als sats, darüber BTC mit 2 Dezimalstellen
- **Lange Listen:** `cancellable_output` — `q` zum Abbrechen (nur interaktives TTY)
