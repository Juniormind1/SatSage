"""UTXO-Ingress-Report: Persistenz, Collect/Youngest, Print/Followups (Slice 4).

Collect-/Youngest-/Oldest-Helfer, persist_utxo_ingress, Print-Summaries,
_analyze_utxo_funding und Tx-/UTXO-Followup-Kontexte. analyze.py re-exportiert
die öffentliche API; core.trace importiert hier direkt für Persist/_youngest_*,
damit kein Domänen-Zyklus core → analyze entsteht.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from display import (
    abbrev_display,
    format_sats,
    format_tx_display,
    format_utxo_display,
    format_utxo_ref,
    is_verbose,
)

from core.utxo_origin import (
    _EphemeralProgress,
    trace_utxo_origin,
)

if TYPE_CHECKING:
    from main import WalletContext


def _format_amount_display(sats: int | float) -> str:
    """Betragsanzeige: bei Verbose=n ``format_sats``, sonst sats + 8 Dezimal-BTC."""
    amount = int(sats)
    if is_verbose():
        return f"{amount:,} sats ({amount / 1e8:.8f} BTC)"
    return format_sats(amount)


@dataclass
class TxFollowupContext:
    predecessors: set[str]
    found_inputs: list
    found_outputs: list
    total_external_sats: int
    txid: str
    depth: int
    analyzed_txs: set[str]


@dataclass
class UtxoFollowupContext:
    predecessors: set[str]
    utxo_count: int
    analyzed_txs: set[str]


def _sum_external_sats(node: dict | None) -> int:
    if not node:
        return 0
    total = 0
    for src in node.get("sources", []):
        if src["type"] == "external":
            total += src["amount_sats"]
        elif src["type"] == "coinbase":
            total += src["amount_sats"]
        elif src["type"] == "internal":
            total += _sum_external_sats(src.get("trace"))
    return total


def _sum_internal_sats(node: dict | None) -> int:
    if not node:
        return 0
    total = 0
    for src in node.get("sources", []):
        if src["type"] == "internal":
            total += src["amount_sats"]
    return total


def _group_external_sources(sources: list) -> list[dict]:
    """Gruppiert externe/Coinbase-Inputs nach Adresse und saldiert Sats."""
    groups: dict[str, dict] = {}
    for src in sources:
        if src["type"] == "coinbase":
            key = "__coinbase__"
            label = "Coinbase"
            count = 1
        elif src["type"] == "external":
            key = src.get("address") or "unbekannt"
            label = key
            count = 1
        elif src["type"] == "external_unresolved":
            key = "__external_unresolved__"
            count = int(src.get("input_count", 0))
            label = f"{count} externe Inputs (Vorgänger nicht aufgelöst)"
        else:
            continue

        if key not in groups:
            groups[key] = {
                "address": label,
                "utxo_count": 0,
                "total_sats": 0,
            }
        groups[key]["utxo_count"] += count
        groups[key]["total_sats"] += src["amount_sats"]

    return sorted(groups.values(), key=lambda g: -g["total_sats"])


def _format_utxo_count(count: int) -> str:
    return f"{count} UTXO" if count == 1 else f"{count} UTXOs"


def _print_external_groups(groups: list[dict], pad: str):
    for group in groups:
        if group["address"] == "Coinbase":
            print(
                f"{pad}⛏️  Coinbase: {_format_utxo_count(group['utxo_count'])}, "
                f"{_format_amount_display(group['total_sats'])} gesamt"
            )
        elif "(Vorgänger nicht aufgelöst)" in group["address"]:
            print(f"{pad}🌐 Extern: {group['address']}")
        else:
            print(
                f"{pad}🌐 Extern: {abbrev_display(group['address'])}  "
                f"{_format_utxo_count(group['utxo_count'])}, "
                f"{_format_amount_display(group['total_sats'])} gesamt"
            )


def _print_funding_trace(
    node: dict | None,
    indent: int = 0,
    wallet: WalletContext | None = None,
):
    if not node:
        return

    pad = "   " * indent

    if node.get("type") == "error":
        print(f"{pad}⚠️  Fehler bei {format_utxo_ref(str(node.get('utxo', '')))}: {node.get('error')}")
        return

    if node.get("type") == "cycle":
        print(f"{pad}↩️  Zyklus / Tiefe erreicht bei {format_utxo_ref(str(node.get('utxo', '')))}")
        return

    if node.get("type") == "utxo":
        out_addrs = node.get("addresses") or ["?"]
        if wallet:
            addrs = wallet.format_addresses(out_addrs)
        else:
            addrs = ", ".join(abbrev_display(a) for a in out_addrs)
        print(
            f"{pad}📦 UTXO {format_utxo_display(node['txid'], node['vout'], addresses=node.get('addresses'))} → {addrs} "
            f"({_format_amount_display(node['amount_sats'])}, {node.get('time', 'unbekannt')})"
        )

    sources = node.get("sources", [])
    external_groups = _group_external_sources(sources)
    if external_groups:
        _print_external_groups(external_groups, pad + "   ")

    for src in sources:
        if src["type"] == "internal":
            from_label = (
                wallet.resolve_address(src["address"]) if wallet else None
            )
            to_labels = wallet.own_labels(node.get("addresses", [])) if wallet else []
            if from_label and to_labels and from_label != to_labels[0]:
                intern_label = f"{from_label} → {to_labels[0]}"
            elif from_label:
                intern_label = from_label
            elif wallet:
                intern_label = "intern"
            else:
                intern_label = src["address"]
            print(
                f"{pad}   🔄 Intern ({intern_label}): "
                f"{_format_amount_display(src['amount_sats'])} aus {format_utxo_ref(src['from_utxo'])}"
            )
            _print_funding_trace(src.get("trace"), indent + 2, wallet=wallet)


def _find_wallet_entries(node: dict | None) -> list[dict]:
    """Tx(s), bei denen externe Sats erstmals auf eine Wallet-Adresse landeten."""
    if not node or node.get("type") not in ("utxo", "unknown"):
        return []

    sources = node.get("sources", [])
    internal = [s for s in sources if s["type"] == "internal"]
    external = [
        s for s in sources
        if s["type"] in ("external", "external_unresolved", "coinbase")
    ]

    entries = []
    for src in internal:
        entries.extend(_find_wallet_entries(src.get("trace")))

    if external:
        entries.append({
            "txid": node["txid"],
            "vout": node["vout"],
            "addresses": node.get("addresses", []),
            "amount_sats": node["amount_sats"],
            "time": node.get("time", "unbekannt"),
            "time_ts": node.get("time_ts"),
            "external_sats": sum(s["amount_sats"] for s in external),
            "external_groups": _group_external_sources(external),
        })

    return entries


def _print_wallet_entries(
    entries: list[dict],
    header_pad: str,
    wallet: WalletContext | None = None,
):
    """Gibt Zeitpunkt(e) aus, an denen Sats das Wallet betreten haben."""
    if not entries:
        return

    seen = set()
    unique = []
    for entry in sorted(entries, key=lambda e: e.get("time_ts") or 0):
        key = f"{entry['txid']}:{entry['vout']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)

    by_time: dict[int, dict] = {}
    for entry in unique:
        ts = entry.get("time_ts") or 0
        if ts not in by_time:
            by_time[ts] = {
                "time": entry["time"],
                "wallet_sats": 0,
                "external_sats": 0,
                "external_groups": {},
                "outputs": [],
            }
        bucket = by_time[ts]
        bucket["wallet_sats"] += entry["amount_sats"]
        bucket["external_sats"] += entry["external_sats"]
        bucket["outputs"].append(entry)
        for group in entry.get("external_groups", []):
            addr = group["address"]
            if addr not in bucket["external_groups"]:
                bucket["external_groups"][addr] = {
                    "address": addr,
                    "utxo_count": 0,
                    "total_sats": 0,
                }
            bucket["external_groups"][addr]["utxo_count"] += group["utxo_count"]
            bucket["external_groups"][addr]["total_sats"] += group["total_sats"]

    wallet_names: set[str] = set()
    for entry in unique:
        for addr in entry.get("addresses", []):
            if wallet and (label := wallet.resolve_address(addr)):
                wallet_names.add(label)
    wallet_str = ", ".join(sorted(wallet_names)) if wallet_names else (
        wallet.scope_label() if wallet else "das Wallet"
    )
    print(f"{header_pad}🏦 Sats betraten {wallet_str}:")
    for ts in sorted(by_time.keys()):
        bucket = by_time[ts]
        print(
            f"{header_pad}   {bucket['time']}  —  "
            f"{_format_amount_display(bucket['wallet_sats'])} nach {wallet_str}"
        )
        print(
            f"{header_pad}      externe Inputs gesamt: "
            f"{_format_amount_display(bucket['external_sats'])}"
        )
        groups = sorted(
            bucket["external_groups"].values(),
            key=lambda g: -g["total_sats"],
        )
        if groups:
            _print_external_groups(groups, header_pad + "         ")
        for entry in bucket["outputs"]:
            out_addrs = entry.get("addresses") or ["?"]
            if wallet:
                addrs = wallet.format_addresses(out_addrs)
            else:
                addrs = ", ".join(out_addrs)
            print(
                f"{header_pad}      → {addrs}  "
                f"({_format_amount_display(entry['amount_sats'])}, Tx {format_utxo_display(entry['txid'], entry['vout'], addresses=entry.get('addresses'))})"
            )

    if len(by_time) > 1:
        earliest_ts = min(by_time.keys())
        print(f"{header_pad}   → frühester Eingang: {by_time[earliest_ts]['time']}")


def _collect_wallet_ingress_events(
    node: dict | None,
    wallet: WalletContext | None,
) -> list[dict]:
    """Alle Zeitpunkte, an denen Sats auf eine Wallet-Adresse landeten."""
    if not node or node.get("type") not in ("utxo", "unknown"):
        return []

    events: list[dict] = []
    if wallet:
        out_wallets = wallet.own_labels(node.get("addresses", []))
        if out_wallets:
            events.append({
                "time_ts": node.get("time_ts") or 0,
                "time": node.get("time", "unbekannt"),
                "amount_sats": node["amount_sats"],
                "wallet": ", ".join(sorted(out_wallets)),
                "txid": node.get("txid"),
                "vout": node.get("vout"),
            })

    for src in node.get("sources", []):
        if src["type"] == "internal":
            events.extend(_collect_wallet_ingress_events(src.get("trace"), wallet))

    return events


def _youngest_wallet_ingress(
    trace: dict | None,
    wallet: WalletContext | None,
) -> dict | None:
    events = _collect_wallet_ingress_events(trace, wallet)
    if not events:
        return None
    return max(events, key=lambda e: e["time_ts"])


def _collect_external_ingress_events(node: dict | None) -> list[dict]:
    """
    Alle externen Zuflüsse im Baum — die Stellen, an denen Sats erstmals von
    außen in die eigene Verfügungsmacht kamen.

    Steuerlich ist das der Anschaffungszeitpunkt: Interne Überträge (auch
    über mehrere eigene XPUBs/Seeds hinweg) verändern die Haltedauer nicht;
    erst ein externer Zufluss beginnt sie.
    """
    if not node or node.get("type") not in ("utxo", "unknown"):
        return []

    events: list[dict] = []
    for src in node.get("sources", []):
        typ = src["type"]
        if typ == "internal":
            events.extend(_collect_external_ingress_events(src.get("trace")))
        elif typ == "external":
            events.append({
                "time_ts": src.get("time_ts"),
                "amount_sats": src.get("amount_sats", 0),
                "address": src.get("address", ""),
                "from_utxo": src.get("from_utxo", ""),
            })
        elif typ == "external_unresolved":
            events.append({
                "time_ts": None,
                "amount_sats": 0,
                "address": "",
                "from_utxo": "",
                "unresolved": True,
            })
        elif typ == "coinbase":
            # Geschürfte Sats: der Coinbase selbst ist der externe Zufluss.
            # Sein Zeitpunkt ist die Blockzeit der aktuellen Kette in `node`.
            events.append({
                "time_ts": node.get("time_ts"),
                "amount_sats": node.get("amount_sats", 0),
                "address": "",
                "from_utxo": "",
                "coinbase": True,
            })
    return events


def _external_ingress_extrema(trace: dict | None) -> dict | None:
    """
    Jüngster und ältester datierter externer Zufluss im Baum.

    *untergrenze*: True, wenn daneben Zuflüsse ohne Datum stehen (einer
    davon kann jünger sein als der jüngste Bekannte).
    """
    events = _collect_external_ingress_events(trace)
    if not events:
        return None
    bekannte = [e for e in events if e.get("time_ts")]
    if not bekannte:
        return None
    juengster = max(bekannte, key=lambda e: e["time_ts"])
    aeltester = min(bekannte, key=lambda e: e["time_ts"])
    untergrenze = len(events) > len(bekannte)
    return {
        "youngest": {
            "time_ts": juengster["time_ts"],
            "amount_sats": juengster["amount_sats"],
            "address": juengster["address"],
            "untergrenze": untergrenze,
        },
        "oldest": {
            "time_ts": aeltester["time_ts"],
            "amount_sats": aeltester["amount_sats"],
            "address": aeltester["address"],
            "untergrenze": untergrenze,
        },
        "untergrenze": untergrenze,
    }


def _collect_tax_horizon_events(node: dict | None) -> list[dict]:
    """Blätter, an denen der Steuer-Trace absichtlich endete."""
    if not node:
        return []
    events: list[dict] = []
    if node.get("tax_horizon") and node.get("time_ts"):
        addrs = node.get("addresses") or []
        events.append({
            "time": node.get("time") or "",
            "time_ts": int(node["time_ts"]),
            "amount_sats": int(node.get("amount_sats") or 0),
            "address": addrs[0] if addrs else "",
            "wallet": None,
        })
        return events
    for src in node.get("sources") or []:
        if not isinstance(src, dict):
            continue
        if src.get("type") == "internal":
            events.extend(_collect_tax_horizon_events(src.get("trace")))
    return events


def _youngest_tax_horizon(trace: dict | None) -> dict | None:
    events = _collect_tax_horizon_events(trace)
    bekannte = [e for e in events if e.get("time_ts")]
    if not bekannte:
        return None
    return max(bekannte, key=lambda e: e["time_ts"])


def _youngest_external_ingress(trace: dict | None) -> dict | None:
    """
    Jüngster bekannter externer Zufluss — defensive Anschaffungslesart.

    Liefert ein dict mit time_ts, amount_sats und address des jüngsten
    externen Zuflusses sowie *untergrenze*: True, wenn daneben externe
    Zuflüsse ohne bekanntes Datum stehen. Einer davon kann jünger sein als
    der gefundene — dann ist die ausgewiesene Haltefrist zu lang, also die
    riskante Richtung.

    Ohne einen einzigen datierten externen Zufluss liefert die Funktion
    None: Aus unbekannten Daten lässt sich kein Anschaffungsdatum ableiten.
    Die Steuerschicht fällt dann auf den jüngsten Wallet-Eingang zurück und
    weist das aus — der ist bei Eigenüberträgen zu jung, aber nie zu alt.
    """
    extrema = _external_ingress_extrema(trace)
    return extrema["youngest"] if extrema else None


def _oldest_external_ingress(trace: dict | None) -> dict | None:
    """Ältester bekannter externer Zufluss — offensive Anschaffungslesart."""
    extrema = _external_ingress_extrema(trace)
    return extrema["oldest"] if extrema else None


def persist_utxo_ingress(
    trace: dict | None,
    *,
    txid: str,
    vout: int,
    address: str = "",
    amount_sats: int = 0,
    wallet=None,
    cache_dir=None,
    immutable_cache_dir=None,
):
    """
    Hält das Ergebnis einer Herkunftsanalyse im Ingress-Cache fest.

    Muss von **jeder** Oberfläche aufgerufen werden, die Herkunft verfolgt: Die
    Steuerjahr-Auswertung liest das Anschaffungsdatum ausschließlich von dort
    (``core.tax._anschaffung``). Fehlt der Eintrag, fällt sie auf das
    Entstehungsdatum des Outputs zurück und weist die Zeile als „nur
    Output-Datum" aus, obwohl die Herkunft längst bekannt ist.

    *immutable_cache_dir* benennt das Ziel ausdrücklich. Wer nur *cache_dir*
    übergibt, bekommt das daneben liegende ``immutable_cache`` — so macht es
    das CLI. Beide Wege müssen dasselbe Verzeichnis treffen wie die lesende
    Seite: Ein eigenes ``--immutable-cache-dir`` verschiebt nur das Lesen, und
    ein daraus abgeleitetes Schreibziel liefe daran vorbei.

    Ohne beides wird nichts geschrieben — ein Trace zum bloßen Ansehen soll
    keine Spuren hinterlassen.
    """
    if not trace or not (cache_dir or immutable_cache_dir):
        return None

    youngest = _youngest_wallet_ingress(trace, wallet)
    external = _youngest_external_ingress(trace)
    oldest = _oldest_external_ingress(trace)
    horizon = _youngest_tax_horizon(trace)
    # Steuer-Horizont ohne Extern: Horizont-Zeit als Wallet-Eingang-Ersatz
    # (wahrer Extern ist älter → Haltedauer hier höchstens unterschätzt).
    if not youngest and horizon:
        youngest = {
            "time": horizon.get("time"),
            "time_ts": horizon.get("time_ts"),
            "wallet": horizon.get("wallet"),
            "amount_sats": horizon.get("amount_sats") or amount_sats,
        }
    if not (youngest or external):
        return None

    from main import resolve_immutable_cache_dir, save_utxo_ingress_cache

    imm_root = (
        Path(immutable_cache_dir) if immutable_cache_dir
        else resolve_immutable_cache_dir(utxo_cache_dir=cache_dir)
    )
    nutzlast = {
        "youngest_time": youngest["time"] if youngest else None,
        "youngest_time_ts": youngest["time_ts"] if youngest else None,
        "youngest_wallet": youngest["wallet"] if youngest else None,
        "youngest_sats": (
            min(youngest["amount_sats"], amount_sats) if youngest and amount_sats
            else (youngest["amount_sats"] if youngest else None)
        ),
        # Steuerliches Anschaffungsdatum: jüngster und ältester externer
        # Zufluss (Report wählt per STEUER_ANSCHAFFUNG). Interne Überträge
        # zwischen eigenen XPUBs/Seeds verändern die Haltedauer nicht.
        "external_time_ts": external["time_ts"] if external else None,
        "external_sats": external["amount_sats"] if external else None,
        "external_address": external["address"] if external else None,
        "external_oldest_time_ts": (
            oldest["time_ts"] if oldest else None
        ),
        "external_oldest_sats": (
            oldest["amount_sats"] if oldest else None
        ),
        "external_oldest_address": (
            oldest["address"] if oldest else None
        ),
        "external_untergrenze": (
            external["untergrenze"] if external else False
        ),
        "address": address,
    }
    # Schlüssel setzen, auch wenn Wert None: „getraced, kein Extern“ vs. Alt-Cache.
    if external is None and horizon is not None:
        nutzlast["external_time_ts"] = None
        nutzlast["tax_horizon_time_ts"] = horizon.get("time_ts")
    return save_utxo_ingress_cache(
        txid,
        vout,
        nutzlast,
        imm_root,
    )


def _print_youngest_sats_summary(
    header_pad: str,
    total_sats: int,
    trace: dict | None,
    wallet: WalletContext | None,
    spend_txid: str | None = None,
) -> None:
    youngest = _youngest_wallet_ingress(trace, wallet)
    if not youngest:
        return

    z = min(youngest["amount_sats"], total_sats)
    wallet_name = youngest["wallet"]
    timestamp = youngest["time"]

    if spend_txid:
        prefix = (
            f"Von den {_format_amount_display(total_sats)}, die in Tx {format_tx_display(spend_txid)} "
            f"als Input ausgegeben wurden,"
        )
    else:
        prefix = f"Von den {_format_amount_display(total_sats)} an diesem UTXO"

    print(
        f"{header_pad}   → {prefix} sind die jüngsten {_format_amount_display(z)} "
        f"dem Wallet {wallet_name} am {timestamp} zugegangen. "
        f"Alle anderen sats sind noch älter."
    )


def _analyze_utxo_funding(
    get_tx,
    address: str,
    amount_sats: int,
    creator_txid: str,
    vout_index: int,
    own_addresses: set,
    header_pad: str,
    depth: int,
    internal_predecessors: set,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    spend_txid: str | None = None,
):
    """Herkunftsanalyse für ein UTXO (Input oder unspent)."""
    progress = _EphemeralProgress(prefix=header_pad)
    trace = trace_utxo_origin(
        get_tx,
        creator_txid,
        vout_index,
        own_addresses,
        wallet=wallet,
        cache_dir=cache_dir,
        fetch_address_utxos=fetch_address_utxos,
        cache_source=cache_source,
        progress=progress,
    )
    progress.clear()
    _print_funding_trace(trace, indent=depth + 1, wallet=wallet)

    ext_sats = _sum_external_sats(trace)
    int_sats = _sum_internal_sats(trace)
    if ext_sats or int_sats:
        print(
            f"{header_pad}   → Ursprung: {_format_amount_display(ext_sats)} extern / "
            f"{_format_amount_display(int_sats)} aus internem Wallet-Umlauf"
        )
        if wallet and int_sats and trace:
            source_wallets = sorted({
                wallet.resolve_address(src["address"])
                for src in trace.get("sources", [])
                if src["type"] == "internal"
                and wallet.resolve_address(src["address"])
            })
            if source_wallets:
                print(
                    f"{header_pad}   → Direkt aus Wallet(s): "
                    f"{', '.join(source_wallets)}"
                )

    entries = _find_wallet_entries(trace)
    if entries:
        print()
        _print_wallet_entries(entries, header_pad + "   ", wallet=wallet)

    _print_youngest_sats_summary(
        header_pad, amount_sats, trace, wallet, spend_txid=spend_txid
    )
    print()

    persist_utxo_ingress(
        trace,
        txid=creator_txid,
        vout=vout_index,
        address=address,
        amount_sats=amount_sats,
        wallet=wallet,
        cache_dir=cache_dir,
    )

    _collect_internal_creator_txs(trace, internal_predecessors)
    return trace


def _collect_internal_creator_txs(node: dict | None, txids: set):
    """Sammelt Txs mit interner Finanzierung für die vollständige Folge-Analyse."""
    if not node or node.get("type") not in ("utxo", "unknown"):
        return

    has_internal = any(src["type"] == "internal" for src in node.get("sources", []))
    if has_internal and node.get("txid"):
        txids.add(node["txid"])

    for src in node.get("sources", []):
        if src["type"] == "internal":
            _collect_internal_creator_txs(src.get("trace"), txids)


def _run_tx_oriented_followups(
    get_tx,
    internal_predecessors: set[str],
    current_txid: str,
    own_addresses: set,
    analyzed_txs: set,
    depth: int,
    wallet: WalletContext | None,
    cache_dir: Path | None,
    fetch_address_utxos,
    cache_source: str | None,
    *,
    cancel_cb=None,
    progress_cb=None,
):
    """Führt die transaktionsorientierte Folge-Analyse für Vorgänger-Txs aus."""
    from core.jobs import Cancelled
    # Late: vermeidet Importzyklus tx_utxo_analyze ↔ utxo_ingress_report.
    from core.tx_utxo_analyze import analyze_tx

    preds = [t for t in sorted(internal_predecessors) if t != current_txid]
    gesamt = len(preds)
    for index, pred_txid in enumerate(preds, start=1):
        if cancel_cb and cancel_cb():
            raise Cancelled()
        if progress_cb:
            progress_cb(
                f"Eigene Vorgänger-Txs {index}/{gesamt}: {pred_txid[:16]}…"
            )
        analyze_tx(
            get_tx,
            pred_txid,
            own_addresses,
            analyzed_txs=analyzed_txs,
            depth=depth + 1,
            trace_funding=True,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            allow_tx_followup=True,
            cancel_cb=cancel_cb,
            progress_cb=progress_cb,
        )

