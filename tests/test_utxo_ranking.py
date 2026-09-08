"""
UTXO-Rangfolge.

Kernzusicherung: Die Oberfläche muss dieselben Zahlen liefern wie das CLI.
Weicht etwas ab, ist die Kernschicht falsch — nicht die Anzeige.
"""
import json
import tempfile
import unittest
from pathlib import Path

import main
from core.utxos import load_cached_utxos, rank_wallet_utxos, utxo_as_dict
from tests.fixtures import BIP84_CHANGE_0, BIP84_RECEIVE_0, BIP84_ZPUB, txid


def utxo(betrag_sats: int, adresse: str = BIP84_RECEIVE_0, *, marker="a1",
         vout=0, block_time=1_700_000_000, block_height=857_930, confirmed=True):
    return {
        "txid": txid(marker),
        "vout": vout,
        "address": adresse,
        "value": betrag_sats,
        "status": {
            "confirmed": confirmed,
            "block_height": block_height if confirmed else None,
            "block_time": block_time if confirmed else None,
        },
    }


class TestSortierung(unittest.TestCase):

    def setUp(self):
        self.utxos = [
            utxo(61_200, marker="c3"),
            utxo(84_000_000, marker="a1"),
            utxo(124_500, marker="b2"),
        ]

    def test_absteigend_nach_betrag(self):
        ergebnis = rank_wallet_utxos(self.utxos)
        betraege = [e["value_sats"] for e in ergebnis["utxos"]]
        self.assertEqual(betraege, sorted(betraege, reverse=True))

    def test_rang_beginnt_bei_eins(self):
        ergebnis = rank_wallet_utxos(self.utxos)
        self.assertEqual([e["rank"] for e in ergebnis["utxos"]], [1, 2, 3])

    def test_summe_umfasst_alle_utxos(self):
        ergebnis = rank_wallet_utxos(self.utxos)
        self.assertEqual(ergebnis["total_sats"], 84_185_700)
        self.assertEqual(ergebnis["total_count"], 3)

    def test_limit_kuerzt_die_liste_nicht_die_summe(self):
        """
        Sonst liest man aus einer Top-1-Liste einen falschen Wallet-Bestand ab.
        """
        ergebnis = rank_wallet_utxos(self.utxos, limit=1)
        self.assertEqual(ergebnis["shown_count"], 1)
        self.assertEqual(ergebnis["total_count"], 3)
        self.assertEqual(ergebnis["total_sats"], 84_185_700)
        self.assertEqual(ergebnis["shown_sats"], 84_000_000)

    def test_leere_liste(self):
        ergebnis = rank_wallet_utxos([])
        self.assertEqual(ergebnis["total_count"], 0)
        self.assertEqual(ergebnis["total_sats"], 0)
        self.assertEqual(ergebnis["utxos"], [])

    def test_limit_groesser_als_liste(self):
        ergebnis = rank_wallet_utxos(self.utxos, limit=99)
        self.assertEqual(ergebnis["shown_count"], 3)

    def test_datum_sortiert_neueste_zuerst(self):
        utxos = [
            utxo(1000, marker="a1", block_time=1_700_000_000),
            utxo(9_000_000, marker="b2", block_time=1_600_000_000),
            utxo(50, marker="c3", block_time=1_800_000_000),
        ]
        ergebnis = rank_wallet_utxos(utxos, sort="datum")
        zeiten = [e["block_time"] for e in ergebnis["utxos"]]
        self.assertEqual(zeiten, [1_800_000_000, 1_700_000_000, 1_600_000_000])


class TestGleichstandMitCli(unittest.TestCase):
    """Dieselbe Sortierung und dieselbe Summe wie main.list_top_wallet_utxos."""

    def test_reihenfolge_stimmt_mit_dem_cli_ueberein(self):
        utxos = [utxo(500, marker="a1"), utxo(9000, marker="b2"), utxo(70, marker="c3")]
        cli_sortiert = sorted(utxos, key=lambda u: u["value"], reverse=True)
        kern = rank_wallet_utxos(utxos)["utxos"]
        self.assertEqual(
            [u["value"] for u in cli_sortiert],
            [e["value_sats"] for e in kern],
        )

    def test_status_label_identisch_zum_cli(self):
        """status_label ist die unveränderte CLI-Formatierung."""
        einzeln = utxo(1000)
        self.assertEqual(
            utxo_as_dict(einzeln)["status_label"],
            main._format_utxo_status(einzeln),
        )

    def test_time_label_ohne_blockangabe(self):
        """
        Die Oberfläche zeigt Blockhöhe als eigenes Feld; bliebe sie im
        Zeitstempel, stünde sie doppelt da — einmal mit englischer und einmal
        mit deutscher Tausendertrennung.
        """
        eintrag = utxo_as_dict(utxo(1000))
        self.assertNotIn("Block", eintrag["time_label"])
        self.assertIn(eintrag["time_label"], eintrag["status_label"])


class TestEinzelnesUtxo(unittest.TestCase):

    def test_felder(self):
        eintrag = utxo_as_dict(utxo(124_500, marker="b2", vout=1))
        self.assertEqual(eintrag["value_sats"], 124_500)
        self.assertEqual(eintrag["vout"], 1)
        self.assertEqual(eintrag["address"], BIP84_RECEIVE_0)
        self.assertTrue(eintrag["confirmed"])
        self.assertEqual(eintrag["block_height"], 857_930)

    def test_unbestaetigtes_utxo_hat_keine_haltedauer(self):
        eintrag = utxo_as_dict(utxo(1000, confirmed=False))
        self.assertFalse(eintrag["confirmed"])
        self.assertIsNone(eintrag["hold_days"])

    def test_haltedauer_wird_berechnet(self):
        import time

        vor_100_tagen = int(time.time()) - 100 * 86_400
        eintrag = utxo_as_dict(utxo(1000, block_time=vor_100_tagen))
        self.assertEqual(eintrag["hold_days"], 100)

    def test_wallet_zuordnung(self):
        ctx = main.build_wallet_context(
            [BIP84_ZPUB], wallet_names=["Cold Storage"], max_addresses=6
        )
        eintrag = utxo_as_dict(utxo(1000, BIP84_RECEIVE_0), wallet=ctx)
        self.assertEqual(eintrag["wallet"], "Cold Storage")

    def test_fremde_adresse_bleibt_ohne_wallet(self):
        ctx = main.build_wallet_context([BIP84_ZPUB], max_addresses=6)
        fremd = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        self.assertIsNone(utxo_as_dict(utxo(1000, fremd), wallet=ctx)["wallet"])


class TestHerkunftsAnreicherung(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_juengste_sats_kommen_aus_dem_cache(self):
        ziel = self.cache / main.UTXO_INGRESS_CACHE_SUBDIR
        ziel.mkdir(parents=True)
        # load_utxo_ingress_cache prüft txid und vout gegen den Dateiinhalt —
        # ein Eintrag ohne diese Felder gilt zu Recht als ungültig.
        (ziel / f"{txid('b2')}_1.json").write_text(
            json.dumps({
                "txid": txid("b2"),
                "vout": 1,
                "youngest_time": "2025-02-02 11:20",
            }),
            encoding="utf-8",
        )
        eintrag = utxo_as_dict(
            utxo(1000, marker="b2", vout=1), immutable_cache_dir=self.cache
        )
        self.assertEqual(eintrag["youngest_sats_time"], "2025-02-02 11:20")

    def test_ohne_cache_bleibt_das_feld_leer(self):
        eintrag = utxo_as_dict(
            utxo(1000, marker="b2", vout=1), immutable_cache_dir=self.cache
        )
        self.assertIsNone(eintrag["youngest_sats_time"])

    def test_vollstaendiger_baum_liefert_juengste_sats(self):
        from core import trace_cache
        from tests.fixtures import EXTERN_A

        ziel = utxo(1000, marker="b2", vout=1)
        trace_cache.speichern(
            ziel["txid"], 1,
            {
                "found": True,
                "root": {"txid": ziel["txid"], "vout": 1},
                "children": [{"type": "external", "address": EXTERN_A}],
                "summary": {"external_count": 1, "unresolved_inputs": 0},
            },
            self.cache,
            {BIP84_RECEIVE_0},
        )
        (self.cache / main.UTXO_INGRESS_CACHE_SUBDIR).mkdir(parents=True, exist_ok=True)
        (self.cache / main.UTXO_INGRESS_CACHE_SUBDIR / f"{ziel['txid']}_1.json").write_text(
            json.dumps({
                "txid": ziel["txid"],
                "vout": 1,
                "external_time_ts": 1_718_294_400,
                "youngest_time_ts": 1_720_000_000,
            }),
            encoding="utf-8",
        )
        eintrag = utxo_as_dict(
            ziel,
            immutable_cache_dir=self.cache,
            own_addresses={BIP84_RECEIVE_0, BIP84_CHANGE_0},
        )
        self.assertTrue(eintrag["verfolgt"])
        self.assertTrue(eintrag["verfolgt_veraltet"])
        self.assertTrue(
            eintrag["verfolgt_vollstaendig"],
            "Neue Adressen dürfen die jüngsten Sats nicht verschwinden lassen",
        )
        self.assertEqual(eintrag["juengste_sats_ts"], 1_718_294_400)

    def test_unvollstaendiger_baum_zeigt_keine_juengsten_sats(self):
        from core import trace_cache

        ziel = utxo(1000, marker="b2", vout=1)
        trace_cache.speichern(
            ziel["txid"], 1,
            {
                "found": True,
                "root": {"txid": ziel["txid"], "vout": 1},
                "children": [{"type": "external_unresolved", "input_count": 8}],
                "summary": {"external_count": 0, "unresolved_inputs": 8},
            },
            self.cache,
            {BIP84_RECEIVE_0},
        )
        eintrag = utxo_as_dict(ziel, immutable_cache_dir=self.cache)
        self.assertTrue(eintrag["verfolgt"])
        self.assertFalse(eintrag["verfolgt_vollstaendig"])
        self.assertIsNone(eintrag["juengste_sats_ts"])


class TestAdressGruppierung(unittest.TestCase):
    """
    Grundlage für die aufklappbare Adressliste in der Wallet-Ansicht.
    """

    def setUp(self):
        from core.utxos import group_by_address

        self.gruppieren = group_by_address
        self.eintraege = rank_wallet_utxos([
            utxo(84_000_000, BIP84_RECEIVE_0, marker="a1"),
            utxo(124_500, BIP84_RECEIVE_0, marker="c3", vout=1),
            utxo(51_000_000, BIP84_CHANGE_0, marker="b2"),
        ])["utxos"]

    def test_utxos_derselben_adresse_landen_zusammen(self):
        gruppen = self.gruppieren(self.eintraege)
        self.assertEqual(len(gruppen), 2)
        empfang = next(g for g in gruppen if g["address"] == BIP84_RECEIVE_0)
        self.assertEqual(empfang["utxo_count"], 2)

    def test_summe_je_adresse(self):
        gruppen = self.gruppieren(self.eintraege)
        empfang = next(g for g in gruppen if g["address"] == BIP84_RECEIVE_0)
        self.assertEqual(empfang["total_sats"], 84_124_500)

    def test_groesster_bestand_zuerst(self):
        gruppen = self.gruppieren(self.eintraege)
        summen = [g["total_sats"] for g in gruppen]
        self.assertEqual(summen, sorted(summen, reverse=True))

    def test_innerhalb_der_gruppe_nach_betrag(self):
        gruppen = self.gruppieren(self.eintraege)
        empfang = next(g for g in gruppen if g["address"] == BIP84_RECEIVE_0)
        betraege = [u["value_sats"] for u in empfang["utxos"]]
        self.assertEqual(betraege, sorted(betraege, reverse=True))

    def test_zeitspanne_je_adresse(self):
        gruppen = self.gruppieren(self.eintraege)
        empfang = next(g for g in gruppen if g["address"] == BIP84_RECEIVE_0)
        self.assertIsNotNone(empfang["first_seen"])
        self.assertLessEqual(empfang["first_seen"], empfang["last_seen"])

    def test_summe_aller_gruppen_entspricht_dem_gesamtbestand(self):
        gruppen = self.gruppieren(self.eintraege)
        self.assertEqual(
            sum(g["total_sats"] for g in gruppen),
            sum(e["value_sats"] for e in self.eintraege),
        )

    def test_leere_liste(self):
        self.assertEqual(self.gruppieren([]), [])

    def test_rangfolge_liefert_die_gruppierung_gleich_mit(self):
        ergebnis = rank_wallet_utxos([utxo(1000, BIP84_RECEIVE_0)])
        self.assertIn("addresses", ergebnis)
        self.assertEqual(len(ergebnis["addresses"]), 1)


class TestUtxoKennung(unittest.TestCase):

    def test_form_txid_doppelpunkt_vout(self):
        from core.utxos import utxo_key

        self.assertEqual(utxo_key(utxo(1000, marker="a1", vout=3)),
                         f"{txid('a1')}:3")

    def test_kennung_im_eintrag(self):
        eintrag = utxo_as_dict(utxo(1000, marker="b2", vout=1))
        self.assertEqual(eintrag["key"], f"{txid('b2')}:1")

    def test_kennung_passt_zum_trace_format(self):
        """core.trace.parse_ziel muss die Kennung wieder zerlegen können."""
        from core.trace import parse_ziel

        eintrag = utxo_as_dict(utxo(1000, marker="b2", vout=1))
        self.assertEqual(parse_ziel(eintrag["key"]), (txid("b2"), 1))


class TestCacheZugriff(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_fehlender_cache_liefert_none(self):
        """Unterschied zu 'leeres Wallet': None heißt 'noch nie gescannt'."""
        self.assertIsNone(load_cached_utxos(BIP84_ZPUB, self.cache))

    def test_gespeicherte_utxos_werden_gelesen(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo(5000, BIP84_CHANGE_0)], self.cache, 50
        )
        geladen = load_cached_utxos(BIP84_ZPUB, self.cache)
        self.assertIsNotNone(geladen)
        self.assertEqual(len(geladen), 1)
        self.assertEqual(geladen[0]["value"], 5000)

    def test_leeres_wallet_ist_nicht_none(self):
        main.save_xpub_utxo_cache(BIP84_ZPUB, [], self.cache, 50)
        self.assertEqual(load_cached_utxos(BIP84_ZPUB, self.cache), [])


if __name__ == "__main__":
    unittest.main()
