# Testprotokoll: Lab-Traces ausschließlich über Bitcoin-P2P

**Stand:** 2026-10-07  
**Für:** Maintainer, Regtest-Labor.  
**Zweck:** Herkunft, Tx-Klassifikation und Sanktions-Hops **ohne Electrs und ohne Core-`getrawtransaction`** — nur Compact Filter, Header und Blöcke vom Labor-Node. P2P war im Labor bisher ungenutzt.

**Verwandt:** [`testprotokoll-scan-abbruch-cache.md`](testprotokoll-scan-abbruch-cache.md), [`core/AGENTS.md`](../core/AGENTS.md) (BIP-158), [`lab/regtest/README.md`](../lab/regtest/README.md). Electrs gegen dasselbe Inventar: `lab/regtest/scripts/verify_electrs_inventar.py`. Mainnet: Knopf „Check P2P Walks“ in den Datenquellen, Route `POST /api/p2p/walk-abgleich`.

**Runner:** `lab/regtest/scripts/verify_p2p_traces.py`

Kein Pflichtlauf in Dealbreaker **Q6**, bis P2P auf Regtest grün ist.

---

## 1. Warum extra

Die übrigen Labor-Prüfer holen Txs über Electrs oder Core-RPC. Der BIP-158-Pfad (Filter matchen, Block nur bei Treffer, Herkunft über P2P-`getdata` / Block) bleibt dann unberührt.

Typische Lücken, die nur dieser Lauf trifft:

| Lücke | Wirkung |
|-------|---------|
| P2P-Magic/Genesis nur Mainnet | Handshake mit Regtest-Node scheitert |
| `BIP158_START_HEIGHT` Default 481824 | Filter-Scan überspringt die kurze Lab-Kette |
| Compact Filter nicht angeboten (`peerblockfilters` aus) | `verify_p2p_filters` scheitert |
| P2P-Port 18444 nicht auf dem Host | Docker: nur RPC 18443 veröffentlicht |
| `get_tx` fällt still auf Core zurück | Der Test wäre grün, ohne P2P zu üben |
| Herkunft ohne Blockhöhe des Prevouts | `getdata` TX notfound, kein Block-Fallback |

---

## 2. Soll

| Regel | Inhalt |
|-------|--------|
| P1 | Handshake mit `127.0.0.1:18444`, Compact Filter, Netz **regtest**. |
| P2 | Wallet-Scan über BIP-158 findet **jeden** Outpoint aus `.data/herkunft-inventar.json` (Alpha/Beta/Change/Gamma), Betrag und Wallet gleich, kein Extra. |
| P3 | `get_tx` im Lauf hat **kein** Electrs und **kein** Core. Höhe kommt aus dem Filter-Scan (`note_tx_height`) oder aus dem Block. |
| P4 | Herkunft jedes Inventar-UTXOs deckt die gespeicherte Signatur (Typ, Prevouts, Beträge, Enden). Ein `error`-Blatt ist nur dann grün, wenn das Inventar dasselbe Blatt hat. Der Prozess hängt nicht. |
| P5 | Tx-Klassifikation der Lab-Formen liefert dieselben Soft-Labels wie `verify_tx_classify.py`. |
| P6 | Sanktions-Hop-Ketten: Treffer bei der erwarteten Tiefe, analog `verify_sanctions_hops.py`. |
| E1 | Erstscan: Historie-Pass nur Gap-Scripts, nicht die volle Lookahead-Menge (Turbo wie Wasabi). |
| E2 | `getcfilters` nur für fehlende Höhen-Spannen, nicht den ganzen 1000er-Chunk bei einer Lücke. Expect-Summe in O(Kette), nicht Keys×Höhe. |
| E3 | Derselbe Block-Hash höchstens einmal über P2P — Session-Cache, Geschwister-Txs aus dem Block. |
| E4 | Bekannte Blockhöhe: kein `getdata` TX (notfound), direkt der Block. |
| E5 | Header-Overlap nutzt den Hash-Index, nicht Header-für-Header über die Kette (wie Electrs-Tip per Binärsuche in `p2p_headers.bin`). |

Rot: Handshake tot, Scan leer, Timeout/Hang, HTTP-loser Absturz, stiller Core/Electrs-Pfad, Budget E1–E5 gerissen.

---

## 3. Testumgebung

| Item | Vorgabe |
|------|---------|
| Node | `blockfilterindex=1`, `peerblockfilters=1`, `listen=1`, P2P `127.0.0.1:18444` |
| Docker | Port **18444** auf den Host mappen (Compose enthält das) |
| Windows | `scripts/win/_common.ps1` schreibt `peerblockfilters=1`. Bestehende `bitcoin.conf` einmal neu schreiben oder die Zeile ergänzen, Node neu starten |
| Start-Höhe | `BIP158_START_HEIGHT=1` (nicht 481824) |
| Peer | `BIP158_PEERS=127.0.0.1:18444` |
| Isolierung | Caches unter `lab/regtest/.data/p2p-traces/` |
| Inventar | `lab/regtest/.data/herkunft-inventar.json`, erzeugt von `herkunft_inventar.py` (auch am Ende von `generate_scenarios.py`). Quelle: `listunspent` plus Core-`getrawtransaction`. Der P2P-Lauf liest die Datei nur. |
| Electrs | Läuft dürfen, der Prüfer konfiguriert ihn nicht |
| Szenarien | `generate_scenarios.py` und `generate_sanctions_scenarios.py` schon gelaufen |

Bestehendes Labor ohne Compact Filter: Node mit neuer Conf neu starten. Chain-Wipe ist nicht nötig, nur Filter-Index + `peerblockfilters`.

---

## 4. Suiten

### 4.1 `origin`

1. P2P-Client, Handshake, Header ab Höhe 1.  
2. BIP-158-Scan aller Lab-Wallets.  
3. Bestand gegen das Inventar: jeder Outpoint, Betrag, Wallet. Fehlend oder extra ist rot.  
4. `trace_utxo_origin` je Inventar-UTXO mit P2P-`get_tx`, Signatur gleich dem Inventar.

`--max-traces N` begrenzt die Zahl (Rauchtest).

### 4.2 `classify`

Dieselben Fälle wie `scenario-report-txclass.json` (Wasabi-classic, WabiSabi, Whirlpool, JoinMarket, PayJoin, Fan-out, Exchange-Batch). `get_tx` nur P2P.

### 4.3 `sanctions`

Ketten aus `scenario-report-sanctions.json`. Default-Tiefen `1,3,10` (100 ist mit Block-Download je Hop sehr lang; Vollprotokoll setzt `--depths 1,3,10,25,100`).

### 4.4 `economy`

Zählt `getcfilters`/`getdata` während origin/classify/sanctions. Zusätzlich der Turbo-Pass ohne Node (Lookahead nicht durch die Historie).

Analogie: Electrs-Tip war `block.header` 0…1,5 Mio., jetzt Halbierung über `p2p_headers.bin`. Derselbe Anspruch an P2P: keine lineare Vollabfrage, wo Index, Cache oder Gap reicht.

---

## 5. Automatisierung

```bash
python3 lab/regtest/scripts/verify_p2p_traces.py
python3 lab/regtest/scripts/verify_p2p_traces.py --suite origin --max-traces 8
python3 lab/regtest/scripts/verify_p2p_traces.py --suite classify,sanctions
python3 lab/regtest/scripts/verify_p2p_traces.py --suite economy
python3 lab/regtest/scripts/verify_p2p_traces.py --depths 1,3,10,25,100
```

Windows: `py -3 lab\regtest\scripts\verify_p2p_traces.py`

Report: `lab/regtest/.data/p2p-traces/report.json` (gekürzte TxIDs, keine XPUBs).

Infra: `brauche("bitcoind", "p2p")` — Electrs ist hier keine Pflicht.

---

## 6. Kurzprotokoll (~15–30 min)

1. P2P 18444 offen, Compact Filter an.  
2. `--suite origin --max-traces 8`.  
3. `--suite classify`.  
4. Handshake und mindestens ein Origin-Trace plus Klassifikation grün.

---

## 7. Vollprotokoll

Alle drei Suiten ohne `--max-traces`, Sanktionen mit `--depths 1,3,10,25,100`.

---

## 8. Befundvorlage

```text
Datum:
VERSION / Git:
peerblockfilters: ja/nein
P2P 18444: ja/nein

Suite      | OK/Fail | Notiz
-----------|---------|----------------
handshake  |         |
origin     |         |
classify   |         |
sanctions  |         |
economy    |         |

Erste rote Zeile (Exception-Typ):
```

---

## 9. Stolpersteine

| Symptom | Deutung |
|---------|---------|
| Handshake / Magic | Client spricht Mainnet (`f9beb4d9`) mit Regtest (`fabfb5da`) |
| Scan 0 UTXOs, Tip winzig | Start-Höhe 481824 oder Header-Cache von Mainnet im selben Ordner — Isolationsdir nutzen |
| `notfound` / keine Blockhöhe | Prevout war kein Filter-Treffer; P2P-`getdata` TX kennt historische Tx nicht |
| Klassifikation grün, Origin rot | Core-RPC hat classify früher getragen; dieser Lauf darf Core nicht anfassen |
| Docker: Connection refused 18444 | Port-Mapping fehlt, Compose neu starten |

---

## 10. Abnahme

**Grün:** Handshake, Origin-Bestand und Herkunft deckungsgleich mit dem Inventar, Klassifikation und Sanktions-Hops über P2P, ohne Electrs und ohne Core-Tx im Prüfer.

**Rot:** Handshake tot, stiller Core/Electrs-Pfad, Hang, oder Herkunft bricht an jedem Fremd-Prevout ohne klare Fehlerzeile ab.
