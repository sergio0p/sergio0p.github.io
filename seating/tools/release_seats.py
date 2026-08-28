#!/usr/bin/env python3
"""Free a claimed seat, so a student who left the course stops holding one.

A claim is two documents, not one: `seats/{seatId}.taken` is what the map
paints, and `claims/{pid}` is who holds it. Releasing has to move both, or the
room ends up in one of two broken states -- a seat marked taken that nobody
holds (invisible to the student who wants it, and unclaimable forever), or a
claim pointing at a seat that reads free (two students sent to one chair). The
service already does this correctly in a transaction; this mirrors that path
exactly, and for the same reason it is a transaction here too.

That release path exists only as the student's own `/release` endpoint, which
refuses past the deadline. Neither is any use for a student who has dropped:
they will not release it themselves, and the seat matters most precisely after
the deadline, when the map has frozen with a dead student in the middle of it.
So this tool takes no deadline into account -- it is the instructor's, not the
student's.

`--dropped` is the reason this exists rather than a hand-written one-off:
Canvas is the only source of truth for enrolment, so the tool asks Canvas who
is active and frees every seat whose holder is not. That is the whole of
add/drop, run as often as you like.

The access code is a separate matter and is deliberately left alone -- a
student who drops and re-adds keeps a working link and simply claims again.
Use `revoke_code.py` when you want the link dead as well.

    python3 tools/release_seats.py --list              # every claim, and who still counts
    python3 tools/release_seats.py --dropped --dry-run # what add/drop has stranded
    python3 tools/release_seats.py --dropped           # free them
    python3 tools/release_seats.py 730123456           # free one student's seat
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `fetch_students` is not duplicated here on purpose: it is the one function
# that decides who is enrolled, it validates the roster hard enough to act on,
# and a second copy would be a second answer to that question.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue_codes import COURSE_ID, PROJECT, fetch_students  # noqa: E402


def active_pids(course_id: int) -> set[str]:
    return {s["pid"] for s in fetch_students(course_id)}


def load_claims(db):
    """{pid: {seatId, canvasId, claimedAt, ...}} -- the docs are keyed by PID."""
    return {d.id: d.to_dict() for d in db.collection("claims").stream()}


def release(db, pid: str, claim: dict) -> str:
    """Both documents or neither. Mirrors `/release` in server/main.py."""
    from google.cloud import firestore

    seat_id = claim.get("seatId")
    if not seat_id:
        return f"claim has no seatId; deleting the dangling claim"

    @firestore.transactional
    def run(tx):
        claim_ref = db.collection("claims").document(pid)
        seat_ref = db.collection("seats").document(seat_id)
        # Firestore requires every read before every write in a transaction.
        current = claim_ref.get(transaction=tx)
        seat = seat_ref.get(transaction=tx)
        if not current.exists:
            return "claim vanished between listing and release; nothing done"
        if seat.exists:
            tx.update(seat_ref, {"taken": False,
                                 "updatedAt": firestore.SERVER_TIMESTAMP})
            outcome = f"seat {seat_id} freed"
        else:
            # No seat document to un-take. The claim is still wrong and still
            # has to go, but say so rather than reporting a freed seat.
            outcome = f"seat {seat_id} has no document; claim removed only"
        tx.delete(claim_ref)
        return outcome

    return run(db.transaction())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pids", nargs="*", metavar="PID",
                    help="students whose seats to free")
    ap.add_argument("--dropped", action="store_true",
                    help="free every seat whose holder is no longer active in Canvas")
    ap.add_argument("--list", action="store_true",
                    help="show every claim and whether its holder is still enrolled")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be freed, write nothing")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--course", type=int, default=COURSE_ID)
    args = ap.parse_args()

    if not (args.pids or args.dropped or args.list):
        ap.error("give one or more PIDs, or --dropped, or --list")

    from google.cloud import firestore
    db = firestore.Client(project=args.project)
    claims = load_claims(db)

    # Only ask Canvas when the answer is actually used: freeing seats by PID is
    # the instructor saying so outright, and needs no roster to second-guess it.
    active: set[str] | None = None
    if args.dropped or args.list:
        active = active_pids(args.course)
        print(f"canvas: {len(active)} active student(s) in course {args.course}")
    print(f"firestore: {len(claims)} claim(s)")

    if args.list:
        print(f"\n{'PID':<12} {'seat':<7} {'holder':<10} claimed")
        for pid, c in sorted(claims.items(), key=lambda kv: str(kv[1].get("seatId"))):
            held = "active" if pid in active else "DROPPED"
            print(f"  {pid:<12} {str(c.get('seatId')):<7} {held:<10} "
                  f"{str(c.get('claimedAt'))[:19]}")
        if not args.pids and not args.dropped:
            return

    targets = list(args.pids)
    if args.dropped:
        targets += [p for p in claims if p not in active and p not in targets]

    unknown = [p for p in targets if p not in claims]
    for p in unknown:
        print(f"  PID {p}: holds no seat, skipping")
    targets = [p for p in targets if p in claims]

    if not targets:
        print("\nnothing to free")
        return

    print(f"\n{'would free' if args.dry_run else 'freeing'} {len(targets)} seat(s):")
    for pid in sorted(targets, key=lambda p: str(claims[p].get("seatId"))):
        seat_id = claims[pid].get("seatId")
        if args.dry_run:
            print(f"  PID {pid}  seat {seat_id}")
            continue
        print(f"  PID {pid}  {release(db, pid, claims[pid])}")

    if args.dry_run:
        print("\n--dry-run: nothing was written")
    else:
        print(f"\nCheck the map with: python3 tools/seed_seats.py --verify")


if __name__ == "__main__":
    main()
