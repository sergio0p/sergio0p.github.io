#!/usr/bin/env python3
"""Send a prepared outbox through the Canvas conversations API.

`send_codes.py` deliberately does not send: the original workflow handed the
outbox to the assistant, which sent each message through the Canvas MCP server.
When that server is unavailable there is no route at all, which is how a
finished, approved message ends up stuck. This tool is that route.

    POST /api/v1/conversations
      recipients[]  required, the student's Canvas user id
      body          required, this student's rendered message
      subject       <= 255 characters
      force_new     true -- a new message, not an append to an old thread
      group_conversation  false -- individual private conversations
      context_code  course_<id>, so it is attributed to the course

One request per student, because every body carries that student's own link.
Nothing here decides who gets a message: the outbox is the list, and it was
built and reviewed before this ran.

    python3 tools/send_outbox.py --test        # one message to yourself
    python3 tools/send_outbox.py --dry-run
    python3 tools/send_outbox.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import keyring
import requests

SECURE_DIR = Path.home() / "Dropbox/Teaching/416/Data"
OUTBOX = SECURE_DIR / "416_seating_outbox.json"
API = "https://uncch.instructure.com/api/v1"
COURSE_ID = 128467
FRONT_DOOR = "https://econ416-seating-273200940906.us-east1.run.app/"


def session() -> requests.Session:
    token = keyring.get_password("canvas", "access-token")
    if not token:
        sys.exit("no Canvas token in the keychain")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def send(s: requests.Session, canvas_id: str, subject: str, body: str) -> tuple[bool, str]:
    r = s.post(f"{API}/conversations", data={
        "recipients[]": canvas_id,
        "subject": subject[:255],
        "body": body,
        "force_new": "true",
        "group_conversation": "false",
        "context_code": f"course_{COURSE_ID}",
    }, timeout=30)
    return r.ok, ("" if r.ok else f"{r.status_code}: {r.text[:160]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outbox", type=Path, default=OUTBOX)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true",
                    help="send one copy to yourself, with no student's token in it")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    s = session()

    if args.test:
        me = s.get(f"{API}/users/self", timeout=30).json()
        messages = json.loads(args.outbox.read_text())
        # The front door, never a student's live link: this copy lands in an
        # inbox that is not theirs.
        body = messages[0]["body"].replace(
            messages[0]["body"].split("\n\n")[3].strip(), FRONT_DOOR)
        ok, err = send(s, str(me["id"]), "[TEST] " + messages[0]["subject"], body)
        print(f"test -> {me.get('name')} ({me['id']}): {'sent' if ok else err}")
        return

    messages = json.loads(args.outbox.read_text())
    print(f"{len(messages)} message(s) in {args.outbox}")
    if args.dry_run:
        for m in messages:
            print(f"  would send to {m['name']} (canvas {m['canvasId']}, pid {m['pid']})")
        return

    sent, failed = [], []
    for i, m in enumerate(messages, 1):
        ok, err = send(s, m["canvasId"], m["subject"], m["body"])
        if ok:
            sent.append(m["pid"])
            print(f"  [{i}/{len(messages)}] {m['name']}: sent")
        else:
            failed.append((m["pid"], m["name"], err))
            print(f"  [{i}/{len(messages)}] {m['name']}: FAILED {err}")
        time.sleep(args.delay)

    print(f"\nsent {len(sent)}, failed {len(failed)}")
    if failed:
        print("failures:")
        for pid, name, err in failed:
            print(f"  {name} ({pid}): {err}")
    if sent:
        print("\nrecord them with:")
        print("  python3 tools/send_codes.py --mark-sent " + " ".join(sent)
              + " --sent-log ~/Dropbox/Teaching/416/Data/416_seating_reopen_sent.json")


if __name__ == "__main__":
    main()
