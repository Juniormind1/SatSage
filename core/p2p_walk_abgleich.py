"""P2P-Entdeckung und Herkunft gegen den Electrs-Cache.

Soll-Bestand: UTXOs im Wallet-Cache. Soll-Herkunft: gespeicherter
Trace-Baum, soweit vorhanden. Ist: Compact-Filter-Scan und
``fetch_tx_p2p_mit_fallback``, kein Electrs, kein Core. Der Electrs-Cache
bleibt unangetastet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.trace_cache import origin_tree_laden
from core.xpub_cache import load_xpub_cache_entry


def _utxo_key(txid: str, vout: int) -> str:
    return f"{str(txid).strip().lower()}:{int(vout)}"


def cache_utxos(entries, cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Alle UTXOs aus dem Wallet-Cache, Schlüssel ``txid:vout``."""
    soll: dict[str, dict[str, Any]] = {}
    for entry in entries:
        xpub = getattr(entry, "analyse_schluessel", None) or getattr(entry, "xpub", "")
        geladen = load_xpub_cache_entry(xpub, cache_dir)
        if not geladen:
            continue
        wallet = getattr(entry, "display_name", "") or ""
        for u in geladen.get("utxos") or []:
            if not isinstance(u, dict):
                continue
            txid = str(u.get("txid") or "").strip().lower()
            if len(txid) != 64:
                continue
            try:
                vout = int(u.get("vout", 0))
                sats = int(u.get("value") or 0)
            except (TypeError, ValueError):
                continue
            soll.setdefault(_utxo_key(txid, vout), {
                "txid": txid,
                "vout": vout,
                "amount_sats": sats,
                "address": u.get("address") or "",
                "wallet": wallet,
            })
    return soll


def vergleiche_entdeckung(
    soll: dict[str, dict[str, Any]],
    gefunden: list[dict],
    *,
    addr_wallet: dict[str, str],
) -> dict[str, Any]:
    """Bestand: jeder Soll-Outpoint, Betrag und Wallet. Extra zählt mit."""
    ist: dict[str, dict] = {}
    for u in gefunden:
        if not isinstance(u, dict):
            continue
        txid = str(u.get("txid") or "").strip().lower()
        try:
            vout = int(u.get("vout", 0))
            sats = int(u.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if len(txid) != 64:
            continue
        ist[_utxo_key(txid, vout)] = {
            "txid": txid,
            "vout": vout,
            "amount_sats": sats,
            "address": u.get("address") or "",
        }
    faelle: list[dict[str, Any]] = []
    fehlend = extra = betrag = 0
    for key, eintrag in soll.items():
        treffer = ist.get(key)
        if treffer is None:
            fehlend += 1
            faelle.append({
                "txid": eintrag["txid"], "vout": eintrag["vout"],
                "wallet": eintrag.get("wallet") or "",
                "grund": "nicht im P2P-Scan",
            })
            continue
        if treffer["amount_sats"] != int(eintrag["amount_sats"]):
            betrag += 1
            faelle.append({
                "txid": eintrag["txid"], "vout": eintrag["vout"],
                "wallet": eintrag.get("wallet") or "",
                "grund": f"Betrag {treffer['amount_sats']} != {eintrag['amount_sats']}",
            })
        wallet_ist = addr_wallet.get(treffer["address"])
        if wallet_ist and wallet_ist != eintrag.get("wallet"):
            betrag += 1
            faelle.append({
                "txid": eintrag["txid"], "vout": eintrag["vout"],
                "wallet": eintrag.get("wallet") or "",
                "grund": f"Wallet {wallet_ist} != {eintrag.get('wallet')}",
            })
    for key, treffer in ist.items():
        if key in soll:
            continue
        if not addr_wallet.get(treffer["address"]):
            continue
        extra += 1
        faelle.append({
            "txid": treffer["txid"], "vout": treffer["vout"],
            "wallet": addr_wallet.get(treffer["address"]) or "",
            "grund": "nicht im Electrs-Cache",
        })
    return {
        "ok": not fehlend and not extra and not betrag and bool(soll),
        "soll": len(soll),
        "gefunden": len(ist),
        "fehlend": fehlend,
        "extra": extra,
        "betrag": betrag,
        "faelle": faelle[:40],
    }


def utxos_mit_herkunft(
    entries,
    cache_dir: Path,
    immutable_dir: Path,
) -> list[dict[str, Any]]:
    """Cache-UTXOs, deren Herkunftsbaum schon im Trace-Cache liegt."""
    gesehen: set[str] = set()
    aus: list[dict[str, Any]] = []
    for entry in entries:
        xpub = getattr(entry, "analyse_schluessel", None) or getattr(entry, "xpub", "")
        geladen = load_xpub_cache_entry(xpub, cache_dir)
        if not geladen:
            continue
        for u in geladen.get("utxos") or []:
            if not isinstance(u, dict):
                continue
            txid = str(u.get("txid") or "").strip().lower()
            if len(txid) != 64:
                continue
            try:
                vout = int(u.get("vout", 0))
                sats = int(u.get("value") or 0)
            except (TypeError, ValueError):
                continue
            key = _utxo_key(txid, vout)
            if key in gesehen:
                continue
            baum = origin_tree_laden(txid, vout, immutable_dir)
            if not isinstance(baum, dict):
                continue
            gesehen.add(key)
            aus.append({
                "txid": txid,
                "vout": vout,
                "amount_sats": sats,
                "address": u.get("address") or "",
                "wallet": getattr(entry, "display_name", "") or "",
                "herkunft": baum,
            })
    aus.sort(key=lambda e: (e["wallet"], e["txid"], e["vout"]))
    return aus


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
    sources.sort(key=lambda s: (str(s["type"]), s["from_utxo"], s["amount_sats"]))
    return {
        "type": knoten.get("type"),
        "tx_class": knoten.get("tx_class") or "",
        "amount_sats": int(knoten.get("amount_sats") or 0),
        "sources": sources,
        "enden": _enden(knoten),
    }


def _enden(knoten: dict) -> list[dict]:
    enden: list[dict] = []

    def walk(node: dict) -> None:
        for src in node.get("sources") or []:
            if not isinstance(src, dict):
                continue
            if src.get("type") == "internal":
                kind = src.get("trace")
                if isinstance(kind, dict):
                    walk(kind)
                continue
            enden.append({
                "type": src.get("type"),
                "from_utxo": str(src.get("from_utxo") or ""),
                "amount_sats": int(src.get("amount_sats") or 0),
            })

    walk(knoten)
    enden.sort(key=lambda e: (str(e["type"]), e["from_utxo"], e["amount_sats"]))
    return enden


def _unterschied(soll: dict, ist: dict) -> str | None:
    if soll == ist:
        return None
    if soll.get("enden") != ist.get("enden"):
        return (
            f"Enden {len(ist.get('enden') or [])}"
            f"/{len(soll.get('enden') or [])}"
        )
    return "Herkunftsbaum weicht ab"


def gleiche_herkunft_ab(
    soll: list[dict[str, Any]],
    get_tx: Callable[[str], dict],
    *,
    eigene: set[str],
    wallet,
    on_progress: Callable[[str], None] | None = None,
    abbruch: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    Verfolgt jedes Soll-UTXO über *get_tx* und vergleicht die Signatur.

    Schreibt weder Trace-Cache noch Ingress.
    """
    from core.utxo_origin import trace_utxo_origin

    ok = 0
    abweichungen: list[dict[str, Any]] = []
    gesamt = len(soll)
    for i, eintrag in enumerate(soll, 1):
        if abbruch:
            abbruch()
        txid = eintrag["txid"]
        vout = int(eintrag["vout"])
        if on_progress:
            on_progress(
                f"P2P-Abgleich {i}/{gesamt} {txid[:8]}…:{vout}"
            )
        try:
            baum = trace_utxo_origin(
                get_tx, txid, vout, eigene, wallet=wallet,
            )
            diff = _unterschied(_signatur(eintrag["herkunft"]), _signatur(baum))
            if diff:
                abweichungen.append({
                    "txid": txid,
                    "vout": vout,
                    "wallet": eintrag.get("wallet") or "",
                    "grund": diff,
                })
            else:
                ok += 1
        except Exception as exc:
            abweichungen.append({
                "txid": txid,
                "vout": vout,
                "wallet": eintrag.get("wallet") or "",
                "grund": f"{type(exc).__name__}: {exc}",
            })
    return {
        "ok": not abweichungen and ok == gesamt and gesamt > 0,
        "verglichen": ok,
        "abweichungen": len(abweichungen),
        "gesamt": gesamt,
        "faelle": abweichungen[:40],
    }
