#!/usr/bin/env python3
"""Leitet UI-/Packaging-Marken aus sat-logo.png ab.

Marke (Sat-Symbol): sat-logo.png
Volles SatSage-Logo (Sherlock + Sat-Wolke): SatSage final.jpg → web/img/logo.jpg

Aufruf vor dem Splash-Build. Benötigt Pillow.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_IMG = ROOT / "web" / "img"
PACKAGING = ROOT / "packaging"

SAT_LOGO_KANDIDATEN = (
    ROOT / "sat-logo.png",
    WEB_IMG / "sat-logo.png",
)
FINAL_LOGO_KANDIDATEN = (
    ROOT / "SatSage final.jpg",
    ROOT / "satsage hires.jpg",
)


def _transparent_bg(im):
    """Helle Studio-Hintergründe (grau/weiß) → Alpha 0."""
    from PIL import Image

    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # sat-logo: ~#EEEEEE Fläche; Weiß ebenfalls entfernen.
            if r >= 220 and g >= 220 and b >= 220:
                px[x, y] = (r, g, b, 0)
    return rgba


def _fit(im, size: int, *, pad_ratio: float = 0.06):
    """Quadrat size×size, Logo zentriert mit etwas Innenabstand, nie hochskalieren über native."""
    from PIL import Image

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, int(size * (1 - 2 * pad_ratio)))
    src = im.convert("RGBA")
    # Nur verkleinern.
    if src.width > inner or src.height > inner:
        src.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    x = (size - src.width) // 2
    y = (size - src.height) // 2
    canvas.paste(src, (x, y), src)
    return canvas


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow fehlt — installiere: pip install Pillow", file=sys.stderr)
        return 1

    sat_src = next((p for p in SAT_LOGO_KANDIDATEN if p.is_file()), None)
    if sat_src is None:
        print("sat-logo.png nicht gefunden (Repo-Root oder web/img/).", file=sys.stderr)
        return 1

    WEB_IMG.mkdir(parents=True, exist_ok=True)
    PACKAGING.mkdir(parents=True, exist_ok=True)

    sat = _transparent_bg(Image.open(sat_src))
    # Kanonische Marke in web/img (RGBA, transparenter Grund).
    sat_web = WEB_IMG / "sat-logo.png"
    sat.save(sat_web, "PNG")
    print(f"  Marke: {sat_web.relative_to(ROOT)} ({sat.width}×{sat.height})")

    # Abgeleitete UI-/Packaging-Dateien (bestehende Pfade bleiben gültig).
    mark = _fit(sat, 128)
    mark.save(WEB_IMG / "logo-mark.png", "PNG")
    _fit(sat, 32, pad_ratio=0.04).convert("RGBA").save(WEB_IMG / "favicon-32.png", "PNG")
    _fit(sat, 180, pad_ratio=0.05).save(WEB_IMG / "apple-touch-icon.png", "PNG")
    mark.save(PACKAGING / "icon.png", "PNG")
    print("  Abgeleitet: logo-mark.png, favicon-32.png, apple-touch-icon.png, packaging/icon.png")

    final_src = next((p for p in FINAL_LOGO_KANDIDATEN if p.is_file()), None)
    if final_src is not None:
        # Handbuch / Lockup: aus dem vollen Logo, nur verkleinern wenn riesig.
        full = Image.open(final_src).convert("RGB")
        max_w, max_h = 960, 640
        if full.width > max_w or full.height > max_h:
            full.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        out = WEB_IMG / "logo.jpg"
        full.save(out, "JPEG", quality=92, optimize=True)
        print(
            f"  Logo:  {out.relative_to(ROOT)} "
            f"({full.width}×{full.height} aus {final_src.name})"
        )
    else:
        print("  Hinweis: SatSage final.jpg fehlt — web/img/logo.jpg unverändert.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
