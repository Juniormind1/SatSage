# Changelog

Alle nennenswerten Änderungen an SatSage.  
Neue Einträge oben. Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

**Release Notes:** GitHub-/Tag-Release-Texte entstehen nur bei Version-Bump, Merge nach `main` oder Tag — Inhalt = der dann datierte Block aus `[Unveröffentlicht]` (nicht bei jedem Dev-Push).

**Herkunft:** Die datierten Abschnitte ab `2026-07-08` stammen aus dem privaten Vorgängerprojekt **xPubQuery** (lokale Kopie unter PyCharmProjects) und wurden unverändert übernommen — in der gesamten Changelog-Historie dort kamen **keine** Klarname-Einträge ( o. Ä.) vor; Maintainer-Bezug ist durchgängig die Projekt-Identität **Juniormind1**. Ab dem Marker **2026-09-08** gilt die öffentliche SatSage-Historie.

## [Unveröffentlicht]

- **Aktualität · Nur bekannte UTXOs:** Unteroption zu „Wallets immer aktuell halten“ — Tip-Nachzug (Start, neuer Block, „Bis Tip“) prüft nur bekannte UTXOs/Adressen, **kein Gap-Scan**. Neue Empfangsadressen dann per manuellem UTXO-Scan. `.env`: `WALLETS_NUR_BEKANNTE_UTXOS`.
- **Wallets · Öffnen:** Mempool-Pending-Check über eigenen Electrs prüft nur noch die geöffnete Wallet — nicht mehr `listunspent` über alle Adressen aller anderen Wallets. Öffnen eines kleinen Wallets (z. B. 1 UTXO) blieb sonst ~2 s hinter dem Querschnitt stecken; Herkunft (alle UTXOs) unverändert.
- **Wallets · Erst-Paint:** Wallet-Ansicht lädt zuerst nur den Cache (`mempool=0`), zeichnet sofort, und zieht Pending/Mempool danach im Hintergrund nach — Wallets mit vielen Adressen (z. B. 9× `listunspent`) blockieren den Wechsel nicht mehr ~1 s.
- **Wallets · Sync-Hinweis:** Gelber Kurztext während Tip-Nachzug heißt jetzt „aktualisiere…“ statt „aktualisiert…“ — klar als laufender Vorgang, nicht als fertiger Zustand.
- **UTXO-Scan · xpub+auto:** Gap-Scan prüft pro Index alle Skriptformen (Legacy/Nested/SegWit/Taproot), nicht nur die erste (Legacy). Sonst findet z. B. Wasabi-SegWit unter generischem `xpub` keine UTXOs, obwohl welche da sind. `scantxoutset` splittet Mehrpfad-Deskriptoren `…/<0;1>/*` in Empfang/Change.
- **Wallets · Wasabi WPKH-Policy:** Single-Sig-Deskriptoren (`wpkh([…/84h/…]xpub/<0;1>/*)`, auch mit Prüfsumme) werden als normales Wallet gespeichert und analysiert — nicht mehr fälschlich als Multisig ohne Bestand. Paste ins XPUB-Feld wird erkannt und in den Deskriptor-Import umgeleitet; Specter-DIY `/{0,1}/*` wird auf Core `/<0;1>/*` normalisiert.
- **Herkunftsbaum · lazy Rendern:** Erste Ebene unter dem UTXO bleibt sofort sichtbar; tiefere Zweige werden erst beim Aufklappen ins DOM gebaut (große CoinJoin-/Remix-Bäume sonst tausende Knoten auf einmal).
- **Herkunft · Mix-Icon-Tooltip:** Hover zeigt wieder die CoinJoin-Art (Soft-Label), nicht „Zweig auf- und zuklappen“ — Klapp-Hinweis nur noch am Pfeil.
- **StartOS · Build:** `npm ci` braucht `packaging/package-lock.json`; Select-Indexer-i18n-Keys und `dependencies.ts`-Typen so, dass `tsc`/`make x86` wieder durchlaufen. Build-Skripte ausführbar (`+x`).

## [0.9.1] - 2026-09-11

- **Version:** 0.9.1 — Pflege-Release: CoinJoin-Herkunft (Soft-Labels/Icons, Own-only-Walk), Marke Pfeiffe-Icon, Core-Rollen UTXO vs. Lookup, Kurs-Historie/Onion-Latenz, Steuerjahr- und Herkunfts-UI.
- **Marke · Pfeiffe-Icon:** Favicon, Kopf-Mark, Apple-Touch und Packaging-Icon stammen aus `Pfeiffe-Icon.jpg` → transparente PNG (`web/img/pfeiffe-icon.png`, Schwarz = Vordergrund) via `scripts/prepare_brand_assets.py`. Splash bleibt das volle Logo.
- **Herkunft · Mempool-Link:** Am Herkunftsbaum öffnet ↗ die **Transaktion** (VIN/VOUT), sobald `from_utxo`/`txid` da ist; `/address/…` nur an reinen Adresszeilen. Tooltip nennt das Ziel.
- **Herkunft · Mix-Icons:** Soft-Labels Wasabi / WabiSabi / Whirlpool / JoinMarket mit farbigen Form-Icons (Mempool-Stil) in der Herkunftszeile; an Adressgruppen nur die Icons (ohne Text), wenn gespeicherte Bäume Mix-Formen enthalten — kein Extra-Scan.

- **Herkunft · gezielte Suche:** Nach Trace zeigt die Kopfzeile den **Output-Betrag** (und Adresse) des gewählten `txid:vout` — nicht dauerhaft „0 sats“.
- **Herkunft aller UTXOs:** Ohne UTXO-Bestand: Bestätigungsdialog — OK startet UTXO-Scan aller Wallets, danach automatisch die Herkunft (Abbruch möglich); kein falsches „schon erledigt“ mehr.
- **Lab · CJ-Peers:** Mix-Fixtures nutzen `lab-faucet` als Fremd-Inputs (Funding-Quelle, nicht in SatSage `WALLET_*`); Viewer nur mit eigenen Anteilen — kein Fan-Out-Fehllabel mehr bei Wasabi/WabiSabi.
- **Herkunft · Mix-Form vor Fan-Out:** Klar erkennbare CoinJoin-Form (Wasabi/WabiSabi/…) behält das Soft-Label auch wenn alle Inputs eigene XPUBs sind (Multi-Wallet/Lab) — kein Fehl-Label „eigene Auszahlung“.
- **Lab · mempool.space:** Regtest-Docker startet lokalen Explorer unter `http://127.0.0.1:18080` (API + MariaDB + Frontend); `MEMPOOL_URL` in der Lab-`.env` zeigt darauf — Tx-Form (z. B. Whirlpool 5×5) im Browser prüfbar.
- **Herkunft · kompaktere Knoten:** Soft-Label („Wahrscheinlich …“) rechts neben Timestamp; externe Enden kurz als „Externer Eingang“ in der TxID-Zeile statt Extra-Notiz.
- **Herkunft · CoinJoin-Klassifikation:** Soft-Labels („Wahrscheinlich Wasabi-CoinJoin (Classic) / WabiSabi / Whirlpool / JoinMarket“, PayJoin, Exchange-Batch, eigener Fan-Out). Bei erkanntem Mix nur **eigene** Inputs weiterverfolgen — Peer-Adressen nicht mehr als „Herkunft von extern“. Lab-Fixtures + `verify_tx_classify.py`. Whirlpool-Ketten (Remix × n) bleiben Folgepunkt.
- **Marke · Sherlock-Pfeife:** Web-Kopf, Login, Favicon und Packaging-Icon nutzen einen Ausschnitt aus `satsage-head.png` mit Fokus auf die **stilisierte Pfeife** (nicht die Hutkrone), abgeleitet über `scripts/prepare_brand_assets.py` — nicht mehr das Sat-Symbol. Splash bleibt das volle Logo.
- **Datenquellen · Onion-Latenz-Gate:** Beim Setup öffentlicher Onion-Electrs eine kurze Probe-`get_history`; bei Überschreitung (Default 8 s, `PUBLIC_ONION_LATENCY_SECONDS`) BIP-158 bevorzugen, wenn Peers da sind — sonst klare Warnung „wird langsam“ und interaktiv Abbruch. Nur Auto-Priorität (nicht `--rpc-only`); kein Quellenwechsel mitten im Scan.
- **Kurs · Spot-Log:** Heutiger Tageskurs aus Historie erzeugt keine Warnung mehr („Realtime fehlt“); Hinweis nur bei wirklich älterem Historien-Tag, und höchstens einmal pro Session.
- **Core · Tx/Block-Rollen:** Bei BIP-158-Lookup zuerst lokaler Core solange Höhe > ``pruneheight``, sonst Lookup-Core (Start9); optional ``getblock``. Mit Electrs/Fulcrum bleibt Electrs primär — Core nur, wenn Electrs die Tx nicht liefert.
- **Kurs-Historie · Release bis Tip:** ``scripts/refresh_btc_price_bundle.py`` aktualisiert ``data/btc_price/{EUR,USD}.csv`` aus Bitstamp/CDD vor PyInstaller- und StartOS-Builds (macOS/Linux/Win-Scripts + CI). Offline: ``SKIP_BTC_PRICE_REFRESH=1``. Bundle im Repo jetzt bis 2026-09-11 nachgezogen.
- **Kurs-Historie · täglicher Lücken-Nachzug:** Einmal pro UTC-Tag prüft ein Hintergrundlauf, ob EUR/USD hinter gestern zurückliegen. Mit ``SATSAGE_PRICE_HISTORY_OPT_IN=1`` (Datenquellen → BTC-Kurse) wird die Bitstamp-Tages-CSV von CryptoDataDownload geholt, 4 Wochen überlappt (Median |Δ| > 1,5 % → neuere Serie + Log), bei Kurssprung 7-Tage-Smoothing. Schreibt nur ``immutable_cache/btc_price/``. Knopf „Jetzt nachziehen“. Startet **erst nach** „Server bereit“/GUI (ca. 45 s Verzögerung) — nicht im Splash neben Header/Wallet-Sync.
- **Kurs · Spot-Fallback:** Scheitert der Live-Spot (Opt-in/Netz), wird zuerst der heutige Tageskurs (Historie-API/CSV) versucht, sonst der **letzte lokale Historien-Tag** — auch wenn das Bundle älter als 14 Tage ist. Log: eine kurze Zeile *„aktueller Kurs nicht beschaffbar, letzter Kurs aus Historie von … wird verwendet“* statt der langen Opt-in-/Pipe-Fehlermeldung.
- **Core-Rollen · UTXO-Set vs. Tx/Block-Lookup:** Eigener Env-Slot ``UTXO_RPC_*`` für ``scantxoutset`` (lokaler pruned Node); ``NODE_IP``/``RPC*`` bleibt Lookup (Start9). Lokaler bitcoin-qt füllt den UTXO-Slot still **in die .env** (+ ``BIP158_HOST``, ohne ``BIP158_P2P`` zu erzwingen). **Priorität Bestand:** Electrs/Fulcrum-LAN vor scantxoutset (auch vor lokalem Slot); ohne LAN-Electrs scantxoutset über ``UTXO_RPC_*`` vor Lookup-Core. Datenquellen-UI: „UTXO-Set-Quelle“ / „Tx/Block-Lookup“.
- **Steuerjahr · Selbstanzeige-Kandidaten:** Beim Öffnen der Ansicht und beim Jahreswechsel automatisch aus dem Cache geladen (kurzer Log-Hinweis). Der frühere Pflicht-Knopf „Kandidaten laden“ heißt jetzt **Aktualisieren** (z. B. nach Verlaufsscan oder mit Einzahl-TxID-Filter).
- **Bereits ausgegeben · Beschriftung:** Die Satoshi-Summe heißt jetzt **Gesamtvolumen** (kein Saldo) — z. B. „42 Vorgänge · Gesamtvolumen 1,23 BTC“. Tooltip erklärt: Summe der Nennwerte ausgegebener Outputs. In der Kopfzeile **kein Spot-€** mehr auf dem Brutto-Volumen (sonst wirken alte Ausgaben wie heutiger Reichtum); € zum Tageskurs am Ausgabedatum bleibt an den Adress-/UTXO-Zeilen.
- **Steuerjahr · Phantom-Unspent:** Verlaufseinträge ohne `spent`, die nicht im aktuellen UTXO-Cache stehen, zählen nicht mehr zum Bestand (häufig Ursache für aufgeblähtes „außerhalb Haltefrist“). Abgänge bleiben; Hinweis in der Auswertung.
- **Steuerjahr · Bestand gesamt:** Ausgegebene Verlaufs-Outputs ohne Abgangsdatum (`spent` ohne `spent_time_ts`) zählen nicht mehr zum Bestand — verhindert aufgeblähte Summen (z. B. 1,89 BTC aus Historie). Hinweis in der Auswertung.
- **Electrum-UTXO-Scan · Tip:** Nach erfolgreichem Fulcrum-/Electrum-Fullscan wird `scan_tip_height` (Chain-Tip) und „Bestand am Tip“ (`bip158_fullscan_ok`) gesetzt — Folgeläufe per P2P können Tip-Nachzug statt Erstscan.
- **Datenquellen · öffentlich nach P2P-Kappen:** Keine gelbe „Verbindung im Aufbau…“ mehr an Onion/Clearnet, wenn Opt-in aus oder Hoch-Privatsphäre Vorrang hat — nur noch grau/ungenutzt.
- **Verlaufsscan · kein Doppel-Gap:** Liegt ein frischer UTXO-Cache vor (≤2 h, kein unvollständiger BIP-158-Lauf), überspringt der Verlauf den erneuten Bestands-Scan und nutzt den Cache — Log: „UTXO-Cache frisch — Gap-Scan übersprungen“.
- **Doku · Testprotokoll Datenquellen-Wechsel:** `doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md` — Härtung gegen Quellenwechsel während UTXO-/Verlaufs-Scans (P2P ↔ Electrum, Queue, Cache-Flags, GUI).
- **Clearnet-Electrum · Opt-in:** `OEFFENTLICHE_ELECTRUM=1` (Dialog-Bestätigung) gilt auch als Outbound-Freigabe für Fulcrum-Clearnet — sonst blockierte die Allowlist alle öffentlichen IPs trotz erlaubter Electrum-Nutzung.
- **Verlaufsscan · öffentliche Onion:** Feinerer Fortschritt (Adresse n/m · get_history/Tx i/j), Socket-Timeout auch nach Connect, Rotation wechselt bei Timeout zum nächsten Server — weniger stummes „Moment noch“ bei hängendem Peer.
- **Wallet · UTXO-Scan-Knopf:** Nur gesperrt, wenn wirklich dieses Portfolio scannt oder in der Queue steht — nicht wegen abgebrochenem Lauf, stale Job-Bindung oder globalem Tip-Nachzug. Abbrechen gibt den Knopf sofort frei.
- **Wallet · Scan-Abbrechen:** Knopf rechtsbündig in der Lauf-Leiste — springt nicht mehr mit der Textlänge.
- **Datenquellen · Bezeichnung:** Öffentliche Electrum nicht mehr als „Peers“, sondern **onion-electrs** / **clearnet-electrs** (Kopf, Wechsel-Log, Verbindungstest).
- **Datenquellen · P2P an + öffentlich:** Nach erfolgreichem P2P-Aufbau Dialog „Höhere Privatsphäre?“ — optional öffentliche Electrum-Nutzung kappen (langsamerer Fallback). Solange geprüft wird: Pille **Verbindung im Aufbau…**, danach verbunden/nicht erreichbar. Bei aktiver höherer Quelle kein stale „verbunden“ an Onion/Clearnet.
- **Datenquellen · P2P-Papierkorb:** Schaltet „P2P aufbauen“ wirklich aus (`BIP158_P2P=false`), räumt Live-Peer-Anzeige und `sources_last` — gleichwertig zum manuellen Schalter; nächste Quelle (z. B. Onion) greift.
- **P2P · Abbruch vs. Turbo:** UTXO-Zwischenstände nach abgebrochenem BIP-158-Scan deaktivieren Turbo-Erstscan nicht mehr. Flag `bip158_fullscan_ok` erst nach vollständigem Fullscan; bis dahin gilt wieder Turbo + Gap-Historie.
- **P2P · Startdatum-Dialog:** Fragt wieder bei BIP-158-Erstscan ohne First-seen — auch wenn ein eigener Electrum/Core nur *konfiguriert*, aber nicht verbunden ist (früher blockierte `autoQuelle` den Dialog).
- **P2P · Erstscan (TurboSync):** Ohne used-Keys zuerst nur das Turbo-Fenster (~2016 Blöcke) mit voller Lookahead-Menge, danach Historie nur mit Gap/Hits — nicht mehr alle Keys × SegWit…Tip. cfilter-Disk-Cache unter `immutable_cache/cfilter/` (Höhe+Blockhash). Filter-Match und Block-Download entkoppelt (eigene Block-Worker bei ≥2 Peers). Start: First-seen − Reorg-Puffer; SegWit nur als Default ohne besseren Hinweis.
- **Datenquellen · Status:** Grüne Pille heißt jetzt **verbunden** (EN: *Connected*) statt „erreichbar“. Privatsphäre mäßig/gering bleibt grau, solange nur die Serverliste geladen ist; gelb/rot erst bei bestehender und genutzter Verbindung (nicht von Hoch-Privatsphäre verdrängt). Papierkorb hinter „Von Electrum laden“ löscht Onion-/Clearnet-Listen, Opt-in bleibt.
- **Datenquellen · P2P:** Papierkorb neben dem Stift schaltet Compact Filter aus (`BIP158_P2P=0`). Im Bearbeiten-Dialog Checkbox **P2P aufbauen** — nur wenn aktiv, ist P2P in der Priorität; sonst greifen geladene öffentliche Listen (nach Opt-in).
- **Kopf · Pillen-Texte:** Keine Roh-i18n-Keys mehr beim Start (`P2P n` / Fallbacks); während Verbindungsaufbau **Privatsphäre unklar**. Letzter Quellen-Check bleibt im Server für `/api/config` — Browser neu öffnen baut die Pillen nicht mehr „von null“ auf; stiller Peer-Nachcheck statt lautem Verbindungstest.
- **Log · P2P-Peers:** Pro neu entdecktem Compact-Filter-Peer eine Zeile `Verbunden. Compact-Filter-Peer …` (pro Serverlauf); kein Kandidaten-/Fehlschlag-/Summen-Spam beim Peer-Check.
- **Log · Header/Peers:** Peer-Takt startet keinen Header-Nachzug mehr. Unveränderter Tip bleibt still. Peer-Erfolge werden bis **3** Peers gemeldet (danach Stille); vor Tor-Fallback klare Ankündigung, damit die GUI nicht „eingefroren“ wirkt.
- **Log · Peer-Wechsel:** Meldung nutzt den letzten korrekten Stand — nicht mehr die kurze Tor-Probe (oft „2 Peers“) als Ausgang vor Live-Scan-Peers.
- **Prozess · Log-Richtlinie:** `doc/logging-richtlinie.md` — sparsam wenn arbeitsbereit, gesprächig bei Problemen/Privatsphäre-Wechsel; in `AGENTS.md` verankert (Vertrauen für Erstnutzer + Fehlersuche).
- **Prozess · Merge-Dealbreaker:** Liste in `doc/merge-dealbreakers.md` (Malware/Trust, Secrets, CI, Produkt); in `AGENTS.md` verankert. Contributor-IDs erlaubt; Juniormind1-Pflicht nur für Maintainer-/Agent-Clones.
- **CI · Unittests:** Workflow `.github/workflows/test.yml` läuft auf Push/PR nach `main` und `dev-juniormind` (sowie manuell) — `unittest discover` unter `tests/`, ohne Regtest/E2E/Chaos. Suite an i18n-/Tor-/Peer-/Windows-chmod-Verhalten angepasst (grüne Suite vor CI-Schutz).
- **Tests · Isolation:** Peer-Status-Tests blenden Live-BIP-158-Peers aus; Tor-Autostart respektiert leeres `env={}`; eingebetteter Server weicht bei belegt wirkendem Port auch unter Windows aus; Ollama-Live nur mit `qwen2.5:7b`.
- **Kopf · Quellen-Pillen:** Kein Katalog ungenutzter Quellen mehr — nur aktive, im Aufbau oder fehlerhafte Verbindungen (Core / P2P n / Electrum privat / Electrum öffentlich). Privatsphäre als eigene Pille (hoch / mittel / keine Privatsphäre); ohne Live-Verbindung (nur Cache) zählt als hoch.
- **Wallets immer aktuell:** Electrs-Watch reconnectet nach Verbindungsabbruch wieder (früher beendete `on_disconnect` den Watcher dauerhaft → über Nacht „vor N Std. −M Blöcke“). Tip-Nachzug während laufendem Job wird vorgemerkt; Electrs-Light setzt `scan_tip_height` auf den **Live**-Electrs-Tip (`force`), nicht nur auf ggf. veraltete `p2p_headers.bin`.
- **Wallets · Cache-Dashboard:** Vor der Danger Zone zeigt die Oberfläche Belegung (Platte, UTXO/Immutable/Tx/Herkunft/Header/Sanktionen) und pro Wallet UTXOs, Tip-Lag, Gap, Verlauf und Herkunfts-Abdeckung — nur Größen/Abdeckung, keine Zugriffszähler (`GET /api/cache/stats`).
- **CI · Linux-Webgui:** Manueller Workflow `build-linux-webgui.yml` (ubuntu-latest, x86_64) baut PyInstaller-Onefile und hängt es an ein bestehendes Release an — mit Hinweis *GitHub-Build für Linux, ungetestet*.
- **Prozess · Release Notes:** Nur bei Version/`main`/Tag aus `[Unveröffentlicht]` datieren; nicht bei jedem Push auf `dev-juniormind` (in `AGENTS.md` verankert).
- **Desktop · lokaler Bitcoin Core:** Erkennt Default-Datadir/Cookie + Loopback-RPC; Opt-in per Datenquellen-Banner oder `LOCAL_CORE_OPT_IN=1` (kein stilles Verbinden). Setzt RPC **und** `BIP158_HOST` (P2P Prefer-Peer). Pruned bleibt für scantxoutset nutzbar. Sonderfälle in `ISSUES.md`.
- **Cache · SQLite-Hinweis:** Ab 10 000 JSON-Dateien in `immutable_cache/tx` oder `utxo_ingress` einmalig im Log: *Cache wächst — sqlite ab jetzt sinnvoll* (GitHub-Issue erbeten). SQLite-Umbau weiter zurückgestellt bis nach CoinJoin-Verfolgung.
- **Specter-Plugin · Cache-Seed:** Aus Specter kommen Node/Electrum und Wallets (managed); zusätzlich UTXOs, Verlaufs-Merge, Adress-Labels und Scan-Indizes in die SatSage-Caches (`specter_seed.py`) — ohne doppelte Einrichtung.
- **Start9 · Fulcrum-Indexer (Vorbereitung):** Action **Select Indexer** (Electrs oder Fulcrum), conditional Dependencies, Bridge auf Port 50001; App meldet `electrum_indexer` / Hinweis. Design: `doc/START9-fulcrum-indexer.md`. Sideload-Bau/Geräte-Verify noch offen.
- **Lab · Sanktions-Hops:** Pseudo-Liste + Ketten 1/10/25/100 Hops (und Clean) im Regtest; `SANKTION_MAX_HOPS_CAP` für Lab bis 100; GUI mit `--sanctions-dir` unter `.data/sanctioned_cache`. On-Chain-Verify grün (TP bei exakter Hop-Tiefe, Clean ohne False Positives).
- **Lab · bitcoind-Start:** Windows startet bitcoind per WMI (`Win32_Process.Create`), damit der Node das Shell-Job-Object überlebt — sonst war die Chain nach Generator-Abbruch weg.
- **Sanktionen · Regtest-Adressen:** Listen-Parser akzeptiert `bcrt1`/`tb1` neben `bc1` (Lab-Pseudo-OFAC).
- **Sanktionen · eigener Node:** Pool-Öffnung prüft nicht mehr Mainnet-Höhe 500k — Regtest/LAN-Fulcrum fällt sonst fälschlich auf Clearnet zurück.
- **Lab · Hop-Generator:** `raw_spend` ohne Change → Fee = Rest; Ketten reichen jetzt Input−kleine Fee weiter (kein `maxfeerate`-Abbruch). Mining gebündelt.
- **Git · Identitäts-Härtung:** `githooks/pre-commit` und `pre-push` erlauben ausschließlich `Juniormind1 <juniormind@proton.me>` (Allowlist). Aktivierung: `git config core.hooksPath githooks`. In `AGENTS.md` verankert.
- **README · Marke:** Logo (`web/img/logo.jpg`) und Slogan oben; Kurz-Badges und Feature-Tabelle statt nackter Fließtext-Einstieg.
- **CI · keine Auto-Releases:** Workflow `build-executables.yml` entfernt (hatte macOS/Linux/Windows ungeprüft an `v*`-Tags gehängt). StartOS-Workflow nur noch manuell (`workflow_dispatch`), ohne Release-Attach — Veröffentlichung nach Test per `scripts/publish_startos_release`.
- **README · Oberflächen:** Kein Legacy-CLI-Hauptmenü mehr beschrieben. Stattdessen: Zusammenspiel von Terminal-Steuerung (`py server.py`, Tasten 1/2/3) und Browser-GUI; `main.py` nur noch für Einmal-Analysen.
- **Windows-Build · Splash:** PyInstaller-Splash mit `max_img_size=(1200, 900)` statt `None` — 6.22 crasht sonst beim Vergleich `tuple > None`.
- **Windows · Terminal-Menü:** Feste ANSI-Fußzeile (VT-Modus), Logs scrollen darüber — Menü bleibt stehen. Tasten 1/2/3 ohne Enter; bei Beenden j/n. Fallback `Auswahl [1-3]:` wenn VT fehlt. `--plain-console` = ohne Menü. Abschalten: `SATSAGE_ANSI_MENU=0` / `SATSAGE_TERMINAL_MENU=0`.
- **Windows · Browser-Start / Server-Halt:** Auto-Browser wieder an (nach Menü/HTTP, verzögert per `os.startfile`). Kein Tk-Splash in der CLI (opt-in `SATSAGE_SPLASH=1`). HTTP in Daemon-Thread, bei Abbruch Neustart; Menü-Beenden setzt Stop-Flag zuerst.
- **HTTP · Browser zu / Beenden:** `ConnectionAbortedError` und Shutdown-`RuntimeError` (futures after interpreter shutdown) werden still geschluckt. Beim Menü-Beenden zuerst `_shutting_down` + HTTP-Stop, dann Job-Abbruch — kein Traceback-Sturm und kein „HTTP-Thread weg“.
- **Einstellungen · Darstellung:** Umschalter Hell/Dunkel. Hell wie bisher; Dunkel mit sehr dunklem Grau (nicht pechschwarz), hellerer Schrift und unveränderten Markierungsfarben. Sprache und Darstellung werden **immer** in die `.env` geschrieben (keine Extra-Checkbox).
- **Marke · sat-logo:** Sat-Symbol (`sat-logo.png`) ist die SatSage-Marke (Web-Kopf, Login, Favicon, Packaging-Icon). Volles Logo: `SatSage final.jpg` → `web/img/logo.jpg`. Ableitung: `scripts/prepare_brand_assets.py`.
- **Windows-Splash · Logo:** PyInstaller-Splash zeigt das volle `logo.jpg` (nativ, vollständig) — nur herunterskalieren wenn über dem Limit; `max_img_size=None`. Kein Zuschneiden auf die kleine Marke.
- **Login · Look & Feel:** Anmeldeseite mit SatSage-Marke (Logo + Slogan), Kartenlayout und Dark-/Light-Mode über `prefers-color-scheme` — statt der früheren Plain-HTML-Seite. Logo/Favicon für `/login` ohne Auth erreichbar; übrige UI-Shell weiter geschützt.
- **StartOS-Paket:** Wrapper liegt in `packaging/` (Dockerfile, Makefile, SDK). Bau-Anleitung `doc/START9-packaging.md`; Skripte `scripts/build_startos_s9pk` und `scripts/publish_startos_release`. Nur x86_64.
- **Wallet · Ladehinweis:** Beim Öffnen der Wallet-/Herkunftsansicht immer **Lade aus Cache…** (der GET ist Cache). **Lade von Electrum…** / **P2P…** / **Core RPC…** nur in der Scan-/Sync-Leiste, nicht fälschlich bei Cache-Reads.
- **Bereits ausgegeben · Zeile:** In der zugeklappten Adresszeile steht neben „1 UTXO“ / „N UTXOs“ jetzt „ausgegeben am …“ (bzw. Pending) — ohne Aufklappen.
- **Bereits ausgegeben · EUR:** ≈ € zum **Tageskurs am Ausgabedatum** (lokale Historie), nicht zum Spot. Fehlt der Tag, Spot-Fallback **gelb** mit Tooltip-Warnung. API: ``GET /api/price/history?series=1``.
- **Designhinweis · Node-Anbindung:** `doc/design-node-anbindung.md` — Node verbinden so einfach und fehlertolerant wie möglich (Apple-Leitbild); in `AGENTS.md` verankert.
- **TLS · LAN vs. Clearnet:** Fulcrum/Core prüfen Zertifikate nur noch bei **öffentlichen** Hosts. Private/LAN/Loopback/Onion behalten die alte Self-Signed-Praxis (keine CA-Prüfung) — Desktop-`.env` gegen Start9-LAN funktioniert wieder ohne `SATSAGE_TLS_INSECURE`. Der Start9-Sideload spricht Electrs ohnehin ohne TLS über die Bridge. `SATSAGE_TLS_INSECURE=1` bleibt die Ausnahme für öffentliche Self-Signed-Ziele.

## 2026-09-08 — Öffentlicher Start (SatSage Open Source)

- **Public Release:** Erstes öffentliches GitHub-Repository unter dem Namen **SatSage – know your sats** (MIT, Maintainer `Juniormind1 <juniormind@proton.me>`). Commit-Marke im öffentlichen Tree: `d8d3601` (*Initial public release of SatSage*).
- **Vorgeschichte:** Alles **unterhalb** dieses Abschnitts (`2026-09-07` … `2026-07-08`) ist die private xPubQuery-/SatSage-Entwicklung vor der Freigabe — inhaltlich deckungsgleich mit `PyCharmProjects/xPubQuery/CHANGELOG.md` (Stand Abgleich 2026-09-09); kein nachträgliches Umschreiben von Klarnamen nötig.
- **Danach:** Einträge in `[Unveröffentlicht]` bzw. neueren Datumsabschnitten gehören zur öffentlichen Weiterentwicklung (u. a. Identitäts-Hooks, Lab-Sanktions-Hops, README/CI).

## 2026-09-07

- **Log · „Moment noch“:** Globaler 10‑s‑Takt über alle parallelen Jobs — die Zeile nennt keinen Job, also höchstens *eine* Meldung, und nur wenn **kein** Job in den letzten 10 s etwas ins Log geschrieben hat.
- **Regtest-Lab · Assistent:** Lab-`.regtest.env` / Vorlage und `generate_scenarios.write_env` tragen Ollama-Loopback ein (`qwen2.5:0.5b`, `127.0.0.1:11434`) — bleibt nach Szenario-Neulauf erhalten.
- **Wallet · Herkunft vollständig:** Pro Wallet ein Knopf, der alle UTXOs wie „Herkunftslücken schließen“ durchzieht (gebündelte Eingänge **und** Vorgänger-Txs) bis external/Coinbase. Mit Dauer-Hinweis; bereits vollständige Bäume werden übersprungen. Danach sitzt alles im Cache.
- **Herkunft vollständig = Lücken-Pfad:** Der Superscan nutzt denselben Ablauf wie der Einzel-Knopf „Herkunftslücken schließen“ — zuvor fehlten die Vorgänger-Txs, deshalb blieben bei manchen CoinJoin-UTXOs Lücken.
- **Regtest-Lab · leere Scans:** `MAX_ADDRESSES=100` deckte nur Empfang 0–49 ab; nach erneutem Szenario-Lauf lagen UTXOs auf Index 50+. Lab-Default jetzt 400; Szenarien holen Empfangsadressen per `deriveaddresses` (kein Keypool-Vorschub).
- **Herkunft · Entwirren bis rot/lila:** Gemeinsame Vorgänger (Raute, typisch CoinJoin/Mix) wurden fälschlich als leere grüne Blätter abgeschnitten (`visited` global statt pfad-lokal + Memo). Vollständigkeit prüft jetzt jedes Blatt (nicht nur „irgendwo external“); „Lücken geschlossen“ / Done-Flag nur wenn wirklich alle Enden external oder Coinbase sind.
- **Lizenz / Release:** MIT (Copyright Juniormind1); `NOTICE` listet Drittanbieter (u. a. embit MIT, chiabip158 Apache-2.0) und Build-/Test-Werkzeuge für Releases.

- **Regtest-Labor · Windows:** Portable bitcoind + Fulcrum ohne Admin/Docker (`lab/regtest/scripts/win/`: Setup, Start/Stop, Szenarien). Loopback-RPC/Electrum, `NETWORK=regtest` in der generierten Lab-Env. Szenario-Skript robuster (Wallet-Load, UTXO-Auswahl, Fan-out-Adressen).
- **Regtest-Lab · start_lab:** Ein-Kommando-Start (`start_lab.ps1` / `stop_lab.ps1`) inkl. GUI und Browser (Edge/Chrome/Firefox) mit Token-URL; optional Playwright-Verify der Web-Oberfläche.
- **Web-GUI · Token-URL:** Gültiges `?t=` wird nicht mehr serverseitig auf `/` umgeleitet — sonst erschien trotz korrekter Link-Adresse der Dialog „Token fehlt“.
- **Log · Datenquelle:** Wiederholte Zeilen „Datenquelle: eigener Electrum-Server …“ und erneute „Automatische Datenquellen-Priorität…“ (bei Herkunft/Watch/Reconnect) werden unterdrückt — nur noch bei Wechsel oder neuem Lauf.
- **Herkunft · Folgeanalyse:** Ein Knopf „Herkunftslücken schließen“ statt zweier getrennter Aktionen; schließt gebündelte eigene Eingänge und Vorgänger-Txs (`followup=full`). Hinweis erwähnt Sammel-Txs inkl. CoinJoin/Mix ohne automatische Erkennung.
- **Regtest-Labor:** Neues secrets-freies, portables Labor unter `lab/regtest/` für Mac und Linux mit bitcoind, Electrs und reproduzierbaren Wallet-/Transaktionsszenarien inklusive zweier CoinJoin-ähnlicher Strukturen mit mehr als 20 Inputs und Outputs. Lokale Chain-Daten und Lab-Umgebungen bleiben außerhalb der Versionsverwaltung.
- **Mempool · Selbstüberweisung:** Pending-Spends (eigener Electrs) zeigen in der Wallet-Liste die Marke „wird gerade ausgegeben“; eigene Empfangs-Outputs der Spend-Tx (Change/Self) erscheinen als unbestätigte UTXOs („Mempool“). Bestandssumme ohne doppelte Zählung der ausgehenden Pending-UTXOs. Electrs-Light/Tip-Nachzug entfernt Mempool-Spends nicht mehr still; Wallet-Watch übernimmt Empfänge und abonniert neue Adressen.
- **Wallets immer aktuell · Sofort:** Schalter an → Tip-Nachzug und Electrs-Watch **sofort**, ohne Server-Neustart.
- **Tip-Nachzug · eigener Electrs:** Kein BIP-158-Multi-Peer mehr, wenn Fulcrum/electrs im LAN (oder eigener Onion-Client) die Quelle ist — nur Electrs light; Live danach über Subscribe. BIP-158-Tip nur ohne eigenen Electrs bzw. wenn BIP-158 die aktive Quelle ist.

## 2026-09-05

- **Wallets immer aktuell:** Option umbenannt (`.env`: `WALLETS_IMMER_AKTUELL`, Legacy `WALLETS_BEIM_START_AKTUALISIEREN`). Mit **eigenem Electrs**: `scripthash.subscribe` + Header-Subscribe im Hintergrund; bei Aktivität gezieltes `listunspent`, bei neuem Block leichter Tip-Nachzug. **Core** eignet sich nicht für Adress-Push — Electrs ist der richtige Kanal. Ohne eigenen Electrs nur Start-Tip-Nachzug.
- **Mempool · Pending/Settle:** Nur **eigener Electrs**: unbestätigte Spends → Marke „wird gerade ausgegeben“ + pending unter ausgegeben. Bei **Bestätigung** gezielter Settle (UTXO raus, Verlauf spent, `listunspent` nur betroffene Adressen für Change) — kein Fullscan/Tip-Walk.
- **Wallet · Frische:** Anzeige primär nach **mtime** (vor N Min./Std.), nicht nur „bis Tip“. Hinter der Chain zusätzlich „−N Blöcke“.
- **Wallet · Bis Tip:** Knopf „Bis Tip“ startet inkrementellen Tip-Nachzug ohne Neustart (`POST /api/jobs/wallet-sync`) — kein Fullscan wie UTXO-Scan.

## 2026-09-04

- **Start-Sync · Multisig:** BIP-158 behandelte `wsh(sortedmulti…)` fälschlich als XPUB (`invalid xpub: '('`) und brach ab — Wallet blieb hinter dem Tip. Deskriptor-Adressen werden jetzt abgeleitet; bei BIP-158-Fehler Fallback auf Electrs light; Electrs light hebt `scan_tip_height` auf den Header-Tip an.
- **P2P · Merk-Liste:** Zuletzt erfolgreiche Compact-Filter-Peers in `immutable_cache/p2p_filter_peers.json` (überlebt Neustart). Verbindung startet mit LAN/fest + Merk-Liste; DNS-Seeds nur wenn noch Plätze fehlen. Fehlschläge werden ans Ende der Liste geschoben.
- **Start · Log/Performance:** Header-Tip-Check höchstens alle 15 Min (Cooldown), nicht bei jedem Peer-Takt. UI-Peer-Check während Scan nicht mehr alle 4 s (Live-Peers nur aus Job-Poll). BIP-158-Multi-Peer nur wenn mind. ein Wallet `scan_tip_height` hat — sonst direkt Electrs light ohne teuren P2P-Aufbau.
- **P2P · Peers:** Header-/Probe-Pfad (`limit=1`) meldet nicht mehr „1 Peer — Scan langsamer“. BIP-158-Setup füllt den Peer-Pool (bis 4, Tor 2) nach dem Handshake. Start-Sync ohne `scan_tip_height` loggt klar Electrs-Gap statt Multi-Peer; nach Electrs-Light wird Header-Tip als `scan_tip_height` gesetzt, damit der nächste Lauf BIP-158 multi-peer kann.
- **Header-Vorab · Log:** Bei schon gefülltem Cache kein erneutes „Lade Block-Header ab SegWit…“; stattdessen Tip-Prüfung. Ist der Cache am Peer-Tip, entfällt `getheaders`. Kein zweiter Header-Job in den ersten 2 Min nach erfolgreichem Abschluss (Browser-Peer-Check).
- **Terminal · Beenden mit Jobs:** Nach „3“ blieb die Bestätigung oft hängen bzw. `j` wirkte nicht — Enter nach „3“ setzte den Wartezustand zurück. Jetzt cbreak (Taste ohne Enter), Enter während der Nachfrage ignoriert, nur **j** beendet / **n** bricht ab.
- **Kopf · P2P-Pille bei Tip-Sync:** Offene Compact-Filter-Peers des Start-Sync/Scans werden live gezählt (`live_p2p_peers`); die BIP-158-Pille zeigt die aktive Peer-Zahl (gelb/grün) und Hosts im Tooltip — danach wieder Probe-Takt (grau möglich).
- **Start-Sync · Produktregel:** Tip-Nachzug (`WALLETS_BEIM_START_AKTUALISIEREN`) bevorzugt **BIP-158 inkrementell** ab `scan_tip_height` — auch wenn Electrs/Core die allgemeine Datenquelle ist. Ohne Filter-Peer oder ohne Tip: **Electrs light** (bekannte UTXOs auf spent + Gap ab `scan_end_index`), **kein** `scantxoutset` und kein Abfragen aller Indizes #0…N. Vollabgleich (Electrs-Gap / Core scantxoutset) bleibt beim expliziten User-UTXO-Scan.
- **Wallet · Cache-Aktualität:** Nav-Marker und Wallet-Meta zeigen Stand (gerade eben / vor … / bis Tip / hinter Tip / Start-Sync läuft); `scan_tip_height` in der Summary; Start-Sync erscheint unter Vorgänge.
- **Jobs · Nav:** Laufende Nutzer-Jobs unter Datenquellen; UTXO/Verlauf serverseitige Warteschlange („X, dann Y“), GUI-zu-fest; Doppelstart disabled („läuft schon“); failed/cancelled 10 s sichtbar.
- **Datenquellen · Privatsphäre-Pille:** „hoch“ nur noch grün, wenn die Quelle konfiguriert ist; unkonfiguriertes Electrs/Core bleibt grau.
- **Datenquellen · Import:** Labels und Sanktionslisten manuell als Datei(en)/ZIP einspielbar („Dateien importieren“), wenn der Online-Download scheitert.
- **Labels/Sanktionen/Kurs · HTTPS:** Gemeinsamer CA-Kontext (`core/tls.py`) — Label-Download scheitert unter macOS-Framework-Python nicht mehr still an `CERTIFICATE_VERIFY_FAILED` (Status blieb „nicht geladen“).
- **Web-UI · Kopf-Quelle:** Pille „Quelle: …“ folgt der echten Kaskade (Electrs → Core → P2P → keine) — nicht mehr Default „Electrs privat“, wenn gar kein eigener Electrs konfiguriert ist.
- **Web-UI · Datenquellen:** Nach leerer/.env ohne Host keinen alten „verbunden“-Stand mehr für Electrs/Core behalten (Pille und Kopfzeile).
- **Web-UI · Einstellungen:** SMTP- und Assistenten-Felder wieder einzeilig (``feld-breit`` wuchs in der Label-Spalte).

## 2026-09-02

- **Web-UI · Sprache:** Umschalter Deutsch/Englisch in den Einstellungen (`localStorage` + optional ``UI_LANG`` in ``.env``). Catalogs ``web/locales/{de,en}.json``, ``i18n.js``. Datums-/Zahlenformat folgt der Sprache. Job-Log und viele API-Fehler können weiterhin Deutsch sein (Hinweis in der EN-UI).
- **Herkunft · Folgeanalyse:** Nach erfolgreichem „Vorgänger gründlicher“ erscheint statt des Knopfs der Hinweis „Schon gründlicher analysiert“ (bleibt am gespeicherten Baum; „Scan neu“ setzt zurück).
- **Herkunft · gründlicher (Issue 4):** Nach dem Trace Opt-in am Baum — „Vorgänger gründlicher analysieren“ (CLI-Folgeanalyse) und „Gebündelte Eingänge nachziehen“ (alle eigenen Inputs jenseits des 20er-Limits). Confirm + Abbruch; schreibt denselben Trace-/Ingress-Cache.
- **Steuer · Anschaffungslesart:** Einstellung ``STEUER_ANSCHAFFUNG`` / UI „Anschaffung aus Herkunft“ — **defensiv** (jüngster externer Zufluss, Default) oder **offensiv** (ältester). Export und Hinweise kennzeichnen Offensiv; Alt-Caches ohne Oldest-Feld fallen mit Warnung auf jüngste zurück.
- **Kopieren:** Klick auf gekürzte Adresse, TxID oder UTXO (``txid:vout``) legt den Vollwert in die Zwischenablage — kurzes „kopiert“-Feedback. Wallet, Herkunft, Steuerjahr, Sanktionstreffer.
- **Herkunft · Sprung aus Wallet:** fehlt der Output in der Herkunftsliste (oft schon ausgegeben), wird ``txid:vout`` ins Suchfeld übernommen — „Gezielt tracen“ reicht zum Starten.
- **Version 0.9:** Datei ``VERSION`` als einzige Quelle; Web-Fußzeile zeigt ``v0.9``, ``GET /api/config`` liefert ``version``. Neue Nummern nur durch Maintainer.

## 2026-08-31

- **Scan neu:** die Knöpfe „Herkunft neu“ (Wallet- und Herkunftsansicht) und „Neu verfolgen“ (Baum-Kopf) sind zusammengeführt — ein Knopf **Scan neu** am UTXO, derselbe Ablauf. Der zweite Knopf im Baum-Kopf entfällt.
- **Block-Explorer-Pfeil (↗):** grün bei Explorer im eigenen Netz, gelb bei öffentlichem/fremdem Dienst — statt einheitlich grau. Tooltip: „Privaten/Öffentlichen Blockexplorer öffnen“ plus Host darunter.
- **Herkunft neu / Neu verfolgen:** nach dem Lauf erscheinen Stand-Datum und „verfolgt · …“ sofort mit dem neuen Zeitpunkt — kein Seiten-Refresh mehr nötig.
- **Terminal-Steuerung:** Menü als feste Fußzeile (ANSI-Scrollregion); Log scrollt darüber. Tasten 1–3 ohne Enter; periodisches Neuzeichnen der Job-Zahl. Fußzeilen-Reihenfolge: URL darüber, Menüzeile darunter (mit ``:``); Cursor steht auf der Menüzeile.

## 2026-08-29

- **Status-Mails:** Opt-in und SMTP in Einstellungen/``.env``. Bei fertigem UTXO- oder Verlaufsscan neutrale Mail (Ereignis, Status, Zeit — keine Wallet-/Scan-Daten).
- **Wallets · nach Anlegen:** Dialog fragt nach UTXO-Scan (Vorgabe), Verlaufsscan oder später manuell; bei Scan-Hinweis, dass der Browser geschlossen werden darf.
- **Technische IDs · satsage:** Extension/Package ``satsage.specterext.satsage``, Binary/Spec/Build-Skripte ``satsage-webgui``, HTTP-Header ``X-Satsage-Token``, Specter-Env ``satsage.env``, Config-Keys ``SATSAGE_*``. Frühere ``xpubquery``-Pfade entfallen (Breaking für alte Plugin-Installationen und Lesezeichen mit altem Header-Namen).
- **Web-Server · Terminal-Steuerung:** nach ``py server.py`` Menü im Terminal (Status, Browser erneut öffnen, Server beenden). Browser darf zu — Scans laufen weiter; dieselben Job-Log-Zeilen wie in der Web-GUI erscheinen im Terminal. ``--plain-console`` lässt das Menü weg (Tests/Automation). Onefile-Spec bündelt ``core.terminal_steuerung`` / ``core.jobs`` per ``hiddenimports``.
- **CLI-Menü · Legacy:** interaktives Terminal-Menü (`py main.py`) als Legacy/Fallback gekennzeichnet; empfohlen bleibt die Web-GUI. Direktmodi ``--txid`` / ``--address`` / ``--cli`` unverändert.
- **Verlaufsscan · Priorität:** eigene Datenquellen-Kette statt der allgemeinen Auto-Wahl — Electrs LAN → Onion → BIP-158 Blockwalk/Cache → öffentliche Electrum (nach Bestätigung). Core ``scantxoutset`` entfällt. Log-Zeile begründet die Wahl; BIP-158 kann Historie jetzt ohne Electrum liefern. Behebt den Abbruch, wenn BIP-158 vor öffentlichen Servern lag und ``fetch_wallet_history`` fehlte.
- **Quellen-Check · P2P-Meldung:** statt „P2P übersprungen“ klarer Text: mit Electrs allein „P2P als Datenquelle nicht erforderlich (Electrs erreichbar)“; mit Electrs und Core zusätzlich Hinweis, dass der Header-Tip nur selten nachgezogen wird.
- **Header-Sync · Peer hinter Tip / Kurz-Reorg:** ``getheaders``-Antworten, die ab einem älteren gemeinsamen Block kommen (Peer noch nicht auf unserem Tip, oder kurze Gabel), reißen die lokale Kette nicht mehr ab. Bekannte Header werden übersprungen, abweichende Spitzen auf den Vorfahren gekappt — der Vorab-Job endet nicht mehr mit ``Header-Kette reißt (prev-Hash)``.
- **Umbenennung · SatSage:** Anzeigename und Slogan **SatSage – know your sats** (Wortspiel Sat Sage / Sats Age). Logo (Eule) in Web-Kopfzeile, Favicon und Specter-Plugin; kanonischer On-Chain-Hinweis und Nutzertexte auf den neuen Namen. Technische IDs damals noch ``xpubquery`` (später auf ``satsage`` nachgezogen).
- **BTC-Kurs:** Spot und Tageskurs über ``core/price.py``. Mitgelieferte Historie ``data/btc_price/{EUR,USD}.csv`` (Bitstamp-Schlusskurse via CryptoDataDownload); CSV-Import unter Datenquellen schreibt 1:1 in ``immutable_cache/btc_price/``. Netz (Mempool, Spot-Fallback Coinbase) nur für Lücken und aktuellen Kurs; Spot fällt bei Netzfehler auf den lokalen Tageskurs zurück. ``GET /api/price`` blockiert den Start nicht mehr (Timeout). Kopfzeilen-Pille mit EUR-Spot; Salden zeigen ``≈ … €`` neben Sats/BTC.

## 2026-08-27

- **Multisig · Specter-Import:** Import der Specter-JSON (auch ohne `/0/*` nach den xpubs) endet nicht mehr mit Serverfehler (`_deskriptor_kennungen`). Fehlende Wildcard-Ableitung wird wie bei Specter um `/<0;1>/*` ergänzt — die erste Empfangsadresse stimmt mit BlueWallet/Specter überein. BlueWallet-Cosigner-Dateien (nur Schlüssel) bekommen einen klaren Hinweis statt der generischen Deskriptor-Meldung.
- **Adressgruppe · jüngste sats:** wenn an einer Adresse schon vollständig verfolgte UTXOs „jüngste sats“ zeigen, aber noch unverfolgte UTXOs daneben liegen, erscheint gelb „aber n UTXOs ohne Herkunftstrace“ — das Datum gilt nur für die bereits verfolgten. Der Zähler sinkt direkt nach jedem Trace (Wallet- und Herkunftsansicht), ohne Seiten-Refresh.
- **Wallets · Hinzufügen:** Name-Feld ist immer sichtbar. „Hinzufügen“ (und Multisig-„Übernehmen“) schreibt sofort in die `.env` — kein Scrollen zu Speichern/Verwerfen mehr. Name, Skripttyp und Scan-Tiefe speichert die Zeile per „Aktualisieren“.
- **UTXO-Scan · Priorität:** Electrs/Fulcrum im LAN vor Core-``scantxoutset`` (LAN vor Onion), dann Electrs-Onion, dann BIP-158. Öffentliche Electrum-Server bleiben dahinter (Privatsphäre). Mit Electrs im LAN entfällt der ~1‑Minuten-Core-Set-Scan. Verlaufsscan-Reihenfolge ist offen (`ISSUES.md`).
- **Kopfzeile · Core/Electrs:** nach UTXO-Scan kein kurzes Rot-Grün-Flackern mehr — `/config` ohne Live-Check behält den letzten Verbindungsstand; während eines Scans zählen kurz fehlgeschlagene Core-Checks nicht als „offline“.
- **UTXO-Cache · Speicherplatz:** Schreiben blockiert nur noch, wenn unter 5 % **und** unter 2 GiB frei sind (große Platten mit z. B. 18 GiB bei 4 % bleiben schreibbar). Scheitert das Speichern trotzdem, endet der Scan mit Fehler statt „UTXOs gefunden“ ohne „Cache vom …“.
- **Erster Start · Dialoge:** On-Chain-Hinweis ist ein eigener, kurzer Dialog mit OK — nicht mehr oben auf „Erste Einrichtung“ geklebt. Einrichtung folgt erst danach. Overlay-Karten sind auf dem Viewport begrenzt und scrollbar.

## 2026-08-24

- **Wallets löschen · Cache:** Beim Speichern nach dem Entfernen eines Wallets fragt die Oberfläche, ob der zugehörige Analyse-Cache mit gelöscht werden soll — mit Angabe der Größe in MB. OK löscht UTXO-/Verlauf-/Herkunftsdateien und die Altersdatei des entfernten Wallets; Abbrechen behält den Cache.
- **Unreferenzierte Cachedaten:** unter der Wallet-Liste (über Speichern) erscheint eine Aufräum-Zeile, wenn Cache-Dateien ohne passendes Wallet in der `.env` liegen — mit Größe in MB und Knopf zum Löschen. Kein Danger-Zone-Eintrag.
- **Hinweis On-Chain-Beleg:** ein kanonischer Absatz stellt klar, dass SatSage Börsenhistorien und Kaufbelege nicht ersetzt, sondern nur ergänzt. Er steht in README, Handbuch, Steuerjahr, Fristen, CSV/HTML-Export, Selbstanzeige und Assistent. Beim ersten Einrichtungsdialog einmal, mit OK und „Nicht nochmal anzeigen“ in der `.env` dieser Installation gemerkt.

## 2026-08-23

- **Assistent · Slash-Liste:** eigene Vorschläge statt Browser-Datalist — nach Enter zu; Pfeil rechts (am Zeilenende) und Tab vervollständigen.
- **Assistent · Phase 5:** Handbuch-Abschnitt, Härtungs-Tests (Blockliste, kein Job aus Werkzeugen, Steuer-Kennzahlen = Cache-Auswertung, Status ohne Key). Specter-iframe höher, damit Log und Assistent Platz haben.
- **Assistent · Phase 4:** Remote nur nach Opt-in und Key aus der .env (``LLM_API_KEY`` / Datei-Alias ``XAI_API_KEY`` — nie der Prozess-Key). ``/export markdown`` und ``/export brief`` rendern denselben Cache wie die Steuerauswertung; CSV/HTML bleiben maßgeblich. Remote-Prompts werden redigiert (keine XPUBs/Adressen/TxIDs).
- **Assistent · Phase 3:** Freitext über ``POST /api/llm/chat`` an Ollama/LM Studio (Loopback/LAN). Dieselben Cache-Tools wie die Slash-Befehle; Remote bleibt hart gesperrt, ``XAI_API_KEY`` zählt nicht. Kein Job-Start, keine Chat-Completions aus dem Browser.
- **Assistent · Phase 2:** Slash-Befehle lesen nur den lokalen Cache (`/hilfe`, `/anbindung`, `/neu`, `/luecken`, `/wallets`, `/steuer`, `/export legende`). Neu: ``GET /api/llm/context/…``. Job-Start und Chat-Completion bleiben aus; gesperrte Befehle (`/scan`, `/exec`, …) enden mit einer festen Ablehnzeile.
- **Assistent · Phase 1:** Untere Leiste mit Log links und Chat-Shell rechts (Eingabe noch gesperrt). Kopf-Pille und Anbindungs-Banner aus ``GET /api/llm/status``. Einstellungen-Block „Assistent“ schreibt nach ``PUT /api/config/llm`` — ohne ``XAI_API_KEY``, ohne Chat-Completion. Live-Tests gegen Ollama ``qwen2.5:7b``.

## 2026-08-22

- **Assistent · Phase 0:** `core/llm_anbindung.py` stuft die LLM-Anbindung ein (Loopback/LAN/Remote), baut Banner-/Pillen-Felder und prüft optional die Erreichbarkeit. Neu: `GET /api/llm/status` (``?check=1`` für Probe). API-Key erscheint nie in der Antwort. Noch keine Chat-UI. Live-Tests gegen laufendes Ollama (`127.0.0.1:11434`), sonst Skip.

## 2026-08-21

- **Standalone-Build:** Skripte ``scripts/build_satsage_macos``, ``_linux``, ``_win.bat`` bauen per PyInstaller die Web-GUI (``dist/satsage-webgui``); Spec bündelt ``web/``, ``data/``, ``doc/``.
- **Selbstanzeige · HTML:** Report öffnet sich im neuen Tab (Druck → PDF) und wird parallel als Datei gespeichert — kein manuelles „Heruntergeladene Datei öffnen“ mehr.
- **Selbstanzeige · Was-wäre-wenn:** ohne Abflüsse im Jahr trotzdem Kandidaten — offene UTXOs als Hypothese (fiktive Veräußerung zum Jahresende bzw. heute). UI einklappbar: Abflüsse, UTXOs, Verlauf-Überblick.
- **Herkunft aller UTXOs · Zwischenstand:** während des Massenlaufs aktualisiert sich die aktuelle Ansicht (Herkunft / Wallet / Steuerjahr) gedrosselt (~2,5 s), sobald neue UTXOs fertig sind — „jüngste sats vom …“ ohne manuelles Neuladen. Statuszeile nennt zusätzlich die Zahl vollständiger „jüngste sats“.
- **Specter-Plugin · Oberfläche:** dieselbe Web-GUI (`server.py` + `web/`) per iframe unter `/svc/satsage/gui`; Specter-Wallets in `.specter_dev/satsage.env`, Fallback „neuer Tab“.
- **UTXO-Scan · Zwischenstand:** gefundene UTXOs erscheinen schon während des Scans in Cache, Nav und Wallet-Liste (gedrosselt ~2,5 s) — Gap-Scan (Fulcrum) und Filter-Treffer (BIP-158). Abbruch behält den Zwischenstand. ``scan_end_index``/Tip bleiben bis zum fertigen Lauf unverändert.
- **Verlaufsscan · Zwischenstand:** nach jeder Adresse wird gemerged und gespeichert; bricht der Lauf ab (Timeout), setzt der nächste Scan bei denselben Adressen fort statt bei null. Fortschrittszeile nennt „setze fort, n schon da“.
- **Fulcrum/Tor · Verlaufsscan:** bei Timeout oder Verbindungsabbruch während ``blockchain.transaction.get`` bis zu dreimal neu verbinden und die Anfrage wiederholen — statt den Job mit rohem ``TimeoutError`` abzubrechen.
- **Selbstanzeige-Report:** unter Steuerjahr Kandidaten (Netto-Abflüsse) manuell ankreuzen oder per Börsen-Einzahl-TxID vorwählen; HTML/CSV mit walletbezogenem FiFo, vollständigen TxIDs/Adressen, Summenzeile (jüngstes verbrauchtes Los) und Platzhalter-Stammdaten (Donald Duck / 0/8/15 / Entenhausen). HTML-Druck mit Kopf-/Fußzeile und Seitenzahl.
- **Peers · ruhiger Takt:** sind Electrs und Core beide erreichbar, prüft die Oberfläche Peers nur noch alle **10 Minuten** (sonst 30 s) und loggt keine ausfallenden Compact-Filter-Peers. Header-Tip wird dabei weiter mitgezogen.

## 2026-08-20

- **UTXO-Ankunftszeit:** fehlt ``block_time`` (typisch nach ``scantxoutset``), wird sie lokal aus ``block_header/`` bzw. ``p2p_headers.bin`` nachgezogen und in den UTXO-Cache geschrieben — Anzeige wie bei BIP-158 („Ankunft am … um …“).
- **Trace ohne Electrs:** bei BIP-158 holt ``get_tx`` zuerst Core-RPC (``getrawtransaction``, ideal mit ``-txindex=1``), dann P2P-``getdata``, sonst den ganzen Block an der bekannten UTXO-Höhe (Header-Cache). Damit endet Herkunft nicht mehr bei „Peer hat die Transaktion nicht“, wenn die Scan-Höhe oder Core greifen. Tiefe Prevouts ohne Höhe brauchen weiter Electrs oder Core-txindex — kein Ketten-Blindflug.
- **Verwaltung aufgeteilt:** Seitenleiste unter Verwaltung mit **Wallets** (XPUB/Deskriptor, Speichern, Danger Zone), **Einstellungen** (Start-Sync, Fristen/Stichtag) und **Datenquellen** (Core/Electrs, Block-Explorer, Labels, Sanktionslisten). Ohne privaten Node (weder Core-RPC noch Electrs privat) steht „Datenquellen“ gelb mit Warn-Tooltip.
- **Kopfzeile · Datenquellen:** rechts oben vier Zustands-Pillen — Core RPC privat, ``n P2Peers anonym``, Electrs privat, Electrs öffentlich — danach Privatsphäre (hoch/grün solange kein öffentlicher Electrum verbunden, sonst niedrig/rot). Core und Electrs privat: neutral ohne Konfig, rot konfiguriert aber nicht verbunden, grün verbunden. P2P: Label mit Peer-Anzahl; 0 grau, 1–2 gelb, >2 grün. Electrs öffentlich: neutral unverbunden, rot verbunden. Tooltips erklären Privatsphäre und Bedeutung je Quelle.
- **Bitcoin Core · scantxoutset-Log:** während ``scantxoutset start`` pollt ein Parallelthread ``scantxoutset status`` auf einer zweiten RPC-Verbindung — im Log erscheinen Prozent und Laufzeit statt nur „Moment noch“.
- **Bitcoin Core · scantxoutset:** bei konfiguriertem RPC (LAN/Onion) ist der UTXO-Scan zuerst ``scantxoutset`` — schneller Bestand als Seed für Rescan und Start-Sync; sonst unverändert Electrum/BIP-158. Einstellungen Rang 2, Verbindungstest, Passwort maskiert.
- **Cache löschen:** Wallet-Alter (First-seen) blieb schon in `*_alter.json`; der BIP-158-Rescan startet damit jetzt **ab Wallet-Beginn**, nicht wieder bei SegWit. Rein-BIP-158-Scans speichern First-seen aus den gefundenen UTXOs. Danger-Zone-Text und Lösch-Meldung sagen das.
- **UTXO-Scan · Log:** Filter-Treffer-Zeile wird in place fortgeschrieben — aus „Filter-Treffer Block … — hole Block…“ wird dieselbe Zeile mit „False Positive“ bzw. „+n UTXO…“ (keine zweite Zeile).
- **Einstellungen · Beim Start:** Option „Wallets beim Start aktualisieren?“ (`.env`: `WALLETS_BEIM_START_AKTUALISIEREN`). Wenn an, zieht jeder Start (Web und CLI-Menü) vorhandene UTXO-Caches bis zum Chain-Tip nach — bekannte Adressen neu abfragen und Gap fortsetzen, kein Fullscan. BIP-158 nur mit gespeichertem `scan_tip_height`.
- **BIP-158-Scan:** Filter-Chunks in Höhenreihenfolge während weitere laden; Peer-Abbruch beim Header-Sync bis zu fünf Mal; inkrementell mit `scan_tip_height`; Verlauf aus dem Blockscan; Filter-Treffer im Web-Log; ruhigeres P2P-Log; Prozentfortschritt.
- **Esplora entfernt:** keine Esplora-Datenquelle mehr. Auto-Kette: eigener Electrum-Server → BIP-158 → öffentliche Electrum nur nach Bestätigung.
- **Handbuch:** nur noch in der Fußzeile, nicht in der Seitenleiste.
- **P2P über Tor:** nach Clearnet-Fail (Firewall 8333) Tor Browser SOCKS oder tor-Binary; vorher billiger TCP-Probe auf 8333.
- **Header-Archiv:** `data/p2p_headers_segwit.bin.gz` im Repo; fehlt der lokale Cache, wird er ausgelegt.
- **UTXO-Scan:** ohne Datenquelle endet der Job mit Fehler statt ewig „läuft“.
- **Header-Vorab:** auch mit Wallet, wenn `p2p_headers.bin` fehlt; Cache-Löschen lässt Header und Wallet-Alter.
- **P2P-Peers:** DNS-Seeds mit ``x40`` (Compact Filter); gefundene Filter-Peers merkt sich der Prozess.

## 2026-08-19

- **P2P-Header:** Erstsync startet an einem Mainnet-Checkpoint (SegWit, 700k/800k/850k/900k), nicht bei Genesis. Die Datei `p2p_headers.bin` gilt für alle Wallets; Zwischenspeicher nach jeder 2000er-Runde. Log nur alle 50 000 Blöcke.
- **P2P-Peers:** der Host im LAN wird zuerst als Compact-Filter-Peer (Port 8333) gefragt. Liefert er keine Filter, folgen extra Peers und DNS-Seeds — nicht gleich öffentliche Electrum-Server. LAN-IPs gehen nicht über Tor.
- **P2P-Scan:** bis zu vier Compact-Filter-Peers holen Filter-Chunks parallel. Header-Sync bleibt auf dem ersten (LAN). Die UTXO-Auswertung bleibt in Blockreihenfolge. Ein Peer allein arbeitet wie bisher sequentiell.
- **Start:** Block-Header ab SegWit (August 2017) laden im Hintergrund, auch ohne XPUB. Die Begrüßung sagt, dass das nur einmal nötig ist und ein eigener electrs/Fulcrum den Vorgang erspart.
- **Öffentliche Electrum-Server:** Verbindungen zu Onions oder Clearnet erst nach Bestätigung (Dialog in der Oberfläche, `--oeffentliche-electrum` oder `OEFFENTLICHE_ELECTRUM=1`). Ohne Zustimmung bleiben eigener Node und BIP-158.
- **Log · P2P-Discovery:** DNS-Seeds, Handshake und Fehlschläge stehen im Log, **bevor** der Schritt losläuft. Treffer als „Verbunden. Compact Filter …“, sonst „Verbindung fehlgeschlagen …“.
- **Peers:** alle 30 s stiller Nachcheck. Ausfall, Neuzugang und Sortenwechsel aktualisieren die Kopfzeile und stehen im Log („Peer … ausgefallen“, „Neuer Peer …“, „Wechsel: … → …“).
- **Kopfzeile:** „Eigener Peer verbunden“ (electrs/Fulcrum am eigenen Node), sonst „n Peers verbunden“ (BIP-158 Compact Filter), sonst „n öffentliche Peers verbunden“ (Onion oder Clearnet). Nach Fehlschlag „0 Peers verbunden“.
- **Datenquellen:** Bitcoin-Core-RPC und BIP-158 am eigenen Node entfallen. Höchste Privatsphäre ist der eigene Electrum-Server (electrs/Fulcrum). Compact Filter laufen über Bitcoin-P2P (BIP 157/158): DNS-Seeds bzw. `BIP158_PEERS`, optional Tor. TurboSync: ungenutzte Keys nur gegen das jüngste Fenster (~14 Tage), Historie nur schon gesehene Adressen. Vorgabe-Starthöhe SegWit (481 824). `NODE_IP`/`RPCUSER`/`RPCPASSWORD` werden nicht mehr genutzt.

- **UTXO-Scan · BIP-158:** reißt die RPC-Antwort mitten im Block ab (`IncompleteRead`, typisch `getblock` über Tor), wird derselbe Abruf bis zu dreimal wiederholt statt den Scan zu beenden. Im Log steht der Wiederholversuch. `getblock` wartet bis 180 Sekunden auf den Body.
- **UTXO-Scan · BIP-158:** ohne First-seen fragt die Oberfläche nach einem Startdatum (Vorschlag: SegWit 24.08.2017). Electrum-Scans bleiben ungefragt.
- **Wallet-Alter:** First-seen bleibt in einer eigenen Datei und überlebt „Cache löschen“ (pro Wallet und gesamt).
- **BIP-158-Scan:** nutzt die Gap-Scan-Tiefe (nicht nur Index 0–25). Cash & Carry mit UTXOs auf hohen Change-Indizes blieb sonst leer. Nach dem letzten Block steht „Filter-Scan fertig“, danach „Prüfe … auf unspent“.
- **Steuerjahr · Chart:** UTXOs vor der Haltefrist oder vor dem Stichtag werden zu **einem** Punkt am Quartalsbeginn davor. Tooltip: „n UTXOs vor Stichtag“ bzw. „n UTXOs älter als Haltefrist“.
- **Steuerjahr:** statt „Frist erfüllt/offen“ steht „außerhalb/innerhalb Haltefrist“. Mit gesetztem Stichtag zusätzlich „vor Stichtag“ oder „nach Stichtag“.
- **Verlauf / Herkunft aller UTXOs:** Status nennt den Rest („noch 40 von 58 Adressen“ bzw. UTXOs). Log-Bereich bekommt dieselben Zeilen plus Herzschlag „Moment noch“, wenn sich 10 Sekunden nichts ändert.
- **Einstellungen · Bitcoin Core:** Zugangsdaten werden auch nach einem Fehlschlag in die `.env` geschrieben. Vor den Core-Feldern steht ein Kommentar „Erfolgreicher/Erfolgloser Verbindungsversuch am … um …“.
- **Einstellungen · Fristen:** Haltefrist Vorgabe 1 Jahr (Deutschland). Stichtag standardmäßig leer — die Frist gilt für alle Anschaffungen. Hinweis nennt bekannte europäische Haltefristen (DE/PT 1 Jahr, CZ 3 Jahre, LU 6 Monate, CH privat ohne Frist, AT ohne Steuerfreiheit durch Halten) und den österr. Cutoff 28.02.2021.
- **Steuerjahr · Chart:** UTXOs sitzen in der Höhe ihrer Sats. Am Punkt nur „0,000 BTC“; Summe, Wallet und Frist stehen im Tooltip.
- **Einstellungen · Danger Zone:** Cache auch pro Wallet löschen — UTXO-Bestand, Verlauf und Herkunft nur dieses Wallets. „Gesamten Cache löschen“ bleibt.
- **Log · Herzschlag:** wenn nach zehn Sekunden derselbe Stand gilt, steht „Moment noch“ — nicht noch einmal dieselbe Arbeitszeile.
- **Log:** nach der Uhrzeit der Wallet-Name, wenn die Aktion zu einem Wallet gehört (Scan, Verlauf, Herkunft neu). Verbindungstest und Listen bleiben ohne.
- **UTXO-Scan · Log:** nach der letzten Adresse nicht mehr „Prüfe 101 von 101“ im 10-Sekunden-Takt. Danach läuft die einmalige Alter-Erhebung — die steht jetzt als eigene Phase mit Fortschritt im Log.
- **Log · Datenquelle:** Im Log steht „Datenquelle:“ erst, wenn die Quelle feststeht. Ohne eigenen Node heißt das „öffentliche Electrum-Server (Clearnet)“, nicht mehr „Bitcoin Core RPC (BIP-158)“ aus der fehlgeschlagenen Probe. Ohne `NODE_IP` wird Core gar nicht erst geprüft. Ohne `FULCRUM_TOR_0…` entfällt die Onion-Probe (sonst wiederholte der 10-Sekunden-Herzschlag „Onions nicht nutzbar“, während Clearnet sucht).
- **Clearnet-Fallback:** ohne eigenen Node und ohne Onion-Server läuft der Wallet-Scan über öffentliche Clearnet-Fulcrum-Server durch. Extra-Scan-Verbindungen gelten nur für den eigenen LAN-Fulcrum — bei öffentlicher Rotation (kein `.port`) knallte der Aufbau.
- **Start:** `server.py` startet wieder unter Python 3.10/3.11. Ein mehrzeiliges f-String im Scan-Fortschritt (PEP 701, erst ab 3.12) war ein Syntaxfehler.
- **Doku:** `README.md` beschreibt die Web-Oberfläche, Steuerjahr, Wallet-Alter und den Clearnet-Fallback; `AGENTS.md` denselben Stand für Assistenten.

## 2026-08-18

- **Einstellungen · Multisig:** Knopf „Import“ liest Sparrow-, Specter- und Bitcoin-Core-Exporte ins Deskriptor-Feld. Welche Formate gehen und welche nicht, steht im Tooltip.
- **Einstellungen · Wallets:** XPUB- und Multisig-Feld gleich breit. Rechts neben dem Deskriptor steht, warum dort kein „Hinzufügen“ ist — der lange Grund im Tooltip.
- **Handbuch:** in der Seitenleiste und in der Fußzeile — öffnet `doc/handbuch.html` in einem neuen Tab.
- **Einstellungen:** ganz unten „Danger Zone!!!!“ — gesamter Analyse-Cache (UTXOs, Verlauf, Herkunft) löschen, mit zweiter Bestätigung. Sanktionslisten und Labels bleiben.
- **Wallet-UTXO:** „Ankunft am … um …“ führt in die Herkunft; der Knopf „Herkunft →“ entfällt. „Herkunft neu“ bleibt.
- **Jüngste Sats nach Trace:** die Adresszeile übernimmt die Angabe sofort, ohne die Seite neu zu laden.
- **Offen festgehalten:** gründlichere Herkunft in der Web-GUI (CLI-Folgeanalyse / Sammel-Txs über 20 Eingänge) — siehe `ISSUES.md`.
- **Jüngste Sats:** bei vollständigem Herkunftsbaum steht die Angabe schon auf der Adresszeile (Wallet und Herkunft), ohne aufzuklappen: „jüngste sats vom TT.MM.JJJJ um HH:MM:SS“. Ein späterer Scan (mehr Adressen) blendet sie nicht mehr aus.
- **Herkunftsbaum:** oberste Ebene (Adressen, „Bereits ausgegeben“) immer zu. Darunter steht offen, was der Cache schon hat; ungescannte UTXO-Bäume bleiben zu, weil Aufklappen den Node fragen würde.
- **Aufklapp-Pfeil:** größer und dunkler; im Herkunftsbaum ist die ganze Zeile der Treffer, nicht nur das Dreieck.
- **Herkunft neu:** Knopf am einzelnen UTXO (Wallet-Liste und Herkunft) verwirft nur dessen gespeicherten Baum und verfolgt ihn erneut durch alle eigenen XPUBs bis zur ersten fremden Adresse.
- **UTXO-Zeit:** als „Ankunft am: TT.MM.JJJJ um: HH:MM:SS“ — Blockzeit dieses Outputs, nicht der Eingang beim vorherigen Dienst.
- **Wallet-Liste:** Sortierung „größte zuerst“ oder „neueste zuerst“ (UTXOs nach Eingang, ausgegebene nach Abgang).
- **UTXO-Scan-Status:** „Prüfe Adresse 50 von 101“ statt „UTXOs 50/101“ — das war die Zahl der abgefragten Adressen, nicht der Funde.
- **Sanktionskarte:** ohne Treffer unter der UTXO-Liste; bei einem Treffer darüber.
- **Wallet-Scan-Schlange:** während ein Scan läuft, stellt ein Klick auf ein anderes Wallet ihn an. Der nächste startet automatisch. Abbrechen gilt nur für den laufenden. Doppelt derselbe Scan wird ignoriert.
- **Wallet-Scan:** die Statuszeile nennt immer das gescannte Wallet. Wechselst du währenddessen zu einem anderen, steht dort ausdrücklich „läuft für …, nicht für dieses Wallet“ — Abbruch/Fehler überschreiben dessen Bestand nicht.
- **Fensteraufteilung:** Wallet-Inhalt scrollt im Bereich über dem Log. Kopf, Log und Fußzeile (Quelle) bleiben sichtbar, auch wenn die UTXO-Liste lang wird.
- **Log-Bereich:** feste Höhe (wächst nicht mit), Inhalt scrollbar, oberer Rand zum Ziehen. Die gewählte Höhe bleibt im Browser gemerkt.
- **Wallet-Name:** grüner Haken rechts neben dem Namensfeld speichert sofort — ohne zur Leiste unten zu scrollen. Enter im Feld ebenso.
- **UTXO-Scan:** Statuszeile und Log denselben Stand — „bisher n UTXOs“. Leere Folgeadressen überschreiben einen Treffer nicht mehr mit „0 UTXOs gefunden“.
- **UTXO-Scan im Log:** Gap-Scan-Zeile nennt sofort die UTXO-Zahl der gerade geprüften Adresse („darin n UTXOs gefunden“). Treffer stehen ohne Wartezeit im Log.
- **UTXO-Scan im Log:** nach dem Start nicht mehr stumm. Neue Phase (Verbinden, Gap-Scan, UTXOs) sofort; sonst spätestens alle zehn Sekunden eine Zeile, wo der Lauf steht.
- **Verlaufsscan** neben dem UTXO-Scan: erhebt die Historie **dieses** Wallets in denselben Cache, den Steuerjahr und „Bereits ausgegeben“ lesen. Im Steuerjahr bleibt der Knopf für alle Wallets (jetzt „Verlauf aller Wallets“).
- **Wallet-Ansicht:** liegt ein Verlauf vor, hängt darunter zugeklappt „Bereits ausgegeben“ — dieselben Einträge wie in Herkunft und Steuerjahr, ohne die Liste zu füllen.
- **Knopf „UTXO-Scan“** statt „Rescan“: holt nur den aktuellen Bestand, nicht den Verlauf.
- **Log-Bereich beim Start:** Sobald die Oberfläche den automatischen Verbindungstest anstößt, steht sofort „Starte Verbindungstest…“. Weitere Zeilen (SOCKS prüfen, Binary suchen, Starte Tor, Verbinde) erscheinen, während der Test noch läuft — nicht erst, wenn Tor und Node fertig sind.
- **Start9-Onion aus der GUI:** Copy-Paste als `https://….onion` wird beim Speichern und beim Connect auf den nackten Host normalisiert. Sonst scheitert SOCKS/IDNA (`label empty or too long`).
- **TLS auf Port 50001:** Handshake `WRONG_VERSION_NUMBER` wird automatisch ohne TLS wiederholt (Start9-Onion typisch Klartext).
- **„Von Electrum laden“** in den Abschnitten Öffentliche Onions (nur `.onion` → bis zu zehn `FULCRUM_TOR_0…`) und Öffentliche Electrum-Server (`electrum_servers.json`, nur Clearnet gezählt).
- **Kopfzeile:** Pille „Node verbunden“ (grün) oder „Node nicht erreichbar“ (rot); „Übernehmen“ startet denselben Test wie „Eigenen Node testen“.
- **Wallet-Liste:** statt eines kleinen „C“ der Hinweis **Cache vom TT.MM.JJJJ** (mtime der Cache-Datei).
- **Zeige Log** (Checkbox oben rechts, Standard an): unteres Drittel für späteres Fortschritts-Log. Kein Umleiten von stdout.
- **Log-Bereich:** Verbindungsversuche zum eigenen Node (Adresse, Fallback, Fehler oder Erfolg mit Privatsphäre-Einstufung). Jede Zeile mit Datum und Uhrzeit. Erfolg und Misserfolg fett, Fortschritt normal.
- **Dieses Changelog** und der Hinweis in `AGENTS.md`, es spätestens beim Commit nachzuziehen.
- Tor ohne Browser starten; Web: keine Quelle, Warnung beim ersten XPUB (`7e1eea3`)

## 2026-08-16

- Adress-Labels: fremde Adressen benennen (`26aac5c`)
- Doku: Handbuch nachgezogen, Begründung zur Deskriptor-Speicherung (`9517dc0`)
- Web-Oberfläche: Einrichtungshinweis, Tx-Historie, Hilfetexte (`8c295a6`)
- Steuerjahr: Eigenüberträge erkennen, Grundlage je Wallet, Sanktionscache (`b91e252`)
- Engine: Multisig über Deskriptor, Parallelisierung, Verlauf und Wallet-Alter (`c9766d7`)

## 2026-08-06

- webgui-integration branch in master gemergt (`2601d4b`)

## 2026-08-02

- Wallet-Alter: wann ein XPUB zum ersten Mal benutzt wurde (`840af7a`)
- Handbuch, Diagnosewerkzeug und Bauwerkzeug (`efeb86a`)
- Testfundament: 482 Tests, offline, ohne Node (`19bb1ed`)
- Herkunft: Ergebnis festhalten, statt es jedes Mal neu zu erheben (`17ab95d`)
- Sicherungen der `.env` von der Versionierung ausnehmen (`7c7eef1`)
- Web-Oberfläche: lokaler Server, Kernschicht, Frontend (`2146889`)
- Geteilte Engine: externes Anschaffungsdatum, Skripttyp-Override, Fixes (`76fd2b1`)

## 2026-07-21

- Specter Plugin erste Gehversuche (`be59469`)

## 2026-07-15

- Bessere Cache-Ausgabe mit UTXO-Markierung (`f2980ee`)

## 2026-07-14

- Disk-Negative-Cache und Cache-Size-Optimierungen (`9a880f9`)
- Fullscan, um den Cache zu befüllen, danach interaktiv flott (`86338c6`)

## 2026-07-13

- Merge `origin/master` (`0115fe1`)
- Disk-Negative-Cache und Cache-Size-Optimierungen (`d07d735`)
- Standard-XPUBs und Wallet-Namen in argparse aktualisiert (`993c7e5`)

## 2026-07-12

- Parallelisierung vieler Scans (`ed7e8d5`)

## 2026-07-11

- Sanktionsliste analysieren (`d658a58`)

## 2026-07-10

- Menüumbau (`4952b6f`)
- BIP-158 LAN-RPC: Tor nur für `.onion`, `scanblocks`-Index erkennen (`19ee807`)

## 2026-07-09

- Menüumbau (`99f40fb`)
- Menüsystem statt nur CLI; BIP-158-Scanner (damals noch ungetestet) (`1737d65`)
- Fulcrum-Rotation und `check_fulcrum_tor` für öffentliche Server aus der Electrum-JSON (`cadded7`)

## 2026-07-08

- Fulcrum statt Core — noch ungetestet (`575a3c4`)
- Refactoring in drei Dateien, `analyze` und `interact` (`a101894`)
- README (`6de095e`)
- Erstes Commit: Light-Scan nach UTXO, optionaler Saldencheck (`be1aee5`)
