"""P2P-Walk vergleicht Signaturen, ohne den Soll-Baum zu schreiben."""
from __future__ import annotations

import unittest

from core.p2p_walk_abgleich import gleiche_herkunft_ab, vergleiche_entdeckung


class _Wallet:
    def resolve_address(self, addr):
        return addr


def _tx(txid: str, vout_addr: str, prev: tuple[str, int] | None) -> dict:
    vin = [{"is_coinbase": True}] if prev is None else [
        {"txid": prev[0], "vout": prev[1]},
    ]
    return {
        "txid": txid,
        "vin": vin,
        "vout": [{
            "n": 0,
            "value": 0.01,
            "scriptPubKey": {"address": vout_addr},
        }],
        "status": {"confirmed": True, "block_height": 10, "block_time": 1_700_000_000},
    }


class TestP2pEntdeckung(unittest.TestCase):
    def test_fehlender_outpoint_ist_rot(self):
        soll = {
            "aa" * 32 + ":0": {
                "txid": "aa" * 32, "vout": 0, "amount_sats": 1000,
                "address": "bc1qeigen", "wallet": "Test",
            },
        }
        ergebnis = vergleiche_entdeckung(
            soll, [], addr_wallet={"bc1qeigen": "Test"},
        )
        self.assertFalse(ergebnis["ok"])
        self.assertEqual(ergebnis["fehlend"], 1)

    def test_gleicher_bestand_ist_gruen(self):
        soll = {
            "aa" * 32 + ":1": {
                "txid": "aa" * 32, "vout": 1, "amount_sats": 1000,
                "address": "bc1qeigen", "wallet": "Test",
            },
        }
        ergebnis = vergleiche_entdeckung(
            soll,
            [{"txid": "aa" * 32, "vout": 1, "value": 1000, "address": "bc1qeigen"}],
            addr_wallet={"bc1qeigen": "Test"},
        )
        self.assertTrue(ergebnis["ok"])
        self.assertEqual(ergebnis["extra"], 0)


class TestP2pWalkAbgleich(unittest.TestCase):
    def test_gleicher_baum_ist_gruen(self):
        eigene = {"bc1qeigen"}
        txs = {
            "aa" * 32: _tx("aa" * 32, "bc1qeigen", ("bb" * 32, 0)),
            "bb" * 32: _tx("bb" * 32, "bc1qfremd", None),
        }

        def get_tx(txid):
            return txs[txid]

        from core.utxo_origin import trace_utxo_origin

        soll_baum = trace_utxo_origin(
            get_tx, "aa" * 32, 0, eigene, wallet=_Wallet(),
        )
        ergebnis = gleiche_herkunft_ab(
            [{
                "txid": "aa" * 32,
                "vout": 0,
                "amount_sats": 1_000_000,
                "address": "bc1qeigen",
                "wallet": "Test",
                "herkunft": soll_baum,
            }],
            get_tx,
            eigene=eigene,
            wallet=_Wallet(),
        )
        self.assertTrue(ergebnis["ok"])
        self.assertEqual(ergebnis["verglichen"], 1)
        self.assertEqual(ergebnis["abweichungen"], 0)

    def test_fremder_vorgaenger_ist_rot(self):
        eigene = {"bc1qeigen"}
        soll_tx = {
            "aa" * 32: _tx("aa" * 32, "bc1qeigen", ("bb" * 32, 0)),
            "bb" * 32: _tx("bb" * 32, "bc1qfremd", None),
        }
        ist_tx = {
            "aa" * 32: _tx("aa" * 32, "bc1qeigen", ("cc" * 32, 1)),
            "cc" * 32: _tx("cc" * 32, "bc1qanders", None),
        }

        def get_soll(txid):
            return soll_tx[txid]

        from core.utxo_origin import trace_utxo_origin

        soll_baum = trace_utxo_origin(
            get_soll, "aa" * 32, 0, eigene, wallet=_Wallet(),
        )
        ergebnis = gleiche_herkunft_ab(
            [{
                "txid": "aa" * 32,
                "vout": 0,
                "amount_sats": 1_000_000,
                "address": "bc1qeigen",
                "wallet": "Test",
                "herkunft": soll_baum,
            }],
            lambda txid: ist_tx[txid],
            eigene=eigene,
            wallet=_Wallet(),
        )
        self.assertFalse(ergebnis["ok"])
        self.assertEqual(ergebnis["abweichungen"], 1)


if __name__ == "__main__":
    unittest.main()
