# Testplan · Features seit letztem `main`-Stand (Release-Kandidat 0.9.6)

**Stand:** 2026-09-17 (Juniormind: **A1–A10** abgehakt; weiter mit **B**)  
**Scope:** `origin/main`…`HEAD` auf `dev-juniormind` (Merge-Base `ac62b7f`, 24 Commits, Changelog `[Unveröffentlicht]`).  
**Ziel:** Vor Merge/Bump 0.9.6 wissen, wer was absichert.

### Juniormind-Notizen (A)

- **A6:** TLS-Auto-Flip ok. **Idee (offen):** analog Port **50001↔50002** mitprobieren und bei Erfolg in `.env` schreiben (wie `FULCRUM_SSL`).
- **A10:** mempool.space → rote Explorer-Pille ok; kurz verschwindet die grüne libbitcoin-Pille und kommt wieder — **halb so wild**, kein Blocker.

## Legende

| Spalte | Bedeutung |
|--------|-----------|
| **Feature** | Zusammengefasste Nutzerwirkung (Changelog-Bullets gebündelt, wo ein Smoke denselben Pfad trifft). |
| **testet Grok** | Was der Assistent hier ausführen / verifizieren soll. Leer = nicht vorgesehen; Begründung in Spalte **Warum Grok leer / Automation**. |
| **testet Juniormind** | Was du manuell / auf Gerät / mit echtem Node prüfst. |
| **Warum Grok leer / Automation** | Nur relevant, wenn Grok-Spalte leer oder nur Teilabdeckung. |

**Priorität vor Merge:** Zeilen mit **P0** zuerst (Semantik/Privatsphäre/Datenkorrektheit). **P1** UX-kritisch. **P2** Politur/Meta.

**Voraussetzungen Grok:** grüne Unittests (CI lokal), Lab-Regtest optional (`lab/regtest`), GUI via `scripts/webgui_test_ready.py` / Browser — **nie** Token aus Logs greppen.

---

## A · Datenquellen, Tor, Electrum

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| A1 | P0 | **Electrs über Tor · JSON-RPC-Batch** (UTXO, Gap, Alter) | `tests/test_fulcrum_tor_batch.py`; Fake-Clients in Parallel-/Zwischenstand-Tests um `tor_batch_sinnvoll` ergänzen bis Suite/CI grün | **✓ Juniormind** (Commit „Batched Tor getestet“ + erneute Bestätigung) — Live am eigenen Onion-Node | Live erledigt. Offen nur noch **CI-Fakes** (`tor_batch_sinnvoll` in `test_parallel` / `test_utxo_zwischenstand`) — Grok-Fix vor Merge |
| A2 | P0 | **Tor/Electrs · SOCKS-Cache 90 s + Electrum-Gate** (Jobs nacheinander) | `tests/test_tor.py`, Job-Serialisierung in `tests/test_jobs.py` soweit vorhanden | **✓ Juniormind** — durch Firewall; Herkunft: erst UTXO-Scan, danach Herkunft (Gate serialisiert) | Live erledigt. Unit-Abdeckung Gate/SOCKS-Cache bleibt Grok-Sache |
| A3 | P0 | **Öffentliches Electrum · nur Sitzungs-Opt-in** (kein Dauer-`.env`) | API-/Config-Test: Start entfernt `OEFFENTLICHE_ELECTRUM=1`; Dialog-Flag nur Runtime; Stichprobe-Tests (`TestOeffentlicheElectrumStichprobe`) | **✓ Juniormind** — Dialog/Sitzung + Connect nach Stichproben-Fix | Grok: Suite/CI weiter |
| A4 | P1 | **Empfang über öffentlichen Pool** nach Opt-in | — | **✓ Juniormind** | Optional später Mock-Fetcher |
| A5 | P1 | **Electrs-Config-Wechsel** startet Watch/Empfang neu; alte Tor-Port/SSL-Keys weg | Config-Write-Test (Key-Löschung) | **✓ Juniormind** | Key-Löschung weiter automatisierbar |
| A6 | P1 | **TLS auto-flip** + Schreiben `FULCRUM_SSL` | `tests/test_connection_hints.py` an neue Texte anpassen (CI-Fail) | **✓ Juniormind** — flippt und verbindet. **Wunsch:** gleiches für Port 50001/50002 | Port-Auto-Flip = mögliche Folgeaufgabe (nicht Blocker) |
| A7 | P1 | **Kopf-Pille:** grau nach Speichern; Indexer-Name nach Handshake (`electrs`/`fulcrum`/`libbitcoin`) | Browser: Speichern → grau; nach Connect Name | **✓ Juniormind** — läuft | — |
| A8 | P2 | **Staub-Konfetti** nach grünem Node-Test | — | **✓ Juniormind** — staubt (hoch-privat, auch nach Wechsel) | Visuell; kein Auto-Test |
| A9 | P2 | **Log: Peers + electrs gemeinsam**; Log-Knopf statt Checkbox | Browser-Smoke Log-Toggle | **✓ Juniormind** — klappt | — |
| A10 | P0 | **Block-Explorer öffentlich mit Warnung** + Pille privat/öffentlich | API/UI: Speichern mempool.space → Dialog; Abbruch leert Feld | **✓ Juniormind** — Warnung/Pille ok. **Winzig:** kurze Ausblendung der grünen libbitcoin-Pille, kommt wieder | Halb so wild; optional später Pillen-Flicker glätten |

---

## B · Börsen-CSV

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| B1 | P0 | **CSV-Import** (nur BTC-Addr/TxID; Cache `exchange_reports/`) | `tests/test_exchange_reports.py` (Parse/Import/Label) | 1–2 echte Exchange-CSVs (Kraken/Binance o. Ä.), UI-Knopf, Fehler bei Altcoins | Kern **automatisiert**; Format-Vielfalt echter Börsen = du |
| B2 | P0 | **Trace endet an Börse** (Label „Börse · …“, keine Hops dahinter) | Unit: Label + Stop-Bedingung an Fixture-Tx/Addr | Herkunftsbaum an importierter Einzahlung | Stop-Logik **automatisierbar** (noch dünn → erweitern); reale CSV-Zuordnung du |

---

## C · Herkunft / Trace

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| C1 | P0 | **Zwei Tiefen:** Steuer-Horizont vs. voll bis Extern/Coinbase | `tests/test_trace_steuer_horizon.py` | Lab: Steuerjahr „klären“ stoppt an Frist; „Herkunft tracen“ tiefer | Suite vorhanden; Lab-End-to-End du+Grok |
| C2 | P0 | **Resume / Lücken schließen** behält fertige Zweige | `tests/test_trace_resume_luecken.py` | Abbruch mitten im Trace → Resume füllt nur Lücken | Kern automatisiert; UI-Knöpfe manuell |
| C3 | P0 | **Leerer Trace → sichtbare Lücke** (kein stilles „Keine Zuflüsse“) | Unit mit mock `get_tx`-Fail | Kaputte/fehlende Prevout-Situation in Lab/GUI | **Automation möglich** |
| C4 | P0 | **Unvollständig rot** statt grün „verfolgt“ | DOM/CSS-Klasse oder Snapshot-String-Test | Visuell im Baum | String/Klasse **automatisierbar**; Farbe du |
| C5 | P0 | **Fan-In vs. Fan-Out** Soft-Labels | `tests/test_tx_classify.py` + Trace-Classify | Lab Fan-out / Konsolidierung | Vorhanden; Lab-GUI du |
| C6 | P0 | **Interner Übertrag** jenseits `max_addresses` via `scan_end_index` | `tests/test_trace.py` (`TestInternUeberChangeJenseitsMaxAddresses`) | Cash+Carry→anderes Wallet nicht als Extern | Gut abgedeckt |
| C7 | P0 | **Fan-Out-Hang-Fix** (keine HD-Suche je fremder Out-Addr) | Unit/Perf-Smoke: viele Outs, Abbruch reagiert | Optional große Exchange-Tx | Hang-Regression **automatisierbar** (Timeout-Test) |
| C8 | P1 | **Flache Hierarchie** nur bei Wallet-Wechsel | HTML-Hop-Bericht-Test / DOM-Tiefe | Baum-Einrückung in GUI | DOM-Tiefe **automatisierbar** |
| C9 | P1 | **Cache-first POST /api/trace**; Job-Meta `wallet_name`; Doppelstart-Schutz | API-Tests in `tests/test_api.py` / Jobs | Browser-Neustart während Job; Doppelklick | Teils vorhanden; Rest Userflow |
| C10 | P1 | **Externe Blätter mit Eingangsdatum**; Sprung Steuerjahr→richtiges Wallet | `tests/test_trace.py` Zeitstempel | Klick Dotplot → Herkunft korrektes Wallet | Zeitstempel automatisiert; Nav-Sprung manuell/Userflow |
| C11 | P1 | **Abbruch** Lücken-Phase + Fortschritt; Statuszeile Abbrechen | `tests/test_jobs.py` Cancel-Pfade | Abbrechen während „Lücken schließen“ | Kern automatisiert; Layout-Sprung du |
| C12 | P2 | **Knopftexte / AML-Erklärtext / Nav-Reihenfolge** | Locale-Keys vorhanden (`tests/test_i18n.py` / Einrichtungs-Strings) | DE/EN lesen, Nav Steuerjahr über Herkunft | Copy-Review = du; Key-Existenz Grok |

---

## D · Sanktionen

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| D1 | P0 | **xpub-blinder n-Hop-Check** (Hop 0 = UTXO-Addr) | `tests/test_sanction_hops.py`; Lab `verify_sanctions_hops.py` | Lab-Szenarien 1/10/25 Hop | Automation stark; Cap-100 Lab du |
| D2 | P0 | **Walk-Cache** `*.sanction_walk.json` | `TestSanctionWalkCache` | Zweiter Lauf ohne Chain-Walk | Vorhanden |
| D3 | P1 | **CoinJoin-Hinweise** im Hop-Fenster | `TestSanctionCoinJoinHinweis` | Lab Wasabi/Whirlpool-like Text in UI | Soft-Label; Automation da, Wortlaut du |

---

## E · Steuerjahr / Bericht

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| E1 | P0 | **Scorecard + klappen + graue Dots** ohne Herkunft innerhalb Frist | Tax-API/Unit soweit vorhanden; Browser Scorecard | Visuell Dotplot grau vs grün; Klappzustand | Farben/Layout = du; Datenklasse Grok |
| E2 | P0 | **Hop-Kette im HTML/CSV-Bericht** („Sat-Geschichte“) | `tests/test_herkunft_bericht.py`, `test_selbstanzeige.py` | Export öffnen, Hop-Nesting, Dateiname ohne „Selbstanzeige“ | Kern automatisiert; Druck/HTML-Optik du |
| E3 | P1 | **Persönliche Daten** → Berichtskopf | Config-Write + Report-String-Test | Formular füllen, HTML prüfen | **Automation möglich** |
| E4 | P1 | **Historien**-Knopf aktualisiert Nav-Alter ohne Refresh | — | Nach Job „gerade eben“ in Nav | Timing/UI; Userflow **möglich**, bisher dünn |
| E5 | P1 | **Zeitstrahl** Log-Y, Pan/Zoom, keine Betrags-Labels, Hover | — | Interaktion Chart | Canvas/Plot-Interaktion: Automation teuer/flakeig — **manuell sinnvoller** |
| E6 | P2 | **FiFo-Log-Prefix** nicht mehr „Selbstanzeige:“ | Log-String-Test falls greifbar | Log beim Kandidaten-Laden | Kleiner String-Test **möglich** |
| E7 | — | **Offen (ISSUES):** Bericht gelb/grün nach Voll-Trace-Tiefe | nicht release-blockierend testen als „fertig“ | Bewusst als Lücke kennen | Feature noch nicht geliefert |

---

## F · Empfang, Tip-Sync, Animation

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| F1 | P0 | **QR-Dock + Wallet-Wechsel entwertet sofort** (Flüchtigkeit) | Browser: Wechsel Wallet → alter QR weg | Alltagsgefühl + Spalter-Breite | Userflow/Browser **möglich und vorgesehen** |
| F2 | P0 | **Empfangsadresse unbenutzt** bei eigenem Electrs; Subscribe-Gap +20 | Lab + Electrs; ggf. Watch-Tests | Zahlung auf Index+1 noch unangezeigt → trotzdem erkannt | Live-Zahlung = Lab/du; Subscribe-Logik teilw. unit-testbar |
| F3 | P0 | **Konfetti nur Mempool-TxIN**; nicht bei Gap/Scan-Adresssprung | `tests/test_mempool_pending_self.py` o. Ä. + Logik-Assert | Echte Receive-Animation | Trigger-Logik automatisierbar; Ka-Ching-Feel du |
| F4 | P1 | **Orange-₿** Schwelle/Skalierung/kein Nachklapp | — | Visuell bei ≥500 sats | Animation: Automation unsinnig |
| F5 | P1 | **Herzschlag-Glyphs + Lern-QR** (Neugier-Opt-in) | JSON `lernhinweise.json` Schema/URLs; T13 Stichprobe | Opt-in an, Tooltips, FAQ §14 | URL-Kuratierung **teilautomatisierbar** (Domain-Allowlist); UX du |
| F6 | P1 | **Tip-Sync / „gerade eben“ je Wallet**; Subscribe statt Tip-pro-Block | `tests/test_wallet_watch.py`, `test_start_sync.py` | Mehrere Wallets, Tip-Lag-Text weg | Kern automatisiert; Nav-Timing du |
| F7 | P1 | **Interne Transfers:** Animation nur Ziel-Wallet | — | Self-Send / Wallet→Wallet | Braucht Live-Coins; Lab möglich, teuer zu automatisieren |
| F8 | P2 | **bc1 zuerst** bei xpub+auto am Empfang | `tests/test_derivation.py` (CI-Fail anpassen falls Spec geändert) | QR beginnt mit bc1/bcrt1 | **Automation Pflicht** (Suite wieder grün) |
| F9 | P2 | **Bitkey External/Internal**-Deskriptor | `tests/test_deskriptor_import.py` | Echten Bitkey-Export einfügen | Parse automatisiert; Gerät du |

---

## G · Sprache, Kurs, Umbrel/Managed

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| G1 | P0 | **DE/EN + Accept-Language + storedLang-Fix**; Login zweisprachig | `tests/test_web_i18n.py`, `test_web_sprache.py`, Browser DE↔EN | Login ohne `UI_LANG`, Browser EN → EN-UI | Gut abgedeckt |
| G2 | P0 | **Fiat folgt UI-Sprache** (DE→EUR, EN→USD) | Browser: Sprachwechsel → Spot-Währung | Spot + ≈-Umrechnung | Userflow **möglich** |
| G3 | P1 | **Kurs-Historie auto-nachziehen**; Spot TLS wie Node | `tests/test_price_history_sync.py`, `test_price.py` | LAN-Mempool Self-Signed falls vorhanden | Sync-Logik automatisiert; LAN-TLS du |
| G4 | P0 | **Umbrel Managed-Modus** (Quellen gesperrt, Bootstrap-PW, Bind/`local_only`) | `tests/test_umbrel_mode.py`, `local_only`-Tests | Echtes Umbrel (Busch) nach 0.9.6-Image | Unit stark; Gerät = Busch/du |
| G5 | P1 | **Fußzeile „nur lokal“** nur bei Loopback | Unit `_ist_local_only` | Hinter Proxy keine Fake-Localhost-Behauptung | Automatisiert + Geräte-Check |
| G6 | P2 | **Umbrel Packaging / `:latest` Dev-Pin** | Dateien/`build_umbrel_community_store` Smoke | Store-Release mit Busch | Kein Produkt-GUI-Test für Grok vor Image |

---

## H · Jobs, Abbruch, Meta, Lab

| # | P | Feature | testet Grok | testet Juniormind | Warum Grok leer / Automation |
|---|---|---|---|---|---|
| H1 | P0 | **Job-Abbruch überall** + `JOB-START`/`JOB-ENDE` | `tests/test_jobs.py` | Abbruch BIP-158 / Labels / Sanktionslisten in GUI | Kern automatisiert |
| H2 | P1 | **Userflow-Skript** `scripts/webgui_userflow.py` | Skript grün fahren (Spawn-Session) | Stichproben wo Skript flach bleibt | **Automation vorgesehen** — Grok soll laufen lassen |
| H3 | P1 | **`.env`-Backup-Rotation** | `tests/test_env_backup.py` | Nach Start `backup0…` prüfen | Automatisiert |
| H4 | P2 | **Lab Kalender / Faucet / Alters-UTXOs** | `generate_scenarios` + Verify-Skripte wo vorhanden | Steuerjahr-Dots gestreut; Faucet-Send | Lab-Setup gemeinsam; visuelle Steuer du |
| H5 | P2 | **commit.sh Text-auto / Binär-Nachfrage** | — | Einmal Script-Verhalten | Shell-Interaktiv; Automation wenig wert |
| H6 | P2 | **Handbuch §14 Lern-URLs** sync zu `lernhinweise.json` | Diff/Check-Skript oder manueller Abgleich durch Grok | Lesbarkeit FAQ | Sync-Check **automatisierbar** (sollte ein kleiner Test werden) |

---

## Verteilung (Soll vor Merge)

| Rolle | Fokus |
|-------|--------|
| **Grok** | CI/Unittests grün (A1/A6/F8 Fix), Userflow, Browser-Smokes P0/P1 lokal, Lab-Verifies Sanktion/Tx-Classify, Umbrel-Unit, Trace/Sanktion/Exchange-Unit |
| **Juniormind** | **A erledigt** → weiter **B1/B2** (Börsen-CSV); danach C/E/F nach Plan. Offen notiert: Port-Auto-Flip 50001/50002 (A6), Pillen-Flicker Explorer (A10) |

---

## Explizit: leere oder schwache Grok-Spalten — Automation?

| Feature | Warum Grok schwach/leer | Automation sinnvoll? |
|---------|-------------------------|----------------------|
| Staub-/Receive-Konfetti, Orange-₿, Herzschlag | Visuelles Timing | **Nein** (Flakes); Trigger-Bedingungen ja unit-testen |
| Chart Pan/Zoom Steuerjahr | Canvas-Interaktion | **Kaum** lohnenswert; Datenpunkte unit-testen |
| Echter Tor-Onion-Electrs | Live bereits von dir getestet | Unit+Fake (CI) noch fixen; kein zweiter Live-Lauf nötig |
| Echte Exchange-CSV-Formate | Proprietäre Spalten | Parser-Fixtures ja; neue Börse = Fixture + du |
| Umbrel/StartOS Hardware | Fremdes Gerät | Unit Managed-Mode ja; Store = Busch |
| commit.sh interaktiv | TTY-Prompt | Nein |
| Interne Transfer-Animation nur Ziel-Wallet | Live-Mempool zwischen Wallets | Lab-Skript **möglich**, Aufwand hoch — manuell reicht für 0.9.6 |
| Bericht gelb/grün Volltiefe | Noch ISSUES, nicht geliefert | Später automatisieren wenn gebaut |

---

## Reihenfolge (Vorschlag)

1. **Grok:** Suite lokal grün (Tor-Batch-Fakes, connection_hints, derivation, api sanctions assert, config backup).  
2. **Grok:** `webgui_userflow.py` + Browser P0 (Opt-in, Pille, QR-Flüchtigkeit, DE/EN+Fiat, Trace Resume Smoke).  
3. **Juniormind:** Tor live + eine Börsen-CSV + Steuerjahr-Augen + Empfangs-Animation.  
4. **Gemeinsam:** Lab Sanktions-Hops + Tx-Classify Verify.  
5. Erst dann VERSION 0.9.6 / Merge-Plan.
