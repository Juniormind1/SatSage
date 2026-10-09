# Testprotokoll: Scan-Abbruch und Cache-Hinterlassenschaften

**Stand:** 2026-10-07  
**Für:** Maintainer, Regtest-Labor, spätere Produkthärtung.  
**Zweck:** Ein Scan, der mittendrin stirbt, darf **keinen Cache hinterlassen, an dem die nächste SatSage-Instanz hängt, abstürzt oder in einer Schleife bleibt.**

**Verwandt:** [`testprotokoll-datenquellen-wechsel-waehrend-scan.md`](testprotokoll-datenquellen-wechsel-waehrend-scan.md), [`core/AGENTS.md`](../core/AGENTS.md) (Caches), Labor [`lab/regtest/README.md`](../lab/regtest/README.md).

**Runner:** `lab/regtest/scripts/verify_scan_abort_cache.py`  
**Proxy:** `lab/regtest/scripts/electrs_delay_proxy.py`

Kein Pflichtlauf in Dealbreaker **Q6**, bis das Produkt die Fälle grün hat.

---

## 1. Warum das heikel ist

Regtest indexiert und antwortet in Millisekunden. Ein Abbruch trifft dann oft den **fertigen** Cache. In der Realität (Electrs über Onion, Gap über hunderte Indizes, Zwischenstand alle paar Sekunden) stirbt der Prozess **während** `write_text` oder mit einem unfertigen JSON.

Beobachtete Fehlmodi:

1. **Abbruch-Knopf** — Job `cancelled`, Zwischenstand bleibt (`scan_end_index` unverändert, UTXOs schon geschrieben, Verlauf `incomplete`).
2. **Electrs weg** — TCP-RST / Timeout mitten im Gap. Halbes JSON oder `incomplete` ohne Resume-Grenze.
3. **kill -9 / taskkill /F** — `save_xpub_utxo_cache` und der Verlaufs-Cache schreiben **nicht** atomar (kein tmp+replace). Die Datei kann abgeschnitten sein. Immutable-Caches lassen `.json.tmp` liegen.
4. **Wallet aktualisieren, bevor Electrs steht** — Auto-Priorität wartet auf den eigenen Indexer (90 s), fällt dann auf BIP-158. Header-/Filter-P2P ist oft nur halb da. Kommt Electrs danach, mischt sich die Quelle mit dem angefangenen Cache.
5. **Ungeduldiger Scan** (aktuell halten aus) — User startet UTXO-/Verlaufsscan, während der Handshake noch hängt, besonders über Onion. Derselbe Mix: P2P-Halbstand, dann Electrs, dann Abbruch.

Ein zu freundlicher Loader (`json.loads` klappt → Felder werden geglaubt) führt in undefinierte Pfade oder Schleifen (Resume über `scanned_addresses` / `scan_end_index` / `incomplete`).

---

## 2. Soll

Nach **jedem** Abbruch und nach **jedem** Neustart gegen denselben Cache:

| Regel | Inhalt |
|-------|--------|
| R1 | Jede Cache-Datei ist gültiges JSON **oder** wird als Fehlschlag gelesen (`None` / leer), nie als Teilstück ausgewertet. |
| R2 | Liegengebliebenes `.json.tmp` wird ignoriert oder verworfen, nicht als Bestand gelesen. |
| R3 | `scan_end_index` / `scan_tip_height` / `bip158_fullscan_ok` markieren keinen fertigen Lauf, wenn der Scan abgebrochen wurde. |
| R4 | Verlauf `incomplete=True` setzt beim nächsten Lauf fort oder startet neu — ohne Endlosschleife. |
| R5 | Eine frische Instanz antwortet auf `/api/config`, `/api/wallets/{id}/utxos`, `/api/jobs` in wenigen Sekunden. Kein Hang, kein 500 durch kaputtes JSON. |
| R6 | Ein neuer UTXO-Scan nach dem Neustart endet (`done` / `failed` / `cancelled`), er bleibt nicht `running`. |
| R7 | Ein Job bindet die Quelle beim Start. Electrs, das **danach** kommt, übernimmt nicht mitten im P2P-Walk. Neue Jobs dürfen Electrs nutzen. |
| R8 | Start-Nachzug (`WALLETS_IMMER_AKTUELL`) wartet auf den eigenen Indexer. P2P startet den Bestandsscan nicht, solange der Indexer noch verbindet. |

---

## 3. Testumgebung

| Item | Vorgabe |
|------|---------|
| Infra | Lab-bitcoind + Electrs/Fulcrum, Szenarien erzeugt (`.data/.regtest.env`) |
| Isolierung | Eigene Cache-Dirs unter `lab/regtest/.data/abort-scan/` — nicht der GUI-Cache auf 8730 |
| GUI-Port | 8740 (fällt auf 8741… wenn belegt) |
| Electrs-Sicht von SatSage | Delay-Proxy `127.0.0.1:15001` → echter Indexer `127.0.0.1:50001` |
| Delay | Vorgabe 400 ms je Electrum-Zeile; Onion-Fall 2000 ms |
| Hold | Proxy nimmt TCP an, reicht den Handshake nicht durch (Indexer „verbindet noch“) |
| Wallets | Nur Lab Alpha in der isolierten Env |
| Auto-Scan | Aus, außer in Q-START-* |
| P2P | In Quelle-Fällen `BIP158_P2P=1`, Peer `127.0.0.1:18444`. Compact Filter nur wenn der Labor-Node `peerblockfilters=1` anbietet — sonst bleibt die P2P-Probe stecken, das zählt trotzdem als Hinterlassenschaft. |
| Recovery | Neustart **am echten** Electrs (Port 50001), Delay aus |

Windows: Docker nicht starten. Lab lokal (`start_lab.ps1`), dann den Prüfer.

---

## 4. Szenarien

Jedes Szenario: **Vorbedingung → Abbruch → Schnappschuss → Neustart → Soll**.

### 4.1 Gruppe `abort` — Scan läuft, Electrs ist da, nur langsam

Der Proxy verzögert, der Scan schreibt Zwischenstand, dann der Abbruch.

| ID | Scan | Abbruch |
|----|------|---------|
| U-ABORT | UTXO (`POST /api/jobs/rescan`) | `DELETE /api/jobs/{id}` |
| U-DROP | UTXO | Proxy `drop` (alle Sockets zu) |
| U-KILL | UTXO | `kill -9` / `taskkill /F /T` |
| V-ABORT | Verlauf (`POST /api/verlauf`) | Abbruch-Knopf |
| V-DROP | Verlauf | Electrs-Drop |
| V-KILL | Verlauf | kill -9 |

**Soll nach Neustart:** R1–R6. UTXO-Liste HTTP 200. Recovery-Scan endet.

### 4.2 Gruppe `quelle` — Electrs steht noch nicht / kommt zu spät

| ID | Ablauf | Abbruch |
|----|--------|---------|
| Q-START-P2P | **Ausgesetzt.** Seed-Cache (schneller Scan). Neu starten mit `WALLETS_IMMER_AKTUELL=1`. Proxy **hold**. `POST /api/gui-bereit` löst Wallet-Aktualisieren aus. Hold > Indexer-Frist (90 s) → P2P-Fallback. Dann Proxy **resume** (Electrs plötzlich da). | Abbruch-Knopf |
| Q-START-KILL | **Ausgesetzt.** wie Q-START-P2P | kill -9 während P2P oder Mix |
| Q-IMPATIENT | Aktuell halten **aus**. Hold. User startet UTXO-Scan sofort (Job in der Indexer-Warte). Nach wenigen Sekunden resume. | Abbruch-Knopf |
| Q-IMPATIENT-ONION | Kein Hold, Delay 2 s/Zeile (Onion-ähnlich). Scan sofort. | Abbruch-Knopf |
| Q-IMPATIENT-DROP | Hold bleibt. Scan sofort. Electrs kommt nie. | Drop |

**Soll zusätzlich R7–R8:** Der laufende Job wechselt die Fetchers nicht, wenn Electrs nachträglich da ist. Log: eine Quellen-Bindung. Nach Neustart keine Schleife zwischen P2P-Tip und Electrs-Gap.

### 4.3 Gruppe `synthetic` — Dateien, die kill -9 nicht zuverlässig trifft

| ID | Datei |
|----|-------|
| S-TRUNC-UTXO | `{key}.json` nach `{"xpub":"` abgeschnitten |
| S-EMPTY-UTXO | leere `{key}.json` |
| S-TMP | `{key}.json.tmp` ohne fertige `.json` |
| S-LIST | `{key}.json` ist `[]` |
| S-TRUNC-VERLAUF | `{key}_verlauf.json` abgeschnitten |
| S-INCOMPLETE-VERLAUF | `incomplete: true`, `scanned_addresses == planned_addresses` |
| S-TRUNC-EXTERNAL | `external_addresses.json` abgeschnitten |

**Soll:** Boot + APIs wie R5–R6. Kaputte Datei = Cache-Miss, nicht 500.

---

## 5. Automatisierung

```bash
# Katalog
python3 lab/regtest/scripts/verify_scan_abort_cache.py --list

# Alles außer den ausgesetzten P2P-Fällen (Labor muss laufen)
python3 lab/regtest/scripts/verify_scan_abort_cache.py

# Nur Abbruch / nur Quelle / nur synthetisch
python3 lab/regtest/scripts/verify_scan_abort_cache.py --group abort
python3 lab/regtest/scripts/verify_scan_abort_cache.py --group quelle
python3 lab/regtest/scripts/verify_scan_abort_cache.py --group synthetic

# Einzelne IDs
python3 lab/regtest/scripts/verify_scan_abort_cache.py --only U-KILL,Q-IMPATIENT
```

Windows: `py -3 lab\regtest\scripts\verify_scan_abort_cache.py`

Report: `lab/regtest/.data/abort-scan/report.json` (keine XPUBs, keine Tokens).  
Schnappschüsse: `lab/regtest/.data/abort-scan/leftovers/<ID>/`.

Proxy allein (manueller Lauf):

```bash
python3 lab/regtest/scripts/electrs_delay_proxy.py --delay-ms 400 --hold --control-file lab/regtest/.data/abort-scan/proxy.control
# Datei: je Zeile hold | resume | drop | delay 400 | stop
```

SatSage gegen den Proxy: `FULCRUM_PORT=15001`, `--cache-dir` auf den Isolationsordner, `--port 8740`.

---

## 6. Kurzprotokoll (~25 min, ohne Q-START)

1. Lab läuft, Szenarien existieren.  
2. `--group abort` (U-* und V-*).  
3. `--group synthetic`.  
4. Q-IMPATIENT und Q-IMPATIENT-ONION.  
5. Report: alle `ok: true`, keine Timeouts.

---

## 7. Vollprotokoll (~45–70 min)

Dasselbe wie das Kurzprotokoll. **Q-START-P2P** und **Q-START-KILL** nicht dazunehmen: sie prüfen P2P als Quelle, und P2P ist keine (`doc/issues/p2p-herkunft.md`). Der Default-Lauf lässt sie aus. Ein ausdrückliches `--only Q-START-P2P` startet sie trotzdem, für den Tag, an dem die Sperre fällt.

---

## 8. Befundvorlage

```text
Datum:
VERSION / Git:
Lab: bitcoind+Electrs ja/nein
peerblockfilters am Node: ja/nein

ID                  | OK/Fail | Trigger     | leftover trunc/tmp | Restart-Notiz
--------------------|---------|-------------|--------------------|----------------
U-ABORT             |         |             |                    |
U-DROP              |         |             |                    |
U-KILL              |         |             |                    |
V-ABORT             |         |             |                    |
V-DROP              |         |             |                    |
V-KILL              |         |             |                    |
Q-START-P2P         | ausgesetzt (P2P keine Datenquelle) | | |
Q-START-KILL        | ausgesetzt (P2P keine Datenquelle) | | |
Q-IMPATIENT         |         |             |                    |
Q-IMPATIENT-ONION   |         |             |                    |
Q-IMPATIENT-DROP    |         |             |                    |
S-TRUNC-UTXO        |         |             |                    |
S-EMPTY-UTXO        |         |             |                    |
S-TMP               |         |             |                    |
S-LIST              |         |             |                    |
S-TRUNC-VERLAUF     |         |             |                    |
S-INCOMPLETE-VERLAUF|         |             |                    |
S-TRUNC-EXTERNAL    |         |             |                    |

Blocker:
```

---

## 9. Stolpersteine

| Symptom | Deutung |
|---------|---------|
| „Scan war fertig bevor der Abbruch greifen konnte“ | Delay zu klein, Hold zu kurz |
| Recovery-Scan Timeout | Endlosschleife oder Quelle blockiert — Rot |
| `GET /api/config` Timeout | Loader hängt in kaputtem JSON / Adressableitung |
| Q-START ohne Seed | Start-Sync braucht vorhandenen UTXO-Cache; der Runner seeden selbst |
| P2P-Probe ohne Compact Filter | Labor-Node ohne `peerblockfilters=1`; Fall bleibt gültig (kein Electrs, Scan scheitert sauber) |
| Port 8740 belegt | Runner nimmt den nächsten freien Port |
| GUI auf 8730 | Unberührt; Isolations-Cache ist ein anderer Ordner |

---

## 10. Abnahme

**Grün**, wenn jedes gewählte Szenario `ok: true` ist: Neustart bootet, APIs antworten, kein Hang, Recovery-Scan endet, kaputte Dateien sind Cache-Miss.

**Rot** bei Timeout/Hang, HTTP 500 durch kaputtes JSON, Endlos-Resume, oder wenn ein laufender Job nachträglich die Fetchers auf Electrs umlegt.
