"""Herkunft: Rückwärts-Walk und flacher Baum für die Oberfläche.

Der Walk (früher ``trace_engine``) und die UI-Form leben in diesem Modul.
Root-``trace_engine`` re-exportiert den Walk.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from core.utxo_report import (
    _extract_addresses,
    _extract_value_sats,
    _tx_block_time,
)

if TYPE_CHECKING:
    from core.wallet_context import WalletContext


MAX_TRACE_DEPTH = 20


class ProgressCallback(Protocol):
    def __call__(self, message: str) -> None: ...


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
    prev_out["_prev_tx_time_ts"] = _tx_block_time(prev_tx)
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


@dataclass(frozen=True)
class UnresolvedPrevout:
    """
    Ein Input, dessen Vorgänger-Tx nicht geladen werden konnte.

    Darf nicht still verworfen werden — sonst endet der Trace mit leeren
    ``sources`` und der UI-Text „Keine Zuflüsse ermittelbar“, obwohl die
    Erzeuger-Tx klar Inputs hat (extern / intern / noch zu laden).
    """

    spending_txid: str
    prev_txid: str
    prev_vout: int

    @property
    def key(self) -> str:
        return utxo_ref(self.prev_txid, self.prev_vout)


FundingInput = FundingEdge | CoinbaseFunding


def _funding_edge_from_vin(
    vin: dict,
    prev_out: dict,
    spending_txid: str,
) -> FundingEdge:
    return FundingEdge(
        spending_txid=spending_txid,
        prevout=PrevoutRef(txid=vin["txid"], vout=int(vin["vout"])),
        addresses=tuple(_extract_addresses(prev_out)),
        amount_sats=_extract_value_sats(prev_out),
        prev_time_ts=prev_out.get("_prev_tx_time_ts"),
    )


def _abbruch_durchreichen(exc: BaseException) -> None:
    """Job-Abbruch nicht in bare except schlucken."""
    from core.jobs import ist_abbruch

    if ist_abbruch(exc):
        raise


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
    except Exception as exc:
        _abbruch_durchreichen(exc)
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
        except Exception as exc:
            _abbruch_durchreichen(exc)
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


def match_own_address(
    addrs: tuple[str, ...] | list[str],
    own_addresses: set[str],
    wallet: WalletContext | None = None,
) -> str | None:
    """
    Erste passende eigene Adresse oder None.

    Nur O(1)-Lookups (Set / address_to_wallet). Kein ``resolve_address``:
    das leitet unbekannte Adressen über alle XPUBs ab und blockiert bei
    Fan-Outs mit Hunderten Outputs (Minuten, Abbruch greift nicht).
    Eigene Adressen müssen im Set bzw. Wallet-Kontext stehen (Cache-Seed).
    """
    for addr in addrs:
        if not addr:
            continue
        if addr in own_addresses:
            return addr
        if wallet is not None:
            # own_label = dict-get, keine HD-Suche
            label = getattr(wallet, "own_label", None)
            if callable(label) and label(addr):
                return addr
            mapping = getattr(wallet, "address_to_wallet", None)
            if isinstance(mapping, dict) and addr in mapping:
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
    except Exception as exc:
        _abbruch_durchreichen(exc)
        return edge
    zeit = _tx_block_time(prev_tx)
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
    own_inputs_only: bool = False,
    own_prevouts: set[str] | None = None,
) -> Iterator[
    FundingEdge | CoinbaseFunding | UnresolvedExternalBatch | UnresolvedPrevout
]:
    """
    Trace-Variante: Deferred-Inputs ohne inline-prevout werden bei kleinen
    Transaktionen (≤ FULL_RESOLUTION_INPUT_LIMIT Eingänge) vollständig
    aufgelöst. Bei größeren endet die Auflösung beim ersten internen Input;
    der Rest wird als UnresolvedExternalBatch gezählt.

    *alle_eigenen_inputs*: Opt-in für große Sammel-Txs — alle Eingänge
    auflösen und alle eigenen weitergeben. Fremde kommen als externe Kanten
    mit Blockzeit (keine Untergrenze durch Abbruch).

    *own_inputs_only*: CoinJoin-/Mix-Hybrid — nur eigene Inputs weitergeben;
    Fremde sind Rauschen (kein ``external``, kein ``UnresolvedExternalBatch``).
    Bekannte Outpoints aus dem Verlauf (*own_prevouts*) werden ohne
    Prevout-Resolve als eigen erkannt; Lücken werden gezielt nachgeladen.

    Inline gelieferte Prevouts (Esplora) tragen keine Blockzeit. Bei kleinen
    Transaktionen (und bei *alle_eigenen_inputs*) wird sie für **externe**
    Eingänge nachgeholt; interne Eingänge verfolgt der Aufrufer weiter.
    """
    try:
        tx = get_tx(creator_txid)
    except Exception as exc:
        _abbruch_durchreichen(exc)
        return

    known_own = {
        str(p).strip().lower() for p in (own_prevouts or ()) if p
    }

    def _is_own_edge(edge: FundingEdge) -> bool:
        if edge.prevout.key.lower() in known_own:
            return True
        return match_own_address(edge.addresses, own_addresses, wallet) is not None

    def _is_own_vin(vin: dict) -> bool | None:
        """True/False wenn klar, None wenn Prevout fehlt."""
        if "txid" not in vin or "vout" not in vin:
            return None
        key = utxo_ref(str(vin["txid"]), int(vin["vout"])).lower()
        if key in known_own:
            return True
        prev = vin.get("prevout")
        if not prev:
            return None
        addrs = tuple(_extract_addresses(prev))
        return match_own_address(addrs, own_addresses, wallet) is not None

    # CoinJoin: alle eigenen finden; Fremde nie als Zufluss ausgeben.
    if own_inputs_only:
        voll_cj = True
    else:
        voll_cj = False

    klein = len(tx.get("vin", [])) <= FULL_RESOLUTION_INPUT_LIMIT
    voll = klein or alle_eigenen_inputs or voll_cj

    deferred: list[dict] = []
    inline: list[FundingEdge] = []
    for vin in tx.get("vin", []):
        if vin.get("is_coinbase"):
            yield CoinbaseFunding(spending_txid=creator_txid)
            continue
        if "txid" not in vin or "vout" not in vin:
            continue
        if own_inputs_only:
            klar = _is_own_vin(vin)
            if klar is False:
                continue  # Fremd = Rauschen
            if klar is True and vin.get("prevout"):
                try:
                    edge = _funding_edge_from_vin(vin, vin["prevout"], creator_txid)
                except Exception as exc:
                    _abbruch_durchreichen(exc)
                    deferred.append(vin)
                    continue
                yield edge
                continue
            if klar is True and not vin.get("prevout"):
                deferred.append(vin)
                continue
            # Unklar: Prevout nachladen (Stufe 2).
            deferred.append(vin)
            continue
        prev_out = vin.get("prevout")
        if prev_out:
            try:
                inline.append(_funding_edge_from_vin(vin, prev_out, creator_txid))
            except Exception as exc:
                _abbruch_durchreichen(exc)
                continue
        else:
            deferred.append(vin)

    if not own_inputs_only:
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
        except Exception as exc:
            _abbruch_durchreichen(exc)

    def _unresolved_prev(vin: dict) -> UnresolvedPrevout:
        return UnresolvedPrevout(
            spending_txid=creator_txid,
            prev_txid=str(vin.get("txid") or ""),
            prev_vout=int(vin.get("vout") or 0),
        )

    if voll:
        # Alle Eingänge auflösen — bei Opt-in / CJ auch jenseits des 20er-Limits.
        for vin in deferred:
            try:
                if own_inputs_only:
                    key = utxo_ref(str(vin["txid"]), int(vin["vout"])).lower()
                    if key in known_own:
                        prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
                        if not prev_out:
                            yield _unresolved_prev(vin)
                            continue
                        yield _funding_edge_from_vin(vin, prev_out, creator_txid)
                        continue
                prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
                if not prev_out:
                    # CJ-Fremd ohne Prevout: Rauschen. Sonst Lücke melden.
                    if own_inputs_only:
                        continue
                    yield _unresolved_prev(vin)
                    continue
                edge = _funding_edge_from_vin(vin, prev_out, creator_txid)
                if own_inputs_only:
                    if _is_own_edge(edge):
                        yield edge
                    continue
                if not match_own_address(edge.addresses, own_addresses, wallet):
                    edge = _mit_vorgaengerzeit(get_tx, edge, progress=progress)
                yield edge
            except Exception as exc:
                _abbruch_durchreichen(exc)
                if own_inputs_only:
                    continue
                yield _unresolved_prev(vin)
                continue
        return

    external_before_internal: list[FundingEdge] = []
    for index, vin in enumerate(deferred):
        try:
            prev_out = resolve_vin_prevout(get_tx, vin, progress=progress)
            if not prev_out:
                yield _unresolved_prev(vin)
                continue
            edge = _funding_edge_from_vin(vin, prev_out, creator_txid)
        except Exception as exc:
            _abbruch_durchreichen(exc)
            yield _unresolved_prev(vin)
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


import labels
from core import utxo_report
from core import xpub_cache
from core import trace_cache

#: Typen, die ein Knoten annehmen kann.
KNOTEN_TYPEN = ("utxo", "internal", "external", "external_unresolved",
                "coinbase", "cycle", "error", "unknown", "tax_horizon")


def parse_ziel(eingabe: str) -> tuple[str, int] | None:
    """
    Erkennt 'txid:vout' oder eine reine TxID (dann vout 0).

    Adressen werden hier nicht behandelt — die Oberfläche löst sie vorher
    über die UTXO-Liste auf.
    """
    text = (eingabe or "").strip()
    if not text:
        return None
    if ":" in text:
        txid, _, vout = text.rpartition(":")
        try:
            return xpub_cache._normalize_txid(txid), int(vout)
        except ValueError:
            return None
    if len(text) == 64:
        try:
            int(text, 16)
        except ValueError:
            return None
        return xpub_cache._normalize_txid(text), 0
    return None


def _blockhoehe_fuer_utxo(
    txid: str,
    vout: int,
    cache_dir: Path | None,
    wallet,
) -> int | None:
    """Höhe aus UTXO-Cache, falls der Scan sie schon kennt."""
    import json
    from pathlib import Path as _Path

    key_txid = xpub_cache._normalize_txid(txid)
    ziel_vout = int(vout)
    root = _Path(cache_dir) if cache_dir else xpub_cache.UTXO_CACHE_DIR
    if not root.is_dir():
        return None

    kandidaten: list[list] = []
    xpubs = list(getattr(wallet, "xpubs", None) or []) if wallet is not None else []
    for xpub in xpubs:
        try:
            liste = xpub_cache.load_xpub_utxo_cache(xpub, root)
        except Exception:
            liste = None
        if liste:
            kandidaten.append(liste)
    if not kandidaten:
        for pfad in root.glob("*.json"):
            if (
                pfad.name.endswith("_alter.json")
                or "external" in pfad.name
                or "verlauf" in pfad.name
            ):
                continue
            try:
                data = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            utxos = data.get("utxos") if isinstance(data, dict) else None
            if isinstance(utxos, list):
                kandidaten.append(utxos)

    for utxos in kandidaten:
        for u in utxos:
            if xpub_cache._normalize_txid(str(u.get("txid") or "")) != key_txid:
                continue
            try:
                if int(u.get("vout", -1)) != ziel_vout:
                    continue
            except (TypeError, ValueError):
                continue
            status = u.get("status") or {}
            raw = status.get("block_height", u.get("height"))
            try:
                h = int(raw)
            except (TypeError, ValueError):
                return None
            return h if h > 0 else None
    return None


def erklaere_fehler(roh: str) -> str:
    """
    Übersetzt Meldungen der Datenquelle in verständlichen Text.

    Ein durchgereichtes ``DaemonError({'code': -5, …})`` sagt niemandem, was zu
    tun ist. Unbekannte Meldungen bleiben unverändert — lieber roh als falsch
    gedeutet.
    """
    text = str(roh or "").strip()
    if not text:
        return "Unbekannter Fehler."
    klein = text.lower()

    if "peer hat die transaktion nicht" in klein:
        return (
            "Der P2P-Peer kennt die Transaktion nicht als Einzelabruf "
            "(typisch ohne Tx-Index). Mit bekannter Blockhöhe wird der ganze "
            "Block geladen; sonst Core mit -txindex=1 oder ein Electrum-Server."
        )
    if "nicht auflösbar ohne electrs" in klein or "keine blockhöhe bekannt" in klein:
        return (
            "Ohne Electrs fehlt die Höhe dieser Vorgänger-Tx. Core mit "
            "-txindex=1 eintragen, oder einen Electrum-Server nutzen — ein "
            "Blindflug über die ganze Kette ist absichtlich nicht eingebaut."
        )
    if "no such mempool or blockchain transaction" in klein:
        return (
            "Die Datenquelle kennt diese Transaktion nicht. Entweder ist die "
            "TxID falsch, oder der Node hat den Block noch nicht — bei einem "
            "frisch synchronisierten Node kann das vorkommen."
        )
    if "vout" in klein and "ungültig" in klein:
        return (
            "Diesen Ausgang gibt es in der Transaktion nicht. Stimmt die "
            "Nummer hinter dem Doppelpunkt?"
        )
    if "timed out" in klein or "timeout" in klein:
        return (
            "Die Datenquelle hat nicht rechtzeitig geantwortet. Bei "
            "Tor-Verbindungen kommt das vor — noch einmal versuchen."
        )
    if "connection refused" in klein or "nicht erreichbar" in klein:
        return (
            "Keine Verbindung zur Datenquelle. Läuft der Node, und stimmen "
            "Host und Port in den Einstellungen?"
        )
    if "wrong version number" in klein:
        return (
            "TLS-Handshake fehlgeschlagen — der Port spricht vermutlich kein "
            "SSL. In den Einstellungen FULCRUM_SSL abschalten."
        )
    return text


def _format_time_ts(ts) -> str:
    """Unix-Zeit → Anzeige wie bei Tx-Zeiten (ohne Block-Präfix)."""
    try:
        wert = int(ts)
    except (TypeError, ValueError):
        return ""
    if wert <= 0:
        return ""
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(wert, UTC).strftime("%d.%m.%Y %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _setze_externe_zeit(knoten: dict, quelle: dict | None = None) -> None:
    """
    Füllt time_label / block_time am UI-Knoten aus Analyse-Source oder
    bereits gesetzten Feldern (Cache-Nachzug).
    """
    quelle = quelle or {}
    if knoten.get("time_label") and knoten.get("block_time"):
        return
    ts = knoten.get("block_time") or knoten.get("time_ts") or quelle.get("time_ts")
    label = (knoten.get("time_label") or quelle.get("time") or "").strip()
    if not label and ts:
        label = _format_time_ts(ts)
    if not label and not ts:
        return
    if label:
        knoten["time_label"] = label
    try:
        if ts is not None and int(ts) > 0:
            knoten["block_time"] = int(ts)
            knoten["time_ts"] = int(ts)
    except (TypeError, ValueError):
        pass


def _anreichere_externe_zeiten(
    knoten_liste: list,
    immutable_cache_dir: Path | str | None = None,
) -> None:
    """
    Nachträglich Zeiten an externe Blätter hängen (alte Caches ohne time_label).

    Reihenfolge: vorhandenes time_ts → Tx-Cache zum from_utxo.
    """
    if not knoten_liste:
        return
    immutable: Path | None = None
    if immutable_cache_dir:
        try:
            immutable = Path(immutable_cache_dir)
        except TypeError:
            immutable = None

    def _aus_tx_cache(from_utxo: str) -> tuple[int | None, str]:
        if not immutable or not from_utxo or ":" not in str(from_utxo):
            return None, ""
        try:
            txid, _vout = str(from_utxo).rsplit(":", 1)
            txid = xpub_cache._normalize_txid(txid)
        except Exception:
            return None, ""
        pfad = immutable / "tx" / f"{txid}.json"
        if not pfad.is_file():
            return None, ""
        try:
            roh = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None, ""
        if not isinstance(roh, dict):
            return None, ""
        # Flatfile oft {txid, source, tx: {...}} — Zeit sitzt im inneren tx.
        tx = roh.get("tx") if isinstance(roh.get("tx"), dict) else roh
        if not isinstance(tx, dict):
            return None, ""
        ts = utxo_report._tx_block_time(tx)
        if ts is None:
            return None, ""
        return int(ts), utxo_report._format_tx_time(tx)

    def _walk(knoten: dict) -> None:
        if not isinstance(knoten, dict):
            return
        if knoten.get("type") == "external":
            if not (knoten.get("time_label") and knoten.get("block_time")):
                _setze_externe_zeit(knoten)
            if not knoten.get("time_label") and not knoten.get("block_time"):
                ts, label = _aus_tx_cache(knoten.get("from_utxo") or "")
                if ts or label:
                    if label:
                        knoten["time_label"] = label
                    if ts:
                        knoten["block_time"] = ts
                        knoten["time_ts"] = ts
        for kind in knoten.get("children") or []:
            _walk(kind)

    for knoten in knoten_liste:
        _walk(knoten)


def _kind_knoten(quelle: dict, wallet, pfad: str, tiefe: int) -> dict:
    """Baut einen Knoten aus einem Quellen-Eintrag des Analysebaums."""
    typ = quelle.get("type", "unknown")
    adresse = quelle.get("address", "")

    knoten = {
        "id": pfad,
        "type": typ,
        "depth": tiefe,
        "address": adresse,
        "amount_sats": int(quelle.get("amount_sats", 0) or 0),
        "from_utxo": quelle.get("from_utxo", ""),
        "wallet": None,
        "time_label": "",
        "block_height": None,
        "children": [],
        "expandable": False,
        "note": "",
        # Nur externe Enden werden beschriftet — bei eigenen Adressen wäre die
        # Frage sinnlos. Der Schlüssel ist trotzdem immer da, damit sich
        # „nichts gefunden" nicht von „gar nicht nachgeschaut" unterscheidet.
        "label": None,
    }

    if typ == "internal":
        knoten["wallet"] = wallet.resolve_address(adresse) if wallet else None
        unterbaum = quelle.get("trace")
        if unterbaum:
            knoten["time_label"] = unterbaum.get("time", "")
            knoten["txid"] = unterbaum.get("txid", "")
            knoten["vout"] = unterbaum.get("vout")
            # Soft-Label der Erzeuger-Tx (CoinJoin-Art am eigenen Hop).
            if unterbaum.get("tx_class"):
                knoten["tx_class"] = unterbaum.get("tx_class")
                knoten["tx_class_label"] = unterbaum.get("tx_class_label") or ""
                knoten["tx_class_label_en"] = unterbaum.get("tx_class_label_en") or ""
                if knoten["tx_class_label"]:
                    knoten["note"] = knoten["tx_class_label"]
            quellen = unterbaum.get("sources") or []
            if unterbaum.get("tax_horizon") and not quellen:
                # Steuer-Frühabbruch: Blatt bis Stichtag/Haltefrist-Anfang.
                knoten["type"] = "tax_horizon"
                knoten["tax_horizon"] = True
                knoten["children"] = []
                knoten["note"] = (
                    "Für Steuerjahr ausreichend (vor Stichtag bzw. "
                    "Haltefrist-Anfang). Herkunft tracen führt bis "
                    "extern/Coinbase weiter."
                )
                if unterbaum.get("time_ts"):
                    knoten["block_time"] = int(unterbaum["time_ts"])
            elif unterbaum.get("exchange_stop"):
                # Börsen-Grenze: kein Walk hinter Ein-/Auszahlung.
                knoten["exchange_stop"] = True
                knoten["label"] = (
                    unterbaum.get("exchange_label")
                    or labels.beschrifte(
                        adresse or "",
                        txid=str(unterbaum.get("txid") or ""),
                    )
                )
                knoten["note"] = (
                    "Börse — Herkunft endet an der Ein-/Auszahlung "
                    "(keine Hops darüber hinaus)."
                )
                if quellen:
                    knoten["children"] = _quellen_zu_knoten(
                        unterbaum, wallet, pfad, tiefe + 1
                    )
                else:
                    knoten["children"] = []
                knoten["expandable"] = bool(knoten["children"])
            elif quellen:
                knoten["children"] = _quellen_zu_knoten(
                    unterbaum, wallet, pfad, tiefe + 1
                )
            elif unterbaum.get("coinjoin_noise_skipped") and unterbaum.get("tx_class"):
                # CJ ohne aufgelöste eigene Ins: Soft-Label reicht als Blatt —
                # absichtlicher Peer-Skip ist keine Herkunftslücke.
                knoten["children"] = []
                knoten["coinjoin_noise_skipped"] = True
            else:
                # cycle/error/unknown ohne Quellen: als Blatt sichtbar machen,
                # sonst wirkt der interne Knoten fälschlich „fertig grün“.
                marker = unterbaum.get("type") or "unknown"
                if marker == "utxo":
                    marker = "unknown"
                if unterbaum.get("tax_horizon"):
                    marker = "tax_horizon"
                knoten["children"] = [{
                    "id": f"{pfad}.0",
                    "type": marker,
                    "depth": tiefe + 1,
                    "address": "",
                    "amount_sats": 0,
                    "from_utxo": unterbaum.get("utxo") or quelle.get("from_utxo", ""),
                    "wallet": None,
                    "time_label": unterbaum.get("time") or "",
                    "block_height": None,
                    "block_time": unterbaum.get("time_ts"),
                    "tax_horizon": bool(unterbaum.get("tax_horizon")),
                    "children": [],
                    "expandable": False,
                    "note": (
                        unterbaum.get("error")
                        or (
                            "Für Steuerjahr ausreichend (vor Stichtag/Haltefrist)."
                            if marker == "tax_horizon"
                            else (
                                "Zyklus oder Maximaltiefe — Herkunft hier abgebrochen."
                                if marker == "cycle"
                                else "Herkunft dieses Zweigs konnte nicht ermittelt werden."
                            )
                        )
                    ),
                    "label": None,
                }]
            knoten["expandable"] = bool(knoten["children"])
    elif typ == "tax_horizon":
        knoten["tax_horizon"] = True
        knoten["note"] = (
            "Für Steuerjahr ausreichend (vor Stichtag bzw. "
            "Haltefrist-Anfang)."
        )
        _setze_externe_zeit(knoten, quelle)
    elif typ == "external":
        if quelle.get("exchange_stop"):
            knoten["exchange_stop"] = True
            knoten["note"] = (
                "Börse — Herkunft endet an der Ein-/Auszahlung "
                "(keine Hops darüber hinaus)."
            )
        else:
            knoten["note"] = "Externe Zweige werden nicht weiterverfolgt."
        # Genau hier endet die Verfolgung — und genau hier ist die Frage
        # „von wem kam das eigentlich" am interessantesten.
        # Börsen-CSV: Adresse oder TxID des Prevouts (Ein-/Auszahlung).
        from_utxo = str(quelle.get("from_utxo") or "")
        prev_txid = from_utxo.rsplit(":", 1)[0] if ":" in from_utxo else ""
        knoten["label"] = labels.beschrifte(adresse, txid=prev_txid)
        # Blockzeit des Prevouts: wann diese Sats die fremde Adresse erreichten
        # (bzw. der Funding-Output bestätigt wurde). analyze legt time_ts ab;
        # ohne das blieb die UI-Zeile ohne Datum, obwohl die jüngsten sats
        # genau aus diesen Zeiten berechnet werden.
        _setze_externe_zeit(knoten, quelle)
    elif typ == "external_unresolved":
        anzahl = int(quelle.get("input_count", 0) or 0)
        knoten["input_count"] = anzahl
        knoten["note"] = (
            f"{anzahl} weitere Eingänge wurden nicht aufgelöst — nach dem "
            "ersten eigenen Eingang bricht die Auflösung ab, um bei "
            "Sammel-Transaktionen nicht hunderte Abrufe auszulösen. "
            "Beträge dieser Eingänge fehlen."
        )
    elif typ == "coinbase":
        knoten["note"] = "Frisch geschürfte Sats — hier endet jede Herkunft."
    elif typ == "error":
        knoten["note"] = (
            quelle.get("error")
            or "Herkunft dieses Zweigs konnte nicht ermittelt werden."
        )
        if quelle.get("input_count"):
            knoten["input_count"] = int(quelle.get("input_count") or 0)
    elif typ == "unknown":
        knoten["note"] = (
            quelle.get("error")
            or "Herkunft unvollständig — kein externes oder Coinbase-Ende."
        )

    return knoten


def _quellen_zu_knoten(baum: dict, wallet, pfad: str, tiefe: int) -> list[dict]:
    kinder = []
    for nummer, quelle in enumerate(baum.get("sources", [])):
        kinder.append(
            _kind_knoten(quelle, wallet, f"{pfad}.{nummer}", tiefe)
        )
    return kinder


def _summen(knoten: list[dict]) -> dict:
    """Zählt Zuflüsse nach Art über den gesamten Baum."""
    ergebnis = {
        "internal_sats": 0,
        "external_sats": 0,
        "external_count": 0,
        "unresolved_inputs": 0,
        "coinbase": False,
        "max_depth": 0,
        "node_count": 0,
    }

    stapel = list(knoten)
    while stapel:
        aktuell = stapel.pop()
        ergebnis["node_count"] += 1
        ergebnis["max_depth"] = max(ergebnis["max_depth"], aktuell["depth"])
        typ = aktuell["type"]
        if typ == "internal":
            ergebnis["internal_sats"] += aktuell["amount_sats"]
        elif typ == "external":
            ergebnis["external_sats"] += aktuell["amount_sats"]
            ergebnis["external_count"] += 1
        elif typ == "external_unresolved":
            ergebnis["unresolved_inputs"] += aktuell.get("input_count", 0)
        elif typ == "coinbase":
            ergebnis["coinbase"] = True
        stapel.extend(aktuell["children"])
    return ergebnis


def interne_vorgaenger_anzahl(baum: dict | None) -> int:
    """
    Anzahl eindeutiger interner Creator-Txs im flachen UI-Baum.

    Entspricht grob der CLI-Heuristik für transaktionsorientierte Folgeanalyse
    (≥2 → Verzweigung lohnt sich oft).
    """
    if not baum:
        return 0
    txids: set[str] = set()
    stapel = list(baum.get("children") or [])
    while stapel:
        knoten = stapel.pop()
        if not isinstance(knoten, dict):
            continue
        if knoten.get("type") == "internal":
            tid = str(knoten.get("txid") or "").strip().lower()
            if tid:
                txids.add(tid)
            # from_utxo „txid:vout“ als Fallback
            roh = str(knoten.get("from_utxo") or "")
            if ":" in roh:
                txids.add(roh.rsplit(":", 1)[0].strip().lower())
        stapel.extend(knoten.get("children") or [])
    return len(txids)


def folge_meta(baum: dict | None) -> dict:
    """Signale für Opt-in-Folgeaktionen in der Oberfläche."""
    n = interne_vorgaenger_anzahl(baum)
    summary = (baum or {}).get("summary") or {}
    unresolved = int(summary.get("unresolved_inputs") or 0)
    # Immer an den Blättern messen — ältere Caches speicherten fälschlich
    # verfolgt_vollstaendig=True, sobald irgendwo external_count > 0 war.
    voll = trace_cache.baum_ist_vollstaendig(baum) if baum else False
    # „Done“ nur wenn wirklich jedes Blatt rot/lila ist — sonst bleibt der
    # Entwirren-Knopf sichtbar, auch nach einem abgebrochenen/lückigen Lauf.
    done_flag = bool((baum or {}).get("followup_tx_oriented_done")) and voll
    return {
        "internal_predecessor_count": n,
        "followup_tx_oriented_suggested": n >= 2 or (
            bool(baum and baum.get("found")) and not voll
        ),
        "followup_resolve_unresolved_suggested": unresolved > 0 or (
            bool(baum and baum.get("found")) and not voll
        ),
        "followup_tx_oriented_done": done_flag,
        "verfolgt_vollstaendig": voll,
        # Explizit für UI/Liste: Abbruch, fehlende Prevouts, Lücken, …
        "unvollstaendig": bool(baum and baum.get("found") and not voll),
    }


def trace_utxo(
    get_tx,
    txid: str,
    vout: int,
    own_addresses: set,
    *,
    wallet=None,
    cache_dir: Path | None = None,
    immutable_cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress=None,
    resolve_bundled: bool = False,
    merke_tx_oriented_done: bool = False,
    stop_before_ts: int | None = None,
    resume_origin: dict | None = None,
) -> dict:
    """
    Führt die Herkunftsanalyse durch und liefert sie als Baum aus Wörterbüchern.

    Das Ergebnis wird im Ingress-Cache festgehalten — ohne das sähe die
    Steuerjahr-Auswertung nichts davon. *immutable_cache_dir* benennt dessen
    Ziel; fehlt es, wird es aus *cache_dir* abgeleitet.

    *progress* ist ein Callable[[str], None] — dieselbe Form wie
    ProgressCallback. Wird es von einem Job durchgereicht, wirkt
    ein Abbruch an jeder Fortschrittsmeldung.

    *resolve_bundled*: große Sammel-Txs vollständig auflösen (alle eigenen
    Inputs), Opt-in aus der GUI.

    *merke_tx_oriented_done*: nach erfolgreicher Folgeanalyse am Baum
    speichern — UI zeigt dann Hinweis statt Knopf.

    *stop_before_ts*: Steuer-Horizont — Trace endet an Hops vor Stichtag/
    Haltefrist-Anfang (siehe ``utxo_origin.trace_utxo_origin``).

    *resume_origin*: gespeicherter Analyse-Rohbaum. Bei vollem Lauf werden
    Lücken nachgezogen (tax_horizon, error-Prevouts, unvollständige interne
    Zweige) — fertige Äste bleiben erhalten (kein Komplett-Neulauf).
    """
    from core import utxo_ingress_report, utxo_origin

    fortschritt = _FortschrittsAdapter(progress) if progress else None
    txid_n = xpub_cache._normalize_txid(txid)
    vout_n = int(vout)

    # Bekannte Scan-Höhe → P2P kann bei getdata-notfound den Block holen.
    hoehe = _blockhoehe_fuer_utxo(txid_n, vout_n, cache_dir, wallet)
    if hoehe:
        try:
            from core.bip158_wallet import note_tx_height

            note_tx_height(txid_n, hoehe)
        except Exception:
            pass

    if (
        resume_origin
        and isinstance(resume_origin, dict)
        and stop_before_ts is None
        and (
            utxo_origin._hat_tax_horizon(resume_origin)
            or utxo_origin._origin_hat_luecken(resume_origin)
        )
        and utxo_origin.hat_brauchbaren_teilfortschritt(resume_origin)
    ):
        if progress:
            try:
                if utxo_origin._hat_tax_horizon(resume_origin):
                    progress("Setze Steuer-Horizont bis extern/Coinbase fort…")
                else:
                    progress("Setze unvollständige Herkunft fort (Teilbaum)…")
            except Exception:
                pass
        roh = utxo_origin.vertiefe_herkunft_luecken(
            resume_origin,
            get_tx,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=fortschritt,
            alle_eigenen_inputs=bool(resolve_bundled),
        )
    else:
        roh = utxo_origin.trace_utxo_origin(
            get_tx,
            txid_n,
            vout_n,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=fortschritt,
            alle_eigenen_inputs=bool(resolve_bundled),
            stop_before_ts=stop_before_ts,
        )

    if roh is None:
        return {
            "found": False,
            "error": "Keine Herkunft ermittelbar.",
            "root": None,
            "children": [],
            "summary": {},
        }

    if roh.get("type") == "error":
        return {
            "found": False,
            "error": erklaere_fehler(roh.get("error")),
            "error_raw": str(roh.get("error", "")),
            "root": {
                "txid": xpub_cache._normalize_txid(txid),
                "vout": int(vout),
                "utxo": roh.get("utxo", ""),
            },
            "children": [],
            "summary": {},
        }

    kinder = _quellen_zu_knoten(roh, wallet, "0", 1)
    # Wurzel selbst ist Steuer-Horizont (Output alt genug) → künstliches Blatt.
    if roh.get("tax_horizon") and not kinder:
        kinder = [{
            "id": "0.0",
            "type": "tax_horizon",
            "depth": 1,
            "address": (roh.get("addresses") or [""])[0] if roh.get("addresses") else "",
            "amount_sats": int(roh.get("amount_sats", 0) or 0),
            "from_utxo": f"{roh.get('txid', '')}:{int(roh.get('vout', 0) or 0)}",
            "wallet": None,
            "time_label": roh.get("time") or "",
            "block_height": None,
            "block_time": roh.get("time_ts"),
            "tax_horizon": True,
            "children": [],
            "expandable": False,
            "note": (
                "Für Steuerjahr ausreichend (vor Stichtag bzw. "
                "Haltefrist-Anfang). Herkunft tracen führt bis "
                "extern/Coinbase weiter."
            ),
            "label": None,
        }]
    _anreichere_externe_zeiten(kinder, immutable_cache_dir)
    adressen = roh.get("addresses") or []
    wurzel_adresse = adressen[0] if adressen else ""

    # Ergebnis festhalten, sonst sieht das Steuerjahr nichts davon: Es liest
    # das Anschaffungsdatum allein aus dem Ingress-Cache und weist die Zeile
    # sonst weiter als "nur Output-Datum" aus. Dieselbe Funktion benutzt das
    # CLI — die Einträge beider Wege sind damit identisch.
    utxo_ingress_report.persist_utxo_ingress(
        roh,
        txid=roh.get("txid") or xpub_cache._normalize_txid(txid),
        vout=int(roh.get("vout", vout) or 0),
        address=wurzel_adresse,
        amount_sats=int(roh.get("amount_sats", 0) or 0),
        wallet=wallet,
        cache_dir=cache_dir,
        immutable_cache_dir=immutable_cache_dir,
    )

    summary = _summen(kinder)
    baum_probe = {
        "found": True,
        "summary": summary,
        "children": kinder,
        "tx_class": roh.get("tx_class"),
        "coinjoin_noise_skipped": bool(roh.get("coinjoin_noise_skipped")),
        "tax_horizon": bool(roh.get("tax_horizon")),
    }
    voll = trace_cache.baum_ist_vollstaendig(baum_probe)
    steuer_ok = trace_cache.baum_ist_steuer_ausreichend(baum_probe)
    juengste = None
    if voll or steuer_ok:
        extern = utxo_ingress_report._youngest_external_ingress(roh)
        wallet_eingang = utxo_ingress_report._youngest_wallet_ingress(roh, wallet)
        horizon = utxo_ingress_report._youngest_tax_horizon(roh)
        if extern and extern.get("time_ts"):
            juengste = int(extern["time_ts"])
        elif wallet_eingang and wallet_eingang.get("time_ts"):
            juengste = int(wallet_eingang["time_ts"])
        elif horizon and horizon.get("time_ts"):
            juengste = int(horizon["time_ts"])

    root = {
        "id": "0",
        "txid": roh.get("txid", ""),
        "vout": roh.get("vout", 0),
        "address": wurzel_adresse,
        "wallet": wallet.resolve_address(wurzel_adresse) if wallet else None,
        "amount_sats": int(roh.get("amount_sats", 0) or 0),
        "time_label": roh.get("time", ""),
        "type": roh.get("type", "utxo"),
        "label": None,
    }
    # Börsen-CSV: Empfangs-Tx als Auszahlung der Börse markieren (wenn gelistet).
    root["label"] = labels.beschrifte(
        wurzel_adresse or "", txid=str(roh.get("txid") or ""),
    )
    if roh.get("tax_horizon"):
        root["tax_horizon"] = True
    if roh.get("tx_class"):
        root["tx_class"] = roh.get("tx_class")
        root["tx_class_label"] = roh.get("tx_class_label") or ""
        root["tx_class_label_en"] = roh.get("tx_class_label_en") or ""
        root["note"] = root["tx_class_label"]
        # Exchange-Batch: Soft-Label anhand bekannter Börsen in den Kindern
        # konkretisieren (Prevouts oft erst im Baum gelabelt).
        if str(root.get("tx_class") or "") == "exchange_batch":
            try:
                from core.trace_cache import boerse_namen_im_baum
                from core.tx_classify import soft_label_exchange_batch

                probe = {"root": root, "children": kinder}
                namen = boerse_namen_im_baum(probe)
                if not namen:
                    namen = boerse_namen_im_baum({"root": roh, "children": roh.get("sources") or []})
                if namen:
                    root["tx_class_label"] = soft_label_exchange_batch(namen, lang="de")
                    root["tx_class_label_en"] = soft_label_exchange_batch(namen, lang="en")
                    root["note"] = root["tx_class_label"]
                    root["boerse_namen"] = namen
            except Exception:
                pass
    if roh.get("exchange_stop"):
        root["exchange_stop"] = True
        if roh.get("exchange_label"):
            root["label"] = roh.get("exchange_label")
        root["note"] = (
            "Börse — Herkunft endet an der Ein-/Auszahlung "
            "(keine Hops darüber hinaus)."
        )

    ergebnis = {
        "found": True,
        "error": "",
        "root": root,
        "children": kinder,
        "summary": summary,
        "verfolgt_vollstaendig": voll,
        "steuer_ausreichend": steuer_ok,
        "juengste_sats_ts": juengste,
        "max_trace_depth": utxo_origin.MAX_TRACE_DEPTH,
        "tx_class": roh.get("tx_class"),
        "tx_class_label": roh.get("tx_class_label") or "",
        # Rohbaum für späteren Voll-Lauf (nur Horizont nachziehen).
        "origin_tree": roh,
    }
    ergebnis.update(folge_meta(ergebnis))
    # Done nur bei echtem Blatt-Ende (external/coinbase). Sonst bleibt
    # Entwirren anwählbar und behauptet nicht fälschlich „Lücken geschlossen“.
    if merke_tx_oriented_done and voll:
        ergebnis["followup_tx_oriented_done"] = True
    else:
        ergebnis["followup_tx_oriented_done"] = False
    # Meta erneut, damit suggested/done zur finalen Vollständigkeit passen.
    ergebnis.update(folge_meta(ergebnis))

    # Den Baum selbst ablegen, damit ihn der nächste Seitenaufruf ohne Job und
    # ohne Node-Verbindung zeigen kann. Die Adressmenge wandert als
    # Fingerabdruck mit: Ob ein Zweig intern oder extern ist, hängt an ihr.
    trace_cache.speichern(
        ergebnis["root"]["txid"] or xpub_cache._normalize_txid(txid),
        int(ergebnis["root"]["vout"] or 0),
        ergebnis,
        _immutable_ziel(cache_dir, immutable_cache_dir),
        own_addresses,
    )

    return ergebnis


def _immutable_ziel(cache_dir, immutable_cache_dir) -> Path | None:
    """
    Wohin unveränderliche Daten gehören.

    Ausdrücklich benanntes Verzeichnis gewinnt; sonst das neben dem
    UTXO-Cache — so macht es auch das CLI. Ohne beides: nirgendwohin.
    """
    if immutable_cache_dir:
        return Path(immutable_cache_dir)
    if cache_dir:
        return xpub_cache.resolve_immutable_cache_dir(utxo_cache_dir=cache_dir)
    return None


class _FortschrittsAdapter:
    """
    utxo_origin.trace_utxo_origin erwartet ein Objekt mit .update(text);
    core.jobs liefert eine schlichte Funktion. Dieser Adapter verbindet beide.
    """

    def __init__(self, callback):
        self._callback = callback

    def update(self, message: str) -> None:
        self._callback(message)

    def clear(self) -> None:
        pass
