"""Interaktive Prompts und Orchestrierung der Analyse."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from analyze import (
    TxFollowupContext,
    UtxoFollowupContext,
    _run_tx_oriented_followups,
    analyze_address_utxos,
    analyze_tx,
)

if TYPE_CHECKING:
    from main import WalletContext


def prompt_yes_no(default_yes: bool = True) -> bool:
    """Liest J/n von stdin; Leereingabe = default_yes."""
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    if not answer:
        return default_yes
    return answer in ("j", "ja", "y", "yes")


def prompt_wallet_scan(
    missing_xpubs: list[str],
    wallet: WalletContext | None = None,
) -> bool:
    """Fragt interaktiv, ob ein Wallet-UTXO-Scan gewünscht ist."""
    print(
        "Kein UTXO-Cache für "
        f"{len(missing_xpubs)} XPUB(s) gefunden "
        f"({', '.join(
            wallet.xpub_label(x) if wallet else x[:25] + '...'
            for x in missing_xpubs
        )})."
    )
    print(
        "Wallet-Scan nach UTXOs durchführen? "
        "(kann bei vielen Adressen einige Minuten dauern) [J/n]: ",
        end="",
        flush=True,
    )
    return prompt_yes_no()


_DATA_SOURCE_MENU_LINES = (
    "[1] Bitcoin-P2P Compact Filter (BIP-158, kein eigener Node)",
    "[2] Fulcrum / electrs (LAN, Tor, öffentliche Onions)",
)
_DATA_SOURCE_ALIASES = {
    "1": "bip158",
    "p2p": "bip158",
    "filter": "bip158",
    "bip158": "bip158",
    "core": "bip158",
    "2": "fulcrum",
    "fulcrum": "fulcrum",
    "electrum": "fulcrum",
    "f": "fulcrum",
}


def print_data_source_menu(*, heading: str) -> None:
    """Gibt die einheitliche Datenquellen-Auswahl aus."""
    print(f"\n{heading}", flush=True)
    for line in _DATA_SOURCE_MENU_LINES:
        print(f"  {line}", flush=True)


def _parse_data_source_answer(answer: str, *, default: str = "fulcrum") -> str | None:
    if not answer:
        return default
    return _DATA_SOURCE_ALIASES.get(answer)


def prompt_data_source(
    *,
    heading: str = "Datenquelle nicht eindeutig — bitte wählen:",
    prompt: str = "Auswahl [1/2] (Default: 2): ",
    strict: bool = True,
) -> str | None:
    """
    Fragt die Blockchain-Datenquelle ab.
    Rückgabe: ``bip158`` oder ``fulcrum``; bei strict=False und
    ungültiger Eingabe ``None``.
    """
    print_data_source_menu(heading=heading)
    print(prompt, end="", flush=True)
    try:
        answer = input().strip().lower()
    except EOFError:
        if strict:
            raise SystemExit(
                "Keine interaktive Eingabe möglich — "
                "nutze --bip158 oder --rpc-only."
            )
        return None

    choice = _parse_data_source_answer(answer)
    if choice is not None:
        return choice
    if strict:
        raise SystemExit(f"Ungültige Auswahl: {answer!r} (erwartet 1 oder 2)")
    return None


def prompt_rescan_mode() -> str | None:
    """Fragt Light-, Full-Rescan oder Abbruch ab. Rückgabe: light/full/None."""
    print(
        "Cache aktualisieren? "
        "[L]ight (nächste Adressen) / [F]ull (komplett ab #0) / [n]ein: ",
        end="",
        flush=True,
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        return None
    if answer in ("", "l", "light"):
        return "light"
    if answer in ("f", "full", "v", "voll"):
        return "full"
    return None



def prompt_top_utxo_selection(
    shown_count: int,
    total_count: int,
    default_more: int = 10,
    *,
    f_hint: str | None = None,
) -> tuple[str, int | None]:
    """
    Liest Benutzereingabe für die UTXO-Rangliste.
    Rückgabe: ("select", index) | ("more", n) | ("trace_all", bool) | ("quit", None)
    """
    while True:
        more_hint = ""
        if shown_count < total_count:
            more_hint = (
                f", '+' für {default_more} weitere oder '+N' "
                f"({shown_count}/{total_count} sichtbar)"
            )
        fullscan_hint = f", {f_hint}" if f_hint else ""
        print(
            f"Nummer der zu analysierenden UTXO{more_hint}{fullscan_hint} "
            f"oder 'Q' für Quit: ",
            end="",
            flush=True,
        )
        try:
            answer = input().strip()
        except EOFError:
            return ("quit", None)

        if answer.lower() == "q":
            return ("quit", None)

        if f_hint and answer == "f":
            return ("trace_all", False)
        if f_hint and answer == "F":
            return ("trace_all", True)

        if answer == "+" or (answer.startswith("+") and len(answer) > 1):
            if shown_count >= total_count:
                print("Alle UTXOs der Rangliste sind bereits sichtbar.")
                continue
            if answer == "+":
                return ("more", default_more)
            try:
                more_n = int(answer[1:])
            except ValueError:
                print(
                    f"Ungültige Eingabe: {answer!r} "
                    f"(Nummer 1–{shown_count}, '+', '+N'{fullscan_hint} oder Q)",
                )
                continue
            if more_n < 1:
                print("Anzahl nach '+' muss >= 1 sein.")
                continue
            return ("more", more_n)

        try:
            number = int(answer)
        except ValueError:
            print(
                f"Ungültige Eingabe: {answer!r} "
                f"(Nummer 1–{shown_count}, '+', '+N'{fullscan_hint} oder Q)",
            )
            continue

        if 1 <= number <= shown_count:
            return ("select", number - 1)

        print(f"Nummer außerhalb der Rangliste (1–{shown_count}).")


def _assess_tx_oriented_followup(
    predecessor_txids: set[str],
    found_inputs: list,
    found_outputs: list,
    total_external_sats: int,
) -> tuple[bool, list[str]]:
    """Heuristik: lohnt sich transaktionsorientierte Folge-Analyse?"""
    reasons: list[str] = []
    pred_count = len(predecessor_txids)
    if pred_count == 0:
        return False, []

    if pred_count > 1:
        reasons.append(f"{pred_count} Vorgänger-Txs")

    if len(found_inputs) > 1:
        reasons.append(f"{len(found_inputs)} Wallet-Inputs")
    if total_external_sats > 0:
        reasons.append("externe Ausgänge")
    if len(found_outputs) > 2:
        reasons.append(f"{len(found_outputs)} Wallet-Outputs")

    input_addrs = {item["address"] for item in found_inputs}
    if len(input_addrs) > 1 and pred_count > 1:
        reasons.append("mehrere Wallets in der Kette")

    looks_worthwhile = (
        pred_count > 2
        or len(found_inputs) > 1
        or total_external_sats > 0
        or len(found_outputs) > 2
        or (pred_count > 1 and len(input_addrs) > 1)
    )

    if not looks_worthwhile:
        reasons = ["einfache Kette mit einem Vorgänger"]

    return looks_worthwhile, reasons


def _assess_utxo_oriented_followup(
    predecessor_txids: set[str],
    utxo_count: int,
) -> tuple[bool, list[str]]:
    """Heuristik für Folge-Analyse nach UTXO-Herkunftstracing."""
    reasons: list[str] = []
    pred_count = len(predecessor_txids)
    if pred_count == 0:
        return False, []

    if utxo_count > 1:
        reasons.append(f"{utxo_count} UTXOs mit unterschiedlicher Herkunft")
    if pred_count > 1:
        reasons.append(f"{pred_count} Vorgänger-Txs")
    if pred_count > 2:
        reasons.append("verzweigte Vorgänger-Kette")

    looks_worthwhile = utxo_count > 1 or pred_count > 1 or pred_count > 2
    if not looks_worthwhile:
        reasons = ["einfache Kette mit einem Vorgänger"]

    return looks_worthwhile, reasons


def _prompt_tx_oriented_followup(
    looks_worthwhile: bool,
    predecessor_count: int,
    reasons: list[str] | None = None,
) -> bool:
    """Fragt nach transaktionsorientierter Folge-Analyse (Default: Nein)."""
    if predecessor_count == 0:
        return False

    if looks_worthwhile:
        hint = "Es sieht verzweigt aus und könnte den Zusatzaufwand lohnen"
    else:
        hint = "Es sieht nicht sinnvoll aus"

    reason_text = ""
    if reasons:
        reason_text = f" ({'; '.join(reasons)})"

    print(
        f"\nSoll ich auch Transaktionsorientiert analysieren? {hint}{reason_text}. "
        f"[j/N]: ",
        end="",
        flush=True,
    )
    return prompt_yes_no(default_yes=False)



def run_analyze_tx(
    get_tx,
    txid: str,
    own_addresses: set,
    analyzed_txs: set | None = None,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
) -> None:
    """Tx-Analyse mit optionaler transaktionsorientierter Folge-Analyse."""
    ctx = analyze_tx(
        get_tx,
        txid,
        own_addresses,
        analyzed_txs=analyzed_txs,
        depth=0,
        trace_funding=True,
        wallet=wallet,
        cache_dir=cache_dir,
        fetch_address_utxos=fetch_address_utxos,
        cache_source=cache_source,
        allow_tx_followup=False,
    )
    if not isinstance(ctx, TxFollowupContext):
        return
    looks_worthwhile, reasons = _assess_tx_oriented_followup(
        ctx.predecessors,
        ctx.found_inputs,
        ctx.found_outputs,
        ctx.total_external_sats,
    )
    if not _prompt_tx_oriented_followup(
        looks_worthwhile, len(ctx.predecessors), reasons
    ):
        return
    _run_tx_oriented_followups(
        get_tx,
        ctx.predecessors,
        ctx.txid,
        own_addresses,
        ctx.analyzed_txs,
        ctx.depth,
        wallet,
        cache_dir,
        fetch_address_utxos,
        cache_source,
    )


def run_analyze_address_utxos(
    get_tx,
    fetch_utxos,
    address: str,
    own_addresses: set,
    utxo_ref: str | None = None,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
) -> None:
    """UTXO-Herkunftsanalyse mit optionaler Folge-Analyse."""
    ctx = analyze_address_utxos(
        get_tx,
        fetch_utxos,
        address,
        own_addresses,
        utxo_ref=utxo_ref,
        wallet=wallet,
        cache_dir=cache_dir,
        fetch_address_utxos=fetch_address_utxos,
        cache_source=cache_source,
    )
    if not isinstance(ctx, UtxoFollowupContext):
        return
    looks_worthwhile, reasons = _assess_utxo_oriented_followup(
        ctx.predecessors, ctx.utxo_count
    )
    if not _prompt_tx_oriented_followup(
        looks_worthwhile, len(ctx.predecessors), reasons
    ):
        return
    _run_tx_oriented_followups(
        get_tx,
        ctx.predecessors,
        "",
        own_addresses,
        ctx.analyzed_txs,
        0,
        wallet,
        cache_dir,
        fetch_address_utxos,
        cache_source,
    )


def interactive_analyze_top_utxos(
    get_tx,
    fetch_utxos,
    all_utxos: list[dict],
    own_addresses: set,
    shown_count: int,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    page_size: int = 10,
    output_dir: Path | None = None,
    fulcrum=None,
    immutable_cache_dir: Path | None = None,
    f_hint: str | None = None,
) -> None:
    """Ermöglicht die Detail-Analyse einzelner UTXOs aus der Top-Liste."""
    from analyze import trace_known_utxos
    from display import cancellable_output
    from main import print_utxo_rank_entries

    shown = min(shown_count, len(all_utxos))
    total = len(all_utxos)

    while True:
        action, value = prompt_top_utxo_selection(
            shown,
            total,
            default_more=page_size,
            f_hint=f_hint,
        )
        if action == "quit":
            return

        if action == "trace_all":
            tx_oriented = bool(value)
            if not all_utxos:
                print("Keine UTXOs in der Rangliste zum Tracen.\n")
                continue
            mode = (
                "UTXO- + Transaktions-Trace"
                if tx_oriented
                else "UTXO-Trace"
            )
            print(
                f"\nStarte {mode} für {len(all_utxos)} UTXO(s) "
                f"(ohne erneuten Scan)…\n",
                flush=True,
            )
            with cancellable_output(hint="UTXO-Trace — q zum Abbrechen"):
                trace_known_utxos(
                    get_tx,
                    all_utxos,
                    own_addresses,
                    wallet=wallet,
                    cache_dir=cache_dir,
                    fetch_address_utxos=fetch_address_utxos,
                    cache_source=cache_source,
                    tx_oriented_followup=tx_oriented,
                )
            print()
            continue

        if action == "more":
            old_shown = shown
            shown = min(shown + value, total)
            if shown <= old_shown:
                print("Alle UTXOs der Rangliste sind bereits sichtbar.\n")
                continue
            print(f"\n{'─'*85}")
            print(f"Weitere UTXOs ({old_shown + 1}–{shown} von {total}):")
            print()
            print_utxo_rank_entries(all_utxos, old_shown, shown, wallet, immutable_cache_dir)
            if shown < total:
                print(f"... und {total - shown} weitere UTXO(s) in der Rangliste")
            print(f"{'='*85}\n")
            continue

        utxo = all_utxos[value]
        address = utxo.get("address")
        if not address or address == "?":
            print("Keine Adresse für dieses UTXO bekannt — Analyse nicht möglich.\n")
            continue

        run_analyze_address_utxos(
            get_tx,
            fetch_utxos,
            address,
            own_addresses,
            utxo_ref=f"{utxo['txid']}:{utxo['vout']}",
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
        )
        print()
