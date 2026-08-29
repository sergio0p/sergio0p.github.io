#!/usr/bin/env python3
"""Freeze the group structure for one problem set.

Tokens are permanent; groups are not. Canvas holds a separate group category per
round -- `S01`, `S02`, ... -- and `makegroups.py` recuts them every time. So a
submission cannot be resolved against "the student's group" in the abstract: it
has to be resolved against the group they were in *for that problem set*, and
that pairing has to survive the next recut. A regrade in November must still
attribute PS 02 answers to the PS 02 pairing.

Hence this: read Canvas once, write `psGroups/{ps}` in Firestore, and never
touch it again. Everything downstream reads the frozen copy, never Canvas.

Refuses to overwrite an existing snapshot without --force, because overwriting
one after students have submitted against it is how answers get attributed to
the wrong pair.

    python3 tools/freeze_ps_groups.py --ps 02 --dry-run
    python3 tools/freeze_ps_groups.py --ps 02
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

CANVAS_HOST = "https://uncch.instructure.com"
API = f"{CANVAS_HOST}/api/v1"
COURSE_ID = 128467
PROJECT = "econ416-seating"


def canvas():
    import keyring
    import requests
    token = keyring.get_password("canvas", "access-token")
    if not token:
        sys.exit("no Canvas token in the keychain")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def paged(s, url, params):
    out = []
    while url:
        r = s.get(url, params=params, timeout=30)
        if not r.ok:
            sys.exit(f"Canvas {r.status_code} on {url}: {r.text[:200]}")
        out += r.json()
        url = r.links.get("next", {}).get("url")
        params = None
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ps", required=True, help="problem set number, e.g. 02")
    ap.add_argument("--course", type=int, default=COURSE_ID)
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--category", type=int,
                    help="group category id (default: the one named S<ps>)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing frozen snapshot")
    args = ap.parse_args()

    ps = args.ps.zfill(2)
    s = canvas()

    # The category whose name matches the round, per makegroups.format_group_set_name
    cats = paged(s, f"{API}/courses/{args.course}/group_categories", {"per_page": 100})
    if args.category:
        cat = next((c for c in cats if c["id"] == args.category), None)
    else:
        cat = next((c for c in cats if c["name"] == f"S{ps}"), None)
    if not cat:
        sys.exit(f"no group category named S{ps} in course {args.course} "
                 f"(found: {', '.join(c['name'] for c in cats)})")
    print(f"category: {cat['name']} (id {cat['id']})")

    # PID map: the group endpoints carry user ids only, everything downstream
    # keys on PID, and sis_user_id IS the PID.
    users = paged(s, f"{API}/courses/{args.course}/users",
                  {"per_page": 100, "enrollment_type[]": "student",
                   "enrollment_state[]": "active"})
    pids = {u["id"]: str(u["sis_user_id"]) for u in users if u.get("sis_user_id")}
    print(f"active students: {len(pids)}")

    # The instructor and the TA, so a staff group can be frozen like any other.
    #
    # There has to be one group that can be exercised end to end without using a
    # student's credential, and Canvas will not provide it: the Test Student is
    # refused outright by POST /groups/:id/memberships ("user not authorized to
    # perform that action"), has no sis_user_id to key on, and does not appear
    # in the student roster at all. Staff have real PIDs and join groups
    # normally, so the test group is a real group and the path under test is the
    # real path.
    #
    # Kept in a separate map from `pids` on purpose. `ungrouped` below reports
    # students who will see the no-group page, and staff who happen not to be in
    # a group are not that -- folding them together would put the instructor in
    # a list of students to chase.
    staff = paged(s, f"{API}/courses/{args.course}/users",
                  {"per_page": 100, "enrollment_type[]": ["teacher", "ta"],
                   "enrollment_state[]": "active"})
    staff_pids = {u["id"]: str(u["sis_user_id"]) for u in staff
                  if u.get("sis_user_id") and u["id"] not in pids}
    if staff_pids:
        print(f"staff: {len(staff_pids)} "
              f"({', '.join(u['name'] for u in staff if u['id'] in staff_pids)})")
    known = {**pids, **staff_pids}

    groups_raw = paged(s, f"{API}/group_categories/{cat['id']}/groups", {"per_page": 100})
    groups, by_pid, problems = [], {}, []

    for g in sorted(groups_raw, key=lambda g: g["name"]):
        members = paged(s, f"{API}/groups/{g['id']}/users",
                        {"per_page": 100, "exclude_inactive": "true"})
        rows = []
        for m in members:
            pid = known.get(m["id"])
            if not pid:
                problems.append(f"{m.get('name')} in {g['name']} is not an "
                                f"active student -- excluded")
                continue
            if pid in by_pid:
                problems.append(f"PID {pid} is in two groups: "
                                f"{by_pid[pid]} and {g['name']}")
                continue
            by_pid[pid] = g["name"]
            rows.append({"pid": pid, "canvasId": int(m["id"]),
                         "name": m.get("name") or ""})
        groups.append({"groupId": int(g["id"]), "groupName": g["name"],
                       "members": rows})

    placed = {p for p in by_pid}
    ungrouped = sorted(set(pids.values()) - placed)      # students only
    name_of = {str(u.get("sis_user_id")): u.get("name") for u in users}

    print(f"\ngroups: {len(groups)}   students placed: {len(placed)}")
    solo = [g for g in groups if len(g["members"]) == 1]
    empty = [g for g in groups if not g["members"]]
    print(f"solo groups: {len(solo)}   empty groups: {len(empty)}")
    for g in solo:
        print(f"   solo: {g['groupName']} -> {g['members'][0]['name']}")
    for g in empty:
        print(f"   EMPTY: {g['groupName']}")
    if ungrouped:
        print(f"\nactive students in NO group ({len(ungrouped)}) -- they will "
              f"see the no-group page:")
        for p in ungrouped:
            print(f"   {name_of.get(p, '?')} ({p})")
    for p in problems:
        print(f"   ! {p}")

    doc = {
        "ps": ps,
        "courseId": args.course,
        "categoryId": int(cat["id"]),
        "categoryName": cat["name"],
        "frozenAt": datetime.now(timezone.utc),
        "groups": groups,
        # pid -> groupId, so submit-time resolution is a single lookup and
        # never a scan that could pick a stale group.
        "byPid": {pid: next(g["groupId"] for g in groups if g["groupName"] == gname)
                  for pid, gname in by_pid.items()},
    }

    if args.dry_run:
        print(f"\ndry run -- would write psGroups/{ps} "
              f"({len(groups)} groups, {len(doc['byPid'])} students)")
        return

    from google.cloud import firestore
    db = firestore.Client(project=args.project)
    ref = db.collection("psGroups").document(ps)
    existing = ref.get()
    if existing.exists and not args.force:
        sys.exit(f"psGroups/{ps} already exists (frozen "
                 f"{existing.to_dict().get('frozenAt')}). Overwriting it after "
                 f"students have submitted would reattribute their answers. "
                 f"Pass --force only if you are certain.")
    ref.set(doc)
    print(f"\nwrote psGroups/{ps}: {len(groups)} groups, "
          f"{len(doc['byPid'])} students")


if __name__ == "__main__":
    main()
