#!/usr/bin/env python3
"""Issue one random access code per student, straight from Canvas.

The roster is pulled live from the Canvas section at issue time. There is no
roster file and no merge with any other source: Canvas has everything this
needs -- `sis_user_id` IS the PID, `id` is the integer Canvas ID a message is
sent to, `login_id` is the onyen, `name` is the name. A local snapshot could
only be stale or wrong, and the previous merged one was both (it carried a
duplicated student and a Canvas ID stored as the float `136574.0`).

The code itself is `secrets.token_urlsafe(16)` -- 22 characters, 128 bits, from
the OS CSPRNG, derived from *nothing*. Not the PID, not the Canvas ID, not the
onyen. Knowing a student's PID tells you nothing about their code.

**Firestore never sees the token.** The document ID is `sha256(token)`, for the
same reason a password database stores hashes: if the database leaked, no
working link could be built from it. The gate hashes what arrives in the URL
and looks that up.

The (Canvas ID, code) table is written OUTSIDE this repository, to
`~/Dropbox/Teaching/416/Data/`. `seating/` is published to GitHub Pages, and a
file of student PIDs and live credentials has no business inside a directory
that gets copied to a public website -- gitignored or not.

Re-running is safe: a student who already holds a live code keeps it, so a
partial run can simply be repeated. `--reissue PID` is the deliberate exception.

    python3 tools/issue_codes.py --dry-run     # who would get one
    python3 tools/issue_codes.py               # issue for anyone missing one
    python3 tools/issue_codes.py --reissue 730123456
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Student PII and live credentials live here, never in the published directory.
SECURE_DIR = Path.home() / "Dropbox/Teaching/416/Data"
LOCAL_TABLE = SECURE_DIR / "416_seating_codes.json"

CANVAS_HOST = "https://uncch.instructure.com"
COURSE_ID = 128467
KEYRING_SERVICE, KEYRING_USER = "canvas", "access-token"

PROJECT = "econ416-seating"
SERVICE_URL = "https://econ416-seating-273200940906.us-east1.run.app"

# Claiming closes at midnight ending Sun 30 Aug 2026 (America/New_York).
DEADLINE = datetime.fromisoformat("2026-08-31T00:00:00-04:00")

# Codes outlive the deadline by the grace window the service gives sessions, so
# a student opening their link on the 26th sees TIME IS UP and the seat they
# got rather than a bare 404. Claiming still stops at DEADLINE; the service
# enforces that independently of this expiry.
CODE_EXPIRES = DEADLINE + timedelta(days=7)


def fetch_students(course_id: int) -> list[dict]:
    """The Canvas section roster, validated hard enough to send from."""
    import keyring
    import requests

    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not token:
        sys.exit(f"no Canvas token in the keychain "
                 f"(service={KEYRING_SERVICE!r}, username={KEYRING_USER!r})")

    students: list[dict] = []
    url = f"{CANVAS_HOST}/api/v1/courses/{course_id}/users"
    # enrollment_state matters: without it Canvas returns inactive enrolments
    # too. An inactive student cannot even be sent a Canvas message (the API
    # answers 400), so issuing them a code produces a credential nobody can
    # deliver -- while a student who enrolled since the last run is exactly the
    # one who must not be missed.
    params: dict | None = {"enrollment_type[]": "student",
                           "enrollment_state[]": ["active", "invited"],
                           "per_page": 100}
    while url:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
        if not r.ok:
            sys.exit(f"Canvas {r.status_code}: {r.text[:200]}")
        students += r.json()
        url = r.links.get("next", {}).get("url")
        params = None

    problems: list[str] = []
    seen_pid: set[str] = set()
    seen_cid: set[int] = set()
    clean: list[dict] = []

    for s in students:
        pid, cid = s.get("sis_user_id"), s.get("id")
        name = s.get("name") or s.get("sortable_name") or ""
        if not pid:
            problems.append(f"{name!r} (canvas id {cid}) has no sis_user_id/PID")
            continue
        if not isinstance(cid, int):
            # Canvas returns integers here. Anything else means the shape
            # changed -- and str() on a float addresses nobody.
            problems.append(f"{name!r} has a non-integer Canvas id: {cid!r}")
            continue
        if str(pid) in seen_pid:
            problems.append(f"PID {pid} appears twice in the Canvas section")
            continue
        if cid in seen_cid:
            problems.append(f"Canvas id {cid} appears twice")
            continue
        seen_pid.add(str(pid))
        seen_cid.add(cid)
        clean.append({"pid": str(pid), "canvasId": str(cid), "name": name,
                      "onyen": s.get("login_id") or ""})

    if problems:
        print("Canvas roster problems -- refusing to issue:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    return clean


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--course", type=int, default=COURSE_ID)
    ap.add_argument("--url", default=SERVICE_URL)
    ap.add_argument("--table", type=Path, default=LOCAL_TABLE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reissue", metavar="PID", action="append", default=[],
                    help="revoke this student's existing code and issue a new one")
    args = ap.parse_args()

    roster = fetch_students(args.course)
    print(f"canvas: {len(roster)} students in course {args.course}")
    print(f"codes expire {CODE_EXPIRES.isoformat()} "
          f"(claiming closes {DEADLINE.isoformat()})")

    if args.dry_run:
        print(f"  would issue up to {len(roster)} codes into "
              f"{args.project}/codes")
        print(f"  and write the (Canvas ID, code) table to {args.table}")
        print("  no token is ever stored in Firestore -- only sha256(token)")
        return

    from google.cloud import firestore
    db = firestore.Client(project=args.project)
    codes = db.collection("codes")

    existing: dict[str, str] = {}
    for d in codes.stream():
        v = d.to_dict()
        if not v.get("revoked") and not v.get("test"):
            existing[str(v.get("pid"))] = d.id
    print(f"firestore: {len(existing)} student(s) already hold a live code")

    table: dict[str, dict] = {}
    if args.table.exists():
        table = {str(k): v for k, v in json.loads(args.table.read_text()).items()}

    reissue = {str(p) for p in args.reissue}
    issued = kept = revoked = 0

    for student in roster:
        pid = student["pid"]
        have = existing.get(pid)

        if have and pid in reissue:
            codes.document(have).update({"revoked": True,
                                         "revokedAt": datetime.now(timezone.utc)})
            table.pop(pid, None)
            have = None
            revoked += 1

        if have and pid in table:
            kept += 1
            continue
        if have and pid not in table:
            # A code exists in Firestore but its token is not in the table. The
            # token is unrecoverable by design, so the only way back to a
            # working link is a fresh code.
            print(f"  PID {pid}: code in Firestore but no local token; reissuing")
            codes.document(have).update({"revoked": True,
                                         "revokedAt": datetime.now(timezone.utc)})
            revoked += 1

        token = secrets.token_urlsafe(16)
        digest = hashlib.sha256(token.encode()).hexdigest()
        codes.document(digest).set({
            "pid": pid,
            "canvasId": student["canvasId"],
            "name": student["name"],
            "issuedAt": datetime.now(timezone.utc),
            "expiresAt": CODE_EXPIRES,
            "revoked": False,
        })
        table[pid] = {**student, "token": token,
                      "link": f"{args.url.rstrip('/')}/c/{token}",
                      "issuedAt": datetime.now(timezone.utc).isoformat()}
        issued += 1

    args.table.parent.mkdir(parents=True, exist_ok=True)
    args.table.write_text(json.dumps(table, indent=2, sort_keys=True))
    args.table.chmod(0o600)      # live credentials; not world-readable

    print(f"issued {issued}, kept {kept}, revoked {revoked}")
    print(f"code table: {args.table} ({len(table)} entries, mode 600)")
    if issued:
        print("NOTE: this file is the only copy of the tokens. Firestore holds "
              "hashes only -- losing it means reissuing.")


if __name__ == "__main__":
    main()
