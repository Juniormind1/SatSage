"""Selbstanzeige-Report: FiFo und Auswahl."""
from __future__ import annotations

import unittest
from datetime import datetime

from core import selbstanzeige as sa
from core import tax


def _recv(txid, vout, sats, ts, address="bc1qrecv", wallet_addr=None):
    return {
        "txid": txid,
        "vout": vout,
        "value": sats,
        "address": wallet_addr or address,
        "status": {"confirmed": True, "block_time": ts, "block_height": 800000},
        "spent": False,
    }


def _spent(txid, vout, sats, recv_ts, spent_txid, spent_ts, address="bc1qrecv"):
    u = _recv(txid, vout, sats, recv_ts, address=address)
    u["spent"] = True
    u["spent_txid"] = spent_txid
    u["spent_time_ts"] = spent_ts
    return u


class FakeWallet:
    def resolve_address(self, address):
        if address.startswith("bc1qa"):
            return "Wallet A"
        if address.startswith("bc1qb"):
            return "Wallet B"
        return "Wallet A"


class TestFifo(unittest.TestCase):
    def test_aeltestes_los_zuerst(self):
        # Zwei Empfänge, dann ein Abgang über beide
        t0 = int(datetime(2023, 1, 1).timestamp())
        t1 = int(datetime(2024, 6, 1).timestamp())
        t2 = int(datetime(2025, 3, 1).timestamp())
        spend = "ab" * 32
        utxos = [
            _spent("11" * 32, 0, 100_000, t0, spend, t2, "bc1qaold"),
            _spent("22" * 32, 0, 50_000, t1, spend, t2, "bc1qanew"),
            # Change zurück, damit Netto = Einsatz - Change
            _recv(spend, 0, 10_000, t2, "bc1qachange"),
        ]
        # Netto = 150000 - 10000 = 140000
        report = sa.auswerten(
            utxos, 2025, [spend], haltefrist_jahre=1, wallet=FakeWallet(),
        )
        self.assertEqual(len(report["vorgaenge"]), 1)
        vg = report["vorgaenge"][0]
        self.assertEqual(vg["netto_sats"], 140_000)
        self.assertTrue(vg["lose"])
        # FiFo: zuerst das ältere Los
        self.assertEqual(vg["lose"][0]["anschaffung_datum"], "01.01.2023")
        self.assertEqual(vg["lose"][0]["sats"], 100_000)
        self.assertEqual(vg["lose"][1]["anschaffung_datum"], "01.06.2024")
        self.assertEqual(vg["lose"][1]["sats"], 40_000)
        # Summenzeile = jüngstes verbrauchtes Los
        self.assertEqual(vg["summe_juengstes_anschaffung_datum"], "01.06.2024")

    def test_kandidat_txid_waehlt_aus(self):
        t0 = int(datetime(2024, 1, 1).timestamp())
        t1 = int(datetime(2024, 6, 1).timestamp())
        spend = "cd" * 32
        utxos = [
            _spent("33" * 32, 0, 80_000, t0, spend, t1, "bc1qa1"),
        ]
        k = sa.kandidaten(utxos, 2024, wallet=FakeWallet(), txid=spend)
        self.assertEqual(len(k["kandidaten"]), 1)
        self.assertTrue(k["kandidaten"][0]["ausgewaehlt"])
        self.assertEqual(len(k["kandidaten"][0]["inputs"]), 1)

    def test_ohne_vorauswahl(self):
        t0 = int(datetime(2024, 1, 1).timestamp())
        t1 = int(datetime(2024, 6, 1).timestamp())
        spend = "ef" * 32
        utxos = [_spent("44" * 32, 0, 80_000, t0, spend, t1, "bc1qa1")]
        k = sa.kandidaten(utxos, 2024, wallet=FakeWallet())
        self.assertFalse(k["kandidaten"][0]["ausgewaehlt"])

    def test_kandidaten_ohne_abfluss_bieten_offene_utxos(self):
        t0 = int(datetime(2023, 5, 1).timestamp())
        offen = "66" * 32
        utxos = [_recv(offen, 1, 25_000, t0, "bc1qaopen")]
        k = sa.kandidaten(utxos, 2025, wallet=FakeWallet())
        self.assertEqual(k["abfluesse"], [])
        self.assertEqual(len(k["utxos"]), 1)
        self.assertTrue(k["utxos"][0]["hypothese"])
        self.assertEqual(k["utxos"][0]["txid"], offen)
        self.assertIn("stichtag_hypothese", k)

    def test_hypothese_auswerten_zum_jahresende(self):
        t0 = int(datetime(2023, 1, 1).timestamp())
        offen = "77" * 32
        utxos = [_recv(offen, 0, 12_000, t0, "bc1qaopen")]
        report = sa.auswerten(
            utxos, 2024, [], haltefrist_jahre=1, wallet=FakeWallet(),
            utxo_keys=[f"{offen}:0"],
        )
        self.assertEqual(len(report["vorgaenge"]), 1)
        vg = report["vorgaenge"][0]
        self.assertTrue(vg["hypothese"])
        self.assertEqual(vg["abgang_datum"], "31.12.2024")
        self.assertEqual(vg["netto_sats"], 12_000)
        self.assertEqual(vg["lose"][0]["anschaffung_datum"], "01.01.2023")
        self.assertTrue(vg["summe_alle_lose_frist_erfuellt"])
        html = sa.als_html(report).decode("utf-8")
        self.assertIn("Hypothese", html)
        self.assertIn(offen, html)

    def test_html_enthaelt_person_und_volle_txid(self):
        t0 = int(datetime(2023, 1, 1).timestamp())
        t1 = int(datetime(2025, 1, 2).timestamp())
        spend = "aa" * 32
        utxos = [_spent("55" * 32, 0, 10_000, t0, spend, t1, "bc1qa1")]
        report = sa.auswerten(
            utxos, 2025, [spend], haltefrist_jahre=1, wallet=FakeWallet(),
        )
        html = sa.als_html(report).decode("utf-8")
        self.assertIn("Donald Duck", html)
        self.assertIn("0/8/15", html)
        self.assertIn("Entenhausen", html)
        self.assertIn(spend, html)
        self.assertIn("bc1qa1", html)
        self.assertIn("Summenzeile", html)
        self.assertIn(tax.HINWEIS_ONCHAIN, html)
        csv_text = sa.als_csv(report).decode("utf-8")
        self.assertIn("Donald Duck", csv_text)
        self.assertIn(spend, csv_text)
        self.assertIn("Börsenhistorien", csv_text)


if __name__ == "__main__":
    unittest.main()
