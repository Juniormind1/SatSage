# SatSage – know your sats

**Version 0.9** — steht in der Datei [`VERSION`](VERSION) (einzige Quelle). Neue Nummern setzen nur Maintainer; Builds und UI lesen sie nur. In der Web-GUI erscheint sie in der Fußzeile.

**Sprache:** Web-Oberfläche Deutsch oder Englisch (Einstellungen → Sprache; optional ``UI_LANG`` in ``.env``). Job-Log und viele Server-Meldungen können weiterhin Deutsch sein. Das Handbuch bleibt vorerst nur auf Deutsch.

Der Name ist Absicht als Wortspiel: **Sat Sage** (Sat-Weiser) und **Sats Age** (Alter der Sats) — passend zum Slogan *know your sats* und zur Frage, wie alt die Bestände on-chain schon sind.

Multi-XPUB- und Taproot-Analyzer für Wasabi- und Standard-Wallets.  
Analysiert Transaktionen und unspent UTXOs und zeigt, **woher die Sats wann kamen** — insbesondere wann sie ein xPub-Wallet betraten oder es wieder verließen. Daraus lässt sich die On-Chain-Haltedauer ablesen. Das ersetzt keine Börsenhistorie und keine Kaufbelege.

Früherer Projektname: xPubQuery. Technische IDs laufen unter `satsage` (Binary `satsage-webgui`, Specter-Extension `satsage.specterext.satsage`).

**Datenquellen:** eigener Electrum-Server (electrs/Fulcrum), Compact Filter über Bitcoin-P2P (`--bip158`), öffentliche Onions, Clearnet. Beim Start ohne explizite Wahl: eigener Electrum-Server → P2P-BIP-158; öffentliche Onions/Clearnet erst nach Bestätigung.

**Oberflächen:** Web (`py server.py`, empfohlen); interaktives CLI-Menü (`py main.py`) als **Legacy/Fallback** (Terminal/SSH ohne Browser); Specter-Plugin; StartOS-Sideload (`.s9pk`, x86_64) — Bau: [`doc/START9-packaging.md`](doc/START9-packaging.md). Direktmodi `--txid` / `--address` / `--cli` bleiben für Einmal-Analysen nützlich. Nutzerhandbuch: [`doc/handbuch.html`](doc/handbuch.html) (in der Web-GUI unter „Handbuch“).

## Was das ist — und was nicht

SatSage rekonstruiert aus der Blockchain, wann Sats diese Wallet-Adressen erreicht oder verlassen haben. Das ist ein On-Chain-Beleg, kein vollständiger Anschaffungsnachweis. Börsenhistorien, Kaufbelege, Kontoauszüge und ähnliche Unterlagen ersetzt das nicht — es kann sie nur ergänzen. Ob ein Stichtag oder eine Haltefrist greift, prüft nicht dieses Programm.

---

## Features

- **Web-Oberfläche** (`py server.py`) — Wallets, UTXO-/Verlaufsscan, Herkunft, Steuerjahr, Assistent (Cache-only), Einstellungen; nur localhost mit Sitzungs-Token
- **Interaktives Hauptmenü** (Legacy/Fallback: CLI ohne `--txid` / `--address` / `--cli`; empfohlen ist die Web-GUI)
- **Mehrere XPUBs** gleichzeitig (zpub, xpub, ypub, Taproot, Multisig-Deskriptor) mit Anzeigenamen
- **Tx-Trace** — TxID, UTXO (`txid:vout`) oder Adresse
- **Steuerjahr** — Haltefrist (Vorgabe 1 Jahr, Deutschland) und optionaler Stichtag; Chart und Export
- **Wallet-Alter** — First-seen in `utxo_cache/{hash}_alter.json`, überlebt „Cache löschen“
- **UTXO-Rangfolge** pro Wallet oder über alle Wallets
- **UTXO-Cache** pro XPUB (`utxo_cache/`) mit Salden-Check, Light-/Full-Rescan
- **Adress-Auflösungs-Cache** (`external_addresses.json`) für schnellere Trace-Zuordnung
- **Immutable-Cache** (`immutable_cache/`) für Transaktionen und Blockzeiten (alle Quellen)
- **Sanktions- & Blacklists** — OFAC, OpenSanctions, Scam-Listen; Wallet-Check und UTXO-Scan
- **UTXO-Konsolidierung** — Dust zusammenführen, PSBT erzeugen
- **Drei Blockchain-Backends** mit Privatsphäre-Hinweis in der Statuszeile
- **Einstellungen** im Menü bzw. in der Web-GUI: Datenquelle, Verbose, BIP-158-Start, Fristen, Sanktionslisten-Update, `.env`
- **Specter-Desktop-Plugin** (Testumgebung) — SatSage als Extension in Specter: Wallets/XPUBs vom Node, Tx-/UTXO-Trace und Rangfolge im Browser

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

Kopiere `.env.example` nach `.env` und passe Werte an. Wallets stehen dort als Block je Wallet (`WALLET_0_NAME`, `WALLET_0_XPUB`, …, fortlaufend ab 0) — dann reicht `py server.py` bzw. `py main.py` ohne `--xpubs`. Die alte Schreibweise (`XPUBS`, `WALLET_NAMES`) wird weiter gelesen und beim nächsten Speichern aus der Oberfläche umgewandelt. `.env` ist in `.gitignore` — **niemals** RPC-Passwörter, XPUBs oder persönliche Wallet-Namen committen.

---

## Schnellstart

```bash
# Web-Oberfläche (localhost, Sitzungs-Token in der URL)
py server.py

# Interaktives Menü (Legacy/Fallback) — XPUBs aus .env oder CLI
py main.py
py main.py --xpubs zpub6DeinXPUB... --wallet-names "Mein Wallet"

# Transaktion analysieren (direkt, ohne Menü)
py main.py --xpubs zpub6... --txid <txid>

# Adresse / einzelnes UTXO
py main.py --xpubs zpub6... --address bc1q...
py main.py --xpubs zpub6... --address bc1q... --utxo <txid>:<vout>

# Klassischer CLI-Modus: Top-UTXOs ohne Menü
py main.py --xpubs zpub6... --cli --top-utxos 10
```

Ohne `--wallet-names` bzw. ohne `WALLET_NAMES` in `.env` wird pro XPUB ein **SHA256-Hex** des Keys als Anzeigename verwendet.

---

## Web-Oberfläche

```bash
py server.py                 # http://127.0.0.1:8730/?t=… + Terminal-Menü
py server.py --port 8731     # anderer Port, falls 8730 belegt
py server.py --no-browser    # Browser nicht automatisch öffnen
py server.py --plain-console # ohne Terminal-Menü (nur URL, Strg+C)
```

Der Server bindet **nur an 127.0.0.1**. Jede API-Anfrage braucht das Sitzungs-Token aus der Start-URL — damit eine beliebige Webseite den lokalen Server nicht mitlesen kann.

**Terminal-Steuerung** (TTY): feste Menüzeile unten (Tasten **1** Status · **2** Browser · **3** Beenden); Log scrollt darüber. Der **Browser darf geschlossen werden** — UTXO-/Verlaufsscan und Job-Log laufen im Terminal weiter (dieselben Zeilen wie im Web-Log). Beenden: Taste 3 oder Strg+C. **Konsole offen lassen** (auch beim Onefile-Binary).

| Bereich | Inhalt |
|---------|--------|
| **Wallets** | Bestand, UTXO-Scan (aktuell unspent) und Verlaufsscan (Historie inkl. ausgegeben) |
| **Herkunft** | Rückwärts über eigene XPUBs bis zur ersten fremden Adresse |
| **Steuerjahr** | Haltefrist / Stichtag, Chart, CSV- und Berichtsexport |
| **Einstellungen** | Node, Wallets, Fristen, Status-Mails (SMTP, Opt-in), Sanktionslisten, Danger Zone (Cache) |
| **Log** | Fortschritt vor dem nächsten Schritt; bei Stillstand „Moment noch“ |

**UTXO-Scan über P2P-BIP-158:** ohne gespeichertes First-seen fragt die Oberfläche nach einem Startdatum (Vorschlag: SegWit 24.08.2017). Filter kommen von Peers, Blöcke nur bei Treffer. Ungenutzte Lookahead-Adressen laufen nur durch das jüngste Fenster (TurboSync).

Ausführlich: [`doc/handbuch.html`](doc/handbuch.html). Offene Lücke (gründlichere Herkunft / Sammel-Txs): [`ISSUES.md`](ISSUES.md).

**Web-GUI-Stabilität (Rumgeklicke):** wiederkehrendes Testprotokoll gegen schwer reproduzierbare UI-Bugs — [`doc/testprotokoll-webgui-stabilitaet.md`](doc/testprotokoll-webgui-stabilitaet.md); halbautomatisch `scripts/webgui_chaos_run.py` (optional Playwright).

---

## Hauptmenü (Legacy / Fallback)

**Empfohlen:** Web-GUI (`py server.py`). Das Terminal-Menü bleibt für Umgebungen ohne Browser (SSH, Server-Konsole) und schnelle Checks.

Beim Start ohne `--txid`, `--address` oder `--cli` erscheint das Menü mit Statuszeile:

- Gewählte **Datenquelle** inkl. **Privatsphäre-Hinweis**
- Anzahl und **Namen** der XPUBs; `[C]` = UTXO-Cache vorhanden

| Nr. | Funktion |
|-----|----------|
| 1 | Tracen: TxID oder UTXO |
| 2 | UTXO-Rangfolge eines Wallets (nummerierte Auswahl) |
| 3 | UTXO-Rangfolge aller Wallets |
| 4 | Gespeicherte Herkunfts-Analysen zu Outputs (auch ausgegebene; `immutable_cache/utxo_ingress/`) |
| 5 | UTXO-Konsolidierung |
| 6 | Prüfe Sanktionsliste |
| 7 | Einstellungen |
| 8 | Quit |

### Sanktionsliste (Menü 6)

| Nr. | Funktion |
|-----|----------|
| 1 | Wallet-UTXOs gegen Sanktionslisten prüfen |
| 2 | UTXOs auf sanktionierten Adressen scannen |
| 3 | **Sanktionslisten-Überblick** — pro Quelle: Entitäten, Adressen, Listungsdatum, Adress-Standards; danach Online-Aktualitätsprüfung (j/N zum Aktualisieren) |
| 4 | Adress-Gruppen (Person, Grund, Quelle) |

Sanktions-UTXO-Abfragen laufen immer über **Clearnet-Fulcrum** (unabhängig von der Wallet-Datenquelle).

**Quellen** (in `sanctioned_cache/`):

- OFAC SDN (0xB10C Flatliste + treasury.gov SDN-XML)
- OpenSanctions: Israel NBCTF, US FBI Lazarus Group, ransomwhe.re
- Badd-Boyz Bitcoin Scammers

### Einstellungen (Menü 7)

| Nr. | Funktion |
|-----|----------|
| 1 | Datenquelle: BIP-158 / Fulcrum |
| 2 | BIP-158 Start-Blockhöhe (Default: 850 000) oder Startdatum |
| 3 | Top-N-Limit für Ranglisten |
| 4 | Verbose (j/n) — volle TxIDs/Adressen (Default: nein) |
| 5 | `.env` im Editor öffnen |
| 6 | `check_fulcrum_tor.py` in externem Terminal |
| 7 | Sanktions- & Blacklists aktualisieren |
| 8 | Zurück |

---

## Datenquellen

| Modus | CLI / Menü | Privatsphäre | Verhalten |
|-------|------------|--------------|-----------|
| **Eigener Electrum-Server** | Auto (Priorität 1) | hoch | electrs/Fulcrum: `FULCRUM_HOST` / `FULCRUM_TOR` |
| **Bitcoin-P2P Compact Filter** | `--bip158`, Auto (2) | hoch | BIP 157/158, Filter lokal, Block nur bei Treffer. Kein Core-RPC. Scheitert Clearnet, folgt Tor (laufender Browser oder Autostart). |
| **Fulcrum (öffentlich)** | nach Bestätigung, `--oeffentliche-electrum` oder `--rpc-only` | mäßig | Electrum-Protokoll: Rotation `FULCRUM_TOR_0`…`9` oder Clearnet |

**Automatische Priorität** beim Start (wenn weder CLI-Flag noch manuelle Menüwahl gesetzt):

1. eigener Electrum-Server → 2. P2P-BIP-158 → 3./4. öffentliche Onions bzw. Clearnet **nur nach Bestätigung** (`OEFFENTLICHE_ELECTRUM=1`, `--oeffentliche-electrum`, Dialog in der Web-Oberfläche, oder j/N im CLI-Menü)

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

Erreichbare Onions werden als `FULCRUM_TOR_0=…` usw. ausgegeben — ins Menü **Einstellungen → .env bearbeiten** oder direkt in `.env` eintragen.

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

Lokal gecachte Blacklists (Download über Einstellungen [7] oder aus dem Überblick heraus):

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
| `--txid TXID` | Spending-Tx analysieren (ohne Menü) |
| `--address ADDR` | Unspent UTXOs + Herkunft |
| `--utxo TXID:VOUT` | Einzelnes UTXO (mit `--address`) |
| `--cli` | Klassischer Modus: Top-UTXOs statt Menü |
| `--top-utxos N` | Top-N im Menü bzw. mit `--cli` (Default: 10) |
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