# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller-Spec für die SatSage-Web-Oberfläche (Standalone).
# Binary-Name: satsage-webgui.
#
# Bauen (aus dem Projekt-Wurzelverzeichnis):
#   scripts/build_satsage_macos
#   scripts/build_satsage_linux
#   scripts/build_satsage_win.bat
# oder:
#   pyinstaller packaging/satsage-webgui.spec
#
# Ergebnis: dist/satsage-webgui (bzw. .exe unter Windows).
# Nutzerdaten (.env, Caches) liegen neben der Executable (siehe core/paths.py).
#
# Splash: packaging/satsage-splash.png (volles logo.jpg). Build-Skripte:
#   prepare_brand_assets.py (sat-logo → UI-Marke) + make_splash.py (Lockup)
# - Windows/Linux: PyInstaller-Bootloader-Splash (pyi_splash)
# - macOS: Tk-Fenster via core.splash_ui (--splash-only Kindprozess);
#   server schließt bei erstem Browser-Request mit Token
# Bild immer mitbündeln (Tk-Fallback und Dev).

import sys
from pathlib import Path

PROJEKT_ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(PROJEKT_ROOT / "web"), "web"),
    (str(PROJEKT_ROOT / "data"), "data"),
    (str(PROJEKT_ROOT / "doc"), "doc"),
]
for optional in ("VERSION", "electrum_servers.json", ".env.example"):
    pfad = PROJEKT_ROOT / optional
    if pfad.is_file():
        datas.append((str(pfad), "."))
_splash_png = PROJEKT_ROOT / "packaging" / "satsage-splash.png"
if _splash_png.is_file():
    datas.append((str(_splash_png), "packaging"))

# Bootloader-Splash nur Windows/Linux.
SPLASH_OK = sys.platform.startswith(("win", "linux"))

hidden = [
    "embit",
    "embit.bip32",
    "embit.script",
    "embit.descriptor",
    "embit.ec",
    "embit.networks",
    # Lokal in server.main_cli importiert — Analysis soll sie sicher bündeln.
    "core.terminal_steuerung",
    "core.jobs",
    "core.i18n",
    "core.log_i18n",
    "core.splash_ui",
    "core.single_instance",
    "core.gui_session",
    "tkinter",
]
if SPLASH_OK:
    hidden.append("pyi_splash")

# Ohne Splash-Bootloader darf pyi_splash nicht mitwandern (sonst Import-Warnung).
excludes = [] if SPLASH_OK else ["pyi_splash"]

a = Analysis(
    [str(PROJEKT_ROOT / "server.py")],
    pathex=[str(PROJEKT_ROOT)],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    excludes=excludes,
)

pyz = PYZ(a.pure)

exe_args = [pyz, a.scripts]
exe_kw = dict(
    name="satsage-webgui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

if SPLASH_OK:
    import json
    from PyInstaller.building.splash import Splash

    # Splash-Bild: vorbereitetes PNG (make_splash.py), sonst Lockup/Marke.
    _splash_kandidaten = (
        PROJEKT_ROOT / "packaging" / "satsage-splash.png",
        PROJEKT_ROOT / "web" / "img" / "logo.jpg",
        PROJEKT_ROOT / "web" / "img" / "sat-logo.png",
        PROJEKT_ROOT / "web" / "img" / "logo-mark.png",
        PROJEKT_ROOT / "web" / "img" / "apple-touch-icon.png",
    )
    SPLASH_IMAGE = next((p for p in _splash_kandidaten if p.is_file()), None)
    if SPLASH_IMAGE is None:
        raise SystemExit(
            "Kein Splash-Bild gefunden (packaging/satsage-splash.png oder web/img/logo-*)."
        )

    # text_pos aus Meta (make_splash.py) oder unterer Bildrand.
    _meta = PROJEKT_ROOT / "packaging" / "satsage-splash.meta.json"
    _text_pos = (134, 272)
    if _meta.is_file():
        try:
            _text_pos = tuple(json.loads(_meta.read_text(encoding="utf-8"))["text_pos"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    else:
        try:
            from PIL import Image as _SplashImage

            _sw, _sh = _SplashImage.open(SPLASH_IMAGE).size
            _text_pos = (max(12, (_sw - 212) // 2), max(12, _sh - 28))
        except Exception:
            pass

    # PyInstaller 6.22: max_img_size=None crasht (tuple > None). Stattdessen
    # großzügig setzen — make_splash.py hält das Bild ohnehin ≤ 1200×900.
    splash = Splash(
        str(SPLASH_IMAGE),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=_text_pos,
        text_size=12,
        text_color="#B25834",
        text_default="SatSage …",
        always_on_top=True,
        full_tf=True,
        max_img_size=(1200, 900),
    )
    exe_args.extend([splash, splash.binaries])

exe_args.extend([a.binaries, a.datas, []])
exe = EXE(*exe_args, **exe_kw)
