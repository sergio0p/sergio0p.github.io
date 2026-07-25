# Phase 2 — Identity, claiming, and the server

Implementation plan, written 2026-07-24 for the week of 2026-07-27. This
supersedes the Phase 2 sketch in `PLAN.md`, which assumed a static app talking
straight to Firestore with PID-based identity. It doesn't.

## Your requirements

Everything below is built to satisfy these, in your words, gathered while we
argued it out:

1. Each student gets a **unique access code**, emailed through Canvas.
2. Codes are **random** — never derived from PID, Canvas ID, or onyen.
3. The email carries a **clickable link**; nothing to type.
4. The code lives in the **URL path**, not a query string.
5. **Without a code you don't get to see the page** — a bogus URL returns a real
   404, not a JavaScript curtain over an already-downloaded app.
6. Validation happens **server-side**. The browser is not trusted.
7. **Cloud Run**, not Firebase App Hosting (framework/SSR product, wrong fit) and
   not Compute Engine (a VM to patch and pay for).
8. A local **table of (Canvas ID, code)** is the record of who got what.
9. Onyen is not needed. It's available from Canvas as `login_id` if we ever want
   a human-readable handle.
10. The link opens an **ongoing scoped session** — check my seat, change my seat,
    come back next week — not a one-shot claim, the way recommendation systems
    actually behave.

Two things were added on the way and are in the design below: **no student
identifiers in any publicly readable document**, and **an expiry date** so every
link in every inbox goes inert when claiming closes.

## Architecture

### Where things run

| Piece | Where | Deploy |
|---|---|---|
| The gate, the API, the static files | Cloud Run (`econ416-seating`) | `gcloud run deploy --source .` |
| Seat data, code hashes, claims | Firestore (same GCP project) | `tools/seed_seats.py` |
| Public front door | GitHub Pages, `sergio0p.github.io/seating/` | `git push` |

One container serves the app *and* validates the token *and* handles writes.
There is no second service and no Cloud Function — the whole point of Cloud Run
here is that it is one thing.

`sergio0p.github.io/seating/` is not wasted: it becomes a short public page
saying seat claiming is open and to check your Canvas inbox for your link. All
the deploy-ready work already done (relative paths, favicon, cache buster)
carries over to it unchanged.

### Data model

Three collections. The rule of the whole design: **anything a browser can read
contains no student identifier.**

```
seats/{row_col}            PUBLIC READ, no client writes
  { row, col, handed, reserved, usable, taken: bool, updatedAt }
```
Enough to draw the live map and nothing else. `taken` is a boolean — not a PID,
not a name. This is the only collection any browser ever touches, and
`onSnapshot` on it gives real-time availability with no authentication at all.

```
codes/{sha256(token)}      NO CLIENT ACCESS
  { canvasId, pid, issuedAt, expiresAt, revoked: bool }
```
The document ID is a **hash** of the token, never the token. If the database
ever leaks, nobody gets a working link out of it — the same reason you don't
store passwords. The server hashes what arrives in the URL and looks that up.

```
claims/{pid}               NO CLIENT ACCESS
  { seatId, canvasId, claimedAt, source: 'student' }
```
One document per student, so one-seat-per-student is enforced by document-ID
uniqueness rather than by a rule that has to be right. `source` is already the
field Phase 4's Top-Trading-Cycle export expects, so reassignments land here as
`source: 'algorithm'` later with no schema change.

### Firestore rules

```
match /seats/{id}  { allow read: if true;  allow write: if false; }
match /{doc=**}    { allow read: if false; allow write: if false; }
```

That's the entire ruleset, and it's the strongest posture available: no client
writes anywhere, ever. All enforcement is ordinary Python in the service, where
it can be read, tested, and reasoned about — not expressed in the rules DSL,
which is where the previous design kept running aground.

### Endpoints

```
GET  /                     public landing page (or 302 to the GitHub front door)
GET  /c/<token>            THE GATE.  valid -> set cookie, 302 to /app
                                      anything else -> 404, identical every time
GET  /app                  the seating app; no cookie -> 404
GET  /api/me               { seatId | null, deadline, displayName }
POST /api/claim  {seatId}  transactional claim / change of seat
POST /api/release          give up the seat (before the deadline)
GET  /assets/...           css, js, art
```

`GET /c/<token>` is the only place a token is ever accepted, and it trades the
token for a session immediately, then **redirects to a clean `/app` URL**. The
token leaves the address bar, the browser history, and any screenshot taken
after the first second. Serve everything with `Referrer-Policy: no-referrer` so
it can't leak sideways either.

Session = an **HttpOnly, Secure, SameSite=Lax cookie** holding `canvasId` plus an
expiry, HMAC-signed with a key from Secret Manager. Stateless, so there's no
session collection to clean up; expiry is baked into the signature.

### `POST /api/claim`, the only operation that matters

In one Firestore transaction, server-side:

1. Cookie valid and unexpired, and now < deadline. Else 403.
2. Read `seats/{seatId}`: must be `usable`, not `reserved`, and `taken == false`.
   Else 409 — this is the no-double-booking guarantee, and it is a real
   transaction rather than a hope.
3. If `claims/{pid}` already exists, flip the old seat's `taken` back to false in
   the same transaction. That's the "change my seat" path, and it can't strand a
   seat as permanently occupied.
4. Set `seats/{seatId}.taken = true` and write `claims/{pid}`.

## The token

`secrets.token_urlsafe(16)` — 22 characters, 128 bits. It arrives as a
clickable link so nobody types it, which makes length free and brute force
irrelevant. Not derived from anything.

Link shape: `https://<service-url>/c/kJ8vQ2mNp4rT7wXyZ1aBcD`

Every failure — unknown token, expired token, revoked token, malformed token —
returns the **identical 404**. No distinction to measure, and a per-IP rate limit
on misses so nobody can grind against it anyway.

## Tools to write

```
tools/issue_codes.py     roster -> tokens -> codes/{hash} in Firestore
                         -> data/codes-local.json  (GITIGNORED, already added)
                         -> prints the 52 links
tools/send_codes.py      Canvas MCP send_conversation, one call per student
                         (bodies differ), resumable, logs what was sent
tools/seed_seats.py      room-layout.json -> seats collection
tools/revoke_code.py     mark revoked / reissue for a lost or dropped student
```

`data/codes-local.json` is the (Canvas ID, code) table you asked for and it is
the one genuinely secret file in this project — it holds 52 working credentials.
It is already in `.gitignore`. It never gets committed, never gets deployed, and
lives only on your machine.

**Resend** is instructor-run through Canvas, never self-service in the app. A
self-service "resend my code" box would rebuild the enrollment oracle the whole
design exists to avoid.

## What changes in the app

Less than you'd expect. `js/seating.js` keeps rendering the room, walking Link,
zooming, and dragging exactly as it does now.

- `claimSeat(seatId)` — the seam that was built for this — swaps its
  `localStorage` body for `fetch('/api/claim', …)`. It is already async and
  already failable, so nothing around it changes.
- On load, `GET /api/me` replaces the `localStorage` read that currently decides
  whether Link starts on a claimed seat.
- The seat map subscribes to `seats` with `onSnapshot`, so a seat taken by
  another student greys out live. (Fallback if you'd rather not ship the
  Firebase JS SDK at all: poll `GET /api/seats` every few seconds. Slightly more
  traffic, one less public surface. Either is fine at 52 students.)
- New NES dialog states: `SEAT TAKEN` on a 409, `TIME IS UP` past the deadline.
- `?reset` and `seating.reset()` stay as local-only debug helpers.

## Build order, next week

1. **Count the room.** Blocks everything — see below.
2. Create the GCP project, enable billing, Firestore, Cloud Run, Secret Manager.
3. `seed_seats.py` → verify 134 seats and the blocked rows land correctly.
4. Publish the rules above. Confirm from a browser console that a write is
   refused.
5. Write the service: gate, session, `/api/me`, `/api/claim`, static serving.
   Deploy. Confirm a bogus path 404s **before** any app file is served.
6. Wire `claimSeat()` and `onSnapshot` in the app; the NES failure dialogs.
7. `issue_codes.py` against the real roster, but send to **yourself first** —
   one test student, full round trip, before 52 messages go out.
8. Playwright pass (below).
9. `send_codes.py` for real. Front-door page pushed to GitHub Pages.

## Decisions needed before step 2

- **Row and column count.** Still unverified: `room-layout.json` assumes 10
  tiered rows × 13 columns, and seat document IDs are `"row_col"`. A miscount
  bakes wrong IDs into Firestore, the claims, and the SQLite export. One
  in-person count settles it and nothing should be seeded until it's done.
- **Which GCP project.** `ldb-form-test` exists but is named for something else
  and would now hold student PIDs. A fresh `econ416-seating` project is free,
  takes two minutes, and keeps this separable from `form.html`. Recommended.
- **Billing.** Cloud Run requires a billing account on the project. Usage here
  is far inside the free tier; expect a zero invoice.
- **The deadline.** A date and time. Everything expires against it.
- **The reserved-seat set.** Which seats are held for latecomers. Default: the
  ones nearest the back-left cave.
- **The unlabelled blue seat**, back-centre — mark it reserved explicitly, or
  leave it covered by the rows 7–10 block.

## What this does not protect against

Worth writing down so nobody later mistakes the system for something it isn't:

- **A forwarded link works for whoever holds it.** Inherent to capability URLs,
  including the recommendation systems this is modelled on. Bounded by: one seat
  per student, the deadline, and the fact that you can see and reverse any claim.
- **The occupancy map is public.** By design — students need to see which seats
  are free. It shows *that* a seat is taken, never by whom.
- **A student can screenshot their own link.** Same bound as forwarding.
- **Nothing here is FERPA-grade identity.** It proves possession of a code that
  was delivered behind UNC SSO, which is appropriate for choosing a chair and is
  not appropriate for anything graded.

## Test plan

Extend the existing Playwright scripts in the scratchpad:

- Bogus path → HTTP 404, and **no app asset requested**. This is requirement 5;
  assert on the network log, not on what's painted.
- Expired token → the same 404, byte for byte.
- Valid token → 302 → `/app`, cookie set, token absent from the final URL.
- `/app` with no cookie → 404.
- Claim → `taken: true`, `claims/{pid}` written, survives reload.
- Two sessions racing the same seat → one 200, one 409.
- Change seat → old seat frees in the same transaction.
- Claim after the deadline → 403, `TIME IS UP`.
- Console write attempt against `seats` → refused by rules.
- Regressions: zoom, drag, death, dwell, `?reset` — all still pass.

## Cost

Cloud Run scales to zero, so idle is free. 52 students clicking a handful of
times is well inside the free allowance for requests, CPU, Firestore reads and
writes. The only real cost is the 1–2 second cold start on the first click after
a quiet spell; pin one warm instance during claim week for a few dollars if that
bothers you, then set it back to zero.
