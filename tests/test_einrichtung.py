"""
Der Einrichtungshinweis beim ersten Start.

Er zeigt für Wallets, Electrum-Server und Block-Explorer, was schon eingetragen
ist. Den Stand liest er aus der Konfigurations-API — also aus Feldern, die hier
im Python-Teil entstehen. Benennt jemand dort einen Schlüssel um, meldet der
Hinweis stillschweigend „nicht eingetragen", obwohl alles konfiguriert ist.
Genau diese Kopplung prüfen die folgenden Tests.
"""
import re
import unittest
from pathlib import Path

from core import source as source_mod
from core.config import mempool_info

WEB = Path(__file__).resolve().parent.parent / "web"


class TestVertragMitDerApi(unittest.TestCase):

    def setUp(self):
        self.js = (WEB / "app.js").read_text(encoding="utf-8")

    def test_der_electrum_schluessel_existiert_wirklich(self):
        """Die Oberfläche sucht die Quelle über ihren Schlüssel."""
        self.assertIn('q.key === "own_fulcrum"', self.js)
        schluessel = {q.key for q in source_mod.describe_sources({})}
        self.assertIn("own_fulcrum", schluessel)

    def test_uebernehmen_loest_node_test_aus(self):
        """Sonst speichert der Benutzer neue Verbindungsdaten und sieht nicht, ob sie greifen."""
        self.assertIn("testeEigenenNode", self.js)
        self.assertIn('t("sources.appliedTesting")', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("teste Verbindung", de)

    def test_electrum_hat_einen_papierkorb(self):
        """Sonst bleibt eine Onion in der .env und der Node-Test startet Tor."""
        self.assertIn("verwerfeQuelle", self.js)
        self.assertIn("papierkorb", self.js)
        self.assertIn("verwerfbar", self.js)
        self.assertIn('methode: "DELETE"', self.js)
        self.assertRegex(
            self.js,
            r'eigene\.find\(\(q\) => q\.reachable === true\)',
        )

    def test_log_flaeche_ist_standard_an(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="log-anzeige"', html)
        self.assertRegex(html, r'id="log-anzeige"[^>]*checked')
        self.assertIn('id="log-text"', html)
        self.assertIn("logZeile", self.js)
        self.assertIn("logZeitstempel", self.js)
        self.assertIn("logIstWichtig", self.js)
        self.assertIn("log-wichtig", self.js)
        self.assertIn('id="log-zieher"', html)
        self.assertIn("macheLogZiehbar", self.js)

    def test_log_flaeche_waechst_nicht_mit_dem_inhalt(self):
        """Sonst schiebt das Log die übrige Oberfläche weg."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("--log-hoehe", css)
        self.assertRegex(css, r"minmax\(0,\s*1fr\)")
        self.assertRegex(css, r"\.log-text\s*\{[^}]*overflow-y:\s*auto")
        self.assertIn(".log-zieher", css)

    def test_fusszeile_bleibt_im_fenster(self):
        """Wallet-Inhalt scrollt intern — Log und Fußzeile bleiben sichtbar."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"#app\s*\{[^}]*height:\s*100%")
        self.assertRegex(css, r"#app\s*\{[^}]*overflow:\s*hidden")
        self.assertRegex(css, r"\.inhalt\s*\{[^}]*overflow-y:\s*auto")
        self.assertRegex(css, r"\.fussleiste\s*\{[^}]*flex-shrink:\s*0")

    def test_log_hebt_nur_erfolg_und_fehler_hervor(self):
        """Fettdruck nur für Ergebniszeilen, nicht für Verbinde/Fallback."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.log-wichtig\s*\{[^}]*font-weight:\s*700")
        gefunden = re.search(
            r"function logIstWichtig\(text\) \{.*?return (/.*?/)\.test",
            self.js,
            re.S,
        )
        self.assertIsNotNone(gefunden, "logIstWichtig braucht ein Regex-Muster")
        muster = gefunden.group(1).strip("/")
        rx = re.compile(muster)
        for zeile in (
            "Verbunden. Privatsphäre: hoch",
            "Verbunden. Compact Filter 192.0.2.2:8333",
            "Verbunden. 2 Compact-Filter-Peers.",
            "Verbunden. 5 öffentliche Electrum-Peers.",
            "Wechsel: Eigener Peer verbunden → 2 Peers verbunden",
            "Neuer Peer 192.0.2.3:8333.",
            "Peer 192.0.2.1:8333 ausgefallen.",
            "Verbindung fehlgeschlagen: timeout",
            "Verbindung fehlgeschlagen 192.0.2.1:8333: nein",
            "TLS-Handshake fehlgeschlagen: WRONG_VERSION_NUMBER",
            "Port geschlossen — läuft Fulcrum, und stimmt FULCRUM_PORT?",
            "Zertifikat nicht überprüfbar — bei öffentlichen Hosts prüft SatSage "
            "streng. Heimnetz/LAN bleibt ohne CA-Prüfung; für öffentliche "
            "Self-Signed-Ziele: SATSAGE_TLS_INSECURE=1.",
            "Verbindung ohne TLS abgebrochen — der Port erwartet vermutlich SSL.",
            "Header-Cache fertig bis Block 912.345.",
            "Port 8333 wirkt blockiert (Timeout zu allen Stichproben).",
            "Filter-Treffer Block 850.123 — hole Block…",
            "Filter-Treffer Block 850.123 — False Positive",
            "Filter-Treffer Block 850.123 — +1 UTXO, 45,000 sats auf bc1qabcd…2345",
            "Nur 2 Compact-Filter-Peers — Scan wird langsamer.",
            "Nur 2 Peers verbunden.",
        ):
            self.assertTrue(rx.search(zeile), zeile)
        for zeile in (
            "Starte Verbindungstest…",
            "Filter Block 612.000–613.000…",
            "Filter Block 612.000–613.000 · 12.000/481.375 (2,5 %)",
            "Filter 481.375 Blöcke zu prüfen (481.824–963.198).",
            "Prüfe Eigener Electrum-Server…",
            "Prüfe Compact-Filter-Peers…",
            "Prüfe Port 8333 an 3 Hosts (TCP, ohne Handshake)…",
            "Port 8333 ist erreichbar.",
            "Suche P2P-Peers über DNS-Seeds…",
            "Frage DNS-Seed seed.bitcoin.sipa.be…",
            "Prüfe Tor-SOCKS 127.0.0.1:9050…",
            "Kein laufender Tor-SOCKS — suche Binary…",
            "Verbinde mit 192.0.2.1:50001 ohne TLS",
            "Verbinde mit 192.0.2.1:8333",
            "Verbinde mit 192.0.2.1:8333 über Tor",
            "Clearnet-P2P ohne Compact-Filter-Peer — versuche über Tor…",
            "Fallback: derselbe Port ohne TLS",
            "Fallback SOCKS 127.0.0.1:9150 (statt 127.0.0.1:9050)",
            "Starte Tor (tor.exe) — SOCKS 127.0.0.1:9050",
            "Tor-SOCKS 127.0.0.1:9150 (in .env: 127.0.0.1:9050)",
            "Lade Block-Header ab SegWit (Block 481.824, August 2017) — einmalig, für alle späteren Wallets.",
            "Frage Block-Header ab Höhe 481.824 (Checkpoint)…",
        ):
            self.assertFalse(rx.search(zeile), zeile)

    def test_verbindungstest_loggt_sofort_und_liest_den_strom(self):
        """Sonst bleibt das Log leer, bis Tor und Node fertig sind."""
        self.assertIn('logZeile("Starte Verbindungstest…")', self.js)
        self.assertIn("apiSourceCheck", self.js)
        self.assertIn("leseSourceCheckStream", self.js)
        self.assertIn("application/x-ndjson", self.js)

    def test_log_zeile_wallet_nur_bei_walletspezifischer_aktion(self):
        """Nach dem Timestamp der Wallet-Name — Verbindungstest bleibt ohne."""
        self.assertRegex(
            self.js,
            r"function logZeile\(text, wichtig, wallet\)",
        )
        self.assertIn("log-wallet", self.js)
        self.assertIn("log-zeit", self.js)
        self.assertIn('logZeile("Starte Verbindungstest…")', self.js)
        self.assertIn("function scanWalletName()", self.js)
        self.assertIn("undefined, wallet", self.js)
        # Wallet-Name nur bei Scan/Herkunft — Verbindungstest ohne dritten Arg.
        self.assertRegex(
            self.js,
            r'logZeile\(\s*`Starte \$\{scanArtName',
        )

    def test_wallet_nav_zeigt_cache_datum(self):
        self.assertIn('t("wallet.cacheFrom"', self.js)
        self.assertIn("cacheHinweis", self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Cache vom", de)

    def test_kopfzeile_zeigt_peer_status(self):
        self.assertIn("peerStatusAusQuellen", self.js)
        self.assertIn("peerAenderungen", self.js)
        self.assertIn("peerAenderungenFuerLog", self.js)
        self.assertIn("Nur ${neu.n}", self.js)
        self.assertIn("pruefePeersLeise", self.js)
        self.assertIn("Eigener Peer verbunden", self.js)
        self.assertIn("öffentliche Peers verbunden", self.js)
        self.assertIn("Peers verbunden", self.js)
        self.assertIn("zeichneKopfStatus", self.js)
        self.assertIn("zeichneKursPille", self.js)
        self.assertIn("ladeSpotkurs", self.js)
        self.assertIn("formatKursLabel", self.js)
        self.assertIn("KURS_TAKT_MS", self.js)
        self.assertIn("kurs-pille", self.js)
        self.assertIn("ladeKursHistorie", self.js)
        self.assertIn("starteKursImport", self.js)
        self.assertIn("liesKursCsvDatei", self.js)
        self.assertIn("formatEurAusSats", self.js)
        self.assertIn("aktualisiereFiatAnzeigen", self.js)
        self.assertIn("(≈ ${info.text})", self.js)
        self.assertIn("PEER_TAKT_RUHE_MS", self.js)
        self.assertIn("eigeneNodesBeideErreichbar", self.js)
        self.assertIn("setzePeerTakt", self.js)
        self.assertIn('t("header.sourceCore")', self.js)
        self.assertIn('t("header.sourceElectrumOwn")', self.js)
        self.assertIn('t("header.sourceElectrumPublic")', self.js)
        self.assertIn('t("header.p2pPeers"', self.js)
        self.assertIn('t("privacy.pillHigh")', self.js)
        self.assertIn('t("privacy.pillMedium")', self.js)
        self.assertIn('t("privacy.pillNone")', self.js)
        self.assertIn("kopfQuelleAufbau", self.js)
        self.assertIn("kopfQuelleFehler", self.js)
        self.assertNotIn("kopfQuelleStufe", self.js)
        self.assertIn("keine Privatsphäre", self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn('"header.sourceCore": "Core"', de)
        self.assertIn('"header.p2pPeers": "P2P {n}"', de)
        self.assertIn('"header.sourceElectrumOwn": "Electrum privat"', de)
        self.assertIn('"header.sourceElectrumPublic": "Electrum öffentlich"', de)
        self.assertIn('"privacy.pillNone": "keine Privatsphäre"', de)
        # Nach Scan: /config ohne Check darf grüne Pillen nicht rot blitzen.
        self.assertIn("function uebernehmeQuellenErreichbarkeit", self.js)
        self.assertIn("behaltePositivBeiNegativ", self.js)
        self.assertIn(
            "uebernehmeQuellenErreichbarkeit(\n    altQuellen, Zustand.config.sources",
            self.js,
        )

    def test_assistent_dock_und_pille_phase1(self):
        """Phase 1: Log|Chat-Leiste, Kopf-Pille, Einstellungen — kein Chat-Call."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn('id="dock"', html)
        self.assertIn('id="chat-pane"', html)
        self.assertIn('id="chat-anbindung"', html)
        self.assertIn('id="dock-spalter"', html)
        self.assertIn('id="llm-url"', html)
        self.assertIn('id="llm-modell"', html)
        self.assertIn('id="llm-anbieter"', html)
        self.assertIn('id="llm-remote-opt-in"', html)
        self.assertIn('id="llm-api-key"', html)
        self.assertIn('id="chat-feld"', html)
        self.assertNotIn("/chat/completions", self.js)
        self.assertIn("zeichneLlmPille", self.js)
        self.assertIn("ladeLlmStatus", self.js)
        self.assertIn('"/config/llm"', self.js)
        self.assertIn("macheDockSpalter", self.js)
        self.assertIn(".dock-spalten", css)
        self.assertIn(".chat-pane", css)
        self.assertIn(".buehne:not(.log-an)", css)

    def test_assistent_slash_phase2(self):
        """Phase 2: Slash liest Cache, startet keine Jobs, kein Completion."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r'id="chat-feld"[^>]*disabled')
        self.assertIn("parseSlash", self.js)
        self.assertIn("SLASH_BLOCK", self.js)
        self.assertIn("SLASH_BEFEHLE", self.js)
        self.assertIn("vervollstaendigeSlash", self.js)
        self.assertIn("schliesseSlashListe", self.js)
        self.assertIn('id="chat-slash"', html)
        self.assertNotIn("chat-slash-liste", html)
        self.assertIn("sendeChatZeile", self.js)
        self.assertIn('"/llm/context/luecken"', self.js)
        self.assertIn('"/llm/context/wallets"', self.js)
        self.assertIn("/llm/context/steuer", self.js)
        self.assertIn("markdown", self.js)
        self.assertIn("brief", self.js)
        self.assertIn("SLASH_BLOCK", self.js)
        self.assertIn('"scan"', self.js)
        self.assertIn('"exec"', self.js)
        self.assertIn('t("dock.blocked"', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("ist gesperrt", de)
        self.assertIn('"/llm/chat"', self.js)
        self.assertIn("frageAssistent", self.js)
        self.assertNotIn("/v1/chat/completions", self.js)

    def test_wallets_beim_start_aktualisieren_in_einstellungen(self):
        """Opt-in: Cache bis Tip nachziehen, kein Fullscan."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="start-sync"', html)
        self.assertIn('data-i18n="settings.start.sync"', html)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Wallets immer aktuell", de)
        self.assertIn("speichereStartSync", self.js)
        self.assertIn('"/config/start-sync"', self.js)
        self.assertIn("folgeWalletSyncJob", self.js)
        self.assertIn("wallets_immer_aktuell", self.js)

    def test_filter_treffer_log_wird_in_place_aktualisiert(self):
        """Ergebnis überschreibt „hole Block…“, hängt keine zweite Zeile an."""
        self.assertIn("nimmLogZeilen", self.js)
        self.assertIn("aktualisiereLogZeile", self.js)
        self.assertIn("stand.knoten", self.js)

    def test_oeffentliche_electrum_erst_nach_bestaetigung(self):
        """BIP-158 ist der Fallback — öffentliche Electrs nur nach Klick."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="oeffentliche-electrum-warnung"', html)
        self.assertIn('id="oeffentliche-electrum-nein"', html)
        self.assertIn('id="oeffentliche-electrum-ja"', html)
        self.assertIn("frageOeffentlicheElectrum", self.js)
        self.assertIn("erlaubeOeffentlicheElectrum", self.js)
        self.assertIn("lehneOeffentlicheElectrumAb", self.js)
        self.assertIn("braucht_oeffentliche", self.js)
        self.assertIn('"/source/oeffentlich"', self.js)
        self.assertIn(
            '$("#oeffentliche-electrum-nein").addEventListener', self.js
        )
        self.assertIn(
            '$("#oeffentliche-electrum-ja").addEventListener', self.js
        )

    def test_erster_xpub_ohne_node_braucht_warnung(self):
        """Sonst speichert Daddeldu still und landet auf öffentlichen Servern."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="privatsphaere-warnung"', html)
        self.assertIn('id="privatsphaere-entfernen"', html)
        self.assertIn('id="privatsphaere-ok"', html)
        self.assertIn("xpub entfernen", html)
        self.assertIn("Spiel-xPubs", html)
        self.assertIn("ersterXpubOhneSicherenNode", self.js)
        self.assertIn("own_fulcrum", self.js)
        self.assertIn("bip158", self.js)

    def test_leere_kette_heisst_keine_quelle(self):
        """Fußzeile darf Esplora nicht als aktiv ausgeben, wenn nichts gewählt ist."""
        # Leer = kind none / 0 Peers; Cache-only → Privatsphäre hoch, kein Leak.
        self.assertIn('kind: "none"', self.js)
        self.assertIn("0 Peers verbunden", self.js)
        self.assertIn('t("privacy.pillHigh")', self.js)
        self.assertNotIn("esplora", self.js.lower())
        self.assertIn("public_onion", self.js)
        self.assertRegex(
            self.js,
            r'auto\.has\(q\.key\)|auto\.includes\(q\.key\)',
        )

    def test_configured_sagt_ob_die_quelle_eingetragen_ist(self):
        leer = next(q for q in source_mod.describe_sources({})
                    if q.key == "own_fulcrum")
        gesetzt = next(q for q in source_mod.describe_sources(
            {"FULCRUM_HOST": "10.0.0.99"}) if q.key == "own_fulcrum")
        self.assertFalse(leer.as_dict()["configured"])
        self.assertTrue(gesetzt.as_dict()["configured"])
        self.assertIn("10.0.0.99", gesetzt.as_dict()["detail"])

    def test_der_explorer_meldet_configured_und_host(self):
        ohne = mempool_info("")
        mit = mempool_info("https://mempool.test.lan")
        self.assertFalse(ohne["configured"])
        self.assertTrue(mit["configured"])
        self.assertEqual(mit["host"], "mempool.test.lan")


class TestOberflaeche(unittest.TestCase):

    def setUp(self):
        self.html = (WEB / "index.html").read_text(encoding="utf-8")
        self.js = (WEB / "app.js").read_text(encoding="utf-8")
        self.css = (WEB / "style.css").read_text(encoding="utf-8")

    def test_wallet_ansicht_zeigt_ausgegeben_nur_mit_verlauf(self):
        """Zugeklappt unter den UTXOs — ohne Verlauf kein zusätzlicher Hinweis."""
        self.assertIn('id="wallet-ausgegeben"', self.html)
        self.assertIn("zeichneAusgegeben", self.js)
        self.assertRegex(
            self.js,
            r"if \(hatVerlauf\) \{\s*ausgegeben\.append\(zeichneAusgegeben",
        )

    def test_multisig_feld_erklaert_warum_kein_hinzufuegen(self):
        self.assertIn('id="deskriptor-hinweis"', self.html)
        self.assertIn('data-i18n="wallets.descriptorHint"', self.html)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Erst Adresse prüfen, dann übernehmen", de)
        self.assertIn("Cosigner vertauscht", de)
        self.assertIn("wallet-einfuegen", self.html)
        self.assertIn('id="deskriptor-import"', self.html)
        self.assertIn('data-i18n="common.import"', self.html)
        self.assertIn("Sparrow-JSON", de)
        self.assertIn("listdescriptors", de)
        self.assertIn("liesDeskriptorDatei", self.js)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(0, 1fr) 10.5rem", css)

    def test_fristen_und_stichtag_stehen_in_den_einstellungen(self):
        self.assertIn("Fristen und Stichtag", self.html)
        self.assertIn('id="steuer-stichtag"', self.html)
        self.assertIn('id="steuer-haltefrist"', self.html)
        self.assertIn('id="steuer-anschaffung"', self.html)
        self.assertIn("speichereSteuerEinstellungen", self.js)
        self.assertIn("28.02.2021", self.html)
        # Folgeanalyse: ein Knopf „Herkunftslücken schließen“ (full).
        self.assertIn('t("trace.folgeLuecken")', self.js)
        self.assertIn('t("trace.folgeDone")', self.js)
        self.assertIn('t("trace.folgeLueckenHint")', self.js)
        self.assertIn('"full"', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Herkunftslücken schließen", de)
        self.assertIn("Lücken bereits geschlossen", de)
        self.assertIn("CoinJoin/Mix", de)

    def test_handbuch_ist_verlinkt(self):
        """Handbuch nur in der Fußzeile, nicht in der Seitenleiste."""
        self.assertIn('class="fuss-handbuch"', self.html)
        self.assertIn('href="/handbuch.html"', self.html)
        self.assertEqual(self.html.count('href="/handbuch.html"'), 1)
        self.assertNotIn(
            'class="nav-eintrag" href="/handbuch.html"',
            self.html,
        )

    def test_fusszeile_zeigt_version(self):
        self.assertIn('id="fuss-version"', self.html)
        self.assertIn("function zeichneFussVersion", self.js)
        self.assertIn("Zustand.config?.version", self.js)

    def test_gekuerzte_werte_sind_kopierbar(self):
        self.assertIn("function macheKopierbar", self.js)
        self.assertIn("function kopiereInZwischenablage", self.js)
        self.assertIn("macheKopierbar(kennung, utxo.key", self.js)
        self.assertIn(".kopierbar", self.css)
        self.assertIn("cursor: copy", self.css)

    def test_bip158_fragt_startdatum_ohne_alter(self):
        self.assertIn('id="scan-datum-dialog"', self.html)
        self.assertIn("brauchtBip158Startdatum", self.js)
        self.assertIn("frageScanDatum", self.js)
        self.assertIn("2017-08-24", self.js)

    def test_danger_zone_steht_ganz_unten(self):
        self.assertIn("Danger Zone!!!!", self.html)
        self.assertIn('id="cache-leeren"', self.html)
        self.assertIn('id="cache-wallets"', self.html)
        self.assertIn("leereGesamtenCache", self.js)
        self.assertIn("leereWalletCache", self.js)
        self.assertIn("zeichneGefahrWallets", self.js)
        # Nach dem Wegfall der sticky Speichern-Leiste: Aufräumen, dann Danger.
        self.assertLess(
            self.html.find('id="cache-unreferenziert"'),
            self.html.find("Danger Zone!!!!"),
        )

    def test_verlaufsscan_steht_neben_dem_utxo_scan(self):
        self.assertIn('id="verlauf-knopf"', self.html)
        self.assertIn("Verlaufsscan", self.html)
        self.assertIn("starteVerlaufsscan", self.js)
        self.assertIn("Verlauf aller Wallets", self.html)

    def test_der_hinweis_fuehrt_zu_den_einstellungen(self):
        """Ohne diesen Weg wäre der Hinweis eine Sackgasse."""
        self.assertIn('id="einrichtung-weiter"', self.html)
        self.assertIn('oeffneVerwaltung(walletsOk ? "datenquellen" : "wallets")', self.js)

    def test_verwaltung_ist_aufgeteilt(self):
        """Wallets, Einstellungen und Datenquellen sind eigene Ansichten."""
        html = self.html
        self.assertIn('id="ansicht-wallets"', html)
        self.assertIn('id="ansicht-einstellungen"', html)
        self.assertIn('id="ansicht-datenquellen"', html)
        self.assertIn('data-ansicht="wallets"', html)
        self.assertIn('data-ansicht="datenquellen"', html)
        self.assertIn('id="nav-datenquellen"', html)
        # Reihenfolge in der Nav: Wallets, Einstellungen, Datenquellen
        i_w = html.find('data-ansicht="wallets"')
        i_e = html.find('data-ansicht="einstellungen"')
        i_d = html.find('data-ansicht="datenquellen"')
        self.assertTrue(0 < i_w < i_e < i_d)
        # Danger Zone bei Wallets, Fristen bei Einstellungen, Quellen bei Datenquellen
        w = html.find('id="ansicht-wallets"')
        e = html.find('id="ansicht-einstellungen"')
        d = html.find('id="ansicht-datenquellen"')
        self.assertTrue(w < html.find("Danger Zone!!!!") < e)
        self.assertTrue(e < html.find("Fristen und Stichtag") < d)
        self.assertTrue(d < html.find('id="quellen-liste"'))
        self.assertIn("aktualisiereDatenquellenNav", self.js)
        self.assertIn("DATENQUELLEN_NAV_WARNUNG", self.js)
        self.assertIn("nav-warn", (WEB / "style.css").read_text(encoding="utf-8"))

    def test_er_bleibt_erreichbar(self):
        """
        Einmal weggeklickt, erscheint er nicht mehr von selbst — dann muss er
        sich von Hand öffnen lassen.
        """
        self.assertIn('id="einrichtung-oeffnen"', self.html)
        self.assertIn('$("#einrichtung-oeffnen").addEventListener', self.js)

    def test_begruessung_nennt_header_download_und_electrs(self):
        """Sonst startet der erste XPUB-Scan ohne Vorwarnung in den Header-Sync."""
        self.assertIn("Block-Header", self.html)
        self.assertIn("SegWit", self.html)
        self.assertIn("August 2017", self.html)
        self.assertIn("einmalig", self.html)
        self.assertIn("electrs", self.html)
        self.assertIn("Hintergrund", self.html)
        self.assertIn("folgeHeaderJob", self.js)
        self.assertIn("sichereHeaderVorab", self.js)
        self.assertIn("header_job_id", self.js)
        self.assertIn('"/headers"', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("erspart den einmaligen Block-Header-Download", de)
        self.assertIn('t("setup.step.electrumText")', self.js)

    def test_alle_knoepfe_haben_einen_hilfetext(self):
        """Im Rest der Oberfläche hat jeder Knopf einen — hier auch."""
        start = self.html.find('id="einrichtung"')
        ende = self.html.find('id="privatsphaere-warnung"')
        self.assertGreater(start, 0)
        self.assertGreater(ende, start)
        block = self.html[start:ende]
        knoepfe = re.findall(r"<button[^>]*>", block)
        self.assertEqual(len(knoepfe), 2)
        for knopf in knoepfe:
            self.assertIn("title=", knopf)

    def test_onchain_hinweis_einmal_mit_ok(self):
        """Eigener Dialog vor der Einrichtung; Merker in der .env."""
        from core import tax
        self.assertIn('id="onchain-hinweis"', self.html)
        self.assertIn('id="einrichtung-onchain-ok"', self.html)
        self.assertIn('id="einrichtung-onchain-nicht-nochmal"', self.html)
        self.assertIn("Nicht nochmal anzeigen", self.html)
        self.assertIn(tax.HINWEIS_ONCHAIN, self.html)
        # Nicht mehr oben auf denselben Kasten wie „Erste Einrichtung“.
        onchain = self.html.find('id="onchain-hinweis"')
        einr = self.html.find('id="einrichtung"')
        self.assertGreater(onchain, 0)
        self.assertGreater(einr, onchain)
        self.assertIsNone(
            re.search(r'id="einrichtung-onchain"(?![-a-z])', self.html),
            "alter On-Chain-Kasten im Einrichtungsdialog",
        )
        self.assertIn("function bestaetigeOnchainHinweis", self.js)
        self.assertIn("function zeigeOnchainHinweis", self.js)
        self.assertIn('"/config/hinweis-onchain"', self.js)
        self.assertIn("hinweis_onchain_bestaetigt", self.js)
        self.assertIn("onchainHinweisSichtbar", self.js)
        self.assertIn("max-height: calc(100dvh - 32px)", self.css)
        self.assertIn("overflow-y: auto", self.css)

    def test_wallet_loeschung_fragt_nach_cache(self):
        """Sonst bleiben verwaiste Cache-Dateien ohne Nachfrage liegen."""
        self.assertIn("function frageCacheBeiWalletLoeschung", self.js)
        self.assertIn('"/config/wallets/cache-vorschau"', self.js)
        self.assertIn("cache_entfernte_loeschen", self.js)
        self.assertIn("window.confirm", self.js)
        self.assertIn("Zugehörigen Analyse-Cache auch löschen", self.js)

    def test_unreferenzierter_cache_steht_ueber_danger(self):
        """Aufräumen, kein Danger — nur wenn Altlasten da sind."""
        html = self.html
        i_unref = html.find('id="cache-unreferenziert"')
        i_danger = html.find("Danger Zone!!!!")
        self.assertGreater(i_unref, 0)
        self.assertGreater(i_danger, i_unref)
        self.assertNotIn('class="speicherleiste"', html)
        self.assertNotIn('id="speichern"', html)
        self.assertIn("function ladeUnreferenziertenCache", self.js)
        self.assertIn('"/cache/unreferenziert"', self.js)
        self.assertIn("loescheUnreferenziertenCache", self.js)
        self.assertIn("Unreferenzierte Cachedaten löschen", self.html)

    def test_utxo_zeit_heisst_ankunft(self):
        """Sonst liest man die Output-Zeit als Eingang beim Vor-Dienst."""
        self.assertIn("function formatAnkunft", self.js)
        self.assertIn('t("trace.arrival"', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Ankunft am:", de)
        self.assertIn("ankunft-link", self.js)
        self.assertNotIn("Herkunft →", self.js)

    def test_vollstaendige_herkunft_zeigt_juengste_sats(self):
        self.assertIn("function formatJuengsteSats", self.js)
        self.assertIn("function juengsteSatsMarke", self.js)
        self.assertIn("function juengsteSatsDerGruppe", self.js)
        self.assertIn("function merkeTraceAmUtxo", self.js)
        self.assertIn("function setzeVerfolgtMarke", self.js)
        # Frischer Trace darf das alte Stand-Datum nicht behalten.
        self.assertIn(
            "utxo.verfolgt_ts = Math.floor(Date.now() / 1000)", self.js
        )
        self.assertNotIn(
            "utxo.verfolgt_ts = utxo.verfolgt_ts ||", self.js
        )
        self.assertIn('t("trace.youngestSats"', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("jüngste sats vom", de)
        self.assertIn("verfolgt_vollstaendig", self.js)
        # Adressgruppe: jüngste sats nur für voll verfolgte UTXOs — Vorbehalt.
        self.assertIn("function gruppeOhneHerkunftstraceMarke", self.js)
        self.assertIn("ohne-herkunft-marke", self.js)
        self.assertIn("ohne Herkunftstrace", de)
        self.assertIn("haengeGruppenJuengsteAn", self.js)
        self.assertIn("function aktualisiereAdressgruppenJuengste", self.js)
        self.assertIn("gruppeAusTraceListe", self.js)
        self.assertEqual(
            self.js.count("const juengste = juengsteSatsMarke(utxo)"),
            2,
            "Marke muss in Wallet-Zeile und Herkunfts-UTXO stehen",
        )

    def test_cache_startet_offen_analyse_nicht(self):
        """Oberste Ebene zu; darunter Cache offen, ungescannte Bäume zu."""
        self.assertIn("function setzeKlapp", self.js)
        self.assertIn("function ladeGespeichertenZweig", self.js)
        self.assertIn("oeffneAusCache", self.js)
        self.assertIn('knoten.expandable ? "▾" : "·"', self.js)
        self.assertIn("Scan neu", self.js)
        self.assertNotIn("Herkunft neu", self.js)
        self.assertNotIn("Neu verfolgen", self.js)
        self.assertRegex(
            self.js,
            re.compile(
                r"function zeichneAdressGruppe\(gruppe\).*?setzeKlapp\(kopf, klapp, inhalt, false\)",
                re.S,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"function zeichneTraceAdressGruppe\(gruppe\).*?setzeKlapp\(kopf, klapp, inhalt, false\)",
                re.S,
            ),
        )
        self.assertIsNone(
            re.search(
                r"function zeichneKnoten\(knoten\) \{.*?kinder\.hidden = true",
                self.js,
                re.S,
            ),
            "Herkunftszweige dürfen nicht mehr mit hidden starten",
        )

    def test_klapp_pfeil_ist_kein_zierat(self):
        """10 px blass im Mono war unsichtbar — der Pfeil muss als Steuerung lesbar sein."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.klapp\s*\{[^}]*font-size:\s*(1[4-9]|[2-9]\d)px")
        self.assertRegex(css, r"\.klapp\s*\{[^}]*width:\s*(1[8-9]|[2-9]\d)px")
        self.assertRegex(css, r"\.klapp\s*\{[^}]*color:\s*var\(--text\)")

    def test_wallet_hat_sortierung_nach_datum(self):
        self.assertIn('id="sort-wahl"', self.html)
        self.assertIn("neueste zuerst", self.html)
        self.assertIn("sort-wahl", self.js)

    def test_sanktionskarte_steht_unten_ausser_bei_treffer(self):
        html = self.html
        pos_liste = html.find('id="adress-liste"')
        pos_sank = html.find('id="sanktions-karte"')
        self.assertGreater(pos_sank, pos_liste)
        self.assertIn("platziereSanktionsKarte", self.js);
        self.assertRegex(
            self.js,
            r"platziereSanktionsKarte\(Boolean\(befund\.treffer",
        )

    def test_scan_leiste_nennt_das_gescannte_wallet(self):
        """Sonst wirkt ein laufender Scan beim Wechsel wie der des sichtbaren Wallets."""
        self.assertIn("scanWalletId", self.js);
        self.assertIn("aktualisiereScanAnzeige", self.js);
        self.assertIn("nicht für dieses Wallet", self.js);
        self.assertIn("hinweis-fremd", self.js);

    def test_scan_schlange_ist_duenn(self):
        """Ein Klick während eines Scans stellt an, startet nicht parallel."""
        self.assertIn("stelleScanAn", self.js)
        self.assertIn("schonGeplant", self.js)
        self.assertIn("starteScanFuer", self.js)
        self.assertIn("Warteschlange", self.js)
        self.assertIn("queue_status", self.js)

    def test_wallet_hinzufuegen_speichert_sofort(self):
        """Name sichtbar vor dem Klick; Hinzufügen schreibt die .env."""
        self.assertIn('id="neuer-name"', self.html)
        self.assertIn('id="hinzufuegen"', self.html)
        self.assertIn("Aktualisieren", self.html)
        self.assertIn('class="name-uebernehmen"', self.html)
        self.assertIn("function fuegeWalletHinzu", self.js)
        self.assertIn("speichereWallets(false)", self.js)
        # Sofort speichern, nicht nur in den Entwurf schieben.
        self.assertRegex(
            self.js,
            r"function fuegeWalletHinzu\(\)[\s\S]{0,800}?speichereWallets\(false\)",
        )
        self.assertIn(
            'haken.addEventListener("click", () => speichereWallets(false))',
            self.js,
        )

    def test_drei_schritte_werden_beschrieben(self):
        abschnitt = re.search(r"function einrichtungsSchritte\(.*?\n}",
                              self.js, re.S).group(0)
        keys = re.findall(r't\("(setup\.step\.[^"]+)"', abschnitt)
        self.assertIn("setup.step.wallets", keys)
        self.assertIn("setup.step.electrum", keys)
        self.assertIn("setup.step.explorer", keys)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Wallets eintragen", de)
        self.assertIn("Eigener Electrum-Server", de)
        self.assertIn("Block-Explorer", de)

    def test_explorer_pfeil_faerbt_nach_netz(self):
        """Grün im eigenen Netz, Gelb bei öffentlichem/fremdem Explorer."""
        self.assertIn("extern-link-lokal", self.js)
        self.assertIn("extern-link-fremd", self.js)
        self.assertIn(".extern-link-lokal", self.css)
        self.assertIn(".extern-link-fremd", self.css)
        self.assertLess(
            self.css.index(".extern-link:hover"),
            self.css.index(".extern-link-lokal:hover"),
            "lokale Hover-Farbe muss die allgemeine überschreiben",
        )
        self.assertIn('t("sources.mempool.openPrivate")', self.js)
        self.assertIn('t("sources.mempool.openPublic")', self.js)
        de = (WEB / "locales" / "de.json").read_text(encoding="utf-8")
        self.assertIn("Privaten Blockexplorer öffnen", de)
        self.assertIn("Öffentlichen Blockexplorer öffnen", de)
        self.assertNotIn("in der eigenen Instanz öffnen", self.js)


if __name__ == "__main__":
    unittest.main()
