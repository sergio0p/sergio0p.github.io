#!/usr/bin/env python3
"""Problem-set routes: group resolution, the append, and the two-partner case.

    ./.venv/bin/python server/test_ps.py

SAFE TO RUN WITH REAL CODES OUT, unlike test_service.py and test_browser.py.
Those write to `codes`, `seats` and `claims` -- the live seating collections.
This one touches nothing but `psGroups/T0` and `submissions/T0_*`, a problem set
that exists only in this process's PS_SETS, and it deletes both on the way out.
A stray T0 document could not reach a student even if cleanup failed: the
deployed service's PS_SETS has no T0 in it, so every route would 404 on it.

The case worth the whole exercise is two partners on two machines. That is what
localStorage could not do: A submitted Part I, B opened the page on their own
laptop, saw an empty form and was told "Part I is still outstanding" -- which was
false. Here B's request carries B's own session and still sees what A filed.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

PS = "T0"                       # the only id this file may ever write
os.environ["DEV"] = "1"
os.environ["SESSION_SECRET"] = "test-only-not-the-real-one"
os.environ["PS_SETS"] = json.dumps({PS: {"due": None, "parts": ["I", "II"]}})

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main                                                     # noqa: E402
from google.cloud import firestore                              # noqa: E402

assert PS not in json.loads('{"02": {"due": null, "parts": ["I", "II"]}}'), \
    "T0 must not collide with a real problem set"

ok = True
def check(name, cond, detail=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail and not cond else ""))
    if not cond:
        ok = False

A = {"pid": "900000001", "cid": "1", "name": "Ada Test"}
B = {"pid": "900000002", "cid": "2", "name": "Bo Test"}
SOLO = {"pid": "900000003", "cid": "3", "name": "Cy Test"}
NOBODY = {"pid": "900000009", "cid": "9", "name": "Dee Unenrolled"}

GROUPS = [
    {"groupId": 990001, "groupName": "Test & Partner PS T0",
     "members": [{"pid": A["pid"], "canvasId": 1, "name": A["name"]},
                 {"pid": B["pid"], "canvasId": 2, "name": B["name"]}]},
    {"groupId": 990002, "groupName": "Solo PS T0",
     "members": [{"pid": SOLO["pid"], "canvasId": 3, "name": SOLO["name"]}]},
]

db = firestore.Client(project=main.PROJECT)


def cookie_for(who):
    return main.make_session(who["pid"], who["cid"], who["name"], time.time() + 3600)


def client_for(who):
    c = main.app.test_client()
    if who:
        c.set_cookie(main.COOKIE, cookie_for(who), domain="localhost")
    return c


def cleanup():
    db.collection("psGroups").document(PS).delete()
    for g in GROUPS:
        ref = db.collection("submissions").document(f"{PS}_{g['groupId']}")
        for v in ref.collection("versions").stream():
            v.reference.delete()
        ref.delete()


cleanup()                                   # a failed earlier run leaves nothing behind
db.collection("psGroups").document(PS).set({
    "ps": PS, "categoryId": 0, "groups": GROUPS,
    "frozenAt": firestore.SERVER_TIMESTAMP})

try:
    # --- who am I, and what has my group filed --------------------------------
    print("reading")
    a = client_for(A)
    r = a.get(f"/api/ps/{PS}/me")
    check("a signed-in student gets their group", r.status_code == 200, str(r.status_code))
    me = r.get_json()
    check("named as Canvas names it", me["group"]["groupName"] == "Test & Partner PS T0",
          str(me["group"]))
    check("with both members, since surnames go ambiguous",
          [m["name"] for m in me["group"]["members"]] == [A["name"], B["name"]],
          str(me["group"]["members"]))
    check("and no PIDs on the wire",
          "pid" not in json.dumps(me["group"]) and A["pid"] not in json.dumps(me),
          json.dumps(me)[:120])
    check("nothing filed yet", me["submission"] is None, str(me["submission"]))

    check("no cookie, no answer", client_for(None).get(f"/api/ps/{PS}/me").status_code == 404)
    check("a problem set that does not exist is a 404, not a hint",
          a.get("/api/ps/T9/me").status_code == 404)
    check("and its body is the identical 404",
          a.get("/api/ps/T9/me").data.decode() == main.NOT_FOUND_BODY)

    # A student with no group for this round is a defined state, not an error.
    r = client_for(NOBODY).get(f"/api/ps/{PS}/me")
    check("no group is 200 with group null, not a 404",
          r.status_code == 200 and r.get_json()["group"] is None, str(r.status_code))

    # --- the append -----------------------------------------------------------
    print("\nsubmitting")
    r = a.post(f"/api/ps/{PS}/submit", json={
        "part": "I", "blanks": [],
        "answers": {"I-I": ["a>b:DR"], "I-II": [], "I-III": []}})
    check("Ada files Part I", r.status_code == 200, r.data.decode()[:120])
    check("and it is version 1", r.get_json()["version"] == 1, str(r.get_json()))

    # THE POINT OF ALL OF THIS.
    print("\nthe partner, on another machine")
    b = client_for(B)
    sub = b.get(f"/api/ps/{PS}/me").get_json()["submission"]
    check("Bo sees the group's submission without having made one",
          sub is not None and sub["version"] == 1, str(sub))
    check("and can see who filed it", sub["submittedBy"] == A["name"], str(sub))
    check("and reads back Ada's actual answers",
          sub["answers"]["I"]["I-I"] == ["a>b:DR"], json.dumps(sub["answers"])[:120])
    check("Part II is correctly still outstanding", sub["parts"] == ["I"], str(sub["parts"]))

    r = b.post(f"/api/ps/{PS}/submit", json={
        "part": "II", "blanks": [], "answers": ["stated-1:lt", "infer-1:no"]})
    check("Bo files Part II", r.get_json()["version"] == 2, str(r.get_json()))

    # Filing one part must not wipe the other. This is the merge, and it is the
    # difference between "a submission" and "half a submission".
    sub = a.get(f"/api/ps/{PS}/me").get_json()["submission"]
    check("Ada now sees both parts", sub["parts"] == ["I", "II"], str(sub["parts"]))
    check("Part I survived Bo's write",
          sub["answers"]["I"]["I-I"] == ["a>b:DR"], json.dumps(sub["answers"])[:140])
    check("and Part II is there too",
          sub["answers"]["II"] == ["stated-1:lt", "infer-1:no"], str(sub["answers"].get("II")))

    r = a.post(f"/api/ps/{PS}/submit", json={
        "part": "I", "blanks": ["Part I-II"],
        "answers": {"I-I": ["a>b:DR", "b>c:DR"], "I-II": [], "I-III": []}})
    check("resubmitting appends rather than overwriting", r.get_json()["version"] == 3)
    sub = b.get(f"/api/ps/{PS}/me").get_json()["submission"]
    check("the new Part I is live", len(sub["answers"]["I"]["I-I"]) == 2)
    check("and Part II still survives", "II" in sub["answers"])
    check("nothing is marked late while no due date is set", sub["late"] is False)

    # --- refusals -------------------------------------------------------------
    print("\nrefusals")
    check("an unknown part is rejected",
          a.post(f"/api/ps/{PS}/submit", json={"part": "III", "answers": {}}).status_code == 400)
    check("a missing answers key is rejected",
          a.post(f"/api/ps/{PS}/submit", json={"part": "I"}).status_code == 400)
    check("an oversized body is refused, not stored",
          a.post(f"/api/ps/{PS}/submit",
                 json={"part": "I", "answers": {"x": "y" * 70000}}).status_code == 413)
    check("a student with no group cannot create an orphan submission",
          client_for(NOBODY).post(f"/api/ps/{PS}/submit",
                                  json={"part": "I", "answers": {}}).status_code == 409)
    check("and no cookie means 404, not 401",
          client_for(None).post(f"/api/ps/{PS}/submit",
                                json={"part": "I", "answers": {}}).status_code == 404)

    # --- the race -------------------------------------------------------------
    # Two partners pressing submit at the same instant. Without the transaction
    # both read count=3, both write version 4, and one submission disappears
    # with nothing anywhere recording that it ever existed.
    print("\nboth at once")
    before = a.get(f"/api/ps/{PS}/me").get_json()["submission"]["count"]
    results, errors = [], []
    def fire(who, part, answers):
        try:
            c = client_for(who)
            r = c.post(f"/api/ps/{PS}/submit", json={"part": part, "answers": answers})
            results.append((r.status_code, (r.get_json() or {}).get("version")))
        except Exception as e:                       # noqa: BLE001
            errors.append(repr(e))
    threads = [
        threading.Thread(target=fire, args=(A, "I", {"I-I": ["a>c:IR"], "I-II": [], "I-III": []})),
        threading.Thread(target=fire, args=(B, "II", ["stated-1:gt"])),
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    check("both writes succeeded", errors == [] and all(s == 200 for s, _ in results),
          str(results + errors))
    got = sorted(v for _, v in results if v is not None)
    check("they got different version numbers", got == [before + 1, before + 2], str(got))
    after = a.get(f"/api/ps/{PS}/me").get_json()
    check("and the count moved by exactly two",
          after["submission"]["count"] == before + 2, str(after["submission"]["count"]))
    versions = list(db.collection("submissions").document(f"{PS}_{GROUPS[0]['groupId']}")
                    .collection("versions").stream())
    check("every version is on disk, none overwritten",
          len(versions) == before + 2, f"{len(versions)} vs {before + 2}")
    check("and the last one still holds both parts",
          set(after["submission"]["answers"]) == {"I", "II"},
          str(list(after["submission"]["answers"])))

    # --- lateness -------------------------------------------------------------
    print("\nlateness")
    main.PS_SETS[PS]["due"] = "2020-01-01T00:00:00-05:00"
    r = a.post(f"/api/ps/{PS}/submit", json={"part": "I", "answers": {"I-I": []}})
    check("a late submission is stored, not refused", r.status_code == 200)
    check("and marked late", r.get_json()["late"] is True, str(r.get_json()))
    check("the page is told the set is closed",
          a.get(f"/api/ps/{PS}/me").get_json()["closed"] is True)
    main.PS_SETS[PS]["due"] = None
    check("an unset due date is never 'closed'",
          a.get(f"/api/ps/{PS}/me").get_json()["closed"] is False)

finally:
    cleanup()
    left = db.collection("psGroups").document(PS).get().exists
    print(f"\ncleaned up: psGroups/{PS} gone = {not left}")

print("\n" + ("ALL CHECKS PASSED" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
