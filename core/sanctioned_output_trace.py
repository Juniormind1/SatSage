"""Sanctioned output / entity-trace (Slice 4).

trace_sanctioned_outputs_since / _by_entity, Entity-Reports.
analyze.py re-exportiert die öffentliche API.
"""
from __future__ import annotations

from pathlib import Path

from display import (
    abbrev_display,
    cancellable_output,
    is_list_abort_requested,
)

from core.sanctioned_address_utxos import (
    _sanctioned_input_sats,
    scan_sanctioned_addresses_fulcrum_sync,
)


def _main():
    import main
    return main


def _collect_sanction_output_traces(
    get_tx,
    scan_addresses_sync,
    addresses: list[str],
    sanctioned_addresses: frozenset[str],
    *,
    start_height: int,
    since_label: str,
    on_progress=None,
    batch_size: int = 40,
) -> list[dict]:
    """Txs mit Sanktions-Inputs seit start_height inkl. Outputs und moved_sats."""
    if not addresses:
        return []

    traces: list[dict] = []
    seen_tx: set[str] = set()
    total_batches = (len(addresses) + batch_size - 1) // batch_size

    for batch_index, start in enumerate(range(0, len(addresses), batch_size), start=1):
        batch = addresses[start : start + batch_size]
        if on_progress:
            on_progress(
                batch_index=batch_index,
                total_batches=total_batches,
                txs_found=len(traces),
            )
        try:
            result = scan_addresses_sync(
                batch,
                start_height=start_height,
                on_progress=on_progress,
            )
        except Exception:
            continue
        for mtx in result.transactions:
            if mtx.txid in seen_tx:
                continue
            if not mtx.matched_inputs:
                continue
            moved_sats, sanctioned_inputs = _sanctioned_input_sats(
                get_tx,
                mtx.txid,
                sanctioned_addresses,
            )
            if not sanctioned_inputs:
                continue
            seen_tx.add(mtx.txid)
            try:
                tx = get_tx(mtx.txid)
            except Exception:
                tx = mtx.raw_tx
            outputs: list[dict] = []
            for vout_index, vout in enumerate(tx.get("vout", [])):
                out_addrs = _main()._extract_addresses(vout)
                outputs.append({
                    "vout": vout_index,
                    "addresses": out_addrs,
                    "amount_sats": _main()._extract_value_sats(vout),
                })
            traces.append({
                "txid": mtx.txid,
                "block_height": mtx.block_height,
                "sanctioned_inputs": sanctioned_inputs,
                "outputs": outputs,
                "moved_sats": moved_sats,
                "since_label": since_label,
            })
    return traces


def trace_sanctioned_outputs_since(
    get_tx,
    scan_addresses_sync,
    sanctioned_addresses: frozenset[str],
    *,
    start_height: int,
    since_label: str,
    on_progress=None,
    batch_size: int = 40,
) -> list[dict]:
    """
    Findet Ausgänge (vouts) von Transaktionen, in denen sanktionierte
    Adressen Inputs waren, seit start_height.
    """
    return _collect_sanction_output_traces(
        get_tx,
        scan_addresses_sync,
        sorted(sanctioned_addresses),
        sanctioned_addresses,
        start_height=start_height,
        since_label=since_label,
        on_progress=on_progress,
        batch_size=batch_size,
    )


def _build_entity_trace_entry(
    group,
    *,
    get_tx,
    scan_addresses_sync,
    height_for_date,
    batch_size: int,
    on_group_progress=None,
) -> dict:
    from sanctioned import _format_listed_date

    person = group.person
    listed_date = group.listed_date
    since_label = _format_listed_date(listed_date)
    addresses = sorted(set(group.addresses))
    address_set = frozenset(addresses)

    entry: dict = {
        "entity_id": group.entity_id,
        "person": person,
        "listed_date": listed_date,
        "since_label": since_label,
        "start_height": None,
        "addresses": addresses,
        "traces": [],
        "moved_sats": 0,
        "skipped": False,
        "skip_reason": None,
    }

    if not listed_date:
        entry["skipped"] = True
        entry["skip_reason"] = "kein Listungsdatum in OFAC-Daten"
        return entry

    try:
        start_height = height_for_date(listed_date)
    except (ValueError, OSError, RuntimeError) as exc:
        entry["skipped"] = True
        entry["skip_reason"] = str(exc)
        return entry

    entry["start_height"] = start_height
    traces = _collect_sanction_output_traces(
        get_tx,
        scan_addresses_sync,
        addresses,
        address_set,
        start_height=start_height,
        since_label=since_label,
        on_progress=on_group_progress,
        batch_size=batch_size,
    )
    entry["traces"] = traces
    entry["moved_sats"] = sum(int(t.get("moved_sats", 0)) for t in traces)
    return entry


def _trace_sanctioned_outputs_by_entity_parallel(
    fulcrum_pool,
    get_tx,
    entity_groups: list,
    *,
    height_for_date,
    batch_size: int = 40,
    parallel_progress=None,
    cache_root: Path | None = None,
) -> list[dict]:
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    scannable = [g for g in entity_groups if g.addresses]
    total_groups = len(scannable)
    if not scannable:
        return []

    work: queue.Queue = queue.Queue()
    for group_index, group in enumerate(scannable, start=1):
        work.put((group_index, group))

    results: list[dict | None] = [None] * total_groups
    txs_found = 0
    txs_lock = threading.Lock()
    worker_count = min(len(fulcrum_pool), total_groups)

    def worker(worker_id: int) -> None:
        nonlocal txs_found

        from main import make_cached_fulcrum_get_tx

        worker_client = fulcrum_pool.client_at(worker_id)
        worker_get_tx = make_cached_fulcrum_get_tx(worker_client, cache_root)

        def scan_addresses_sync(
            addrs,
            *,
            start_height: int = 0,
            on_progress=None,
            **_kw,
        ):
            batch = list(addrs) if not isinstance(addrs, list) else addrs
            return scan_sanctioned_addresses_fulcrum_sync(
                worker_client,
                worker_get_tx,
                batch,
                start_height=start_height,
                on_progress=on_progress,
            )

        while True:
            try:
                group_index, group = work.get_nowait()
            except queue.Empty:
                break

            person = group.person
            addr_count = len(group.addresses)
            if parallel_progress is not None:
                parallel_progress.update_worker(
                    worker_id,
                    batch_index=group_index,
                    done=0,
                    total=max(addr_count, 1),
                    state="scan",
                    detail=person[:20],
                )

            def _group_progress(**kw) -> None:
                if parallel_progress is None:
                    return
                if kw.get("addr_index") and kw.get("total_addrs"):
                    done = int(kw["addr_index"])
                    total = int(kw["total_addrs"])
                else:
                    done = kw.get("batch_index", 0)
                    total = kw.get("total_batches", 1) or 1
                parallel_progress.update_worker(
                    worker_id,
                    batch_index=group_index,
                    done=done,
                    total=total,
                    state="scan",
                    detail=person[:20],
                )

            entry = _build_entity_trace_entry(
                group,
                get_tx=worker_get_tx,
                scan_addresses_sync=scan_addresses_sync,
                height_for_date=height_for_date,
                batch_size=batch_size,
                on_group_progress=_group_progress if parallel_progress else None,
            )
            results[group_index - 1] = entry

            with txs_lock:
                txs_found += len(entry.get("traces", []))

            if parallel_progress is not None:
                parallel_progress.batch_complete(
                    worker_id,
                    addrs_in_batch=1,
                    utxos_found=txs_found,
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

    return [entry for entry in results if entry is not None]


def trace_sanctioned_outputs_by_entity(
    get_tx,
    scan_addresses_sync,
    entity_groups: list,
    *,
    height_for_date,
    on_progress=None,
    batch_size: int = 40,
    fulcrum_pool=None,
    parallel_progress=None,
    cache_root: Path | None = None,
) -> list[dict]:
    """
    Pro OFAC-Gruppe: Bewegungen ab Listungsdatum der Gruppe.
    Rückgabe: Liste mit Gruppen-Ergebnissen (traces, moved_sats, …).
    """
    if fulcrum_pool is not None and len(fulcrum_pool) > 1:
        return _trace_sanctioned_outputs_by_entity_parallel(
            fulcrum_pool,
            get_tx,
            entity_groups,
            height_for_date=height_for_date,
            batch_size=batch_size,
            parallel_progress=parallel_progress,
            cache_root=cache_root,
        )

    results: list[dict] = []
    scannable = [g for g in entity_groups if g.addresses]
    total_groups = len(scannable)

    for group_index, group in enumerate(scannable, start=1):
        person = group.person

        if on_progress:
            on_progress(
                group_index=group_index,
                total_groups=total_groups,
                person=person,
                txs_found=sum(len(r["traces"]) for r in results),
            )

        def _group_progress(**kw) -> None:
            if on_progress:
                on_progress(
                    group_index=group_index,
                    total_groups=total_groups,
                    person=person,
                    txs_found=sum(len(r["traces"]) for r in results) + kw.get("txs_found", 0),
                    batch_index=kw.get("batch_index"),
                    total_batches=kw.get("total_batches"),
                )

        entry = _build_entity_trace_entry(
            group,
            get_tx=get_tx,
            scan_addresses_sync=scan_addresses_sync,
            height_for_date=height_for_date,
            batch_size=batch_size,
            on_group_progress=_group_progress if on_progress else None,
        )
        results.append(entry)

    return results


def _print_sanction_trace_entries(
    traces: list[dict],
    *,
    show_moved: bool = True,
    indent: str = "  ",
    numbered: bool = True,
) -> None:
    outdent = indent + "  "
    for index, entry in enumerate(traces, start=1):
        if is_list_abort_requested():
            return
        txid = abbrev_display(entry["txid"])
        inputs = ", ".join(abbrev_display(a) for a in entry["sanctioned_inputs"])
        moved = int(entry.get("moved_sats", 0))
        prefix = f"[{index}] " if numbered else "· "
        header = (
            f"\n{indent}{prefix}Tx {txid}  Block {entry['block_height']:,}  "
            f"Input(s): {inputs}"
        )
        if show_moved and moved:
            header += f"  —  {moved:,} sats bewegt"
        print(header)
        for out in entry["outputs"]:
            if is_list_abort_requested():
                return
            addrs = ", ".join(abbrev_display(a) for a in out["addresses"] if a) or "?"
            print(
                f"{outdent}→ vout {out['vout']}: {addrs}  "
                f"({out['amount_sats']:,} sats)"
            )


def print_sanctioned_output_trace_report(traces: list[dict], *, since_label: str) -> None:
    moved_total = sum(int(t.get("moved_sats", 0)) for t in traces)
    print(f"\n{'═' * 72}")
    print(f"  Outputs von sanktionierten Adressen seit {since_label}")
    print(f"  {len(traces)} Transaktion(en) mit Sanktions-Input(s)", end="")
    if moved_total:
        print(f"  —  {moved_total:,} sats bewegt", end="")
    print()
    print(f"{'═' * 72}")
    if not traces:
        print("\n  Keine Ausgänge seit dem Stichtag gefunden.")
        return
    with cancellable_output(hint="Sanktions-Trace — q zum Abbrechen"):
        _print_sanction_trace_entries(traces)


def print_sanctioned_entity_trace_report(group_results: list[dict]) -> None:
    """Bericht: Bewegungen pro OFAC-Gruppe ab jeweiligem Listungsdatum."""
    active = [r for r in group_results if not r.get("skipped")]
    with_moves = [r for r in active if r.get("traces")]
    moved_total = sum(int(r.get("moved_sats", 0)) for r in active)

    print(f"\n{'═' * 72}")
    print("  Outputs nach OFAC-Listung (pro Gruppe)")
    print(
        f"  {len(with_moves)} Gruppe(n) mit Bewegungen, "
        f"{sum(len(r['traces']) for r in active)} Tx(s) gesamt",
        end="",
    )
    if moved_total:
        print(f"  —  {moved_total:,} sats bewegt", end="")
    print()
    print(f"{'═' * 72}")

    if not group_results:
        print("\n  Keine OFAC-Gruppen geladen.")
        return

    with cancellable_output(hint="Sanktions-Trace — q zum Abbrechen"):
        for index, entry in enumerate(group_results, start=1):
            if is_list_abort_requested():
                break
            person = entry["person"]
            since_label = entry.get("since_label") or "unbekannt"
            print(f"\n  [{index}] {person}")
            if entry.get("skipped"):
                print(f"      ⚠️  Übersprungen: {entry.get('skip_reason')}")
                continue
            height = entry.get("start_height")
            if height is not None:
                print(f"      Listung: {since_label}  (ab Block {height:,})")
            print(f"      Adressen: {len(entry.get('addresses', [])):,}")

            traces = entry.get("traces") or []
            moved = int(entry.get("moved_sats", 0))
            if not traces:
                print("      Keine Outputs nach Listung gefunden.")
                continue
            print(
                f"      {len(traces)} Tx(s) mit Sanktions-Input(s)"
                + (f"  —  {moved:,} sats bewegt" if moved else "")
            )
            _print_sanction_trace_entries(
                traces,
                show_moved=True,
                indent="      ",
                numbered=False,
            )

