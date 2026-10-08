#!/usr/bin/env python3
"""Soll-Inventar der Lab-UTXOs und ihrer Herkunft.

Schreibt ``.data/herkunft-inventar.json``. Quelle ist der Labor-Node
(listunspent der vier Watch-Wallets, getrawtransaction für den Walk).
Der P2P-Prüfer liest nur diese Datei und vergleicht vollständig.

Keine XPUBs, keine Seeds. Adressen und TxIDs bleiben im ignorierten
``.data/``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from generate_scenarios import ENV_PATH, Rpc, choose_native, load_or_create  # noqa: E402

INVENTAR = HERE / ".data" / "herkunft-inventar.json"
WALLETS = (
    ("lab-alpha", "Lab Alpha"),
    ("lab-beta", "Lab Beta"),
    ("lab-change", "Lab Change"),
    ("lab-gamma", "Lab Gamma"),
)


def _sats(amount: Any) -> int:
    return int(round(float(amount) * 1e8))


def _core_tx(rpc: Rpc, txid: str, cache: dict[str, dict]) -> dict:
    key = txid.strip().lower()
    if key not in cache:
        from core.bitcoind_rpc import normalize_core_tx

        roh = rpc.json("getrawtransaction", key, "true")
        cache[key] = normalize_core_tx(roh, client=None)
        tx = cache[key]
        blockhash = roh.get("blockhash")
        if blockhash and not (tx.get("status") or {}).get("block_height"):
            header = rpc.json("getblockheader", str(blockhash))
            status = dict(tx.get("status") or {})
            if header.get("height") is not None:
                status["block_height"] = int(header["height"])
            if header.get("time") and "block_time" not in status:
                status["block_time"] = int(header["time"])
            status["confirmed"] = True
            tx["status"] = status
    return cache[key]


def _blatt(knoten: dict) -> list[dict]:
    """Flache Enden: coinbase / external / error, plus interne Kinder."""
    enden: list[dict] = []

    def walk(node: dict) -> None:
        for src in node.get("sources") or []:
            if not isinstance(src, dict):
                continue
            typ = src.get("type")
            if typ == "internal":
                kind = src.get("trace")
                if isinstance(kind, dict):
                    walk(kind)
                continue
            enden.append({
                "type": typ,
                "from_utxo": src.get("from_utxo") or "",
                "amount_sats": int(src.get("amount_sats") or 0),
                "address": src.get("address") or "",
            })

    walk(knoten)
    enden.sort(key=lambda e: (e["type"], e["from_utxo"], e["amount_sats"]))
    return enden


def _signatur(knoten: dict | None) -> dict:
    if not isinstance(knoten, dict):
        return {"type": "missing", "sources": [], "enden": []}
    sources = []
    for src in knoten.get("sources") or []:
        if not isinstance(src, dict):
            continue
        eintrag = {
            "type": src.get("type"),
            "from_utxo": str(src.get("from_utxo") or ""),
            "amount_sats": int(src.get("amount_sats") or 0),
        }
        kind = src.get("trace")
        if isinstance(kind, dict):
            eintrag["trace"] = _signatur(kind)
        elif src.get("type") == "internal":
            eintrag["trace"] = {"type": "missing", "sources": []}
        sources.append(eintrag)
    sources.sort(key=lambda s: (s["type"], s["from_utxo"], s["amount_sats"]))
    return {
        "type": knoten.get("type"),
        "tx_class": knoten.get("tx_class") or "",
        "amount_sats": int(knoten.get("amount_sats") or 0),
        "sources": sources,
        "enden": _blatt(knoten),
    }


def schreibe_inventar(rpc: Rpc, *, pfad: Path = INVENTAR) -> dict:
    import os

    os.environ.setdefault("NETWORK", "regtest")
    import main as satsage_main
    from core.config import EnvFile, read_wallets
    from core.utxo_origin import trace_utxo_origin

    satsage_main.set_chain_network("regtest")
    env = EnvFile.load(ENV_PATH)
    wallets = read_wallets(env)
    ctx = satsage_main.build_wallet_context(
        [w.xpub for w in wallets],
        wallet_names=[w.name for w in wallets],
        max_addresses_per_xpub=[w.max_addresses for w in wallets],
        script_types=[w.script_type for w in wallets],
    )
    eigene = set(ctx.address_to_wallet)
    tx_cache: dict[str, dict] = {}

    def get_tx(txid: str) -> dict:
        return _core_tx(rpc, txid, tx_cache)

    eintraege: list[dict] = []
    for core_name, label in WALLETS:
        load_or_create(rpc, core_name)
        rows = rpc.json("listunspent", "1", "9999999", wallet=core_name)
        for row in rows:
            txid = str(row["txid"]).lower()
            vout = int(row["vout"])
            betrag = _sats(row["amount"])
            baum = trace_utxo_origin(
                get_tx, txid, vout, eigene, wallet=ctx,
            )
            eintraege.append({
                "wallet": label,
                "txid": txid,
                "vout": vout,
                "amount_sats": betrag,
                "address": row.get("address") or "",
                "height": None,
                "herkunft": _signatur(baum),
            })
        print(f"  {label}: {len(rows)} UTXOs", flush=True)

    # Höhe aus der Erzeuger-Tx, nicht aus confirmations (die wandert mit dem Tip).
    for eintrag in eintraege:
        tx = get_tx(eintrag["txid"])
        status = tx.get("status") or {}
        eintrag["height"] = status.get("block_height")
    eintraege.sort(key=lambda e: (e["wallet"], e["txid"], e["vout"]))
    tip = int(rpc.call("getblockcount"))
    inventar = {
        "tip_height": tip,
        "utxo_count": len(eintraege),
        "utxos": eintraege,
    }
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(inventar, indent=2) + "\n", encoding="utf-8")
    print(f"Inventar {len(eintraege)} UTXOs, Tip {tip} → {pfad}", flush=True)
    return inventar


def lade_inventar(pfad: Path = INVENTAR) -> dict[str, dict]:
    """Outpoint ``txid:vout`` → Inventar-Eintrag."""
    if not pfad.is_file():
        raise FileNotFoundError(
            f"Inventar fehlt: {pfad}. Zuerst herkunft_inventar.py."
        )
    roh = json.loads(pfad.read_text(encoding="utf-8"))
    soll: dict[str, dict] = {}
    for eintrag in roh.get("utxos") or []:
        key = f"{str(eintrag['txid']).strip().lower()}:{int(eintrag['vout'])}"
        soll[key] = eintrag
    if not soll:
        raise RuntimeError("Inventar enthält keine UTXOs")
    return soll


def vergleiche_herkunft(soll: dict, ist: dict) -> str | None:
    """None bei Deckung. Sonst ein kurzer Unterschied."""
    if soll == ist:
        return None
    soll_enden = soll.get("enden") or []
    ist_enden = ist.get("enden") or []
    if soll_enden != ist_enden:
        return (
            f"Enden {len(ist_enden)}/{len(soll_enden)} "
            f"soll={soll_enden[:2]} ist={ist_enden[:2]}"
        )
    return "Herkunftsbaum weicht ab"


def vergleiche_bestand(
    soll: dict[str, dict],
    gefunden: dict[str, dict],
    *,
    addr_wallet: dict[str, str],
    quelle: str,
) -> tuple[list[str], list[str], list[dict]]:
    """
    Fehlende und zusätzliche Outpoints.

    *gefunden* mappt ``txid:vout`` auf ein UTXO-Dict mit ``txid``, ``vout``,
    ``value`` (Sats), ``address``.
    """
    fehlend = sorted(set(soll) - set(gefunden))
    extra = sorted(
        key for key, u in gefunden.items()
        if key not in soll and addr_wallet.get(u.get("address"))
    )
    faelle: list[dict] = []
    for key in fehlend:
        eintrag = soll[key]
        print(
            f"  FAIL fehlt {eintrag['txid'][:8]}…:{eintrag['vout']} "
            f"{eintrag['wallet']} {eintrag['amount_sats']} sat ({quelle})",
            flush=True,
        )
        faelle.append({
            "txid": eintrag["txid"][:8], "vout": eintrag["vout"],
            "ok": False, "error": f"nicht im {quelle}-Scan",
        })
    for key in extra:
        u = gefunden[key]
        txid = str(u.get("txid") or "")
        print(f"  FAIL extra {txid[:8]}…:{u.get('vout')} ({quelle})", flush=True)
        faelle.append({
            "txid": txid[:8], "vout": u.get("vout"),
            "ok": False, "error": "nicht im Inventar",
        })
    return fehlend, extra, faelle


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--out", type=Path, default=INVENTAR)
    args = parser.parse_args()
    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        return 1
    rpc = Rpc(choose_native(args.native))
    schreibe_inventar(rpc, pfad=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
