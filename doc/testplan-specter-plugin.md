# Testplan: SatSage als Specter-Plugin

**Stand:** 2026-09-06 · Umgebung: diese Box / Lab Regtest · Branch: `master-dev-hh-regtest-bot`  
**Zielbild:** Verbindungen (Node/Datenquelle) und Wallets kommen aus Specter; die entsprechenden SatSage-Einstellungsabschnitte sind ausgeblendet bzw. read-only.

SatSage bleibt watch-only (keine Privkeys). Specter liefert Kontext; die Web-GUI läuft eingebettet (`server.py` per iframe).

---

## 1. Ist vs. Soll

| Bereich | Ist (Code) | Soll (dieser Plan) |
|---------|------------|---------------------|
| Wallets | `gui_server._schreibe_specter_env` spiegelt Specter-Wallets nach `specter_plugin/.specter_dev/satsage.env` | **umgesetzt:** DESC bleibt Descriptor, sonst XPUB; Reload bei Fingerprint-Wechsel |
| Node / Verbindung | Specter-Node wird in die Plugin-Env gemappt | **umgesetzt:** Chain → `NETWORK`; Core → BIP-158/P2P + optional RPC, Electrum/Spectrum → Fulcrum-Felder; Datenquellen-Settings ausgeblendet |
| Wallets-UI | `ansicht-wallets` voll editierbar | Im Specter-Modus: Nav/Abschnitt Wallets-Verwaltung ausblenden; Anzeige der übernommenen Wallets read-only (Hinweis „aus Specter“) |
| Auth | Token-URL localhost | unverändert Loopback (Plugin bleibt lokal) |
| UTXO-Seed | `collect_specter_utxos` → Cache `source=specter` | behalten; danach Tip/Verlauf über übernommene Quelle |

**Implementierungs-Voraussetzung für volle Abnahme (Phase A):**

1. Flag/API `betrieb=specter` bzw. `managed_by=specter` in `api_config` (setzt `gui_server` beim Start).
2. Node-Mapping Specter → Env (`NETWORK`/chain, Electrs-Host wenn Spectrum/Electrum, sonst BIP-158 bevorzugt + Hinweis).
3. UI: `ansicht-wallets` + `ansicht-datenquellen` (+ Nav) hidden; optional Mempool-URL behalten.
4. API: `PUT` Wallets/Source im Specter-Modus → 403 mit klarer Meldung.
5. Descriptor-/Multisig-Wallets: Bridge liefert Deskriptor wenn vorhanden (nicht nur XPUB-Extrakt).

Phase A ist umgesetzt. T-CONN und T-HIDE sind mit den Unit- und API-Tests sowie dem manuellen Ablauf zu verifizieren.

---

## 2. Umgebung „hier“ starten

### 2.1 Lab-Chain (Regtest)

Voraussetzung: `/workspace/satsage-lab/` (bitcoind + electrs `:50001`) oder:

```bash
cd /workspace/xPubQuery/specter_plugin
./scripts/run_bitcoind_regtest.sh
# bzw. docker compose -f docker-compose.regtest.yml up -d
```

RPC typisch: `127.0.0.1:18443` / `bitcoin` / `secret` (nur Lab).

### 2.2 Specter + Plugin

```bash
cd /workspace/xPubQuery/specter_plugin
./scripts/setup_dev.sh          # einmalig; Python 3.10 bevorzugt (3.13 ggf. problematisch)
./scripts/run_specter.sh        # http://127.0.0.1:25441
```

1. Login (Dev oft `admin`/`admin`).
2. Node verbinden → Regtest Core.
3. Device + Watch-only-Wallet(s) mit Lab-`vpub`s (z. B. aus Lab Alpha/Beta) oder Hot-Wallet + Coins minen.
4. **Plugins → SatSage** aktivieren.
5. Sidebar → **SatSage → Oberfläche** (iframe GUI).

Offline-Bridge ohne GUI:

```bash
./.venv/bin/python scripts/unit_bridge.py
./.venv/bin/python scripts/probe_api.py
```

**Hinweis Box:** Wenn `cryptoadvance.specter` unter 3.13 scheitert → `PYTHON_BIN=python3.10` in `setup_dev.sh`. GUI-Port SatSage default `8730` (nicht mit Specter `25441` verwechseln).

---

## 3. Testfälle

### T-SETUP — Specter läuft mit Plugin

| Schritt | Erwartung |
|---------|-----------|
| Specter UI erreichbar | 200 auf `:25441` |
| Extension in Liste | SatSage / satsage sichtbar, aktivierbar |
| `/svc/satsage/` | Übersicht ohne 500 |

### T-BRIDGE — Kontext

| Schritt | Erwartung |
|---------|-----------|
| Mind. 1 Wallet in Specter | `build_context` → `wallet_count ≥ 1`, XPUBs nicht leer |
| Node verbunden | `node.host/port/chain` gesetzt (`regtest`) |
| `unit_bridge.py` | exit 0; Secrets in Dump maskiert |

### T-GUI — iframe / Tab

| Schritt | Erwartung |
|---------|-----------|
| Oberfläche öffnen | iframe oder „neuer Tab“ → GUI mit Token-URL auf `127.0.0.1:8730` |
| `satsage.env` | unter `.specter_dev/` mit `WALLET_*` aus Specter |
| Wallet-Nav in GUI | übernommene Namen sichtbar |
| UTXO-Cache | nach Seed `source=specter` oder nach Scan Bestand > 0 |

### T-WALLET-SYNC — Änderung in Specter

| Schritt | Erwartung |
|---------|-----------|
| Zweites Wallet in Specter anlegen, GUI neu öffnen / Reload | zweite Wallet in SatSage ohne manuelles XPUB-Einfügen |
| Wallet in Specter umbenennen | Name nach Reload gespiegelt (Fingerprint-Reload) |

### T-CONN — Verbindung aus Specter (nach Phase A)

| Schritt | Erwartung |
|---------|-----------|
| Specter auf Lab-Core | SatSage nutzt passende Quelle (BIP-158 und/oder Lab-Electrs), nicht Mainnet-Fallback |
| `NETWORK` | `regtest` → Adressen `bcrt1` |
| Eigenen Node testen / Status | zeigt übernommene Quelle; kein manuelles Fulcrum-Pflichtfeld |

### T-HIDE — Settings ausgeblendet (nach Phase A)

| Schritt | Erwartung |
|---------|-----------|
| Nav „Wallets“ (Verwaltung) | ausgeblendet oder nur RO-Liste ohne Hinzufügen/Import |
| Nav „Datenquellen“ | ausgeblendet oder RO + Status |
| Einstellungen (Steuer, LLM, Mail, Sprache) | weiterhin sichtbar (nicht Specter-managed) |
| Direkter `PUT /api/config/wallets` | 403 im Specter-Modus |
| Direkter `PUT /api/config/source` | 403 im Specter-Modus |

### T-SCAN — Funktion

| Schritt | Erwartung |
|---------|-----------|
| Verlauf oder UTXO-Scan einer Specter-Wallet | Treffer auf Regtest; keine stille Mainnet-BIP-158-Verwirrung |
| Mempool-Spend (optional Lab-Harness) | `spending_pending` / `receive_pending` wie Desktop-Fixes |
| Legacy-Tab Analyse (`/svc/satsage/analyze`) | Tx-Trace gegen Session ok oder klarer Fehler |

### T-PRIVACY / NEGATIV

| Schritt | Erwartung |
|---------|-----------|
| Specter-Node = eigener Node | keine erzwungene öffentliche Electrum-Nutzung ohne Bestätigung |
| Repo-`.env` Wallets | werden nicht aus Nutzer-`.env` in Specter-Env übernommen (nur nicht-Wallet-Keys) |
| Token nur localhost | von außen nicht erreichbar |

### T-REGRESS — Desktop unverändert

| Schritt | Erwartung |
|---------|-----------|
| `py server.py` ohne Specter | Wallets/Datenquellen voll editierbar |
| Kein `managed_by=specter` | Hide-Logik inaktiv |

---

## 4. Protokoll-Vorlage

| ID | Datum | Ergebnis (ok/fail/skip) | Notiz |
|----|-------|-------------------------|-------|
| T-SETUP | | | |
| T-BRIDGE | | | |
| T-GUI | | | |
| T-WALLET-SYNC | | | |
| T-CONN | | | Phase A |
| T-HIDE | | | Phase A |
| T-SCAN | | | |
| T-PRIVACY | | | |
| T-REGRESS | | | |

---

## 5. Definition of Done (Plugin-Zielbild)

- [x] Specter-Wallets und -Verbindung sind alleinige Quelle für GUI-Bestand/Datenquelle.
- [x] Entsprechende Einstellungsabschnitte ausgeblendet; API schreibt sie nicht.
- [ ] Regtest-E2E hier: Setup → Oberfläche → Scan ohne manuelle XPUB/Fulcrum-Eingabe.
- [x] Desktop-Loopback-Pfad unverändert nutzbar.
- [x] Kurz in `specter_plugin/README.md` verlinkt.

---

## 6. Referenzen

- `specter_plugin/README.md`
- `specter_plugin/src/satsage/specterext/satsage/{bridge,gui_server,controller,specter_session}.py`
- Lab: `/workspace/satsage-lab/`, `lab/regtest/`
- Specter Extensions: https://github.com/cryptoadvance/specter-desktop/blob/master/docs/extensions/intro.md
