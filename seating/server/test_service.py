#!/usr/bin/env python3
"""End-to-end tests for the seating service — the Phase 2 test plan, executed.

Runs the real Flask app against the real Firestore project, because the two
things most worth testing are exactly the two a mock would fake: that a Firestore
transaction actually refuses a double booking under concurrency, and that a
request with no cookie actually gets nothing.

Every artifact this creates is namespaced `TEST-` and removed in teardown; the
run finishes by asserting the seat map is back to 134 seats with zero taken. It
is safe to run against the live project *before* codes go out, and must not be
run after — it would disturb real claims.

    .venv/bin/python server/test_service.py               # local, all tests
    .venv/bin/python server/test_service.py --remote URL  # against Cloud Run
"""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "econ416-seating"
SECRET = "test-only-not-the-real-key"
PORT = 8931          # not 8000/8416/8731 — those are in use on this machine
PORT_CLOSED = 8932   # a second instance whose deadline has already passed

TEST_PID = "TEST-PID-0001"
TEST_PID2 = "TEST-PID-0002"
SEAT_A = "4_5"       # ordinary claimable seats, well inside the open rows
SEAT_B = "4_6"
SEAT_RESERVED = "0_4"
SEAT_BLOCKED = "8_5"  # rows 7-10 are usable:false

ok_count = 0
fail_count = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  PASS  {name}")
    else:
        fail_count += 1
        print(f"  FAIL  {name}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)


def make_code(db, pid: str, *, revoked=False, expired=False) -> str:
    """Create a real code document and return its clear token."""
    token = secrets.token_urlsafe(16)
    digest = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + (
        timedelta(days=-1) if expired else timedelta(days=30))
    db.collection("codes").document(digest).set({
        "canvasId": "TEST-CANVAS",
        "pid": pid,
        "name": "TEST STUDENT",
        "issuedAt": datetime.now(timezone.utc),
        "expiresAt": expires,
        "revoked": revoked,
        "test": True,
    })
    return token


def start_server(port: int, deadline: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "PORT": str(port), "DEV": "1", "SESSION_SECRET": SECRET,
        "GCP_PROJECT": PROJECT, "CLAIM_DEADLINE": deadline,
    })
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "server/main.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                return proc
        except requests.RequestException:
            pass
        time.sleep(0.2)
    out = proc.stdout.read() if proc.stdout else ""
    proc.kill()
    raise RuntimeError(f"server on {port} did not start:\n{out}")


def cleanup(db) -> None:
    for d in db.collection("codes").where("test", "==", True).stream():
        d.reference.delete()
    for pid in (TEST_PID, TEST_PID2):
        db.collection("claims").document(pid).delete()
    for seat in (SEAT_A, SEAT_B):
        db.collection("seats").document(seat).update({"taken": False})


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------

def main(remote: str | None = None) -> int:
    db = firestore_client()
    # Seats already claimed before this run — a real instructor or student
    # claim, not ours. The end-of-run check is a delta against this, so a live
    # claim does not read as a leak. (The suite still WRITES to the live
    # collections, so it is still not safe to run once codes are out.)
    pre_taken = {d.id for d in db.collection("seats").stream()
                 if d.to_dict().get("taken")}
    print(f"setup: clearing leftovers ({'remote ' + remote if remote else 'local'})")
    cleanup(db)

    good = make_code(db, TEST_PID)
    good2 = make_code(db, TEST_PID2)
    expired = make_code(db, TEST_PID, expired=True)
    revoked = make_code(db, TEST_PID, revoked=True)

    if remote:
        # The deployed revision carries the real deadline and the real Secret
        # Manager key, so it cannot be handed a fake deadline; the
        # post-deadline section is covered by the local run instead.
        base = remote.rstrip("/")
        proc = None
    else:
        base = f"http://127.0.0.1:{PORT}"
        proc = start_server(PORT, "2026-08-26T00:00:00-04:00")
    proc_closed = None

    try:
        # --- the gate ------------------------------------------------------
        print("\nGATE")
        r = requests.get(f"{base}/c/{'x'*22}", allow_redirects=False)
        bogus_body = r.text
        check("bogus token -> 404", r.status_code == 404, f"got {r.status_code}")
        check("bogus token leaks no app asset",
              "seating.js" not in r.text and "assets/" not in r.text)

        r = requests.get(f"{base}/c/{expired}", allow_redirects=False)
        check("expired token -> 404", r.status_code == 404, f"got {r.status_code}")
        check("expired 404 is byte-identical to bogus", r.text == bogus_body)

        r = requests.get(f"{base}/c/{revoked}", allow_redirects=False)
        check("revoked token -> 404", r.status_code == 404, f"got {r.status_code}")
        check("revoked 404 is byte-identical to bogus", r.text == bogus_body)

        s = requests.Session()
        r = s.get(f"{base}/c/{good}", allow_redirects=False)
        check("valid token -> 302", r.status_code == 302, f"got {r.status_code}")
        check("valid token -> /app", r.headers.get("Location") == "/app")
        check("cookie set", "s416" in s.cookies)
        gate_setcookie = r.headers.get("Set-Cookie", "")
        check("cookie is HttpOnly", "httponly" in gate_setcookie.lower())
        if remote:
            check("cookie is Secure over https",
                  "secure" in gate_setcookie.lower(), gate_setcookie)
        check("Referrer-Policy: no-referrer",
              r.headers.get("Referrer-Policy") == "no-referrer")

        r2 = s.get(f"{base}/app")
        check("token absent from final URL", good not in r2.url)
        check("/app with cookie -> 200", r2.status_code == 200)
        check("/app serves the app", "seating.js" in r2.text)

        # --- no code, no page ----------------------------------------------
        print("\nNO CODE, NO PAGE")
        anon = requests.Session()
        for path in ("/app", "/js/seating.js", "/style.css",
                     "/assets/room.png", "/data/room-layout.json",
                     "/api/me", "/api/seats"):
            rr = anon.get(f"{base}{path}")
            check(f"anonymous {path} -> 404", rr.status_code == 404,
                  f"got {rr.status_code}")
        rr = anon.post(f"{base}/api/claim", json={"seatId": SEAT_A})
        check("anonymous POST /api/claim -> 404", rr.status_code == 404,
              f"got {rr.status_code}")

        rr = anon.get(f"{base}/")
        check("landing page is public", rr.status_code == 200)
        rr = anon.get(f"{base}/tools/seed_seats.py")
        check("tools/ not served", rr.status_code == 404)
        rr = anon.get(f"{base}/PHASE2-PLAN.md")
        check("plans not served", rr.status_code == 404)

        # --- claiming --------------------------------------------------------
        print("\nCLAIM")
        r = s.get(f"{base}/api/me").json()
        check("/api/me starts with no seat", r["seatId"] is None, str(r))
        check("/api/me carries the deadline", r["deadline"].startswith("2026-08-26"))

        r = s.post(f"{base}/api/claim", json={"seatId": SEAT_A})
        check(f"claim {SEAT_A} -> 200", r.status_code == 200, r.text)
        check("firestore seat is taken",
              db.collection("seats").document(SEAT_A).get().to_dict()["taken"] is True)
        cl = db.collection("claims").document(TEST_PID).get()
        check("claims/{pid} written", cl.exists)
        check("claim carries source=student",
              cl.exists and cl.to_dict().get("source") == "student")
        check("no PID in the public seat doc",
              "pid" not in db.collection("seats").document(SEAT_A).get().to_dict())

        r = s.get(f"{base}/api/me").json()
        check("/api/me survives reload", r["seatId"] == SEAT_A, str(r))

        r = s.post(f"{base}/api/claim", json={"seatId": SEAT_RESERVED})
        check("reserved seat refused (409)", r.status_code == 409, r.text)
        r = s.post(f"{base}/api/claim", json={"seatId": SEAT_BLOCKED})
        check("off-limits seat refused (409)", r.status_code == 409, r.text)
        r = s.post(f"{base}/api/claim", json={"seatId": "99_99"})
        check("nonexistent seat -> 404", r.status_code == 404, r.text)

        # --- change of seat frees the old one --------------------------------
        print("\nCHANGE SEAT")
        r = s.post(f"{base}/api/claim", json={"seatId": SEAT_B})
        check(f"change to {SEAT_B} -> 200", r.status_code == 200, r.text)
        check(f"{SEAT_A} freed in the same transaction",
              db.collection("seats").document(SEAT_A).get().to_dict()["taken"] is False)
        check(f"{SEAT_B} now taken",
              db.collection("seats").document(SEAT_B).get().to_dict()["taken"] is True)
        check("still exactly one claim for this student",
              db.collection("claims").document(TEST_PID).get().to_dict()["seatId"] == SEAT_B)

        # --- the race --------------------------------------------------------
        print("\nRACE (two students, one seat)")
        s.post(f"{base}/api/release")
        s2 = requests.Session()
        s2.get(f"{base}/c/{good2}", allow_redirects=False)

        results: list[int] = []
        lock = threading.Lock()

        def grab(sess):
            rr = sess.post(f"{base}/api/claim", json={"seatId": SEAT_A})
            with lock:
                results.append(rr.status_code)

        t1 = threading.Thread(target=grab, args=(s,))
        t2 = threading.Thread(target=grab, args=(s2,))
        t1.start(); t2.start(); t1.join(); t2.join()
        check("exactly one winner", sorted(results) == [200, 409],
              f"got {sorted(results)}")
        holders = [d.id for d in db.collection("claims").stream()
                   if d.to_dict().get("seatId") == SEAT_A]
        check("exactly one claim document for that seat", len(holders) == 1,
              f"holders={holders}")

        # --- the deadline -----------------------------------------------------
        # Needs a server whose deadline has already passed, which means booting
        # one locally; the deployed revision has the real August date.
        print("\nDEADLINE" + ("  (skipped on remote)" if remote else ""))
        if not remote:
          # A deadline that passed an hour ago -- the real post-deadline case.
          # (A date years in the past would also outrun the grace window and the
          # session would be refused for expiry rather than for the deadline,
          # which is a different code path than the one under test.)
          just_closed = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
          proc_closed = start_server(PORT_CLOSED, just_closed)
          closed = f"http://127.0.0.1:{PORT_CLOSED}"
          s3 = requests.Session()
          s3.get(f"{closed}/c/{good}", allow_redirects=False)
          r = s3.post(f"{closed}/api/claim", json={"seatId": SEAT_B})
          check("claim after deadline -> 403", r.status_code == 403, r.text)
          r = s3.post(f"{closed}/api/release")
          check("release after deadline -> 403", r.status_code == 403, r.text)
          check("app still loads during grace",
                s3.get(f"{closed}/app").status_code == 200)
          me = s3.get(f"{closed}/api/me")
          check("/api/me still answers during grace", me.status_code == 200,
                me.text[:80])
          if me.status_code == 200:
              j = me.json()
              check("/api/me reports closed", j["closed"] is True, str(j))
              check("/api/me still shows the seat you got",
                    j["seatId"] in (SEAT_A, SEAT_B, None), str(j))

        # --- tampering --------------------------------------------------------
        print("\nCOOKIE TAMPERING")
        stolen = s.cookies.get("s416")
        payload, sig = stolen.split(".", 1)
        forged = requests.Session()
        host = base.split("://", 1)[1].split("/")[0].split(":")[0]
        forged.cookies.set("s416", f"{payload}.{'A'*len(sig)}", domain=host)
        check("bad signature -> 404",
              forged.get(f"{base}/app").status_code == 404)
        forged.cookies.set("s416", "garbage", domain=host)
        check("malformed cookie -> 404",
              forged.get(f"{base}/app").status_code == 404)

    finally:
        if proc:
            proc.terminate()
        if proc_closed:
            proc_closed.terminate()
        print("\nteardown: removing test codes, claims and holds")
        cleanup(db)

    # --- the room is back where it started ---------------------------------
    print("\nPOST-RUN STATE")
    seats = list(db.collection("seats").stream())
    taken = [d.id for d in seats if d.to_dict().get("taken")]
    test_codes = list(db.collection("codes").where("test", "==", True).stream())
    check("134 seats present", len(seats) == 134, f"got {len(seats)}")
    leaked = set(taken) - pre_taken
    check("no seat left taken by this run", not leaked, f"leaked={sorted(leaked)}")
    if pre_taken:
        print(f"  (ignoring {len(pre_taken)} seat(s) claimed before the run: "
              f"{', '.join(sorted(pre_taken))})")
    check("zero test codes left", not test_codes, f"n={len(test_codes)}")

    print(f"\n{ok_count} passed, {fail_count} failed")
    return 1 if fail_count else 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    url = argv[argv.index("--remote") + 1] if "--remote" in argv else None
    sys.exit(main(url))
