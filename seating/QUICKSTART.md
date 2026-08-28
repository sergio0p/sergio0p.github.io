# Quickstart

Everything you actually need to run, in the order you'd need it. The reasoning
behind each choice is in `PHASE2-PLAN.md`; this file is just the commands.

## What is where

| | |
|---|---|
| Live app (students) | `https://econ416-seating-273200940906.us-east1.run.app` |
| Public front door | `https://sergio0p.github.io/seating/` |
| GCP project | `econ416-seating` (number `273200940906`) |
| Claiming closes | **2026-08-31T00:00 America/New_York** — midnight ending Sun 30 Aug |

A student never sees the bare service URL: they get `…/c/<token>`, which sets a
cookie and redirects to `/app`. Without a token, every path but `/` returns 404.

## Run it locally

```bash
cd ~/Dropbox/Teaching/Projects/PersonalWebsite/seating

# the app on its own, no server — the demo the GitHub Pages copy runs
python3 -m http.server 8000          # -> http://localhost:8000/

# the real thing, gate and all
PORT=8080 DEV=1 SESSION_SECRET=dev-only .venv/bin/python server/main.py
```

`DEV=1` drops the `Secure` flag so cookies work over plain http. Never set it in
production. Without `SESSION_SECRET` the service pulls the real key from Secret
Manager, which also works locally if you're logged in with `gcloud`.

## Test it

Both suites run against the **live** Firestore project and clean up after
themselves. **Do not run either once real codes are out** — they write to the
live collections.

```bash
.venv/bin/python server/test_service.py            # API, 53 checks
.venv/bin/python server/test_browser.py            # real Chrome, 23 checks

# same suites against the deployed service
URL=https://econ416-seating-273200940906.us-east1.run.app
.venv/bin/python server/test_service.py --remote $URL   # 48 (deadline is local-only)
.venv/bin/python server/test_browser.py --remote $URL
```

## Deploy

```bash
# the service (from seating/ — the Dockerfile needs the app files beside it)
gcloud run deploy econ416-seating --source . --project econ416-seating \
  --region us-east1 \
  --service-account seating-run@econ416-seating.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT=econ416-seating,CLAIM_DEADLINE=2026-08-31T00:00:00-04:00"

# the Firestore rules
firebase deploy --only firestore:rules --project econ416-seating

# the public front door (GitHub Pages) — bump ?v= in index.html first
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite add seating
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite commit -m "..."
git -C ~/Dropbox/Teaching/Projects/PersonalWebsite push
```

## The seats

```bash
python3 tools/seed_seats.py --dry-run   # validate the layout, write nothing
python3 tools/seed_seats.py             # seed / refresh — claims are PRESERVED
python3 tools/seed_seats.py --verify    # diff Firestore against room-layout.json
```

Re-running the seeder never un-claims anyone. `--reset-claims` does, and asks
first.

## Codes: issue, send, revoke

The roster comes live from Canvas — `sis_user_id` is the PID, `id` is the
Canvas ID. No roster file, no merge, nothing to go stale.

```bash
# 1. issue (writes ~/Dropbox/Teaching/416/Data/416_seating_codes.json, 0600)
python3 tools/issue_codes.py --dry-run
python3 tools/issue_codes.py

# 2. send to YOURSELF first — the full round trip before anyone else gets one
python3 tools/send_codes.py --prepare --only <your-PID>
#    …then have the assistant send the outbox through the Canvas MCP
python3 tools/send_codes.py --mark-sent <your-PID>

# 3. the rest
python3 tools/send_codes.py --prepare
python3 tools/send_codes.py --status

# lost or forwarded code
python3 tools/revoke_code.py <PID> --reissue
python3 tools/revoke_code.py --list
```

`send_codes.py` never sends: Canvas is reached through the MCP server, so the
tool prepares the messages and records what went out, which is what makes a
half-finished run resumable.

## Roster

**Canvas is the only source.** `issue_codes.py` pulls the section live at issue
time and takes `sis_user_id` as the PID, `id` as the Canvas ID, `login_id` as
the onyen. Currently **50 students**. It validates before writing anything and
refuses on a missing PID, a non-integer Canvas ID, or any duplicate.

The old `416_roster.json` merged Canvas with a ConnectCarolina export and is not
used here: the name-based match appended instead of updated, so it carries a
duplicated student and a Canvas ID stored as the float `136574.0`. Nothing in
the seating app reads it.

## The secret files

All three live in `~/Dropbox/Teaching/416/Data/`, **outside this repository** —
`seating/` is published to GitHub Pages and none of this belongs near it:

- `416_seating_codes.json` — the (Canvas ID, code) table, 0600
- `416_seating_outbox.json` — prepared messages, each containing a live link
- `416_seating_sent.json` — what actually went out

The code table is the only copy of the tokens; Firestore stores `sha256(token)`
and nothing else, so losing it means reissuing.

## If something looks wrong

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND severity>=WARNING' \
  --project econ416-seating --limit 20 --format="value(textPayload)"

curl -s $URL/health          # NOT /healthz — Google Frontend eats that path
```
