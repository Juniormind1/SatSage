"""Interaktives Hauptmenü für SatSage (Legacy / Fallback).

Die empfohlene Oberfläche ist die Web-GUI (``py server.py``). Dieses Menü
bleibt für Terminal-only, SSH und schnelle Checks ohne Browser.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.i18n import t, ja_nein, init_from_env
from core.log_i18n import install_stdout_translation, translate_line
from display import set_verbose
from interact import (
    interactive_analyze_top_utxos,
    run_analyze_address_utxos,
    run_analyze_tx,
)

DEFAULT_BIP158_START_HEIGHT = 850_000
DEFAULT_TOP_UTXOS = 10


@dataclass
class MenuSession:
    """Laufzeitkontext für Menü und Blockchain-Zugriff."""

    args: Any
    wallet_ctx: Any
    cache_dir: Path
    env: dict[str, str]
    all_addresses: set[str]
    source: str | None = None
    backend: Any = None
    get_tx: Callable[[str], dict] | None = None
    fetch_address_utxos: Callable[[str], list] | None = None
    fetch_addresses_utxos: Callable[[set], list] | None = None
    fetch_addresses_utxos_utxoset: Callable[[set], list] | None = None
    fetch_wallet_utxos: Callable[[set], list] | None = None
    fetch_utxos: Callable[[str], list] | None = None
    verify_utxo_spent: Callable[[str, int], int | None] | None = None
    fulcrum: Any = None
    bip158_start: int = DEFAULT_BIP158_START_HEIGHT
    top_utxos_limit: int = DEFAULT_TOP_UTXOS
    connected: bool = False
    verbose: bool = False
    sanctioned_addresses: frozenset[str] = field(default_factory=frozenset)
    sanctioned_meta: dict | None = None
    sanctioned_entities: list = field(default_factory=list)
    sanctioned_entities_meta: dict | None = None


def _read_line(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        print("\n" + t("cli.abort"), flush=True)
        raise SystemExit(0)


def _clear_screen() -> None:
    import os

    if os.name == "nt":
        os.system("cls")
    else:
        print("\033[2J\033[H", end="", flush=True)


def _source_label(session: MenuSession) -> str:
    if not session.connected or not session.source:
        return t("cli.notConnected")

    if session.source == "bip158":
        return t("cli.source.bip158", n=f"{session.bip158_start:,}")
    if session.source == "fulcrum":
        return t("cli.source.fulcrum")
    return session.source


def _xpub_has_cache(xpub: str, cache_dir: Path) -> bool:
    from main import load_xpub_utxo_cache

    return load_xpub_utxo_cache(xpub, cache_dir) is not None


def _source_line(session: MenuSession) -> str:
    label = _source_label(session)
    if session.connected and session.source:
        from main import privacy_notice_for_source

        notice = privacy_notice_for_source(session.source, fulcrum=session.fulcrum)
        if notice:
            return f"{label}  —  {notice}"
    return label


def _alter_suffix(xpub: str, cache_dir) -> str:
    """Alter-Hinweis hinter dem Wallet-Namen (seit Datum/Block)."""
    from main import xpub_first_seen

    first_seen = xpub_first_seen(xpub, cache_dir)
    if not first_seen:
        return ""
    stempel = first_seen.get("time_ts")
    if stempel:
        try:
            from datetime import datetime

            return f" · seit {datetime.fromtimestamp(int(stempel)):%d.%m.%Y}"
        except (ValueError, OSError, OverflowError):
            pass
    hoehe = first_seen.get("height")
    return f" · seit Block {hoehe:,}".replace(",", ".") if hoehe else ""


def print_status(session: MenuSession) -> None:
    """Statuszeile über dem Menü."""
    print(f"\n{'═' * 72}")
    print(f"  {t('cli.status.source', line=_source_line(session))}")
    print(f"  {t('cli.status.xpubs', n=len(session.args.xpubs))}")
    for xpub in session.args.xpubs:
        name = session.wallet_ctx.xpub_label(xpub)
        cached = " [C]" if _xpub_has_cache(xpub, session.cache_dir) else ""
        print(f"    {name}{cached}{_alter_suffix(xpub, session.cache_dir)}")
    print(f"{'═' * 72}")


def print_main_menu(session: MenuSession) -> None:
    print("\n  " + t("cli.menu.title"))
    print("  " + t("cli.menu.1"))
    print("  " + t("cli.menu.2"))
    print("  " + t("cli.menu.3"))
    print("  " + t("cli.menu.4"))
    print("  " + t("cli.menu.5"))
    print("  " + t("cli.menu.6"))
    print("  " + t("cli.menu.7"))
    print("  " + t("cli.menu.8"))
    print()


def _parse_trace_target(raw: str) -> tuple[str, str | None, str | None, str | None]:
    """
    Erkennt Eingabe: txid, utxo (txid:vout) oder Adresse.
    Rückgabe: (modus, txid, adresse, utxo_ref)
    """
    value = raw.strip()
    if not value:
        raise ValueError(t("cli.emptyInput"))

    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return "txid", value, None, None

    if ":" in value:
        txid, vout_str = value.rsplit(":", 1)
        if re.fullmatch(r"[0-9a-fA-F]{64}", txid) and vout_str.isdigit():
            return "utxo", txid, None, value

    return "address", None, value, None


def _resolve_height_for_date(
    session: MenuSession,
    sanctions_backend: dict | None = None,
):
    """Datum → Blockhöhe passend zur aktiven Datenquelle."""
    if session.source == "fulcrum" and sanctions_backend is None:
        from fulcrum import date_to_block_height_fulcrum

        client = session.fulcrum
        if client is not None:
            return lambda date_str: date_to_block_height_fulcrum(client, date_str)

    from main import estimate_block_height_for_date

    return estimate_block_height_for_date


def _apply_data_source_choice(session: MenuSession, choice: str) -> None:
    from main import apply_data_source_choice

    apply_data_source_choice(
        session.args,
        session.env,
        choice,
        bip158_start=session.bip158_start,
    )


def connect_blockchain(
    session: MenuSession,
    *,
    interactive_onion: bool = False,
) -> None:
    """Stellt Blockchain-Verbindung her und bindet Fetcher in die Session."""
    from main import (
        DEFAULT_MAX_ADDRESSES,
        _build_blockchain_fetchers,
        _setup_blockchain_client,
        resolve_immutable_cache_dir,
    )

    if session.args.bip158 and session.args.bip158_start is None:
        session.args.bip158_start = session.bip158_start

    print("\n" + t("cli.connectSource"), flush=True)
    source, backend = _setup_blockchain_client(
        session.args,
        session.env,
        interactive_onion=interactive_onion,
    )
    fetchers = _build_blockchain_fetchers(
        source,
        backend,
        session.args,
        session.wallet_ctx,
        immutable_cache_dir=resolve_immutable_cache_dir(session.args),
    )
    session.source = source
    session.backend = backend
    session.get_tx = fetchers["get_tx"]
    session.fetch_address_utxos = fetchers["fetch_address_utxos"]
    session.fetch_addresses_utxos = fetchers["fetch_addresses_utxos"]
    session.fetch_addresses_utxos_utxoset = fetchers.get("fetch_addresses_utxos_utxoset")
    session.fetch_wallet_utxos = fetchers["fetch_wallet_utxos"]
    session.fetch_utxos = fetchers["fetch_utxos"]
    session.verify_utxo_spent = fetchers.get("verify_utxo_spent")
    session.fulcrum = fetchers["fulcrum"]
    session.connected = True
    set_verbose(session.verbose)
    if source == "bip158" and isinstance(backend, dict):
        client = backend.get("client")
        if client is not None:
            client.verbose = session.verbose


def _ensure_connected(session: MenuSession) -> None:
    if session.connected:
        return
    connect_blockchain(session)


def _resolve_wallet_utxos(
    session: MenuSession,
    xpubs: list[str] | None = None,
    *,
    use_cache_only: bool = False,
) -> list[dict]:
    from main import resolve_wallet_utxos

    _ensure_connected(session)
    target_xpubs = xpubs or session.args.xpubs
    return resolve_wallet_utxos(
        target_xpubs,
        session.fetch_wallet_utxos,
        session.fetch_address_utxos,
        session.fetch_addresses_utxos,
        session.cache_dir,
        session.source,
        rescan=session.args.rescan,
        max_addresses=session.args.max_addresses,
        wallet=session.wallet_ctx,
        verify_utxo_spent=session.verify_utxo_spent,
        use_cache_only=use_cache_only,
        fulcrum=session.fulcrum,
    )


def _filter_utxos_for_wallet(utxos: list[dict], wallet_name: str, wallet_ctx) -> list[dict]:
    filtered: list[dict] = []
    for utxo in utxos:
        addr = utxo.get("address", "")
        if wallet_ctx.resolve_address(addr) == wallet_name:
            filtered.append(utxo)
    return filtered


def menu_trace(session: MenuSession) -> None:
    _ensure_connected(session)
    print("\n" + t("cli.prompt.trace"), flush=True)
    raw = _read_line("> ")
    try:
        mode, txid, address, utxo_ref = _parse_trace_target(raw)
    except ValueError as exc:
        print(f"  ⚠️  {exc}", flush=True)
        return

    if mode == "txid" and txid:
        run_analyze_tx(
            session.get_tx,
            txid,
            session.all_addresses,
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetch_address_utxos,
            cache_source=session.source,
        )
    elif mode == "utxo" and utxo_ref:
        from main import _extract_addresses

        txid_part, vout_str = utxo_ref.rsplit(":", 1)
        try:
            tx = session.get_tx(txid_part)
            vout = tx["vout"][int(vout_str)]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            print(f"  ⚠️  {t('cli.warn.utxoNotFound', exc=exc)}", flush=True)
            return
        addrs = _extract_addresses(vout)
        if not addrs:
            print(f"  ⚠️  {t('cli.warn.noAddress')}", flush=True)
            return
        run_analyze_address_utxos(
            session.get_tx,
            session.fetch_utxos,
            addrs[0],
            session.all_addresses,
            utxo_ref=utxo_ref,
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetch_address_utxos,
            cache_source=session.source,
        )
    elif mode == "address" and address:
        run_analyze_address_utxos(
            session.get_tx,
            session.fetch_utxos,
            address,
            session.all_addresses,
            utxo_ref=utxo_ref,
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetch_address_utxos,
            cache_source=session.source,
        )


def menu_wallet_ranking(session: MenuSession) -> None:
    print("\n" + t("cli.pickWallet"), flush=True)
    for index, xpub in enumerate(session.args.xpubs, start=1):
        name = session.wallet_ctx.xpub_label(xpub)
        print(f"  {index}. {name}")
    choice = _read_line(t("cli.prompt.number"))
    if not choice.isdigit():
        print(f"  ⚠️  {t('cli.warn.invalidInput')}", flush=True)
        return
    index = int(choice)
    if index < 1 or index > len(session.args.xpubs):
        print(f"  ⚠️  {t('cli.warn.outOfRange')}", flush=True)
        return

    xpub = session.args.xpubs[index - 1]
    wallet_name = session.wallet_ctx.xpub_label(xpub)
    utxos = _resolve_wallet_utxos(session, xpubs=[xpub])
    from main import list_top_wallet_utxos, resolve_immutable_cache_dir

    immutable_cache_dir = resolve_immutable_cache_dir(session.args)
    if utxos:
        ranked = list_top_wallet_utxos(
            utxos,
            session.top_utxos_limit,
            wallet=session.wallet_ctx,
            immutable_cache_dir=immutable_cache_dir,
        )
    else:
        print(
            f"Keine UTXOs für {wallet_name} im Cache — "
            f"beim Laden Salden mit j prüfen / Rescan anbieten lassen.",
            flush=True,
        )
        ranked = []
    _interactive_ranking(session, ranked)


def menu_all_wallets_ranking(session: MenuSession) -> None:
    utxos = _resolve_wallet_utxos(session)
    from main import list_top_wallet_utxos, resolve_immutable_cache_dir

    immutable_cache_dir = resolve_immutable_cache_dir(session.args)
    if utxos:
        ranked = list_top_wallet_utxos(
            utxos,
            session.top_utxos_limit,
            wallet=session.wallet_ctx,
            immutable_cache_dir=immutable_cache_dir,
        )
    else:
        print(
            "Keine UTXOs in der Rangliste (Cache leer) — "
            "beim Laden Salden mit j prüfen / Rescan anbieten lassen.",
            flush=True,
        )
        ranked = []
    _interactive_ranking(session, ranked)


def menu_utxo_consolidation(session: MenuSession) -> None:
    from consolidate import DUST_SATS, run_dust_consolidation_prompt

    _ensure_connected(session)
    print("\n" + t("cli.pickWalletConsolidate"), flush=True)
    for index, xpub in enumerate(session.args.xpubs, start=1):
        name = session.wallet_ctx.xpub_label(xpub)
        print(f"  {index}. {name}")
    choice = _read_line(t("cli.prompt.number"))
    if not choice.isdigit():
        print(f"  ⚠️  {t('cli.warn.invalidInput')}", flush=True)
        return
    index = int(choice)
    if index < 1 or index > len(session.args.xpubs):
        print(f"  ⚠️  {t('cli.warn.outOfRange')}", flush=True)
        return

    xpub = session.args.xpubs[index - 1]
    wallet_name = session.wallet_ctx.xpub_label(xpub)
    raw_limit = _read_line(f"Dust-Limit in sats (Enter = {DUST_SATS:,}): ")
    if not raw_limit.strip():
        dust_limit = DUST_SATS
    else:
        cleaned = raw_limit.strip().replace("_", "").replace(",", "")
        if not cleaned.isdigit() or int(cleaned) < 1:
            print(f"  ⚠️  {t('cli.warn.positiveSats')}", flush=True)
            return
        dust_limit = int(cleaned)

    utxos = _resolve_wallet_utxos(session, xpubs=[xpub])
    if not utxos:
        print(t('cli.noUtxosWallet', wallet=wallet_name), flush=True)
        return

    print(f"\nKonsolidierung für {wallet_name} (Dust < {dust_limit:,} sats)\n", flush=True)
    run_dust_consolidation_prompt(
        utxos,
        session.wallet_ctx,
        dust_limit,
        session.cache_dir.parent / "psbt_out",
        cache_source=session.source,
        fulcrum=session.fulcrum,
    )
    _read_line("\nEnter zum Fortfahren...")



def _sanction_list_line(session: MenuSession) -> None:
    from sanctioned import format_sanctioned_status

    print(
        f"\nSanktionsliste: "
        f"{format_sanctioned_status(session.sanctioned_meta, len(session.sanctioned_addresses))}",
        flush=True,
    )


def _sanctions_fulcrum_backend(session: MenuSession) -> dict | None:
    """Dedizierter Clearnet-Fulcrum für OFAC-Abfragen (unabhängig von der Wallet-Datenquelle)."""
    from main import build_sanctions_fulcrum_fetchers

    fetchers = build_sanctions_fulcrum_fetchers(session)
    return fetchers or None


def _require_sanction_list(session: MenuSession) -> bool:
    if session.sanctioned_addresses:
        return True
    print(
        "\n  ⚠️  Keine Sanktionsliste geladen. "
        "Bitte unter Einstellungen (7) → [7] Aktualisiere Sanktions- & Blacklists.",
        flush=True,
    )
    _read_line("\nEnter zum Fortfahren...")
    return False


def _menu_sanctions_wallet(session: MenuSession) -> None:
    from analyze import check_wallet_utxos_sanctions, print_sanction_check_report

    print("\nWallet für Sanktionsprüfung auswählen:", flush=True)
    print("  " + t("cli.allWallets"))
    for index, xpub in enumerate(session.args.xpubs, start=1):
        name = session.wallet_ctx.xpub_label(xpub)
        print(f"  {index}. {name}")
    choice = _read_line(t("cli.prompt.number"))
    if not choice.isdigit():
        print(f"  ⚠️  {t('cli.warn.invalidInput')}", flush=True)
        return

    index = int(choice)
    if index < 0 or index > len(session.args.xpubs):
        print(f"  ⚠️  {t('cli.warn.outOfRange')}", flush=True)
        return

    raw_hops = _read_line(
        "Externe Hops vor Wallet-Eingang prüfen (Enter = 3): "
    )
    if not raw_hops.strip():
        max_hops = 3
    else:
        if not raw_hops.strip().isdigit() or int(raw_hops.strip()) < 1:
            print(f"  ⚠️  {t('cli.warn.positiveNumber')}", flush=True)
            return
        max_hops = min(int(raw_hops.strip()), 20)

    if index == 0:
        targets = [
            (xpub, session.wallet_ctx.xpub_label(xpub))
            for xpub in session.args.xpubs
        ]
    else:
        xpub = session.args.xpubs[index - 1]
        targets = [(xpub, session.wallet_ctx.xpub_label(xpub))]

    _sanction_list_line(session)

    from display import cancellable_output

    wallet_ctx = cancellable_output(hint="Sanktionsprüfung — q zum Abbrechen")
    with wallet_ctx:
        for xpub, wallet_name in targets:
            if wallet_ctx.aborted:
                break
            utxos = _resolve_wallet_utxos(
                session, xpubs=[xpub], use_cache_only=True,
            )
            utxos = _filter_utxos_for_wallet(utxos, wallet_name, session.wallet_ctx)
            if not utxos:
                print('\n' + t('cli.noUtxosWallet', wallet=wallet_name), flush=True)
                continue

            print(
                f"\nPrüfe {len(utxos)} UTXO(s) in {wallet_name} "
                f"({max_hops} externe Hop(s))…",
                flush=True,
            )
            get_tx = session.get_tx
            if get_tx is None:
                sanctions_backend = _sanctions_fulcrum_backend(session)
                if sanctions_backend:
                    get_tx = sanctions_backend.get("get_tx")
            if get_tx is None:
                print(f"  ⚠️  {t('cli.warn.noTxFetch')}", flush=True)
                break

            hits, checked, abort_hit = check_wallet_utxos_sanctions(
                get_tx,
                utxos,
                session.all_addresses,
                session.sanctioned_addresses,
                max_hops=max_hops,
                wallet=session.wallet_ctx,
                abort_on_hit=True,
            )
            if wallet_ctx.aborted:
                break
            print_sanction_check_report(
                hits,
                wallet_name=wallet_name,
                max_hops=max_hops,
                utxo_count=checked,
                sanctioned_count=len(session.sanctioned_addresses),
                aborted=abort_hit is not None,
            )
            if abort_hit:
                from display import abbrev_display, format_utxo_ref

                print(
                    f"\n  ⚠️  Abbruch: sanktionierte Adresse "
                    f"{abbrev_display(abort_hit['address'])} in Hop "
                    f"{abort_hit['hop']} (UTXO {format_utxo_ref(abort_hit['from_utxo'])})",
                    flush=True,
                )
                break

    if wallet_ctx.aborted:
        return
    _read_line("\nEnter zum Fortfahren...")


def _menu_sanctions_scan_utxos(session: MenuSession) -> None:
    from analyze import (
        print_sanctioned_utxo_findings,
        print_sanctioned_utxo_scan_report,
        scan_sanctioned_address_utxos,
    )
    from display import SanctionParallelScanProgress, SanctionUtxoScanProgressLine, cancellable_output

    _sanction_list_line(session)
    sanctions_backend = _sanctions_fulcrum_backend(session)
    fetch_utxoset = None
    fulcrum_pool = None
    if session.source == "bip158":
        _ensure_connected(session)
        fetch_utxoset = (
            session.fetch_addresses_utxos_utxoset or session.fetch_addresses_utxos
        )
    if not fetch_utxoset and sanctions_backend:
        fetch_utxoset = sanctions_backend.get("fetch_addresses_utxos_utxoset")
        fulcrum_pool = sanctions_backend.get("fulcrum_pool")
    if not fetch_utxoset:
        print(f"  ⚠️  {t('cli.warn.noAddrScan')}", flush=True)
        return

    entity_groups = session.sanctioned_entities
    addr_count = len(session.sanctioned_addresses)
    batch_size = 40
    total_batches = (addr_count + batch_size - 1) // batch_size if addr_count else 0
    use_parallel = fulcrum_pool is not None and len(fulcrum_pool) > 1
    parallel_progress = None
    progress = None
    if use_parallel:
        parallel_progress = SanctionParallelScanProgress(
            worker_labels=fulcrum_pool.worker_labels(),
            total_addrs=addr_count,
            total_batches=total_batches,
            title="Sanktions-UTXO-Scan",
        )
    else:
        progress = SanctionUtxoScanProgressLine()
    utxos: list[dict] = []
    scan_ctx = cancellable_output(hint="Sanktions-UTXO-Scan — q zum Abbrechen")
    with scan_ctx:
        try:
            def on_progress(**kw) -> None:
                if progress is None:
                    return
                progress.update(
                    batch_index=kw["batch_index"],
                    total_batches=kw["total_batches"],
                    addrs_done_in_batch=kw["addrs_done_in_batch"],
                    addrs_in_batch=kw["addrs_in_batch"],
                    utxos_found=kw.get("utxos_found", 0),
                )

            def on_batch_findings(
                batch_utxos: list[dict],
                batch_index: int,
                total_batches: int,
                *,
                entity_groups=None,
            ) -> None:
                from display import is_list_abort_requested

                if is_list_abort_requested():
                    return
                if progress is not None:
                    progress.finalize_batch_line()
                print_sanctioned_utxo_findings(
                    batch_utxos,
                    entity_groups or session.sanctioned_entities,
                    batch_index=batch_index,
                    total_batches=total_batches,
                )

            print(
                f"\nScanne {addr_count:,} sanktionierte "
                f"Adressen auf unspent UTXOs…",
                flush=True,
            )
            if session.source == "bip158":
                print(
                    "  (scantxoutset, ggf. BIP-158 ab Höhe 0 — "
                    "unabhängig von BIP158_START_HEIGHT)",
                    flush=True,
                )
            if use_parallel:
                parallel_progress.start()
            utxos = scan_sanctioned_address_utxos(
                fetch_utxoset,
                session.sanctioned_addresses,
                on_progress=on_progress,
                on_batch_findings=on_batch_findings,
                entity_groups=entity_groups,
                single_fetch=(session.source == "bip158"),
                fulcrum_pool=fulcrum_pool if use_parallel else None,
                parallel_progress=parallel_progress,
            )
        finally:
            if parallel_progress is not None:
                parallel_progress.finish()
            elif progress is not None:
                progress.finish()

        if not scan_ctx.aborted:
            print_sanctioned_utxo_scan_report(
                utxos,
                entity_groups=entity_groups,
                wrap_cancellable=False,
            )
    if scan_ctx.aborted:
        return
    _read_line("\nEnter zum Fortfahren...")


def _menu_sanctions_overview(session: MenuSession) -> None:
    from interact import prompt_yes_no
    from sanctioned import (
        check_sanctions_source_updates,
        format_entities_status,
        format_sanctioned_status,
        load_sanctioned_address_index,
        load_sanctioned_entities,
        print_sanctions_overview,
        print_sanctions_source_update_status,
        update_sanctioned_lists,
    )

    _sanction_list_line(session)
    groups, entities_meta = load_sanctioned_entities()
    session.sanctioned_entities = groups
    session.sanctioned_entities_meta = entities_meta

    if not session.sanctioned_addresses:
        print(
            "\n  ⚠️  Keine Sanktionsliste geladen. "
            "Bitte unter Einstellungen (7) → [7] Aktualisiere Sanktions- & Blacklists.",
            flush=True,
        )
        _read_line("\nEnter zum Fortfahren...")
        return

    print(
        f"\n  {format_sanctioned_status(session.sanctioned_meta, len(session.sanctioned_addresses))}",
        flush=True,
    )
    if print_sanctions_overview(
        groups,
        session.sanctioned_meta,
        entities_meta=entities_meta,
        address_index=load_sanctioned_address_index(),
    ):
        return

    print("\n  " + t("cli.sanctions.checkOnline"), flush=True)
    update_checks = check_sanctions_source_updates(session.sanctioned_meta)
    updates_available = print_sanctions_source_update_status(update_checks)
    if updates_available:
        update_count = sum(
            1 for check in update_checks if check.status == "update_available"
        )
        plural = "Quelle(n)" if update_count != 1 else "Quelle"
        print(
            f"\n  Neuere Version für {update_count} {plural} verfügbar. "
            "Sanktionslisten aktualisieren? (j/N)",
            end=" ",
            flush=True,
        )
        if prompt_yes_no(default_yes=False):
            print(
                "\n  Aktualisiere Sanktions- und Blacklists "
                "(OFAC, OpenSanctions, Scam-Listen)…",
                flush=True,
            )
            try:
                addresses, meta = update_sanctioned_lists()
            except OSError as exc:
                print(f"  ⚠️  {t('cli.warn.downloadFailed', exc=exc)}", flush=True)
            else:
                session.sanctioned_addresses = addresses
                session.sanctioned_meta = meta
                groups, entities_meta = load_sanctioned_entities()
                session.sanctioned_entities = groups
                session.sanctioned_entities_meta = entities_meta
                print(
                    f"  → {format_sanctioned_status(meta, len(addresses))} gespeichert "
                    f"(sanctioned_cache/).",
                    flush=True,
                )
                if groups:
                    print(
                        f"  → {format_entities_status(entities_meta, group_count=len(groups))} "
                        f"(sanctioned_entities_XBT.json).",
                        flush=True,
                    )

    _read_line("\nEnter zum Fortfahren...")


def _menu_sanctions_show_groups(session: MenuSession) -> None:
    from sanctioned import (
        format_entities_status,
        load_sanctioned_entities,
        print_sanctioned_entity_detail,
        print_sanctioned_entity_groups,
    )

    _sanction_list_line(session)
    groups, entities_meta = load_sanctioned_entities()
    session.sanctioned_entities = groups
    session.sanctioned_entities_meta = entities_meta

    if not groups:
        print(
            "\n  ⚠️  Keine Gruppendaten (Person/Grund/Quelle). "
            "Bitte unter Einstellungen (7) → [7] Aktualisiere Sanktions- & Blacklists — "
            "lädt OFAC, OpenSanctions und Scam-Listen.",
            flush=True,
        )
        _read_line("\nEnter zum Fortfahren...")
        return

    print(
        f"\n  {format_entities_status(entities_meta, group_count=len(groups))}",
        flush=True,
    )
    if print_sanctioned_entity_groups(
        groups,
        all_addresses=session.sanctioned_addresses,
    ):
        return

    while True:
        raw = _read_line(
            "\nGruppen-Nr. für alle Adressen (Enter = zurück): "
        )
        if not raw.strip():
            break
        if not raw.isdigit():
            print(f"  ⚠️  {t('cli.warn.numberOrEnter')}", flush=True)
            continue
        index = int(raw)
        if index < 1 or index > len(groups):
            print(f"  ⚠️  {t('cli.warn.range1n', n=len(groups))}", flush=True)
            continue
        if print_sanctioned_entity_detail(groups[index - 1]):
            return

    _read_line("\nEnter zum Fortfahren...")


def menu_check_sanctions(session: MenuSession) -> None:
    if not _require_sanction_list(session):
        return

    while True:
        print(f"\n{'─' * 72}")
        print("  Prüfe Sanktionsliste")
        _sanction_list_line(session)
        print("  " + t("cli.sanctions.m1"))
        print("  " + t("cli.sanctions.m2"))
        print("  " + t("cli.sanctions.m3"))
        print("  " + t("cli.sanctions.m4"))
        print("  " + t("cli.sanctions.m5"))
        choice = _read_line("\nAuswahl [1-5]: ")
        if choice == "1":
            _menu_sanctions_wallet(session)
        elif choice == "2":
            _menu_sanctions_scan_utxos(session)
        elif choice == "3":
            _menu_sanctions_overview(session)
        elif choice == "4":
            _menu_sanctions_show_groups(session)
        elif choice in ("5", "b", "back", ""):
            return
        else:
            print(f"  ⚠️  {t('cli.warn.choose15')}", flush=True)
def menu_show_analyzed_utxos(session: MenuSession) -> None:
    from main import print_analyzed_utxo_ingress_report, resolve_immutable_cache_dir

    print_analyzed_utxo_ingress_report(
        resolve_immutable_cache_dir(session.args),
        utxo_cache_dir=session.cache_dir,
    )
    _read_line("\nEnter zum Fortfahren...")


def _interactive_ranking(session: MenuSession, ranked: list[dict]) -> None:
    from main import resolve_immutable_cache_dir

    f_hint = (
        "'f' alle UTXOs tracen, 'F' + transaktionsorientiert (ohne erneuten Scan)"
        if ranked
        else None
    )

    interactive_analyze_top_utxos(
        session.get_tx,
        session.fetch_utxos,
        ranked,
        session.all_addresses,
        shown_count=session.top_utxos_limit,
        wallet=session.wallet_ctx,
        cache_dir=session.cache_dir,
        fetch_address_utxos=session.fetch_address_utxos,
        cache_source=session.source,
        output_dir=session.cache_dir.parent / "psbt_out",
        fulcrum=session.fulcrum,
        immutable_cache_dir=resolve_immutable_cache_dir(session.args),
        f_hint=f_hint,
    )


def _reload_session_env(session: MenuSession) -> None:
    from main import ENV_FILE, _load_dotenv

    session.env = _load_dotenv(ENV_FILE)
    session.connected = False
    raw_start = session.env.get("BIP158_START_HEIGHT")
    if raw_start:
        try:
            session.bip158_start = int(raw_start)
            session.args.bip158_start = session.bip158_start
        except ValueError:
            pass
    print('  → ' + t('cli.env.reread', name=ENV_FILE.name), flush=True)
    print(
        "  → Datenquelle wird beim nächsten Zugriff mit den neuen Werten verbunden.",
        flush=True,
    )


def _menu_edit_env(session: MenuSession) -> None:
    from main import ENV_FILE, open_env_file_in_editor

    try:
        open_env_file_in_editor(ENV_FILE)
    except OSError as exc:
        print(f"  ⚠️  {t('cli.warn.editorFailed', exc=exc)}", flush=True)
        return
    _reload_session_env(session)


def _menu_launch_check_fulcrum_tor(session: MenuSession) -> None:
    from main import launch_check_fulcrum_tor_external

    try:
        launch_check_fulcrum_tor_external()
        print("  → " + t("cli.checkFulcrum.started"), flush=True)
        print(
            "  → Erreichbare Server in .env eintragen, danach [5] .env bearbeiten.",
            flush=True,
        )
    except (OSError, RuntimeError, FileNotFoundError) as exc:
        print(f"  ⚠️  {exc}", flush=True)




def _load_sanctioned_into_session(session: MenuSession) -> None:
    from sanctioned import load_sanctioned_entities, load_sanctioned_xbt_addresses

    addresses, meta = load_sanctioned_xbt_addresses()
    session.sanctioned_addresses = addresses
    session.sanctioned_meta = meta
    groups, entities_meta = load_sanctioned_entities()
    session.sanctioned_entities = groups
    session.sanctioned_entities_meta = entities_meta


def _menu_update_sanctioned_xbt(session: MenuSession) -> None:
    from sanctioned import (
        format_entities_status,
        format_sanctioned_status,
        load_sanctioned_entities,
        update_sanctioned_lists,
    )

    print(
        "\nAktualisiere Sanktions- und Blacklists "
        "(OFAC, OpenSanctions, Scam-Listen)…",
        flush=True,
    )
    try:
        addresses, meta = update_sanctioned_lists()
    except OSError as exc:
        print(f"  ⚠️  {t('cli.warn.downloadFailed', exc=exc)}", flush=True)
        return
    session.sanctioned_addresses = addresses
    session.sanctioned_meta = meta
    groups, entities_meta = load_sanctioned_entities()
    session.sanctioned_entities = groups
    session.sanctioned_entities_meta = entities_meta
    print(
        f"  → {format_sanctioned_status(meta, len(addresses))} gespeichert "
        f"(sanctioned_cache/).",
        flush=True,
    )
    if groups:
        print(
            f"  → {format_entities_status(entities_meta, group_count=len(groups))} "
            f"(sanctioned_entities_XBT.json).",
            flush=True,
        )

def menu_settings(session: MenuSession) -> None:

    while True:
        print(f"\n{'─' * 72}")
        print("  " + t("cli.settings.title"))
        print(f"  {t('cli.settings.currentSource', line=_source_line(session))}")
        print(f"  {t('cli.settings.topLimit', n=session.top_utxos_limit)}")
        if session.source == "bip158" or session.args.bip158:
            print(f"  {t('cli.settings.bip158Start', n=f'{session.bip158_start:,}')}")
        print(f"  Verbose: {'ja' if session.verbose else 'nein'}")
        from main import resolve_wallets_beim_start_aktualisieren

        start_sync = resolve_wallets_beim_start_aktualisieren(session.env)
        print(
            f"  Wallets immer aktuell halten: "
            f"{'ja' if start_sync else 'nein'}"
        )
        from sanctioned import format_entities_status, format_sanctioned_status

        print(
            f"  Sanktionierte XBT: "
            f"{format_sanctioned_status(session.sanctioned_meta, len(session.sanctioned_addresses))}"
        )
        print(
            f"  Adress-Gruppen: "
            f"{format_entities_status(session.sanctioned_entities_meta, group_count=len(session.sanctioned_entities))}"
        )
        print("  " + t("cli.settings.1"))
        print("  " + t("cli.settings.2"))
        print("  " + t("cli.settings.3"))
        print("  " + t("cli.settings.4"))
        print("  " + t("cli.settings.5"))
        print("  " + t("cli.settings.6"))
        print("  " + t("cli.settings.7"))
        print("  " + t("cli.settings.8"))
        print("  " + t("cli.settings.9"))
        choice = _read_line(t("cli.prompt.choice"))

        if choice in ("9", "b", "z", "back", ""):
            return
        if choice == "1":
            from interact import prompt_data_source

            src = prompt_data_source(
                heading="Datenquelle wählen:",
                strict=False,
            )
            if src is None:
                print(f"  ⚠️  {t('cli.warn.invalidChoice')}", flush=True)
                continue
            _apply_data_source_choice(session, src)
            session.connected = False
            try:
                connect_blockchain(session, interactive_onion=True)
                print("  → " + t("cli.source.updated"), flush=True)
            except (SystemExit, RuntimeError) as exc:
                print(f"  ⚠️  {t('cli.warn.connectFailed', exc=exc)}", flush=True)
                session.connected = False
            continue
        if choice == "2":
            print(
                f"\nStart-Blockhöhe (Enter = {DEFAULT_BIP158_START_HEIGHT:,}) "
                f"oder Datum DD.MM.YYYY:",
                flush=True,
            )
            raw = _read_line("> ")
            if not raw:
                session.bip158_start = DEFAULT_BIP158_START_HEIGHT
            elif raw.isdigit():
                session.bip158_start = int(raw)
            else:
                try:
                    session.bip158_start = _resolve_height_for_date(session)(raw)
                    print('  → ' + t('cli.source.dateBlock', n=f'{session.bip158_start:,}'), flush=True)
                except (ValueError, OSError) as exc:
                    print(f"  ⚠️  {exc}", flush=True)
                    continue
            session.args.bip158_start = session.bip158_start
            if session.args.bip158:
                session.connected = False
                try:
                    connect_blockchain(session, interactive_onion=True)
                except (SystemExit, RuntimeError) as exc:
                    print(f"  ⚠️  {exc}", flush=True)
            continue
        if choice == "3":
            raw = _read_line(f"Top-N (Enter = {DEFAULT_TOP_UTXOS}): ")
            if raw:
                if not raw.isdigit() or int(raw) < 1:
                    print(f"  ⚠️  {t('cli.warn.positiveNumber')}", flush=True)
                    continue
                session.top_utxos_limit = int(raw)
            else:
                session.top_utxos_limit = DEFAULT_TOP_UTXOS
            continue
        if choice == "4":
            from interact import prompt_yes_no

            print("Verbose (volle TxID/UTXO/Adressen)? [j/N]: ", end="", flush=True)
            session.verbose = prompt_yes_no(default_yes=session.verbose)
            set_verbose(session.verbose)
            if session.backend and hasattr(session.backend, "get") and session.backend.get("client"):
                client = session.backend["client"]
                client.verbose = session.verbose
            print(f"  → Verbose: {'ja' if session.verbose else 'nein'}", flush=True)
            continue
        if choice == "5":
            from interact import prompt_yes_no
            from core.config import EnvFile
            from main import ENV_FILE, resolve_wallets_beim_start_aktualisieren
            from pathlib import Path

            aktuell = resolve_wallets_beim_start_aktualisieren(session.env)
            print(
                "Wallets immer aktuell halten "
                "(Electrs-Subscribe + Tip-Nachzug, kein Fullscan)? "
                f"[{'J/n' if aktuell else 'j/N'}]: ",
                end="",
                flush=True,
            )
            an = prompt_yes_no(default_yes=aktuell)
            env_path = Path(getattr(session.args, "env", None) or ENV_FILE)
            env_datei = EnvFile.load(env_path)
            env_datei.apply(
                {
                    "WALLETS_IMMER_AKTUELL": "1" if an else "0",
                    "WALLETS_BEIM_START_AKTUALISIEREN": "1" if an else "0",
                }
            )
            try:
                env_datei.save()
            except OSError as exc:
                print(f"  ⚠️  {t('cli.warn.envNotWritten', exc=exc)}", flush=True)
                continue
            session.env["WALLETS_IMMER_AKTUELL"] = "1" if an else "0"
            session.env["WALLETS_BEIM_START_AKTUALISIEREN"] = "1" if an else "0"
            print(
                f"  → Wallets immer aktuell halten: "
                f"{'ja' if an else 'nein'}",
                flush=True,
            )
            continue
        if choice == "6":
            _menu_edit_env(session)
            continue
        if choice == "7":
            _menu_launch_check_fulcrum_tor(session)
            continue
        if choice == "8":
            _menu_update_sanctioned_xbt(session)
            continue
        print(f"  ⚠️  {t('cli.warn.invalidChoice')}", flush=True)


def _aktualisiere_wallets_beim_start(session: MenuSession) -> None:
    """Cache bis Chain-Tip nachziehen, wenn in der .env eingeschaltet."""
    from main import (
        load_xpub_cache_entry,
        resolve_wallets_beim_start_aktualisieren,
        sync_wallets_zum_tip,
        try_bip158_fetch_for_tip_sync,
    )

    if not resolve_wallets_beim_start_aktualisieren(session.env):
        return
    if not session.connected or not session.fetch_wallet_utxos:
        return
    xpubs = list(session.wallet_ctx.xpubs) if session.wallet_ctx else []
    mit_cache = [
        x for x in xpubs if load_xpub_cache_entry(x, session.cache_dir)
    ]
    if not mit_cache:
        return
    print(
        "\n" + t("cli.startUpdate.running", n=len(mit_cache)),
        flush=True,
    )
    bip158_fetch = None
    quelle = session.source or "fulcrum"
    from main import is_own_fulcrum_backend, resolve_immutable_cache_dir

    electrs_eigen = (
        quelle == "fulcrum"
        and session.fulcrum is not None
        and is_own_fulcrum_backend(session.fulcrum)
    )
    if electrs_eigen:
        # Eigener Electrs: kein BIP-158-Tip — light + Subscribe reicht.
        bip158_fetch = None
    elif quelle == "bip158":
        bip158_fetch = session.fetch_wallet_utxos
    else:
        try:
            bip158_fetch = try_bip158_fetch_for_tip_sync(
                session.args,
                session.env,
                session.wallet_ctx,
                immutable_cache_dir=resolve_immutable_cache_dir(
                    session.args
                ),
            )
        except (SystemExit, RuntimeError, OSError):
            bip158_fetch = None
    try:
        sync_wallets_zum_tip(
            mit_cache,
            session.fetch_wallet_utxos,
            session.fetch_address_utxos,
            session.fetch_addresses_utxos,
            session.cache_dir,
            quelle,
            wallet=session.wallet_ctx,
            fulcrum=session.fulcrum,
            verify_utxo_spent=session.verify_utxo_spent,
            bip158_fetch_wallet_utxos=bip158_fetch,
            on_progress=lambda text, **_k: print(f"  … {translate_line(text)}", flush=True),
        )
    except (SystemExit, RuntimeError, OSError) as exc:
        print(f"  ⚠️  {t('cli.warn.startUpdate', exc=exc)}", flush=True)


def run_main_menu(session: MenuSession) -> None:
    """Hauptmenü-Schleife."""
    init_from_env(getattr(session, "env", None) or {})
    install_stdout_translation()
    set_verbose(session.verbose)
    _load_sanctioned_into_session(session)
    if not session.connected:
        try:
            connect_blockchain(session)
        except (SystemExit, RuntimeError) as exc:
            msg = str(exc) if str(exc) else type(exc).__name__
            print(
                "\n" + t("cli.noSource", msg=msg) + "\n",
                flush=True,
            )
    _aktualisiere_wallets_beim_start(session)

    while True:
        _clear_screen()
        print_status(session)
        print_main_menu(session)
        choice = _read_line(t("cli.prompt.choice18"))

        if choice in ("8", "q", "quit", "exit"):
            print(t("cli.quit"), flush=True)
            return
        if choice == "1":
            try:
                menu_trace(session)
            except SystemExit as exc:
                print(f"\n⚠️  {exc}", flush=True)
            continue
        if choice == "2":
            try:
                menu_wallet_ranking(session)
            except SystemExit as exc:
                print(f"\n⚠️  {exc}", flush=True)
            continue
        if choice == "3":
            try:
                menu_all_wallets_ranking(session)
            except SystemExit as exc:
                print(f"\n⚠️  {exc}", flush=True)
            continue
        if choice == "4":
            menu_show_analyzed_utxos(session)
            continue
        if choice == "5":
            try:
                menu_utxo_consolidation(session)
            except SystemExit as exc:
                print(f"\n⚠️  {exc}", flush=True)
            continue
        if choice == "6":
            try:
                menu_check_sanctions(session)
            except SystemExit as exc:
                print(f"\n⚠️  {exc}", flush=True)
            continue
        if choice == "7":
            menu_settings(session)
            continue
        print(f"  ⚠️  {t('cli.warn.choose18')}", flush=True)