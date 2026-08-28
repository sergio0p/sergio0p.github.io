#!/usr/bin/env python3
"""Push out the expiry on codes that already exist, without reissuing them.

The seating codes were issued to die a week after the seat deadline. The problem
set app reuses the same tokens, so they have to live for the term instead.

This is only possible because `416_seating_codes.json` still holds the plaintext
tokens: Firestore stores `sha256(token)` as the document id and nothing else, so
the only way from a token table back to a Firestore document is to hash it
again. If that file is ever lost, no code can be extended and every student
needs a fresh one. Back it up before running this.

Nothing else about a code changes -- not the token, not the pid, not the link a
student already has in their Canvas inbox. A revoked code stays revoked; this
never resurrects one.

    python3 tools/extend_codes.py --until 2027-01-01T00:00:00-05:00 --dry-run
    python3 tools/extend_codes.py --until 2027-01-01T00:00:00-05:00
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SECURE_DIR = Path.home() / "Dropbox/Teaching/416/Data"
LOCAL_TABLE = SECURE_DIR / "416_seating_codes.json"
PROJECT = "econ416-seating"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--until", required=True,
                    help="new expiry, ISO 8601 with an offset "
                         "(e.g. 2027-01-01T00:00:00-05:00)")
    ap.add_argument("--table", type=Path, default=LOCAL_TABLE)
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_expiry = datetime.fromisoformat(args.until)
    if new_expiry.tzinfo is None:
        sys.exit("--until needs a timezone offset; a naive datetime would be "
                 "interpreted differently here and in Firestore")
    if new_expiry <= datetime.now(timezone.utc):
        sys.exit(f"--until {new_expiry.isoformat()} is in the past")

    if not args.table.exists():
        sys.exit(f"{args.table} is missing -- without the plaintext tokens "
                 f"there is no way to find these codes in Firestore")
    table = json.loads(args.table.read_text())
    print(f"token table: {len(table)} entr(ies) in {args.table}")
    print(f"new expiry : {new_expiry.isoformat()}")

    from google.cloud import firestore
    db = firestore.Client(project=args.project)
    codes = db.collection("codes")

    extend, skipped, missing = [], [], []
    for pid, row in sorted(table.items()):
        token = row.get("token")
        if not token:
            missing.append((pid, row.get("name", ""), "no token in the table"))
            continue
        digest = hashlib.sha256(token.encode()).hexdigest()
        doc = codes.document(digest).get()
        if not doc.exists:
            missing.append((pid, row.get("name", ""), "no such code in Firestore"))
            continue
        d = doc.to_dict()
        if d.get("revoked"):
            skipped.append((pid, row.get("name", ""), "revoked"))
            continue
        current = d.get("expiresAt")
        if current is not None and current.timestamp() >= new_expiry.timestamp():
            skipped.append((pid, row.get("name", ""), "already later"))
            continue
        extend.append((pid, row.get("name", ""), digest, current))

    print(f"\nto extend: {len(extend)}   skipped: {len(skipped)}   "
          f"not found: {len(missing)}")
    for pid, name, reason in skipped:
        print(f"  skip {name} ({pid}): {reason}")
    for pid, name, reason in missing:
        print(f"  MISS {name} ({pid}): {reason}")

    if args.dry_run:
        if extend:
            pid, name, _, current = extend[0]
            print(f"\nexample: {name} ({pid}) "
                  f"{current.isoformat() if current else 'no expiry'} "
                  f"-> {new_expiry.isoformat()}")
        print("\ndry run -- nothing written")
        return

    for pid, name, digest, _ in extend:
        codes.document(digest).update({"expiresAt": new_expiry})
    print(f"\nextended {len(extend)} code(s) to {new_expiry.isoformat()}")


if __name__ == "__main__":
    main()
