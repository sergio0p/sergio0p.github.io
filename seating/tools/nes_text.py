#!/usr/bin/env python3
"""Render text in the NES Legend of Zelda font.

Cuts glyphs straight from the ripped sheet in `Teaching/ZeldaAssets/` so the
typeface in the app is the game's own, not a lookalike. Deterministic: same
inputs, same pixels.

The sheet holds an FDS block (left) and an NES block (right), each repeated in
four ink colours. We use the NES block only. Grid coordinates below were
measured off the sheet, not guessed -- see `glyph_box()`.

    python3 nes_text.py --verify out.png        # full charset, indexed
    python3 nes_text.py --text "OPEN" --scale 4 --color white out.png
    python3 nes_text.py --atlas assets/font-white.png   # the app's font
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

# tools/ -> seating/ -> PersonalWebsite/ -> Projects/ -> Teaching/
SHEET = (Path(__file__).resolve().parents[4] / "ZeldaAssets" / "miscellaneous"
         / "NES - The Legend of Zelda - Miscellaneous - Fonts.png")

# --- measured geometry of the NES block -------------------------------------
# Glyphs are 8x8, laid out on a 16px horizontal pitch (8px glyph, 8px gap).
CELL = 8
PITCH = 16
X0 = 336                      # x of the first glyph in every row

# Each ink colour repeats the same 3 rows; value is the y of each row.
COLOR_ROWS = {
    "white": (24, 40, 56),
    "blue":  (88, 104, 120),
    "red":   (152, 168, 184),
    "green": (216, 232, 248),
}

# What sits in those three rows, in order.
ROWS = (
    "0123456789ABCDEF",
    "GHIJKLMNOPQRSTUV",
    "WXYZ,!'&.\"?-",
)
CHARSET = "".join(ROWS)
ATLAS_COLS = 16               # the sheet's own row length; keeps the grid regular


def glyph_box(ch: str, color: str) -> tuple[int, int, int, int]:
    """Pixel box of `ch` in the sheet. Raises KeyError for unsupported chars."""
    for row_idx, row in enumerate(ROWS):
        col_idx = row.find(ch)
        if col_idx != -1:
            x = X0 + PITCH * col_idx
            y = COLOR_ROWS[color][row_idx]
            return (x, y, x + CELL, y + CELL)
    raise KeyError(ch)


_sheet_cache: dict[Path, Image.Image] = {}


def _load(sheet: Path) -> Image.Image:
    if sheet not in _sheet_cache:
        _sheet_cache[sheet] = Image.open(sheet).convert("RGB")
    return _sheet_cache[sheet]


def render(text: str, color: str = "white", scale: int = 1,
           tracking: int = 0, sheet: Path = SHEET) -> Image.Image:
    """Render `text` as an RGBA image with a transparent background.

    Space is a blank cell. Unsupported characters raise KeyError -- the NES
    font has no lowercase, colon, slash or parentheses, and silently dropping
    them would ship a legend with holes in it.
    """
    src = _load(sheet)
    advance = CELL + tracking
    out = Image.new("RGBA", (max(1, advance * len(text) - tracking), CELL),
                    (0, 0, 0, 0))

    for i, ch in enumerate(text):
        if ch == " ":
            continue
        # The sheet's background is black; make it transparent, keep the ink.
        rgb = src.crop(glyph_box(ch, color))
        cell = Image.new("RGBA", rgb.size)
        cell.putdata([(r, g, b, 0) if (r, g, b) == (0, 0, 0) else (r, g, b, 255)
                      for (r, g, b) in rgb.getdata()])
        out.alpha_composite(cell, (advance * i, 0))

    if scale != 1:
        out = out.resize((out.width * scale, out.height * scale), Image.NEAREST)
    return out


def atlas(color: str = "white", sheet: Path = SHEET) -> Image.Image:
    """The whole charset as one tight 16x3 grid of 8x8 cells, for the app.

    Always 1x: the app draws single cells out of it with drawImage, so the cell
    pitch has to stay 8. Packing it at the sheet's own row length means JS needs
    no per-glyph JSON -- `CHARSET.indexOf(ch)` gives the cell, row = i / 16,
    col = i % 16.
    """
    out = Image.new("RGBA", (ATLAS_COLS * CELL, len(ROWS) * CELL), (0, 0, 0, 0))
    for i, ch in enumerate(CHARSET):
        out.alpha_composite(render(ch, color, sheet=sheet),
                            (CELL * (i % ATLAS_COLS), CELL * (i // ATLAS_COLS)))
    return out


def verify_sheet(scale: int = 4) -> Image.Image:
    """Every glyph we can render, in all four inks, for eyeballing."""
    pad, cols = 2, len(ROWS[0])
    cw, ch = CELL * scale + pad, CELL * scale + pad
    colors = list(COLOR_ROWS)
    rows_total = len(ROWS) * len(colors)
    out = Image.new("RGBA", (cw * cols, ch * rows_total), (0, 0, 0, 255))

    line = 0
    for color in colors:
        for row in ROWS:
            for i, chx in enumerate(row):
                out.alpha_composite(render(chx, color, scale),
                                    (cw * i, ch * line))
            line += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", type=Path)
    ap.add_argument("--text")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--atlas", action="store_true",
                    help="the charset as one 128x24 strip (always 1x)")
    ap.add_argument("--color", default="white", choices=sorted(COLOR_ROWS))
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--tracking", type=int, default=0,
                    help="extra px between glyphs, in NES pixels")
    args = ap.parse_args()

    if args.atlas:
        img = atlas(args.color)
    elif args.verify:
        img = verify_sheet(args.scale)
    elif args.text:
        img = render(args.text, args.color, args.scale, args.tracking)
    else:
        ap.error("give --text, --verify or --atlas")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"{args.out}  {img.width}x{img.height}")


if __name__ == "__main__":
    main()
