"""Log-Bereich der Oberfläche, zusätzlich als Datei unter tmp/.

Die Zeilen sind dieselben, die im Log-Bereich stehen. tmp/ ist gitignored
und nur für die spätere Auswertung auf diesem Rechner.
"""
from __future__ import annotations

import threading
from pathlib import Path

from core.paths import app_dir

_LOCK = threading.Lock()
_MAX = 8_000_000
_BEHALTEN = 2_000_000


def datei() -> Path:
    return app_dir() / "tmp" / "logbereich.log"


def api_logbereich(_state, body: dict | None) -> dict:
    zeilen = body.get("zeilen") if isinstance(body, dict) else None
    if not isinstance(zeilen, list):
        zeilen = []
    schreibe(zeilen[:200])
    return {"ok": True}


def schreibe(zeilen: list[dict]) -> None:
    """Hängt Zeilen an. Jede Zeile: t, text, optional wallet."""
    bloecke: list[str] = []
    for eintrag in zeilen:
        if not isinstance(eintrag, dict):
            continue
        text = str(eintrag.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        zeit = str(eintrag.get("t") or "").strip() or "--:--:--"
        name = str(eintrag.get("wallet") or "").replace("\n", " ").strip()
        if name:
            bloecke.append(f"{zeit}  {name}  {text}\n")
        else:
            bloecke.append(f"{zeit}  {text}\n")
    if not bloecke:
        return
    ziel = datei()
    daten = "".join(bloecke).encode("utf-8")
    with _LOCK:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        with ziel.open("ab") as handle:
            handle.write(daten)
        if ziel.stat().st_size > _MAX:
            roh = ziel.read_bytes()
            ziel.write_bytes(roh[-_BEHALTEN:])
