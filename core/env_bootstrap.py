"""
.env-Bootstrap: Pfad, Laden und Editor-Öffnen.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.paths import app_dir

ENV_FILE = app_dir() / ".env"


def _load_dotenv(env_path: Path | None = None) -> dict[str, str]:
    """Lädt KEY=VALUE-Paare aus einer .env-Datei (ohne externe Abhängigkeit).

    *env_path* default zur Laufzeit ``ENV_FILE`` — nicht als Default-Argument
    einfrieren, sonst bleibt nach ``server --env lab/…`` die Root-``.env``
    (und z. B. ``NETWORK=main``) aktiv und setzt Regtest-Adressen zurück.

    Scrambled ``.env`` (SSGB1): Klartext nur mit Session-Key; ohne Key leeres
    Dict (wie ``EnvFile`` mit ``scramble_locked``).
    """
    if env_path is None:
        # ``server --env`` setzt ``main.ENV_FILE``; Fassade und Modul-Default
        # können auseinanderlaufen — main gewinnt, sobald geladen.
        env_path = ENV_FILE
        main_mod = sys.modules.get("main")
        if main_mod is not None:
            main_env = getattr(main_mod, "ENV_FILE", None)
            if main_env is not None:
                env_path = main_env
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values

    text = ""
    try:
        from core import env_scramble as scramble_mod

        try:
            text = scramble_mod.load_plaintext_or_scramble(env_path)
        except scramble_mod.ScrambleLocked:
            return values
        except scramble_mod.ScrambleError:
            if scramble_mod.is_env_scrambled(env_path):
                return values
            text = env_path.read_text(encoding="utf-8")
    except ImportError:
        text = env_path.read_text(encoding="utf-8")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    if values.get("NETWORK"):
        # Lazy: set_chain_network bleibt in main (Caches/Façade); kein Top-Level-Import.
        from main import set_chain_network

        set_chain_network(values.get("NETWORK"))
    return values


def _editor_from_env() -> list[str] | None:
    """EDITOR/VISUAL aus der Umgebung (Windows: posix=False für Pfade mit Leerzeichen)."""
    import os
    import platform
    import shlex

    for key in ("EDITOR", "VISUAL"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return shlex.split(raw, posix=(platform.system() != "Windows"))
    return None


def open_env_file_in_editor(env_path: Path | None = None) -> None:
    """Öffnet .env im System-Editor (blockiert bis der Editor geschlossen wird)."""
    import os
    import platform
    import shutil
    import subprocess

    if env_path is None:
        env_path = ENV_FILE
        main_mod = sys.modules.get("main")
        if main_mod is not None:
            main_env = getattr(main_mod, "ENV_FILE", None)
            if main_env is not None:
                env_path = main_env
    env_path = Path(env_path)
    if not env_path.is_file():
        example = env_path.parent / ".env.example"
        if example.is_file():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch()

    target = str(env_path.resolve())

    def _wait_editor(cmd, *, shell: bool = False) -> None:
        proc = subprocess.Popen(cmd, shell=shell, cwd=env_path.parent)
        proc.wait()

    def _run_checked(cmd: list[str]) -> None:
        subprocess.run(cmd, cwd=env_path.parent, check=True)

    def _prompt_saved() -> None:
        print("Nach dem Speichern hier Enter drücken… ", end="", flush=True)
        try:
            input()
        except EOFError:
            pass

    def _run_custom_editor(editor: list[str]) -> None:
        print(f"Öffne {env_path.name} mit {editor[0]}…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        try:
            _wait_editor([*editor, target])
        except OSError:
            quoted = " ".join(
                f'"{part}"' if " " in part else part for part in [*editor, target]
            )
            _wait_editor(quoted, shell=True)

    custom = _editor_from_env()
    if custom:
        _run_custom_editor(custom)
        return

    system = platform.system()
    if system == "Windows":
        notepad = (
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
        )
        print(f"Öffne {env_path.name} mit Notepad…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        if notepad.is_file():
            try:
                _wait_editor([str(notepad), target])
                return
            except OSError:
                pass
        try:
            _wait_editor(f'notepad.exe "{target}"', shell=True)
            return
        except OSError:
            pass
        try:
            os.startfile(target)
            print("  → Datei mit Standard-App geöffnet.", flush=True)
            _prompt_saved()
            return
        except OSError as exc:
            raise OSError(f"Editor konnte nicht gestartet werden: {exc}") from exc

    if system == "Darwin":
        print(f"Öffne {env_path.name}…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        errors: list[str] = []
        try:
            print("  → TextEdit", flush=True)
            _run_checked(["open", "-W", "-e", target])
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"TextEdit: {exc}")

        code = shutil.which("code")
        if code:
            try:
                print("  → Visual Studio Code", flush=True)
                _wait_editor([code, "--wait", target])
                return
            except OSError as exc:
                errors.append(f"code: {exc}")

        nano = shutil.which("nano")
        if nano:
            try:
                print("  → nano", flush=True)
                _wait_editor([nano, target])
                return
            except OSError as exc:
                errors.append(f"nano: {exc}")

        try:
            print("  → Standard-Texteditor", flush=True)
            _run_checked(["open", "-W", "-t", target])
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"open -t: {exc}")

        try:
            subprocess.run(["open", target], cwd=env_path.parent, check=True)
            print("  → Datei im Standard-Programm geöffnet.", flush=True)
            _prompt_saved()
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"open: {exc}")
        raise OSError(
            "Editor konnte nicht gestartet werden: " + "; ".join(errors)
        ) from None

    editor = ["nano"]
    for candidate in ("nano", "vim", "vi"):
        found = shutil.which(candidate)
        if found:
            editor = [found]
            break
    _run_custom_editor(editor)

