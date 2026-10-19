"""Eigenes Esplora neben Electrs. Lokaler HTTP-Stub, kein Node."""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from core.esplora_lokal import sitzung_fuer, zuruecksetzen
from core.fulcrum_wallet import (
    address_has_received_fulcrum,
    fetch_address_utxos_fulcrum,
)
from core.source import describe_sources
from core.trace import iter_trace_funding_inputs

TX = "11" * 32
VORG = "22" * 32
ZEIT = 1_700_000_000
HOEHE = 100
WERT = 5000
ADRESSE = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
FREMD = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def _utxo(*, mit_zeit: bool = True) -> dict:
    status: dict = {"confirmed": True, "block_height": HOEHE}
    if mit_zeit:
        status["block_time"] = ZEIT
    return {"txid": TX, "vout": 0, "value": WERT, "status": status}


def _tx(*, prevout: bool) -> dict:
    vin: dict = {"txid": VORG, "vout": 1, "is_coinbase": False}
    if prevout:
        vin["prevout"] = {"scriptpubkey_address": FREMD, "value": WERT}
    return {
        "txid": TX,
        "vin": [vin],
        "vout": [{"scriptpubkey_address": ADRESSE, "value": WERT}],
        "status": {
            "confirmed": True,
            "block_height": HOEHE,
            "block_time": ZEIT,
        },
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        pfad = self.path.split("?", 1)[0]
        self.server.pfade.append(pfad)
        treffer = self.server.router(pfad)
        if treffer is None:
            status, inhalt, art = 404, b"", "text/plain"
        else:
            status, inhalt, art = treffer
        if not isinstance(inhalt, bytes):
            inhalt = json.dumps(inhalt).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        self.wfile.write(inhalt)

    def log_message(self, fmt: str, *args) -> None:
        return


class _Stub:
    def __init__(self, router) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.router = router
        self._server.pfade = []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.port = self._server.server_address[1]

    @property
    def pfade(self) -> list[str]:
        return self._server.pfade

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class _Electrum:
    def __init__(self, software: str = "electrs") -> None:
        self.server_software = software
        self.host = "192.0.2.50"
        self.aufrufe: list[str] = []
        self.history = [{"tx_hash": TX, "height": HOEHE}]
        self.unspent = [{
            "tx_hash": TX,
            "tx_pos": 0,
            "value": WERT,
            "height": HOEHE,
        }]
        self._esplora_werte: dict[str, str] = {}
        self._libbitcoin_werte = {
            "FULCRUM_HOST": "192.0.2.9",
            "FULCRUM_TOR": "",
            "LIBBITCOIN_NATIVE_PORT": "9",
        }

    def request(self, methode: str, _params):
        self.aufrufe.append(methode)
        if methode.endswith("get_history"):
            return self.history
        if "listunspent" in methode:
            return self.unspent
        raise RuntimeError(methode)


class EsploraLokalTest(unittest.TestCase):
    def setUp(self) -> None:
        zuruecksetzen()
        self.stubs: list[_Stub] = []

    def tearDown(self) -> None:
        for stub in self.stubs:
            stub.close()
        zuruecksetzen()

    def _stub(self, router) -> _Stub:
        stub = _Stub(router)
        self.stubs.append(stub)
        return stub

    def _kunde(self, url: str, software: str = "electrs") -> _Electrum:
        kunde = _Electrum(software)
        kunde._esplora_werte = {"MEMPOOL_URL": url}
        return kunde

    def test_libbitcoin_fragt_esplora_nicht(self) -> None:
        stub = self._stub(lambda _pfad: (200, "1", "text/plain"))
        kunde = self._kunde(stub.url(), "libbitcoin")
        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            fetch_address_utxos_fulcrum(kunde, ADRESSE)
        self.assertEqual(stub.pfade, [])
        self.assertTrue(any("listunspent" in name for name in kunde.aufrufe))

    def test_oeffentlich_und_onion_bleiben_aus(self) -> None:
        for url in ("https://mempool.space", "http://beispiel.onion"):
            zuruecksetzen()
            kunde = self._kunde(url)
            sitzung = sitzung_fuer(kunde)
            self.assertFalse(sitzung.aktiv)
            self.assertEqual(sitzung.anfragen, 0)

    def test_bestand_traegt_blockzeit_luecke_bleibt_electrum(self) -> None:
        def router(pfad: str):
            if pfad.endswith("/blocks/tip/height"):
                return 200, "100", "text/plain"
            if pfad.endswith(f"/address/{ADRESSE}/utxo"):
                return 200, [_utxo()], "application/json"
            return None

        stub = self._stub(router)
        kunde = self._kunde(stub.url())
        bestand = fetch_address_utxos_fulcrum(kunde, ADRESSE)
        self.assertEqual(bestand, [_utxo()])
        self.assertFalse(any("listunspent" in name for name in kunde.aufrufe))
        self.assertTrue(address_has_received_fulcrum(kunde, ADRESSE))
        self.assertTrue(any(name.endswith("get_history") for name in kunde.aufrufe))
        self.assertFalse(any("/utxo" in pfad and pfad.count("/utxo") > 1 for pfad in stub.pfade))

    def test_ohne_blockzeit_faellt_bestand_zurueck(self) -> None:
        def router(pfad: str):
            if pfad.endswith("/blocks/tip/height"):
                return 200, "100", "text/plain"
            if pfad.endswith("/utxo"):
                return 200, [_utxo(mit_zeit=False)], "application/json"
            return None

        stub = self._stub(router)
        kunde = self._kunde(stub.url())
        with mock.patch(
            "core.fulcrum_history._block_time_for_height",
            return_value=ZEIT,
        ):
            erster = fetch_address_utxos_fulcrum(kunde, ADRESSE)
            zweiter = fetch_address_utxos_fulcrum(kunde, ADRESSE)
        self.assertEqual(erster[0]["txid"], TX)
        self.assertEqual(zweiter[0]["txid"], TX)
        self.assertEqual(sum(1 for pfad in stub.pfade if pfad.endswith("/utxo")), 1)
        self.assertGreaterEqual(
            sum(1 for name in kunde.aufrufe if "listunspent" in name),
            2,
        )

    def test_herkunft_holt_nur_die_vorgaengerzeit(self) -> None:
        def router(pfad: str):
            if pfad.endswith("/blocks/tip/height"):
                return 200, "100", "text/plain"
            if pfad.endswith(f"/tx/{TX}"):
                return 200, _tx(prevout=True), "application/json"
            if pfad.endswith(f"/tx/{VORG}/status"):
                return 200, {
                    "confirmed": True,
                    "block_height": 90,
                    "block_time": ZEIT - 100,
                }, "application/json"
            return None

        stub = self._stub(router)
        kunde = self._kunde(stub.url())
        geladen: list[str] = []
        vorgeladen: list[str] = []

        def get_tx(txid: str) -> dict:
            geladen.append(txid)
            from core.esplora_lokal import hole_tx

            lokal = hole_tx(kunde, txid)
            if lokal is not None:
                return lokal
            raise AssertionError("volle Vorgänger-Tx")

        from core.esplora_lokal import haenge_vorgaengerzeit_an

        haenge_vorgaengerzeit_an(get_tx, kunde)
        get_tx.prefetch = lambda txids: vorgeladen.extend(txids)

        kanten = list(iter_trace_funding_inputs(
            get_tx, TX, {ADRESSE},
        ))
        self.assertEqual(geladen, [TX])
        self.assertEqual(vorgeladen, [])
        self.assertEqual(kanten[0].prev_time_ts, ZEIT - 100)
        self.assertTrue(any(pfad.endswith("/status") for pfad in stub.pfade))
        self.assertFalse(any(pfad.endswith(f"/tx/{VORG}") for pfad in stub.pfade))

    def test_ohne_prevout_ist_herkunft_aus(self) -> None:
        def router(pfad: str):
            if pfad.endswith("/blocks/tip/height"):
                return 200, "100", "text/plain"
            if pfad.endswith(f"/tx/{TX}"):
                return 200, _tx(prevout=False), "application/json"
            return None

        stub = self._stub(router)
        kunde = self._kunde(stub.url())
        from core.esplora_lokal import hole_tx

        self.assertIsNone(hole_tx(kunde, TX))
        self.assertFalse(sitzung_fuer(kunde).herkunft_an)
        self.assertIsNone(hole_tx(kunde, TX))
        self.assertEqual(sum(1 for pfad in stub.pfade if "/tx/" in pfad), 1)

    def test_zu_gross_bleibt_herkunft_an(self) -> None:
        def router(pfad: str):
            if pfad.endswith("/blocks/tip/height"):
                return 200, "100", "text/plain"
            if pfad.endswith(f"/tx/{TX}"):
                return 200, b"x" * (256 * 1024 + 1), "application/json"
            if pfad.endswith(f"/tx/{VORG}"):
                return 200, _tx(prevout=True), "application/json"
            return None

        stub = self._stub(router)
        kunde = self._kunde(stub.url())
        from core.esplora_lokal import hole_tx

        self.assertIsNone(hole_tx(kunde, TX))
        sitzung = sitzung_fuer(kunde)
        self.assertTrue(sitzung.herkunft_an)
        self.assertIsNotNone(hole_tx(kunde, VORG))

    def test_esplora_ist_keine_quelle(self) -> None:
        keys = {q.key for q in describe_sources({})}
        self.assertNotIn("esplora", keys)


if __name__ == "__main__":
    unittest.main()
