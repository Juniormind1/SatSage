"""
Datenquellen-Beschreibung und Erreichbarkeitsprüfung.

Deckt den Fehler ab, bei dem der Node-Test in der Web-Oberfläche mit
„SourceInfo.__init__() got an unexpected keyword argument 'editierbar'"
scheiterte: check_reachable baute die Kopie über SourceInfo(**as_dict()),
und as_dict() enthält die Property editierbar sowie felder als rohe dicts —
beides keine Konstruktor-Argumente.
"""
import unittest
from unittest import mock

from core.source import (
    check_reachable,
    check_sources,
    describe_sources,
    mergere_erreichbarkeit,
    oeffentliche_electrum_erlaubt,
    peer_aenderungen,
    peer_status,
    source_needs_tor,
)


def _ohne_live_p2p():
    """Suite kann parallele BIP-158-Peers halten — Tests brauchen Isolation."""
    return mock.patch(
        "core.source.anreichere_live_p2p",
        side_effect=lambda quellen: list(quellen),
    )


class TestTlsAutoProbe(unittest.TestCase):
    """TLS ja/nein: Gegenprobe und Festschreiben."""

    def test_should_try_opposite_bei_wrong_version(self):
        import main

        self.assertTrue(
            main.tls_should_try_opposite("WRONG_VERSION_NUMBER")
        )
        self.assertTrue(
            main.tls_should_try_opposite(
                "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF"
            )
        )
        self.assertFalse(main.tls_should_try_opposite("connection refused"))
        self.assertFalse(main.tls_should_try_opposite("timed out"))
        self.assertFalse(
            main.tls_should_try_opposite("listunspent nicht unterstützt")
        )

    def test_check_reachable_probiert_ohne_tls_und_meldet_persist(self):
        from fulcrum import FulcrumClient

        client = mock.Mock(spec=FulcrumClient)
        client.server_software = "libbitcoin"
        client.server_software_raw = "/libbitcoin:4.0.0/"
        client.close = mock.Mock()
        werte = {
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "true",  # falsch für Klartext-Port
        }
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        calls = {"n": 0}

        def connect(host, port, use_ssl=True, timeout=5, tor_proxy=None,
                    require_listunspent=False):
            calls["n"] += 1
            if use_ssl:
                return None, "WRONG_VERSION_NUMBER"
            return client, None

        with mock.patch("core.fulcrum_client.connect_fulcrum", side_effect=connect):
            out = check_reachable(quelle, werte, timeout=1)
        self.assertTrue(out.reachable)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(out.ssl_effective, False)
        self.assertEqual(out.ssl_persist.get("FULCRUM_SSL"), "false")
        self.assertIn("festgeschrieben", out.note)


class TestElectrumSoftwareLabel(unittest.TestCase):
    """server.version → Pillen-Name (electrs / fulcrum / libbitcoin)."""

    def test_libbitcoin_pfad_form(self):
        from fulcrum import parse_electrum_server_software

        label, roh = parse_electrum_server_software(["/libbitcoin:4.0.0/", "1.4"])
        self.assertEqual(label, "libbitcoin")
        self.assertIn("libbitcoin", roh)

    def test_electrs_und_fulcrum(self):
        from fulcrum import parse_electrum_server_software

        self.assertEqual(
            parse_electrum_server_software(["electrs/0.10.5", "1.4"])[0],
            "electrs",
        )
        self.assertEqual(
            parse_electrum_server_software(["Fulcrum 1.9.1", "1.4"])[0],
            "fulcrum",
        )

    def test_check_reachable_uebernimmt_software(self):
        from fulcrum import FulcrumClient

        client = mock.Mock(spec=FulcrumClient)
        client.server_software = "libbitcoin"
        client.server_software_raw = "/libbitcoin:4.0.0/"
        client.close = mock.Mock()
        werte = {
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "false",
        }
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        with mock.patch("core.fulcrum_client.connect_fulcrum", return_value=(client, None)):
            out = check_reachable(quelle, werte, timeout=1)
        self.assertTrue(out.reachable)
        self.assertEqual(out.software, "libbitcoin")
        self.assertIn("libbitcoin", out.detail)
        self.assertIn("libbitcoin", out.as_dict()["software"])

    def test_merke_own_fulcrum_sofort_in_sources(self):
        from core.source import (
            merke_own_fulcrum_in_sources,
            own_fulcrum_stand_from_client,
            peer_status,
            verbindung_label,
        )

        self.assertEqual(
            verbindung_label(electrs_n=1, electrum_name="libbitcoin"),
            "1 libbitcoin verbunden",
        )
        self.assertEqual(
            verbindung_label(electrs_n=1),
            "1 electrs verbunden",
        )
        client = mock.Mock()
        client.host = "192.0.2.10"
        client.port = 50001
        client.server_software = "libbitcoin"
        client.server_software_raw = "/libbitcoin:4.0.0/"
        stand = own_fulcrum_stand_from_client(client)
        self.assertEqual(stand["software"], "libbitcoin")
        werte = {
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "false",
        }
        frisch = describe_sources(werte)
        liste = merke_own_fulcrum_in_sources(None, frisch, stand)
        own = next(q for q in liste if q["key"] == "own_fulcrum")
        self.assertTrue(own["reachable"])
        self.assertEqual(own["software"], "libbitcoin")
        gemerged = mergere_erreichbarkeit(describe_sources(werte), liste)
        ps = peer_status(gemerged)
        # Label kann Peers + Indexer nennen (z. B. „2 Peers · 1 libbitcoin…“).
        self.assertIn("libbitcoin", ps["label"])
        self.assertEqual(ps.get("software"), "libbitcoin")


class TestCheckReachable(unittest.TestCase):

    def test_kopie_funktioniert_fuer_alle_quellen(self):
        """Jede Quelle muss durch check_reachable kopierbar sein."""
        quellen = describe_sources({})
        self.assertTrue(quellen)
        for quelle in quellen:
            kopie = check_reachable(quelle, {})
            self.assertEqual(kopie.key, quelle.key)
            self.assertEqual(kopie.felder, quelle.felder)

    def test_nicht_eigene_quellen_werden_nicht_geprueft(self):
        """Tor/Third-Party-Quellen kosten Verbindungen oder verraten Daten."""
        quellen = describe_sources({})
        for quelle in quellen:
            if quelle.key == "own_fulcrum":
                continue
            kopie = check_reachable(quelle, {})
            self.assertIsNone(kopie.reachable)

    def test_check_reachable_normalisiert_https_onion(self):
        """Start9-Kopieren liefert https://….onion — SOCKS darf das nicht roh sehen."""
        from unittest import mock
        werte = {
            "FULCRUM_TOR": "https://abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwxyz.onion",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "false",
        }
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        with mock.patch(
            "core.tor.stelle_tor_socks_bereit", return_value=("127.0.0.1", 9150)
        ), mock.patch("core.fulcrum_client.connect_fulcrum", return_value=(None, "timeout")) as cf:
            check_reachable(quelle, werte, timeout=1)
        host = cf.call_args[0][0]
        self.assertFalse(host.startswith("http"))
        self.assertTrue(host.endswith(".onion"))
        self.assertNotIn(":", host)

    def test_check_reachable_schreibt_verbindungs_log(self):
        from unittest import mock
        werte = {"FULCRUM_HOST": "192.0.2.1", "FULCRUM_PORT": "50001",
                 "FULCRUM_SSL": "false"}
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        with mock.patch("core.fulcrum_client.connect_fulcrum", return_value=(None, "timeout")):
            geprueft = check_reachable(quelle, werte, timeout=1)
        text = "\n".join(geprueft.log)
        self.assertIn("Prüfe Eigener Electrum-Server", text)
        self.assertIn("Verbinde mit 192.0.2.1:50001", text)
        self.assertIn("ohne TLS", text)
        self.assertIn("Verbindung fehlgeschlagen: timeout", text)
        self.assertNotIn("Verbunden.", text)
        self.assertTrue(
            geprueft.log[0].startswith("Prüfe "),
            geprueft.log,
        )

    def test_check_reachable_meldet_log_sofort(self):
        """on_log feuert bei jeder Zeile, nicht erst beim Rückgabewert."""
        from unittest import mock
        gesehen = []
        werte = {"FULCRUM_HOST": "192.0.2.1", "FULCRUM_PORT": "50001",
                 "FULCRUM_SSL": "false"}
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        with mock.patch("core.fulcrum_client.connect_fulcrum", return_value=(None, "timeout")):
            geprueft = check_reachable(
                quelle, werte, timeout=1, on_log=gesehen.append,
            )
        self.assertEqual(gesehen, geprueft.log)
        self.assertTrue(gesehen[0].startswith("Prüfe "))

    def test_port_50001_ist_standard_ohne_tls(self):
        quelle = next(
            q for q in describe_sources({"FULCRUM_TOR": "abc.onion",
                                         "FULCRUM_PORT": "50001"})
            if q.key == "own_fulcrum"
        )
        ssl = next(f for f in quelle.felder if f.key == "FULCRUM_SSL")
        self.assertEqual(ssl.value, "false")

    def test_oeffentliche_quellen_haben_electrum_ladeknopf(self):
        quellen = {q.key: q for q in describe_sources({})}
        self.assertEqual(quellen["public_onion"].laden_filter, "onion")
        self.assertEqual(quellen["clearnet"].laden_filter, "clearnet")
        self.assertIn("electrum", quellen["public_onion"].laden_url)
        self.assertNotIn("esplora", quellen)
        self.assertFalse(quellen["public_onion"].editierbar)
        self.assertEqual(quellen["public_onion"].felder, [])

    def test_esplora_ist_keine_quelle_mehr(self):
        """Esplora entfällt — P2P und Electrum reichen."""
        keys = {q.key for q in describe_sources({})}
        self.assertNotIn("esplora", keys)
        keys2 = {q.key for q in describe_sources({"ESPLORA_URL": "https://mempool.example/api"})}
        self.assertNotIn("esplora", keys2)

    def test_bitcoin_core_rpc_in_einstellungen(self):
        """Lookup-Core und UTXO-Set-Slot — Felder und Geheimnis-Maske."""
        leer = {q.key: q for q in describe_sources({})}
        self.assertIn("own_core", leer)
        self.assertIn("own_utxo_core", leer)
        self.assertEqual(leer["own_utxo_core"].rank, 2)
        self.assertEqual(leer["own_core"].rank, 3)
        self.assertFalse(leer["own_core"].configured)
        self.assertIn("Tx/Block", leer["own_core"].note)
        self.assertIn("scantxoutset", leer["own_utxo_core"].note)

        werte = {
            "NODE_IP": "https://abcdefghijklmnop.onion",
            "RPCPORT": "443",
            "RPCUSER": "rpc",
            "RPCPASSWORD": "geheim-nicht-zeigen",
            "RPC_SSL": "true",
        }
        core = next(q for q in describe_sources(werte) if q.key == "own_core")
        self.assertTrue(core.configured)
        self.assertTrue(core.verwerfbar)
        pwd = next(f for f in core.felder if f.key == "RPCPASSWORD")
        self.assertEqual(pwd.typ, "geheim")
        self.assertEqual(pwd.value, "")
        self.assertTrue(pwd.gesetzt)
        self.assertIn("getrawtransaction", core.note)  # configured branch
        host = next(f for f in core.felder if f.key == "NODE_IP")
        self.assertTrue(host.value.endswith(".onion"))
        self.assertFalse(host.value.startswith("http"))

    def test_unkonfigurierter_eigener_node_bleibt_ungeprueft(self):
        quelle = next(q for q in describe_sources({}) if q.key == "own_fulcrum")
        self.assertFalse(quelle.configured)
        kopie = check_reachable(quelle, {})
        self.assertIsNone(kopie.reachable)
        self.assertEqual(kopie.error, "")

    def test_konfigurierter_eigener_node_meldet_fehler_statt_ausnahme(self):
        """Ohne erreichbaren Server muss reachable=False mit Text kommen."""
        werte = {"FULCRUM_HOST": "127.0.0.1", "FULCRUM_PORT": "1",
                 "FULCRUM_SSL": "0"}
        quelle = next(
            q for q in describe_sources(werte) if q.key == "own_fulcrum"
        )
        kopie = check_reachable(quelle, werte, timeout=1)
        self.assertFalse(kopie.reachable)
        self.assertTrue(kopie.error)

    def test_lan_braucht_kein_tor(self):
        fulcrum = next(
            q for q in describe_sources({"FULCRUM_HOST": "192.0.2.1"})
            if q.key == "own_fulcrum"
        )
        self.assertFalse(source_needs_tor(fulcrum, {"FULCRUM_HOST": "192.0.2.1"}))
        p2p = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertFalse(source_needs_tor(p2p, {}))

    def test_onion_braucht_tor(self):
        onion = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwxyz.onion"
        fulcrum = next(
            q for q in describe_sources({"FULCRUM_TOR": onion})
            if q.key == "own_fulcrum"
        )
        self.assertTrue(source_needs_tor(fulcrum, {"FULCRUM_TOR": onion}))
        p2p = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertTrue(source_needs_tor(
            p2p, {"FULCRUM_TOR_PROXY": "127.0.0.1:9050"},
        ))
        p2p_lan = next(
            q for q in describe_sources({"FULCRUM_HOST": "192.168.1.50"})
            if q.key == "bip158"
        )
        self.assertFalse(source_needs_tor(
            p2p_lan,
            {"FULCRUM_HOST": "192.168.1.50", "FULCRUM_TOR_PROXY": "127.0.0.1:9050"},
        ))

    def test_lan_host_schlaegt_onion_fuer_tor_bedarf(self):
        """check_reachable nimmt FULCRUM_HOST vor FULCRUM_TOR — dann kein SOCKS."""
        onion = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwxyz.onion"
        werte = {"FULCRUM_HOST": "192.0.2.1", "FULCRUM_TOR": onion}
        quelle = next(q for q in describe_sources(werte) if q.key == "own_fulcrum")
        self.assertFalse(source_needs_tor(quelle, werte))

    def test_erreichbares_lan_electrum_startet_kein_tor(self):
        from unittest import mock

        onion = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwxyz.onion"
        werte = {
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "false",
            "FULCRUM_TOR": onion,
        }
        with mock.patch(
            "core.fulcrum_client.connect_fulcrum", return_value=(object(), None)
        ), mock.patch("core.tor.stelle_tor_socks_bereit") as tor, mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[],
        ) as p2p:
            ergebnis = check_sources(describe_sources(werte), werte, timeout=1)
        tor.assert_not_called()
        p2p.assert_not_called()
        nach_key = {q.key: q for q in ergebnis}
        self.assertTrue(nach_key["own_fulcrum"].reachable)
        self.assertIn("electrs", peer_status(ergebnis)["label"])
        self.assertEqual(
            nach_key["bip158"].note,
            "P2P als Datenquelle nicht erforderlich (Electrs erreichbar).",
        )

    def test_p2p_hinweis_mit_electrs_und_core(self):
        from unittest import mock

        werte = {
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50001",
            "FULCRUM_SSL": "false",
            "NODE_IP": "192.0.2.20",
            "RPCPORT": "8332",
            "RPCUSER": "u",
            "RPCPASSWORD": "p",
        }
        core_client = mock.Mock()
        core_client.cfg.host = "192.0.2.20"
        with mock.patch(
            "core.fulcrum_client.connect_fulcrum", return_value=(object(), None)
        ), mock.patch(
            "core.bitcoind_rpc.stelle_core_client_bereit",
            return_value=core_client,
        ), mock.patch(
            "core.bitcoind_rpc.verify_core_rpc",
            return_value={"blocks": 800_000},
        ), mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[],
        ) as p2p:
            ergebnis = check_sources(describe_sources(werte), werte, timeout=1)
        p2p.assert_not_called()
        nach = {q.key: q for q in ergebnis}
        self.assertTrue(nach["own_fulcrum"].reachable)
        self.assertTrue(nach["own_core"].reachable)
        self.assertEqual(
            nach["bip158"].note,
            "P2P als Datenquelle nicht erforderlich; "
            "Header-Tip wird nur selten nachgezogen.",
        )

    def test_electrum_und_p2p_sind_verwerfbar(self):
        leer = {q.key: q for q in describe_sources({})}
        self.assertFalse(leer["own_fulcrum"].verwerfbar)
        # P2P ist standardmäßig an → Papierkorb sichtbar.
        self.assertTrue(leer["bip158"].verwerfbar)
        self.assertFalse(leer["public_onion"].verwerfbar)
        gesetzt = {q.key: q for q in describe_sources({
            "FULCRUM_HOST": "192.0.2.1",
        })}
        self.assertTrue(gesetzt["own_fulcrum"].verwerfbar)
        self.assertTrue(gesetzt["bip158"].verwerfbar)
        self.assertTrue(gesetzt["own_fulcrum"].as_dict()["verwerfbar"])
        aus = {q.key: q for q in describe_sources({"BIP158_P2P": "0"})}
        self.assertFalse(aus["bip158"].verwerfbar)
        self.assertFalse(aus["bip158"].configured)

    def test_p2p_bip158_ist_standard_konfiguriert(self):
        quelle = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertTrue(quelle.configured)
        self.assertEqual(quelle.name, "Bitcoin-P2P · Compact Filter")
        self.assertNotIn("NODE_IP", [f.key for f in quelle.felder])
        self.assertIn("DNS-Seeds", quelle.detail)
        # Kein Stift-Dialog — Start­höhe nur noch inline in der Zeile.
        self.assertFalse(quelle.editierbar)
        self.assertEqual(quelle.felder, [])
        self.assertEqual(quelle.start_height, 481824)

    def test_p2p_aus_zeigt_hinweis_auf_oeffentliche_listen(self):
        quelle = next(
            q for q in describe_sources({"BIP158_P2P": "false"}) if q.key == "bip158"
        )
        self.assertFalse(quelle.configured)
        self.assertIn("öffentliche Listen", quelle.detail)
        self.assertNotIn("BIP158_P2P", [f.key for f in quelle.felder])

    def test_p2p_nennt_node_im_lan_und_dns_fallback(self):
        quelle = next(
            q for q in describe_sources({"FULCRUM_HOST": "192.168.1.50"})
            if q.key == "bip158"
        )
        self.assertIn("Node im LAN 192.168.1.50", quelle.detail)
        self.assertIn("DNS-Seeds", quelle.detail)
        # Extra-Peers nur noch per .env — kein Stift-Feld mehr.
        self.assertNotIn("BIP158_PEERS", [f.key for f in quelle.felder])
        self.assertEqual(quelle.start_height, 481824)

    def test_p2p_pruefung_nutzt_lan_und_dns_fallback(self):
        from unittest import mock

        werte = {"FULCRUM_HOST": "192.168.1.50", "FULCRUM_PORT": "50001",
                 "FULCRUM_SSL": "false"}
        with mock.patch(
            "core.fulcrum_client.connect_fulcrum", return_value=(None, "timeout"),
        ), mock.patch(
            "core.p2p.zaehle_compact_filter_peers",
            return_value=["192.0.2.9:8333"],
        ) as zaehl:
            ergebnis = check_sources(describe_sources(werte), werte, timeout=1)
        nach = {q.key: q for q in ergebnis}
        self.assertFalse(nach["own_fulcrum"].reachable)
        self.assertEqual(nach["bip158"].peer_count, 1)
        kwargs = zaehl.call_args.kwargs
        self.assertEqual(kwargs["peers"], [("192.168.1.50", 8333)])
        self.assertTrue(kwargs["dns_fallback"])
        self.assertIsNone(kwargs.get("tor_proxy"))

    def test_verbindungstest_zaehlt_compact_filter_peers(self):
        with mock.patch(
            "core.p2p.zaehle_compact_filter_peers",
            return_value=["192.0.2.2:8333", "192.0.2.3:8333", "192.0.2.4:8333"],
        ) as zaehl, _ohne_live_p2p():
            ergebnis = check_sources(describe_sources({}), {}, timeout=1)
            nach = {q.key: q for q in ergebnis}
            self.assertEqual(nach["bip158"].peer_count, 3)
            self.assertTrue(nach["bip158"].reachable)
            zaehl.assert_called()
            self.assertEqual(nach["bip158"].as_dict()["peer_count"], 3)
            stand = peer_status(ergebnis)
        self.assertEqual(stand["kind"], "p2p")
        self.assertEqual(stand["label"], "3 Peers verbunden")

    def test_peer_status_peers_und_electrs_gemeinsam(self):
        from types import SimpleNamespace

        own = SimpleNamespace(
            key="own_fulcrum", reachable=True, peer_count=1, peer_hosts=["192.0.2.10"],
        )
        p2p = SimpleNamespace(
            key="bip158", reachable=True, peer_count=4, peer_hosts=["a", "b", "c", "d"],
        )
        pub = SimpleNamespace(key="public_onion", reachable=True, peer_count=7)
        with _ohne_live_p2p():
            stand = peer_status([own, p2p, pub])
        self.assertEqual(stand["label"], "4 Peers · 1 electrs verbunden")
        self.assertEqual(stand["kind"], "mixed")
        self.assertEqual(stand["peers_n"], 4)
        self.assertEqual(stand["electrs_n"], 1)

    def test_peer_status_nur_electrs(self):
        from types import SimpleNamespace

        own = SimpleNamespace(key="own_fulcrum", reachable=True, peer_count=1)
        p2p = SimpleNamespace(key="bip158", reachable=False, peer_count=0)
        with _ohne_live_p2p():
            stand = peer_status([own, p2p])
        self.assertEqual(stand["label"], "1 electrs verbunden")
        self.assertEqual(stand["kind"], "own")

    def test_peer_status_oeffentliche_electrum(self):
        from types import SimpleNamespace

        own = SimpleNamespace(key="own_fulcrum", reachable=False, peer_count=0)
        p2p = SimpleNamespace(key="bip158", reachable=False, peer_count=0)
        onion = SimpleNamespace(key="public_onion", reachable=True, peer_count=2)
        clear = SimpleNamespace(key="clearnet", reachable=True, peer_count=3)
        with _ohne_live_p2p():
            stand = peer_status([own, p2p, onion, clear])
        self.assertEqual(stand["kind"], "public")
        self.assertEqual(stand["count"], 5)
        self.assertEqual(
            stand["label"],
            "2 onion-electrs · 3 clearnet-electrs verbunden",
        )
        self.assertEqual(stand.get("onion_electrs"), 2)
        self.assertEqual(stand.get("clearnet_electrs"), 3)
        self.assertFalse(stand["braucht_oeffentliche"])

    def test_peer_status_fragt_oeffentliche_nur_ohne_bestaetigung(self):
        from types import SimpleNamespace

        own = SimpleNamespace(key="own_fulcrum", reachable=False, peer_count=0)
        p2p = SimpleNamespace(key="bip158", reachable=False, peer_count=0)
        werte = {"FULCRUM_TOR_0": "abc.onion"}
        with _ohne_live_p2p():
            stand = peer_status([own, p2p], werte)
            self.assertTrue(stand["braucht_oeffentliche"])
            self.assertFalse(oeffentliche_electrum_erlaubt(werte))
            stand = peer_status(
                [own, p2p], {**werte, "OEFFENTLICHE_ELECTRUM": "1"}
            )
            self.assertFalse(stand["braucht_oeffentliche"])
            own_ok = SimpleNamespace(key="own_fulcrum", reachable=True, peer_count=1)
            stand = peer_status([own_ok, p2p], werte)
        self.assertFalse(stand["braucht_oeffentliche"])

    def test_verbindungstest_fragt_oeffentliche_nicht_ohne_bestaetigung(self):
        from unittest import mock

        gesehen = []
        with mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[]
        ), mock.patch(
            "core.p2p.stelle_p2p_tor_bereit", return_value=None
        ), mock.patch(
            "core.source._pruefe_oeffentliche_electrum"
        ) as pruefe:
            check_sources(
                describe_sources({}), {}, timeout=1, on_log=gesehen.append,
            )
        pruefe.assert_not_called()
        self.assertTrue(any("Bestätigung fehlt" in z for z in gesehen))

    def test_p2p_ok_raeumt_oeffentliche_verbunden_stand(self):
        """Mit P2P-Peers kein stale „verbunden“ an Onion/Clearnet."""
        from unittest import mock

        from core.source import SourceInfo, PRIVACY_HIGH, PRIVACY_MEDIUM

        p2p = SourceInfo(
            rank=4, key="bip158", name="P2P", detail="", privacy=PRIVACY_HIGH,
            configured=True, reachable=True, peer_count=3,
            peer_hosts=["a:8333"],
        )
        onion = SourceInfo(
            rank=5, key="public_onion", name="Onion", detail="",
            privacy=PRIVACY_MEDIUM, configured=True, reachable=True,
            peer_count=2, peer_hosts=["x.onion:50002"],
        )
        clear = SourceInfo(
            rank=6, key="clearnet", name="Clear", detail="",
            privacy=PRIVACY_MEDIUM, configured=True, reachable=True,
            peer_count=1, peer_hosts=["e.example:50002"],
        )
        logs: list[str] = []
        with mock.patch(
            "core.source._pruefe_p2p_peers", return_value=p2p,
        ), mock.patch(
            "core.source._pruefe_oeffentliche_electrum",
        ) as pruefe_oeff:
            out = {
                q.key: q
                for q in check_sources(
                    [p2p, onion, clear], {}, timeout=1, on_log=logs.append,
                )
            }
        pruefe_oeff.assert_not_called()
        self.assertIsNone(out["public_onion"].reachable)
        self.assertEqual(out["public_onion"].peer_count, 0)
        self.assertIsNone(out["clearnet"].reachable)
        self.assertTrue(any("Öffentliche Electrum" in z for z in logs))

    def test_verbindungstest_fragt_oeffentliche_nach_bestaetigung(self):
        from unittest import mock

        with mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[]
        ), mock.patch(
            "core.p2p.stelle_p2p_tor_bereit", return_value=None
        ), mock.patch(
            "core.source._pruefe_oeffentliche_electrum",
            side_effect=lambda gefunden, *a, **k: gefunden,
        ) as pruefe:
            check_sources(
                describe_sources({}),
                {"OEFFENTLICHE_ELECTRUM": "1"},
                timeout=1,
            )
        pruefe.assert_called()

    def test_peer_aenderungen_p2p_host_rotation_stumm(self):
        """Probe-Hosts rotieren — bei gleichem Label kein Spam."""
        alt = {
            "kind": "p2p", "count": 2, "label": "2 Peers verbunden",
            "peers": ["192.0.2.1:8333", "192.0.2.2:8333"],
        }
        neu = {
            "kind": "p2p", "count": 2, "label": "2 Peers verbunden",
            "peers": ["192.0.2.2:8333", "192.0.2.3:8333"],
        }
        self.assertEqual(peer_aenderungen(alt, neu), [])

    def test_peer_aenderungen_zahl_wechselt(self):
        alt = {
            "kind": "mixed", "count": 3, "label": "2 Peers · 1 electrs verbunden",
            "peers": [],
        }
        neu = {
            "kind": "mixed", "count": 4, "label": "3 Peers · 1 electrs verbunden",
            "peers": [],
        }
        self.assertEqual(
            peer_aenderungen(alt, neu),
            ["Wechsel: 2 Peers · 1 electrs verbunden → 3 Peers · 1 electrs verbunden"],
        )

    def test_peer_aenderungen_kein_quatsch_peers_zu_onion(self):
        """Peers+electrs bleiben; nicht fälschlich nur onion-electrs."""
        alt = {
            "kind": "mixed", "count": 3, "label": "2 Peers · 1 electrs verbunden",
            "peers": [],
        }
        neu = {
            "kind": "mixed", "count": 3, "label": "2 Peers · 1 electrs verbunden",
            "peers": [],
        }
        self.assertEqual(peer_aenderungen(alt, neu), [])

    def test_peer_aenderungen_erster_stand_bleibt_stumm(self):
        neu = {
            "kind": "p2p", "count": 1, "label": "1 Peer verbunden",
            "peers": ["192.0.2.1:8333"],
        }
        self.assertEqual(peer_aenderungen(None, neu), [])

    def test_p2p_clearnet_ohne_peer_startet_tor(self):
        from unittest import mock

        gesehen = []
        aufrufe = {"n": 0}

        def zaehl(*, tor_proxy=None, **kwargs):
            aufrufe["n"] += 1
            if tor_proxy:
                return ["198.51.100.9:8333"]
            return []

        with mock.patch(
            "core.fulcrum_client.connect_fulcrum", return_value=(None, "timeout"),
        ), mock.patch(
            "core.p2p.zaehle_compact_filter_peers", side_effect=zaehl,
        ), mock.patch(
            "core.p2p.stelle_p2p_tor_bereit",
            return_value=("127.0.0.1", 9150),
        ) as tor:
            ergebnis = check_sources(
                describe_sources({}), {}, timeout=1, on_log=gesehen.append,
            )
        tor.assert_called_once()
        self.assertEqual(aufrufe["n"], 2)
        nach = {q.key: q for q in ergebnis}
        self.assertEqual(nach["bip158"].peer_hosts, ["198.51.100.9:8333"])
        self.assertTrue(nach["bip158"].reachable)
        self.assertTrue(
            any("versuche über Tor" in z for z in gesehen),
            gesehen,
        )

    def test_p2p_clearnet_mit_peer_startet_kein_tor(self):
        from unittest import mock

        with mock.patch(
            "core.p2p.zaehle_compact_filter_peers",
            return_value=["192.0.2.2:8333"],
        ), mock.patch("core.p2p.stelle_p2p_tor_bereit") as tor:
            ergebnis = check_sources(describe_sources({}), {}, timeout=1)
        tor.assert_not_called()
        nach = {q.key: q for q in ergebnis}
        self.assertEqual(nach["bip158"].peer_count, 1)

    def test_p2p_tor_fehlschlag_bleibt_ohne_peer(self):
        from unittest import mock

        gesehen = []
        with mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[]
        ), mock.patch(
            "core.p2p.stelle_p2p_tor_bereit", return_value=None,
        ) as tor:
            ergebnis = check_sources(
                describe_sources({}), {}, timeout=1, on_log=gesehen.append,
            )
        tor.assert_called_once()
        nach = {q.key: q for q in ergebnis}
        self.assertFalse(nach["bip158"].reachable)
        self.assertEqual(nach["bip158"].error, "kein Compact-Filter-Peer")

    def test_peer_status_keiner(self):
        from types import SimpleNamespace

        with _ohne_live_p2p():
            stand = peer_status([
                SimpleNamespace(key="own_fulcrum", reachable=False, peer_count=0),
                SimpleNamespace(key="bip158", reachable=False, peer_count=0),
            ])
        self.assertEqual(stand["label"], "0 Peers verbunden")

    def test_mergere_erreichbarkeit_uebernimmt_letzten_check(self):
        frisch = describe_sources({
            "FULCRUM_HOST": "192.0.2.10",
            "FULCRUM_PORT": "50002",
        })
        alt = [
            {
                "key": "own_fulcrum",
                "reachable": True,
                "error": "",
                "peer_count": 1,
                "peer_hosts": ["192.0.2.10:50002"],
            },
        ]
        gemerged = mergere_erreichbarkeit(frisch, alt)
        nach = {q.key: q for q in gemerged}
        self.assertTrue(nach["own_fulcrum"].configured)
        self.assertTrue(nach["own_fulcrum"].reachable)
        self.assertEqual(nach["own_fulcrum"].peer_count, 1)


class TestOeffentlicheClearnetVorOnion(unittest.TestCase):
    """Nach Opt-in: Clearnet zuerst; Onions/Tor nur wenn Clearnet fehlt."""

    def test_clearnet_treffer_probt_keine_onions(self):
        from core import source as source_mod
        from core.source import SourceInfo, PRIVACY_MEDIUM

        gefunden = {
            "public_onion": SourceInfo(
                rank=5, key="public_onion", name="Onion", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
            "clearnet": SourceInfo(
                rank=6, key="clearnet", name="Clear", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
        }
        values = {"FULCRUM_TOR_0": "abc.onion", "OEFFENTLICHE_ELECTRUM": "1"}
        logs: list[str] = []

        with mock.patch.object(
            source_mod, "_zaehle_electrum_endpunkte",
            side_effect=lambda endpunkte, **kw: (
                ["1.2.3.4:50002"] if endpunkte and not str(endpunkte[0][0]).endswith(".onion")
                else (_ for _ in ()).throw(AssertionError("Onion darf nicht geprobt werden"))
            ),
        ), mock.patch.object(
            source_mod, "splitte_electrum_server",
            return_value=([], [("1.2.3.4", 50002, True)] * 3),
        ), mock.patch(
            "core.electrum_servers.load_electrum_servers", return_value={},
        ), mock.patch.object(
            source_mod, "_loese_oeffentliches_onion_tor",
        ) as loese:
            out = source_mod._pruefe_oeffentliche_electrum(
                gefunden, values, timeout=1, on_log=logs.append,
            )
        self.assertEqual(out["clearnet"].peer_count, 1)
        self.assertEqual(out["public_onion"].peer_count, 0)
        self.assertIsNone(out["public_onion"].reachable)
        loese.assert_called_once()
        self.assertTrue(any("Clearnet" in z for z in logs))


class TestOeffentlicheElectrumStichprobe(unittest.TestCase):
    """Clearnet-Probe darf nicht an den ersten 8 alphabetischen IPs hängen."""

    def test_stichprobe_nicht_nur_prefix(self):
        from core import source as source_mod

        endpunkte = [(f"h{i}.example", 50002, True) for i in range(30)]
        gesehen = set()
        for _ in range(40):
            stich = source_mod._waehle_electrum_stichprobe(endpunkte, 8)
            self.assertEqual(len(stich), 8)
            gesehen.update(h for h, _p, _s in stich)
        # Bei echter Zufallsstichprobe tauchen auch hintere Hosts auf.
        self.assertGreater(len(gesehen), 8)
        self.assertTrue(any(h.startswith("h2") for h in gesehen), gesehen)

    def test_zweite_runde_wenn_erste_tot(self):
        from core import source as source_mod

        tot = [(f"dead{i}.example", 50002, True) for i in range(8)]
        gut = [("alive.example", 50002, True)]
        endpunkte = tot + gut
        logs: list[str] = []

        def fake_connect(host, port, use_ssl=True, timeout=8, tor_proxy=None,
                         require_listunspent=False):
            if host == "alive.example":
                class _C:
                    def close(self):
                        return None
                return _C(), None
            return None, "timed out"

        with mock.patch("core.fulcrum_client.connect_fulcrum", side_effect=fake_connect):
            with mock.patch.object(
                source_mod.random, "sample",
                side_effect=[list(tot), list(gut)],
            ):
                treffer = source_mod._zaehle_electrum_endpunkte(
                    endpunkte, timeout=5, tor_proxy=None,
                    on_log=logs.append, limit=8, max_runden=2,
                )
        self.assertEqual(treffer, ["alive.example:50002"])
        self.assertTrue(any("weitere" in z for z in logs), logs)


if __name__ == "__main__":
    unittest.main()
