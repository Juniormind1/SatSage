"""UTXO-/Analyse-Cache-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


def _cache_utxo_schluessel(eintrag: dict) -> tuple[str, int] | None:
    txid = eintrag.get("txid")
    if not txid:
        return None
    try:
        return str(txid), int(eintrag.get("vout", 0))
    except (TypeError, ValueError):
        return None


def _wallet_cache_pfade(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
) -> list[Path]:
    """
    Dateien, die zum Analyse-Cache dieses Wallets gehören.

    *mit_alter*: Altersdatei mitnehmen — bei Wallet-Entfernung ja (sonst
    bleibt sie verwaist), beim normalen Cache-Löschen nein (First-seen bleibt).
    """
    from server import main, trace_cache, utxos_mod

    schluessel = entry.analyse_schluessel
    pfade: list[Path] = []
    for pfad in (
        main._xpub_cache_path(schluessel, state.cache_dir),
        main._xpub_verlauf_cache_path(schluessel, state.cache_dir),
    ):
        if pfad.is_file():
            pfade.append(pfad)
    if mit_alter:
        alter = main._xpub_alter_path(schluessel, state.cache_dir)
        if alter.is_file():
            pfade.append(alter)

    utxos = utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or []
    verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or []
    gesehen: set[tuple[str, int]] = set()
    for eintrag in list(utxos) + list(verlauf):
        paar = _cache_utxo_schluessel(eintrag)
        if paar is None or paar in gesehen:
            continue
        gesehen.add(paar)
        txid, vout = paar
        for pfad in (
            main._utxo_ingress_cache_path(txid, vout, state.immutable_cache_dir),
            trace_cache.pfad(txid, vout, state.immutable_cache_dir),
        ):
            if pfad is not None and pfad.is_file():
                pfade.append(pfad)
    return pfade


def _wallet_cache_umfang(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
) -> dict:
    from server import _datei_groesse, format_dateigroesse, wallets_mod

    pfade = _wallet_cache_pfade(state, entry, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "dateien": len(pfade),
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _wallet_cache_loeschen(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
    on_log=None,
) -> dict:
    """Löscht den Analyse-Cache eines Wallets. Siehe ``_wallet_cache_pfade``."""
    from server import _datei_groesse, _datei_loeschen, format_dateigroesse, wallets_mod

    name = entry.display_name or wallets_mod.eintrag_id(entry)

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    _log(f"Lösche {name}")
    # Teuer bei Import-Wallets: UTXO+Verlauf laden, je Tx Ingress/Trace-Pfad.
    pfade = _wallet_cache_pfade(state, entry, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    utxo_n = 0
    verlauf_n = 0
    herkunft_n = 0
    alter_n = 0
    n_pfade = len(pfade)
    for i, pfad in enumerate(pfade, start=1):
        if pfad.parent == state.cache_dir:
            if pfad.name.endswith("_verlauf.json"):
                verlauf_n += _datei_loeschen(pfad)
            elif pfad.name.endswith("_alter.json"):
                alter_n += _datei_loeschen(pfad)
            else:
                utxo_n += _datei_loeschen(pfad)
        else:
            herkunft_n += _datei_loeschen(pfad)
        # Fortschritt nur bei vielen Herkunftsdateien (sonst Rauschen).
        if n_pfade >= 50 and (i == 1 or i == n_pfade or i % 100 == 0):
            _log(f"Lösche {name}: Datei {i}/{n_pfade}…")
    _log("Löschen beendet")
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "dateien": utxo_n + verlauf_n + herkunft_n + alter_n,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
        "utxo_eintraege": utxo_n,
        "verlauf_eintraege": verlauf_n,
        "herkunft_eintraege": herkunft_n,
        "alter_eintraege": alter_n,
    }


def api_cache_leeren(state: AppState) -> dict:
    """
    Löscht den Analyse-Cache: UTXOs, Verlauf, Herkunftsbäume, Tx- und
    Block-Dateien. Sanktionslisten und Adress-Labels bleiben — die haben
    eigene Knöpfe.
    """
    from server import _ordner_leeren

    utxo = _ordner_leeren(state.cache_dir)
    unveraenderlich = _ordner_leeren(
        state.immutable_cache_dir,
        behalten=("p2p_headers.bin", "p2p_headers.bin.tmp"),
    )
    return {
        "ok": True,
        "utxo_eintraege": utxo,
        "immutable_eintraege": unveraenderlich,
    }


def _cache_kennung_hat_dateien(state: AppState, kennung: str) -> bool:
    base = state.cache_dir
    if not base.is_dir():
        return False
    for name in (
        f"{kennung}.json",
        f"{kennung}_verlauf.json",
        f"{kennung}_alter.json",
    ):
        if (base / name).is_file():
            return True
    return False


def _wallet_cache_pfade_kennung(
    state: AppState,
    kennung: str,
    *,
    mit_alter: bool = False,
) -> list[Path]:
    """Cache-Dateien zu einer 16-hex-Kennung (auch ohne WalletEntry)."""
    from server import main, trace_cache

    kid = (kennung or "").strip().lower()
    pfade: list[Path] = []
    base = state.cache_dir
    for name in (f"{kid}.json", f"{kid}_verlauf.json"):
        p = base / name
        if p.is_file():
            pfade.append(p)
    if mit_alter:
        alter = base / f"{kid}_alter.json"
        if alter.is_file():
            pfade.append(alter)

    orphan_refs: set[tuple[str, int]] = set()
    for p in list(pfade):
        orphan_refs |= _utxo_refs_aus_datei(p)
    noch_aktiv = _aktive_utxo_refs(state)
    for txid, vout in orphan_refs - noch_aktiv:
        for pfad in (
            main._utxo_ingress_cache_path(txid, vout, state.immutable_cache_dir),
            trace_cache.pfad(txid, vout, state.immutable_cache_dir),
        ):
            if pfad is not None and pfad.is_file():
                pfade.append(pfad)
    return pfade


def _wallet_cache_loeschen_kennung(
    state: AppState,
    kennung: str,
    *,
    name: str = "",
    mit_alter: bool = False,
    on_log=None,
) -> dict:
    from server import _datei_groesse, _datei_loeschen, format_dateigroesse

    anzeige = name or f"Cache {kennung[:8]}…"

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    _log(f"Lösche {anzeige}")
    pfade = _wallet_cache_pfade_kennung(state, kennung, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    utxo_n = 0
    verlauf_n = 0
    herkunft_n = 0
    alter_n = 0
    n_pfade = len(pfade)
    for i, pfad in enumerate(pfade, start=1):
        if pfad.parent == state.cache_dir:
            if pfad.name.endswith("_verlauf.json"):
                verlauf_n += _datei_loeschen(pfad)
            elif pfad.name.endswith("_alter.json"):
                alter_n += _datei_loeschen(pfad)
            else:
                utxo_n += _datei_loeschen(pfad)
        else:
            herkunft_n += _datei_loeschen(pfad)
        if n_pfade >= 50 and (i == 1 or i == n_pfade or i % 100 == 0):
            _log(f"Lösche {anzeige}: Datei {i}/{n_pfade}…")
    _log("Löschen beendet")
    return {
        "wallet_id": kennung,
        "wallet_name": anzeige,
        "dateien": utxo_n + verlauf_n + herkunft_n + alter_n,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
        "utxo_eintraege": utxo_n,
        "verlauf_eintraege": verlauf_n,
        "herkunft_eintraege": herkunft_n,
        "alter_eintraege": alter_n,
    }


#: utxo_cache/{16 hex}.json | _verlauf.json | _alter.json
_CACHE_DATEI_KENNUNG = re.compile(
    r"^([0-9a-f]{16})(?:_verlauf|_alter)?\.json$",
    re.IGNORECASE,
)


def _cache_datei_kennung(name: str) -> str | None:
    treffer = _CACHE_DATEI_KENNUNG.match(name or "")
    return treffer.group(1).lower() if treffer else None


def _aktive_cache_kennungen(state: AppState) -> set[str]:
    from server import main

    return {
        main._xpub_cache_key(entry.analyse_schluessel)
        for entry in state.entries
    }


def _utxo_refs_aus_datei(pfad: Path) -> set[tuple[str, int]]:
    """txid:vout aus einer UTXO- oder Verlaufs-JSON."""
    if not pfad.is_file():
        return set()
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return set()
    refs: set[tuple[str, int]] = set()
    if isinstance(roh, dict):
        eintraege = (
            roh.get("utxos")
            or roh.get("eintraege")
            or roh.get("entries")
            or []
        )
    elif isinstance(roh, list):
        eintraege = roh
    else:
        eintraege = []
    for eintrag in eintraege:
        if not isinstance(eintrag, dict):
            continue
        paar = _cache_utxo_schluessel(eintrag)
        if paar is not None:
            refs.add(paar)
    return refs


def _aktive_utxo_refs(state: AppState) -> set[tuple[str, int]]:
    from server import main, utxos_mod

    refs: set[tuple[str, int]] = set()
    for entry in state.entries:
        schluessel = entry.analyse_schluessel
        for liste in (
            utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or [],
            main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or [],
        ):
            for eintrag in liste:
                paar = _cache_utxo_schluessel(eintrag)
                if paar is not None:
                    refs.add(paar)
    return refs


def _unreferenzierte_cache_pfade(state: AppState) -> list[Path]:
    """
    Cache-Dateien ohne passendes Wallet in der .env.

    UTXO/Verlauf/Alter verwaisten Kennungen; Herkunft nur, wenn kein
    verbleibendes Wallet denselben Output noch referenziert.
    """
    from server import main, trace_cache

    aktiv = _aktive_cache_kennungen(state)
    cache_dir = state.cache_dir
    if not cache_dir.is_dir():
        return []

    pfade: list[Path] = []
    orphan_refs: set[tuple[str, int]] = set()
    for kind in cache_dir.iterdir():
        if not kind.is_file():
            continue
        kennung = _cache_datei_kennung(kind.name)
        if kennung is None or kennung in aktiv:
            continue
        pfade.append(kind)
        name = kind.name.lower()
        if name == f"{kennung}.json" or name.endswith("_verlauf.json"):
            orphan_refs |= _utxo_refs_aus_datei(kind)

    if orphan_refs:
        noch_aktiv = _aktive_utxo_refs(state)
        for txid, vout in orphan_refs - noch_aktiv:
            for pfad in (
                main._utxo_ingress_cache_path(
                    txid, vout, state.immutable_cache_dir
                ),
                trace_cache.pfad(txid, vout, state.immutable_cache_dir),
            ):
                if pfad is not None and pfad.is_file():
                    pfade.append(pfad)
    return pfade


def _unreferenzierter_cache_bericht(state: AppState) -> dict:
    from server import _datei_groesse, format_dateigroesse

    pfade = _unreferenzierte_cache_pfade(state)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    kennungen: dict[str, int] = {}
    for pfad in pfade:
        if pfad.parent == state.cache_dir:
            k = _cache_datei_kennung(pfad.name)
            if k:
                kennungen[k] = kennungen.get(k, 0) + 1
    return {
        "vorhanden": len(pfade) > 0,
        "dateien": len(pfade),
        "kennungen": len(kennungen),
        "bytes": bytes_anzahl,
        "groesse_mb": round(bytes_anzahl / (1024 * 1024), 3),
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def api_cache_unreferenziert(state: AppState) -> dict:
    """Stand der verwaisten Cache-Dateien (ohne Wallet in der .env)."""
    return _unreferenzierter_cache_bericht(state)


def api_cache_unreferenziert_loeschen(state: AppState) -> dict:
    """
    Löscht verwaiste Cache-Dateien. Kein Danger: ohne Wallet greift die
    Oberfläche sie ohnehin nicht mehr an.
    """
    from server import _datei_groesse, _datei_loeschen, format_dateigroesse

    pfade = _unreferenzierte_cache_pfade(state)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    geloescht = 0
    for pfad in pfade:
        geloescht += _datei_loeschen(pfad)
    return {
        "ok": True,
        "dateien": geloescht,
        "bytes": bytes_anzahl,
        "groesse_mb": round(bytes_anzahl / (1024 * 1024), 3),
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _cache_baum_stats(pfad: Path) -> dict:
    """Dateien und Bytes unter *pfad* (rekursiv). Fehlender Ordner → 0."""
    from server import format_dateigroesse

    dateien = 0
    bytes_anzahl = 0
    if not pfad.is_dir():
        return {
            "dateien": 0,
            "bytes": 0,
            "groesse_label": format_dateigroesse(0),
        }
    for wurzel, _dirs, namen in os.walk(pfad):
        for name in namen:
            kind = Path(wurzel) / name
            try:
                bytes_anzahl += int(kind.stat().st_size)
            except OSError:
                continue
            dateien += 1
    return {
        "dateien": dateien,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _cache_datei_stats(pfad: Path) -> dict:
    from server import _datei_groesse, format_dateigroesse

    groesse = _datei_groesse(pfad)
    return {
        "vorhanden": pfad.is_file(),
        "bytes": groesse,
        "groesse_label": format_dateigroesse(groesse),
    }


def _platte_cache_stats(cache_dir: Path) -> dict:
    """Belegung der Platte, auf der die Caches liegen (kein Zugriffszähler)."""
    from server import format_dateigroesse, main

    try:
        ziel = main._cache_disk_target(cache_dir)
        usage = shutil.disk_usage(ziel)
    except OSError:
        return {
            "free_bytes": None,
            "total_bytes": None,
            "free_ratio": None,
            "free_label": "—",
            "total_label": "—",
            "write_blocked": bool(main.is_cache_disk_write_blocked()),
            "ampel": "warn",
        }
    free = int(usage.free)
    total = int(usage.total)
    ratio = (free / total) if total > 0 else 0.0
    blocked = free < main.MIN_FREE_DISK_BYTES and ratio < main.MIN_FREE_DISK_RATIO
    if blocked or main.is_cache_disk_write_blocked():
        ampel = "krit"
    elif free < 2 * main.MIN_FREE_DISK_BYTES or ratio < 0.10:
        ampel = "warn"
    else:
        ampel = "gut"
    return {
        "free_bytes": free,
        "total_bytes": total,
        "free_ratio": round(ratio, 4),
        "free_label": format_dateigroesse(free),
        "total_label": format_dateigroesse(total),
        "write_blocked": bool(blocked or main.is_cache_disk_write_blocked()),
        "ampel": ampel,
        "schwelle_ratio": main.MIN_FREE_DISK_RATIO,
        "schwelle_bytes": main.MIN_FREE_DISK_BYTES,
    }


def _wallet_cache_belegung(state: AppState, entry) -> dict:
    """Belegung eines Wallets: Dateigrößen und Abdeckung, keine Hits."""
    from server import (
        _datei_groesse,
        _header_tip,
        format_dateigroesse,
        main,
        utxos_mod,
        wallets_mod,
    )

    schluessel = entry.analyse_schluessel
    zusammen = wallets_mod.summarize([entry], state.cache_dir)[0]
    utxo_pfad = main._xpub_cache_path(schluessel, state.cache_dir)
    verlauf_pfad = main._xpub_verlauf_cache_path(schluessel, state.cache_dir)
    alter_pfad = main._xpub_alter_path(schluessel, state.cache_dir)
    verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or []
    utxos = utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or []

    gesehen: set[tuple[str, int]] = set()
    herkunft_treffer = 0
    herkunft_bytes = 0
    for eintrag in list(utxos) + list(verlauf):
        paar = _cache_utxo_schluessel(eintrag)
        if paar is None or paar in gesehen:
            continue
        gesehen.add(paar)
        txid, vout = paar
        try:
            ingress = main._utxo_ingress_cache_path(
                txid, vout, state.immutable_cache_dir
            )
        except (TypeError, ValueError):
            continue
        if ingress.is_file():
            herkunft_treffer += 1
            herkunft_bytes += _datei_groesse(ingress)

    referenzen = len(gesehen)
    tip = _header_tip(state)
    scan_tip = zusammen.scan_tip_height
    tip_lag = None
    if tip is not None and scan_tip is not None:
        tip_lag = max(0, int(tip) - int(scan_tip))

    max_addr = int(entry.max_addresses or 0)
    scan_end = zusammen.scan_end_index
    gap_ratio = None
    if max_addr > 0 and scan_end is not None:
        try:
            gap_ratio = min(1.0, max(0.0, int(scan_end) / float(max_addr)))
        except (TypeError, ValueError):
            gap_ratio = None

    utxo_bytes = _datei_groesse(utxo_pfad)
    verlauf_bytes = _datei_groesse(verlauf_pfad)
    alter_bytes = _datei_groesse(alter_pfad)
    eigen_bytes = utxo_bytes + verlauf_bytes + alter_bytes + herkunft_bytes

    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "has_cache": zusammen.has_cache,
        "utxo_count": zusammen.utxo_count,
        "total_sats": zusammen.total_sats,
        "utxo_bytes": utxo_bytes,
        "verlauf_count": len(verlauf),
        "verlauf_bytes": verlauf_bytes,
        "alter_vorhanden": alter_pfad.is_file(),
        "alter_bytes": alter_bytes,
        "first_seen_height": zusammen.first_seen_height,
        "first_seen_ts": zusammen.first_seen_ts,
        "scan_end_index": scan_end,
        "max_addresses": max_addr,
        "gap_ratio": gap_ratio,
        "scan_tip_height": scan_tip,
        "header_tip": tip,
        "tip_lag": tip_lag,
        "herkunft_referenzen": referenzen,
        "herkunft_treffer": herkunft_treffer,
        "herkunft_bytes": herkunft_bytes,
        "herkunft_ratio": (
            round(herkunft_treffer / referenzen, 4) if referenzen else None
        ),
        "bytes": eigen_bytes,
        "groesse_label": format_dateigroesse(eigen_bytes),
    }


def api_cache_stats(state: AppState) -> dict:
    """
    Cache-Belegung fürs Dashboard (Größe/Abdeckung, keine Zugriffe).

    Pro Wallet und Summe; Schwellen für Platte und Flatfile-Warnung.
    """
    from server import _header_pfad, _header_tip, format_dateigroesse, main

    utxo = _cache_baum_stats(state.cache_dir)
    immutable = _cache_baum_stats(state.immutable_cache_dir)
    tx = _cache_baum_stats(state.immutable_cache_dir / main.TX_IMMUTABLE_CACHE_SUBDIR)
    ingress = _cache_baum_stats(
        state.immutable_cache_dir / main.UTXO_INGRESS_CACHE_SUBDIR
    )
    block_header = _cache_baum_stats(
        state.immutable_cache_dir / main.BLOCK_HEADER_CACHE_SUBDIR
    )
    headers = _cache_datei_stats(_header_pfad(state))
    price = _cache_baum_stats(state.immutable_cache_dir / "btc_price")
    external = _cache_datei_stats(state.cache_dir / "external_addresses.json")
    sanktionen_dir = state.sanctions_dir
    if sanktionen_dir is None:
        sanktionen_dir = state.cache_dir.parent / "sanctioned_cache"
    sanktionen = _cache_baum_stats(sanktionen_dir)

    schwelle = int(main._SQLITE_FLATFILE_HINT_THRESHOLD)
    tx_n = int(tx["dateien"])
    ingress_n = int(ingress["dateien"])
    if tx_n >= schwelle or ingress_n >= schwelle:
        flat_ampel = "krit"
    elif tx_n >= max(1000, schwelle // 5) or ingress_n >= max(1000, schwelle // 5):
        flat_ampel = "warn"
    else:
        flat_ampel = "gut"

    wallets = [_wallet_cache_belegung(state, e) for e in state.entries]
    summe = (
        int(utxo["bytes"])
        + int(immutable["bytes"])
        + int(sanktionen["bytes"])
    )
    platte = _platte_cache_stats(state.cache_dir)
    return {
        "ok": True,
        "platte": platte,
        "summe_bytes": summe,
        "summe_label": format_dateigroesse(summe),
        "utxo_cache": utxo,
        "immutable_cache": immutable,
        "tx": {**tx, "schwelle": schwelle, "ampel": flat_ampel},
        "utxo_ingress": {**ingress, "schwelle": schwelle, "ampel": flat_ampel},
        "block_header": block_header,
        "p2p_headers": {**headers, "tip": _header_tip(state)},
        "btc_price": price,
        "external_addresses": external,
        "sanctioned_cache": sanktionen,
        "wallets": wallets,
    }
