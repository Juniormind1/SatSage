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
        ), mock.patch("fulcrum.connect_fulcrum", return_value=(None, "timeout")) as cf:
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
        with mock.patch("fulcrum.connect_fulcrum", return_value=(None, "timeout")):
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
        with mock.patch("fulcrum.connect_fulcrum", return_value=(None, "timeout")):
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

    def test_esplora_ist_keine_quelle_mehr(self):
        """Esplora entfällt — P2P und Electrum reichen."""
        keys = {q.key for q in describe_sources({})}
        self.assertNotIn("esplora", keys)
        keys2 = {q.key for q in describe_sources({"ESPLORA_URL": "https://mempool.example/api"})}
        self.assertNotIn("esplora", keys2)

    def test_bitcoin_core_rpc_in_einstellungen(self):
        """Core für schnelleren UTXO-Scan — Felder und Geheimnis-Maske."""
        leer = {q.key: q for q in describe_sources({})}
        self.assertIn("own_core", leer)
        self.assertEqual(leer["own_core"].rank, 2)
        self.assertFalse(leer["own_core"].configured)
        self.assertIn("scantxoutset", leer["own_core"].note)

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
        self.assertIn("scantxoutset", core.note)
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
            "fulcrum.connect_fulcrum", return_value=(object(), None)
        ), mock.patch("core.tor.stelle_tor_socks_bereit") as tor, mock.patch(
            "core.p2p.zaehle_compact_filter_peers", return_value=[],
        ) as p2p:
            ergebnis = check_sources(describe_sources(werte), werte, timeout=1)
        tor.assert_not_called()
        p2p.assert_not_called()
        nach_key = {q.key: q for q in ergebnis}
        self.assertTrue(nach_key["own_fulcrum"].reachable)
        self.assertEqual(peer_status(ergebnis)["label"], "Eigener Peer verbunden")
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
            "fulcrum.connect_fulcrum", return_value=(object(), None)
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

    def test_nur_electrum_ist_verwerfbar(self):
        leer = {q.key: q for q in describe_sources({})}
        self.assertFalse(leer["own_fulcrum"].verwerfbar)
        self.assertFalse(leer["bip158"].verwerfbar)
        self.assertFalse(leer["public_onion"].verwerfbar)
        gesetzt = {q.key: q for q in describe_sources({
            "FULCRUM_HOST": "192.0.2.1",
        })}
        self.assertTrue(gesetzt["own_fulcrum"].verwerfbar)
        self.assertFalse(gesetzt["bip158"].verwerfbar)
        self.assertTrue(gesetzt["own_fulcrum"].as_dict()["verwerfbar"])

    def test_p2p_bip158_ist_standard_konfiguriert(self):
        quelle = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertTrue(quelle.configured)
        self.assertEqual(quelle.name, "Bitcoin-P2P · Compact Filter")
        self.assertNotIn("NODE_IP", [f.key for f in quelle.felder])
        self.assertIn("DNS-Seeds", quelle.detail)

    def test_p2p_nennt_node_im_lan_und_dns_fallback(self):
        quelle = next(
            q for q in describe_sources({"FULCRUM_HOST": "192.168.1.50"})
            if q.key == "bip158"
        )
        self.assertIn("Node im LAN 192.168.1.50", quelle.detail)
        self.assertIn("DNS-Seeds", quelle.detail)
        hinweis = next(f for f in quelle.felder if f.key == "BIP158_PEERS").hinweis
        self.assertIn("Host im LAN", hinweis)

    def test_p2p_pruefung_nutzt_lan_und_dns_fallback(self):
        from unittest import mock

        werte = {"FULCRUM_HOST": "192.168.1.50", "FULCRUM_PORT": "50001",
                 "FULCRUM_SSL": "false"}
        with mock.patch(
            "fulcrum.connect_fulcrum", return_value=(None, "timeout"),
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

    def test_peer_status_eigener_electrum_sticht_p2p(self):
        from types import SimpleNamespace

        own = SimpleNamespace(key="own_fulcrum", reachable=True, peer_count=1)
        p2p = SimpleNamespace(key="bip158", reachable=True, peer_count=4)
        pub = SimpleNamespace(key="public_onion", reachable=True, peer_count=7)
        with _ohne_live_p2p():
            stand = peer_status([own, p2p, pub])
        self.assertEqual(stand["label"], "Eigener Peer verbunden")
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
        self.assertEqual(stand["label"], "5 öffentliche Peers verbunden")
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

    def test_peer_aenderungen_ausfall_und_zugang(self):
        alt = {
            "kind": "p2p", "count": 2, "label": "2 Peers verbunden",
            "peers": ["192.0.2.1:8333", "192.0.2.2:8333"],
        }
        neu = {
            "kind": "p2p", "count": 2, "label": "2 Peers verbunden",
            "peers": ["192.0.2.2:8333", "192.0.2.3:8333"],
        }
        zeilen = peer_aenderungen(alt, neu)
        self.assertEqual(
            zeilen,
            [
                "Peer 192.0.2.1:8333 ausgefallen.",
                "Neuer Peer 192.0.2.3:8333.",
            ],
        )

    def test_peer_aenderungen_sorte_wechselt(self):
        alt = {
            "kind": "own", "count": 1, "label": "Eigener Peer verbunden",
            "peers": ["192.0.2.10:50001"],
        }
        neu = {
            "kind": "p2p", "count": 2, "label": "2 Peers verbunden",
            "peers": ["192.0.2.1:8333", "192.0.2.2:8333"],
        }
        self.assertEqual(
            peer_aenderungen(alt, neu),
            ["Wechsel: Eigener Peer verbunden → 2 Peers verbunden"],
        )

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
            "fulcrum.connect_fulcrum", return_value=(None, "timeout"),
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
            any("versuche über Tor" in z for z in gesehen), gesehen
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
        self.assertEqual(stand["count"], 0)


if __name__ == "__main__":
    unittest.main()
