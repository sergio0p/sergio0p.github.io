#!/usr/bin/env python3
"""Compose a Zelda dungeon room of any size, with doors wherever we want.

The canonical NES room is fixed at a 12x7 interior with one centred door per
wall. ECON 416 needs 13x11 and two doors both on the left wall, so we can't use
a room screenshot as-is. Instead we harvest the pieces from the ripped tileset
and lay them like bricks.

Coordinates below were measured off the sheet, not guessed. The tileset's
"Room Exterior" block marks its four door slots in flat colour -- red top,
yellow left, blue right, green bottom -- which is how the slot geometry was
recovered.

    python3 room_kit.py --list-doors doors.png     # what door types exist
    python3 room_kit.py econ416.png                # the ECON 416 room
    python3 room_kit.py big.png --cols 20 --rows 16
    python3 room_kit.py --emit .                   # the app's shipping assets
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[4] / "ZeldaAssets"
LAYOUT = Path(__file__).resolve().parents[1] / "data" / "room-layout.json"
TILESET = ASSETS / "tilesets" / "NES - The Legend of Zelda - Tilesets - Dungeon Tileset.png"

# Floors come from Second Quest Level 3, which carries both the stipple and the
# plain tiled floor in the same palette as its walls. Taking them from one map
# is what makes the spacing match the walls without any recolouring.
FLOOR_MAP = (ASSETS / "dungeon-maps-second-quest"
             / "NES - The Legend of Zelda - Dungeon Maps (Second Quest) - Level 3 (L).png")
MAP_RW, MAP_RH, MAP_SEP = 256, 176, 1
SEAT_FLOOR_ROOM = (1, 0)     # plain tiled floor -- under the seats
SPACE_FLOOR_ROOM = (2, 5)    # stipple, one repeating tile -- the open space

T = 16                       # tile size
WALL = 32                    # wall thickness: 2 tiles
BG = (0, 128, 0)             # tileset background

# The frame is ripped in the tileset's teal; the floors are Level 3 blue. Both
# are 4-colour NES palettes, so matching them is a straight swap, darkest first.
TEAL = ((0, 0, 0), (24, 60, 92), (0, 128, 136), (0, 232, 216))
PALETTES = {
    "teal": TEAL,
    "blue": ((0, 0, 0), (0, 0, 168), (32, 56, 236), (92, 148, 252)),
}

# --- measured: the "Room Exterior" frame -------------------------------------
FRAME = (521, 11, 777, 187)          # 256x176

# --- measured: the "Tiles" block ---------------------------------------------
# Its grid starts at (984, 11), 16px tiles on a 17px pitch. Column 1 of row 0 is
# the bevelled recess: the single "you cannot sit here" tile.
BLOCKED_TILE = (1001, 11)

# Seat colour carries handedness, so it is fixed per hand rather than following
# --palette (which colours the room).
HAND_PALETTE = {"right": "blue", "left": "teal"}

# --- measured: door strips, one row per orientation --------------------------
DOOR_ROWS = {"top": 11, "left": 44, "right": 77, "bottom": 110}
DOOR_X0, DOOR_X1 = 815, 1052
DOOR = 32

# Every orientation lays its 5 variants out in the same order.
WALL_ONLY, OPEN, LOCKED, SHUTTER, BOMBED = range(5)
CHOSEN_DOOR = OPEN          # settled: the plain open passage, both exits

# --- clean slices to repeat (chosen to miss statues and door slots) ----------
SLICE_TOP = (48, 0, 16, WALL)        # 16 wide, full top-wall depth
SLICE_BOT = (48, 144, 16, WALL)
SLICE_LEFT = (0, 32, WALL, 16)       # full left-wall depth, 16 tall
SLICE_RIGHT = (224, 32, WALL, 16)
CORNERS = {"tl": (0, 0), "tr": (224, 0), "bl": (0, 144), "br": (224, 144)}


def recolor(img: Image.Image, palette: str,
            src: tuple = TEAL) -> Image.Image:
    """Remap one 4-colour NES palette onto another, darkest to lightest.

    `src` matters: the frame and doors are ripped in the tileset's teal, but the
    floors come out of the Level 3 map already blue. Recolouring both from the
    wrong source is what produced the teal-walls/blue-floor mismatch.
    """
    dst = PALETTES[palette]
    if dst == src:
        return img
    table = dict(zip(src, dst))
    out = Image.new("RGB", img.size)
    out.putdata([table.get(px, px) for px in img.getdata()])
    return out


def _frame(palette: str) -> Image.Image:
    return recolor(Image.open(TILESET).convert("RGB").crop(FRAME), palette)


def _floor_tile(room: tuple[int, int], palette: str = "blue") -> Image.Image:
    """One 16x16 floor tile from a Level 3 room interior. The tileset frame's
    own interior is a flat placeholder, so floors come from a real map."""
    c, r = room
    x = MAP_SEP + c * (MAP_RW + MAP_SEP) + WALL
    y = MAP_SEP + r * (MAP_RH + MAP_SEP) + WALL
    tile = Image.open(FLOOR_MAP).convert("RGB").crop((x, y, x + T, y + T))
    return recolor(tile, palette, src=PALETTES["blue"])


def door_cells(orientation: str) -> list[Image.Image]:
    """Every door variant for one wall, left to right as the sheet lays them."""
    sheet = Image.open(TILESET).convert("RGB")
    y = DOOR_ROWS[orientation]
    strip = sheet.crop((DOOR_X0, y, DOOR_X1, y + DOOR))

    # Variants are separated by columns of flat background.
    gaps, run = [], None
    for x in range(strip.width):
        blank = all(strip.getpixel((x, yy)) == BG for yy in range(DOOR))
        if blank and run is None:
            run = x
        elif not blank and run is not None:
            gaps.append((run, x))
            run = None
    if run is not None:
        gaps.append((run, strip.width))

    cells, x = [], 0
    for a, b in gaps + [(strip.width, strip.width)]:
        if a - x >= DOOR:
            cells.append(strip.crop((x, 0, a, DOOR)))
        x = b
    return cells


def build(cols: int, rows: int, doors: list[tuple[str, int]],
          door_variant: int = CHOSEN_DOOR, palette: str = "blue",
          pad_top: int = 2, pad_left: int = 1) -> Image.Image:
    """A room holding a `cols` x `rows` seat grid.

    `pad_top` is the professor's space in front of the board; `pad_left` is the
    stairs, drawn as flat floor. Both are stippled so they read as circulation
    rather than seating, and the stipple's background is the wall colour.

    `doors` is a list of (wall, index) where wall is top/bottom/left/right and
    index is the interior tile the door starts at, along that wall. A door is
    32px, so it covers two tiles.
    """
    fr = _frame(palette)
    seat_floor = _floor_tile(SEAT_FLOOR_ROOM, palette)
    space_floor = _floor_tile(SPACE_FLOOR_ROOM, palette)
    icols, irows = pad_left + cols, pad_top + rows
    W, H = WALL * 2 + icols * T, WALL * 2 + irows * T
    room = Image.new("RGB", (W, H), (0, 0, 0))

    # corners
    for name, (sx, sy) in CORNERS.items():
        patch = fr.crop((sx, sy, sx + WALL, sy + WALL))
        dx = 0 if name[1] == "l" else W - WALL
        dy = 0 if name[0] == "t" else H - WALL
        room.paste(patch, (dx, dy))

    # horizontal wall runs
    for slc, dy in ((SLICE_TOP, 0), (SLICE_BOT, H - WALL)):
        sx, sy, sw, sh = slc
        piece = fr.crop((sx, sy, sx + sw, sy + sh))
        for i in range(icols):
            room.paste(piece, (WALL + i * T, dy))

    # vertical wall runs
    for slc, dx in ((SLICE_LEFT, 0), (SLICE_RIGHT, W - WALL)):
        sx, sy, sw, sh = slc
        piece = fr.crop((sx, sy, sx + sw, sy + sh))
        for i in range(irows):
            room.paste(piece, (dx, WALL + i * T))

    # floor: stipple for the professor's space and the stairs, plain under seats
    for r in range(irows):
        for c in range(icols):
            space = r < pad_top or c < pad_left
            room.paste(space_floor if space else seat_floor,
                       (WALL + c * T, WALL + r * T))

    # doors
    for wall, idx in doors:
        cells = door_cells(wall)
        d = recolor(cells[min(door_variant, len(cells) - 1)], palette)
        if wall in ("top", "bottom"):
            x = WALL + idx * T
            y = 0 if wall == "top" else H - WALL
        else:
            x = 0 if wall == "left" else W - WALL
            y = WALL + idx * T
        room.paste(d, (x, y))

    return room


def load_layout(path: Path = LAYOUT) -> dict:
    return json.loads(path.read_text())


def _blocked_tile(palette: str) -> Image.Image:
    x, y = BLOCKED_TILE
    tile = Image.open(TILESET).convert("RGB").crop((x, y, x + T, y + T))
    return recolor(tile, palette)


def place_seats(room: Image.Image, layout: dict, palette: str = "blue",
                pad_top: int = 2, pad_left: int = 1) -> Image.Image:
    """Paint the seat block: one tile per seat, stipple where there is none.

    Two independent axes, so every seat is a colour x texture pair:

        colour  = which hand      right -> the room's blue, left -> teal
        texture = can you sit     open  -> flat floor,      closed -> bevelled recess

    A left seat stays teal whether it is free or not; "open" and "lefty" are not
    alternatives, they are answers to different questions.

    Reserved, taken and off-limits all share the closed texture. A student only
    needs to know whether a seat is available -- collapsing the three keeps the
    discretionary and blocked sets private.

    There is no "yours" tile: a student who claims a seat sees Link standing on
    it, which is also what they see on any later visit.

    Row 0 is the only row that is not full: seats at cols 3-4 and 10-11 only, so
    the rest of it stipples out.
    """
    (r0, r1), (c0, c1) = layout["grid"]["seat_rows"], layout["grid"]["seat_cols"]
    space = _floor_tile(SPACE_FLOOR_ROOM, palette)
    open_ = {h: _floor_tile(SEAT_FLOOR_ROOM, p) for h, p in HAND_PALETTE.items()}
    closed = {h: _blocked_tile(p) for h, p in HAND_PALETTE.items()}
    seats = {(s["row"], s["col"]): s for s in layout["seats"]}

    for row in range(r0, r1 + 1):
        for col in range(c0, c1 + 1):
            s = seats.get((row, col))
            if s is None:
                tile = space
            else:
                texture = closed if s["reserved"] or not s["usable"] else open_
                tile = texture[s["handed"]]
            room.paste(tile, (WALL + (pad_left + col - c0) * T,
                              WALL + (pad_top + row - r0) * T))
    return room


def _map_box(room: tuple[int, int]) -> list[int]:
    """Pixel box of one floor tile on the dungeon-map sheet."""
    c, r = room
    return [MAP_SEP + c * (MAP_RW + MAP_SEP) + WALL,
            MAP_SEP + r * (MAP_RH + MAP_SEP) + WALL, T, T]


def emit(root: Path, palette: str = "blue",
         pad_top: int = 2, pad_left: int = 1) -> list[Path]:
    """Write the app's shipping assets, plus the manifest describing them.

    The app takes three things from this tool: the finished room at 1x (its
    background layer -- one image, drawn every frame, no tile bookkeeping), the
    five cell tiles on their own so Phase 2 can flip a seat without re-rendering
    the room, and `data/tile-manifest.json` recording where every pixel came
    from. The manifest covers the sprite and font files too, even though other
    tools write those -- a manifest with holes in it is not a manifest.
    """
    import cut_link
    import cut_moblin
    import nes_text

    layout = load_layout()
    (r0, r1), (c0, c1) = layout["grid"]["seat_rows"], layout["grid"]["seat_cols"]
    cols, rows = c1 - c0 + 1, r1 - r0 + 1
    irows = pad_top + rows

    room = build(cols, rows, doors=[("left", 0), ("left", irows - 2)],
                 palette=palette, pad_top=pad_top, pad_left=pad_left)
    place_seats(room, layout, palette=palette,
                pad_top=pad_top, pad_left=pad_left)

    # The same five tiles place_seats() paints with, as separate files.
    tiles = {"stipple": _floor_tile(SPACE_FLOOR_ROOM, palette)}
    for hand, hand_palette in HAND_PALETTE.items():
        tiles[f"seat-open-{hand}"] = _floor_tile(SEAT_FLOOR_ROOM, hand_palette)
        tiles[f"seat-closed-{hand}"] = _blocked_tile(hand_palette)

    written: list[Path] = []
    (root / "assets" / "tiles").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)

    room_path = root / "assets" / "room.png"
    room.save(room_path)
    written.append(room_path)
    for name, img in tiles.items():
        path = root / "assets" / "tiles" / f"{name}.png"
        img.save(path)
        written.append(path)

    rel = lambda p: str(p.relative_to(ASSETS))          # noqa: E731
    swap = {"from": "blue", "to": palette}
    files = {
        "assets/room.png": {
            "kind": "composed",
            "size": [room.width, room.height],
            "palette": palette,
            "emitted_by": "tools/room_kit.py --emit",
            "built_from": {
                "frame": {"sheet": "tileset", "box": list(FRAME)},
                "doors": {"sheet": "tileset", "strip_x": [DOOR_X0, DOOR_X1],
                          "row_y": DOOR_ROWS, "variant": "open",
                          "placed": [["left", 0], ["left", irows - 2]]},
                "seat_floor": {"sheet": "floor_map",
                               "box": _map_box(SEAT_FLOOR_ROOM)},
                "space_floor": {"sheet": "floor_map",
                                "box": _map_box(SPACE_FLOOR_ROOM)},
                "seats": "data/room-layout.json",
            },
        },
        "assets/tiles/stipple.png": {
            "sheet": "floor_map", "box": _map_box(SPACE_FLOOR_ROOM),
            "recolor": swap, "emitted_by": "tools/room_kit.py --emit"},
        "assets/legend.png": {
            "kind": "composed", "emitted_by": "tools/legend.py",
            "note": "built from these same tiles + the font, so it cannot drift"},
        "assets/font-white.png": {
            "sheet": "font", "kind": "atlas",
            "cell": nes_text.CELL, "cols": nes_text.ATLAS_COLS,
            "rows": len(nes_text.ROWS), "charset": nes_text.CHARSET,
            "color": "white", "emitted_by": "tools/nes_text.py --atlas",
            "note": "glyph index = CHARSET.indexOf(ch); regular grid, no JSON"},
    }
    for hand, hand_palette in HAND_PALETTE.items():
        files[f"assets/tiles/seat-open-{hand}.png"] = {
            "sheet": "floor_map", "box": _map_box(SEAT_FLOOR_ROOM),
            "recolor": {"from": "blue", "to": hand_palette},
            "emitted_by": "tools/room_kit.py --emit"}
        files[f"assets/tiles/seat-closed-{hand}.png"] = {
            "sheet": "tileset", "box": [*BLOCKED_TILE, T, T],
            "recolor": {"from": "teal", "to": hand_palette},
            "emitted_by": "tools/room_kit.py --emit"}
    for i, name in enumerate(cut_link.NAMES):
        files[f"assets/tiles/link-{name}.png"] = {
            "sheet": "link",
            "box": [cut_link.X0 + i * cut_link.PITCH, cut_link.ROW_Y, T, T],
            "emitted_by": "tools/cut_link.py"}
    for i, name in enumerate(cut_moblin.NAMES):
        files[f"assets/tiles/moblin-{name}.png"] = {
            "sheet": "moblin",
            "box": [cut_moblin.X0 + i * cut_moblin.PITCH,
                    cut_moblin.ROW_ORANGE, T, T],
            "emitted_by": "tools/cut_moblin.py"}

    manifest = {
        "version": 1,
        "note": "every shipping asset -> source sheet + measured coords",
        "sheets": {"tileset": rel(TILESET), "floor_map": rel(FLOOR_MAP),
                   "link": rel(cut_link.SHEET), "moblin": rel(cut_moblin.SHEET),
                   "font": rel(nes_text.SHEET)},
        "sheets_root": "Teaching/ZeldaAssets",
        # The app derives seat pixels from these, so they must match
        # place_seats(): x = wall + (pad_left + col - c0) * tile.
        "geometry": {"tile": T, "wall": WALL, "pad_top": pad_top,
                     "pad_left": pad_left, "seat_origin": [r0, c0]},
        "mirrored_at_runtime": {
            "link-left-1/2": "link-right-1/2 flipped",
            "moblin-left-1/2": "moblin-right-1/2 flipped",
            "note": "the NES drew them the same way; no files for these"},
        "files": files,
    }
    manifest_path = root / "data" / "tile-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    written.append(manifest_path)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", nargs="?", type=Path)
    ap.add_argument("--emit", type=Path, metavar="DIR",
                    help="write the app's assets under DIR (the seating/ root)")
    ap.add_argument("--list-doors", action="store_true")
    # ECON 416: 13 seats across, 11 rows.
    ap.add_argument("--cols", type=int, default=13)
    ap.add_argument("--rows", type=int, default=11)
    ap.add_argument("--pad-top", type=int, default=2, help="professor's space")
    ap.add_argument("--pad-left", type=int, default=1, help="the stairs")
    ap.add_argument("--palette", choices=sorted(PALETTES), default="blue")
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--bare", action="store_true",
                    help="empty room; skip the seat grid from room-layout.json")
    args = ap.parse_args()
    if not args.emit and args.out is None:
        ap.error("give an output path, or --emit DIR")

    if args.emit:
        for path in emit(args.emit, palette=args.palette,
                         pad_top=args.pad_top, pad_left=args.pad_left):
            print(f"  {path}")
        return

    if args.list_doors:
        S = args.scale
        rows = list(DOOR_ROWS)
        grids = [door_cells(o) for o in rows]
        ncol = max(len(g) for g in grids)
        sheet = Image.new("RGB", (ncol * (DOOR + 4) * S,
                                  len(rows) * (DOOR + 4) * S), (20, 20, 20))
        for r, g in enumerate(grids):
            print(f"{rows[r]:7s}: {len(g)} variants, widths {[c.width for c in g]}")
            for c, cell in enumerate(g):
                sheet.paste(cell.resize((cell.width * S, DOOR * S), Image.NEAREST),
                            (c * (DOOR + 4) * S, r * (DOOR + 4) * S))
        sheet.save(args.out)
    else:
        # Board at the top, so both real exits are on the left wall -- one at
        # the front, one at the back. Doors open onto the stairs. A door is 2
        # tiles tall, hence the -2.
        cols, rows = args.cols, args.rows
        layout = None
        if not args.bare:
            layout = load_layout()
            (r0, r1), (c0, c1) = (layout["grid"]["seat_rows"],
                                  layout["grid"]["seat_cols"])
            cols, rows = c1 - c0 + 1, r1 - r0 + 1
        irows = args.pad_top + rows
        room = build(cols, rows,
                     doors=[("left", 0), ("left", irows - 2)],
                     palette=args.palette,
                     pad_top=args.pad_top, pad_left=args.pad_left)
        if layout:
            place_seats(room, layout, palette=args.palette,
                        pad_top=args.pad_top, pad_left=args.pad_left)
            print(f"{len(layout['seats'])} seats from {LAYOUT.name}")
        room = room.resize((room.width * args.scale, room.height * args.scale),
                           Image.NEAREST)
        room.save(args.out)
        print(f"{cols}x{rows} seats + {args.pad_left} left / "
              f"{args.pad_top} top -> {room.width}x{room.height} at {args.scale}x")
    print(f"{args.out}")


if __name__ == "__main__":
    main()
