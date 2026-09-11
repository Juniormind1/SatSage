"""
Klassifikation von Transaktionen für Herkunft (CoinJoin vs. Fan-Out / PayJoin / Exchange).

Eigentum zuerst, dann Formheuristik. Soft-Labels („Wahrscheinlich …“) —
keine forensische Sicherheit.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

from trace_engine import (
    ProgressCallback,
    match_own_address,
    resolve_vin_prevout,
    utxo_ref,
)

if TYPE_CHECKING:
    from main import WalletContext

#: CoinJoin-Untertypen und generischer Fallback — Own-only-Walk.
COINJOIN_KINDS = frozenset({
    "wasabi_classic",
    "wabisabi",
    "whirlpool",
    "joinmarket",
    "coinjoin",
})

#: Richtwerte PayJoin (BIP78/77): übersichtlich, wenige Fremd-Ins.
_PAYJOIN_MAX_INS = 8
_PAYJOIN_MAX_FOREIGN = 2

#: Ab dieser Input-Zahl gilt eine n:m-Tx als „groß“ (Wasabi/WabiSabi).
_LARGE_NM_MIN_INS = 15
_LARGE_NM_MIN_OUTS = 10

#: Whirlpool: starres 5×5 mit gleicher Denomination.
_WHIRLPOOL_SIZE = 5

#: Bisq-Payout: Seller bekommt Deposit ``s``, Buyer ``t+s``.
#: ``s/(t+s)`` bei Deposit 15–50 % der Trade-Summe ≈ 0,13–0,33 — etwas Spiel.
_BISQ_PAYOUT_RATIO_MIN = 0.10
_BISQ_PAYOUT_RATIO_MAX = 0.40

#: Bisq-Deposit: OP_RETURN trägt typisch den Contract-Hash (~20 Byte).
_BISQ_OP_RETURN_DATA_MIN = 16
_BISQ_OP_RETURN_DATA_MAX = 32


def _chain():
    import main

    return main


@dataclass(frozen=True)
class TxOwnership:
    """Eigentum aller bekannten vin/vout — Unbekanntes zählt nicht als eigen."""

    input_count: int
    output_count: int
    own_input_indices: tuple[int, ...]
    foreign_input_indices: tuple[int, ...]
    unknown_input_indices: tuple[int, ...]
    own_output_indices: tuple[int, ...]
    foreign_output_indices: tuple[int, ...]

    @property
    def own_input_count(self) -> int:
        return len(self.own_input_indices)

    @property
    def foreign_input_count(self) -> int:
        return len(self.foreign_input_indices)

    @property
    def unknown_input_count(self) -> int:
        return len(self.unknown_input_indices)

    @property
    def own_output_count(self) -> int:
        return len(self.own_output_indices)

    @property
    def ownership_complete(self) -> bool:
        return self.unknown_input_count == 0


@dataclass(frozen=True)
class TxClassification:
    kind: str
    soft_label_de: str
    soft_label_en: str
    walk_own_inputs_only: bool
    treat_foreign_as_noise: bool
    ownership: TxOwnership | None = None

    @property
    def is_coinjoin(self) -> bool:
        return self.kind in COINJOIN_KINDS


_LABELS: dict[str, tuple[str, str]] = {
    "wasabi_classic": (
        "Wahrscheinlich Wasabi-CoinJoin",
        "Likely Wasabi CoinJoin",
    ),
    "wabisabi": (
        "Wahrscheinlich WabiSabi-CoinJoin",
        "Likely WabiSabi CoinJoin",
    ),
    "whirlpool": (
        "Wahrscheinlich Whirlpool-CoinJoin",
        "Likely Whirlpool CoinJoin",
    ),
    "joinmarket": (
        "Wahrscheinlich JoinMarket",
        "Likely JoinMarket",
    ),
    "coinjoin": (
        "Wahrscheinlich CoinJoin/Mix",
        "Likely CoinJoin/Mix",
    ),
    "payjoin": (
        "Wahrscheinlich PayJoin",
        "Likely PayJoin",
    ),
    "fan_out_own": (
        "Wahrscheinlich eigene Auszahlung (Fan-Out)",
        "Likely own fan-out spend",
    ),
    "exchange_batch": (
        "Wahrscheinlich Batch-Auszahlung von Exchange",
        "Likely exchange batch payout",
    ),
    "bisq_payout": (
        "Wahrscheinlich Bisq-Auszahlung",
        "Likely Bisq payout",
    ),
    "bisq_deposit": (
        "Wahrscheinlich Bisq-Deposit (Escrow)",
        "Likely Bisq deposit (escrow)",
    ),
    "unknown": ("", ""),
}


def soft_label(kind: str, *, lang: str = "de") -> str:
    de, en = _LABELS.get(kind, ("", ""))
    return de if lang == "de" else en


def _classification(kind: str, ownership: TxOwnership | None) -> TxClassification:
    de, en = _LABELS.get(kind, ("", ""))
    cj = kind in COINJOIN_KINDS
    return TxClassification(
        kind=kind,
        soft_label_de=de,
        soft_label_en=en,
        walk_own_inputs_only=cj,
        treat_foreign_as_noise=cj,
        ownership=ownership,
    )


def _output_values_sats(tx: dict) -> list[int]:
    chain = _chain()
    return [chain._extract_value_sats(v) for v in tx.get("vout", [])]


def _equal_output_stats(values: list[int]) -> tuple[int, int, int]:
    """
    Größte Gleichbetrags-Gruppe unter den Outputs.

    Rückgabe: (häufigster_betrag_sats, anzahl_dieser_gruppe, anzahl_anderer).
    """
    if not values:
        return 0, 0, 0
    counts = Counter(values)
    betrag, n = counts.most_common(1)[0]
    andere = len(values) - n
    return betrag, n, andere


def analyze_ownership(
    tx: dict,
    own_addresses: set[str],
    *,
    wallet: WalletContext | None = None,
    get_tx: Callable[[str], dict] | None = None,
    own_prevouts: Collection[str] | None = None,
    progress: ProgressCallback | None = None,
) -> TxOwnership:
    """
    Klärt Eigentum aller Ins/Outs.

    *own_prevouts*: Outpoints ``txid:vout``, die laut Verlauf in diese Tx
    fließen (``spent_txid``) — Stufe‑1 ohne Prevout-Resolve.
    Unbekannte Inputs bleiben ``unknown`` (kein Exchange-/Fan-Out-Label).
    """
    chain = _chain()
    vins = list(tx.get("vin") or [])
    vouts = list(tx.get("vout") or [])
    known = {str(p).strip().lower() for p in (own_prevouts or ()) if p}

    own_ins: list[int] = []
    foreign_ins: list[int] = []
    unknown_ins: list[int] = []

    for i, vin in enumerate(vins):
        if vin.get("is_coinbase") or "txid" not in vin or "vout" not in vin:
            # Coinbase zählt nicht als Wallet-Input.
            continue
        key = utxo_ref(str(vin["txid"]), int(vin["vout"])).lower()
        if key in known:
            own_ins.append(i)
            continue

        addrs: tuple[str, ...] = ()
        prev = vin.get("prevout")
        if prev:
            addrs = tuple(chain._extract_addresses(prev))
        elif get_tx is not None:
            try:
                resolved = resolve_vin_prevout(get_tx, vin, progress=progress)
            except Exception:
                resolved = None
            if resolved:
                addrs = tuple(chain._extract_addresses(resolved))
            else:
                unknown_ins.append(i)
                continue
        else:
            unknown_ins.append(i)
            continue

        if match_own_address(addrs, own_addresses, wallet):
            own_ins.append(i)
        else:
            foreign_ins.append(i)

    own_outs: list[int] = []
    foreign_outs: list[int] = []
    for i, vout in enumerate(vouts):
        addrs = tuple(chain._extract_addresses(vout))
        if match_own_address(addrs, own_addresses, wallet):
            own_outs.append(i)
        else:
            foreign_outs.append(i)

    return TxOwnership(
        input_count=len(vins),
        output_count=len(vouts),
        own_input_indices=tuple(own_ins),
        foreign_input_indices=tuple(foreign_ins),
        unknown_input_indices=tuple(unknown_ins),
        own_output_indices=tuple(own_outs),
        foreign_output_indices=tuple(foreign_outs),
    )


def _looks_whirlpool(n_in: int, n_out: int, values: list[int]) -> bool:
    if n_in != _WHIRLPOOL_SIZE or n_out != _WHIRLPOOL_SIZE:
        return False
    if len(values) != _WHIRLPOOL_SIZE:
        return False
    return len(set(values)) == 1 and values[0] > 0


def _looks_wasabi_classic(n_in: int, n_out: int, values: list[int]) -> bool:
    if n_in < _LARGE_NM_MIN_INS or n_out < _LARGE_NM_MIN_OUTS:
        return False
    _betrag, equal_n, andere = _equal_output_stats(values)
    # Viele gleiche Mix-Outs + typisch Change (ungleiche Reste).
    return equal_n >= 8 and andere >= 1 and equal_n >= n_out // 2


def _looks_wabisabi(n_in: int, n_out: int, values: list[int]) -> bool:
    if n_in < _LARGE_NM_MIN_INS or n_out < _LARGE_NM_MIN_OUTS:
        return False
    _betrag, equal_n, _andere = _equal_output_stats(values)
    # Keine dominante Denomination — Zerlegung/Rekombination.
    return equal_n < max(4, n_out // 3)


def _looks_joinmarket(n_in: int, n_out: int, values: list[int]) -> bool:
    if n_in < 2 or n_out < 3:
        return False
    # Klein genug, dass Whirlpool/Wasabi nicht greifen.
    if n_in >= _LARGE_NM_MIN_INS:
        return False
    if _looks_whirlpool(n_in, n_out, values):
        return False
    _betrag, equal_n, andere = _equal_output_stats(values)
    # N+1 gleiche CJ-Outs + typisch Change je Teilnehmer (andere ≈ equal_n − 1
    # bis equal_n, grob).
    if equal_n < 2:
        return False
    return andere >= 1 and equal_n + andere == n_out


def _form_coinjoin_kind(n_in: int, n_out: int, values: list[int]) -> str | None:
    """Formheuristik — Reihenfolge: Whirlpool → Classic → WabiSabi → JM → generic."""
    if _looks_whirlpool(n_in, n_out, values):
        return "whirlpool"
    if _looks_wasabi_classic(n_in, n_out, values):
        return "wasabi_classic"
    if _looks_wabisabi(n_in, n_out, values):
        return "wabisabi"
    if _looks_joinmarket(n_in, n_out, values):
        return "joinmarket"
    # Große n:m mit ≥1 eigener Beteiligung → generischer Mix-Hinweis.
    if n_in >= _LARGE_NM_MIN_INS and n_out >= _LARGE_NM_MIN_OUTS:
        return "coinjoin"
    return None


def _vout_is_op_return(vout: dict) -> bool:
    """True, wenn der Output ein OP_RETURN / nulldata ist."""
    spk = vout.get("scriptPubKey") or {}
    typ = str(spk.get("type") or "").lower().replace(" ", "")
    if typ in ("nulldata", "op_return"):
        return True
    hx = str(spk.get("hex") or "").lower()
    if hx.startswith("6a"):
        return True
    asm = str(spk.get("asm") or "").upper()
    if asm.startswith("OP_RETURN"):
        return True
    # Esplora-ähnlich
    if str(vout.get("scriptpubkey_type") or "").lower() in ("op_return", "nulldata"):
        return True
    return False


def _op_return_push_len(vout: dict) -> int | None:
    """Länge der OP_RETURN-Daten (Push), oder None wenn nicht lesbar."""
    if not _vout_is_op_return(vout):
        return None
    hx = str((vout.get("scriptPubKey") or {}).get("hex") or "").lower()
    if not hx.startswith("6a") or len(hx) < 4:
        return None
    # 6a + direkter Push (1–75): nächstes Byte = Länge
    try:
        push = int(hx[2:4], 16)
    except ValueError:
        return None
    if 1 <= push <= 75:
        return push
    return None


def _spendable_output_values_sats(tx: dict) -> list[int]:
    """Output-Werte ohne OP_RETURN."""
    chain = _chain()
    out: list[int] = []
    for vout in tx.get("vout") or []:
        if _vout_is_op_return(vout):
            continue
        sats = chain._extract_value_sats(vout)
        if sats > 0:
            out.append(sats)
    return out


def _looks_bisq_payout_amounts(values: list[int]) -> bool:
    """
    Zwei Ausgänge: kleiner ≈ Deposit, größer ≈ Trade+Deposit.

    ``kleiner/größer`` bei 15–50 % Deposit ≈ 0,13–0,33.
    """
    if len(values) != 2:
        return False
    a, b = sorted(int(v) for v in values)
    if a <= 0 or b <= 0:
        return False
    ratio = a / b
    return _BISQ_PAYOUT_RATIO_MIN <= ratio <= _BISQ_PAYOUT_RATIO_MAX


def _prev_tx_via_single_vin(
    tx: dict,
    get_tx: Callable[[str], dict] | None,
) -> dict | None:
    vins = list(tx.get("vin") or [])
    if len(vins) != 1:
        return None
    vin = vins[0]
    if vin.get("is_coinbase") or "txid" not in vin:
        return None
    if get_tx is None:
        return None
    try:
        return get_tx(str(vin["txid"]))
    except Exception:
        return None


def _deposit_has_bisq_op_return(prev_tx: dict | None) -> bool:
    """Prevout-Tx sieht nach Bisq-Deposit aus (OP_RETURN mit Contract-Hash)."""
    if not prev_tx:
        return False
    return _looks_bisq_deposit_form(prev_tx)


def _looks_bisq_deposit_form(tx: dict) -> bool:
    """
    Bisq-v1-Deposit: typisch ≥2 Inputs, genau 2 Outs —
    Escrow-Wert + OP_RETURN (Contract-Hash ~20 Byte).
    """
    vins = [v for v in (tx.get("vin") or []) if not v.get("is_coinbase")]
    vouts = list(tx.get("vout") or [])
    if len(vins) < 2 or len(vouts) != 2:
        return False
    op_outs = [v for v in vouts if _vout_is_op_return(v)]
    spend = [v for v in vouts if not _vout_is_op_return(v)]
    if len(op_outs) != 1 or len(spend) != 1:
        return False
    if _chain()._extract_value_sats(spend[0]) <= 0:
        return False
    push = _op_return_push_len(op_outs[0])
    if push is None:
        # type/asm erkannt, Hex fehlt — Form reicht als weicher Hinweis
        return True
    return _BISQ_OP_RETURN_DATA_MIN <= push <= _BISQ_OP_RETURN_DATA_MAX


def _looks_bisq_payout(
    tx: dict,
    own: TxOwnership,
    *,
    get_tx: Callable[[str], dict] | None = None,
) -> bool:
    """
    Soft-Heuristik Bisq-Trade-Payout: 1 Input (Escrow) → 2 Spend-Outs,
    Deposit-Verhältnis; OP_RETURN am Deposit-Prevout verstärkt.
    """
    if own.own_output_count < 1 or own.own_input_count > 0:
        return False
    if own.input_count != 1:
        return False
    values = _spendable_output_values_sats(tx)
    if not _looks_bisq_payout_amounts(values):
        return False
    # Mit geklärtem Fremd-Input reicht die Form.
    if own.ownership_complete and own.foreign_input_count == 1:
        return True
    # Sonst nur mit Deposit-Fingerprint (OP_RETURN) soft labeln.
    prev = _prev_tx_via_single_vin(tx, get_tx)
    return _deposit_has_bisq_op_return(prev)


def classify_tx(
    tx: dict,
    own_addresses: set[str],
    *,
    wallet: WalletContext | None = None,
    get_tx: Callable[[str], dict] | None = None,
    own_prevouts: Collection[str] | None = None,
    progress: ProgressCallback | None = None,
    ownership: TxOwnership | None = None,
) -> TxClassification:
    """
    Klassifiziert eine Tx: Eigentum zuerst, dann Form.

    Detektor-Reihenfolge:
    1. Eigentum klären
    2. Bisq-Deposit / Bisq-Payout (Form + optional OP_RETURN am Prevout)
    3. 0 eigene Ins + eigene Outs → Exchange-Batch (bei Fan-out-Form)
    4. alle Ins eigen → Fan-Out (eigen), **außer** die Form ist klar Mix
       (Wasabi/WabiSabi/Whirlpool/…) — Soft-Label der Form bleibt nützlich,
       auch wenn alle Teilnehmer eigene XPUBs sind (Lab / Multi-Wallet)
    5. wenige Ins, wenige Fremd → PayJoin
    6. Whirlpool → Wasabi Classic → WabiSabi → JoinMarket → coinjoin
    """
    own = ownership or analyze_ownership(
        tx,
        own_addresses,
        wallet=wallet,
        get_tx=get_tx,
        own_prevouts=own_prevouts,
        progress=progress,
    )
    n_in = own.input_count
    n_out = own.output_count
    values = _output_values_sats(tx)

    # Coinbase / leere Txs
    if n_in == 0 or (n_in == 1 and (tx.get("vin") or [{}])[0].get("is_coinbase")):
        return _classification("unknown", own)

    # 2a. Bisq-Deposit: strukturell (OP_RETURN + Escrow), unabhängig vom Eigentum.
    if _looks_bisq_deposit_form(tx):
        return _classification("bisq_deposit", own)

    # 2b. Bisq-Payout: Empfang aus Escrow (vor generischem Exchange).
    if _looks_bisq_payout(tx, own, get_tx=get_tx):
        return _classification("bisq_payout", own)

    # 3. Exchange-Batch: kein eigener Input, aber eigener Empfang; typisch Fan-out.
    if (
        own.ownership_complete
        and own.own_input_count == 0
        and own.own_output_count >= 1
        and n_out >= 3
    ):
        return _classification("exchange_batch", own)

    # Mix-Form früh: auch bei rein eigenen Inputs (Multi-Wallet / Lab).
    form_kind = None
    if own.own_input_count >= 1 and own.own_output_count >= 1:
        form_kind = _form_coinjoin_kind(n_in, n_out, values)

    # 3. Fan-Out (eigen): alle Inputs eigen — Soft-Label nur bei erkennbarer
    # Auszahlungs-/Konsolidierungsform, nicht bei klarer Mix-Struktur.
    if (
        own.ownership_complete
        and own.own_input_count == n_in
        and n_in >= 1
        and own.foreign_input_count == 0
    ):
        if form_kind:
            return _classification(form_kind, own)
        if n_out >= 3 or n_in >= 2:
            return _classification("fan_out_own", own)
        return _classification("unknown", own)

    # 4. PayJoin: gemischt, übersichtlich, wenige Fremd-Ins.
    if (
        own.ownership_complete
        and own.own_input_count >= 1
        and 1 <= own.foreign_input_count <= _PAYJOIN_MAX_FOREIGN
        and n_in <= _PAYJOIN_MAX_INS
        and own.own_output_count >= 1
    ):
        # Keine große Peer-/Equal-Out-Menge (sonst eher JM/CJ).
        _b, equal_n, _a = _equal_output_stats(values)
        if equal_n < 3 and n_out <= 6:
            return _classification("payjoin", own)

    # 5. CoinJoin-Form — mindestens ein eigener Input und Output.
    if own.own_input_count >= 1 and own.own_output_count >= 1:
        if form_kind:
            return _classification(form_kind, own)
        # Kleiner Mix-Verdacht (z. B. 3–14 Ins) mit Gleichbeträgen → generic.
        _b, equal_n, andere = _equal_output_stats(values)
        if (
            n_in >= 3
            and equal_n >= 2
            and andere >= 1
            and own.foreign_input_count >= 1
        ):
            return _classification("coinjoin", own)

    return _classification("unknown", own)


def own_prevouts_for_txid(
    creator_txid: str,
    *,
    wallet: WalletContext | None = None,
    cache_dir=None,
) -> set[str]:
    """
    Stufe‑1-Index: eigene Outpoints mit ``spent_txid == creator_txid``.

    Liest den Verlaufs-Cache je XPUB. Fehlt Cache/Wallet → leeres Set.
    """
    if wallet is None or cache_dir is None:
        return set()
    chain = _chain()
    ziel = str(creator_txid).strip().lower()
    if not ziel:
        return set()
    treffer: set[str] = set()
    for xpub in getattr(wallet, "xpubs", None) or []:
        try:
            verlauf = chain.load_xpub_verlauf_cache(xpub, cache_dir) or []
        except Exception:
            continue
        for e in verlauf:
            spent = str(e.get("spent_txid") or "").strip().lower()
            if spent != ziel:
                continue
            tid = str(e.get("txid") or "").strip().lower()
            if not tid:
                continue
            try:
                vout = int(e.get("vout"))
            except (TypeError, ValueError):
                continue
            treffer.add(utxo_ref(tid, vout).lower())
    return treffer
