#!/usr/bin/env python3
"""Electrs-Scan und Herkunft gegen das Lab-Inventar.

UTXOs über ``fetch_wallet_utxos_fulcrum``, Herkunft über
``trace_utxo_origin`` mit Electrs-``get_tx``. Kein Core-Fallback.
Soll: ``.data/herkunft-inventar.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
WORK = HERE / ".data" / "electrs-traces"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from infra_check import brauche  # noqa: E402
from herkunft_inventar import (  # noqa: E402
    _signatur,
    lade_inventar,
    vergleiche_bestand,
    vergleiche_herkunft,
)


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


def _kurz(txid: str) -> str:
    t = (txid or "").strip().lower()
    return f"{t[:8]}…{t[-4:]}" if len(t) >= 16 else t


def _electrs_get_tx(client):
    """Nur Electrs. Core-Lookup wäre ein stiller zweiter Weg."""
    from core.chain_sources import wrap_get_tx_with_immutable_cache
    from core.fulcrum_history import fetch_tx_fulcrum

    imm = WORK / "immutable_cache"
    imm.mkdir(parents=True, exist_ok=True)

    def raw(txid: str) -> dict:
        return fetch_tx_fulcrum(client, txid)

    return wrap_get_tx_with_immutable_cache(raw, imm, "electrs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-traces", type=int, default=0,
        help="höchstens n Herkunftsbäume (0 = alle). Teilvergleich bleibt rot.",
    )
    parser.add_argument("--report", type=Path, default=WORK / "report.json")
    args = parser.parse_args()

    fehl = brauche("bitcoind", "electrs")
    if fehl is not None:
        return fehl
    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        return 1

    werte = _load_env(ENV_PATH)
    os.environ["NETWORK"] = werte.get("NETWORK") or "regtest"
    for k, v in werte.items():
        if k.startswith("WALLET_") or k in ("NETWORK",):
            os.environ[k] = v

    import main as satsage_main
    from core.config import EnvFile, read_wallets
    from core.fulcrum_client import connect_fulcrum
    from core.fulcrum_wallet import fetch_wallet_utxos_fulcrum
    from core.utxo_origin import trace_utxo_origin

    satsage_main.set_chain_network("regtest")
    wallets = read_wallets(EnvFile.load(ENV_PATH))
    if not wallets:
        print("Keine WALLET_* in Lab-Env", file=sys.stderr)
        return 1
    ctx = satsage_main.build_wallet_context(
        [w.xpub for w in wallets],
        wallet_names=[w.name for w in wallets],
        max_addresses_per_xpub=[w.max_addresses for w in wallets],
        script_types=[w.script_type for w in wallets],
    )
    try:
        soll = lade_inventar()
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    host = werte.get("FULCRUM_HOST") or "127.0.0.1"
    port = int(werte.get("FULCRUM_PORT") or "50001")
    ssl = str(werte.get("FULCRUM_SSL") or "false").lower() in ("1", "true", "ja")
    client, fehler = connect_fulcrum(host, port, use_ssl=ssl, timeout=30)
    if client is None:
        print(f"Electrs nicht verbunden: {fehler}", file=sys.stderr)
        return 1
    print(f"Electrs {host}:{port} ({client.server_software or '?'})", flush=True)

    adressen = set(ctx.address_to_wallet)
    t0 = time.monotonic()
    print(f"Electrs-Scan {len(adressen)} Adressen…", flush=True)
    utxos = fetch_wallet_utxos_fulcrum(client, adressen)
    print(
        f"  {len(utxos)} UTXOs, Inventar {len(soll)}, "
        f"{time.monotonic() - t0:.1f}s",
        flush=True,
    )
    gefunden: dict[str, dict] = {}
    for u in utxos:
        txid = str(u.get("txid") or "").lower()
        try:
            vout = int(u.get("vout", 0))
        except (TypeError, ValueError):
            continue
        u = dict(u)
        u["txid"] = txid
        u["vout"] = vout
        gefunden[f"{txid}:{vout}"] = u

    fehlend, extra, faelle = vergleiche_bestand(
        soll, gefunden, addr_wallet=ctx.address_to_wallet, quelle="Electrs",
    )
    get_tx = _electrs_get_tx(client)
    keys = list(soll)[: args.max_traces] if args.max_traces > 0 else list(soll)
    ok = fail = 0
    fail += len(fehlend) + len(extra)
    cache_dir = WORK / "utxo_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    eigene = set(ctx.address_to_wallet)

    for i, key in enumerate(keys, 1):
        if key not in gefunden:
            continue
        eintrag = soll[key]
        u = gefunden[key]
        txid = eintrag["txid"]
        vout = int(eintrag["vout"])
        start = time.monotonic()
        try:
            ist_sats = int(u.get("value") or 0)
            if ist_sats != int(eintrag["amount_sats"]):
                raise AssertionError(
                    f"Betrag {ist_sats} != {eintrag['amount_sats']}"
                )
            wallet_ist = ctx.address_to_wallet.get(u.get("address"))
            if wallet_ist != eintrag["wallet"]:
                raise AssertionError(
                    f"Wallet {wallet_ist} != {eintrag['wallet']}"
                )
            baum = trace_utxo_origin(
                get_tx, txid, vout, eigene, wallet=ctx, cache_dir=cache_dir,
            )
            diff = vergleiche_herkunft(eintrag["herkunft"], _signatur(baum))
            if diff:
                raise AssertionError(diff)
            dauer = time.monotonic() - start
            ok += 1
            print(
                f"  OK  electrs {i}/{len(keys)} {_kurz(txid)}:{vout} "
                f"{eintrag['wallet']} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz(txid), "vout": vout, "ok": True,
                "wallet": eintrag["wallet"], "seconds": round(dauer, 2),
            })
        except Exception as exc:
            dauer = time.monotonic() - start
            fail += 1
            print(
                f"  FAIL electrs {i}/{len(keys)} {_kurz(txid)}:{vout} "
                f"{type(exc).__name__}: {exc} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz(txid), "vout": vout, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(dauer, 2),
            })

    vollstaendig = (
        args.max_traces <= 0
        and not fehlend
        and not extra
        and fail == 0
        and ok == len(soll)
    )
    if args.max_traces > 0:
        print(
            f"  Teilvergleich {ok}/{len(keys)} — "
            "Suite bleibt rot, bis alle Inventar-UTXOs verglichen sind.",
            flush=True,
        )
    ergebnis: dict[str, Any] = {
        "ok": vollstaendig,
        "traced": ok,
        "failed": fail,
        "utxos": len(gefunden),
        "inventar": len(soll),
        "missing": len(fehlend),
        "extra": len(extra),
        "cases": faelle,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(ergebnis, indent=2) + "\n", encoding="utf-8")
    print(
        f"{'OK' if vollstaendig else 'FAIL'} electrs-inventar "
        f"utxos={len(gefunden)}/{len(soll)} traced={ok} failed={fail}",
        flush=True,
    )
    try:
        client.close()
    except Exception:
        pass
    return 0 if vollstaendig else 1


if __name__ == "__main__":
    raise SystemExit(main())
