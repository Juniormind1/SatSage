# Changelog

Alle nennenswerten Änderungen an SatSage.  
Neue Einträge oben. Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

**Release Notes:** GitHub-/Tag-Release-Texte entstehen nur bei Version-Bump, Merge nach `main` oder Tag — Inhalt = der dann datierte Block aus `[Unveröffentlicht]` (nicht bei jedem Dev-Push).

**Herkunft:** Die datierten Abschnitte ab `2026-07-08` stammen aus dem privaten Vorgängerprojekt **xPubQuery** und wurden unverändert übernommen; Maintainer-Bezug ist durchgängig die Projekt-Identität **Juniormind1**. Ab dem Marker **2026-09-08** gilt die öffentliche SatSage-Historie.

## [Unveröffentlicht]

- **UI · Englisch:** Hardcodierte Production-GUI-Texte (Steuerjahr, Herkunft, Scans, Cache, Wallets, Datenquellen, Importe, Assistent, QR-Atem-Witze u. a.) über Locales `de.json`/`en.json` und `t()` verdrahtet — inkl. fehlender Trace-Sort-Keys und „Lokalen Core übernehmen“.
- **Tests · .env-Scramble:** Unittests schreiben/lesen mit festem Passwort `tralala123` (scramble + descramble); kein Roh-`read_text` mehr auf Cipher-`.env`. `main._load_dotenv` liest scrambled Dateien mit Session-Key.
- **Sicherheit · `.satsage-password`:** aus dem Git-Index entfernt und in `.gitignore` — Login-Hash gehört nie ins Repo.
- **Agents · HART:** Grundregel „niemals Geheimnisse pushen oder persönliche Daten doxxen“ prominent in `AGENTS.md`, Dealbreaker **S1**, `githooks/pre-commit` blockiert Secret-Pfade.
- **.env-Scramble:** Eine Datei **`.env`** — mit Passwort scrambled (Magic `SSGB1`), ohne Passwort Klartext. **`.env.backup0`…`9`** werden mitgesetzt (scramble bei Passwort, unscramble bei Löschen, Umschlüsselung bei Änderung). Kein `.env.gobbledigook` mehr; Legacy wird migriert. Login = Hash + File-Key. CLI/Specter/Umbrel/Start9 ausgenommen. Doku (Handbuch §11, README): `.env` at rest mit Passwort; Caches/Exporte Klartext — Schutz über verschlüsselte Volume (FDE/VeraCrypt), SatSage vor dem Schließen beenden.
- **Login · Passwort bei GUI-Start:** Ist ein App-Passwort gesetzt, reicht ``?t=``/Token auch auf Loopback nicht mehr — Login-Seite nach Serverstart. Session-Cookie nach Anmeldung wie bisher.
- **Einstellungen · Passwort (Windows):** Login-Hash ohne ``os.fchmod`` (fehlte → ``AttributeError`` → Browser-NetworkError). Löschen per **POST** statt DELETE+Body. Aktuelles Passwort wird bei Entfernen eingefordert (Fokus aufs Feld).
- **UI · Fiat-Historie an Summen:**
 Steuerjahr (Kennzahlen, Gruppen, Abgänge), Meta-Zeilen und Trace-Knoten/`atTs` — **nur** wenn alle saldierten Zeilen denselben Kalendertag haben; sonst nur sats/BTC (kein Spot-Mix).
- **Cache · Tageskurs EUR+USD:** Neue UTXO-/Verlaufs-/Ingress-/First-seen-/Blockzeit-Einträge speichern bei Datum den **BTC-Tageskurs EUR und USD** sowie bei Sat-Volumen die **Fiat-Gegenwerte** (`btc_eur`/`btc_usd`/`value_eur`/…, bei Ausgaben `spent_*`). Nur lokal aus Historie, kein Backfill-Job, bestehende Felder bleiben.
- **UI · Listen-Filter:** Wallet + Herkunft — Adresse/TxID, Börse/CJ-Label (`Kraken`, `Wasabi`, …), Betrag `>n`/`<n`, Datum. Andere Ansichten ausgegraut.
- **Start · .env-Modus:** Unter Windows keine Dauer-Warnung mehr „Modus … 0666 → 0600“ — ``chmod`` greift dort nicht; Prüfung nur noch auf POSIX.
- **Wallets · Löschen:** Log **„Lösche …“** / **„Löschen beendet“** (Timestamps), bei vielen Cache-Dateien Zwischenstand. Langsam v. a. durch Walk über UTXO-/Verlauf → je Tx Herkunfts-/Ingress-Dateien (Import-Wallets).
- **Wallets · Adressen nachziehen:** Nach Export-Import wartet der Job bis ~2 min auf den Indexer (Tor-Bootstrap), statt still abzubrechen. Log: **„Adressen nachziehen braucht Indexer…“** / Warte-Zeilen; ohne Konfiguration klare Meldung, Adressen bleiben unzugeordnet sichtbar.
- **Wallets · Suche:** Schon bekannte Schlüssel (z. B. zpub „Cash & Carry“) blenden Specter-/Wasabi-Treffer mit anderem Namen („Cash+Carry“) aus — Abgleich über Adress-ID und Schlüsselkennung, nicht nur rohe zpub-String-ID. Import legt solche Duplikate nicht erneut an.
- **Log · Tor-SOCKS:** Kein Heartbeat mehr („Prüfe Tor-SOCKS… / erreichbar“) bei Routine-Recheck mitten im Scan. Log nur noch bei **echter Wiederherstellung** nach Ausfall bzw. Tor-Autostart.
- **Empfang · QR:** QR-Bereich bleibt nach Dock-/Spalten-Resize **quadratisch** (größtes 1:1 in der Pane-Fläche); Maske und Konfetti am Quadrat.
- **Log · UTXO-Scan:** „BIP-158 ab Wallet-Beginn …“ / „BIP-158 nicht vor …“ nur noch, wenn der Scan wirklich über BIP-158 läuft — nicht mehr vor der Quellenwahl (z. B. Fulcrum).
- **Wallets · Suche-Log:** Beim Suchen erscheinen im GUI-Log nacheinander **Suche Sparrow…** / **Wasabi…** / **Specter…** / **Electrum…** / **Bitcoin Core…** (live); Log-Zeilen nicht mehr doppelt; Abschluss **Suche X… n gefunden**.
- **Wallets · Suche:** „Load failed“ behoben — Antwort wieder normales JSON mit `logs[]` (NDJSON-Stream unter WebKit unzuverlässig); Log-Reihenfolge inkl. „n gefunden“ bleibt.
- **Wallets · Wasabi-Suche:** Ordnersuche liest den BitcoinStore **nicht** mehr mit (nur Deskriptor) — vorher ~15 s Pause vor Electrum; Store-Verlauf weiter beim **Import**.
- **Wallets · Specter:** Lokale Specter-Desktop-JSON (`recv_descriptor`/`change_descriptor`, gleiches Layout wie Plugin-Bridge) such- und importierbar.
- **Wallets · Electrum:** Unverschlüsselte Wallet-Dateien (nur xpub/Öffentliches; xprv/seed verworfen); verschlüsselte mit Schloss.
- **Wallets · Bitcoin Core:** Angeschlossener Node per RPC (`listwallets`/`listdescriptors`) — Descriptor-Wallets importierbar.
- **Wallets · Suchliste:** Herkunft **rechtsbündig** (Wasabi / Specter / Electrum / Bitcoin Core / …).
- **Wallets · Wasabi-Suche:** Wallet-JSON mit UTF-8-BOM (Wasabi-Standard) gilt wieder als importierbar — vorher fälschlich „Kein JSON“.
- **Wallets · Export-Suche:** Gefundene importierbare Wallets standardmäßig **unchecked** — Nutzer wählt ausdrücklich. Liste: zuerst importierbar, dann gesperrt; jeweils A–Z.
- **Wallets · Export-Knopf:** Ein Knopf **Datei(en) importieren** / bei Auswahl **Wallet(s) importieren** (separater Import-Knopf entfernt). Nach Import Wechsel zum Wallet (bei mehreren: alphabetisch erstes).
- **Wallets · Import-Pille:** Nach Export-Import grün **importiert** auch ohne offene UTXOs (leerer UTXO-Cache + Verlauf zählt); `ORIGIN=wallet_export` wird bei Re-Import nachgezogen.
- **Wallets · Wasabi-Hot:** Passwortgeschützte Wallets (`EncryptedSecret`) nicht mehr importierbar (nur gelistet mit Schloss); kein automatisches Anlegen von SegWit/Taproot aus dem Hot-Secret.
- **Wallets · Wasabi-Import:** Adressen aus `HdPubKeys` (PubKey→Adresse); UTXOs und **bereits ausgegeben** aus lokalem `BitcoinStore`/`Transactions.sqlite`, soweit vorhanden.
- **Wallets · Cache löschen:** Listet auch **nicht konfigurierte** (verwaiste) Cache-Kennungen — einzeln löschbar, ohne Gesamtlöschung.
- **Wallets · Import-Pille:** Nach Sparrow/Wasabi-Export grün **importiert** (alle Verlaufsadressen) bzw. gelb **importiert** (noch Lücken); aktualisiert sich nach Adressen-Nachziehen.
- **Wallet-Export · Adressen nachziehen:** Electrs-Job mit Batch; Fortschritt im **GUI-Log** (nicht nur stdio). Ableitung mind. 500/Kette (Gap); Spends ohne Wert-Match am Prevout. Knopf **Datei(en) importieren** orange.
- **Wallet-Export-Import · Stabilität:** Descriptor+CSV per Klartext (kein Base64-Freeze), Timeout, Sofort-Log, Fehler beenden „Export wird gelesen…“; CSV immer als Tabelle; Server-Text-Upload und Größenlimit.
- **Bereits ausgegeben · Export-Verlauf:** Wallet-Name aus Cache-Kontext, wenn Sparrow-Tx-CSV keine Adresse hat (nicht mehr „unbekanntes Wallet“); leere Adresszeile als „ohne Adresse (Export)“.
- **Log · Release-Zeile:** Beim Start steht die laufende SatSage-Version (`SatSage v…`) als erste Zeile im Log-Bereich.
- **Wallets · Export-Import (Sparrow / Wasabi):** Unter Multisig: **Suchen** in Standardordnern, Liste mit Checkboxen (Schloss = nicht direkt lesbar: Passwort **oder** native Sparrow-DB), orangener **Import** der Auswahl; manuell **Datei wählen…**. Format-Auto-Erkennung; Herkunft `WALLET_n_ORIGIN` (`xpub` / `descriptor` / `wallet_export`) — schon vorhandene entfallen in der Suche. Wasabi-JSON View-only/HW importierbar; Sparrow-`.mv.db` nur nach Descriptor-Export. Kein Passwort-Dialog. Multisig-**Import** orange wie „Hinzufügen“.

## [0.9.6] — 2026-09-17

- **Tests / Stabilität:** Unittest-Suite wieder grün — u. a. Tor erst nach LAN-Fail, SSL-Hinweistexte an Auto-Flip, Trace-Sort-IDs im HTML, Job-Gate-Reset in Tests, Empfangs-Ka-Ching nach Tip-Sync.
- **Empfang · Mempool-Sprung:** Reihenfolge jetzt: Adresse benutzt bemerkt → **Konfetti auf alter QR** → Wallet-Update (Pending) → **neuer QR erst nach Animation**.
- **Empfang · Ka-Ching:** Mempool-Eingang während Tip-Sync / Empfangs-Schärfung wurde verschluckt (QR sprang, kein Konfetti). Incoming wird gemerkt; Index-Sprung kurz nach Tip-Sync holt Ka-Ching nach.
- **Sanktionsprüfung · UI:** Nach Seitenwechsel / Klick auf den Vorgang erscheint die **Fortschrittszeile** wieder (Job wird neu angebunden, Poller fortgesetzt).
- **Sanktionsprüfung · Fortschritt:** Hop-0-Adresse und Origin-Events werden sofort gematcht/gezählt — die UI klebt nicht mehr bei „Hop 0, 0 Adressen“, während Frontier-`get_tx` nachzieht. Lücken einzeln mit Status „Lücke i/n“; fehlgeschlagene Frontier-Tx überspringen statt Endlos-Warten.
- **Sanktionsprüfung · Abbruch:** Cancel greift jetzt auch mitten im Hop-Walk / vor `get_tx` (nicht nur zwischen UTXOs) — „Abbruch angefordert“ bleibt nicht wirkungslos.
- **Steuerjahr · klären (gelb):** Nutzt `eintraege` (Bugfix); Mehrfachklick gesperrt. Gelb startet pragmatisch voll bis extern/Coinbase. **Zwei-Tiefen-Abnahme** (Horizont vs. voll) bewusst **nicht** für 0.9.6 — späteres Release (siehe ISSUES / Testplan C1).
- **Herkunft · Exchange-Batch:** Soft-Label „**u. a. Auszahlung von Kraken**“ (ggf. mehrere Namen), sobald Börsenadressen am Batch bekannt sind — „u. a.“, weil nicht alle Inputs von der Börse sein müssen. Sonst weiterhin „Wahrscheinlich Batch…“.
- **Herkunft · Börsen-Label:** Anzeige nur noch der **Börsenname** (nicht „Börse · …“). **Grün** = Zufluss Börse→Wallet, **rot** = Abfluss zur Börse (Einzahlung dort).
- **Herkunft tracen · Sortierung:** Dropdown (Volumen/Alter) gilt auch für **„Bereits ausgegeben“**, nicht nur für den UTXO-Bestand darüber.
- **Herkunft · Adressgruppe:** Börsen-Namen (z. B. Kraken, Coinbase) aus dem Trace erscheinen wie Mix-Icons in der **Gruppen-Kopfzeile**, sobald entsprechende Adressen/TxIDs im Verlauf vorkommen.
- **Börsen-Reports:** Papierkorb-Icon statt „Entfernen“. Import akzeptiert CSV **ohne** Kopfzeile bzw. reine Adress-/TxID-Listen (bc1…, Legacy ``1…``, P2SH ``3…``).
- **Datenquellen · Bezeichnung:** „UTXO-Set-Quelle“ → **pruned UTXO-Set-Quelle** (Rolle scantxoutset / oft pruned Node).
- **P2P · Zeile:** Stift-Dialog entfernt. Inline-Feld mit Placeholder „erster Scan-Block“; Extra-Peers und Tor-Proxy nur noch über `.env`.
- **Datenquelle · Staub-Jubel:** Staub im QR-Feld bei **jedem** erfolgreichen Speichern/Test einer Verbindung mit Privatsphäre **hoch** (eigener Indexer oder P2P, auch nach IP-Wechsel). Öffentliches Electrum: kein Jubel.
- **Einstieg · leer:** Ohne Wallets und ohne eigenen Indexer/Onion öffnet die GUI **Datenquellen** — mitgeliefertes `electrum_servers.json` und P2P zählen dafür nicht.
- **P2P trennen:** Papierkorb an Compact Filter bricht laufende Header- sowie UTXO-/Verlaufs-Scans (inkl. Queue) ab; Electrum und erneuten Scan startet der Nutzer selbst.
- **BIP-158 · Abbruch:** Cancel-Event gilt auch in Filter-/Block-Worker-Threads (kein ContextVar); Warte-Schleifen starten bei Abbruch keine neuen Peers mehr. Scan-UI bleibt auf „Abbruch angefordert…“ bis der Job wirklich `cancelled` ist (nicht mehr sofort „fertig“ vortäuschen).
- **Datenquellen · öffentlich:** Stift an öffentlichen Onions entfernt (Liste nur „Verbinden“ / `.env`). „Verbinden“ bleibt voll sichtbar, auch wenn die Zeile sonst noch unkonfiguriert/gedimmt ist.
- **Öffentliches Electrum:** Nach Opt-in zuerst **Clearnet**; öffentliche Onions nur wenn Clearnet fehlt. Steht Clearnet, werden Onion-Peers nicht mehr als verbunden geführt und ein Tor-Autostart für öffentliche Onions beendet — Scans nutzen den Tor-Flaschenhals dann nicht.
- **Nav · keine Wallets:** „noch keine“ unter Wallets öffnet Verwaltung · Wallets (Neunutzer-Kürzel).
- **UTXO-Scan · öffentliche Electrum:** `RotatingFulcrumPool` kennt `tor_batch_sinnvoll` (immer aus) — Scan über Clearnet-Rotation stürzt nicht mehr mit `AttributeError` ab.
- **Datenquellen · Verbinden:** Knopfbeschriftung „Von Electrum laden“ → **Verbinden**. P2P: Checkbox „P2P aufbauen“ aus den Details entfernt; gleicher Schalter als **Verbinden** in der P2P-Zeile (wie bei Electrum), Papierkorb schaltet weiter aus.
- **Öffentliches Electrum · Probe:** Clearnet-Stichprobe nicht mehr die ersten 8 Einträge der alphabetischen Liste (oft tote IP-Literale), sondern zufällig bis 8 und bei 0 Treffern eine zweite Runde. Tor-Autostart wartet auf Bootstrap 100 %, bevor `.onion`-Probes laufen (SOCKS allein war zu früh).
- **Kopf · Log-Schalter:** Statt Checkbox „Zeige Log“ nur noch kompakter Knopf **Log** (wie DE/EN daneben) — an = Akzent, aus = gedimmt.
- **Datenquelle · Pille nach Übernehmen:** Speichern von Electrum/Core setzt die Kopf-Pille sofort **grau** (Indexer/Core) und verwirft den alten Connect-Stand. Grün + konkreter Name (`libbitcoin`/`electrs`/`fulcrum`) erst nach erfolgreichem Verbindungstest — kein Weitergrün mit dem vorigen Endpoint.
- **Dock · Empfangs-QR ziehbar:** Zwischen Assistent (LLM) und Empfangs-QR wieder ein horizontaler Spalter — Breite speichert sich (`xpq-dock-empfang`). Die QR-Fläche folgt der Spaltenbreite (QR bleibt innen quadratisch), nicht mehr starr an die Dock-Höhe gekoppelt.
- **Kopf-Pille · Indexer:** Vor dem Handshake grau **Indexer**; sobald Tip-Sync/Empfang den eigenen Electrum-Server nutzt, sofort grün mit `libbitcoin`/`electrs`/`fulcrum` (aus `server.version`) — nicht erst nach dem 30‑s-Peer-Takt. Log: `1 libbitcoin verbunden` statt generisch „electrs“, wenn die Software bekannt ist.
- **Tor/Electrs · Performance:** SOCKS-Check wird 90 s gecacht (kein Dauer-„Prüfe Tor-SOCKS“). UTXO-Scan, Herkunft und verwandte Jobs laufen **nacheinander** (Electrum-Gate) — nicht parallel auf demselben Tor-Socket. Stiller Peer-Takt verbindet währenddessen nicht neu zu own_fulcrum.
- **Eigener Electrs · Config-Wechsel:** Host/Port/TLS speichern startet die Verbindung neu (Wallet-Watch-Session + Empfangs-Client). Altes `FULCRUM_TOR_PORT`/`FULCRUM_TOR_SSL` wird beim Speichern des UI-Ports/TLS gelöscht — sonst blieb der Verbindungsversuch am alten Endpoint hängen (nur Server-Neustart half).
- **Electrs über Tor · JSON-RPC-Batch:** Beim eigenen Node über Tor bündelt SatSage `listunspent`/`get_history` (UTXO-Scan, Wallet-Alter, **Gap-Scan**) in Batches — weniger Roundtrips auf dem einen Socket. Gap-Scan: Fenster-Batch, Auswertung weiter indexweise inkl. Gap-Limit; Log kann `· Batch N` zeigen. LAN/Parallel-Pool und öffentliche Server unverändert.
- **Herkunft · unvollständig rot:** Lückige/abgebrochene Bäume zeigen **„unvollständig · Datum“** in Rot statt grün „verfolgt“.
- **Herkunft · Resume:** „Scan neu“ / Lücken schließen verwerfen brauchbare Teilbäume nicht mehr — fertige Zweige bleiben, nur Lücken (error-Prevout, tax_horizon, unvollständige interne Äste) werden nachgezogen. Leere/kaputte Stände starten weiterhin von null.
- **Herkunft · leerer Trace:** Wenn die Vorgänger-Tx nicht ladbar war, endet der Baum nicht mehr still mit „Keine Zuflüsse ermittelbar“ und leeren Kindern. Stattdessen sichtbare Lücke (error-Blatt) und Hinweis auf unvollständige Herkunft — „Scan neu“ / Lücken schließen. Ursache war u. a. still übersprungene Prevouts.
- **Öffentliches Electrum · Sitzungs-Opt-in:** Die Freigabe („Privatsphäre gering“) gilt nur bis zum Server-Neustart — nicht mehr dauerhaft in der `.env`. Beim Start wird ein altes `OEFFENTLICHE_ELECTRUM=1` entfernt; der Dialog erscheint erneut, sobald öffentliche Server nötig wären. CLI: weiterhin `--oeffentliche-electrum` / `.env` für Headless.
- **Empfang · öffentliches Electrum:** Nach Opt-in (`OEFFENTLICHE_ELECTRUM`) prüft die freie Empfangsadresse per `get_history` auch über den öffentlichen Pool — nicht nur über den eigenen Electrs. Ohne Opt-in bleibt die Cache-Schätzung mit Warnung.
- **Empfang · Cache-Warnung:** „Schätzung aus Cache …“ erscheint nur noch einmal (Quelle-Zeile), nicht doppelt unter Index.
- **Datenquellen · Börsen-CSV:** Transaktionsreports importieren (Knopf unter Datenquellen). Nur Bitcoin-Adressen und TxIDs — Kurse und andere Coins verworfen. Pro Börse eine Cache-Datei (`exchange_reports/`); Herkunft zeigt Klarname „Börse · …“ (optional Ein-/Auszahlung). Trace **endet** an Börsen-Adresse/Tx — keine Hops hinter die Ein-/Auszahlung.
- **Sanktionscheck · CoinJoins im Hop-Fenster:** Beim Scan über n Hops werden Form-Heuristiken (Wasabi/WabiSabi/Whirlpool/JoinMarket/Mix) hervorgehoben — z. B. „Keine sanktionierte Adresse in den letzten n Hops. CoinJoins: Hop m · Zeit · vermutlich …“. Soft-Label, keine forensische Sicherheit; im Walk-Cache und in CLI/Web.
- **Herkunft · Fan-In vs. Fan-Out:** Rein eigene Spends trennen nach Richtung — Fan-Out nur noch bei mehr Outputs als Inputs (≥3 Outs, Auszahlung/Split); Fan-In bei mehr Inputs als Outputs (Konsolidierung n→wenige). Soft-Label „eigene Konsolidierung (Fan-In)“.
- **Einstellungen · Darstellung:** Hell/Dunkel als Radiobuttons statt Dropdown.
- **Herkunft · flache Hierarchie im Wallet:** Einrückung nur bei Wallet-Wechsel (oder Extern/Coinbase), nicht mehr pro Hop innerhalb desselben Wallets — Web-Baum und HTML-Hop-Bericht.
- **Einstellungen · Persönliche Daten:** Name, Steuernummer, Anschrift, E-Mail sowie zuständiges Finanzamt, FA-Adresse und Sachbearbeiter für HTML-/CSV-Berichte; Name/FA-Defaults Donald Duck / 0/8/15 / Entenhausen. Lokal in `.env` (`STEUER_PERSON_*`).
- **Block-Explorer · öffentlich mit Warnung:** Öffentliche Adressen (z. B. mempool.space) speichern nur nach Bestätigung im Warndialog; Abbruch leert das Feld und speichert nicht. Kopf-Pille **Block-Explorer** (privat grün / öffentlich rot / unkonfiguriert grau ohne Zusatztext).
- **Steuerjahr · klären:** Knopf „Herkünfte UTXOs“ → **klären** (EN: **trace**), nur in der Scorecard „Ohne Herkunftsanalyse“ (sichtbar solange graue UTXOs fehlen).
- **Steuerjahr · Bericht Sat-Geschichte:** Karte und Export heißen nicht mehr „Selbstanzeige“ (Titel, HTML/CSV, Dateiname).
- **Log · Verbindung:** Kopf/Wechsel zeigt **Peers und electrs gemeinsam** (z. B. `3 Peers · 1 electrs verbunden`) — kein Quatsch-Wechsel „Peers → onion-electrs“, solange beides parallel da ist.
- **Nav · Auswerten:** Steuerjahr steht über Herkunft tracen.
- **Herkunft tracen · Erklärtext:** Hinweis auf Herkunftsnachweise im Kontext Geldwäschegesetz (EN: AML laws).
- **Sanktionscheck · xpub-blind:** Vorgeschichte wie ein Dritter ohne XPUB — jeder Prevout-Hop zählt (keine Skip-Logik für eigene Adressen). Hop 0 = UTXO-Adresse selbst. Grün = keine gelistete Adresse im Hop-Fenster.
- **Sanktionscheck · Cache:** Nutzt Herkunfts-``origin_tree`` und speichert den Hop-Graphen als ``*.sanction_walk.json`` neben dem Trace-Cache; Live-``get_tx`` füllt den Tx-Immutable-Cache. Zweiter Lauf / Listen-Update matcht nur noch die Liste, ohne Chain erneut abzulaufen.
- **Herkunft · zwei Tiefen:** Steuerjahr **Herkünfte UTXOs** bricht am Stichtag/Haltefrist-Anfang ab (oder extern/Coinbase) — schneller für Anschaffungsdatum. Herkunft tracen geht immer bis extern/Coinbase und setzt Steuer-Teilbäume fort (`origin_tree`), statt alles neu zu rechnen.
- **Herkunft · Knopftext:** „Herkunft aller UTXOs“ / „UTXO Herkunft“ → **Herkünfte UTXOs** (Steuerjahr und Herkunft tracen; Funktion unverändert).
- **Steuerjahr · UTXO-Liste klappbar:** „außerhalb Haltefrist“ und „innerhalb Haltefrist“ sind Gruppen, initial zugeklappt (Anzahl + Summe in der Kopfzeile) — die lange Tabelle erdrückt die Ansicht nicht mehr.
- **Steuerjahr · Kennzahlen oben:** Scorecard (Bestand gesamt, außerhalb/innerhalb Haltefrist, ohne Herkunftsanalyse) steht über dem Zeitstrahl-Dotplot.
- **Steuerjahr · Knopftexte:** „Verlauf aller Wallets“ → **Historien** (Plural, alle Wallet-Historien; Wallet-Ansicht bleibt „Historie“).
- **Git · commit-Skripte:** `scripts/commit.sh` / `commit.bat` stagen im Default untracked **Textdateien** mit; untracked **Binärdateien** nur nach Nachfrage (`-A` = alles, `-u` = nur getrackt). Verhindert Commits ohne neue Skripte/Quellen.
- **Steuerjahr · Punkte ohne Herkunft grau:** UTXOs **innerhalb** der Haltefrist ohne Herkunftsanalyse sind im Zeitstrahl grau statt gelb (dunkelgrau Light-Mode, hellgrau Dark-Mode). **Außerhalb** der Frist bzw. prä-Stichtag bleiben sie grün — auch ohne Trace. Legende: „ohne Herkunft“.
- **Log · Job-Start/Ende greppbar:** Lange Vorgänge (UTXO-Scan, Verlauf aller Wallets, Herkunft aller UTXOs, Herkunft vollständig, u. a.) schreiben `JOB-START` und `JOB-ENDE` mit kind, id, Wanduhr, Status und Dauer ins Log — im Log-Bereich und Terminal-Spiegel suchbar.
- **Steuerbericht · Hop-Kette:** HTML-Aufstellung und Selbstanzeige-Report enthalten den vollständigen on-chain Herkunftsnachweis (Trace-Cache, nested Hops) — Beleg für Haltedauer, keine Börsen-/Konto-Belege.
- **Datenquelle · Staub-Jubel:** Nach erfolgreichem Speichern + grünem Node-Test einmal viel Staub-Konfetti (keine großen Scheine) — Belohnung für die knifflige Config.
- **Datenquelle · TLS automatisch:** Electrum-Verbindung probiert bei Protokoll-Mismatch die andere TLS-Einstellung (an↔aus) und schreibt den Erfolg nach `FULCRUM_SSL` / `FULCRUM_TOR_SSL` in die `.env` (nicht unter Start9/Umbrel-Bridge).
- **Datenquelle · Pille zeigt Implementierung:** Nach dem Electrum-Handshake steht in der Kopf-Pille `electrs` / `fulcrum` / `libbitcoin` (aus `server.version`), nicht nur „Electrum privat“. Handshake pro TCP-Session nur einmal — libbitcoin lehnt ein zweites `server.version` ab.
- **Herkunft · interner Übertrag erkannt:** Change-Adressen jenseits von `max_addresses`, die der UTXO-Scan schon kannte (`scan_end_index`), werden wieder geseedet. Sonst wirkte z. B. Cash+Carry→Firmung fälschlich als „Extern“ (match_own ohne HD-Suche).
- **Steuerjahr · „Verlauf aller Wallets“:** Nach Fertigstellung Nav sofort mit frischem Cache-Alter („gerade eben“) — nicht erst nach Browser-Refresh (`ladeConfig` wie beim Einzel-Verlaufsscan).
- **Abbruch · alle Jobs enden sauber:** Web-Job-Abbruch gilt jetzt überall, wo bisher nur CLI-`q` zählte (`is_list_abort_requested` + Job-ContextVar). BIP-158-Filter/Block-Worker, Gap-/Electrs-Scans, Label- und Listen-Downloads prüfen Abbruch; `Cancelled` wird nicht mehr in bare `except` geschluckt. Job-Ende immer mit Status `cancelled` und Meldung „Abgebrochen.“ Nav-Vorgänge, Labels und Sanktionslisten haben Abbruch-Knöpfe; wartende Scan-Queue-Einträge lassen sich entfernen.
- **Herkunft · Lücken schließen bricht ab + meldet Fortschritt:** Die erste Tiefen-Phase (gebündelte Eingänge) lief ohne Fortschritts-Callback und schluckte `Cancelled` in bare `except Exception` — Abbruch wirkte nicht, UI blieb bei einer Zeile stehen. Jetzt: Progress/Cancel durchgängig (Engine, Classify, Follow-ups), Meilensteine und „Moment noch“ im Job-Log.
- **GUI · Userflow-Testframe:** `scripts/webgui_userflow.py` (+ `doc/testprotokoll-webgui-userflow.md`) — deterministischer Klick-Pfad durch Wallet/Herkunft/Steuerjahr/Sanktionen/Verwaltung; Exit 0 = freigabefähig. Assistent führt den Lauf aus, bevor GUI-Änderungen als fertig gelten.
- **Herkunft tracen · hängt nicht mehr an „Lade aus Cache…“:** Verlaufsadressen (oft Index ≫ `max_addresses`) werden aus dem Verlaufs-Cache ins Wallet-Mapping geseedet — ohne HD-Suche bis `MAX_TRACE_ADDRESS_SEARCH` je Adresse × alle XPUBs.
- **Steuerjahr · Selbstanzeige:** Ungültige TxID im Filter → 400 statt „Interner Serverfehler“. Report akzeptiert TxID im Eingabefeld ohne Checkbox (auch `txid:vout`). HTML-Report: Blob-Tab statt leerem `window.open`, Fehlerseite statt JSON, CSS-Print-Strings ohne kaputte Quotes. UTXO-Liste: Checkboxen, „Alle ankreuzen“, Chunk-Laden; Tax+Kandidaten parallel.
- **Empfang · Konfetti nur bei Mempool-TxIN:** Adresssprung nach UTXO-Scan/Gap löst kein Ka-Ching mehr aus; Konfetti nur wenn `pending_receive` steigt (und nicht während Scan).
- **Empfang · Orange-₿ bei schnellem UTXO-Scan:** Läuft die Fund-Animation, werden weitere Funde still verworfen (kein Nachklapp); `stop`/Empfang-Refresh bricht Orange-₿ nicht mehr ab. ₿ nur ab **500 sats** (Dust); Größe log1p **15 %…90 %** der QR-Seite, 90 % ab 500 k sats.
- **Kurs · Spot klemmt nicht mehr:** Eigene `MEMPOOL_URL` (LAN, Self-Signed) nutzt denselben TLS-Pfad wie Node-Anbindung; Spot-Fallbacks (mempool.space/Coinbase) und Historie-Nachzug brauchen **kein Opt-in** mehr (nur Fiat-Kurse).
- **Kurs · Historie immer nachziehen:** Lücken bis gestern füllt SatSage von allein (Bitstamp/CDD, sonst Mempool-Tageskurse). Einstellung/Checkbox entfällt; CSV-Import bleibt für Puristen.
- **Kurs · Sprache steuert Fiat:** UI **DE → EUR**, **EN → USD** (Spot-Kopfzeile und ≈-Umrechnung inkl. Tageshistorie); Sprachwechsel lädt Kurs und Serie neu.
- **Web · Sprache DE/EN:** Header-Knöpfe und Einstellungen nutzen denselben Wechsel (`UI_LANG` + Katalog). Fiat folgt der **aktiven** UI-Sprache (`currentLang`), nicht allein `config.ui_lang`/`Accept-Language` — behebt „DE-Texte + USD-Kurs“. DE/EN-Handler werden **sofort** beim Start gebunden (nicht erst nach Header-Job); Sprachwechsel hängt nicht am Speichern von `UI_LANG`.
- **Umbrel · App-Store-Paket:** `packaging/umbrel/` (Manifest, Compose, `exports.sh`, pre-start), Doku `doc/UMBREL-packaging.md`, Community-Store-Generator `scripts/build_umbrel_community_store`, Dev-Install `scripts/umbrel_dev_install`, Image-Build-Workflow `.github/workflows/build-docker-image.yml`. Dev-Pin: `ghcr.io/juniormind1/satsage:latest` (ohne Digest); Manifest-`version` folgt `VERSION` (0.9.2). Fester Tag+Digest und Store-Release erst mit **0.9.6** beim nächsten Merge nach main.
- **Umbrel · Managed-Modus:** `SATSAGE_MANAGED_BY=umbrel` — Electrum/Core/Mempool aus Compose-Env (runtime-only), Bridge-Quellen in der UI gesperrt, Bootstrap-Passwort aus `APP_PASSWORD`, Login hinter `app_proxy` bleibt. Gemeinsame Mengen `_NODE_MANAGED`/`_MANAGED_MODI`; `_electrum_indexer` statt `_start9_electrum_indexer`.
- **Container:** Dockerfile/Entrypoint setzen `SATSAGE_MANAGED_BY` nicht mehr fest auf `start9`; `/data` gehört `1000:1000` (Umbrel-UID).
- **Web · Sprache:** Ohne `UI_LANG` folgt die Web-UI `Accept-Language` (sonst EN); Login-Seite zweisprachig. `storedLang()` blockiert Config-Sprache nicht mehr mit falschem Default-`de`.
- **Web · Fußzeile:** „nur lokal erreichbar“ nur wenn `local_only` (Listener wirklich Loopback) — relevant hinter Umbrel `0.0.0.0`.


- **Steuerjahr · Chart:** UTXO-Betragsbeschriftungen am Plot entfernt (nur noch Hover-Tooltip).
- **Start-/Tip-Aktualisierung:** Nav zeigt „gerade eben“ je Wallet, sobald dessen Tip fertig ist — nicht erst, wenn alle Wallets durch sind (`done_wallet_ids` im Job-Meta). Light-Tip: ein `listunspent`-Durchgang pro bekannter Adresse (vorher Prune + Live doppelt). Empfangs-Atem läuft auch bei Read-only und nach Wallet-Wechsel, solange dieses Wallet noch „aktualisiere…“ ist (nicht nur beim ersten schnellen Wallet).

- **Herkunft · Abbrechen:** Statuszeile fixiert den Knopf rechts (kein Springen bei wachsendem Text); Abbruch auch vor Job-ID und ohne Event-Bubbling zum UTXO-Kopf.
- **Herkunft · Fan-Out-Hang:** Bei Txs mit hunderten Outputs (z. B. 608 Outs) hing der Trace in `match_own_address` → `resolve_address` (HD-Suche je fremder Adresse, Abbruch wirkungslos). Jetzt nur O(1)-Lookups; Eigentums-Scan meldet Fortschritt und ist cancelbar.
- **Herkunft · Job-Klick:** Wallet-Name in Job-Meta (`wallet_name`); nach Browser-Neustart kein „unbekanntes Wallet“ mehr beim Anbinden eines laufenden Trace-Jobs.
- **Herkunft · Cache-first:** POST `/api/trace` ohne followup liefert bei vorhandenem Trace-Baum sofort aus dem Immutable-Cache (kein Job, kein Electrs). Plot-Klick und Ankunft nutzen das; Electrs nur wenn kein Baum liegt.
- **Log · FiFo-Kandidaten:** Cache-Nachladen der Abfluss-/Was-wäre-wenn-Liste loggt nicht mehr als „Selbstanzeige:“ (Auto still; manuell „FiFo-Kandidaten:“). Das war kein Trace — nur GET Kandidaten beim Steuerjahr.
- **Herkunft · Sprung aus Steuerjahr:** Wallet-Name kommt vom angeklickten UTXO (nicht mehr vom zuletzt gewählten Nav-Wallet, z. B. „Firmung“ während des Scans). CLI-Fehler `can't access local variable trace_mod` beim Laden gespeicherter Bäume behoben (Import-Scoping).
- **Herkunft · externe Blätter:** Eingangsdatum (Blockzeit des Prevouts) an jedem aufgelösten externen TxIN. Die Analyse hatte `time_ts` schon; die UI-Knoten übernahmen es nicht. Alte Bäume: Nachzug aus dem Tx-Cache beim Laden.
- **Steuerjahr · Zeitstrahl:** Visualisierung ganz oben; X startet 6 Monate vor ältestem UTXO; Y eine Dekade über Max; Labels kontrastreicher; „sats vor Haltefrist: …“ horizontal links vom Ring. Mittelklick-Pan; Bubble → Herkunft.
- **Herkunft-Jobs:** Doppelstarts desselben UTXO unterbunden (Server: laufenden Job wiedergeben; Client: Race + Nav-Klick bindet an). Fortschritt im Log; Status zeigt letzte Logzeile.
- **Wallet-Nav · Tip-Lag:** Nach Wallet-Watch/Spend-Settle bleibt die Cache-mtime frisch, `scan_tip_height` hing aber oft zurück („vor 12 Min · −53 Blöcke“). Settle hebt den Tip jetzt wie Light-Sync über Header/Electrs an (nie absenken).
- **Steuerjahr · Zeitstrahl:** Kein Bündeln mehr vor der Haltefrist — jedes UTXO auf echtem Datum (grün/gelb ausgefüllt). Geister-Saldo als Ring auf y=0 mit volumensabhängigem Radius (Log-Y nur Einzel-UTXOs). X-Pan über window-Listener (nach Zoom). Y-Achse dekadisch (`1 sat` … `100k sat`, ab `0,01 btc`).
- **Wallet-Knöpfe:** Nach Sortierung steht **UTXO** als Präfix vor **Bestand**, **Historie**, **Herkunft** (früher UTXO-Scan / Verlaufsscan / Herkunft vollständig).
- **Empfang · interne Transfers:** Animation nur am **aktuell gewählten** Wallet. Ausgang an ein eigenes Wallet (z. B. Cash+Carry→Bitkey) oder Self-Send: nur **Konfetti**, kein „OH NO!“. Fremder Ausgang: weiterhin „OH NO!“.
- **Herkunftsliste · Tempo:** UTXO-Adressen aus dem Cache in den Wallet-Kontext seedern (kein teures `resolve_address`-Nachableiten). Adressgruppen bauen UTXO-Zeilen erst beim Aufklappen; Bäume weiterhin nur bei Klick aufs UTXO.
- **Tip-Nachzug · Nav früher grün:** Sobald die UTXOs am Tip sind, zeigt die Wallet-Liste „gerade eben“ — Empfangs-QR-Schärfung (Electrs) läuft danach ohne „aktualisiere…“; Verfügbarkeit am QR.
- **Herkunft · zwei Einstiege:** Sprung aus dem Wallet = **Fokus nur dieses UTXO**; Knopf „Alle UTXOs zeigen“ → volle Liste. Nav „Herkunft tracen“ nur beim Wechsel *aus einer anderen* Ansicht → volle Liste; erneuter Klick im Fokus ändert nichts. Meta-Sidecar und kein Mempool-Rundlauf für die Liste.
- **Lab-Regtest · UTXO-Alter:** Funding-Zeiten zufällig über gestern…vor 7 Jahren (monoton gemined); 40 unspent Alters-UTXOs bleiben liegen. Block-Header-Cache netzwerkpräfixiert (`regtest-130.json`) + Lab-`IMMUTABLE_CACHE_DIR`, damit Mainnet-Zeiten Regtest-Alter nicht verfälschen.
- **Empfangen · neuer Block:** Bei Chain-Tip (Electrs `headers.subscribe`) zwei Atemzüge: „NEUER BLOCK“ (zweizeilig), dann Blockhöhe in Monospace. Debug: `?animdebug=1` → ▣.
- **Wallets immer aktuell:** Bei greifendem Electrs-Subscribe kein Tip-Nachzug mehr pro neuem Block (nur Adress-Push). Fehlt Subscribe: stiller Hintergrund-Tip ohne Nav-„aktualisiere…“. Start-Aktualisierung und manueller Tip unverändert sichtbar.
- **Empfangen · unbenutzt bei Electrs:** Ist eigener Electrs/Fulcrum erreichbar, ist die angezeigte Empfangsadresse **immer unbenutzt**. Strategie: Cache-Schätzung (nach Tip oft schon richtig) + **vorwärts** nur wenige `get_history` (typisch 1 RPC) — kein Gap-Walk ab #0 / kein electrs-Fullscan. Electrs-Verbindung wird wiederverwendet (kein TLS-Handshake pro Klick). Ohne Electrs: Schätzung aus Cache mit **Warnhinweis**.
- **Empfangen · Puls/Sync-Status:** Herzschlag startet nicht mehr bei bloßem Wallet-Wechsel oder veralteter Tip-Sync-Job-ID; stoppt zuverlässig nach Scan/Tip-Ende. „aktualisiere…“ nur noch an wirklich laufenden Tip-Nachzug und nur für betroffene Wallets (nicht pauschal alle). Server gibt `wallet_sync_job_id` nach Job-Ende frei. Tip-Sync-Ende eines *anderen* Wallets lässt Empfangs-QR und Animation des aktuellen Wallets unberührt (`EmpfangPuls.stop` zerstört den QR nicht mehr, wenn nichts atmete).
- **Empfangen · Subscribe-Gap:** Bei aktivem Wallet-Watch werden die nächste freie Empfangsadresse und die folgenden 20 Indizes abonniert — Zahlungen auf noch nicht in SatSage gezeigte Adressen werden mitbemerkt.
- **Lab · Faucet-Senden:**
 Unter `NETWORK=regtest` Eingabefeld + OK neben Empfangen — sendet Sats von `lab-faucet` an die aktuelle Empfangsadresse (Mempool, für Animations-Tests).
- **.env-Backup:** Beim Serverstart Rotation `.env.backup0`…`.env.backup9` (vorgefundene `.env` → backup0). Zur Laufzeit schreibt SatSage nur noch `.env` — kein `.bak` mehr bei jedem Speichern.
- **Handbuch · FAQ Lernstoff:** Anhang mit allen Pleb-Lern-URLs aus `web/lernhinweise.json` — Deutsch und Englisch (`doc/handbuch.html` §14). Externe Links öffnen in neuem Tab. Kuratierung: nur konkrete Artikel (keine Anbieter-Startseiten/Shops); u. a. Österr. Schule, XPUB, UTXO, SegWit.
- **UI · Flüchtigkeit:** Richtlinie `doc/design-fluchtigkeit.md` — Nutzer in Eile; Fehlerverhinderung statt Hinweis. Empfangs-QR beim Wallet-Wechsel sofort weg (kein Cache-Vorzeigen), erst wieder wenn die Adresse des neuen Wallets feststeht.
- **UI · Neugier:** Richtlinie `doc/design-neugier.md` — unwissend/lernfaul aber neugierig; bevorzugt Tooltips („Wo ist Walter?“): Eilige ungestört, Neugierige lernen nebenbei.
- **Dealbreaker T13:** Lern-URLs nur Bitcoin-only; Shitcoins/Eth im Zweifel warnen, nicht durchwinken. Lernstoff = Bitcoin-Mechanismen für Plebs, keine SatSage-Internals (`doc/merge-dealbreakers.md`, `doc/lernhinweise-kuratierung.md`).
- **Empfangen · Herzschlag:** Glyph-Atmung (**₿ → sat → Pfeife → Lupe → ∞/21M**, +Student mit Lernhinweisen); Text über dem QR atmet mit. Mempool eingehend: Fade-to-black + Konfetti + ggf. neue Empfangsadresse; ausgehend: „OH NO!“ einen Atemzug; pro gefundenem Scan-UTXO: oranges B.
- **Lernhinweise für Plebs (Experiment):** Einstellung (default aus); Tooltips mit „geeignete Quelle für einen Einstieg in diesen Kaninchenbau“; optional Lern-QR (Klick = kopieren + neuer Tab). Kuratierung: `web/lernhinweise.json`, DE u. a. Aprycot/Blocktrainer/Einundzwanzig.
- **Empfangen · schneller & genauer:** Wallet-Wechsel zeigt sofort den QR des neuen Wallets (Client-Cache) bzw. „wird ermittelt…“ — nie länger den alten. Nächste freie Adresse = höchster bekannter Empfangs-Index + 1 aus UTXO/Verlauf (kein Electrs-Rundlauf bei jedem Klick). Wallets können „Nur lesen“ markiert werden → kein QR, Hinweis „Read-only-Wallet ausgewählt“.
- **Empfangen · bc1 zuerst:** Bei generischem `xpub`/`tpub` und Skripttyp „Automatisch“ ist die Empfangsadresse (QR, Ableitung #0) natives SegWit (`bc1q`), nicht mehr Legacy (`1…`). Gap-Scan prüft weiter alle Skriptformen; in den Wallet-Einstellungen bleibt Legacy/Nested/Taproot wählbar.
- **Wallets · Bitkey-Deskriptor:** Export mit `External:` / `Internal:` (2-of-3 `wsh(sortedmulti…)`) wird zu einer multipfadigen Wallet zusammengeführt; auch bei vertauschter Cosigner-Reihenfolge. Die Kontrolladresse ist Empfang #0 (nicht mehr Change durch Sortierung).
- **Lab · Kalender:** Regtest-Szenarien streuen Blockzeiten mit `setmocktime` über 2022–2025 bis Tip≈heute — Steuerjahr-/Haltefrist-Visualisierung testbar. Frische Chain nötig (`.data/` wipen). Lab-Env setzt `STEUER_HALTEFRIST_JAHRE=1`; Phasen in `scenario-report.json`.
- **Empfangen · QR:** Rechts neben dem Assistenten zeigt ein quadratisches Dock-Feld die nächste Empfangsadresse der gewählten Wallet als QR (lokal generiert, kein CDN), mit Name, Index und Quelle. Ableitung nur serverseitig; Electrs/Fulcrum bevorzugt, sonst „Schätzung aus Cache“. Bei aktivem Wallet-Watch werden die Adresse und Index+1 abonniert. Kurzes Polling erkennt eingehende Zahlungen.
- **Tests · CI:** Vier Unittests nach dem WPKH-/Gap-Scan-Fix wieder grün — Skripttyp-Registry vor Ableitungstests leeren, Sofort-Speichern-Prüfung an Deskriptor-Umleitung anpassen, Specter-`wpkh` als Single-Sig erwarten, Regex-Literal in `fuegeWalletHinzu` ohne falsche Klammerbilanz.

## [0.9.5] - 2026-09-13

- **Version:** 0.9.5 — die Sprachwahl aus 0.9.4 greift jetzt auch in der Oberfläche.
- **Web · Sprache (Nachtrag zu 0.9.4):** Die in 0.9.4 eingeführte Sprachwahl kam in der Hauptoberfläche nicht an. `storedLang()` in `web/i18n.js` gab `normalizeLang(localStorage.getItem(…))` zurück, und `normalizeLang()` macht aus allem Unbekannten — auch aus `null` — ein `"de"`. Damit lieferte `storedLang()` selbst ohne gespeicherte Wahl immer `"de"`, und der Zweig `|| config.ui_lang` in `initI18n` war unerreichbar: die API meldete `ui_lang: en`, die Oberfläche blieb deutsch. Nur die servergerenderte Anmeldeseite funktionierte, weil sie kein JS-i18n nutzt. `storedLang()` gibt jetzt `null` ohne gespeicherten Wert, letzter Rückfall ist die Browsersprache statt eines festen `"de"`. Neue Tests in `tests/test_web_i18n.py` laden `i18n.js` in Node mit gestubbtem `localStorage`/`navigator` und prüfen die Auflösungsreihenfolge.

## [0.9.4] - 2026-09-13

- **Version:** 0.9.4 — Weboberfläche spricht die Sprache des Browsers; Fußzeile behauptet nichts Falsches mehr.
- **Web · Sprache:** Ohne gesetztes `UI_LANG` entscheidet jetzt der `Accept-Language`-Header des Browsers über die Oberflächensprache, sonst Englisch. Hintergrund: umbrelOS reicht seine eigene Spracheinstellung nicht an Apps durch, der Browser-Header ist das einzige verfügbare Signal. Der DE/EN-Umschalter überschreibt weiterhin alles und wird in `UI_LANG` gespeichert. CLI und Terminal-Menü bleiben unverändert bei Deutsch.
- **Web · Anmeldeseite:** War hartcodiert Deutsch und damit die einzige Ansicht ohne Übersetzung — im App Store das Erste, was ein Nutzer sieht. Alle Texte inklusive der StartOS- und Umbrel-Hinweise liegen jetzt zweisprachig in `_LOGIN_TEXTE`; `<html lang>` und Seitentitel folgen der gewählten Sprache.
- **Web · Fußzeile:** „127.0.0.1 — nur lokal erreichbar“ stand unabhängig von der tatsächlichen Bind-Adresse im HTML. Hinter Umbrels `app_proxy` bindet SatSage an `0.0.0.0` und ist aus dem ganzen LAN erreichbar — die Zeile erscheint jetzt nur noch, wenn der Listener wirklich auf Loopback sitzt (`local_only` in `/api/config`).

## [0.9.3] - 2026-09-13

- **Version:** 0.9.3 — Umbrel-Paketierung: SatSage läuft als App im Umbrel App Store und nutzt den dort installierten Bitcoin Node, Electrum-Server und mempool.
- **Umbrel · Managed-Modus:** Neuer Wert `SATSAGE_MANAGED_BY=umbrel`. Electrum-, Core- und Mempool-Adressen kommen als Compose-Env aus den Umbrel-Dependencies (`electrs`, transitiv `bitcoin`) und werden zur Laufzeit übernommen, ohne in die `.env` geschrieben zu werden. Die Datenquellen-Felder `own_fulcrum`/`own_core` sind wie unter StartOS gesperrt; der Managed-Hinweis nennt Umbrel und den erkannten Indexer.
- **Umbrel · Login:** Umbrel reicht `APP_PASSWORD` als `SATSAGE_BOOTSTRAP_PASSWORD` herein; SatSage hinterlegt daraus seinen Passwort-Hash und verlangt hinter dem `app_proxy` weiterhin den eigenen Login — das Docker-Netz gilt als nicht vertrauenswürdig. Die Login-Seite verweist auf die Umbrel-App-Details.
- **Intern:** Die Start9-spezifischen Modus-Abfragen laufen jetzt über die Mengen `_NODE_MANAGED`/`_MANAGED_MODI`; `_start9_electrum_indexer` heißt `_electrum_indexer`, die Bridge-Konstanten heißen `_BRIDGE_QUELLEN`/`_BRIDGE_SCHLUESSEL`. Verhalten unter StartOS und Specter unverändert.
- **Container:** `packaging/Dockerfile` setzt `SATSAGE_MANAGED_BY` nicht mehr fest auf `start9` — der Modus kommt von der Plattform (StartOS-Daemon-Env bzw. Umbrel-Compose). `/data` gehört `1000:1000`, weil Umbrel den Dienst unter dieser UID startet.


## [0.9.2] - 2026-09-11

- **Version:** 0.9.2 — Wallet-Öffnen/Tip-Sync schneller, „Nur bekannte UTXOs“, Bisq-Soft-Labels, Wallet-Einstellungen klarer.
- **Wallets · Einstellungen:** Dickere Trennlinie zwischen Wallet-Zeilen; Namensfeld „Name (optional)“ mit Akzent-Hintergrund/Rahmen — klarer Einstieg fürs nächste Wallet trotz XPUB-Balken darunter. Bereits konfigurierte Wallet-Namen fett (`font-weight: 700`).
- **Herkunft · Bisq:** Soft-Labels „Wahrscheinlich Bisq-Auszahlung“ / „Bisq-Deposit (Escrow)“ — Payout: 1 Input → 2 Outs mit Deposit-Verhältnis (~15–50 %); Deposit: ≥2 Ins, Escrow+`OP_RETURN` (Contract-Hash). OP_RETURN am Prevout verstärkt den Payout, wenn Eigentum noch unklar ist. Kein Mix/Own-only-Walk. Form-Icon (Amber, P2P-Escrow 2→1→2) wie bei den CoinJoin-Icons an Herkunftszeile und Adressgruppe.
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
- **Vorgeschichte:** Alles **unterhalb** dieses Abschnitts (`2026-09-07` … `2026-07-08`) ist die private xPubQuery-/SatSage-Entwicklung vor der Freigabe — inhaltlich deckungsgleich mit dem privaten Vorgänger-Changelog (Stand Abgleich 2026-09-09).
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
