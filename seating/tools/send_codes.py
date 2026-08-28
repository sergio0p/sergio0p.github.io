#!/usr/bin/env python3
"""Prepare the Canvas messages that carry each student's link, and track sends.

This tool does NOT send. Canvas is reached through the Canvas MCP server, which
lives in the assistant's session and not in a Python process, so the split is:

    send_codes.py --prepare   ->  416_seating_outbox.json  (one message each)
    <the assistant sends them through Canvas `send_conversation`>
    send_codes.py --mark-sent PID [PID...]   ->  records what actually went out

That makes the run resumable: if it stops after 20 messages, `--prepare` next
time emits only the rest. Sending 50 messages is not an operation to guess
about halfway through.

All three files live in `~/Dropbox/Teaching/416/Data/`, outside this repository,
because every one of them contains student PII or a working credential and
`seating/` is published to GitHub Pages.

Nothing is ever sent to a student without the instructor triggering it, and the
plan's own build order says to send to yourself first -- `--only PID` exists for
exactly that.

    python3 tools/send_codes.py --prepare
    python3 tools/send_codes.py --prepare --only 730123456   # the test run
    python3 tools/send_codes.py --status
    python3 tools/send_codes.py --mark-sent 730123456
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Outside the repository: `seating/` is published to GitHub Pages, and every one
# of these files contains student PII or a live credential.
SECURE_DIR = Path.home() / "Dropbox/Teaching/416/Data"
LOCAL_TABLE = SECURE_DIR / "416_seating_codes.json"
OUTBOX = SECURE_DIR / "416_seating_outbox.json"
SENT_LOG = SECURE_DIR / "416_seating_sent.json"

SUBJECT = "ECON 416 — claim your seat"

# The message body is `seating/message.tex` (plain text despite the extension),
# so the wording lives in one editable file and not in this script. The literal
# placeholder below is replaced with that student's personal link.
TEMPLATE = Path(__file__).resolve().parents[1] / "message.tex"
PLACEHOLDER = "[SEAT RESERVATION LINK]"


def render(link: str, template: Path = None) -> str:
    template = template or TEMPLATE
    body = template.read_text()
    if PLACEHOLDER not in body:
        sys.exit(f"{template} has no {PLACEHOLDER} to put the link in -- "
                 f"refusing to send a message with no link in it")
    return body.replace(PLACEHOLDER, link)


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prepare", action="store_true",
                    help="write the outbox for everyone not yet sent")
    ap.add_argument("--status", action="store_true",
                    help="how many are issued, sent, outstanding")
    ap.add_argument("--mark-sent", nargs="+", metavar="PID", default=[],
                    help="record that these students' messages went out")
    ap.add_argument("--only", metavar="PID",
                    help="restrict the outbox to one student (the test send)")
    # A re-send is a different campaign, not a retry of the first one: different
    # wording, different subject, and everybody is already in the sent log. Each
    # campaign therefore carries its own template, subject and log, and --resend
    # is what lets it past the "already sent" filter that protects the first run.
    ap.add_argument("--template", type=Path, default=TEMPLATE,
                    help="message body file (default message.tex)")
    ap.add_argument("--subject", default=SUBJECT)
    ap.add_argument("--sent-log", type=Path, default=SENT_LOG,
                    help="which send log to read and write (one per campaign)")
    ap.add_argument("--resend", action="store_true",
                    help="ignore the sent log -- for a follow-up to students "
                         "who already received the first message")
    ap.add_argument("--skip", nargs="*", metavar="PID", default=[],
                    help="exclude these PIDs (students who have since dropped)")
    args = ap.parse_args()

    table = load_json(LOCAL_TABLE, {})
    sent = load_json(args.sent_log, {})

    if not table and not args.status:
        sys.exit(f"{LOCAL_TABLE} is missing or empty -- run issue_codes.py first")

    if args.mark_sent:
        for pid in args.mark_sent:
            if pid not in table:
                print(f"  warning: PID {pid} is not in the code table", file=sys.stderr)
            sent[pid] = datetime.now(timezone.utc).isoformat()
        args.sent_log.write_text(json.dumps(sent, indent=2, sort_keys=True))
        args.sent_log.chmod(0o600)
        print(f"recorded {len(args.mark_sent)} send(s); {len(sent)} total")
        return

    if args.status:
        outstanding = [p for p in table if p not in sent]
        print(f"issued     : {len(table)}")
        print(f"sent       : {len(sent)}")
        print(f"outstanding: {len(outstanding)}")
        if outstanding:
            print("  " + ", ".join(sorted(outstanding)[:10])
                  + ("  …" if len(outstanding) > 10 else ""))
        return

    if args.prepare:
        skip = {str(p) for p in args.skip}
        pending = [v for pid, v in sorted(table.items())
                   if (args.resend or pid not in sent)
                   and pid not in skip
                   and (not args.only or pid == args.only)]
        if args.only and not pending:
            sys.exit(f"PID {args.only} is not pending (unknown, or already sent)")
        messages = [{
            "pid": v["pid"],
            "canvasId": v["canvasId"],
            "name": v["name"],
            "subject": args.subject,
            "body": render(v["link"], args.template),
        } for v in pending]
        OUTBOX.write_text(json.dumps(messages, indent=2))
        OUTBOX.chmod(0o600)          # every body contains a working credential
        print(f"wrote {len(messages)} message(s) to {OUTBOX} (mode 600)")
        print("This file contains live links. It lives outside the repo; "
              "delete it once the send is done.")
        print("\nNext: have the assistant send these through the Canvas MCP "
              "(`send_conversation`, one call per student), then run:")
        print("  python3 tools/send_codes.py --mark-sent <PID> [...]")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
