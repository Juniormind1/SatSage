"""
Paralleler Scan über mehrere Fulcrum-Verbindungen.

Ein FulcrumClient hält genau einen Socket und verträgt keine gleichzeitigen
Anfragen. Der Pool gibt deshalb jedem Worker-Thread seine eigene Verbindung.
Geprüft wird hier vor allem, was dabei schiefgehen könnte: vertauschte
Reihenfolge, ein Client in zwei Threads, eine einzelne kaputte Adresse, die
den ganzen Scan mitreißt.
"""
import threading
import time
import unittest
from unittest import mock

import fulcrum
import main


class FakeClient:
    """Merkt sich, aus welchen Threads er benutzt wurde."""

    def __init__(self, kennung: int):
        self.kennung = kennung
        self.threads: set[int] = set()
        self.aufrufe = 0

    def benutze(self):
        self.threads.add(threading.get_ident())
        self.aufrufe += 1


class FakePool:
    def __init__(self, anzahl: int):
        self.clients = [FakeClient(i) for i in range(anzahl)]

    def __len__(self) -> int:
        return len(self.clients)

    def client_at(self, worker_id: int) -> FakeClient:
        return self.clients[worker_id % len(self.clients)]


class TestReihenfolge(unittest.TestCase):

    def test_ergebnis_folgt_der_eingabe_nicht_der_fertigstellung(self):
        """
        Die erste Aufgabe braucht am längsten. Käme das Ergebnis in der
        Reihenfolge der Fertigstellung, stünde sie am Ende — und der Aufrufer
        bekäme bei jedem Lauf eine andere Anordnung.
        """
        pool = FakePool(4)

        def arbeit(client, zahl):
            client.benutze()
            if zahl == 0:
                time.sleep(0.05)
            return zahl * 10

        ergebnis = fulcrum.parallel_ueber_pool(pool, list(range(8)), arbeit)
        self.assertEqual(ergebnis, [0, 10, 20, 30, 40, 50, 60, 70])

    def test_leere_eingabe(self):
        self.assertEqual(
            fulcrum.parallel_ueber_pool(FakePool(4), [], lambda c, a: a), []
        )

    def test_eine_aufgabe_bei_vielen_verbindungen(self):
        pool = FakePool(8)
        ergebnis = fulcrum.parallel_ueber_pool(pool, ["x"], lambda c, a: a.upper())
        self.assertEqual(ergebnis, ["X"])


class TestVerbindungen(unittest.TestCase):

    def test_kein_client_in_zwei_threads(self):
        """
        Der eigentliche Grund für den Pool: Zwei Threads auf einem Socket
        würden sich die Antworten gegenseitig wegnehmen.
        """
        pool = FakePool(4)

        def arbeit(client, zahl):
            client.benutze()
            time.sleep(0.01)
            return zahl

        fulcrum.parallel_ueber_pool(pool, list(range(40)), arbeit)
        for client in pool.clients:
            self.assertLessEqual(
                len(client.threads), 1,
                f"Verbindung {client.kennung} wurde aus mehreren Threads benutzt.",
            )

    def test_nicht_mehr_worker_als_aufgaben(self):
        pool = FakePool(8)
        fulcrum.parallel_ueber_pool(pool, [1, 2], lambda c, a: (c.benutze(), a)[1])
        benutzt = sum(1 for c in pool.clients if c.aufrufe)
        self.assertLessEqual(benutzt, 2)


class TestFehlertoleranz(unittest.TestCase):

    def test_eine_kaputte_aufgabe_stoppt_die_uebrigen_nicht(self):
        pool = FakePool(4)

        def arbeit(client, zahl):
            if zahl == 3:
                raise OSError("Verbindung weg")
            return zahl

        ergebnis = fulcrum.parallel_ueber_pool(pool, list(range(6)), arbeit)
        self.assertEqual(ergebnis, [0, 1, 2, None, 4, 5])

    def test_fortschritt_wird_gemeldet(self):
        pool = FakePool(3)
        stand: list[tuple[int, int]] = []
        sperre = threading.Lock()

        def melde(fertig, gesamt):
            with sperre:
                stand.append((fertig, gesamt))

        fulcrum.parallel_ueber_pool(
            pool, list(range(9)), lambda c, a: a, fortschritt=melde
        )
        self.assertEqual(len(stand), 9)
        self.assertEqual(sorted(f for f, _ in stand), list(range(1, 10)))
        self.assertTrue(all(g == 9 for _, g in stand))


class TestAbbruch(unittest.TestCase):

    def setUp(self):
        import display

        self._alt = display.is_list_abort_requested
        self.addCleanup(lambda: setattr(display, "is_list_abort_requested", self._alt))

    def test_abbruch_beendet_den_lauf(self):
        """
        Der Abbruch wirkt zwischen den Aufgaben. Laufende Abfragen werden zu
        Ende geführt — sie mitten im Socket abzuschneiden hinterließe eine
        unbrauchbare Verbindung.
        """
        import display

        display.is_list_abort_requested = lambda: True
        pool = FakePool(4)
        ergebnis = fulcrum.parallel_ueber_pool(
            pool, list(range(10)), lambda c, a: a
        )
        self.assertEqual(ergebnis, [None] * 10)


class TestUtxoScan(unittest.TestCase):
    """Der Scan liefert mit und ohne Pool dasselbe."""

    def setUp(self):
        self.adressen = {f"bc1qtest{i}" for i in range(12)}

        def fake_fetch(client, adresse):
            nummer = int(adresse.replace("bc1qtest", ""))
            return [{"txid": f"{nummer:064x}", "vout": 0, "value": nummer * 1000}]

        self._alt = fulcrum.fetch_address_utxos_fulcrum
        fulcrum.fetch_address_utxos_fulcrum = fake_fetch
        self.addCleanup(
            lambda: setattr(fulcrum, "fetch_address_utxos_fulcrum", self._alt)
        )

    def test_gleiche_menge_mit_und_ohne_pool(self):
        ohne = fulcrum.fetch_wallet_utxos_fulcrum(FakeClient(0), self.adressen)
        mit = fulcrum.fetch_wallet_utxos_fulcrum(
            FakeClient(0), self.adressen, pool=FakePool(4)
        )
        schluessel = lambda liste: sorted((u["txid"], u["address"]) for u in liste)
        self.assertEqual(schluessel(ohne), schluessel(mit))
        self.assertEqual(len(mit), 12)

    def test_jede_utxo_traegt_ihre_adresse(self):
        utxos = fulcrum.fetch_wallet_utxos_fulcrum(
            FakeClient(0), self.adressen, pool=FakePool(4)
        )
        self.assertTrue(all(u.get("address") in self.adressen for u in utxos))

    def test_einzelne_verbindung_bleibt_sequenziell(self):
        """Ein Pool mit einer Verbindung bringt nichts — dann der alte Weg."""
        utxos = fulcrum.fetch_wallet_utxos_fulcrum(
            FakeClient(0), self.adressen, pool=FakePool(1)
        )
        self.assertEqual(len(utxos), 12)


class TestVorladen(unittest.TestCase):
    """
    Das Vorladen füllt nur den Cache. Baum und Reihenfolge müssen exakt
    dieselben bleiben — sonst hinge das Ergebnis einer Herkunftsanalyse davon
    ab, ob gerade ein Pool zur Verfügung stand.
    """

    def setUp(self):
        import trace_engine
        from tests.fixtures import make_get_tx, simple_chain

        self.kette = simple_chain()
        self.engine = trace_engine
        self.make_get_tx = make_get_tx

    def kanten(self, get_tx):
        from tests.fixtures import BIP84_CHANGE_0, BIP84_RECEIVE_0, TXID_WALLET_IN

        return list(self.engine.iter_trace_funding_inputs(
            get_tx, TXID_WALLET_IN, {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        ))

    def test_ergebnis_mit_und_ohne_vorlader_gleich(self):
        ohne = self.kanten(self.make_get_tx(self.kette))

        vorgeladen: list[list[str]] = []
        mit_vorlader = self.make_get_tx(self.kette)
        mit_vorlader.prefetch = lambda txids: vorgeladen.append(list(txids))

        mit = self.kanten(mit_vorlader)
        self.assertEqual(
            [type(k).__name__ for k in ohne], [type(k).__name__ for k in mit]
        )
        self.assertEqual(len(ohne), len(mit))

    def test_vorlader_bekommt_die_offenen_vorgaenger(self):
        gerufen: list[list[str]] = []
        get_tx = self.make_get_tx(self.kette)
        get_tx.prefetch = lambda txids: gerufen.append(list(txids))

        self.kanten(get_tx)
        self.assertTrue(gerufen, "Der Vorlader wurde nicht aufgerufen.")
        self.assertTrue(all(isinstance(t, str) for t in gerufen[0]))

    def test_fehler_im_vorlader_bricht_nichts_ab(self):
        """
        Vorladen ist Beschleunigung, kein Abruf. Fällt es aus, holt der
        reguläre Weg die Vorgänger einzeln nach.
        """
        def kaputt(_txids):
            raise OSError("Pool weg")

        get_tx = self.make_get_tx(self.kette)
        get_tx.prefetch = kaputt
        self.assertEqual(len(self.kanten(get_tx)), len(self.kanten(
            self.make_get_tx(self.kette)
        )))


class TestOpenScanPool(unittest.TestCase):
    """
    Extra-Sockets nur zum eigenen LAN-Fulcrum. Öffentliche Rotation hat
    keinen einzelnen Host/Port — das war der Crash nach Clearnet-Fallback.
    """

    def _client(self, *, tor=False) -> fulcrum.FulcrumClient:
        proxy = ("127.0.0.1", 9050) if tor else None
        return fulcrum.FulcrumClient(
            "192.0.2.1", 50002, use_ssl=True, timeout=5, tor_proxy=proxy
        )

    def test_rotating_pool_ohne_crash(self):
        pool = fulcrum.RotatingFulcrumPool([self._client()])
        with mock.patch("fulcrum.connect_fulcrum") as connect:
            self.assertIsNone(main._open_scan_pool(pool))
        connect.assert_not_called()

    def test_clearnet_pool_ohne_crash(self):
        pool = fulcrum.SanctionsClearnetPool([self._client()])
        with mock.patch("fulcrum.connect_fulcrum") as connect:
            self.assertIsNone(main._open_scan_pool(pool))
        connect.assert_not_called()

    def test_tor_client_bekommt_keine_extra_sockets(self):
        with mock.patch("fulcrum.connect_fulcrum") as connect:
            self.assertIsNone(main._open_scan_pool(self._client(tor=True)))
        connect.assert_not_called()

    def test_none_und_zu_wenig_worker(self):
        self.assertIsNone(main._open_scan_pool(None))
        with mock.patch("fulcrum.connect_fulcrum") as connect:
            self.assertIsNone(main._open_scan_pool(self._client(), workers=1))
        connect.assert_not_called()

    def test_eigener_lan_client_oeffnet_weitere(self):
        erster = self._client()
        extra = self._client()
        with mock.patch(
            "fulcrum.connect_fulcrum", return_value=(extra, None)
        ) as connect:
            pool = main._open_scan_pool(erster, workers=3)
        self.assertIsInstance(pool, fulcrum.SanctionsClearnetPool)
        self.assertEqual(len(pool), 3)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(connect.call_args.args[:2], ("192.0.2.1", 50002))

    def test_fehlende_extra_verbindung_ist_kein_pool(self):
        with mock.patch(
            "fulcrum.connect_fulcrum", return_value=(None, "timeout")
        ):
            self.assertIsNone(main._open_scan_pool(self._client()))


if __name__ == "__main__":
    unittest.main()
