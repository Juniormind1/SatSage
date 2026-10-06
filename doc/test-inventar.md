# Test-Inventar

Stand: 2026-10-06. Erhebung per AST und Import-Zuordnung, **ohne** die Suite oder das Regtest-Labor zu fahren.

Die schnelle CI-Suite (`tests/`, Dealbreaker **Q1**) umfasst Unittests ohne Node. Hart-Dealbreaker (T1/T6/T9/T13, Auth, CSRF) sind auf `dev-juniormind` optional und auf `main` Pflicht (`SATSAGE_HARD_TESTS`).

---

## 1 · Schichten

| Schicht | Ort | Wann | Inhalt |
|---------|-----|------|--------|
| Unittests | `tests/` | jeder Push/PR (`test.yml`), Hook vor Push nach `main` | gemockt, ohne Node/Electrs/persönliche `.env` |
| Regtest-Labor | `lab/regtest/scripts/` | Merge nach `main`, Release, wöchentlich bei Delta (**Q6**) | Core + Electrs, Allowlist am echten Node, Szenarien, `verify_tx_classify.py`, `verify_sanctions_hops.py` |
| GUI-Chaos / Userflow | `scripts/webgui_*.py`, `doc/testprotokoll-*.md` | manuell / Assistent nach Angebot | Playwright, kein CI |
| Specter | `tests/test_specter_*.py` | in Q1 | ohne laufendes Specter |
| Start9 / Umbrel | `tests/test_start9_phase_s*.py`, `test_umbrel_mode.py` | in Q1 | Bind, Auth, Outbound, Managed-Modus |
| Hart-Dealbreaker | `tests/test_dealbreaker_*.py`, Gate `tests/hart.py` | `main` Pflicht, `dev-juniormind` Skip | T1/T6/T9/T13, Auth, CSRF — ohne Node |

Hilfen in `tests/`: `fixtures.py` (BIP-Spezifikations-XPUBs, erfundene Txs), `env_scramble_helpers.py`, `i18n_harness.mjs`, `herkunftsnetz_dom_stub.js`.

---

## 2 · Inventar nach Domäne

Zahlen: Methoden | Zeilen. Dateien mit einem Satz Zweck.

### HTTP / Sitzung / Start

| Datei | n | Zweck |
|-------|--:|-------|
| `test_api.py` | 205 | echter Loopback-Server: Auth-Token, Config, Wallets, UTXOs, Trace, Tax, Cache, Jobs, Quellen, Sanktionscheck, Preis |
| `test_eingebetteter_server.py` | 2 | GUI im Hintergrund / Specter-iframe |
| `test_gui_session.py` | 2 | Session-JSON für GUI-Helfer |
| `test_boot_log.py` | 8 | Start-Log-Strom, Wallet-Klick während Seed |
| `test_einrichtung.py` | 53 | Erststart-Hinweis, öffentliche Electrum erst nach Bestätigung |
| `test_single_instance.py` | 3 | Port-Übernahme |
| `test_start9_phase_s0.py` | 5 | Default-Bind Loopback, Health |
| `test_start9_phase_s1.py` | 23 | Passwort, Login, Proxy, CSRF/Origin hinter Start9 |
| `test_start9_phase_s2.py` | 9 | Outbound/SSRF |
| `test_start9_phase_s3.py` | 4 | Import-Limits / DoS |
| `test_umbrel_mode.py` | 14 | Managed Electrum/Auth |
| `test_env_scramble.py` | 8 | `.env` SSGB1 |
| `test_env_backup.py` | 5 | `.env.backup0–9` |
| `test_config.py` | 44 | `.env` lesen/schreiben (temporäre Dateien) |
| `test_wallet_bloecke.py` | 33 | `WALLET_n_*` vs. alte XPUB-Liste |
| `test_paths.py` | 5 | PyInstaller-frozen Pfade |
| `test_version.py` | 2 | `VERSION` |
| `test_connection_hints.py` | 7 | TLS/Protokoll-Hinweise |

### Herkunft / Trace / FIFO

| Datei | n | Zweck |
|-------|--:|-------|
| `test_trace.py` | 30 | Rückwärts-Walk, Zyklen, Tiefe |
| `test_core_trace.py` | 33 | Baum so, wie die UI ihn braucht (Lücken sichtbar) |
| `test_trace_cache.py` | 38 | persistente Bäume |
| `test_trace_ingress.py` | 10 | Ergebnis in Ingress-Cache |
| `test_trace_knoten.py` | 6 | knotenweise API + JS |
| `test_trace_live_punkt.py` | 8 | Dotplot nur irreversibler Stand |
| `test_trace_resume_luecken.py` | 5 | Resume fertiger Zweige |
| `test_trace_steuer_horizon.py` | 6 | Horizont vs. voll bis Extern |
| `test_trace_wald.py` | 6 | hop-weiser Wald |
| `test_fifo_lots.py` | 67 | FIFO je Output, Whirlpool, CoinJoin-Hop |
| `test_lot_ring_fifo_js.py` | 3 | Donut = Server-Ring |
| `test_herkunftsnetz.py` | 19 | Steuer-Overlay API |
| `test_herkunftsnetz_js.py` | 18 | Overlay DOM |
| `test_herkunft_sprung_js.py` | 1 | Sprung Netz → Baum |
| `test_herkunft_bericht.py` | 4 | Hop-Kette im HTML-Bericht |
| `test_historie_ansicht.py` | 10 | ausgegebene Outputs in der Herkunft |
| `test_tx_classify.py` | 20 | Eigentum vor Formheuristik |
| `test_tx_formats.py` | 14 | Core-float vs. Electrs |
| `test_tx_fallback.py` | 9 | Tx ohne Electrs: Core → P2P → Block |
| `test_chain_network_hrp.py` | 9 | HRP/Netz im Trace und Cache |
| `test_label_anzeige.py` | 9 | Label kommt in der Herkunft an |
| `test_eigenuebertrag.py` | 10 | Eigenübertrag vs. Veräußerung |
| `test_vervollstaendigen_log.py` | 2 | Hop-Log ohne Adressen |

### Steuer

| Datei | n | Zweck |
|-------|--:|-------|
| `test_tax.py` | 128 | Auswertung und Export |
| `test_tax_verlauf.py` | 17 | mit vollständigem Verlauf |
| `test_steuer_grundlage.py` | 9 | je Wallet Verlauf oder Bestand, kein stilles Verschwinden |
| `test_steuer_fenster.py` | 19 | Seiten, Summen, Selbstanzeige-Download |
| `test_steuer_leere_achse_js.py` | 3 | leerer Plot |
| `test_steuer_scorecard_js.py` | 1 | Scorecard ohne Reload |
| `test_klaeren_vorab_scan_js.py` | 1 | „klären“ nur Wallets ohne Bestand |
| `test_selbstanzeige.py` | 7 | Sat-Geschichte FIFO |
| `test_bericht_wallet.py` | 12 | Wallet-Etikett in Berichten |
| `test_listen_fenster.py` | 28 | seitenweise UTXO-/Listen |

### Wallets / Ableitung / Import

| Datei | n | Zweck |
|-------|--:|-------|
| `test_derivation.py` | 19 | XPUB → Adresse |
| `test_multisig_ableitung.py` | 29 | wsh-Multisig |
| `test_deskriptor_import.py` | 26 | Sparrow/Specter-Text, **xprv abgelehnt** |
| `test_sparrow_import.py` | 4 | Sparrow-Datei parsen |
| `test_wallet_export_import.py` | 9 | Sparrow/Wasabi erkennen |
| `test_wallet_discover.py` | 9 | lokale Sparrow-/Wasabi-Suche |
| `test_wallet_discover_companion.py` | 9 | Ledger Live / BitBox, nur Bitcoin |
| `test_export_adressen.py` | 6 | Adressen aus Export nachziehen |
| `test_wallet_alter.py` | 29 | first-seen |
| `test_first_seen_scan.py` | 3 | First-Seen-Scan |
| `test_wallet_watch.py` | 18 | Reconnect, Tip-Vormerkung |
| `test_diagnose.py` | 15 | Befund ohne Secret-Leak |

### Scan / Quellen / Mempool / RPC

| Datei | n | Zweck |
|-------|--:|-------|
| `test_source.py` | 47 | Kaskade, öffentliche Electrum nur mit Opt-in (**P2/T11**) |
| `test_bip158_scanblocks.py` | 53 | TurboSync, CFilter, P2P |
| `test_start_sync.py` | 16 | Start-Nachzug, kein Fullscan |
| `test_tip_fenster_je_chain.py` | 8 | Empfang/Change getrennt |
| `test_utxo_scan_prioritaet.py` | 6 | Electrs-LAN vor scantxoutset |
| `test_utxo_zwischenstand.py` | 5 | Cache schon während des Scans |
| `test_utxo_cache_frisch.py` | 3 | Frische, kein Doppel-Gap |
| `test_utxo_ranking.py` | 33 | Rangfolge UI = CLI |
| `test_block_time_enrich.py` | 4 | Blockzeit aus Header-Cache |
| `test_verlauf_cache.py` | 8 | `*_verlauf.json` |
| `test_verlauf_prioritaet.py` | 8 | Verlaufskette ≠ UTXO-Kette |
| `test_fulcrum_verlauf.py` | 11 | History-Fetch |
| `test_fulcrum_verlauf_hrp.py` | 1 | scriptPubKey vs. HRP |
| `test_fulcrum_retry.py` | 7 | Reconnect bei Timeout |
| `test_fulcrum_tor_batch.py` | 8 | Batch nur eigener Electrs über Tor |
| `test_parallel.py` | 20 | ein Socket je Client |
| `test_jobs.py` | 47 | Phasen, Zwischenstand, Quota |
| `test_bitcoind_rpc.py` | 10 | RPC-Client |
| `test_rpc_allowlist.py` | 31 | **T14** Laufzeit |
| `test_rpc_allowlist_statisch.py` | 8 | **T14** AST-Scan Produktivcode |
| `test_local_bitcoind.py` | 5 | Cookie/Loopback erkennen |
| `test_mempool.py` | 35 | eigene mempool.space-URL, kein Default-Leak |
| `test_mempool_node_pause.py` | 4 | Node-Fehler merken |
| `test_mempool_pending_self.py` | 2 | unbestätigte Selbstüberweisung |
| `test_mempool_untergrenze.py` | 5 | Mindesthöhe = Chain-Tip |
| `test_tor.py` | 21 | lokaler Tor ohne Browser |
| `test_sqlite_flatfile_hint.py` | 2 | Flatfile → SQLite-Hinweis |

### FIFO-Spend / PSBT / Tools

| Datei | n | Zweck |
|-------|--:|-------|
| `test_psbt_bau.py` | 45 | unsignierte PSBT, Staub, RBF |
| `test_coin_auswahl.py` | 44 | Branch-and-Bound |
| `test_fee_vorschlag.py` | 12 | sat/vB, Deckel, Fallback |
| `test_zieladresse.py` | 14 | Netz, eigenes Wallet |
| `test_wallet_fifo_spend_js.py` | 53 | Spend-Leiste in `wallets.js` |
| `test_wallet_mempool_js.py` | 8 | Mempool-Abgleich nach Start |
| `test_adresse_werkzeug.py` | 12 | „Ist die Adresse meine?“ + Tools-API |
| `test_cache_suche.py` | 3 | Kopf-Filter über alle Wallets |
| `test_schatzsuche.py` | 7 | Fenster/Zuordnung ohne Node |

### Sanktionen / Labels / Börse / Preis

| Datei | n | Zweck |
|-------|--:|-------|
| `test_sanctions.py` | 22 | Treffer, False-Positive-Härte |
| `test_sanctions_quelle.py` | 21 | eigener Server vor Clearnet |
| `test_sanction_hops.py` | 9 | Hop-Graph |
| `test_sanktions_cache_pfad.py` | 5 | Ergebnispfad |
| `test_labels.py` | 15 | Format; optional echter Bestand |
| `test_exchange_reports.py` | 13 | CSV-Import nur BTC |
| `test_exchange_spend.py` | 9 | „davon an Börse“ |
| `test_price.py` | 30 | Spot, Cache, Fallback ohne Netz |
| `test_price_history_sync.py` | 7 | Lücke/Overlap |

### i18n / Web-Statik / LLM

| Datei | n | Zweck |
|-------|--:|-------|
| `test_i18n.py` | 6 | de/en Key-Satz, Gerüst |
| `test_web_locales.py` | 4 | jeder `t()`/`data-i18n` in beiden Katalogen |
| `test_web_i18n.py` | 5 | `storedLang` vs. `ui_lang` vs. Browser |
| `test_web_sprache.py` | 30 | Accept-Language, Fußzeile |
| `test_hinweis_sprache.py` | 10 | On-Chain-Hinweis folgt der Sprache |
| `test_web_js.py` | 17 | doppelte `const`, Syntax-Fallen in `web/` |
| `test_chrome_nav_js.py` | 6 | Nav nach `/api/config` |
| `test_pager_js.py` | 17 | Seitenleiste |
| `test_anzeige.py` | 10 | sats/BTC-Schwelle Python = `format.js` |
| `test_llm_anbindung.py` | 34 | Pille, Status, **kein Key im JSON**; Ollama skip |
| `test_llm_client.py` | 11 | Tool-Whitelist, kein Remote-Default |
| `test_llm_context.py` | 6 | nur lokale Bestände, keine Jobs (**P4**) |
| `test_llm_haertung.py` | 6 | DoD ohne Netz/Cloud-Key |
| `test_status_mail.py` | 8 | Opt-in, neutrale Texte |
| `test_terminal_steuerung.py` | 15 | Job-Log-Spiegel |

### Specter / Packaging-nah

| Datei | n | Zweck |
|-------|--:|-------|
| `test_specter_gui_server.py` | 1 | GUI-Server ohne Specter |
| `test_specter_phase_a.py` | 3 | Plugin-Phase A |
| `test_specter_seed.py` | 4 | Cache-Seed aus Specter-Wallet-Info |

---

## 3 · Labor und GUI (nicht in Q1)

Labor (`lab/regtest/scripts/`):

- `verify_rpc_allowlist.py` — Allowlist + Hinweise `rpcwhitelist?` / `disablewallet?` am echten Node
- `generate_scenarios.py` / `generate_sanctions_scenarios.py`
- `verify_tx_classify.py` / `verify_sanctions_hops.py`
- Windows: `verify_gui.py` (Playwright, `channel=chrome`)
- `live_psbt_regtest_timing.py` — Lab darf `sendrawtransaction`, die App nicht

GUI-Protokolle: `doc/gui-test-protokoll.md`, `doc/testprotokoll-webgui-stabilitaet.md`, `doc/testprotokoll-webgui-userflow.md`, `doc/testprotokoll-datenquellen-wechsel-waehrend-scan.md`. Runner: `scripts/webgui_test_ready.py`, `webgui_chaos_run.py`, `webgui_userflow.py`.

---

## 4 · Skip-Marker

Alle `skipUnless`/`skipIf` sind begründet (kein Q2- paltes Skip):

| Bedingung | Dateien |
|-----------|---------|
| `node` fehlt | JS-Harness (`*_js.py`, `test_web_i18n.py`, `test_trace_knoten.py`, …) |
| kein Label-Bestand | `test_labels.TestGegenEchtenBestand` |
| kein Ollama / kein `qwen2.5:7b` | Teile von `test_llm_anbindung.py` |

Ubuntu-CI bringt Node mit; Label-Bestand und Ollama fehlen dort — die synthetischen Klassen derselben Dateien laufen trotzdem.

---

## 5 · Blinde Flecken

### Dealbreaker ohne eigenen Test

| ID | Lage |
|----|------|
| **T1** | Deskriptor-Import lehnt xprv ab. Es gibt **keinen** Scan von Locales, Login-HTML, Chat-Prompts und Specter-Templates auf Seed-/Mnemonic-/WIF-Felder. |
| **T6** | Kein Scan von `web/` auf Remote-`<script src>`, CDN, `eval`, `new Function`. `test_web_js.py` fängt Syntax, nicht Netz. |
| **T13** | `web/lernhinweise.json` und Handbuch §14 haben **null** Tests (Bitcoin-only, keine Anbieter-Startseiten). |
| **T4 / S1** | Secret-Pfade nur im Hook `githooks/pre-commit`, nicht in der Suite. Contributor ohne `hooksPath` haben keinen automatischen Riegel in Q1. |
| **T5** | Default-Bind ist getestet. Unmanaged `0.0.0.0` / Auth aus bleibt dünn. |
| **T7 / T8 / T10 / T12** | keine Tests. |
| **T9** | PSBT-**Bau** ist dick getestet. HTTP `POST /api/psbt/*` und „App broadcastet nie“ fehlen in Q1. Lab-Faucet `POST /api/lab/faucet-senden` ohne Test, dass er auf Mainnet tot ist. |
| **P1** | Cache-Löschen vs. Wallet-Alter/Header-Cache nicht als Dealbreaker-Test. |
| **P3** | neue Outbound-Hosts: nur Start9-SSRF-Ausschnitt. |

Gut abgedeckt: **T14** (Laufzeit + AST + Labor), **T11/P2** (öffentliche Electrum erst nach Bestätigung), **P4** (LLM startet keine Jobs).

### HTTP-Endpunkte ohne Treffer in `tests/`

Fachlogik kann in Core-Tests stecken; der **HTTP-Pfad** (Auth, Methode, Body-Limit, 404) ist das Loch.

- Auth: `/api/auth/logout`, `/api/auth/password`, `/api/auth/unlock-env`
- Config: `ui-theme`, `fifo-strategie`, `lernhinweise-plebs`, `person`, `status-mail`, `mempool` + `probe`, `sparrow-import`, `wallet-export-*`, `unlock-env`
- Fach: `/api/labels*`, `/api/exchange-reports*`, `/api/psbt/auswahl|erzeugen|max`, `/api/address/owner`, `/api/fee/suggestion`, `/api/tools/cache-suche`, `/api/source/local-core`, `/api/sanctions/update|import`, `/api/tax/lots` (NDJSON), `/api/jobs/wallet-sync`, `/api/gui-bereit`, `/api/lab/faucet-senden`, `/api/cache/wallets`

`/api/boot-log` hat Tests, aber nur den normalen JSON-Pfad — der NDJSON-Zweig in `server._verarbeite` bleibt unberührt.

### Core-Module ohne Import in Tests

`core/__init__.py` braucht keinen. Die anderen sind echte Lücken oder nur indirekt über Fassaden getroffen:

- `bip158_filter.py`, `electrum_servers.py`, `env_bootstrap.py`, `env_wallets.py`
- `fulcrum_client.py`, `fulcrum_transport.py` (Retry/Batch existieren, der Client selbst kaum)
- `launch_checks.py`, `log_i18n.py`, `splash_ui.py`, `tls.py`
- `receive_address.py` (Empfangs-API in `test_api` deckt den HTTP-Pfad, nicht die Flüchtigkeitsregel „QR sofort tot bei Wallet-Wechsel“)
- `sanctioned_address_utxos.py`, `sanctioned_output_trace.py`, `wallet_sanctions_check.py`
- `tx_utxo_analyze.py`, `utxo_report.py`

### Oberfläche

Kein Node-Test für: `web/app.js` (nur statische Fallen), `web/state.js`, `web/log_i18n.js`, `web/mempool_links.js`, `web/views/adress_labels.js`, `datenquellen.js`, `einstellungen.js`, `sanktionen.js`, `tools.js`. `steuerjahr.js` und `wallets.js` sind über Spezialtests teilweise gehalten.

`httpserver/handler_static.py`, `handler_sse.py`, `handler_download.py`, `splash.py`, `tls_p2p.py`, `historie_nachzug.py`: keine gezielten Tests (Path-Traversal, SSE-Abbruch, Download-Disposition).

### Packaging, Hooks, GUI-E2E

- `packaging/` (PyInstaller-Spec, StartOS-Manifest, Umbrel-YML): kein Q1-Test außer `test_paths.py`.
- `githooks/`: kein Test, dass Secret-Pfade und Identitätsregeln noch greifen.
- Browser-E2E und „Quelle wechseln während Scan“: Protokoll da, **kein CI** (steht so in `ISSUES.md` Tests · Blind spots).
- Chaos-Harness startet auf Windows ohne `channel="chrome"` (`doc/gui-test-protokoll.md`).

### Semantik, die ISSUES bewusst offen lässt

Steuerjahr zwei Tiefen (Horizont vs. voll) — `test_trace_steuer_horizon.py` ist ein Keim, keine Abnahme. BIP-158 ein Filterpass für alle XPUBs: ungetestet, weil Feature offen.

---

## 6 · Überflüssig oder überlappend

Nichts in Q1 ist toter Code im Sinne „assert True“. Überlappung gibt es.

**Erledigt (2026-10-06)**

1. Locale-Parität nur noch in `test_web_locales.py`; `test_i18n.py` hält das Gerüst.
2. Root-`test_server_auth.py` gelöscht, Inhalt in `test_start9_phase_s0.py`.
3. `test_labels.TestGegenEchtenBestand` aus Q1 entfernt.

**Komplementär, nicht streichen**

- `test_trace.py` (Walk) und `test_core_trace.py` (UI-Form) — die zweite Datei sagt das selbst.
- `test_tax.py` vs. `test_steuer_grundlage.py` / `test_tax_verlauf.py` / Fenster-Tests: verschiedene Zusicherungen.
- `test_fifo_lots.py` vs. `test_lot_ring_fifo_js.py` vs. `test_wallet_fifo_spend_js.py`: Core vs. Donut vs. Spend-Leiste.
- `test_rpc_allowlist.py` vs. `_statisch.py` vs. Labor-Verify: drei Riegel, Dealbreaker verlangt sie.
- `test_tx_classify.py` vs. `verify_tx_classify.py`: Fake-Graph vs. echte Lab-Txs.
- i18n-Rest: `test_web_i18n.py` (Client-Reihenfolge), `test_web_sprache.py` (Accept-Language), `test_hinweis_sprache.py` (Haftungstext) — nicht dieselbe Bugklasse.
- `test_mempool.py` (35 Methoden) ist repetitiv (URL-Formen), aber jeder Fall ist ein Leak-Vektor. Kürzen ginge per Tabelle, lohnt wenig.

**Schwer, nicht überflüssig:** `test_api.py` (205) und `test_tax.py` (128) und `test_wallet_fifo_spend_js.py` (53). Splitten hilft der Navigation, ändert die Abdeckung nicht.

---

## 7 · Was dazukommen sollte

Reihenfolge: Dealbreaker und Datenverlust zuerst, dann HTTP-Löcher der Produktflächen, dann E2E.

### Sofort (Hart / Review) — erledigt 2026-10-06

`tests/test_dealbreaker_statisch.py`, `tests/test_dealbreaker_http.py`. Gate `tests/hart.py`: auf `dev-juniormind` Skip, auf `main` Pflicht (`SATSAGE_HARD_TESTS=1`). Labor-Hinweise: `lab/regtest/scripts/infra_check.py`.

### Produktflächen (nächste PRs)

7. HTTP-Smoke (ein Happy-Path + ein 403) für Labels, Exchange-Reports, Sparrow-Import, Wallet-Export, `address/owner`, `fee/suggestion`, `psbt/auswahl|erzeugen`, `tools/cache-suche`.
8. **Empfangs-QR:** Wallet-Wechsel macht den QR sofort ungültig (`doc/design-fluchtigkeit.md`) — JS- oder API-Test.
9. `wallet_sanctions_check` / `sanctioned_output_trace` mit Fake-Graph (Hop-Tests decken die Engine, nicht den Wallet-Lauf).
10. `electrum_servers.json` Schema + `core/electrum_servers.py` Laden.
11. `env_bootstrap.py` / `launch_checks.py`: Start ohne `.env`, frozen vs. Skript.
12. Node-Stubs für `einstellungen.js` (Quelle speichern), `datenquellen.js` (Kaskade-UI), `sanktionen.js` (Job-Start), `adress_labels.js`.
13. `githooks/pre-commit`: Secret-Pfad-Liste gegen `.gitignore` und Dealbreaker-S1 (Hook-Skript mit Fake-`git` oder extrahierte Pfadliste).
14. **P1:** `DELETE /api/cache` lässt Header-Cache und Wallet-Alter liegen.

### Labor / GUI (nicht in die 20-Minuten-Suite)

15. Ein E2E-Smoke im Userflow-Sinn (Kern-Nav, keine 100 Chaos-Runden) — erst wenn der Maintainer CI-Zeit will; steht in ISSUES.
16. Eine automatisierte Mini-Variante von `testprotokoll-datenquellen-wechsel-waehrend-scan.md` im Labor.
17. Chaos-Runner: Windows `channel="chrome"` wie im GUI-Protokoll beschrieben.

### Bewusst nicht

- Volle Coverage von `splash_ui` / PyInstaller-Boot — manuell am Binary.
- Ollama-Live in CI.
- Steuer-Zwei-Tiefen-Abnahme, solange ISSUES das Feature verschiebt.
- Eigene Los-Buchhaltung testen — widerspricht dem Nutzerprofil.

---

## 8 · Pflege

Neue Testdatei: eine Zusicherung im Dateikopf, synthetische Fixtures, kein Mainnet des Nutzers. Neue Core-RPC-Methode: `test_rpc_allowlist*.py` + Labor-Verify + Doku, sonst **T14**.

Dieses Inventar nach größeren Schnitten an `tests/` oder `server._api` neu ziehen (Dateizahl, Methoden, ungetestete `/api/`-Zweige).
