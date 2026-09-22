# Offene Punkte

Bekannte Lücken, noch ohne Lösung. Neueste oben.

## Datenschutz · Optionales Scrambling geheimnistragender Dateien

**Stand:** 2026-09-22 · **offen** · Idee / notiert · Sicherheit / UX / Cache

**Ziel:** Klartext von Secrets (XPUBs, Wallet-Namen, RPC-Credentials, Cache-Inhalte mit Adressen/Tx) **nur noch im Speicher**. Auf der Platte liegen die betroffenen Dateien gescrambled, sobald der Nutzer ein Passwort setzt.

**UX**

- Einstellungen: Feld **„Passwort festlegen:“** (optional; Default = kein Scrambling, Verhalten wie heute).
- **Passwort setzen:** Alle geheimnistragenden Dateien werden konvertiert (Scramble). Fortschritt im **Log**.
- **Web-GUI-Start:** Passwort abfragen → **Proberead** (falsches Passwort sofort zurückweisen) → danach jede Lese- und Schreiboperation über die **Scramble-Envelope**.
- **Passwort löschen:** Alle Dateien wieder unscrambled konvertieren. Fortschritt im **Log**.

**Betroffene Dateien (mindestens)**

- `.env` und deren Backups
- UTXO-Caches (`utxo_cache/`)
- Tx-/immutable Caches mit Wallet-Bezug (`immutable_cache/` u. a. `tx/`, `utxo_ingress/`)
- ggf. Adress-Auflösungs-Cache (`external_addresses.json`) und weitere Dateien, die XPUB/Adresse/Wallet-Klartext tragen

**Nicht hier:** Seed/xprv/WIF (SatSage nimmt die nicht an). Sanktionslisten-Clearnet-Pools ohne Wallet-Bezug ggf. ausnehmen, wenn sie keine Nutzer-Secrets enthalten — beim Entwurf klären.

**Technik (Skizze, noch offen)**

- Ableitung aus Passwort (z. B. KDF) → Schlüssel nur in-memory für die Session
- Einheitliche Envelope um Read/Write (ein Einstiegspunkt, kein ad-hoc Open in Dutzenden Pfaden)
- Erkennung scrambled vs. plain (Magic/Header), damit Mischzustände und Migration robust sind
- Proberead beim Unlock: bekannte Datei oder Envelope-Header prüfen, bevor die App weiterarbeitet
- CLI/Specter: gleiches Unlock-Modell oder dokumentierte Einschränkung

**Noch offen:** Krypto-Wahl (nur lokal, kein Cloud-Key), welche Pfade exakt in der Envelope liegen, Verhalten bei Teil-Migration/Abbruch, Backup-Rotation unter Scramble, ob Header-Caches ohne Adressbezug draußen bleiben. Nur notiert.

---

## Setup · UTXO + Tx-Verlauf aus bestehenden Wallets importieren

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

## Labels · BIP-329 Import (separat vom Scan-Boost)

**Stand:** 2026-09-21 · **offen** · Idee / später · UI / Cache

**Ziel:** BIP-329-Label-Dateien (`.jsonl`) importieren und an Adressen/Txs/Outputs in der UI anzeigen (Herkunft, Bestand, Steuerjahr lesbarer).

**Nicht:** Erstscan beschleunigen — BIP-329 liefert **keine** UTXOs und **keinen** Tx-Verlauf, nur Namensschilder. Scan-Boost = Issue „UTXO + Tx-Verlauf aus bestehenden Wallets“.

**Quellen (wo Nutzer BIP-329 herkriegen):** u. a. Sparrow, Nunchuk, BitBoxApp, Liana, Bitcoin Safe — sobald die Labels in SatSage landen, egal welches Wallet den Scan gefüttert hat.

**Noch offen:** Mapping auf SatSage-Caches, Überschreiben vs. mergen, UI-Einstieg. Nur notiert.

---

## Empfang · Ka-Ching mit libbitcoin

**Stand:** 2026-09-17 · **kein SatSage-Bug** · Hinweis

**Beobachtung:** Konfetti/Ka-Ching bei Mempool-Empfang funktioniert; **mit libbitcoin als Indexer nicht**, weil libbitcoin **keinen Tx-Pool/Mempool** hat — Pending-Receive steigt nicht.

**Bewertung:** Erwartetes Limit der Datenquelle, kein SatSage-Fehler. Mit electrs/Fulcrum (Mempool) ok.

---

## Herkunft · Soft-Label „Wahrscheinlich Coinjoin/Mix“ ohne CJ-Icon

**Stand:** 2026-09-17 · **offen** · näher untersuchen · UI / Trace

**Beobachtung:** In **Herkunft tracen** erscheint häufiger der Soft-Text **„Wahrscheinlich Coinjoin/Mix“** (o. Ä.), aber das zugehörige **CJ-/Mix-Icon** taucht darunter **nicht** auf (weder an der Zeile noch in der Gruppen-Kopf-Leiste).

**Zu klären:**

- Welche `tx_class`-Werte den Text setzen vs. welche in `MIX_ICON_ORDER` / `TX_CLASS_ICON` ein Icon haben
- Ob Icon nur bei konkreten Formen (Wasabi/Whirlpool/…) gerendert wird, Soft-Label aber bei generischem `coinjoin`/`mix`
- Ob `mix_arten` am UTXO/Gruppe nach Trace nicht gesetzt wird, obwohl `tx_class_label` da ist
- Soft-Label an Wurzel vs. Icon nur an Kindknoten / Gruppenkopf

**Nächster Schritt:** Repro mit einer betroffenen Tx, `tx_class` / `mix_arten` / DOM prüfen. Kein 0.9.6-Blocker, aber UX-Inkonsistenz.

---

## Herkunft · „Scan neu“ auf Adresszeile (Bereits ausgegeben)

**Stand:** 2026-09-17 · **offen** · Idee / später · UI / Herkunft

**Ist:** Unter **Bereits ausgegeben** Adressgruppen; jede Adresse klappt zu mehreren Tx-Zeilen auf. „Scan neu“ sitzt je Tx — bei vielen Tx mühsam.

**Soll:** In der **Adresszeile** selbst ein Knopf **„Scan neu“**, der alle **untergeordneten** Tx/UTXOs dieser Adresse neu scannt/traced (Batch), nicht nur eine einzelne Tx.

**Nutzen:** Weniger Klicks bei großen Ausgaben-Gruppen. Kein 0.9.6-Blocker.

---

## Steuerjahr · Zwei Tiefen (Horizont vs. voll) — Abnahme später

**Stand:** 2026-09-17 · **offen für späteres Release** · Semantik / Test

**Hintergrund:** Steuer-Horizont vs. voll bis Extern/Coinbase war als Optimierung gedacht, erzeugt aber hohe Komplexität (Scorecard gelb/grau, `steuer_ausreichend`, gelb-klären, Berichtstiefe).

**Für 0.9.6:** Keine systematische Abnahme der Zwei-Tiefen-Sonderfälle. Pragmatisch: klären möglichst vollständig, aufs Beste hoffen. Testplan **C1** (und verwandte Horizont-Semantik) **verschoben**.

**Später:** Gelb erst „fertig“, wenn **grün** oder voller Baum gelb bestätigt; Horizont-Stop ≠ gelb erledigt. UI/Backend und Testfälle dann bewusst nachziehen.

---

## Herkunft · Stichwort-Filter in Sammelzeilen

**Stand:** 2026-09-17 · **offen** · Idee / später · UI / Herkunft tracen

**Soll:** In jeder **Sammelzeile** (Gruppe zum Ausklappen darunter) ein Eingabefeld **„Stichwort“** + **Filtern**. Danach bleiben nur noch die Teile der Gruppe sichtbar, die zum Stichwort passen.

**Match egal worauf** (Teilstring, case-insensitive sinnvoll):

- Adresse (auch Teil)
- TxID (auch Teil)
- Börsenlabel (z. B. Kraken)
- Monat / Jahr (Datumsfelder)

**Bezug:** Ergänzt die geplanten Filter in der Gruppen-Überschrift (Datumsbereich, Coinjoins, Börsen, Volumen) — Stichwort ist der schnelle Freitext. Kein 0.9.6-Blocker.

---

## Auswerten · Tools · Adresse nachschlagen

**Stand:** 2026-09-17 · **offen** · Idee / später · UI

**Soll:** Unter **Auswerten** einen Punkt **Tools**. Darin:

- Eingabefeld für eine **Adresse**
- Knopf **„Auswerten“**

**Verhalten:**

1. Gehört die Adresse zu einem der konfigurierten Wallets? Wenn ja → welches (Name / XPUB-Kontext).
2. Wurde sie schon verwendet? (Historie/UTXO-Cache)
3. Wenn verwendet **und** Herkunfts-Trace vorliegt → **Link zum Trace** anbieten.
4. Gehört sie zu **keinem** Wallet → **„nicht gefunden“** und, sofern konfiguriert, **Link zum Block-Explorer**.

**Nutzen:** Schnelle Zuordnung ohne manuell Wallets/Listen durchzuklicken. Kein 0.9.6-Blocker — nur Idee notiert.

---

## Herkunft · Filter in der Gruppen-Überschriftenzeile

**Stand:** 2026-09-17 · **offen** · später · UI / Herkunft tracen

**Soll:** In jeder **Adressgruppen-Kopfzeile** (Bestand und „Bereits ausgegeben“) Filteroptionen:

- **Datumsbereich**
- **Coinjoins** (Mix-Formen vorhanden / Art)
- **Börsen** (z. B. nur Kraken/Coinbase / mit Börsen-Label)
- **Volumen** `<` / `>` / **zwischen**

**Kontext:** Sortierung (Volumen/Alter) wirkt bereits auf Bestand und Ausgaben; Mix-Icons und Börsen-Pillen stehen schon in der Kopfzeile — Filter wären die nächste Stufe zum Eingrenzen großer Listen.

**Nutzen:** Hoch bei vielen Adressen/UTXOs. Kein 0.9.6-Blocker — **später bauen**.

---

## BIP-158 · ein Filterpass für alle XPUBs (ohne eigenen Indexer)

**Stand:** 2026-09-17 · **offen** · später · Datenquelle / P2P · Performance

**Problem:** Ohne eigenen Electrs/Fulcrum läuft der UTXO-Bestand über Compact Filter **pro Wallet / XPUB** (Scan-Queue + `fetch_wallet_utxos_bip158`: `for xpub in xpubs`). Mehrere Wallets ⇒ mehrfacher Lauf über dieselben Höhen (Turbo/Historie) — großer Zeitfresser für P2P-only-Nutzer.

**Soll (Idee):** Ein gemeinsamer Filterpass: Scripts **aller** konfigurierten XPUBs in einem `watched`-Set matchen, Treffer dem richtigen XPUB zuordnen, Caches weiter **pro Wallet** schreiben. Abbruch, Zwischenstand und unterschiedliche Start­höhen/Alter sauber lösen.

**Nicht:** Herkunft-Trace umbauen — der liest den Bestand aus dem Cache und macht Tx-Graph-Walks; der Boost trifft die **Bestands-Population**.

**Nutzen:** Sehr hoch für Nutzer ohne Indexer. Architektur-Hebel, kein Mikro-Polish — **später bauen**, kein 0.9.6-Blocker.

---

## Steuerbericht · HTML/CSV-Knöpfe gelb/grün nach Trace-Tiefe (BMF)

**Stand:** 2026-09-16 · **offen** · Produkt / UI / Steuer

**Hintergrund (BMF 2022 / 2025):** Die Sat-Historie muss **durchgehend** sein — auch wenn die Haltefrist schon **innerhalb** der XPUB-Wallets erreicht wurde. Abbruch nur an Haltefrist/Stichtag reicht für den **amtlichen Herkunftsnachweis nicht**.

**Ist / Abgrenzung:**
- **Dotplot + UTXO-Klassifikation** (innerhalb / außerhalb Haltefrist): begrenzter Scan, der früher abbricht als „extern / Coinbase“, **reicht**.
- **HTML- oder CSV-Bericht:** ohne Kette bis **extern / Coinbase** wäre der Bericht **unvollständig** (BMF-Lesart).

**Soll:**
1. HTML-Bericht-Knöpfe **gelb**, wenn der Verlauf **nicht** bis extern/Coinbase im Cache liegt → Klick löst tieferen Herkunftsscan aus (kann dauern).
2. HTML-Bericht-Knöpfe **grün**, wenn die Herkunft **schon vollständig** im Cache liegt → Export schnell.
3. **Tooltips:**  
   - Gelb: „erfordert Herkunftsscan. Kann dauern…“  
   - Grün: „Herkunft liegt schon im Cache“
4. Analog ggf. CSV, falls derselbe Vollständigkeits-Anspruch gilt.

**Nicht:** Dotplot/Klassifikation auf Voll-Trace umstellen — der begrenzte Scan bleibt dort korrekt und schneller.

---

## UTXO-Bestand · libbitcoin `scantxoutset` (RPC wie Core)

**Stand:** 2026-09-16 · **offen** · später · Datenquelle / UTXO-Scan

**Idee:** Libbitcoin (bzw. vergleichbarer Stack) per **RPC wie Bitcoin Core** anbinden und **`scantxoutset`** für den UTXO-Bestand nutzen — parallel/alternativ zum Electrum-Gap-Scan.

**Nutzen:** Kann bei **exotischen Wallets** (Miniscript, unübliche Deskriptoren, Adressen jenseits typischer Gap-Annahmen) Treffer liefern, die ein Gap-Scan **übersieht**.

**Nicht der Treiber:** Laut Einschätzung **nicht schneller** als Gap-Scan am eigenen Indexer — also kein Performance-Projekt, sondern **Vollständigkeit / Exoten**.

**Voraussetzung:** Libbitcoin wie Core konfigurierbar (Host/Port/User/Pass oder Cookie), eigene Slot-Logik oder Erweiterung von `UTXO_RPC_*` / `own_utxo_core`, klare Priorität gegenüber Electrs-LAN-Gap und Core-`scantxoutset`.

**Priorität:** niedrig — **irgendwann später**, wenn Exoten-Wallets oder fehlende UTXOs das rechtfertigen. Kein Blocker für den normalen Electrs/Fulcrum/libbitcoin-Electrum-Pfad.

---

## Steuerbericht · zwei Berichtsarten (Geldwäsche vs. Haltefrist/Stichtag)

**Stand:** 2026-09-15 · **offen** · Produkt / Export

Der HTML-Herkunftsnachweis (Hop-Kette aus Trace-Cache) braucht **zwei getrennte Berichtsarten** — nicht eine Vollkette für alles:

1. **Geldwäsche / vollständiger Herkunftsnachweis**  
   Hop-Kette bis zum **externen Zugang** (Kauf-/Zuflussdatum außerhalb der eigenen Wallets). Länger, für Nachvollziehbarkeit „woher die Sats kamen“.

2. **Haltefrist / Stichtag**  
   Hop-Kette nur so weit, bis die Sats **älter als Haltefrist bzw. vor dem Stichtag** sind — dann Abbruch. Kürzer, reicht zur Untermauerung der Haltedauer-/Altbestand-Behauptung.

**Abgrenzung:** On-chain Hops only. Börsen-/Konto-/Kaufbelege („externe Belege“ im Sinne von Drittunterlagen) baut SatSage **nicht**.

**Ist:** Ein Hop-Abschnitt im Steuer-/Selbstanzeige-HTML, immer volle Trace-Tiefe (sofern Cache vorhanden).

**Soll:** UI/API-Wahl der Berichtsart; Haltefrist-Modus schneidet den Baum am Frist-/Stichtags-Horizont; Dateiname/Titel kennzeichnen die Art; Tests für Abbruchkriterium.

---

## Config · EnvFile vs. plain `dict` — Aufrufstellen härten

**Stand:** 2026-09-15 · **offen** · API-Klarheit / Härtung

Wiederkehrende Stolperfalle (Assistenten und Skripte): Manche Einstiege erwarten ein **`EnvFile`** (`.values()` → `dict[str, str]`), andere ein **plain `dict`**. Wer ein `dict` an eine EnvFile-API übergibt, bekommt still `dict_values` statt Key-Zugriff (`AttributeError: 'dict_values' object has no attribute 'get'` — z. B. `read_wallets(env)` ruft `env.values()` auf).

**Ist-Zustand (Stichprobe):**
- `EnvFile` in `core/config.py` — `values()` liefert den Key/Value-Dict.
- `read_wallets(env: EnvFile)`, ähnliche Block-APIs: brauchen **EnvFile**, nicht Dict.
- Viele interne Helfer und Tests: erwarten bereits **`dict`** / `env.values()`.
- `_load_dotenv()` in `main` liefert **Dict**, nicht EnvFile — Verwechslung vorprogrammiert.

**Ziel:**
1. Pro öffentlicher Funktion eindeutig: Param-Name + Typ (`env: EnvFile` vs. `values: Mapping[str, str]`), Docstring eine Zeile.
2. An EnvFile-Grenzen **tolerant oder klar**: entweder `isinstance`-Normalisierung (`EnvFile` | `Mapping` → values-dict) **oder** harter TypeError mit lesbarer Meldung („EnvFile erwartet, got dict“).
3. Keine stillen `env.values()`-Aufrufe auf Objekten, die schon ein Dict sind.
4. Optional: schmaler Helfer `als_env_values(env_or_dict) -> dict[str, str]` an einer Stelle, alle Config-Leser darüber.

**Nicht:** Drive-by-Refactor aller Call-Sites ohne Nutzen; zuerst die öffentlichen Config/Wallet-Leser und die Stellen, an denen Assistenten/Tests typisch anecken.

---

## Eastereggs · SatSage-würdige Ereignis-Atemzüge

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

## Empfangen · Mempool-Lebenszeichen (Herzschlag + Wallet-Blink)

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

## Kurs-Historie · Bundle veraltet / Lücken bis „heute“ — teilweise gelöst


**Stand:** 2026-09-11 · **umgesetzt (MVP)** · **zurückgestellt** (Feinschliff im Büro)

Täglicher Job + Opt-in ``SATSAGE_PRICE_HISTORY_OPT_IN`` lädt Bitstamp/CDD bei Lücke; Overlap/Smoothing wie geplant. Bundle selbst wird nicht überschrieben (Cache darunter). Lauf **nach** GUI/„Server bereit“ (~45 s), nicht im Splash. Release-bis-Tip-Script in Builds/CI ist drin.

**Zurückgestellt bis Büro:** Live-Test hinter Firewall; UI-Texte EN durchklicken (restliche DE-Strings in `app.js` / Log).

---

## Datenquellen · Onion-Electrs zu langsam → früh BIP-158 / Abbruch

**Stand:** 2026-09-11 · **umgesetzt (MVP)** · Feinschliff offen

Latenz-Gate beim Setup öffentlicher Onion-Electrs (Auto-Priorität): Probe-`get_history`, Default 8 s (`PUBLIC_ONION_LATENCY_SECONDS`; `0` = aus). Zu langsam → BIP-158 erneut versuchen und binden; sonst Warnung „einzige Option, wird langsam“ + interaktiv Abbruch. Kein Mid-Scan-Hop; `--rpc-only` überspringt das Gate.

**Offen/Feinschliff:** Live hinter Firewall/Tor messen; optional Setup-Race BIP-158-Peer-Hunt ‖ Onion-Probe (schnelleres BIP-158-Fail).

---

## Marke · Sherlock-Satoshi-Kopf statt Sat-Symbol

**Stand:** 2026-09-11 · **umgesetzt**

Marke aus `Pfeiffe-Icon.jpg` (S/W, Schwarz = Vordergrund) → transparente `web/img/pfeiffe-icon.png` und Ableitungen (`sat-logo`, Favicon, `logo-mark`, Packaging) über `scripts/prepare_brand_assets.py`. Fallback: Splash-Ausschnitt `satsage-head.png`. Splash/Windows weiter volles `logo.jpg`.

---

## Core-Rollen · UTXO-Set vs. Tx/Block-Lookup (+ lokaler pruned Qt)

**Stand:** 2026-09-11 · **umgesetzt** (Morgen-Plan inkl. Block-Fetch)

**Ist:** `UTXO_RPC_*` vs. `NODE_IP`/`RPC*`; Still-Fill in `.env`; Bestand Electrs-LAN vor scantxoutset; Tx/Block: lokal bis `pruneheight`, darunter Lookup-Core; mit Electrs Core nur Fallback wenn Electrs die Tx nicht liefert; UI-Karten; Prefer-Peer `BIP158_HOST`.

**Feinschliff:** `AGENTS.md`/Handbuch-Prioritätstabelle; UI-Hinweis `peerblockfilters=1` am Qt.

---

## Tests · Blind spots (vs. Specter / LNbits / Jam)

**Stand:** 2026-09-10 · **teilweise** · Vergleich Python-Server + Browser-UI

Kurzanalyse: SatSage hat starke Domain-/API-Unittests und Chaos/Session-Helfer; gegenüber Specter (pytest+Cypress), LNbits (unit/api/regtest/e2e-Playwright) und Jam (Vitest+Playwright) fehlen vor allem deterministische Browser-E2E (CI-Unittest ist da).

| # | Punkt | Status |
|---|--------|--------|
| 1 | **CI: Unittest-Suite** auf Push/PR (`dev-juniormind` / `main`), nur schnelle Tests (kein Regtest/E2E/Chaos) | **umgesetzt** (Suite grün vorausgesetzt; lokal 1202 OK) |
| 2 | **Browser-E2E-Smoke** (Playwright): Spawn → Token → Kernansichten / Kopf-Pillen — deterministisch, optional CI | offen |
| 3 | **Test-Marker / Schichten** (`fast` vs. `regtest` vs. `e2e`) statt einer flachen `tests/`-Liste | offen |
| 4 | Weniger **String-Suche in `app.js`**, mehr API+DOM-Verhalten | offen |
| 5 | Stabile UI-Selektoren (`data-cy` o. Ä.) für Chaos/E2E | offen |
| 6 | Coverage-/Lint-Gates in CI (Python; JS optional ohne npm-Zwang) | offen |

Chaos-Harness und GUI-Session-Protokoll bleiben Vorsprung — nicht durch E2E ersetzen, sondern ergänzen.

---

## Web-UI · Mobile-Darstellung für Tablet

**Stand:** 2026-09-10 · **offen** · nur notiert

Desktop-GUI auf Tablet-Viewport brauchbar machen (Kopf-Pillen, Nav, Inhalt, Dock). Handy optional später — Fokus zuerst Tablet. Bisher nur schmaler Viewport-Check der Quellen-Pillen, kein Responsive-Umbau.

---

## Kopf · Pillen entschlacken (Electrs privat / öffentlich) — erledigt

**Stand:** 2026-09-10 · **umgesetzt** · UI-Kopfzeile

Nur noch aktive / Aufbau- / Fehler-Quellen plus Privatsphäre-Pille (hoch/mittel/keine); Labels Core / P2P n / Electrum privat / öffentlich. Cache-only → Privatsphäre hoch. Siehe CHANGELOG [Unveröffentlicht].

---

## Lokal Bitcoin Core erkennen (Desktop, ohne Start9/Specter)

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

## Immutable-Cache · SQLite statt Winz-JSONs (tx / utxo_ingress)

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

## Ideensammlung: CoinJoins rückverfolgen können

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
