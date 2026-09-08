"""
Start-Splash ohne PyInstaller-Bootloader (macOS und Fallback).

PyInstaller-Splash gibt es nur unter Windows/Linux. Hier: eigenes Tk-Fenster
in einem Kindprozess (``--splash-only``), früh sichtbar, schließt wenn der
Elternprozess stirbt, die GUI im Browser ankommt, oder close() aufgerufen wird.

Statuszeile: Eltern schreibt Text in die Statusdatei; das Kind liest sie.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_KIND_FLAG = "--splash-only"
_proc: subprocess.Popen | None = None
_status_pfad: Path | None = None
_aktiv = False


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def splash_bild() -> Path | None:
    basis = _resource_dir()
    for rel in (
        "packaging/satsage-splash.png",
        "satsage-splash.png",
        # Splash-PNG fehlt: volles Lockup, sonst Marke.
        "web/img/logo.jpg",
        "web/img/sat-logo.png",
        "web/img/logo-mark.png",
        "web/img/apple-touch-icon.png",
    ):
        p = basis / rel
        if p.is_file():
            return p
    # Dev: packaging neben Repo-Root
    extra = Path(__file__).resolve().parent.parent / "packaging" / "satsage-splash.png"
    return extra if extra.is_file() else None


def ist_splash_kind_argv(argv: list[str] | None = None) -> bool:
    args = list(sys.argv if argv is None else argv)
    return _KIND_FLAG in args


def _parent_lebt(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return True


def _photo_fuer_bildschirm(bild: Path, root) -> object | None:
    """Logo in nativer Größe; nur verkleinern, wenn der Bildschirm zu klein ist."""
    import tkinter as tk

    sw = max(int(root.winfo_screenwidth()), 1)
    sh = max(int(root.winfo_screenheight()), 1)
    # Etwas Rand für Taskleiste / Statuszeile im Fenster.
    max_w = max(160, int(sw * 0.90))
    max_h = max(120, int(sh * 0.80))

    try:
        from PIL import Image, ImageTk  # type: ignore
    except ImportError:
        Image = None  # type: ignore
        ImageTk = None  # type: ignore

    if Image is not None and ImageTk is not None:
        try:
            im = Image.open(bild).convert("RGBA")
            w, h = im.size
            if w > max_w or h > max_h:
                skala = min(max_w / w, max_h / h)
                im = im.resize(
                    (max(1, int(round(w * skala))), max(1, int(round(h * skala)))),
                    Image.Resampling.LANCZOS,
                )
            return ImageTk.PhotoImage(im)
        except Exception:
            pass

    try:
        photo = tk.PhotoImage(file=str(bild))
    except tk.TclError:
        return None
    w, h = int(photo.width()), int(photo.height())
    if w <= max_w and h <= max_h:
        return photo
    # Ganzzahliges subsample (PhotoImage kann nicht beliebig skalieren).
    faktor = max(1, (w + max_w - 1) // max_w, (h + max_h - 1) // max_h)
    if faktor > 1:
        try:
            return photo.subsample(faktor, faktor)
        except tk.TclError:
            return photo
    return photo


def lauf_splash_kind(argv: list[str] | None = None) -> int:
    """Tk-Splash im Kindprozess. Argv: … --splash-only [statusdatei] [parent_pid]."""
    args = list(sys.argv if argv is None else argv)
    try:
        i = args.index(_KIND_FLAG)
    except ValueError:
        return 2
    rest = args[i + 1 :]
    status = Path(rest[0]) if rest else None
    parent_pid = int(rest[1]) if len(rest) > 1 else 0

    try:
        import tkinter as tk
    except Exception:
        return 0

    bild = splash_bild()
    root = tk.Tk()
    root.title("SatSage")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    # Kein normales Fenster-Chrome, wo möglich
    try:
        root.overrideredirect(True)
    except tk.TclError:
        pass

    rahmen = tk.Frame(root, bg="#0e1419", padx=8, pady=8)
    rahmen.pack(fill="both", expand=True)
    photo = None
    if bild is not None:
        photo = _photo_fuer_bildschirm(bild, root)
        if photo is not None:
            tk.Label(rahmen, image=photo, bg="#0e1419", borderwidth=0).pack()
    if photo is None:
        tk.Label(
            rahmen,
            text="SatSage",
            fg="#dce4e3",
            bg="#0e1419",
            font=("Helvetica", 28),
        ).pack(pady=(40, 8))
        tk.Label(
            rahmen,
            text="know your sats",
            fg="#8b99a1",
            bg="#0e1419",
            font=("Helvetica", 14),
        ).pack()

    status_lbl = tk.Label(
        rahmen,
        text="SatSage …",
        fg="#B25834",
        bg="#0e1419",
        font=("Helvetica", 12),
    )
    status_lbl.pack(pady=(8, 12))

    root.update_idletasks()
    w = max(root.winfo_reqwidth(), 320)
    h = max(root.winfo_reqheight(), 200)
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    # Falls das Fenster trotz Skalierung noch größer wäre: hart begrenzen.
    if w > sw or h > sh:
        w = min(w, sw)
        h = min(h, sh)
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
    else:
        root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    def tick() -> None:
        if parent_pid and not _parent_lebt(parent_pid):
            root.destroy()
            return
        if status is not None and status.is_file():
            try:
                text = status.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text == "__CLOSE__":
                root.destroy()
                return
            if text:
                status_lbl.configure(text=text[:80])
        root.after(200, tick)

    root.after(200, tick)
    try:
        root.mainloop()
    except Exception:
        pass
    return 0


def _kind_kommando(status: Path) -> list[str]:
    cmd = [sys.executable]
    if not getattr(sys, "frozen", False):
        # Dev: server.py als Skript, damit --splash-only ganz oben greift.
        server_py = Path(__file__).resolve().parent.parent / "server.py"
        cmd.append(str(server_py))
    cmd.extend([_KIND_FLAG, str(status), str(os.getpid())])
    return cmd


def start_tk_splash() -> bool:
    """Startet den Tk-Splash-Kindprozess. True wenn gestartet."""
    global _proc, _status_pfad, _aktiv
    if _aktiv or _proc is not None:
        return True
    # Headless/CI: kein Display
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    if os.environ.get("SATSAGE_NO_SPLASH", "").strip() in ("1", "true", "yes"):
        return False
    try:
        fd, name = tempfile.mkstemp(prefix="satsage-splash-", suffix=".txt")
        os.close(fd)
        _status_pfad = Path(name)
        _status_pfad.write_text("SatSage …", encoding="utf-8")
    except OSError:
        return False

    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # Kein extra Konsolenfenster
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        _proc = subprocess.Popen(_kind_kommando(_status_pfad), **kwargs)
        _aktiv = True
        return True
    except Exception:
        _cleanup_status()
        _proc = None
        _aktiv = False
        return False


def _cleanup_status() -> None:
    global _status_pfad
    if _status_pfad is not None:
        try:
            _status_pfad.unlink(missing_ok=True)
        except TypeError:
            try:
                if _status_pfad.exists():
                    _status_pfad.unlink()
            except OSError:
                pass
        except OSError:
            pass
        _status_pfad = None


def update_tk_splash(meldung: str) -> None:
    if not _aktiv or _status_pfad is None:
        return
    try:
        _status_pfad.write_text((meldung or "SatSage …")[:80], encoding="utf-8")
    except OSError:
        pass


def close_tk_splash() -> None:
    """Signalisiert dem Kind zu schließen und räumt auf."""
    global _proc, _aktiv
    if _status_pfad is not None:
        try:
            _status_pfad.write_text("__CLOSE__", encoding="utf-8")
        except OSError:
            pass
    if _proc is not None:
        try:
            _proc.wait(timeout=1.5)
        except Exception:
            try:
                _proc.terminate()
            except Exception:
                pass
            try:
                _proc.wait(timeout=0.5)
            except Exception:
                try:
                    _proc.kill()
                except Exception:
                    pass
        _proc = None
    _cleanup_status()
    _aktiv = False
    # Kurze Pause, damit das Fenster weg ist bevor Browser-Fokus wechselt
    time.sleep(0.05)


def tk_splash_aktiv() -> bool:
    return bool(_aktiv and _proc is not None and _proc.poll() is None)
