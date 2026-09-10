"""
HTTP-API.

Startet einen echten Server auf einem freien Port und spricht ihn über HTTP an
— dieselbe Strecke, die auch der Browser nimmt. Alle Daten liegen in
temporären Verzeichnissen; die echte .env wird nicht angefasst.
"""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import main
import server
from core import sanctions as sanctions_mod
from core import trace as trace_mod
from tests.fixtures import (
    BIP84_AS_XPUB,
    BIP84_RECEIVE_0,
    BIP84_ZPUB,
    ZWEITER_ALS_XPUB,
    txid,
)


def utxo(sats, adresse=BIP84_RECEIVE_0, marker="a1", vout=0):
    return {
        "txid": txid(marker),
        "vout": vout,
        "address": adresse,
        "value": sats,
        "status": {"confirmed": True, "block_height": 857_930,
                   "block_time": 1_700_000_000},
    }


class ApiTestBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)

        self.env_pfad = wurzel / ".env"
        self.env_pfad.write_text(
            "# Testkonfiguration\n"
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=Cold Storage|Ledger Alt\n"
            "SCRIPT_TYPES=auto|segwit\n"
            # Klein halten: Der Server leitet die Adressen bei jedem Aufbau neu
            # ab, und das dominiert sonst die Laufzeit der Testsuite.
            "MAX_ADDRESSES_PER_XPUB=6|6\n"
            # 192.0.2.0/24 ist laut RFC 5737 für Dokumentation reserviert und
            # wird nirgends geroutet. Sollte ein Test doch einmal eine
            # Verbindung anstoßen, landet sie garantiert im Leeren statt auf
            # einem echten Node im Netz des Benutzers.
            "FULCRUM_HOST=192.0.2.1\n"
            # Unverwechselbar: Ein gängiges Wort würde zufällig auch in
            # Feldnamen oder Hinweistexten vorkommen und die Prüfung
            # auf Preisgabe wertlos machen.
            "RPCPASSWORD=xpq-testgeheimnis-8f3a2c\n",
            encoding="utf-8",
        )
        self.cache = wurzel / "utxo_cache"
        self.cache.mkdir()
        self.immutable = wurzel / "immutable_cache"
        self.immutable.mkdir()
        # Muss gesetzt sein: ohne eigenes Verzeichnis griffe der Server auf das
        # echte sanctioned_cache/ des Projekts zu — also auf die tatsächlich
        # heruntergeladenen Listen des Benutzers.
        self.sanktionen = wurzel / "sanctioned_cache"
        self.sanktionen.mkdir()

        self.state = server.AppState(
            self.env_pfad, self.cache, self.immutable,
            sanctions_dir=self.sanktionen,
        )
        server.Handler.state = self.state

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        # poll_interval klein halten: shutdown() wartet sonst bis zu 0,5 s je
        # Test, was die Laufzeit der Suite dominiert.
        threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        ).start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)

    # -- Hilfen -------------------------------------------------------------

    def anfrage(self, pfad, *, methode="GET", daten=None, token=True, host=None):
        url = f"http://127.0.0.1:{self.port}{pfad}"
        koerper = json.dumps(daten).encode() if daten is not None else None
        req = urllib.request.Request(url, data=koerper, method=methode)
        req.add_header("Content-Type", "application/json")
        req.add_header("Host", host or f"127.0.0.1:{self.port}")
        if token:
            req.add_header("X-Satsage-Token", self.state.token)
        try:
            with urllib.request.urlopen(req, timeout=10) as antwort:
                return antwort.status, json.loads(antwort.read() or b"{}")
        except urllib.error.HTTPError as fehler:
            rohtext = fehler.read()
            try:
                return fehler.code, json.loads(rohtext or b"{}")
            except json.JSONDecodeError:
                return fehler.code, {"raw": rohtext.decode("utf-8", "replace")}

    def wallet_id(self, xpub):
        return main._xpub_cache_key(xpub)


class TestAbsicherung(ApiTestBasis):

    def test_ohne_token_abgelehnt(self):
        status, körper = self.anfrage("/api/config", token=False)
        self.assertEqual(status, 403)
        self.assertIn("Token", körper["error"])

    def test_falsches_token_abgelehnt(self):
        url = f"http://127.0.0.1:{self.port}/api/config?t=falsch"
        req = urllib.request.Request(url)
        with self.assertRaises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(fehler.exception.code, 403)

    def test_token_per_query_akzeptiert(self):
        """Der erste Aufruf aus dem Browser trägt das Token in der URL."""
        status, _ = self.anfrage(
            f"/api/config?t={self.state.token}", token=False
        )
        self.assertEqual(status, 200)

    def test_fremder_host_header_abgelehnt(self):
        """Schutz gegen DNS-Rebinding durch eine beliebige besuchte Webseite."""
        status, körper = self.anfrage("/api/config", host="boese.example.com")
        self.assertEqual(status, 403)
        self.assertIn("Host", körper["error"])

    def test_unbekannter_endpunkt(self):
        status, _ = self.anfrage("/api/gibtsnicht")
        self.assertEqual(status, 404)

    def test_statische_dateien_ohne_token(self):
        status, _ = self.anfrage("/gibtsnicht.html", token=False)
        self.assertEqual(status, 404)

    def test_kein_ausbruch_aus_dem_web_verzeichnis(self):
        status, _ = self.anfrage("/../.env", token=False)
        self.assertEqual(status, 404)

    def test_handbuch_ohne_token(self):
        url = f"http://127.0.0.1:{self.port}/handbuch.html"
        req = urllib.request.Request(url)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        with urllib.request.urlopen(req, timeout=10) as antwort:
            self.assertEqual(antwort.status, 200)
            text = antwort.read().decode("utf-8")
        self.assertIn("Handbuch", text)
        self.assertIn("SatSage", text)


class TestKonfiguration(ApiTestBasis):

    def test_wallets_werden_geliefert(self):
        status, körper = self.anfrage("/api/config")
        self.assertEqual(status, 200)
        namen = [w["name"] for w in körper["wallets"]]
        self.assertEqual(namen, ["Cold Storage", "Ledger Alt"])

    def test_xpubs_sind_maskiert(self):
        _, körper = self.anfrage("/api/config")
        roh = json.dumps(körper)
        self.assertNotIn(BIP84_ZPUB, roh)
        self.assertNotIn(ZWEITER_ALS_XPUB, roh)
        for wallet in körper["wallets"]:
            self.assertIn("…", wallet["xpub_masked"])

    def test_rpc_passwort_wird_nie_ausgeliefert(self):
        _, körper = self.anfrage("/api/config")
        self.assertNotIn("xpq-testgeheimnis-8f3a2c", json.dumps(körper))
        self.assertFalse(körper["rpc_password_set"])

    def test_skripttyp_wird_gemeldet(self):
        _, körper = self.anfrage("/api/config")
        ledger = next(w for w in körper["wallets"] if w["name"] == "Ledger Alt")
        self.assertEqual(ledger["script_type"], "segwit")
        self.assertEqual(ledger["prefix"], "xpub")

    def test_datenquellen_mit_privatsphaere(self):
        _, körper = self.anfrage("/api/config")
        quellen = {q["key"]: q for q in körper["sources"]}
        self.assertEqual(quellen["own_fulcrum"]["privacy"], "hoch")
        self.assertEqual(quellen["bip158"]["privacy"], "hoch")
        self.assertNotIn("esplora", quellen)
        self.assertTrue(quellen["own_fulcrum"]["configured"])


class TestWalletsSpeichern(ApiTestBasis):

    def test_speichern_und_zurueckgelesen(self):
        status, körper = self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [
                {"xpub": BIP84_ZPUB, "name": "Neu", "script_type": "segwit",
                 "max_addresses": 80},
            ]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])

        _, config = self.anfrage("/api/config")
        self.assertEqual([w["name"] for w in config["wallets"]], ["Neu"])
        self.assertEqual(config["wallets"][0]["max_addresses"], 80)

    def test_kommentare_und_zugangsdaten_ueberleben(self):
        self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [{"xpub": BIP84_ZPUB, "name": "Neu"}]},
        )
        text = self.env_pfad.read_text(encoding="utf-8")
        self.assertIn("# Testkonfiguration", text)
        self.assertIn("RPCPASSWORD=xpq-testgeheimnis-8f3a2c", text)

    def test_speichern_ueber_kennung_ohne_xpub(self):
        """
        Der Regelfall aus der Oberfläche: Sie kennt nur die maskierte Fassung
        und schickt deshalb die Kennung zurück. Ginge das nicht, ließe sich
        kein bestehendes Wallet je bearbeiten.
        """
        _, config = self.anfrage("/api/config")
        nutzlast = [
            {"id": w["id"], "name": w["name"], "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]}
            for w in config["wallets"]
        ]
        nutzlast[0]["name"] = "Umbenannt"
        nutzlast[0]["script_type"] = "taproot"

        status, _ = self.anfrage(
            "/api/config/wallets", methode="PUT", daten={"wallets": nutzlast}
        )
        self.assertEqual(status, 200)

        _, danach = self.anfrage("/api/config")
        self.assertEqual(danach["wallets"][0]["name"], "Umbenannt")
        self.assertEqual(danach["wallets"][0]["script_type"], "taproot")

    def test_speichern_ueber_kennung_erhaelt_den_schluessel(self):
        """Der XPUB darf beim Umbenennen nicht verloren gehen."""
        _, config = self.anfrage("/api/config")
        vorher = config["wallets"][0]["xpub_masked"]
        self.anfrage("/api/config/wallets", methode="PUT", daten={"wallets": [
            {"id": w["id"], "name": w["name"]} for w in config["wallets"]
        ]})
        _, danach = self.anfrage("/api/config")
        self.assertEqual(danach["wallets"][0]["xpub_masked"], vorher)
        self.assertIn(BIP84_ZPUB, self.env_pfad.read_text(encoding="utf-8"))

    def test_unbekannte_kennung_wird_abgelehnt(self):
        status, körper = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": [{"id": "gibtsnicht", "name": "X"}]},
        )
        self.assertEqual(status, 400)
        self.assertIn("Kennung", körper["error"])

    def test_ungueltiger_xpub_wird_abgelehnt(self):
        status, körper = self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [{"xpub": "kein-xpub", "name": "X"}]},
        )
        self.assertEqual(status, 400)
        self.assertIn("gültiger", körper["error"])

    def test_abgelehnte_eingabe_veraendert_die_datei_nicht(self):
        vorher = self.env_pfad.read_text(encoding="utf-8")
        self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [{"xpub": "unsinn", "name": "X"}]},
        )
        self.assertEqual(self.env_pfad.read_text(encoding="utf-8"), vorher)

    def test_gleicher_schluessel_verlangt_bestaetigung(self):
        """
        Dasselbe Konto als zpub und als xpub: 409 statt 400 — die Oberfläche
        zeigt die Folge und bietet „Trotzdem speichern“ an.
        """
        status, körper = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": [
                {"xpub": BIP84_ZPUB, "name": "Cold Storage"},
                {"xpub": BIP84_AS_XPUB, "name": "Ledger Alt",
                 "script_type": "segwit"},
            ]},
        )
        self.assertEqual(status, 409)
        self.assertIn("doppelt", körper["error"])
        self.assertIn("Cold Storage", körper["error"])

    def test_mit_bestaetigung_wird_gespeichert(self):
        status, _ = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"confirm": True, "wallets": [
                {"xpub": BIP84_ZPUB, "name": "Cold Storage"},
                {"xpub": BIP84_AS_XPUB, "name": "Ledger Alt",
                 "script_type": "segwit"},
            ]},
        )
        self.assertEqual(status, 200)
        _, config = self.anfrage("/api/config")
        self.assertEqual(len(config["wallets"]), 2)

    def test_mehrere_konten_aus_einem_seed_ohne_rueckfrage(self):
        """
        Der Praxisfall: mehrere Konten desselben Seeds. Sie haben
        unterschiedliche Schlüssel und dürfen nicht beanstandet werden.
        """
        from embit import bip32, bip39

        seed = bip39.mnemonic_to_seed(
            "abandon abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon about"
        )
        wurzel = bip32.HDKey.from_seed(seed)
        wallets = [
            {"xpub": wurzel.derive(pfad).to_public().to_string(
                version=b"\x04\x88\xb2\x1e"),
             "name": f"Konto {i}", "script_type": "segwit", "max_addresses": 4}
            for i, pfad in enumerate(("m/84h/0h/0h", "m/84h/0h/1h", "m/84h/0h/2h"))
        ]
        status, körper = self.anfrage(
            "/api/config/wallets", methode="PUT", daten={"wallets": wallets}
        )
        self.assertEqual(status, 200, körper.get("error"))
        self.assertEqual(körper["wallet_count"], 3)

    def test_doppelter_name_wird_abgelehnt(self):
        status, körper = self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [
                {"xpub": BIP84_ZPUB, "name": "Gleich"},
                {"xpub": ZWEITER_ALS_XPUB, "name": "Gleich"},
            ]},
        )
        self.assertEqual(status, 400)
        self.assertIn("mehrfach", körper["error"])

    def test_fehlendes_feld(self):
        status, _ = self.anfrage("/api/config/wallets", methode="PUT", daten={})
        self.assertEqual(status, 400)

    def test_kaputtes_json(self):
        url = f"http://127.0.0.1:{self.port}/api/config/wallets"
        req = urllib.request.Request(url, data=b"{kaputt", method="PUT")
        req.add_header("X-Satsage-Token", self.state.token)
        with self.assertRaises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(fehler.exception.code, 400)


class TestUtxoListe(ApiTestBasis):

    def test_ohne_cache(self):
        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertEqual(status, 200)
        self.assertFalse(körper["has_cache"])
        self.assertEqual(körper["utxos"], [])

    def test_mit_cache(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000), utxo(124_500, marker="b2")],
            self.cache, 50,
        )
        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertEqual(status, 200)
        self.assertTrue(körper["has_cache"])
        self.assertEqual(körper["total_count"], 2)
        self.assertEqual(körper["total_sats"], 84_124_500)
        self.assertEqual(körper["utxos"][0]["value_sats"], 84_000_000)

    def test_limit(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(500), utxo(9000, marker="b2"), utxo(70, marker="c3")],
            self.cache, 50,
        )
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos?limit=1")
        self.assertEqual(körper["shown_count"], 1)
        self.assertEqual(körper["total_count"], 3)

    def test_unbekanntes_wallet(self):
        status, _ = self.anfrage("/api/wallets/gibtsnicht/utxos")
        self.assertEqual(status, 404)

    def test_ohne_verlauf_kein_ausgegeben_block(self):
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertFalse(körper["hat_verlauf"])
        self.assertEqual(körper["verlauf"]["total_count"], 0)

    def test_verlauf_liefert_ausgegebene_dieses_wallets(self):
        """Steuerjahr und Herkunft lesen dieselbe Datei — die Wallet-Ansicht auch."""
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        main.save_xpub_verlauf_cache(BIP84_ZPUB, [
            {
                "txid": txid("a1"), "vout": 0, "address": BIP84_RECEIVE_0,
                "value": 84_000_000,
                "status": {"confirmed": True, "block_time": 1_700_000_000},
                "spent": False, "spent_txid": None,
            },
            {
                "txid": txid("c3"), "vout": 0, "address": BIP84_RECEIVE_0,
                "value": 50_000,
                "status": {"confirmed": True, "block_time": 1_600_000_000},
                "spent": True, "spent_txid": txid("ff"),
                "spent_time_ts": 1_650_000_000,
            },
        ], self.cache)
        main.save_xpub_verlauf_cache(ZWEITER_ALS_XPUB, [
            {
                "txid": txid("d4"), "vout": 0, "value": 9_000_000,
                "spent": True, "spent_txid": txid("ee"),
                "spent_time_ts": 1_660_000_000,
            },
        ], self.cache)

        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertEqual(status, 200, körper)
        self.assertTrue(körper["hat_verlauf"])
        self.assertEqual(körper["verlauf"]["total_count"], 1)
        self.assertEqual(körper["verlauf"]["utxos"][0]["value_sats"], 50_000)
        self.assertTrue(körper["verlauf"]["utxos"][0]["spent"])


class TestVerlaufJob(ApiTestBasis):
    """Zweiter Einstieg in denselben Verlaufs-Cache — ein Wallet oder alle."""

    def test_unbekanntes_wallet(self):
        status, _ = self.anfrage(
            "/api/verlauf", methode="POST", daten={"wallet_id": "gibtsnicht"},
        )
        self.assertEqual(status, 404)

    def test_einzelnes_wallet_steht_im_label(self):
        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(
            "/api/verlauf", methode="POST", daten={"wallet_id": kennung},
        )
        self.assertEqual(status, 202)
        self.assertIn("Cold Storage", körper["label"])
        self.assertNotIn("Ledger", körper["label"])
        self.assertIn("log", körper)

    def test_ohne_id_trifft_alle_wallets(self):
        status, körper = self.anfrage("/api/verlauf", methode="POST", daten={})
        self.assertEqual(status, 202)
        self.assertIn("aller Wallets", körper["label"])


class TestAlleUtxos(ApiTestBasis):
    """Einstieg der Herkunftsansicht — alle Wallets zusammen, aus dem Cache."""

    def test_leer_wenn_nichts_gescannt(self):
        status, körper = self.anfrage("/api/utxos")
        self.assertEqual(status, 200)
        self.assertEqual(körper["total_count"], 0)
        self.assertEqual(len(körper["wallets_ohne_cache"]), 2)

    def test_utxos_beider_wallets(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        zweit = sorted(main.derive_addresses(
            ZWEITER_ALS_XPUB, 4, script_type="segwit"))[0]
        main.save_xpub_utxo_cache(
            ZWEITER_ALS_XPUB, [utxo(61_200, zweit, marker="d4")], self.cache, 6
        )

        _, körper = self.anfrage("/api/utxos")
        self.assertEqual(körper["total_count"], 2)
        self.assertEqual(körper["total_sats"], 84_061_200)
        self.assertEqual(körper["wallets_ohne_cache"], [])

    def test_wallet_zuordnung_je_utxo(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        _, körper = self.anfrage("/api/utxos")
        self.assertEqual(körper["utxos"][0]["wallet"], "Cold Storage")

    def test_kennung_taugt_als_trace_ziel(self):
        """
        Die Oberfläche reicht diesen Wert unverändert an /api/trace weiter.

        Geprüft wird hier nur das Format — ein echter Aufruf würde einen Job
        starten, der eine Verbindung zur Datenquelle aufbaut. Dass parse_ziel
        die Kennung annimmt, deckt tests/test_utxo_ranking.py offline ab.
        """
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1", vout=2)], self.cache, 6
        )
        _, körper = self.anfrage("/api/utxos")
        schluessel = körper["utxos"][0]["key"]
        self.assertEqual(schluessel, f"{txid('a1')}:2")
        self.assertIsNotNone(trace_mod.parse_ziel(schluessel))

    def test_adressgruppierung_fuer_die_herkunftsansicht(self):
        """
        Die Herkunftsansicht gruppiert nach Adressen. Serverseitig liefert
        rank_wallet_utxos das bereits mit — hier festgehalten, damit es beim
        Umbau nicht verloren geht.
        """
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000, marker="a1"),
            utxo(124_500, marker="c3", vout=1),
        ], self.cache, 6)

        _, körper = self.anfrage("/api/utxos")
        self.assertIn("addresses", körper)
        self.assertEqual(len(körper["addresses"]), 1)

        gruppe = körper["addresses"][0]
        self.assertEqual(gruppe["utxo_count"], 2)
        self.assertEqual(gruppe["total_sats"], 84_124_500)

    def test_gruppierung_enthaelt_dieselben_utxos_wie_die_flache_liste(self):
        """
        Sonst zeigte die Ansicht weniger an, als tatsächlich vorhanden ist.
        """
        zweit = sorted(main.derive_addresses(
            ZWEITER_ALS_XPUB, 4, script_type="segwit"))[0]
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000, marker="a1"),
            utxo(124_500, marker="c3", vout=1),
        ], self.cache, 6)
        main.save_xpub_utxo_cache(
            ZWEITER_ALS_XPUB, [utxo(61_200, zweit, marker="d4")], self.cache, 6
        )

        _, körper = self.anfrage("/api/utxos")
        flach = {u["key"] for u in körper["utxos"]}
        gruppiert = {
            u["key"] for g in körper["addresses"] for u in g["utxos"]
        }
        self.assertEqual(flach, gruppiert)
        self.assertEqual(len(flach), 3)

    def test_jede_gruppe_nennt_ihr_wallet(self):
        """Die Ansicht zeigt das Wallet am Gruppenkopf."""
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        _, körper = self.anfrage("/api/utxos")
        self.assertEqual(körper["addresses"][0]["wallet"], "Cold Storage")

    def test_keine_xpubs_in_der_antwort(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        _, körper = self.anfrage("/api/utxos")
        roh = json.dumps(körper)
        self.assertNotIn(BIP84_ZPUB, roh)
        self.assertNotIn(ZWEITER_ALS_XPUB, roh)


class TestAdressgruppen(ApiTestBasis):

    def test_wallet_antwort_enthaelt_adressgruppen(self):
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000, marker="a1"),
            utxo(124_500, marker="c3", vout=1),
        ], self.cache, 6)

        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertIn("addresses", körper)
        self.assertEqual(len(körper["addresses"]), 1)

        gruppe = körper["addresses"][0]
        self.assertEqual(gruppe["address"], BIP84_RECEIVE_0)
        self.assertEqual(gruppe["utxo_count"], 2)
        self.assertEqual(gruppe["total_sats"], 84_124_500)

    def test_jede_gruppe_liefert_ihre_utxos_mit_kennung(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        utxos = körper["addresses"][0]["utxos"]
        self.assertEqual(len(utxos), 1)
        self.assertEqual(utxos[0]["key"], f"{txid('a1')}:0")


class TestDatenquellenBearbeiten(ApiTestBasis):

    def quellen(self):
        _, körper = self.anfrage("/api/config")
        return {q["key"]: q for q in körper["sources"]}

    def test_bearbeitbare_quellen_bringen_ihre_felder_mit(self):
        quellen = self.quellen()
        self.assertTrue(quellen["own_fulcrum"]["editierbar"])
        schluessel = [f["key"] for f in quellen["own_fulcrum"]["felder"]]
        self.assertIn("FULCRUM_HOST", schluessel)
        self.assertIn("FULCRUM_PORT", schluessel)

    def test_clearnet_ist_nicht_bearbeitbar(self):
        """Die Liste kommt aus electrum_servers.json, nicht aus der .env."""
        self.assertFalse(self.quellen()["clearnet"]["editierbar"])

    def test_config_liefert_header_job_id(self):
        _, körper = self.anfrage("/api/config")
        self.assertIn("header_job_id", körper)
        self.assertIn("header_tip", körper)
        self.assertIsNone(körper["header_job_id"])

    def test_header_vorab_legt_einen_job_an(self):
        with mock.patch(
            "bip158_scanner.vorab_block_header", return_value=900_000,
        ):
            server.starte_header_vorab(self.state)
        self.assertTrue(self.state.header_job_id)
        job = None
        for _ in range(80):
            job = self.state.jobs.get(self.state.header_job_id)
            if job and job.status != "running":
                break
            time.sleep(0.05)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result["tip"], 900_000)

    def test_header_vorab_laeuft_trotz_wallet_wenn_cache_leer(self):
        """Wallet im Cache ändert nichts — ohne Header-Datei muss geladen werden."""
        self.assertTrue(self.state.entries)
        with mock.patch(
            "bip158_scanner.vorab_block_header", return_value=850_000,
        ) as vorab:
            server.starte_header_vorab(self.state, nur_wenn_leer=True)
        self.assertTrue(self.state.header_job_id)
        for _ in range(80):
            job = self.state.jobs.get(self.state.header_job_id)
            if job and job.status != "running":
                break
            time.sleep(0.05)
        vorab.assert_called()

    def test_header_vorab_nicht_doppelt_solange_laufend(self):
        def langsam(*_a, **_k):
            time.sleep(0.4)
            return 900_000

        with mock.patch("bip158_scanner.vorab_block_header", side_effect=langsam):
            server.starte_header_vorab(self.state)
            erste = self.state.header_job_id
            server.starte_header_vorab(self.state, nur_wenn_leer=True)
            self.assertEqual(self.state.header_job_id, erste)

    def test_post_headers_startet_job(self):
        with mock.patch(
            "bip158_scanner.vorab_block_header", return_value=900_000,
        ):
            status, körper = self.anfrage("/api/headers", methode="POST")
        self.assertEqual(status, 202)
        self.assertTrue(körper["header_job_id"])

    def test_p2p_bip158_hat_keine_rpc_felder(self):
        felder = {f["key"]: f for f in self.quellen()["bip158"]["felder"]}
        self.assertIn("BIP158_START_HEIGHT", felder)
        self.assertNotIn("RPCPASSWORD", felder)
        self.assertNotIn("NODE_IP", felder)

    def test_speichern_und_zuruecklesen(self):
        status, körper = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "own_fulcrum", "values": {
                "FULCRUM_HOST": "192.0.2.50", "FULCRUM_PORT": "50001",
                "FULCRUM_SSL": "false",
            }},
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])

        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["FULCRUM_HOST"], "192.0.2.50")
        self.assertEqual(werte["FULCRUM_PORT"], "50001")
        self.assertEqual(werte["FULCRUM_SSL"], "false")

    def test_p2p_starthoehe_wird_gespeichert(self):
        status, _ = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "bip158", "values": {"BIP158_START_HEIGHT": "481824"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            main._load_dotenv(self.env_pfad)["BIP158_START_HEIGHT"], "481824"
        )

    def test_fremdes_feld_wird_abgelehnt(self):
        """
        Die Positivliste ist der eigentliche Schutz: Ohne sie wäre der
        Endpunkt ein Schreibzugriff auf beliebige .env-Einträge — auch XPUBS.
        """
        status, körper = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "own_fulcrum", "values": {"XPUBS": "zpub6BOESE"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("gehört nicht", körper["error"])
        self.assertNotIn("zpub6BOESE", self.env_pfad.read_text(encoding="utf-8"))

    def test_unbekannte_quelle_wird_abgelehnt(self):
        status, _ = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "clearnet", "values": {"X": "1"}},
        )
        self.assertEqual(status, 400)

    def test_port_muss_eine_zahl_sein(self):
        status, körper = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "own_fulcrum", "values": {"FULCRUM_PORT": "abc"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("Zahl", körper["error"])

    def test_onion_liste_wird_auf_indizes_abgebildet(self):
        self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "public_onion", "values": {
                "FULCRUM_TOR_LISTE": "aaa.onion\nbbb.onion\n\nccc.onion\n",
            }},
        )
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["FULCRUM_TOR_0"], "aaa.onion")
        self.assertEqual(werte["FULCRUM_TOR_1"], "bbb.onion")
        self.assertEqual(werte["FULCRUM_TOR_2"], "ccc.onion")
        self.assertNotIn("FULCRUM_TOR_3", werte)

    def test_onion_liste_kuerzen_entfernt_die_ueberzaehligen(self):
        for liste in ("a.onion\nb.onion\nc.onion", "a.onion"):
            self.anfrage(
                "/api/config/source", methode="PUT",
                daten={"source": "public_onion",
                       "values": {"FULCRUM_TOR_LISTE": liste}},
            )
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["FULCRUM_TOR_0"], "a.onion")
        self.assertNotIn("FULCRUM_TOR_1", werte)

    def test_zu_viele_onions(self):
        status, _ = self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "public_onion", "values": {
                "FULCRUM_TOR_LISTE": "\n".join(f"{i}.onion" for i in range(15)),
            }},
        )
        self.assertEqual(status, 400)

    def test_kommentare_und_wallets_ueberleben(self):
        self.anfrage(
            "/api/config/source", methode="PUT",
            daten={"source": "own_fulcrum", "values": {"FULCRUM_HOST": "192.0.2.9"}},
        )
        text = self.env_pfad.read_text(encoding="utf-8")
        self.assertIn("# Testkonfiguration", text)
        self.assertIn(BIP84_ZPUB, text)

    def test_electrum_server_heisst_nicht_mehr_fulcrum(self):
        """
        Jede Implementierung des Electrum-Protokolls funktioniert — Fulcrum
        ist nur eine davon. Die .env-Schlüssel bleiben trotzdem FULCRUM_*,
        damit bestehende Konfigurationen weiterlaufen.
        """
        quelle = self.quellen()["own_fulcrum"]
        self.assertEqual(quelle["name"], "Eigener Electrum-Server")
        self.assertIn("FULCRUM_HOST", [f["key"] for f in quelle["felder"]])

    def test_oeffentliche_quellen_bieten_electrum_laden(self):
        quellen = self.quellen()
        for key, art in (("public_onion", "onion"), ("clearnet", "clearnet")):
            self.assertEqual(quellen[key]["laden_filter"], art)
            self.assertIn("githubusercontent.com", quellen[key]["laden_url"])
        self.assertEqual(quellen["own_fulcrum"]["laden_url"], "")

    def test_electrum_laden_lehnt_unbekannten_filter_ab(self):
        status, körper = self.anfrage(
            "/api/config/electrum-servers",
            methode="POST", daten={"filter": "esplora"},
        )
        self.assertEqual(status, 400)
        self.assertIn("filter", körper["error"])

    def test_electrum_verwerfen_entfernt_host(self):
        status, körper = self.anfrage(
            "/api/config/source/own_fulcrum", methode="DELETE",
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertNotIn("FULCRUM_HOST", main._load_dotenv(self.env_pfad))
        nach_key = {q["key"]: q for q in körper["sources"]}
        self.assertFalse(nach_key["own_fulcrum"]["configured"])
        self.assertFalse(nach_key["own_fulcrum"]["verwerfbar"])

    def test_p2p_laesst_sich_ausschalten(self):
        status, körper = self.anfrage("/api/config/source/bip158", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertEqual(körper["cleared"], "bip158")
        # Wie manuelle Checkbox: false in .env, Feld und configured aus.
        self.assertEqual(
            main._load_dotenv(self.env_pfad).get("BIP158_P2P"), "false",
        )
        nach_key = {q["key"]: q for q in körper["sources"]}
        self.assertFalse(nach_key["bip158"]["configured"])
        self.assertFalse(nach_key["bip158"]["verwerfbar"])
        felder = {f["key"]: f for f in nach_key["bip158"]["felder"]}
        self.assertEqual(felder["BIP158_P2P"]["value"], "false")
        # GET /config darf P2P nicht wieder als an zeigen.
        status2, cfg = self.anfrage("/api/config")
        self.assertEqual(status2, 200)
        bip = next(q for q in cfg["sources"] if q["key"] == "bip158")
        self.assertFalse(bip["configured"])
        self.assertEqual(
            next(f["value"] for f in bip["felder"] if f["key"] == "BIP158_P2P"),
            "false",
        )

    def test_p2p_aufbauen_schalter_schreibt_env(self):
        status, körper = self.anfrage(
            "/api/config/source",
            methode="PUT",
            daten={
                "source": "bip158",
                "values": {
                    "BIP158_P2P": "false",
                    "BIP158_START_HEIGHT": "481824",
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            main._load_dotenv(self.env_pfad).get("BIP158_P2P"), "false",
        )
        nach_key = {q["key"]: q for q in körper["sources"]}
        self.assertFalse(nach_key["bip158"]["configured"])
        # Checkbox-Feld ist im Formular.
        felder = {f["key"]: f for f in nach_key["bip158"]["felder"]}
        self.assertEqual(felder["BIP158_P2P"]["typ"], "checkbox")
        self.assertEqual(felder["BIP158_P2P"]["value"], "false")

    def test_unbekannte_quelle_laesst_sich_nicht_loeschen(self):
        status, körper = self.anfrage(
            "/api/config/source/mempool", methode="DELETE",
        )
        self.assertEqual(status, 400)
        self.assertIn("verworfen", körper["error"])

    def test_oeffentliche_onion_liste_laesst_sich_loeschen(self):
        self.anfrage(
            "/api/config/source",
            methode="PUT",
            daten={
                "source": "public_onion",
                "values": {"FULCRUM_TOR_LISTE": "aaa.onion\nbbb.onion\n"},
            },
        )
        vor = main._load_dotenv(self.env_pfad)
        self.assertEqual(vor.get("FULCRUM_TOR_0"), "aaa.onion")
        status, körper = self.anfrage(
            "/api/config/source/public_onion", methode="DELETE",
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertEqual(körper["cleared"], "public_onion")
        nach = main._load_dotenv(self.env_pfad)
        self.assertNotIn("FULCRUM_TOR_0", nach)
        self.assertNotIn("FULCRUM_TOR_1", nach)
        # Opt-in und Proxy bleiben unberührt, wenn gesetzt.
        nach_key = {q["key"]: q for q in körper["sources"]}
        self.assertFalse(nach_key["public_onion"]["configured"])

    def test_clearnet_liste_laesst_sich_loeschen(self):
        ziel = Path(self._tmp.name) / "electrum_servers.json"
        ziel.write_text('{"s1.example": {"t": "50001"}}', encoding="utf-8")
        with mock.patch.object(main, "ELECTRUM_SERVERS_FILE", ziel):
            self.assertTrue(ziel.is_file())
            status, körper = self.anfrage(
                "/api/config/source/clearnet", methode="DELETE",
            )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertEqual(körper["cleared"], "clearnet")
        self.assertFalse(ziel.is_file())
        nach_key = {q["key"]: q for q in körper["sources"]}
        self.assertFalse(nach_key["clearnet"]["configured"])

    def test_source_status_ohne_check_bleibt_json(self):
        status, körper = self.anfrage("/api/source/status")
        self.assertEqual(status, 200)
        self.assertIn("sources", körper)
        self.assertIn("peers", körper)
        self.assertTrue(any(q["key"] == "own_fulcrum" for q in körper["sources"]))

    def test_oeffentliche_electrum_bestaetigung_schreibt_env(self):
        self.assertNotIn(
            "OEFFENTLICHE_ELECTRUM", main._load_dotenv(self.env_pfad)
        )
        status, körper = self.anfrage(
            "/api/source/oeffentlich",
            methode="POST",
            daten={"erlauben": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertTrue(körper["erlaubt"])
        self.assertEqual(
            main._load_dotenv(self.env_pfad).get("OEFFENTLICHE_ELECTRUM"), "1"
        )

    def test_source_status_streamt_log_zeilen(self):
        """Die Oberfläche soll Zeilen sehen, bevor die Prüfung fertig ist."""
        from dataclasses import replace

        def fake_check(info, values, *, timeout=5, on_log=None):
            zeilen = []
            if info.configured and info.key == "own_fulcrum":
                zeilen.append("Prüfe Eigener Electrum-Server…")
                if on_log:
                    on_log(zeilen[-1])
                zeilen.append("Verbindung fehlgeschlagen: timeout")
                if on_log:
                    on_log(zeilen[-1])
                return replace(info, reachable=False, error="timeout", log=zeilen)
            return replace(info, log=[])

        url = f"http://127.0.0.1:{self.port}/api/source/status?check=1"
        req = urllib.request.Request(url)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        req.add_header("X-Satsage-Token", self.state.token)
        req.add_header("Accept", "application/x-ndjson")
        with mock.patch("server.source_mod.check_reachable", side_effect=fake_check), \
             mock.patch("core.p2p.zaehle_compact_filter_peers", return_value=[]), \
             mock.patch("core.p2p.stelle_p2p_tor_bereit", return_value=None), \
             mock.patch(
                 "core.source._pruefe_oeffentliche_electrum",
                 side_effect=lambda gefunden, *a, **k: gefunden,
             ):
            with urllib.request.urlopen(req, timeout=10) as antwort:
                typ = antwort.headers.get("Content-Type") or ""
                roh = antwort.read().decode("utf-8")
        self.assertIn("ndjson", typ)
        objekte = [json.loads(z) for z in roh.splitlines() if z.strip()]
        logs = [o["log"] for o in objekte if "log" in o]
        self.assertIn("Prüfe Eigener Electrum-Server…", logs)
        self.assertTrue(any("sources" in o for o in objekte))

    def test_electrum_laden_onion_schreibt_nur_onions(self):
        daten = {
            "zzz.onion": {"s": "50002"},
            "aaa.onion": {"t": "50001"},
            "clear.example": {"s": "50002"},
        }

        def fake(dest, url=None):
            Path(dest).write_text(json.dumps(daten), encoding="utf-8")
            return daten

        ziel = Path(self._tmp.name) / "electrum_servers.json"
        with mock.patch(
            "check_fulcrum_tor.fetch_electrum_servers_json", side_effect=fake
        ), mock.patch.object(main, "ELECTRUM_SERVERS_FILE", ziel):
            status, körper = self.anfrage(
                "/api/config/electrum-servers",
                methode="POST", daten={"filter": "onion"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(körper["count"], 2)
        self.assertIn("Onion", körper["message"])
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["FULCRUM_TOR_0"], "aaa.onion")
        self.assertEqual(werte["FULCRUM_PORT_0"], "50001")
        self.assertEqual(werte["FULCRUM_SSL_0"], "false")
        self.assertEqual(werte["FULCRUM_TOR_1"], "zzz.onion")
        self.assertEqual(werte["FULCRUM_SSL_1"], "true")
        self.assertNotIn("FULCRUM_TOR_2", werte)

    def test_electrum_laden_clearnet_laesst_onion_env_in_ruhe(self):
        self.env_pfad.write_text(
            self.env_pfad.read_text(encoding="utf-8") + "FULCRUM_TOR_0=keep.onion\n",
            encoding="utf-8",
        )
        daten = {
            "n.onion": {"s": "50002"},
            "a.example": {"s": "50002"},
            "b.example": {"t": "50001"},
        }

        def fake(dest, url=None):
            Path(dest).write_text(json.dumps(daten), encoding="utf-8")
            return daten

        ziel = Path(self._tmp.name) / "electrum_servers.json"
        with mock.patch(
            "check_fulcrum_tor.fetch_electrum_servers_json", side_effect=fake
        ), mock.patch.object(main, "ELECTRUM_SERVERS_FILE", ziel):
            status, körper = self.anfrage(
                "/api/config/electrum-servers",
                methode="POST", daten={"filter": "clearnet"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(körper["count"], 2)
        self.assertIn("Clearnet", körper["message"])
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte.get("FULCRUM_TOR_0"), "keep.onion")


class TestSanktionen(ApiTestBasis):

    def test_status_ohne_listen(self):
        """
        Ohne Listen muss der Zustand eindeutig sein: `vorhanden` false, und
        kein Hinweis, der einen stattgefundenen Abgleich nahelegt. Den Satz
        „ohne Listen ist ein leeres Ergebnis kein Freibrief" setzt die
        Oberfläche selbst — hier ginge er als Dopplung durch.
        """
        status, körper = self.anfrage("/api/sanctions")
        self.assertEqual(status, 200)
        self.assertFalse(körper["vorhanden"])
        self.assertNotIn("geprüft", " ".join(körper["hinweise"]))

    def test_status_mit_listen(self):
        import json as _json

        (self.sanktionen / "sanctioned_addresses_XBT.json").write_text(
            _json.dumps(["1BoatSLRHtKNngkdXEeobR76b53LETtpyT"]), encoding="utf-8"
        )

        _, körper = self.anfrage("/api/sanctions")
        self.assertTrue(körper["vorhanden"])
        self.assertEqual(körper["adressen"], 1)

    def test_wallet_antwort_traegt_den_befund(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertIn("sanctions", körper)
        self.assertIn("geprueft", körper["sanctions"])

    def test_utxos_tragen_das_markierungsfeld(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(f"/api/wallets/{kennung}/utxos")
        self.assertIn("flagged", körper["utxos"][0])

    def test_gesamtliste_traegt_den_befund(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )
        _, körper = self.anfrage("/api/utxos")
        self.assertIn("sanctions", körper)


class TestSanktionsCheck(ApiTestBasis):
    """
    POST /api/sanctions/check — der Job hinter dem Sanktionscheck der
    Oberfläche.

    Die Serverwahl ist hier durchgehend gefälscht. Ohne das griffe der Job
    auf resolve_sanctions_preferred_pool durch: Der lädt electrum_servers.json
    aus dem Electrum-Repo nach und baut Verbindungen zu bis zu acht
    öffentlichen Servern auf — aus einem Unit-Test heraus, in einem Projekt,
    dessen ganzer Zweck es ist, solche Abfragen unter Kontrolle zu halten.
    """

    def setUp(self):
        super().setUp()
        # Kein Server erreichbar — die Fehlerpfade sind genau das, was diese
        # Klasse prüft.
        patcher = mock.patch.object(
            main, "resolve_sanctions_preferred_pool",
            side_effect=lambda env: (None, "none", False),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def warte_auf_job(self, job_id, timeout_s=30):
        import time

        schluss = time.time() + timeout_s
        while time.time() < schluss:
            _, job = self.anfrage(f"/api/jobs/{job_id}")
            if not job["running"]:
                return job
            time.sleep(0.05)
        self.fail(f"Job {job_id} lief nicht zu Ende")

    def listen_hinterlegen(self, adressen=("1BoatSLRHtKNngkdXEeobR76b53LETtpyT",)):
        (self.sanktionen / "sanctioned_addresses_XBT.json").write_text(
            json.dumps(list(adressen)), encoding="utf-8"
        )

    def test_ohne_listen_meldet_der_job_den_fehler(self):
        status, körper = self.anfrage(
            "/api/sanctions/check", methode="POST", daten={"max_hops": 2}
        )
        self.assertEqual(status, 202)
        job = self.warte_auf_job(körper["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("Sanktionslisten", job["error"])

    def test_unbekanntes_wallet_wird_abgelehnt(self):
        status, _ = self.anfrage(
            "/api/sanctions/check", methode="POST",
            daten={"wallet_id": "gibtsnicht"},
        )
        self.assertEqual(status, 404)

    def test_max_hops_wird_begrenzt(self):
        from core.sanctions import DEFAULT_SANKTION_MAX_HOPS_CAP

        self.listen_hinterlegen()
        status, körper = self.anfrage(
            "/api/sanctions/check", methode="POST", daten={"max_hops": 99}
        )
        self.assertEqual(status, 202)
        job = self.warte_auf_job(körper["id"])
        # Ohne erreichbaren Sanktions-Server scheitert der Lauf — aber das
        # Job-Label zeigt: die Hops wurden auf den Cap gedeckelt.
        self.assertIn(f"{DEFAULT_SANKTION_MAX_HOPS_CAP} Hops", job["label"])

    def test_ohne_server_scheitert_der_job_ohne_netzzugriff(self):
        self.listen_hinterlegen()
        status, körper = self.anfrage(
            "/api/sanctions/check", methode="POST", daten={"max_hops": 1}
        )
        self.assertEqual(status, 202)
        job = self.warte_auf_job(körper["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("erreichbar", job["error"])

    def test_ohne_wallet_konfiguration_fehler(self):
        self.env_pfad.write_text("# leer\n", encoding="utf-8")
        self.state.reload()
        status, _ = self.anfrage(
            "/api/sanctions/check", methode="POST", daten={}
        )
        self.assertEqual(status, 400)


class TestSanktionsCheckCache(ApiTestBasis):
    """
    Der letzte Prüflauf bleibt liegen und wird beim Öffnen der Ansicht
    gezeigt. Ein Lauf über mehrere Hops dauert Minuten — ihn bei jedem
    Seitenaufruf zu wiederholen, wäre unzumutbar.
    """

    def test_ohne_lauf_meldet_der_endpunkt_nichts_vorhandenes(self):
        status, körper = self.anfrage("/api/sanctions/check")
        self.assertEqual(status, 200)
        self.assertFalse(körper["vorhanden"])

    def test_gespeichertes_ergebnis_kommt_zurueck(self):
        sanctions_mod.check_ergebnis_speichern(self.sanktionen, {
            "max_hops": 3,
            "erstellt": "25.07.2026 13:42",
            "erstellt_ts": 1785066120,
            "listen_adressen": 1234,
            "vollstaendig": True,
            "wallets": [{
                "wallet": "Cold Storage", "geprueft": 2, "treffer": [],
                "adressen_geprueft": 17, "adressen": ["bc1qtest"],
                "abgebrochen": False,
            }],
        })
        status, körper = self.anfrage("/api/sanctions/check")
        self.assertEqual(status, 200)
        self.assertTrue(körper["vorhanden"])
        self.assertEqual(körper["max_hops"], 3)
        self.assertEqual(körper["erstellt"], "25.07.2026 13:42")
        self.assertEqual(körper["wallets"][0]["adressen_geprueft"], 17)
        self.assertEqual(körper["wallets"][0]["adressen"], ["bc1qtest"])

    def test_verwerfen_loescht_das_ergebnis(self):
        sanctions_mod.check_ergebnis_speichern(
            self.sanktionen, {"max_hops": 1, "wallets": []}
        )
        status, körper = self.anfrage("/api/sanctions/check", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(körper["geloescht"])
        _, danach = self.anfrage("/api/sanctions/check")
        self.assertFalse(danach["vorhanden"])

    def test_fremde_version_wird_verworfen_statt_halb_gelesen(self):
        """
        Ein falsch interpretierter Sanktionsbefund wäre schlimmer als gar
        keiner — bei unbekanntem Format gilt: nichts vorhanden.
        """
        pfad = self.sanktionen / sanctions_mod.CHECK_ERGEBNIS_DATEI
        pfad.write_text(
            json.dumps({"version": 99, "wallets": [{"wallet": "X"}]}),
            encoding="utf-8",
        )
        _, körper = self.anfrage("/api/sanctions/check")
        self.assertFalse(körper["vorhanden"])

    def test_kaputte_datei_wird_verworfen(self):
        pfad = self.sanktionen / sanctions_mod.CHECK_ERGEBNIS_DATEI
        pfad.write_text("{kein json", encoding="utf-8")
        _, körper = self.anfrage("/api/sanctions/check")
        self.assertFalse(körper["vorhanden"])

    def test_echter_lauf_schreibt_den_cache_mit_adressen(self):
        """
        Der Kernfall: Nach einem Lauf steht das Ergebnis in der Datei und
        kommt über GET zurück — samt der geprüften Adressen.
        """
        gelistet = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        (self.sanktionen / "sanctioned_addresses_XBT.json").write_text(
            json.dumps([gelistet]), encoding="utf-8"
        )
        # Ein UTXO auf einer Wallet-Adresse, gespeist aus einer externen
        # Adresse, die auf der Liste steht.
        vorgaenger = txid("ff")
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(50_000)], self.cache, "test", max_addresses=6
        )
        self.state.reload()
        txs = {
            txid("a1"): {
                "txid": txid("a1"),
                "vin": [{
                    "txid": vorgaenger, "vout": 0, "is_coinbase": False,
                    "prevout": {"scriptpubkey_address": gelistet,
                                "value": 50_000},
                }],
                "vout": [{"scriptpubkey_address": BIP84_RECEIVE_0,
                          "value": 50_000}],
                "status": {"confirmed": True, "block_time": 1_700_000_000},
            },
            vorgaenger: {
                "txid": vorgaenger, "vin": [],
                "vout": [{"scriptpubkey_address": gelistet, "value": 50_000}],
                "status": {"confirmed": True, "block_time": 1_600_000_000},
            },
        }
        # Vier Verbindungen wie beim eigenen Node: Der Lauf muss über den
        # Parallelweg dasselbe Ergebnis liefern.
        self.worker = set()

        def pool(state):
            def je_worker(worker_id):
                self.worker.add(worker_id)
                return lambda t: txs[t]

            return je_worker, 4

        with mock.patch.object(server, "_sanctions_get_tx_pool", side_effect=pool):
            status, körper = self.anfrage(
                "/api/sanctions/check", methode="POST", daten={"max_hops": 1}
            )
            self.assertEqual(status, 202)
            job = self.warte_auf_job(körper["id"])

        self.assertEqual(job["status"], "done", job.get("error"))

        _, gespeichert = self.anfrage("/api/sanctions/check")
        self.assertTrue(gespeichert["vorhanden"])
        self.assertEqual(gespeichert["max_hops"], 1)
        self.assertTrue(gespeichert["vollstaendig"])
        self.assertTrue(gespeichert["erstellt"])
        self.assertEqual(gespeichert["verbindungen"], 4)

        wallet = next(
            w for w in gespeichert["wallets"] if w["geprueft"] > 0
        )
        self.assertEqual(wallet["geprueft"], 1)
        self.assertIn(gelistet, wallet["adressen"])
        self.assertEqual(wallet["adressen_geprueft"], 1)
        self.assertEqual(
            [t["address"] for t in wallet["treffer"]], [gelistet]
        )

    def warte_auf_job(self, job_id, timeout_s=30):
        import time

        schluss = time.time() + timeout_s
        while time.time() < schluss:
            _, job = self.anfrage(f"/api/jobs/{job_id}")
            if not job["running"]:
                return job
            time.sleep(0.05)
        self.fail(f"Job {job_id} lief nicht zu Ende")



class TestSkripttypErkennung(ApiTestBasis):

    def test_kandidaten_werden_geliefert(self):
        status, körper = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"xpub": BIP84_AS_XPUB}
        )
        self.assertEqual(status, 200)
        typen = {k["script_type"] for k in körper["candidates"]}
        self.assertIn("segwit", typen)

        segwit = next(k for k in körper["candidates"] if k["script_type"] == "segwit")
        self.assertEqual(segwit["example_address"], BIP84_RECEIVE_0)

    def test_ohne_verbindung_keine_empfehlung(self):
        """Ein falscher Vorschlag ist schlimmer als gar keiner."""
        _, körper = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"xpub": BIP84_AS_XPUB}
        )
        self.assertIsNone(körper["suggestion"])
        self.assertIn("nicht sicher", körper["note"])

    def test_unbrauchbarer_xpub(self):
        status, _ = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"xpub": "unsinn"}
        )
        self.assertEqual(status, 400)

    def test_pruefung_ueber_kennung(self):
        """
        Für gespeicherte Wallets kennt die Oberfläche nur die Maskierung —
        sie muss die Prüfung über die Kennung anstoßen können.
        """
        _, config = self.anfrage("/api/config")
        kennung = next(w["id"] for w in config["wallets"] if w["prefix"] == "xpub")
        status, körper = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"wallet_id": kennung}
        )
        self.assertEqual(status, 200)
        segwit = next(
            k for k in körper["candidates"] if k["script_type"] == "segwit"
        )
        # Empfangsadresse #0 desselben Schlüssels — das ist die Adresse, die
        # die Wallet-Software als erste anzeigt.
        erwartet = main.derive_addresses(
            ZWEITER_ALS_XPUB, max_addresses=2, script_type="segwit"
        )
        self.assertIn(segwit["example_address"], erwartet)
        self.assertTrue(segwit["example_address"].startswith("bc1q"))

    def test_pruefung_gibt_den_schluessel_nicht_preis(self):
        _, config = self.anfrage("/api/config")
        kennung = config["wallets"][0]["id"]
        _, körper = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"wallet_id": kennung}
        )
        self.assertNotIn(BIP84_ZPUB, json.dumps(körper))

    def test_pruefung_fuer_unbekanntes_wallet(self):
        status, _ = self.anfrage(
            "/api/wallets/probe", methode="POST", daten={"wallet_id": "gibtsnicht"}
        )
        self.assertEqual(status, 404)


class TestSteuerjahr(ApiTestBasis):

    def setUp(self):
        super().setUp()
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000, marker="a1"),
            utxo(124_500, marker="c3"),
        ], self.cache, 6)

    def test_auswertung_wird_geliefert(self):
        status, körper = self.anfrage("/api/tax?jahr=2026&frist=1")
        self.assertEqual(status, 200)
        self.assertEqual(körper["jahr"], 2026)
        self.assertEqual(körper["kennzahlen"]["gesamt_count"], 2)

    def test_abgeschlossenes_jahr_bezieht_sich_aufs_jahresende(self):
        """Ein Jahr in der Vergangenheit rechnet gegen den 31.12."""
        _, körper = self.anfrage("/api/tax?jahr=2024&frist=1")
        self.assertEqual(körper["stichtag"], "31.12.2024")
        self.assertFalse(körper["laufend"])
        self.assertIn("Stichtag", körper["stichtag_label"])

    def test_laufendes_jahr_bezieht_sich_auf_heute(self):
        """
        Für das laufende Jahr zählt der heutige Tag. Gegen den 31.12.
        gerechnet gälten Beträge als fristerfüllt, deren Jahr erst später
        abläuft.
        """
        from datetime import date

        _, körper = self.anfrage(f"/api/tax?jahr={date.today().year}&frist=1")
        self.assertTrue(körper["laufend"])
        self.assertEqual(körper["stichtag"], date.today().strftime("%d.%m.%Y"))
        self.assertIn("Stand heute", körper["stichtag_label"])
        self.assertIn("läuft noch", " ".join(körper["hinweise"]))

    def test_haltefrist_wirkt(self):
        _, mit = self.anfrage("/api/tax?jahr=2026&frist=1")
        _, ohne = self.anfrage("/api/tax?jahr=2026&frist=0")
        self.assertGreaterEqual(
            ohne["kennzahlen"]["erfuellt_count"],
            mit["kennzahlen"]["erfuellt_count"],
        )

    def test_hinweise_werden_mitgeliefert(self):
        _, körper = self.anfrage("/api/tax?jahr=2026")
        self.assertTrue(körper["hinweise"])
        text = " ".join(körper["hinweise"])
        self.assertIn("keine Steuerberatung", text)
        self.assertIn("Börsenhistorien", text)

    def test_verfuegbare_jahre(self):
        _, körper = self.anfrage("/api/tax")
        self.assertTrue(körper["verfuegbare_jahre"])

    def test_interne_objekte_werden_nicht_ausgeliefert(self):
        _, körper = self.anfrage("/api/tax?jahr=2026")
        self.assertNotIn("_objekte", körper)

    def test_unsinniges_jahr_faellt_auf_default(self):
        status, körper = self.anfrage("/api/tax?jahr=quatsch")
        self.assertEqual(status, 200)
        self.assertIsInstance(körper["jahr"], int)

    def test_stichtagsregel_ohne_env_ist_aus(self):
        _, körper = self.anfrage("/api/tax?jahr=2026&frist=1")
        self.assertEqual(körper["stichtag_regel"], "")

    def test_stichtag_laesst_sich_abschalten(self):
        _, körper = self.anfrage("/api/tax?jahr=2026&frist=1&stichtag=")
        self.assertEqual(körper["stichtag_regel"], "")

    def test_steuer_einstellungen_werden_gespeichert(self):
        status, körper = self.anfrage(
            "/api/config/steuer", methode="PUT",
            daten={"haltefrist_jahre": 7, "stichtag": "2021-02-28"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(körper["steuer"]["haltefrist_jahre"], 7)
        self.assertEqual(körper["steuer"]["stichtag"], "28.02.2021")
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["STEUER_HALTEFRIST_JAHRE"], "7")
        self.assertEqual(werte["STEUER_STICHTAG"], "28.02.2021")

        _, leer = self.anfrage(
            "/api/config/steuer", methode="PUT",
            daten={"haltefrist_jahre": 1, "stichtag": ""},
        )
        self.assertEqual(leer["steuer"]["stichtag"], "")

    def test_start_sync_einstellung_wird_gespeichert(self):
        _, cfg = self.anfrage("/api/config")
        self.assertFalse(cfg.get("wallets_beim_start_aktualisieren"))

        status, körper = self.anfrage(
            "/api/config/start-sync", methode="PUT",
            daten={"enabled": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["wallets_beim_start_aktualisieren"])
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["WALLETS_BEIM_START_AKTUALISIEREN"], "1")

        _, cfg2 = self.anfrage("/api/config")
        self.assertTrue(cfg2["wallets_beim_start_aktualisieren"])

        _, aus = self.anfrage(
            "/api/config/start-sync", methode="PUT",
            daten={"enabled": False},
        )
        self.assertFalse(aus["wallets_beim_start_aktualisieren"])
        self.assertEqual(
            main._load_dotenv(self.env_pfad)["WALLETS_BEIM_START_AKTUALISIEREN"],
            "0",
        )

    def test_onchain_hinweis_steht_in_der_config(self):
        from core import tax
        _, cfg = self.anfrage("/api/config")
        self.assertEqual(cfg["hinweis_onchain"], tax.HINWEIS_ONCHAIN)
        self.assertFalse(cfg["hinweis_onchain_bestaetigt"])

    def test_onchain_hinweis_wird_in_der_env_gemerkt(self):
        status, körper = self.anfrage(
            "/api/config/hinweis-onchain", methode="PUT",
            daten={"bestaetigt": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["hinweis_onchain_bestaetigt"])
        werte = main._load_dotenv(self.env_pfad)
        self.assertEqual(werte["HINWEIS_ONCHAIN_BESTAETIGT"], "1")
        _, cfg = self.anfrage("/api/config")
        self.assertTrue(cfg["hinweis_onchain_bestaetigt"])


class TestExport(ApiTestBasis):

    def setUp(self):
        super().setUp()
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(84_000_000, marker="a1")], self.cache, 6
        )

    def _hole_roh(self, pfad):
        url = f"http://127.0.0.1:{self.port}{pfad}"
        req = urllib.request.Request(url)
        req.add_header("X-Satsage-Token", self.state.token)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        with urllib.request.urlopen(req, timeout=10) as antwort:
            return antwort, antwort.read()

    def test_csv_wird_als_download_geliefert(self):
        antwort, inhalt = self._hole_roh("/api/tax/export.csv?jahr=2026")
        self.assertEqual(antwort.status, 200)
        self.assertIn("text/csv", antwort.headers["Content-Type"])
        self.assertIn("attachment", antwort.headers["Content-Disposition"])
        self.assertIn("steuerjahr-2026.csv", antwort.headers["Content-Disposition"])

    def test_csv_hat_bom_und_inhalt(self):
        _, inhalt = self._hole_roh("/api/tax/export.csv?jahr=2026")
        self.assertTrue(inhalt.startswith(b"\xef\xbb\xbf"))
        text = inhalt.decode("utf-8-sig")
        self.assertIn("Steuerjahr 2026", text)
        self.assertIn("0,84000000", text)

    def test_bericht_ist_eigenstaendiges_html(self):
        antwort, inhalt = self._hole_roh("/api/tax/bericht.html?jahr=2026")
        self.assertEqual(antwort.status, 200)
        text = inhalt.decode("utf-8")
        self.assertTrue(text.startswith("<!DOCTYPE html>"))
        self.assertNotIn("http://", text)

    def test_export_ohne_token_abgelehnt(self):
        url = f"http://127.0.0.1:{self.port}/api/tax/export.csv"
        with self.assertRaises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(urllib.request.Request(url), timeout=10)
        self.assertEqual(fehler.exception.code, 403)

    def test_token_per_query_reicht_fuer_den_download(self):
        """Ein Download-Fenster kann keinen Header setzen."""
        url = (f"http://127.0.0.1:{self.port}/api/tax/export.csv"
               f"?jahr=2026&t={self.state.token}")
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as a:
            self.assertEqual(a.status, 200)


class TestTraceEndpunkt(ApiTestBasis):

    def test_unbrauchbares_ziel(self):
        status, körper = self.anfrage(
            "/api/trace", methode="POST", daten={"target": "quatsch"}
        )
        self.assertEqual(status, 400)
        self.assertIn("txid:vout", körper["error"])

    def test_leeres_ziel(self):
        status, _ = self.anfrage(
            "/api/trace", methode="POST", daten={"target": ""}
        )
        self.assertEqual(status, 400)


def _abgeleitete_cosigner(anzahl: int = 2) -> list[str]:
    """
    Eigenständige Testschlüssel für Multisig.

    Aus dem BIP-84-Testvektor abgeleitet, damit sie gültig sind, aber mit
    keinem der Einzel-Wallets übereinstimmen.
    """
    from tests.fixtures import BIP84_ZPUB

    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return [hd.derive([100 + i]).to_base58() for i in range(anzahl)]


class TestWalletBloeckeUeberDieApi(ApiTestBasis):
    """
    Speichern aus der Oberfläche überführt eine alte .env ins Blockformat —
    und darf dabei nichts verlieren, was die Oberfläche gar nicht bearbeiten
    kann.
    """

    def wallets(self):
        status, körper = self.anfrage("/api/config")
        self.assertEqual(status, 200)
        return körper["wallets"]

    def speichere(self, nutzlast, confirm=False):
        return self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": nutzlast, "confirm": confirm},
        )

    def test_speichern_erzeugt_bloecke(self):
        wallets = self.wallets()
        status, _ = self.speichere([
            {"id": w["id"], "name": w["name"],
             "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]}
            for w in wallets
        ])
        self.assertEqual(status, 200)
        werte = server.EnvFile.load(self.env_pfad).values()
        self.assertIn("WALLET_0_XPUB", werte)
        self.assertNotIn("XPUBS", werte)
        self.assertNotIn("WALLET_NAMES", werte)

    def test_rpc_passwort_ueberlebt(self):
        wallets = self.wallets()
        self.speichere([{"id": w["id"], "name": w["name"],
                         "script_type": w["script_type"],
                         "max_addresses": w["max_addresses"]} for w in wallets])
        werte = server.EnvFile.load(self.env_pfad).values()
        self.assertEqual(werte["RPCPASSWORD"], "xpq-testgeheimnis-8f3a2c")

    # -- Multisig -----------------------------------------------------------

    def multisig_eintragen(self):
        """
        Trägt von Hand eine Multisig in die .env — wie ein Benutzer es täte.

        Erst wird die alte .env ins Blockformat überführt (ein Speichern aus
        der Oberfläche), dann kommt der Multisig-Block lückenlos dahinter.
        Ein Block ohne WALLET_0 gälte nicht: Die Liste beginnt bei null.
        """
        wallets = self.wallets()
        self.speichere([{"id": w["id"], "name": w["name"],
                         "script_type": w["script_type"],
                         "max_addresses": w["max_addresses"]} for w in wallets])

        env = server.EnvFile.load(self.env_pfad)
        werte = env.values()
        naechste = len([
            key for key in werte
            if key.startswith("WALLET_") and key.endswith("_XPUB")
        ])
        # Eigene Schlüssel für die Cosigner: Wären es die der beiden
        # Einzel-Wallets, wäre die Konfiguration zu Recht ungültig — dieselben
        # Beträge zählten doppelt.
        cosigner = _abgeleitete_cosigner()
        env.apply({
            f"WALLET_{naechste}_NAME": "Tresor",
            f"WALLET_{naechste}_M": "2",
            f"WALLET_{naechste}_SCRIPT": "wsh",
            f"WALLET_{naechste}_XPUBS": " ".join(cosigner),
        })
        env.save()
        self.state.reload()
        return naechste

    def test_multisig_erscheint_in_der_api(self):
        self.multisig_eintragen()
        multisig = [w for w in self.wallets() if w["is_multisig"]]
        self.assertEqual(len(multisig), 1)
        self.assertEqual(multisig[0]["threshold"], 2)
        self.assertEqual(multisig[0]["cosigner_count"], 2)
        self.assertEqual(len(multisig[0]["xpubs_masked"]), 2)

    def test_put_ohne_multisig_verliert_sie_nicht(self):
        """
        Eine ältere Oberfläche schickt Multisig gar nicht mit. Sie deshalb zu
        löschen wäre nicht wiedergutzumachen — die Cosigner stünden nirgends
        mehr.
        """
        self.multisig_eintragen()
        wallets = self.wallets()
        single = [w for w in wallets if not w["is_multisig"]]
        status, _ = self.speichere([
            {"id": w["id"], "name": w["name"],
             "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]}
            for w in single
        ])
        self.assertEqual(status, 200)

        werte = server.EnvFile.load(self.env_pfad).values()
        # Gespeichert wird der Deskriptor, auch wenn sie als Kurzform
        # (_M/_XPUBS) eingetragen wurde.
        deskriptoren = [
            v for k, v in werte.items() if k.endswith("_DESC") and v.strip()
        ]
        self.assertTrue(
            deskriptoren,
            "Die Multisig-Wallet ist beim Speichern verlorengegangen.",
        )
        self.assertIn("sortedmulti", deskriptoren[0])

    def test_multisig_ist_nicht_im_analyse_stack(self):
        self.multisig_eintragen()
        args = self.state.args_namespace()
        for eintrag in self.state.multisig_entries:
            for cosigner in eintrag.xpubs:
                self.assertNotIn(
                    cosigner, args.xpubs,
                    "Cosigner dürfen nicht als eigene Wallets gescannt werden.",
                )


class TestHerkunftVollstaendig(ApiTestBasis):
    """
    Wallet-Knopf „Herkunft vollständig“: nur UTXOs ohne vollständigen Baum,
    mit wallet_id und resolve_bundled.
    """

    def test_vollstaendig_ohne_wallet_id_abgelehnt(self):
        status, körper = self.anfrage(
            "/api/trace/alle",
            methode="POST",
            daten={"vollstaendig": True},
        )
        self.assertEqual(status, 400)
        self.assertIn("wallet_id", körper["error"])

    def test_vollstaendig_unbekanntes_wallet(self):
        status, körper = self.anfrage(
            "/api/trace/alle",
            methode="POST",
            daten={"vollstaendig": True, "wallet_id": "gibt-es-nicht"},
        )
        self.assertEqual(status, 404)

    def test_vollstaendig_nichts_zu_tun_ohne_utxos(self):
        wid = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(
            "/api/trace/alle",
            methode="POST",
            daten={"vollstaendig": True, "wallet_id": wid},
        )
        # Route liefert 202 wie andere Jobs; bei nichts_zu_tun startet kein Job.
        self.assertIn(status, (200, 202))
        self.assertTrue(körper.get("nichts_zu_tun"))
        self.assertEqual(körper.get("offen"), 0)

    def test_offen_tief_nimmt_unvollstaendige(self):
        from core import trace_cache

        main.save_xpub_utxo_cache(
            BIP84_ZPUB,
            [
                utxo(100_000, BIP84_RECEIVE_0, marker="a1", vout=0),
                utxo(50_000, BIP84_RECEIVE_0, marker="b2", vout=1),
            ],
            self.cache,
            "test",
        )
        # Ein vollständiger Baum, einer unvollständig (leeres internal-Blatt).
        voll = {
            "found": True,
            "children": [{"type": "external", "children": []}],
            "summary": {"external_count": 1, "unresolved_inputs": 0},
        }
        luecke = {
            "found": True,
            "children": [
                {"type": "external", "children": []},
                {"type": "internal", "children": []},
            ],
            "summary": {"external_count": 1, "unresolved_inputs": 0},
        }
        eigene = {BIP84_RECEIVE_0}
        trace_cache.speichern(txid("a1"), 0, voll, self.immutable, eigene)
        trace_cache.speichern(txid("b2"), 1, luecke, self.immutable, eigene)

        utxos = server._utxos_fuer_trace(
            self.state, wallet_id=self.wallet_id(BIP84_ZPUB),
        )
        offen = server._trace_offen_tief(self.state, utxos, eigene)
        keys = {(t, v) for t, v in offen}
        self.assertIn((txid("b2"), 1), keys)
        self.assertNotIn((txid("a1"), 0), keys)


class TestGespeicherterBaum(ApiTestBasis):
    """
    GET /api/trace liefert einen bereits verfolgten Baum sofort — ohne Job und
    ohne Node-Verbindung. Genau daran hängt, dass ein Seitenaufruf die
    Herkunft zeigen kann, statt sie neu zu erheben.
    """

    ZIEL = "a1" * 32
    BAUM = {
        "found": True,
        "root": {"id": "0", "txid": "a1" * 32, "vout": 0, "amount_sats": 500},
        "children": [{"id": "0.0", "type": "external", "address": "bc1qtest"}],
        "summary": {"external_sats": 500},
    }

    def ablegen(self, adressen=None):
        from core import trace_cache

        trace_cache.speichern(
            self.ZIEL, 0, self.BAUM, self.immutable, adressen or {"bc1qeigene"}
        )

    def test_ohne_gespeicherten_baum(self):
        status, körper = self.anfrage(f"/api/trace?target={self.ZIEL}:0")
        self.assertEqual(status, 200)
        self.assertFalse(körper["vorhanden"])

    def test_gespeicherter_baum_kommt_zurueck(self):
        self.ablegen()
        status, körper = self.anfrage(f"/api/trace?target={self.ZIEL}:0")
        self.assertEqual(status, 200)
        self.assertTrue(körper["vorhanden"])
        self.assertEqual(körper["ergebnis"]["root"]["txid"], self.ZIEL)
        self.assertGreater(körper["erstellt_ts"], 0)

    def test_fremde_adressmenge_meldet_veraltet(self):
        """
        Abgelegt unter einer Adressmenge, die mit der jetzigen nichts zu tun
        hat: Der Baum kommt trotzdem, aber gekennzeichnet.
        """
        self.ablegen(adressen={"bc1qganzandere"})
        _, körper = self.anfrage(f"/api/trace?target={self.ZIEL}:0")
        self.assertTrue(körper["vorhanden"])
        self.assertTrue(körper["veraltet"])
        self.assertTrue(körper["ergebnis"]["found"])

    def test_unbrauchbares_ziel(self):
        status, körper = self.anfrage("/api/trace?target=quatsch")
        self.assertEqual(status, 400)
        self.assertIn("txid:vout", körper["error"])

    def test_ohne_token_kein_baum(self):
        self.ablegen()
        status, _ = self.anfrage(
            f"/api/trace?target={self.ZIEL}:0", token=False
        )
        self.assertEqual(status, 403)


class TestCacheLeeren(ApiTestBasis):

    def test_loescht_analyse_cache_nicht_sanktionen(self):
        (self.cache / "wallet.json").write_text("{}", encoding="utf-8")
        (self.immutable / "tx").mkdir()
        (self.immutable / "tx" / "abc.json").write_text("{}", encoding="utf-8")
        (self.sanktionen / "liste.json").write_text("{}", encoding="utf-8")

        status, körper = self.anfrage("/api/cache", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(körper["ok"])
        self.assertGreaterEqual(körper["utxo_eintraege"], 1)
        self.assertGreaterEqual(körper["immutable_eintraege"], 1)
        self.assertFalse((self.cache / "wallet.json").exists())
        self.assertFalse((self.immutable / "tx").exists())
        self.assertTrue(self.cache.is_dir())
        self.assertTrue(self.immutable.is_dir())
        self.assertTrue((self.sanktionen / "liste.json").exists())

    def test_cache_leeren_behaelt_p2p_headers(self):
        pfad = self.immutable / "p2p_headers.bin"
        pfad.write_bytes(b"xpqh")
        status, _ = self.anfrage("/api/cache", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(pfad.is_file())

    def test_gesamter_cache_behaelt_wallet_alter(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
        )
        alter = main._xpub_alter_path(BIP84_ZPUB, self.cache)
        self.assertTrue(alter.is_file())
        status, _ = self.anfrage("/api/cache", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(alter.is_file())
        self.assertFalse(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())
        self.assertEqual(main.xpub_first_seen(BIP84_ZPUB, self.cache)["height"], 700_000)
        # Rescan ohne UTXO-Cache soll am First-seen ansetzen, nicht bei SegWit.
        start = main.bip158_start_aus_first_seen(
            BIP84_ZPUB, self.cache, floor=481_824, puffer=6,
        )
        self.assertEqual(start, 700_000 - 6)

    def test_leerer_cache_ist_kein_fehler(self):
        status, körper = self.anfrage("/api/cache", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(körper["utxo_eintraege"], 0)
        self.assertEqual(körper["immutable_eintraege"], 0)

    def test_cache_stats_belegung(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
            scan_end_index=12,
        )
        main.save_xpub_verlauf_cache(
            BIP84_ZPUB, [utxo(500, marker="hist")], self.cache
        )
        (self.immutable / "tx").mkdir()
        (self.immutable / "tx" / ("a" * 64 + ".json")).write_text(
            '{"txid":"aa"}', encoding="utf-8"
        )
        (self.sanktionen / "liste.json").write_text("{}", encoding="utf-8")

        status, körper = self.anfrage("/api/cache/stats")
        self.assertEqual(status, 200)
        self.assertTrue(körper["ok"])
        self.assertIn("platte", körper)
        self.assertGreater(körper["utxo_cache"]["bytes"], 0)
        self.assertGreaterEqual(körper["tx"]["dateien"], 1)
        self.assertEqual(körper["tx"]["schwelle"], 10_000)
        wallets = {w["wallet_id"]: w for w in körper["wallets"]}
        kennung = self.wallet_id(BIP84_ZPUB)
        self.assertIn(kennung, wallets)
        self.assertEqual(wallets[kennung]["utxo_count"], 1)
        self.assertEqual(wallets[kennung]["verlauf_count"], 1)
        self.assertTrue(wallets[kennung]["alter_vorhanden"])
        self.assertGreater(körper["summe_bytes"], 0)

    def test_loescht_nur_dieses_wallet(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
        )
        main.save_xpub_utxo_cache(
            ZWEITER_ALS_XPUB, [utxo(2_000, marker="b2")], self.cache, "test"
        )
        main.save_xpub_verlauf_cache(
            BIP84_ZPUB, [utxo(500, marker="c3")], self.cache
        )
        tx = txid("a1")
        (self.immutable / "utxo_ingress").mkdir()
        (self.immutable / "utxo_trace").mkdir()
        (self.immutable / "utxo_ingress" / f"{tx}_0.json").write_text(
            "{}", encoding="utf-8"
        )
        (self.immutable / "utxo_trace" / f"{tx}_0.json").write_text(
            "{}", encoding="utf-8"
        )
        fremd = txid("b2")
        (self.immutable / "utxo_ingress" / f"{fremd}_0.json").write_text(
            "{}", encoding="utf-8"
        )
        (self.sanktionen / "liste.json").write_text("{}", encoding="utf-8")

        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(f"/api/cache/{kennung}", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(körper["ok"])
        self.assertEqual(körper["wallet_id"], kennung)
        self.assertEqual(körper["utxo_eintraege"], 1)
        self.assertEqual(körper["verlauf_eintraege"], 1)
        self.assertEqual(körper["herkunft_eintraege"], 2)
        self.assertFalse(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())
        self.assertTrue(main._xpub_alter_path(BIP84_ZPUB, self.cache).is_file())
        self.assertTrue(
            main._xpub_cache_path(ZWEITER_ALS_XPUB, self.cache).is_file()
        )
        self.assertFalse(
            (self.immutable / "utxo_ingress" / f"{tx}_0.json").exists()
        )
        self.assertTrue(
            (self.immutable / "utxo_ingress" / f"{fremd}_0.json").exists()
        )
        self.assertTrue((self.sanktionen / "liste.json").exists())

    def test_wallet_cache_unbekanntes_wallet(self):
        status, körper = self.anfrage("/api/cache/gibtsnicht", methode="DELETE")
        self.assertEqual(status, 404)

    def test_wallet_cache_ohne_dateien_ist_kein_fehler(self):
        kennung = self.wallet_id(BIP84_ZPUB)
        status, körper = self.anfrage(f"/api/cache/{kennung}", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(körper["utxo_eintraege"], 0)
        self.assertEqual(körper["verlauf_eintraege"], 0)
        self.assertEqual(körper["herkunft_eintraege"], 0)

    def test_cache_vorschau_bei_wallet_entfernung(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
        )
        # Zweite Wallet bleibt — nur die erste fällt aus der Liste.
        behalten = {
            "id": self.wallet_id(ZWEITER_ALS_XPUB),
            "name": "Ledger Alt",
            "script_type": "segwit",
            "max_addresses": 6,
        }
        status, körper = self.anfrage(
            "/api/config/wallets/cache-vorschau",
            methode="POST",
            daten={"wallets": [behalten]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(körper["entfernt"]), 1)
        self.assertEqual(körper["entfernt"][0]["wallet_id"], self.wallet_id(BIP84_ZPUB))
        self.assertGreater(körper["bytes"], 0)
        self.assertIn("MB", körper["groesse_label"])
        self.assertTrue(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())

    def test_speichern_loescht_cache_entfernten_wallets(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
        )
        main.save_xpub_verlauf_cache(
            BIP84_ZPUB, [utxo(500, marker="c3")], self.cache
        )
        behalten = {
            "id": self.wallet_id(ZWEITER_ALS_XPUB),
            "name": "Ledger Alt",
            "script_type": "segwit",
            "max_addresses": 6,
        }
        status, körper = self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={
                "wallets": [behalten],
                "cache_entfernte_loeschen": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertEqual(len(körper["cache_entfernt"]), 1)
        self.assertIn("MB", körper["cache_groesse_label"])
        self.assertFalse(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())
        self.assertFalse(
            main._xpub_verlauf_cache_path(BIP84_ZPUB, self.cache).is_file()
        )
        # Wallet weg: Altersdatei darf mit weg, sonst bleibt sie verwaist.
        self.assertFalse(main._xpub_alter_path(BIP84_ZPUB, self.cache).is_file())

    def test_speichern_ohne_flag_behaelt_cache(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test"
        )
        behalten = {
            "id": self.wallet_id(ZWEITER_ALS_XPUB),
            "name": "Ledger Alt",
            "script_type": "segwit",
            "max_addresses": 6,
        }
        status, körper = self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [behalten], "cache_entfernte_loeschen": False},
        )
        self.assertEqual(status, 200)
        self.assertEqual(körper.get("cache_entfernt"), [])
        self.assertTrue(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())

    def test_unreferenzierter_cache_wird_gemeldet_und_geloescht(self):
        """Wallet weg, Cache bleibt → Aufräumen findet und löscht ihn."""
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(1_000)], self.cache, "test",
            first_seen={"height": 700_000, "time_ts": 1_600_000_000},
        )
        main.save_xpub_verlauf_cache(
            BIP84_ZPUB, [utxo(500, marker="c3")], self.cache
        )
        # BIP84 aus der .env nehmen — Cache-Dateien bleiben liegen.
        behalten = {
            "id": self.wallet_id(ZWEITER_ALS_XPUB),
            "name": "Ledger Alt",
            "script_type": "segwit",
            "max_addresses": 6,
        }
        self.anfrage(
            "/api/config/wallets",
            methode="PUT",
            daten={"wallets": [behalten], "cache_entfernte_loeschen": False},
        )
        self.assertTrue(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())

        status, stand = self.anfrage("/api/cache/unreferenziert")
        self.assertEqual(status, 200)
        self.assertTrue(stand["vorhanden"])
        self.assertGreaterEqual(stand["kennungen"], 1)
        self.assertGreater(stand["bytes"], 0)
        self.assertIn("MB", stand["groesse_label"])

        status, weg = self.anfrage("/api/cache/unreferenziert", methode="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(weg["ok"])
        self.assertGreaterEqual(weg["dateien"], 1)
        self.assertFalse(main._xpub_cache_path(BIP84_ZPUB, self.cache).is_file())
        self.assertFalse(
            main._xpub_verlauf_cache_path(BIP84_ZPUB, self.cache).is_file()
        )
        self.assertFalse(main._xpub_alter_path(BIP84_ZPUB, self.cache).is_file())
        # Zweiter Call: nichts mehr.
        _, leer = self.anfrage("/api/cache/unreferenziert")
        self.assertFalse(leer["vorhanden"])
        self.assertEqual(leer["dateien"], 0)


class TestVorgaenge(ApiTestBasis):

    def test_unbekannter_vorgang(self):
        status, _ = self.anfrage("/api/jobs/gibtsnicht")
        self.assertEqual(status, 404)

    def test_abbruch_eines_unbekannten_vorgangs(self):
        status, _ = self.anfrage("/api/jobs/gibtsnicht", methode="DELETE")
        self.assertEqual(status, 409)

    def test_rescan_fuer_unbekanntes_wallet(self):
        status, _ = self.anfrage(
            "/api/jobs/rescan", methode="POST", daten={"wallet_id": "gibtsnicht"}
        )
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()


class TestDeskriptorEndpunkt(ApiTestBasis):
    """
    Ein Feld für zwei Wege: getippter Deskriptor und kopierter Wallet-Export.
    Der Unterschied liegt im Text, nicht in der Absicht.
    """

    def pruefe(self, text):
        return self.anfrage(
            "/api/config/deskriptor", methode="POST", daten={"text": text}
        )

    def deskriptor(self):
        cosigner = _abgeleitete_cosigner(2)
        return (
            f"wsh(sortedmulti(2,{cosigner[0]}/<0;1>/*,{cosigner[1]}/<0;1>/*))"
        )

    def test_gueltiger_deskriptor_wird_beschrieben(self):
        status, körper = self.pruefe(self.deskriptor())
        self.assertEqual(status, 200)
        self.assertEqual(len(körper["gefunden"]), 1)
        treffer = körper["gefunden"][0]
        self.assertEqual(treffer["threshold"], 2)
        self.assertEqual(treffer["cosigner_count"], 2)
        self.assertTrue(treffer["erste_adresse"].startswith("bc1q"))

    def test_erste_adresse_dient_der_kontrolle(self):
        """
        Nur an ihr lässt sich vor dem Speichern sehen, ob wirklich die eigene
        Wallet gemeint ist — ein Deskriptor sieht auch mit vertauschtem
        Schlüssel richtig aus.
        """
        _, körper = self.pruefe(self.deskriptor())
        adresse = körper["gefunden"][0]["erste_adresse"]
        self.assertEqual(
            adresse,
            sorted(main.derive_descriptor_addresses(
                körper["gefunden"][0]["descriptor"], max_addresses=2
            ))[0],
        )

    def test_volle_schluessel_verlassen_den_server_nicht(self):
        _, körper = self.pruefe(self.deskriptor())
        for maskiert in körper["gefunden"][0]["xpubs_masked"]:
            self.assertIn("…", maskiert)

    def test_wallet_export_als_json(self):
        text = json.dumps({"label": "Tresor", "descriptor": self.deskriptor()})
        _, körper = self.pruefe(text)
        self.assertEqual(len(körper["gefunden"]), 1)

    def test_privater_schluessel_wird_abgelehnt(self):
        # Absichtlich ungültiger xprv-ähnlicher String (kein BIP32-Testvektor).
        text = "wpkh(xprv11111111111111111111111111111111111111111111111111111111111111111111111111111111/0/*)"
        _, körper = self.pruefe(text)
        self.assertEqual(körper["gefunden"], [])
        self.assertIn("privaten Schlüssel", körper["fehler"])

    def test_unbrauchbarer_text(self):
        _, körper = self.pruefe("wsh(sortedmulti(2,abc,def))")
        self.assertEqual(körper["gefunden"], [])
        self.assertIn("Kein verwendbarer Deskriptor", körper["fehler"])

    def test_leerer_text_ist_kein_fehler(self):
        _, körper = self.pruefe("   ")
        self.assertEqual(körper["gefunden"], [])
        self.assertEqual(körper["fehler"], "")

    def test_bereits_vorhandene_werden_gemeldet(self):
        """Zweimal dieselbe Wallet zählte Beträge doppelt."""
        desc = self.deskriptor()
        wallets = self.anfrage("/api/config")[1]["wallets"]
        nutzlast = [
            {"id": w["id"], "name": w["name"], "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]} for w in wallets
        ]
        nutzlast.append({"name": "Tresor", "descriptor": desc,
                         "max_addresses": 20})
        status, _ = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": nutzlast, "confirm": False},
        )
        self.assertEqual(status, 200)

        _, körper = self.pruefe(desc)
        self.assertTrue(körper["gefunden"][0]["bereits_vorhanden"])


class TestMultisigAnlegen(ApiTestBasis):

    def test_neue_multisig_wird_gespeichert(self):
        cosigner = _abgeleitete_cosigner(3)
        desc = (
            f"wsh(sortedmulti(2,{cosigner[0]}/<0;1>/*,"
            f"{cosigner[1]}/<0;1>/*,{cosigner[2]}/<0;1>/*))"
        )
        wallets = self.anfrage("/api/config")[1]["wallets"]
        nutzlast = [
            {"id": w["id"], "name": w["name"], "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]} for w in wallets
        ]
        nutzlast.append({"name": "Neuer Tresor", "descriptor": desc,
                         "max_addresses": 30})

        status, _ = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": nutzlast, "confirm": False},
        )
        self.assertEqual(status, 200)

        werte = server.EnvFile.load(self.env_pfad).values()
        deskriptoren = [v for k, v in werte.items() if k.endswith("_DESC")]
        self.assertEqual(len(deskriptoren), 1)
        self.assertIn("sortedmulti", deskriptoren[0])

        neu = [w for w in self.anfrage("/api/config")[1]["wallets"]
               if w["name"] == "Neuer Tresor"]
        self.assertEqual(len(neu), 1)
        self.assertTrue(neu[0]["is_multisig"])
        self.assertEqual(neu[0]["max_addresses"], 30)

    def test_taproot_multisig_anlegen(self):
        cosigner = _abgeleitete_cosigner(3)
        desc = (
            f"tr({cosigner[0]}/<0;1>/*,multi_a(2,"
            f"{cosigner[1]}/<0;1>/*,{cosigner[2]}/<0;1>/*))"
        )
        wallets = self.anfrage("/api/config")[1]["wallets"]
        nutzlast = [
            {"id": w["id"], "name": w["name"], "script_type": w["script_type"],
             "max_addresses": w["max_addresses"]} for w in wallets
        ]
        nutzlast.append({"name": "Taproot", "descriptor": desc,
                         "max_addresses": 20})
        status, _ = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": nutzlast, "confirm": False},
        )
        self.assertEqual(status, 200)

        neu = [w for w in self.anfrage("/api/config")[1]["wallets"]
               if w["name"] == "Taproot"][0]
        self.assertEqual(neu["script_type"], "tr")

    def test_kaputter_deskriptor_wird_abgelehnt(self):
        status, körper = self.anfrage(
            "/api/config/wallets", methode="PUT",
            daten={"wallets": [{"name": "Kaputt",
                                "descriptor": "wsh(sortedmulti(2,abc,def))"}],
                   "confirm": False},
        )
        self.assertEqual(status, 400)
        self.assertIn("Deskriptor", körper["error"])


class TestPriceApi(ApiTestBasis):
    """Spotkurs für die Kopfzeile — ohne echtes Netz (Fetch gemockt)."""

    def test_price_liefert_eur_spot(self):
        fake = server.price_mod.BtcPreis(
            amount=69013.0,
            currency="EUR",
            time=1_700_000_000,
            source="mempool",
            kind="spot",
            day="2023-11-14",
        )
        with mock.patch.object(server.price_mod, "spot_preis", return_value=fake) as spot:
            status, körper = self.anfrage("/api/price?currency=EUR")
        self.assertEqual(status, 200)
        self.assertEqual(körper["amount"], 69013.0)
        self.assertEqual(körper["currency"], "EUR")
        self.assertEqual(körper["source"], "mempool")
        self.assertEqual(körper["kind"], "spot")
        spot.assert_called_once()
        kwargs = spot.call_args.kwargs
        self.assertEqual(kwargs.get("immutable_cache_dir"), self.immutable)

    def test_price_ungültige_waehrung(self):
        status, körper = self.anfrage("/api/price?currency=XYZ")
        self.assertEqual(status, 400)
        self.assertIn("Währung", körper["error"])

    def test_price_quelle_ausgefallen(self):
        with mock.patch.object(
            server.price_mod,
            "spot_preis",
            side_effect=server.price_mod.PriceError("offline"),
        ):
            status, körper = self.anfrage("/api/price")
        self.assertEqual(status, 502)
        self.assertIn("offline", körper["error"])

    def test_price_history_bundle(self):
        status, körper = self.anfrage("/api/price/history")
        self.assertEqual(status, 200)
        by_cur = {h["currency"]: h for h in körper["histories"]}
        self.assertIn("EUR", by_cur)
        self.assertIn("USD", by_cur)
        if by_cur["EUR"].get("ok"):
            self.assertGreater(by_cur["EUR"]["days"], 100)

    def test_price_import_csv(self):
        status, körper = self.anfrage(
            "/api/price/import",
            methode="POST",
            daten={
                "currency": "EUR",
                "csv": "date,price\n2099-06-01,123.45\n",
                "filename": "bloomberg.csv",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(körper["imported"], 1)
        self.assertGreaterEqual(körper["days"], 1)
        self.assertTrue((self.immutable / "btc_price" / "EUR.csv").is_file())
