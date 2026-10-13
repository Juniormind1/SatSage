"""Libbitcoin-Abfrage am eigenen Indexer. Lokaler HTTP-Stub, kein Node."""
from __future__ import annotations

import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from embit import script
from embit.ec import PrivateKey
from embit.script import Script
from embit.transaction import Transaction, TransactionInput, TransactionOutput

from core.fulcrum_client import address_to_scripthash
from core.fulcrum_history import fetch_tx_fulcrum
from core.fulcrum_wallet import (
    address_has_received_fulcrum,
    fetch_address_utxos_fulcrum,
    first_seen_height_fulcrum,
)
from core.libbitcoin_native import abfrage_hinweis, skript_aus_nativ
from core.trace import FundingEdge, PrevoutRef, _mit_vorgaengerzeit, resolve_vin_prevout

TX = "11" * 32
ZEIT = 1_700_000_000
HOEHE = 100
WERT = 5000


def _adresse(roh: bytes) -> tuple[str, bytes]:
    pubkey = PrivateKey(roh).get_public_key()
    spk = script.p2wpkh(pubkey)
    return spk.address(), spk.data


def _intern(spk: bytes) -> str:
    return hashlib.sha256(spk).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        pfad = self.path.split("?", 1)[0]
        self.server.pfade.append(pfad)
        treffer = self.server.router(pfad)
        if treffer is None:
            body = b""
            status = 404
            art = "text/plain"
        else:
            status, inhalt, art = treffer
            if isinstance(inhalt, bytes):
                body = inhalt
            else:
                body = json.dumps(inhalt).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


class _Kunde:
    def __init__(self, software: str, host: str, port: int) -> None:
        self.host = host
        self.port = 50001
        self.timeout = 2
        self.tor_proxy = None
        self.server_software = software
        self.use_ssl = False
        self.aufrufe: list[str] = []
        self.history: list = []
        self.unspent: list = []
        self._libbitcoin_werte = {
            "FULCRUM_HOST": "127.0.0.1",
            "LIBBITCOIN_NATIVE_PORT": str(port),
        }

    def request(self, method: str, params=None):
        self.aufrufe.append(method)
        if method == "blockchain.scripthash.get_history":
            return list(self.history)
        if method == "blockchain.scripthash.listunspent":
            return list(self.unspent)
        if method == "blockchain.transaction.get":
            raise AssertionError("Electrum-Transaktion")
        raise AssertionError(method)


def _server(router):
    dienst = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    dienst.router = router
    dienst.pfade = []
    thread = threading.Thread(target=dienst.serve_forever, daemon=True)
    thread.start()
    return dienst


def _kopf() -> dict:
    return {
        "hash": "22" * 32,
        "height": HOEHE,
        "timestamp": ZEIT,
        "version": 1,
        "previous": "00" * 32,
        "merkle_root": "33" * 32,
        "bits": 1,
        "nonce": 0,
    }


class NativeWegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adresse, self.spk = _adresse(b"\x01" * 32)
        self.andere, self.spk_andere = _adresse(b"\x02" * 32)
        self.electrum_hash = address_to_scripthash(self.adresse)
        self.intern_hash = _intern(self.spk)
        self.dienst = None

    def tearDown(self) -> None:
        if self.dienst is not None:
            self.dienst.shutdown()
            self.dienst.server_close()

    def _kunde(self, software: str = "libbitcoin", host: str = "127.0.0.1") -> _Kunde:
        port = self.dienst.server_address[1] if self.dienst is not None else 9
        return _Kunde(software, host, port)

    def test_probe_nur_eigener_libbitcoin(self) -> None:
        self.dienst = _server(lambda pfad: (200, {"address": False}, "application/json"))
        eigener = self._kunde()
        address_has_received_fulcrum(eigener, self.adresse)
        self.assertEqual(self.dienst.pfade, ["/v1/configuration"])
        self.assertIn("blockchain.scripthash.get_history", eigener.aufrufe)

        self.dienst.pfade.clear()
        electrs = self._kunde(software="electrs")
        electrs.history = [{"height": 5}]
        self.assertTrue(address_has_received_fulcrum(electrs, self.adresse))
        self.assertEqual(self.dienst.pfade, [])

        self.dienst.pfade.clear()
        fremd = self._kunde(host="192.0.2.50")
        fremd._libbitcoin_werte["FULCRUM_HOST"] = "127.0.0.1"
        address_has_received_fulcrum(fremd, self.adresse)
        self.assertEqual(self.dienst.pfade, [])
        self.assertFalse(fremd._libbitcoin_native.aktiv)

    def test_abfrage_hinweis_im_log(self) -> None:
        self.dienst = _server(lambda pfad: (200, {"address": True}, "application/json"))
        zeilen: list[str] = []
        kunde = self._kunde()
        text = abfrage_hinweis(kunde, log=zeilen.append)
        port = self.dienst.server_address[1]
        self.assertEqual(
            zeilen,
            [
                f"Prüfe libbitcoin-Abfrage 127.0.0.1:{port}…",
                f"libbitcoin-Abfrage 127.0.0.1:{port}: Adressindex an — "
                "Bestand und Herkunft darüber.",
            ],
        )
        self.assertEqual(text, zeilen[-1])
        self.assertEqual(self.dienst.pfade, ["/v1/configuration"])
        self.dienst.pfade.clear()
        self.assertEqual(abfrage_hinweis(kunde), text)
        self.assertEqual(self.dienst.pfade, [])

        ohne = self._kunde(software="electrs")
        self.assertIsNone(abfrage_hinweis(ohne, log=zeilen.append))
        self.assertEqual(len(zeilen), 2)

        leer = self._kunde()
        leer._libbitcoin_werte = {"FULCRUM_HOST": "127.0.0.1", "LIBBITCOIN_NATIVE_PORT": "1"}
        leer.timeout = 0.2
        self.assertIn(
            "nicht erreichbar",
            abfrage_hinweis(leer) or "",
        )

        ohne_index = self._kunde()
        self.dienst.router = lambda pfad: (200, {"address": False}, "application/json")
        self.assertIn("kein Adressindex", abfrage_hinweis(ohne_index) or "")

        fremd = self._kunde(host="192.0.2.50")
        fremd._libbitcoin_werte["FULCRUM_HOST"] = "127.0.0.1"
        self.assertIsNone(abfrage_hinweis(fremd, log=zeilen.append))
        self.assertEqual(len(zeilen), 2)

    def test_weiterleitung_wird_nicht_verfolgt(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 302, b"", "text/plain"
            return 200, {"address": True}, "application/json"

        self.dienst = _server(router)
        # Location würde der Stub nicht sehen: der Client bricht bei 3xx ab.
        kunde = self._kunde()
        kunde.history = [{"height": 5}]
        self.assertTrue(address_has_received_fulcrum(kunde, self.adresse))
        self.assertEqual(self.dienst.pfade, ["/v1/configuration"])
        self.assertFalse(kunde._libbitcoin_native.aktiv)

    def test_luecke_404_erst_nach_hash_treffer(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/address/{self.electrum_hash}/confirmed":
                return 200, [{
                    "point": {"hash": TX, "index": 0},
                    "value": WERT,
                }], "application/json"
            if pfad == f"/v1/address/{self.intern_hash}/confirmed":
                return 200, [{
                    "point": {"hash": "aa" * 32, "index": 0},
                    "value": 1,
                }], "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            if pfad.endswith("/unconfirmed"):
                return 501, {"message": "mempool"}, "application/json"
            if pfad == f"/v1/address/{self.electrum_hash}":
                return 200, {"ignoriert": True}, "application/json"
            if pfad == f"/v1/address/{address_to_scripthash(self.andere)}":
                return None
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        kunde.history = [{"tx_hash": TX, "height": HOEHE}]
        kunde.unspent = [{
            "tx_hash": TX,
            "tx_pos": 0,
            "value": WERT,
            "height": HOEHE,
        }]
        self.dienst.pfade.clear()
        self.assertTrue(address_has_received_fulcrum(kunde, self.adresse))
        self.assertNotIn(f"/v1/address/{self.electrum_hash}", self.dienst.pfade)
        self.assertIn("blockchain.scripthash.get_history", kunde.aufrufe)

        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            erster = fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertEqual(erster[0]["txid"], TX)
        self.assertTrue(kunde._libbitcoin_native.hash_bestaetigt)
        self.assertFalse(kunde._libbitcoin_native.hash_intern)

        kunde.aufrufe.clear()
        self.dienst.pfade.clear()
        zweiter = fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertNotIn("blockchain.scripthash.listunspent", kunde.aufrufe)
        self.assertEqual(zweiter, [{
            "txid": TX,
            "vout": 0,
            "value": WERT,
            "status": {
                "confirmed": True,
                "block_height": HOEHE,
                "block_time": ZEIT,
            },
        }])
        self.assertFalse(address_has_received_fulcrum(kunde, self.andere))
        self.assertNotIn("blockchain.scripthash.get_history", kunde.aufrufe)
        self.assertTrue(address_has_received_fulcrum(kunde, self.adresse))

    def test_hash_drehung_wenn_nur_die_interne_form_trifft(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/address/{self.intern_hash}/confirmed":
                return 200, [{
                    "point": {"hash": TX, "index": 1},
                    "value": WERT,
                }], "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            if pfad.endswith("/unconfirmed"):
                return None
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        kunde.unspent = [{
            "tx_hash": TX,
            "tx_pos": 1,
            "value": WERT,
            "height": HOEHE,
        }]
        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertTrue(kunde._libbitcoin_native.hash_bestaetigt)
        self.assertTrue(kunde._libbitcoin_native.hash_intern)
        kunde.aufrufe.clear()
        bestand = fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertEqual(bestand[0]["vout"], 1)
        self.assertNotIn("blockchain.scripthash.listunspent", kunde.aufrufe)

    def test_unpassender_hash_schaltet_nativ_aus(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad.endswith("/confirmed"):
                return 200, [{
                    "point": {"hash": "ab" * 32, "index": 0},
                    "value": 1,
                }], "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        kunde.unspent = [{
            "tx_hash": TX,
            "tx_pos": 0,
            "value": WERT,
            "height": HOEHE,
        }]
        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertFalse(kunde._libbitcoin_native.aktiv)
        self.assertEqual(kunde._libbitcoin_native.grund, "hash")

    def test_native_fehler_faellt_auf_listunspent_zurueck(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad.endswith("/confirmed"):
                return 500, {"message": "kaputt"}, "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        kunde.unspent = [{
            "tx_hash": TX,
            "tx_pos": 0,
            "value": WERT,
            "height": HOEHE,
        }]
        # Hash gilt als geprüft, die Bestandsabfrage selbst scheitert.
        from core.libbitcoin_native import sitzung_fuer

        sitzung = sitzung_fuer(kunde)
        sitzung.hash_bestaetigt = True
        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            bestand = fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertEqual(bestand[0]["value"], WERT)
        self.assertIn("blockchain.scripthash.listunspent", kunde.aufrufe)
        self.assertTrue(sitzung.aktiv)

    def test_wert_ohne_outpoint_kommt_vom_output(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad.endswith("/confirmed"):
                return 200, [{"point": {"hash": TX, "index": 0}}], "application/json"
            if pfad == f"/v1/output/{TX}/0":
                return 200, {"value": WERT, "script": "0 [00]"}, "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            if pfad.endswith("/unconfirmed"):
                return None
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        from core.libbitcoin_native import sitzung_fuer

        sitzung = sitzung_fuer(kunde)
        sitzung.hash_bestaetigt = True
        bestand = fetch_address_utxos_fulcrum(kunde, self.adresse)
        self.assertEqual(bestand[0]["value"], WERT)
        self.assertIn(f"/v1/output/{TX}/0", self.dienst.pfade)
        self.assertNotIn("blockchain.scripthash.listunspent", kunde.aufrufe)

    def test_first_seen_bleibt_historie(self) -> None:
        self.dienst = _server(
            lambda pfad: (200, {"address": True}, "application/json"),
        )
        kunde = self._kunde()
        from core.libbitcoin_native import sitzung_fuer

        sitzung = sitzung_fuer(kunde)
        sitzung.hash_bestaetigt = True
        kunde.history = [{"height": 123}]
        self.assertEqual(
            first_seen_height_fulcrum(kunde, [self.adresse]),
            123,
        )
        self.assertIn("blockchain.scripthash.get_history", kunde.aufrufe)

    def test_transaktion_aus_rohbytes_und_header(self) -> None:
        prev = bytes.fromhex("0123456789abcdef" * 4)
        tx = Transaction(
            vin=[TransactionInput(prev, 3)],
            vout=[TransactionOutput(1000, Script(b"\x51"))],
        )
        roh = tx.serialize()
        txid = tx.txid().hex()

        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/tx/{txid}":
                return 200, roh, "application/octet-stream"
            if pfad == f"/v1/tx/{txid}/header":
                return 200, _kopf(), "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        geladen = fetch_tx_fulcrum(kunde, txid)
        self.assertEqual(geladen["vin"][0]["txid"], prev.hex())
        self.assertEqual(geladen["status"]["block_time"], ZEIT)
        self.assertEqual(geladen["status"]["block_height"], HOEHE)
        self.assertNotIn("blockchain.transaction.get", kunde.aufrufe)

    def test_duennes_prevout_ohne_vorgaenger_tx(self) -> None:
        programm = self.spk[2:]
        mnemonik = "0 [" + programm.hex() + "]"
        self.assertEqual(skript_aus_nativ(mnemonik), self.spk)

        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/output/{TX}/0":
                return 200, {"value": WERT, "script": mnemonik}, "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        from core.libbitcoin_native import haenge_prevout_duenn_an

        def get_tx(_txid: str) -> dict:
            raise AssertionError("volle Vorgänger-Transaktion")

        haenge_prevout_duenn_an(get_tx, kunde)
        prevout = resolve_vin_prevout(get_tx, {"txid": TX, "vout": 0})
        self.assertIsNotNone(prevout)
        self.assertEqual(prevout["value"], WERT)
        self.assertEqual(prevout["_prev_tx_time_ts"], ZEIT)
        self.assertEqual(prevout["scriptpubkey_address"], self.adresse)

    def test_unlesbares_skript_laedt_die_vorgaenger_tx(self) -> None:
        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/output/{TX}/0":
                return 200, {"value": WERT, "script": "keinemnemonik"}, "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        from core.libbitcoin_native import haenge_prevout_duenn_an

        gesehen: list[str] = []

        def get_tx(txid: str) -> dict:
            gesehen.append(txid)
            return {
                "txid": txid,
                "vout": [{
                    "value": WERT / 1e8,
                    "scriptPubKey": {"address": self.adresse},
                }],
                "status": {"block_time": ZEIT, "block_height": HOEHE},
            }

        haenge_prevout_duenn_an(get_tx, kunde)
        prevout = resolve_vin_prevout(get_tx, {"txid": TX, "vout": 0})
        self.assertEqual(gesehen, [TX])
        self.assertEqual(prevout["scriptPubKey"]["address"], self.adresse)

    def test_blockzeit_ohne_volle_vorgaenger_tx(self) -> None:
        programm = self.spk[2:]

        def router(pfad):
            if pfad == "/v1/configuration":
                return 200, {"address": True}, "application/json"
            if pfad == f"/v1/output/{TX}/0":
                return 200, {
                    "value": WERT,
                    "script": "0 [" + programm.hex() + "]",
                }, "application/json"
            if pfad == f"/v1/tx/{TX}/header":
                return 200, _kopf(), "application/json"
            return None

        self.dienst = _server(router)
        kunde = self._kunde()
        from core.libbitcoin_native import haenge_prevout_duenn_an

        def get_tx(_txid: str) -> dict:
            raise AssertionError("volle Vorgänger-Transaktion")

        haenge_prevout_duenn_an(get_tx, kunde)
        kante = FundingEdge(
            spending_txid="22" * 32,
            prevout=PrevoutRef(txid=TX, vout=0),
            addresses=(self.adresse,),
            amount_sats=WERT,
            prev_time_ts=None,
        )
        ergaenzt = _mit_vorgaengerzeit(get_tx, kante)
        self.assertEqual(ergaenzt.prev_time_ts, ZEIT)


if __name__ == "__main__":
    unittest.main()
