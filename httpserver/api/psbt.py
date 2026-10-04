"""PSBT-Vorschau fürs FIFO-Spend — noch ohne PSBT, nur die Coin-Auswahl."""

from __future__ import annotations

from typing import Any

#: Mehr UTXOs schickt die Ansicht nicht (Schutz vor Riesen-Körpern).
_MAX_UTXOS = 20_000


def api_psbt_auswahl(state: Any, payload: dict | None) -> dict:
    """
    ``POST /api/psbt/auswahl`` — welche grünen UTXOs, welches Wechselgeld,
    welche Gebühr? Körper: ``betrag`` (sats), ``modus`` (defensiv/offensiv),
    ``utxos`` (Zeitstrahl-Punkte des Wallets), ``pending`` (Schlüssel der
    Mempool-Ausgaben), ``strategie`` (wechselgeld/gebuehr/aelteste/staub,
    Standard wechselgeld). Regel und Suche: ``core/coin_auswahl.py``.

    Vorschau: Die Antwort trägt nur ``txid:vout``, Beträge und grüne Anteile —
    kein Schlüsselmaterial. Erzeugt, signiert und sendet nichts.
    """
    from core.bitcoind_rpc import stelle_core_client_bereit, stelle_utxo_core_client_bereit
    from core.coin_auswahl import auswahl_vorschau
    from core.fee_vorschlag import schaetzung_holen
    from server import ApiError

    koerper = payload or {}
    try:
        betrag = int(koerper.get("betrag") or 0)
    except (TypeError, ValueError):
        raise ApiError(400, "„betrag“ ist keine ganze Zahl.")
    if betrag <= 0 or betrag > 21_000_000 * 100_000_000:
        raise ApiError(400, "Betrag außerhalb des Bereichs.")
    utxos = koerper.get("utxos")
    pending = koerper.get("pending")
    utxos = [] if utxos is None else utxos
    pending = [] if pending is None else pending
    if not isinstance(utxos, list) or not isinstance(pending, list):
        raise ApiError(400, "„utxos“ und „pending“ müssen Listen sein.")
    if len(utxos) > _MAX_UTXOS:
        raise ApiError(400, "Zu viele UTXOs.")
    from core.coin_auswahl import STANDARD_STRATEGIE, STRATEGIEN

    strategie = str(koerper.get("strategie") or STANDARD_STRATEGIE).strip().lower()
    if strategie not in STRATEGIEN:
        raise ApiError(400, f"„strategie“ muss {', '.join(STRATEGIEN)} sein.")
    env = state.env().values()

    def fabrik():
        return (
            stelle_core_client_bereit(env, timeout=5.0)
            or stelle_utxo_core_client_bereit(env, timeout=5.0)
        )

    feerate, fehler = schaetzung_holen(fabrik)
    return auswahl_vorschau(
        utxos,
        modus=str(koerper.get("modus") or "defensiv"),
        betrag=betrag,
        pending=[str(k) for k in pending],
        feerate_btc_kvb=feerate,
        fehler=fehler,
        strategie=strategie,
    )
