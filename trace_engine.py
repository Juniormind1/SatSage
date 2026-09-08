"""Gemeinsame Graph-Engine: Rückwärts-Walk über Tx-Inputs (vin → prevout)."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

MAX_TRACE_DEPTH = 20


class ProgressCallback(Protocol):
    def __call__(self, message: str) -> None: ...


def _chain():
    import main

    return main


def utxo_ref(txid: str, vout: int) -> str:
    return f"{txid}:{vout}"


def parse_utxo_ref(utxo_ref: str) -> tuple[str, int] | None:
    if ":" not in utxo_ref:
        return None
    txid, vout = utxo_ref.rsplit(":", 1)
    try:
        return txid, int(vout)
    except ValueError:
        return None


def resolve_vin_prevout(
    get_tx: Callable[[str], dict],
    vin: dict,
    *,
    progress: ProgressCallback | None = None,
) -> dict | None:
    """Ermittelt den Output einer Input-Referenz (RPC oder Esplora)."""
    if vin.get("is_coinbase") or "txid" not in vin or "vout" not in vin:
        return None

    prevout = vin.get("prevout")
    if prevout:
        return prevout

    if progress:
        progress(f"↻ Herkunft: lade Vorgänger-Output {vin['txid'][:16]}…")
    prev_tx = get_tx(vin["txid"])
    vouts = prev_tx.get("vout", [])
    vout_index = int(vin["vout"])
    if vout_index >= len(vouts):
        return None
    prev_out = dict(vouts[vout_index])
    prev_out["_prev_tx_time_ts"] = _chain()._tx_block_time(prev_tx)
    return prev_out


@dataclass(frozen=True)
class PrevoutRef:
    txid: str
    vout: int

    @property
    def key(self) -> str:
        return utxo_ref(self.txid, self.vout)


@dataclass(frozen=True)
class FundingEdge:
    """Ein nicht-Coinbase-Input der Erzeuger-Tx."""

    spending_txid: str
    prevout: PrevoutRef
    addresses: tuple[str, ...]
    amount_sats: int
    #: Blockzeit der Vorgänger-Tx, wenn sie beim Auflösen mitgeladen wurde.
    prev_time_ts: int | None = None


@dataclass(frozen=True)
class CoinbaseFunding:
    spending_txid: str


@dataclass(frozen=True)
class UnresolvedExternalBatch:
    """Externe Inputs ohne Vorgänger-Tx (nach erstem internen Treffer übersprungen)."""

    spending_txid: str
    input_count: int


FundingInput = FundingEdge | CoinbaseFunding


def _funding_edge_from_vin(
    vin: dict,
    prev_out: dict,
    spending_txid: str,
) -> FundingEdge:
    chain = _chain()
    return FundingEdge(
        spending_txid=spending_txid,
        prevout=PrevoutRef(txid=vin["txid"], vout=int(vin["vout"])),
        addresses=tuple(chain._extract_addresses(prev_out)),
        amount_sats=chain._extract_value_sats(prev_out),
        prev_time_ts=prev_out.get("_prev_tx_time_ts"),
    )


def iter_funding_inputs(
    get_tx: Callable[[str], dict],
    creator_txid: str,
    *,
    progress: ProgressCallback | None = None,
) -> Iterator[FundingInput]:
    """
    Iteriert alle Finanzierungs-Inputs der Transaktion *creator_txid*.

    Vollständige Auflösung — für Tx-Analyse und Sanktions-Scans.
    """
    try:
        tx = get_tx(creator_txid)
    except Exception:
        return

    for vin in tx.get("vin", []):
        if vin.get("is_coinbase"):
            yield CoinbaseFunding(spending_txid=creator_txid)
            continue
        try:
            prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
            if not prev_out:
                continue
            yield _funding_edge_from_vin(vin, prev_out, creator_txid)
        except Exception:
            continue


@dataclass
class BackwardWalkState:
    """Zustand für zyklusfreie Rückwärts-Pfade."""

    visited: set[str]

    def mark(self, txid: str, vout: int) -> bool:
        """Markiert UTXO; Rückgabe False wenn bereits besucht."""
        key = utxo_ref(txid, vout)
        if key in self.visited:
            return False
        self.visited.add(key)
        return True


if TYPE_CHECKING:
    from main import WalletContext


def match_own_address(
    addrs: tuple[str, ...] | list[str],
    own_addresses: set[str],
    wallet: WalletContext | None = None,
) -> str | None:
    """Erste passende eigene Adresse oder None."""
    for addr in addrs:
        if not addr:
            continue
        if wallet and wallet.resolve_address(addr):
            return addr
        if addr in own_addresses:
            return addr
    return None


def is_own_output(
    addrs: tuple[str, ...] | list[str],
    own_addresses: set[str],
    wallet: WalletContext | None = None,
) -> bool:
    return match_own_address(addrs, own_addresses, wallet) is not None


def visit_utxo(state: BackwardWalkState, txid: str, vout: int) -> bool:
    return state.mark(txid, vout)


#: Bis zu dieser Zahl von Eingängen werden alle Inputs aufgelöst — dann ist
#: das jüngste externe Zuflussdatum exakt. Darüber wird nach dem ersten
#: internen Treffer abgebrochen und der Rest nur gezählt: Bei
#: Sammel-Transaktionen mit hunderten Inputs kostete jeder externe Input
#: einen get_tx-Abruf, und das Datum wäre ohnehin nur eine Untergrenze.
FULL_RESOLUTION_INPUT_LIMIT = 20


def _mit_vorgaengerzeit(
    get_tx: Callable[[str], dict],
    edge: FundingEdge,
    *,
    progress: ProgressCallback | None = None,
) -> FundingEdge:
    """
    Ergänzt die Blockzeit des Vorgängers, wenn sie noch fehlt.

    Esplora liefert den Vorgänger-Output inline in ``vin[].prevout`` — aber
    ohne dessen Blockzeit, und genau die ist das Anschaffungsdatum. Ein
    get_tx pro Eingang holt sie nach; das ist derselbe Preis, den der
    deferred-Pfad ohnehin zahlt, und get_tx ist gecacht.
    """
    if edge.prev_time_ts is not None:
        return edge
    if progress:
        progress(f"↻ Herkunft: Blockzeit zu {edge.prevout.txid[:16]}…")
    try:
        prev_tx = get_tx(edge.prevout.txid)
    except Exception:
        return edge
    zeit = _chain()._tx_block_time(prev_tx)
    if zeit is None:
        return edge
    return replace(edge, prev_time_ts=int(zeit))


def iter_trace_funding_inputs(
    get_tx: Callable[[str], dict],
    creator_txid: str,
    own_addresses: set[str],
    *,
    wallet: WalletContext | None = None,
    progress: ProgressCallback | None = None,
    alle_eigenen_inputs: bool = False,
) -> Iterator[FundingEdge | CoinbaseFunding | UnresolvedExternalBatch]:
    """
    Trace-Variante: Deferred-Inputs ohne inline-prevout werden bei kleinen
    Transaktionen (≤ FULL_RESOLUTION_INPUT_LIMIT Eingänge) vollständig
    aufgelöst. Bei größeren endet die Auflösung beim ersten internen Input;
    der Rest wird als UnresolvedExternalBatch gezählt.

    *alle_eigenen_inputs*: Opt-in für große Sammel-Txs — alle Eingänge
    auflösen und alle eigenen weitergeben. Fremde kommen als externe Kanten
    mit Blockzeit (keine Untergrenze durch Abbruch).

    Inline gelieferte Prevouts (Esplora) tragen keine Blockzeit. Bei kleinen
    Transaktionen (und bei *alle_eigenen_inputs*) wird sie für **externe**
    Eingänge nachgeholt; interne Eingänge verfolgt der Aufrufer weiter.
    """
    try:
        tx = get_tx(creator_txid)
    except Exception:
        return

    klein = len(tx.get("vin", [])) <= FULL_RESOLUTION_INPUT_LIMIT
    voll = klein or alle_eigenen_inputs

    deferred: list[dict] = []
    inline: list[FundingEdge] = []
    for vin in tx.get("vin", []):
        if vin.get("is_coinbase"):
            yield CoinbaseFunding(spending_txid=creator_txid)
            continue
        if "txid" not in vin or "vout" not in vin:
            continue
        prev_out = vin.get("prevout")
        if prev_out:
            try:
                inline.append(_funding_edge_from_vin(vin, prev_out, creator_txid))
            except Exception:
                continue
        else:
            deferred.append(vin)

    for edge in inline:
        if voll and not match_own_address(edge.addresses, own_addresses, wallet):
            edge = _mit_vorgaengerzeit(get_tx, edge, progress=progress)
        yield edge

    if not deferred:
        return

    # Vorgänger vorab parallel in den Cache holen. Die Auflösung darunter
    # bleibt Schritt für Schritt und liefert dieselbe Reihenfolge — sie
    # wartet nur nicht mehr auf jede einzelne Abfrage. Ohne Vorlader (Esplora,
    # BIP-158, Tor) passiert hier schlicht nichts.
    vorladen = getattr(get_tx, "prefetch", None)
    if vorladen is not None:
        try:
            vorladen([vin["txid"] for vin in deferred if vin.get("txid")])
        except Exception:
            pass

    if voll:
        # Alle Eingänge auflösen — bei Opt-in auch jenseits des 20er-Limits.
        for vin in deferred:
            try:
                prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
                if not prev_out:
                    continue
                edge = _funding_edge_from_vin(vin, prev_out, creator_txid)
                if not match_own_address(edge.addresses, own_addresses, wallet):
                    edge = _mit_vorgaengerzeit(get_tx, edge, progress=progress)
                yield edge
            except Exception:
                continue
        return

    external_before_internal: list[FundingEdge] = []
    for index, vin in enumerate(deferred):
        try:
            prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
            if not prev_out:
                continue
            edge = _funding_edge_from_vin(vin, prev_out, creator_txid)
        except Exception:
            continue

        if match_own_address(edge.addresses, own_addresses, wallet):
            yield edge
            remaining = len(deferred) - index - 1
            if remaining > 0:
                yield UnresolvedExternalBatch(
                    spending_txid=creator_txid,
                    input_count=remaining,
                )
            break

        external_before_internal.append(edge)

    for edge in external_before_internal:
        yield edge