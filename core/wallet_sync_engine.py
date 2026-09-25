"""
Wallet Tip-Sync / Scan / Resolve.

Aus main.py ausgelagert (Slice 3 step 7 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.

httpserver/wallet_sync bleibt HTTP-Orchestrierung; diese Datei ist die Engine.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from display import abbrev_display

from core.derivation import (
    DEFAULT_MAX_ADDRESSES,
    derive_address_at_index,
    derive_addresses,
    derive_addresses_at_index,
)
from core.env_bootstrap import _load_dotenv
from core.chain_sources import _fulcrum_transport_ist_lan
from core.wallet_context import (
    MAX_TRACE_ADDRESS_SEARCH,
    WalletContext,
    _max_addresses_for_xpub,
    _seed_wallet_addresses_from_cache,
)
from core.xpub_cache import (
    SALDEN_CHECK_LOOKAHEAD,
    _address_known_in_cache,
    _describe_utxo_diff,
    _fetch_address_batch_utxos,
    _fetch_lookahead_utxos,
    _first_seen_label,
    _mark_address_scanned,
    _merge_utxo_lists,
    _merge_verlauf_eintraege,
    _prune_cached_utxos,
    _scan_tip_anheben,
    _verify_cached_utxo_set,
    _xpub_cache_path,
    first_seen_from_utxos,
    load_xpub_cache_entry,
    load_xpub_utxo_cache,
    load_xpub_verlauf_cache,
    load_xpub_verlauf_scan_meta,
    merke_bip158_verlauf,
    save_xpub_utxo_cache,
    save_xpub_verlauf_cache,
    schreibe_utxo_zwischenstand,
    xpub_first_seen,
)

if TYPE_CHECKING:
    pass

BIP44_GAP_LIMIT = 20


UTXO_SCAN_GAP_LIMIT = 100  # Wasabi/CoinJoin: Lücken >20 zwischen genutzten Indizes


def _merge_cached_utxos(
    xpubs: list[str],
    cached_by_xpub: dict[str, list[dict]],
    wallet: WalletContext | None = None,
    *,
    cache_dir: Path | None = None,
) -> list[dict]:
    _seed_wallet_addresses_from_cache(
        wallet,
        cached_by_xpub,
        cache_dir=cache_dir,
        xpubs=xpubs,
    )
    merged: list[dict] = []
    for xpub in xpubs:
        merged.extend(cached_by_xpub.get(xpub, []))
    return merged


def _scan_index_cap_per_chain(
    xpub: str,
    wallet: WalletContext | None,
    max_addresses: int,
) -> int:
    """Obergrenze Indizes pro Chain; Default nutzt Gap-Scan bis MAX_TRACE_ADDRESS_SEARCH."""
    configured = _max_addresses_for_xpub(xpub, wallet, max_addresses)
    if configured > DEFAULT_MAX_ADDRESSES:
        return configured // 2
    return MAX_TRACE_ADDRESS_SEARCH


def _collect_used_chain_indices_gap(
    xpub: str,
    change: int,
    max_index: int,
    gap_limit: int,
    address_has_received,
    *,
    start_index: int = 0,
    progress_label: str | None = None,
    on_progress=None,
) -> tuple[set[int], int]:
    """Gap-Walk: benutzte Indizes einer Chain (change=0/1)."""
    from display import is_list_abort_requested

    used: set[int] = set()
    gap = 0
    next_index = start_index
    for i in range(start_index, max_index):
        if is_list_abort_requested():
            break
        next_index = i + 1
        adressen = derive_addresses_at_index(xpub, change, i)
        if not adressen:
            break
        if any(address_has_received(a) for a in adressen):
            used.add(i)
            gap = 0
        else:
            gap += 1
            if gap >= gap_limit:
                break
        if progress_label and (i - start_index + 1) % 25 == 0:
            print(f"  {progress_label} Index #{i}…", flush=True)
        if on_progress:
            on_progress(f"Gap-Scan {progress_label or ''} Index #{i}…".replace("  ", " "))
    return used, next_index


def discover_wallet_scan_addresses(
    xpub: str,
    *,
    max_index_per_chain: int,
    gap_limit: int = UTXO_SCAN_GAP_LIMIT,
    start_index: int = 0,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
) -> tuple[set[str], int]:
    """
    Gap-Scan (Fulcrum): Adressen mit Historie (+ Gap-Puffer).
    Rückgabe: (adressen, scan_end_index für Light-Rescan).
    """
    if fulcrum is not None:
        from core.fulcrum_wallet import collect_used_chain_indices_fulcrum

        from display import is_list_abort_requested

        addresses: set[str] = set()
        scan_end_index = start_index
        gesamt_utxos: list[dict] = []

        def _kette_utxos(teil: list[dict]) -> None:
            if not on_utxos_update:
                return
            # Empfang + Change teilen sich den Zwischenstand.
            nonlocal gesamt_utxos
            gesamt_utxos = _merge_utxo_lists(gesamt_utxos, teil)
            on_utxos_update(list(gesamt_utxos))

        for change, label in ((0, "Empfang"), (1, "Change")):
            if is_list_abort_requested():
                break
            print(
                f"  Gap-Scan {label}-Chain "
                f"(ab Index #{start_index}, max #{max_index_per_chain - 1})...",
                flush=True,
            )
            if on_progress:
                on_progress(f"Gap-Scan {label}-Adressen…")
            used, next_index = collect_used_chain_indices_fulcrum(
                fulcrum,
                xpub,
                change,
                max_index_per_chain,
                gap_limit,
                derive_addresses_at_index,
                start_index=start_index,
                on_progress=on_progress,
                on_utxos_update=_kette_utxos if on_utxos_update else None,
                kette=label,
            )
            scan_end_index = max(scan_end_index, next_index)
            indices_to_derive: set[int] = set(used)
            if used:
                last_used = max(used)
                for i in range(
                    last_used + 1,
                    min(last_used + 1 + gap_limit, max_index_per_chain),
                ):
                    indices_to_derive.add(i)
            for i in sorted(indices_to_derive):
                for addr in derive_addresses_at_index(xpub, change, i):
                    addresses.add(addr)
            print(
                f"  → {label}: {len(used)} genutzte Indizes, "
                f"{len(indices_to_derive)} Adressen",
                flush=True,
            )
        return addresses, scan_end_index
    raise ValueError("fulcrum erforderlich für Gap-Scan")


def ermittle_first_seen(
    xpub: str,
    addresses,
    cache_dir: Path,
    fulcrum_client=None,
    *,
    on_progress=None,
    utxos: list[dict] | None = None,
) -> dict | None:
    """
    Erhebt das Wallet-Alter — einmalig, und nur wenn es noch fehlt.

    Die älteste Transaktion eines Wallets kann sich nicht mehr ändern; steht
    sie im Cache, wird nicht erneut gefragt. Ohne Electrum-Server: aus den
    gefundenen UTXOs (BIP-158), sonst leer bis zum nächsten Electrum-Scan.

    Kostet eine Abfrage je Adresse und läuft deshalb bewusst nur dieses eine
    Mal (Fulcrum).
    """
    vorhanden = xpub_first_seen(xpub, cache_dir)
    if vorhanden:
        return vorhanden

    aus_utxo = first_seen_from_utxos(utxos)
    if aus_utxo:
        print(
            f"  → Wallet erstmals benutzt: {_first_seen_label(aus_utxo)}",
            flush=True,
        )
        return aus_utxo

    if fulcrum_client is None or not addresses:
        return None

    if on_progress:
        try:
            on_progress("Ermittle Wallet-Alter…", sofort=True)
        except TypeError:
            on_progress("Ermittle Wallet-Alter…")

    try:
        from core.fulcrum_wallet import first_seen_fulcrum

        ergebnis = first_seen_fulcrum(
            fulcrum_client, sorted(addresses), on_progress=on_progress
        )
    except Exception:
        return None
    if ergebnis:
        print(
            f"  → Wallet erstmals benutzt: {_first_seen_label(ergebnis)}",
            flush=True,
        )
    return ergebnis


def resolve_wallet_verlauf(
    xpubs: list[str],
    fetch_wallet_history,
    cache_dir: Path,
    wallet: "WalletContext | None" = None,
) -> dict[str, list[dict]]:
    """
    Erhebt den Verlauf je XPUB und legt ihn ab.

    Je XPUB werden nur dessen eigene Adressen abgefragt. Nach jeder Adresse
    Zwischenstand speichern; nach Abbruch/Timeout setzt der nächste Lauf bei
    denselben geplanten Adressen fort.
    """
    ergebnis: dict[str, list[dict]] = {}
    for xpub in xpubs:
        adressen = sorted({
            adresse
            for adresse, zugehoerig in (wallet.address_to_xpub if wallet else {}).items()
            if zugehoerig == xpub
        })
        if not adressen:
            ergebnis[xpub] = load_xpub_verlauf_cache(xpub, cache_dir) or []
            continue

        bisher = load_xpub_verlauf_cache(xpub, cache_dir) or []
        meta = load_xpub_verlauf_scan_meta(xpub, cache_dir)
        geplant = list(adressen)
        skip: list[str] = []
        if (
            meta.get("incomplete")
            and meta.get("planned_addresses") == geplant
            and meta.get("scanned_addresses")
        ):
            skip = list(meta["scanned_addresses"])

        stand = {
            "eintraege": list(bisher),
            "scanned": set(skip),
        }

        def on_address_done(address: str, neu: list[dict], *, _xpub=xpub) -> None:
            stand["eintraege"] = _merge_verlauf_eintraege(stand["eintraege"], neu)
            stand["scanned"].add(address)
            save_xpub_verlauf_cache(
                _xpub,
                stand["eintraege"],
                cache_dir,
                scanned_addresses=sorted(stand["scanned"]),
                planned_addresses=geplant,
                incomplete=True,
            )

        fehler: BaseException | None = None
        try:
            try:
                fetch_wallet_history(
                    adressen,
                    skip_addresses=skip,
                    on_address_done=on_address_done,
                    seed_eintraege=bisher,
                )
            except TypeError:
                # Älterer Fetcher ohne Resume-Argumente.
                roh = fetch_wallet_history(adressen)
                stand["eintraege"] = _merge_verlauf_eintraege(bisher, roh or [])
                stand["scanned"] = set(geplant)
        except BaseException as exc:
            # Timeout/Abbruch: Zwischenstand aus on_address_done bleibt,
            # incomplete=True — nächster Lauf setzt fort.
            fehler = exc
            if not stand["scanned"]:
                raise

        from display import is_list_abort_requested

        fertig = (
            fehler is None
            and (not is_list_abort_requested())
            and set(geplant) <= stand["scanned"]
        )
        save_xpub_verlauf_cache(
            xpub,
            stand["eintraege"],
            cache_dir,
            scanned_addresses=[] if fertig else sorted(stand["scanned"]),
            planned_addresses=geplant,
            incomplete=not fertig,
        )
        if fehler is not None:
            raise fehler
        ergebnis[xpub] = stand["eintraege"]
    return ergebnis


def _supplement_cache_address(
    xpub: str,
    address: str,
    fetch_address_utxos,
    cache_dir: Path,
    source: str,
    wallet: WalletContext | None = None,
) -> None:
    """Scannt genau eine Adresse und ergänzt den Cache — kein Bereichs-Scan."""
    entry = load_xpub_cache_entry(xpub, cache_dir)
    if _address_known_in_cache(entry, address):
        return

    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(f"  Ziel-Scan {label}: {abbrev_display(address)}", flush=True)
    try:
        live_utxos = fetch_address_utxos(address)
    except Exception as exc:
        print(f"  ⚠️  Ziel-Scan fehlgeschlagen: {exc}", flush=True)
        return

    for utxo in live_utxos:
        utxo["address"] = address

    cached = list(entry["utxos"]) if entry else []
    merged = _merge_utxo_lists(cached, live_utxos)
    _mark_address_scanned(xpub, address, cache_dir, source, merged)

    if wallet:
        wallet.address_to_wallet[address] = wallet.names_by_xpub[xpub]
        wallet.address_to_xpub[address] = xpub

    if live_utxos:
        print(
            f"  → {len(live_utxos)} UTXO(s) für {abbrev_display(address)} im Cache ergänzt",
            flush=True,
        )
    else:
        print(f"  → Keine unspent UTXOs auf {abbrev_display(address)} (im Cache vermerkt)", flush=True)


def _ensure_address_cached(
    address: str,
    wallet: WalletContext,
    cache_dir: Path | None,
    fetch_address_utxos,
    source: str,
) -> None:
    """
    Wallet-Zuordnung lokal per XPUB; API nur für diese eine Adresse,
    und nur wenn sie noch nicht im Cache bekannt ist.
    """
    if not wallet.resolve_address(address):
        return
    xpub = wallet.xpub_for_address(address)
    if not xpub or not cache_dir or not fetch_address_utxos:
        return
    _supplement_cache_address(
        xpub, address, fetch_address_utxos, cache_dir, source, wallet
    )


def _mempool_pending_nach_prune(
    xpub: str,
    cached: list[dict],
    pruned: list[dict],
    *,
    fulcrum=None,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
) -> list[dict]:
    """
    Nach Light-Prune: Mempool-Spends behalten und eigene Empfänge anhängen.

    ``listunspent`` sieht unbestätigte Ausgaben nicht — ohne diesen Schritt
    verschwinden Self-Tx/Change still aus dem Cache (15→14), obwohl die Tx
    nur im Mempool liegt. Zusätzlich: bereits im Verlauf als
    ``spent_pending`` vermerkte Outpoints erneut prüfen (Recovery).
    """
    if fulcrum is None:
        return pruned

    live_keys = {
        f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        for u in pruned
    }
    fehlt = [
        u for u in cached
        if f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        not in live_keys
    ]
    # Recovery: Pending aus Verlauf, falls Light sie schon entfernt hatte.
    if cache_dir is not None:
        try:
            verlauf = load_xpub_verlauf_cache(xpub, cache_dir) or []
        except Exception:
            verlauf = []
        gesehen_f = {
            f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
            for u in fehlt
        }
        for e in verlauf:
            if not e.get("spent_pending"):
                continue
            key = (
                f"{str(e.get('txid') or '').lower()}:"
                f"{int(e.get('vout') or 0)}"
            )
            if key in live_keys or key in gesehen_f:
                continue
            gesehen_f.add(key)
            fehlt.append({
                "txid": e.get("txid"),
                "vout": e.get("vout"),
                "value": int(e.get("value") or 0),
                "address": e.get("address"),
                "status": e.get("status") or {},
            })


    try:
        from core.fulcrum_wallet import eigene_mempool_empfaenge, klassifiziere_utxo_spends
    except Exception:
        return pruned

    # Auch andere Wallet-Caches liefern Inputs für Cross-Wallet-Empfänge.
    kandidaten = list(fehlt)
    gesehen_k = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in kandidaten}
    if wallet is not None and cache_dir is not None:
        for anderes in wallet.xpubs:
            if anderes == xpub:
                continue
            try:
                eintrag = load_xpub_cache_entry(anderes, cache_dir)
                andere_utxos = (eintrag or {}).get("utxos") or []
            except Exception:
                andere_utxos = []
            for u in andere_utxos:
                key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
                if key not in gesehen_k:
                    gesehen_k.add(key)
                    kandidaten.append(u)
            try:
                verlauf = load_xpub_verlauf_cache(anderes, cache_dir) or []
            except Exception:
                verlauf = []
            for e in verlauf:
                if not e.get("spent_pending"):
                    continue
                key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
                if key in gesehen_k:
                    continue
                gesehen_k.add(key)
                kandidaten.append({"txid": e.get("txid"), "vout": e.get("vout"), "value": int(e.get("value") or 0), "address": e.get("address"), "status": e.get("status") or {}})
    if not kandidaten:
        return pruned
    try:
        alle_pending, alle_confirmed, _live = klassifiziere_utxo_spends(fulcrum, kandidaten)
    except Exception:
        return pruned

    ziel_keys = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in fehlt}
    pending = [p for p in alle_pending if not xpub or f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}" in ziel_keys]
    confirmed = [c for c in alle_confirmed if not xpub or f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}" in ziel_keys]
    # Bestätigte Spends: Verlauf merken, UTXO bleibt draußen.
    if confirmed and cache_dir is not None:
        try:
            merke_bip158_verlauf(
                xpub,
                [
                    {
                        "txid": str(c.get("txid") or "").lower(),
                        "vout": int(c.get("vout") or 0),
                        "address": c.get("address"),
                        "value": int(c.get("value") or 0),
                        "spent": True,
                        "spent_pending": False,
                        "spent_txid": c.get("spent_txid") or "",
                        "spent_height": int(c.get("spent_height") or 0),
                        "spent_time_ts": c.get("spent_time_ts"),
                        "spent_outputs": c.get("spent_outputs") or [],
                        "spent_coinjoin": bool(c.get("spent_coinjoin")),
                        "status": c.get("status") or {},
                    }
                    for c in confirmed
                ],
                cache_dir,
            )
        except Exception:
            pass


    by_key = {
        f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}": p
        for p in pending
    }
    result = list(pruned)
    result_keys = set(live_keys)
    for u in fehlt:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        p = by_key.get(key)
        if p is None:
            continue
        neu = dict(u)
        neu["spending_pending"] = True
        neu["spent_txid"] = p.get("spent_txid") or ""
        if key not in result_keys:
            result_keys.add(key)
            result.append(neu)

    empfaenge: list[dict] = []
    if wallet is not None:
        try:
            if xpub:
                ziel_name = wallet.xpub_label(xpub)
                def _empfang_gehort(addr: str) -> bool:
                    return wallet.resolve_address(addr) == ziel_name
            else:
                _empfang_gehort = wallet.is_own_address
            empfaenge = eigene_mempool_empfaenge(
                fulcrum, alle_pending, is_own_address=_empfang_gehort,
            )
        except Exception:
            empfaenge = []
    for e in empfaenge:
        key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        if key in result_keys:
            continue
        result_keys.add(key)
        result.append(dict(e))

    if cache_dir is not None:
        try:
            merke_bip158_verlauf(
                xpub,
                [
                    {
                        "txid": str(p.get("txid") or "").lower(),
                        "vout": int(p.get("vout") or 0),
                        "address": p.get("address"),
                        "value": int(p.get("value") or 0),
                        "spent": True,
                        "spent_pending": True,
                        "spent_txid": p.get("spent_txid") or "",
                        "spent_height": 0,
                        "spent_outputs": p.get("spent_outputs") or [],
                        "spent_coinjoin": bool(p.get("spent_coinjoin")),
                        "status": p.get("status") or {},
                    }
                    for p in pending
                ],
                cache_dir,
            )
        except Exception:
            pass

    return result


def _light_rescan_xpub(
    xpub: str,
    cached: list[dict],
    scan_end_index: int,
    fetch_wallet_utxos,
    fetch_address_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
) -> list[dict]:
    """Light-Rescan: Cache bereinigen + nächste Adress-Batch scannen."""
    next_start = scan_end_index
    next_end = next_start + max_addresses // 2 - 1
    print(
        f"\nLight-Rescan {(wallet.xpub_label(xpub) if wallet else xpub[:25] + '...')} "
        f"(Index #{next_start}–#{next_end} pro Chain)",
        flush=True,
    )

    pruned, _live_snapshot = _prune_cached_utxos(
        cached, fetch_address_utxos,
    )
    pruned = _mempool_pending_nach_prune(
        xpub,
        cached,
        pruned,
        fulcrum=fulcrum,
        wallet=wallet,
        cache_dir=cache_dir,
    )
    removed = len(cached) - len(pruned)
    if removed:
        print(f"  {removed} verbrauchte UTXO(s) aus Cache entfernt", flush=True)

    new_addresses = derive_addresses(
        xpub,
        max_addresses=max_addresses,
        start_index=next_start,
    )
    print(f"  Scanne {len(new_addresses)} neue Adressen...", flush=True)
    new_utxos = fetch_wallet_utxos(new_addresses)
    merged = _merge_utxo_lists(pruned, new_utxos)
    new_scan_end = next_start + max_addresses // 2

    cache_path = save_xpub_utxo_cache(
        xpub,
        merged,
        cache_dir,
        source,
        scan_end_index=new_scan_end,
        max_addresses=max_addresses,
        # Der Light-Rescan kennt nur die neue Batch; für das Alter zählen alle
        # bisher bekannten Adressen mit.
        first_seen=ermittle_first_seen(
            xpub,
            derive_addresses(xpub, max_addresses=max_addresses) | set(new_addresses),
            cache_dir,
            fulcrum,
        ),
    )
    print(
        f"  → {len(merged)} UTXO(s) gecacht "
        f"({len(new_utxos)} neu, bis Index #{new_scan_end - 1}) "
        f"in {cache_path.name}",
        flush=True,
    )
    return merged


def _full_rescan_xpub(
    xpub: str,
    fetch_wallet_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """Full-Rescan: gesamten Adressraum ab Index #0 neu scannen."""
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(f"\nFull-Rescan {label} (ab Index #0)", flush=True)
    return _scan_xpub_utxos(
        xpub,
        fetch_wallet_utxos,
        cache_dir,
        source,
        max_addresses,
        start_index=0,
        wallet=wallet,
        fulcrum=fulcrum,
        on_progress=on_progress,
        on_utxos_update=on_utxos_update,
    )


def _verify_cached_utxos_against_chain(
    cached_by_xpub: dict[str, list[dict]],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    verify_utxo_spent=None,
    fulcrum=None,
) -> dict[str, list[dict]]:
    """
    Fragt optional nach Cache-Prüfung der gecachten UTXOs
    plus der nächsten SALDEN_CHECK_LOOKAHEAD Adress-Indizes
    und bietet bei Abweichung Light- oder Full-Rescan an.
    """
    if not cached_by_xpub:
        return cached_by_xpub

    cached_xpubs = list(cached_by_xpub)
    prefixes = ", ".join(
        wallet.xpub_label(x) if wallet else x[:25] + "..."
        for x in cached_xpubs
    )
    print(
        f"\nUTXO-Set zu {len(cached_xpubs)} XPUB(s) im Cache gefunden "
        f"({prefixes})."
    )
    print(
        "Salden gegen Blockchain prüfen? [j/N] (Enter = Cache nutzen): ",
        end="",
        flush=True,
    )
    from interact import prompt_rescan_mode, prompt_yes_no

    if not prompt_yes_no(default_yes=False):
        return cached_by_xpub

    mismatched: list[str] = []
    scan_end_by_xpub: dict[str, int] = {}

    for xpub in cached_xpubs:
        cached = cached_by_xpub[xpub]
        entry = load_xpub_cache_entry(xpub, cache_dir)
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        scan_end_index = entry["scan_end_index"] if entry else xpub_max // 2
        scan_end_by_xpub[xpub] = scan_end_index

        label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
        print(f"\nPrüfe {label} gegen Blockchain...", flush=True)

        matches, pruned, lookahead = _verify_cached_utxo_set(
            xpub,
            cached,
            scan_end_index,
            fetch_address_utxos,
            fetch_addresses_utxos,
            fetch_wallet_utxos,
            verify_utxo_spent=verify_utxo_spent,
        )
        live = _merge_utxo_lists(pruned, lookahead)

        if matches:
            if cached:
                cached_total = sum(u["value"] for u in cached)
                print(
                    f"  {len(cached)} UTXO(s), {cached_total:,} sats — stimmt überein",
                    flush=True,
                )
            else:
                print("  Keine UTXOs — folgende Indizes ebenfalls leer.", flush=True)
        else:
            mismatched.append(xpub)
            _describe_utxo_diff(cached, live)

    if not mismatched:
        print("\nUTXO-Set unverändert.")
        return cached_by_xpub

    print("\nSalden weichen vom Cache ab.")
    mode = prompt_rescan_mode()
    if mode is None:
        print("Nutze veralteten Cache.", flush=True)
        return cached_by_xpub

    for xpub in mismatched:
        cached = cached_by_xpub[xpub]
        scan_end_index = scan_end_by_xpub[xpub]
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        if mode == "light":
            updated = _light_rescan_xpub(
                xpub,
                cached,
                scan_end_index,
                fetch_wallet_utxos,
                fetch_address_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
            )
        else:
            updated = _full_rescan_xpub(
                xpub,
                fetch_wallet_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
            )
        cached_by_xpub[xpub] = updated

    return cached_by_xpub


def _utxo_scan_scantxoutset_vorrang(fulcrum=None, env: dict[str, str] | None = None) -> bool:
    """
    Wann Bitcoin Core ``scantxoutset`` vor dem Electrum-Gap-Scan steht.

    Reihenfolge für den **reinen UTXO-Bestand** (Alltag = Tempo):

    1. Electrs/Fulcrum **im LAN** — Gap-Scan nur über genutzte Adressen
    2. Core ``scantxoutset`` — bevorzugt ``UTXO_RPC_*`` (lokaler Node),
       sonst Lookup-``NODE_IP`` (z. B. Start9)
    3. Electrs Onion / BIP-158 / öffentlich

    Lokaler scantxoutset bleibt Fallback (Vollständigkeit ohne Gap-Policy,
    Privatsphäre), nicht der Default neben schnellem LAN-Electrs.
    """
    _ = env  # reserviert (Tests/Caller); Priorität hängt am Fulcrum-Transport
    if _fulcrum_transport_ist_lan(fulcrum):
        return False
    return True


def _try_scantxoutset_xpub(
    xpub: str,
    cache_dir: Path,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
) -> list[dict] | None:
    """
    UTXO-Bestand über Bitcoin Core ``scantxoutset``, falls sinnvoll und konfiguriert.

    None = absichtlich übersprungen, Core fehlt/unerreichbar → Caller nutzt
    Electrum/BIP-158. Siehe ``_utxo_scan_scantxoutset_vorrang``.
    """
    env = _load_dotenv()
    if not _utxo_scan_scantxoutset_vorrang(fulcrum, env=env):
        msg = (
            "scantxoutset übersprungen — Electrs/Fulcrum im LAN ist für den "
            "UTXO-Bestand typischerweise schneller (Gap-Scan)."
        )
        print(f"  {msg}", flush=True)
        if on_progress:
            try:
                on_progress(msg, sofort=True)
            except TypeError:
                on_progress(msg)
        return None

    from core.bitcoind_rpc import try_scantxoutset_for_xpubs

    scan_cap = _scan_index_cap_per_chain(xpub, wallet, max_addresses)

    def _max_for(key: str) -> int:
        return _scan_index_cap_per_chain(key, wallet, max_addresses)

    try:
        ergebnis = try_scantxoutset_for_xpubs(
            env,
            [xpub],
            max_addresses_for=_max_for,
            default_max=scan_cap,
            wallet=wallet,
            on_progress=on_progress,
        )
    except Exception as exc:
        from core.jobs import ist_abbruch

        if ist_abbruch(exc):
            raise
        print(f"  scantxoutset übersprungen: {exc}", flush=True)
        return None
    if ergebnis is None:
        return None
    by_xpub, tip = ergebnis
    utxos = by_xpub.get(xpub) or []
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(
        f"\nscantxoutset {label}: {len(utxos)} UTXO(s)"
        + (f" · Tip {tip}" if tip else ""),
        flush=True,
    )
    cache_path = save_xpub_utxo_cache(
        xpub,
        utxos,
        cache_dir,
        "bitcoind",
        scan_end_index=scan_cap,
        max_addresses=max_addresses,
        first_seen=ermittle_first_seen(
            xpub,
            derive_addresses(xpub, max_addresses=max(scan_cap * 2, 2)),
            cache_dir,
            None,
            on_progress=on_progress,
            utxos=utxos,
        ),
        scan_tip_height=tip,
    )
    print(f"  → {len(utxos)} UTXO(s) gecacht in {cache_path.name}", flush=True)
    return utxos


def _scan_xpub_utxos(
    xpub: str,
    fetch_wallet_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
    allow_scantxoutset: bool = True,
) -> list[dict]:
    """Scannt ein XPUB und schreibt das Ergebnis in den Cache."""
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    zwischen: list[dict] = []

    def _melde_utxos(stand: list[dict]) -> None:
        nonlocal zwischen
        zwischen = list(stand)
        schreibe_utxo_zwischenstand(
            xpub, zwischen, cache_dir, source, max_addresses=max_addresses,
        )
        if on_utxos_update:
            on_utxos_update(zwischen)

    # Core scantxoutset nur bei Vollabgleich (User-Scan), nie beim Tip-Nachzug.
    if allow_scantxoutset and start_index == 0:
        core_utxos = _try_scantxoutset_xpub(
            xpub,
            cache_dir,
            max_addresses,
            wallet=wallet,
            fulcrum=fulcrum,
            on_progress=on_progress,
        )
        if core_utxos is not None:
            if on_utxos_update:
                on_utxos_update(core_utxos)
            return core_utxos
    scan_end_index = start_index + max_addresses // 2
    scan_cap = _scan_index_cap_per_chain(xpub, wallet, max_addresses)
    use_gap_scan = start_index == 0 and (fulcrum is not None)
    if use_gap_scan:
        if on_progress:
            on_progress(f"Suche benutzte Adressen von {label}…")
        addresses, scan_end_index = discover_wallet_scan_addresses(
            xpub,
            fulcrum=fulcrum,
            max_index_per_chain=scan_cap,
            start_index=start_index,
            on_progress=on_progress,
            on_utxos_update=_melde_utxos,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(Gap-Scan bis Index #{scan_end_index - 1} pro Chain, "
            f"{len(addresses)} Adressen)",
            flush=True,
        )
    elif source == "bip158" and start_index == 0:
        addresses = derive_addresses(
            xpub,
            max_addresses=max(scan_cap * 2, max_addresses),
            start_index=start_index,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(BIP-158 Filter bis Index #{scan_cap - 1} pro Chain)",
            flush=True,
        )
    else:
        end_index = start_index + max_addresses // 2 - 1
        addresses = derive_addresses(
            xpub,
            max_addresses=max_addresses,
            start_index=start_index,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(Index #{start_index}–#{end_index} pro Chain, {len(addresses)} Adressen)",
            flush=True,
        )
    from display import is_list_abort_requested

    if is_list_abort_requested():
        return list(zwischen)

    if on_progress:
        on_progress(
            f"Frage UTXOs…"
            if source == "bip158"
            else f"Frage UTXOs für {len(addresses)} Adressen…"
        )
    tip_hoehe = None
    # Nach Gap-Scan sind die UTXOs schon im Zwischenstand — listunspent
    # startet bei null und würde die GUI sonst kurz leeren. BIP-158 und
    # feste Adresslisten melden weiter live.
    live_update = None if use_gap_scan else _melde_utxos
    fetch_kwargs = {
        "filter_scan": False,
        "on_progress": on_progress,
        "on_utxos_update": live_update,
        "xpubs": [xpub],
    }
    if source == "bip158" and start_index == 0:
        fetch_kwargs["filter_scan"] = True
        fetch_kwargs["max_addr"] = scan_cap * 2
        try:
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        except TypeError:
            fetch_kwargs.pop("on_utxos_update", None)
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        scan_end_index = scan_cap
        try:
            from core.bip158_wallet import take_last_scan_tip

            tip_hoehe = take_last_scan_tip(xpub)
        except Exception:
            tip_hoehe = None
    else:
        try:
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        except TypeError:
            fetch_kwargs.pop("on_utxos_update", None)
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        # Electrum/Fulcrum liefert den Bestand am Tip — Höhe mitschreiben,
        # damit späterer P2P-Lauf Tip-Nachzug machen kann.
        if fulcrum is not None and not is_list_abort_requested():
            try:
                from core.fulcrum_history import get_chain_tip_height

                tip_hoehe = int(get_chain_tip_height(fulcrum, force=True))
            except Exception:
                tip_hoehe = None
    if is_list_abort_requested() and not utxos:
        return list(zwischen) if zwischen else utxos
    # Bestand am Tip: BIP-158-Fullscan oder erfolgreicher Electrum-Gap.
    # Abbruch: kein Tip / fullscan_ok=False → nächster P2P-Lauf Turbo-Erstscan.
    full_ok = None
    if is_list_abort_requested():
        if source == "bip158":
            full_ok = False
            tip_hoehe = None
    elif source == "bip158":
        full_ok = True
    elif tip_hoehe and tip_hoehe > 0:
        # Fulcrum/Electrum (und Core+Fulcrum-Tip): Flag heißt historisch
        # bip158_fullscan_ok, meint aber „UTXO-Stand am Tip bekannt“.
        full_ok = True
    cache_path = save_xpub_utxo_cache(
        xpub,
        utxos,
        cache_dir,
        source,
        scan_end_index=scan_end_index,
        max_addresses=max_addresses,
        first_seen=ermittle_first_seen(
            xpub,
            addresses,
            cache_dir,
            fulcrum,
            on_progress=on_progress,
            utxos=utxos,
        ),
        scan_tip_height=tip_hoehe,
        bip158_fullscan_ok=full_ok,
    )
    print(
        f"  → {len(utxos)} UTXO(s) gecacht in {cache_path.name}",
        flush=True,
    )
    if on_utxos_update:
        on_utxos_update(utxos)
    return utxos


def _adressen_bis_index(xpub: str, end_index: int) -> set[str]:
    """Receive- und Change-Adressen Index #0 … #end_index−1."""
    addresses: set[str] = set()
    if end_index <= 0:
        return addresses
    for change in (0, 1):
        for i in range(end_index):
            addr = derive_address_at_index(xpub, change, i)
            if addr:
                addresses.add(addr)
    return addresses


def sync_xpub_zum_tip(
    xpub: str,
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    verify_utxo_spent=None,
    bip158_fetch_wallet_utxos=None,
    on_progress=None,
    nur_bekannte: bool = False,
) -> list[dict] | None:
    """
    Leichtes Nachziehen bis Chain-Tip (Start-Sync / Light-Update).

    Nur mit bestehendem UTXO-Cache. **Kein** Fullscan, **kein** scantxoutset.

    Produktregel:
    1. **BIP-158 inkrementell**, wenn Compact-Filter-Fetcher und
       ``scan_tip_height`` vorhanden (auch wenn Electrs/Core die allgemeine
       Datenquelle sind) — entfällt bei ``nur_bekannte``.
    2. Sonst **Electrs/Adresse light**: nur bekannte UTXOs auf spent prüfen
       + Gap/Lookahead ab ``scan_end_index`` — nicht alle Indizes #0…N.
       Bei ``nur_bekannte``: nur bekannte UTXOs/Adressen, kein Gap.
    3. Expliziter User-UTXO-Scan bleibt bei Electrs/Core-Vorrang (anderer Pfad).

    Rückgabe: aktualisierte UTXO-Liste, oder ``None`` ohne Cache.
    """
    entry = load_xpub_cache_entry(xpub, cache_dir)
    if entry is None:
        return None

    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
    scan_end = int(entry["scan_end_index"] or 0)
    if scan_end <= 0:
        scan_end = max(xpub_max // 2, 1)
    tip = (entry.get("raw") or {}).get("scan_tip_height")
    try:
        tip_i = int(tip) if tip is not None else None
    except (TypeError, ValueError):
        tip_i = None

    if on_progress:
        if nur_bekannte:
            on_progress(f"Aktualisiere {label} (nur bekannte UTXOs)…")
        else:
            on_progress(f"Aktualisiere {label} bis Chain-Tip…")

    # --- 1) BIP-158 inkrementell (bevorzugt für Tip-Nachzug) ---------------
    # Bei nur_bekannte: kein Filter-Walk — nur Light auf bekannte Adressen.
    bip_fetch = bip158_fetch_wallet_utxos
    if bip_fetch is None and source == "bip158":
        bip_fetch = fetch_wallet_utxos
    if not nur_bekannte and bip_fetch is not None and tip_i is not None:
        print(
            f"\nAktualisiere {label} (BIP-158 ab Tip {tip_i:,})".replace(",", "."),
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: BIP-158 inkrementell ab Block {tip_i:,}".replace(",", ".")
            )
        try:
            # Kein Electrs-Gap und kein scantxoutset — nur Compact-Filter ab Tip.
            return _scan_xpub_utxos(
                xpub,
                bip_fetch,
                cache_dir,
                "bip158",
                xpub_max,
                start_index=0,
                wallet=wallet,
                fulcrum=None,
                on_progress=on_progress,
                allow_scantxoutset=False,
            )
        except Exception as exc:
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
            # Multisig/Deskriptor oder Peer-Fehler: nicht den ganzen Wallet
            # überspringen — Electrs light hält den Cache frisch.
            msg = (
                f"{label}: BIP-158 fehlgeschlagen ({exc}) — "
                "weiche auf Electrs light aus…"
            )
            print(f"  ⚠️  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
    if not nur_bekannte and bip_fetch is not None and tip_i is None:
        msg = (
            f"{label}: kein scan_tip_height im Cache — "
            "kein BIP-158-Filter-Nachzug (bräuchte mehrere Peers ab Tip); "
            "Electrs light (Gap) statt Multi-Peer-Scan."
        )
        print(f"  {msg}", flush=True)
        if on_progress:
            on_progress(msg)

    # --- 2) Electrs/Adresse light: spent der bekannten UTXOs + Gap ----------
    # BIP-158-Adressabruf ist teuer (Filter/Block) — nur echte Electrs/Core-
    # Spent-Prüfung oder Fulcrum-Gap, nicht der BIP-158-Fallback-Fetcher.
    electrs_light = (
        fulcrum is not None
        or verify_utxo_spent is not None
        or (
            source not in ("bip158",)
            and (
                fetch_address_utxos is not None
                or fetch_addresses_utxos is not None
            )
        )
    )
    if not electrs_light:
        msg = (
            f"{label}: kein Electrs-Light-Pfad — Cache unverändert."
            if bip_fetch is None or tip_i is not None
            else f"{label}: Cache unverändert (kein Tip, kein Electrs)."
        )
        if bip_fetch is None or tip_i is not None:
            print(f"  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
        return list(entry["utxos"])

    alt = list(entry["utxos"] or [])
    # Adressen der Cache-UTXOs: auch nach spent erneut abfragen (neue Empfänge).
    addrs_cache = {u.get("address") for u in alt if u.get("address")}
    if nur_bekannte:
        print(
            f"\nAktualisiere {label} (Light: nur {len(alt)} bekannte UTXO(s), kein Gap)",
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: prüfe {len(alt)} bekannte UTXO(s) (kein Gap)…"
            )
    else:
        print(
            f"\nAktualisiere {label} (Light: bekannte UTXOs + Gap ab #{scan_end})",
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: prüfe {len(alt)} bekannte UTXO(s), Gap ab #{scan_end}…"
            )

    # Ein listunspent-Durchgang: Prune + neue Empfänge auf denselben Adressen.
    # Früher: prune listunspent + extra_same listunspent = doppelt so langsam.
    live, extra_same = _prune_cached_utxos(
        alt,
        fetch_address_utxos,
        verify_utxo_spent=verify_utxo_spent,
        fetch_addresses_utxos=fetch_addresses_utxos,
        on_progress=on_progress,
        progress_label=f"Live {label}",
    )
    # verify_utxo_spent-Pfad liefert kein Adress-Snapshot → einmal nachholen.
    if (
        not extra_same
        and addrs_cache
        and (fetch_address_utxos or fetch_addresses_utxos)
    ):
        extra_same = _fetch_address_batch_utxos(
            addrs_cache,
            fetch_address_utxos,
            fetch_addresses_utxos,
            progress_label=f"Live {label}",
            on_progress=on_progress,
        )
    live = _mempool_pending_nach_prune(
        xpub,
        alt,
        live,
        fulcrum=fulcrum,
        wallet=wallet,
        cache_dir=cache_dir,
    )
    new_end = scan_end
    extra_utxos: list[dict] = []
    extra_window: list[dict] = []

    if not nur_bekannte and fulcrum is not None:
        scan_cap = _scan_index_cap_per_chain(xpub, wallet, xpub_max)
        if on_progress:
            on_progress(f"{label}: Gap ab Index #{scan_end}…")
        try:
            extra_addrs, walked_end = discover_wallet_scan_addresses(
                xpub,
                fulcrum=fulcrum,
                max_index_per_chain=scan_cap,
                start_index=scan_end,
                gap_limit=UTXO_SCAN_GAP_LIMIT,
                on_progress=on_progress,
            )
        except ValueError:
            extra_addrs, walked_end = set(), scan_end
        neu = set(extra_addrs) - addrs_cache
        if neu:
            if on_progress:
                on_progress(f"{label}: {len(neu)} neue Gap-Adressen…")
            extra_utxos = _fetch_address_batch_utxos(
                neu,
                fetch_address_utxos,
                fetch_addresses_utxos,
                progress_label=f"Gap {label}",
                on_progress=on_progress,
            )
            new_end = max(scan_end, int(walked_end))
        # Rückwärts-Gap: Empfänge auf zuvor leeren Indizes können unterhalb
        # des bisherigen Scan-Endes liegen (Empfang und Change).
        window_start = max(0, scan_end - UTXO_SCAN_GAP_LIMIT)
        if window_start < scan_end and (fetch_address_utxos or fetch_addresses_utxos):
            window_addrs = derive_addresses(
                xpub,
                max_addresses=(scan_end - window_start) * 2,
                start_index=window_start,
            )
            neu_window = window_addrs - addrs_cache - set(extra_addrs)
            if neu_window:
                extra_window = _fetch_address_batch_utxos(
                    neu_window,
                    fetch_address_utxos,
                    fetch_addresses_utxos,
                    progress_label=f"Rückwärts-Gap {label}",
                    on_progress=on_progress,
                )
    elif not nur_bekannte:
        lookahead = max(BIP44_GAP_LIMIT, SALDEN_CHECK_LOOKAHEAD)
        if on_progress:
            on_progress(f"{label}: Lookahead {lookahead} Indizes…")

        def _look_fetch(addrs, **_kw):
            return _fetch_address_batch_utxos(
                addrs,
                fetch_address_utxos,
                fetch_addresses_utxos,
                progress_label=f"Lookahead {label}",
                on_progress=on_progress,
            )

        extra_utxos = _fetch_lookahead_utxos(
            xpub, scan_end, _look_fetch, lookahead,
        )
        if extra_utxos:
            new_end = scan_end + lookahead

    merged = _merge_utxo_lists(live, extra_same)
    merged = _merge_utxo_lists(merged, extra_utxos)
    merged = _merge_utxo_lists(merged, extra_window)
    old_n = len(alt)
    # Electrs light: Tip auf Live-Electrs (bevorzugt) bzw. Header-Datei
    # anheben — sonst bleibt „−N Blöcke“ hängen, wenn p2p_headers hinter
    # dem Node liegt oder stundenlang nicht nachgezogen wurde.
    tip_fuer_cache = _scan_tip_anheben(tip_i, cache_dir, fulcrum=fulcrum)
    cache_path = save_xpub_utxo_cache(
        xpub,
        merged,
        cache_dir,
        source if source != "bip158" else "fulcrum",
        scan_end_index=new_end,
        max_addresses=xpub_max,
        scan_tip_height=tip_fuer_cache,
    )
    print(
        f"  → {label}: {len(merged)} UTXO(s) (vorher {old_n}), "
        f"Scan bis Index #{max(new_end - 1, 0)} in {cache_path.name}",
        flush=True,
    )
    if on_progress:
        on_progress(f"{label}: {len(merged)} UTXO(s) aktuell.")
    return merged


def sync_wallets_zum_tip(
    xpubs: list[str],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    verify_utxo_spent=None,
    bip158_fetch_wallet_utxos=None,
    on_progress=None,
    on_wallet_done=None,
    nur_bekannte: bool = False,
) -> dict[str, list[dict]]:
    """
    Aktualisiert alle XPUBs mit Cache bis Chain-Tip (Light-Update).

    Ohne Cache: übersprungen. Rückgabe: ``{xpub: utxos}`` nur für
    bearbeitete Schlüssel. *on_wallet_done(xpub, utxos_oder_None)*.
    """
    ergebnis: dict[str, list[dict]] = {}
    for xpub in xpubs:
        try:
            aktualisiert = sync_xpub_zum_tip(
                xpub,
                fetch_wallet_utxos,
                fetch_address_utxos,
                fetch_addresses_utxos,
                cache_dir,
                source,
                max_addresses=_max_addresses_for_xpub(
                    xpub, wallet, max_addresses
                ),
                wallet=wallet,
                fulcrum=fulcrum,
                verify_utxo_spent=verify_utxo_spent,
                bip158_fetch_wallet_utxos=bip158_fetch_wallet_utxos,
                on_progress=on_progress,
                nur_bekannte=nur_bekannte,
            )
        except Exception as exc:
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
            label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
            msg = f"{label}: Aktualisierung fehlgeschlagen ({exc})"
            print(f"  ⚠️  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
            if on_wallet_done:
                on_wallet_done(xpub, None)
            continue
        if aktualisiert is None:
            if on_wallet_done:
                on_wallet_done(xpub, None)
            continue
        ergebnis[xpub] = aktualisiert
        if on_wallet_done:
            on_wallet_done(xpub, aktualisiert)
    return ergebnis


def resolve_wallet_utxos(
    xpubs: list[str],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    rescan: bool = False,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    verify_utxo_spent=None,
    use_cache_only: bool = False,
    fulcrum=None,
    on_missing_xpubs=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """
    Liefert Wallet-UTXOs aus Cache oder nach optionalem Scan.
    Mit --rescan werden alle XPUBs per Full-Rescan ab Index #0 neu gescannt.

    *on_missing_xpubs* entscheidet, ob nicht gecachte XPUBs gescannt werden:
    Callable[[list[str]], bool]. Ohne Angabe fragt das CLI wie bisher nach.
    Nicht-interaktive Aufrufer (Web-Server) müssen etwas übergeben — sonst
    blockiert der Prompt den Thread auf unbestimmte Zeit.

    *on_utxos_update* erhält während des Scans den bekannten UTXO-Zwischenstand
    (voller Snapshot), sobald neue Funde dazukommen.
    """
    if rescan:
        print("Erzwinge Full-Rescan (--rescan)...", flush=True)
        cached_by_xpub: dict[str, list[dict]] = {}
        for xpub in xpubs:
            xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
            cached_by_xpub[xpub] = _full_rescan_xpub(
                xpub,
                fetch_wallet_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
                on_progress=on_progress,
                on_utxos_update=on_utxos_update,
            )
        return _merge_cached_utxos(xpubs, cached_by_xpub, wallet, cache_dir=cache_dir)

    cached_by_xpub: dict[str, list[dict]] = {}
    missing_xpubs: list[str] = []

    for xpub in xpubs:
        cached = load_xpub_utxo_cache(xpub, cache_dir)
        if cached is not None:
            cached_by_xpub[xpub] = cached
            cache_path = _xpub_cache_path(xpub, cache_dir)
            print(
                f"UTXO-Cache geladen: {(wallet.xpub_label(xpub) if wallet else xpub[:25] + '...')} "
                f"({len(cached)} UTXO(s) aus {cache_path.name})",
                flush=True,
            )
        else:
            missing_xpubs.append(xpub)

    if not use_cache_only:
        cached_by_xpub = _verify_cached_utxos_against_chain(
            cached_by_xpub,
            fetch_wallet_utxos,
            fetch_address_utxos,
            fetch_addresses_utxos,
            cache_dir,
            source,
            max_addresses,
            wallet=wallet,
            verify_utxo_spent=verify_utxo_spent,
            fulcrum=fulcrum,
        )

    if not missing_xpubs:
        return _merge_cached_utxos(xpubs, cached_by_xpub, wallet, cache_dir=cache_dir)

    if on_missing_xpubs is None:
        from interact import prompt_wallet_scan

        do_scan = prompt_wallet_scan(missing_xpubs, wallet=wallet)
    else:
        do_scan = bool(on_missing_xpubs(missing_xpubs))
    if not do_scan:
        if cached_by_xpub:
            print(
                "Scan abgebrochen — nutze vorhandenen Cache "
                f"für {len(cached_by_xpub)} XPUB(s).",
                flush=True,
            )
            return _merge_cached_utxos(
                xpubs,
                cached_by_xpub,
                wallet,
                cache_dir=cache_dir,
            )

        print(
            "Kein UTXO-Cache vorhanden und Scan abgelehnt. "
            "Nutze --rescan für einen erzwungenen Scan.",
            file=sys.stderr,
        )
        return []

    for xpub in missing_xpubs:
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        cached_by_xpub[xpub] = _scan_xpub_utxos(
            xpub,
            fetch_wallet_utxos,
            cache_dir,
            source,
            xpub_max,
            wallet=wallet,
            fulcrum=fulcrum,
        )
    return _merge_cached_utxos(
        xpubs,
        cached_by_xpub,
        wallet,
        cache_dir=cache_dir,
    )
