#!/usr/bin/env python3
"""Seed the Firestore `seats` collection from room-layout.json.

`data/room-layout.json` is the single source of truth for the room; this writes
it into the one collection a browser is allowed to read. The rule that shapes
every field choice here: **a public document carries no student identifier.**
`taken` is a bare boolean, never a PID and never a name, because anyone can read
it. Who sits where lives in `claims/{pid}`, which no client can touch.

Document ID is `"{row}_{col}"` -- the same `seat.id` the renderer and the claim
transaction use, so a seat is the same string everywhere in the system.

Re-running this is safe and is meant to be. A seed that reset `taken` would
silently un-claim every student the moment someone re-ran it during claim week,
so by default an existing document keeps its `taken` value and only the layout
fields are refreshed. Wiping claims is possible, but you have to ask for it by
name and confirm it.

The layout is validated against its own declared `counts` before a single write
goes out: a seat file that disagrees with itself would bake wrong IDs into
Firestore, the claims, and the Phase 4 SQLite export at once.

    python3 tools/seed_seats.py --dry-run     # what would be written
    python3 tools/seed_seats.py               # seed / refresh, claims preserved
    python3 tools/seed_seats.py --verify      # compare Firestore against layout
    python3 tools/seed_seats.py --reset-claims  # DESTRUCTIVE: taken -> false
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LAYOUT = Path(__file__).resolve().parents[1] / "data" / "room-layout.json"
PROJECT = "econ416-seating"
COLLECTION = "seats"

# Firestore caps a batched write at 500 operations; 134 seats fit in one, but
# batching by this keeps the tool honest if the room ever grows.
BATCH = 400


def load_layout(path: Path) -> dict:
    """Read the layout and refuse to proceed if it disagrees with itself."""
    layout = json.loads(path.read_text())
    seats = layout["seats"]
    counts = layout["counts"]
    reserved_set = set(layout["reserved_set"]["seats"])
    blocked_rows = set(layout["off_limits"]["rows"])

    problems = []

    ids = [s["id"] for s in seats]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"duplicate seat ids: {dupes}")

    for s in seats:
        if s["id"] != f"{s['row']}_{s['col']}":
            problems.append(f"id {s['id']!r} does not match row/col {s['row']}/{s['col']}")

    checks = {
        "seats": len(seats),
        "left_handed": sum(1 for s in seats if s["handed"] == "left"),
        "right_handed": sum(1 for s in seats if s["handed"] == "right"),
        "reserved": sum(1 for s in seats if s["reserved"]),
        "claimable": sum(1 for s in seats if s["usable"] and not s["reserved"]),
    }
    for key, got in checks.items():
        want = counts.get(key)
        if want is not None and got != want:
            problems.append(f"counts.{key} says {want}, seats say {got}")

    flagged = {s["id"] for s in seats if s["reserved"]}
    if flagged != reserved_set:
        problems.append(
            f"reserved flags {sorted(flagged)} != reserved_set {sorted(reserved_set)}"
        )

    unusable = {s["id"] for s in seats if not s["usable"]}
    off_rows = {s["id"] for s in seats if s["row"] in blocked_rows}
    if unusable != off_rows:
        problems.append(
            f"usable:false set does not match off_limits rows {sorted(blocked_rows)}"
        )

    if problems:
        print("layout is inconsistent -- refusing to seed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    return layout


def seat_doc(seat: dict, taken: bool) -> dict:
    """The public shape. Nothing here identifies a student."""
    return {
        "row": seat["row"],
        "col": seat["col"],
        "handed": seat["handed"],       # 'left' | 'right'  -- colour in the render
        "reserved": seat["reserved"],   # held back by the instructor
        "usable": seat["usable"],       # false = off-limits rows 7-10
        "taken": taken,                 # a bare boolean, never a PID
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--layout", type=Path, default=LAYOUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and report; write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="compare Firestore against the layout; write nothing")
    ap.add_argument("--reset-claims", action="store_true",
                    help="DESTRUCTIVE: force taken=false on every seat")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt for --reset-claims")
    args = ap.parse_args()

    layout = load_layout(args.layout)
    seats = layout["seats"]
    c = layout["counts"]
    print(f"layout OK: {len(seats)} seats "
          f"({c['reserved']} reserved, {c['off_limits']} off-limits, "
          f"{c['claimable']} claimable)")

    if args.dry_run:
        for s in seats[:3]:
            print(f"  would write seats/{s['id']}: {seat_doc(s, False)}")
        print(f"  ... {len(seats)} documents total -> "
              f"{args.project}/{COLLECTION}")
        return

    from google.cloud import firestore  # imported late so --dry-run needs no creds

    db = firestore.Client(project=args.project)
    col = db.collection(COLLECTION)

    existing = {d.id: d.to_dict() for d in col.stream()}
    print(f"firestore: {len(existing)} existing documents in {COLLECTION}")

    if args.verify:
        want = {s["id"] for s in seats}
        missing = sorted(want - existing.keys())
        extra = sorted(existing.keys() - want)
        drift = []
        for s in seats:
            got = existing.get(s["id"])
            if not got:
                continue
            for k, v in seat_doc(s, got.get("taken", False)).items():
                if got.get(k) != v:
                    drift.append(f"{s['id']}.{k}: firestore={got.get(k)!r} layout={v!r}")
        taken = sorted(i for i, d in existing.items() if d.get("taken"))
        print(f"  missing: {missing or 'none'}")
        print(f"  unexpected: {extra or 'none'}")
        print(f"  field drift: {drift or 'none'}")
        print(f"  taken: {len(taken)} -> {taken or 'none'}")
        sys.exit(1 if (missing or extra or drift) else 0)

    claimed = sorted(i for i, d in existing.items() if d.get("taken"))
    if args.reset_claims:
        if claimed and not args.yes:
            print(f"\n--reset-claims will un-claim {len(claimed)} seat(s): "
                  f"{', '.join(claimed)}")
            print("The matching claims/{pid} documents are NOT deleted by this "
                  "tool, so they would be left pointing at freed seats.")
            if input("Type 'reset' to proceed: ").strip() != "reset":
                print("aborted")
                return
    elif claimed:
        print(f"  preserving taken=true on {len(claimed)} seat(s): "
              f"{', '.join(claimed)}")

    written = 0
    batch = db.batch()
    pending = 0
    for s in seats:
        prior = existing.get(s["id"], {})
        taken = False if args.reset_claims else bool(prior.get("taken", False))
        doc = seat_doc(s, taken)
        doc["updatedAt"] = firestore.SERVER_TIMESTAMP
        batch.set(col.document(s["id"]), doc)
        pending += 1
        written += 1
        if pending >= BATCH:
            batch.commit()
            batch = db.batch()
            pending = 0
    if pending:
        batch.commit()

    print(f"wrote {written} documents to {args.project}/{COLLECTION}")

    stale = sorted(existing.keys() - {s["id"] for s in seats})
    if stale:
        print(f"NOTE: {len(stale)} document(s) in Firestore are not in the "
              f"layout and were left alone: {', '.join(stale)}")


if __name__ == "__main__":
    main()
