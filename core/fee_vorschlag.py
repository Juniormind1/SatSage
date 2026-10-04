"""
Gebührenvorschlag fürs FIFO-Spend (PSBT-Ziel-Zeile).

Regel (vereinbart 2026-10-04, ISSUES „Wallet · FIFO-Spend (PSBT)“):

1. Schätzung: ``estimatesmartfee`` mit ``conf_target=1`` (nächster Block),
   ``feerate`` in BTC/kvB → sat/vB (× 100 000, exakt über ``Decimal``).
2. Puffer: aufrunden auf die nächste ganze sat/vB *oberhalb* der Schätzung,
   ``floor(schaetzung) + 1`` — das sind mehr als 0 und höchstens +1 sat/vB
   (3,2 → 4; 3,0 → 4; 0,8 → 1). Nie unter 1 sat/vB.
3. Deckel: Läge die Gebühr ``rate × vsize`` über 0,1 % des Betrags, gilt
   1 sat/vB.
4. Keine Schätzung (Regtest ohne Daten, Fehler, kein Core): 1 sat/vB.

vsize: ``ceil(10,5 + 68 × Inputs + 31 × Outputs)`` vB — P2WPKH-Näherung,
2 Outputs (Ziel und Wechselgeld). Die Zahl der Inputs liefert die Ansicht
(Näherung der FIFO-Auswahl, siehe ``web/views/wallets.js``); ohne Angabe 1.

Kein Schlüsselmaterial, keine Wallet-RPC — nur die lesende Schätzung.
"""
from __future__ import annotations

import math
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

#: P2WPKH-Näherung in vB.
VBYTES_OVERHEAD = Decimal("10.5")
VBYTES_INPUT = 68
VBYTES_OUTPUT = 31
OUTPUTS_STANDARD = 2

#: Ziel der Schätzung: nächster Block.
CONF_TARGET = 1

#: Deckel: Gebühr höchstens 0,1 % des Betrags, sonst 1 sat/vB.
DECKEL_PROMILLE = 1

#: Kleinste Rate.
MIN_SAT_VB = 1

#: Schätzung so lange wiederverwenden (Sekunden).
CACHE_SEKUNDEN = 60.0

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"zeit": 0.0, "wert": None}


def btc_kvb_zu_sat_vb(feerate: Any) -> Decimal | None:
    """``0.00012345`` BTC/kvB → ``12.345`` sat/vB. None bei Unsinn."""
    try:
        wert = Decimal(str(feerate))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not wert.is_finite() or wert <= 0:
        return None
    return wert * Decimal(100_000_000) / Decimal(1000)


def rate_mit_puffer(schaetzung_sat_vb: Decimal | float | None) -> int | None:
    """Nächste ganze sat/vB oberhalb der Schätzung (Puffer > 0 und ≤ +1)."""
    if schaetzung_sat_vb is None:
        return None
    wert = Decimal(str(schaetzung_sat_vb))
    if not wert.is_finite() or wert <= 0:
        return None
    return max(MIN_SAT_VB, int(math.floor(wert)) + 1)


def vsize_schaetzung(inputs: int, outputs: int = OUTPUTS_STANDARD) -> int:
    """``ceil(10,5 + 68·Inputs + 31·Outputs)`` vB, mindestens 1 Input."""
    n_in = max(1, int(inputs or 1))
    n_out = max(1, int(outputs or OUTPUTS_STANDARD))
    return int(math.ceil(VBYTES_OVERHEAD + VBYTES_INPUT * n_in + VBYTES_OUTPUT * n_out))


def gebuehr_vorschlag(
    schaetzung_btc_kvb: Any,
    *,
    betrag_sats: int,
    inputs: int = 1,
    outputs: int = OUTPUTS_STANDARD,
    fehler: str | None = None,
) -> dict:
    """
    Wendet die Regel an. ``quelle``:

    - ``schaetzung`` — Schätzung + Puffer,
    - ``deckel`` — über 0,1 % des Betrags, daher 1 sat/vB,
    - ``fallback`` — keine Schätzung, daher 1 sat/vB (``grund`` sagt warum).
    """
    vsize = vsize_schaetzung(inputs, outputs)
    betrag = max(0, int(betrag_sats or 0))
    schaetzung = btc_kvb_zu_sat_vb(schaetzung_btc_kvb) if schaetzung_btc_kvb is not None else None
    basis = {
        "vsize": vsize,
        "inputs": max(1, int(inputs or 1)),
        "outputs": max(1, int(outputs or OUTPUTS_STANDARD)),
        "betrag_sats": betrag,
        "conf_target": CONF_TARGET,
        "schaetzung_sat_vb": float(schaetzung) if schaetzung is not None else None,
    }
    rate = rate_mit_puffer(schaetzung)
    if rate is None:
        return {
            **basis, "sat_vb": MIN_SAT_VB, "fee_sats": MIN_SAT_VB * vsize,
            "quelle": "fallback", "grund": fehler or "keine Schätzung",
        }
    fee = rate * vsize
    # fee > 0,1 % · betrag  ⇔  fee · 1000 > betrag (ganzzahlig, ohne Rundung)
    if fee * 1000 > betrag * DECKEL_PROMILLE:
        return {
            **basis, "sat_vb": MIN_SAT_VB, "fee_sats": MIN_SAT_VB * vsize,
            "quelle": "deckel", "rate_ohne_deckel": rate, "fee_ohne_deckel": fee,
        }
    return {**basis, "sat_vb": rate, "fee_sats": fee, "quelle": "schaetzung"}


def schaetzung_holen(
    client_fabrik: Callable[[], Any],
    *,
    jetzt: Callable[[], float] = time.monotonic,
) -> tuple[Any, str | None]:
    """
    ``(feerate_btc_kvb, fehler)`` aus ``estimatesmartfee [1]``, 60 s gecacht.

    *client_fabrik* liefert einen ``BitcoinRpcClient`` oder None (kein Core).
    Allowlist-Verstöße werden weitergereicht (Dealbreaker T14).
    """
    from core.bitcoind_rpc import RpcAllowlistError

    with _cache_lock:
        if _cache["wert"] is not None and jetzt() - _cache["zeit"] < CACHE_SEKUNDEN:
            return _cache["wert"]
    client = None
    try:
        client = client_fabrik()
        if client is None:
            wert: tuple[Any, str | None] = (None, "kein Bitcoin Core verbunden")
        else:
            antwort = client.call("estimatesmartfee", [CONF_TARGET])
            feerate = antwort.get("feerate") if isinstance(antwort, dict) else None
            if feerate is None:
                fehler = "; ".join(str(e) for e in (antwort or {}).get("errors") or []) \
                    if isinstance(antwort, dict) else ""
                wert = (None, fehler or "keine Daten für die Schätzung")
            else:
                wert = (feerate, None)
    except RpcAllowlistError:
        raise
    except Exception as exc:  # Node weg, rpcwhitelist, Timeout …
        wert = (None, str(exc) or exc.__class__.__name__)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    with _cache_lock:
        _cache["zeit"] = jetzt()
        _cache["wert"] = wert
    return wert


def cache_leeren() -> None:
    with _cache_lock:
        _cache["zeit"] = 0.0
        _cache["wert"] = None
