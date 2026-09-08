"""
Verlaufs-Cache (utxo_cache/{xpub}_verlauf.json) und dessen Orchestrierung.

Getrennt vom normalen UTXO-Cache: hier geht es um den On-Demand-Vollscan, der
auch ausgegebene Outputs festhält. Läuft ausschließlich in temporären
Verzeichnissen — keine echten Cache-Dateien werden angefasst.
"""
import unittest


import tempfile
import unittest
from pathlib import Path

import main
from tests.fixtures import txid

XPUB_A = "xpubTESTA"
XPUB_B = "xpubTESTB"


class VerlaufCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)

    def test_load_ohne_datei_ist_none(self):
        self.assertIsNone(main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir))

    def test_speichern_und_laden_liefert_dieselben_eintraege(self):
        eintraege = [
            {"txid": txid("a1"), "vout": 0, "value": 100_000, "spent": False, "spent_txid": None},
            {"txid": txid("a2"), "vout": 0, "value": 200_000, "spent": True, "spent_txid": txid("b1")},
        ]
        main.save_xpub_verlauf_cache(XPUB_A, eintraege, self.cache_dir)

        geladen = main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir)
        self.assertEqual(geladen, eintraege)

    def test_cache_dateien_verschiedener_xpubs_kollidieren_nicht(self):
        main.save_xpub_verlauf_cache(XPUB_A, [{"txid": txid("a1"), "vout": 0}], self.cache_dir)
        main.save_xpub_verlauf_cache(XPUB_B, [{"txid": txid("b1"), "vout": 0}], self.cache_dir)

        self.assertEqual(
            main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir),
            [{"txid": txid("a1"), "vout": 0}],
        )
        self.assertEqual(
            main.load_xpub_verlauf_cache(XPUB_B, self.cache_dir),
            [{"txid": txid("b1"), "vout": 0}],
        )

    def test_defekte_datei_liefert_none_statt_absturz(self):
        path = main._xpub_verlauf_cache_path(XPUB_A, self.cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("kein json{", encoding="utf-8")
        self.assertIsNone(main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir))


class ResolveWalletVerlaufTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)

        self.wallet = main.WalletContext(
            xpubs=[XPUB_A, XPUB_B],
            names_by_xpub={XPUB_A: "Erstes", XPUB_B: "Zweites"},
            address_to_wallet={
                "addr-a-1": "Erstes",
                "addr-a-2": "Erstes",
                "addr-b-1": "Zweites",
            },
            address_to_xpub={
                "addr-a-1": XPUB_A,
                "addr-a-2": XPUB_A,
                "addr-b-1": XPUB_B,
            },
            max_addresses_by_xpub={XPUB_A: 50, XPUB_B: 50},
        )
        self.aufrufe: list[set] = []

    def _fake_fetch_wallet_history(self, adressen, **kwargs) -> list[dict]:
        self.aufrufe.append((set(adressen), dict(kwargs)))
        # Resume-fähiger Fetcher: on_address_done je Adresse aufrufen.
        seed = list(kwargs.get("seed_eintraege") or [])
        skip = set(kwargs.get("skip_addresses") or [])
        on_done = kwargs.get("on_address_done")
        ergebnis = list(seed)
        for adresse in adressen:
            if adresse in skip:
                continue
            neu = [{"txid": txid("aa"), "vout": 0, "address": adresse}]
            ergebnis.extend(neu)
            if on_done:
                on_done(adresse, neu)
        return ergebnis

    def test_ruft_pro_xpub_nur_dessen_eigene_adressen_ab(self):
        main.resolve_wallet_verlauf(
            [XPUB_A, XPUB_B], self._fake_fetch_wallet_history, self.cache_dir, self.wallet,
        )
        self.assertEqual(len(self.aufrufe), 2)
        self.assertEqual(self.aufrufe[0][0], {"addr-a-1", "addr-a-2"})
        self.assertEqual(self.aufrufe[1][0], {"addr-b-1"})

    def test_setzt_nach_abbruch_bei_gescannten_adressen_fort(self):
        # Erster Lauf: bricht nach der ersten Adresse ab (incomplete speichern).
        def erst_teilweise(adressen, **kwargs):
            on_done = kwargs["on_address_done"]
            seed = list(kwargs.get("seed_eintraege") or [])
            adresse = sorted(adressen)[0]
            neu = [{"txid": txid("p1"), "vout": 0, "address": adresse, "value": 1}]
            on_done(adresse, neu)
            return seed + neu

        main.resolve_wallet_verlauf(
            [XPUB_A], erst_teilweise, self.cache_dir, self.wallet,
        )
        # Manuell incomplete lassen — resolve markiert fertig wenn scanned==geplant.
        # Deshalb incomplete erzwingen:
        eintraege = main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir)
        main.save_xpub_verlauf_cache(
            XPUB_A, eintraege, self.cache_dir,
            scanned_addresses=[sorted(["addr-a-1", "addr-a-2"])[0]],
            planned_addresses=sorted(["addr-a-1", "addr-a-2"]),
            incomplete=True,
        )
        meta = main.load_xpub_verlauf_scan_meta(XPUB_A, self.cache_dir)
        self.assertTrue(meta["incomplete"])

        gesehen = []

        def zweiter(adressen, **kwargs):
            gesehen.append(set(kwargs.get("skip_addresses") or []))
            on_done = kwargs["on_address_done"]
            skip = set(kwargs.get("skip_addresses") or [])
            seed = list(kwargs.get("seed_eintraege") or [])
            ergebnis = list(seed)
            for adresse in adressen:
                if adresse in skip:
                    continue
                neu = [{"txid": txid("p2"), "vout": 0, "address": adresse, "value": 2}]
                ergebnis.extend(neu)
                on_done(adresse, neu)
            return ergebnis

        main.resolve_wallet_verlauf(
            [XPUB_A], zweiter, self.cache_dir, self.wallet,
        )
        self.assertEqual(len(gesehen[0]), 1)
        meta2 = main.load_xpub_verlauf_scan_meta(XPUB_A, self.cache_dir)
        self.assertFalse(meta2["incomplete"])
        final = main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir)
        self.assertEqual(len(final), 2)

    def test_speichert_ergebnis_pro_xpub_im_cache(self):
        main.resolve_wallet_verlauf(
            [XPUB_A], self._fake_fetch_wallet_history, self.cache_dir, self.wallet,
        )
        gecacht = main.load_xpub_verlauf_cache(XPUB_A, self.cache_dir)
        self.assertEqual(len(gecacht), 1)

    def test_gibt_ergebnis_je_xpub_zurueck(self):
        ergebnis = main.resolve_wallet_verlauf(
            [XPUB_A, XPUB_B], self._fake_fetch_wallet_history, self.cache_dir, self.wallet,
        )
        self.assertEqual(set(ergebnis), {XPUB_A, XPUB_B})


if __name__ == "__main__":
    unittest.main()
