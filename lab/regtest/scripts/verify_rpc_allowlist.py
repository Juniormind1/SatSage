#!/usr/bin/env python3
"""Regtest: Client-Allowlist und die Node-Hinweise dazu.

Harte Regel (Dealbreaker Q6): jeder Pull Request nach main. Der Labor-Node
hat den User ``satsage`` (Passwort ``lab-whitelist``) mit ``rpcwhitelist``
nur für die Lese-Methoden. ``bitcoin``/``secret`` bleibt offen, sonst
brechen Electrs und die Szenarien. Ein zweiter Node auf Port 18445 läuft
mit ``disablewallet``.

Der Client muss ``dumpwallet`` verwerfen, bevor ein Socket aufgeht.
``listwallets`` am Whitelist-User liefert den Hinweis „rpcwhitelist?“.
``listwallets`` am Node ohne Wallet liefert „disablewallet?“.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from core.bitcoind_rpc import (  # noqa: E402
    BitcoinRpcClient,
    CoreRpcConfig,
    RpcAllowlistError,
    RpcVerweigertError,
    rpc_allowlist_status,
    setze_rpc_allowlist_status_zurueck,
)
from core.wallet_discover import suche_core_rpc_wallets  # noqa: E402
import core.bitcoind_rpc as rpc_mod  # noqa: E402

HOST = "127.0.0.1"
PORT_OFFEN = 18443
PORT_OHNE_WALLET = 18445
USER_OFFEN = "bitcoin"
PASS_OFFEN = "secret"
USER_LISTE = "satsage"
PASS_LISTE = "lab-whitelist"


def _client(user: str, password: str, port: int, network: str = "regtest") -> BitcoinRpcClient:
    return BitcoinRpcClient(
        CoreRpcConfig(
            host=HOST,
            port=port,
            user=user,
            password=password,
            use_ssl=False,
            network=network,
        ),
        timeout=20.0,
    )


def _port_offen(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), 1.0):
            return True
    except OSError:
        return False


def _warte(port: int, sekunden: int = 60) -> None:
    for _ in range(sekunden):
        if _port_offen(port):
            return
        time.sleep(1)
    raise SystemExit(f"Nichts hört auf {HOST}:{port}.")


def _nowallet_holen() -> None:
    if _port_offen(PORT_OHNE_WALLET):
        return
    compose = HERE / "docker-compose.yml"
    if not compose.is_file():
        raise SystemExit("bitcoind ohne Wallet fehlt, und es gibt kein docker-compose.yml.")
    print("Starte bitcoind-nowallet…")
    subprocess.run(
        ["docker", "compose", "-f", str(compose), "up", "-d", "bitcoind-nowallet"],
        check=True,
        cwd=HERE,
    )
    _warte(PORT_OHNE_WALLET)


def _ohne_socket(aktion) -> None:
    """Die Aktion darf keinen RPC-Socket öffnen."""
    echt = rpc_mod.socket.create_connection
    getroffen = {"n": 0}

    def wrapper(*args, **kwargs):
        getroffen["n"] += 1
        return echt(*args, **kwargs)

    rpc_mod.socket.create_connection = wrapper
    try:
        aktion()
    finally:
        rpc_mod.socket.create_connection = echt
    if getroffen["n"]:
        raise SystemExit(f"Allowlist hat trotzdem verbunden ({getroffen['n']}×).")


def _blockiert(method: str, params: list | None, *, user: str, password: str, network: str) -> None:
    setze_rpc_allowlist_status_zurueck()
    client = _client(user, password, PORT_OFFEN, network)
    gesehen: list[BaseException] = []

    def aktion() -> None:
        try:
            client.call(method, params or [])
        except RpcAllowlistError as exc:
            if method not in str(exc):
                raise SystemExit(f"Allowlist-Text ohne Methodenname: {exc}")
            gesehen.append(exc)
            return
        raise SystemExit(f"{method} wurde nicht von der Allowlist gestoppt.")

    _ohne_socket(aktion)
    if not gesehen:
        raise SystemExit(f"{method}: kein Allowlist-Fehler.")
    stand = rpc_allowlist_status()
    if not stand["verstoss"]:
        raise SystemExit(f"{method}: Prozess-Flag blieb leer.")
    print(f"  Allowlist stoppt {method} ({network}, {user}), Node unberührt")


def _kette(user: str, password: str) -> None:
    info = _client(user, password, PORT_OFFEN).call("getblockchaininfo")
    kette = str((info or {}).get("chain") or "")
    if kette != "regtest":
        raise SystemExit(f"{user}: Kette ist {kette!r}, erwartet regtest.")
    print(f"  getblockchaininfo als {user}: regtest")


def _whitelist_verweigert() -> None:
    client = _client(USER_LISTE, PASS_LISTE, PORT_OFFEN)
    try:
        client.call("listwallets")
    except RpcVerweigertError as exc:
        text = str(exc)
        if "listwallets" not in text or "rpcwhitelist" not in text:
            raise SystemExit(f"Hinweis unklar: {text}")
    else:
        raise SystemExit("listwallets lief trotz rpcwhitelist durch.")
    logs: list[str] = []
    suche_core_rpc_wallets(
        env={
            "NODE_IP": HOST,
            "RPCPORT": str(PORT_OFFEN),
            "RPCUSER": USER_LISTE,
            "RPCPASSWORD": PASS_LISTE,
            "NETWORK": "regtest",
        },
        on_log=logs.append,
    )
    if not any("rpcwhitelist" in zeile for zeile in logs):
        raise SystemExit(f"Wallet-Suche ohne rpcwhitelist-Hinweis: {logs}")
    print("  listwallets als satsage: Hinweis rpcwhitelist")


def _ohne_wallet() -> None:
    client = _client(USER_OFFEN, PASS_OFFEN, PORT_OHNE_WALLET)
    try:
        client.call("listwallets")
    except RuntimeError as exc:
        if "-32601" not in str(exc):
            raise SystemExit(f"disablewallet-Node anders als -32601: {exc}")
    else:
        raise SystemExit("listwallets lief auf dem Node ohne Wallet.")
    logs: list[str] = []
    suche_core_rpc_wallets(
        env={
            "NODE_IP": HOST,
            "RPCPORT": str(PORT_OHNE_WALLET),
            "RPCUSER": USER_OFFEN,
            "RPCPASSWORD": PASS_OFFEN,
            "NETWORK": "regtest",
        },
        on_log=logs.append,
    )
    if not any("disablewallet" in zeile for zeile in logs):
        raise SystemExit(f"Wallet-Suche ohne disablewallet-Hinweis: {logs}")
    print("  listwallets ohne Wallet: Hinweis disablewallet")


def _offen_darf_listwallets() -> None:
    namen = _client(USER_OFFEN, PASS_OFFEN, PORT_OFFEN).call("listwallets")
    if not isinstance(namen, list):
        raise SystemExit(f"bitcoin/secret listwallets keine Liste: {namen!r}")
    print(f"  listwallets als bitcoin: {len(namen)} Wallet(s), Whitelist gilt nicht für ihn")


def main() -> None:
    _warte(PORT_OFFEN)
    _nowallet_holen()
    print("Core-Allowlist am Regtest-Node")
    _kette(USER_OFFEN, PASS_OFFEN)
    _kette(USER_LISTE, PASS_LISTE)
    block0 = _client(USER_LISTE, PASS_LISTE, PORT_OFFEN).call("getblockhash", [0])
    if not isinstance(block0, str) or len(block0) != 64:
        raise SystemExit(f"getblockhash unerwartet: {block0!r}")
    print("  getblockhash 0 als satsage")
    _offen_darf_listwallets()
    _blockiert("dumpwallet", ["lab"], user=USER_OFFEN, password=PASS_OFFEN, network="regtest")
    _blockiert("dumpwallet", ["lab"], user=USER_LISTE, password=PASS_LISTE, network="regtest")
    _blockiert(
        "listdescriptors",
        [True],
        user=USER_LISTE,
        password=PASS_LISTE,
        network="regtest",
    )
    _blockiert(
        "sendtoaddress",
        ["", 0],
        user=USER_OFFEN,
        password=PASS_OFFEN,
        network="main",
    )
    try:
        _client(USER_LISTE, PASS_LISTE, PORT_OFFEN).call("sendtoaddress", ["", 0])
    except RpcVerweigertError as exc:
        if "rpcwhitelist" not in str(exc):
            raise SystemExit(f"sendtoaddress-Hinweis unklar: {exc}")
    except RpcAllowlistError as exc:
        raise SystemExit(f"sendtoaddress im Regtest von der Allowlist gestoppt: {exc}")
    else:
        raise SystemExit("sendtoaddress lief trotz rpcwhitelist durch.")
    print("  sendtoaddress im Regtest erlaubt, Node-Whitelist lehnt ab")
    _whitelist_verweigert()
    _ohne_wallet()
    print("Core-Allowlist grün")


if __name__ == "__main__":
    main()
