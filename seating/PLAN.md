# Zelda Seating — implementation plan

Six phases, ordered so the deterministic, reversible work comes first; nothing
touches live Firestore until the data model is solid. See `README.md` for the
settled decisions this plan rests on.

## Phase 0 — Room model (`data/room-layout.json`)
Single source of truth read by BOTH the renderer and the seeder: all 134 seats as
`(row, col, handed, reserved, usable)`, plus non-seat features — board across the top,
the two cave-doors (front-left / back-left, at aisle levels per the default), the front
monster, wall pieces. Geometry lives in data, not code.

Built from photos of the real hall, kept alongside it in `data/room-photos/` on
disk but gitignored (see Phase 5). They verify the irregular floor row, both
left-side doors, and the both-flanks-no-centre aisle arrangement. They do
**not** verify the 10 × 13 grid dimensions or per-seat handedness — see the
Phase 2 gate below. The README in that directory is committed, so the findings
survive without the pictures.

## Phase 1 — Art prep (Pillow, one tool per sheet)
Deterministic cut-and-recolor from `Teaching/ZeldaAssets/` sheets. Four tools rather
than the single `cut_tiles.py` first sketched here, because the sheets have nothing in
common but the palette: `room_kit.py` (room, doors, seat tiles), `cut_link.py`,
`cut_moblin.py`, `nes_text.py` (font). `room_kit.py --emit` writes the app's shipping
assets — `assets/room.png` at 1×, the five cell tiles, and
`data/tile-manifest.json` (every file → source sheet + measured coords, fully
reproducible).

Settled while building, and different from the sketch above:
- **Two axes, not five states** — colour = handedness, texture = availability. Claimed,
  reserved and off-limits all render as the bevelled recess; *why* a seat is unavailable
  is none of the student's business.
- **No "yours" tile, no off-limits colour, no blackboard, no dialog art.** A claimed
  seat is Link standing on it; the dialog is drawn on canvas from the font atlas.

**Font is done** — `tools/nes_text.py` cuts the real NES glyphs (44: digits, caps,
`, ! ' & . " ? -`; four inks). No lowercase or colon exists, so all UI copy must be
caps within that set; see `GUI.md`.

**Selection is collaborative:** the instructor picks the tiles. Start by examining the
candidate sheets in `Teaching/ZeldaAssets/` (tilesets, enemies-bosses, miscellaneous
fonts), present crop options, and let the user choose before cutting. Don't auto-pick.

## Phase 2 — Identity, claiming, and the server
**See `PHASE2-PLAN.md` for the full design and build order.** Settled 2026-07-24,
scheduled for the week of 2026-07-27. In short: per-student capability links
delivered over Canvas, validated **server-side on Cloud Run**, which serves the
app only after the token checks out — an unrecognised link gets a real 404 and
never sees a single app file. All writes go through the service, so the Firestore
rules are `read` on `seats` and nothing else, and no student identifier appears
in any publicly readable document.

**Gate before seeding:** confirm the room really is 10 tiered rows × 13 columns.
Seat doc ids are `"row_col"`, so a miscount bakes wrong IDs into Firestore, the
claims, and the SQLite export. One in-person count settles it.

This replaces the earlier sketch here, which had the static page talking straight
to Firestore with PID-based identity. That design could not enforce who a
claimant was — Firestore rules see only `request.auth` and the document being
written, so a code checked in browser JavaScript is a check the browser can skip.
The server removes the problem rather than working around it.

## Phase 3 — The app (`index.html` + `style.css` + `js/seating.js`) — **built**
Static files, vanilla JS, no framework and no build step. `assets/room.png` (emitted
by `room_kit.py --emit`) is the background layer, repainted every frame with Link and
the Moblin on top; geometry comes from `room-layout.json` through the same cell→pixel
formula `place_seats()` paints with, so renderer and tools cannot disagree.

- **Tap / click an open seat** → BFS route → Link walks there, one tile per 150 ms.
  Closed seats and bare floor are not clickable.
- **Moblin = Prof. Parreiras** patrols the band in front of the board at half speed.
  Routes avoid his lane, so autopilot never dies; only the easter egg can walk into him.
  Touching him runs the NES death in full: he vanishes, the palette flips red, Link
  spins, then he is gone and the room fades to black under a `GAME OVER` / `RETRY?`
  menu. **YES** restarts at the front door with the professor back on his mark; **NO**
  does nothing, which is the only screen in the app you cannot dismiss.
- **Drag Link with a finger or the mouse** and he follows it; let go and he settles
  on that cell, asking `SIT HERE?` if it is an open seat. A touch on him is still a
  tap until it travels 6 px, so the seats beside him stay tappable.
- **Easter egg** (unadvertised, no instruction copy): arrow keys and swipes step Link
  one tile, and override an autopilot route mid-walk.
- **Pinch to zoom the map**, 1× to 4×, with the wheel doing it on a desktop. The
  room is drawn into a frame that clips, so zooming crops the sides instead of
  moving the page; tapping and steering work zoomed, and a dialog drops to 1× for
  as long as it is up. The browser's own pinch was tried first and dropped — iOS
  refuses it too often, and it magnifies the whole page. See `GUI.md`.
- **On arrival**: a canvas-drawn NES dialog — `ROW 4 SEAT 11` / `SIT HERE?` /
  `YES` `NO`, placed in whichever half of the room Link is not standing in.
  **YES** → `claimSeat()`; **NO** → the box closes and Link stays on that seat, free
  to be sent elsewhere by tap or arrows. Tapping the seat he is standing on asks again.
  A tapped seat asks the moment Link arrives — it was the point of the walk. A
  seat reached with the arrows asks only after 1.6 s of standing still, so
  stepping along a row does not get grabbed by the first free seat crossed.
- **`claimSeat(seatId)` is the one seam for Phase 2.** Async and failable already, so
  the Firestore transaction drops in where `localStorage` is today with nothing else
  to change. Until then a claim is per-device: reopening the page shows Link on the
  seat. `seating.reset()` in the console clears it, or `?reset` in the URL for a
  phone, which has no console — it clears on every load until the query is dropped.

Still Phase 2's, not built: `onSnapshot` for live availability, PID identity and
eligibility, the no-double-book transaction, "find my seat".

## Phase 4 — Offline bridge (`tools/export_to_sqlite.py`)
Pull Firestore `seats` → the existing SQLite schema (in `Teaching/ZeldaAssets/seating/`).
This is the Top-Trading-Cycle on-ramp: once it exists, the future preferences form + TTC
run on exported data with no rework.

## Phase 5 — Deploy
`seating/` is a directory of the `sergio0p.github.io` repo, which GitHub Pages
serves as it stands, so deploying is committing it — no build, no workflow, no
Pages configuration. Live at **https://sergio0p.github.io/seating/**.
(User does the commit/push.)

```
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite add seating
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite commit -m "Add the ECON 416 seating map"
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite push
```

**Checked against the subdirectory, not just localhost:**
- Every path in the page is relative, so `/seating/` needs no configuration. Served
  from that subpath the app makes 16 requests, all under `/seating/`, none failing;
  tap → walk → `SIT HERE?` → claim → survives a reload, and `?reset` still clears.
- No build step, no dependencies, no external hosts — nothing to install and
  nothing to break under HTTPS.
- Nothing here starts with `_`, which Jekyll drops from the published site.
- `?v=` on the stylesheet and the script in `index.html`: **bump it on every
  deploy**, or a phone keeps the old file for as long as it likes.
- The favicon is Link's down-facing sprite — already a 16×16 PNG with alpha.
- `.gitignore` keeps `.DS_Store` and `__pycache__` out.

Everything committed here is public and downloadable. The docs, `reference/`
and `tools/` are fine — they are the record of how the room was built, and
`reference/` is cited by `GUI.md`, `APP-PLAN.md` and the two `cut_*.py` tools.
**The lecture-hall photos are not**: `data/room-photos/*.heic|jpg` is
gitignored. They are 24 MB against a 437 KB app, the page never loads them, and
pictures of the room have no business on a public URL. They stay on disk; their
README ships so the geometry they settled is still on the record.

## Inputs still needed (all have defaults in README.md)
- Reserved-seat set (default: seats nearest the back-left cave)
- Front monster: Moblin vs Aquamentus (cosmetic, swappable)
- ~~Door/seat reconcile~~ — settled: photos show both doors on the left at front
  and back, neither on a tiered row. Default stands, no seat data changes.
- **Row/column count** — must be verified in the room before Phase 2 seeds.
- **GCP project** — fresh `econ416-seating`, or reuse `ldb-form-test`; and
  billing enabled either way (Cloud Run requires it; usage here is free-tier).
- **Claim deadline** — a date and time. Every link expires against it.
- ~~Code enforcement~~ — settled: server-side on Cloud Run. See `PHASE2-PLAN.md`.
- The unlabelled blue seat (back-centre): mark it explicitly, or leave it covered
  by the rows 7-10 block.

## Status
- [x] Project skeleton + README + this plan
- [x] Phase 0 — room-layout.json
- [x] Room photos archived in `data/room-photos/` (2026-05-27, exported
      2026-07-24; local only — gitignored, README committed)
- [x] `GUI.md` — legend spec + interface decisions consolidated
- [x] Phase 1 — art prep
  - [x] NES font (`tools/nes_text.py`, charset verified) + `--atlas` for the app
  - [x] Room + doors (`tools/room_kit.py`) — 13×11 composed from tileset pieces,
        both doors on the left wall front/back; see `GUI.md`
  - [x] Link ×6 (`cut_link.py`) and Moblin ×4 (`cut_moblin.py`); the mirrored
        facings are drawn by mirroring, as the NES did, so they are not files
  - [x] seat + room tiles — settled: colour = handedness, texture = availability
  - [x] `data/tile-manifest.json` — every shipping asset → sheet + measured coords
        (`room_kit.py --emit`)
- [ ] Phase 2 — seed + rules
- [x] Phase 3 — the app (claim stubbed at `claimSeat()` until Phase 2 lands)
- [ ] Phase 4 — export bridge
- [ ] Phase 5 — deploy
