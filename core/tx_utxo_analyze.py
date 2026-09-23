"""CLI Tx/UTXO-Analyse: analyze_tx, Adress-UTXOs, Batch-Trace (Slice 4).

Specter-/interact-Einstiege und Batch-Progress. analyze.py re-exportiert die
öffentliche API. Late-Import in core.utxo_ingress_report (_run_tx_oriented_followups)
zeigt auf dieses Modul statt auf analyze, damit kein Domänen-Zyklus core → analyze
entsteht.
"""
from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

from display import (
    abbrev_display,
    format_utxo_display,
    format_utxo_ref,
    is_list_abort_requested,
)

from trace_engine import (
    CoinbaseFunding,
    iter_funding_inputs,
)

from core.utxo_origin import (
    _is_own_address,
    _parse_utxo_ref,
)

from core.utxo_ingress_report import (
    TxFollowupContext,
    UtxoFollowupContext,
    _analyze_utxo_funding,
    _format_amount_display,
    _run_tx_oriented_followups,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


def analyze_tx(
    get_tx,
    txid: str,
    own_addresses: set,
    analyzed_txs: set | None = None,
    depth: int = 0,
    trace_funding: bool = True,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    allow_tx_followup: bool = False,
    cancel_cb=None,
    progress_cb=None,
) -> TxFollowupContext | None:
    """Analysiert die Tx und zeigt eigene Adressen als Input/Output."""
    from core.jobs import Cancelled, ist_abbruch

    if analyzed_txs is None:
        analyzed_txs = set()

    if cancel_cb and cancel_cb():
        raise Cancelled()

    if txid in analyzed_txs:
        return
    analyzed_txs.add(txid)

    try:
        tx = get_tx(txid)
    except urllib.error.HTTPError as e:
        print(f"Fehler beim Laden der Tx: HTTP {e.code} ({e.reason})")
        return
    except Exception as e:
        if ist_abbruch(e):
            raise
        print(f"Fehler beim Laden der Tx: {e}")
        return

    header_pad = "   " * depth
    print(f"\n{header_pad}{'='*85}")
    print(f"{header_pad}TxID: {abbrev_display(txid)}" + ("  [Herkunfts-Analyse]" if depth else ""))
    print(f"{header_pad}{'='*85}\n")

    found_inputs = []
    found_outputs = []
    external_outputs = []

    for inp in iter_funding_inputs(get_tx, txid):
        if isinstance(inp, CoinbaseFunding):
            continue
        try:
            value = inp.amount_sats / 1e8
            for addr in inp.addresses:
                if _is_own_address(addr, own_addresses, wallet):
                    found_inputs.append({
                        "address": addr,
                        "amount": value,
                        "amount_sats": inp.amount_sats,
                        "from_tx": inp.prevout.key,
                    })
        except Exception as exc:
            if ist_abbruch(exc):
                raise
            continue

    for vout in tx.get("vout", []):
        addrs = _main()._extract_addresses(vout)
        value_sats = _main()._extract_value_sats(vout)
        value = value_sats / 1e8

        if addrs and not any(_is_own_address(addr, own_addresses, wallet) for addr in addrs):
            external_outputs.append({
                "addresses": addrs,
                "amount_sats": value_sats,
                "amount": value,
            })

        for addr in addrs:
            if _is_own_address(addr, own_addresses, wallet):
                found_outputs.append({
                    "address": addr,
                    "amount": value
                })

    if found_inputs:
        print(f"{header_pad}📤 Eigene Wallets als INPUT (gesendet):")
        for item in found_inputs:
            label = (
                wallet.resolve_address(item["address"]) if wallet else item["address"]
            )
            print(f"{header_pad}   {label}   {_format_amount_display(item['amount_sats'])}")
            print(f"{header_pad}      (aus vorheriger Tx: {format_utxo_ref(item['from_tx'])})")
    else:
        print(f"{header_pad}📤 Keine eigenen Wallets als Input gefunden.")

    print()

    if found_outputs:
        print(f"{header_pad}📥 Eigene Wallets als OUTPUT (empfangen / Change):")
        for item in found_outputs:
            label = (
                wallet.resolve_address(item["address"]) if wallet else item["address"]
            )
            print(
                f"{header_pad}   {label}   "
                f"{_format_amount_display(int(round(item['amount'] * 1e8)))}"
            )
    else:
        print(f"{header_pad}📥 Keine eigenen Wallets als OUTPUT gefunden.")

    print()

    total_external_sats = sum(item["amount_sats"] for item in external_outputs)
    if external_outputs:
        print(f"{header_pad}💸 An Zieladressen außerhalb der eigenen Wallets:")
        for item in external_outputs:
            for addr in item["addresses"]:
                print(
                    f"{header_pad}   {abbrev_display(addr)}   "
                    f"{_format_amount_display(item['amount_sats'])}"
                )
        print(
            f"{header_pad}\n   Gesamt verlassen: "
            f"{_format_amount_display(total_external_sats)}"
        )
    elif found_inputs:
        print(f"{header_pad}💸 Keine Ausgänge an Adressen außerhalb der eigenen Wallets.")

    print(f"\n{header_pad}🕐 Zeitpunkt: {_main()._format_tx_time(tx)}")

    internal_predecessors = set()

    if trace_funding and found_inputs:
        print(f"\n{header_pad}{'─'*85}")
        print(f"{header_pad}🔍 Herkunft der Input-Sats (wie kam es auf die Adresse?):")
        print(f"{header_pad}{'─'*85}\n")

        for item in found_inputs:
            parsed = _parse_utxo_ref(item["from_tx"])
            if not parsed:
                continue
            creator_txid, vout_index = parsed

            input_label = (
                wallet.resolve_address(item["address"]) if wallet else item["address"]
            )
            print(f"{header_pad}Input {input_label} ({_format_amount_display(item['amount_sats'])}):")
            _analyze_utxo_funding(
                get_tx,
                item["address"],
                item["amount_sats"],
                creator_txid,
                vout_index,
                own_addresses,
                header_pad,
                depth,
                internal_predecessors,
                wallet=wallet,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_address_utxos,
                cache_source=cache_source,
                spend_txid=txid,
            )

    elif found_outputs and not found_inputs:
        print(f"\n{header_pad}{'─'*85}")
        entry_wallets = sorted({
            wallet.resolve_address(item["address"])
            for item in found_outputs
            if wallet and wallet.resolve_address(item["address"])
        })
        wallet_str = ", ".join(entry_wallets) if entry_wallets else (
            wallet.scope_label() if wallet else "das Wallet"
        )
        print(f"{header_pad}🏦 Sats betraten {wallet_str} (diese Tx):")
        print(f"{header_pad}{'─'*85}\n")
        tx_time = _main()._format_tx_time(tx)
        for item in found_outputs:
            print(f"{header_pad}   {tx_time}")
            out_label = (
                wallet.resolve_address(item["address"]) if wallet else item["address"]
            )
            print(
                f"{header_pad}      {out_label}   "
                f"{_format_amount_display(int(round(item['amount'] * 1e8)))}"
            )

    print(f"\n{header_pad}{'='*85}")
    summary = f"Zusammenfassung: {len(found_inputs)} Input(s) | {len(found_outputs)} Output(s)"
    if total_external_sats:
        summary += f" | {_format_amount_display(total_external_sats)} extern gesendet"
    print(f"{header_pad}{summary}")
    print(f"{header_pad}{'='*85}")


    predecessors = {p for p in internal_predecessors if p != txid}
    if predecessors and allow_tx_followup:
        _run_tx_oriented_followups(
            get_tx,
            predecessors,
            txid,
            own_addresses,
            analyzed_txs,
            depth,
            wallet,
            cache_dir,
            fetch_address_utxos,
            cache_source,
            cancel_cb=cancel_cb,
            progress_cb=progress_cb,
        )
        return None
    if predecessors:
        return TxFollowupContext(
            predecessors=predecessors,
            found_inputs=found_inputs,
            found_outputs=found_outputs,
            total_external_sats=total_external_sats,
            txid=txid,
            depth=depth,
            analyzed_txs=analyzed_txs,
        )
    return None


def analyze_address_utxos(
    get_tx,
    fetch_utxos,
    address: str,
    own_addresses: set,
    utxo_ref: str | None = None,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
) -> UtxoFollowupContext | None:
    """Analysiert unspent UTXO(s) auf einer Wallet-Adresse und deren Herkunft."""
    if not _is_own_address(address, own_addresses, wallet):
        print(f"⚠️  Adresse {abbrev_display(address)} nicht in abgeleiteten XPUB-Adressen.")

    try:
        utxos = fetch_utxos(address)
    except urllib.error.HTTPError as e:
        print(f"Fehler beim Laden der UTXOs: HTTP {e.code} ({e.reason})")
        return
    except Exception as e:
        print(f"Fehler beim Laden der UTXOs: {e}")
        return

    if utxo_ref:
        parsed = _parse_utxo_ref(utxo_ref)
        if not parsed:
            print(f"Ungültiges --utxo Format: {format_utxo_ref(utxo_ref)} (erwartet: txid:vout)")
            return
        filter_txid, filter_vout = parsed
        utxos = [
            u for u in utxos
            if u["txid"] == filter_txid and u["vout"] == filter_vout
        ]
        if not utxos:
            print(f"UTXO {format_utxo_ref(utxo_ref)} ist nicht unspent auf {abbrev_display(address)}")
            return

    if not utxos:
        print(f"Keine unspent UTXOs auf {abbrev_display(address)}")
        return

    total_sats = sum(u["value"] for u in utxos)
    print(f"\n{'='*85}")
    wallet_label = wallet.resolve_address(address) if wallet else None
    if wallet_label:
        print(f"Wallet: {wallet_label}")
    else:
        print(f"Adresse: {abbrev_display(address)}")
    print(
        f"Unspent: {len(utxos)} UTXO(s), {_format_amount_display(total_sats)} gesamt"
    )
    print(f"{'='*85}\n")

    analyzed_txs: set[str] = set()
    internal_predecessors: set[str] = set()

    for index, utxo in enumerate(utxos, start=1):
        txid = utxo["txid"]
        vout = utxo["vout"]
        value = utxo["value"]
        try:
            from bip158_scanner import note_tx_height

            status = utxo.get("status") or {}
            note_tx_height(txid, status.get("block_height") or utxo.get("height"))
        except Exception:
            pass

        print(f"{'─'*85}")
        print(f"UTXO {index}/{len(utxos)}: {format_utxo_display(txid, vout, address=address)}")
        print(f"   Betrag: {_format_amount_display(value)}")
        print(f"   Auf Adresse seit: {_main()._format_utxo_status(utxo)}\n")
        print("🔍 Herkunft der Sats (wie kam es auf die Adresse?):")
        print()

        _analyze_utxo_funding(
            get_tx,
            address,
            value,
            txid,
            vout,
            own_addresses,
            "",
            0,
            internal_predecessors,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
        )

    print(f"\n{'='*85}")
    print(f"Zusammenfassung: {len(utxos)} unspent UTXO(s) | {_format_amount_display(total_sats)}")
    print(f"{'='*85}")


    predecessors = set(internal_predecessors)
    if predecessors:
        return UtxoFollowupContext(
            predecessors=predecessors,
            utxo_count=len(utxos),
            analyzed_txs=analyzed_txs,
        )
    return None


def _print_utxo_batch_progress(done: int, total: int) -> None:
    """Fortschritt im Batch-UTXO-Trace (f/F): Anteil in % und Anzahl."""
    if total <= 0:
        return
    pct = 100 * done // total
    print(
        f"Fortschritt: {pct}% ({done}/{total} UTXOs analysiert)\n",
        flush=True,
    )


def trace_known_utxos(
    get_tx,
    utxos: list[dict],
    own_addresses: set,
    *,
    wallet: "WalletContext | None" = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    tx_oriented_followup: bool = False,
) -> bool:
    """
    Trace bereits bekannter UTXOs ohne erneuten Adress-/UTXO-Scan.
    tx_oriented_followup: Vorgänger-Txs transaktionsorientiert nachverfolgen.
    Rückgabe: False wenn mit q abgebrochen.
    """
    if not utxos:
        print("Keine UTXOs zum Tracen.")
        return True

    sorted_utxos = sorted(utxos, key=lambda u: u["value"], reverse=True)
    total_sats = sum(u["value"] for u in sorted_utxos)
    print(f"\n{'='*85}")
    print(
        f"Trace {len(sorted_utxos)} UTXO(s), "
        f"{_format_amount_display(total_sats)}"
    )
    print(f"{'='*85}\n")

    internal_predecessors: set[str] = set()
    total_count = len(sorted_utxos)
    for index, utxo in enumerate(sorted_utxos, start=1):
        if is_list_abort_requested():
            return False
        address = utxo.get("address") or "?"
        txid = utxo["txid"]
        vout = int(utxo["vout"])
        value = int(utxo["value"])

        print(f"{'─'*85}")
        pct = 100 * (index - 1) // total_count if total_count else 0
        print(
            f"UTXO {index}/{total_count} ({pct}%): "
            f"{format_utxo_display(txid, vout, address=address)}"
        )
        print(f"   Betrag: {_format_amount_display(value)}")
        print(
            f"   Auf Adresse seit: {_main()._format_utxo_status(utxo)}\n"
        )
        print("🔍 Herkunft der Sats (wie kam es auf die Adresse?):")
        print()

        _analyze_utxo_funding(
            get_tx,
            address,
            value,
            txid,
            vout,
            own_addresses,
            "",
            0,
            internal_predecessors,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
        )
        _print_utxo_batch_progress(index, total_count)

    if is_list_abort_requested():
        return False

    print(f"\n{'='*85}")
    print(
        f"Trace abgeschlossen: 100% ({total_count}/{total_count} UTXOs) | "
        f"{_format_amount_display(total_sats)}"
    )
    print(f"{'='*85}\n")

    if tx_oriented_followup and internal_predecessors:
        if is_list_abort_requested():
            return False
        print(
            f"\nTransaktionsorientierte Folge-Analyse "
            f"({len(internal_predecessors)} Vorgänger-Tx(s))…\n",
            flush=True,
        )
        analyzed_txs: set[str] = set()
        _run_tx_oriented_followups(
            get_tx,
            internal_predecessors,
            "",
            own_addresses,
            analyzed_txs,
            0,
            wallet,
            cache_dir,
            fetch_address_utxos,
            cache_source,
        )

    return True
