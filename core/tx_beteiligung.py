"""Gezielte Tx-Analyse: welche Inputs/Outputs gehören zu unseren Wallets?"""
from __future__ import annotations

from typing import Any, Callable

from core.trace import _tx_als_dict, parse_ziel, resolve_vin_prevout
from core.utxo_report import _extract_addresses, _extract_value_sats
from core.xpub_cache import load_cached_tx


def parse_txid(text: str) -> str | None:
    """Reine TxID oder ``txid:vout`` — nur der Tx-Teil, kleingeschrieben."""
    ziel = parse_ziel(text)
    if ziel is None:
        return None
    return ziel[0]


def cache_deckt_analyse(txid: str, cache_root=None) -> bool:
    """
    True, wenn die Tx und alle Input-Vorgänger im Immutable-Cache liegen
    (oder die Prevouts schon in der Tx stehen). Dann braucht die Analyse
    kein Electrs.
    """
    key = parse_txid(txid)
    if not key:
        return False
    tx = load_cached_tx(key, cache_root)
    if not isinstance(tx, dict):
        return False
    for vin in tx.get("vin") or []:
        if not isinstance(vin, dict):
            continue
        if vin.get("is_coinbase") or "txid" not in vin:
            continue
        prev = vin.get("prevout")
        if isinstance(prev, dict) and prev:
            continue
        parent = load_cached_tx(str(vin.get("txid") or ""), cache_root)
        if not isinstance(parent, dict):
            return False
        vouts = parent.get("vout") or []
        try:
            idx = int(vin.get("vout") or 0)
        except (TypeError, ValueError):
            return False
        if idx < 0 or idx >= len(vouts):
            return False
    return True


def _adresse_wallet(wallet: Any, adressen: list[str]) -> tuple[str, str]:
    """Erste erkennbare Adresse und Wallet-Name (leer = fremd)."""
    for addr in adressen:
        if not addr:
            continue
        name = ""
        if wallet is not None and getattr(wallet, "resolve_address", None):
            name = wallet.resolve_address(addr) or ""
        return str(addr), str(name or "")
    return "", ""


def _zeile_output(n: int, vout: dict, wallet: Any) -> dict:
    addrs = _extract_addresses(vout) if isinstance(vout, dict) else []
    adresse, name = _adresse_wallet(wallet, addrs)
    return {
        "n": n,
        "value_sats": _extract_value_sats(vout) if isinstance(vout, dict) else 0,
        "address": adresse,
        "wallet": name,
        "eigen": bool(name),
    }


def analysiere_tx(
    txid: str,
    *,
    get_tx: Callable[[str], dict],
    wallet: Any = None,
    cache_root=None,
    on_progress: Callable[[str], None] | None = None,
    raise_if_cancelled: Callable[[], None] | None = None,
) -> dict:
    """
    Holt die Tx (Cache, sonst *get_tx*) und prüft jeden Zu- und Abgang.

    *get_tx* ist die übliche Chain-Funktion (Electrs/Core, schreibt den Cache).
    """
    key = parse_txid(txid)
    if not key:
        raise ValueError("Das ist keine Transaktions-ID.")

    def brich():
        if raise_if_cancelled:
            raise_if_cancelled()

    def melde(text: str) -> None:
        if on_progress:
            on_progress(text)

    im_cache = load_cached_tx(key, cache_root) is not None
    melde("Hole Transaktion aus dem Cache…" if im_cache else "Hole Transaktion (Electrs)…")
    brich()
    tx = _tx_als_dict(get_tx(key))
    vins = tx.get("vin") or []
    vouts = tx.get("vout") or []
    if not isinstance(vins, list):
        vins = []
    if not isinstance(vouts, list):
        vouts = []

    inputs: list[dict] = []
    for i, vin in enumerate(vins):
        brich()
        melde(f"Prüfe Input {i + 1}/{len(vins) or 1}…")
        if not isinstance(vin, dict):
            inputs.append({
                "n": i, "txid": "", "vout": 0, "value_sats": 0,
                "address": "", "wallet": "", "eigen": False, "coinbase": False,
            })
            continue
        if vin.get("is_coinbase") or "txid" not in vin:
            inputs.append({
                "n": i, "txid": "", "vout": 0, "value_sats": 0,
                "address": "", "wallet": "", "eigen": False, "coinbase": True,
            })
            continue
        prev = resolve_vin_prevout(get_tx, vin)
        addrs = _extract_addresses(prev) if prev else []
        adresse, name = _adresse_wallet(wallet, addrs)
        inputs.append({
            "n": i,
            "txid": str(vin.get("txid") or ""),
            "vout": int(vin.get("vout") or 0),
            "value_sats": _extract_value_sats(prev) if prev else 0,
            "address": adresse,
            "wallet": name,
            "eigen": bool(name),
            "coinbase": False,
        })

    outputs: list[dict] = []
    for i, vout in enumerate(vouts):
        brich()
        outputs.append(_zeile_output(i, vout if isinstance(vout, dict) else {}, wallet))

    eigene_in = sum(1 for z in inputs if z["eigen"])
    eigene_out = sum(1 for z in outputs if z["eigen"])
    return {
        "txid": key,
        "aus_cache": im_cache,
        "inputs": inputs,
        "outputs": outputs,
        "eigene_inputs": eigene_in,
        "eigene_outputs": eigene_out,
    }
