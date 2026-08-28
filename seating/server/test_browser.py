#!/usr/bin/env python3
"""Browser tests: the student journey, driven through a real Chrome.

`test_service.py` proves the API. This proves the thing the student actually
touches — a real click on a real seat, Link walking there, the NES dialog, the
claim, and the seat following the student to a different device.

Clicks are real mouse events at real pixels: the seat's canvas coordinates come
from the same formula the renderer uses (`GUI.md`), mapped through the canvas's
bounding box, so this exercises the tap → route → dwell → dialog → claim path
end to end rather than calling a function directly.

Any uncaught JS error fails the run — the cheapest way to catch a wiring mistake
that still renders.

Uses the installed Chrome (`channel="chrome"`), so no browser download.

    .venv/bin/python server/test_browser.py                # local server
    .venv/bin/python server/test_browser.py --remote URL   # Cloud Run
"""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "econ416-seating"
SECRET = "test-only-not-the-real-key"
PORT = 8933
DEMO_PORT = 8934     # a plain static server: the GitHub Pages copy, locally

TEST_PID = "TEST-BROWSER-1"
TEST_PID2 = "TEST-BROWSER-2"
SEAT = "5_4"          # an ordinary claimable seat, reachable from the door
SEAT_OTHER = "5_9"    # claimed by "another student" mid-session
SEAT_MOVED = "5_5"    # where the first student moves on a second visit

# The renderer's geometry, from GUI.md. Duplicated here on purpose: if someone
# changes the layout constants without updating the art, this test should break.
T, WALL, PAD_TOP, PAD_LEFT = 16, 32, 2, 1

ok = fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}" + (f"  — {detail}" if detail else ""))


def firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)


def make_code(db, pid: str) -> str:
    token = secrets.token_urlsafe(16)
    db.collection("codes").document(hashlib.sha256(token.encode()).hexdigest()).set({
        "canvasId": "TEST-CANVAS", "pid": pid, "name": "TEST STUDENT",
        "issuedAt": datetime.now(timezone.utc),
        "expiresAt": datetime.now(timezone.utc) + timedelta(days=30),
        "revoked": False, "test": True,
    })
    return token


def cleanup(db) -> None:
    for d in db.collection("codes").where("test", "==", True).stream():
        d.reference.delete()
    for pid in (TEST_PID, TEST_PID2):
        db.collection("claims").document(pid).delete()
    for seat in (SEAT, SEAT_OTHER, SEAT_MOVED):
        db.collection("seats").document(seat).update({"taken": False})


def start_server() -> subprocess.Popen:
    env = dict(os.environ)
    env.update({"PORT": str(PORT), "DEV": "1", "SESSION_SECRET": SECRET,
                "GCP_PROJECT": PROJECT,
                "CLAIM_DEADLINE": "2026-08-26T00:00:00-04:00"})
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "server/main.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=1).ok:
                return proc
        except requests.RequestException:
            pass
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not start")


def click_seat(page, seat_id: str) -> None:
    """Click the centre of a seat, in real page pixels."""
    row, col = (int(x) for x in seat_id.split("_"))
    pt = page.evaluate(
        """([row, col, T, WALL, PAD_TOP, PAD_LEFT]) => {
            const cv = document.getElementById('room');
            const box = cv.getBoundingClientRect();
            const ic = PAD_LEFT + col - 1;      // C0 = seat_cols[0] = 1
            const ir = PAD_TOP + row - 0;       // R0 = seat_rows[0] = 0
            const x = WALL + ic * T + T / 2;
            const y = WALL + ir * T + T / 2;
            return { x: box.x + x * (box.width / cv.width),
                     y: box.y + y * (box.height / cv.height) };
        }""",
        [row, col, T, WALL, PAD_TOP, PAD_LEFT])
    page.mouse.click(pt["x"], pt["y"])


def wait_for_dialog(page, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_function(
            "() => window.seating.game.dialog !== null", timeout=timeout_ms)
        return True
    except Exception:
        return False


def boot(ctx, base: str, token: str):
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{base}/c/{token}", wait_until="networkidle")
    page.wait_for_function("() => window.seating !== undefined", timeout=20000)
    return page, errs


def main(remote: str | None = None) -> int:
    db = firestore_client()
    # Seats already claimed before this run — a real instructor or student
    # claim, not ours. The end-of-run check is a delta against this, so a live
    # claim does not read as a leak. (The suite still WRITES to the live
    # collections, so it is still not safe to run once codes are out.)
    pre_taken = {d.id for d in db.collection("seats").stream()
                 if d.to_dict().get("taken")}
    print(f"setup ({'remote ' + remote if remote else 'local'})")
    cleanup(db)
    tok1 = make_code(db, TEST_PID)
    tok2 = make_code(db, TEST_PID2)

    proc = None
    if remote:
        base = remote.rstrip("/")
    else:
        base = f"http://127.0.0.1:{PORT}"
        proc = start_server()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")

            # --- the gate ----------------------------------------------------
            print("\nGATE")
            ctx = browser.new_context()
            page, errors = boot(ctx, base, tok1)
            check("valid link lands on /app", page.url.endswith("/app"), page.url)
            check("token is gone from the URL", tok1 not in page.url)
            check("app booted", page.evaluate("!!window.seating"))
            check("no seat held yet",
                  page.evaluate("window.seating.game.mySeat") is None)

            probe = ctx.new_page()
            resp = probe.goto(f"{base}/c/{'q' * 22}")
            check("bogus link 404s in a real browser", resp.status == 404,
                  str(resp.status))
            probe.close()

            # --- claim by clicking the seat ----------------------------------
            print("\nCLAIM BY CLICKING")
            click_seat(page, SEAT)
            check("clicking a seat opens the dialog", wait_for_dialog(page))
            check("dialog names the right seat",
                  page.evaluate("window.seating.game.dialog.title")
                  == f"ROW {SEAT.split('_')[0]} SEAT {SEAT.split('_')[1]}",
                  page.evaluate("window.seating.game.dialog.title"))
            check("dialog asks to sit",
                  page.evaluate("window.seating.game.dialog.prompt") == "SIT HERE?")

            page.keyboard.press("Enter")            # YES is the default choice
            page.wait_for_function(
                "() => window.seating.game.dialog === null", timeout=10000)
            page.wait_for_timeout(1200)             # let the POST land

            check("app records the seat",
                  page.evaluate("window.seating.game.mySeat") == SEAT,
                  str(page.evaluate("window.seating.game.mySeat")))
            check("claiming leaves the session free to move (IDLE)",
                  page.evaluate("window.seating.game.state") == "IDLE",
                  str(page.evaluate("window.seating.game.state")))
            check("the hint reports the claim",
                  page.evaluate("window.seating.hint()")
                  == "SEAT CLAIMED - CLICK TO MOVE",
                  page.evaluate("window.seating.hint()"))
            check("firestore recorded the claim",
                  db.collection("seats").document(SEAT).get().to_dict()["taken"] is True)
            check("claim document written",
                  db.collection("claims").document(TEST_PID).get().exists)

            # --- the seat follows the student, not the device -----------------
            print("\nDIFFERENT DEVICE, SAME STUDENT")
            ctx2 = browser.new_context()            # fresh profile, no cookies
            page2, errs2 = boot(ctx2, base, tok1)
            page2.wait_for_timeout(600)
            check("claimed seat restored on a new device",
                  page2.evaluate("window.seating.game.mySeat") == SEAT,
                  str(page2.evaluate("window.seating.game.mySeat")))
            # A fresh visit starts you ON your seat but free to move: that is
            # the only way to change one, and it is why the confirm dialog can
            # stay final within a session.
            check("a fresh visit is free to choose again (IDLE, not SEATED)",
                  page2.evaluate("window.seating.game.state") == "IDLE",
                  str(page2.evaluate("window.seating.game.state")))
            check("no JS errors on the second device", not errs2, str(errs2))

            # --- the live map -------------------------------------------------
            print("\nLIVE MAP (no reload)")
            ctx3 = browser.new_context()
            page3, errs3 = boot(ctx3, base, tok2)
            click_seat(page3, SEAT_OTHER)
            check("second student's dialog opens", wait_for_dialog(page3))
            page3.keyboard.press("Enter")
            page3.wait_for_timeout(1200)
            check("second student got their seat",
                  page3.evaluate("window.seating.game.mySeat") == SEAT_OTHER,
                  str(page3.evaluate("window.seating.game.mySeat")))

            page2.wait_for_timeout(7000)            # one poll interval + slack
            seen = page2.evaluate(
                "(id) => window.seating.seat(id).taken", SEAT_OTHER)
            check("first student sees it taken without reloading",
                  seen is True, str(seen))

            # --- changing seats on a second visit -----------------------------
            print("\nCHANGE SEAT ON A NEW VISIT")
            click_seat(page2, SEAT_MOVED)
            check("a held seat does not block choosing another",
                  wait_for_dialog(page2))
            check("the dialog says MOVE, not SIT",
                  page2.evaluate("window.seating.game.dialog.prompt") == "MOVE HERE?",
                  str(page2.evaluate("window.seating.game.dialog.prompt")))
            page2.keyboard.press("Enter")
            page2.wait_for_function(
                "() => window.seating.game.dialog === null", timeout=10000)
            page2.wait_for_timeout(1500)
            check("the app moved to the new seat",
                  page2.evaluate("window.seating.game.mySeat") == SEAT_MOVED,
                  str(page2.evaluate("window.seating.game.mySeat")))
            check("firestore moved the claim",
                  db.collection("claims").document(TEST_PID).get()
                    .to_dict()["seatId"] == SEAT_MOVED)
            check("the old seat was freed in the same transaction",
                  db.collection("seats").document(SEAT).get()
                    .to_dict()["taken"] is False)
            check("the new seat is taken",
                  db.collection("seats").document(SEAT_MOVED).get()
                    .to_dict()["taken"] is True)

            # Unlimited moves: claiming does not lock the session.
            check("claiming leaves you free to move again (IDLE)",
                  page2.evaluate("window.seating.game.state") == "IDLE",
                  str(page2.evaluate("window.seating.game.state")))
            check("the hint says the seat is claimed and movable",
                  page2.evaluate("window.seating.hint()")
                  == "SEAT CLAIMED - CLICK TO MOVE",
                  page2.evaluate("window.seating.hint()"))
            click_seat(page2, "5_6")
            check("a second move in the same visit is allowed",
                  wait_for_dialog(page2))
            page2.keyboard.press("Escape")
            page2.wait_for_timeout(600)

            # --- losing the race ----------------------------------------------
            print("\nSEAT TAKEN")
            # The live map refreshes on a poll, not instantly: wait for page3
            # to actually observe the seat as taken before asserting on it.
            seen_taken = True
            try:
                page3.wait_for_function(
                    "(id) => window.seating.seat(id).taken === true",
                    arg=SEAT_MOVED, timeout=15000)
            except Exception:
                seen_taken = False
            check("the other student's map picks up the new claim by polling",
                  seen_taken, "still shows free after 15s")
            click_seat(page3, SEAT_MOVED)
            page3.wait_for_timeout(1500)
            check("a seat someone else holds cannot be selected",
                  page3.evaluate("window.seating.game.dialog") is None,
                  "a dialog opened for a taken seat")

            check("no JS errors in the main session", not errors, str(errors))
            check("no JS errors in the third session", not errs3, str(errs3))

            # --- the first device catches up with the move ---------------------
            # `page` claimed SEAT; `page2` (same student, other device) has
            # since moved to SEAT_MOVED. The first device must follow, or a
            # student sees a seat they gave up until they happen to reload.
            print("\nTHE OTHER DEVICE FOLLOWS")
            followed = True
            try:
                page.wait_for_function(
                    "(id) => window.seating.game.mySeat === id",
                    arg=SEAT_MOVED, timeout=20000)
            except Exception:
                followed = False
            check("the first device picks up the seat change by polling",
                  followed, str(page.evaluate("window.seating.game.mySeat")))
            check("and it frees the seat it used to think it held",
                  page.evaluate("(id) => window.seating.seat(id).taken",
                                SEAT) is False,
                  str(page.evaluate("(id) => window.seating.seat(id).taken", SEAT)))

            # --- the room stays yours after you sit down ----------------------
            # Claiming must not turn the game off: arrows, swipes and the
            # Moblin all still work, and dying does not cost you your seat.
            print("\nSTILL A GAME AFTER CLAIMING")
            page.wait_for_timeout(300)
            before = page.evaluate("[window.seating.game.link.x, "
                                   "window.seating.game.link.y]")
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(700)
            after = page.evaluate("[window.seating.game.link.x, "
                                  "window.seating.game.link.y]")
            check("arrow keys still move Link after claiming", before != after,
                  f"{before} -> {after}")

            # The server's view of this student's seat, which is the thing that
            # must survive a death. (Not SEAT: this student moved seats on a
            # second device earlier in the run, and `page` still shows its own
            # stale copy -- polling deliberately skips your own seat.)
            seat_before_death = (db.collection("claims").document(TEST_PID)
                                 .get().to_dict()["seatId"])

            # Walk up the room until the Moblin catches him. He paces interior
            # row 0, so heading up from a seat runs into him.
            died = False
            for _ in range(40):
                page.keyboard.press("ArrowUp")
                page.wait_for_timeout(220)
                st = page.evaluate("window.seating.game.state")
                if st in ("DYING", "GAMEOVER"):
                    died = True
                    break
            check("you can still get killed by the Moblin", died,
                  page.evaluate("window.seating.game.state"))

            if died:
                page.wait_for_function(
                    "() => window.seating.game.state === 'GAMEOVER'",
                    timeout=10000)
                page.keyboard.press("Enter")          # RETRY
                page.wait_for_timeout(800)
                check("dying does not cost you your seat",
                      page.evaluate("window.seating.game.mySeat") is not None,
                      str(page.evaluate("window.seating.game.mySeat")))
                seat_after_death = (db.collection("claims").document(TEST_PID)
                                    .get().to_dict()["seatId"])
                check("and the server's claim is untouched by dying",
                      seat_after_death == seat_before_death,
                      f"{seat_before_death} -> {seat_after_death}")
                check("back to a playable room after retry",
                      page.evaluate("window.seating.game.state") == "IDLE",
                      str(page.evaluate("window.seating.game.state")))

            # --- the public demo ---------------------------------------------
            # Served statically with no service behind it, which is exactly
            # what GitHub Pages is. No code, no cookie, and nothing claimed.
            print("\nDEMO (static, no service)")
            demo_proc = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(DEMO_PORT),
                 "--directory", str(ROOT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        if requests.get(f"http://127.0.0.1:{DEMO_PORT}/",
                                        timeout=1).ok:
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(0.2)

                ctxd = browser.new_context()
                paged = ctxd.new_page()
                errsd: list[str] = []
                api_calls: list[str] = []
                paged.on("pageerror", lambda e: errsd.append(str(e)))
                paged.on("request", lambda r: api_calls.append(r.url)
                         if "/api/" in r.url else None)
                paged.goto(f"http://127.0.0.1:{DEMO_PORT}/",
                           wait_until="networkidle")
                paged.wait_for_function("() => window.seating !== undefined",
                                        timeout=20000)

                check("demo loads with no code and no cookie",
                      paged.evaluate("!!window.seating"))
                check("demo knows it is a demo",
                      paged.evaluate("window.seating.isDemo()") is True)
                check("demo hint says the seat cannot be claimed",
                      paged.evaluate("window.seating.hint()")
                      == "DEMO - SEAT CANNOT BE CLAIMED",
                      paged.evaluate("window.seating.hint()"))

                click_seat(paged, SEAT)
                check("demo lets you pick a seat", wait_for_dialog(paged))
                paged.keyboard.press("Enter")
                paged.wait_for_timeout(1000)
                check("demo seats you locally",
                      paged.evaluate("window.seating.game.mySeat") == SEAT,
                      str(paged.evaluate("window.seating.game.mySeat")))
                check("demo hint still says it cannot be claimed",
                      paged.evaluate("window.seating.hint()")
                      == "DEMO - SEAT CANNOT BE CLAIMED",
                      paged.evaluate("window.seating.hint()"))
                # The demo probes `api/me` exactly once -- the 404 is how it
                # discovers there is no service and switches to demo mode.
                # What must never happen is a claim, a release, or seat data.
                probes = [u for u in api_calls if u.endswith("/api/me")]
                writes = [u for u in api_calls if not u.endswith("/api/me")]
                check("demo probes api/me once to detect demo mode",
                      len(probes) == 1, str(probes))
                check("demo never claims, releases or fetches seat data",
                      not writes, str(writes))
                check("demo claims nothing in firestore",
                      db.collection("seats").document(SEAT).get()
                        .to_dict()["taken"] is False)

                paged.reload(wait_until="networkidle")
                paged.wait_for_function("() => window.seating !== undefined",
                                        timeout=20000)
                check("demo keeps nothing across a reload",
                      paged.evaluate("window.seating.game.mySeat") is None,
                      str(paged.evaluate("window.seating.game.mySeat")))
                check("no JS errors in the demo", not errsd, str(errsd))
            finally:
                demo_proc.terminate()

            browser.close()
    finally:
        if proc:
            proc.terminate()
        print("\nteardown")
        cleanup(db)

    seats = list(db.collection("seats").stream())
    check("134 seats present", len(seats) == 134)
    leaked = {d.id for d in seats if d.to_dict().get("taken")} - pre_taken
    check("no seat left taken by this run", not leaked, f"leaked={sorted(leaked)}")
    if pre_taken:
        print(f"  (ignoring {len(pre_taken)} seat(s) claimed before the run: "
              f"{', '.join(sorted(pre_taken))})")

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    url = argv[argv.index("--remote") + 1] if "--remote" in argv else None
    sys.exit(main(url))
