"""
Core-RPC-Allowlist (Dealbreaker T14) — Laufzeit.

Jeder Aufruf läuft durch ``BitcoinRpcClient.call``. Nicht erlaubte Methoden
werden vor Payload/Auth/Socket blockiert, setzen ein Prozess-Flag und dürfen
nirgends in einen stillen Fallback (Electrum, P2P, „nicht erreichbar“) fallen.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import bitcoind_rpc as rpc
from core.bitcoind_rpc import (
    ALLE_RPC_METHODEN,
    ERLAUBTE_RPC_METHODEN,
    RPC_KERN,
    RPC_LAB_REGTEST,
    RPC_WALLET_IMPORT,
    BitcoinRpcClient,
    CoreRpcConfig,
    RpcAllowlistError,
    RpcVerweigertError,
    pruefe_rpc_methode,
    rpc_allowlist_status,
    setze_rpc_allowlist_status_zurueck,
)
from core.outbound_policy import OutboundPolicyError

_TXID = "ab" * 32


def _cfg(**kw) -> CoreRpcConfig:
    werte = dict(
        host="127.0.0.1", port=18443, user="u", password="p", use_ssl=False,
    )
    werte.update(kw)
    return CoreRpcConfig(**werte)


class _FakeSock:
    """Minimaler Socket: nimmt den Request, liefert eine feste HTTP-Antwort."""

    def __init__(self, antwort: bytes):
        self.gesendet = b""
        self._antwort = [antwort]

    def settimeout(self, _t):
        pass

    def sendall(self, data: bytes):
        self.gesendet += data

    def recv(self, _n: int) -> bytes:
        return self._antwort.pop(0) if self._antwort else b""

    def close(self):
        pass

    def payload(self) -> dict:
        _kopf, _, body = self.gesendet.partition(b"\r\n\r\n")
        return json.loads(body.decode("utf-8"))


def _http(status: str, body: bytes) -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode("ascii") + body


def _ok(result) -> bytes:
    return _http("200 OK", json.dumps({"result": result, "error": None, "id": 1}).encode())


class _Basis(unittest.TestCase):
    def setUp(self):
        setze_rpc_allowlist_status_zurueck()
        self.addCleanup(setze_rpc_allowlist_status_zurueck)


class TestAllowlistKonstanten(unittest.TestCase):
    def test_gruppen(self):
        self.assertEqual(
            set(RPC_KERN),
            {"getblockchaininfo", "getblockhash", "getblockheader", "getblock",
             "getrawtransaction", "scantxoutset"},
        )
        self.assertEqual(
            set(RPC_WALLET_IMPORT),
            {"listwallets", "listwalletdir", "loadwallet", "listdescriptors"},
        )
        self.assertEqual(set(RPC_LAB_REGTEST), {"sendtoaddress"})
        self.assertEqual(ERLAUBTE_RPC_METHODEN, set(RPC_KERN) | set(RPC_WALLET_IMPORT))
        self.assertEqual(ALLE_RPC_METHODEN, ERLAUBTE_RPC_METHODEN | {"sendtoaddress"})

    def test_keine_schreibenden_oder_signierenden_methoden(self):
        verboten = {
            "sendrawtransaction", "signrawtransactionwithwallet", "walletprocesspsbt",
            "dumpprivkey", "dumpwallet", "importdescriptors", "importprivkey",
            "createwallet", "unloadwallet", "sendmany", "stop", "generatetoaddress",
            "setban", "addnode", "walletpassphrase", "encryptwallet", "backupwallet",
        }
        self.assertFalse(verboten & ALLE_RPC_METHODEN)

    def test_exception_ist_outbound_policy_error(self):
        self.assertTrue(issubclass(RpcAllowlistError, OutboundPolicyError))


class TestPruefung(_Basis):
    def test_verbotene_methode_ohne_socket(self):
        client = BitcoinRpcClient(_cfg())
        with patch.object(rpc.socket, "create_connection") as conn, \
                patch.object(rpc, "_socks5_connect") as socks:
            with self.assertLogs("satsage.rpc", level="ERROR") as logs:
                with self.assertRaises(RpcAllowlistError) as ctx:
                    client.call("stop")
            conn.assert_not_called()
            socks.assert_not_called()
        self.assertEqual(ctx.exception.method, "stop")
        self.assertIn("RPC-ALLOWLIST-VERSTOSS method=stop", "\n".join(logs.output))
        self.assertEqual(client._id, 0, "kein Payload gebaut")

    def test_erlaubte_methoden_gehen_durch(self):
        for methode in sorted(ERLAUBTE_RPC_METHODEN):
            with self.subTest(methode=methode):
                sock = _FakeSock(_ok({"ok": methode}))
                client = BitcoinRpcClient(_cfg())
                with patch.object(rpc.socket, "create_connection", return_value=sock):
                    ergebnis = client.call(methode)
                self.assertEqual(ergebnis, {"ok": methode})
                self.assertEqual(sock.payload()["method"], methode)
        self.assertFalse(rpc_allowlist_status()["verstoss"])

    def test_listdescriptors_nur_ohne_private(self):
        pruefe_rpc_methode("listdescriptors", None)
        pruefe_rpc_methode("listdescriptors", [])
        pruefe_rpc_methode("listdescriptors", [False])
        for params in ([True], ["true"], [1], [0], [False, True]):
            with self.subTest(params=params):
                with self.assertLogs("satsage.rpc", level="ERROR"):
                    with self.assertRaises(RpcAllowlistError):
                        pruefe_rpc_methode("listdescriptors", params)
        self.assertTrue(rpc_allowlist_status()["verstoss"])

    def test_listdescriptors_true_ohne_socket(self):
        client = BitcoinRpcClient(_cfg(wallet="w"))
        with patch.object(rpc.socket, "create_connection") as conn:
            with self.assertLogs("satsage.rpc", level="ERROR"):
                with self.assertRaises(RpcAllowlistError):
                    client.call("listdescriptors", [True])
            conn.assert_not_called()

    def test_sendtoaddress_nur_regtest(self):
        for netz in (None, "", "main", "test", "signet"):
            with self.subTest(netz=netz):
                client = BitcoinRpcClient(_cfg(network=netz))
                with patch.object(rpc.socket, "create_connection") as conn:
                    with self.assertLogs("satsage.rpc", level="ERROR"):
                        with self.assertRaises(RpcAllowlistError):
                            client.call("sendtoaddress", ["bcrt1qx", 0.001])
                    conn.assert_not_called()
        for netz in ("regtest", "reg", "REGTEST"):
            with self.subTest(netz=netz):
                sock = _FakeSock(_ok(_TXID))
                client = BitcoinRpcClient(_cfg(network=netz, wallet="lab-faucet"))
                with patch.object(rpc.socket, "create_connection", return_value=sock):
                    self.assertEqual(client.call("sendtoaddress", ["bcrt1qx", 0.001]), _TXID)

    def test_network_kommt_aus_env(self):
        env = {"NODE_IP": "127.0.0.1", "RPCUSER": "u", "RPCPASSWORD": "p",
               "NETWORK": "regtest"}
        self.assertEqual(rpc.config_from_env(env).network, "regtest")
        env["NETWORK"] = ""
        self.assertIsNone(rpc.config_from_env(env).network)

    def test_kein_methodenname(self):
        for m in (None, "", 7):
            with self.subTest(m=m):
                with self.assertLogs("satsage.rpc", level="ERROR"):
                    with self.assertRaises(RpcAllowlistError):
                        pruefe_rpc_methode(m, [])

    def test_flag_und_status(self):
        self.assertEqual(rpc_allowlist_status(), {"verstoss": False, "anzahl": 0, "letzter": None})
        with self.assertLogs("satsage.rpc", level="ERROR"):
            with self.assertRaises(RpcAllowlistError):
                pruefe_rpc_methode("dumpwallet", ["/tmp/x"])
        stand = rpc_allowlist_status()
        self.assertTrue(stand["verstoss"])
        self.assertEqual(stand["anzahl"], 1)
        self.assertEqual(stand["letzter"]["method"], "dumpwallet")
        self.assertIn("Allowlist", stand["letzter"]["grund"])


class TestHttpStatus(_Basis):
    def test_403_leer_klare_meldung(self):
        sock = _FakeSock(_http("403 Forbidden", b""))
        client = BitcoinRpcClient(_cfg())
        with patch.object(rpc.socket, "create_connection", return_value=sock):
            with self.assertLogs("satsage.rpc", level="WARNING"):
                with self.assertRaises(RpcVerweigertError) as ctx:
                    client.call("scantxoutset", ["status"])
        text = str(ctx.exception)
        self.assertIn("Node verweigert Methode scantxoutset", text)
        self.assertIn("rpcwhitelist", text)
        # Node-Ablehnung ist kein SatSage-Verstoß → kein Dealbreaker-Flag.
        self.assertFalse(rpc_allowlist_status()["verstoss"])
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_401_leer_klare_meldung(self):
        sock = _FakeSock(_http("401 Unauthorized", b""))
        client = BitcoinRpcClient(_cfg())
        with patch.object(rpc.socket, "create_connection", return_value=sock):
            with self.assertRaises(ConnectionError) as ctx:
                client.call("getblockchaininfo")
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_rpc_fehler_mit_body_bleibt(self):
        body = json.dumps({"result": None, "error": {"code": -5, "message": "No such tx"}}).encode()
        sock = _FakeSock(_http("500 Internal Server Error", body))
        client = BitcoinRpcClient(_cfg())
        with patch.object(rpc.socket, "create_connection", return_value=sock):
            with self.assertRaises(RuntimeError) as ctx:
                client.call("getrawtransaction", [_TXID, True])
        self.assertIn("Fehler -5", str(ctx.exception))


def _verstoss_client(cfg=None):
    """Client-Double, dessen call wie ein Allowlist-Verstoß wirft."""
    def call(method, params=None):
        raise RpcAllowlistError(method, "Test")
    return SimpleNamespace(cfg=cfg or _cfg(), timeout=5.0, call=MagicMock(side_effect=call))


class TestKeinStillesAusweichen(_Basis):
    def test_try_scantxoutset_wirft(self):
        client = _verstoss_client()
        with patch.object(rpc, "stelle_utxo_core_client_bereit", return_value=client):
            with self.assertRaises(RpcAllowlistError):
                rpc.try_scantxoutset_for_xpubs({}, ["xpub-dummy"])

    def test_scantxoutset_abort_wirft(self):
        client = _verstoss_client()
        with patch.object(rpc, "descriptors_for_key", return_value=[{"desc": "d", "range": [0, 1]}]):
            with self.assertRaises(RpcAllowlistError):
                rpc.scantxoutset_utxos(client, ["k"], status_client=_verstoss_client())

    def test_fetch_tx_mit_rollen_wirft(self):
        with self.assertRaises(RpcAllowlistError):
            rpc.fetch_tx_core_mit_rollen(
                _TXID, local=_verstoss_client(), archival=_verstoss_client(), height=100,
            )

    def test_pruneheight_wirft(self):
        with self.assertRaises(RpcAllowlistError):
            rpc.pruneheight_of(_verstoss_client())

    def test_normalize_core_tx_wirft(self):
        with self.assertRaises(RpcAllowlistError):
            rpc.normalize_core_tx(
                {"txid": _TXID, "vin": [], "vout": [], "blockhash": "00" * 32},
                _verstoss_client(),
            )

    def test_bip158_fallback_weicht_nicht_auf_p2p_aus(self):
        from core import bip158_wallet

        with patch.object(bip158_wallet, "fetch_tx_p2p") as p2p:
            with self.assertRaises(RpcAllowlistError):
                bip158_wallet.fetch_tx_p2p_mit_fallback(
                    MagicMock(), _TXID, core_client=_verstoss_client(),
                )
            p2p.assert_not_called()
            with self.assertRaises(RpcAllowlistError):
                bip158_wallet.fetch_tx_p2p_mit_fallback(
                    MagicMock(), _TXID, archival_core=_verstoss_client(),
                )
            p2p.assert_not_called()

    def test_local_bitcoind_probe_wirft(self):
        from core import local_bitcoind

        with patch.object(BitcoinRpcClient, "call", side_effect=RpcAllowlistError("x", "Test")):
            with self.assertRaises(RpcAllowlistError):
                local_bitcoind._probe_rpc("127.0.0.1", 8332, "u", "p")

    def test_schatzsuche_probe_wirft(self):
        from core import schatzsuche

        with patch.object(rpc, "stelle_utxo_core_client_bereit", return_value=_verstoss_client()):
            with self.assertRaises(RpcAllowlistError):
                schatzsuche.core_fuer_scantxoutset({})

    def test_wallet_sync_scantxoutset_wirft(self):
        from core import wallet_sync_engine as eng

        with patch.object(eng, "_load_dotenv", return_value={}), \
                patch.object(eng, "_utxo_scan_scantxoutset_vorrang", return_value=True), \
                patch.object(rpc, "try_scantxoutset_for_xpubs",
                             side_effect=RpcAllowlistError("scantxoutset", "Test")):
            with self.assertRaises(RpcAllowlistError):
                eng._try_scantxoutset_xpub("xpub-dummy", Path("/nonexistent"), 10)

    def test_wallet_suche_wirft(self):
        from core import wallet_discover

        env = {"NODE_IP": "127.0.0.1", "RPCUSER": "u", "RPCPASSWORD": "p"}
        with patch.object(rpc, "BitcoinRpcClient", return_value=_verstoss_client()):
            with self.assertRaises(RpcAllowlistError):
                wallet_discover.suche_core_rpc_wallets(env=env)
            with self.assertRaises(RpcAllowlistError):
                wallet_discover.importiere_core_rpc_wallet("corerpc:w", env=env)

    def test_wallet_suche_disablewallet_klar(self):
        from core import wallet_discover

        env = {"NODE_IP": "127.0.0.1", "RPCUSER": "u", "RPCPASSWORD": "p"}
        client = SimpleNamespace(
            cfg=_cfg(),
            call=MagicMock(side_effect=RuntimeError("RPC listwallets Fehler -32601: Method not found")),
        )
        logs: list[str] = []
        with patch.object(rpc, "BitcoinRpcClient", return_value=client):
            out = wallet_discover.suche_core_rpc_wallets(env=env, on_log=logs.append)
        self.assertEqual(out, [])
        self.assertTrue(any("disablewallet" in z for z in logs), logs)
        self.assertFalse(any("nicht erreichbar" in z for z in logs), logs)

    def test_wallet_suche_403_klar(self):
        from core import wallet_discover

        env = {"NODE_IP": "127.0.0.1", "RPCUSER": "u", "RPCPASSWORD": "p"}
        client = SimpleNamespace(cfg=_cfg(), call=MagicMock(side_effect=RpcVerweigertError("listwallets")))
        logs: list[str] = []
        with patch.object(rpc, "BitcoinRpcClient", return_value=client):
            wallet_discover.suche_core_rpc_wallets(env=env, on_log=logs.append)
        self.assertTrue(any("rpcwhitelist" in z for z in logs), logs)


class TestStatusSichtbar(_Basis):
    def test_health_zeigt_nur_flag(self):
        from httpserver.api.health import api_health

        state = SimpleNamespace(managed_by=None)
        self.assertFalse(api_health(state)["rpc_allowlist_verstoss"])
        with self.assertLogs("satsage.rpc", level="ERROR"):
            with self.assertRaises(RpcAllowlistError):
                pruefe_rpc_methode("stop")
        antwort = api_health(state)
        self.assertTrue(antwort["rpc_allowlist_verstoss"])
        self.assertNotIn("stop", json.dumps(antwort), "Health ohne Login: keine Details")

    def test_config_und_quellenstatus_liefern_flag(self):
        from httpserver.api import config_ui

        with self.assertLogs("satsage.rpc", level="ERROR"):
            with self.assertRaises(RpcAllowlistError):
                pruefe_rpc_methode("importprivkey")
        stand = config_ui._rpc_allowlist_status_for_api()
        self.assertTrue(stand["verstoss"])
        self.assertEqual(stand["letzter"]["method"], "importprivkey")
        quelle = Path(__file__).resolve().parents[1] / "httpserver" / "api" / "source.py"
        self.assertIn('"rpc_allowlist": rpc_allowlist_status()', quelle.read_text(encoding="utf-8"))

    def test_server_meldet_verstoss_als_403(self):
        quelle = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        self.assertIn("isinstance(exc, RpcAllowlistError)", quelle)
        self.assertIn("self._fehler(403, str(exc))", quelle)

    def test_web_zeigt_pille(self):
        wurzel = Path(__file__).resolve().parents[1] / "web"
        app = (wurzel / "app.js").read_text(encoding="utf-8")
        self.assertIn("function zeichneRpcSperrePille()", app)
        self.assertIn("nimmRpcAllowlist(ergebnis.rpc_allowlist)", app)
        self.assertIn('t("header.rpcBlocked")', app)
        for lang in ("de", "en"):
            daten = json.loads((wurzel / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for key in ("header.rpcBlocked", "header.rpcBlockedTitle", "header.rpcBlockedLog"):
                self.assertTrue(daten.get(key), (lang, key))
            self.assertIn("{methode}", daten["header.rpcBlockedTitle"])


if __name__ == "__main__":
    unittest.main()
