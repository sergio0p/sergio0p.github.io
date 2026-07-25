# Room photos — the physical source for `room-layout.json`

Three shots of the ECON 416 lecture hall, taken 2026-05-27. These are the
ground truth `data/room-layout.json` was built from; keep them here so the
geometry can be re-checked without a trip to the room.

Exported from the macOS Photos library on 2026-07-24. Full-resolution
originals (5712 × 4284) as `.heic`, plus `.jpg` conversions for anything that
can't read HEIC. They are Live Photos — the paired `.mov` sidecars were not
exported.

**The image files are not in the repo** — only this README is. This directory
publishes to `sergio0p.github.io/seating/`, and 24 MB of photographs of the
room is neither part of the page nor something to put on a public URL; the
`.gitignore` keeps them out. They live here on disk, backed up by Dropbox, so
the geometry can still be re-checked without a trip to the room. What follows
is the record of what they settled, which is the part worth publishing.

| File | Vantage | Shows |
|---|---|---|
| `room-01-from-back-right` | Back-right, looking at the board | Board wall, podium, front-left door, the floor-row seat pairs, both side aisles |
| `room-02-from-front-center` | Floor level, looking up at the tiers | Full tier stack, back-left door, blue back wall, the lone blue seat |
| `room-03-from-front-left` | Front-left, raking along the tiers | Tablet-arm detail, floor-row seats against the ledge, left aisle stairs |

## What they confirm in `room-layout.json`

- **Row 0 is four seats in two pairs.** `0_3`, `0_4` — gap — `0_10`, `0_11`,
  sitting on the flat floor in front of the wooden ledge. Visible in 02 and 03.
- **Two doors, both on the left.** Front-left (01, under the exit sign) and
  back-left (02, in the blue wall). Matches the two `cave` features at
  `(0,1)` and `(11,1)`, and the "Door/seat reconcile" default in the root
  README stands: neither door lands on a tiered row, so no seat is displaced.
- **Aisles on both flanks, none in the middle.** Tiered rows run unbroken
  across, consistent with cols 1–13 having no center gap.
- **Board band and front furniture.** Whiteboard plus a darker panel to its
  left; podium front-right — the `board` span and the front-centre `monster`
  cell are placed against real geometry.

## What they do NOT settle

- **The counts.** 10 tiered rows × 13 columns is not verifiable from these
  angles — perspective compresses the back of the room. Worth one deliberate
  count before Phase 2 seeds Firestore, since every seat ID depends on it.
- **Per-seat handedness.** The layout puts all 11 left-handed seats in column 1
  (one per tiered row) plus `0_3`. The aisle-end tablet arms are visible in 01
  and 03 but not at a resolution that resolves which side they fold from.
- **The blue seat.** Back-centre in 02, the usual marker for an accessible or
  reserved seat. Not in `reserved_set`. It falls inside rows 7–10, which are
  already `usable:false` under the back-rows-blocked policy, so nothing breaks
  — but it is unlabelled rather than deliberately handled.
