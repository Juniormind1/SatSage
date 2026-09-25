"""Sanction hop walk/check helpers (Slice 4).

Lab-Hop-Semantik: scan_external_sanction_hops, CoinJoin-Merge-Helfer,
SanctionHitFound. analyze.py re-exportiert die öffentliche API.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from display import abbrev_display

from core.trace import (
    CoinbaseFunding,
    FundingEdge,
    iter_funding_inputs,
    utxo_ref,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


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
