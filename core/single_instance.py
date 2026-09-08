"""
Ein-Instanz-Hilfe: Prozess auf einem TCP-Port finden und SatSage-Instanzen beenden.

Wenn ``satsage-webgui`` / ``server.py`` versehentlich doppelt startet, gibt der
zweite Start den Port frei (SIGTERM/taskkill) und bindet neu.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _cmdline(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        if sys.platform == "win32":
            fertig = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return (fertig.stdout or "").strip()
        # macOS / Linux
        fertig = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return (fertig.stdout or "").strip()
    except Exception:
        return ""


def ist_satsage_prozess(pid: int) -> bool:
    """True, wenn die Kommandozeile nach SatSage-Web-GUI aussieht."""
    if pid <= 0 or pid == os.getpid():
        return False
    cmd = _cmdline(pid).lower()
    if not cmd:
        return False
    marken = (
        "satsage-webgui",
        "satsage_webgui",
        "server.py",
        "packaging/satsage",
    )
    return any(m in cmd for m in marken)


def pids_auf_port(port: int, host: str = "127.0.0.1") -> list[int]:
    """PIDs, die auf host:port (TCP LISTEN) lauschen."""
    port = int(port)
    pids: list[int] = []
    try:
        if sys.platform == "win32":
            fertig = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            nadel = f":{port}"
            for zeile in (fertig.stdout or "").splitlines():
                if "LISTENING" not in zeile.upper():
                    continue
                if nadel not in zeile:
                    continue
                teile = zeile.split()
                if not teile:
                    continue
                try:
                    pid = int(teile[-1])
                except ValueError:
                    continue
                if pid > 0:
                    pids.append(pid)
        else:
            # lsof: -sTCP:LISTEN, numerisch, nur TCP
            fertig = subprocess.run(
                [
                    "lsof",
                    "-nP",
                    f"-iTCP@{host}:{port}",
                    "-sTCP:LISTEN",
                    "-t",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for zeile in (fertig.stdout or "").splitlines():
                zeile = zeile.strip()
                if zeile.isdigit():
                    pids.append(int(zeile))
            if not pids:
                # Fallback ohne Host-Filter
                fertig = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                for zeile in (fertig.stdout or "").splitlines():
                    zeile = zeile.strip()
                    if zeile.isdigit():
                        pids.append(int(zeile))
    except Exception:
        return []
    # unique, stable
    gesehen: set[int] = set()
    out: list[int] = []
    for p in pids:
        if p not in gesehen:
            gesehen.add(p)
            out.append(p)
    return out


def _beende_pid(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=8,
                check=False,
            )
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            deadline = time.time() + 3.0
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    return
                time.sleep(0.1)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass


def port_freigeben_satsage(
    port: int,
    host: str = "127.0.0.1",
    *,
    nur_satsage: bool = True,
) -> list[int]:
    """
    Beendet lauschende Prozesse auf host:port.

    Default nur SatSage-ähnliche Kommandozeilen. Liefert beendete PIDs.
    """
    beendet: list[int] = []
    for pid in pids_auf_port(port, host=host):
        if pid == os.getpid():
            continue
        if nur_satsage and not ist_satsage_prozess(pid):
            continue
        _beende_pid(pid)
        beendet.append(pid)
    if beendet:
        # TIME_WAIT / Kernel: kurz warten, dann Port prüfen
        deadline = time.time() + 4.0
        while time.time() < deadline:
            rest = [
                p
                for p in pids_auf_port(port, host=host)
                if p != os.getpid() and (not nur_satsage or ist_satsage_prozess(p))
            ]
            if not rest:
                break
            time.sleep(0.15)
    return beendet


def binary_name() -> str:
    return Path(sys.argv[0]).name if sys.argv else "satsage-webgui"
