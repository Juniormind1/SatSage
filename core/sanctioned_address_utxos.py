"""Sanctioned address UTXO list-scan (Slice 4).

scan_sanctioned_address_utxos (+ parallel/Fulcrum-Sync), Findings-Reports.
analyze.py re-exportiert die öffentliche API.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from display import (
    abbrev_display,
    cancellable_output,
    format_sats,
    format_utxo_display,
    is_list_abort_requested,
)

from trace_engine import (
    resolve_vin_prevout,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


def _call_fetch_addresses_utxos(
    fetch_addresses_utxos,
    batch: list[str],
    *,
    progress_label: str | None = None,
    on_batch_progress=None,
    on_batch_complete=None,
) -> list[dict]:
    """Ruft den Batch-Fetcher auf; optionale Fortschritts-/Batch-Callbacks."""
    kwargs: dict = {}
    if progress_label is not None:
        kwargs["progress_label"] = progress_label
    if on_batch_progress is not None:
        kwargs["on_batch_progress"] = on_batch_progress
    if on_batch_complete is not None:
        kwargs["on_batch_complete"] = on_batch_complete
    try:
        return fetch_addresses_utxos(batch, **kwargs)
    except TypeError:
        kwargs.pop("progress_label", None)
        try:
            return fetch_addresses_utxos(set(batch), **kwargs)
        except TypeError:
            kwargs.pop("on_batch_progress", None)
            try:
                return fetch_addresses_utxos(batch, **kwargs)
            except TypeError:
                kwargs.pop("on_batch_complete", None)
                if kwargs:
                    try:
                        return fetch_addresses_utxos(batch, **kwargs)
                    except TypeError:
                        pass
                return fetch_addresses_utxos(batch)


_UNMAPPED_SANCTION_ENTITY = "__unmapped__"


def _bucket_utxos_by_sanction_entity(
    utxos: list[dict],
    entity_groups: list,
) -> list[tuple[str, str, dict[str, list[dict]]]]:
    """
    Gruppiert UTXOs nach OFAC-Entität.
    Rückgabe: [(entity_id, Anzeigename, {Adresse: [UTXOs]})], sortiert nach Name.
    """
    from sanctioned import build_entity_lookup, load_sanctioned_address_index

    by_id, addr_to_id = build_entity_lookup(entity_groups)
    address_index = load_sanctioned_address_index()
    buckets: dict[str, dict[str, list[dict]]] = {}
    for utxo in utxos:
        addr = str(utxo.get("address") or "?")
        entity_id = addr_to_id.get(addr, _UNMAPPED_SANCTION_ENTITY)
        buckets.setdefault(entity_id, {}).setdefault(addr, []).append(utxo)

    ordered: list[tuple[str, str, dict[str, list[dict]]]] = []
    for entity_id, by_addr in buckets.items():
        if entity_id == _UNMAPPED_SANCTION_ENTITY:
            sample_addr = next(iter(by_addr), "")
            rec = address_index.get(sample_addr) if sample_addr else None
            if rec and rec.get("person"):
                label = str(rec["person"])
            else:
                label = "Ohne Gruppen-Zuordnung"
        else:
            label = by_id[entity_id].person if entity_id in by_id else entity_id
        ordered.append((entity_id, label, by_addr))
    ordered.sort(key=lambda item: (item[0] == _UNMAPPED_SANCTION_ENTITY, item[1].lower()))
    return ordered


def print_sanctioned_utxo_findings(
    utxos: list[dict],
    entity_groups: list,
    *,
    batch_index: int | None = None,
    total_batches: int | None = None,
    max_utxos_per_addr: int = 5,
) -> None:
    """Gibt UTXO-Salden aus, gruppiert nach sanktionierter Person/Organisation."""
    if not utxos or is_list_abort_requested():
        return

    total_sats = sum(int(u.get("value", 0)) for u in utxos)
    if batch_index is not None and total_batches is not None:
        print(
            f"\n  Batch {batch_index}/{total_batches}: "
            f"{len(utxos)} UTXO(s), {format_sats(total_sats)}",
            flush=True,
        )
        if is_list_abort_requested():
            return
    else:
        print(
            f"\n  {len(utxos)} UTXO(s), {format_sats(total_sats)} gesamt",
            flush=True,
        )

    if not entity_groups:
        by_addr: dict[str, list[dict]] = {}
        for utxo in utxos:
            by_addr.setdefault(str(utxo.get("address") or "?"), []).append(utxo)
        print("  (Keine OFAC-Gruppendaten — nur nach Adresse)", flush=True)
        for addr in sorted(by_addr):
            if is_list_abort_requested():
                break
            items = by_addr[addr]
            addr_total = sum(int(u.get("value", 0)) for u in items)
            print(
                f"\n    {abbrev_display(addr)} — "
                f"{len(items)} UTXO(s), {format_sats(addr_total)}",
                flush=True,
            )
            if _print_sanction_utxo_items(items, max_utxos_per_addr):
                return
        return

    for _entity_id, label, by_addr in _bucket_utxos_by_sanction_entity(utxos, entity_groups):
        if is_list_abort_requested():
            break
        entity_utxos = sum(by_addr.values(), [])
        entity_total = sum(int(u.get("value", 0)) for u in entity_utxos)
        print(
            f"\n  {label} — {len(entity_utxos)} UTXO(s), {format_sats(entity_total)}",
            flush=True,
        )
        for addr in sorted(by_addr):
            if is_list_abort_requested():
                break
            items = by_addr[addr]
            addr_total = sum(int(u.get("value", 0)) for u in items)
            print(
                f"    {abbrev_display(addr)} — "
                f"{len(items)} UTXO(s), {format_sats(addr_total)}",
                flush=True,
            )
            if _print_sanction_utxo_items(items, max_utxos_per_addr, indent="      "):
                return


def _print_sanction_utxo_items(
    items: list[dict],
    max_show: int,
    *,
    indent: str = "    ",
) -> bool:
    for utxo in items[:max_show]:
        if is_list_abort_requested():
            return True
        print(
            f"{indent}{format_utxo_display(utxo['txid'], int(utxo['vout']), address=utxo.get('address'))}: "
            f"{format_sats(int(utxo.get('value', 0)))}",
            flush=True,
        )
    if len(items) > max_show and not is_list_abort_requested():
        print(f"{indent}… +{len(items) - max_show} weitere", flush=True)
    return is_list_abort_requested()


def _scan_sanctioned_address_utxos_parallel(
    fulcrum_pool,
    sanctioned_addresses: frozenset[str],
    *,
    batch_size: int = 40,
    on_batch_findings=None,
    entity_groups: list | None = None,
    parallel_progress=None,
) -> list[dict]:
    """Paralleler UTXO-Scan: Batches werden auf Clearnet-Server verteilt."""
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from core.fulcrum_wallet import fetch_address_utxos_fulcrum

    addresses = sorted(sanctioned_addresses)
    if not addresses:
        return []

    batch_ranges = [
        (batch_index, addresses[start : start + batch_size])
        for batch_index, start in enumerate(
            range(0, len(addresses), batch_size), start=1
        )
    ]
    total_batches = len(batch_ranges)
    work: queue.Queue = queue.Queue()
    for item in batch_ranges:
        work.put(item)

    found: list[dict] = []
    found_lock = threading.Lock()
    print_lock = threading.Lock()
    worker_count = min(len(fulcrum_pool), total_batches)

    def worker(worker_id: int) -> None:
        client = fulcrum_pool.client_at(worker_id)
        while not is_list_abort_requested():
            try:
                batch_index, batch = work.get_nowait()
            except queue.Empty:
                break
            batch_len = len(batch)
            batch_found: list[dict] = []
            for done, address in enumerate(batch, start=1):
                if is_list_abort_requested():
                    break
                if parallel_progress is not None:
                    parallel_progress.update_worker(
                        worker_id,
                        batch_index=batch_index,
                        done=done,
                        total=batch_len,
                        state="scan",
                    )
                try:
                    for utxo in fetch_address_utxos_fulcrum(client, address):
                        utxo["address"] = address
                        if address in sanctioned_addresses:
                            batch_found.append(utxo)
                except Exception:
                    continue

            with found_lock:
                found.extend(batch_found)
                utxos_total = len(found)

            if parallel_progress is not None:
                parallel_progress.batch_complete(
                    worker_id,
                    addrs_in_batch=batch_len,
                    utxos_found=utxos_total,
                )

            if batch_found and not is_list_abort_requested():
                with print_lock:
                    if parallel_progress is not None:
                        parallel_progress.pause_for_output()
                    if is_list_abort_requested():
                        break
                    if on_batch_findings:
                        on_batch_findings(
                            batch_found,
                            batch_index,
                            total_batches,
                            entity_groups=entity_groups,
                        )
                    else:
                        print_sanctioned_utxo_findings(
                            batch_found,
                            entity_groups or [],
                            batch_index=batch_index,
                            total_batches=total_batches,
                        )
            work.task_done()
            if is_list_abort_requested():
                break

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(worker, worker_id) for worker_id in range(worker_count)]
        for future in as_completed(futures):
            if is_list_abort_requested():
                break
            future.result()

    return found


def scan_sanctioned_address_utxos(
    fetch_addresses_utxos,
    sanctioned_addresses: frozenset[str],
    *,
    batch_size: int = 40,
    single_fetch: bool = False,
    on_progress=None,
    on_batch_findings=None,
    entity_groups: list | None = None,
    fulcrum_pool=None,
    parallel_progress=None,
) -> list[dict]:
    """Sucht unspent UTXOs auf sanktionierten Adressen (Batch-Scan)."""
    addresses = sorted(sanctioned_addresses)
    if not addresses:
        return []

    if fulcrum_pool is not None and len(fulcrum_pool) > 1:
        return _scan_sanctioned_address_utxos_parallel(
            fulcrum_pool,
            sanctioned_addresses,
            batch_size=batch_size,
            on_batch_findings=on_batch_findings,
            entity_groups=entity_groups,
            parallel_progress=parallel_progress,
        )

    found: list[dict] = []
    total_batches = (len(addresses) + batch_size - 1) // batch_size

    if single_fetch:
        batch_complete_used = False

        def on_internal_batch(**kw) -> None:
            if on_progress:
                on_progress(
                    addrs_total=len(addresses),
                    utxos_found=len(found),
                    **kw,
                )

        def _emit_batch_findings(
            batch_found: list[dict],
            batch_index: int,
            total_batches: int,
        ) -> None:
            if on_batch_findings:
                on_batch_findings(
                    batch_found,
                    batch_index,
                    total_batches,
                    entity_groups=entity_groups,
                )
            else:
                print_sanctioned_utxo_findings(
                    batch_found,
                    entity_groups or [],
                    batch_index=batch_index,
                    total_batches=total_batches,
                )

        def on_internal_batch_complete(
            batch_index: int,
            total_batches: int,
            batch_utxos: list[dict],
        ) -> None:
            nonlocal batch_complete_used
            batch_complete_used = True
            batch_found = [
                utxo
                for utxo in batch_utxos
                if utxo.get("address") in sanctioned_addresses
            ]
            if not batch_found:
                return
            found.extend(batch_found)
            _emit_batch_findings(batch_found, batch_index, total_batches)

        try:
            batch_utxos = _call_fetch_addresses_utxos(
                fetch_addresses_utxos,
                addresses,
                on_batch_progress=on_internal_batch,
                on_batch_complete=on_internal_batch_complete,
            )
        except Exception as exc:
            print(f"  ⚠️  Sanktions-UTXO-Scan fehlgeschlagen: {exc}", flush=True)
            return found
        if not batch_complete_used:
            batch_found = []
            for utxo in batch_utxos:
                addr = utxo.get("address")
                if addr and addr in sanctioned_addresses:
                    found.append(utxo)
                    batch_found.append(utxo)
            if batch_found and not is_list_abort_requested():
                _emit_batch_findings(batch_found, 1, 1)
        return found

    batch_ranges = [
        (
            batch_index,
            addresses[start : start + batch_size],
        )
        for batch_index, start in enumerate(
            range(0, len(addresses), batch_size), start=1
        )
    ]
    for batch_index, batch in batch_ranges:
        if is_list_abort_requested():
            break
        batch_len = len(batch)

        def _report_batch_progress(
            addrs_done_in_batch: int,
            *,
            _batch_index: int = batch_index,
            _batch_len: int = batch_len,
        ) -> None:
            if on_progress:
                on_progress(
                    batch_index=_batch_index,
                    total_batches=total_batches,
                    addrs_done_in_batch=addrs_done_in_batch,
                    addrs_in_batch=_batch_len,
                    addrs_total=len(addresses),
                    utxos_found=len(found),
                )

        _report_batch_progress(0)
        progress_label = f"Sanktionsliste Batch {batch_index}/{total_batches}"
        try:
            batch_utxos = _call_fetch_addresses_utxos(
                fetch_addresses_utxos,
                batch,
                progress_label=progress_label,
                on_batch_progress=_report_batch_progress,
            )
        except Exception as exc:
            print(
                f"  ⚠️  Batch {batch_index}/{total_batches} fehlgeschlagen: {exc}",
                flush=True,
            )
            continue
        batch_found = []
        for utxo in batch_utxos:
            addr = utxo.get("address")
            if addr and addr in sanctioned_addresses:
                found.append(utxo)
                batch_found.append(utxo)
        if batch_found and not is_list_abort_requested():
            if on_batch_findings:
                on_batch_findings(
                    batch_found,
                    batch_index,
                    total_batches,
                    entity_groups=entity_groups,
                )
            else:
                print_sanctioned_utxo_findings(
                    batch_found,
                    entity_groups or [],
                    batch_index=batch_index,
                    total_batches=total_batches,
                )
    return found


def print_sanctioned_utxo_scan_report(
    utxos: list[dict],
    entity_groups: list | None = None,
    *,
    wrap_cancellable: bool = True,
) -> None:
    if is_list_abort_requested():
        return
    print(f"\n{'═' * 72}")
    print(f"  UTXOs auf sanktionierten Adressen: {len(utxos)}")
    print(f"{'═' * 72}")
    if not utxos:
        print("\n  Keine unspent UTXOs auf sanktionierten Adressen gefunden.")
        return
    print("\n  Gesamtergebnis (nach Entität):", flush=True)
    if wrap_cancellable:
        with cancellable_output(hint="UTXO-Liste — q zum Abbrechen"):
            print_sanctioned_utxo_findings(utxos, entity_groups or [])
    else:
        print_sanctioned_utxo_findings(utxos, entity_groups or [])


def scan_sanctioned_addresses_fulcrum_sync(
    fulcrum_client,
    get_tx,
    addresses: list[str],
    *,
    start_height: int = 0,
    on_progress=None,
):
    """
    Fulcrum-Fallback: Txs finden, in denen Adressen als Input auftreten.
    Kompatibel zu :meth:`Bip158Client.scan_addresses_sync` (ScanResult).
    """
    from core.bip158_filter import MatchedTransaction, ScanResult
    from core.fulcrum_client import address_to_scripthash

    address_set = set(addresses)
    transactions: list[MatchedTransaction] = []
    seen_tx: set[str] = set()
    total_addrs = len(addresses)

    for addr_index, address in enumerate(addresses, start=1):
        if on_progress:
            on_progress(addr_index=addr_index, total_addrs=total_addrs)
        sh = address_to_scripthash(address)
        try:
            history = fulcrum_client.request(
                "blockchain.scripthash.get_history",
                [sh],
            ) or []
        except Exception:
            continue
        for entry in history:
            height = int(entry.get("height", 0))
            if height > 0 and height < start_height:
                continue
            txid = str(entry.get("tx_hash", ""))
            if not txid or txid in seen_tx:
                continue
            try:
                raw_tx = get_tx(txid)
            except Exception:
                continue
            _moved, sanctioned_inputs = _sanctioned_input_sats(
                get_tx,
                txid,
                address_set,
                tx=raw_tx,
            )
            if not sanctioned_inputs:
                continue
            seen_tx.add(txid)
            transactions.append(
                MatchedTransaction(
                    txid=txid,
                    block_height=height,
                    block_hash="",
                    raw_tx=raw_tx,
                    matched_inputs=({"spend": True},),
                )
            )

    return ScanResult(
        start_height=start_height,
        stop_height=0,
        transactions=transactions,
    )


def _sanctioned_input_sats(
    get_tx,
    txid: str,
    sanctioned_addresses: frozenset[str] | set[str],
    *,
    tx: dict | None = None,
) -> tuple[int, list[str]]:
    """Summiert Input-Sats von sanktionierten Adressen in einer Tx."""
    if tx is None:
        try:
            tx = get_tx(txid)
        except Exception:
            return 0, []

    total = 0
    input_addrs: set[str] = set()
    chain = _main()
    for vin in tx.get("vin", []):
        if vin.get("is_coinbase"):
            continue
        try:
            prev_out = resolve_vin_prevout(get_tx, vin)
            if not prev_out:
                continue
            prev_addrs = chain._extract_addresses(prev_out)
            amount_sats = chain._extract_value_sats(prev_out)
        except Exception:
            continue
        if any(addr in sanctioned_addresses for addr in prev_addrs):
            total += amount_sats
            input_addrs.update(prev_addrs)
    relevant = sorted(addr for addr in input_addrs if addr in sanctioned_addresses)
    return total, relevant
