"""
Jäger der verlorene Schätze.

scantxoutset jenseits des normalen Suchfensters. Treffer werden in den
UTXO-Cache der Wallets einsortiert — derselbe Bestand, den die Wallet-Ansicht
liest. Der Lauf ist langsam, weil der Node das UTXO-Set abklopft.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.derivation import (
    derive_addresses_at_index,
    ist_deskriptor,
)
from core.wallet_sync_engine import _scan_index_cap_per_chain

#: Indizes je Kette hinter dem normalen Fenster (Empfang und Wechselgeld).
SCHATZ_WEITE = 2000

LogFn = Callable[[str], None]


def suchfenster(cap: int, *, cache_scan_end: int | None = None) -> tuple[int, int]:
    """
    Erstes Index außerhalb des normalen Scans und Ende der Schatzsuche.

    ``cap`` ist die Obergrenze des normalen Scans (exklusiv). Liegt der
    Cache schon weiter, beginnt die Suche dort.
    """
    start = max(0, int(cap))
    if cache_scan_end is not None:
        start = max(start, int(cache_scan_end))
    return start, start + SCHATZ_WEITE


def schatz_hinweis(
    *,
    wallet: str,
    chain: int,
    index: int,
    fenster_bis: int,
    sats: int,
) -> str:
    """Was der normale Scan an diesem UTXO übersehen hat."""
    kette = "Empfang" if int(chain) == 0 else "Wechselgeld"
    bis = max(0, int(fenster_bis) - 1)
    return (
        f"Schatz: {int(sats)} sats auf {kette} #{int(index)} von {wallet}. "
        f"Der normale Scan reicht nur bis Index #{bis} — "
        f"diese Adresse lag außerhalb des Suchfensters."
    )


def _utxo_schluessel(utxo: dict) -> str:
    return f"{utxo.get('txid')}:{utxo.get('vout')}"


def merge_utxos(bisher: list[dict], neu: list[dict]) -> list[dict]:
    """Hängt neue Outpoints an, ohne den vorhandenen Bestand zu ersetzen."""
    gesehen = {_utxo_schluessel(u) for u in bisher}
    out = list(bisher)
    for utxo in neu:
        key = _utxo_schluessel(utxo)
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append(utxo)
    return out


def adressen_im_fenster(
    schluessel: str,
    start: int,
    ende: int,
    script_type: str | None,
) -> dict[str, tuple[int, int]]:
    """Adresse → (change, index) für Indizes ``start`` .. ``ende`` (Ende exklusiv)."""
    gefunden: dict[str, tuple[int, int]] = {}
    for index in range(max(0, int(start)), max(0, int(ende))):
        for change in (0, 1):
            adressen = derive_addresses_at_index(
                schluessel, change, index, script_type,
            )
            if ist_deskriptor(schluessel) and not adressen:
                continue
            for addr in adressen:
                if addr:
                    gefunden.setdefault(addr, (change, index))
    return gefunden


def sammle_schaetze(
    utxos: list[dict],
    *,
    zuordnung: dict[str, dict[str, Any]],
    vorhanden_je_xpub: dict[str, list[dict]],
) -> list[dict]:
    """
    Behält nur UTXOs, deren Adresse im Schatzfenster liegt und die der
    Cache noch nicht hat.

    *zuordnung*: Adresse → ``xpub``, ``wallet``, ``chain``, ``index``,
    ``fenster_bis``.
    """
    schon: dict[str, set[str]] = {}
    for xpub, liste in vorhanden_je_xpub.items():
        schon[xpub] = {_utxo_schluessel(u) for u in liste}

    funde: list[dict] = []
    for utxo in utxos:
        adresse = str(utxo.get("address") or "")
        info = zuordnung.get(adresse)
        if not info:
            continue
        xpub = str(info["xpub"])
        if _utxo_schluessel(utxo) in schon.get(xpub, set()):
            continue
        sats = int(utxo.get("value") or 0)
        chain = int(info["chain"])
        index = int(info["index"])
        fenster_bis = int(info["fenster_bis"])
        wallet = str(info["wallet"])
        funde.append({
            "xpub": xpub,
            "wallet": wallet,
            "address": adresse,
            "sats": sats,
            "chain": chain,
            "index": index,
            "fenster_bis": fenster_bis,
            "txid": utxo.get("txid"),
            "vout": utxo.get("vout"),
            "hinweis": schatz_hinweis(
                wallet=wallet,
                chain=chain,
                index=index,
                fenster_bis=fenster_bis,
                sats=sats,
            ),
            "utxo": utxo,
        })
        schon.setdefault(xpub, set()).add(_utxo_schluessel(utxo))
    return funde


def schreibe_schaetze_in_cache(
    funde: list[dict],
    *,
    cache_dir: Path,
    vorhanden_je_xpub: dict[str, list[dict]],
    scan_end_je_xpub: dict[str, int | None],
    max_addresses_je_xpub: dict[str, int],
) -> None:
    """Sortiert die Funde in den bestehenden UTXO-Cache je Wallet ein."""
    from core.xpub_cache import save_xpub_utxo_cache

    je: dict[str, list[dict]] = {}
    for fund in funde:
        je.setdefault(str(fund["xpub"]), []).append(fund["utxo"])
    for xpub, neu in je.items():
        bisher = list(vorhanden_je_xpub.get(xpub) or [])
        save_xpub_utxo_cache(
            xpub,
            merge_utxos(bisher, neu),
            cache_dir,
            "scantxoutset",
            scan_end_index=scan_end_je_xpub.get(xpub),
            max_addresses=max_addresses_je_xpub.get(xpub) or 50,
            extra_scanned=[str(f["address"]) for f in funde if f["xpub"] == xpub],
        )


def core_fuer_scantxoutset(env: dict[str, str]):
    """
    Verbundene Core-Quelle mit scantxoutset, sonst None.

    Bevorzugt den UTXO-RPC-Slot, sonst den Lookup-Core.
    """
    from core.bitcoind_rpc import stelle_utxo_core_client_bereit, verify_core_rpc

    client = stelle_utxo_core_client_bereit(env, timeout=20.0)
    if client is None:
        return None
    try:
        verify_core_rpc(client)
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        return None
    return client


def jage_verlorene_schaetze(
    *,
    env: dict[str, str],
    wallets: list[Any],
    wallet_ctx: Any,
    cache_dir: Path,
    on_log: LogFn | None = None,
    on_progress: Callable[..., None] | None = None,
    raise_if_cancelled: Callable[[], None] | None = None,
) -> list[dict]:
    """
    Sucht und speichert UTXOs außerhalb des normalen Suchfensters.

    Wirft, wenn kein Core mit scantxoutset verbunden ist.
    """
    from core.bitcoind_rpc import scantxoutset_utxos
    from core.wallet_context import _register_wallet_address
    from core.xpub_cache import load_xpub_cache_entry

    def log(text: str) -> None:
        if on_log:
            on_log(text)
        if on_progress:
            try:
                on_progress(text, sofort=True)
            except TypeError:
                on_progress(text)

    def brich_ab() -> None:
        if raise_if_cancelled:
            raise_if_cancelled()

    if not wallets:
        log("Keine Wallets — nichts zu suchen.")
        return []

    client = core_fuer_scantxoutset(env)
    if client is None:
        raise RuntimeError(
            "Keine verbundene Bitcoin-Core-Quelle mit scantxoutset."
        )

    schluessel: list[str] = []
    start_by: dict[str, int] = {}
    end_by: dict[str, int] = {}
    type_by: dict[str, str] = {}
    name_by: dict[str, str] = {}
    max_by: dict[str, int] = {}
    scan_end_by: dict[str, int | None] = {}
    vorhanden: dict[str, list[dict]] = {}

    for eintrag in wallets:
        brich_ab()
        key = eintrag.analyse_schluessel
        name = eintrag.display_name
        cap = _scan_index_cap_per_chain(
            key, wallet_ctx, int(eintrag.max_addresses),
        )
        cache = load_xpub_cache_entry(key, cache_dir)
        cache_end = cache["scan_end_index"] if cache else None
        start, ende = suchfenster(cap, cache_scan_end=cache_end)
        schluessel.append(key)
        start_by[key] = start
        end_by[key] = ende
        type_by[key] = (
            wallet_ctx.script_type_for(key) if wallet_ctx is not None else "auto"
        )
        name_by[key] = name
        max_by[key] = int(eintrag.max_addresses)
        scan_end_by[key] = cache_end
        vorhanden[key] = list(cache["utxos"]) if cache else []
        log(
            f"{name}: scantxoutset ab Index #{start} "
            f"({SCHATZ_WEITE} weitere je Kette, normal bis #{start - 1})…"
        )

    brich_ab()
    try:
        roh, _tip = scantxoutset_utxos(
            client,
            schluessel,
            max_index_by_key=end_by,
            range_start_by_key=start_by,
            script_type_by_key=type_by,
            on_log=log,
            on_progress=on_progress,
        )
    finally:
        try:
            client.close()
        except Exception:
            pass

    brich_ab()
    zuordnung: dict[str, dict[str, Any]] = {}
    for key in schluessel:
        brich_ab()
        adressen = adressen_im_fenster(
            key, start_by[key], end_by[key] + 1, type_by.get(key),
        )
        for adresse, (chain, index) in adressen.items():
            zuordnung.setdefault(adresse, {
                "xpub": key,
                "wallet": name_by[key],
                "chain": chain,
                "index": index,
                "fenster_bis": start_by[key],
            })

    funde = sammle_schaetze(
        roh, zuordnung=zuordnung, vorhanden_je_xpub=vorhanden,
    )
    if not funde:
        return []

    schreibe_schaetze_in_cache(
        funde,
        cache_dir=cache_dir,
        vorhanden_je_xpub=vorhanden,
        scan_end_je_xpub=scan_end_by,
        max_addresses_je_xpub=max_by,
    )
    if wallet_ctx is not None:
        for fund in funde:
            _register_wallet_address(wallet_ctx, fund["xpub"], fund["address"])
    for fund in funde:
        log(fund["hinweis"])
    return [
        {k: v for k, v in fund.items() if k != "utxo"}
        for fund in funde
    ]
