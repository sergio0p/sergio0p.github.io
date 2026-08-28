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
seats/{row_col}            NO CLIENT ACCESS (see below), no client writes
  { row, col, handed, reserved, usable, taken: bool, updatedAt }
```
Enough to draw the live map and nothing else. `taken` is a boolean — not a PID,
not a name. **Superseded as built:** this was `PUBLIC READ` when the browser
subscribed with `onSnapshot`. The app polls `GET api/seats` through the service
instead, so the public read was dropped and *no* client reads any collection.

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

As built (`firestore.rules`) — stricter than this plan originally called for,
because polling removed the need for any public read:

```
match /{doc=**}    { allow read: if false; allow write: if false; }
```

That's the entire ruleset, and it's the strongest posture available: no client
read and no client write, anywhere, ever. All enforcement is ordinary Python in the service, where
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
tools/seed_seats.py      room-layout.json -> seats collection            [BUILT]
tools/issue_codes.py     LIVE Canvas roster -> tokens -> codes/{hash}     [BUILT]
                         -> ~/Dropbox/Teaching/416/Data/416_seating_codes.json
tools/send_codes.py      prepares the outbox for Canvas MCP,              [BUILT]
                         resumable via --mark-sent / --status
tools/revoke_code.py     mark revoked / reissue for a lost or dropped     [BUILT]
                         student
server/main.py           the gate + API + static serving                  [BUILT]
server/test_service.py   API end-to-end, local and --remote               [BUILT]
server/test_browser.py   the student journey through real Chrome          [BUILT]
```

`~/Dropbox/Teaching/416/Data/416_seating_codes.json` is the (Canvas ID, code)
table you asked for and it is the one genuinely secret artifact here — it holds
a working credential for every student. It lives **outside this repository**:
`seating/` is published to GitHub Pages, and a gitignore is a thin thing to put
between 50 live credentials and a public website. Mode 0600, never committed,
never deployed.

**Resend** is instructor-run through Canvas, never self-service in the app. A
self-service "resend my code" box would rebuild the enrollment oracle the whole
design exists to avoid.

## What changes in the app (the plan; see "What changed in the app" for as-built)

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
  traffic, one less public surface. Either is fine at this size.)
- New NES dialog states: `SEAT TAKEN` on a 409, `TIME IS UP` past the deadline.
- `?reset` and `seating.reset()` stay as local-only debug helpers.

## Build order

1. ~~Count the room.~~ Done — the layout was already settled; see Decisions.
2. ~~Create the GCP project, enable billing, Firestore, Cloud Run, Secret
   Manager.~~ **Done 2026-08-16** — see `Provisioning` below.
3. ~~`seed_seats.py` → verify 134 seats and the blocked rows land
   correctly.~~ **Done 2026-08-16** — 134 documents written and verified.
4. ~~Publish the rules. Confirm a write is refused.~~ **Done 2026-08-16**
   — deployed and probed unauthenticated; see `Rules — deployed`.
5. ~~Write the service: gate, session, `/api/me`, `/api/claim`, static
   serving. Deploy. Confirm a bogus path 404s before any app file is
   served.~~ **Done 2026-08-17** — deployed, and the 404-before-any-asset
   claim is asserted by test, not by inspection.
6. ~~Wire `claimSeat()` and the live map in the app; the NES failure
   dialogs.~~ **Done 2026-08-17** — polling, not `onSnapshot`; see below.
7. `issue_codes.py` against the real roster, but send to **yourself first** —
   one test student, full round trip, before the class gets theirs.
   **BLOCKED on the roster** — see `Roster problems`.
8. ~~Playwright pass.~~ **Done 2026-08-17** — `server/test_browser.py`.
9. `send_codes.py` for real. Front-door page pushed to GitHub Pages.

## Decisions — settled 2026-08-16

Everything that blocked step 2 is closed. `data/room-layout.json` is the single
source of truth and was re-verified against its own declared counts on
2026-08-16: 134 seats, 6 reserved, 52 off-limits, 76 claimable, IDs unique.

- ~~**Row and column count.**~~ **Settled — it was never open in the data.** The
  layout is fixed and *not* a rectangle: row 0 is the 4-seat floor row
  (cols 3, 4, 10, 11), rows 1–10 are 13 wide. The old wording here predated the
  instructor setting `reserved_set` and `off_limits` and was simply stale.
- ~~**Which GCP project.**~~ Fresh `econ416-seating`, created via CLI/API.
- ~~**Billing.**~~ Linked to `01F3A6-EFDF5C-89260F`, plus a $1/month budget alert.
- ~~**The deadline.**~~ **2026-08-27T00:00:00−04:00** (midnight *ending* Wed
  Aug 26, America/New_York). Every code's `expiresAt` and the `/api/claim`
  deadline check use this one constant.
- ~~**The reserved-seat set.**~~ **Set by the instructor**, in the layout:
  `0_4`, `0_10`, `0_11` (front floor) + `1_13`, `2_13`, `3_13` (col 13, rows 1–3).
  All right-handed, so no left-handed seat is withheld.
- ~~**The unlabelled blue seat.**~~ Covered by the rows 7–10 `usable:false` block.
- ~~`0_3`.~~ **Settled: stays claimable.** The fourth floor-row seat is
  left-handed, and reserving it would withhold one of only 11 left-handed seats.
  `room-layout.json` already encodes this — no data change was made.

Still open, cosmetic only: **front monster** — Moblin vs Aquamentus.

## Provisioning — DONE 2026-08-16

Provisioned end to end over the CLI/REST API; no console clicking. Verified live
afterwards.

| Thing | Value |
|---|---|
| Project ID | `econ416-seating` |
| Project number | `273200940906` |
| Billing account | `01F3A6-EFDF5C-89260F` — `billingEnabled: true` |
| Firestore | `(default)`, **`nam5`** (US multi-region), Native mode, `freeTier: true` |
| APIs enabled | run, firestore, secretmanager, artifactregistry, cloudbuild, billingbudgets |
| Budget alert | $1/month, emails at 50% and 100% |

**Firestore location is `nam5`, not the `us-east1` this section originally
specified.** Multi-region rather than regional: no practical difference at 52
students and the free tier applies either way, but it is fixed at creation —
changing it means deleting and recreating the database.

Two gotchas worth keeping, both cost real time:

- The `beta` component is not installed, so `gcloud beta billing` fails. Billing
  is linked over the Cloud Billing REST API instead.
- `billingbudgets.googleapis.com` rejects Application Default Credentials
  without a quota project. Enable the API on the project *and* send
  `x-goog-user-project: econ416-seating`.

Reproduce (or rebuild after a teardown):

```bash
PROJECT=econ416-seating
BILLING=billingAccounts/01F3A6-EFDF5C-89260F
TOK=$(gcloud auth print-access-token)

gcloud projects create "$PROJECT" --name="ECON 416 Seating"

curl -s -X PUT -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "{\"billingAccountName\":\"$BILLING\"}" \
  "https://cloudbilling.googleapis.com/v1/projects/$PROJECT/billingInfo"

gcloud services enable run.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com billingbudgets.googleapis.com --project "$PROJECT"

gcloud firestore databases create --location=nam5 --project "$PROJECT"
```

## Seeding and rules — DONE 2026-08-16

**Seed.** `tools/seed_seats.py` writes `data/room-layout.json` into `seats/`.
134 documents, IDs `"{row}_{col}"`, fields exactly as the data model above.

It validates the layout against its own declared `counts` before writing a
single document and exits non-zero on any disagreement — duplicate IDs, an ID
that contradicts its own row/col, a `reserved` flag outside `reserved_set`, a
`usable:false` seat outside the off-limits rows. Confirmed by feeding it a
deliberately corrupted layout: it caught every planted fault and refused.

**Re-running is safe, and that is the point.** A seed that reset `taken` would
silently un-claim every student if anyone re-ran it during claim week. By
default an existing document keeps its `taken` value and only layout fields
refresh; `--reset-claims` forces `taken:false` and prompts before it does.
Verified live: a seat set `taken:true`, re-seeded, survived.

```bash
python3 tools/seed_seats.py --dry-run   # validate, write nothing
python3 tools/seed_seats.py             # seed / refresh, claims preserved
python3 tools/seed_seats.py --verify    # diff Firestore against the layout
```

**Rules — deployed** from `seating/firestore.rules` via `seating/firebase.json`,
kept separate from the repo-root Firebase config so `ldb-form-test` is untouched:

```bash
firebase deploy --only firestore:rules --project econ416-seating
```

Probed unauthenticated over the Firestore REST API — which is what a browser
is — rather than trusted on inspection:

| Probe | Expected | Result |
|---|---|---|
| read `seats/0_3` | allow | 200 |
| list `seats` | allow | 200, 134 docs |
| write `seats/0_3` | deny | `PERMISSION_DENIED` |
| read `claims/{pid}` | deny | `PERMISSION_DENIED` |
| list `claims` | deny | `PERMISSION_DENIED` |
| create in `claims` | deny | `PERMISSION_DENIED` |
| read `codes/{hash}` | deny | `PERMISSION_DENIED` |

## The service — DEPLOYED 2026-08-17

    https://econ416-seating-273200940906.us-east1.run.app

| Thing | Value |
|---|---|
| Cloud Run service | `econ416-seating`, region `us-east1` |
| Runtime identity | `seating-run@econ416-seating.iam.gserviceaccount.com` |
| Its roles | `datastore.user`, `secretmanager.secretAccessor` — nothing else |
| Session key | Secret Manager `session-secret` (256-bit, generated locally) |
| Scaling | min 0 / max 4, 512Mi, 1 vCPU |

The runtime is a **dedicated** service account, not the default compute one:
that default carries `roles/editor` across the whole project, which is far too
much for a service holding student PIDs. This one can read the session secret
and talk to Firestore, and that is the entire list.

**Firestore rules are now deny-everything.** The original design needed a public
read on `seats` for the browser's `onSnapshot`; choosing polling through the
service instead made even that unnecessary, so no client can read or write any
collection. The service bypasses rules with admin credentials and is the only
thing that touches the data. Verified unauthenticated: `seats`, `claims` and
`codes` all return `PERMISSION_DENIED`.

### Two things that cost real time

- **`/healthz` is not usable on Cloud Run.** Google Frontend answers that exact
  path with its own 404 before the request reaches the container. Every other
  path arrives normally. The health route is `/health`.
- **Secret Manager's Python client takes `request={"name": ...}`**, not
  `name={"name": ...}`. The latter raises a `TypeError` deep inside proto-plus
  and surfaced only as a 500 from the deployed gate — local tests never saw it
  because they take the key from `SESSION_SECRET`. The remote test run is what
  caught it, which is the argument for having one.

### The grace window — a design change

Sessions and codes now outlive the deadline by 7 days (`CLAIM_GRACE_DAYS`).
The original design expired everything exactly at the deadline, which meant the
cookie died at the same instant claiming closed: a student opening their link on
the 26th got a bare 404, and the `TIME IS UP` dialog the plan calls for could
never render — the 403 branch was unreachable. During grace the app loads
read-only, `/api/me` reports `closed: true`, and claim/release return 403.
**Claiming still stops dead at the deadline**; only visibility extends.

## What changed in the app

`js/seating.js` keeps its renderer, walking, zoom and drag untouched.

- `claimSeat()` now `POST`s `api/claim` and returns a reason — `ok`, `taken`,
  `closed`, `error` — because "someone beat you to it" and "claiming has closed"
  need different words on screen. A failed claim puts Link back on his previous
  seat, not at the door.
- On load, `GET api/me` replaces the `localStorage` read. The seat follows the
  **student**, not the device: a different phone with the same link shows the
  same seat. Asserted in `test_browser.py` with a fresh browser profile.
- **Polling, not `onSnapshot`** (`api/seats` every 5s, paused when the tab is
  hidden). At ~51 students the traffic is nothing, and it keeps the Firebase SDK
  and every public read path off the page.
- `room.png` bakes the seats in, so a seat claimed while you are looking gets
  the bevelled tile painted over it — `drawTakenSeats()`.
- New dialogs: `SEAT TAKEN`, `TIME IS UP`, `NO CONNECTION`.
- **Offline degrades to the old behaviour.** If `api/me` 404s there is no
  service behind the page, so claims fall back to `localStorage` exactly as
  before Phase 2. That is what keeps the GitHub Pages copy working as a demo.

## Test results — 2026-08-17

Both suites run against the **live** project; nothing is mocked, because the two
things most worth proving are the two a mock would fake.

| Suite | Local | Against Cloud Run |
|---|---|---|
| `server/test_service.py` | 53 pass | 48 pass (deadline block is local-only) |
| `server/test_browser.py` | 23 pass | 23 pass |

Every artifact is namespaced `TEST-` and torn down, and each run ends by
asserting the room is back to 134 seats with zero taken and zero test codes.

Covered: identical 404s for bogus/expired/revoked tokens (asserted byte-for-byte);
every asset 404ing without a cookie; the token leaving the URL; a real click
walking Link to a seat and claiming it; the claim surviving on a different
device; a seat greying out live without a reload; two concurrent sessions racing
one seat (exactly one 200, one 409, one claim document); change-of-seat freeing
the old seat in the same transaction; post-deadline 403s; forged and malformed
cookies; and zero uncaught JS errors.

**Do not run either suite once real codes are out** — they write to the live
collections.

## The roster — Canvas only, decided 2026-08-17

`issue_codes.py` pulls the Canvas section live at issue time. There is no roster
file and no merge with any other source, because Canvas already carries
everything this needs:

| Field | Canvas | Used as |
|---|---|---|
| `sis_user_id` | `"730123456"` | the PID — seat key and `claims/{pid}` id |
| `id` | `136574` (int) | the Canvas ID a message is addressed to |
| `login_id` | `raulgonz` | the onyen, if a readable handle is ever wanted |
| `name` | | greeting in the message |

**50 students** in course `128467`. Validation refuses to issue on a missing
PID, a non-integer Canvas ID, or any duplicate PID or Canvas ID.

### Why not the merged roster

`Teaching/416/Data/416_roster.json` was built by matching a ConnectCarolina
export against Canvas **by name**, and the match appended instead of updating.
Canvas spells one student `Jose Raul Gonzalez Ibarmea`; ConnectCarolina spells
him `Jose Gonzalez Ibarmea`. So he became two rows — 52 rows for 51 students —
and the Canvas ID landed in a pandas `float64` column (one NaN was enough),
serialising as `136574.0`. A bare `str()` on that addresses nobody in Canvas.

Canvas itself was never wrong: one student, one integer id `136574`. Nothing in
the seating app reads the merged file, and `.json.bak` carries the same defect,
so restoring the backup would not help. Level and Major are the only fields
Canvas lacks, and seat claiming has no use for either.

Later work (the participation tracker) can join on `sis_user_id` or the Canvas
id — both are carried in `claims/{pid}` already.

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

Cloud Run scales to zero, so idle is free. ~51 students clicking a handful of
times is well inside the free allowance for requests, CPU, Firestore reads and
writes. The only real cost is the 1–2 second cold start on the first click after
a quiet spell; pin one warm instance during claim week for a few dollars if that
bothers you, then set it back to zero.
