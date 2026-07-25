"""Cut Link's six basic movement sprites out of the ripped character sheet.

The "Basic movement" block sits top-left: one row of six 16x16 sprites at
y=11..26, on a 17px pitch starting at x=1 -- measured, not eyeballed (the sheet's
flat green `(0,128,0)` gutters give the runs exactly).

Order on the sheet is down, down, RIGHT, right, up, up. The side pose faces
right, not left: the sword rows further down the sheet reuse this exact pose with
the blade extending to the right, and the cap's point trails to the left. Left is
not on the sheet -- the game itself draws it by mirroring right, so `--mirror`
writes those two as well.

The sprite boxes sit on a grey `(116,116,116)` field; that and the green gutter
both become transparent, so a sprite drops onto any floor tile.

    python3 tools/cut_link.py              # -> assets/tiles/link-*.png
    python3 tools/cut_link.py --mirror     # + link-right-1/2.png
    python3 tools/cut_link.py --sheet reference/link-basic-movement.png
"""
import argparse
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[4] / "ZeldaAssets"
OUT = Path(__file__).resolve().parents[1] / "assets" / "tiles"
SHEET = (ASSETS / "playable-characters"
         / "NES - The Legend of Zelda - Playable Characters - Link.png")

T = 16
ROW_Y = 11                   # measured: the movement row is y 11..26
X0, PITCH = 1, 17            # six boxes at x = 1, 18, 35, 52, 69, 86
NAMES = ["down-1", "down-2", "right-1", "right-2", "up-1", "up-2"]

GREEN = (0, 128, 0)          # sheet gutter
BOX = (116, 116, 116)        # sprite-box field
TRANSPARENT = {GREEN, BOX}


def cut(sheet=SHEET):
    """The six sprites, in sheet order, RGBA with the backdrop knocked out."""
    im = Image.open(sheet).convert("RGB")
    out = []
    for i in range(len(NAMES)):
        x = X0 + i * PITCH
        box = im.crop((x, ROW_Y, x + T, ROW_Y + T)).convert("RGBA")
        box.putdata([(0, 0, 0, 0) if px[:3] in TRANSPARENT else px
                     for px in box.getdata()])
        out.append(box)
    return out


def contact_sheet(sprites, names, scale=6, gap=4):
    """One strip of every sprite, for eyeballing what was cut."""
    w = T * scale
    im = Image.new("RGBA", (len(sprites) * (w + gap) - gap, w), (0, 0, 0, 0))
    for i, s in enumerate(sprites):
        im.paste(s.resize((w, w), Image.NEAREST), (i * (w + gap), 0))
    return im


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--mirror", action="store_true",
                   help="also write link-left-1/2 as mirrored right frames")
    p.add_argument("--sheet", type=Path, help="write a contact sheet here too")
    p.add_argument("--scale", type=int, default=6)
    args = p.parse_args()

    sprites, names = cut(), list(NAMES)
    if args.mirror:
        for i, n in enumerate(("left-1", "left-2")):
            sprites.append(sprites[NAMES.index(f"right-{i+1}")]
                           .transpose(Image.FLIP_LEFT_RIGHT))
            names.append(n)

    args.out.mkdir(parents=True, exist_ok=True)
    for sprite, name in zip(sprites, names):
        path = args.out / f"link-{name}.png"
        sprite.save(path)
        print(f"  {path.name:<16} {sprite.size[0]}x{sprite.size[1]}")

    if args.sheet:
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        contact_sheet(sprites, names, args.scale).save(args.sheet)
        print(f"\ncontact sheet -> {args.sheet}")


if __name__ == "__main__":
    main()
