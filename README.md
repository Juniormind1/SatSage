<p align="center">
  <img src="web/img/logo.jpg" alt="SatSage" width="320">
</p>

<p align="center">
  <strong>know your sats</strong><br>
  <em>Woher die Sats wann kamen — On-Chain-Alter für Steuer und Überblick</em>
</p>

<p align="center">
  <a href="VERSION"><img src="https://img.shields.io/badge/version-0.9.2-f7931a?style=flat-square" alt="Version 0.9.2"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/badge/UI-localhost%20Web--GUI-111111?style=flat-square" alt="Web-GUI">
</p>

---

**SatSage** (Wortspiel: *Sat Sage* / *Sats Age*) analysiert XPUB-Single- und Multisig-Wallets und zeigt, **woher die Sats wann kamen** — insbesondere wann sie ein xPub-Wallet betraten oder wieder verließen. Daraus lässt sich die On-Chain-Haltedauer ablesen. Das ersetzt keine Börsenhistorie und keine Kaufbelege.

| | |
|:--|:--|
| **Version** | [`VERSION`](VERSION) → aktuell **0.9.2** (einzige Quelle; Fußzeile der Web-GUI) |
| **Oberfläche** | Web (`py server.py`) + Terminal-Steuerung · Specter-Plugin · StartOS-Sideload |
| **Sprache** | DE/EN in der UI (`UI_LANG` / Einstellungen); Handbuch vorerst DE |
| **IDs** | `satsage` · Binary `satsage-webgui` · Specter `satsage.specterext.satsage` |

**Datenquellen:** eigener Electrum-Server (electrs/Fulcrum) → Compact Filter über Bitcoin-P2P (`--bip158`) → öffentliche Onions/Clearnet erst nach Bestätigung. Lokaler Pruned-Node für schnellen UTXO-Scan wird erkannt. Nutzerhandbuch: [`doc/handbuch.html`](doc/handbuch.html).

## Was das ist — und was nicht

SatSage rekonstruiert aus der Blockchain, wann Sats diese Wallet-Adressen erreicht oder verlassen haben. Das ist ein On-Chain-Beleg, kein vollständiger Anschaffungsnachweis. Börsenhistorien, Kaufbelege, Kontoauszüge und ähnliche Unterlagen ersetzt das nicht — es kann sie nur ergänzen. Ob ein Stichtag oder eine Haltefrist greift, prüft nicht dieses Programm.

---

## Features

| Bereich | Inhalt |
|---------|--------|
| **Web-Oberfläche** | Wallets, UTXO-/Verlaufsscan, Herkunft, Steuerjahr, Assistent (Cache-only), Einstellungen — nur localhost mit Sitzungs-Token |
| **Wallets** | Mehrere XPUBs (zpub, xpub, ypub, Taproot, Multisig-Deskriptor) mit Anzeigenamen |
| **Herkunft** | Tx-Trace per TxID, UTXO (`txid:vout`) oder Adresse |
| **Steuerjahr** | Haltefrist (Vorgabe 1 Jahr, DE), optionaler Stichtag; Chart und Export |
| **Caches** | UTXO-, Alters-, Adress-Auflösungs- und Immutable-Cache |
| **Privatsphäre** | Eigener Node / BIP-158 bevorzugt; öffentliche Server nur nach Bestätigung |
| **Sanktionen** | OFAC, OpenSanctions, Scam-Listen — Wallet-Check und UTXO-Scan |
| **Mehr** | Dust-Konsolidierung (PSBT), Specter-Desktop-Plugin |

---

## Voraussetzungen

- Python 3.10+
- Internetzugang (öffentliche Fulcrum-Onions/Clearnet, BIP-158-Blockdownload, Sanktionslisten-Download)
- Optional: eigener Node (Fulcrum oder Bitcoin Core mit `blockfilterindex=1`)
- Für Tor-Onions: ein Tor-Binary (meist schon im Tor-Browser-Ordner). SatSage startet es selbst und braucht kein Browser-Fenster. Alternativ ein schon laufender SOCKS-Proxy (`FULCRUM_TOR_PROXY`)

---

## Installation

```bash
git clone https://github.com/<dein-user>/SatSage.git
cd SatSage
py -m venv .venv    # Windows; Linux/macOS: python3 -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Kopiere `.env.example` nach `.env` und passe Werte an. Wallets stehen dort als Block je Wallet (`WALLET_0_NAME`, `WALLET_0_XPUB`, …, fortlaufend ab 0) — dann reicht `py server.py` ohne `--xpubs`. Die alte Schreibweise (`XPUBS`, `WALLET_NAMES`) wird weiter gelesen und beim nächsten Speichern aus der Oberfläche umgewandelt. `.env` ist in `.gitignore` — **niemals** RPC-Passwörter, XPUBs oder persönliche Wallet-Namen committen.

---

## Schnellstart

```bash
# Empfohlen: Web-GUI + Terminal-Steuerung (localhost, Token in der URL)
py server.py

# Einmal-Analysen ohne GUI (XPUBs aus .env oder --xpubs)
py main.py --xpubs zpub6... --txid <txid>
py main.py --xpubs zpub6... --address bc1q...
py main.py --xpubs zpub6... --address bc1q... --utxo <txid>:<vout>
py main.py --xpubs zpub6... --cli --top-utxos 10
```

Ohne `--wallet-names` bzw. ohne `WALLET_NAMES` / `WALLET_0_NAME`… in `.env` wird pro XPUB ein **SHA256-Hex** des Keys als Anzeigename verwendet.

---

## Web-Oberfläche und Terminal-Steuerung

```bash
py server.py                 # http://127.0.0.1:8730/?t=… + Terminal-Steuerung
py server.py --port 8731     # anderer Port, falls 8730 belegt
py server.py --no-browser    # Browser nicht automatisch öffnen
py server.py --plain-console # ohne Terminal-Steuerung (nur URL, Strg+C)
```

Der Server bindet **nur an 127.0.0.1**. Jede API-Anfrage braucht das Sitzungs-Token aus der Start-URL — damit eine beliebige Webseite den lokalen Server nicht mitlesen kann.

**Zwei Oberflächen, ein Prozess.** `py server.py` startet den lokalen HTTP-Server und — in einem normalen Terminal (TTY) — ein **minimales Steuerungsmenü** in derselben Konsole. Die eigentliche Arbeit (Wallets, Scans, Herkunft, Einstellungen) passiert in der **Browser-GUI**. Das Terminal-Menü steuert den Serverprozess, ersetzt die GUI aber nicht.

| Wo | Wofür |
|----|--------|
| **Browser-GUI** | Wallets, Scans, Herkunft, Steuerjahr, Einstellungen, Log-Ansicht |
| **Terminal-Steuerung** | Status, Browser erneut öffnen, Server beenden; Job-Log parallel zur Web-Log-Ansicht |

**Terminal-Steuerung** (TTY): feste Menüzeile unten (Tasten **1** Status · **2** Browser-GUI öffnen · **3** Beenden); das Job-Log scrollt darüber (dieselben Zeilen wie im Web-Log). Der **Browser darf geschlossen werden** — Scans und Logs laufen in der Konsole weiter; Taste **2** öffnet die Token-URL erneut. Beenden: Taste **3** (mit Bestätigung) oder Strg+C. **Konsole offen lassen** (auch beim Onefile-Binary) — schließt du das Terminalfenster, endet der Server. Ohne nutzbare TTY oder mit `--plain-console` entfällt das Menü; der Server läuft trotzdem, Beenden nur per Strg+C.

| Bereich (Browser) | Inhalt |
|---------|--------|
| **Wallets** | Bestand, UTXO-Scan (aktuell unspent) und Verlaufsscan (Historie inkl. ausgegeben) |
| **Herkunft** | Rückwärts über eigene XPUBs bis zur ersten fremden Adresse |
| **Steuerjahr** | Haltefrist / Stichtag, Chart, CSV- und Berichtsexport |
| **Einstellungen** | Node, Wallets, Fristen, Status-Mails (SMTP, Opt-in), Sanktionslisten, Danger Zone (Cache) |
| **Log** | Fortschritt vor dem nächsten Schritt; bei Stillstand „Moment noch“ |

**UTXO-Scan über P2P-BIP-158:** ohne gespeichertes First-seen fragt die Oberfläche nach einem Startdatum (Vorschlag: SegWit 24.08.2017). Filter kommen von Peers, Blöcke nur bei Treffer. **Erstscan:** zuerst Turbo-Fenster (~14 Tage) mit voller Lookahead-Menge (Zwischenstand nutzbar), danach Historie nur mit getroffenen Adressen plus kleiner Gap — nicht die ganze Lookahead-Menge seit SegWit. Compact Filter werden unter `immutable_cache/cfilter/` (Höhe + Blockhash) gecacht und beim nächsten Wallet/Rescan wiederverwendet.

Ausführlich: [`doc/handbuch.html`](doc/handbuch.html). Offene Lücke (gründlichere Herkunft / Sammel-Txs): [`ISSUES.md`](ISSUES.md).

**Web-GUI-Stabilität (Rumgeklicke):** wiederkehrendes Testprotokoll gegen schwer reproduzierbare UI-Bugs — [`doc/testprotokoll-webgui-stabilitaet.md`](doc/testprotokoll-webgui-stabilitaet.md); halbautomatisch `scripts/webgui_chaos_run.py` (optional Playwright).

---

**Quellen** (in `sanctioned_cache/`):

- OFAC SDN (0xB10C Flatliste + treasury.gov SDN-XML)
- OpenSanctions: Israel NBCTF, US FBI Lazarus Group, ransomwhe.re
- Badd-Boyz Bitcoin Scammers

**Automatische Priorität** beim Start (wenn weder CLI-Flag noch manuelle Wahl in den Einstellungen gesetzt):

1. eigener Electrum-Server → 2. P2P-BIP-158 → 3./4. öffentliche Onions bzw. Clearnet **nur nach Bestätigung** (`OEFFENTLICHE_ELECTRUM=1`, `--oeffentliche-electrum` oder Dialog in der Web-Oberfläche)

Ohne Bestätigung bleiben nur eigener Node und BIP-158. Extra-Scan-Verbindungen gelten nur für den eigenen LAN-Fulcrum. `BIP158_P2P=0` lässt Compact Filter in der Auto-Kette aus.

**Verlaufsscan** hat eine eigene Kette (Core `scantxoutset` liefert keinen Verlauf): Electrs/Fulcrum LAN → Onion → BIP-158 Blockwalk/Cache → öffentliche Electrum (nach Bestätigung).

`BIP158_P2P=1` in `.env` erzwingt **keine** Quelle — nur `--bip158`, `--rpc-only` oder die manuelle Wahl unter Einstellungen.

```bash
# Compact Filter über Bitcoin-P2P
py main.py --bip158 --bip158-start 481824 --xpubs zpub6...

# Eigener Electrum-Server
py main.py --rpc-only --xpubs zpub6...

# Öffentliche Electrum-Server (Adressen gehen an Dritte)
py main.py --oeffentliche-electrum --xpubs zpub6...

```

Öffentliche Fulcrum-Server und der **Sanktions-Clearnet-Pool** nutzen `electrum_servers.json` (lokal, optional per `check_fulcrum_tor.py` aktualisiert).

### Fulcrum-Verbindung testen

```bash
py check_fulcrum_tor.py
py check_fulcrum_tor.py --onion-list-only   # nur öffentliche Server scannen
```

Erreichbare Onions werden als `FULCRUM_TOR_0=…` usw. ausgegeben — in der Web-GUI unter **Einstellungen → .env bearbeiten** oder direkt in `.env` eintragen.

---

## Konfiguration (`.env`)

Auszug — vollständige Vorlage: `.env.example`

```env
# Wallet (optional — sonst --xpubs / --wallet-names per CLI)
# WALLET_0_NAME=Mein Wallet                # Leerzeichen erlaubt
# WALLET_0_XPUB=zpub6DeinXPUB
# WALLET_0_SCRIPT=segwit                   # auto|legacy|nested|segwit|taproot
# WALLET_0_MAX_ADDRESSES=50
# WALLET_1_NAME=Zweites Wallet
# WALLET_1_XPUB=xpub6ZweiterXPUB
#
# Multisig — über den Output-Deskriptor (deckt auch Taproot und Liana ab):
# WALLET_2_NAME=Tresor
# WALLET_2_DESC=wsh(sortedmulti(2,xpubA/<0;1>/*,xpubB/<0;1>/*,xpubC/<0;1>/*))
# Taproot: tr(xpubA/<0;1>/*,multi_a(2,xpubB/<0;1>/*,xpubC/<0;1>/*))
#
# Kurzform als Eingabe (nur sortedmulti, wird zum Deskriptor umgeschrieben):
# WALLET_2_M=2 / WALLET_2_SCRIPT=wsh / WALLET_2_XPUBS=xpub6A xpub6B xpub6C
# Alternativ: XPUB_0, XPUB_1 … und WALLET_NAME_0, WALLET_NAME_1 …

# Fulcrum — eigener Node
FULCRUM_HOST=192.168.1.100
FULCRUM_TOR=deinnode.onion
FULCRUM_PORT=50002
FULCRUM_SSL=true
FULCRUM_TOR_PROXY=127.0.0.1:9150

# Öffentliche Onion-Rotation (max. 10)
# FULCRUM_TOR_0=beispiel.onion

# Sanktionslisten (Clearnet, ohne eigene XPUBs)
# Leer = schnellste Server aus electrum_servers.json (parallel)
# FULCRUM_SANCTIONS_HOST=fulcrum.sethforprivacy.com
# FULCRUM_SANCTIONS_PORT=50002
# FULCRUM_SANCTIONS_SSL=true

# Compact Filter über Bitcoin-P2P (kein Core-RPC)
# BIP158_P2P=1
# BIP158_START_HEIGHT=481824
# BIP158_PEERS=                 # extra P2P-Peers; Host im LAN zuerst, dann DNS
#
# Header-Archiv: data/p2p_headers_segwit.bin.gz (ab SegWit). Beim ersten
# Compact-Filter-Lauf nach immutable_cache/p2p_headers.bin entpacken;
# nur der Tip wird per P2P nachgezogen.


# Verbose: volle TxIDs/Adressen (Default: aus)
# VERBOSE=1

# Steuer: Haltefrist in Jahren (Vorgabe 1, Deutschland). Stichtag leer =
# Frist gilt für alle Anschaffungen. Beispiel Cutoff: Österreich 28.02.2021.
# STEUER_HALTEFRIST_JAHRE=1
# STEUER_STICHTAG=
```

**Start9 / electrs über Tor:** `FULCRUM_TOR=<electrs-onion>.onion`, Port oft 50001 ohne TLS. Tor startet SatSage selbst (SOCKS 9050), sofern ein `tor`-Binary gefunden wird — Windows: `Tor Browser\Browser\TorBrowser\Tor\tor.exe`, macOS: `/Applications/Tor Browser.app/Contents/MacOS/Tor/tor`. Ein laufender Tor Browser (9150) wird weiter genutzt. Abschalten: `TOR_AUTOSTART=0`. Eigenes Binary: `TOR_BINARY`. Derselbe Weg gilt für Compact-Filter-P2P, wenn Clearnet (Port 8333) keine Peers liefert.

---

## Caches (Flatfiles)

### UTXO-Cache — `utxo_cache/`

Wallet-spezifisch, **veränderlich** (UTXOs kommen und gehen).

- Pro XPUB eine JSON-Datei mit UTXOs, `scan_end_index`, ggf. `scanned_addresses`
- `{hash}_alter.json` — First-seen (Wallet-Alter). Bleibt beim Löschen des UTXO-/Verlaufs-/Herkunfts-Caches (Danger Zone in der Web-GUI, auch pro Wallet)
- `external_addresses.json` — Adress-Auflösungs-Cache (externe Adressen, XPUB-Negative, verifizierte Wallet-Treffer); beschleunigt Trace und `WalletContext.resolve_address()`
- Beim Ranglisten-Abruf: Cache laden → optional Salden-Check → Light-/Full-Rescan
- Unter **5 % freiem Speicherplatz** am Cache-Laufwerk werden neue Cache-Schreibvorgänge pausiert (Warnung einmalig)

```bash
py main.py --xpubs zpub6... --rescan          # Full-Rescan erzwingen
py main.py --xpubs zpub6... --cache-dir ./mein_utxo_cache
```

**Ablauf bei vorhandenem Cache:**

1. *Salden noch prüfen?*
2. Check der gecachten UTXOs + 5 Lookahead-Adress-Indizes
3. Stimmt alles → Cache nutzen
4. Abweichung → Light-Rescan (nächste Batch) oder Full-Rescan (ab Index #0)

### Immutable-Cache — `immutable_cache/`

**Unveränderliche** Blockchain-Daten, quellenunabhängig (Fulcrum, BIP-158):

| Unterordner | Inhalt |
|-------------|--------|
| `tx/` | Transaktionen (`{txid}.json`) — jede erfolgreich geladene Tx |
| `block_header/` | Blockzeit pro Höhe (Fulcrum-Anreicherung) |
| `utxo_ingress/` | Herkunfts-Metadaten analysierter Outputs (auch bereits ausgegebene) |

Wird automatisch beim Tracen befüllt; beschleunigt wiederholte Analysen und Vorgänger-Ketten auch nach Neustart.

```bash
py main.py --immutable-cache-dir ./mein_immutable_cache ...
```

`utxo_ingress/` kann **Wallet-Anzeigenamen** enthalten — bei Teilen des Repos oder Backups neutrale Namen verwenden.

### Sanktions-Cache — `sanctioned_cache/`

Lokal gecachte Blacklists (Download in der Web-GUI unter Einstellungen oder aus dem Überblick heraus):

| Datei | Inhalt |
|-------|--------|
| `sanctioned_addresses_XBT.json` | Alle BTC-Adressen (vereinigt) |
| `sanctioned_entities_XBT.json` | Entitäten mit Person, Grund, Quellen |
| `sanctioned_address_index.json` | Metadaten pro Adresse |
| `*.meta.json` | Stand, Quellen-Statistik (`etag`, `export_id`, …) |
| `sdn_advanced.xml` | OFAC SDN-Rohdaten (optional) |

---

## Wichtige CLI-Optionen

| Option | Beschreibung |
|--------|--------------|
| `--xpubs XPUB [XPUB ...]` | Extended Public Keys (sonst `WALLET_0_XPUB`… aus `.env`) |
| `--wallet-names NAME [NAME ...]` | Anzeigenamen (sonst `WALLET_NAMES` / `WALLET_NAME_0`… aus `.env`) |
| `--txid TXID` | Spending-Tx analysieren (Einmal-Lauf) |
| `--address ADDR` | Unspent UTXOs + Herkunft |
| `--utxo TXID:VOUT` | Einzelnes UTXO (mit `--address`) |
| `--cli` | Einmal-Lauf: Top-UTXOs ausgeben und beenden |
| `--top-utxos N` | Anzahl Top-UTXOs mit `--cli` (Default: 10) |
| `--max-addresses N` | Abgeleitete Adressen pro XPUB (Default: 50) |
| `--max-addresses-per-xpub N [N ...]` | Individuelles Limit pro XPUB (Reihenfolge wie `--xpubs`) |
| `--rescan` | Full-Rescan aller XPUBs |
| `--cache-dir DIR` | UTXO-Cache-Verzeichnis |
| `--immutable-cache-dir DIR` | Cache unveränderlicher Daten |
| `--bip158` | Compact Filter über Bitcoin-P2P (kein Core-RPC) |
| `--bip158-start HEIGHT` | Erster Scan-Block (Default: 481 824, SegWit) |
| `--rpc-only` | Fulcrum erzwingen |
| `--no-verbose` | Gekürzte TxIDs/Adressen erzwingen |
| `--fulcrum-host`, `--fulcrum-port`, `--fulcrum-no-ssl` | Fulcrum-Verbindung |

---

## Adressableitung

Pro XPUB werden Adressen ab Index #0 abgeleitet (Receive- und Change-Chain), abhängig vom XPUB-Präfix:

- `zpub` / `vpub` → Native SegWit (BIP84)
- `xpub` / `tpub` → Legacy + Taproot
- `ypub` / `upub` → Nested SegWit

Ein **Light-Rescan** setzt am gespeicherten `scan_end_index` fort (z. B. #25–#49 bei Default 50).

---

## Specter Desktop Plugin

Unter `specter_plugin/` liegt eine **Specter-Desktop-Extension** (Package `satsage.specterext.satsage`). Specter hostet die UI; SatSage nutzt Specters Wallets und den verbundenen Node — **ohne** `main.py` als CLI zu starten.

| | |
|--|--|
| **Zweck** | Config-Kontext (Node, XPUBs, UTXOs) + Herkunftsanalyse im Browser |
| **URL** | http://127.0.0.1:25441 → Plugins → **SatSage** → `/svc/satsage/` |
| **Detail-Doku** | [`specter_plugin/README.md`](specter_plugin/README.md) |

### Was die Extension kann

| Bereich | Inhalt |
|---------|--------|
| **Übersicht** | Node, XPUB-Anzahl, Session-Status (Datenquelle, Privatsphäre), Adress-/UTXO-Counts |
| **Wallets** | Specter-Wallets inkl. XPUBs, Saldo, UTXO-/Tx-Vorschau; Detailseite pro Alias |
| **Analyse** | Tx-Trace (TxID), UTXO-Trace (`txid:vout`), UTXO-Rangfolge, Top-N-UTXOs tracen |
| **Kontext** | `context.json` (exportierbarer Bridge-Snapshot; Secrets nur mit Dev-Flag) |

Die Analyse ruft dieselbe Logik wie die CLI auf (`analyze.analyze_tx`, `analyze_address_utxos`, `list_top_wallet_utxos`, `trace_known_utxos`). XPUBs und Node kommen aus Specter; Caches liegen im Repo-Root (`utxo_cache/`, `immutable_cache/`). Bevorzugt wird **Bitcoin Core + BIP-158**, wenn Specter einen Core-Node mit RPC-Credentials hat.

**Privatsphäre:** Abfragen laufen **in-process** über Specters Node — kein Extra-Leak an öffentliche Esplora/Fulcrum-Server, solange Specter auf deinen eigenen Node zeigt.

### Schnellstart (macOS / Linux)

```bash
cd specter_plugin
chmod +x scripts/*.sh
./scripts/setup_dev.sh

# Optional: Regtest-Node (Docker)
./scripts/run_bitcoind_regtest.sh

# Specter + Plugin
./scripts/run_specter.sh
```

1. Browser: **http://127.0.0.1:25441** (Dev-Login typisch `admin` / `admin`)
2. Node verbinden (Regtest: `localhost:18443`, User `bitcoin`, Pass `secret`)
3. Device + Watch-Only-Wallet mit XPUB anlegen (oder Hot-Wallet im Regtest)
4. **Plugins → SatSage** aktivieren
5. Sidebar → **SatSage**: Übersicht, Wallets, Analyse

Offline-Checks:

```bash
./.venv/bin/python scripts/unit_bridge.py   # Bridge ohne laufenden Specter
./.venv/bin/python scripts/probe_api.py     # REST-API (Specter muss laufen)
```

### Architektur (Kurz)

```
Specter Desktop (Flask)
 ├── app.specter.node / wallet_manager
 └── Extension satsage
      ├── bridge.py          # Specter → SatSageContext (XPUBs, Node, env_like)
      ├── specter_session.py # WalletContext + BIP-158/Fetchers + analyze_*
      ├── controller.py      # UI unter /svc/satsage/
      └── service.py         # Extension-Metadaten (alpha)
```

- **Dev-Config:** `app_config.DevConfig` — Extension in `EXTENSION_LIST`, API an, `devstatus=alpha`
- **Lokale Daten:** `specter_plugin/.specter_dev/`, `.venv/`, `.run/` (gitignore) — nicht committen
- **Python:** Specter historisch 3.9/3.10; bei Installationsfehlern 3.10-venv nutzen

Production-Binaries von Specter laden fremde Extensions **nicht** aus dem CWD; die Testumgebung installiert das Package editable und setzt `EXTENSION_LIST`.

---

## Sicherheit & Datenschutz

- **XPUBs** erlauben das Ableiten aller Wallet-Adressen — behandle sie wie sensible Daten.
- **Wallet-Namen** in `.env`, `utxo_cache/` und `immutable_cache/` können persönliche Bezeichnungen enthalten — nicht committen oder in Screenshots zeigen.
- Nutze das Tool lokal; teile keine XPUBs in Issues oder Screenshots.
- **Fulcrum (öffentliche Onions/Clearnet):** Rotation mildert Einzelserver-Risiko — Privatsphäre „mäßig“.
- **Eigener Node (BIP-158 / eigener Fulcrum):** beste Option — Privatsphäre „hoch“.
- **Sanktions-Scans:** nutzen Clearnet-Fulcrum für Listen-Adressen (nicht deine Wallet-XPUBs).
- **Specter-Plugin:** nutzt Specters Node in-process; Secrets/XPUBs nicht aus der UI/Logs exportieren; `.specter_dev/` lokal belassen.

---

## Lizenz

SatSage steht unter der [MIT License](LICENSE) — Copyright (c) 2026 Juniormind1.

Drittanbieter-Laufzeitbibliotheken und Build-/Test-Werkzeuge: siehe [`NOTICE`](NOTICE).
