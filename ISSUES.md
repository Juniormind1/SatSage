# Offene Punkte

Bekannte Lücken, noch ohne Lösung. Sortiert nach **voraussichtlichem Aufwand** (niedrigster zuerst).
Erledigte Abschnitte weiter unten unter **Erledigt:** / Historie (Detail behalten).

## Specter-Plugin · manuelle Abnahme

**Stand:** 2026-09-09 · **Kern umgesetzt** · Abnahme in Specter-UI offen

Aufwand: **gering** (manuelle Abnahme)

---
---

## Kurs-Historie · wo überall verwendet?

**Stand:** 2026-09-22 · **offen** · Inventar / Konsistenz

Aufwand: **gering** (Inventar + gezielte Fixes); Steuer-Fiat/P&L-Anbindung später **mittel**

**Bundle/Nachzug erledigt** (`core/price.py`, `price_history_sync`, Opt-in, Bundle, API). Offen: konsistente **Nutzung** und sinnvolle Erweiterungen (unten).

### Inventar · heute

**Pipeline (liefern)**

| Baustein | Rolle |
|----------|--------|
| `core/price.py` | Spot, Tageskurs, CSV Bundle/Cache |
| `core/price_history_sync.py` | Lücken-Nachzug (Opt-in) |
| `server.py` | `/api/price`, `/api/price/history`, Import, Sync |
| Einstellungen · Datenquellen | Status, „Jetzt nachziehen“, CSV-Import |
| Build-Script Bundle | Release-Historie aktualisieren |

**Verbrauch (Anzeige) — on the fly**

| Nutzung | Spot | Tages-Historie (Client-Serie) |
|---------|------|-------------------------------|
| Kopfzeile / `Zustand.kurs` | ja | — |
| Beträge **ohne** einheitliches Datum | ja / nur sats | — |
| Mit `atTs` / `gemeinsamerAtTs` (einheitlicher Kalendertag): ausgegebene UTXOs, Gruppen, Steuerjahr-Zeilen/Meta, Trace-Knoten, Abgänge | Fallback | **ja** (`tageskursAusSerie`) |
| Saldo mit **gemischten** Tagen | — | **kein** Fiat (nur sats/BTC) |

**Cache-Felder (Schreiben, UI liest sie noch nicht)**

Beim Speichern neuer UTXO-/Verlaufs-/Ingress-/…-Einträge: `btc_eur` / `btc_usd` / `btc_day` / `value_eur` / `value_usd` (und `spent_*` …) aus lokaler Historie. **Kein** Backfill-Job; GUI hängt weiter an Spot + Client-Serie.

**Heute bewusst ohne Kurs in Reports/Kern**

- Selbstanzeige / HTML- und CSV-Steuerbericht (sats/BTC, kein historischer Fiat-Ausweis)
- Scorecard / Dotplot / Haltefrist-Logik (Zeit/Hops, kein €)
- LLM/Assistent, CLI `display.py`

### Künftig sinnvoll

1. **Steuer-HTML und CSV — wichtigste Erweiterung**  
   Optional Fiat am Anschaffungs-/Zufluss- bzw. Abgangsdatum aus der **Tageskurs-Historie**, mit Quellenangabe (Bundle/Cache).  
   **Zweck:** Steuerschätzung der Finanzverwaltung **kontern** — **Plausibilität** zählt mehr als der exakte Börsenkaufpreis (den SatSage ohnehin nicht hat). Grobe, nachvollziehbare €-Größenordnung aus On-Chain-Zeit + Historie reicht dafür besser als nichts; Feintuning „echter Kaufbeleg“ bleibt externe Belege.

2. **„Sats sind teilweise steuerpflichtig“ · P&L in der Zusammenfassung**  
   Wenn die Auswertung **teilweise** innerhalb der Haltefrist / steuerrelevant ausweist: in der **Zusammenfassung** eine einfache **Gewinn-/Verlust-Skizze (P&L)** auf Basis der **Tageskurs-Historie** mitliefern (z. B. Wert am Zufluss- vs. Abgangstag bzw. Stichtag — Formel im Entwurf festnageln). Kein Buchhaltungsersatz, aber greifbare Plausibilitätszahl neben den sats.

3. **Anzeige auf Cache-Fiat verbiegen (später, optional)**  
   GUI liest `btc_eur`/`value_eur` (bzw. USD) **aus dem Eintrags-Cache**, statt on the fly über `kursSerie`/Spot. Vorteil: ein Bewertungspfad mit dem, was beim Scan geschrieben wurde; Offline/ohne Serie; konsistent mit Export. Voraussetzung: genug Einträge haben die Felder (oder gezielter Nachzug). **Kein Muss** — aktueller on-the-fly-Pfad bleibt ok, bis man umstellt.

4. Weitere (nachrangig): Assistent nur mit Quellenzeile; optional Export-Spalten.

**Nicht-Ziel:** Intraday-Charts, Multi-Fiat-Trading, „exakter Exchange-Fill“.

**Nächste Schritte:** Steuer-Export + P&L-Zusammenfassung; Cache→UI-Verbiegung nur wenn gewünscht (Punkt 3).

---

## Auswerten · Tools · Adresse nachschlagen

**Stand:** 2026-09-17 · **offen** · Idee / später · UI

Aufwand: **gering–mittel** (eine Tools-Ansicht)

Unter **Auswerten → Tools**: Adresse eingeben → Wallet-Zuordnung, Verwendung, Trace-Link oder Explorer. Kein 0.9.6-Blocker.

---
---

## Steuerbericht · HTML/CSV-Knöpfe gelb/grün nach Trace-Tiefe (BMF)

**Stand:** 2026-09-16 · **offen** · Produkt / UI / Steuer

Aufwand: **mittel** (UI + Trace-Tiefe-Status)

Berichtsknöpfe gelb ohne Kette bis extern/Coinbase (Scan anstoßen), grün wenn vollständig im Cache. Dotplot bleibt begrenzter Scan.

---
---

## Steuerbericht · zwei Berichtsarten (Geldwäsche vs. Haltefrist/Stichtag)

**Stand:** 2026-09-15 · **offen** · Produkt / Export

Aufwand: **mittel** (Export-Semantik + UI)

1. Voll bis externem Zugang (AML).  
2. Abbruch an Haltefrist/Stichtag. UI/API-Wahl, Tests.

---
---

## Labels · BIP-329 Import

**Stand:** 2026-09-21 · **offen** · Idee / später · UI / Cache

Aufwand: **mittel** (Import + Anzeige)

**Ziel:** BIP-329-Label-Dateien (`.jsonl`) importieren und an Adressen/Txs/Outputs in der UI anzeigen.

**Nicht:** Erstscan beschleunigen. UTXO/Verlauf-Import aus Wallets ist **erledigt**.

**Quellen:** u. a. Sparrow, Nunchuk, BitBoxApp, Liana, Bitcoin Safe.

**Noch offen:** Mapping, Überschreiben vs. mergen, UI-Einstieg.

---
---

## UI · Globaler Stichwort-Filter (Pillen-Zeile)

**Stand:** 2026-09-22 · **in Arbeit** · UI  
**Ersetzt:** frühere Idee „Filter je Sammelzeile / Gruppenkopf“ (zu viele Einstiege).

Aufwand: **gering–mittel** (ein Feld + Sichtbarkeitslogik; kein Backend)

### Fortschritt

- **Erledigt:** Eingabefeld links in der Pillen-Zeile (`#kopf-filter`), optisch abgesetzt; Pillen in `#quelle-pillen`.
- **Erledigt · Wallet-Ansicht:** Filter **aktiv**; Teiltext Adresse/TxID; Betrag `>n`/`<n` (sats); Bestand + ausgegeben.
- **Erledigt · Herkunft tracen:** dieselbe Logik auf `#trace-liste` (Gruppen, flache Sortierung, Fokus-UTXO, ausgegeben).
- **Erledigt · Datum:** `>1.1.25` / `<05.12.2023` (TT.MM.JJ oder TT.MM.JJJJ); nach dem Tag = ab Folgetag, vor dem Tag = vor 00:00; Ereignis = Ausgabe- bzw. Ankunftszeit.
- **Erledigt · Labels:** Börsen- und CJ-Namen im Suchtext (`Kraken`, `Wasabi`, `Whirlpool`, …) über `mix_arten` / `boerse_namen` an UTXO und Adressgruppe.
- **Als Nächstes:** weitere Ansichten (Steuerjahr, …).

### Soll · MVP

- In der **Pillen-Zeile oben** ein **Filter-Eingabefeld** (ein Suchbegriff, „googleartig“ / Excel-Autofilter über **alle** Textfelder der Zeile — nicht spaltenweise eigene Begriffe).
- Filtert, **was im Hauptbereich gerade** an Listen/Bäumen angezeigt wird: nur **Treffer-Zeilen** bleiben sichtbar.
- Match case-insensitive auf Daten der Zeile (Adresse, TxID, Labels, Datumstexte, Wallet-Name, Mix-/Börsen-Hinweise, …) — ideal aus dem **Datenobjekt**, nicht nur DOM-Kurztext.
- **Bäume/Gruppen:** Zeile oder Vorfahr sichtbar, wenn sie selbst oder ein Nachkomme matcht; Treffer-Gruppen bei Bedarf aufklappen.
- Debounce; leerer Begriff = alles wie heute. Optional Chip „Suche: … ×“.

### Aktiv nur wenn filterbar

- Das Feld ist **nur aktiv**, wenn der **aktuelle Hauptinhalt filterbar** ist (z. B. Wallet-UTXO/Ausgaben, Herkunfts-Trace, ggf. Steuerjahr-Listen mit vielen Zeilen).
- Sonst: **ausgegraut** (`disabled` / `aria-disabled`), kein Fokus — damit klar ist, dass die Suche nicht „kaputt“ ist.
- Beim Wechsel auf eine filterbare Ansicht: Feld aktivieren (ggf. letzten Begriff behalten oder leeren — einmal festlegen).

### Nicht MVP (später optional)

Strukturfilter (Datumsbereich, Volumen `</>`/zwischen, nur Coinjoins, nur Börsen) als Chips/Widgets — ersetzen den globalen Stichwort-Filter nicht; ergänzen ihn höchstens.

### Nicht-Ziel

- Filter pro Sammelzeile / pro Gruppenkopf als erster Wurf  
- Server-seitige Suche  
- Einstellungen/Datenquellen-Formulare durchsuchen  

Kein 0.9.6-Blocker.

---

## Tests · Blind spots (vs. Specter / LNbits / Jam)

**Stand:** 2026-09-10 · **teilweise** (CI-Unittests da)

Aufwand: **mittel** (Infrastruktur, schrittweise)

Offen: Browser-E2E-Smoke, Test-Marker/Schichten, weniger String-Suche in app.js, stabile Selektoren, Coverage/Lint-Gates.

---
---

## Web-UI · Mobile-Darstellung für Tablet

**Stand:** 2026-09-10 · **offen** · notiert

Aufwand: **mittel–hoch** (Layout/CSS)

Tablet-Viewport; Handy später.

---
---

## BIP-158 · ein Filterpass für alle XPUBs (ohne eigenen Indexer)

**Stand:** 2026-09-17 · **offen** · später · P2P / Performance

Aufwand: **hoch** (Scan-Engine)

Gemeinsamer Compact-Filter-Pass für alle XPUBs statt pro-Wallet-Lauf. Kein 0.9.6-Blocker.

---
---

## Steuerjahr · Zwei Tiefen (Horizont vs. voll) — Abnahme später

**Stand:** 2026-09-17 · **offen für späteres Release** · Semantik / Test

Aufwand: **hoch** (Semantik + Tests)

Horizont vs. voll bis Extern/Coinbase: hohe Komplexität. Für 0.9.6 keine systematische Abnahme (C1 verschoben). Später: Gelb erst fertig wenn grün oder voller Baum gelb bestätigt.

---
---

## Datenschutz · Scrambling + Config-Zugriff (EnvFile / dict)

**Stand:** 2026-09-22 · **offen** · spezifiziert · Sicherheit / UX / Config-API  
Aufwand: **hoch** (Krypto + zentraler Read/Write-Hook + Config)

Zwei Bausteine **gemeinsam** (ein IO-Umbau):

### A · `.env`-Scramble (Web-GUI, nur `.env`) — **Privacy erledigt**

**Ziel (aktuell):** Eine Datei **`.env`**: mit App-Passwort **scrambled** (Magic `SSGB1`), ohne Passwort **Klartext**. Klartext-Werte nur im **RAM** nach Login. **Backups** weiter Klartext-Kopien beim Start wenn möglich. Caches später. **CLI / Specter / Umbrel / Start9:** vorerst **ausgenommen**.

**UX**

- Passwort-UI; Setzen/Ändern/Löschen steuert Hash + scrambled `.env` (`core/env_scramble.py`).
- **Login** = Hash-Check **und** File-Key (KDF) + Config-Reload.
- **Passwort setzen:** `.env` wird scrambled (ersetzt Klartext-Inhalt).
- **Passwort ändern:** umschlüsseln in derselben `.env`.
- **Passwort löschen:** `.env` wieder Klartext. **Kein Recovery** jenseits Backups.
- **Start:** ohne Session → Login; scrambled ohne Key → `env_scramble.locked`.
- Legacy **`.env.gobbledigook`**: beim Unlock/Login nach `.env` migrieren und löschen.

#### Wahrheit & Dateien

| | |
|--|--|
| **Wahrheit im laufenden Prozess** | EnvFile / Werte **im RAM** |
| **Wahrheit auf der Platte** | **eine** `.env` (scrambled oder Klartext) |
| **Wahrheit zum Abgleich nach Write** | entschlüsselter Blob ≡ RAM (strukturell) |
| **Backups** | `.env.backup0`…`9` — bei Passwort-Setzen/Ändern mitscrambled, bei Löschen Klartext; Start-Rotation kopiert `.env` 1:1 |

#### Read-Hook und Write-Hook

- **Write:** Session-Key → scrambled `.env` + Probe. Ohne Key bei aktivem Scramble → Locked. Ohne Passwort → Klartext-`.env`.
- **Read:** scrambled + Key → RAM; scrambled ohne Key → Locked; sonst Klartext.
- File-Key **prozessweit**.

#### Session-Key

- **Nicht** auf die Platte.  
- Login-Hash prüft „Passwort korrekt“; File-Key = KDF(Passwort, Salt im Scramble-Header der `.env`).  
- Login setzt beides; Logout löscht den Key. Prozess tot = Key tot.

#### Krypto · festgelegt

- **Login-Hash:** bereits **Argon2id** via **`argon2-cffi`** (wie `server._hash_password`); Stdlib-**scrypt**-Fallback nur ohne Dependency.  
- **File-Key-Ableitung:** **Argon2id** (`argon2-cffi`) — **eigener Salt** (Header in scrambled `.env`), **nicht** den Login-Hash als AES-Key.  
- **Nutzdaten-Cipher:** AES-256-GCM; eine Datei `.env` (scrambled oder Klartext).  

- Primär immer argon2-cffi; scrypt-Fallback analog Login nur Minimalinstall.

#### Explizit später / ausgenommen

- Backups verschlüsseln; UTXO-/Tx-Caches; CLI; Specter; **Umbrel & Start9** (managed Passwort) bis eigene Story  
- EnvFile vs. dict Härtung (B) im gleichen Hook-Wurf wo sinnvoll  

### B · EnvFile vs. plain `dict` — Aufrufstellen härten

**Mit A koppeln** am Read/Write-Hook: ein Einstieg, klare Typen (`EnvFile` vs. `werte`), `als_env_values` oder harter TypeError.

**Ist-Falle:** Dict an `read_wallets` → `env.values()` auf dict → `dict_values` ohne `.get`.

---
---

## Architektur · Modularisierung (kleinere Module)

**Stand:** 2026-09-24 · **Slice 1+2 weitgehend · Slice 3–5 erledigt · UI/Server-Schnitte 1–6 erledigt** · Architektur  
**ADR/Abschlussmemo:** [`doc/adr-modularisierung.md`](doc/adr-modularisierung.md)

Aufwand: **sehr hoch** (viele Slices; Slice 1–5 erledigt, Shared-Kern/CLI 1–6 erledigt)
**Prompt/Detail:** [`doc/issues/modularisiere_prompt.txt`](doc/issues/modularisiere_prompt.txt)

**Hauptziel:** God-Files (`server.py`, `main.py`, `analyze.py`, `web/app.js`, …) inkrementell entkernen — Engine / core / Adapter / Surfaces, Verhalten 1:1, Tests als Netz. Kein Big-Bang.

**Pflicht-Nebeneffekt · Parallel-Dev / Merges** (nicht Hauptziel, aber hart):

Viele Entwickler und Assistenten arbeiten in **vielen Branches/Worktrees parallel**. Solange Fast-alles an denselben Monolithen hängt, sind Merge-Konflikte teuer. Wenn wir modularisieren, muss sich die **Merge-Lage massiv verbessern** (Schnitte nach Änderungsdomäne). Nur umbenennen / in ein neues God-File schieben gilt als **ungenügend** → gründlicher nachschneiden.

**Done-Check je Slice (neben Tests grün):** Typische parallele Features können weitgehend **ohne dieselbe Datei** landen; ADR/Abschlussmemo sagt das explizit.

**Fortschritt (2026-09-23):** `server.py` ~389 KB → ~62 KB; Domänen unter `httpserver/api/` + Helfer/`AppState`/`wallet_sync`/`splash`/`main_cli` unter `httpserver/`. `web/app.js` ~583 KB → ~90 KB: Views + Chrome + `api.js`/`state.js`/`format.js`/`mempool_links.js`. Rest in `app.js`: Laden-Ballast (Kurs/Chat/Sync-UI). **Slice 3:** `main.py` ~250 KB → ~23 KB; Domänen unter `core/`; Fassade + dünnes `main()`. **Slice 4:** `analyze.py` ~143 KB → **~2,8 KB**; Domänen unter `core/utxo_origin` … `sanctioned_output_trace`; Fassade + `_main`-Shim. **Slice 5 erledigt:** `fulcrum.py` ~87 KB → **~2,5 KB**; `bip158_scanner.py` ~84 KB → **~3,6 KB**; `outbound_policy.py` Fassade. Domänen `core/fulcrum_*`, `core/bip158_{filter,scan,wallet}.py`, `core/electrum_servers.py`, `core/outbound_policy.py`. Diagnose-CLI `check_fulcrum_tor.py` bleibt (nur Listen-Kern ausgelagert). Detail/Abschlussmemo in `doc/adr-modularisierung.md`. **Nächster Schritt:** optional Laden-Ballast in `app.js`; Push/FF nur nach explizitem OK; vor FF Playwright-Userflow; nach Merge push+continue vs push+pause fragen.

---
---

## Immutable-Cache · SQLite (tx / utxo_ingress)

**Stand:** 2026-09-15 · **zurückgestellt**

Aufwand: **sehr hoch** (zurückgestellt)

Nach CJ-MVP; Design in Historie. Welle 1 nur tx+ingress; keine zweite Chain.

---
---

## Start9 Community Package — Härtung

**Stand:** 2026-09-06 · **Backlog** · Community-Einreichung (S4-7) offen  

Aufwand: **hoch** (Prozess/Geräte, extern getrieben)
Fulcrum/Electrs-Auswahl: **erledigt**.

---
---

## Ideensammlung: Besitz-Signatur pro Wallet für Reports

**Stand:** 2026-08-31 · **nur notiert**

Aufwand: **sehr hoch** (Produkt + Crypto-Flow)

Message-Signatur A (Besitz, cachebar) + B (Report-gebunden). Detail in Historie.

---
---

## UTXO-Bestand · libbitcoin `scantxoutset` (RPC wie Core)

**Stand:** 2026-09-22 · **offen** · später · **hängt an libbitcoin**

Aufwand: **unbekannt/hoch** · hängt an libbitcoin

`scantxoutset` über libbitcoin-RPC für Exoten-Wallets (Vollständigkeit, nicht Speed). **Abhängig von libbitcoin-Fähigkeit/Verfügbarkeit.** Priorität niedrig.

---

# Historie / Langtexte

## Erledigt: Empfang · Ka-Ching mit libbitcoin

**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme) · Hinweis, kein SatSage-Bug

Konfetti/Ka-Ching braucht Mempool; libbitcoin hat keinen Tx-Pool — mit electrs/Fulcrum ok. Als Limit der Datenquelle abgehakt, kein offener SatSage-Punkt.

---

## Erledigt: Herkunft · Soft-Label „Wahrscheinlich Coinjoin/Mix“ ohne CJ-Icon

**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme)

Soft-Label und CJ-/Mix-Icon-Darstellung abgestimmt bzw. als erledigt abgenommen.

---

## Erledigt: Setup · UTXO + Tx-Verlauf aus bestehenden Wallets importieren
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-21 · **offen** · Idee / notiert · Setup / Cache

**Ziel:** Initiales Aufsetzen **beschleunigen** (Erstscan/Gap/P2P), indem **UTXO-Bestand** und **Tx-Verlauf** aus bereits vorhandenen Wallets des Nutzers übernommen und in die SatSage-Caches geschrieben werden.

**Nicht hier:** Labels (BIP-329) — eigener Punkt unten. Labels ersetzen keinen Scan-Boost.

**Standard?** Es gibt **keinen** verbreiteten Standard für „UTXO-Set + voller Tx-Verlauf exportieren“. BIP-329 = nur Labels; Deskriptoren = nur was abgeleitet/gescannt werden soll, nicht der Bestand. Deshalb: **Adapter je Wallet** (RPC, Wallet-Datei, App-DB, Export-CSV — je nachdem, was die App hergibt). Gemeinsam nur die **Zielseite** in SatSage (UTXO-Cache, Verlaufs-Cache, ggf. Deskriptor/XPUB anlegen).

**Kriterien:** Popularität und **Einfachheit der Implementation**. Unten nach Aufwand (leicht → schwer); Popularität zweites Kriterium.

**Kandidaten** (UTXO/History-Pfad, ohne BIP-329):

1. **Bitcoin Core / Knots** — RPC `listunspent` / History / Deskriptoren; Stack teilweise schon da
2. **Electrum** — Wallet-JSON / History-Export; Formate im Projekt bekannt
3. **Sparrow** — lokale DB / Export; OSS, nachvollziehbar
4. **Wasabi 2** — Wallet-JSON / RPC; OSS, CJ-Modell komplexer
5. **Liana / Bitcoin Safe** — OSS, Deskriptor-Wallets; History-Export je App klären
6. **JoinMarket** — OSS, spezielles Layout
7. **BitBoxApp** — Bulk-History/UTXO-Pfad unklar
8. **Nunchuk** — eher proprietär / Multisig
9. **Trezor Suite** — wenig lokaler Full-History-Dump
10. **BlueWallet** — mobil, App-DB mühsam
11. **Blockstream Green** — GDK/mobil, am unzugänglichsten

**Noch offen:** Konkretes Format je Wallet, was vertrauenswürdig in den Cache darf (Höhe, Bestätigt-only?), Abgleich mit späterem Node-Scan, UI-Einstieg. Nur notiert.

---


## Erledigt: Herkunft · „Scan neu“ auf Adresszeile
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-17 · **offen** · Idee / später · UI / Herkunft

**Ist:** Unter **Bereits ausgegeben** Adressgruppen; jede Adresse klappt zu mehreren Tx-Zeilen auf. „Scan neu“ sitzt je Tx — bei vielen Tx mühsam.

**Soll:** In der **Adresszeile** selbst ein Knopf **„Scan neu“**, der alle **untergeordneten** Tx/UTXOs dieser Adresse neu scannt/traced (Batch), nicht nur eine einzelne Tx.

**Nutzen:** Weniger Klicks bei großen Ausgaben-Gruppen. Kein 0.9.6-Blocker.

---


## Erledigt: Eastereggs · Ereignis-Atemzüge
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-13 · **offen** · Ideen (Form: Ereignis → ein Atemzug → fertig; Flüchtigkeit beachten)

Anschluss an bestehende Empfangs-Animationen (Konfetti/OH-NO/✓/oranges B) und Lernhinweise. Kein Streak-/Push-Gamification.

1. **21-Millionen-Moment:** Session-Gesamtsaldo erstmals ≥ 21 000 000 sats → einmal ∞/21M-Maske atmen.
2. **Haltefrist-Grenzübergang:** Ein UTXO wird „grün“ (außerhalb Frist) → einmal grüner Haken am Zeitstrahl (nicht nur Farbwechsel).
3. **Privatsphäre-Pille:** Wechsel öffentlich → eigener Node/Electrs/P2P → kurzer „aufatmen“-Atem am QR (ruhiger Text).
4. **Lern-Wo-ist-Walter:** Nach 5 gefundenen Lern-Tooltips in einer Session einmal Student-Maske (nur wenn Lernhinweise an).
5. **Dust-Humor:** Versuch &lt;546 sats (Lab-Faucet) → OH NO! oder „Dust…“ — lehrreich.
6. **Erste BIP-158-Treffer:** Compact Filter lädt zum ersten Mal einen Trefferblock → einmal Lupe-Atem.

**Optional / nah an Technik:** Gap-Catch-Logzeile (*„Fremde Zahlung auf #n+k — Gap hat’s gefangen“*) + einmal Lupe, wenn Subscribe-Gap einen Empfang außerhalb der QR-Adresse meldet.

**Nicht tun:** Daily Streaks, laut FOMO, Animationen die einen scannbaren Empfangs-QR während Zahlungsabsicht verdecken.

---


## Erledigt: Empfangen · Mempool-Lebenszeichen
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-12 · **offen** · Idee / Experiment

Wenn eine für ein Wallet **relevante Tx im Mempool** auftaucht (Wallet-Watch / Pending):

1. **Herzschlag** im Empfangs-QR (maskierter, nicht scanbarer Puls — wie beim Scan-Denken).
2. Das betroffene Wallet in der Nav **kurz aufblinken**.
3. Maske nach Betrag (eingehend, Satoshi):
   - **≥ 1 000 000 sats** → Bitcoin-**B**
   - **≥ 10 000 und &lt; 1 000 000** → **sat**
   - **&lt; 10 000 sats** → **Pfeiffe**

Wenn dieselbe Tx **bestätigt** (erster Block — binär, nicht „Pending sinkt“):

4. Grüner **✓**-Atemzug (~80 % der QR-Fläche) — `EmpfangPuls.flashHaken()` ist vorbereitet.
5. Wallet **nochmals** kurz aufblinken (Nav-Blink noch offen).

**Hinweise:** Flüchtigkeit beachten. Trigger für Bestätigung: Txid war pending und hat jetzt `block_height` — nicht Zähler-Heuristik. Debug: `?animdebug=1` zeigt Test-Buttons neben Empfangen (nicht für Releases).

**Abgrenzung:** Lernhinweise-QR und Scan-Herzschlag bleiben getrennte Modi; Mempool-Puls ist Ereignis, kein Dauerzustand.

---


## Erledigt: Kurs-Historie · Bundle / Nachzug
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-11 · **umgesetzt (MVP)** · **zurückgestellt** (Feinschliff im Büro)

Täglicher Job + Opt-in ``SATSAGE_PRICE_HISTORY_OPT_IN`` lädt Bitstamp/CDD bei Lücke; Overlap/Smoothing wie geplant. Bundle selbst wird nicht überschrieben (Cache darunter). Lauf **nach** GUI/„Server bereit“ (~45 s), nicht im Splash. Release-bis-Tip-Script in Builds/CI ist drin.

**Zurückgestellt bis Büro:** Live-Test hinter Firewall; UI-Texte EN durchklicken (restliche DE-Strings in `app.js` / Log).

---


## Erledigt: Datenquellen · Onion-Latenz → BIP-158
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-11 · **umgesetzt (MVP)** · Feinschliff offen

Latenz-Gate beim Setup öffentlicher Onion-Electrs (Auto-Priorität): Probe-`get_history`, Default 8 s (`PUBLIC_ONION_LATENCY_SECONDS`; `0` = aus). Zu langsam → BIP-158 erneut versuchen und binden; sonst Warnung „einzige Option, wird langsam“ + interaktiv Abbruch. Kein Mid-Scan-Hop; `--rpc-only` überspringt das Gate.

**Offen/Feinschliff:** Live hinter Firewall/Tor messen; optional Setup-Race BIP-158-Peer-Hunt ‖ Onion-Probe (schnelleres BIP-158-Fail).

---


## Erledigt: Marke · Sherlock-Satoshi / Pfeiffe
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-11 · **umgesetzt**

Marke aus `Pfeiffe-Icon.jpg` (S/W, Schwarz = Vordergrund) → transparente `web/img/pfeiffe-icon.png` und Ableitungen (`sat-logo`, Favicon, `logo-mark`, Packaging) über `scripts/prepare_brand_assets.py`. Fallback: Splash-Ausschnitt `satsage-head.png`. Splash/Windows weiter volles `logo.jpg`.

---


## Erledigt: Core-Rollen · UTXO vs. Tx/Block-Lookup
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-11 · **umgesetzt** (Morgen-Plan inkl. Block-Fetch)

**Ist:** `UTXO_RPC_*` vs. `NODE_IP`/`RPC*`; Still-Fill in `.env`; Bestand Electrs-LAN vor scantxoutset; Tx/Block: lokal bis `pruneheight`, darunter Lookup-Core; mit Electrs Core nur Fallback wenn Electrs die Tx nicht liefert; UI-Karten; Prefer-Peer `BIP158_HOST`.

**Feinschliff:** `AGENTS.md`/Handbuch-Prioritätstabelle; UI-Hinweis `peerblockfilters=1` am Qt.

---


## Erledigt: Kopf · Pillen entschlacken
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-10 · **umgesetzt** · UI-Kopfzeile

Nur noch aktive / Aufbau- / Fehler-Quellen plus Privatsphäre-Pille (hoch/mittel/keine); Labels Core / P2P n / Electrum privat / öffentlich. Cache-only → Privatsphäre hoch. Siehe CHANGELOG [Unveröffentlicht].

---


## Erledigt: Lokal Bitcoin Core erkennen
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-09 · **MVP umgesetzt** (Opt-in) · Sonderfälle offen

Wenn SatSage **standalone** auf derselben Maschine wie ein laufendes `bitcoind` startet (nicht Start9/Specter-managed), findet es Default-Datadir + `.cookie` + Loopback-RPC und bietet **Opt-in** (Datenquellen-Banner / `LOCAL_CORE_OPT_IN=1`) — kein stilles Verbinden.

**MVP (Ist):**

- `core/local_bitcoind.py`: Standard-Datadirs (Win/macOS/Linux), main/test/signet/regtest, Cookie, `getblockchaininfo`.
- Log-Hinweis beim GUI-Start; API `local_core` + `POST /api/source/local-core`.
- Opt-in schreibt RPC **und** `BIP158_HOST=<host>:<p2p-port>` (+ `BIP158_P2P=1`) — Compact Filter bevorzugt den lokalen Node (braucht `peerblockfilters=1`).
- Pruned wird nicht verworfen (scantxoutset bleibt sinnvoll).
- Managed-Modi unberührt.

**Sonderfälle (noch offen):**

- Custom `-datadir` / Flatpak / Dienst-User (Cookie nicht unter Default-Pfad)
- Mehrere lokalen Nodes → Auswahl-UI
- `rpcbind` nur auf LAN-IP, nicht `127.0.0.1`
- Feinere Priorität archival/txindex vs. Electrs-LAN in der Auto-Kette
- Stille Auto-Connect (bewusst nicht im MVP)

---


## Zurückgestellt / Detail: Immutable-Cache · SQLite

**Stand:** 2026-09-15 · **zurückgestellt** — erst **nach** Implementation der CoinJoin-Verfolgung (siehe Ideensammlung unten)

### Entscheidungsgrundlage (nicht vorab bauen)

Punktzugriff per TxID / `(txid, vout)` ist mit Flatfiles schon O(1). SQLite lohnt wegen Syscall-/AV-/Glob-Kosten, nicht wegen Lookup-Komplexität.

| Dateien in `tx/` **oder** `utxo_ingress/` | Haltung |
|------------------------------------------|---------|
| < ~1 000 | Flatfiles behalten |
| ~2 000–5 000 | Grauzone — messen (Walk-Zeit, Windows); SQLite wenn Batch-Walks/Reports stocken |
| ≥ ~10 000 | SQLite sinnvoll bis geboten (**Implementierungs-Schwelle** / Log-Hinweis) |

**Feldbeobachtung (echte XPUBs):** `immutable_cache` inkl. `tx/` kann schon **über ~5 000 Dateien** laufen, bevor die 10k-Schwelle greift — Grauzone ist real, nicht nur theoretisch. Schwelle für den einmaligen Log-Hinweis und für „jetzt bauen“ bleibt bewusst **≥ ~10 000**.

**Wachstumstreiber:** Herkunft in der Breite (viele UTXOs → `utxo_ingress/`) und/oder Tiefe/Breite des Graphen (viele `get_tx` → `tx/`), v. a. „Herkunft vollständig“, hohe `max_hops`, aufgelöste große Sammel-/CoinJoin-Txs. Reiner UTXO-/Specter-Seed füllt diese Ordner nicht.

**Scope / Reihenfolge:** SQLite-Umbau **zunächst nur** die Immutable-Seite — konkret **`immutable_cache/tx`** (Tx-Cache) und mitgedacht **`utxo_ingress`** (zwei Tabellen, PK). **Nicht** in der ersten Welle: `utxo_cache/` (XPUB-UTXO, Verlauf, Alter, Adress-Auflösung), **`utxo_trace/`**, `cfilter/`, Header-Binaries, Sanktions-Cache, Labels. Optional lazy Migration / Schwellwert-Opt-in. Windows/StartOS + Antivirus stärker betroffen als warmer Linux-Page-Cache.

**Laufzeit-Hinweis:** Ab ≥10 000 JSON-Dateien in `tx/` oder `utxo_ingress/` schreibt SatSage einmalig ins Log: *Cache wächst — sqlite ab jetzt sinnvoll* (+ Bitte um GitHub-Issue). Zählung nur alle 500 Writes, damit das Zählen selbst nicht teuer wird.

**Abgrenzung:** Kein Drive-by vor CoinJoin-Hybrid-Walk — CJ-Auflösung treibt `tx/` voraussichtlich erst richtig in die Tausender.

### Skalierung · Gedankenexperiment (Gesamt-UTXO-Set × bis Coinbase)

**Kontext (Theorie, 2026-09-15):** Jemand lädt das **gesamte aktuelle UTXO-Set** in SatSage (grundlegende Modifikation, UTXOs ohne XPUB) und veranlasst den **Gesamtverlauf aller UTXOs bis Coinbase** (z. B. Sanktions-Check mit „1 Mio Hops“ ≈ kein künstlicher Tiefenstopp). Vergleichsgröße: Full-Node **mit Index ~1,3 TB**.

**Größenordnung Cache danach (sehr grob):**

| Teil | Charakter | vs. ~1,3 TB Node |
|------|-----------|------------------|
| `tx/` | unique TxIDs im Vorfahren-DAG ≈ großer Teil der Tx-Historie; JSON-Flatfile dicker als Wire | oft **~1×–wenige ×** Node (≈ 1–5 TB+, dickere JSONs mehr) |
| `utxo_ingress/` | 1 schlanke Datei pro UTXO (~10⁸) | **~0,1–0,4 TB** — lästig, nicht dominant |
| `utxo_trace/` | **1 Vollbaum pro UTXO**, geteilte Vorfahren **ohne Sharing erneut serialisiert** | leicht **~10–100 TB+** (CJ/breit: deutlich mehr) — **dominiert** |
| Header / cfilter / UTXO-Liste | Nebenkosten | ≪ Trace/Tx |

**Key takeaway:** Ja — **`utxo_trace`-Flatfiles sind massiv redundant**, weil **geteilte Vergangenheiten** (gemeinsame Vorfahren bis Coinbase) **pro UTXO erneut weggeschrieben** werden. `tx/` ist dagegen schon **pro TxID dedupliziert** (ein File je Transaktion); der Schmerz dort ist vor allem **JSON-Aufblähung + Millionen Dateien/Syscalls**, nicht Baum-Kopie. Ohne Voll-Traces: Cache eher „Node-Liga oder etwas drüber“. Mit Voll-Trace je Output: **Größenordnungen über** 1,3 TB; OS/AV sterben an **Dateianzahl** oft vor der TB-Zahl. Node bleibt effizienter: Historie **einmal** binär, kein materialisierter Baum je Coin.

**Erkenntnis · geteiltes DAG-/Graph-Modell:** Die **Blockchain selbst** *ist* bereits das Funding-DAG in **höchstkomprimierter** Form (binäre Txs, Blöcke, optional txindex/UTXO-Set). Ein SatSage-internes „shared Graph gegen Trace-Redundanz“ für den **Vollgraphen** (alle Coins, multi-user, bis Coinbase) konvergiert gegen **Node-/Indexer-Arbeit** — Konsens-Historie plus Wallet-Färbung (own/external, Fingerprint, CJ, Steuer) in einem eigenen Store zu halten wäre **sehr komplex** und meist eine **schlechtere zweite Chain**. Schichten grob: (1) `tx`+`ingress`-Tabellen = mittel, Datei-Schmerz; (2) App-Kanten-Cache + lazy Walk = schon semantisch heikel (Invalidierung, Färbung); (3) chain-gleicher Vollgraph = falsch investiert. Redundanz der Traces stirbt primär durch **Nicht-Materialisieren**, nicht durch Ultra-Graph-Eigenbau.

**SQLite — was hilft (ohne zweite Chain):**

- **Erste Welle (`tx` + `ingress` als Tabellen/PK):** mildert **Inode-/Open-/AV-Kosten** und Backup-Chaos; speichert **nicht magisch weniger Nutzdaten**, wenn jede Tx weiter als fetter JSON-Blob in einer Zeile liegt. Kompression kann JSON-Bloat mindern, nicht die „fast volle Historie“-Menge.
- **Traces nur als Blob-pro-UTXO in SQLite** (1:1-Port): **behebt die Redundanz nicht** — weniger Dateien, ähnliche TB-Lage.
- **Nicht-Ziel:** SatSage als Exchange-Backend mit privatem Voll-Trace-Clone je Kunde. Multi-User-Fantasie → **Indexer/Node** als DAG, SatSage = Policy/Steuer/UI.

### Designentscheidung · keine „bessere Blockchain“, Cache-Grenze, Trace on demand

**Stand:** 2026-09-15 · **beschlossen (Richtung)**

1. **SatSage soll keine „bessere Blockchain“ als DAG-/Graph-Modell neu erfinden.** Die Chain (bzw. ein fähiger Index darüber) bleibt Source of Truth für den Funding-Graphen. Kein Projektziel „shared Herkunfts-DAG parallel zur Node“.
2. **Cache hat einen Grenzfall, den wir bei Bedarf scharf ziehen** — wenn Skalierung weh tut (viele Traces, ggf. multi-user / viele XPUB-Welten): geeigneten **Cache-Ceiling** identifizieren (was darf persistent sein: typisch schlankes `tx`/`ingress`/UTXO-Meta; was nicht: Vollbäume auf Vorrat).
3. **Darüber hinaus:** Herkunfts-/Sanktions-Bäume **nur individuell je Anforderung** erzeugen (Job/Request), **nicht auf Vorrat in den Cache verklappen**. Optional ephemer in RAM/Session; Persistenz von Voll-`utxo_trace` ist Komfort unter der Grenze, kein Pflichtpfad für Masse.
4. **Performance jenseits der Grenze:** nicht mehr Cache-Philosophie, sondern **bessere Datenquelle/Indexer**. Orientierung: **Libbitcoin** (bzw. vergleichbar starker Stack) schafft grob **~vierfache electrs-Performance** — das muss für schwere Walks **dann mal reichen**, statt Graph-DB in-process.

**Konsequenz für diese Issue:** SQLite-Welle 1 bleibt **`tx` + `ingress`** (Zugriffskosten). **Kein** Folge-Epic „Graph-DB / shared trace DAG“. Trace-Redundanz und Exchange-Skalen → **Ceiling + on-demand + Indexer**, nicht Denormalisierungs-Kunst in SatSage.

---


## Erledigt: Start9 · Fulcrum/Electrs-Auswahl
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-09 · **in Arbeit (Vorbereitung)** · Bezug: [`doc/START9-fulcrum-indexer.md`](doc/START9-fulcrum-indexer.md), [`doc/START9-packaging.md`](doc/START9-packaging.md)

Der Start9-Build-/Package-Prozess soll **Fulcrum** können, nicht nur `electrs-startos`.

**Soll:**

- In der **StartOS-GUI auswählbar** (Action **Select Indexer**), analog Mempool — Fulcrum oder Electrs.
- Manifest: beide Deps optional; zur Laufzeit genau eine aktiv.
- Bridge-Env → `FULCRUM_*` + `SATSAGE_ELECTRUM_INDEXER`; SatSage-UI bleibt für Bridge-Quellen read-only.

**Erledigt in Vorbereitung (ohne `.s9pk`-Bau):** Design-Doku; Packaging (`store.indexer`, `selectIndexer`, conditional deps, Bridge electrs/`electrum` oder fulcrum/`main`); App-`managed_hint` / `electrum_indexer`; Unit-Tests.

**Offen bis Sideload:** `npm ci` + `./scripts/build_startos_s9pk` auf Build-Host; Geräte-Test Fulcrum-Wahl; optional Task „Indexer wählen“ erzwingen; Auto-Detect nur als spätere Stufe.

---


## Start9 Community Package — Härtung (Detail)

**Stand:** 2026-09-06 Â· **Backlog aktiv, Umsetzung schrittweise**

- Analyse & Soll-Modell: [`doc/START9-hardening.md`](doc/START9-hardening.md)
- Tickets/Phasen: [`doc/START9-backlog.md`](doc/START9-backlog.md)
- Specter-Plugin-Testplan (paralleler Distributionsweg): [`doc/testplan-specter-plugin.md`](doc/testplan-specter-plugin.md)

Kurz: Loopback+Token-URL reichen nicht fÃ¼r LAN/Tor hinter StartOS. S0â€“S3 sind im Code; der Wrapper liegt in **`packaging/`** (Branch `main`). Bauen/Sideload/Release: [`doc/START9-packaging.md`](doc/START9-packaging.md). **S4-6** (GerÃ¤te-E2E mit Release 0.9) erledigt; **Community-Einreichung (S4-7)** bleibt offen.

---


## Erledigt: Ideensammlung · echte Wallet-Software
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


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


## Ideensammlung (Detail): Besitz-Signatur pro Wallet

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


## Erledigt: CoinJoins rückverfolgen (MVP)
**Stand:** 2026-09-22 · **erledigt** (Maintainer-Abnahme).


**Stand:** 2026-09-11 · **MVP umgesetzt** (Klassifikation + Soft-Label + Own-only-Walk; ohne Einstellungs-UI A/B/C)  
**Kurzfassung:** [`doc/issues/coinjoin-herkunft.md`](doc/issues/coinjoin-herkunft.md)  
**Code:** `core/tx_classify.py`, Own-only in `trace_engine.iter_trace_funding_inputs` / `analyze.trace_utxo_origin`, UI Soft-Label in `web/app.js`, Lab `verify_tx_classify.py`  
**Bisq:** Soft-Labels Deposit/Payout (Form + OP_RETURN); kein Own-only  
**Offen / Folge:** Whirlpool-Ketten (Remix × n kumuliert); Einstellungen A/B/C; langer WabiSabi-Remix-Job / Status-Mails  
**Danach:** Immutable-Cache SQLite (tx/ingress) — Entscheidungsgrundlage siehe Issue oben; nicht parallel vorziehen.  
**Ort:** Herkunftsanalyse (`trace_engine.py`, `analyze.py`, Web-Herkunft / CLI), Einstellungen, Steuerbericht; Hintergrundjob/Status-Mails für lange Walks

### Ist-Zustand

Bei Sammel-Txs mit mehr als 20 Eingängen bricht die Engine nach dem ersten eigenen Input ab (`FULL_RESOLUTION_INPUT_LIMIT`); der Rest erscheint als „n Eingänge gebündelt“. Das trifft typische Wasabi-/WabiSabi-CoinJoins. Regtest: zwei CJ-**ähnliche** Txs (24 in / 28 out) — kein echter Coordinator.

| Muster | vs. 20er-Limit | Anschaffungsdatum |
|--------|----------------|-------------------|
| Wasabi / WabiSabi (oft ≫20 Inputs) | bricht ab → gebündelt | unvollständig / Untergrenze |
| Whirlpool (typisch 5×5) | unter Limit, schon voll aufgelöst | Peer-Inputs dürfen trotzdem **kein** Datum liefern (nur eigene Zweige; Fremde = Rauschen) |
| JoinMarket (oft klein–mittel) | meist unter Limit | wie CoinJoin: nur eigene Zweige |
| PayJoin (typisch 2–wenige Inputs) | **bricht nicht** am Limit | kein Mix — fremder Input = Gegenstelle, nicht Peer-Rauschen |

Verwandt mit „Gründlichere Herkunft in der Web-GUI“.

### Klassifikation · Eigentum zuerst (festgeschrieben)

Vor Formheuristik: **alle** `vin`/`vout` gegen konfigurierte XPUBs matchen. Sonst kein Exchange-/PayJoin-Label. Soft: „Wahrscheinlich …“.

| Label | Eigene Inputs | Form (In/Out) | Lesart |
|--------|---------------|---------------|--------|
| **Fan-Out (eigen)** | **alle** Ins eigen | mehr Outs als Ins, ≥3 Outs | Auszahlung/Split (wenige→n) |
| **Fan-In (eigen)** | **alle** Ins eigen | mehr Ins als Outs, ≥2 Ins | Konsolidierung (n→wenige) |
| **PayJoin** | gemischt; übersichtlich viele Ins, **wenige** Fremd (typisch 1, selten 2) | Sender oft Change; Empfänger oft 1 Netto-Out | kollaborative Zahlung, **kein** Mix |
| **Exchange-Batch** | **0** eigen | typisch viele Outs, ≥1 eigen | nur Empfang; **kein** CJ |
| **CoinJoin** (Wasabi / Whirlpool / JM) | ≥1 eigen | ≥1 eigen | Mix; Fremde = Rauschen |

**Detektor-Reihenfolge:** (1) Eigentum klären → (2) 0 eigene Ins + eigene Outs → Exchange-Batch → (3) alle Ins eigen → Fan-In/Fan-Out nach Richtung → (4) wenige Ins/wenige Fremd → PayJoin → (5) Whirlpool → Wasabi → JoinMarket → unklar.

**Abgrenzung:** Fan-In/Out = 0 Fremd-Ins, Richtung `n_in` vs. `n_out` (nicht pauschal „alle eigenen Ins“); PayJoin = ≥1 Fremd-In bei kleinem Ins-Set (Richtwert ≤5–8 Ins, ≤2 Fremd); Exchange ohne eigenen Input kein CJ. PayJoin/Fan-In/Fan-Out/Exchange **nicht** in die CJ-Stop-/Auflös-Optionen.

### Umsetzungsstrategie (Reihenfolge)

**1. Einstellung: Behandlung von CoinJoins**

Benutzer regelt in den Einstellungen (Web + `.env`), was bei erkannten CoinJoins passiert. Cache vermerkt Typ (`whirlpool` / `wasabi` / `joinmarket`; Exchange/PayJoin/Fan-Out separat):

| Option | Verhalten |
|--------|-----------|
| A — Scan stoppt am CoinJoin | Herkunft endet am Mix; Cache: „CoinJoin erkannt (…)“; kein Weiterlaufen durch den Mix |
| B — Nur Wasabi stoppt | Whirlpool wird aufgelöst; Wasabi bleibt Markierung + Abbruch |
| C — Beide auflösen | Wasabi und Whirlpool werden durchverfolgt (langsamste Variante) |

Erkennung vor dem teuren Walk; Abgrenzung zur normalen Sammel-/Konsolidierungs-Tx (dort bleiben unaufgelöste eigene Inputs eine echte Untergrenze).

**2. Whirlpool-Scan (Samourai / Nachfolger z. B. Ashigaru)**

- Heuristik: starres Muster (typisch 5 In / 5 Out, gleiche Pool-Denomination; Tx0 separat).  
- n Remix-Runden erkennen und nach Möglichkeit **kumuliert** darstellen (eine Kette „Whirlpool × n“, nicht n Einzelbäume in der UI).  
- Im **Steuerbericht** die Kette auflösen: Anschaffungsdatum über eigene Zweige durchreichen; Peer-Inputs als Rauschen, nicht als externer Zufluss.  
- Eigene Inputs bevorzugt über Verlauf/`spent_txid`-Index finden, nicht alle Prevouts laden.

**3. Wasabi-/WabiSabi-Scan**

- Große n:m-Txs; nur eigene Inputs/Outputs weiterverfolgen, Rest verwerfen (kein Blind-Auflösen aller `vin`s).  
- Erfordert Geduld (viele Abrufe über Remix-Historie). Praktisch erst sinnvoll mit Hintergrundbetrieb + Status-Mails.  
- Einstellung C (oder B nur für den Wasabi-Zweig) steuert, ob überhaupt durchgelaufen wird.

#### Lösungsskizze: Hybrid-Walk (bei Implementation hier ansetzen)

Rückwärts in eine erkannte n:m-CoinJoin-Tx `C`. Semantik: CoinJoin ist **kein** externer Zufluss; Anschaffungsdatum nur über **eigene** Vorfahren. Fremde Inputs = Rauschen, nie auflösen.

**Auswahlregel = Eigentum, nicht Betrag.** Betragsgleichheit Output↔Inputs ist höchstens Priorisierung (WabiSabi zerlegt/rekombiniert; Fees; mehrere eigene Ins/Outs). Weiterverfolgt werden **alle** eigenen Inputs von `C`.

| Stufe | Wann | Vorgehen | Kosten |
|-------|------|----------|--------|
| **1 · Index** | Verlauf/`spent_txid` brauchbar | eigene Outpoints mit `spent_txid == C` — kein Prevout-Resolve | billig (Cache) |
| **2 · Lücke** | Verlauf `incomplete`, fehlende `spent_txid`, unsicherer `max_index`/Gap | Ein `get_tx(C)` (alle `vin`s, billig). Dann Outpoint∩bekannte eigenen Outpoints und/oder Adressraum∩Vin-Adressen. Prevouts **nur** für Treffer — nie blind alle Fremden | teuer/zeitaufwändig, **korrekt** wenn Wallets/Deskriptoren stimmen und der Adressraum reicht |

**Deckung:** Stufe 1 und „Adressraum ∩ Vins“ sind dieselbe Aussage, sobald Cache und Adressraum vollständig sind. Lücken werden erkannt → bewusst Stufe 2, nicht raten.

**Nicht verwechseln:** `FULL_RESOLUTION_INPUT_LIMIT` / „gebündelt“ bleibt für **normale** Sammel-/Konsolidierungs-Txs (ohne CJ-Erkennung); dort sind unaufgelöste eigene Inputs echte Untergrenze. Beim CJ-Hybrid entfällt Blind-Resolve der Fremden.

**Voraussetzungen für „korrekt“:** alle relevanten XPUBs/Deskriptoren konfiguriert; Scan/Gap deckt Mix-Adressen; bei Stufe 2 Eigentums-Schnittmenge statt Betragsfilter. Remix-Ketten bleiben lang → Hintergrundjob/Mails bleiben Voraussetzung; der Hybrid macht den **einzelnen Hop** billig bzw. die Teuerkeit an erkannte Lücken gebunden.

**4. JoinMarket (später, echte CoinJoin-Variante)**

- P2P Maker/Taker, **kein** zentraler Coordinator; Taker wählt den gleichen Output-Betrag.  
- On-chain: N+1 **gleiche** CJ-Outputs + meist je Teilnehmer ein Change (außer Sweep). Kein festes 5×5 → Erkennung **locker**, False Positives möglich. Detektoren: erst Whirlpool/Wasabi, JoinMarket als Fallback.  
- Mit XPUB: eigene Inputs + typisch ein CJ-Out + ggf. eigenes Change; Fremde = Rauschen.  
- In die CoinJoin-Einstellung aufnehmen; Cache-Typ `joinmarket`.

**5. PayJoin / Fan-In / Fan-Out / Exchange-Batch — eigene Labels, kein CJ**

- Siehe Tabelle „Klassifikation · Eigentum zuerst“.  
- PayJoin (BIP78/BIP77): weicher Hinweis möglich; **nicht** in CJ-Stop-/Auflös-Optionen.  
- Exchange-Batch erst nach vollständigem Input-Eigentum (0 eigene Ins).  
- Fan-Out (eigen): alle Ins eigen, mehr Outs als Ins (≥3 Outs).  
- Fan-In (eigen): alle Ins eigen, mehr Ins als Outs (Konsolidierung).

**Erledigt (MVP):** Detektor + Soft-Labels + Own-Input-Walk + Lab-Fixtures.  
**Wenn wir wieder drankommen:** Einstellungs-Enum A/B/C → Whirlpool-Kette (Remix × n) → Handbuch-Abschnitt Trace-Verhalten.


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

