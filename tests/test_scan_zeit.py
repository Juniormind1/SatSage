"""Datum ↔ Blockhöhe: Header, Explorer, Schätzung. Keine echten Explorer-Abrufe."""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.p2p import GENESIS_HEADER, HEADER_FILE_MAGIC, HeaderChain, header_hash
from core.scan_zeit import (
    explorer_datum_aus_hoehe,
    explorer_hoehe_aus_datum,
    rechne_scan_zeit,
    schaetze_datum_aus_hoehe,
    schaetze_hoehe_aus_datum,
)



def _header(prev: bytes, zeit: int) -> bytes:
    kopf = GENESIS_HEADER[:4] + prev + GENESIS_HEADER[36:68]
    return kopf + struct.pack("<I", zeit) + GENESIS_HEADER[72:]


class _Antwort:
    def __init__(self, body: bytes | str, status: int = 200):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSchaetzung(unittest.TestCase):
    def test_genesis_ist_hoehe_null(self):
        self.assertEqual(schaetze_hoehe_aus_datum("2009-01-03"), 0)

    def test_hoehe_null_ist_genesis_tag(self):
        self.assertEqual(schaetze_datum_aus_hoehe(0), "2009-01-03")

    def test_datum_rundreise_ueber_schaetzung(self):
        hoehe = schaetze_hoehe_aus_datum("2017-08-24")
        self.assertGreater(hoehe, 0)
        self.assertEqual(schaetze_hoehe_aus_datum("24.08.2017"), hoehe)


class TestLokaleHeader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        kette = HeaderChain()
        kette._anchor_height = 700_000
        kette._anchor_hash = header_hash(GENESIS_HEADER)
        self.h1 = _header(kette._anchor_hash, 1_638_000_000)
        self.h2 = _header(header_hash(self.h1), 1_638_000_600)
        kette._data = bytearray(self.h1 + self.h2)
        pfad = self.root / "p2p_headers.bin"
        pfad.write_bytes(
            HEADER_FILE_MAGIC
            + struct.pack("<I", kette._anchor_height)
            + kette._anchor_hash
            + bytes(kette._data)
        )
        from unittest.mock import patch

        self._p = patch(
            "core.xpub_cache._p2p_header_chain",
            lambda *_a, **_k: HeaderChain(pfad),
        )
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_hoehe_fuellt_datum_aus_header(self):
        ergebnis = rechne_scan_zeit(hoehe=700_001, cache_root=self.root)
        self.assertEqual(ergebnis["source"], "headers")
        self.assertEqual(ergebnis["height"], 700_001)
        self.assertEqual(ergebnis["date"], "2021-11-27")

    def test_datum_fuellt_hoehe_aus_header(self):
        ergebnis = rechne_scan_zeit(datum="2021-11-27", cache_root=self.root)
        self.assertEqual(ergebnis["source"], "headers")
        self.assertEqual(ergebnis["height"], 700_001)


class TestExplorer(unittest.TestCase):
    def setUp(self):
        self.url = "http://192.0.2.8:8080"
        self._policy = mock.patch(
            "core.outbound_policy.ensure_url_allowed",
            side_effect=lambda u, **_k: u,
        )
        self._policy.start()
        self.addCleanup(self._policy.stop)

    def test_datum_nimmt_explorer_wenn_header_fehlen(self):
        def urlopen(anfrage, timeout=None, context=None):
            url = anfrage.full_url
            if "timestamp/" in url:
                return _Antwort(json.dumps({
                    "height": 769786,
                    "hash": "ab" * 32,
                    "timestamp": "2022-12-31T23:30:31.000Z",
                }))
            raise AssertionError(url)

        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            hoehe = explorer_hoehe_aus_datum(self.url, "2023-01-01")
        # Closest-Block liegt vor Mitternacht → nächste Höhe.
        self.assertEqual(hoehe, 769787)

    def test_hoehe_nimmt_explorer_blockzeit(self):
        def urlopen(anfrage, timeout=None, context=None):
            url = anfrage.full_url
            if url.endswith("/block-height/481824"):
                return _Antwort("aa" * 32)
            if "/block/" in url:
                return _Antwort(json.dumps({"timestamp": 1_503_539_857}))
            raise AssertionError(url)

        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            datum = explorer_datum_aus_hoehe(self.url, 481824)
        self.assertEqual(datum, "2017-08-24")

    def test_explorer_vor_schaetzung(self):
        def urlopen(anfrage, timeout=None, context=None):
            if "timestamp/" in anfrage.full_url:
                return _Antwort(json.dumps({
                    "height": 610690,
                    "timestamp": 1_577_836_800,
                }))
            raise AssertionError(anfrage.full_url)

        leer = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(leer, ignore_errors=True))
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            ergebnis = rechne_scan_zeit(
                datum="2020-01-01",
                cache_root=leer,
                explorer_url=self.url,
            )
        self.assertEqual(ergebnis["source"], "explorer")
        self.assertEqual(ergebnis["height"], 610690)

    def test_ohne_explorer_schaetzung(self):
        leer = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(leer, ignore_errors=True))
        ergebnis = rechne_scan_zeit(hoehe=100, cache_root=leer)
        self.assertEqual(ergebnis["source"], "estimate")
        self.assertEqual(ergebnis["date"], schaetze_datum_aus_hoehe(100))
        self.assertEqual(ergebnis["height"], 100)

    def test_explorer_fehler_faellt_auf_schaetzung(self):
        leer = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(leer, ignore_errors=True))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            ergebnis = rechne_scan_zeit(
                hoehe=100,
                cache_root=leer,
                explorer_url=self.url,
            )
        self.assertEqual(ergebnis["source"], "estimate")
        self.assertEqual(ergebnis["date"], schaetze_datum_aus_hoehe(100))

    def test_public_ohne_opt_in_wird_nicht_gefragt(self):
        from core.outbound_policy import OutboundPolicyError

        leer = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(leer, ignore_errors=True))
        self._policy.stop()
        with mock.patch(
            "core.outbound_policy.ensure_url_allowed",
            side_effect=OutboundPolicyError("blockiert"),
        ), mock.patch("urllib.request.urlopen") as urlopen:
            ergebnis = rechne_scan_zeit(
                datum="2017-08-24",
                cache_root=leer,
                explorer_url="https://mempool.space",
            )
        urlopen.assert_not_called()
        self.assertEqual(ergebnis["source"], "estimate")
        self.assertEqual(ergebnis["height"], schaetze_hoehe_aus_datum("2017-08-24"))


class TestEingabe(unittest.TestCase):
    def test_leere_richtung_wirft(self):
        with self.assertRaises(ValueError):
            rechne_scan_zeit()

    def test_negative_hoehe_wirft(self):
        with self.assertRaises(ValueError):
            rechne_scan_zeit(hoehe=-1)


if __name__ == "__main__":
    unittest.main()
