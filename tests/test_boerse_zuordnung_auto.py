"""Auto-Bestätigung, Schwellen, Anzeige-Felder und Logs ohne Kennungen."""
from __future__ import annotations

import unittest
from datetime import datetime

from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, txid
from core.boerse.modell import Zuordnung
from core.boerse.schwellen import (
    Schwellen,
    auto_erlaubt,
    lese_zuordnung_einstellungen,
    standard,
)
from core.boerse.zuordnung import (
    gui_felder,
    schlage_vor,
    setze_status,
    txid_kurz,
)
from tests.test_boerse_zuordnung import T0, _aus, _empf, KETTE, ANDERER


class SchwellenDefaultTest(unittest.TestCase):
    def test_defaults_wie_bisher(self):
        s = lese_zuordnung_einstellungen({})
        self.assertEqual(s.fenster_vor_s, 3600)
        self.assertEqual(s.fenster_nach_s, 72 * 3600)
        self.assertEqual(s.max_delta_sats, 0)
        self.assertEqual(s.max_delta_rel, 0.0)
        self.assertFalse(s.gebuehr_als_toleranz)
        self.assertFalse(s.auto)
        self.assertTrue(s.auto_adresse)
        self.assertEqual(s.auto_min_abstand_s, 0)


class AutoBestaetigungTest(unittest.TestCase):
    def test_ohne_auto_bleibt_vorschlag(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, adresse=BIP84_RECEIVE_0, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10, adresse=BIP84_RECEIVE_0)],
            schwellen=standard(),
        )
        self.assertEqual(lauf.zuordnungen[0].status, "vorschlag")
        self.assertIsNone(lauf.zuordnungen[0].bestaetigt_durch)

    def test_auto_bei_eindeutigem_adresstreffer(self):
        s = Schwellen(auto=True, auto_adresse=True)
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, adresse=BIP84_RECEIVE_0, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10, adresse=BIP84_RECEIVE_0)],
            schwellen=s,
        )
        z = lauf.zuordnungen[0]
        self.assertEqual(z.status, "bestaetigt")
        self.assertEqual(z.bestaetigt_durch, "auto")
        self.assertEqual(z.auto_grund, "eindeutig_adresse")
        self.assertEqual(z.methode, "adresse")

    def test_auto_ohne_adresse_bleibt_vorschlag(self):
        s = Schwellen(auto=True, auto_adresse=True)
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10)],
            schwellen=s,
        )
        self.assertEqual(lauf.zuordnungen[0].status, "vorschlag")
        self.assertEqual(lauf.zuordnungen[0].methode, "betrag_zeit")

    def test_auto_greift_nie_bei_mehrdeutigkeit(self):
        s = Schwellen(auto=True, auto_adresse=True)
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, adresse=BIP84_RECEIVE_0, konto="kraken")],
            [
                _empf(KETTE, zeit=T0 + 10, adresse=BIP84_RECEIVE_0),
                _empf(ANDERER, zeit=T0 + 20, adresse=BIP84_RECEIVE_0),
            ],
            schwellen=s,
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(len(lauf.quarantaene), 1)
        self.assertEqual(lauf.quarantaene[0]["grund"], "mehrere Kandidaten")

    def test_auto_min_abstand_0_blockt_zweiten(self):
        self.assertFalse(auto_erlaubt(2, 10_000, True, Schwellen(auto=True, auto_min_abstand_s=0)))
        self.assertTrue(auto_erlaubt(1, None, True, Schwellen(auto=True)))
        self.assertFalse(auto_erlaubt(1, None, False, Schwellen(auto=True, auto_adresse=True)))


class AnzeigeFelderTest(unittest.TestCase):
    def test_gui_felder_ohne_log_pflicht(self):
        z = Zuordnung("kraken", "LSYN-1", KETTE, 0, 500_000, "adresse", "vorschlag")
        b = _aus("LSYN-1", -500_000, konto="kraken", gebuehr=10_000)
        e = _empf(KETTE, zeit=T0 + 600, adresse=BIP84_RECEIVE_0)
        e = type(e)(**{**e.__dict__, "wallet": "Cold"})
        d = gui_felder(z, b, e, "Cold")
        self.assertEqual(d["auszahlung_sats"], 500_000)
        self.assertTrue(d["auszahlung_datum"])
        self.assertEqual(d["txid_kurz"], txid_kurz(KETTE))
        self.assertIn("…", d["txid_kurz"])
        self.assertEqual(d["txid"], KETTE)
        self.assertEqual(d["wallet"], "Cold")
        self.assertEqual(d["zeitabstand_s"], 600)
        self.assertEqual(d["betrag_delta_sats"], 0)
        self.assertEqual(d["gebuehr_sats"], 10_000)


class LogOhneKennungenTest(unittest.TestCase):
    def test_kalibrier_log_ohne_refs_und_txids(self):
        s = Schwellen(auto=True, auto_adresse=True)
        with self.assertLogs("satsage.boerse", level="INFO") as cm:
            schlage_vor(
                [_aus("LSYN-1", -500_000, adresse=BIP84_RECEIVE_0, konto="kraken")],
                [_empf(KETTE, zeit=T0 + 10, adresse=BIP84_RECEIVE_0)],
                schwellen=s,
            )
        text = "\n".join(cm.output)
        self.assertIn("zuordnung_kandidat", text)
        self.assertIn("entscheidung=auto", text)
        self.assertNotIn("LSYN-1", text)
        self.assertNotIn(KETTE, text)
        self.assertNotIn(BIP84_RECEIVE_0, text)
        self.assertIn("ref:", text)

    def test_nutzerentscheidung_log_ohne_txid(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10)],
        )
        with self.assertLogs("satsage.boerse", level="INFO") as cm:
            setze_status(
                lauf.zuordnungen, konto="kraken", auszahlung_ref="LSYN-1",
                status="bestaetigt", bestaetigt_ts=T0 + 20,
            )
        text = "\n".join(cm.output)
        self.assertIn("zuordnung_entscheidung", text)
        self.assertIn("status=bestaetigt", text)
        self.assertNotIn("LSYN-1", text)
        self.assertNotIn(KETTE, text)


class KalibrierSkriptTest(unittest.TestCase):
    def test_auswertung_aus_synthetischem_log(self):
        from scripts.zuordnung_kalibrierung import auswerten

        log = (
            "INFO zuordnung_kandidat ref=ref:abcd1234 methode=adresse "
            "zeit_min_bucket=0-1 delta_rel_bucket=0 n_kandidaten=1 "
            "abstand_zweit_min_bucket=unbekannt entscheidung=vorschlag\n"
            "INFO zuordnung_entscheidung ref=ref:abcd1234 status=bestaetigt "
            "vorher=vorschlag methode=adresse bisher_durch=-\n"
        )
        # parse via _lesen is file-based; use _parse through auswerten input
        from scripts.zuordnung_kalibrierung import _parse_zeile
        eintraege = [_parse_zeile(z) for z in log.splitlines() if _parse_zeile(z)]
        text = auswerten(eintraege)
        self.assertIn("eindeutig (n=1): 1", text)
        self.assertIn("davon Adresstreffer: 1", text)
        self.assertIn("1 bestätigt, 0 abgelehnt", text)
        self.assertNotIn("LSYN", text)


if __name__ == "__main__":
    unittest.main()
