"""
„davon … an Kraken“ an ausgegebenen Outputs.

Gezählt wird der Output der Ausgabetransaktion, dessen Adresse als Börse
bekannt ist. Wechselgeld, Gebühr und unbekannte Ziele zählen nicht mit.
CoinJoin: keine Adress-Zuordnung. Report-TxID ohne Adresse: Name ohne Betrag.
"""
import unittest
from unittest.mock import patch

from core.exchange_spend import boerse_ziele, ziele_aus_outputs, ziele_aus_tx
from core.utxos import exchange_spends_fuer, historische_eintraege
from tests.fixtures import BIP84_RECEIVE_0, txid


KRAKEN = "bc1qkrakenaddr000000000000000000000000000"
COINBASE = "bc1qcoinbaseaddr0000000000000000000000000"
FREMD = "bc1qunbekannt000000000000000000000000000000"
EIGEN = BIP84_RECEIVE_0


def _name(adresse: str) -> str:
    return {
        KRAKEN: "Kraken",
        COINBASE: "Coinbase",
    }.get(adresse, "")


def _tx(outs: list[tuple[str, int]], *, n_in: int = 1) -> dict:
    return {
        "vin": [{"txid": "aa" * 32, "vout": i} for i in range(n_in)],
        "vout": [
            {"scriptpubkey_address": addr, "value": sats}
            for addr, sats in outs
        ],
    }


class TestZieleAusTx(unittest.TestCase):

    def test_nur_boersenanteil(self):
        tx = _tx([
            (KRAKEN, 15_000_000),
            (EIGEN, 4_000_000),
            (FREMD, 900_000),
        ])
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            ziele = ziele_aus_tx(tx)
        self.assertEqual(ziele, [{"name": "Kraken", "sats": 15_000_000}])

    def test_mehrere_boersen_summiert(self):
        tx = _tx([
            (KRAKEN, 10_000_000),
            (COINBASE, 2_000_000),
            (KRAKEN, 500_000),
        ])
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            ziele = ziele_aus_tx(tx)
        self.assertEqual(ziele, [
            {"name": "Kraken", "sats": 10_500_000},
            {"name": "Coinbase", "sats": 2_000_000},
        ])

    def test_coinjoin_ohne_adress_treffer(self):
        # 5×5 gleiche Beträge — Whirlpool-Form.
        denom = 1_000_000
        tx = _tx([(KRAKEN, denom)] * 5, n_in=5)
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            self.assertEqual(ziele_aus_tx(tx), [])

    def test_txid_ohne_betrag_wenn_adresse_fehlt(self):
        with patch(
            "core.exchange_reports.beschrifte_txid",
            return_value={"name": "Kraken", "kategorie": "exchange"},
        ):
            ziele = boerse_ziele(None, txid="ab" * 32)
        self.assertEqual(ziele, [{"name": "Kraken", "sats": None}])

    def test_adresse_schlaegt_txid(self):
        tx = _tx([(KRAKEN, 3_000_000)])
        with patch("core.exchange_spend._boerse_name", side_effect=_name), \
             patch(
                 "core.exchange_reports.beschrifte_txid",
                 return_value={"name": "Coinbase", "kategorie": "exchange"},
             ):
            ziele = boerse_ziele(tx, txid="ab" * 32)
        self.assertEqual(ziele, [{"name": "Kraken", "sats": 3_000_000}])


class TestGespeicherteOutputs(unittest.TestCase):

    def test_verlaufsfelder(self):
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            ziele = ziele_aus_outputs([
                {"address": KRAKEN, "sats": 15_000_000},
                {"address": EIGEN, "sats": 1_000},
                {"address": FREMD, "sats": 50},
            ])
        self.assertEqual(ziele, [{"name": "Kraken", "sats": 15_000_000}])

    def test_wechselgeld_entfaellt(self):
        eintrag = {
            "spent": True,
            "spent_txid": txid("ff"),
            "spent_outputs": [
                {"address": KRAKEN, "sats": 8_000_000},
                {"address": EIGEN, "sats": 2_000_000},
            ],
        }
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            ziele = exchange_spends_fuer(eintrag, own_addresses={EIGEN})
        self.assertEqual(ziele, [{"name": "Kraken", "sats": 8_000_000}])

    def test_coinjoin_flag_unterdrueckt_adresse(self):
        eintrag = {
            "spent": True,
            "spent_txid": txid("ff"),
            "spent_coinjoin": True,
            "spent_outputs": [{"address": KRAKEN, "sats": 1_000_000}],
        }
        with patch("core.exchange_spend._boerse_name", side_effect=_name), \
             patch("core.exchange_spend.ziele_aus_txid", return_value=[]):
            self.assertEqual(exchange_spends_fuer(eintrag), [])

    def test_historie_traegt_feld(self):
        roh = {
            "txid": txid("a1"), "vout": 0, "address": EIGEN, "value": 10_000_000,
            "status": {"confirmed": True, "block_time": 1_700_000_000},
            "spent": True, "spent_txid": txid("ff"),
            "spent_time_ts": 1_760_000_000,
            "spent_outputs": [{"address": KRAKEN, "sats": 9_000_000}],
        }
        with patch("core.exchange_spend._boerse_name", side_effect=_name):
            aus = historische_eintraege([roh])["utxos"][0]
        self.assertEqual(
            aus["exchange_spends"],
            [{"name": "Kraken", "sats": 9_000_000}],
        )


if __name__ == "__main__":
    unittest.main()
