#!/usr/bin/env python3
"""Leitet UI-/Packaging-Marken aus dem Pfeifen-Icon ab.

Marke (stilisierte Sherlock-Pfeife): Pfeiffe-Icon.jpg
  → transparente PNG, Schwarz = Vordergrund
  Fallback: satsage-head.png (Splash-Ausschnitt mit Crop)
  Fallback: sat-logo.png (älteres Sat-Symbol)
Volles SatSage-Logo (Sherlock + Sat-Wolke): SatSage final.jpg → web/img/logo.jpg

Aufruf vor dem Splash-Build. Benötigt Pillow.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_IMG = ROOT / "web" / "img"
PACKAGING = ROOT / "packaging"

#: Fertiges Marken-Icon (S/W, Schwarz = Vordergrund) — bevorzugt.
PIPE_ICON_KANDIDATEN = (
    ROOT / "Pfeiffe-Icon.jpg",
    ROOT / "pfeiffe-icon.jpg",
    ROOT / "Pfeiffe-Icon.png",
    ROOT / "pfeiffe-icon.png",
    WEB_IMG / "pfeiffe-icon.png",
)
#: Splash-Clipping: dunkler Grund, Figur mit Hut + Pfeife.
HEAD_KANDIDATEN = (
    ROOT / "satsage-head.png",
    WEB_IMG / "satsage-head.png",
)
#: Älteres Sat-Symbol — nur Fallback, wenn kein Head vorliegt.
SAT_LOGO_KANDIDATEN = (
    ROOT / "sat-logo.png",
    WEB_IMG / "sat-logo.png",
)
FINAL_LOGO_KANDIDATEN = (
    ROOT / "SatSage final.jpg",
    ROOT / "satsage hires.jpg",
)

#: Marken-Ausschnitt als Anteile am Content-BBox (l, t, r, b).
#: Nur Fallback aus satsage-head — Hut bewusst weitgehend weg.
PIPE_CROP_FRAC = (0.31, 0.33, 0.67, 0.64)


def _transparent_light_bg(im):
    """Helle Studio-Hintergründe (grau/weiß) → Alpha 0 (Sat-Symbol)."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r >= 220 and g >= 220 and b >= 220:
                px[x, y] = (r, g, b, 0)
    return rgba


def _transparent_dark_bg(im, *, threshold: int = 18):
    """Pechtiefer Splash-Grund → Alpha 0 (satsage-head)."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r <= threshold and g <= threshold and b <= threshold:
                px[x, y] = (0, 0, 0, 0)
    return rgba


def _bw_black_fg_transparent(im):
    """
    S/W-Icon: Schwarz = Vordergrund, hell = transparent.

    Anti-Aliasing am Rand wird als Alpha auf reinem Schwarz abgebildet —
    lesbar auf hellem und dunklem UI-Grund.
    """
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # Helligkeit (Rec. 601 grob)
            lum = (299 * r + 587 * g + 114 * b) // 1000
            if lum >= 245:
                px[x, y] = (0, 0, 0, 0)
            elif lum <= 20:
                px[x, y] = (0, 0, 0, 255)
            else:
                # Weicher Übergang: dunkler → opaker
                alpha = max(0, min(255, 255 - lum))
                px[x, y] = (0, 0, 0, alpha)
    boxed = rgba.getbbox()
    return rgba.crop(boxed) if boxed else rgba


def _crop_head_mark(im):
    """
    Marken-Ausschnitt aus dem Splash-Clipping: stilisierte Pfeife
    (Mund→Rauch-Geometrie), nicht die Hutkrone.
    """
    boxed = im.getbbox()
    if not boxed:
        return im
    full = im.crop(boxed)
    cw, ch = full.size
    l, t, r, b = PIPE_CROP_FRAC
    x0 = max(0, int(cw * l))
    y0 = max(0, int(ch * t))
    x1 = min(cw, max(x0 + 1, int(cw * r)))
    y1 = min(ch, max(y0 + 1, int(ch * b)))
    # Quadrat: kürzere Seite, vom gewählten Ursprung
    side = min(x1 - x0, y1 - y0)
    crop = full.crop((x0, y0, x0 + side, y0 + side))
    hb = crop.getbbox()
    return crop.crop(hb) if hb else crop


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

    WEB_IMG.mkdir(parents=True, exist_ok=True)
    PACKAGING.mkdir(parents=True, exist_ok=True)

    pipe_src = next((p for p in PIPE_ICON_KANDIDATEN if p.is_file()), None)
    head_src = next((p for p in HEAD_KANDIDATEN if p.is_file()), None)
    sat_src = next((p for p in SAT_LOGO_KANDIDATEN if p.is_file()), None)

    if pipe_src is not None:
        raw = Image.open(pipe_src)
        mark_src = _bw_black_fg_transparent(raw)
        # Kanonische transparente Quelle im Web-Bundle.
        pipe_web = WEB_IMG / "pfeiffe-icon.png"
        mark_src.save(pipe_web, "PNG")
        print(
            f"  Quelle: {pipe_src.relative_to(ROOT)} → "
            f"{pipe_web.relative_to(ROOT)} "
            f"({mark_src.width}×{mark_src.height}, S/W transparent)"
        )
    elif head_src is not None:
        raw = Image.open(head_src)
        mark_src = _crop_head_mark(_transparent_dark_bg(raw))
        head_web = WEB_IMG / "satsage-head.png"
        if head_src.resolve() != head_web.resolve():
            Image.open(head_src).convert("RGB").save(head_web, "PNG")
        print(
            f"  Quelle: {head_src.relative_to(ROOT)} → Marken-Ausschnitt "
            f"{mark_src.width}×{mark_src.height} (stilisierte Pfeife)"
        )
    elif sat_src is not None:
        mark_src = _transparent_light_bg(Image.open(sat_src))
        print(f"  Quelle (Fallback Sat-Symbol): {sat_src.relative_to(ROOT)}")
    else:
        print(
            "Pfeiffe-Icon.jpg / satsage-head.png / sat-logo.png nicht gefunden "
            "(Repo-Root oder web/img/).",
            file=sys.stderr,
        )
        return 1

    # Kanonische Marke in web/img (RGBA) — bestehende Pfade bleiben gültig.
    sat_web = WEB_IMG / "sat-logo.png"
    # Für die Kopfzeile: ausreichend groß, transparenter Grund.
    _fit(mark_src, 256, pad_ratio=0.04).save(sat_web, "PNG")
    print(f"  Marke: {sat_web.relative_to(ROOT)} (256×256)")

    mark = _fit(mark_src, 128)
    mark.save(WEB_IMG / "logo-mark.png", "PNG")
    _fit(mark_src, 32, pad_ratio=0.04).convert("RGBA").save(
        WEB_IMG / "favicon-32.png", "PNG"
    )
    _fit(mark_src, 180, pad_ratio=0.05).save(WEB_IMG / "apple-touch-icon.png", "PNG")
    mark.save(PACKAGING / "icon.png", "PNG")
    print(
        "  Abgeleitet: logo-mark.png, favicon-32.png, "
        "apple-touch-icon.png, packaging/icon.png"
    )

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
