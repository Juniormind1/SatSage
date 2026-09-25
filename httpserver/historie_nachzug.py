"""Kurs-Historie-Nachzug — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations

import threading


def starte_historie_nachzug_taeglich(
    state: AppState,
    *,
    warte_sekunden: float = 45.0,
) -> None:
    """Lücken-Check erst *nach* GUI-Start — nicht während Splash/Verbindungsaufbau.

    Einmal pro Prozess; wartet ``warte_sekunden``, damit Browser und
    Datenquellen-Pillen stehen, bevor Bitstamp ggf. gezogen wird.
    """
    if getattr(state, "_historie_sync_gestartet", False):
        return
    state._historie_sync_gestartet = True  # type: ignore[attr-defined]

    def _lauf() -> None:
        import time as _time

        from core import price_history_sync as hist_sync

        _time.sleep(max(0.0, float(warte_sekunden)))
        try:
            hist_sync.historie_nachziehen_alle(
                state.immutable_cache_dir,
                values=state.env().values(),
                on_log=lambda t: print(t, flush=True),
                force=False,
            )
        except Exception as exc:
            print(f"Kurs-Historie-Nachzug: {exc}", flush=True)

    threading.Thread(
        target=_lauf, name="satsage-price-history-sync", daemon=True,
    ).start()
