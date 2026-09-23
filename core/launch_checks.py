"""
Externe Launch-Checks (CLI-Helfer).

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

from pathlib import Path


def _escape_for_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def launch_check_fulcrum_tor_external(project_dir: Path | None = None) -> None:
    """Startet check_fulcrum_tor.py in einem eigenen Terminalfenster."""
    import platform
    import shlex
    import subprocess
    import sys

    root = project_dir or Path(__file__).resolve().parent
    script = root / "check_fulcrum_tor.py"
    if not script.is_file():
        raise FileNotFoundError(f"{script.name} nicht gefunden")

    py = sys.executable
    if platform.system() == "Windows":
        inner = f'cd /d "{root}" && "{py}" "{script}"'
        subprocess.Popen(
            f'start "check_fulcrum_tor" cmd /k {inner}',
            shell=True,
            cwd=root,
        )
        return

    if platform.system() == "Darwin":
        shell_cmd = (
            f"cd {shlex.quote(str(root))} && "
            f"{shlex.quote(py)} {shlex.quote(str(script))}; "
            f"echo; read -r -p 'Enter zum Schliessen...'"
        )
        escaped = _escape_for_applescript(shell_cmd)
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f'tell application "Terminal" to do script "{escaped}"',
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                detail or "Terminal konnte nicht gestartet werden (osascript)"
            )
        return

    for term_cmd in (
        ["x-terminal-emulator", "-e", py, str(script)],
        ["gnome-terminal", "--", py, str(script)],
        ["konsole", "-e", py, str(script)],
        ["xterm", "-e", py, str(script)],
    ):
        try:
            subprocess.Popen(term_cmd, cwd=root)
            return
        except OSError:
            continue
    raise RuntimeError("Kein Terminal-Emulator gefunden")
