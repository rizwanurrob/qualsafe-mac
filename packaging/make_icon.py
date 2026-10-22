#!/usr/bin/env python
"""
Generate the application icon.

    python packaging/make_icon.py            # -> qualsafe_qt/resources/qualsafe.ico + .icns
    python packaging/make_icon.py --icns-only   # just the macOS icon

**This is a placeholder.** It exists so the installer, the taskbar, and the
window title bar have something deliberate rather than the generic Windows
default, and so the build pipeline is complete and testable end to end. Swap in
real artwork whenever it exists; nothing but this file needs to change.

The mark is the one thing this program does that no spreadsheet does: a passage
of text with a coded span marked beside it. A red stripe in the margin, three
lines of text to its right — the reader's margin stripes, at 32 pixels.

Every size is **drawn at its own resolution** rather than downsampled from one
large bitmap. A 1-pixel line downsampled from 256px turns to grey mush; drawn
natively at 16px it stays a line. The small sizes also drop to a simplified
two-bar form, because three bars plus their gaps cannot survive in 16 pixels.

Colours come from `core/theme.py` so the icon cannot drift from the app's own
palette. That is the same single-source rule the views follow.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT = PROJECT_ROOT / "qualsafe_qt" / "resources" / "qualsafe.ico"
ICNS_OUTPUT = OUTPUT.with_suffix(".icns")

# Windows uses 16 in the title bar, 32 in the taskbar and alt-tab, 48 in the
# desktop, and 256 in the shell's extra-large view and the installer header.
SIZES = (16, 24, 32, 48, 64, 128, 256)

# macOS asks for these, up to 1024 for Retina Dock and Finder. Drawn natively at
# each size for the same reason as the Windows frames (see _draw).
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)

# Below this the three-bar form loses its gaps and reads as a smudge.
SIMPLIFY_AT = 32


def _palette() -> dict[str, str]:
    """The app's dark palette, or a literal copy of it if the import fails.

    The fallback exists only so this script still runs standalone; the values
    are the same and a mismatch would be caught by anyone looking at the icon.
    """
    try:
        from core.theme import DARK
        return dict(DARK)
    except Exception:
        return {"bg_elevated": "#1C1E22", "border": "#35373E",
                "text": "#E8E9EC", "text_muted": "#9AA0A8", "red": "#E03846"}


def _draw(size: int, palette: dict[str, str]):
    from PIL import Image, ImageDraw

    # Supersample 4x, then reduce once. Antialiases the rounded corners and the
    # stripe without turning the bars to mush, because the geometry below is
    # computed from the *target* size, not the supersampled one.
    scale = 4
    s = size * scale
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = max(1, round(size * 0.20)) * scale
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius,
                           fill=palette["bg_elevated"],
                           outline=palette["border"],
                           width=max(1, round(size * 0.03)) * scale)

    simple = size <= SIMPLIFY_AT

    # The coded span: a stripe in the margin.
    stripe_w = max(1, round(size * (0.15 if simple else 0.11))) * scale
    stripe_x = round(size * 0.21) * scale
    draw.rounded_rectangle(
        [stripe_x, round(size * 0.24) * scale,
         stripe_x + stripe_w, round(size * 0.76) * scale],
        radius=stripe_w // 2, fill=palette["red"])

    # The text it marks. Last bar short, so it reads as a paragraph ending.
    bar_x = round(size * (0.46 if simple else 0.42)) * scale
    right = round(size * 0.79) * scale
    rows = ((0.30, 1.0), (0.62, 0.62)) if simple else \
           ((0.27, 1.0), (0.46, 1.0), (0.65, 0.58))
    bar_h = max(1, round(size * (0.12 if simple else 0.085))) * scale

    for top, width_frac in rows:
        y = round(size * top) * scale
        end = bar_x + round((right - bar_x) * width_frac)
        draw.rounded_rectangle([bar_x, y, end, y + bar_h],
                               radius=bar_h // 2,
                               fill=palette["text"] if width_frac == 1.0
                               else palette["text_muted"])

    return image.resize((size, size), Image.LANCZOS)


def write_icns(palette: dict[str, str]) -> Path:
    """Write the macOS icon. Every size is drawn at its own resolution."""
    frames = [_draw(size, palette) for size in ICNS_SIZES]
    ICNS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(ICNS_OUTPUT, format="ICNS", append_images=frames[:-1])
    print(f"wrote {ICNS_OUTPUT.relative_to(PROJECT_ROOT)} "
          f"({ICNS_OUTPUT.stat().st_size:,} bytes, sizes {list(ICNS_SIZES)})")
    return ICNS_OUTPUT


def main() -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Pillow is required:  pip install pillow", file=sys.stderr)
        return 1

    palette = _palette()
    if "--icns-only" in sys.argv:
        write_icns(palette)
        return 0
    frames = [_draw(size, palette) for size in SIZES]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # bitmap_format="bmp" is load-bearing, not a preference.
    #
    # Pillow defaults to writing EVERY frame PNG-compressed. Windows accepts a
    # PNG-compressed icon frame only at 256x256; at 16 through 128 the shell
    # expects an uncompressed BMP/DIB and silently renders nothing otherwise.
    # The first version of this script shipped an all-PNG .ico and the shortcut
    # had no icon at all -- while Pillow re-read the same file perfectly, which
    # is why inspecting it in Python looked fine.
    #
    # Forcing BMP for every frame costs about 350 KB instead of 21 KB and works
    # everywhere, which for one icon is not a trade worth thinking about.
    frames[-1].save(OUTPUT, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1],
                    bitmap_format="bmp")

    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)} "
          f"({OUTPUT.stat().st_size:,} bytes, sizes {list(SIZES)})")

    # A PNG of the largest frame, for the README and any store listing.
    png = OUTPUT.with_suffix(".png")
    frames[-1].save(png, format="PNG")
    print(f"wrote {png.relative_to(PROJECT_ROOT)}")
    write_icns(palette)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
