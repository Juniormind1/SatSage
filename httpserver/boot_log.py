"""Start-Log der Wallet-Vorbereitung.

Die Oberfläche steht schon, während Adressen und Cache noch gelesen werden.
Jede Zeile geht sofort in den Puffer — der NDJSON-Stream der GUI wartet
nicht, bis das letzte Wallet fertig ist.
"""
from __future__ import annotations

import threading
from typing import Callable


class BootLog:
    """Kleiner Puffer plus Live-Abonnenten. Threadsicher."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zeilen: list[dict] = []
        self._seq = 0
        #: Vorbereitung durch (``fertig()``). Seit d3f85c8 endet damit nur der
        #: Start-Strom, Job-Zeilen kommen weiter in den Puffer.
        self._bereit = False
        self._hoerer: list[Callable[[dict], None]] = []
        self._ereignis = threading.Event()

    def zeile(self, text: str, *, wallet: str = "", extra: dict | None = None) -> None:
        eintrag = {"text": str(text or "").strip()}
        name = str(wallet or "").strip()
        if name:
            eintrag["wallet"] = name
        if extra:
            eintrag["extra"] = dict(extra)
        with self._lock:
            self._seq += 1
            eintrag["seq"] = self._seq
            self._zeilen.append(eintrag)
            hoerer = list(self._hoerer)
            self._ereignis.set()
        for fn in hoerer:
            try:
                fn(eintrag)
            except Exception:
                pass

    def fertig(self) -> None:
        """Vorbereitung ist durch. Der Strom bleibt für spätere Job-Zeilen offen."""
        with self._lock:
            self._bereit = True
            self._ereignis.set()

    def stand(self) -> tuple[list[dict], bool]:
        """(Zeilen, Vorbereitung durch)."""
        with self._lock:
            return list(self._zeilen), self._bereit

    def abonniere(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        """Hängt *fn* an neue Zeilen. Nach der Vorbereitung ohne Rückspiel."""
        with self._lock:
            bisher = [] if self._bereit else list(self._zeilen)
            self._hoerer.append(fn)

        def abmelden() -> None:
            with self._lock:
                try:
                    self._hoerer.remove(fn)
                except ValueError:
                    pass

        for eintrag in bisher:
            try:
                fn(eintrag)
            except Exception:
                pass
        return abmelden

    def warte(self, timeout: float) -> bool:
        """True, sobald eine neue Zeile da ist oder die Vorbereitung fertig ist."""
        with self._lock:
            if self._bereit:
                # Sonst wartete ein Strom, der erst nach der Vorbereitung
                # kommt, die volle Frist auf sein „done“.
                return True
            self._ereignis.clear()
        return self._ereignis.wait(timeout)
