"""Tx/UTXO-Herkunftsanalyse und Trace (ohne interaktive Prompts)."""
from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

from display import (
    abbrev_display,
    cancellable_output,
    format_sats,
    format_utxo_display,
    format_utxo_ref,
    is_list_abort_requested,
)

from trace_engine import (
    CoinbaseFunding,
    FundingEdge,
    iter_funding_inputs,
    resolve_vin_prevout,
    utxo_ref,
)

from core.utxo_origin import (
    MAX_TRACE_DEPTH,
    _EphemeralProgress,
    _hat_tax_horizon,
    _is_own_address,
    _is_own_output,
    _knoten_txid_vout,
    _match_own_address,
    _origin_hat_luecken,
    _parse_utxo_ref,
    _quelle_hat_luecke,
    _resolve_input_output,
    _seed_memo_fertige_unterbaeume,
    hat_brauchbaren_teilfortschritt,
    trace_utxo_origin,
    vertiefe_herkunft_luecken,
    vertiefe_tax_horizon,
)

from core.utxo_ingress_report import (
    TxFollowupContext,
    UtxoFollowupContext,
    _analyze_utxo_funding,
    _collect_external_ingress_events,
    _collect_internal_creator_txs,
    _collect_tax_horizon_events,
    _collect_wallet_ingress_events,
    _external_ingress_extrema,
    _find_wallet_entries,
    _format_amount_display,
    _format_utxo_count,
    _group_external_sources,
    _oldest_external_ingress,
    _print_external_groups,
    _print_funding_trace,
    _print_wallet_entries,
    _print_youngest_sats_summary,
    _run_tx_oriented_followups,
    _sum_external_sats,
    _sum_internal_sats,
    _youngest_external_ingress,
    _youngest_tax_horizon,
    _youngest_wallet_ingress,
    persist_utxo_ingress,
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


class SanctionHitFound(Exception):
    """Sanktionierte Adresse gefunden — Prüfung wird abgebrochen."""

    def __init__(self, hit: dict) -> None:
        self.hit = hit
        super().__init__(hit.get("address", ""))


def _sanction_progress_status(hits: list[dict]) -> str:
    if hits:
        return f"⚠️  Treffer: {abbrev_display(hits[-1]['address'])}"
    return "noch keine sanktionierte Adresse gefunden"


def _sanction_coinjoin_eintrag(
    tx: dict | None,
    *,
    hop: int,
    txid: str,
    wallet_utxo_ref: str = "",
    kind: str | None = None,
) -> dict | None:
    """
    Form-Heuristik (xpub-blind) → CoinJoin-Hinweis für den Sanktions-Report.

    *hop*: Entfernung der Tx-Ausgabe zum geprüften Wallet-UTXO (0 = UTXO-Tx).
    """
    from core.tx_classify import COINJOIN_KINDS, form_coinjoin_kind_from_tx, soft_label

    kind_eff = (kind or "").strip() or None
    if kind_eff is None and isinstance(tx, dict):
        kind_eff = form_coinjoin_kind_from_tx(tx)
    if not kind_eff or kind_eff not in COINJOIN_KINDS:
        return None
    time_ts = None
    time_label = ""
    if isinstance(tx, dict):
        try:
            time_ts = _main()._tx_block_time(tx)
        except Exception:
            time_ts = None
        try:
            time_label = str(_main()._format_tx_time(tx) or "")
        except Exception:
            time_label = ""
    if time_ts is not None:
        try:
            time_ts = int(time_ts)
        except (TypeError, ValueError):
            time_ts = None
    return {
        "hop": int(hop),
        "txid": str(txid or "").strip(),
        "kind": kind_eff,
        "label": soft_label(kind_eff, lang="de"),
        "label_en": soft_label(kind_eff, lang="en"),
        "time_ts": time_ts,
        "time": time_label,
        "wallet_utxo": wallet_utxo_ref,
    }


def _coinjoins_zusammenfuehren(eintraege: list[dict]) -> list[dict]:
    """Gleiche Tx einmal; kleinster Hop, Wallet-UTXOs vereinigt."""
    by_txid: dict[str, dict] = {}
    for raw in eintraege or []:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("txid") or "").strip().lower()
        if not tid:
            continue
        hop = int(raw.get("hop") or 0)
        kind = str(raw.get("kind") or "").strip()
        entry = by_txid.get(tid)
        if entry is None:
            wrefs = set()
            w = str(raw.get("wallet_utxo") or "").strip()
            if w:
                wrefs.add(w)
            for extra in raw.get("wallet_utxos") or []:
                e = str(extra or "").strip()
                if e:
                    wrefs.add(e)
            by_txid[tid] = {
                "hop": hop,
                "txid": tid,
                "kind": kind,
                "label": str(raw.get("label") or ""),
                "label_en": str(raw.get("label_en") or ""),
                "time_ts": raw.get("time_ts"),
                "time": str(raw.get("time") or ""),
                "wallet_utxos": wrefs,
            }
            continue
        if hop < int(entry["hop"]):
            entry["hop"] = hop
        if raw.get("time_ts") and not entry.get("time_ts"):
            entry["time_ts"] = raw.get("time_ts")
            entry["time"] = str(raw.get("time") or "")
        if kind and not entry.get("kind"):
            entry["kind"] = kind
            entry["label"] = str(raw.get("label") or "")
            entry["label_en"] = str(raw.get("label_en") or "")
        w = str(raw.get("wallet_utxo") or "").strip()
        if w:
            entry["wallet_utxos"].add(w)
        for extra in raw.get("wallet_utxos") or []:
            e = str(extra or "").strip()
            if e:
                entry["wallet_utxos"].add(e)
    out: list[dict] = []
    for entry in by_txid.values():
        refs = sorted(entry.pop("wallet_utxos"))
        entry["wallet_utxos"] = refs
        out.append(entry)
    out.sort(
        key=lambda e: (
            int(e.get("hop") or 0),
            int(e.get("time_ts") or 0),
            str(e.get("txid") or ""),
        )
    )
    return out


def scan_external_sanction_hops(
    get_tx,
    creator_txid: str,
    vout_index: int,
    own_addresses: set | None = None,
    sanctioned_addresses: frozenset[str] | None = None,
    *,
    max_hops: int,
    wallet: WalletContext | None = None,
    wallet_utxo_ref: str | None = None,
    visited_utxos: set[str] | None = None,
    depth: int = 1,
    progress: "SanctionCheckProgressLine | None" = None,
    counters: dict[str, int] | None = None,
    hits: list[dict] | None = None,
    abort_on_hit: bool = True,
    gesehene_adressen: set[str] | None = None,
) -> list[dict]:
    """
    Verfolgt die Finanzierung eines UTXO **xpub-blind** bis *max_hops* rückwärts
    und meldet Treffer auf der Sanktionsliste.

    Perspektive eines Dritten **ohne** XPUB-Wissen: Jeder Prevout-Hop zählt,
    eigene Wallet-Adressen werden nicht übersprungen. Grünes Licht = keine
    gelistete Adresse in diesem Fenster. (``own_addresses`` / ``wallet``
    bleiben API-kompatibel, steuern den Walk aber nicht mehr.)

    *gesehene_adressen* sammelt, wenn übergeben, jede geprüfte Adresse.
    Anders als ``counters["addrs_checked"]`` zählt das Set jede Adresse
    einmal — „was wurde geprüft“, nicht „wie viele Vergleiche liefen“.
    """
    del own_addresses, wallet  # xpub-blind: keine Eigentumsfilter
    if sanctioned_addresses is None:
        sanctioned_addresses = frozenset()
    if counters is None:
        counters = {"addrs_checked": 0}
    if hits is None:
        hits = []

    if depth > max_hops or not sanctioned_addresses:
        return hits

    if visited_utxos is None:
        visited_utxos = set()

    utxo_key = utxo_ref(creator_txid, vout_index)
    if utxo_key in visited_utxos:
        return hits
    visited_utxos.add(utxo_key)

    ref = wallet_utxo_ref or utxo_key
    if progress:
        progress.update(
            wallet_utxo=ref,
            hop=min(depth, max_hops),
            max_hops=max_hops,
            addrs_checked=counters["addrs_checked"],
            status=_sanction_progress_status(hits),
        )

    try:
        tx = get_tx(creator_txid)
    except Exception:
        return hits

    if vout_index >= len(tx.get("vout", [])):
        return hits

    try:
        for inp in iter_funding_inputs(get_tx, creator_txid):
            if isinstance(inp, CoinbaseFunding):
                continue
            edge: FundingEdge = inp
            prev_ref = edge.prevout.key
            for addr in edge.addresses:
                if not addr:
                    continue
                counters["addrs_checked"] += 1
                if gesehene_adressen is not None:
                    gesehene_adressen.add(addr)
                if progress:
                    progress.update(
                        wallet_utxo=ref,
                        hop=depth,
                        max_hops=max_hops,
                        addrs_checked=counters["addrs_checked"],
                        status=_sanction_progress_status(hits),
                    )
                if addr in sanctioned_addresses:
                    hit = {
                        "hop": depth,
                        "address": addr,
                        "from_utxo": prev_ref,
                        "in_tx": creator_txid,
                        "amount_sats": edge.amount_sats,
                        "wallet_utxo": ref,
                    }
                    hits.append(hit)
                    if progress:
                        progress.update(
                            wallet_utxo=ref,
                            hop=depth,
                            max_hops=max_hops,
                            addrs_checked=counters["addrs_checked"],
                            status=_sanction_progress_status(hits),
                        )
                    if abort_on_hit:
                        raise SanctionHitFound(hit)

            # Jeder Prevout weiter — auch „eigene“ Adressen (xpub-blind).
            scan_external_sanction_hops(
                get_tx,
                edge.prevout.txid,
                edge.prevout.vout,
                None,
                sanctioned_addresses,
                max_hops=max_hops,
                wallet=None,
                wallet_utxo_ref=ref,
                visited_utxos=visited_utxos,
                depth=depth + 1,
                progress=progress,
                counters=counters,
                hits=hits,
                abort_on_hit=abort_on_hit,
                gesehene_adressen=gesehene_adressen,
            )
    except SanctionHitFound:
        raise

    return hits


class _FortschrittsAdapter:
    """
    Übersetzt die ``update(**felder)``-Aufrufe aus
    ``scan_external_sanction_hops`` in ein ``progress_cb(felder)``.

    Damit meldet auch der Nicht-CLI-Aufrufer die tatsächliche Hop-Tiefe und
    Adresszahl, statt nur einmal pro UTXO ``hop=0``. Der Lock hält die
    Meldungen im Parallel-Lauf auseinander — sonst mischen sich die Zeilen
    zweier Worker zu einer, die keinen Zustand mehr beschreibt.
    """

    def __init__(self, callback, lock):
        self._callback = callback
        self._lock = lock

    def update(self, **felder):
        with self._lock:
            self._callback(felder)


def _event_gegen_liste(
    event: dict,
    sanctioned_addresses: frozenset[str],
    *,
    wallet_utxo_ref: str,
) -> dict | None:
    """Ein Hop-Event gegen die aktuelle Liste — None wenn kein Treffer."""
    addr = str(event.get("address") or "").strip()
    if not addr or addr not in sanctioned_addresses:
        return None
    return {
        "hop": int(event.get("hop") or 0),
        "address": addr,
        "from_utxo": str(event.get("from_utxo") or ""),
        "in_tx": str(event.get("in_tx") or ""),
        "amount_sats": int(event.get("amount_sats") or 0),
        "wallet_utxo": wallet_utxo_ref,
    }


def _events_aus_origin_tree(
    node: dict | None,
    *,
    max_hops: int,
    wallet_utxo_ref: str,
    depth: int = 0,
    events: list | None = None,
    frontiers: list | None = None,
    coinjoins: list | None = None,
) -> tuple[list, list, list]:
    """
    Liest Adress-Hops aus dem Herkunfts-Rohbaum (xpub-blind nutzbar).

    *frontiers*: (txid, vout, next_depth) wo der Baum endet, aber noch
    Hops bis *max_hops* fehlen (typisch externes Blatt).
    *coinjoins*: Soft-Labels aus dem Herkunftsbaum (``tx_class``).
    """
    from core.tx_classify import COINJOIN_KINDS

    if events is None:
        events = []
    if frontiers is None:
        frontiers = []
    if coinjoins is None:
        coinjoins = []
    if not isinstance(node, dict) or depth > max_hops:
        return events, frontiers, coinjoins

    txid = str(node.get("txid") or "").strip()
    try:
        vout = int(node.get("vout", 0))
    except (TypeError, ValueError):
        vout = 0
    utxo_k = f"{txid}:{vout}" if txid else ""
    amount = int(node.get("amount_sats") or 0)

    kind = str(node.get("tx_class") or "").strip()
    if kind in COINJOIN_KINDS and txid:
        cj = _sanction_coinjoin_eintrag(
            None,
            hop=depth,
            txid=txid,
            wallet_utxo_ref=wallet_utxo_ref,
            kind=kind,
        )
        if cj is not None:
            # Zeit aus dem Herkunftsknoten, falls Form-Label ohne get_tx.
            if node.get("time_ts") is not None and not cj.get("time_ts"):
                try:
                    cj["time_ts"] = int(node["time_ts"])
                except (TypeError, ValueError):
                    pass
            if node.get("time") and not cj.get("time"):
                cj["time"] = str(node.get("time") or "")
            if node.get("tx_class_label"):
                cj["label"] = str(node["tx_class_label"])
            if node.get("tx_class_label_en"):
                cj["label_en"] = str(node["tx_class_label_en"])
            coinjoins.append(cj)

    for addr in node.get("addresses") or []:
        if not addr:
            continue
        events.append({
            "hop": depth,
            "address": addr,
            "from_utxo": utxo_k or wallet_utxo_ref,
            "in_tx": txid,
            "amount_sats": amount,
        })

    if node.get("tax_horizon"):
        # Teilbaum: tiefer nur per get_tx
        if depth < max_hops and txid:
            frontiers.append((txid, vout, depth + 1))
        return events, frontiers, coinjoins

    quellen = node.get("sources") or []
    if not quellen:
        if depth < max_hops and txid and depth > 0:
            # Unvollständiger Knoten — Finanzierung unbekannt
            frontiers.append((txid, vout, depth + 1))
        return events, frontiers, coinjoins

    for src in quellen:
        if not isinstance(src, dict):
            continue
        typ = src.get("type")
        hop = depth + 1
        if hop > max_hops:
            continue
        if typ == "coinbase":
            continue
        if typ == "external_unresolved":
            continue
        addr = str(src.get("address") or "").strip()
        from_utxo = str(src.get("from_utxo") or "")
        amt = int(src.get("amount_sats") or 0)
        if addr:
            events.append({
                "hop": hop,
                "address": addr,
                "from_utxo": from_utxo,
                "in_tx": txid,
                "amount_sats": amt,
            })
        if typ == "internal" and isinstance(src.get("trace"), dict):
            _events_aus_origin_tree(
                src["trace"],
                max_hops=max_hops,
                wallet_utxo_ref=wallet_utxo_ref,
                depth=hop,
                events=events,
                frontiers=frontiers,
                coinjoins=coinjoins,
            )
        elif typ == "external" and hop < max_hops and ":" in from_utxo:
            # Externes Blatt: tiefer nur per Chain-Walk
            try:
                pt, _, pv = from_utxo.rpartition(":")
                frontiers.append((pt, int(pv), hop + 1))
            except ValueError:
                pass
        elif typ == "external" and hop < max_hops and src.get("txid") is not None:
            try:
                frontiers.append(
                    (str(src["txid"]), int(src.get("vout", 0)), hop + 1)
                )
            except (TypeError, ValueError):
                pass
    return events, frontiers, coinjoins


def _sammle_sanction_events_live(
    get_tx,
    txid: str,
    vout_index: int,
    utxo: dict,
    *,
    max_hops: int,
    wallet_utxo_ref: str,
    start_depth: int = 1,
    visited: set | None = None,
    cancel_cb=None,
) -> tuple[list[dict], list[dict]]:
    """
    xpub-blinder Hop-Walk → Event- und CoinJoin-Liste
    (get_tx füllt den Tx-Immutable-Cache).

    *start_depth*: 1 = Inputs der UTXO-Tx; >1 = Fortsetzung an einem Frontier.
    CoinJoin-Hop = Hop der Tx-Ausgabe Richtung Wallet-UTXO (0 = UTXO-Tx).
    *cancel_cb*: bei True Abbruch (Cancelled) — auch mitten im Hop-Walk.
    """
    from core.jobs import Cancelled

    events: list[dict] = []
    coinjoins: list[dict] = []
    if visited is None:
        visited = set()

    def _abbruch() -> None:
        if cancel_cb and cancel_cb():
            raise Cancelled()

    if start_depth <= 1:
        _abbruch()
        hop0: list[str] = []
        raw = str(utxo.get("address") or "").strip()
        if raw:
            hop0.append(raw)
        amount0 = int(utxo.get("value") or utxo.get("value_sats") or 0)
        tx0 = None
        try:
            tx0 = get_tx(txid)
            outs = tx0.get("vout") or []
            if 0 <= vout_index < len(outs):
                for a in _main()._extract_addresses(outs[vout_index]):
                    if a and a not in hop0:
                        hop0.append(a)
                try:
                    amount0 = int(_main()._extract_value_sats(outs[vout_index]))
                except Exception:
                    pass
        except Cancelled:
            raise
        except Exception:
            tx0 = None
        for a in hop0:
            events.append({
                "hop": 0,
                "address": a,
                "from_utxo": wallet_utxo_ref,
                "in_tx": txid,
                "amount_sats": amount0,
            })
        if tx0 is not None:
            cj0 = _sanction_coinjoin_eintrag(
                tx0, hop=0, txid=txid, wallet_utxo_ref=wallet_utxo_ref,
            )
            if cj0 is not None:
                coinjoins.append(cj0)

    def _walk(creator_txid: str, depth: int) -> None:
        _abbruch()
        if depth > max_hops:
            return
        key = f"{creator_txid}:walk"
        # creator-weit: Inputs einer Tx nur einmal (vout irrelevant für vin)
        if key in visited:
            return
        visited.add(key)
        try:
            # Tx laden (auch für CJ-Form); iter_funding_inputs lädt ggf. nochmal
            # aus Cache.
            try:
                _abbruch()
                tx = get_tx(creator_txid)
            except Cancelled:
                raise
            except Exception:
                tx = None
            # Hop der Ausgabe dieser Tx Richtung Wallet = depth-1 (depth≥1).
            # UTXO-Tx (start_depth≤1, depth=1, dieselbe txid) schon bei Hop 0.
            schon_hop0 = (
                start_depth <= 1 and depth == 1 and creator_txid == txid
            )
            if tx is not None and not schon_hop0:
                cj = _sanction_coinjoin_eintrag(
                    tx,
                    hop=max(0, int(depth) - 1),
                    txid=creator_txid,
                    wallet_utxo_ref=wallet_utxo_ref,
                )
                if cj is not None:
                    coinjoins.append(cj)

            for inp in iter_funding_inputs(get_tx, creator_txid):
                _abbruch()
                if isinstance(inp, CoinbaseFunding):
                    continue
                edge: FundingEdge = inp
                prev_ref = edge.prevout.key
                for addr in edge.addresses:
                    if not addr:
                        continue
                    events.append({
                        "hop": depth,
                        "address": addr,
                        "from_utxo": prev_ref,
                        "in_tx": creator_txid,
                        "amount_sats": edge.amount_sats,
                    })
                if depth < max_hops:
                    _walk(edge.prevout.txid, depth + 1)
        except Cancelled:
            raise
        except Exception:
            return

    _walk(txid, max(1, int(start_depth)))
    return events, coinjoins


def _pruefe_ein_utxo(
    get_tx,
    utxo: dict,
    own_addresses: set | None,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    abort_on_hit: bool,
    progress,
    immutable_cache_dir: Path | None = None,
    cancel_cb=None,
) -> tuple[str, list[dict], set[str], list[dict]] | None:
    """
    Ein UTXO prüfen. Rückgabe: (ref, treffer, gesehene Adressen, coinjoins)
    oder None.

    Cache-Reihenfolge:
    1. ``sanction_walk`` (Graph) → aktuelle Liste matchen
    2. Herkunfts-``origin_tree`` + ggf. Live-Lücken (get_tx / Tx-Cache)
    3. Live-Walk ab Root; Ergebnis als sanction_walk speichern

    Hop 0 = UTXO-Adresse; danach xpub-blind bis *max_hops*.
    CoinJoins: Form-Heuristik je Tx im Fenster (Soft-Label).
    """
    del own_addresses, wallet
    from core import trace_cache
    from core.jobs import Cancelled

    txid = str(utxo.get("txid", "")).strip()
    vout = utxo.get("vout")
    if not txid or vout is None:
        return None
    try:
        vout_index = int(vout)
    except (TypeError, ValueError):
        return None

    ref = f"{txid}:{vout_index}"
    treffer: list[dict] = []
    gesehen: set[str] = set()
    coinjoins: list[dict] = []
    counters = {"addrs_checked": 0}

    def _abbruch() -> None:
        if cancel_cb and cancel_cb():
            raise Cancelled()

    # UI nicht bei jedem Address-Match fluten (große Origin-Bäume).
    _last_prog = {"hop": -1, "n": 0, "t": 0.0}

    def _fortschritt(hop: int, *, force: bool = False) -> None:
        if progress is None:
            return
        import time as _time

        n = counters["addrs_checked"]
        jetzt = _time.monotonic()
        hop_i = min(int(hop), max_hops)
        if not force and hop_i == _last_prog["hop"] and n - _last_prog["n"] < 25:
            if jetzt - _last_prog["t"] < 0.4:
                return
        _last_prog["hop"] = hop_i
        _last_prog["n"] = n
        _last_prog["t"] = jetzt
        progress.update(
            wallet_utxo=ref,
            hop=hop_i,
            max_hops=max_hops,
            addrs_checked=n,
            status=_sanction_progress_status(treffer),
        )

    gematcht: set[tuple] = set()

    def _match_events(events: list) -> None:
        for ev in events:
            _abbruch()
            hop = int(ev.get("hop") or 0)
            if hop > max_hops:
                continue
            addr = str(ev.get("address") or "").strip()
            if not addr:
                continue
            schluessel = (
                hop,
                addr,
                str(ev.get("from_utxo") or ""),
                str(ev.get("in_tx") or ""),
            )
            if schluessel in gematcht:
                continue
            gematcht.add(schluessel)
            counters["addrs_checked"] += 1
            gesehen.add(addr)
            _fortschritt(hop)
            hit = _event_gegen_liste(
                ev, sanctioned_addresses, wallet_utxo_ref=ref,
            )
            if hit:
                treffer.append(hit)
                _fortschritt(hop, force=True)
                if abort_on_hit:
                    raise SanctionHitFound(hit)

    _abbruch()
    # Sofort Hop 0 aus dem UTXO melden — sonst bleibt die UI bei
    # „0 Adressen“ stehen, während Frontiers noch get_tx machen.
    hop0_addr = str(utxo.get("address") or "").strip()
    if hop0_addr:
        _match_events([{
            "hop": 0,
            "address": hop0_addr,
            "from_utxo": ref,
            "in_tx": txid,
            "amount_sats": int(utxo.get("value") or utxo.get("value_sats") or 0),
        }])
    elif progress is not None:
        _fortschritt(0)

    # 1) Fertiger Sanktions-Walk
    walk = (
        trace_cache.sanction_walk_laden(txid, vout_index, immutable_cache_dir)
        if immutable_cache_dir
        else None
    )
    if (
        walk
        and walk.get("complete")
        and int(walk.get("max_hops") or 0) >= max_hops
    ):
        _match_events(walk.get("events") or [])
        coinjoins = [
            c for c in (walk.get("coinjoins") or [])
            if int(c.get("hop") or 0) <= max_hops
        ]
        return ref, treffer, gesehen, coinjoins

    # 2+3) origin_tree und/oder Live-Walk → Event-Liste aufbauen
    events: list[dict] = []
    origin = (
        trace_cache.origin_tree_laden(txid, vout_index, immutable_cache_dir)
        if immutable_cache_dir
        else None
    )
    frontiers: list[tuple[str, int, int]] = []
    if origin:
        events, frontiers, coinjoins = _events_aus_origin_tree(
            origin,
            max_hops=max_hops,
            wallet_utxo_ref=ref,
        )
        # Bekannte Origin-Events sofort matchen — nicht erst nach Live-Lücken.
        _match_events(events)

    live_complete = True
    if not origin or frontiers:
        visited: set = set()
        if not origin:
            events, coinjoins = _sammle_sanction_events_live(
                get_tx,
                txid,
                vout_index,
                utxo,
                max_hops=max_hops,
                wallet_utxo_ref=ref,
                start_depth=1,
                visited=visited,
                cancel_cb=cancel_cb,
            )
            _match_events(events)
        else:
            # Lücken hinter externen Blättern nachziehen — je Frontier
            # matchen, damit Fortschritt/Abbruch nicht bis zum Schluss warten.
            for i, (f_txid, f_vout, f_depth) in enumerate(frontiers):
                _abbruch()
                if f_depth > max_hops:
                    continue
                if progress is not None:
                    progress.update(
                        wallet_utxo=ref,
                        hop=min(f_depth, max_hops),
                        max_hops=max_hops,
                        addrs_checked=counters["addrs_checked"],
                        status=(
                            f"{_sanction_progress_status(treffer)}"
                            f" · Lücke {i + 1}/{len(frontiers)}"
                        ),
                    )
                try:
                    extra, extra_cj = _sammle_sanction_events_live(
                        get_tx,
                        f_txid,
                        f_vout,
                        {"address": "", "value": 0},
                        max_hops=max_hops,
                        wallet_utxo_ref=ref,
                        start_depth=f_depth,
                        visited=visited,
                        cancel_cb=cancel_cb,
                    )
                except Exception as exc:
                    from core.jobs import ist_abbruch

                    if ist_abbruch(exc):
                        live_complete = False
                        raise
                    # Einzelne Frontier-Tx nicht erreichbar: weiter, Walk unvollständig.
                    live_complete = False
                    continue
                events.extend(extra)
                coinjoins.extend(extra_cj)
                _match_events(extra)

    coinjoins = _coinjoins_zusammenfuehren(coinjoins)

    if immutable_cache_dir and events:
        # Dedup Events (gleiche hop/address/from_utxo)
        gesehen_k: set[tuple] = set()
        unique: list[dict] = []
        for ev in events:
            k = (
                int(ev.get("hop") or 0),
                str(ev.get("address") or ""),
                str(ev.get("from_utxo") or ""),
                str(ev.get("in_tx") or ""),
            )
            if k in gesehen_k:
                continue
            gesehen_k.add(k)
            unique.append(ev)
        # Nur als complete speichern, wenn alle Frontiers gezogen wurden.
        trace_cache.sanction_walk_speichern(
            txid,
            vout_index,
            max_hops=max_hops,
            complete=live_complete and (not frontiers or origin is not None),
            events=unique,
            coinjoins=coinjoins,
            immutable_cache_dir=immutable_cache_dir,
        )

    return ref, treffer, gesehen, coinjoins


def _check_wallet_utxos_parallel(
    get_tx_je_worker,
    utxos: list[dict],
    own_addresses: set | None,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    worker_count: int,
    progress_cb,
    cancel_cb,
    gesehene_adressen: set[str] | None,
    immutable_cache_dir: Path | None = None,
) -> tuple[list[dict], int, dict | None]:
    """
    Verteilt die UTXOs auf mehrere Verbindungen — je Worker eine eigene.

    Ein Fulcrum-Client ist eine einzelne Socket-Verbindung und verträgt
    keine parallelen Anfragen; deshalb bekommt jeder Worker seinen eigenen
    (``pool.client_at``). Abbruch bei Treffer gibt es hier nicht: Der
    Web-Lauf will die vollständige Liste, und ein früher Ausstieg wäre bei
    laufenden Threads ohnehin nur ungefähr.
    """
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor

    arbeit: queue.Queue = queue.Queue()
    for utxo in utxos:
        arbeit.put(utxo)

    sperre = threading.Lock()
    melde_sperre = threading.Lock()
    alle_treffer: list[dict] = []
    alle_coinjoins: list[dict] = []
    geprueft = 0
    fortschritt = (
        _FortschrittsAdapter(progress_cb, melde_sperre)
        if progress_cb is not None else None
    )

    def abbruch_gewuenscht() -> bool:
        return bool(cancel_cb and cancel_cb())

    def worker(worker_id: int) -> None:
        nonlocal geprueft
        from core.jobs import Cancelled

        roh_get_tx = get_tx_je_worker(worker_id)

        def get_tx(txid: str):
            if abbruch_gewuenscht():
                raise Cancelled()
            return roh_get_tx(txid)

        while not abbruch_gewuenscht():
            try:
                utxo = arbeit.get_nowait()
            except queue.Empty:
                return
            try:
                ergebnis = _pruefe_ein_utxo(
                    get_tx, utxo, own_addresses, sanctioned_addresses,
                    max_hops=max_hops, wallet=wallet, abort_on_hit=False,
                    progress=fortschritt,
                    immutable_cache_dir=immutable_cache_dir,
                    cancel_cb=abbruch_gewuenscht,
                )
            except Cancelled:
                # Restliche Queue leeren — andere Worker sollen auch enden.
                while True:
                    try:
                        arbeit.get_nowait()
                    except queue.Empty:
                        break
                return
            if ergebnis is None:
                continue
            _ref, treffer, gesehen, cjs = ergebnis
            with sperre:
                geprueft += 1
                alle_treffer.extend(treffer)
                alle_coinjoins.extend(cjs)
                if gesehene_adressen is not None:
                    gesehene_adressen.update(gesehen)

    arbeiter = min(worker_count, len(utxos))
    with ThreadPoolExecutor(max_workers=arbeiter) as executor:
        futures = [executor.submit(worker, i) for i in range(arbeiter)]
        for future in futures:
            future.result()

    # Stabile Reihenfolge: Ohne Sortierung hinge sie am Thread-Timing, und
    # zwei Läufe über dieselben Daten lieferten verschiedene Dateien.
    alle_treffer.sort(
        key=lambda t: (t.get("wallet_utxo", ""), t.get("hop", 0),
                       t.get("address", ""))
    )
    return alle_treffer, geprueft, None, _coinjoins_zusammenfuehren(alle_coinjoins)


def check_wallet_utxos_sanctions(
    get_tx,
    utxos: list[dict],
    own_addresses: set | None = None,
    sanctioned_addresses: frozenset[str] | None = None,
    *,
    max_hops: int,
    wallet: WalletContext | None = None,
    abort_on_hit: bool = True,
    progress_cb=None,
    cancel_cb=None,
    gesehene_adressen: set[str] | None = None,
    get_tx_je_worker=None,
    worker_count: int = 1,
    immutable_cache_dir: Path | None = None,
) -> tuple[list[dict], int, dict | None, list[dict]]:
    """
    Prüft Wallet-UTXOs xpub-blind auf sanktionierte Adressen (Drittperspektive).

    Je UTXO: Output-Adresse (Hop 0) plus bis *max_hops* Prevout-Hops rückwärts
    — ohne XPUB-Filter. Grün = keine gelistete Adresse in diesem Fenster.
    Rückgabe: (treffer, geprüfte_utxos, abbruch_treffer|None, coinjoins)

    *coinjoins*: Form-Heuristik (Wasabi/Whirlpool/JoinMarket/…) je Tx im
    Hop-Fenster — Soft-Label „vermutlich …“, keine forensische Sicherheit.

    Cache: ``sanction_walk`` und Herkunfts-``origin_tree`` unter
    *immutable_cache_dir*; Live-``get_tx`` füllt den Tx-Immutable-Cache
    (später Herkunft/Sanktion wiederverwendbar).

    *own_addresses* / *wallet* sind API-kompatibel und werden ignoriert.

    *progress_cb* ist ein Callable[[dict], None] mit Feldern
    (wallet_utxo, hop, max_hops, addrs_checked, status). *cancel_cb* ist ein
    Callable[[], bool] — liefert es True, bricht die Prüfung sauber ab.
    Beides optional; ohne Angabe läuft die CLI-Ausgabe über
    SanctionCheckProgressLine und die Tastatur-Abfrage.

    *gesehene_adressen* wird, wenn übergeben, mit jeder geprüften Adresse
    befüllt — der Aufrufer liest das Set nach dem Lauf aus.

    *get_tx_je_worker* ist ein Callable[[int], get_tx]: Liefert es zusammen
    mit *worker_count* > 1 eine eigene Verbindung je Worker, laufen die
    UTXOs parallel. Ohne das bleibt es beim seriellen Lauf über *get_tx* —
    der Weg, den die CLI mit ihrem Treffer-Abbruch nimmt.
    """
    if sanctioned_addresses is None:
        sanctioned_addresses = frozenset()
    if not utxos or not sanctioned_addresses or max_hops < 1:
        return [], 0, None, []

    if get_tx_je_worker is not None and worker_count > 1 and not abort_on_hit:
        return _check_wallet_utxos_parallel(
            get_tx_je_worker, utxos, own_addresses, sanctioned_addresses,
            max_hops=max_hops, wallet=wallet, worker_count=worker_count,
            progress_cb=progress_cb, cancel_cb=cancel_cb,
            gesehene_adressen=gesehene_adressen,
            immutable_cache_dir=immutable_cache_dir,
        )

    import threading

    from display import SanctionCheckProgressLine

    all_hits: list[dict] = []
    all_coinjoins: list[dict] = []
    checked = 0
    cli_progress = SanctionCheckProgressLine() if progress_cb is None else None
    # Ohne CLI-Zeile meldet der Adapter denselben Zustand an progress_cb —
    # inklusive echter Hop-Tiefe aus scan_external_sanction_hops.
    progress = cli_progress or (
        _FortschrittsAdapter(progress_cb, threading.Lock())
        if progress_cb is not None else None
    )
    abort_hit: dict | None = None

    def abbruch_gewuenscht() -> bool:
        if cancel_cb is not None:
            return cancel_cb()
        return is_list_abort_requested()

    try:
        for utxo in utxos:
            if abbruch_gewuenscht():
                break
            try:
                ergebnis = _pruefe_ein_utxo(
                    get_tx, utxo, own_addresses, sanctioned_addresses,
                    max_hops=max_hops, wallet=wallet,
                    abort_on_hit=abort_on_hit, progress=progress,
                    immutable_cache_dir=immutable_cache_dir,
                    cancel_cb=abbruch_gewuenscht,
                )
            except SanctionHitFound as exc:
                checked += 1
                abort_hit = exc.hit
                break
            except Exception as exc:
                from core.jobs import Cancelled, ist_abbruch

                if ist_abbruch(exc) or isinstance(exc, Cancelled):
                    break
                raise
            if ergebnis is None:
                continue
            _ref, treffer, gesehen, cjs = ergebnis
            checked += 1
            all_hits.extend(treffer)
            all_coinjoins.extend(cjs)
            if gesehene_adressen is not None:
                gesehene_adressen.update(gesehen)
    finally:
        if cli_progress is not None:
            cli_progress.finish()

    return all_hits, checked, abort_hit, _coinjoins_zusammenfuehren(all_coinjoins)


def print_sanction_check_report(
    hits: list[dict],
    *,
    wallet_name: str,
    max_hops: int,
    utxo_count: int,
    sanctioned_count: int,
    aborted: bool = False,
    coinjoins: list[dict] | None = None,
) -> None:
    """Gibt das Ergebnis der Sanktionsprüfung aus."""
    print(f"\n{'═' * 72}")
    print(f"  Sanktionsprüfung: {wallet_name}")
    print(
        f"  {utxo_count} UTXO(s) geprüft, {max_hops} Hop(s) xpub-blind, "
        f"{sanctioned_count:,} Adressen in der Liste"
    )
    if aborted:
        print("  ⚠️  Prüfung nach Treffer abgebrochen")
    print(f"{'═' * 72}")

    if not hits:
        print(
            f"\n  Keine sanktionierte Adresse in den letzten {max_hops} Hop(s)."
        )
    else:
        by_key: dict[tuple, dict] = {}
        for hit in hits:
            key = (hit["hop"], hit["address"], hit["from_utxo"], hit["in_tx"])
            entry = by_key.get(key)
            if entry is None:
                entry = {
                    "hop": hit["hop"],
                    "address": hit["address"],
                    "from_utxo": hit["from_utxo"],
                    "in_tx": hit["in_tx"],
                    "amount_sats": hit["amount_sats"],
                    "wallet_utxos": set(),
                }
                by_key[key] = entry
            entry["wallet_utxos"].add(hit.get("wallet_utxo", ""))

        print(
            f"\n  ⚠️  {len(by_key)} Treffer "
            f"(sanktionierte Adresse in der Hop-Vorgeschichte):\n"
        )
        with cancellable_output(hint="Trefferliste — q zum Abbrechen"):
            for index, entry in enumerate(
                sorted(by_key.values(), key=lambda e: (e["hop"], e["address"])),
                start=1,
            ):
                if is_list_abort_requested():
                    break
                addr = abbrev_display(entry["address"])
                from_utxo = format_utxo_ref(entry["from_utxo"])
                in_tx = abbrev_display(entry["in_tx"])
                wallet_refs = ", ".join(
                    format_utxo_ref(ref)
                    for ref in sorted(entry["wallet_utxos"])
                    if ref
                )
                print(
                    f"  [{index}] Hop {entry['hop']}: {addr} "
                    f"({entry['amount_sats']:,} sats)"
                )
                print(f"       UTXO: {from_utxo}  →  Tx {in_tx}")
                if wallet_refs:
                    print(f"       Betrifft Wallet-UTXO(s): {wallet_refs}")
                print()

    cjs = _coinjoins_zusammenfuehren(list(coinjoins or []))
    if not cjs:
        return
    print("\n  CoinJoins in der geprüften Vorgeschichte:")
    for cj in cjs:
        hop = cj.get("hop", 0)
        when = str(cj.get("time") or "").strip() or "Zeit unbekannt"
        label = str(cj.get("label") or "").strip() or "vermutlich CoinJoin/Mix"
        # „Wahrscheinlich X“ → „vermutlich X“ für den Report-Satz
        if label.lower().startswith("wahrscheinlich "):
            label = "vermutlich " + label[len("Wahrscheinlich "):]
        tid = abbrev_display(str(cj.get("txid") or ""))
        print(f"    Hop {hop} · {when} · {label}" + (f" · Tx {tid}" if tid else ""))
    print()



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

    from fulcrum import fetch_address_utxos_fulcrum

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
    from bip158_scanner import MatchedTransaction, ScanResult
    from fulcrum import address_to_scripthash

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

