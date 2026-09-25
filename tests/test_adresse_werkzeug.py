"""Ist die Adresse meine? Ableitung, nicht Bestand."""
import unittest
from pathlib import Path

from embit.networks import NETWORKS

import main
from core.adresse_werkzeug import bereinige_bitcoin_adresse, pruefe_eigene_adresse
from httpserver.api.tools import api_tools_adresse
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    BIP84_ZPUB,
    ZWEITER_ZPUB,
)
from tests.test_api import ApiTestBasis


class _State:
    def __init__(self, wallet):
        self.wallet_ctx = wallet


class TestAdresseWerkzeug(unittest.TestCase):

    def setUp(self):
        main.set_chain_network("main")
        self.ctx = main.build_wallet_context(
            [BIP84_ZPUB],
            wallet_names=["Cold Storage"],
            max_addresses_per_xpub=[6],
            script_types=["segwit"],
        )

    def test_empfang_ohne_bestand(self):
        """Adresse aus dem Fenster, ohne dass je ein UTXO dazu liegt."""
        ergebnis = pruefe_eigene_adresse(self.ctx, BIP84_RECEIVE_0)
        self.assertEqual(ergebnis["status"], "meine")
        self.assertEqual(ergebnis["wallet"], "Cold Storage")

    def test_change_unbenutzt(self):
        ergebnis = pruefe_eigene_adresse(self.ctx, BIP84_CHANGE_0)
        self.assertEqual(ergebnis["status"], "meine")
        self.assertEqual(ergebnis["wallet"], "Cold Storage")

    def test_index_jenseits_der_konfigurierten_tiefe(self):
        """max 6 leitet nur 0..2 je Kette vorab ab. Index 40 ist unbenutzt und außerhalb."""
        adresse = main.derive_address_at_index(BIP84_ZPUB, 0, 40)
        self.assertIsNotNone(adresse)
        self.assertNotIn(adresse, self.ctx.address_to_wallet)
        ergebnis = pruefe_eigene_adresse(self.ctx, adresse)
        self.assertEqual(ergebnis["status"], "meine")
        self.assertEqual(ergebnis["wallet"], "Cold Storage")

    def test_fremd(self):
        fremd = main.derive_address_at_index(ZWEITER_ZPUB, 0, 0)
        ergebnis = pruefe_eigene_adresse(self.ctx, fremd)
        self.assertEqual(ergebnis["status"], "fremd")
        self.assertNotIn("wallet", ergebnis)

    def test_grossschreibung_und_uri(self):
        gross = pruefe_eigene_adresse(self.ctx, BIP84_RECEIVE_0.upper())
        self.assertEqual(gross["status"], "meine")
        uri = pruefe_eigene_adresse(
            self.ctx, "bitcoin:" + BIP84_RECEIVE_0 + "?amount=0.01"
        )
        self.assertEqual(uri["status"], "meine")
        self.assertEqual(uri["address"], BIP84_RECEIVE_0)

    def test_ungueltig_und_leer(self):
        self.assertIsNone(bereinige_bitcoin_adresse("keine-adresse"))
        self.assertEqual(pruefe_eigene_adresse(self.ctx, "  ")["status"], "ungueltig")
        self.assertEqual(
            pruefe_eigene_adresse(self.ctx, "hello")["status"], "ungueltig"
        )

    def test_keine_wallets(self):
        ergebnis = pruefe_eigene_adresse(None, BIP84_RECEIVE_0)
        self.assertEqual(ergebnis["status"], "keine_wallets")

    def test_deskriptor_unbenutzt(self):
        xpub = main._hdkey_for_xpub(BIP84_ZPUB).to_base58(
            version=NETWORKS["main"]["xpub"]
        )
        ctx = main.build_wallet_context(
            [f"wpkh({xpub}/<0;1>/*)"],
            wallet_names=["Deskriptor"],
            max_addresses_per_xpub=[10],
        )
        ergebnis = pruefe_eigene_adresse(ctx, BIP84_CHANGE_0)
        self.assertEqual(ergebnis["status"], "meine")
        self.assertEqual(ergebnis["wallet"], "Deskriptor")

    def test_api_liefert_denselben_status(self):
        koerper = api_tools_adresse(_State(self.ctx), {"address": BIP84_RECEIVE_0})
        self.assertEqual(koerper["wallet"], "Cold Storage")
        leer = api_tools_adresse(_State(self.ctx), {})
        self.assertEqual(leer["status"], "ungueltig")

    def test_oberflaeche_enthaelt_den_eintrag(self):
        wurzel = Path(__file__).resolve().parent.parent
        html = (wurzel / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-ansicht="tools"', html)
        self.assertIn('id="ansicht-tools"', html)
        self.assertIn('id="tools-meine"', html)
        self.assertIn("ist die meine?", html)
        self.assertLess(
            html.index('data-ansicht="sanktionen"'),
            html.index('data-ansicht="tools"'),
        )
        self.assertLess(
            html.index('data-ansicht="tools"'),
            html.index("nav.sectionAdmin"),
        )


class TestToolsApi(ApiTestBasis):

    def test_post_eigene_und_ungueltige_adresse(self):
        status, koerper = self.anfrage(
            "/api/tools/adresse",
            methode="POST",
            daten={"address": BIP84_RECEIVE_0},
        )
        self.assertEqual(status, 200)
        self.assertEqual(koerper["status"], "meine")
        self.assertEqual(koerper["wallet"], "Cold Storage")
        self.assertEqual(koerper["address"], BIP84_RECEIVE_0)

        status, koerper = self.anfrage(
            "/api/tools/adresse",
            methode="POST",
            daten={"address": "keine-adresse"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(koerper["status"], "ungueltig")

    def test_schatzsuche_ohne_core_wird_abgelehnt(self):
        status, koerper = self.anfrage(
            "/api/tools/schatzsuche",
            methode="POST",
            daten={},
        )
        self.assertEqual(status, 409)
        self.assertIn("scantxoutset", koerper.get("error") or koerper.get("message") or str(koerper))
