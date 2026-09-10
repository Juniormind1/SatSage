# Plan: P2P-BIP-158-Erstscan beschleunigen

## Ziel

Erstscan über Compact Filter (BIP 157/158) massiv beschleunigen — Wasabi-Turbo-UX, cfilter-Disk-Cache, Filter/Block-Entkopplung — ohne Steuer-/Trace-Refactor, ohne Public-Electrum-Default, ohne Filterformat-Änderung. Protokoll bleibt Core-kompatibel (`M=784931`, `P=19`, SipHash aus Blockhash).

## Ist (knapp)

| Stelle | Problem |
|--------|---------|
| `plane_filter_passes()` (`bip158_scanner.py` ~474–502) | `used_scripts` leer → ein Pass `historie(all × start…tip)` — Turbo greift erst später |
| `_lade_cfilter_chunk` (~609–636) | Match-Hit → synchron `peer.fetch_block` im Filter-Worker |
| cfilters | nur RAM; kein Disk-Cache → zweites Wallet/Rescan holt alles neu |
| Historie-Keys | `max_index` bis ~250–500 inkl. Change → FP-Lawine in der Historie |
| Start | oft still `SEGWIT_HEIGHT=481824`, auch wenn First-seen/UI jünger |

Bestehende Stärken behalten: `GETCFILTERS_MAX=1000`, `FILTER_PEERS_MAX=4` (optional 6), `_CoreBasicFilterMatcher`, Header-Archiv, `BIP158_REORG_BUFFER=6`.

---

## Architektur nach dem Patch

```
Pass A turbo (all scripts × tip−2016…tip)
  → Zwischenstand / UI nutzbar
Pass B historie (gap∪hits × start…turbo−1)  [gleicher Job]
  → Block-Events sammeln
Final: UTXO-Set chronologisch aus allen Block-Events (Höhe aufsteigend)

Filter-Worker: getcfilters + Match (+ Disk-Cache)
Block-Worker (1–2): Queue ← Hits; fetch_block parallel
```

**UTXO-Korrektheit bei Turbo-zuerst:** Spends alter Coins im Turbo-Fenster ohne vorherigen Receive würden sonst hängende UTXOs erzeugen. Deshalb Block-Ergebnisse beider Pässe **nach Höhe sortiert** auf `bestaende` anwenden (Zwischenstand nach Pass A = provisorisch OK; final nach Pass B korrekt).

---

## 1. `plane_filter_passes` — Wasabi-Erstscan

**Datei:** `bip158_scanner.py`

### Verhalten

```text
used leer (Erstscan):
  1. ("turbo",    turbo_from, tip,           all_scripts)
  2. ("historie", start,      turbo_from-1,  gap_scripts)
     — gap_scripts default: Indizes 0..gap_limit-1 (Receive+Change); nach Pass A: used∪gap um Hits

used gesetzt (wie bisher, Reihenfolge historie→turbo chronologisch):
  1. ("historie", start, turbo_from-1, used)   falls start < turbo_from
  2. ("turbo",    turbo_from, tip, all)
```

Optionaler Parameter: `gap_scripts: set[bytes] | None = None`.

**Docstring** an reale Erstscan-Praxis anpassen (Kommentar heute widerspricht dem Code).

### Scan-Orchestrierung (`_scan_script_map` / `scan_from_xpub`)

1. Watchlist Pass A: `max_index` wie heute (Lookahead).
2. Pass A ausführen → Hits → used aus getroffenen Scripts.
3. Gap lokal: nächste `DEFAULT_GAP_LIMIT=20` ungenutzte Indizes um bekannte (Receive + Change getrennt).
4. Pass B nur mit `used ∪ gap` (nicht volle Lookahead-Menge).
5. Mehrere XPUBs: pro XPUB eigene used/gap in `fetch_wallet_utxos_bip158`.

Neu (klein): `scripts_mit_gap_um_treffer(xpub, hit_scripts, *, gap_limit=20, ...) -> set[bytes]`.

---

## 2. cfilter-Disk-Cache (Pflicht)

**Ablage:** `immutable_cache/cfilter/` — Key Höhe + Blockhash (Reorg-sicher), z. B. `{height}_{blockhash_hex}.bin`.

**API:** `lade_cfilter_blob` / `speichere_cfilter_blob` (mit `cache_disk_write_allowed`). Lesen gegen `HeaderChain.hash_at(h)`; Mismatch = Miss.

**Einbindung `_lade_cfilter_chunk`:** vor Netz Cache prüfen; nach Empfang schreiben. Ganz warmer Chunk → 0× `fetch_cfilters`. Log: `#geholt` vs `#gecacht`.

---

## 3. Filter- vs. Block-Download entkoppeln

1. Filter-Worker: nur Match; Hits → `block_queue`; `roh=None` in Chunk-Zeile.
2. 1–2 Block-Fetcher (Peers ohne Filter-Chunk-Lock): `fetch_block` → Result-Map.
3. Consumer wartet höhenweise auf Block-Bytes; False Positives stoppen den nächsten 1000er-Filter-Batch nicht.

Test `test_filter_treffer_loggt_bevor_der_block_kommt` anpassen (Log vor Fetch, Fetch async).

---

## 4. Birthday / Start härten

| Quelle | Start |
|--------|--------|
| First-seen / Alter-Cache | `first_seen_height − BIP158_REORG_BUFFER` |
| UI/CLI jüngeres Datum/Höhe | respektieren — nicht still auf 481824 |
| Default SegWit | nur bei explizitem `BIP158_START_HEIGHT` / User-Set |

Log: Start-Höhe, `#Scripts`, `#Filter geholt` / `#Filter Cache`.

---

## 5. Matching-Hot-Path (leicht)

Queries vorbereiten / Matcher pro Blob wiederverwenden. Keine chiabip158 auf Core-Filter. Keine Cython in diesem Diff.

---

## 6. P2P-Konstanten

`GETCFILTERS_MAX=1000` behalten. `FILTER_PEERS_MAX=4` im Kern-Diff; optional später 6. Keine cfheaders.

---

## Dateien

| Datei | Änderung |
|-------|----------|
| `bip158_scanner.py` | Passes, Gap, Cache-Hooks, Entkopplung, Orchestrierung, Start-Log |
| `core/cfilter_cache.py` (neu, klein) oder inline | laden/schreiben |
| `tests/test_bip158_scanblocks.py` | Pass-Plan, Cache-warm, Block-Queue |
| `README.md` + `doc/handbuch.html` | Absatz Erstscan + Filtercache |
| `CHANGELOG.md` | [Unveröffentlicht] |

Nicht anfassen: Trace/Steuer, Public-Electrum-Default, Filterformat.

---

## Tests (Akzeptanz)

1. used leer → turbo(all) + historie(gap) — kein Full-Range-All-Keys (`test_erstscan_ohne_used_…` ersetzen).
2. used gesetzt → Historie(used) + Turbo(all).
3. Cache warm → 0× `fetch_cfilters`.
4. Filterhit enqueued; Filter-Loop läuft weiter bevor Block fertig.
5. Matcher-Self-Tests grün.

---

## Reihenfolge

1. `plane_filter_passes` + Tests
2. Gap + Pass A→B + chronologischer UTXO-Merge
3. cfilter-Cache + Warm-Test
4. Filter/Block-Entkopplung + Queue-Test
5. Birthday/Start-Log
6. Docs/Changelog
7. Feinschliff danach

---

## Risiken

- Turbo-vor-Historie ohne finalen Höhen-Merge → falsche UTXOs (Merge Pflicht).
- Historie nur Gap-20 ist bewusster Wasabi-Tradeoff, kein „weniger Blöcke ohne Gap“.
- Viele Flatfile-Filterblobs: Schreibgate beachten; kein SQLite in diesem PR.
