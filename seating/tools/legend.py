#!/usr/bin/env python3
"""Render the legend as its own image, separate from the room.

Keeping it out of the room map means it never eats seat space on a phone, and
building it from the SAME functions `room_kit.place_seats()` paints with means
it cannot drift out of sync -- change a seat tile and the legend changes too.

Five entries. Two axes, not five states:

    colour  = which hand     blue right, teal left
    texture = can you sit    flat floor open, bevelled tile closed

which is why "SEAT NOT AVAILABLE" shows BOTH colours. A single sample would
teach that unavailable seats have a colour of their own; they don't, and a
student looking at the teal bevels in column 1 would find nothing to match.

There is no "yours" entry: a claimed seat is Link standing on it.

    python3 tools/legend.py                      # -> assets/legend.png
    python3 tools/legend.py out.png --scale 4 --color blue
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

import cut_link
import cut_moblin
import nes_text
from room_kit import (HAND_PALETTE, SEAT_FLOOR_ROOM, T, WALL, _blocked_tile,
                      _floor_tile, load_layout)

# A shipping asset, not a preview: the page puts it above the room.
OUT = Path(__file__).resolve().parents[1] / "assets" / "legend.png"

PAD, GAP, ROW_GAP = 8, 8, 4          # in NES pixels, before --scale
BG = (0, 0, 0)                       # the game's own HUD background


def room_width(pad_left: int = 1) -> int:
    """How wide the room comes out, from the same layout the room is built from.

    The page stacks legend over room in one fit-to-width column, so they have to
    share a width -- otherwise the browser scales them by different factors and
    the 8px glyphs land on fractional pixels.
    """
    c0, c1 = load_layout()["grid"]["seat_cols"]
    return WALL * 2 + (pad_left + c1 - c0 + 1) * T


def entries():
    """(icons, label) per row, icons already 16x16 RGBA."""
    link = cut_link.cut()[cut_link.NAMES.index("down-1")]
    moblin = cut_moblin.cut()[cut_moblin.NAMES.index("down")]
    open_ = {h: _floor_tile(SEAT_FLOOR_ROOM, p) for h, p in HAND_PALETTE.items()}
    closed = {h: _blocked_tile(p) for h, p in HAND_PALETTE.items()}
    return [
        ([link], "YOU"),
        ([moblin], "PROF. PARREIRAS"),
        ([open_["left"]], "LEFT-HANDED SEAT"),
        ([open_["right"]], "RIGHT-HANDED SEAT"),
        ([closed["right"], closed["left"]], "SEAT NOT AVAILABLE"),
    ]


def build(scale: int = 1, color: str = "white",
          width: int | None = None) -> Image.Image:
    rows = entries()
    labels = [nes_text.render(text, color) for _, text in rows]

    icon_w = max(len(icons) * T + (len(icons) - 1) for icons, _ in rows)
    text_w = max(lab.width for lab in labels)
    w = PAD * 2 + icon_w + GAP + text_w
    h = PAD * 2 + len(rows) * T + (len(rows) - 1) * ROW_GAP
    x0 = PAD
    if width:                       # centre the block on the wider canvas
        x0, w = PAD + (width - w) // 2, max(w, width)

    im = Image.new("RGBA", (w, h), (*BG, 255))
    y = PAD
    for (icons, _), label in zip(rows, labels):
        for i, icon in enumerate(icons):
            im.alpha_composite(icon.convert("RGBA"), (x0 + i * (T + 1), y))
        # Labels are 8px tall; centre them against the 16px tile.
        im.alpha_composite(label, (x0 + icon_w + GAP, y + (T - label.height) // 2))
        y += T + ROW_GAP

    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    return im


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=OUT)
    ap.add_argument("--scale", type=int, default=1,
                    help="1 for the shipping asset; the page scales it")
    ap.add_argument("--width", type=int, default=None,
                    help="canvas width in NES px (default: the room's width)")
    ap.add_argument("--color", default="white", choices=sorted(nes_text.COLOR_ROWS))
    args = ap.parse_args()

    im = build(args.scale, args.color,
               args.width if args.width is not None else room_width())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    im.save(args.out)
    print(f"{args.out}  {im.width}x{im.height}")


if __name__ == "__main__":
    main()
