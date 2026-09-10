# Testprotokoll: Datenquellen-Wechsel während Scans

**Stand:** 2026-09-10  
**Für:** Maintainer, manuelle Live-Tests, spätere Automatisierung (Unit/Chaos).  
**Zweck:** Den Server und die GUI **abhärten**, wenn während UTXO-/Verlaufs-Scans die Datenquelle wechselt — besonders **P2P (BIP-158) ↔ öffentliche Electrum (Onion/Clearnet)** und zurück.

**Verwandt:** [`testprotokoll-webgui-stabilitaet.md`](testprotokoll-webgui-stabilitaet.md), [`logging-richtlinie.md`](logging-richtlinie.md), [`plan-bip158-erstscan.md`](plan-bip158-erstscan.md), [`AGENTS.md`](../AGENTS.md) (Datenquellen-Priorität).

---

## 1. Warum das heikel ist

P2P-Compact-Filter und Electrum-`get_history` / Gap-Scan sind **verschiedene Welten**. Sie teilen denselben UTXO-/Verlaufs-Cache, bauen aber **nicht** naiv aufeinander auf:

| Aspekt | BIP-158 (P2P) | Electrum (eigen / onion-electrs / clearnet-electrs) |
|--------|---------------|-----------------------------------------------------|
| Fortschritt | Blockhöhen, `scan_tip_height`, Filter-Chunks | Adress-Indizes, Gap, `get_history` |
| „Fertig“ | `bip158_fullscan_ok` + Tip | oft `scan_end_index` / volle Adressliste |
| Zwischenstand | UTXOs aus Block-Parse, Turbo-Fenster | listunspent / History-Walk |
| Abbruch | Partial-UTXOs **ohne** Fullscan-Flag → Turbo erneut | Resume über skip_addresses / Cache |
| Privatsphäre | hoch (lokal matchen) | mäßig/gering (Adressen an Server) |

### Typische Fehlmodi ohne Strategie

1. **P2P-Scan läuft → User schaltet P2P aus / Electrum an**  
   Job nutzt weiter alte Fetchers oder bricht still ab; GUI zeigt „verbunden“ für die neue Quelle, Scan schreibt noch P2P-Zwischenstände.

2. **Electrum-Gap halb fertig → User aktiviert P2P**  
   Nächster Lauf liest Electrum-UTXOs als „used“, deaktiviert Turbo-Erstscan fälschlich, oder mischt `scan_tip_height` mit Electrum-Stand.

3. **Öffentliche Onion tot → Clearnet**  
   Allowlist (`OEFFENTLICHE_ELECTRUM` vs. Outbound-Opt-in) blockiert Clearnet; Scan hängt bei „Moment noch“ ohne klare Fehlerphase.

4. **Zwei Wallets in der Queue, Quelle wechselt dazwischen**  
   Wallet A mit Electrum gestartet, Wallet B mit P2P — Pipeline teilt sich Backend-Zustand / Live-Peers / Tor.

5. **Abbruch + Quellenwechsel + Restart**  
   Stale `rescanJob` / `sources_last` / Live-Peers: UTXO-Knopf tot, Pille „verbunden“ an falscher Quelle.

**Härtungsziel:** Jeder laufende Scan hat eine **feste Quellen-Bindung** (Snapshot beim Start). Quellenwechsel betrifft **nur neue** Jobs. Cache-Flags machen klar, **mit welcher Strategie** der Bestand entstanden ist und was der nächste Lauf tun darf.

---

## 2. Soll-Strategien (Produkt / Code)

Diese Regeln sind die **Soll-Architektur**. Wo der Code sie noch nicht erfüllt, markiert das Protokoll den Test als **Rot** und den Punkt als Implementierungs-Backlog.

### S1 · Job-lokaler Quellen-Snapshot

- Beim Start von UTXO-/Verlaufs-Job: `meta.source`, `meta.source_detail` (z. B. `bip158` / `fulcrum-onion` / `fulcrum-clearnet` / `own_fulcrum`) **einfrieren**.
- Laufender Job **wechselt die Fetchers nicht**, wenn der User in Einstellungen die Priorität ändert.
- Log: eine Zeile *„Scan gebunden an: …“* beim Start; bei User-Wechsel der globalen Quelle *„Neue Jobs nutzen ab jetzt …; laufende Scans behalten …“*.

### S2 · Quellenwechsel während Scan

| User-Aktion | Erwartung |
|-------------|-----------|
| P2P aus (Papierkorb / Schalter) während P2P-Scan | Scan **läuft zu Ende oder Abbruch**; Live-Peers der Pille werden für **neue** Checks bereinigt; laufender Job darf bis Ende Peers halten |
| Öffentlich erlauben / kappen | Opt-in speichern; **kein** Abwürgen fremder Jobs ohne Dialog |
| Eigener Electrum speichern | Neuer Connect-Test; laufende öffentliche Scans unberührt |

### S3 · Cache-Kompatibilität P2P ↔ Electrum

- **Partial P2P** (`bip158_fullscan_ok=false`): nächster P2P-Lauf = Turbo-Erstscan; Electrum-Lauf darf Partial-UTXOs als Seed nutzen, setzt **kein** `scan_tip_height` als P2P-fertig.
- **Fertiger P2P-Fullscan** (`bip158_fullscan_ok=true`, Tip): Electrum-Light/Tip-Nachzug ok; Full-Rescan Electrum überschreibt Bestand bewusst (Log).
- **Fertiger Electrum-Scan** ohne Tip: nächster P2P-Lauf **nicht** als Tip-inkrementell behandeln, es sei denn Tip wurde explizit gesetzt. `used_scripts` nur nach klarer Policy (siehe Turbo-Flag).
- Cache-Feld vorschlagen (Backlog): `last_utxo_source` ∈ {`bip158`,`fulcrum`,…} — GUI/Scan entscheidet Merge vs. Full.

### S4 · Fallback-Kette nur **zwischen** Jobs

- Auto-Priorität (eigen → P2P → onion-electrs → clearnet-electrs) gilt beim **Job-Setup**, nicht mitten im Gap-/Filter-Walk.
- Scheitert Setup (z. B. P2P 0 Peers): **eine** klare Phase + optional Fallback **vor** dem ersten Adress-/Filter-Schritt, nicht nach 30 Adressen still umschalten.

### S5 · GUI-Knöpfe und Pillen

- UTXO-Scan-Knopf nur disabled, wenn **dieses** Portfolio wirklich scannt/queued (`jobNochAktiv`).
- Nach Abbruch: Knopf sofort frei.
- Pillen: „Verbindung im Aufbau…“ / „verbunden“ / nicht erreichbar; öffentliche Electrum als **onion-electrs** / **clearnet-electrs**, nicht „Peers“.
- Bei aktiver höherer Quelle: kein stale „verbunden“ an öffentlich.

### S6 · Privatsphäre-Dialog

- P2P wird an und hat Peers, öffentlich war erlaubt → Dialog „Höhere Privatsphäre? / öffentlich kappen“.
- Kappen: `OEFFENTLICHE_ELECTRUM` aus; Clearnet-Outbound folgt derselben Entscheidung (Opt-in gekoppelt).

---

## 3. Testumgebung

| Item | Vorgabe |
|------|---------|
| Server | frischer `py server.py` **nach** den letzten Commits (nicht alter Prozess) |
| Session | `scripts/webgui_test_ready.py attach` oder spawn — **kein** Token-Grep |
| Wallets | ≥ 2 Test-Wallets (z. B. „Cash & Carry“, „Mortens Firmung“); XPUBs nur Lab |
| Quellen | konfigurierbar: P2P an/aus, Onion-Liste, Clearnet-`electrum_servers.json`, Opt-in |
| Tor | SOCKS 9050/9150 wenn Onion/Core-Onion getestet wird |
| Log | Web-Log + optional Terminal; Konsole DevTools |
| Snapshot | VERSION, Git-Hash, Uhrzeit, welche Quelle zu Beginn aktiv |

**Sicherheit:** Keine Prod-XPUBs committen; Lab-`.env` getrennt.

---

## 4. Manuelle Szenarien (Härtungs-Matrix)

Jedes Szenario: **Vorbedingung → Schritte → Erwartung → Beobachtung (OK/Fail) → Cache-Check**.

### 4.1 Baseline: Quelle stabil, Scan durch

| # | Schritte | Erwartung |
|---|----------|-----------|
| B1 | P2P an, UTXO-Scan Wallet A bis Ende | Log: gebunden bip158; `bip158_fullscan_ok`; Tip; Knopf wieder aktiv |
| B2 | P2P aus, onion-electrs, Verlauf A | Fortschritt Adresse n/m; Einträge steigen; kein stummes „Moment noch“ >2 min ohne Detail |
| B3 | Nur clearnet-electrs (Onion-Liste leer), Opt-in an | Clearnet connectet (nicht Allowlist-Block trotz Opt-in); Scan läuft |

### 4.2 P2P-Scan läuft → Electrum-Fallback (User)

| # | Schritte | Erwartung |
|---|----------|-----------|
| P1 | P2P-UTXO-Scan starten (Turbo/Historie sichtbar) | Job `meta` = bip158 |
| P2 | Während Scan: P2P-Schalter aus / Papierkorb | Laufender Scan bricht **nicht still** ab ohne Log; oder bleibt bis Ende auf P2P; GUI: P2P-Zeile aus, nächste Quelle „im Aufbau“ |
| P3 | Parallel zweiten UTXO-Scan A oder B | Entweder Queue mit **neuer** Quelle oder Ablehnung mit klarer Meldung — kein Misch-Fetcher |
| P4 | Nach Abbruch/Ende: UTXO-Scan mit Electrum | Kein falscher Tip-Inkrement aus Partial-P2P; Turbo oder Full laut Flag |

**Cache-Check nach P2–P4:**

```text
utxo_cache/<hash>.json → source, bip158_fullscan_ok, scan_tip_height, utxo_count
```

### 4.3 Electrum-Scan läuft → P2P wieder an

| # | Schritte | Erwartung |
|---|----------|-----------|
| E1 | Öffentlich/Onion, Gap-Scan A starten | `Scanne … fulcrum`, Indizes steigen |
| E2 | Mitten drin: P2P aufbauen + speichern | Dialog Privatsphäre optional; **dieser** Gap-Job bleibt fulcrum |
| E3 | P2P-Peers verbunden (Pille / Log) | Öffentlich nicht mehr „verbunden“ wenn P2P ok (stale cleared) |
| E4 | Gap abbrechen, UTXO erneut (P2P) | P2P-Pfad; wenn Electrum-UTXOs im Cache: Merge-Policy befolgen, Log nennt Quelle |

### 4.4 Hin und her (Stress)

| # | Schritte | Erwartung |
|---|----------|-----------|
| H1 | 5× innerhalb 2 min: P2P an → aus → an, jeweils Connect-Test | Kein Crash; `sources_last` konsistent; keine doppelten Header-Jobs-Storms |
| H2 | Während H1: Scan A in Queue, Scan B starten | Queue FIFO; jeder Job eigene Quellen-Zeile im Log |
| H3 | Abbrechen A, Quelle wechseln, sofort A neu | Knopf aktiv; neuer Job neue Quelle; alter Job nicht „Zombie“ |

### 4.5 Queue + zwei Portfolios

| # | Schritte | Erwartung |
|---|----------|-----------|
| Q1 | A UTXO starten, sofort B UTXO | B queued; Leiste nennt A, „Dann: B“ |
| Q2 | Während A: Quelle P2P→Electrum | A unverändert; B startet mit **neuer** Quelle (Snapshot bei B-Start) |
| Q3 | A bricht mit Fulcrum-Disconnect ab | B startet sauber; Log Fehler A; Knopf für A wieder nutzbar |

### 4.6 Clearnet nach Onion-Löschung

| # | Schritte | Erwartung |
|---|----------|-----------|
| C1 | Onion-Liste löschen (Papierkorb), Clearnet-Liste geladen, Opt-in an | Check: clearnet-electrs, **kein** „Öffentliches Ziel blockiert“ trotz Opt-in |
| C2 | Verlaufsscan | Fortschritt; bei Block Allowlist = **sofortige** Fehlerphase, kein endlos Moment noch |

### 4.7 GUI-Stabilität (Quellen + Scan)

| # | Schritte | Erwartung |
|---|----------|-----------|
| G1 | Abbrechen-Knopf rechtsbündig, Textlänge wechselt | Knopf springt nicht |
| G2 | Nach Abbruch UTXO-Knopf | Sofort klickbar (außer echtem laufendem Scan **dieses** Wallets) |
| G3 | DE/EN während Quellen-Check | Labels onion-electrs / clearnet-electrs / Connected |

---

## 5. Automatisierbare Checks (Backlog → Tests)

Priorität für Unit/API-Tests (ohne Mainnet):

| ID | Testidee | Modul |
|----|----------|--------|
| T1 | `bip158_fullscan_ok=false` + UTXOs → `_used_scripts_aus_cache` leer | `bip158_scanner` / `main` |
| T2 | Job-Meta `source` unverändert wenn Env während Job `BIP158_P2P` flippt | `server` Job + mock fetchers |
| T3 | `OEFFENTLICHE_ELECTRUM=1` → `public_opt_in(..., fulcrum)` true | `outbound_policy` |
| T4 | `check_sources` mit p2p_ok räumt public reachable | `core.source` |
| T5 | `schonGeplant` / `jobNochAktiv` nach cancelled | `web` Vertrag / API |
| T6 | Rotation: Timeout auf Client A → Client B | `fulcrum.RotatingFulcrumPool` |
| T7 | Verlauf-Fortschritt enthält `Adresse n/m` und `get_history` | `fulcrum.fetch_wallet_history_fulcrum` mock |

Chaos-Erweiterung (optional): `webgui_chaos_run.py` mit Aktionen „Quelle toggeln“ + „Scan starten/abbrechen“ (noch nicht implementiert — hier spezifizieren).

---

## 6. Kurzprotokoll (~20 min) vor Release

1. Server **frisch** starten, Session attach.  
2. **B1** oder **B2** (eine stabile Quelle, ein Scan durch).  
3. **P1–P4** (P2P-Scan → P2P aus → Electrum-Scan).  
4. **E1–E4** (Electrum-Scan → P2P an → Abbruch → P2P-Scan).  
5. **G1–G2**, **C1** wenn Clearnet relevant.  
6. Console: keine uncaught Errors; Befundtabelle ausfüllen.

---

## 7. Vollprotokoll (~60–90 min)

Kurz + **H1–H3**, **Q1–Q3**, beide Scan-Arten (UTXO + Verlauf), beide Fallbacks (onion-electrs und clearnet-electrs), Privatsphäre-Dialog **S6**, Cache-Dateien zweier Wallets vergleichen.

---

## 8. Befundvorlage

```text
Datum:
VERSION / Git:
Server-Neustart vor Test: ja/nein
Ausgangsquelle:

Szenario | OK/Fail | Notiz (Log-Zeile / Cache-Feld)
---------|---------|--------------------------------
B1       |         |
P2       |         |
P4       |         |
E2       |         |
E4       |         |
H2       |         |
Q2       |         |
C1       |         |
G2       |         |

Blocker / ISSUES.md-Verweis:
Nacharbeit Code (S1–S6 welche offen):
```

---

## 9. Bekannte Stolpersteine (aus Live-Logs)

| Symptom | Deutung | Härtung |
|---------|---------|---------|
| Nur „Moment noch“, „noch 59 von 59“ | Erste Adresse hängt in get_history/Tx über Tor; alter Server ohne Feinfortschritt | Server mit Fortschritts-Patch; Timeout + Rotation |
| Clearnet „blockiert“ trotz öffentlicher Bestätigung | Outbound-Allowlist sah `OEFFENTLICHE_ELECTRUM` nicht | Opt-in koppeln + `.env` an Connect übergeben |
| „öffentliche Peers“ im Log | Verwechslung mit P2P | Labels onion-electrs / clearnet-electrs |
| UTXO-Knopf grau nach Abbruch | Stale Job-Bindung / globaler Tip-Sync | `jobNochAktiv`, Abbruch gibt Knopf frei |
| Turbo greift nicht nach Abbruch | Partial-UTXOs als used | `bip158_fullscan_ok` erst nach Fullscan |
| Core-Onion SOCKS Status 5 | Tor ok, RPC-Onion down | Erwartbar; nicht als SatSage-SOCKS-Bug werten |

---

## 10. Abnahme

**Grün**, wenn:

- Laufende Scans ihre Start-Quelle behalten oder klar abbrechen (kein stiller Mid-Scan-Fetcher-Wechsel).
- P2P ↔ Electrum-Cache-Flags Turbo/Tip nicht verfälschen.
- GUI-Knöpfe und Pillen dem echten Job-/Quellenstand folgen.
- Clearnet nach Opt-in connectbar; Failures als Phase, nicht als endloses „Moment noch“.

**Rot** bei stillem Quellenwechsel mitten im Walk, Cache-Korruption (Tip als fertig nach Partial), oder dauerhaft disabled Scan-Knopf ohne laufenden Job dieses Wallets.
