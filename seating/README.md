# Zelda Seating

Static, serverless seat-claim app for ECON 416. Ships with the rest of
`sergio0p.github.io` — this directory *is* the deploy, so committing it publishes
it at **https://sergio0p.github.io/seating/**. No build step and no
configuration; see `PLAN.md` Phase 5 for what was checked and the one thing to
remember (bump `?v=` in `index.html` when the CSS or the JS changes).

## Layout
- `index.html`, `style.css`, `js/seating.js` — the page (built; claiming is stubbed
  at `claimSeat()` until Phase 2)
- `assets/` — the shipping art: `room.png` (the background layer), `legend.png`,
  `font-white.png` (the charset atlas), and `tiles/` for Phase 2's seat flipping.
  Emitted by the `tools/` cutters from sheets in `Teaching/ZeldaAssets/`; every
  file is traced back to its sheet and coords in `data/tile-manifest.json`
- `data/` — room-layout + tile-manifest JSON (the 134-seat map)
- `data/room-photos/` — photos of the actual lecture hall (2026-05-27), the
  physical source `room-layout.json` was built from. Local only: the images are
  gitignored (24 MB, and this directory is public), so the repo carries just
  their README — what they confirm and what they leave open
- `tools/` — Python: tile cutter (Pillow), Firestore seed, local export/grade,
  offline SQLite reassignment (schema in `Teaching/ZeldaAssets/seating/`)

## Decided
- **Scope**: one-time, claim-your-seat-for-the-term — a single seating chart,
  no per-date sessions.
- **Hosting**: **Cloud Run** serves the app and validates the access link, with
  Firestore behind it. *Changed 2026-07-24* — this began as a static page on
  GitHub Pages with no server, and that could not satisfy "no code, no page":
  a file server hands over the file before any check runs. `sergio0p.github.io/seating/`
  stays as the public front door pointing at it. Heavy work (grading,
  reassignment) is still done locally after export. See `PHASE2-PLAN.md`.
- **FCFS claim**: `onSnapshot` on non-identifying seat data for live availability
  + a server-side Firestore transaction for atomic, no-double-book claiming.
- **No identifiers in public documents**: the readable seat map carries
  `taken: true/false` and nothing else. PIDs live only in collections no client
  can read.
- **Identity**: a per-student random access code, delivered as a Canvas inbox
  message. Canvas sits behind UNC SSO, so a code sent that way is a secret only
  the enrolled student can fetch — the app's login is as strong as UNC's auth
  and no password is ever handled here. Codes are random (`secrets.token_urlsafe`),
  never derived from PID or Canvas ID, so they can't be guessed from public
  identifiers, and long enough (128 bits) that guessing is not a consideration.
  Delivered as a capability link with the token **in the path** — `…/c/<token>` —
  so there is nothing to type and an unknown link 404s before any app file is
  served. The link opens an ongoing scoped session (check my seat, change my
  seat, come back later), not a one-shot claim, and everything expires at the
  claim deadline. Roster is `Teaching/416/Data/416_roster.json` (52 students; `CanvasId` is the
  send target, `PID` stays the seat key). Onyen is not in the roster file but is
  available from Canvas on demand as the user's `login_id` — pull it at issue
  time if the codes want a human-readable handle.
  - **No enrollment oracle**: the app validates the code, not a name — typing
    someone's PID reveals nothing about whether they are in the class, and every
    bad code gets the identical "INVALID CODE".
  - **Lost codes** are re-sent through Canvas by the instructor, never displayed
    in the app. Self-service resend would rebuild the oracle.
- **Aesthetic**: classroom rendered as a Zelda dungeon room. Board at top;
  instructor = a monster at the front (Moblin or Aquamentus — TBD). Doors = cave-mouth
  objects (NOT gaps in the wall) at the front-left and back-left corners; no seat where
  a cave sits.
- **Seat visuals**: colour = handedness (blue right, teal left), texture = availability
  (flat floor open, bevelled recess closed). Claimed, reserved and off-limits share the
  closed texture so students can't claim them, while the data keeps open / claimed /
  reserved-empty distinct. A claim shows as Link standing on the seat — see `GUI.md`.
- **Art prep**: cut & recolor the existing NES sheets with Pillow/ImageMagick (no MCP).

## Future (designed for, NOT built now)
- **Seat trading via Top-Trading-Cycle**: students submit a ranked wish-list of seats,
  then TTC reassigns. Already accommodated — the SQLite `preferences` table + the
  offline export bridge are the hooks; assignments carry `source='algorithm'`. Build
  nothing for it now beyond keeping PID/seat IDs stable and exporting to SQLite.

## Open / defaults
- **Door/seat reconcile** — **settled by the photos.** Both real doors are on the
  left, at the front and the back; neither lines up with a tiered row. The default
  holds: caves sit at the aisle levels (row 0 / past row 10), where column 1 has no
  seat anyway, so the 134-seat set and all 11 left-handed seats stay intact.
- **Row/column counts — unverified.** 10 tiered rows × 13 columns has not been
  checked against the room; the photos can't resolve it. Count before Phase 2
  seeds Firestore, since every seat ID depends on it.
- **Unlabelled blue seat**: back-centre of the hall, the usual accessible/reserved
  marker. Inside the blocked rows 7-10 so nothing breaks today, but it is not in
  `reserved_set` — decide whether to mark it explicitly.
- **Reserved-seat set**: which specific seats are held for latecomers — TBD; default
  to the seats nearest the back-left cave until specified.
- **Front monster**: Moblin (literal orc) vs Aquamentus (boss pun) — cosmetic, swappable.
