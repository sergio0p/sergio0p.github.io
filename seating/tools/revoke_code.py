#!/usr/bin/env python3
"""Revoke a student's access code, and optionally issue a replacement.

For a lost code, a forwarded one, or a student who dropped the course. Revoking
is instant: the gate reads `revoked` on every request, so the old link starts
returning the same 404 as any other bad link the moment this runs.

A revoked code is marked, never deleted. The record of what was issued to whom
and when it was withdrawn is worth keeping, and a deleted document would make a
subsequent "did we ever send them one?" unanswerable.

Reissuing is `issue_codes.py --reissue PID`, which this can call for you with
`--reissue`. The new link still has to be delivered through Canvas by hand --
there is no self-service resend anywhere in this system, because a student who
could ask "resend my code" would have rebuilt the enrollment oracle the whole
design exists to avoid.

    python3 tools/revoke_code.py 730123456                # revoke
    python3 tools/revoke_code.py 730123456 --reissue      # revoke + new code
    python3 tools/revoke_code.py --list                   # who holds what
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
# Outside the repository -- see issue_codes.py.
LOCAL_TABLE = Path.home() / "Dropbox/Teaching/416/Data/416_seating_codes.json"
PROJECT = "econ416-seating"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pid", nargs="?", help="the student's PID")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--list", action="store_true",
                    help="list live codes (hashes and PIDs, never tokens)")
    ap.add_argument("--reissue", action="store_true",
                    help="also issue a replacement code")
    args = ap.parse_args()

    from google.cloud import firestore
    db = firestore.Client(project=args.project)
    codes = db.collection("codes")

    if args.list:
        rows = []
        for d in codes.stream():
            v = d.to_dict()
            rows.append((str(v.get("pid")), v.get("name", ""),
                         "REVOKED" if v.get("revoked") else "live",
                         d.id[:12] + "…"))
        rows.sort()
        print(f"{len(rows)} code document(s):")
        for pid, name, state, digest in rows:
            print(f"  {pid:<12} {state:<8} {digest}  {name}")
        return

    if not args.pid:
        sys.exit("give a PID, or --list")

    hits = [d for d in codes.stream() if str(d.to_dict().get("pid")) == args.pid]
    if not hits:
        sys.exit(f"no code on file for PID {args.pid}")

    live = [d for d in hits if not d.to_dict().get("revoked")]
    if not live:
        print(f"PID {args.pid}: already revoked ({len(hits)} document(s) on file)")
    for d in live:
        d.reference.update({"revoked": True,
                            "revokedAt": datetime.now(timezone.utc)})
        print(f"revoked {d.id[:12]}… for PID {args.pid}")

    # Drop the dead token from the local table so it cannot be re-sent by
    # mistake; the Firestore document stays as the record.
    if LOCAL_TABLE.exists():
        table = json.loads(LOCAL_TABLE.read_text())
        if table.pop(args.pid, None) is not None:
            LOCAL_TABLE.write_text(json.dumps(table, indent=2, sort_keys=True))
            LOCAL_TABLE.chmod(0o600)
            print(f"removed PID {args.pid} from {LOCAL_TABLE.name}")

    if args.reissue:
        print("\nissuing a replacement...")
        subprocess.run([sys.executable, str(HERE / "tools" / "issue_codes.py"),
                        "--reissue", args.pid], check=True)
        print("\nDeliver the new link through Canvas by hand. There is no "
              "self-service resend, by design.")


if __name__ == "__main__":
    main()
