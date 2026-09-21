"""
Adressen für Export-Verlauf nachziehen (Electrs/Fulcrum).

Sparrow-Tx-CSV liefert oft nur Txid/Betrag. Mit angeschlossenem Electrs holen
wir die Tx und matchen eigene Adressen (Deskriptor-Ableitung).
"""
from __future__ import annotations

from typing import Any, Callable

#: Ab dieser Zahl eindeutiger Txids fragt die UI nach.
NACHZIEHEN_AUTO_MAX = 100


def verlauf_ohne_adresse(verlauf: list[dict] | None) -> list[dict]:
    """Einträge ohne nutzbare Adresse."""
    out: list[dict] = []
    for e in verlauf or []:
        if not isinstance(e, dict):
            continue
        if str(e.get("address") or "").strip():
            continue
        txid = str(e.get("txid") or "").strip().lower()
        if len(txid) != 64:
            continue
        out.append(e)
    return out


def unique_txids(eintraege: list[dict]) -> list[str]:
    gesehen: set[str] = set()
    out: list[str] = []
    for e in eintraege:
        txid = str(e.get("txid") or "").strip().lower()
        if len(txid) != 64 or txid in gesehen:
            continue
        gesehen.add(txid)
        out.append(txid)
    return out


def sats_from_vout_value(wert: Any) -> int | None:
    """Electrs/Core: BTC-float oder sats-int."""
    if wert is None:
        return None
    try:
        if isinstance(wert, int):
            return wert
        f = float(wert)
        # typisch BTC < 21000000
        if abs(f) < 21_000_000 and ("." in str(wert) or abs(f) < 1 or f != int(f)):
            return int(round(f * 100_000_000))
        return int(f)
    except (TypeError, ValueError):
        return None


def eigene_adressen_mengen(
    entry,
    *,
    wallet_ctx=None,
) -> set[str]:
    """
    Empfang+Change bis max_addresses für Match gegen Tx-Outputs/Prevouts.
    """
    import main
    from core import config as config_mod

    addrs: set[str] = set()
    max_a = max(2, int(getattr(entry, "max_addresses", 50) or 50))
    desc = (getattr(entry, "descriptor", None) or "").strip()
    if desc:
        try:
            for a in main.derive_descriptor_addresses(desc, max_addresses=max_a) or []:
                if a:
                    addrs.add(str(a))
            # Change-Zweig falls multipath nicht in derive steckt — oft <0;1>
            # ist schon drin. Zusätzlich WalletContext-Cache.
        except Exception:
            pass
    else:
        xpub = getattr(entry, "analyse_schluessel", None) or getattr(entry, "xpub", "")
        script = getattr(entry, "script_type", "auto") or "auto"
        try:
            for a in main.derive_addresses(xpub, "receive", max_a, script) or []:
                if a:
                    addrs.add(str(a))
            for a in main.derive_addresses(xpub, "change", max_a, script) or []:
                if a:
                    addrs.add(str(a))
        except Exception:
            pass

    if wallet_ctx is not None:
        try:
            # bereits geseedete Adressen dieses Wallets
            label = entry.display_name
            for addr, name in (getattr(wallet_ctx, "address_to_wallet", {}) or {}).items():
                if name == label and addr:
                    addrs.add(str(addr))
        except Exception:
            pass
    return addrs


def adresse_fuer_tx_eintrag(
    eintrag: dict,
    tx: dict,
    *,
    own: set[str],
    get_tx: Callable[[str], dict | None] | None = None,
) -> tuple[str, int | None]:
    """
    Bestimme eigene Adresse (+ optional vout) zu einem Verlaufs-Eintrag.

    Rückgabe ``(address, vout_or_None)``. Leere address = kein Treffer.
    """
    from fulcrum import _vout_addresses

    value = eintrag.get("value")
    try:
        want_sats = int(value) if value is not None else None
    except (TypeError, ValueError):
        want_sats = None

    spent = bool(eintrag.get("spent"))

    if spent and get_tx is not None:
        # Ausgabe: unsere Adresse steckt im Prevout der Inputs.
        for vin in tx.get("vin") or []:
            if not isinstance(vin, dict):
                continue
            prev_txid = str(vin.get("txid") or "").strip().lower()
            try:
                prev_vout = int(vin.get("vout"))
            except (TypeError, ValueError):
                continue
            if len(prev_txid) != 64:
                continue
            try:
                prev = get_tx(prev_txid)
            except Exception:
                prev = None
            if not isinstance(prev, dict):
                continue
            vouts = prev.get("vout") or []
            if prev_vout < 0 or prev_vout >= len(vouts):
                continue
            vout = vouts[prev_vout]
            if not isinstance(vout, dict):
                continue
            if want_sats is not None:
                vs = sats_from_vout_value(vout.get("value"))
                if vs is not None and vs != want_sats:
                    # Wert-Mismatch: trotzdem Adresse merken als Kandidat
                    pass
            for addr in _vout_addresses(vout):
                if addr in own:
                    return addr, prev_vout

    # Empfang oder Fallback: eigener Output in dieser Tx
    kandidaten: list[tuple[str, int, int | None]] = []
    for i, vout in enumerate(tx.get("vout") or []):
        if not isinstance(vout, dict):
            continue
        vs = sats_from_vout_value(vout.get("value"))
        for addr in _vout_addresses(vout):
            if addr not in own:
                continue
            kandidaten.append((addr, i, vs))
    if not kandidaten:
        return "", None
    if want_sats is not None:
        treffer = [k for k in kandidaten if k[2] == want_sats]
        if treffer:
            return treffer[0][0], treffer[0][1]
    return kandidaten[0][0], kandidaten[0][1]


def _prefetch_tx_map(
    txids: list[str],
    *,
    get_tx: Callable[[str], dict | None] | None,
    fulcrum_client=None,
    immutable_cache_dir=None,
    on_progress: Callable[[str], None] | None = None,
    raise_if_cancelled: Callable[[], None] | None = None,
) -> dict[str, dict]:
    """
    Tx-Map aufbauen: Immutable-Cache zuerst, Rest per Electrs-Batch (Tor) oder
    einzeln über ``get_tx``.
    """
    import main
    from fulcrum import fetch_txs_fulcrum_batch

    tx_map: dict[str, dict] = {}
    fehlend: list[str] = []
    cache_root = immutable_cache_dir
    for t in txids:
        if raise_if_cancelled:
            raise_if_cancelled()
        if cache_root is not None:
            try:
                cached = main.load_cached_tx(t, cache_root)
            except Exception:
                cached = None
            if isinstance(cached, dict):
                tx_map[t] = cached
                continue
        fehlend.append(t)

    if not fehlend:
        return tx_map

    if fulcrum_client is not None:
        def _prog(text: str, *, sofort: bool = True) -> None:
            if not on_progress:
                return
            try:
                on_progress(text, sofort=sofort)
            except TypeError:
                on_progress(text)

        if fehlend:
            _prog(
                f"Adressen nachziehen: hole {len(fehlend)} Tx "
                f"({len(txids) - len(fehlend)} aus Cache)…",
                sofort=True,
            )
        geholt = fetch_txs_fulcrum_batch(
            fulcrum_client,
            fehlend,
            on_progress=_prog,
        )
        for t, tx in geholt.items():
            tx_map[t] = tx
            if cache_root is not None:
                try:
                    main.save_cached_tx(t, tx, cache_root, "fulcrum_batch")
                except Exception:
                    pass
        return tx_map

    # Fallback: serielles get_tx
    for i, t in enumerate(fehlend, start=1):
        if raise_if_cancelled:
            raise_if_cancelled()
        if on_progress and (i == 1 or i == len(fehlend) or i % 10 == 0):
            on_progress(f"Adressen nachziehen: Tx {i}/{len(fehlend)}…")
        if get_tx is None:
            break
        try:
            tx = get_tx(t)
        except Exception:
            tx = None
        if isinstance(tx, dict):
            tx_map[t] = tx
    return tx_map


def nachziehen_verlauf_adressen(
    verlauf: list[dict],
    *,
    own: set[str],
    get_tx: Callable[[str], dict | None] | None = None,
    fulcrum_client=None,
    immutable_cache_dir=None,
    on_progress: Callable[[str], None] | None = None,
    raise_if_cancelled: Callable[[], None] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """
    Schreibt Adressen in Kopien der Einträge ohne Adresse.

    Mit ``fulcrum_client``: Electrs-**Batch** (Tor) für Tx-Abruf + zweiter
    Batch für Prevouts bei Ausgaben. Sonst serielles ``get_tx``.

    Rückgabe ``(neuer_verlauf, stats)``.
    """
    stats = {
        "filled": 0,
        "failed": 0,
        "skipped": 0,
        "txids": 0,
        "batched": 0,
        "prev_txids": 0,
    }
    if not own:
        stats["skipped"] = len(verlauf_ohne_adresse(verlauf))
        return list(verlauf), stats

    ziel = verlauf_ohne_adresse(verlauf)
    txids = unique_txids(ziel)
    stats["txids"] = len(txids)
    if not txids:
        return list(verlauf), stats

    tx_map = _prefetch_tx_map(
        txids,
        get_tx=get_tx,
        fulcrum_client=fulcrum_client,
        immutable_cache_dir=immutable_cache_dir,
        on_progress=on_progress,
        raise_if_cancelled=raise_if_cancelled,
    )
    if fulcrum_client is not None and getattr(
        fulcrum_client, "tor_batch_sinnvoll", lambda _n: False
    )(len(txids)):
        stats["batched"] = 1

    # Prevouts für Spends in einem zweiten Rutsch holen (Batch).
    prev_ids: list[str] = []
    for e in ziel:
        if not e.get("spent"):
            continue
        t = str(e.get("txid") or "").strip().lower()
        tx = tx_map.get(t)
        if not isinstance(tx, dict):
            continue
        for vin in tx.get("vin") or []:
            if not isinstance(vin, dict):
                continue
            pt = str(vin.get("txid") or "").strip().lower()
            if len(pt) == 64 and pt not in tx_map:
                prev_ids.append(pt)
    prev_ids = unique_txids([{"txid": p} for p in prev_ids])
    stats["prev_txids"] = len(prev_ids)
    if prev_ids:
        def _prog_prev(text: str, *, sofort: bool = True) -> None:
            if not on_progress:
                return
            try:
                on_progress(text, sofort=sofort)
            except TypeError:
                on_progress(text)

        _prog_prev(
            f"Adressen nachziehen: {len(prev_ids)} Prevout-Tx…",
            sofort=True,
        )
        prev_map = _prefetch_tx_map(
            prev_ids,
            get_tx=get_tx,
            fulcrum_client=fulcrum_client,
            immutable_cache_dir=immutable_cache_dir,
            on_progress=on_progress,
            raise_if_cancelled=raise_if_cancelled,
        )
        tx_map.update(prev_map)

    def _tx(txid: str) -> dict | None:
        return tx_map.get(str(txid or "").strip().lower())

    fill_map: dict[tuple[str, int, bool], tuple[str, int | None]] = {}
    for e in ziel:
        txid = str(e.get("txid") or "").strip().lower()
        tx = _tx(txid)
        if not isinstance(tx, dict):
            continue
        key = (txid, int(e.get("vout") or 0), bool(e.get("spent")))
        if key in fill_map:
            continue
        addr, vout = adresse_fuer_tx_eintrag(
            e, tx, own=own, get_tx=_tx if e.get("spent") else None,
        )
        if addr:
            fill_map[key] = (addr, vout)

    neu: list[dict] = []
    for e in verlauf:
        if not isinstance(e, dict):
            continue
        kopie = dict(e)
        if str(kopie.get("address") or "").strip():
            neu.append(kopie)
            continue
        txid = str(kopie.get("txid") or "").strip().lower()
        key = (txid, int(kopie.get("vout") or 0), bool(kopie.get("spent")))
        treffer = fill_map.get(key)
        if treffer:
            kopie["address"] = treffer[0]
            if treffer[1] is not None and not kopie.get("spent"):
                kopie["vout"] = treffer[1]
            stats["filled"] += 1
        else:
            if txid:
                stats["failed"] += 1
            else:
                stats["skipped"] += 1
        neu.append(kopie)
    return neu, stats
