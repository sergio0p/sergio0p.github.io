"""Cut the orange Moblin's four sprites out of the ripped enemy sheet.

Same geometry as Link's basic-movement row -- a 16x16 box on a 17px pitch, the
sheet's flat green `(0,128,0)` gutters giving the runs exactly. The "Moblin"
block is two rows: y=11..26 is the orange (overworld) Moblin, y=28..43 the blue
one; `--blue` takes the second row instead.

Four sprites, at x = 82, 99, 116, 133: facing down, facing up, then the two
side-walk frames -- both of which face RIGHT. Left is not on the sheet because
the game mirrors right, so `--mirror` writes those two as well.

The sprite boxes sit on a grey `(116,116,116)` field; that and the green gutter
both become transparent, so the Moblin drops onto any floor tile.

    python3 tools/cut_moblin.py            # -> assets/tiles/moblin-*.png
    python3 tools/cut_moblin.py --mirror   # + moblin-left-1/2.png
    python3 tools/cut_moblin.py --sheet reference/moblin.png
"""
import argparse
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[4] / "ZeldaAssets"
OUT = Path(__file__).resolve().parents[1] / "assets" / "tiles"
SHEET = (ASSETS / "enemies-bosses"
         / "NES - The Legend of Zelda - Enemies & Bosses - Overworld Enemies.png")

T = 16
ROW_ORANGE, ROW_BLUE = 11, 28        # measured: the two Moblin rows
X0, PITCH = 82, 17                   # four boxes at x = 82, 99, 116, 133
NAMES = ["down", "up", "right-1", "right-2"]

GREEN = (0, 128, 0)          # sheet gutter
BOX = (116, 116, 116)        # sprite-box field
TRANSPARENT = {GREEN, BOX}


def cut(sheet=SHEET, row=ROW_ORANGE):
    """The four sprites, in sheet order, RGBA with the backdrop knocked out."""
    im = Image.open(sheet).convert("RGB")
    out = []
    for i in range(len(NAMES)):
        x = X0 + i * PITCH
        box = im.crop((x, row, x + T, row + T)).convert("RGBA")
        box.putdata([(0, 0, 0, 0) if px[:3] in TRANSPARENT else px
                     for px in box.getdata()])
        out.append(box)
    return out


def contact_sheet(sprites, scale=6, gap=4):
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
    p.add_argument("--blue", action="store_true", help="cut the blue Moblin row")
    p.add_argument("--mirror", action="store_true",
                   help="also write moblin-left-1/2 as mirrored right frames")
    p.add_argument("--sheet", type=Path, help="write a contact sheet here too")
    p.add_argument("--scale", type=int, default=6)
    args = p.parse_args()

    prefix = "moblin-blue" if args.blue else "moblin"
    sprites = cut(row=ROW_BLUE if args.blue else ROW_ORANGE)
    names = list(NAMES)
    if args.mirror:
        for i, n in enumerate(("left-1", "left-2")):
            sprites.append(sprites[NAMES.index(f"right-{i+1}")]
                           .transpose(Image.FLIP_LEFT_RIGHT))
            names.append(n)

    args.out.mkdir(parents=True, exist_ok=True)
    for sprite, name in zip(sprites, names):
        path = args.out / f"{prefix}-{name}.png"
        sprite.save(path)
        print(f"  {path.name:<20} {sprite.size[0]}x{sprite.size[1]}")

    if args.sheet:
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        contact_sheet(sprites, args.scale).save(args.sheet)
        print(f"\ncontact sheet -> {args.sheet}")


if __name__ == "__main__":
    main()
