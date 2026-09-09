# Offene Punkte

Bekannte LÃ¼cken, noch ohne LÃ¶sung. Neueste oben.

## Immutable-Cache · SQLite statt Winz-JSONs (tx / utxo_ingress)

**Stand:** 2026-09-09 · **zurückgestellt** — erst **nach** Implementation der CoinJoin-Verfolgung (siehe Ideensammlung unten)

### Entscheidungsgrundlage (nicht vorab bauen)

Punktzugriff per TxID / `(txid, vout)` ist mit Flatfiles schon O(1). SQLite lohnt wegen Syscall-/AV-/Glob-Kosten, nicht wegen Lookup-Komplexität.

| Dateien in `tx/` **oder** `utxo_ingress/` | Haltung |
|------------------------------------------|---------|
| < ~1 000 | Flatfiles behalten |
| ~2 000–5 000 | Grauzone — messen (Walk-Zeit, Windows); SQLite wenn Batch-Walks/Reports stocken |
| ≥ ~10 000 | SQLite sinnvoll bis geboten |

**Wachstumstreiber:** Herkunft in der Breite (viele UTXOs → `utxo_ingress/`) und/oder Tiefe/Breite des Graphen (viele `get_tx` → `tx/`), v. a. „Herkunft vollständig“, hohe `max_hops`, aufgelöste große Sammel-/CoinJoin-Txs. Reiner UTXO-/Specter-Seed füllt diese Ordner nicht.

**Scope später:** nur `immutable_cache/tx` + `utxo_ingress` (zwei Tabellen, PK); XPUB-UTXO/Verlauf-JSON bleiben. Optional lazy Migration / Schwellwert-Opt-in. Windows/StartOS + Antivirus stärker betroffen als warmer Linux-Page-Cache.

**Laufzeit-Hinweis:** Ab ≥10 000 JSON-Dateien in `tx/` oder `utxo_ingress/` schreibt SatSage einmalig ins Log: *Cache wächst — sqlite ab jetzt sinnvoll* (+ Bitte um GitHub-Issue). Zählung nur alle 500 Writes, damit das Zählen selbst nicht teuer wird.

**Abgrenzung:** Kein Drive-by vor CoinJoin-Hybrid-Walk — CJ-Auflösung treibt `tx/` voraussichtlich erst richtig in die Tausender.

---

## Start9 · Fulcrum als Electrum-Datenquelle (neben electrs)

**Stand:** 2026-09-09 · **in Arbeit (Vorbereitung)** · Bezug: [`doc/START9-fulcrum-indexer.md`](doc/START9-fulcrum-indexer.md), [`doc/START9-packaging.md`](doc/START9-packaging.md)

Der Start9-Build-/Package-Prozess soll **Fulcrum** können, nicht nur `electrs-startos`.

**Soll:**

- In der **StartOS-GUI auswählbar** (Action **Select Indexer**), analog Mempool — Fulcrum oder Electrs.
- Manifest: beide Deps optional; zur Laufzeit genau eine aktiv.
- Bridge-Env → `FULCRUM_*` + `SATSAGE_ELECTRUM_INDEXER`; SatSage-UI bleibt für Bridge-Quellen read-only.

**Erledigt in Vorbereitung (ohne `.s9pk`-Bau):** Design-Doku; Packaging (`store.indexer`, `selectIndexer`, conditional deps, Bridge electrs/`electrum` oder fulcrum/`main`); App-`managed_hint` / `electrum_indexer`; Unit-Tests.

**Offen bis Sideload:** `npm ci` + `./scripts/build_startos_s9pk` auf Build-Host; Geräte-Test Fulcrum-Wahl; optional Task „Indexer wählen“ erzwingen; Auto-Detect nur als spätere Stufe.

---

## Specter-Plugin · Node & Wallets aus Specter übernehmen (read-only)

**Stand:** 2026-09-09 · **umgesetzt (Kern + Cache-Seed)** · manuelle Abnahme in Specter-UI noch offen

Das Specter-Plugin übernimmt **Node-Connections** und **Wallets** aus Specter (Bridge/Session), ohne Doppelpflege in SatSage.

**Soll / Ist:**

- Specter-Node (Core → BIP-158/RPC, Electrum/Spectrum → `FULCRUM_*`) und Wallets/XPUBs/Deskriptoren → Plugin-`.env` (`managed_by=specter`); UI/API Wallets + Datenquellen gesperrt/ausgeblendet.
- **UTXO-Seed** aus `full_utxo` → `utxo_cache` (`source=specter`), Scan-Fenster aus Specter-Indizes (`address_index` / `change_index`).
- **Verlaufs-Merge** aus Specter-UTXOs + Receive-Txs → `merke_bip158_verlauf`.
- **Labels** → `utxo_cache/specter_address_labels.json`, API `specter_labels` / UTXO-Feld `label`.
- Änderungen in Specter: Fingerprint-Reload + erneuter Seed.

**Modul:** `specter_plugin/.../specter_seed.py`. Tests: `tests/test_specter_seed.py`.

**Abgrenzung:** Standalone-`server.py` / Lab bleiben editierbar. PSBT/Devices/Explorer-URL aus Specter = Folge-Issues.

---

## Start9 Community Package â€” HÃ¤rtung

**Stand:** 2026-09-06 Â· **Backlog aktiv, Umsetzung schrittweise**

- Analyse & Soll-Modell: [`doc/START9-hardening.md`](doc/START9-hardening.md)
- Tickets/Phasen: [`doc/START9-backlog.md`](doc/START9-backlog.md)
- Specter-Plugin-Testplan (paralleler Distributionsweg): [`doc/testplan-specter-plugin.md`](doc/testplan-specter-plugin.md)

Kurz: Loopback+Token-URL reichen nicht fÃ¼r LAN/Tor hinter StartOS. S0â€“S3 sind im Code; der Wrapper liegt in **`packaging/`** (Branch `main`). Bauen/Sideload/Release: [`doc/START9-packaging.md`](doc/START9-packaging.md). **S4-6** (GerÃ¤te-E2E mit Release 0.9) erledigt; **Community-Einreichung (S4-7)** bleibt offen.

---

## Ideensammlung: Was trennt SatSage von einer echten Wallet-Software?

**Stand:** 2026-09-04 Â· **nur notiert, noch nicht umsetzen**  
**Ort:** Analyse-Stack vs. Key-Material; experimentell schon `consolidate.py` (PSBT); Web/CLI

### Was SatSage heute ist

- **Beobachter/Analyst:** XPUBs/Deskriptoren, UTXO/Verlauf/Herkunft, Steuer, Sanktionen, Labels.
- **Keine privaten SchlÃ¼ssel** â€” und das soll so bleiben (PrivatsphÃ¤re, AngriffsflÃ¤che, Cold-Storage-KompatibilitÃ¤t).
- Specter/Sparrow liefern Keys und kÃ¶nnen signieren; SatSage hÃ¤ngt sich an den Daten-Stack.

### Was eine â€žechte Walletâ€œ typischerweise kann (LÃ¼cken)

| FÃ¤higkeit | SatSage heute | Gap |
|-----------|---------------|-----|
| Adressen ableiten / Bestand sehen | ja | â€” |
| Empfangen (Adresse anzeigen) | indirekt (abgeleitet) | UI â€žEmpfangenâ€œ optional trivial |
| Senden planen (Coin-Auswahl, Fee, Change) | nur Dust-Konsolidierung experimentell | allgemeine Send-UI fehlt |
| **PSBT erzeugen** (unsigned) | ja, eng: `consolidate.build_consolidation_psbt` | generalisieren, Web-Export |
| Signieren | nein (kein Privkey) | **extern** (Sparrow, Electrum, Coldcard, Specter) |
| Broadcast signierter Tx | nein | Electrum/`blockchain.transaction.broadcast` oder Core `sendrawtransaction` |
| Seed/HW verwalten | nein | bewusst out of scope |
| Multisig-Policy / PSBT cosign | Deskriptor lesen ja | runder Cosign-Flow fehlt |

**Fazit:** Der grÃ¶ÃŸte Sprung zur â€žWallet, die etwas ausgeben kannâ€œ ist nicht Kryptographie im engen Sinne, sondern ein **sauberer PSBT-Lebenszyklus**: bauen â†’ exportieren â†’ fremd signieren â†’ finalisieren â†’ broadcasten â€” ohne je den Seed anzufassen.

### PSBT erzeugen und woanders signieren lassen

**Schon da (CLI/experimentell):** `consolidate.py` baut mit `embit` ein **unsigniertes** PSBT (Dust â†’ eigene Adresse), inkl. BIP32-Derivation-Pfade fÃ¼r Inputs/Change-Ã¤hnlich. Ausgabe unter `psbt_out/`.

**Machbar / sinnvoll:**

1. **Export** Base64/Datei (BIP-174), QR optional spÃ¤ter.  
2. **Signieren:**
   - **Sparrow / Electrum / Specter:** PSBT laden, HW oder Software-Wallet signiert, PSBT zurÃ¼ck.  
   - **Coldcard:** PSBT auf SD / USB / QR (je Modell); GerÃ¤t signiert **on-device**; signed PSBT zurÃ¼ck nach SatSage. Kein Seed in SatSage.  
3. **Import** signed/partially-signed PSBT â†’ `embit` finalisieren (`extract_tx` / combine).  
4. Multisig: mehrere Runden combine â€” Architektur schon PSBT-nativ, UI-Aufwand.

**KomplexitÃ¤t erzeugen:** mittel, wenn auf `embit` und bestehenden UTXO-Cache aufgebaut wird (Coin-Control, Fee-SchÃ¤tzung, Change-Index, RBF-Flag). Dust-Pfad ist der Prototyp. Web-GUI + allgemeine â€žSendenâ€œ-Maske ist der grÃ¶ÃŸere Brocken als die PSBT-Bytes.

### Broadcast einer signierten PSBT â€” wie kompliziert?

**Fachlich einfach**, sobald die **finalisierte Raw-Tx** (hex) da ist:

| Backend | Typischer Call | Aufwand |
|---------|----------------|---------|
| Electrum/Fulcrum | `blockchain.transaction.broadcast` (hex) | gering â€” Client/Protokoll schon im Stack |
| Bitcoin Core RPC | `sendrawtransaction` | gering, wenn RPC schon konfiguriert |
| Ã–ffentliche Explorer-APIs | HTTP POST | mÃ¶glich, **schlechte PrivatsphÃ¤re** (Tx an Dritte) |

**Schritte:** signed PSBT einlesen â†’ prÃ¼fen (vollstÃ¤ndig signiert? BetrÃ¤ge/Fees plausibel?) â†’ `tx.serialize().hex()` â†’ broadcast â†’ txid anzeigen â†’ optional Mempool-Link.

**Fallstricke (nicht die RPC-Zeile, sondern Produkt):**

- Nur **vollstÃ¤ndig** signierte PSBTs broadcasten (partial â†’ ablehnen mit klarer Meldung).  
- Kein stilles Re-Broadcast ohne User-BestÃ¤tigung.  
- Fee/RBF/Replace: Nutzer muss verstehen, was gesendet wird.  
- Bei eigenem Node: Policy (min relay fee, datacarrier) kann rejecten â€” Fehlertext durchreichen.  
- Nach Broadcast: lokalen UTXO-Cache invalidieren / Rescan anbieten (sonst â€žGeister-UTXOsâ€œ).

**Grobe AufwandsschÃ¤tzung (nur Orientierung):**

| Baustein | Aufwand |
|----------|---------|
| PSBT-Import + Finalisierung + PlausibilitÃ¤tscheck | kleinâ€“mittel |
| Broadcast Ã¼ber bestehenden Electrum-/Core-Pfad | **klein** |
| Coldcard/Sparrow-Export-Import-UI | mittel |
| Allgemeine Send-UI (Zieladresse, Coin-Control, Fee) | **grÃ¶ÃŸer** als Broadcast allein |
| Multisig-Cosign-Runden in der GUI | mittelâ€“groÃŸ |

### Empfehlung (wenn wirâ€™s angehen)

1. **Phase A â€” â€žWatch-only Senderâ€œ:** PSBT bauen (erst Konsolidierung/Web, dann freies Senden) â†’ Datei/Base64 â†’ **kein** Signieren in SatSage.  
2. **Phase B â€” â€žSignatur zurÃ¼ckâ€œ:** signed PSBT importieren, finalisieren, **broadcast nur Ã¼ber eigenen Node/Electrs** (Default), Clearnet-Broadcast nur Opt-in.  
3. **Phase C â€” HW-Komfort:** Coldcard-Dateinamen/QR, Sparrow-Deep-Links; Multisig spÃ¤ter.

**Nicht-Ziel:** Seed-Verwaltung, Hot-Wallet, eingebetteter Signer â€” das wÃ¼rde das Bedrohungsmodell und den Produktcharakter (Analyse + Steuer) verwÃ¤ssern.

**Wenn wir wieder drankommen:** API `POST /psbt` (build) / `POST /psbt/finalize` / `POST /tx/broadcast`; Web-Karten â€žPSBT exportieren / importieren / sendenâ€œ; Tests mit Fixtures ohne Mainnet-Broadcast; Cache-Invalidierung nach send.

## Erledigt: Englisch umschaltbare Web-GUI

**Stand:** 2026-09-02 Â· **erledigt** (Phase 0â€“3)  
**Ort:** `web/` (`index.html`, `app.js`, `i18n.js` + `locales/`), `server.py` / `.env` (`UI_LANG`); Specter-iframe profitiert mit

Ziel: Web-OberflÃ¤che zwischen **Deutsch** und **Englisch** umschalten. Ãœbersetzungen aus ProduktverstÃ¤ndnis (Steuer/On-Chain/PrivatsphÃ¤re), nicht WÃ¶rterbuch-Durchlauf des Handbuchs.

### Scope (bestÃ¤tigt)

- Client: statisches HTML-Chrome + dynamische JS-UI (Labels, Dialoge, LeerzustÃ¤nde, Confirms, Tooltips, Chat-Hilfe)
- Persistenz: **`localStorage`** sofort + optional **`UI_LANG` in `.env`**
- **Nicht** in dieser Reihe: vollstÃ¤ndige Job-Logs / alle `ApiError`-Texte / CLI / komplettes Handbuch

Phase 1â€“3 bewusst gemischtsprachig ok: Rahmen EN, Scan-Log und viele API-Fehler noch DE â€” in EN-UI kurz erklÃ¤ren (â€žTechnical log may still be Germanâ€œ).

### Ausgangslage

| Fakt | Konsequenz |
|------|------------|
| Kein Build, kein Framework | JSON-Catalogs + kleines `i18n.js` |
| ~180â€“250 Phrasen HTML, ~300â€“450 in `app.js` | Mehrere Schritte, kein Big-Bang |
| `toLocaleString("de-DE")` ~30Ã— | Anzeige-Locale an Sprachwahl |
| `logIstWichtig` matched DE-Log-PrÃ¤fixe | Backend-Logs vorerst DE; Regex unverÃ¤ndert |
| Slash kanonisch DE (`/hilfe`) | Hilfe Ã¼bersetzen; Canonical intern; EN-Aliasse |
| Specter iframe = dieselbe GUI | Automatisch dabei |
| Handbuch nur FuÃŸzeilen-Link | Hinweis â€ž(DE)â€œ; VollÃ¼bersetzung spÃ¤ter |

### Ãœbersetzungsprinzipien

1. Produktbedeutung vor WÃ¶rterbuch (â€žHaltedauerâ€œ â†’ holding period; â€žHerkunft tracenâ€œ â†’ Trace origin).
2. Fachbegriffe behalten: UTXO, sats, XPUB, BIP-158, Electrum, Fulcrum, PSBT, Coinbase (mining).
3. Recht/Steuer nicht glÃ¤tten (On-Chain-Disclaimer, Haltefrist/Stichtag DE/AT-Kontext).
4. Marke unverÃ¤ndert: â€žSatSage â€“ know your satsâ€œ.
5. KnÃ¶pfe kurz; LÃ¤nge in Tooltips/Dialogen.
6. CSV-Export bleibt DE-konventionell (Semikolon) â€” UI-Hinweis in EN, Format nicht an `UI_LANG`.
7. `de.json` kanonisch; `en.json` parallel; fehlende EN-Keys fallen auf DE zurÃ¼ck.

### Architektur / Lektorat

```
web/
  i18n.js
  locales/de.json   â† menschliches Lektorat DE
  locales/en.json   â† menschliches Lektorat EN
  index.html        # data-i18n*
  app.js            # t("key")
```

Nach Umsetzung: nur **Werte** in den JSON-Dateien anpassen (Keys stabil). Nicht Englisch in HTML/JS nachpflegen. Keys nach PrÃ¤fix gruppiert (`nav.*`, `settings.*`, `wallet.*`, â€¦). Platzhalter `{name}` / `{n}` beim Editieren behalten.

Laden: `localStorage["satsage-ui-lang"]` â†’ sonst `config.ui_lang` â†’ sonst `de`. `fetch("/locales/{lang}.json")`. Einstellungen-Karte â€žSpracheâ€œ ganz oben; Select sofort + optional `PUT /api/config/ui-lang`.

### Phasen

**Phase 0 â€” GerÃ¼st** (~1â€“2 Tage): `i18n.js`, Kern-Keys, Sprach-Karte, `UI_LANG`, Format-Locale; Rest darf noch DE sein.

**Phase 1 â€” Statisches Chrome** (~3â€“5 Tage): ganzes `index.html` inkl. Dialoge, Nav, Ansichten, Dock, FuÃŸ; Browser DE/EN.

**Phase 2 â€” Dynamische UI** (~4â€“6 Tage): `app.js`-sichtbare Strings, Confirms, Chat-Hilfe/Aliasse, clientgeschriebene Log-Zeilen; `logIstWichtig` unverÃ¤ndert.

**Phase 3 â€” Politur** (~1â€“2 Tage): Log-Hinweis gemischtsprachig, README, Key-ParitÃ¤ts-Test, Specter-iframe kurz, Changelog.

**SpÃ¤ter (Merkliste):** `ApiError`/`error_code`; Job-Logs EN; Handbuch EN; CLI; weitere Sprachen.

### Erfolgskriterium

Umschalter in Einstellungen; sichtbare Web-GUI DE/EN; Datums-/Zahlenformat folgt Sprache; Job-Log/API-Fehler dÃ¼rfen noch DE sein; kein Build-Schritt.

**Umgesetzt:** `i18n.js` + `locales/{de,en}.json` (~423 Keys), Sprache-Karte, `UI_LANG`, Format-Locale, HTML `data-i18n*`, dynamische `t()` in `app.js`, `/help`-Alias, ParitÃ¤ts-Test. Job-Logs/`ApiError`/Handbuch/CLI bewusst noch DE.

**SpÃ¤ter (Merkliste):** `ApiError`/`error_code`; Job-Logs EN; Handbuch EN; CLI; weitere `app.js`-Nebenstrings; weitere Sprachen.

## Ideensammlung: Besitz-Signatur pro Wallet fÃ¼r Reports

**Stand:** 2026-08-31 Â· **nur notiert, noch nicht umsetzen**  
**Ort:** Steuer-/Verlaufs-Export (`core/tax.py`, ggf. Selbstanzeige), Web-UI, Cache; Signatur extern (Sparrow/Electrum)

Ziel: stÃ¤rkerer **Eigentums-/Besitznachweis** am Report â€” mindestens **eine Signatur pro Wallet**. Beweisziel: **Kontrolle der privaten SchlÃ¼ssel** zum XPUB/Deskriptor.

### Angriffsmodell

Nur eine gecachte Besitz-Attestierung (â€žich kontrolliere Adresse #0 zu diesem XPUBâ€œ) lÃ¤sst sich vom konkreten Report **lÃ¶sen**: XPUB + Signatur im Freundeskreis weiterreichen und unter beliebige Aufstellungen kleben. Deshalb **zwei Ebenen**:

| Ebene | Was | Wann | Cachebar? |
|-------|-----|------|-----------|
| **A Â· Besitz-Attestierung** | Message-Signatur Ã¼ber kanonischen Challenge (Fingerprint, Adresse #0) | einmalig pro Wallet | **ja** |
| **B Â· Report-Bindung** | Message-Signatur Ã¼ber Text inkl. **SHA-256 der kanonischen Report-Payload** | je Export â€žgebundenâ€œ | **nein** |

â€žWirklich 100â€¯%â€œ fÃ¼r *diesen* Report: **A und B**. Alltag: nur A + unsignierte PrÃ¼fsumme mÃ¶glich â€” klar als schwÃ¤cher kennzeichnen.

### Was signiert wird

**A â€” Besitz (Adresse #0, Electrum-/BIP-137-Message):** Challenge mit SatSage-Kennung, Wallet-Fingerprint, Schema-Version, Datum, Zwecktext. Beweist SchlÃ¼ssel zu #0 (+ Ableitung Ã¼ber XPUB).

**B â€” Report-Bindung (optional):** Nach Entwurf `report_hash = SHA-256(kanonische Payload)`; Challenge enthÃ¤lt Hash + Fingerprint + Exportzeit; dieselbe Adresse #0 signiert erneut. Beweist: SchlÃ¼sselkontrolle bestÃ¤tigt **diesen** Inhalt.

Nicht die Browser-PDF als Rohbytes (Layout drift) â€” signiert wird die SatSage-Payload; der sichtbare Bericht zeigt Hash + Signaturen. On-Chain-Hinweis / Anschaffungsbelege bleiben unberÃ¼hrt.

### Wo im Report

Abschnitt **â€žBesitznachweisâ€œ** (HTML + CSV), je Wallet: Block A (Adresse, Datum, Signatur, Status); optional Block B (`report_hash`, Signatur B, â€žan diesen Export gebundenâ€œ). Ohne B: Warnung â€žReport nicht schlÃ¼sselgebunden â€” weiterreichbarâ€œ.

### Cache

Nur **A** z.â€¯B. in `utxo_cache/{hash}_besitz.json` (fingerprint, address, message, signature, format, verified_at). ReportlÃ¤ufe mit nur A ohne erneutes Signieren; bei A+B wird A aus dem Cache genommen, **B jedes Mal neu**. B nicht cachen.

### Tooling

**Sparrow** empfohlen (Tools â†’ Sign/Verify Message / Rechtsklick Adresse; HW; SegWit/Taproot). **Electrum** Alternative. HW Ã¼ber Sparrow/Electrum. SatSage ohne Privkeys: Challenge â†’ extern signieren â†’ einfÃ¼gen â†’ verifizieren. Multisig/BIP-322: Phase 2.

### Userflow

1. Export: Modus â€žnur Besitz (A)â€œ oder â€žBesitz + Report gebunden (A+B)â€œ.  
2. Pro Wallet: fehlt A â†’ Dialog (Adresse #0, Challenge, Sparrow/Electrum-Hinweis, Signatur, Verify, Cache).  
3. Report-Entwurf + `report_hash`.  
4. Nur A â†’ ausgeben (A + Hash, Warnhinweis).  
5. A+B â†’ pro Wallet Challenge B signieren â†’ finaler Report mit A + B + Hash.

```
Export â†’ A fehlt? â†’ Dialog A â†’ Cache
      â†’ Hash berechnen
      â†’ Modus A+B? â†’ Dialog B (Hash) â†’ Report mit A+B
                 sonst â†’ Report mit A (+ Warnung)
```

**Wenn wir wieder drankommen:** Challenge-/Hash-Schema festlegen; Verify in SatSage; UI-Dialoge + Cache; HTML/CSV-Abschnitt; Multisig/BIP-322 spÃ¤ter.

## Ideensammlung: CoinJoins rÃ¼ckverfolgen kÃ¶nnen

**Stand:** 2026-09-02 Â· **nur notiert, noch nicht umsetzen** (Hybrid-Walk fÃ¼r Wasabi skizziert)  
**Danach:** Immutable-Cache SQLite (tx/ingress) — Entscheidungsgrundlage siehe Issue oben; nicht parallel vorziehen.
**Ort:** Herkunftsanalyse (`trace_engine.py`, `analyze.py`, Web-Herkunft / CLI), Einstellungen, Steuerbericht; abhÃ¤ngig von â€žServer bleibt nach Browser-SchlieÃŸungâ€œ und Status-Mails
### Ist-Zustand

Bei Sammel-Txs mit mehr als 20 EingÃ¤ngen bricht die Engine nach dem ersten eigenen Input ab (`FULL_RESOLUTION_INPUT_LIMIT`); der Rest erscheint als â€žn EingÃ¤nge gebÃ¼ndeltâ€œ. Das trifft typische Wasabi-/WabiSabi-CoinJoins.

| Muster | vs. 20er-Limit | Anschaffungsdatum |
|--------|----------------|-------------------|
| Wasabi / WabiSabi (oft â‰«20 Inputs) | bricht ab â†’ gebÃ¼ndelt | unvollstÃ¤ndig / Untergrenze |
| Whirlpool (typisch 5Ã—5) | unter Limit, schon voll aufgelÃ¶st | Peer-Inputs dÃ¼rfen trotzdem **kein** Datum liefern (nur eigene Zweige; Fremde = Rauschen) |
| JoinMarket (oft kleinâ€“mittel) | meist unter Limit | wie CoinJoin: nur eigene Zweige |
| Payjoin (typisch 2â€“wenige Inputs) | **bricht nicht** am Limit | kein Mix â€” fremder Input = Gegenstelle, nicht Peer-Rauschen |

Verwandt mit â€žGrÃ¼ndlichere Herkunft in der Web-GUIâ€œ.

### Umsetzungsstrategie (Reihenfolge)

**1. Einstellung: Behandlung von CoinJoins**

Benutzer regelt in den Einstellungen (Web + `.env`), was bei erkannten CoinJoins passiert. Cache vermerkt Typ (`samourai` / `wasabi`, spÃ¤ter ggf. `joinmarket`):

| Option | Verhalten |
|--------|-----------|
| A â€” Scan stoppt am CoinJoin | Herkunft endet am Mix; Cache: â€žCoinJoin erkannt (Samourai\|Wasabi\|â€¦)â€œ; kein Weiterlaufen durch den Mix |
| B â€” Nur Wasabi stoppt | Whirlpool/Samourai wird aufgelÃ¶st; Wasabi bleibt Markierung + Abbruch |
| C â€” Beide auflÃ¶sen | Wasabi und Samourai werden durchverfolgt (langsamste Variante) |

Erkennung vor dem teuren Walk; Abgrenzung zur normalen Sammel-/Konsolidierungs-Tx (dort bleiben unaufgelÃ¶ste eigene Inputs eine echte Untergrenze).

**Payjoin gehÃ¶rt nicht in diese Einstellung** (siehe unten).

**2. Whirlpool-Scan (Samourai / Nachfolger z.â€¯B. Ashigaru)**

- Heuristik: starres Muster (typisch 5 In / 5 Out, gleiche Pool-Denomination; Tx0 separat).  
- n Remix-Runden erkennen und nach MÃ¶glichkeit **kumuliert** darstellen (eine Kette â€žWhirlpool Ã— nâ€œ, nicht n EinzelbÃ¤ume in der UI).  
- Im **Steuerbericht** die Kette auflÃ¶sen: Anschaffungsdatum Ã¼ber eigene Zweige durchreichen; Peer-Inputs als Rauschen, nicht als externer Zufluss.  
- Eigene Inputs bevorzugt Ã¼ber Verlauf/`spent_txid`-Index finden, nicht alle Prevouts laden.

**3. Wasabi-/WabiSabi-Scan**

- GroÃŸe n:m-Txs; nur eigene Inputs/Outputs weiterverfolgen, Rest verwerfen (kein Blind-AuflÃ¶sen aller `vin`s).  
- Erfordert Geduld (viele Abrufe Ã¼ber Remix-Historie). Praktisch erst sinnvoll mit Hintergrundbetrieb: Issue â€žServer bleibt nach Browser-SchlieÃŸungâ€œ + Status-Mails (neutrale Fertigmeldung).  
- Einstellung C (oder B nur fÃ¼r den Wasabi-Zweig) steuert, ob Ã¼berhaupt durchgelaufen wird.

#### LÃ¶sungsskizze: Hybrid-Walk (bei Implementation hier ansetzen)

RÃ¼ckwÃ¤rts in eine erkannte n:m-CoinJoin-Tx `C`. Semantik: CoinJoin ist **kein** externer Zufluss; Anschaffungsdatum nur Ã¼ber **eigene** Vorfahren. Fremde Inputs = Rauschen, nie auflÃ¶sen.

**Auswahlregel = Eigentum, nicht Betrag.** Betragsgleichheit Outputâ†”Inputs ist hÃ¶chstens Priorisierung (WabiSabi zerlegt/rekombiniert; Fees; mehrere eigene Ins/Outs). Weiterverfolgt werden **alle** eigenen Inputs von `C`.

| Stufe | Wann | Vorgehen | Kosten |
|-------|------|----------|--------|
| **1 Â· Index** | Verlauf/`spent_txid` brauchbar | `eigene_inputs(C) = { Outpoints aus Verlauf \| spent_txid == C }` â€” kein Prevout-Resolve | billig (Cache) |
| **2 Â· LÃ¼cke** | Verlauf `incomplete`, fehlende `spent_txid`, unsicherer `max_index`/Gap | Ein `get_tx(C)` (alle `vin`s, billig). Dann Outpointâˆ©bekannte eigenen Outpoints und/oder Adressraumâˆ©Vin-Adressen (Receive+Change, alle Script-Typen, Superset bis weit Ã¼ber hÃ¶chstem Index, groÃŸes Gap). Prevouts **nur** fÃ¼r Treffer bzw. fehlende Adressen nachladen â€” nie blind alle Fremden | teuer/zeitaufwÃ¤ndig, **korrekt** wenn Wallets/Deskriptoren stimmen und der Adressraum reicht |

**Deckung:** Stufe 1 und â€žAdressraum âˆ© Vinsâ€œ sind dieselbe Aussage, sobald Cache und Adressraum vollstÃ¤ndig sind. LÃ¼cken werden erkannt â†’ bewusst Stufe 2, nicht raten.

**Nicht verwechseln:** `FULL_RESOLUTION_INPUT_LIMIT` / â€žgebÃ¼ndeltâ€œ bleibt fÃ¼r **normale** Sammel-/Konsolidierungs-Txs (ohne CJ-Erkennung); dort sind unaufgelÃ¶ste eigene Inputs echte Untergrenze. Beim CJ-Hybrid entfÃ¤llt Blind-Resolve der Fremden.

**Voraussetzungen fÃ¼r â€žkorrektâ€œ:** alle relevanten XPUBs/Deskriptoren konfiguriert; Scan/Gap deckt Mix-Adressen; bei Stufe 2 Eigentums-Schnittmenge statt Betragsfilter. Remix-Ketten bleiben lang â†’ Hintergrundjob/Mails bleiben Voraussetzung; der Hybrid macht den **einzelnen Hop** billig bzw. die Teuerkeit an erkannte LÃ¼cken gebunden.

**4. JoinMarket (spÃ¤ter, echte CoinJoin-Variante)**

- P2P Maker/Taker, **kein** zentraler Coordinator; Taker wÃ¤hlt den gleichen Output-Betrag.  
- On-chain: N+1 **gleiche** CJ-Outputs + meist je Teilnehmer ein Change (auÃŸer Sweep). Kein festes 5Ã—5, keine Pool-Liste â†’ Erkennung **locker**, False Positives mÃ¶glich (normale Tx mit gleichen BetrÃ¤gen). Detektoren prÃ¼fen oft erst Whirlpool/Wasabi, JoinMarket als Fallback.  
- Mit XPUB: eigene Inputs + typisch ein CJ-Out + ggf. eigenes Change; Fremde = Rauschen (gleiche Semantik wie Whirlpool). Change historisch leichter an eigene Inputs koppelbar als der gleiche CJ-Out.  
- Tx-GrÃ¶ÃŸe oft unter dem 20er-Limit â†’ teurer Wasabi-Walk selten nÃ¶tig.  
- In die CoinJoin-Einstellung aufnehmen (stoppen vs. nur eigene Zweige), PrioritÃ¤t hinter Whirlpool/Wasabi; eigene Heuristik, Cache-Typ `joinmarket`.

**5. Payjoin (BIP78 / BIP77) â€” bewusst ausklammern**

- **Kein** CoinJoin / keine AnonymitÃ¤tsmenge: kollaborative **Zahlung**, Sender und EmpfÃ¤nger legen Inputs in eine Tx (bricht Common-Input-Ownership fÃ¼r Kettenanalyse).  
- On-chain absichtlich wie normale Multi-Input-Zahlung â†’ **keine zuverlÃ¤ssige** Erkennungsheuristik; nicht in CJ-Stop-/AuflÃ¶s-Optionen stecken (Fehlalarme).  
- Typisch 2â€“wenige Inputs â†’ **trifft die 20er-Grenze nicht**; Engine lÃ¶st schon vollstÃ¤ndig auf.  
- Mit XPUB: fremder Input = Gegenstelle. Sender: Abgang (+ ggf. Change). EmpfÃ¤nger: Nettozufluss bei ggf. mitgegebenem eigenem UTXO â€” eher Empfang/Recycling als Remix.  
- BerÃ¼hrt eher bestehende Logik â€žfremde Inputs / mehr zurÃ¼ck als eingesetztâ€œ (`tax.py`), nicht â€žScan am Mix abbrechenâ€œ oder â€žn Runden kumulierenâ€œ. SpÃ¤testens weicher Hinweis, keine automatische CJ-Klassifikation.

**Wenn wir wieder drankommen:** zuerst Einstellungs-Enum + Cache-Felder + Erkennung Whirlpool; dann kumulierter Whirlpool-Pfad inkl. SteuerauflÃ¶sung; danach Wasabi Ã¼ber **Hybrid-Walk** (Stufe Index â†’ LÃ¼cke) an Hintergrund-Jobs/Mails koppeln; JoinMarket als Phase 4 (Heuristik + gleiche Semantik); Payjoin nicht als CoinJoin fÃ¼hren.

## Erledigt: Logo einbinden

**Stand:** 2026-08-29 Â· **erledigt**  
**Ort:** `web/img/` (Favicon, Marke, Wortmarke), Specter-Plugin `static/â€¦/logo.png`, mit `web/` im Packaging

Eulen-Logo eingebunden: Favicon/`apple-touch-icon`, Kopfzeile (`logo-mark.png` + Name/Slogan), volles Wortmark-Logo fÃ¼rs Handbuch. Quelldatei: `SatSage final.jpg` im Repo-Root.

## Erledigt: Server bleibt nach Browser-SchlieÃŸung â€” Terminal-Steuerung

**Stand:** 2026-08-29 Â· **erledigt (v1)**  
**Ort:** `core/terminal_steuerung.py`, `server.main_cli`, Job-Log-Spiegel in `core/jobs.py`

Browser schlieÃŸen hat den Server schon zuvor nicht beendet; jetzt gibt es eine **Terminal-Steuerung** (ANSI): Status Â· Browser-GUI Ã¶ffnen Â· Server beenden. Job-Log-Zeilen (wie im Web-Log) werden nach stdout gespiegelt. Flag `--plain-console` fÃ¼r Automation/non-TTY. Onefile: Konsole offen lassen.

Weiter offen / verwandt: **Status-Mails**; curses-Scroll-Pane optional spÃ¤ter; Specter-iframe unverÃ¤ndert.

## Erledigt: Umbenennung in â€žSatSage â€“ know your satsâ€œ

**Stand:** 2026-08-29 Â· **erledigt (Branding + technische IDs)**  
**Ort:** Anzeige, Docs, Packaging, Specter-Plugin

Branding und technische IDs: Extension/Package `satsage.specterext.satsage`, Binary `satsage-webgui`, Token-Header `X-Satsage-Token`, Specter-Env `satsage.env`, Config-Keys `SATSAGE_*`.

## Erledigt: Popup bei neuem XPUB â€” Scan-Wahl + Hinweis Hintergrundbetrieb

**Stand:** 2026-08-29 Â· **erledigt**  
**Ort:** `web/index.html` (`#wallet-scan-wahl`), `web/app.js` (`frageWalletScanWahl` / Hook in `speichereWallets`)

Nach Speichern eines neuen Wallets: Dialog UTXO-Scan (Standard) / Verlaufsscan / SpÃ¤ter manuell. Scan Ã¼ber `starteScanFuer`; Hinweis auf Terminal-Hintergrundbetrieb. Status-Mails weiter offen (kein Hinweis â€žMail kommtâ€œ, solange SMTP fehlt).

## Erledigt: Status-Mails (neutrale Fertigmeldungen)

**Stand:** 2026-08-29 Â· **erledigt (v1)**  
**Ort:** `core/status_mail.py`, Hook in `core/jobs.py`, `PUT /api/config/status-mail`, Einstellungen-Karte

SMTP aus `.env` / Web (Opt-in). Bei Job-Ende `rescan` / `verlauf`: Mail nur mit Ereignis, Status, Zeit â€” keine Wallet-/Scan-Daten. Weitere Job-Arten und API-Provider spÃ¤ter.

## Erledigt: PrioritÃ¤tsreihenfolge fÃ¼r den Verlaufsscan

**Stand:** 2026-08-29 Â· **erledigt**  
**Ort:** `main._try_verlauf_priority_chain` / `_setup_verlauf_client`, `server.api_verlauf`, Tests `tests/test_verlauf_prioritaet.py`

Eigene Kette (nicht UTXO-/Auto-PrioritÃ¤t), Log mit BegrÃ¼ndung:

1. Electrs/Fulcrum **LAN** (`get_history`)  
2. Electrs/Fulcrum **Onion**  
3. **BIP-158** Compact Filter (Blockwalk/Cache â€” kein `get_history`)  
4. Ã¶ffentliche Electrum (Onion â†’ Clearnet, nur nach BestÃ¤tigung)  

Core `scantxoutset` bewusst nicht. Verwandt offen: **Server im Hintergrund** und **Status-Mails** fÃ¼r lange LÃ¤ufe.

## Erledigt: GrÃ¼ndlichere Herkunft in der Web-GUI

**Stand:** 2026-09-02 Â· **erledigt** (Folgeanalyse + Report-Politik defensiv/offensiv)  
**Ort:** Herkunftsbaum in der OberflÃ¤che (`server.py` â†’ `trace_utxo`, `web/app.js`); Steuerreport (`core/tax.py`, Einstellungen / `.env`); CLI-Heuristik in `interact.py`

### Ist-Zustand

Die CLI fragt nach einer Tx- oder UTXO-Analyse:

> Soll ich auch Transaktionsorientiert analysieren? Es sieht verzweigt aus â€¦

(`interact.py`, Default nein). Die Web-GUI hat diese RÃ¼ckfrage nicht. Ein Herkunftsklick lÃ¤uft nur `trace_utxo` â€” dieselbe Engine, ohne die Folge-Analyse Ã¼ber VorgÃ¤nger-Txs.

UnabhÃ¤ngig davon bricht die Engine bei Sammel-Txs mit mehr als 20 EingÃ¤ngen nach dem ersten eigenen Input ab (`trace_engine.FULL_RESOLUTION_INPUT_LIMIT`). Der Rest erscheint als â€žn EingÃ¤nge gebÃ¼ndeltâ€œ. Dann gilt der Baum als unvollstÃ¤ndig: keine Angabe â€žjÃ¼ngste sats vom â€¦â€œ, weil einer der unaufgelÃ¶sten EingÃ¤nge jÃ¼nger sein kÃ¶nnte.

In der GUI gibt es keinen Weg, diesen Rest nachzuziehen.

Steuerlich gilt heute **nur die defensive Lesart**: Anschaffung am UTXO = **jÃ¼ngster** externer Zufluss (`_youngest_external_ingress` / Handbuch 4.3). Offensiv (z.â€¯B. Ã¤ltester Zufluss) gibt es nicht.

Verwandt: CoinJoin-/Wasabi-Hybrid in â€žCoinJoins rÃ¼ckverfolgenâ€œ â€” dort Eigentums-Walk; hier Alltagsketten + Report-Politik.

### LÃ¶sungsskizze (bei Implementation hier ansetzen)

**A Â· Opt-in in der GUI (Daten vollstÃ¤ndiger machen)**

Leichter Herkunftsklick bleibt Standard. Am gespeicherten Baum, nicht vorher:

| Aktion | Wann sichtbar | Job |
|--------|---------------|-----|
| VorgÃ¤nger grÃ¼ndlicher analysieren | verzweigte Kette / â‰¥2 interne VorgÃ¤nger (CLI-Heuristik) | `followup=tx_oriented` â†’ `_run_tx_oriented_followups` |
| GebÃ¼ndelte EingÃ¤nge nachziehen | `external_unresolved` / `unresolved_inputs > 0` | gezielt eigene Inputs nachladen (Nicht-CJ); CJ spÃ¤ter an Hybrid-Walk andocken |

Kein Auto-Start, Confirm + Abbruch, Schreiben in denselben Trace-/Ingress-Cache. Folgeanalyse steuert nur VollstÃ¤ndigkeit, nicht die Aggregationsregel.

**B Â· Report-Politik defensiv / offensiv (Teil dieses Issues)**

Orthogonal zu A: derselbe Trace, andere Statistik fÃ¼r den Steuerreport â€” je nach Paranoia gegenÃ¼ber dem Finanzamt.

| Modus | Anschaffung am UTXO (aus externen ZuflÃ¼ssen) | Typische Haltung | Kennzeichnung |
|-------|-----------------------------------------------|------------------|---------------|
| **Defensiv** (Default, wie heute) | **jÃ¼ngster** externer Zufluss; bei LÃ¼cken `untergrenze` (â€žkann jÃ¼nger seinâ€œ, Haltedauer kÃ¼rzer) | hohe Paranoia | â€žHerkunft verfolgtâ€œ / â€žâ€¦ (Untergrenze)â€œ |
| **Offensiv** | **Ã¤ltester** externer Zufluss (lÃ¤ngere Haltedauer behaupten); bei LÃ¼cken ebenfalls ehrlich markieren (unvollstÃ¤ndiger Baum â€” Offensiv ohne VollstÃ¤ndigkeit ist besonders riskant) | niedrige Paranoia | klar als offensiv / riskanter ausweisen; Disclaimer stÃ¤rker |

Umsetzungsskizze: Einstellung z.â€¯B. `STEUER_ANSCHAFFUNG=juengste|aelteste` (Web + `.env`); `tax._anschaffung` / Ingress-Auswertung wÃ¤hlt min vs. max; Trace-BÃ¤ume unverÃ¤ndert. Export und UI nennen den Modus. Handbuch: Offensiv = bewusste Abweichung von der defensiven Grundregel in 4.3.

**Umgesetzt:** A (Opt-in-Followups `tx_oriented` / `resolve_unresolved`) und B (`STEUER_ANSCHAFFUNG`). CoinJoin-Hybrid bleibt Issue â€žCoinJoins rÃ¼ckverfolgenâ€œ.

**Wenn wir wieder drankommen:** Andock an CoinJoin-Hybrid; Specter-Plugin-Followup optional.
