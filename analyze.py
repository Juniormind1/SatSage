"""Tx/UTXO-Herkunftsanalyse und Trace (ohne interaktive Prompts)."""
from __future__ import annotations

import sys
import urllib.error
from dataclasses import dataclass

from display import (
    abbrev_display,
    cancellable_output,
    format_sats,
    format_tx_display,
    format_utxo_display,
    format_utxo_ref,
    is_list_abort_requested,
    is_verbose,
)
from pathlib import Path
from typing import TYPE_CHECKING

from trace_engine import (
    CoinbaseFunding,
    FundingEdge,
    MAX_TRACE_DEPTH,
    UnresolvedExternalBatch,
    iter_funding_inputs,
    iter_trace_funding_inputs,
    is_own_output,
    match_own_address,
    parse_utxo_ref,
    resolve_vin_prevout,
    utxo_ref,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


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


class _EphemeralProgress:
    """Einzelzeilen-Fortschritt; wird vor der Standardausgabe gelöscht."""

    _LINE_WIDTH = 100

    def __init__(self, prefix: str = ""):
        self._prefix = prefix
        self._enabled = sys.stdout.isatty()
        self._shown = False

    def update(self, message: str) -> None:
        if not self._enabled:
            return
        self._shown = True
        line = f"{self._prefix}{message}"
        if len(line) > self._LINE_WIDTH:
            line = line[: self._LINE_WIDTH - 1] + "…"
        padded = line.ljust(self._LINE_WIDTH)
        try:
            print(f"\r\033[2K{padded}", end="", flush=True)
        except Exception:
            print(f"\r{padded}", end="", flush=True)

    def clear(self) -> None:
        if not self._enabled or not self._shown:
            return
        try:
            print("\r\033[2K", end="", flush=True)
        except Exception:
            print("\r" + " " * self._LINE_WIDTH + "\r", end="", flush=True)
        self._shown = False


def _resolve_input_output(
    get_tx,
    vin: dict,
    progress: _EphemeralProgress | None = None,
) -> dict | None:
    """Ermittelt den Output einer Input-Referenz (RPC oder Esplora)."""
    cb = progress.update if progress else None
    return resolve_vin_prevout(get_tx, vin, progress=cb)


def _parse_utxo_ref(ref: str) -> tuple[str, int] | None:
    return parse_utxo_ref(ref)


def _match_own_address(
    addrs: list[str],
    own_addresses: set,
    wallet: WalletContext | None = None,
) -> str | None:
    return match_own_address(addrs, own_addresses, wallet)


def _is_own_output(
    addrs: list[str],
    own_addresses: set,
    wallet: WalletContext | None = None,
) -> bool:
    return is_own_output(addrs, own_addresses, wallet)


def _is_own_address(
    address: str,
    own_addresses: set,
    wallet: WalletContext | None = None,
) -> bool:
    if wallet and wallet.is_own_address(address):
        return True
    return address in own_addresses



def trace_utxo_origin(
    get_tx,
    creator_txid: str,
    vout_index: int,
    own_addresses: set,
    visited_utxos: set | None = None,
    depth: int = 0,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress: _EphemeralProgress | None = None,
    alle_eigenen_inputs: bool = False,
    *,
    memo: dict | None = None,
) -> dict | None:
    """
    Verfolgt, wie der Output creator_txid:vout_index finanziert wurde.
    Wallet-Adressen werden lokal per XPUB erkannt (kein Bereichs-Scan).
    Optional: fehlende Adressen gezielt in den Cache ergänzen.

    *alle_eigenen_inputs*: bei großen Sammel-Txs alle eigenen Inputs
    weiterverfolgen (siehe ``iter_trace_funding_inputs``).

    *visited_utxos* hält nur den aktuellen Pfad (echte Zyklen). Rauten —
    derselbe Vorgänger über mehrere eigene Ausgänge derselben Tx — werden
    über *memo* wiederverwendet, nicht als leerer „cycle“-Blattknoten
    abgeschnitten. Sonst bleiben bei CoinJoin/Mix hunderte grüne Blätter
    ohne rot/lila-Ende stehen.
    """
    # Pfad-lokal: Aufrufer dürfen ein Set übergeben (Tests), aber Geschwister
    # dürfen sich die besuchten Knoten nicht teilen — sonst wird jede Raute
    # fälschlich zum Zyklus. Deshalb kopieren wir bei depth==0 nicht; ab dem
    # ersten Abstieg erhält jedes Kind eine eigene Pfadkopie.
    if visited_utxos is None:
        visited_utxos = set()
    if memo is None:
        memo = {}

    utxo_key = f"{creator_txid}:{vout_index}"
    if utxo_key in visited_utxos or depth > MAX_TRACE_DEPTH:
        return {
            "type": "cycle",
            "utxo": utxo_key,
            "sources": [],
        }

    # Fertigen Unterbaum wiederverwenden (Raute / gemeinsamer Vorgänger).
    if utxo_key in memo:
        return memo[utxo_key]

    visited_utxos.add(utxo_key)

    if progress:
        progress.update(
            f"↻ Herkunft Trace Tiefe {depth + 1}/{MAX_TRACE_DEPTH}: "
            f"lade Tx {creator_txid[:16]}…"
        )

    try:
        tx = get_tx(creator_txid)
    except Exception as e:
        node = {
            "type": "error",
            "utxo": utxo_key,
            "error": str(e),
            "sources": [],
        }
        # Fehler nicht memoisieren — erneuter Versuch (Follow-up) soll neu laden.
        visited_utxos.discard(utxo_key)
        return node

    if vout_index >= len(tx.get("vout", [])):
        visited_utxos.discard(utxo_key)
        return {
            "type": "error",
            "utxo": utxo_key,
            "error": "vout index ungültig",
            "sources": [],
        }

    out = tx["vout"][vout_index]
    out_addrs = _main()._extract_addresses(out)

    node = {
        "type": "utxo",
        "txid": creator_txid,
        "vout": vout_index,
        "addresses": out_addrs,
        "amount_sats": _main()._extract_value_sats(out),
        "time": _main()._format_tx_time(tx),
        "time_ts": _main()._tx_block_time(tx),
        "sources": [],
    }

    progress_cb = progress.update if progress else None
    for inp in iter_trace_funding_inputs(
        get_tx,
        creator_txid,
        own_addresses,
        wallet=wallet,
        progress=progress_cb,
        alle_eigenen_inputs=alle_eigenen_inputs,
    ):
        if isinstance(inp, CoinbaseFunding):
            node["sources"].append({"type": "coinbase", "amount_sats": 0})
            continue
        if isinstance(inp, UnresolvedExternalBatch):
            node["sources"].append({
                "type": "external_unresolved",
                "input_count": inp.input_count,
                "amount_sats": 0,
            })
            continue
        edge: FundingEdge = inp
        prev_ref = edge.prevout.key
        prev_addrs = list(edge.addresses)
        amount_sats = edge.amount_sats
        prev_txid = edge.prevout.txid
        prev_vout = edge.prevout.vout

        try:
            own_addr = _match_own_address(prev_addrs, own_addresses, wallet)
            if own_addr:
                if progress:
                    wallet_label = (
                        wallet.resolve_address(own_addr) if wallet else own_addr[:12]
                    )
                    progress.update(
                        f"↻ Herkunft Trace Tiefe {depth + 2}/{MAX_TRACE_DEPTH}: "
                        f"intern {wallet_label} ← {prev_txid[:16]}…"
                    )
                if wallet and cache_dir and fetch_address_utxos and cache_source:
                    _main()._ensure_address_cached(
                        own_addr,
                        wallet,
                        cache_dir,
                        fetch_address_utxos,
                        cache_source,
                    )
                # Eigener Pfad je Kind — Geschwister sehen nur memo, nicht
                # gegenseitig die besuchten Knoten des anderen Asts.
                child = trace_utxo_origin(
                    get_tx,
                    prev_txid,
                    prev_vout,
                    own_addresses,
                    set(visited_utxos),
                    depth + 1,
                    wallet=wallet,
                    cache_dir=cache_dir,
                    fetch_address_utxos=fetch_address_utxos,
                    cache_source=cache_source,
                    progress=progress,
                    alle_eigenen_inputs=alle_eigenen_inputs,
                    memo=memo,
                )
                node["sources"].append({
                    "type": "internal",
                    "address": own_addr,
                    "amount_sats": amount_sats,
                    "from_utxo": prev_ref,
                    "trace": child,
                })
            else:
                node["sources"].append({
                    "type": "external",
                    "address": prev_addrs[0] if prev_addrs else "unbekannt",
                    "amount_sats": amount_sats,
                    "from_utxo": prev_ref,
                    "time_ts": edge.prev_time_ts,
                })
        except Exception:
            continue

    if not node["sources"]:
        node["type"] = "unknown"

    # Nur abgeschlossene Knoten cachen — cycle bleibt pfadgebunden.
    memo[utxo_key] = node
    visited_utxos.discard(utxo_key)
    return node


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
    if not (youngest or external):
        return None

    from main import resolve_immutable_cache_dir, save_utxo_ingress_cache

    imm_root = (
        Path(immutable_cache_dir) if immutable_cache_dir
        else resolve_immutable_cache_dir(utxo_cache_dir=cache_dir)
    )
    return save_utxo_ingress_cache(
        txid,
        vout,
        {
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
        },
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
):
    """Führt die transaktionsorientierte Folge-Analyse für Vorgänger-Txs aus."""
    for pred_txid in sorted(internal_predecessors):
        if pred_txid != current_txid:
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
            )

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
) -> TxFollowupContext | None:
    """Analysiert die Tx und zeigt eigene Adressen als Input/Output."""
    if analyzed_txs is None:
        analyzed_txs = set()

    if txid in analyzed_txs:
        return
    analyzed_txs.add(txid)

    try:
        tx = get_tx(txid)
    except urllib.error.HTTPError as e:
        print(f"Fehler beim Laden der Tx: HTTP {e.code} ({e.reason})")
        return
    except Exception as e:
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
        except Exception:
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


def scan_external_sanction_hops(
    get_tx,
    creator_txid: str,
    vout_index: int,
    own_addresses: set,
    sanctioned_addresses: frozenset[str],
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
    Verfolgt externe Vorgänger (ohne eigene Wallet-Adressen) rückwärts und
    meldet Treffer auf der OFAC-Sanktionsliste.

    *gesehene_adressen* sammelt, wenn übergeben, jede geprüfte externe
    Adresse. Anders als ``counters["addrs_checked"]`` zählt das Set jede
    Adresse einmal, auch wenn sie in der Vorgeschichte mehrerer UTXOs
    auftaucht — es beantwortet „was wurde geprüft", nicht „wie viele
    Vergleiche liefen".
    """
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
            if is_own_output(edge.addresses, own_addresses, wallet):
                continue

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

            scan_external_sanction_hops(
                get_tx,
                edge.prevout.txid,
                edge.prevout.vout,
                own_addresses,
                sanctioned_addresses,
                max_hops=max_hops,
                wallet=wallet,
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


def _pruefe_ein_utxo(
    get_tx,
    utxo: dict,
    own_addresses: set,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    abort_on_hit: bool,
    progress,
) -> tuple[str, list[dict], set[str]] | None:
    """
    Ein UTXO prüfen. Rückgabe: (ref, treffer, gesehene Adressen) oder None,
    wenn der Eintrag keine brauchbare txid/vout trägt.

    Eigene Ergebnisbehälter je Aufruf — das macht den Parallel-Lauf möglich,
    ohne dass Worker sich gegenseitig in die Listen schreiben.
    """
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
    if progress is not None:
        progress.update(
            wallet_utxo=ref,
            hop=0,
            max_hops=max_hops,
            addrs_checked=0,
            status="noch keine sanktionierte Adresse gefunden",
        )
    scan_external_sanction_hops(
        get_tx,
        txid,
        vout_index,
        own_addresses,
        sanctioned_addresses,
        max_hops=max_hops,
        wallet=wallet,
        wallet_utxo_ref=ref,
        progress=progress,
        counters={"addrs_checked": 0},
        hits=treffer,
        abort_on_hit=abort_on_hit,
        gesehene_adressen=gesehen,
    )
    return ref, treffer, gesehen


def _check_wallet_utxos_parallel(
    get_tx_je_worker,
    utxos: list[dict],
    own_addresses: set,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    worker_count: int,
    progress_cb,
    cancel_cb,
    gesehene_adressen: set[str] | None,
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
    geprueft = 0
    fortschritt = (
        _FortschrittsAdapter(progress_cb, melde_sperre)
        if progress_cb is not None else None
    )

    def abbruch_gewuenscht() -> bool:
        return bool(cancel_cb and cancel_cb())

    def worker(worker_id: int) -> None:
        nonlocal geprueft
        get_tx = get_tx_je_worker(worker_id)
        while not abbruch_gewuenscht():
            try:
                utxo = arbeit.get_nowait()
            except queue.Empty:
                return
            ergebnis = _pruefe_ein_utxo(
                get_tx, utxo, own_addresses, sanctioned_addresses,
                max_hops=max_hops, wallet=wallet, abort_on_hit=False,
                progress=fortschritt,
            )
            if ergebnis is None:
                continue
            _ref, treffer, gesehen = ergebnis
            with sperre:
                geprueft += 1
                alle_treffer.extend(treffer)
                if gesehene_adressen is not None:
                    gesehene_adressen.update(gesehen)

    arbeiter = min(worker_count, len(utxos))
    with ThreadPoolExecutor(max_workers=arbeiter) as executor:
        for future in [executor.submit(worker, i) for i in range(arbeiter)]:
            future.result()

    # Stabile Reihenfolge: Ohne Sortierung hinge sie am Thread-Timing, und
    # zwei Läufe über dieselben Daten lieferten verschiedene Dateien.
    alle_treffer.sort(
        key=lambda t: (t.get("wallet_utxo", ""), t.get("hop", 0),
                       t.get("address", ""))
    )
    return alle_treffer, geprueft, None


def check_wallet_utxos_sanctions(
    get_tx,
    utxos: list[dict],
    own_addresses: set,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None = None,
    abort_on_hit: bool = True,
    progress_cb=None,
    cancel_cb=None,
    gesehene_adressen: set[str] | None = None,
    get_tx_je_worker=None,
    worker_count: int = 1,
) -> tuple[list[dict], int, dict | None]:
    """
    Prüft Wallet-UTXOs auf sanktionierte Adressen in der externen Vorgeschichte.
    Rückgabe: (treffer, geprüfte_utxos, abbruch_treffer|None)

    *progress_cb* ist ein Callable[[dict], None] mit Feldern
    (wallet_utxo, hop, max_hops, addrs_checked, status). *cancel_cb* ist ein
    Callable[[], bool] — liefert es True, bricht die Prüfung sauber ab.
    Beides optional; ohne Angabe läuft die CLI-Ausgabe über
    SanctionCheckProgressLine und die Tastatur-Abfrage.

    *gesehene_adressen* wird, wenn übergeben, mit jeder geprüften externen
    Adresse befüllt — der Aufrufer liest das Set nach dem Lauf aus.

    *get_tx_je_worker* ist ein Callable[[int], get_tx]: Liefert es zusammen
    mit *worker_count* > 1 eine eigene Verbindung je Worker, laufen die
    UTXOs parallel. Ohne das bleibt es beim seriellen Lauf über *get_tx* —
    der Weg, den die CLI mit ihrem Treffer-Abbruch nimmt.
    """
    if not utxos or not sanctioned_addresses or max_hops < 1:
        return [], 0, None

    if get_tx_je_worker is not None and worker_count > 1 and not abort_on_hit:
        return _check_wallet_utxos_parallel(
            get_tx_je_worker, utxos, own_addresses, sanctioned_addresses,
            max_hops=max_hops, wallet=wallet, worker_count=worker_count,
            progress_cb=progress_cb, cancel_cb=cancel_cb,
            gesehene_adressen=gesehene_adressen,
        )

    import threading

    from display import SanctionCheckProgressLine

    all_hits: list[dict] = []
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
                )
            except SanctionHitFound as exc:
                checked += 1
                abort_hit = exc.hit
                break
            if ergebnis is None:
                continue
            _ref, treffer, gesehen = ergebnis
            checked += 1
            all_hits.extend(treffer)
            if gesehene_adressen is not None:
                gesehene_adressen.update(gesehen)
    finally:
        if cli_progress is not None:
            cli_progress.finish()

    return all_hits, checked, abort_hit


def print_sanction_check_report(
    hits: list[dict],
    *,
    wallet_name: str,
    max_hops: int,
    utxo_count: int,
    sanctioned_count: int,
    aborted: bool = False,
) -> None:
    """Gibt das Ergebnis der Sanktionsprüfung aus."""
    print(f"\n{'═' * 72}")
    print(f"  Sanktionsprüfung: {wallet_name}")
    print(
        f"  {utxo_count} UTXO(s) geprüft, {max_hops} externe Hop(s), "
        f"{sanctioned_count:,} Adressen in der Liste"
    )
    if aborted:
        print("  ⚠️  Prüfung nach Treffer abgebrochen")
    print(f"{'═' * 72}")

    if not hits:
        print(
            "\n  Keine Treffer — in der geprüften Vorgeschichte keine "
            "sanktionierte Adresse gefunden."
        )
        return

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
        f"(sanktionierte Adresse in externer Vorgeschichte):\n"
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

