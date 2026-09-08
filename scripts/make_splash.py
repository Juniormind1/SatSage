#!/usr/bin/env python3
"""Erzeugt packaging/satsage-splash.png aus dem vollen Logo (logo.jpg).

Quelle: web/img/logo.jpg (aus SatSage final.jpg). Das Bild wird vollständig
gezeigt in nativer Größe — nur herunterskalieren, wenn es das Limit sprengt.
Unten bleibt Platz für die PyInstaller-Statuszeile.

Marke (sat-logo) ist für UI/Favicon; der Splash zeigt das Lockup.
Vorher idealerweise: scripts/prepare_brand_assets.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "satsage-splash.png"
META = ROOT / "packaging" / "satsage-splash.meta.json"

# Volles Lockup zuerst; Fallbacks nur wenn logo.jpg fehlt.
LOGO_KANDIDATEN = (
    ROOT / "web" / "img" / "logo.jpg",
    ROOT / "SatSage final.jpg",
    ROOT / "satsage hires.jpg",
    ROOT / "web" / "img" / "sat-logo.png",
    ROOT / "sat-logo.png",
    ROOT / "web" / "img" / "logo-mark.png",
)

# PyInstaller Spec setzt max_img_size=None; dies ist nur ein Soft-Limit.
MAX_SPLASH = (1200, 900)
PAD = 16
STATUS_HOEHE = 40
HINTERGRUND = (14, 20, 25, 255)
RAHMEN = (43, 55, 63, 255)


def _skaliere_wenn_noetig(logo, max_w: int, max_h: int):
    """Nur verkleinern, nie vergrößern."""
    from PIL import Image

    w, h = logo.size
    if w <= 0 or h <= 0:
        return logo
    if w <= max_w and h <= max_h:
        return logo
    skala = min(max_w / w, max_h / h)
    neu = (max(1, int(round(w * skala))), max(1, int(round(h * skala))))
    return logo.resize(neu, Image.Resampling.LANCZOS)


def _ist_lockup(name: str) -> bool:
    n = name.lower()
    return n in ("logo.jpg", "satsage final.jpg", "satsage hires.jpg") or n.endswith(
        ("final.jpg", "hires.jpg")
    )


def _font(size: int):
    from PIL import ImageFont

    for name in (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _transparent_bg(im):
    from PIL import Image

    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and r >= 220 and g >= 220 and b >= 220:
                px[x, y] = (r, g, b, 0)
    return rgba


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow fehlt — installiere: pip install Pillow", file=sys.stderr)
        return 1

    logo_src = next((p for p in LOGO_KANDIDATEN if p.is_file()), None)
    if logo_src is None:
        print("Kein Logo gefunden (web/img/logo.jpg).", file=sys.stderr)
        return 1

    lockup = _ist_lockup(logo_src.name)
    if lockup:
        logo = Image.open(logo_src).convert("RGBA")
        text_block = 0
    else:
        logo = _transparent_bg(Image.open(logo_src))
        text_block = 78

    original_size = logo.size
    max_w = MAX_SPLASH[0] - 2 * PAD
    max_h = MAX_SPLASH[1] - 2 * PAD - text_block - STATUS_HOEHE
    logo = _skaliere_wenn_noetig(logo, max_w, max_h)

    width = logo.width + 2 * PAD
    height = PAD + logo.height + text_block + STATUS_HOEHE + PAD

    hintergrund = Image.new("RGBA", (width, height), HINTERGRUND)
    draw = ImageDraw.Draw(hintergrund)
    draw.rounded_rectangle(
        (8, 8, width - 9, height - 9),
        radius=12,
        outline=RAHMEN,
        width=1,
    )

    logo_x = (width - logo.width) // 2
    logo_y = PAD
    hintergrund.paste(logo, (logo_x, logo_y), logo)

    if not lockup:
        def center_text(text: str, y: int, fnt, fill) -> None:
            bbox = draw.textbbox((0, 0), text, font=fnt)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, y), text, font=fnt, fill=fill)

        text_y = logo_y + logo.height + 14
        center_text("SatSage", text_y, _font(28), (220, 228, 227, 255))
        center_text("know your sats", text_y + 36, _font(14), (139, 153, 161, 255))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    hintergrund.convert("RGB").save(OUT, "PNG")

    text_pos = (max(12, (width - 212) // 2), height - 28)
    META.write_text(
        json.dumps(
            {
                "width": width,
                "height": height,
                "text_pos": list(text_pos),
                "source": logo_src.name,
                "logo_size": list(logo.size),
                "scaled_down": logo.size != original_size,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"  Splash: {OUT.relative_to(ROOT)} "
        f"{width}×{height} (aus {logo_src.name}, Logo {logo.width}×{logo.height}"
        f"{', skaliert' if logo.size != original_size else ', nativ'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
