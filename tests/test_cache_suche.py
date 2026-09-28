"""Cache-Suche: dieselbe Grammatik wie der Kopf-Filter, über alle Wallets."""
import unittest

from core.cache_suche import suche_cache


class _Wallet:
    def __init__(self, name, schluessel="zpub"):
        self.display_name = name
        self._schluessel = schluessel

    @property
    def analyse_schluessel(self):
        return self._schluessel

    def wallet_id(self):
        return "id-" + self.display_name


class TestCacheSuche(unittest.TestCase):
    def test_leere_anfrage_sucht_nicht(self):
        gerufen = []

        def lade(_schluessel):
            gerufen.append(1)
            return [{"txid": "aa", "vout": 0, "value": 1, "address": "bc1q"}]

        ergebnis = suche_cache(
            eintraege=[_Wallet("A")],
            roh="   ",
            lang="de",
            lade_bestand=lade,
            lade_verlauf=lade,
            anreichere_bestand=lambda e: e,
            anreichere_verlauf=lambda e: e,
        )
        self.assertEqual(ergebnis["treffer"], [])
        self.assertEqual(gerufen, [])

    def test_stichwort_ueber_bestand_und_verlauf(self):
        bestand = {
            "A": [{
                "txid": "aa" * 32, "vout": 0, "value": 50_000,
                "address": "bc1qtreffer", "status": {"confirmed": True, "block_time": 1_700_000_000},
            }],
            "B": [{
                "txid": "bb" * 32, "vout": 1, "value": 9,
                "address": "bc1qandere", "status": {"confirmed": True, "block_time": 1_700_000_000},
            }],
        }
        verlauf = {
            "A": [{
                "txid": "cc" * 32, "vout": 0, "value": 80_000, "spent": True,
                "address": "bc1qtrefferalt",
                "status": {"confirmed": True, "block_time": 1_600_000_000},
            }],
        }

        def lade_bestand(schluessel):
            return bestand.get(schluessel)

        def lade_verlauf(schluessel):
            return verlauf.get(schluessel)

        wallets = [_Wallet("A", "A"), _Wallet("B", "B")]
        ergebnis = suche_cache(
            eintraege=wallets,
            roh="treffer",
            lang="de",
            lade_bestand=lade_bestand,
            lade_verlauf=lade_verlauf,
            anreichere_bestand=lambda e: {
                "key": f"{e['txid']}:{e['vout']}",
                "value_sats": e["value"],
                "address": e["address"],
                "txid": e["txid"],
                "vout": e["vout"],
                "time_label": "",
            },
            anreichere_verlauf=lambda e: {
                "key": f"{e['txid']}:{e['vout']}",
                "value_sats": e["value"],
                "address": e["address"],
                "txid": e["txid"],
                "vout": e["vout"],
                "spent": True,
                "time_label": "",
            },
        )
        self.assertEqual(ergebnis["total"], 2)
        self.assertEqual(ergebnis["bestand"], 2)
        self.assertEqual(ergebnis["verlauf"], 1)
        self.assertEqual(ergebnis["treffer"][0]["value_sats"], 80_000)
        self.assertTrue(ergebnis["treffer"][0]["spent"])
        self.assertEqual(ergebnis["treffer"][1]["teil"], "bestand")
        self.assertEqual(ergebnis["treffer"][1]["wallet_id"], "id-A")

    def test_betrag_grenzt_aus(self):
        ergebnis = suche_cache(
            eintraege=[_Wallet("A", "A")],
            roh=">1000",
            lang="de",
            lade_bestand=lambda _s: [
                {"txid": "aa", "vout": 0, "value": 500, "address": "bc1qklein"},
                {"txid": "bb", "vout": 0, "value": 5_000, "address": "bc1qgross"},
            ],
            lade_verlauf=lambda _s: [],
            anreichere_bestand=lambda e: {
                "key": f"{e['txid']}:0",
                "value_sats": e["value"],
                "address": e["address"],
                "txid": e["txid"],
                "vout": 0,
            },
            anreichere_verlauf=lambda e: e,
        )
        self.assertEqual([t["address"] for t in ergebnis["treffer"]], ["bc1qgross"])


if __name__ == "__main__":
    unittest.main()
