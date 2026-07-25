# Zelda Seating — GUI

Consolidates the interface decisions that were scattered across `README.md`
(aesthetic, seat visuals) and `PLAN.md` (Phase 1 tile list, Phase 3 flow).

## Reference

`reference/celebration-cinema-seat-picker.png` — the Celebration Cinema seat
picker, on a phone. Borrowed structure, not styling:

- A **legend above the map**, as a two-column icon+label grid. Every seat state
  gets a named entry; nothing relies on the student inferring a colour.
- The screen drawn as a **labelled bar at the top** — our blackboard plays the
  same role, anchoring orientation.
- **Row letters down the left margin**, and `AISLE` marked in place on the map
  rather than in the legend. Landmarks get labelled where they are; only seat
  *states* go in the legend.
- A **zoom control** floating over the map, because a wide seat grid does not
  fit a phone at a readable size.
- A **sticky action bar** at the bottom with the current selection and the
  commit button.

The last two are the ones we did *not* borrow. Both answer "the map is wider than
the phone", and we answer it by shrinking the map to fit and letting a pinch
magnify it — a gesture everyone already has, so the zoom control would be a
button for something the fingers do anyway. See `## Claiming a seat`. Walking
Link to the seat and confirming there does the sticky bar's job (you always know
what you are about to claim) without spending screen height on it.

## The room template

`reference/zelda-room-template.png` — a clean, empty dungeon room, chosen by the
instructor as the basis for the classroom. Cut from Level 2 (Crescent), room grid
`(col 0, row 6)`, i.e. pixel `(1, 1063)`, size 256×176. Dungeon maps are a grid of
256×176 rooms with 1px separators, so room `(c, r)` sits at
`(1 + 257c, 1 + 177r)`.

**Measured interior: 12 columns × 7 rows of 16×16 tiles** (192×112 px, walls 32px
all round). That is the canonical NES room size, not an artefact of this
particular room.

### It does not fit the classroom

ECON 416 needs **13 × 11**. Overlay in `reference/room-fit-overlay.png` — green
cells fit, red ones don't:

| | Needed | Canonical room | Overflow |
|---|---|---|---|
| Columns | 13 | 12 | 1 tile (16px) — spills through the right-hand door |
| Rows | 11 | 7 | 4 tiles (64px) — spills clean out of the bottom wall |

Three ways out. **Option 1 chosen and built** — see the next section:

1. **Extend the room.** Keep 16×16 seats and tile the walls to a 13×11 interior:
   208×176 floor, 272×240 overall. Walls tile cleanly and 272×240 is within a
   hair of the NES screen (256×240), so it still reads as authentic. Costs:
   the wall statues and door recesses sit at fixed positions and have to be
   re-placed — and the doors *should* move anyway, since the real hall has them
   front-left and back-left rather than centred.
2. **Half-size seats.** At 8×8, a canonical room holds 24 × 14, so 13 × 11 fits
   with room to spare and the room stays pixel-exact. Costs: seats end up half
   Link's size, too small to carry the left/right tablet-arm shape the legend
   needs, and awkward to tap.
3. **Split across rooms.** Very Zelda — dungeons *are* room grids — but the
   student loses the single view of the hall.

### Building it — `tools/room_kit.py`

The room is composed, not cropped. The map screenshot can't be reused directly:
it's hand-decorated (70 distinct tiles in 176 cells) and its walls have **no
tiling period** — the best autocorrelation over the top band was 229 differing
pixels at an 80px shift, never zero.

The **Dungeon Tileset** sheet solves this. It carries a bare "Room Exterior"
frame at `(521,11)–(777,187)` whose four door slots are marked in flat colour —
red top, yellow left, blue right, green bottom — which is how the slot geometry
was recovered rather than eyeballed. A separate Doors block supplies **5 variants
× 4 orientations**, each exactly 32×32, laid out in the same order every time:
plain wall, open doorway, locked (keyhole), shutter (diamond), bombed hole. See
`reference/zelda-door-variants.png`.

**Settled: the open doorway** (`CHOSEN_DOOR = OPEN`) for both exits — a real exit
should read as passable. The other four stay available: `WALL_ONLY` seals a wall
outright, and `LOCKED` / `SHUTTER` / `BOMBED` are on hand if a door ever needs to
carry state.

`room_kit.py` harvests corners, one wall slice per side, and the floor tile, then
repeats them — so any interior size works and doors land anywhere on the grid:

```sh
python3 tools/room_kit.py out.png                 # 13×11 seats, the default
python3 tools/room_kit.py out.png --cols 20 --rows 16
python3 tools/room_kit.py out.png --pad-top 3 --pad-left 2
python3 tools/room_kit.py doors.png --list-doors
```

### Spacing and palette

The seat grid does not run to the walls. Two bands of open space:

| Band | Default | For |
|---|---|---|
| `--pad-top` | 2 tiles | The professor, in front of the board |
| `--pad-left` | 1 tile | The stairs — drawn as flat floor, not stepped |

Both are filled with a **stipple** texture so they read as circulation rather
than seating, while the seats sit on the plain tiled floor.

The stipple's background is `(32,56,236)` — **the identical value as the wall
base**, so the space reads as continuous with the walls rather than as another
kind of floor. That comes for free by taking both floors from **Second Quest
Level 3**: its `room(2,5)` is a single repeating stipple tile, `room(1,0)` the
plain tiled floor, and both share the wall palette.

The frame is ripped in the tileset's teal, so it gets swapped to match. Both are
4-colour NES palettes, which makes it a straight darkest-to-lightest remap:

| | teal (tileset) | `blue` (Level 3) |
|---|---|---|
| base | `(0,128,136)` | `(32,56,236)` |
| dark | `(24,60,92)` | `(0,0,168)` |
| light | `(0,232,216)` | `(92,148,252)` |

`--palette` selects it; `blue` is the default. Adding the remaining levels is a
matter of adding rows to `PALETTES` — the tileset's "Dungeon Colors (2nd Quest)"
block has the swatches for all nine, A and B.

ECON 416 is `build(13, 11, doors=[("left", 0), ("left", 9)])` — both exits on the
left wall, front and back, matching the caves at `(0,1)` and `(11,1)` in
`room-layout.json`. The bottom-right door seen in the photos is omitted; it leads
somewhere unknown and the hallway is on the left. Output:
`reference/econ416-room-lego.png`.

Two consequences worth remembering:

- **The walls are uniform.** Repeating one clean slice per side is *why* it
  tiles, but it drops the hand-placed statues and cracks. Scattering decorations
  back at chosen positions is a separate pass — deliberate, not an oversight.
- **Doors are on the 16px grid.** The original frame puts its side-wall slots at
  y=72, which is 4.5 tiles — off-grid. Placing on-grid instead is what makes the
  front door line up exactly with interior row 0.

The tileset also ships Zelda's own **Level 1–9 palettes, each with an A/B
variant** — the game's built-in recolour mechanism, and the natural way to do
seat states in-engine rather than inventing colours. The floor renders blue
because that's Level 2's palette.

### Phone arithmetic

Built at 288×272 (option 1, plus the stairs column). On a 390px iPhone the
column comes out 374 CSS px — scale 1.30, seats at ~21 CSS px, half Apple's
44pt touch target. Settled anyway: fit-to-width, and no zoom *control* — no
button, no slider, nothing floating over the map.
A mis-tap walks Link to the wrong seat and asks `SIT HERE?`, which is a cheaper
recovery than a magnifier is a cost — and the tap target for the answer is the
dialog, not the seat.

**Pinch to zoom, though — the map's own, not the browser's.** The first attempt
was to hand two-finger gestures to the browser (`#room` at `touch-action:
pinch-zoom`) for no UI and almost no code. It does not hold up: iOS refuses the
page pinch often enough to be unusable, and where it works it magnifies the
whole page — legend, margins and all — which is not what "zoom the map" means.

So the map zooms itself. `#stage` is a frame that keeps its place in the column
and clips; `#room` grows and slides inside it, so leaning in makes the sides fall
off the edges rather than pushing the rest of the page around. `#stage` is
`touch-action: none` and every gesture in it is the game's: **one finger** taps,
swipes, or carries Link (see `### Carrying Link`), **two** pinch — the distance
between them is the zoom, the point between them is the pan, both measured from
where the gesture started so a slow one cannot drift. Bounds: 1× to 4×, and the map can never be panned far
enough to show a gap. On a desktop the wheel does it (a trackpad pinch arrives
as ctrl+wheel), about the cursor.

Two details that make it more than a magnifier:

- **The zoom is carried by the canvas's CSS *width***, not by a `scale()`
  transform. Widening it is the same nearest-neighbour upscale the page already
  does at rest, so the pixels stay square instead of going soft at 4×.
- **Nothing else in the code knows about it.** Hit-testing already goes through
  `getBoundingClientRect`, which reports the zoomed, translated box, so a tap at
  3× lands on the seat under the finger with no camera arithmetic anywhere.

A message box takes the room back: it is drawn in art coordinates and at 4× it is
wider than the frame, so opening one drops to 1× and closing it returns to the
magnification you were reading at. After a death the zoom is dropped instead —
Link restarts at the door, and the view you had is looking somewhere else.

## The font

The NES Zelda font, cut from
`ZeldaAssets/miscellaneous/…Fonts.png` by `tools/nes_text.py`. Real game
glyphs, not a lookalike.

**The charset is the binding constraint on all UI copy:**

```
0123456789ABCDEF
GHIJKLMNOPQRSTUV
WXYZ,!'&."?-
```

44 glyphs — digits, uppercase A–Z, and `, ! ' & . " ? -`. There is **no
lowercase, no colon, no slash, no parentheses**. Every label, dialog line and
error message must be writable in that set, in caps. `nes_text.py` raises on an
unsupported character rather than dropping it, so a bad string fails at build
time instead of shipping a hole.

Four inks are available — white, blue `#3FBFFF`, red `#DB2B00`, green
`#83D313` — the game's own palette swaps. Glyphs are 8×8 on a 16px pitch;
measured grid coordinates live in the tool.

Verify the pipeline any time with:

```sh
python3 tools/nes_text.py --verify --scale 5 /tmp/charset.png
```

## The legend

**Two axes, not a list of states.** Every seat is a colour × texture pair, and
the two answer different questions:

| Axis | Values | Question it answers |
|---|---|---|
| Colour | blue / teal | Which hand? |
| Texture | flat floor / bevelled recess | Can you sit here? |

A left-handed seat is teal whether it is free or not — "open" and "lefty" are not
alternatives. That is why the `SEAT NOT AVAILABLE` row in the legend shows **both**
colours: a single sample would teach that unavailable seats have a colour of their
own, and a student looking at the teal bevels in column 1 would find nothing to
match.

Five rows, built by `tools/legend.py` from the same functions `place_seats()`
paints with, so the legend cannot drift from the map:

| Icon | Label |
|---|---|
| Link | `YOU` |
| Moblin | `PROF. PARREIRAS` |
| Teal floor | `LEFT-HANDED SEAT` |
| Blue floor | `RIGHT-HANDED SEAT` |
| Both recesses | `SEAT NOT AVAILABLE` |

**Three states collapse into one texture.** Claimed, reserved and off-limits all
render as the bevelled recess. A student only needs to know whether a seat is
available; *why* it isn't is none of their business. This keeps both the
discretionary late-arrival pool (6 seats) and the blocked back rows (52) private.
Handedness is dropped for blocked seats too — it cannot matter for a seat nobody
can take, and preserving it would leak which blocked seats are lefties.

**There is no `YOURS` tile.** A student who claims a seat sees Link standing on
it, which is also what they see on every later visit. That is a stronger marker
than a recoloured tile, and it costs no new art.

58 blocked, 76 claimable.

## Claiming a seat

Tap or click an open seat and Link walks there — the page is a game, not a form.
The confirm step is a canvas-drawn NES message box (black fill, white double
border, font atlas; no new art):

```
ROW 4 SEAT 11
  SIT HERE?
▸YES      NO
```

- Line 1 is the layout's own coordinates: rows from the board, columns from the
  instructor's right. The charset has no colon, so it is words and digits.
- The box sits in whichever half of the room Link is *not* in, so the seat being
  confirmed stays visible while the student answers.
- **When it opens depends on how you got there.** A tapped seat asks on arrival:
  the seat was the point of the walk. So does a seat Link is *dropped* on —
  letting go is as deliberate as tapping. A seat reached with the arrow keys or a
  swipe asks only after 1.6 s of standing still, because there the seat is just
  where the player happens to be — walking a row costs 150 ms a tile, and the
  first free seat crossed must not grab you. Another step cancels it.
- `YES` claims and Link sits. `NO` only closes the box: Link stays on the seat he
  turned down and the student picks another by tapping it or stepping off with
  the arrows. Nothing is undone, because nothing was done — walking back to the
  door to try again would be a punishment for browsing. Tapping the seat he is
  already standing on asks again, which is the only way back in once you have
  said no to it.
- The Moblin freezes while the box is open. Everywhere else he patrols the band
  in front of the board, and touching him is fatal; routes avoid his lane, so a
  student can only die by driving Link there themselves — with the arrow keys, or
  by carrying him into the professor.

### Carrying Link

Put a finger on him and he comes with it, and where it lifts is where he stands.
This is what a sprite under a finger is *for*, and it is the one control that
needs no explaining, so it is the one the phone leans on: at 2× a seat is a
comfortable target, and dragging beats tapping across a zoomed map where the
seat you want may be under your own hand.

Two things make it behave:

- **A touch on Link is a tap until the finger travels 6 px**, so the grab box can
  carry 8 art px of slack around a 16 px sprite — a fingertip needs it — without
  stealing taps from the seats beside him. Tap the neighbour and Link still walks
  there; drag from the same pixel and he is picked up.
- **A second finger ends the carry**: he settles on the nearest cell and the
  gesture becomes a pinch. Nothing is asked, because a pinch is not an answer.

He is free of the grid while carried and snaps to a cell on release — the walls
are not a place, so he cannot be dropped in one. Carried into the professor, he
dies exactly as he would have walking.

## Dying

The death is the NES one, beat for beat, because the beats are the joke — the
professor kills you and the cartridge takes it seriously:

1. **Every enemy leaves the screen.** The Moblin is drawn and moved only while
   alive, so he is simply gone from the frame Link is hit in.
2. **The palette flips red.** Canvas `color` blending takes the hue from a red
   fill and keeps the room's own luminance, which is what a palette swap does on
   hardware: the blues go red, the black stays black. A white flare over the
   first 140 ms is the hit itself.
3. **Link spins** through the four facings, 70 ms a frame, for 1120 ms.
4. **He disappears** and the red room fades to black over 420 ms.
5. **The menu**, on the black, in the same box as the seat confirmation:

```
 GAME OVER
  RETRY?
▸YES     NO
```

**`NO` does nothing.** Every other box in the app can be dismissed; this one is
the single dead end, because behind it there is nothing but the room you just
died in. `YES` puts Link back at the front door and the professor back on his
mark, pacing right.

The red is one flip that then *holds* — not a strobe. That is what the console
does, and it is also the accessible choice: a rapidly flashing saturated red is
the one thing the flash guidelines single out.

## Open

- Front monster: Moblin vs Aquamentus (cosmetic, swappable).
- Whether the caves and the monster get in-place labels like the reference's
  `AISLE`, or are left to read as themselves.
- ~~Phone layout~~ — settled: fit-to-width, with pinch-to-zoom of our own after
  the browser's proved unreliable on iOS. The legend, the instruction line and
  the room are all 288 art-px wide, so one column width scales all three by the
  same factor. On a 390px phone that is ~1.3×, putting seats at ~21 CSS px —
  under Apple's 44pt target, so pinch to 2× and they clear it. And a mis-tap
  costs one `NO`, which leaves Link right where he is.
