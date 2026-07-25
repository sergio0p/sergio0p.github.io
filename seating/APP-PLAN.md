# Phase 3 — the app (**built**; this is the plan it was built from)

Shipped as written. The living description now lives in `PLAN.md` (Phase 3) and
`GUI.md` (legend + claim flow); this file is the record of what was decided
before the build. What the plan left unspecified, settled while building — plus
the answer to its open question:

- `legend.py` pads its output to the room's width (288) so the legend, the
  instruction line and the room share one scale factor in the page's column.
- The dialog sits in whichever half of the room Link is *not* in, so the seat
  being confirmed stays visible while the student answers.
- The instruction line reads `SEAT CLAIMED` once seated — telling a student who
  already has a seat to tap one would be a lie.
- The dialog is instant for a tapped seat but waits 1.6 s of stillness for one
  reached with the arrows or a swipe. Added after testing: "stepping onto an
  open seat triggers the same dialog" (below) made walking a row impossible,
  since the first free seat crossed grabbed you.
- The interaction model below made `NO` restart the game. Changed after testing:
  it closes the box and leaves Link on the seat, so comparing two seats costs a
  tap rather than the walk back from the door. Tapping the seat he stands on
  re-opens the question.
- Section 1 below has the mirroring backwards, and so did the assets until it was
  spotted in play: the sheet's side pose faces **right**, not left — the sword
  rows reuse it with the blade extending right. `cut_link.py` now writes
  `link-right-1/2` and it is Link's *left* that is mirrored at runtime. The
  Moblin was always right-facing and always named so.
- The death below said "NES death spin → respawn at the front door". Added after
  testing: the console's whole sequence — enemies gone, red palette, spin, fade
  to black, and a `GAME OVER` / `RETRY?` menu whose `NO` does nothing. Silently
  teleporting back to the door read as a glitch rather than a death. See
  `GUI.md`.
- The plan's only direct control over Link was the one-tile swipe below. Added
  after testing on a phone: a finger on Link *carries* him, and he is dropped
  where it lifts. The swipe stays for a nudge, but a sprite under a finger should
  come with it, and on a zoomed map dragging beats aiming.
- Nothing below mentions zooming — the plan assumed fit-to-width was enough, and
  on a 390px phone a seat is ~21 CSS px, so it was not. Added after testing on a
  real device: the map pinches to 4× inside a frame that clips. The browser's own
  pinch was the first attempt and failed on the phone it was for.
- The open question below is answered: the dialog uses the layout's own
  coordinates.

The complete game as static files — vanilla JS, no framework, no build step,
GitHub Pages-ready. Auth + database (Phase 2) stay on hold pending the UNC SSO
answer; the claim is stubbed behind one function so Phase 2 plugs in without
rework.

The canonical look is `reference/econ416-room-lego.png` — the app reproduces it
1:1 and animates on top.

## Interaction model (settled)

- **Tap (mobile) / click (desktop) an open seat → Link pathfinds and walks there.**
- **Easter egg**: arrow keys and swipes also move Link one tile at a time.
  Unadvertised — no instruction copy for it.
- **Moblin = Prof. Parreiras** patrols the front stipple band left↔right.
  Touching it kills Link (NES death spin) → respawn at the front door. Costless
  before a claim.
- **On reaching a seat**: dialog shows the grid position and asks to confirm.
  **YES** → Link sits; the claim persists, so reopening the page shows Link on
  the seat. **NO** → the game restarts: dialog closes, Link back at the entrance.
- Students use this ONCE to claim; no revisits until in-class experiments later.

## 1. Asset emission (extend the existing tools)

- `tools/room_kit.py` gains `--emit DIR`:
  - `assets/room.png` — the approved room at 1× (288×272), seats painted. The
    app's background layer.
  - `assets/tiles/seat-{open,closed}-{right,left}.png` + `stipple.png` — the
    five cell tiles, for Phase 2 seat-flipping later.
  - `data/tile-manifest.json` — every emitted file → source sheet + coords
    (closes the PLAN.md manifest item).
- `tools/nes_text.py` gains `--atlas`: the 44-glyph charset as one strip,
  `assets/font-white.png`. The grid is regular (3 rows × 16 cols, 8px cells),
  so JS finds a glyph by `CHARSET.indexOf(ch)` — no per-glyph JSON.
- Link ×6 and Moblin ×4 are already in `assets/tiles/`. Right-facing Link and
  left-facing Moblin come from canvas mirroring (`ctx.scale(-1,1)`), the same
  trick the NES used.
- `tools/legend.py` default output moves to `assets/legend.png` (shipping
  asset, not a preview).

## 2. Page structure (new files)

- `index.html` — legend image on top, instruction line, `<canvas>` below.
- `style.css` — fit-to-width canvas, `image-rendering: pixelated`, centered
  column, mobile-first.
- `js/seating.js` — the whole engine, one file.

Instruction line: `TAP A SEAT` on touch, `CLICK A SEAT` on pointer devices
(`matchMedia('(pointer: coarse)')`), drawn with the font atlas so it stays
in-charset.

## 3. Engine (`js/seating.js`)

- **Data**: `fetch('data/room-layout.json')`. Cell→pixel uses the exact
  `place_seats()` formula — `x = WALL + (pad_left + col - c0) * 16`,
  `y = WALL + (pad_top + row - r0) * 16` (WALL=32, pads 2 top / 1 left) — so
  JS and Python can never disagree about where a seat is.
- **Render loop**: repaint background + Moblin + Link every frame
  (`requestAnimationFrame`). No tile bookkeeping.
- **State machine**: `IDLE → WALKING → DIALOG → (SEATED | restart)`, plus
  `DYING` from any walking state.
- **Input**: pointer events (unifies tap/click). Hit-test to a cell; open seats
  (`usable && !reserved`) only. BFS over walkable cells (all interior cells;
  walls excluded); the path avoids the Moblin's lane when an alternative
  exists, so autopilot deaths don't happen — only easter-egg steering can walk
  into it.
- **Walk**: tile-to-tile at ~1 tile / 150 ms, alternating the two frames per
  facing; facing from step direction.
- **Easter egg**: `keydown` arrows = one step; swipe (threshold ~24 px) = one
  step. Stepping onto an open seat triggers the same dialog as arriving by path.
- **Moblin**: spawns from the layout's instructor feature (row 0 col 7, nudged
  into the front stipple band per the layout's own note), patrols horizontally
  between the walls at ~half Link's speed, two frames + mirror. Frozen while a
  dialog is open. Collision = shared cell or ≥8 px overlap → `DYING`: Link
  cycles down/left/up/right-mirrored fast, then respawns at the front-door
  cell (0, 1).
- **Dialog** — canvas-drawn, NES-style (black fill, white double border, font
  atlas text; no new art):
  - Line 1: `ROW 4 SEAT 11` — the layout's own coordinates (cols counted from
    the instructor's right, matching the physical room). The charset has no
    colon or underscore, so words + digits is the format.
  - Line 2: `SIT HERE?`
  - Options: `YES` / `NO`, tappable; arrows + Enter also work (egg).
  - **YES** → `claimSeat(seatId)`: today a stub that writes `{seatId}` to
    `localStorage` and sets `SEATED` — Link sits facing down; a reload restores
    him there (per-device until Phase 2 makes it real). This one function is
    where Firestore + SSO identity lands later.
  - **NO** → restart: dialog closes, Link respawns at the entrance, `IDLE`.
- Closed seats aren't clickable, and arrow-walking onto them does nothing.

## 4. Docs (same pass)

- `PLAN.md`: fill in Phase 3 with this model; tick the manifest and room-tiles
  items; remove the stale line `four front seats to match the real chairs`
  (settled — the template renders them correctly as ordinary tiles).
- `GUI.md`: replace the stale legend/state wording with the two-axis rule
  (colour = hand, texture = availability) and the confirm-dialog flow; delete
  the "Hue alone is not enough" paragraph (settled — teal alone marks lefty
  seats).

## Verification

1. Emit assets; check `room.png` is pixel-identical to
   `reference/econ416-room-lego.png` at 1×.
2. `python3 -m http.server` in `seating/` (fetch needs http, not file://).
3. Desktop: click a far seat → route + walk; dialog wording correct for several
   seats (row 0 pairs included); YES → seated + survives reload; NO → back at
   entrance; arrows move him; walking into the Moblin dies + respawns.
4. Mobile (responsive mode + a real phone): fit-to-width, tap works, swipe
   works, text legible.
5. Charset safety: every displayable string passes `nes_text.py` render — it
   raises on any out-of-charset character.

## Open before build

- Seat-number wording: dialog shows the layout's own coordinates (cols from the
  instructor's right). Confirm this matches how seats should be named, or give
  the hall's physical numbering.
