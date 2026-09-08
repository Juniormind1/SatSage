"""
fetch_address_history_fulcrum / fetch_wallet_history_fulcrum: vollständige
Adress-Historie inkl. ausgegebener Outputs über einen Electrum-Server.

Ein Fake-Client ersetzt die echte Netzwerkverbindung — die Tests laufen ohne
Verbindung und ohne echte Wallet-Daten. Alle Höhen bleiben 0 (unconfirmed),
damit die Blockzeit-Anreicherung (die auf main.IMMUTABLE_CACHE_DIR zugreifen
würde) gar nicht erst anläuft.
"""
import unittest

from fulcrum import (
    _fetch_address_utxos_from_history,
    address_to_scripthash,
    collect_used_chain_indices_fulcrum,
    fetch_address_history_fulcrum,
    fetch_wallet_history_fulcrum,
)
from tests.fixtures import (
    BIP84_RECEIVE_0, BIP84_RECEIVE_1, EXTERN_A, EXTERN_B,
    core_tx, core_vin, core_vout, txid,
)

TXID_EMPFANG_UNSPENT = txid("a1")
TXID_EMPFANG_AUSGEGEBEN = txid("a2")
TXID_AUSGABE = txid("b1")
TXID_FREMDE_VORGAENGER_TX = txid("00")


class FakeFulcrumClient:
    """Minimaler Ersatz für FulcrumClient.request() — keine echte Verbindung."""

    def __init__(self, history_by_scripthash: dict, tx_by_id: dict):
        self._history = history_by_scripthash
        self._txs = tx_by_id

    def request(self, method: str, params: list | None = None):
        params = params or []
        if method == "blockchain.scripthash.get_history":
            return self._history.get(params[0], [])
        if method == "blockchain.transaction.get":
            return self._txs[params[0]]
        raise AssertionError(f"unerwartete Methode in Test: {method}")


class VerlaufTest(unittest.TestCase):
    def setUp(self):
        self.adresse = EXTERN_A
        self.scripthash = address_to_scripthash(self.adresse)

        empfang_unspent = core_tx(
            TXID_EMPFANG_UNSPENT,
            vin=[core_vin(TXID_FREMDE_VORGAENGER_TX, 0)],
            vout=[core_vout(0, self.adresse, 0.001)],
            confirmations=0,
        )
        empfang_ausgegeben = core_tx(
            TXID_EMPFANG_AUSGEGEBEN,
            vin=[core_vin(TXID_FREMDE_VORGAENGER_TX, 1)],
            vout=[core_vout(0, self.adresse, 0.002)],
            confirmations=0,
        )
        ausgabe = core_tx(
            TXID_AUSGABE,
            vin=[core_vin(TXID_EMPFANG_AUSGEGEBEN, 0)],
            vout=[core_vout(0, EXTERN_B, 0.0019)],
            confirmations=0,
        )

        self.client = FakeFulcrumClient(
            history_by_scripthash={
                self.scripthash: [
                    {"tx_hash": TXID_EMPFANG_UNSPENT, "height": 0},
                    {"tx_hash": TXID_EMPFANG_AUSGEGEBEN, "height": 0},
                    {"tx_hash": TXID_AUSGABE, "height": 0},
                ],
            },
            tx_by_id={
                TXID_EMPFANG_UNSPENT: empfang_unspent,
                TXID_EMPFANG_AUSGEGEBEN: empfang_ausgegeben,
                TXID_AUSGABE: ausgabe,
            },
        )

    def test_liefert_beide_empfangenen_outputs(self):
        eintraege = fetch_address_history_fulcrum(
            self.client, self.adresse, self.scripthash
        )
        self.assertEqual(len(eintraege), 2)

    def test_ausgegebener_output_traegt_spent_txid(self):
        eintraege = fetch_address_history_fulcrum(
            self.client, self.adresse, self.scripthash
        )
        by_txid = {e["txid"]: e for e in eintraege}
        ausgegeben = by_txid[TXID_EMPFANG_AUSGEGEBEN.lower()]
        self.assertTrue(ausgegeben["spent"])
        self.assertEqual(ausgegeben["spent_txid"], TXID_AUSGABE.lower())
        self.assertEqual(ausgegeben["value"], 200_000)

    def test_unspent_output_hat_kein_spent_txid(self):
        eintraege = fetch_address_history_fulcrum(
            self.client, self.adresse, self.scripthash
        )
        by_txid = {e["txid"]: e for e in eintraege}
        unspent = by_txid[TXID_EMPFANG_UNSPENT.lower()]
        self.assertFalse(unspent["spent"])
        self.assertIsNone(unspent["spent_txid"])

    def test_unspent_ableitung_filtert_ausgegebene(self):
        """Fallback-Pfad für Server ohne listunspent liefert weiterhin nur
        die unspent Teilmenge, ohne die neuen spent-Felder."""
        utxos = _fetch_address_utxos_from_history(
            self.client, self.adresse, self.scripthash
        )
        self.assertEqual(len(utxos), 1)
        self.assertEqual(utxos[0]["txid"], TXID_EMPFANG_UNSPENT.lower())
        self.assertNotIn("spent", utxos[0])
        self.assertNotIn("spent_txid", utxos[0])

    def test_fetch_wallet_history_markiert_adresse(self):
        eintraege = fetch_wallet_history_fulcrum(self.client, {self.adresse})
        self.assertEqual(len(eintraege), 2)
        self.assertTrue(all(e["address"] == self.adresse for e in eintraege))

    def test_verlauf_meldet_restadressen(self):
        """Status nennt den Rest, nicht nur die Gesamtzahl."""
        from fulcrum import _verlauf_fortschritt

        gesehen = []

        def fortschritt(text, *, sofort=False):
            gesehen.append((text, sofort))

        fetch_wallet_history_fulcrum(
            self.client, {self.adresse}, on_progress=fortschritt
        )
        self.assertTrue(gesehen)
        anfang, sofort = gesehen[0]
        self.assertTrue(sofort)
        self.assertIn("noch 1 von 1 Adressen", anfang)
        self.assertEqual(
            _verlauf_fortschritt(40, 58, 12),
            "Frage Verlauf für 58 Adressen — noch 40 von 58 Adressen"
            " · bisher 12 Einträge",
        )

    def test_leere_historie_liefert_leere_liste(self):
        client = FakeFulcrumClient(history_by_scripthash={}, tx_by_id={})
        self.assertEqual(
            fetch_address_history_fulcrum(client, self.adresse, self.scripthash),
            [],
        )


class TestGapScanNenntUtxos(unittest.TestCase):
    """Die Index-Zeile trägt die UTXO-Zahl, sobald die Adresse geprüft ist."""

    def test_benutzte_adresse_meldet_anzahl_sofort(self):
        from unittest.mock import patch

        adresse = BIP84_RECEIVE_0
        sh = address_to_scripthash(adresse)
        client = FakeFulcrumClient(
            history_by_scripthash={sh: [{"tx_hash": txid("a1"), "height": 1}]},
            tx_by_id={},
        )
        gesehen = []

        def fortschritt(text, *, sofort=False):
            gesehen.append((text, sofort))

        with patch(
            "fulcrum.fetch_address_utxos_fulcrum",
            return_value=[{"txid": "aa"}, {"txid": "bb"}],
        ):
            used, _ = collect_used_chain_indices_fulcrum(
                client, "xpubTEST", 0, 1, 2,
                lambda *_args: adresse,
                on_progress=fortschritt,
                kette="Empfang",
            )
        self.assertEqual(used, {0})
        self.assertTrue(gesehen)
        text, sofort = gesehen[0]
        self.assertIn("Index #0", text)
        self.assertIn("darin 2 UTXOs gefunden", text)
        self.assertIn("bisher 2 UTXOs", text)
        self.assertTrue(sofort)

    def test_leere_adresse_sagt_nicht_null_gefunden(self):
        """Sonst stünde oben ‚0 UTXOs gefunden‘, im Log aber schon ein Treffer."""
        adresse = BIP84_RECEIVE_1
        gesehen = []

        def fortschritt(text, *, sofort=False):
            gesehen.append((text, sofort))

        collect_used_chain_indices_fulcrum(
            FakeFulcrumClient({}, {}),
            "xpubTEST", 0, 1, 2,
            lambda *_args: adresse,
            on_progress=fortschritt,
            kette="Empfang",
        )
        self.assertTrue(gesehen)
        text, sofort = gesehen[0]
        self.assertIn("bisher 0 UTXOs", text)
        self.assertNotIn("darin 0", text)
        self.assertFalse(sofort)


if __name__ == "__main__":
    unittest.main()

