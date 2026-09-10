"""
Priorisierung der Sanktions-Datenquelle.

Der eigene, privat adressierte Server (LAN/Loopback) geht vor — schnell
und ohne dass Anfragen nach gelisteten Fremdadressen das eigene Netz
verlassen. Erst wenn keiner konfiguriert oder erreichbar ist, greift der
öffentliche Clearnet-Pool. Öffentlich konfigurierte eigene Server und Tor
werden bewusst übersprungen: Sanktionsabfragen sollen nicht mit der
Identität des Benutzers verknüpft werden.
"""
import unittest
from unittest import mock

import main


class TestSanctionsPrioritaet(unittest.TestCase):

    def _lauf(self, env, probierte_hosts, pool_ok=True):
        """
        Führt resolve_sanctions_preferred_client mit gefälschten Probes aus.
        probierte_hosts sammelt die angefragten Hosts in Reihenfolge.
        """
        def fake_open(host, port, use_ssl, workers):
            probierte_hosts.append(host)
            return None, 0.0  # nie erreichbar — zwingt den Fallback

        class FakePool:
            primary = object()

        main._sanctions_own_pool = None
        main._sanctions_own_cache_key = None
        with mock.patch.object(main, "_open_own_sanctions_pool", fake_open), \
             mock.patch.object(
                 main, "resolve_sanctions_clearnet_pool",
                 return_value=(FakePool() if pool_ok else None, False),
             ):
            return main.resolve_sanctions_preferred_client(env)

    def test_privater_eigener_host_wird_zuerst_versucht(self):
        probiert = []
        client, quelle = self._lauf({"FULCRUM_HOST": "192.168.1.10"}, probiert)
        self.assertEqual(probiert[0], "192.168.1.10")
        # Nicht erreichbar → Fallback auf den Pool
        self.assertEqual(quelle, "clearnet_pool")
        self.assertIsNotNone(client)

    def test_loopback_gilt_als_privat(self):
        probiert = []
        self._lauf({"FULCRUM_HOST": "127.0.0.1"}, probiert)
        self.assertEqual(probiert[0], "127.0.0.1")

    def test_oeffentlicher_eigener_host_wird_uebersprungen(self):
        """Sanktionsabfragen gehören nicht über den eigenen Public-Server."""
        probiert = []
        client, quelle = self._lauf(
            {"FULCRUM_HOST": "fulcrum.example.com"}, probiert
        )
        # Hostname löst nicht als IP auf → nicht privat → kein Probe-Versuch
        self.assertNotIn("fulcrum.example.com", probiert)
        self.assertEqual(quelle, "clearnet_pool")

    def test_sanctions_host_privat_hat_vorrang_vor_fulcrum_host(self):
        probiert = []
        self._lauf(
            {
                "FULCRUM_SANCTIONS_HOST": "10.0.0.5",
                "FULCRUM_HOST": "192.168.1.10",
            },
            probiert,
        )
        self.assertEqual(probiert[:2], ["10.0.0.5", "192.168.1.10"])

    def test_sanctions_host_oeffentlich_bleibt_beim_alten_weg(self):
        """Öffentlicher FULCRUM_SANCTIONS_HOST läuft über den Pool-Pfad."""
        probiert = []
        with mock.patch.object(
            main, "resolve_sanctions_clearnet_pool",
            return_value=(None, False),
        ):
            client, quelle = self._lauf(
                {"FULCRUM_SANCTIONS_HOST": "8.8.8.8"}, probiert, pool_ok=False
            )
        self.assertEqual(probiert, [])
        self.assertEqual(quelle, "none")
        self.assertIsNone(client)

    def test_nichts_konfiguriert_geht_direkt_in_den_pool(self):
        probiert = []
        client, quelle = self._lauf({}, probiert)
        self.assertEqual(probiert, [])
        self.assertEqual(quelle, "clearnet_pool")

    def test_pool_ohne_treffer_liefert_none(self):
        client, quelle = self._lauf({}, [], pool_ok=False)
        self.assertEqual(quelle, "none")
        self.assertIsNone(client)


if __name__ == "__main__":
    unittest.main()


class TestPortAusEnv(unittest.TestCase):
    """
    Eine leergeräumte Zeile in der .env ist ein normaler Zwischenzustand
    beim Bearbeiten — sie darf keine Abfrage mit einem ValueError
    abbrechen.
    """

    def test_leerer_port_faellt_auf_den_standard_zurueck(self):
        self.assertEqual(main._env_port({"FULCRUM_PORT": ""}, "FULCRUM_PORT"), 50002)

    def test_fehlender_port_faellt_auf_den_standard_zurueck(self):
        self.assertEqual(main._env_port({}, "FULCRUM_PORT"), 50002)

    def test_unsinniger_port_faellt_auf_den_standard_zurueck(self):
        self.assertEqual(
            main._env_port({"FULCRUM_PORT": "keine Zahl"}, "FULCRUM_PORT"), 50002
        )

    def test_gesetzter_port_gilt(self):
        self.assertEqual(
            main._env_port({"FULCRUM_PORT": " 50001 "}, "FULCRUM_PORT"), 50001
        )

    def test_serverwahl_ueberlebt_leeren_port(self):
        """Der eigentliche Regressionsfall: kein Absturz in der Serverwahl."""
        main._sanctions_own_pool = None
        main._sanctions_own_cache_key = None
        with mock.patch.object(
            main, "_open_own_sanctions_pool", return_value=(None, 0.0)
        ), mock.patch.object(
            main, "resolve_sanctions_clearnet_pool", return_value=(None, False)
        ):
            client, quelle = main.resolve_sanctions_preferred_client(
                {"FULCRUM_HOST": "192.168.1.10", "FULCRUM_PORT": ""}
            )
        self.assertIsNone(client)
        self.assertEqual(quelle, "none")


class TestEigenerNodePool(unittest.TestCase):
    """
    Der eigene Node trägt den Parallel-Scan mit. Ein Fulcrum im LAN verträgt
    mehrere Verbindungen problemlos; ihn seriell abzufragen, während der
    Clearnet-Weg parallel läuft, wäre eine Strafe fürs Selberhosten.
    """

    def setUp(self):
        main._sanctions_own_pool = None
        main._sanctions_own_cache_key = None
        self.addCleanup(setattr, main, "_sanctions_own_pool", None)
        self.addCleanup(setattr, main, "_sanctions_own_cache_key", None)

    def _lauf(self, env, verbindungen=99):
        """*verbindungen*: wie viele Zusatzverbindungen gelingen."""
        self.verbunden = []

        class FakeClient:
            host = "192.168.1.10"
            port = 50002
            use_ssl = True

            def close(self):
                pass

        def fake_connect(host, port, **kw):
            self.verbunden.append((host, port))
            # Erste Verbindung immer; *verbindungen* = zusätzliche Erfolge.
            if len(self.verbunden) > verbindungen + 1:
                return None, "zu viele"
            return FakeClient(), None

        with mock.patch("fulcrum.connect_fulcrum", fake_connect):
            return main.resolve_sanctions_preferred_pool(env)

    def test_eigener_node_liefert_mehrere_verbindungen(self):
        pool, quelle, aus_cache = self._lauf({"FULCRUM_HOST": "192.168.1.10"})
        self.assertEqual(quelle, "own_private")
        self.assertFalse(aus_cache)
        self.assertEqual(len(pool), main.SANCTIONS_OWN_NODE_WORKERS)
        self.assertGreater(len(pool.worker_labels()), 1)

    def test_zweiter_aufruf_nutzt_den_offenen_pool(self):
        """Vier Verbindungen bei jedem Menüpunkt neu aufzubauen wäre teuer."""
        erster, _, _ = self._lauf({"FULCRUM_HOST": "192.168.1.10"})
        vorher = len(self.verbunden)
        zweiter, quelle, aus_cache = self._lauf({"FULCRUM_HOST": "192.168.1.10"})
        self.assertIs(zweiter, erster)
        self.assertEqual(quelle, "own_private")
        self.assertTrue(aus_cache)
        self.assertEqual(len(self.verbunden), 0, "keine neuen Verbindungen")
        self.assertGreater(vorher, 0)

    def test_nur_eine_verbindung_ist_kein_grund_fuer_clearnet(self):
        """
        Wenn der Node nur eine Verbindung zulässt, läuft der Scan eben
        seriell — über Clearnet auszuweichen wäre schlechter für die
        Privatsphäre.
        """
        pool, quelle, _ = self._lauf(
            {"FULCRUM_HOST": "192.168.1.10"}, verbindungen=0
        )
        self.assertEqual(quelle, "own_private")
        self.assertEqual(len(pool), 1)


class TestParallelerVorgeschichteScan(unittest.TestCase):
    """
    Der Web-Sanktionscheck verteilt die UTXOs auf die Verbindungen des
    Pools. Ein Fulcrum-Client ist eine einzelne Socket-Verbindung — jeder
    Worker braucht deshalb seinen eigenen.
    """

    def setUp(self):
        import analyze

        self.analyze = analyze
        self.eigene = {"bc1qeigen"}
        self.gelistet = frozenset({"1Gelistet"})

    def _kette(self, anzahl):
        """*anzahl* Wallet-UTXOs, jedes mit einem gelisteten Vorgänger."""
        utxos, txs = [], {}
        for i in range(anzahl):
            wallet_tx = f"{i:064d}"
            vorher = f"{i + 500:064d}"
            utxos.append({"txid": wallet_tx, "vout": 0, "address": "bc1qeigen"})
            txs[wallet_tx] = {
                "txid": wallet_tx,
                "vin": [{
                    "txid": vorher, "vout": 0, "is_coinbase": False,
                    "prevout": {"scriptpubkey_address": "1Gelistet",
                                "value": 1000},
                }],
                "vout": [{"scriptpubkey_address": "bc1qeigen", "value": 1000}],
                "status": {"confirmed": True, "block_time": 1_700_000_000},
            }
            txs[vorher] = {
                "txid": vorher, "vin": [],
                "vout": [{"scriptpubkey_address": "1Gelistet", "value": 1000}],
                "status": {"confirmed": True, "block_time": 1_600_000_000},
            }
        return utxos, txs

    def _lauf(self, anzahl, worker):
        utxos, txs = self._kette(anzahl)
        self.benutzte_worker = set()

        def get_tx_je_worker(worker_id):
            self.benutzte_worker.add(worker_id)

            def get_tx(t):
                return txs[t]

            return get_tx

        return self.analyze.check_wallet_utxos_sanctions(
            lambda t: txs[t],
            utxos,
            self.eigene,
            self.gelistet,
            max_hops=1,
            abort_on_hit=False,
            get_tx_je_worker=get_tx_je_worker,
            worker_count=worker,
        )

    def test_parallel_findet_dieselben_treffer_wie_seriell(self):
        treffer_p, geprueft_p, _ = self._lauf(8, worker=4)
        treffer_s, geprueft_s, _ = self._lauf(8, worker=1)
        self.assertEqual(geprueft_p, 8)
        self.assertEqual(geprueft_p, geprueft_s)
        self.assertEqual(len(treffer_p), len(treffer_s))
        self.assertEqual(
            {t["address"] for t in treffer_p},
            {t["address"] for t in treffer_s},
        )

    def test_jeder_worker_bekommt_eine_eigene_verbindung(self):
        self._lauf(8, worker=4)
        self.assertEqual(self.benutzte_worker, {0, 1, 2, 3})

    def test_nicht_mehr_worker_als_utxos(self):
        """Vier Verbindungen für zwei UTXOs zu öffnen wäre Verschwendung."""
        self._lauf(2, worker=4)
        self.assertEqual(self.benutzte_worker, {0, 1})

    def test_treffer_reihenfolge_ist_stabil(self):
        """
        Ohne Sortierung hinge die Reihenfolge am Thread-Timing — zwei Läufe
        über dieselben Daten lieferten verschiedene Cache-Dateien.
        """
        erst, _, _ = self._lauf(8, worker=4)
        zweit, _, _ = self._lauf(8, worker=4)
        schluessel = lambda ts: [(t["wallet_utxo"], t["hop"], t["address"]) for t in ts]
        self.assertEqual(schluessel(erst), schluessel(zweit))
        self.assertEqual(schluessel(erst), sorted(schluessel(erst)))

    def test_serieller_weg_bleibt_bei_treffer_abbruch(self):
        """
        Die CLI bricht beim ersten Treffer ab. Das ist mit laufenden Threads
        nicht sinnvoll umzusetzen — dort bleibt es seriell.
        """
        utxos, txs = self._kette(4)
        benutzt = []
        treffer, geprueft, abbruch = self.analyze.check_wallet_utxos_sanctions(
            lambda t: txs[t],
            utxos,
            self.eigene,
            self.gelistet,
            max_hops=1,
            abort_on_hit=True,
            get_tx_je_worker=lambda wid: benutzt.append(wid),
            worker_count=4,
        )
        self.assertEqual(benutzt, [], "Parallelweg darf hier nicht greifen")
        self.assertIsNotNone(abbruch)
        self.assertEqual(geprueft, 1)


class TestFortschrittMeldetHopTiefe(unittest.TestCase):
    """
    Bis hierher meldete der Nicht-CLI-Weg nur einmal je UTXO ``hop=0``; die
    echte Tiefe blieb in scan_external_sanction_hops stecken. Die
    Weboberfläche zeigte deshalb dauerhaft „Hop 0".
    """

    def test_hop_tiefe_erreicht_das_callback(self):
        import analyze

        wallet_tx, hop1, hop2 = f"{1:064d}", f"{2:064d}", f"{3:064d}"

        def externe_tx(txid, vorher):
            return {
                "txid": txid,
                "vin": [{
                    "txid": vorher, "vout": 0, "is_coinbase": False,
                    "prevout": {"scriptpubkey_address": "1Fremd", "value": 1000},
                }],
                "vout": [{"scriptpubkey_address": "1Fremd", "value": 1000}],
                "status": {"confirmed": True, "block_time": 1_600_000_000},
            }

        txs = {
            wallet_tx: externe_tx(wallet_tx, hop1),
            hop1: externe_tx(hop1, hop2),
            hop2: {"txid": hop2, "vin": [],
                   "vout": [{"scriptpubkey_address": "1Fremd", "value": 1000}],
                   "status": {"confirmed": True, "block_time": 1_500_000_000}},
        }
        gemeldet = []
        analyze.check_wallet_utxos_sanctions(
            lambda t: txs[t],
            [{"txid": wallet_tx, "vout": 0, "address": "bc1qeigen"}],
            {"bc1qeigen"},
            frozenset({"1Gelistet"}),
            max_hops=3,
            abort_on_hit=False,
            progress_cb=gemeldet.append,
        )
        tiefen = {f["hop"] for f in gemeldet}
        self.assertIn(0, tiefen)
        self.assertTrue(
            max(tiefen) >= 1, f"nur Hop 0 gemeldet: {sorted(tiefen)}"
        )
        self.assertTrue(any(f["addrs_checked"] > 0 for f in gemeldet))
