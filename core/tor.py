"""
Lokaler Tor-SOCKS, ohne Tor-Browser-Fenster.

Ablauf, sobald eine .onion-Adresse angefasst wird:

1. Schon laufender Proxy (konfiguriert, sonst 9150 / 9050) wird genutzt.
2. Sonst startet SatSage ein gefundenes ``tor``-Binary — typisch das im
   Tor-Browser-Ordner, aber ohne Firefox und ohne „Verbinden“-Klick.
3. Warten, bis der SOCKS-Port spricht (erster Bootstrap kann eine Minute
   dauern). Der Prozess gehört uns und endet mit dem Programm.

Kein Tor wird heruntergeladen. Ohne Binary bleibt der bisherige Hinweis.
Abschalten: ``TOR_AUTOSTART=0``. Eigenes Binary: ``TOR_BINARY``.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from core.paths import app_dir

TOR_SOCKS_HOST = "127.0.0.1"
TOR_BROWSER_SOCKS_PORT = 9150
TOR_DAEMON_SOCKS_PORT = 9050
TOR_CHECK_TIMEOUT = 2
TOR_BOOTSTRAP_TIMEOUT = 90.0
TOR_BROWSER_DOWNLOAD = "https://www.torproject.org/download/"

_started: subprocess.Popen[str] | None = None
_started_lock = threading.Lock()
_log_tail: list[str] = []

#: Erfolgreicher SOCKS-Fund — TTL spart Dauer-„Prüfe Tor-SOCKS“-Spam
#: (Peer-Takt + parallele Jobs + Reconnects).
_socks_ok_cache: dict[tuple[str, int], tuple[float, tuple[str, int]]] = {}
_socks_ok_lock = threading.Lock()
SOCKS_OK_CACHE_TTL_S = 90.0


class TorFehler(RuntimeError):
    """Tor nicht erreichbar und nicht startbar."""


def socks_erreichbar(
    host: str,
    port: int,
    timeout: float = TOR_CHECK_TIMEOUT,
) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _autostart_erlaubt(env: dict[str, str] | None) -> bool:
    # Explizites env-Dict (auch leer) sticht os.environ — sonst ziehen
    # Tests/Aufrufer mit env={} versehentlich TOR_AUTOSTART aus der Shell.
    if env is not None:
        raw = (env.get("TOR_AUTOSTART") or "").strip()
    else:
        raw = os.environ.get("TOR_AUTOSTART", "").strip()
    if not raw:
        return True
    return raw.lower() not in ("0", "false", "nein", "no", "off")


def _explizites_binary(env: dict[str, str] | None) -> str:
    if env:
        raw = (env.get("TOR_BINARY") or "").strip()
        if raw:
            return raw
    return os.environ.get("TOR_BINARY", "").strip()


def _sieht_nach_tor_browser_aus(name: str) -> bool:
    """„Tor Browser.app“, „tor-browser“, nicht qBittorrent/uTorrent."""
    n = name.lower()
    if n.endswith(".app"):
        n = n[:-4]
    n = n.replace("_", " ").replace("-", " ")
    return n == "tor" or n.startswith("tor browser")


def _unix_rel_tor(wurzel: Path) -> list[Path]:
    """macOS-.app und entpackter Linux-Tor-Browser unter einer Wurzel."""
    return [
        wurzel / "Contents" / "MacOS" / "Tor" / "tor",
        wurzel / "Contents" / "MacOS" / "Tor" / "tor.real",
        wurzel / "Contents" / "Resources" / "TorBrowser" / "Tor" / "tor",
        wurzel / "Contents" / "Resources" / "TorBrowser" / "Tor" / "tor.real",
        wurzel / "Browser" / "TorBrowser" / "Tor" / "tor",
        wurzel / "Tor" / "tor",
    ]


def _kinder_mit_tor_browser(wurzel: Path) -> list[Path]:
    try:
        kinder = list(wurzel.iterdir()) if wurzel.is_dir() else []
    except OSError:
        return []
    return [kind for kind in kinder if kind.is_dir() and _sieht_nach_tor_browser_aus(kind.name)]


def _kandidaten() -> list[Path]:
    """Übliche Orte für tor.exe / tor — kein rekursiver Plattenlauf."""
    if sys.platform == "win32":
        rels = (
            Path("Tor Browser") / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
            Path("TorBrowser") / "Tor" / "tor.exe",
            Path("Tor") / "tor.exe",
        )
        wurzeln: list[Path] = []
        for key in (
            "USERPROFILE",
            "LOCALAPPDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMDATA",
        ):
            wert = os.environ.get(key)
            if wert:
                wurzeln.append(Path(wert))
        home = Path.home()
        wurzeln.extend((
            home / "Desktop",
            home / "Downloads",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Downloads",
            Path("C:/"),
        ))
        gefunden: list[Path] = []
        for wurzel in wurzeln:
            for rel in rels:
                gefunden.append(wurzel / rel)
            # Ein Ordner tiefer: „Tor Browser“ auf dem Desktop o. ä.
            try:
                kinder = list(wurzel.iterdir()) if wurzel.is_dir() else []
            except OSError:
                kinder = []
            for kind in kinder:
                if kind.is_dir() and "tor" in kind.name.lower():
                    gefunden.append(
                        kind / "Browser" / "TorBrowser" / "Tor" / "tor.exe"
                    )
                    gefunden.append(kind / "Tor" / "tor.exe")
        return gefunden

    gefunden = [
        Path("/usr/bin/tor"),
        Path("/usr/sbin/tor"),
        Path("/usr/local/bin/tor"),
        Path("/opt/homebrew/bin/tor"),
        Path("/opt/homebrew/opt/tor/bin/tor"),
        Path("/usr/local/opt/tor/bin/tor"),
        Path("/opt/local/bin/tor"),
    ]
    home = Path.home()
    feste_browser = (
        Path("/Applications") / "Tor Browser.app",
        home / "Applications" / "Tor Browser.app",
        home / "Desktop" / "Tor Browser.app",
        home / "Downloads" / "Tor Browser.app",
        home / "tor-browser",
    )
    for app in feste_browser:
        gefunden.extend(_unix_rel_tor(app))
    for ordner in (
        Path("/Applications"),
        home / "Applications",
        home / "Desktop",
        home / "Downloads",
    ):
        for kind in _kinder_mit_tor_browser(ordner):
            gefunden.extend(_unix_rel_tor(kind))
    return gefunden


def finde_tor_binary(explizit: str | None = None) -> Path | None:
    """Erst TOR_BINARY / PATH, dann Tor-Browser- und Dienst-Pfade."""
    if explizit:
        pfad = Path(explizit).expanduser()
        if pfad.is_file():
            return pfad
    which = shutil.which("tor.exe" if sys.platform == "win32" else "tor")
    if which:
        return Path(which)
    gesehen: set[Path] = set()
    for kandidat in _kandidaten():
        try:
            aufgeloest = kandidat.resolve()
        except OSError:
            continue
        if aufgeloest in gesehen:
            continue
        gesehen.add(aufgeloest)
        if aufgeloest.is_file():
            return aufgeloest
    return None


def erkenne_tor_socks(
    konfiguriert: tuple[str, int] | None = None,
) -> tuple[str, int] | None:
    """Laufender SOCKS: zuerst der konfigurierte, dann Browser, dann Dienst."""
    host, port = konfiguriert or (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT)
    if socks_erreichbar(host, port):
        return host, port
    fallbacks = (
        (TOR_SOCKS_HOST, TOR_BROWSER_SOCKS_PORT),
        (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT),
    )
    for fb in fallbacks:
        if fb != (host, port) and socks_erreichbar(*fb):
            return fb
    return None


def _datenverzeichnis() -> Path:
    ziel = app_dir() / "tor_data"
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def _tor_kommando(binary: Path, socks_port: int) -> list[str]:
    daten = _datenverzeichnis()
    return [
        str(binary),
        "--ignore-missing-torrc",
        "--ClientOnly", "1",
        "--SocksPort", f"{TOR_SOCKS_HOST}:{socks_port}",
        "--DataDirectory", str(daten),
        "--Log", "notice stdout",
    ]


def _popen_kwargs() -> dict:
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def _lese_stdout(proc: subprocess.Popen[str]) -> None:
    stream = proc.stdout
    if stream is None:
        return
    try:
        for zeile in stream:
            text = zeile.rstrip()
            if text:
                _log_tail.append(text)
                if len(_log_tail) > 80:
                    del _log_tail[:-40]
    except (OSError, ValueError):
        return


def _bootstrap_stand() -> str | None:
    for zeile in reversed(_log_tail):
        if "Bootstrapped" in zeile:
            return zeile
    return None


_BOOTSTRAP_PROZENT_RE = re.compile(r"Bootstrapped\s+(\d+)%", re.IGNORECASE)


def _bootstrap_prozent() -> int | None:
    """Letzter bekannter Tor-Bootstrap in Prozent, sonst ``None``."""
    stand = _bootstrap_stand()
    if not stand:
        return None
    m = _BOOTSTRAP_PROZENT_RE.search(stand)
    return int(m.group(1)) if m else None


def _bootstrap_fertig() -> bool:
    prozent = _bootstrap_prozent()
    return prozent is not None and prozent >= 100


def _atexit_stop() -> None:
    stoppe_eigenes_tor()


def stoppe_eigenes_tor() -> None:
    """Beendet nur den von uns gestarteten Prozess."""
    global _started
    with _started_lock:
        proc = _started
        _started = None
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _starte_tor(
    binary: Path,
    socks_port: int,
    timeout: float,
    log: Callable[[str], None] | None,
) -> subprocess.Popen[str]:
    global _started
    cmd = _tor_kommando(binary, socks_port)
    if log:
        log(f"Starte Tor ({binary}) — SOCKS {TOR_SOCKS_HOST}:{socks_port}")
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs())
    except OSError as exc:
        raise TorFehler(f"Tor-Binary ließ sich nicht starten: {exc}") from exc

    threading.Thread(target=_lese_stdout, args=(proc,), daemon=True).start()
    atexit.register(_atexit_stop)

    deadline = time.monotonic() + timeout
    letzte_meldung = ""
    socks_offen = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            rest = "\n".join(_log_tail[-8:]) or f"Exit-Code {proc.returncode}"
            raise TorFehler(f"Tor ist sofort beendet:\n{rest}")
        if not socks_offen and socks_erreichbar(TOR_SOCKS_HOST, socks_port):
            socks_offen = True
            if log:
                stand = _bootstrap_stand()
                log(stand or f"Tor-SOCKS lauscht auf {TOR_SOCKS_HOST}:{socks_port}")
                if not _bootstrap_fertig():
                    log("Warte auf Tor-Bootstrap (100 %), bevor .onion genutzt wird…")
        stand = _bootstrap_stand()
        if log and stand and stand != letzte_meldung:
            log(stand)
            letzte_meldung = stand
        # SOCKS allein reicht nicht: Tor öffnet den Port schon bei 0 %,
        # Onion-Circuits kommen erst mit Bootstrapped 100 %.
        if socks_offen and _bootstrap_fertig():
            with _started_lock:
                _started = proc
            return proc
        time.sleep(0.4)

    if socks_offen:
        # Degraded: SOCKS da, Circuit noch nicht — Aufrufer dürfen trotzdem
        # versuchen; Logs zeigen den Stand. Besser als hart abbrechen, wenn
        # das Netz nur langsam bootstrapped.
        if log:
            stand = _bootstrap_stand() or "Bootstrap unvollständig"
            log(
                f"Tor-SOCKS offen, aber nach {int(timeout)}s noch nicht 100 % "
                f"({stand}). Onion-Verbindungen können scheitern."
            )
        with _started_lock:
            _started = proc
        return proc

    proc.terminate()
    raise TorFehler(
        f"Tor hat nach {int(timeout)}s noch keinen SOCKS-Port geöffnet. "
        "Netzwerk/Firewall prüfen oder Tor Browser einmalig starten, "
        "damit das Binary gefunden wird."
    )


def _socks_cache_key(konfiguriert: tuple[str, int] | None) -> tuple[str, int]:
    return konfiguriert or (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT)


def _socks_cache_get(
    konfiguriert: tuple[str, int] | None,
) -> tuple[str, int] | None:
    """Gecachter SOCKS, still mit kurzem TCP-Ping verifiziert."""
    key = _socks_cache_key(konfiguriert)
    jetzt = time.monotonic()
    with _socks_ok_lock:
        eintrag = _socks_ok_cache.get(key)
    if not eintrag:
        return None
    ts, proxy = eintrag
    if jetzt - ts > SOCKS_OK_CACHE_TTL_S:
        return None
    # Kurzer stiller Ping — kein Log.
    if socks_erreichbar(proxy[0], proxy[1], timeout=0.4):
        return proxy
    with _socks_ok_lock:
        _socks_ok_cache.pop(key, None)
    return None


def _socks_cache_set(
    konfiguriert: tuple[str, int] | None,
    proxy: tuple[str, int],
) -> None:
    key = _socks_cache_key(konfiguriert)
    with _socks_ok_lock:
        _socks_ok_cache[key] = (time.monotonic(), proxy)


def stelle_tor_socks_bereit(
    konfiguriert: tuple[str, int] | None = None,
    *,
    env: dict[str, str] | None = None,
    starten: bool = True,
    timeout: float = TOR_BOOTSTRAP_TIMEOUT,
    log: Callable[[str], None] | None = None,
) -> tuple[str, int]:
    """
    Liefert einen erreichbaren SOCKS5-Endpunkt.

    Startet bei Bedarf ein lokales Tor. Wirft :class:`TorFehler`, wenn weder
    ein Proxy läuft noch eines startbar ist.

    Erfolgreiche Funde werden kurz gecacht (``SOCKS_OK_CACHE_TTL_S``), damit
    parallele Jobs und der Peer-Takt nicht dauernd „Prüfe Tor-SOCKS…“ spammen.
    """
    ziel = konfiguriert or (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT)

    gecacht = _socks_cache_get(konfiguriert)
    if gecacht is not None:
        return gecacht

    if log:
        log(f"Prüfe Tor-SOCKS {ziel[0]}:{ziel[1]}…")
    gefunden = erkenne_tor_socks(konfiguriert)
    if gefunden is not None:
        if log and konfiguriert and gefunden != konfiguriert:
            log(
                f"Tor-SOCKS {gefunden[0]}:{gefunden[1]} "
                f"(in .env: {konfiguriert[0]}:{konfiguriert[1]})"
            )
        elif log:
            log(f"Tor-SOCKS {gefunden[0]}:{gefunden[1]} erreichbar")
        _socks_cache_set(konfiguriert, gefunden)
        return gefunden

    darf = starten and _autostart_erlaubt(env)
    if not darf:
        raise TorFehler(
            "Kein Tor-SOCKS-Proxy erreichbar (Autostart aus). "
            f"Tor Browser starten oder Dienst auf {TOR_SOCKS_HOST}:{TOR_DAEMON_SOCKS_PORT}."
        )

    if log:
        log("Kein laufender Tor-SOCKS — suche Binary…")
    binary = finde_tor_binary(_explizites_binary(env) or None)
    if binary is None:
        raise TorFehler(
            "Kein Tor-Binary gefunden. Einmal den Tor Browser installieren "
            f"({TOR_BROWSER_DOWNLOAD}) — SatSage startet dann nur dessen "
            "tor-Binary (macOS: Tor Browser.app), ohne das Browser-Fenster. "
            "Oder TOR_BINARY setzen."
        )

    with _started_lock:
        schon = _started
    if schon is not None and schon.poll() is None:
        if socks_erreichbar(TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT):
            proxy = (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT)
            _socks_cache_set(konfiguriert, proxy)
            return proxy

    _starte_tor(binary, TOR_DAEMON_SOCKS_PORT, timeout, log)
    proxy = (TOR_SOCKS_HOST, TOR_DAEMON_SOCKS_PORT)
    _socks_cache_set(konfiguriert, proxy)
    return proxy
