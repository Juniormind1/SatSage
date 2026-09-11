#!/usr/bin/env python3
"""Prüft Lab-Tx-Klassifikation (CoinJoin / PayJoin / Fan-Out / Exchange).

Voraussetzung: Lab läuft, ``generate_scenarios.py`` hat
``.data/scenario-report-txclass.json`` geschrieben.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
REPORT = HERE / ".data" / "scenario-report-txclass.json"
ENV_PATH = HERE / ".data" / ".regtest.env"

sys.path.insert(0, str(REPO))


def _load_env(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        werte[k.strip()] = v.strip()
    return werte


def _make_get_tx(werte: dict[str, str]):
    """Fulcrum wenn erreichbar, sonst Core-RPC."""
    import main as satsage_main

    cache_root = HERE / ".data" / "immutable_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        client, quelle = satsage_main.resolve_sanctions_preferred_client(werte)
    except Exception:
        client, quelle = None, None
    if client is not None:
        print(f"get_tx Quelle: {quelle}")
        return satsage_main.make_cached_fulcrum_get_tx(client, cache_root)

    # Core-RPC Fallback (Lab bitcoind)
    import urllib.request

    host = werte.get("NODE_IP") or "127.0.0.1"
    port = werte.get("RPCPORT") or "18443"
    user = werte.get("RPCUSER") or "bitcoin"
    password = werte.get("RPCPASSWORD") or "secret"
    url = f"http://{user}:{password}@{host}:{port}"

    def get_tx(txid: str) -> dict:
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": "txclass",
            "method": "getrawtransaction",
            "params": [txid, True],
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if body.get("error"):
            raise RuntimeError(body["error"])
        return body["result"]

    print("get_tx Quelle: bitcoind-rpc")
    return get_tx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    if not args.report.is_file():
        print(f"Report fehlt: {args.report}", file=sys.stderr)
        print("Zuerst generate_scenarios.py laufen lassen.", file=sys.stderr)
        return 1

    os.environ.setdefault("NETWORK", "regtest")
    werte = _load_env(ENV_PATH)
    for k, v in werte.items():
        os.environ[k] = v

    import main as satsage_main
    from core.config import EnvFile, read_wallets
    from core.tx_classify import classify_tx

    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        return 1
    env = EnvFile.load(ENV_PATH)
    wallets = read_wallets(env)
    if not wallets:
        print("Keine WALLET_* in Lab-Env", file=sys.stderr)
        return 1

    xpubs = [w.xpub for w in wallets]
    names = [w.name for w in wallets]
    scripts = [w.script_type for w in wallets]
    maxes = [w.max_addresses for w in wallets]
    ctx = satsage_main.build_wallet_context(
        xpubs,
        wallet_names=names,
        max_addresses_per_xpub=maxes,
        script_types=scripts,
    )
    eigene = set(ctx.address_to_wallet)
    get_tx = _make_get_tx(werte)

    # Adressen je Wallet-Name — Verify aus Viewer-Perspektive (Peers ≠ eigen).
    addrs_by_wallet: dict[str, set[str]] = {}
    for addr, wname in ctx.address_to_wallet.items():
        addrs_by_wallet.setdefault(wname, set()).add(addr)

    viewer_name = {
        "lab-alpha": "Lab Alpha",
        "lab-beta": "Lab Beta",
        "lab-change": "Lab Change",
        "lab-gamma": "Lab Gamma",
    }

    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = 0
    for case in report.get("cases", []):
        name = case["name"]
        txid = case["txid"]
        expected = case["expected_kind"]
        try:
            tx = get_tx(txid)
        except Exception as exc:
            print(f"FAIL {name}: get_tx {exc}")
            failures += 1
            continue
        # Nur Viewer-Wallet als „eigen“ — sonst wären Lab-CJ-Peers alle eigen
        # und die Form würde als Fan-Out enden.
        vw = case.get("viewer_wallet") or ""
        wlabel = viewer_name.get(vw)
        if wlabel and wlabel in addrs_by_wallet:
            own = set(addrs_by_wallet[wlabel])
        else:
            own = set(eigene)
        result = classify_tx(tx, own, wallet=None, get_tx=get_tx)
        ok = result.kind == expected
        if not ok and expected == "wasabi_classic" and result.kind == "coinjoin":
            ok = True
        status = "OK" if ok else "FAIL"
        print(
            f"{status} {name}: expected={expected} got={result.kind} "
            f"label={result.soft_label_de!r}"
        )
        if not ok:
            failures += 1

    if failures:
        print(f"{failures} Fehler", file=sys.stderr)
        return 1
    print("Alle Klassifikationen ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
