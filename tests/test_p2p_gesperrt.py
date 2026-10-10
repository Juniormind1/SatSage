"""P2P bleibt für Herkunft zu und sucht UTXOs nur ohne verbundene Quellen."""
from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from core.chain_sources import p2p_utxo_entdeckung_frei
from core.fulcrum_client import FulcrumClient
from core.p2p import P2pGesperrt, p2p_gesperrt, p2p_nur_utxo_entdeckung, verbinde_peer
from core.source import describe_sources


class TestP2pGesperrt(unittest.TestCase):
    def test_socket_bleibt_ausserhalb_der_utxo_suche_zu(self):
        self.assertTrue(p2p_gesperrt())
        with patch("socket.create_connection") as conn:
            with self.assertRaises(P2pGesperrt):
                verbinde_peer("127.0.0.1", 18444, timeout=1)
            conn.assert_not_called()

    def test_utxo_suche_darf_socket_auch_im_worker(self):
        gesehen = []

        def arbeit():
            with patch(
                "socket.create_connection", side_effect=OSError("zu"),
            ) as conn:
                with self.assertRaises(OSError):
                    verbinde_peer("127.0.0.1", 18444, timeout=1)
                gesehen.append(conn.called)

        with p2p_nur_utxo_entdeckung():
            worker = threading.Thread(target=arbeit)
            worker.start()
            worker.join()
        self.assertEqual(gesehen, [True])

    def test_datenquellen_zeigen_p2p_fuer_den_bestand(self):
        quelle = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertFalse(quelle.ausgeblendet)
        self.assertTrue(quelle.configured)
        self.assertFalse(quelle.as_dict()["ausgeblendet"])
        self.assertIn("Nur der UTXO-Bestand", quelle.note)


class TestP2pUtxoFrei(unittest.TestCase):
    def test_aus_wenn_schalter_aus(self):
        self.assertFalse(p2p_utxo_entdeckung_frei(
            {"BIP158_P2P": "0"},
            None,
            eigene_electrs=False,
            scantxoutset=False,
        ))

    def test_aus_wenn_electrs_oder_scantxoutset_verbunden(self):
        env = {"BIP158_P2P": "1"}
        self.assertFalse(p2p_utxo_entdeckung_frei(
            env, None, eigene_electrs=True, scantxoutset=False,
        ))
        self.assertFalse(p2p_utxo_entdeckung_frei(
            env, None, eigene_electrs=False, scantxoutset=True,
        ))
        self.assertFalse(p2p_utxo_entdeckung_frei(
            env, None, eigene_electrs=False, scantxoutset=False, core=True,
        ))

    def test_an_wenn_beides_nicht_verbunden(self):
        with patch(
            "core.chain_sources.eigene_electrs_ist_verbunden", return_value=False,
        ) as electrs, patch(
            "core.chain_sources.scantxoutset_ist_verbunden", return_value=False,
        ) as scantx:
            self.assertTrue(p2p_utxo_entdeckung_frei({"BIP158_P2P": "1"}, None))
        electrs.assert_called_once()
        scantx.assert_called_once()

    def test_eigener_client_zaehlt_ohne_probe(self):
        client = MagicMock(spec=FulcrumClient)
        with patch(
            "core.chain_sources.is_own_fulcrum_backend", return_value=True,
        ), patch(
            "core.chain_sources.eigene_electrs_ist_verbunden",
        ) as electrs, patch(
            "core.chain_sources.scantxoutset_ist_verbunden",
        ) as scantx:
            self.assertFalse(p2p_utxo_entdeckung_frei(
                {"BIP158_P2P": "1"},
                client,
                eigene_electrs=False,
                scantxoutset=False,
            ))
        electrs.assert_not_called()
        scantx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
