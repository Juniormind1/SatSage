"""Seitenweise Listen (ISSUES P2): Reihenfolge, Filter 1:1, nur Fenster angereichert."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock

import main
from core import listen_fenster as lf
from core import trace_cache
from core import utxos as utxos_mod
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_ZPUB, txid
from tests.test_api import ApiTestBasis, utxo


def roh(marker, sats, adresse="bc1qa", hoehe=100, zeit=1_700_000_000, **extra):
    return {"txid": txid(marker), "vout": extra.pop("vout", 0), "address": adresse,
            "value": sats, "status": {"confirmed": True, "block_height": hoehe,
                                      "block_time": zeit}, **extra}


class TestFilterParse(unittest.TestCase):
    """Port von parseKopfFilter."""

    def test_tokens(self):
        f = lf.parse_filter("Kraken >1000 <5000,5 >2000")
        self.assertEqual(f["terms"], ["kraken"])
        self.assertEqual(f["min_sats"], 2000)
        self.assertEqual(f["max_sats"], 5000.5)
        self.assertFalse(f["leer"])

    def test_datum_nach_ist_folgetag(self):
        f = lf.parse_filter(">1.1.25 <05.12.2025")
        self.assertEqual(f["after_ts"], int(datetime(2025, 1, 2).timestamp()))
        self.assertEqual(f["before_ts"], int(datetime(2025, 12, 5).timestamp()))

    def test_browser_grenzen_gewinnen(self):
        f = lf.parse_filter(">1.1.25", nach_ts="123")
        self.assertEqual(f["after_ts"], 123)

    def test_ungueltiges_datum_ist_kein_term(self):
        f = lf.parse_filter(">31.2.25")
        self.assertEqual(f["terms"], [])
        self.assertIsNone(f["after_ts"])

    def test_leer(self):
        self.assertTrue(lf.parse_filter("  ")["leer"])


class TestLabelText(unittest.TestCase):
    """Port von kopfFilterLabelText/softTxClassLabel."""

    def test_utxo_labels(self):
        text = lf.filter_label_text(
            {"mix_arten": ["whirlpool"], "tx_class": "exchange_batch",
             "boerse_namen": ["Kraken"], "exchange_spends": [{"name": " Bitstamp "}]},
            "de",
        )
        for teil in ("whirlpool", "Whirlpool", "Wahrscheinlich Whirlpool-CoinJoin",
                     "Wahrscheinlich Batch-Auszahlung von Exchange", "Kraken", "Bitstamp"):
            self.assertIn(teil, text)

    def test_englisch(self):
        self.assertIn("Whirlpool", lf.filter_label_text({"tx_class": "whirlpool"}, "en"))

    def test_gruppe_sammelt_aus_utxos(self):
        text = lf.filter_label_text(
            {"utxos": [{"mix_arten": [], "tx_class": "bisq_deposit", "boerse_namen": ["b", "A"]}]},
            "de",
        )
        self.assertIn("Bisq", text)
        self.assertIn("A b", text)


class TestReihenfolge(unittest.TestCase):

    def setUp(self):
        self.liste = [
            roh("a1", 500, "bc1qx", hoehe=10),
            roh("b2", 900, "bc1qy", hoehe=12),
            roh("c3", 300, "bc1qx", hoehe=12),
            roh("d4", 700, "bc1qz", hoehe=11),
        ]
        self.f = lf.parse_filter("")

    def keys(self, items):
        return [lf.schluessel(e)[:2] for e in items]

    def test_volumen_gruppen_nach_bestand(self):
        schnitt = lf.Fenster(lambda e: e).schneide(
            self.liste, sort="betrag", art="bestand", modus="volume-desc",
            f=self.f, offset=0, limit=10)
        self.assertEqual([g["address"] for g in schnitt["items"]], ["bc1qy", "bc1qx", "bc1qz"])
        self.assertEqual(schnitt["art"], "gruppen")

    def test_alter_flach_und_stabil(self):
        schnitt = lf.Fenster(lambda e: e).schneide(
            self.liste, sort="betrag", art="bestand", modus="age-desc",
            f=self.f, offset=0, limit=10)
        # Gleiche Höhe: Reihenfolge der Gruppen (bc1qy vor bc1qx) bleibt.
        self.assertEqual(self.keys(schnitt["items"]), ["b2", "c3", "d4", "a1"])

    def test_fenster_und_gesamt(self):
        schnitt = lf.Fenster(lambda e: e).schneide(
            self.liste, sort="betrag", art="bestand", modus="age-asc",
            f=self.f, offset=1, limit=2)
        self.assertEqual(schnitt["total"], 4)
        self.assertEqual(self.keys(schnitt["items"]), ["d4", "b2"])

    def test_anreichern_nur_bei_bedarf(self):
        gerufen = []
        fenster = lf.Fenster(lambda e: gerufen.append(e) or dict(e, value_sats=lf.wert(e)))
        fenster.schneide(self.liste, sort="betrag", art="bestand", modus="age-desc",
                         f=lf.parse_filter(">600"), offset=0, limit=1)
        self.assertEqual(gerufen, [])


class TestFilterGruppe(unittest.TestCase):

    def test_gruppe_passt_ueber_adresse_betrag_je_blatt(self):
        liste = [roh("a1", 500, "bc1qkraken"), roh("b2", 5000, "bc1qkraken"),
                 roh("c3", 9000, "bc1qandere")]
        schnitt = lf.Fenster(lambda e: dict(e, value_sats=lf.wert(e))).schneide(
            liste, sort="betrag", art="bestand", modus="volume-desc",
            f=lf.parse_filter("kraken >1000"), offset=0, limit=10)
        self.assertEqual([g["address"] for g in schnitt["items"]], ["bc1qkraken"])

    def test_blatt_label_aus_anreicherung(self):
        liste = [roh("a1", 500, "bc1qa"), roh("b2", 700, "bc1qb")]

        def anreichern(e):
            voll = dict(e, value_sats=lf.wert(e), key=lf.schluessel(e), time_label="")
            voll["boerse_namen"] = ["Kraken"] if e["address"] == "bc1qb" else []
            return voll

        schnitt = lf.Fenster(anreichern).schneide(
            liste, sort="betrag", art="bestand", modus="age-desc",
            f=lf.parse_filter("KRAKEN"), offset=0, limit=10)
        self.assertEqual([e["address"] for e in schnitt["items"]], ["bc1qb"])


class TestFensterCaches(unittest.TestCase):
    """Schritt 6: Label-Auszug über Anfragen, Abdruck, kleiner LRU."""

    def test_label_cache_spart_anreichern_und_filtert_gleich(self):
        liste = [roh("a1", 500, "bc1qa"), roh("b2", 700, "bc1qb", vout=1),
                 roh("c3", 900, "bc1qb", vout=2)]
        gerufen = []

        def anreichern(e):
            gerufen.append(e)
            voll = dict(e, value_sats=lf.wert(e), key=lf.schluessel(e), time_label="",
                        viel="x" * 100)
            voll["boerse_namen"] = ["Kraken"] if e["vout"] == 1 else []
            voll["mix_arten"] = ["whirlpool"] if e["vout"] == 2 else []
            voll["exchange_spends"] = [{"name": "Bitstamp", "sats": 5}] if e["vout"] == 2 else []
            return voll

        def lauf(cache, q, modus):
            return lf.Fenster(anreichern, label_cache=cache).schneide(
                liste, sort="betrag", art="bestand", modus=modus,
                f=lf.parse_filter(q), offset=0, limit=10)

        for q in ("kraken", "whirlpool", "bitstamp", "kraken whirlpool", "nix"):
            for modus in ("age-desc", "volume-desc"):
                ohne = lauf(None, q, modus)
                cache = {}
                mit = lauf(cache, q, modus)
                self.assertEqual(mit["total"], ohne["total"], (q, modus))
                gerufen.clear()
                wieder = lauf(cache, q, modus)
                self.assertEqual(wieder["total"], ohne["total"])
                self.assertEqual(gerufen, [], (q, modus))
        self.assertNotIn("viel", next(iter(cache.values())))

    def test_label_auszug_gleicher_text(self):
        voll = {"mix_arten": ["wabisabi"], "tx_class": "wabisabi", "boerse_namen": ["Kraken"],
                "exchange_spends": [{"name": "Bitstamp", "sats": 1}],
                "label": {"name": "Coinbase", "kategorie": "exchange"}, "address": "bc1q"}
        for sprache in ("de", "en"):
            self.assertEqual(lf.filter_label_text(lf.label_auszug(voll), sprache),
                             lf.filter_label_text(voll, sprache))

    def test_abdruck_aendert_sich_mit_datei_und_ordner(self):
        import tempfile, time
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            klein, gross = Path(tmp, "k"), Path(tmp, "g")
            klein.mkdir(); gross.mkdir()
            (klein / "a.json").write_text("1")
            a = lf.datei_abdruck(dateien=[klein], ordner=[gross])
            self.assertEqual(a, lf.datei_abdruck(dateien=[klein], ordner=[gross]))
            time.sleep(0.01)
            (klein / "a.json").write_text("22")
            b = lf.datei_abdruck(dateien=[klein], ordner=[gross])
            self.assertNotEqual(a, b)
            tmpd = gross / "x.json.tmp"
            tmpd.write_text("1"); tmpd.replace(gross / "x.json")
            self.assertNotEqual(b, lf.datei_abdruck(dateien=[klein], ordner=[gross]))

    def test_klein_cache_lru(self):
        c = lf.KleinCache(2)
        c.lege("a", 1); c.lege("b", 2); c.hole("a"); c.lege("c", 3)
        self.assertEqual((c.hole("a"), c.hole("b"), c.hole("c")), (1, None, 3))


class TestFensterApi(ApiTestBasis):
    """``?seite=1`` an /api/utxos und /api/wallets/<id>/utxos."""

    def setUp(self):
        super().setUp()
        self.bestand = [utxo(84_000 - i * 1000, marker=f"{i:02x}", vout=i)
                        for i in range(7)]
        self.bestand.append(utxo(99_000, BIP84_RECEIVE_1, marker="ee"))
        main.save_xpub_utxo_cache(BIP84_ZPUB, self.bestand, self.cache, 6)

    def test_ohne_seite_unveraendert(self):
        _, körper = self.anfrage("/api/utxos?mempool=0")
        self.assertNotIn("fenster", körper)
        self.assertEqual(len(körper["utxos"]), 8)

    def test_volumen_seite_zwei(self):
        _, alt = self.anfrage("/api/utxos?mempool=0")
        _, körper = self.anfrage(
            "/api/utxos?mempool=0&seite=1&modus=volume-desc&offset=1&limit=1")
        self.assertEqual(körper["fenster"]["total"], 2)
        self.assertEqual(körper["total_count"], 8)
        self.assertEqual(körper["total_sats"], alt["total_sats"])
        self.assertEqual([g["address"] for g in körper["addresses"]],
                         [alt["addresses"][1]["address"]])
        self.assertEqual([u["key"] for u in körper["addresses"][0]["utxos"]],
                         [u["key"] for u in alt["addresses"][1]["utxos"]])

    def test_alter_seite_nur_fenster_angereichert(self):
        echt = utxos_mod.utxo_as_dict
        with mock.patch.object(utxos_mod, "utxo_as_dict", side_effect=echt) as spion:
            _, körper = self.anfrage(
                "/api/utxos?mempool=0&seite=1&modus=age-asc&offset=2&limit=3")
        self.assertEqual(len(körper["utxos"]), 3)
        self.assertEqual(spion.call_count, 3)
        self.assertEqual(körper["fenster"]["art"], "utxos")
        self.assertEqual(körper["addresses"], [])

    def test_filter_ueber_alle_seiten(self):
        trace_cache.speichern(
            txid("06"), 6,
            {"found": True, "root": {"txid": txid("06"), "vout": 6},
             "children": [{"type": "external", "label": {"name": "Kraken", "kategorie": "exchange"}}]},
            self.immutable)
        with mock.patch.object(trace_cache, "boerse_namen_im_baum", return_value=["Kraken"]):
            trace_cache.speichern(
                txid("06"), 6, {"found": True, "root": {}, "children": []}, self.immutable)
        _, körper = self.anfrage(
            "/api/utxos?mempool=0&seite=1&modus=age-desc&limit=10&q=kraken")
        self.assertEqual([u["key"] for u in körper["utxos"]], [f"{txid('06')}:6"])
        self.assertEqual(körper["fenster"]["total"], 1)

    def test_stichwortsuche_nutzt_label_cache(self):
        echt = utxos_mod.utxo_as_dict
        url = "/api/utxos?mempool=0&seite=1&modus=age-desc&limit=2&q=zz"
        with mock.patch.object(utxos_mod, "utxo_as_dict", side_effect=echt) as spion:
            _, erst = self.anfrage(url)
            erst_n = spion.call_count
            spion.reset_mock()
            _, zweit = self.anfrage(url + "zz")
            self.assertEqual(erst["fenster"]["total"], 0)
            self.assertEqual(zweit["fenster"]["total"], 0)
            # Zweite Suche: keine Anreicherung mehr für den Label-Abgleich.
            self.assertEqual(spion.call_count, 0)
        self.assertEqual(erst_n, 8)
        # Neuer Cache-Stand → Abdruck anders → wieder angereichert.
        main.save_xpub_utxo_cache(BIP84_ZPUB, self.bestand[:3], self.cache, 6)
        with mock.patch.object(utxos_mod, "utxo_as_dict", side_effect=echt) as spion:
            _, dritt = self.anfrage(url + "zz")
            self.assertEqual(spion.call_count, 3)
        self.assertEqual(dritt["total_count"], 3)

    def test_betrag_filter(self):
        _, körper = self.anfrage(
            "/api/utxos?mempool=0&seite=1&modus=age-desc&limit=10&q=%3E80000")
        self.assertEqual(sorted(u["value_sats"] for u in körper["utxos"]), [81_000, 82_000, 83_000, 84_000, 99_000])

    def test_wallet_gruppen_seite(self):
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(
            f"/api/wallets/{kennung}/utxos?mempool=0&seite=1&modus=gruppen&limit=1")
        self.assertEqual(körper["fenster"]["total"], 2)
        self.assertEqual(len(körper["addresses"]), 1)
        self.assertTrue(körper["has_cache"])
        self.assertIn("sanctions", körper)

    def test_pending_spending_keys_ueber_den_ganzen_bestand(self):
        """FIFO-Spend zieht Mempool-Ausgaben ab: Schlüssel über den Bestand, nicht nur das Fenster."""
        bestand = [dict(u) for u in self.bestand]
        bestand[6]["spending_pending"] = True   # kleinster Betrag, nicht auf Seite 1
        main.save_xpub_utxo_cache(BIP84_ZPUB, bestand, self.cache, 6)
        kennung = self.wallet_id(BIP84_ZPUB)
        _, körper = self.anfrage(
            f"/api/wallets/{kennung}/utxos?mempool=0&seite=1&modus=gruppen&limit=1")
        self.assertEqual(körper["pending_spending_count"], 1)
        self.assertEqual(körper["pending_spending_keys"], [f"{txid('06')}:6"])
        main.save_xpub_utxo_cache(BIP84_ZPUB, self.bestand, self.cache, 6)
        _, ohne = self.anfrage(
            f"/api/wallets/{kennung}/utxos?mempool=0&seite=1&modus=gruppen&limit=1")
        self.assertEqual(ohne["pending_spending_keys"], [])

    def test_verlauf_seite_ohne_mempool_rundlauf(self):
        """Aufklappen darf keinen Electrs-Check anstoßen, auch ohne mempool=0."""
        from unittest import mock

        verlauf = [dict(roh(f"{i:02x}", 1000 + i, BIP84_RECEIVE_0, vout=i), spent=True,
                        spent_txid=txid("ff"), spent_time_ts=1_700_000_000 + i)
                   for i in range(5)]
        main.save_xpub_verlauf_cache(BIP84_ZPUB, verlauf, self.cache)
        kennung = self.wallet_id(BIP84_ZPUB)
        with mock.patch("server._eigener_fulcrum_client") as client:
            _, körper = self.anfrage(
                f"/api/wallets/{kennung}/utxos?seite=1&teil=verlauf"
                "&modus=age-desc&limit=2")
            client.assert_not_called()
        self.assertEqual(körper["verlauf"]["fenster"]["total"], 5)
        self.assertEqual(len(körper["verlauf"]["utxos"]), 2)
        self.assertFalse(körper["mempool_checked"])

    def test_verlauf_seite(self):
        verlauf = [dict(roh(f"{i:02x}", 1000 + i, BIP84_RECEIVE_0, vout=i), spent=True,
                        spent_txid=txid("ff"), spent_time_ts=1_700_000_000 + i)
                   for i in range(5)]
        main.save_xpub_verlauf_cache(BIP84_ZPUB, verlauf, self.cache)
        _, meta = self.anfrage("/api/utxos?mempool=0&seite=1&limit=1")
        self.assertEqual(meta["verlauf"]["total_count"], 5)
        self.assertEqual(meta["verlauf"]["utxos"], [])
        _, körper = self.anfrage(
            "/api/utxos?mempool=0&seite=1&teil=verlauf&modus=age-desc&sort=datum&offset=1&limit=2")
        v = körper["verlauf"]
        self.assertEqual(v["fenster"]["total"], 5)
        self.assertEqual(len(v["utxos"]), 2)
        self.assertTrue(all(u["spent"] for u in v["utxos"]))


if __name__ == "__main__":
    unittest.main()
