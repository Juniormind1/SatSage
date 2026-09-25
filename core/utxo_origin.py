"""UTXO-Herkunfts-Walk, Vertiefung und Steuer-Horizont (Slice 4).

Kern von analyze.trace_utxo_origin und den Resume-/Lücken-Helfern.
analyze.py re-exportiert die öffentliche API. Der Walk liegt in
``core.trace`` und wird hier importiert; ``core.trace`` lädt dieses Modul
erst nach den Walk-Symbolen, damit der Zyklus beim Import hält.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from core.trace import (
    CoinbaseFunding,
    FundingEdge,
    MAX_TRACE_DEPTH,
    UnresolvedExternalBatch,
    UnresolvedPrevout,
    iter_trace_funding_inputs,
    is_own_output,
    match_own_address,
    parse_utxo_ref,
    resolve_vin_prevout,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


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
    stop_before_ts: int | None = None,
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

    *stop_before_ts*: optionaler Steuer-Horizont (Unix). Hop mit
    ``time_ts <= stop_before_ts`` wird als ``tax_horizon``-Blatt beendet —
    tiefer bis extern/Coinbase braucht das Steuerjahr nicht. Herkunft tracen
    übergibt ``None`` und führt Horizont-Blätter später nach (siehe
    ``vertiefe_tax_horizon``).
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
        from core.jobs import ist_abbruch

        if ist_abbruch(e):
            raise
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

    # Steuer-Horizont: Hop ist alt genug für Haltefrist/Stichtag — nicht tiefer.
    # depth==0 (Wurzel-UTXO): ebenfalls, wenn das Output selbst schon reicht.
    if stop_before_ts is not None and node.get("time_ts") is not None:
        try:
            if int(node["time_ts"]) <= int(stop_before_ts):
                node["tax_horizon"] = True
                memo[utxo_key] = node
                visited_utxos.discard(utxo_key)
                return node
        except (TypeError, ValueError):
            pass

    # Börsen-CSV: an importierter Adresse/Tx endet der Walk — keine Hops
    # hinter die Ein-/Auszahlung (auch wenn der Klarname dem Nutzer gehört).
    try:
        from core import exchange_reports as boerse_mod

        boerse_grenze = boerse_mod.grenze(
            adressen=out_addrs, txid=creator_txid,
        )
    except Exception:
        boerse_grenze = None
    if boerse_grenze is not None:
        node["exchange_stop"] = True
        node["exchange_label"] = boerse_grenze
        # Blatt wie externes Ende: Anschaffung an der Börsen-Grenze.
        # Adress-Treffer → echte Börsen-Adresse; nur Tx-Treffer → Klarname
        # (Wallet-Adresse der Wurzel nicht als „extern“ ausgeben).
        try:
            from core import exchange_reports as _boerse_chk

            addr_disp = next(
                (a for a in out_addrs if _boerse_chk.ist_boerse_adresse(a)),
                "",
            )
        except Exception:
            addr_disp = out_addrs[0] if out_addrs else ""
        if not addr_disp:
            addr_disp = str(boerse_grenze.get("name") or "Börse")
        node["sources"] = [{
            "type": "external",
            "address": addr_disp,
            "amount_sats": node.get("amount_sats") or 0,
            "from_utxo": utxo_key,
            "time_ts": node.get("time_ts"),
            "time": node.get("time") or "",
            "exchange_stop": True,
        }]
        memo[utxo_key] = node
        visited_utxos.discard(utxo_key)
        return node

    progress_cb = progress.update if progress else None

    # CoinJoin-/Mix-Klassifikation: Eigentum (Verlauf-Index + Prevouts), dann Form.
    # Große Nicht-CJ-Txs nicht blind alle Prevouts fürs Label laden.
    from core.tx_classify import classify_tx, own_prevouts_for_txid
    from core.trace import FULL_RESOLUTION_INPUT_LIMIT

    own_prevouts = own_prevouts_for_txid(
        creator_txid, wallet=wallet, cache_dir=cache_dir
    )
    n_vin = len(tx.get("vin") or [])
    n_vout = len(tx.get("vout") or [])
    tx_class = classify_tx(
        tx,
        own_addresses,
        wallet=wallet,
        get_tx=None,
        own_prevouts=own_prevouts,
        progress=progress_cb,
    )
    braucht_prevouts = (
        tx_class.kind == "unknown"
        and (
            n_vin <= FULL_RESOLUTION_INPUT_LIMIT
            or (n_vin >= 15 and n_vout >= 10)
            or bool(own_prevouts)
        )
    )
    if braucht_prevouts:
        tx_class = classify_tx(
            tx,
            own_addresses,
            wallet=wallet,
            get_tx=get_tx,
            own_prevouts=own_prevouts,
            progress=progress_cb,
        )
    # Exchange-Batch ohne Namen: Prevouts nachladen und Label ggf. konkretisieren
    # („Auszahlung von Kraken“ statt „Wahrscheinlich Batch-…“).
    if (
        tx_class.kind == "exchange_batch"
        and str(tx_class.soft_label_de or "").startswith("Wahrscheinlich")
        and get_tx is not None
        and not braucht_prevouts
    ):
        tx_class = classify_tx(
            tx,
            own_addresses,
            wallet=wallet,
            get_tx=get_tx,
            own_prevouts=own_prevouts,
            progress=progress_cb,
        )
    if tx_class.kind != "unknown":
        node["tx_class"] = tx_class.kind
        node["tx_class_label"] = tx_class.soft_label_de
        node["tx_class_label_en"] = tx_class.soft_label_en

    own_only = bool(tx_class.walk_own_inputs_only)
    # CJ: alle eigenen Inputs; Fremde = Rauschen. Nicht-CJ: Limit unverändert.
    for inp in iter_trace_funding_inputs(
        get_tx,
        creator_txid,
        own_addresses,
        wallet=wallet,
        progress=progress_cb,
        alle_eigenen_inputs=alle_eigenen_inputs or own_only,
        own_inputs_only=own_only,
        own_prevouts=own_prevouts if own_only else None,
    ):
        if isinstance(inp, CoinbaseFunding):
            node["sources"].append({"type": "coinbase", "amount_sats": 0})
            continue
        if isinstance(inp, UnresolvedExternalBatch):
            # Bei CJ sollte das nicht vorkommen; bei normalen Sammel-Txs bleibt
            # die Untergrenze sichtbar.
            node["sources"].append({
                "type": "external_unresolved",
                "input_count": inp.input_count,
                "amount_sats": 0,
            })
            continue
        if isinstance(inp, UnresolvedPrevout):
            # Prevout fehlte (get_tx/Netz) — Lücke, kein leeres „found“.
            node["sources"].append({
                "type": "error",
                "from_utxo": inp.key,
                "amount_sats": 0,
                "error": (
                    "Vorgänger-Tx nicht ladbar — Herkunft hier unterbrochen. "
                    "„Scan neu“ erneut versuchen."
                ),
            })
            continue
        edge: FundingEdge = inp
        prev_ref = edge.prevout.key
        prev_addrs = list(edge.addresses)
        amount_sats = edge.amount_sats
        prev_txid = edge.prevout.txid
        prev_vout = edge.prevout.vout

        try:
            # Börsen-Prevout: immer externes Blatt, nie intern weiterverfolgen.
            try:
                from core import exchange_reports as boerse_mod

                prev_boerse = boerse_mod.grenze(
                    adressen=prev_addrs, txid=prev_txid,
                )
            except Exception:
                prev_boerse = None
            if prev_boerse is not None:
                ext_ts = edge.prev_time_ts
                ext_time = ""
                if ext_ts:
                    try:
                        from datetime import UTC, datetime

                        ext_time = datetime.fromtimestamp(
                            int(ext_ts), UTC
                        ).strftime("%d.%m.%Y %H:%M:%S")
                    except (OSError, OverflowError, TypeError, ValueError):
                        ext_time = ""
                node["sources"].append({
                    "type": "external",
                    "address": (
                        prev_addrs[0] if prev_addrs
                        else str(prev_boerse.get("name") or "Börse")
                    ),
                    "amount_sats": amount_sats,
                    "from_utxo": prev_ref,
                    "time_ts": ext_ts,
                    "time": ext_time,
                    "exchange_stop": True,
                })
                continue

            own_addr = _match_own_address(prev_addrs, own_addresses, wallet)
            if not own_addr and own_only and prev_ref.lower() in {
                p.lower() for p in own_prevouts
            }:
                # Index-Treffer ohne Adresse am Prevout — trotzdem intern.
                own_addr = prev_addrs[0] if prev_addrs else prev_ref
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
                    stop_before_ts=stop_before_ts,
                )
                node["sources"].append({
                    "type": "internal",
                    "address": own_addr,
                    "amount_sats": amount_sats,
                    "from_utxo": prev_ref,
                    "trace": child,
                })
            elif own_only:
                # Fremd-Peer trotz Walk — ignorieren (Rauschen).
                continue
            else:
                ext_ts = edge.prev_time_ts
                ext_time = ""
                if ext_ts:
                    try:
                        # Anzeige wie bei internen Hops (ohne extra get_tx).
                        from datetime import UTC, datetime

                        ext_time = datetime.fromtimestamp(
                            int(ext_ts), UTC
                        ).strftime("%d.%m.%Y %H:%M:%S")
                    except (OSError, OverflowError, TypeError, ValueError):
                        ext_time = ""
                node["sources"].append({
                    "type": "external",
                    "address": prev_addrs[0] if prev_addrs else "unbekannt",
                    "amount_sats": amount_sats,
                    "from_utxo": prev_ref,
                    "time_ts": ext_ts,
                    "time": ext_time,
                })
        except Exception as exc:
            # Job-Abbruch (Cancelled) darf hier nicht verschwinden — sonst
            # bleibt „Lücken schließen“ trotz Abbruch-Knopf ewig laufen.
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
            continue

    if not node["sources"]:
        if own_only:
            # Fremde Peers absichtlich übersprungen. Ohne eigene Inputs bleibt
            # der Soft-Label-Knoten ohne Kinder — Completeness behandelt das
            # als absichtlichen Skip, nicht als Lücke (siehe core.trace).
            node["coinjoin_noise_skipped"] = True
            own_ins = (
                tx_class.ownership.own_input_count if tx_class.ownership else 0
            )
            if own_ins == 0:
                node["type"] = "unknown"
        else:
            # Erzeuger-Tx hat Inputs, aber kein Source → Lücke sichtbar machen
            # (nicht „found + leer“ → UI „Keine Zuflüsse ermittelbar“).
            n_vin = sum(
                1 for v in (tx.get("vin") or [])
                if not v.get("is_coinbase") and v.get("txid") is not None
            )
            if n_vin > 0:
                node["sources"].append({
                    "type": "error",
                    "input_count": n_vin,
                    "amount_sats": 0,
                    "error": (
                        "Eingänge nicht auflösbar (Vorgänger-Tx fehlte). "
                        "„Scan neu“ erneut versuchen."
                    ),
                })
            else:
                node["type"] = "unknown"

    # Nur abgeschlossene Knoten cachen — cycle bleibt pfadgebunden.
    memo[utxo_key] = node
    visited_utxos.discard(utxo_key)
    return node


def vertiefe_tax_horizon(
    node: dict | None,
    get_tx,
    own_addresses: set,
    *,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress: _EphemeralProgress | None = None,
    alle_eigenen_inputs: bool = False,
    memo: dict | None = None,
) -> dict | None:
    """
    Setzt einen Steuer-Teilbaum fort: ``tax_horizon``-Blätter bis extern/Coinbase.

    Bereits voll aufgelöste Zweige bleiben unangetastet — Herkunft tracen nach
    Steuerjahr-Trace rechnet nur die Lücken nach, nicht den ganzen Graphen.
    """
    if not isinstance(node, dict):
        return node
    if memo is None:
        memo = {}

    if node.get("tax_horizon"):
        txid = str(node.get("txid") or "").strip()
        try:
            vout = int(node.get("vout", 0))
        except (TypeError, ValueError):
            return node
        if not txid:
            return node
        # Frischen Lauf ohne Horizont — Memo-Key freigeben falls Altlast.
        key = f"{txid}:{vout}"
        memo.pop(key, None)
        return trace_utxo_origin(
            get_tx,
            txid,
            vout,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=progress,
            alle_eigenen_inputs=alle_eigenen_inputs,
            memo=memo,
            stop_before_ts=None,
        )

    quellen = node.get("sources")
    if not isinstance(quellen, list):
        return node
    for src in quellen:
        if not isinstance(src, dict) or src.get("type") != "internal":
            continue
        kind = src.get("trace")
        if isinstance(kind, dict):
            src["trace"] = vertiefe_tax_horizon(
                kind,
                get_tx,
                own_addresses,
                wallet=wallet,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_address_utxos,
                cache_source=cache_source,
                progress=progress,
                alle_eigenen_inputs=alle_eigenen_inputs,
                memo=memo,
            )
    return node


def _hat_tax_horizon(node: dict | None) -> bool:
    """Ob irgendwo ein Steuer-Horizont-Blatt steckt (Teilbaum)."""
    if not isinstance(node, dict):
        return False
    if node.get("tax_horizon"):
        return True
    for src in node.get("sources") or []:
        if not isinstance(src, dict):
            continue
        if src.get("type") == "internal" and _hat_tax_horizon(src.get("trace")):
            return True
    return False


def _knoten_txid_vout(node: dict) -> tuple[str, int] | None:
    """txid/vout aus Rohknoten oder error-from_utxo."""
    txid = str(node.get("txid") or "").strip()
    if txid:
        try:
            return txid, int(node.get("vout", 0) or 0)
        except (TypeError, ValueError):
            return None
    roh = str(node.get("utxo") or node.get("from_utxo") or "").strip()
    if ":" not in roh:
        return None
    tid, _, v = roh.rpartition(":")
    tid = tid.strip()
    if not tid:
        return None
    try:
        return tid, int(v)
    except (TypeError, ValueError):
        return None


def _quelle_hat_luecke(src: dict | None) -> bool:
    """True wenn diese Quelle noch nachgezogen werden muss."""
    if not isinstance(src, dict):
        return True
    typ = src.get("type")
    if typ in ("external", "coinbase"):
        return False
    if src.get("exchange_stop"):
        return False
    if typ == "external_unresolved":
        return True
    if typ == "error":
        return True
    if typ == "internal":
        return _origin_hat_luecken(src.get("trace"))
    return True


def _origin_hat_luecken(node: dict | None) -> bool:
    """
    True wenn der Rohbaum noch kein volles extern/Coinbase-Ende hat.

    Entspricht der UI-Semantik „unvollständig“: error/unknown/cycle,
    leere Sources, tax_horizon, external_unresolved, lückige interne Kinder.
    """
    if not isinstance(node, dict):
        return True
    if node.get("tax_horizon"):
        return True
    typ = node.get("type")
    if typ in ("error", "unknown", "cycle"):
        return True
    if node.get("coinjoin_noise_skipped") and node.get("tx_class"):
        # Absichtliches CJ-Ende ohne Peer-Externals.
        return False
    quellen = node.get("sources")
    if not isinstance(quellen, list) or not quellen:
        # Root ohne Sources (und kein CJ-Skip) = Lücke.
        return typ not in ("external", "coinbase")
    return any(_quelle_hat_luecke(src) for src in quellen)


def hat_brauchbaren_teilfortschritt(node: dict | None) -> bool:
    """
    Ob ein gespeicherter origin_tree bei Resume etwas Erhaltenswertes hat.

    Leerer/kaputter Baum (nur error ohne Struktur) → Neustart sinnvoll.
    Sonst: fertige Zweige behalten und nur Lücken nachziehen.
    """
    if not isinstance(node, dict):
        return False
    if node.get("tax_horizon"):
        return True
    quellen = node.get("sources")
    if not isinstance(quellen, list) or not quellen:
        return False
    for src in quellen:
        if not isinstance(src, dict):
            continue
        typ = src.get("type")
        if typ in ("external", "coinbase"):
            return True
        if typ == "internal" and isinstance(src.get("trace"), dict):
            return True
        if typ == "external_unresolved":
            return True
    return False


def _seed_memo_fertige_unterbaeume(node: dict | None, memo: dict) -> None:
    """Vollständige Unterbäume ins Memo — Resume läuft sie nicht nochmal ab."""
    if not isinstance(node, dict) or not isinstance(memo, dict):
        return
    ref = _knoten_txid_vout(node)
    if ref and not _origin_hat_luecken(node) and node.get("type") not in (
        "error", "unknown", "cycle",
    ):
        memo[f"{ref[0]}:{ref[1]}"] = node
    for src in node.get("sources") or []:
        if isinstance(src, dict) and src.get("type") == "internal":
            _seed_memo_fertige_unterbaeume(src.get("trace"), memo)


def vertiefe_herkunft_luecken(
    node: dict | None,
    get_tx,
    own_addresses: set,
    *,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress: _EphemeralProgress | None = None,
    alle_eigenen_inputs: bool = False,
    memo: dict | None = None,
) -> dict | None:
    """
    Setzt einen unvollständigen Herkunfts-Rohbaum fort.

    * Fertige Zweige (extern/Coinbase, vollständige interne Teilbäume) bleiben.
    * ``tax_horizon``, ``error``, leere Sources und lückige interne Kinder
      werden gezielt nachgezogen — kein Komplett-Neulauf ab der Wurzel.
    """
    if not isinstance(node, dict):
        return node
    if memo is None:
        memo = {}
        _seed_memo_fertige_unterbaeume(node, memo)

    if not _origin_hat_luecken(node):
        return node

    # Steuer-Horizont oder reiner Fehler-/Leer-Knoten: diesen Hop neu laufen.
    if node.get("tax_horizon") or node.get("type") in ("error", "unknown", "cycle"):
        ref = _knoten_txid_vout(node)
        if not ref:
            return node
        txid, vout = ref
        memo.pop(f"{txid}:{vout}", None)
        if progress:
            try:
                progress.update(
                    f"↻ Lücke nachziehen {txid[:16]}…:{vout}"
                )
            except Exception:
                pass
        return trace_utxo_origin(
            get_tx,
            txid,
            vout,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=progress,
            alle_eigenen_inputs=alle_eigenen_inputs,
            memo=memo,
            stop_before_ts=None,
        )

    quellen = node.get("sources")
    if not isinstance(quellen, list) or not quellen:
        ref = _knoten_txid_vout(node)
        if not ref:
            return node
        txid, vout = ref
        memo.pop(f"{txid}:{vout}", None)
        return trace_utxo_origin(
            get_tx,
            txid,
            vout,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=progress,
            alle_eigenen_inputs=alle_eigenen_inputs,
            memo=memo,
            stop_before_ts=None,
        )

    # Ganze Node neu, wenn gebündelte unresolved-Eingänge mit Opt-in.
    if alle_eigenen_inputs and any(
        isinstance(s, dict) and s.get("type") == "external_unresolved"
        for s in quellen
    ):
        ref = _knoten_txid_vout(node)
        if ref:
            txid, vout = ref
            memo.pop(f"{txid}:{vout}", None)
            return trace_utxo_origin(
                get_tx,
                txid,
                vout,
                own_addresses,
                wallet=wallet,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_address_utxos,
                cache_source=cache_source,
                progress=progress,
                alle_eigenen_inputs=True,
                memo=memo,
                stop_before_ts=None,
            )

    neu_quellen: list = []
    geaendert = False
    for src in quellen:
        if not isinstance(src, dict):
            neu_quellen.append(src)
            continue
        typ = src.get("type")
        if typ == "internal":
            kind = src.get("trace")
            if isinstance(kind, dict) and _origin_hat_luecken(kind):
                frisch = vertiefe_herkunft_luecken(
                    kind,
                    get_tx,
                    own_addresses,
                    wallet=wallet,
                    cache_dir=cache_dir,
                    fetch_address_utxos=fetch_address_utxos,
                    cache_source=cache_source,
                    progress=progress,
                    alle_eigenen_inputs=alle_eigenen_inputs,
                    memo=memo,
                )
                if frisch is not kind:
                    src = dict(src)
                    src["trace"] = frisch
                    geaendert = True
            neu_quellen.append(src)
        elif typ == "error":
            ref = _knoten_txid_vout(src)
            if ref is None:
                # from_utxo am error-Source
                roh = str(src.get("from_utxo") or "").strip()
                if ":" in roh:
                    tid, _, v = roh.rpartition(":")
                    try:
                        ref = (tid.strip(), int(v))
                    except (TypeError, ValueError):
                        ref = None
            if ref:
                txid, vout = ref
                memo.pop(f"{txid}:{vout}", None)
                if progress:
                    try:
                        progress.update(
                            f"↻ Fehlenden Prevout nachladen {txid[:16]}…:{vout}"
                        )
                    except Exception:
                        pass
                kind = trace_utxo_origin(
                    get_tx,
                    txid,
                    vout,
                    own_addresses,
                    wallet=wallet,
                    cache_dir=cache_dir,
                    fetch_address_utxos=fetch_address_utxos,
                    cache_source=cache_source,
                    progress=progress,
                    alle_eigenen_inputs=alle_eigenen_inputs,
                    memo=memo,
                    stop_before_ts=None,
                )
                # error-Source → internal oder external ersetzen
                own_addr = None
                if wallet and kind:
                    for a in kind.get("addresses") or []:
                        if wallet.resolve_address(a):
                            own_addr = a
                            break
                if own_addr or (
                    kind
                    and any(
                        a in own_addresses
                        for a in (kind.get("addresses") or [])
                    )
                ):
                    addr = own_addr or (kind.get("addresses") or [""])[0]
                    neu_quellen.append({
                        "type": "internal",
                        "address": addr,
                        "amount_sats": int(
                            src.get("amount_sats")
                            or kind.get("amount_sats")
                            or 0
                        ),
                        "from_utxo": f"{txid}:{vout}",
                        "trace": kind,
                    })
                elif kind and kind.get("type") not in ("error", "unknown"):
                    # Als external-Blatt, wenn Prevout jetzt da und fremd
                    addrs = kind.get("addresses") or []
                    neu_quellen.append({
                        "type": "external",
                        "address": addrs[0] if addrs else "unbekannt",
                        "amount_sats": int(
                            src.get("amount_sats")
                            or kind.get("amount_sats")
                            or 0
                        ),
                        "from_utxo": f"{txid}:{vout}",
                        "time_ts": kind.get("time_ts"),
                        "time": kind.get("time") or "",
                    })
                else:
                    neu_quellen.append(src)
                geaendert = True
            else:
                neu_quellen.append(src)
        else:
            neu_quellen.append(src)

    if not geaendert:
        return node
    out = dict(node)
    out["sources"] = neu_quellen
    if out.get("type") == "unknown" and neu_quellen:
        out["type"] = "utxo"
    return out
