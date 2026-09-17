"""Börsen-CSV-Import: nur BTC-Adressen/TxIDs, Trace-Label."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import exchange_reports as boerse
from core import trace as trace_mod
import labels


KRK_ADDR = "bc1qkrakenxxxxxxxxxxxxxxxxxxxxxxxxxx0"
TX_DEP = "a" * 64
TX_WD = "b" * 64


class TestParseCsv(unittest.TestCase):
    def test_header_address_txid_btc_only(self):
        csv = (
            "Type,Asset,Address,Txid,Amount\n"
            f"deposit,BTC,{KRK_ADDR},{TX_DEP},0.1\n"
            "deposit,ETH,0xdeadbeef,cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc,1.0\n"
            f"withdrawal,XBT,{KRK_ADDR},{TX_WD},0.05\n"
            "trade,BTC,,,1000\n"
        )
        p = boerse.parse_csv_btc_refs(csv)
        self.assertIn(KRK_ADDR, p["addresses"])
        self.assertIn(TX_DEP, p["txids"])
        self.assertIn(TX_WD, p["txids"])
        self.assertNotIn("0xdeadbeef", p["addresses"])
        roles = p["addresses"][KRK_ADDR]["roles"]
        self.assertIn("deposit", roles)
        self.assertIn("withdrawal", roles)

    def test_semicolon_and_shitcoin_asset(self):
        csv = (
            "currency;txid;type\n"
            f"BTC;{TX_DEP};Deposit\n"
            f"DOGE;{TX_WD};Deposit\n"
        )
        p = boerse.parse_csv_btc_refs(csv)
        self.assertIn(TX_DEP, p["txids"])
        self.assertNotIn(TX_WD, p["txids"])

    def test_ohne_btc_refs_fehler(self):
        with self.assertRaises(boerse.ExchangeReportError):
            boerse.parse_csv_btc_refs("a,b\n1,2\n")

    def test_reine_adressliste_ohne_kopf(self):
        legacy = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        p2sh = "3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy"
        bech = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        text = f"{legacy}\n{p2sh}\n{bech}\n# kommentar\n\n"
        p = boerse.parse_csv_btc_refs(text)
        self.assertIn(legacy, p["addresses"])
        self.assertIn(p2sh, p["addresses"])
        self.assertIn(bech, p["addresses"])
        self.assertEqual(len(p["addresses"]), 3)

    def test_liste_mit_txid_ohne_kopf(self):
        text = f"{KRK_ADDR}\n{TX_DEP}\n"
        p = boerse.parse_csv_btc_refs(text)
        self.assertIn(KRK_ADDR, p["addresses"])
        self.assertIn(TX_DEP, p["txids"])


class TestExchangeBatchSoftLabel(unittest.TestCase):
    def test_auszahlung_von_namen(self):
        from core.tx_classify import soft_label_exchange_batch

        self.assertEqual(
            soft_label_exchange_batch(["Kraken"], lang="de"),
            "u. a. Auszahlung von Kraken",
        )
        self.assertEqual(
            soft_label_exchange_batch(["Kraken", "Coinbase"], lang="de"),
            "u. a. Auszahlung von Kraken, Coinbase",
        )
        self.assertTrue(
            soft_label_exchange_batch([], lang="de").startswith("Wahrscheinlich"),
        )


class TestBoerseNamenImBaum(unittest.TestCase):
    def test_sammelt_exchange_labels(self):
        from core import trace_cache as tc

        baum = {
            "root": {"type": "internal", "children": []},
            "children": [
                {
                    "type": "external",
                    "label": {
                        "name": "Kraken",
                        "kategorie": "exchange",
                        "nutzer_import": True,
                    },
                    "children": [],
                },
                {
                    "type": "external",
                    "exchange_label": {
                        "name": "Coinbase",
                        "kategorie": "exchange",
                    },
                    "children": [],
                },
                {
                    "type": "external",
                    "label": {"name": "OFAC", "kategorie": "sanction"},
                    "children": [],
                },
            ],
        }
        namen = tc.boerse_namen_im_baum(baum)
        self.assertEqual(namen, ["Coinbase", "Kraken"])

    def test_oberflaeche_boerse_nur_name_mit_farbe(self):
        js = (
            Path(__file__).resolve().parent.parent / "web" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function istBoersenLabel", js)
        self.assertIn("label-boerse-in", js)
        self.assertIn("label-boerse-out", js)
        # Anzeige nur Name, kein „Börse · …“-Prefix für Exchanges.
        start = js.index("if (istBoersenLabel(label))")
        block = js[start:start + 500]
        self.assertIn("marke.textContent = name", block)


class TestImportUndLabel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        boerse.setze_verzeichnis(self.dir)
        self.addCleanup(boerse.setze_verzeichnis, None)
        labels.setze_verzeichnis(self.dir / "labels_empty")
        self.addCleanup(labels.setze_verzeichnis, None)

    def test_import_merge_und_beschrifte(self):
        csv = (
            "address,txid,type,asset\n"
            f"{KRK_ADDR},{TX_DEP},deposit,BTC\n"
        )
        r = boerse.importiere_csv(
            csv, name="Kraken", filename="k.csv", cache_dir=self.dir,
        )
        self.assertEqual(r["slug"], "kraken")
        self.assertEqual(r["imported_addresses"], 1)
        self.assertTrue((self.dir / "kraken.json").is_file())

        lab = labels.beschrifte(KRK_ADDR)
        self.assertIsNotNone(lab)
        self.assertEqual(lab["name"], "Kraken")
        self.assertTrue(lab.get("nutzer_import"))
        self.assertEqual(lab.get("rolle"), "Einzahlung")

        lab_tx = labels.beschrifte("", txid=TX_DEP)
        self.assertIsNotNone(lab_tx)
        self.assertEqual(lab_tx["name"], "Kraken")

    def test_trace_external_nutzt_boerse(self):
        boerse.importiere_csv(
            f"address,asset\n{KRK_ADDR},BTC\n",
            name="Bitstamp",
            cache_dir=self.dir,
        )
        knoten = trace_mod._kind_knoten(
            {
                "type": "external",
                "address": KRK_ADDR,
                "amount_sats": 10_000,
                "from_utxo": f"{TX_DEP}:0",
            },
            None,
            "0",
            1,
        )
        self.assertIsNotNone(knoten["label"])
        self.assertEqual(knoten["label"]["name"], "Bitstamp")

    def test_loesche(self):
        boerse.importiere_csv(
            f"txid,asset\n{TX_DEP},BTC\n",
            name="Binance",
            cache_dir=self.dir,
        )
        self.assertTrue(boerse.loesche("binance", self.dir))
        self.assertIsNone(labels.beschrifte("", txid=TX_DEP))

    def test_trace_stoppt_an_boerse_txid(self):
        """Wallet-UTXO aus Börsen-Auszahlungs-Tx: keine Prevout-Hops hinter die Börse."""
        import analyze
        from tests.fixtures import core_tx, core_vin, core_vout, make_get_tx, txid

        boerse.importiere_csv(
            f"txid,type,asset\n{TX_WD},withdrawal,BTC\n",
            name="Kraken",
            cache_dir=self.dir,
        )
        own = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
        fremd = "bc1qpeerbehindxxxxxxxxxxxxxxxxxxxxxx0"
        funding = txid("f1")
        # Prevout hinter der Börsen-Tx — darf nicht betreten werden.
        chain = {
            funding: core_tx(
                funding,
                [{"coinbase": "00", "sequence": 0}],
                [core_vout(0, fremd, 1.0)],
            ),
            TX_WD: core_tx(
                TX_WD,
                [core_vin(funding, 0)],
                [core_vout(0, own, 0.9)],
            ),
        }
        node = analyze.trace_utxo_origin(
            make_get_tx(chain),
            TX_WD,
            0,
            {own},
        )
        self.assertTrue(node.get("exchange_stop"))
        self.assertEqual(len(node.get("sources") or []), 1)
        self.assertEqual(node["sources"][0]["type"], "external")
        self.assertTrue(node["sources"][0].get("exchange_stop"))
        # Kein rekursiver Trace in funding
        self.assertNotIn("trace", node["sources"][0])

    def test_trace_stoppt_an_boerse_adresse_als_prevout(self):
        import analyze
        from tests.fixtures import (
            BIP84_RECEIVE_0,
            core_tx,
            core_vin,
            core_vout,
            make_get_tx,
            txid,
        )

        boerse.importiere_csv(
            f"address,asset\n{KRK_ADDR},BTC\n",
            name="Kraken",
            cache_dir=self.dir,
        )
        own = BIP84_RECEIVE_0
        hinter = txid("hh")
        mid = txid("mm")
        win = txid("ww")
        chain = {
            hinter: core_tx(
                hinter,
                [{"coinbase": "00", "sequence": 0}],
                [core_vout(0, "bc1qdeepxxxxxxxxxxxxxxxxxxxxxxxxxxx0", 1.0)],
            ),
            mid: core_tx(
                mid,
                [core_vin(hinter, 0)],
                [core_vout(0, KRK_ADDR, 0.9)],
            ),
            win: core_tx(
                win,
                [core_vin(mid, 0)],
                [core_vout(0, own, 0.8)],
            ),
        }
        node = analyze.trace_utxo_origin(
            make_get_tx(chain),
            win,
            0,
            {own},
        )
        srcs = node.get("sources") or []
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]["type"], "external")
        self.assertEqual(srcs[0].get("address"), KRK_ADDR)
        self.assertTrue(srcs[0].get("exchange_stop"))
        self.assertNotIn("trace", srcs[0])


if __name__ == "__main__":
    unittest.main()
