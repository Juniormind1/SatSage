"""
Ausführliches Lauf-Log für „vervollständigen“.

Die Web-GUI behält nur die letzten Job-Zeilen und fasst Hops zusammen.
Diese Datei schreibt jeden Schritt sofort auf die Platte, damit ein
hängender Lauf an einem komplexen UTXO nachträglich lesbar ist.

Pfad: ``app_dir()/logs/vervollstaendigen.log`` — neben der Executable
bzw. im Repo-Root. Keine XPUBs, keine Adressen, keine Wallet-Namen.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

_SPERRE = threading.Lock()
# Diagnose aus. Die Aufrufer und Spur bleiben, ein späterer Lauf setzt das
# wieder auf True und schreibt logs/vervollstaendigen.log.
AKTIV = False
_SCHRITT = threading.local()
_DATEI = "vervollstaendigen.log"
_MAX_BYTES = 8 * 1024 * 1024


def pfad() -> Path:
    from core.paths import app_dir

    ziel = app_dir() / "logs"
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel / _DATEI


def _kuerzen(txid: str) -> str:
    """Volle Kennung: die Zeile soll sich in mempool.space einfügen lassen."""
    return str(txid or "")


def setze_schritt(spur) -> None:
    """Aktive Spur für die nächsten Abruf-Schritte dieses Threads."""
    _SCHRITT.spur = spur


def schritt(text: str) -> None:
    """Feinschritt, nur solange eine Vervollständigen-Spur gesetzt ist."""
    spur = getattr(_SCHRITT, "spur", None)
    if spur is not None:
        spur.zeile(text)


def schreibe(text: str, *, txid: str = "", vout: int | None = None) -> None:
    """Eine Zeile, sofort auf die Platte. Fehler hier dürfen den Lauf nicht stoppen."""
    if not AKTIV:
        return
    zeile = str(text or "").replace("\n", " ").strip()
    if not zeile:
        return
    kopf = time.strftime("%Y-%m-%dT%H:%M:%S")
    if txid:
        kopf += f" {_kuerzen(txid)}:{int(vout or 0)}"
    try:
        with _SPERRE:
            datei = pfad()
            if datei.is_file() and datei.stat().st_size > _MAX_BYTES:
                alt = datei.with_suffix(".log.1")
                if alt.exists():
                    alt.unlink()
                datei.replace(alt)
            with datei.open("a", encoding="utf-8") as aus:
                aus.write(f"{kopf} {zeile}\n")
                aus.flush()
    except OSError:
        return


class Spur:
    """Zähler und Zeit je Hop, damit ein Stillstand im Log sichtbar wird."""

    def __init__(self, txid: str, vout: int, art: str) -> None:
        self.txid = txid
        self.vout = int(vout)
        self.art = art
        self.anfang = time.monotonic()
        self.hops = 0
        self.fehler = 0
        self.extern = 0
        self.coinbase = 0
        self.intern = 0
        self.buendel = 0
        self.memo = 0
        self.zyklus = 0
        self._letzte = self.anfang

    def zeile(self, text: str) -> None:
        schreibe(text, txid=self.txid, vout=self.vout)

    def hop(self, tiefe: int, utxo_key: str, *, quelle: str) -> None:
        self.hops += 1
        jetzt = time.monotonic()
        pause = jetzt - self._letzte
        self._letzte = jetzt
        self.zeile(
            f"hop n={self.hops} tiefe={tiefe} key={utxo_key} quelle={quelle} "
            f"seit_hop_s={pause:.1f} lauf_s={jetzt - self.anfang:.0f}"
        )

    def ende(self, status: str, extra: str = "") -> None:
        dauer = time.monotonic() - self.anfang
        self.zeile(
            f"ENDE status={status} art={self.art} dauer_s={dauer:.0f} "
            f"hops={self.hops} intern={self.intern} extern={self.extern} "
            f"coinbase={self.coinbase} buendel={self.buendel} memo={self.memo} "
            f"zyklus={self.zyklus} fehler={self.fehler}"
            + (f" {extra}" if extra else "")
        )
