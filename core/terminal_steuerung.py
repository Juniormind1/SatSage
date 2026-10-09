"""
Terminal-Steuerung für die Web-GUI (ANSI, stdlib).

Menü als feste Fußzeile (Scrollregion): Log scrollt darüber, die Leiste
bleibt sichtbar und wird periodisch bzw. bei Job-Wechsel neu gezeichnet.
Job-Log (wie im Web-Log) wird parallel nach stdout gespiegelt.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from typing import Any, TextIO

#: ``httpd.shutdown()`` darf den Menü-Thread nicht blockieren (Windows:
#: ``serve_forever`` wacht erst am ``poll_interval`` auf; Request-Threads
#: können in Socket-Timeouts stecken).
_HTTPD_SHUTDOWN_TIMEOUT_S = 1.0

_HARTES_ENDE_ATEXIT_GESETZT = False

#: Aktive ANSI-Fußleiste + Tees — Taste 3 muss die Scrollregion lösen,
#: bevor noch eine Log-Zeile die Leiste neu zeichnet.
_aktive_fussleiste: Fussleiste | None = None
_aktive_tees: tuple[Any, ...] = ()

#: Nach Taste 3 / Strg+C: Probe-Threads dürfen stdout nicht mehr anfassen.
#: Sonst landet z. B. „9050) — erreichbar“ in der schon gelösten Scrollregion
#: und die Windows-Konsole bleibt kaputt.
_AUSGABE_STUMM = False


LOG_PUFFER_MAX = 400
LOG_PANE_ZEILEN = 18
FUSS_ZEILEN = 3
FUSS_REFRESH_S = 1.0


class LogPuffer:
    """Ringpuffer der letzten Log-Zeilen (für Status-Anzeige)."""

    def __init__(self, *, max_zeilen: int = LOG_PUFFER_MAX):
        self._zeilen: deque[str] = deque(maxlen=max_zeilen)
        self._lock = threading.Lock()

    def anhaengen(self, zeile: str) -> None:
        text = (zeile or "").rstrip("\n")
        if not text:
            return
        with self._lock:
            self._zeilen.append(text)

    def letzte(self, n: int = LOG_PANE_ZEILEN) -> list[str]:
        with self._lock:
            if n <= 0:
                return list(self._zeilen)
            return list(self._zeilen)[-n:]


class StdoutTee:
    """Schreibt parallel in Original-Stream und Log-Puffer."""

    def __init__(self, original: TextIO, puffer: LogPuffer):
        self._original = original
        self._puffer = puffer
        self._lock = threading.Lock()
        self._rest = ""
        self._nach_zeile: Any = None
        self._fuss: Any = None

    def setze_fussleiste(self, fuss: Any) -> None:
        """Fußleiste: Log-Schreiben stellt den Cursor in die Scrollregion."""
        self._fuss = fuss

    def setze_nach_zeile(self, fn: Any) -> None:
        """Optional: nach jeder vollständigen Zeile (z. B. Fuß neuzeichnen)."""
        self._nach_zeile = fn

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if _AUSGABE_STUMM:
            return len(data)
        fertig = 0
        with self._lock:
            if _AUSGABE_STUMM:
                return len(data)
            if self._fuss is not None:
                self._fuss.schreibe_log_text(data)
            else:
                self._original.write(data)
            gebündelt = self._rest + data
            teile = gebündelt.split("\n")
            self._rest = teile[-1]
            for stueck in teile[:-1]:
                if stueck.strip():
                    self._puffer.anhaengen(stueck)
                fertig += 1
        if fertig and self._nach_zeile is not None:
            try:
                self._nach_zeile()
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        with self._lock:
            self._original.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", None) or "utf-8"

    def fileno(self) -> int:
        return self._original.fileno()


class _StummesStdout:
    """Nach Taste 3: print() von Probe-Threads verwerfen, Konsole nicht anfassen."""

    def __init__(self, original: TextIO):
        self._original = original

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        return len(data)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return bool(getattr(self._original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", None) or "utf-8"

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, name: str):
        return getattr(self._original, name)


def _stumme_ausgabe() -> None:
    """Stdout/Tee/Fußleiste: keine Zeichen mehr an die Konsole."""
    global _AUSGABE_STUMM
    _AUSGABE_STUMM = True


def _ausgabe_ist_stumm() -> bool:
    return bool(_AUSGABE_STUMM)


def _stdout_nach_ende(original: TextIO) -> TextIO:
    """Nach Beenden originalen Stream nicht zurückgeben — Probe-print bleibt tot."""
    if _AUSGABE_STUMM:
        return _StummesStdout(original)  # type: ignore[return-value]
    return original


def _schreibe_direkt(text: str) -> None:
    """An die echte Konsole, auch wenn der Tee schon stumm ist."""
    try:
        sys.__stdout__.write(text)
        sys.__stdout__.flush()
        return
    except Exception:
        pass
    try:
        os.write(1, text.encode("utf-8", "replace"))
    except Exception:
        pass


def format_job_log_zeile(job: Any, text: str) -> str:
    from core.log_i18n import translate_line

    stempel = datetime.now().strftime("%H:%M:%S")
    label = (getattr(job, "label", None) or getattr(job, "kind", None) or "Job")
    inhalt = translate_line((text or "").strip())
    return f"{stempel}  {label} · {inhalt}"


def _jobs_laufend(state: Any) -> list[Any]:
    try:
        return [j for j in state.jobs.list() if j.status == "running"]
    except Exception:
        return []


def _job_kurzzeile(job: Any) -> str:
    """Eine Zeile: Art · Label · letzte Meldung (für Bestätigung / Status)."""
    from core.log_i18n import translate_line

    try:
        d = job.as_dict() if hasattr(job, "as_dict") else {}
    except Exception:
        d = {}
    kind = (d.get("kind") or getattr(job, "kind", "") or "?").strip()
    label = (d.get("label") or getattr(job, "label", "") or kind).strip()
    msg = translate_line((d.get("message") or "").strip())
    if len(msg) > 50:
        msg = msg[:49] + "…"
    # Auto-Jobs klar kennzeichnen (Web-Nav zeigt sie nicht)
    auto = ""
    if kind in ("headers", "wallet_sync"):
        auto = " [auto]"
    zeile = f"    · {kind}{auto}: {label}"
    if msg:
        zeile += f" — {msg}"
    return zeile


def _drucke_laufende_jobs(state: Any, *, einleitung: str | None = None) -> list[Any]:
    """Listet laufende Jobs und gibt die Liste zurück."""
    laufend = _jobs_laufend(state)
    if einleitung:
        print(einleitung, flush=True)
    if not laufend:
        print("    (keine)", flush=True)
        return laufend
    for job in laufend:
        print(_job_kurzzeile(job), flush=True)
    return laufend


def _windows_vt_aktivieren() -> bool:
    """Schaltet Virtual-Terminal-Processing für ANSI-Escapes frei (Win10+)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(-11)
        invalid = ctypes.c_void_p(-1).value
        if not handle or handle == invalid:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        neu = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if neu == mode.value:
            return True
        return bool(
            kernel32.SetConsoleMode(ctypes.c_void_p(handle), neu)
        )
    except Exception:
        return False


def _ansi_ok(stream: TextIO) -> bool:
    if not getattr(stream, "isatty", lambda: False)():
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    # Windows: ANSI-Fußzeile braucht VT-Modus (Win10+ / Windows Terminal).
    # Abschalten: SATSAGE_ANSI_MENU=0 — dann Fallback auf input()-Menü.
    if sys.platform == "win32":
        flag = os.environ.get("SATSAGE_ANSI_MENU", "1").strip().lower()
        if flag in ("0", "false", "no", "nein", "off"):
            return False
        if not _windows_vt_aktivieren():
            return False
    return True


def _ansi_reset_bytes(hoehe: int) -> bytes:
    """
    Volle Scrollregion, Fußzeilen leer, Cursor bleibt auf der Log-Position.

    Nicht an den Fensterrand springen — sonst entsteht nach „Beende Server…“
    eine Lücke bis „Beendet.“ am unteren Rand.
    """
    hoehe = max(int(hoehe), FUSS_ZEILEN + 1)
    start = max(1, hoehe - FUSS_ZEILEN + 1)
    # DECSTBM setzt den Cursor auf (1,1). Deshalb zuerst speichern.
    teile = [
        "\033[s",
        f"\033[1;{hoehe}r",
        "\033[0m",
        "\033[?25h",
        "\033[?7h",
    ]
    for i in range(FUSS_ZEILEN):
        teile.append(f"\033[{start + i};1H\033[2K")
    teile.append("\033[u")
    return "".join(teile).encode("ascii")


def _windows_konsole_zuruecksetzen() -> bool:
    """
    DECSTBM und Cursor über die Console-API — die Sequenz muss in dem
    conhost ankommen, den PowerShell nach Prozessende weiterbenutzt.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class COORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

        class SMALL_RECT(ctypes.Structure):
            _fields_ = [
                ("Left", wintypes.SHORT),
                ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT),
                ("Bottom", wintypes.SHORT),
            ]

        class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
            _fields_ = [
                ("dwSize", COORD),
                ("dwCursorPosition", COORD),
                ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD),
            ]

        _windows_vt_aktivieren()
        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel32.GetStdHandle(-11)
        invalid = ctypes.c_void_p(-1).value
        if not handle or handle == invalid:
            return False
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not kernel32.GetConsoleScreenBufferInfo(
            ctypes.c_void_p(handle), ctypes.byref(info),
        ):
            return False
        fenster = max(1, int(info.srWindow.Bottom) - int(info.srWindow.Top) + 1)
        # DECSTBM homed den Cursor. Position vor CSI merken und danach
        # wiederherstellen — sonst steht „Beendet.“ in Zeile 1.
        pos = COORD(info.dwCursorPosition.X, info.dwCursorPosition.Y)
        fuss_start = int(info.srWindow.Bottom) - FUSS_ZEILEN + 1
        if pos.Y >= fuss_start:
            pos = COORD(0, max(int(info.srWindow.Top), fuss_start - 1))
        seq = f"\x1b[1;{fenster}r\x1b[0m\x1b[?25h\x1b[?7h"
        geschrieben = wintypes.DWORD(0)
        kernel32.WriteConsoleW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        kernel32.WriteConsoleW(
            ctypes.c_void_p(handle),
            seq,
            len(seq),
            ctypes.byref(geschrieben),
            None,
        )

        class CONSOLE_CURSOR_INFO(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("bVisible", wintypes.BOOL),
            ]

        cursor = CONSOLE_CURSOR_INFO(25, True)
        kernel32.SetConsoleCursorInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(CONSOLE_CURSOR_INFO),
        ]
        kernel32.SetConsoleCursorInfo(
            ctypes.c_void_p(handle), ctypes.byref(cursor),
        )
        kernel32.SetConsoleCursorPosition.argtypes = [ctypes.c_void_p, COORD]
        kernel32.SetConsoleCursorPosition(ctypes.c_void_p(handle), pos)
        return True
    except Exception:
        return False


def _ansi_terminal_zuruecksetzen(stream: TextIO) -> None:
    """Scrollregion, Attribute und Cursor — sonst bleibt die Konsole kaputt."""
    try:
        stream.flush()
    except Exception:
        pass
    hoehe = 24
    try:
        hoehe = shutil.get_terminal_size(fallback=(80, 24)).lines
    except Exception:
        pass
    try:
        if stream.isatty():
            _windows_konsole_zuruecksetzen()
    except Exception:
        pass
    roh = _ansi_reset_bytes(hoehe)
    try:
        fd = stream.fileno()
        os.write(fd, roh)
        try:
            stream.flush()
        except Exception:
            pass
        return
    except Exception:
        pass
    try:
        stream.write(roh.decode("ascii"))
        stream.flush()
    except Exception:
        pass


def _loese_terminal_fuss() -> None:
    """Fußleiste und Log-Spiegel aus, bevor nach Taste 3 noch etwas druckt."""
    global _aktive_fussleiste, _aktive_tees
    for tee in _aktive_tees:
        try:
            tee.setze_nach_zeile(None)
        except Exception:
            pass
    fuss = _aktive_fussleiste
    if fuss is not None:
        try:
            fuss.deaktivieren()
        except Exception:
            pass
    for tee in _aktive_tees:
        try:
            tee.setze_fussleiste(None)
        except Exception:
            pass
    _aktive_fussleiste = None
    _aktive_tees = ()
    try:
        from core.jobs import setze_log_spiegel

        setze_log_spiegel(None)
    except Exception:
        pass


class Fussleiste:
    """
    Feste Menüzeilen am unteren Rand per ANSI-Scrollregion.

    Log und normale Ausgaben scrollen nur oberhalb; die Fußzeilen bleiben.
    """

    def __init__(self, stream: TextIO, adresse: str, state: Any):
        self._stream = stream
        self._adresse = adresse
        self._state = state
        self._aktiv = False
        self._lock = threading.Lock()
        self._letzte_jobs = -1
        self._letzte_zeichnung = 0.0
        self._hinweis = "Taste 1–3"
        # True = Cursor steht auf der Menüzeile; ESC[s] hält die Log-Position.
        self._cursor_auf_menue = False

    def aktivieren(self) -> bool:
        if not _ansi_ok(self._stream):
            return False
        hoehe = shutil.get_terminal_size(fallback=(80, 24)).lines
        if hoehe < FUSS_ZEILEN + 5:
            return False
        # Scrollregion: Zeilen 1 .. (Höhe − Fuß)
        oben = hoehe - FUSS_ZEILEN
        self._stream.write(f"\033[1;{oben}r")
        self._stream.flush()
        self._aktiv = True
        self.zeichnen(erzwingen=True)
        return True

    def deaktivieren(self) -> None:
        with self._lock:
            if not self._aktiv:
                return
            if self._cursor_auf_menue:
                self._stream.write("\033[u")
                self._cursor_auf_menue = False
            self._aktiv = False
            _ansi_terminal_zuruecksetzen(self._stream)

    def setze_hinweis(self, text: str) -> None:
        self._hinweis = text or "Taste 1–3"
        self.zeichnen(erzwingen=True)

    def schreibe_log_text(self, text: str) -> None:
        """
        Text in die Scrollregion schreiben.

        Stellt zuvor die gemerkte Log-Cursorposition wieder her, falls der
        Cursor auf der Menüzeile steht. Hält denselben Lock wie ``zeichnen``.
        Nach ``deaktivieren`` keine ESC-Sequenzen mehr — sonst bleibt die
        Scrollregion in der Windows-Konsole stehen.
        """
        with self._lock:
            if _AUSGABE_STUMM:
                return
            if not self._aktiv:
                self._stream.write(text)
                self._stream.flush()
                return
            if self._cursor_auf_menue:
                self._stream.write("\033[u")
                self._cursor_auf_menue = False
            self._stream.write(text)
            self._stream.flush()

    def zeichnen(self, *, erzwingen: bool = False) -> None:
        if not self._aktiv:
            return
        laufend = len(_jobs_laufend(self._state))
        jetzt = time.monotonic()
        if (
            not erzwingen
            and laufend == self._letzte_jobs
            and jetzt - self._letzte_zeichnung < FUSS_REFRESH_S
        ):
            return
        with self._lock:
            if not self._aktiv:
                return
            hoehe = shutil.get_terminal_size(fallback=(80, 24)).lines
            breite = shutil.get_terminal_size(fallback=(80, 24)).columns
            start = max(1, hoehe - FUSS_ZEILEN + 1)
            zeilen = self._fuss_zeilen(laufend)
            # Log-Position nur merken, solange der Cursor noch dort ist
            if not self._cursor_auf_menue:
                self._stream.write("\033[s")
            for i, zeile in enumerate(zeilen):
                self._stream.write(f"\033[{start + i};1H\033[2K{zeile}")
            # Cursor auf Menüzeile (letzte Fußzeile) — wirkt wie Eingabe-Prompt
            menue_zeile = start + len(zeilen) - 1
            spalte = min(len(zeilen[-1]) + 1, max(1, breite))
            self._stream.write(f"\033[{menue_zeile};{spalte}H")
            self._cursor_auf_menue = True
            self._stream.flush()
            self._letzte_jobs = laufend
            self._letzte_zeichnung = jetzt

    def _fuss_zeilen(self, laufend: int) -> list[str]:
        breite = shutil.get_terminal_size(fallback=(80, 24)).columns
        linie = "─" * max(20, min(breite, 80))
        from core.i18n import t

        menue = t(
            "cli.term.menu",
            n=laufend,
            hint=self._hinweis,
        )
        url = f"  {self._adresse}"
        if len(menue) > breite:
            menue = menue[: max(0, breite - 1)]
        if len(url) > breite:
            url = url[: max(0, breite - 1)]
        # Vorletzte Zeile URL, darunter Menü (Cursor landet dort)
        return [linie[:breite], url, menue]


def _schreibe_banner(adresse: str, state: Any, *, ansi_menue: bool = False) -> None:
    from core.i18n import t

    n_wallets = len(getattr(state, "entries", []) or [])
    laufend = len(_jobs_laufend(state))
    print("SatSage – know your sats", flush=True)
    print(t("cli.term.webBanner"), flush=True)
    print(f"  {adresse}", flush=True)
    print(t("cli.term.walletsJobs", w=n_wallets, j=laufend), flush=True)
    print(t("cli.term.browserOk"), flush=True)
    if ansi_menue:
        print(t("cli.term.menuHint"), flush=True)
    else:
        print(
            "  Menü: 1=Status  2=Browser  3=Beenden (dann j/n). "
            "Oder Strg+C.",
            flush=True,
        )
    print(flush=True)


def _zeige_status(state: Any, puffer: LogPuffer) -> None:
    from core.i18n import t
    from core.log_i18n import translate_line

    jobs = list(state.jobs.list())
    print(flush=True)
    print(t("cli.term.status"), flush=True)
    print(t("cli.term.config", path=getattr(state, "env_path", "—")), flush=True)
    print(t("cli.term.cache", path=getattr(state, "cache_dir", "—")), flush=True)
    print(
        t("cli.term.wallets", n=len(getattr(state, "entries", []) or [])),
        flush=True,
    )
    header = getattr(state, "header_job_id", None)
    sync = getattr(state, "wallet_sync_job_id", None)
    if header:
        print(t("cli.term.headerJob", id=header), flush=True)
    if sync:
        print(t("cli.term.walletSync", id=sync), flush=True)
    if not jobs:
        print(t("cli.term.noJobs"), flush=True)
    else:
        print(t("cli.term.jobs", n=len(jobs)), flush=True)
        for job in jobs[-12:]:
            d = job.as_dict()
            marke = {
                "running": t("cli.term.job.running"),
                "done": t("cli.term.job.done"),
                "failed": t("cli.term.job.failed"),
                "cancelled": t("cli.term.job.cancelled"),
            }.get(d["status"], d["status"])
            msg = translate_line((d.get("message") or "").strip())
            if len(msg) > 70:
                msg = msg[:69] + "…"
            kind = (d.get("kind") or "").strip()
            auto = " [auto]" if kind in ("headers", "wallet_sync") else ""
            print(
                f"    [{marke}] {kind}{auto}: {d['label']}  ({d['elapsed_s']}s)"
                + (f" — {msg}" if msg else ""),
                flush=True,
            )
            if d["status"] == "running" and d.get("log"):
                for zeile in d["log"][-5:]:
                    print(f"      · {translate_line(zeile)}", flush=True)
    print(t("cli.term.lastLog"), flush=True)
    for z in puffer.letzte(8):
        print(f"  {translate_line(z)}", flush=True)
    print(flush=True)


def _unterdruecke_executor_atexit() -> None:
    """
    ThreadPoolExecutor joint Worker beim Interpreter-Ende ohne Timeout.

    Ab Python 3.9 hängt das an ``threading._register_atexit``, nicht an
    ``atexit``. Ab 3.14 sind die Worker keine Daemons — Onion-SOCKS (bis
    180 s) hält dann die Shell fest, obwohl Taste 3 schon „Beendet.“ schrieb.
    """
    try:
        import concurrent.futures.thread as _ft
    except Exception:
        return
    try:
        _ft._threads_queues.clear()
    except Exception:
        pass
    try:
        atexit.unregister(_ft._python_exit)
    except Exception:
        pass
    try:
        callbacks = getattr(threading, "_threading_atexits", None)
        if not isinstance(callbacks, list):
            return
        def _ruft_python_exit(cb: Any) -> bool:
            for cell in getattr(cb, "__closure__", None) or ():
                try:
                    if cell.cell_contents is _ft._python_exit:
                        return True
                except Exception:
                    pass
            return False

        callbacks[:] = [cb for cb in callbacks if not _ruft_python_exit(cb)]
    except Exception:
        pass


def _hartes_ende_atexit() -> None:
    """Letzte Chance: Konsole zurücksetzen, Prozess normal beenden."""
    try:
        _loese_terminal_fuss()
    except Exception:
        pass
    try:
        _ansi_terminal_zuruecksetzen(sys.__stdout__)
    except Exception:
        pass


def plane_hartes_prozessende() -> None:
    """
    Nach Taste 3 / Strg+C: Interpreter-Ende nicht auf Probe-Sockets warten.

    ``concurrent.futures`` joined seine Worker sonst in einem atexit-Handler.
    Die Konsole wird zurückgesetzt; der Prozess endet über ``return`` /
    ``SystemExit``, nicht über ``os._exit``.
    """
    global _HARTES_ENDE_ATEXIT_GESETZT
    if _HARTES_ENDE_ATEXIT_GESETZT:
        return
    _HARTES_ENDE_ATEXIT_GESETZT = True
    _unterdruecke_executor_atexit()
    atexit.register(_hartes_ende_atexit)


def _reset_hartes_prozessende_fuer_tests() -> None:
    """Nur Tests: atexit-Handler wieder abmelden."""
    global _HARTES_ENDE_ATEXIT_GESETZT, _AUSGABE_STUMM
    _HARTES_ENDE_ATEXIT_GESETZT = False
    _AUSGABE_STUMM = False
    try:
        atexit.unregister(_hartes_ende_atexit)
    except Exception:
        pass
    try:
        import concurrent.futures.thread as _ft

        callbacks = getattr(threading, "_threading_atexits", None)
        if isinstance(callbacks, list):
            vorhanden = False
            for cb in callbacks:
                for cell in getattr(cb, "__closure__", None) or ():
                    try:
                        if cell.cell_contents is _ft._python_exit:
                            vorhanden = True
                            break
                    except Exception:
                        pass
                if vorhanden:
                    break
            if not vorhanden:
                threading._register_atexit(_ft._python_exit)
    except Exception:
        pass
    _loese_terminal_fuss()


def httpd_stopp_ohne_join(httpd: Any, *, timeout_s: float = _HTTPD_SHUTDOWN_TIMEOUT_S) -> None:
    """
    ``serve_forever`` stoppen, ohne auf Request-Threads zu warten.

    ``shutdown()`` läuft in einem Daemon-Thread — hängt er (Windows-select),
    kehrt der Menü-Thread nach *timeout_s* zurück. ``server_close`` joined
    bei ``block_on_close=False`` niemanden.
    """
    fertig = threading.Event()

    def _shutdown() -> None:
        try:
            httpd.shutdown()
        except Exception:
            pass
        finally:
            fertig.set()

    threading.Thread(
        target=_shutdown, name="satsage-http-shutdown", daemon=True,
    ).start()
    try:
        fertig.wait(timeout=max(0.1, float(timeout_s)))
    except KeyboardInterrupt:
        pass
    try:
        httpd.server_close()
    except Exception:
        pass


def _beende_server(state: Any, httpd: Any) -> None:
    # Zuerst Shutdown-Markierung + stop-Flag — laufende Browser-Requests
    # und der HTTP-Neustart-Thread sollen still enden, nicht neu speien.
    try:
        state._shutting_down = True
    except Exception:
        pass
    stop = getattr(state, "_http_stop_event", None)
    if stop is not None:
        try:
            stop.set()
        except Exception:
            pass
    try:
        from core.outbound_policy import stoppe_oeffentliche_electrum_suche

        stoppe_oeffentliche_electrum_suche(prozess_ende=True)
    except Exception:
        pass
    try:
        from core.fulcrum_transport import schliesse_offene_fulcrum_sockets

        schliesse_offene_fulcrum_sockets()
    except Exception:
        pass
    _stumme_ausgabe()
    _loese_terminal_fuss()
    plane_hartes_prozessende()
    laufend = _jobs_laufend(state)
    for job in laufend:
        try:
            label = getattr(job, "label", None) or getattr(job, "kind", "Job")
            _schreibe_direkt(f"  → Abbruch angefordert: {label}\n")
            job.cancel()
        except Exception:
            pass
    httpd_stopp_ohne_join(httpd)
    _schreibe_direkt("Beendet.\n")


def _drain_stdin() -> None:
    """Verwirft bereits gepufferte Tasten (z. B. Enter nach „3“)."""
    try:
        if sys.platform == "win32":
            import msvcrt

            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0") and msvcrt.kbhit():
                    msvcrt.getwch()
            return
        if not sys.stdin.isatty():
            return
        import select

        while select.select([sys.stdin], [], [], 0)[0]:
            if not sys.stdin.read(1):
                break
    except Exception:
        pass


def _lese_taste(timeout: float = 0.2) -> str | None:
    """Ein Zeichen von stdin, oder None bei Timeout. Nicht blockierend."""
    try:
        if sys.platform == "win32":
            import msvcrt

            ende = time.monotonic() + timeout
            while time.monotonic() < ende:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):
                        # Sondertaste: Folgebyte verwerfen
                        if msvcrt.kbhit():
                            msvcrt.getwch()
                        return None
                    return ch
                time.sleep(0.05)
            return None
        if not sys.stdin.isatty():
            time.sleep(timeout)
            return None
        import select

        bereit, _, _ = select.select([sys.stdin], [], [], timeout)
        if not bereit:
            return None
        return sys.stdin.read(1)
    except Exception:
        return None


class _CbreakStdin:
    """Unix: cbreak, damit Tasten ohne Enter ankommen."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._alt: list | None = None

    def __enter__(self) -> "_CbreakStdin":
        if sys.platform == "win32":
            return self
        try:
            if not sys.stdin.isatty():
                return self
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._alt = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:
            self._fd = None
            self._alt = None
        return self

    def __exit__(self, *_exc) -> None:
        if self._fd is None or self._alt is None:
            return
        try:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._alt)
        except Exception:
            pass


def _schreibe_menue_fuss_fallback(adresse: str, state: Any) -> None:
    """Ohne ANSI: wie zuvor ans Ende drucken."""
    laufend = len(_jobs_laufend(state))
    print(flush=True)
    print("─" * 64, flush=True)
    print(f"  {adresse}", flush=True)
    print(
        f"  1 Status   2 Browser-GUI öffnen   3 Server beenden"
        f"   · Jobs: {laufend}   · Taste 1–3:",
        flush=True,
    )


def lauf_steuerung(
    state: Any,
    httpd: Any,
    adresse: str,
    *,
    oeffne_browser_anfangs: bool = True,
) -> int:
    """
    Menüschleife; HTTP läuft parallel im Hintergrund-Thread.

    Mit ANSI: feste Fußzeile + nicht-blockierende Tasten.
    Fallback: blockierendes ``input`` wie zuvor.
    """
    global _aktive_fussleiste, _aktive_tees
    from core.jobs import setze_log_spiegel

    puffer = LogPuffer()
    original_out = sys.stdout
    original_err = sys.stderr
    tee_out = StdoutTee(original_out, puffer)
    tee_err = StdoutTee(original_err, puffer)
    sys.stdout = tee_out  # type: ignore[assignment]
    sys.stderr = tee_err  # type: ignore[assignment]

    fuss: Fussleiste | None = None

    def spiegel(job: Any, text: str) -> None:
        if _AUSGABE_STUMM:
            return
        zeile = format_job_log_zeile(job, text)
        with tee_out._lock:
            if _AUSGABE_STUMM:
                return
            if fuss is not None:
                fuss.schreibe_log_text(zeile + "\n")
            else:
                tee_out._original.write(zeile + "\n")
                tee_out._original.flush()
        puffer.anhaengen(zeile)
        if fuss is not None:
            fuss.zeichnen()

    setze_log_spiegel(spiegel)
    try:
        # Banner zuerst (noch ohne Scrollregion), dann Fußzeile aktivieren —
        # sonst landet der Banner mitten in der eingeschränkten Region.
        fuss_kandidat = Fussleiste(original_out, adresse, state)
        ansi = _ansi_ok(original_out)
        _schreibe_banner(adresse, state, ansi_menue=ansi)
        if oeffne_browser_anfangs:
            # Nach Banner: verzögert und unter Windows per os.startfile,
            # damit die Konsolen-Prozessgruppe nicht mitgerissen wird.
            _oeffne_browser_sicher(adresse)

        if ansi and fuss_kandidat.aktivieren():
            fuss = fuss_kandidat
            _aktive_fussleiste = fuss
            _aktive_tees = (tee_out, tee_err)
            tee_out.setze_fussleiste(fuss)
            tee_err.setze_fussleiste(fuss)
            tee_out.setze_nach_zeile(lambda: fuss.zeichnen() if fuss else None)
            tee_err.setze_nach_zeile(lambda: fuss.zeichnen() if fuss else None)
            return _schleife_ansi(state, httpd, adresse, puffer, fuss)

        _schreibe_menue_fuss_fallback(adresse, state)
        return _schleife_input(state, httpd, adresse, puffer)
    except Exception:
        LOGGER = __import__("logging").getLogger("satsage.terminal")
        LOGGER.exception("Terminal-Steuerung abgebrochen — Server wird beendet.")
        print("\n  ⚠️  Terminal-Menü abgestürzt — Details siehe Log. Server stoppt.", flush=True)
        _beende_server(state, httpd)
        raise
    finally:
        _loese_terminal_fuss()
        # Nach Taste 3 nicht original_out zurück — Probe-Threads würden sonst
        # noch „…9050) — erreichbar“ in die gelöste Konsole schreiben.
        sys.stdout = _stdout_nach_ende(original_out)  # type: ignore[assignment]
        sys.stderr = _stdout_nach_ende(original_err)  # type: ignore[assignment]


def _schleife_ansi(
    state: Any,
    httpd: Any,
    adresse: str,
    puffer: LogPuffer,
    fuss: Fussleiste,
) -> int:
    warte_bestaetigung = False
    fuss.setze_hinweis("Taste 1–3")
    # Ohne cbreak kommt „3“+Enter als zwei Zeichen: Bestätigung, dann sofort
    # Abbruch durch \\n — j greift nie. cbreak + Enter ignorieren behebt das.
    with _CbreakStdin():
        return _schleife_ansi_tasten(
            state, httpd, adresse, puffer, fuss, warte_bestaetigung
        )


def _schleife_ansi_tasten(
    state: Any,
    httpd: Any,
    adresse: str,
    puffer: LogPuffer,
    fuss: Fussleiste,
    warte_bestaetigung: bool,
) -> int:
    while True:
        try:
            taste = _lese_taste(0.25)

            fuss.zeichnen()

            if taste is None:
                continue
            if taste == "\x03":  # Ctrl+C
                print("\n", end="", flush=True)
                _beende_server(state, httpd)
                return 0
            # Ctrl+D: unter Unix übliches EOF/Quit. Unter Windows/ConPTY nicht —
            # dort kann \x04 spontan kommen und den Server ungewollt beenden.
            if taste == "\x04" and sys.platform != "win32":
                print("\n", end="", flush=True)
                _beende_server(state, httpd)
                return 0

            wahl = taste.lower()

            if warte_bestaetigung:
                # j/y = Server aus (Jobs abbrechen). n = weiter.
                # Enter/Space ignorieren (Rest von „3↵“ oder versehentlich).
                if wahl in ("j", "y"):
                    print("  Beende Server (breche laufende Jobs ab)…", flush=True)
                    _drucke_laufende_jobs(state, einleitung="  Noch aktiv:")
                    _beende_server(state, httpd)
                    return 0
                if wahl in ("\n", "\r", "\t"):
                    continue
                if wahl in ("n", " ", "1", "2"):
                    warte_bestaetigung = False
                    fuss.setze_hinweis("Taste 1–3")
                    print("  Abbruch — Server läuft weiter.", flush=True)
                    fuss.zeichnen(erzwingen=True)
                    continue
                # 3 während Bestätigung: Hinweis, Zustand behalten (kein Abbruch)
                print(
                    "  Bitte j (Server beenden) oder n (weiter) drücken.",
                    flush=True,
                )
                fuss.zeichnen(erzwingen=True)
                continue

            if wahl in ("1", "s"):
                _zeige_status(state, puffer)
                fuss.zeichnen(erzwingen=True)
                continue
            if wahl in ("2", "b"):
                print("  Öffne Browser…", flush=True)
                try:
                    _oeffne_browser_sicher(adresse)
                except Exception as exc:
                    print(f"  ⚠️  Browser: {exc}", flush=True)
                fuss.zeichnen(erzwingen=True)
                continue
            if wahl in ("3", "q"):
                # Rest von „3↵“ verwerfen, sonst killt Enter die Bestätigung.
                _drain_stdin()
                laufend = _jobs_laufend(state)
                if laufend:
                    warte_bestaetigung = True
                    fuss.setze_hinweis(
                        f"{len(laufend)} Job(s) — j=Server aus · n=weiter"
                    )
                    print(
                        f"  {len(laufend)} Job(s) laufen noch "
                        "(auch Auto: Header/Wallet-Sync — nicht in der Web-Nav):",
                        flush=True,
                    )
                    _drucke_laufende_jobs(state)
                    print(
                        "  Server wirklich beenden? "
                        "j = ja (bricht Jobs ab und stoppt), "
                        "n = weiterlaufen lassen",
                        flush=True,
                    )
                    fuss.zeichnen(erzwingen=True)
                    continue
                print("  Beende Server…", flush=True)
                _beende_server(state, httpd)
                return 0

            # Unbekannte Taste: ignorieren (kein Spam bei Pfeiltasten-Resten)
            if wahl.isprintable() and wahl not in ("\n", "\r", " "):
                print("  ⚠️  1, 2 oder 3 wählen.", flush=True)
                fuss.zeichnen(erzwingen=True)
        except KeyboardInterrupt:
            print("\n", end="", flush=True)
            _beende_server(state, httpd)
            return 0


def _oeffne_browser_sicher(adresse: str, *, verzoegerung_s: float = 1.2) -> None:
    """Browser öffnen ohne Windows-Konsolen-CTRL an den Server zu senden."""

    def _lauf() -> None:
        time.sleep(max(0.0, verzoegerung_s))
        try:
            if sys.platform == "win32":
                os.startfile(adresse)  # noqa: S606 — lokale http://-URL
                return
            webbrowser.open(adresse)
        except Exception:
            try:
                webbrowser.open(adresse)
            except Exception:
                pass
        finally:
            # Splash zu, sobald der Browser aufgeht — nicht erst nach dem Login.
            try:
                from httpserver.splash import _splash_schliessen

                _splash_schliessen()
            except Exception:
                pass

    threading.Thread(target=_lauf, name="satsage-open-browser", daemon=True).start()


def _warte_auf_strg_c(state: Any, httpd: Any, adresse: str) -> int:
    """HTTP läuft bereits im Hintergrund-Thread — Hauptthread nur noch halten."""
    print(flush=True)
    print("  Kein Menü (Terminal-Eingabe nicht nutzbar) — Server läuft weiter.", flush=True)
    print(f"  GUI: {adresse}", flush=True)
    print("  Beenden: Strg+C", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n", end="", flush=True)
        _beende_server(state, httpd)
        return 0


def _schleife_input(
    state: Any,
    httpd: Any,
    adresse: str,
    puffer: LogPuffer,
) -> int:
    """Fallback ohne ANSI-Scrollregion."""
    while True:
        try:
            wahl = input("Auswahl [1-3]: ").strip().lower()
        except EOFError:
            # PowerShell/ConPTY: isatty() kann True sein, input() liefert trotzdem
            # sofort EOF — Server darf deshalb nicht sterben.
            return _warte_auf_strg_c(state, httpd, adresse)
        except KeyboardInterrupt:
            print("\n", end="", flush=True)
            _beende_server(state, httpd)
            return 0

        if wahl in ("1", "s", "status"):
            _zeige_status(state, puffer)
            _schreibe_menue_fuss_fallback(adresse, state)
            continue
        if wahl in ("2", "b", "browser"):
            print("  Öffne Browser…", flush=True)
            try:
                _oeffne_browser_sicher(adresse)
            except Exception as exc:
                print(f"  ⚠️  Browser: {exc}", flush=True)
            _schreibe_menue_fuss_fallback(adresse, state)
            continue
        if wahl in ("3", "q", "quit", "exit", "ende"):
            laufend = _jobs_laufend(state)
            if laufend:
                print(
                    f"  {len(laufend)} Job(s) laufen noch "
                    "(auch Auto: Header/Wallet-Sync):",
                    flush=True,
                )
                _drucke_laufende_jobs(state)
                print(
                    "  Server beenden und Jobs abbrechen? [j/N]: ",
                    end="",
                    flush=True,
                )
                try:
                    ok = input().strip().lower() in ("j", "ja", "y", "yes")
                except (EOFError, KeyboardInterrupt):
                    ok = False
                if not ok:
                    print("  Abbruch — Server läuft weiter.", flush=True)
                    _schreibe_menue_fuss_fallback(adresse, state)
                    continue
            print("  Beende Server…", flush=True)
            _beende_server(state, httpd)
            return 0

        print("  ⚠️  1, 2 oder 3 wählen.", flush=True)
        _schreibe_menue_fuss_fallback(adresse, state)


def steuerung_sinnvoll(*, plain_console: bool = False) -> bool:
    """Ob die interaktive Terminal-Steuerung gestartet werden soll."""
    if plain_console:
        return False
    # Windows: Menü ja, aber nur input-basiert (_ansi_ok ist unter win32 aus,
    # außer SATSAGE_ANSI_MENU=1). Abschalten: --plain-console oder
    # SATSAGE_TERMINAL_MENU=0
    if sys.platform == "win32":
        flag = os.environ.get("SATSAGE_TERMINAL_MENU", "1").strip().lower()
        if flag in ("0", "false", "no", "nein", "off"):
            return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False
