"""
Seitenweise Listen für Wallet- und Herkunftsansicht (ISSUES P2).

``?seite=1`` schaltet ``/api/utxos`` und ``/api/wallets/<id>/utxos`` in den
Fenster-Modus: sortiert und gefiltert wird auf den Rohdaten aus dem Cache,
angereichert (Herkunfts-Meta, Börsen, Sanktionsmarke) nur das Fenster.
Ohne ``seite`` bleibt die bisherige Antwort (alles auf einmal).

Parameter: ``teil`` = ``bestand`` (Default) | ``verlauf`` (Bereits ausgegeben),
``modus`` = ``gruppen`` | ``volume-desc`` | ``age-desc`` | ``age-asc``,
``offset``, ``limit``, ``sort`` (``betrag``/``datum``), ``q`` (+ ``q_nach``/
``q_vor`` aus der Browser-Zeitzone), ``lang`` (für Soft-Labels im Filter).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core import listen_fenster as lf

_MODI = ("gruppen", "volume-desc", "age-desc", "age-asc")


def ist_fenster(query: dict) -> bool:
    return lf.query_text(query, "seite") == "1"


#: Label-Auszüge für die Stichwortsuche je (Teil, Sprache, Cache-Abdruck).
#: Spart das Anreichern aller Einträge bei jeder Suche (Schritt 6).
_LABEL_CACHES = lf.KleinCache(4)


def cache_abdruck(state: Any, *, preise: bool = False) -> str:
    """
    Abdruck aller Caches, aus denen Listen und Steuer lesen (ohne Inhalte).

    UTXO-/Verlaufs-Cache Datei für Datei; Herkunftsbäume, Ingress und
    Tx-Cache über den Ordner-mtime (dort wird nur per ``tmp.replace``
    geschrieben). Dazu Börsen-/Label-Bestand, eigene Adressen und die
    Einstellungen (Wallets, Steuer) aus der ``.env``.
    """
    import labels as labels_mod

    from core import exchange_reports, xpub_cache

    imm = state.immutable_cache_dir
    ordner = []
    if imm:
        for teil in ("utxo_trace", xpub_cache.UTXO_INGRESS_CACHE_SUBDIR,
                     xpub_cache.TX_IMMUTABLE_CACHE_SUBDIR):
            ordner.append(Path(imm) / teil)
    dateien = [state.cache_dir]
    try:
        dateien.append(exchange_reports.verzeichnis())
    except Exception:
        pass
    try:
        dateien.append(labels_mod._verzeichnis(None))
    except Exception:
        pass
    if preise and imm:
        dateien.append(Path(imm) / "btc_price")
    abdruck = lf.datei_abdruck(dateien=dateien, ordner=ordner)
    ctx = state.wallet_ctx_fuer_ansicht()
    try:
        env = sorted((state.env().values() or {}).items())
    except Exception:
        env = []
    roh = "|".join((
        abdruck,
        str(len(getattr(ctx, "address_to_wallet", None) or {})),
        str(len(xpub_cache._immutable_tx_memory)),
        repr(env),
        ",".join(str(e.analyse_schluessel) for e in getattr(state, "analyse_entries", []) or []),
    ))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def _verlauf_roh(state: Any, entries) -> tuple[list[dict], bool]:
    """
    Ausgegebene Outputs roh aus dem Verlaufs-Cache (wie ``_verlaufs_anhang``)
    und ob überhaupt ein Verlauf vorliegt.
    """
    from server import main

    roh: list[dict] = []
    hat_verlauf = False
    for entry in entries:
        gespeichert = main.load_xpub_verlauf_cache(entry.analyse_schluessel, state.cache_dir)
        for e in gespeichert or []:
            if not isinstance(e, dict):
                continue
            hat_verlauf = True
            if not e.get("spent"):
                continue
            kopie = dict(e)
            if entry.display_name and not kopie.get("_wallet_fallback"):
                kopie["_wallet_fallback"] = entry.display_name
            roh.append(kopie)
    return roh, hat_verlauf


def _formen(fenster: lf.Fenster, schnitt: dict, sort: str) -> tuple[list, list]:
    from server import utxos_mod

    if schnitt["art"] == "gruppen":
        adressen: list[dict] = []
        for g in schnitt["items"]:
            adressen += utxos_mod.group_by_address(
                [fenster.fertig(e) for e in g["utxos"]], sort=sort,
            )
        return [u for g in adressen for u in g["utxos"]], adressen
    return [fenster.fertig(e) for e in schnitt["items"]], []


def fenster_antwort(
    state: Any,
    *,
    entries,
    gesammelt: list[dict],
    query: dict,
    mempool: bool,
    xpub: str | None = None,
) -> dict:
    from server import (
        _eigene_adressen,
        _mit_mempool_pending,
        _sortierung,
        _verlaufs_anhang,
        sanctions_mod,
        utxos_mod,
    )
    from core import xpub_cache

    sort = _sortierung(query)
    teil = "verlauf" if lf.query_text(query, "teil") == "verlauf" else "bestand"
    modus = lf.query_text(query, "modus", "gruppen")
    if modus not in _MODI:
        modus = "gruppen"
    offset = lf.query_int(query, "offset", 0)
    limit = lf.query_int(query, "limit", lf.SEITEN_GROESSEN[0])
    filt = lf.filter_aus_query(query)
    lang = lf.query_text(query, "lang", "de")
    own = _eigene_adressen(state)
    imm = state.immutable_cache_dir

    # „Bereits ausgegeben“ ist der Verlaufs-Cache. Ein Electrs-Mempool-Check
    # ändert diese Liste nicht und kostet sonst den Verbindungsversuch, bevor
    # die erste Seite überhaupt geschnitten wird.
    if mempool and teil != "verlauf":
        # limit=0: nur Summen, kein Eintrag wird angereichert; Pending/
        # bestätigte Spends kommen angereichert zurück (``vorab``).
        anhang = _verlaufs_anhang(state, entries, limit=0, sort=sort)
        gesammelt, anhang = _mit_mempool_pending(
            state, gesammelt, anhang, limit=None, sort=sort, xpub=xpub,
        )
        roh_verlauf, _ = _verlauf_roh(state, entries)
    else:
        roh_verlauf, hat_verlauf = _verlauf_roh(state, entries)
        anhang = {
            "verlauf": {
                "total_count": len(roh_verlauf),
                "total_sats": sum(lf.wert(e) for e in roh_verlauf),
            },
            "hat_verlauf": hat_verlauf,
        }
    verlauf_alt = anhang.get("verlauf") or {}
    vorab = [u for u in (verlauf_alt.get("utxos") or []) if isinstance(u, dict)]
    verlauf_meta = {
        "total_count": int(verlauf_alt.get("total_count") or 0),
        "total_sats": int(verlauf_alt.get("total_sats") or 0),
        "pending_count": int(verlauf_alt.get("pending_count") or 0),
        "shown_count": 0,
        "utxos": [],
        "addresses": [],
    }
    ergebnis: dict = {
        "total_count": len(gesammelt),
        "total_sats": sum(lf.wert(u) for u in gesammelt if not u.get("spending_pending")),
        "pending_spending_count": sum(1 for u in gesammelt if u.get("spending_pending")),
        # Über den ganzen Bestand, nicht nur das Fenster: Die FIFO-Spend-Leiste
        # zieht diese UTXOs von den grünen sats ab (Funds unterwegs).
        "pending_spending_keys": sorted(
            utxos_mod.utxo_key(u) for u in gesammelt if u.get("spending_pending")
        ),
        "pending_receive_count": sum(1 for u in gesammelt if u.get("receive_pending")),
        "pending_spending_internal": any(
            u.get("spending_pending") and u.get("spending_internal") for u in gesammelt
        ),
        # Adressen mit Bestand (ungefiltert) — Kopfzeile der Wallet-Ansicht.
        "adressen_count": len({u.get("address", "") for u in gesammelt}),
        "hat_verlauf": bool(anhang.get("hat_verlauf")),
        "sort": sort,
        "teil": teil,
    }
    if anhang.get("pending_spends") is not None:
        ergebnis["pending_spends"] = anhang.get("pending_spends")

    if teil == "verlauf":
        roh = roh_verlauf
        xpub_cache.enrich_utxos_with_block_times(roh, imm)
        fenster = lf.Fenster(
            lambda e: utxos_mod.verlauf_eintrag_als_dict(
                e, wallet=state.wallet_ctx_fuer_ansicht(),
                immutable_cache_dir=imm, own_addresses=own,
            ),
            lang=lang,
            label_cache=_label_cache(state, "verlauf", lang, filt),
        )
        schnitt = fenster.schneide(
            roh, sort=sort, art="verlauf", modus=modus, f=filt,
            offset=offset, limit=limit, vorab=vorab,
        )
        _label_cache_nachtragen(state, "verlauf", lang, fenster._label_cache)
        utxos, adressen = _formen(fenster, schnitt, sort)
        verlauf_meta.update({
            "shown_count": len(utxos), "utxos": utxos, "addresses": adressen,
            "fenster": _fenster_meta(schnitt, offset, limit, modus),
        })
        ergebnis["shown_count"] = 0
        ergebnis["utxos"] = []
        ergebnis["addresses"] = []
    else:
        fenster = lf.Fenster(
            lambda u: utxos_mod.utxo_as_dict(
                u, wallet=state.wallet_ctx_fuer_ansicht(),
                immutable_cache_dir=imm, own_addresses=own,
            ),
            lang=lang,
            label_cache=_label_cache(state, "bestand", lang, filt),
        )
        schnitt = fenster.schneide(
            gesammelt, sort=sort, art="bestand", modus=modus, f=filt,
            offset=offset, limit=limit,
        )
        _label_cache_nachtragen(state, "bestand", lang, fenster._label_cache)
        utxos, adressen = _formen(fenster, schnitt, sort)
        # Sanktionsbefund über den ganzen Bestand, Marke nur am Fenster.
        ergebnis["sanctions"] = sanctions_mod.markiere_utxos(
            [{"address": u.get("address", ""), "value_sats": lf.wert(u)} for u in gesammelt],
            cache_dir=state.sanctions_dir,
        )
        gelistet = sanctions_mod.lade_adressen(state.sanctions_dir)
        for u in utxos:
            u["flagged"] = bool(gelistet) and u.get("address") in gelistet
        ergebnis.update({
            "shown_count": len(utxos),
            "shown_sats": sum(u["value_sats"] for u in utxos if not u.get("spending_pending")),
            "utxos": utxos,
            "addresses": adressen,
            "fenster": _fenster_meta(schnitt, offset, limit, modus),
        })
    ergebnis["verlauf"] = verlauf_meta
    return ergebnis


def _label_cache(state: Any, teil: str, lang: str, filt: dict) -> dict | None:
    """Label-Auszüge nur, wenn gesucht wird — sonst kein Abdruck nötig."""
    if not filt.get("terms"):
        return None
    schluessel = (teil, lang, cache_abdruck(state))
    cache = _LABEL_CACHES.hole(schluessel)
    if cache is None:
        cache = {}
        _LABEL_CACHES.lege(schluessel, cache)
    return cache


def _label_cache_nachtragen(state: Any, teil: str, lang: str, cache: dict | None) -> None:
    """
    Nach dem Anreichern kennt das Wallet ggf. mehr eigene Adressen (Seed aus
    den Caches) — derselbe Stand gilt dann unter dem neuen Abdruck weiter.
    """
    if cache is None:
        return
    schluessel = (teil, lang, cache_abdruck(state))
    if _LABEL_CACHES.hole(schluessel) is None:
        _LABEL_CACHES.lege(schluessel, cache)


def _fenster_meta(schnitt: dict, offset: int, limit: int, modus: str) -> dict:
    return {
        "offset": max(0, int(offset or 0)),
        "limit": max(0, min(int(limit or 0), lf.MAX_LIMIT)),
        "total": schnitt["total"],
        "art": schnitt["art"],
        "modus": modus,
    }
