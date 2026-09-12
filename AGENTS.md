# AGENTS.md â€” SatSage

Kontext fÃ¼r KI-Assistenten (Cursor, Grok, Claude Code, â€¦), die an diesem Repository arbeiten.

## Zweck

**SatSage â€“ know your sats** (frÃ¼her xPubQuery) ist ein Multi-XPUB- und Taproot-Analyzer fÃ¼r Wasabi- und Standard-Wallets. Das Tool analysiert Transaktionen und unspent UTXOs und zeigt, **woher die Sats wann kamen** â€” insbesondere wann sie ein xPub-Wallet betraten oder es wieder verlieÃŸen. Typischer Anwendungsfall: Nachweise fÃ¼r die SteuererklÃ¤rung (Haltedauer, Stichtage). Anzeigename, Logo und technische IDs (`satsage`, Binary `satsage-webgui`, Specter-Package) sind vereinheitlicht.

## Einstieg

- **Hauptprogramm:** `main.py`
- **Web-OberflÃ¤che:** `server.py` (localhost `127.0.0.1:8730`, Sitzungs-Token) â€” UI in `web/`; Terminal-Steuerung in `core/terminal_steuerung.py` (Browser darf zu; Job-Log wird gespiegelt)
- **Standardmodus (CLI):** interaktives MenÃ¼ (ohne `--txid`, `--address`, `--cli`) â€” **Legacy/Fallback**; empfohlen ist `server.py` (Web)
- **Direktmodi:** `--txid`, `--address`, `--cli` (Einmal-Analysen, weiterhin sinnvoll)
- **Specter-Plugin:** `specter_plugin/` â€” Extension in Specter Desktop (Browser-UI, nutzt `main`/`analyze` in-process)
- **Konfiguration:** `.env` (Vorlage: `.env.example`) â€” niemals Secrets, XPUBs oder persÃ¶nliche Wallet-Namen committen
- **Dokumentation:** `README.md`, Nutzerhandbuch: `doc/handbuch.html`, Ã„nderungshistorie: `CHANGELOG.md`, offene Punkte: `ISSUES.md`, Plugin: `specter_plugin/README.md`
- **Design Â· Node-Anbindung:** `doc/design-node-anbindung.md` â€” schick, minimalistisch, fehlertolerant; Konfigurationsfehler mÃ¶glichst von der App abfangen (nicht vom Nutzer)
- **Design Â· FlÃ¼chtigkeit:** `doc/design-fluchtigkeit.md` â€” Nutzer in Eile/unaufmerksam; Fehlerverhinderung statt Hinweistext (z.â€¯B. Empfangs-QR beim Wallet-Wechsel sofort ungÃ¼ltig)
- **Design Â· Neugier:** `doc/design-neugier.md` â€” unwissend/lernfaul aber neugierig; subtile Hinweise ohne die minimale Funktion zu stÃ¶ren
- **Grok-Bot (remote, z.â€¯B. nur iPhone + GitHub):** `GROK_BOT.md` â€” hart: keine Secrets/Heim-Node; **Mainnet nie**; Lab/CI: **Regtest â†’ Signet â†’ Testnet nur Ausnahme**; Lab-Env getrennt von Prod-`.env` (kein eingebauter Multi-Chain-Schalter)
- **Web-GUI-StabilitÃ¤t (Rumgeklicke):** Protokoll `doc/testprotokoll-webgui-stabilitaet.md`; halbautomatisch `scripts/webgui_chaos_run.py` + `scripts/webgui_chaos_harness.js` (optional Playwright)
- **Datenquellen-Wechsel waehrend Scan:** Protokoll `doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md` — P2P vs Electrum, Job-Snapshot, Cache-Flags, Queue
- **GUI-Tests Â· Token:** Nie Token aus Logs greppen. Session-JSON `tmp/satsage-gui-session.json` bzw. Zeile `SATSAGE_SESSION {â€¦}`; Helfer `scripts/webgui_test_ready.py spawn|attach|url`; Protokoll `doc/gui-test-protokoll.md`. Chaos: `--spawn`.
- **StartOS-Sideload (`.s9pk`):** Wrapper liegt in **`packaging/`** auf Branch `main` â€” nicht auf `master`, nicht in einem Sibling-Repo. Bau-Anleitung fÃ¼r Bots: [`doc/START9-packaging.md`](doc/START9-packaging.md). Kurz: `./scripts/build_startos_s9pk` (x86_64). Vorhandenes Release: Tag `startos-tls11`.

Wallets stehen in `.env` als Block je Wallet (`WALLET_0_NAME`, `WALLET_0_XPUB`, `WALLET_0_SCRIPT`, `WALLET_0_MAX_ADDRESSES`), fortlaufend ab 0 und ohne LÃ¼cke; Multisig Ã¼ber `WALLET_n_DESC` (Output-Deskriptor, kanonische Form â€” deckt wsh/sh-wsh, Taproot `multi_a` und Miniscript-Policies ab; abgeleitet wird Ã¼ber `embit.descriptor`). `WALLET_n_M` + `WALLET_n_XPUBS` bleibt als Eingabe-Kurzform und wird beim Schreiben in einen Deskriptor Ã¼bersetzt. Einzige Quelle ist `core.config.read_wallets` â€” die alten Schreibweisen (`XPUBS`, `XPUB_0` â€¦) werden nur noch gelesen. Ohne CLI-Angabe und ohne `WALLET_NAMES` nutzt `main.py` einen **SHA256-Hex** des XPUB als Anzeigename.

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
| `main.py` | CLI, `.env`-Laden (`_xpubs_from_env`, `_wallet_names_from_env`), Datenquellenwahl (inkl. Auto-PrioritÃ¤t), Caches, `WalletContext`, Adressableitung, Adress-AuflÃ¶sungs-Cache, Sanktions-Clearnet-Pool |
| `server.py` | Web-GUI (stdlib HTTP, nur 127.0.0.1), API, Hintergrund-Jobs |
| `web/` | OberflÃ¤che (`app.js`, `index.html`, `style.css`) |
| `menu.py` | Interaktives HauptmenÃ¼ (**Legacy/Fallback**), Einstellungen, Session-State, SanktionsmenÃ¼ |
| `interact.py` | Prompts (`j/N`), Analyse-Orchestrierung, Top-UTXO-Auswahl |
| `analyze.py` | Tx/UTXO-Herkunftsanalyse, Trace, Sanktions-UTXO-Checks (ohne interaktive Prompts) |
| `trace_engine.py` | Gemeinsame Graph-Engine: RÃ¼ckwÃ¤rts-Walk Ã¼ber Tx-Inputs (`vin` â†’ `prevout`) |
| `display.py` | `format_sats`, Verbose-Modus, `cancellable_output` (q-Abbruch langer Listen) |
| `sanctioned.py` | Multi-Source-Sanktionslisten, Cache, Ãœberblick, Online-AktualitÃ¤tsprÃ¼fung |
| `bip158_scanner.py` | BIP-158 Ã¼ber Bitcoin-P2P (Compact Filter, TurboSync); Matcher `_CoreBasicFilterMatcher` |
| `core/p2p.py` | Bitcoin-P2P: Handshake, Header, `cfilter`, Block-Download |
| `fulcrum.py` | Fulcrum/Electrum-Protokoll, Onion-Rotation |
| `core/jobs.py` | Hintergrund-VorgÃ¤nge (Scan, Verlauf, Herkunft) mit Log und Abbruch |
| `core/tax.py` | Haltefrist, Stichtag, Steuerjahr-Auswertung |
| `core/llm_anbindung.py` / `llm_client.py` / `llm_context.py` | Assistent: Einstufung, Chat-Loop (Loopback/LAN; Remote nur Opt-in), Cache-Reader. Kein Job-Start. Key nie im Status. |
| `core/tor.py` | SOCKS erkennen, lokales `tor` ohne Browser-Fenster starten |
| `consolidate.py` | Dust-Konsolidierung, PSBT-Erzeugung |
| `check_fulcrum_tor.py` | Fulcrum/Tor-Verbindungstest, VorschlÃ¤ge fÃ¼r `.env`, `electrum_servers.json` |
| `specter_plugin/` | Specter-Desktop-Extension: Bridge + Session + Flask-UI (siehe Abschnitt unten) |

### Datenquellen (PrivatsphÃ¤re absteigend)

**Automatische PrioritÃ¤t** (Default beim Start, wenn weder CLI noch manuelle MenÃ¼wahl) â€” allgemeine Datenquelle:

1. **Eigener Electrum-Server** (`FULCRUM_HOST` / `FULCRUM_TOR`, electrs/Fulcrum) â€” PrivatsphÃ¤re **hoch**
2. **Bitcoin-P2P Compact Filter** â€” `--bip158` (kein Core-RPC)
3. **Ã–ffentliche Fulcrum-Onions** â€” `FULCRUM_TOR_0`â€¦`9`, nur nach BestÃ¤tigung
4. **Clearnet-Fulcrum** â€” Ã¶ffentliche Server ohne Tor (`electrum_servers.json`), nur nach BestÃ¤tigung

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

**Verlaufsscan** (`_try_verlauf_priority_chain` / `_setup_verlauf_client`) â€” eigene Kette, Core liefert keinen Verlauf:

1. Electrs/Fulcrum **LAN** (`get_history`)  
2. Electrs/Fulcrum **Onion**  
3. BIP-158 Compact Filter (Blockwalk/Cache)  
4. Ã¶ffentliche Electrum (nach BestÃ¤tigung)

Ã–ffentliche Electrum-Server erst nach User-BestÃ¤tigung: Web-Dialog, `--oeffentliche-electrum` oder `OEFFENTLICHE_ELECTRUM=1` in `.env`. Sanktions-Scans bleiben Clearnet (Listen-Adressen, nicht Wallet-XPUBs).

Explizit nur per **CLI** (`--bip158`, `--rpc-only`) oder **Einstellungen â†’ Datenquelle wÃ¤hlen**. `BIP158_P2P=1` in `.env` allein erzwingt **keine** Datenquelle â€” die Auto-PrioritÃ¤t bleibt aktiv.

Einzelmodi:

- **Bitcoin-P2P Compact Filter** â€” Peers mit `NODE_COMPACT_FILTERS` (`peerblockfilters=1`)
  - Filter lokal matchen, Block nur bei Treffer
  - TurboSync: ungenutzte Keys nur im jÃ¼ngsten Fenster (`TURBO_WINDOW`), Historie nur already-used
  - Peer-Reihenfolge: Host im LAN (`FULCRUM_HOST`, P2P-Port 8333), dann gemerkte Filter-Peers, dann `BIP158_PEERS`, dann DNS-Seeds mit `x40.` (NODE_COMPACT_FILTERS). Ohne Compact Filter am eigenen Node kein Sprung zu Ã¶ffentlichen Electrum-Servern. LAN-IPs nicht Ã¼ber Tor. Vor dem DNS-Rundlauf: drei parallele TCP-PrÃ¼fungen auf 8333; lauter Timeouts = Firewall, Clearnet entfÃ¤llt. Scheitert Clearnet, folgt Tor: laufender Browser (9150) oder Autostart des `tor`-Binary (`stelle_tor_socks_bereit`, wie beim eigenen Onion-Node).
  - Scan: bis zu 4 Peers parallel fÃ¼r `getcfilters` / TrefferblÃ¶cke; Header-Sync auf Peer 0; UTXO-Stand in HÃ¶henreihenfolge
  - `server.py` startet `starte_header_vorab`: Header ab SegWit in `p2p_headers.bin`, Job `headers` fÃ¼r das Log
  - Mitgeliefertes Archiv `data/p2p_headers_segwit.bin.gz` wird ausgelegt, wenn der lokale Cache fehlt oder hinter dem Archiv-Tip liegt; P2P holt nur den Rest bis zum Tip
  - Matcher: `_CoreBasicFilterMatcher` (nicht `chiabip158`)
  - UTXO-Scan schreibt den Verlaufs-Cache mit (Empfang/Ausgabe aus dem Blockwalk); Merge, kein Ãœberschreiben durch Turbo-PÃ¤sse
- **Fulcrum** â€” `--rpc-only` oder Auto-Kette; eigener Node vs. Ã¶ffentliche Rotation (`FULCRUM_TOR_0`â€¦`9`) nur nach BestÃ¤tigung

**Sanktions-Scans** (Wallet-Check, UTXO-Scan auf Listen-Adressen): immer **Clearnet-Fulcrum** Ã¼ber `build_sanctions_fulcrum_fetchers()` / `resolve_sanctions_clearnet_pool()` â€” unabhÃ¤ngig von der Wallet-Datenquelle. Optional `FULCRUM_SANCTIONS_HOST` in `.env`, sonst paralleler Probe aus `electrum_servers.json`.

### Caches

| Verzeichnis | Art | Inhalt |
|-------------|-----|--------|
| `utxo_cache/` | verÃ¤nderlich | UTXOs pro XPUB, `scan_end_index`, `scanned_addresses`, `external_addresses.json` |
| `utxo_cache/{hash}_alter.json` | First-seen | Wallet-Alter; Ã¼berlebt Danger-Zone-/Cache-LÃ¶schen |
| `immutable_cache/` | unverÃ¤nderlich | `tx/`, `block_header/`, `utxo_ingress/` |
| `sanctioned_cache/` | verÃ¤nderlich | OFAC/OpenSanctions/Scam-Adressen, EntitÃ¤ten, Metadaten |

Caches sind Flatfile-JSON. Beim UTXO-Cache: optional Salden-Check, Light-/Full-Rescan. Die Altersdatei nicht mit dem UTXO-Bestand lÃ¶schen.

**Adress-AuflÃ¶sungs-Cache** (`external_addresses.json` in `--cache-dir`): globale externe Adressen, XPUB-Negative und verifizierte Wallet-Treffer; invalidiert bei anderem XPUB-Set oder kleinerem `max_index`. Verwaltung in `main.py` (`init_external_address_cache`, `WalletContext.resolve_address`).

**Plattenplatz:** `cache_disk_write_allowed()` stoppt Cache-SchreibvorgÃ¤nge nur, wenn **unter 5â€¯% frei und unter 2â€¯GiB** frei (`MIN_FREE_DISK_RATIO` + `MIN_FREE_DISK_BYTES`). `save_xpub_utxo_cache` wirft dann `CacheDiskFullError` statt still nichts zu schreiben.

**Sanktions-Cache** (`sanctioned.py`): `sanctioned_addresses_XBT.json`, `sanctioned_entities_XBT.json`, `sanctioned_address_index.json`, `.meta.json`, optional `sdn_advanced.xml`. Quellen: OFAC 0xB10C, OFAC SDN-XML, OpenSanctions (Israel NBCTF, FBI Lazarus, ransomwhe.re), Badd-Boyz. Israel NBCTF als eine zusammengefasste EntitÃ¤t (`group_mode: collapsed`).

### Adressableitung

Pro XPUB ab Index #0 (Receive + Change), abhÃ¤ngig vom SLIP-132-PrÃ¤fix:

- `zpub` / `vpub` â†’ Native SegWit (BIP84)
- `xpub` / `tpub` â†’ Legacy + Taproot
- `ypub` / `upub` â†’ Nested SegWit

Bibliothek: `embit` (`HDKey`, `script`). Pro XPUB individuelles Scan-Limit Ã¼ber `--max-addresses-per-xpub`.

## Konfiguration (`.env`)

Wichtige Variablen:

```env
WALLET_0_XPUB=zpub6...               # ein Block je Wallet, fortlaufend ab 0
WALLET_NAMES=Wallet A|Wallet B       # pipe-getrennt; oder WALLET_NAME_0 â€¦

# BIP158_P2P=1                 # Compact Filter Ã¼ber P2P (kein Core)
# BIP158_START_HEIGHT=481824   # SegWit
# BIP158_PEERS=                # optional host:port je Zeile

FULCRUM_HOST=...
FULCRUM_TOR=....onion
FULCRUM_PORT=50002
FULCRUM_SSL=true
FULCRUM_TOR_PROXY=127.0.0.1:9150   # nur fÃ¼r .onion-Verbindungen

FULCRUM_TOR_0=....onion      # Ã¶ffentliche Server-Rotation (max. 10)
# OEFFENTLICHE_ELECTRUM=1    # Ã¶ffentliche Electrum-Server erlauben
FULCRUM_SANCTIONS_HOST=...   # optional; sonst electrum_servers.json
# VERBOSE=1                                # volle TxIDs/Adressen (Default: aus)
# WALLETS_IMMER_AKTUELL=1                 # Dauer-Watch (Electrs-Subscribe) + Tip-Nachzug beim Start
# WALLETS_BEIM_START_AKTUALISIEREN=1     # Legacy-Alias fÃ¼r WALLETS_IMMER_AKTUELL
# WALLETS_NUR_BEKANNTE_UTXOS=1           # Tip-Nachzug nur bekannte UTXOs (kein Gap; neue Adressen → UTXO-Scan)
# STEUER_HALTEFRIST_JAHRE=1                # Vorgabe 1 (DE); 0 = keine Frist
# STEUER_STICHTAG=                         # leer = Frist fÃ¼r alle Anschaffungen
```

**Tor-Proxy-Regel:** `FULCRUM_TOR_PROXY` gilt nur fÃ¼r `.onion`-Hosts (RPC und Fulcrum). Bei LAN-IPs (`192.168.x.x`) wird direkt verbunden. Fehlt ein laufender SOCKS, startet `core.tor.stelle_tor_socks_bereit` ein gefundenes `tor`-Binary (Tor-Browser-Ordner oder `TOR_BINARY`) ohne Browser-UI. `TOR_AUTOSTART=0` unterbindet das.

## Konventionen beim Bearbeiten

- **Sprache:** UI, Prompts und Nutzerkommunikation auf **Deutsch**
- **Python:** 3.10+, Standardbibliothek bevorzugen; AbhÃ¤ngigkeiten: `embit`, `chiabip158` (nur Self-Tests)
- **Stil:** Bestehenden Code-Stil beibehalten â€” gleiche Namensgebung, Import-Stil, Docstring-Niveau
- **Scope:** Nur Ã¤ndern, was die Aufgabe erfordert; keine Drive-by-Refactors
- **Secrets:** `.env`, XPUBs, RPC-PasswÃ¶rter, persÃ¶nliche Wallet-Namen nie committen oder in Ausgaben wiederholen
- **Tests:** `py` statt `python` auf Windows; bei Netzwerk-Tests `.env` laden via `_load_dotenv()`
- **TemporÃ¤re Skripte:** `_patch_*.py`, `_test_*.py`, `_profile_*.py` sind Entwicklungs-Hilfen â€” nicht committen
- **Changelog:** CHANGELOG.md bei nennenswerten Änderungen nachziehen — spätestens zusammen mit dem Commit. Neue Punkte unter [Unveröffentlicht]. Sprache Deutsch, Nutzerwirkung vor Implementierungsdetail.
- **Release Notes:** Nicht bei jedem Push auf dev-juniormind. Nur bei **Version-Bump** / Merge nach **main** / **Git-Tag** (…, StartOS-Tag): Abschnitt [Unveröffentlicht] als datierten Block setzen und leeren; optional GitHub-Release-Body = dieser Abschnitt (Inhalt = Changelog seit dem letzten Release). StartOS: wie doc/START9-packaging.md + publish_startos_release.

## Version

- **Datei:** `VERSION` im Repo-Root (aktuell `0.9.2`) â€” einzige Quelle
- **Lesen:** `core.version.version()`, Web Ã¼ber `GET /api/config` â†’ `version`, FuÃŸzeile `vâ€¦`
- **PyInstaller:** `VERSION` in `packaging/satsage-webgui.spec` als data bundeln
- **Bump:** nur Maintainer entscheiden und die Datei ändern; kein Auto-Increment in Scripts/CI. Changelog-Eintrag zum Bump mitziehen; dabei Release Notes wie oben (datierter Abschnitt, Unveröffentlicht leeren).

## Standalone-Build (PyInstaller)

Web-GUI als Onefile-Binary:

```bash
./scripts/build_satsage_macos    # oder _linux
scripts\build_satsage_win.bat    # Windows (py / .venv)
```

Spec: `packaging/satsage-webgui.spec` â†’ `dist/satsage-webgui` (`.exe` unter Windows).  
Assets (`web/`, `data/`, `doc/`) Ã¼ber `resource_dir()`; `.env` und Caches neben der Executable (`app_dir()`).

## Git

**Der Benutzer entscheidet selber, wann er git commit und push machen will.**

### Branches

- main — nur **stabiles**, öffentliches Material (Release-tauglich). Merge egal von wem, aber nur nach Prüfung.
- dev-juniormind — laufende Entwicklung von Juniormind1; hier committen/pushen für Work-in-Progress.
- Andere Contributor-Branches/PRs: nach Review in main mergen, wenn stabil; nicht ungeprüft aus dev-* übernehmen.

### Commit-Identität (Maintainer / Assistent)

**Maintainer-Clones und Assistenten-Worktrees** committen/pushen nur unter der Projekt-Identität:

- `user.name=Juniormind1`
- `user.email=juniormind@proton.me`

Pflicht in diesen Clones:

```bash
git config user.name Juniormind1
git config user.email juniormind@proton.me
git config core.hooksPath githooks
```

Hooks in `githooks/` (`pre-commit`, `pre-push`) blockieren abweichende Identitäten **in diesen Worktrees**. Assistenten müssen vor jedem Commit die **lokale** Repo-Config prüfen.

**Fremde Contributor-Commits und PRs:** eigene Autor-/Committer-IDs sind erlaubt (übliche OSS-Praxis). CI verlangt nicht „jeder Commit = Juniormind1“. Merge nach `main` weiter nur nach Prüfung (siehe Branches).

Assistenten sollen:

- Änderungen vorstellen und testen, aber **nicht** automatisch committen oder pushen
- Nicht nach jedem Task „Soll ich committen/pushen?“ fragen
- Auf ausdrückliche Anweisung des Benutzers warten (`commit`, `push`, o. ä.)
- Vor Commit/Push: lokale `user.name`/`user.email` verifizieren; bei Abweichung abbrechen und korrigieren

### Merge-Dealbreaker

Harte und weiche Kriterien gegen riskante Merges (Malware/Trust, Secrets, CI, Produkt-Semantik): [`doc/merge-dealbreakers.md`](doc/merge-dealbreakers.md). Assistenten und Reviews sollen diese Liste kennen; CI deckt sie schrittweise ab (zuerst u. a. Unittests).

## Sicherheit & Datenschutz

- XPUBs erlauben Ableitung aller Wallet-Adressen — sensibel behandeln; keine Seed/xprv/WIF-Eingabe in SatSage (Dealbreaker T1 in `doc/merge-dealbreakers.md`)
- Lern-URLs / Kaninchenbau: nur Bitcoin-only-Content für Plebs (Mechanismen, keine SatSage-Internals); Shitcoins/Eth im Zweifel warnen (Dealbreaker T13)
- Wallet-Namen in `.env`, `utxo_cache/` und `immutable_cache/utxo_ingress/` können Klarnamen enthalten — nicht committen
- Git-Commit-Metadaten (Autor/E-Mail) sind bei `push` öffentlich sichtbar
- Fulcrum (öffentliche Onions/Clearnet): mäßig (Rotation mildert Risiko); öffentliche Server und Remote-LLM nur nach Opt-in
- Eigener Node (BIP-158 / eigener Fulcrum): Privatsphäre **hoch** (`privacy_notice_for_source`, `is_own_fulcrum_backend`)
- Keine Telemetrie / kein XPUB-Upload an Fremde; Web-UI ohne Remote-JS (Dealbreaker T3/T6)
- Sanktions-UTXO-Scans nutzen Clearnet-Fulcrum (nur Listen-Adressen, nicht Wallet-XPUBs)

## UI-Konventionen

- **Node verbinden:** Leitbild in `doc/design-node-anbindung.md` â€” dem Nutzer den Node so einfach wie mÃ¶glich machen; typische Heimnetz-/TLS-/Port-Fallen selbst abfangen; HÃ¤rte nur wo nÃ¶tig (Clearnet, Opt-in), nicht als Kollateralschaden auf Desktop-LAN oder Start9-Bridge.
- **FlÃ¼chtigkeit / Eile:** Leitbild in `doc/design-fluchtigkeit.md` â€” von unaufmerksamem, eiligem Nutzer ausgehen; gefÃ¤hrliche ZwischenzustÃ¤nde unmÃ¶glich machen (nicht nur beschriften). Beispiel Empfangs-QR: bei Wallet-Wechsel sofort entwerten, erst wieder zeigen wenn die Adresse des neuen Wallets feststeht.
- **Neugier / Lernen nebenbei:** Leitbild in `doc/design-neugier.md` â€” unwissend und lernfaul, aber neugierig; bevorzugt native Tooltips (`title` / `data-i18n-title`): Eilige sehen sie nicht, Neugierige spielen „Wo ist Walter?“ mit der GUI. Kein Widerspruch zur FlÃ¼chtigkeit: Hinweise ergÃ¤nzen Absicherung, ersetzen sie nicht.
- **Verbose:** Default `nein` (`VERBOSE` in `.env` oder Einstellungen [4]); gekÃ¼rzte TxIDs/Adressen
- **BetrÃ¤ge:** `format_sats` â€” â‰¤100â€¯000 sats als sats, darÃ¼ber BTC mit 2 Dezimalstellen
- **Lange Listen:** `cancellable_output` â€” `q` zum Abbrechen (nur interaktives TTY)
- **Log-Bereich (Web):** Sparsam, wenn Verbindungen stehen und das Tool arbeitsbereit ist; gesprächig bei Hochfahren, Problemen, Verbindungsabbrüchen unter kritische Werte (z. B. < 3 Compact-Filter-Peers) oder Privatsphäre-Änderung. Eine Zeile kündigt den nächsten Schritt an, **bevor** er losläuft (Erwartungsmanagement, z. B. Tor) — Ergebnis danach. Gleicher Strom (`on_log` / NDJSON); nach ~10 s Stille: „Moment noch“. Wallet-Aktionen: Name nach der Uhrzeit. Richtlinie: [`doc/logging-richtlinie.md`](doc/logging-richtlinie.md).
- **Web-UI prÃ¼fen:** Ã„nderungen an `web/` oder gerenderten API-Daten im Browser durchklicken, nicht nur am Render festhalten.

## Specter Desktop Plugin (Testumgebung)

**Pfad:** `specter_plugin/` â€” editierbares Package `satsage.specterext.satsage`  
**Nutzer-Doku:** `specter_plugin/README.md` und Abschnitt in `README.md`  
**Nicht** `main.py` als CLI in der Plugin-Runtime starten â€” Specter hostet die Extension (Flask).

### Zweck

Specter liefert **Wallets/XPUBs**, den **aktiven Node** und **UTXOs/Txs** in-process. Die Extension baut daraus denselben Analyse-Stack wie die CLI (`WalletContext`, BIP-158/Fetchers, `analyze_*`) und zeigt die Ausgabe im Browser.

### Modul-Ãœbersicht

| Datei (unter `src/satsage/specterext/satsage/`) | Verantwortung |
|----------------------------------------------------|---------------|
| `service.py` | Extension-Metadaten (`id=satsage`, `devstatus=alpha`, Blueprint) |
| `bridge.py` | `build_context(specter)` â†’ `SatSageContext` (Wallets, Keys/XPUBs; kein Core-RPC mehr) |
| `specter_session.py` | Session-Lifecycle: Path zu Repo-Root, `build_wallet_context`, Seed aus Specter, `_setup_blockchain_client` / `_build_blockchain_fetchers`, `run_analyze_*` |
| `controller.py` | Flask-Routes: `/`, `/wallets`, `/wallet/<alias>`, `/analyze`, `/context.json`, `/reload` |
| `config.py` | Extension-Keys `SATSAGE_SHOW_SENSITIVE`, `SATSAGE_PREVIEW_LIMIT` (nicht in Server-Config duplizieren) |
| `app_config.py` | `DevConfig` / `ProdLikeConfig`: `EXTENSION_LIST`, API an, `SERVICES_LOAD_FROM_CWD=False` |
| `templates/satsage/*.jinja` | UI (Ãœbersicht, Wallets, Analyse-Formulare, Ergebnis-Plaintext) |

### Anbindung an SatSage-Core (`main.py` / `analyze.py`)

`specter_session.py` setzt `sys.path` auf das **Repo-Root** (`parents[5]` von der Session-Datei) und importiert:

- `main._load_dotenv`, `build_wallet_context`, `seed_wallet_addresses_*`, `init_external_address_cache`
- `main._setup_blockchain_client`, `_build_blockchain_fetchers`, `privacy_notice_for_source`
- `main.save_xpub_utxo_cache`, `list_top_wallet_utxos`
- `analyze.analyze_tx`, `analyze_address_utxos`, `trace_known_utxos`

Ablauf Session-Setup:

1. `bridge.build_context` â†’ XPUBs + Node
2. `_merged_env`: Repo-`.env` als Basis, Specter-`env_like` Ã¼berschreibt; bei Core-Node `BITCOIN_BIP158=1`
3. `build_wallet_context` + Seed Adressen/UTXOs aus Specter + UTXO-/Resolution-Cache
4. Blockchain-Client (Auto: eigener Electrum-Server, sonst P2P-BIP-158)
5. Specter-UTXOs â†’ `save_xpub_utxo_cache` (Light-Seed, kein Full-Rescan)
6. Cache unter Repo-Root: `utxo_cache/`, `immutable_cache/`

Session ist **gecacht** (`context_fingerprint` aus Node+Wallets); UTXOs werden bei Reuse frisch aus Specter geholt. Force: Route `/reload`.

### UI-Routen

| Route | Funktion |
|-------|----------|
| `/svc/satsage/gui` | Volle Web-GUI (`server.py`+`web/`) per iframe; Specter-Wallets via `gui_server.py` |
| `/svc/satsage/` | Ãœbersicht + Session-Info |
| `/svc/satsage/wallets` | Wallet-Liste |
| `/svc/satsage/wallet/<alias>` | Detail (UTXO/Tx-Preview) |
| `/svc/satsage/analyze` | Formulare: `mode=tx\|utxo\|rank\|trace_top` (Legacy-Plaintext) |
| `/svc/satsage/context.json` | JSON-Export des Bridge-Kontexts |
| `/svc/satsage/reload` | Session neu aufbauen |

Analyse-Ausgabe: stdout von `analyze_*` wird per `capture_output` abgefangen und als Text in `analyze_result.jinja` gerendert (kein interaktives MenÃ¼).

### Dev-Start

```bash
cd specter_plugin
./scripts/setup_dev.sh          # venv, cryptoadvance.specter, pip install -e .
./scripts/run_bitcoind_regtest.sh   # optional
./scripts/run_specter.sh        # http://127.0.0.1:25441
```

Scripts: `unit_bridge.py` (offline), `probe_api.py` (REST JWT). Daten: `specter_plugin/.specter_dev/` (gitignore).

### Konventionen Plugin

- **Sprache:** UI-Texte Deutsch (wie CLI)
- **Keine Secrets** in Templates/Logs; `to_dict(include_secrets=â€¦)` default maskiert
- `SERVICES_LOAD_FROM_CWD=False` + Extension nur Ã¼ber `EXTENSION_LIST` â€” sonst doppelte Blueprint-Registrierung
- Extension-Config-Keys **nur** in `config.py`, nicht in `app_config.DevConfig` (Specter verbietet Override bestehender Keys)
- Core-Ã„nderungen an Analyse/Fetchers in `main.py`/`analyze.py` â€” Plugin nur Adapter; bei API-Break der `main._*`-Internals Session anpassen
- **Nicht** automatisiert committen; `.specter_dev/`, `.venv/`, `.run/` lokal

## Typische Aufgaben

- **Bei unklarer Benutzervorgabe** Die Unklarheit prÃ¤zise beschreiben und durch gezielte Fragen an den Benutzer klarstellen lassen
- **Neue Analyse-Funktion:** Logik in `analyze.py`, Prompts in `interact.py`, MenÃ¼punkt in `menu.py`; Web: Route in `server.py` + `web/app.js`; im Plugin optional `specter_session.run_*` + Route/Template in `controller.py`
- **Neues Backend:** Fetcher in Backend-Modul, Anbindung in `main._setup_blockchain_client()` und `_build_blockchain_fetchers()`
- **BIP-158:** P2P in `core/p2p.py` + `bip158_scanner.py`; kein Core-RPC. Turbo-PÃ¤sse in `plane_filter_passes`
- **Steuerjahr:** `core/tax.py`; Einstellungen `STEUER_HALTEFRIST_JAHRE` / `STEUER_STICHTAG`; Web-Ansicht in `web/app.js`
- **Fulcrum/Tor:** `fulcrum.py`, `check_fulcrum_tor.py`, `.env`-Variablen, `electrum_servers.json`
- **Adress-AuflÃ¶sung:** `WalletContext`, `external_addresses.json` in `main.py`
- **Sanktionslisten:** `sanctioned.py` (Quellen, Parser, `update_sanctioned_lists`), MenÃ¼ in `menu.py` (Punkt 6); Ãœberblick mit `print_sanctions_overview`, danach `check_sanctions_source_updates` + j/N-Aktualisierung
- **Specter-Plugin:** Bridge (`bridge.py`) fÃ¼r neuen Specter-Kontext; Session (`specter_session.py`) fÃ¼r Runtime; UI in `controller.py` + Jinja; Core-API stabil halten (`build_wallet_context`, `_setup_blockchain_client`, `analyze_*`)
- **StartOS `.s9pk`:** nicht neu scaffolding. Wrapper ist `packaging/` auf `main`. Anleitung `doc/START9-packaging.md`. Bauen `./scripts/build_startos_s9pk` (x86). App-HÃ¤rtung nicht im Wrapper duplizieren.

## Regtest-Lab

Die portable Docker-/Linux-Anleitung liegt unter `lab/regtest/README.md`. `.data/` und Lab-Env bleiben lokal und sind nie zu committen.
