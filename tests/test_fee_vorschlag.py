"""Gebührenvorschlag FIFO-Spend: Umrechnung, +1-Puffer, 0,1-%-Deckel, Fallback."""
import unittest
from decimal import Decimal

from core import fee_vorschlag as fv
from core.bitcoind_rpc import RpcAllowlistError
from httpserver.api.tools import api_fee_suggestion


class TestRegel(unittest.TestCase):

    def test_umrechnung_btc_kvb_zu_sat_vb(self):
        self.assertEqual(fv.btc_kvb_zu_sat_vb("0.00001"), Decimal("1"))
        self.assertEqual(fv.btc_kvb_zu_sat_vb(0.00012345), Decimal("12.345"))
        self.assertEqual(fv.btc_kvb_zu_sat_vb("0.001"), Decimal("100"))
        for unsinn in (None, "x", 0, -0.0001, "nan", "inf"):
            self.assertIsNone(fv.btc_kvb_zu_sat_vb(unsinn), unsinn)

    def test_puffer_naechste_ganze_hoechstens_plus_eins(self):
        self.assertEqual(fv.rate_mit_puffer(Decimal("3.2")), 4)
        self.assertEqual(fv.rate_mit_puffer(Decimal("3.0")), 4)
        self.assertEqual(fv.rate_mit_puffer(Decimal("3.999")), 4)
        self.assertEqual(fv.rate_mit_puffer(Decimal("0.8")), 1)
        self.assertEqual(fv.rate_mit_puffer(Decimal("1")), 2)
        for s in (Decimal("0.1"), Decimal("2.5"), Decimal("17"), Decimal("123.456")):
            r = fv.rate_mit_puffer(s)
            self.assertGreater(r, s)
            self.assertLessEqual(r - s, 1)
        self.assertIsNone(fv.rate_mit_puffer(None))

    def test_vsize_naeherung(self):
        self.assertEqual(fv.vsize_schaetzung(1), 141)       # 10,5 + 68 + 62 → 140,5 ↑
        self.assertEqual(fv.vsize_schaetzung(2), 209)
        self.assertEqual(fv.vsize_schaetzung(3, 1), 246)    # 10,5 + 204 + 31 → 245,5 ↑
        self.assertEqual(fv.vsize_schaetzung(0), 141)       # mindestens 1 Input

    def test_schaetzung_plus_puffer(self):
        erg = fv.gebuehr_vorschlag("0.00003200", betrag_sats=100_000_000, inputs=1)
        self.assertEqual(erg["quelle"], "schaetzung")
        self.assertEqual(erg["sat_vb"], 4)
        self.assertEqual(erg["vsize"], 141)
        self.assertEqual(erg["fee_sats"], 564)
        self.assertAlmostEqual(erg["schaetzung_sat_vb"], 3.2)

    def test_deckel_0_1_prozent(self):
        # 4 sat/vB · 141 vB = 564 sats; 0,1 % von 564 000 = 564 → genau an der Grenze ok
        grenze = fv.gebuehr_vorschlag("0.000032", betrag_sats=564_000, inputs=1)
        self.assertEqual(grenze["quelle"], "schaetzung")
        self.assertEqual(grenze["sat_vb"], 4)
        drueber = fv.gebuehr_vorschlag("0.000032", betrag_sats=563_999, inputs=1)
        self.assertEqual(drueber["quelle"], "deckel")
        self.assertEqual(drueber["sat_vb"], 1)
        self.assertEqual(drueber["fee_sats"], 141)
        self.assertEqual(drueber["rate_ohne_deckel"], 4)
        # Mehr Inputs → größere Tx → Deckel greift früher.
        viele = fv.gebuehr_vorschlag("0.000032", betrag_sats=564_000, inputs=3)
        self.assertEqual(viele["quelle"], "deckel")

    def test_fallback_ohne_schaetzung(self):
        erg = fv.gebuehr_vorschlag(None, betrag_sats=1_000_000, fehler="Insufficient data or no feerate found")
        self.assertEqual(erg["quelle"], "fallback")
        self.assertEqual(erg["sat_vb"], 1)
        self.assertIn("Insufficient", erg["grund"])
        self.assertIsNone(erg["schaetzung_sat_vb"])


class _Client:
    def __init__(self, antwort=None, fehler=None):
        self.antwort, self.fehler, self.aufrufe, self.zu = antwort, fehler, [], False

    def call(self, methode, params=None):
        self.aufrufe.append((methode, params))
        if self.fehler:
            raise self.fehler
        return self.antwort

    def close(self):
        self.zu = True


class TestSchaetzungHolen(unittest.TestCase):

    def setUp(self):
        fv.cache_leeren()
        self.addCleanup(fv.cache_leeren)

    def test_ruft_estimatesmartfee_conf_target_1_und_cacht(self):
        client = _Client({"feerate": 0.00002, "blocks": 1})
        uhr = [100.0]
        erg = fv.schaetzung_holen(lambda: client, jetzt=lambda: uhr[0])
        self.assertEqual(erg, (0.00002, None))
        self.assertEqual(client.aufrufe, [("estimatesmartfee", [1])])
        self.assertTrue(client.zu)
        uhr[0] += 30
        fv.schaetzung_holen(lambda: client, jetzt=lambda: uhr[0])
        self.assertEqual(len(client.aufrufe), 1)   # aus dem Cache
        uhr[0] += 31
        fv.schaetzung_holen(lambda: client, jetzt=lambda: uhr[0])
        self.assertEqual(len(client.aufrufe), 2)

    def test_regtest_ohne_daten(self):
        client = _Client({"errors": ["Insufficient data or no feerate found"], "blocks": 0})
        feerate, fehler = fv.schaetzung_holen(lambda: client)
        self.assertIsNone(feerate)
        self.assertIn("Insufficient data", fehler)

    def test_kein_core_und_node_fehler(self):
        self.assertEqual(fv.schaetzung_holen(lambda: None)[1], "kein Bitcoin Core verbunden")
        fv.cache_leeren()
        feerate, fehler = fv.schaetzung_holen(lambda: _Client(fehler=OSError("weg")))
        self.assertIsNone(feerate)
        self.assertIn("weg", fehler)

    def test_allowlist_verstoss_wird_nicht_verschluckt(self):
        with self.assertRaises(RpcAllowlistError):
            fv.schaetzung_holen(lambda: _Client(fehler=RpcAllowlistError("estimatesmartfee", "Test")))


class _Env:
    def values(self):
        return {}


class _State:
    def env(self):
        return _Env()


class TestApi(unittest.TestCase):

    def setUp(self):
        fv.cache_leeren()
        self.addCleanup(fv.cache_leeren)

    def test_ohne_core_fallback(self):
        erg = api_fee_suggestion(_State(), {"betrag": ["101000000"], "inputs": ["2"]})
        self.assertEqual(erg["quelle"], "fallback")
        self.assertEqual(erg["sat_vb"], 1)
        self.assertEqual(erg["vsize"], 209)
        self.assertEqual(erg["betrag_sats"], 101000000)

    def test_unsinn_400(self):
        from server import ApiError
        for q in ({"betrag": ["x"]}, {"betrag": ["-1"]}, {"inputs": ["0"]}):
            with self.assertRaises(ApiError, msg=q):
                api_fee_suggestion(_State(), q)


if __name__ == "__main__":
    unittest.main()
