#!/usr/bin/env python3
"""The ECON 416 seating service: the gate, the API, and the static files.

One Cloud Run container does all three, and that is the whole point. The
requirement that killed the original static design was "without a code you
don't get to see the page": a file server hands over the app before any check
can run, so the check has to live in front of the files.

Two routes are public: `/` (a landing page that tells you to check Canvas) and
`/c/<token>` (the gate). **Everything else requires the session cookie** —
`/app`, the stylesheet, the sprites, the room layout, every API route. A visitor
without a code cannot fetch so much as a tile.

The gate is the only place a token is ever accepted. It trades the token for a
cookie and redirects to a clean `/app`, so the token leaves the address bar, the
history, and any screenshot taken a second later. Every failure — unknown,
expired, revoked, malformed, rate-limited — returns the *identical* 404, so
there is no difference to measure and no way to ask "is this person enrolled".

Enforcement is ordinary Python here, not Firestore rules. The rules deny clients
everything; this service reaches Firestore with admin credentials and is the
only thing that writes. That keeps the security posture readable and testable.

    PORT=8080 DEV=1 SESSION_SECRET=dev-only python3 server/main.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, make_response, redirect, request, send_from_directory

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT = os.environ.get("GCP_PROJECT", "econ416-seating")

# Midnight ENDING Sun 30 Aug 2026, America/New_York (EDT, UTC-4). Every code's
# expiry and every claim check measure against this one constant.
#
# Moved 2026-08-28 from midnight ending Wed 26 Aug. Students who tried to change
# seats after it closed were refused correctly but told so too quietly, and read
# the bounce-back as a broken button; the window was reopened once and the
# message rewritten (`closedMessage()` in js/seating.js). The previous comment
# here said "Tue 25 Aug" and was simply wrong -- it is what made the closure
# look like a bug rather than a deadline. Keep this line and the constant honest.
DEADLINE_ISO = os.environ.get("CLAIM_DEADLINE", "2026-08-31T00:00:00-04:00")
DEADLINE = datetime.fromisoformat(DEADLINE_ISO)

# How long a session may live, independent of any one deadline.
#
# This used to be the claim deadline plus a grace week, back when a seat map was
# the only thing behind the gate: a cookie that died the instant claiming closed
# would have turned every late visit into a bare 404 instead of the `TIME IS UP`
# dialog. The grace still matters for exactly that reason -- you can always open
# your link and see the seat you got, and only the *write* is refused with a 403.
#
# But the same gate and the same tokens now carry the problem set app, so tying
# session life to the seat deadline would lock every student out of their problem
# sets a week after seating closed. It is its own setting, and it should track
# the code expiry set by `tools/extend_codes.py` -- there is no point in a
# session that outlives the credential, or a credential nobody can open.
# Claiming still stops dead at the deadline, enforced on its own in
# `past_deadline()`.
SESSION_UNTIL = datetime.fromisoformat(
    os.environ.get("SESSION_UNTIL", "2027-01-01T00:00:00-05:00"))

DEV = os.environ.get("DEV") == "1"          # http instead of https, for local tests
COOKIE = "s416"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30

# The public front door, for anyone who lands on `/` without a code.
FRONT_DOOR = "https://sergio0p.github.io/seating/"

APP_DIR = Path(__file__).resolve().parents[1]   # the seating/ directory

# Static files a signed-in student is allowed to fetch. An allow-list, not a
# directory hand-off: `tools/`, `reference/`, the plans and the room photos live
# in this same directory and none of them belong in front of a student.
STATIC_DIRS = {"assets", "js"}
STATIC_FILES = {"style.css", "index.html"}
DATA_FILES = {"room-layout.json"}

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Secrets and clients, both resolved lazily so tests and --help need neither
# ---------------------------------------------------------------------------

_secret: bytes | None = None
_db = None


def session_secret() -> bytes:
    """The HMAC key for session cookies, from Secret Manager in production."""
    global _secret
    if _secret is None:
        env = os.environ.get("SESSION_SECRET")
        if env:
            _secret = env.encode()
        else:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{PROJECT}/secrets/session-secret/versions/latest"
            _secret = client.access_secret_version(request={"name": name}).payload.data
    return _secret


def db():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client(project=PROJECT)
    return _db


# ---------------------------------------------------------------------------
# The identical 404
# ---------------------------------------------------------------------------

NOT_FOUND_BODY = (
    "<!DOCTYPE html><html lang=en><meta charset=utf-8>"
    "<title>Not Found</title><h1>404</h1><p>Not found.</p>"
)


def not_found() -> Response:
    """Every refusal in this service returns exactly this, byte for byte.

    A bad token, an expired token, a revoked token, a request for `/app` with no
    cookie: all indistinguishable. Anything that varied — a different status, a
    different length, a different message — would be an oracle telling an
    attacker whether a code or a student exists.
    """
    r = make_response(NOT_FOUND_BODY, 404)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r


@app.errorhandler(404)
def handle_404(_e):
    return not_found()


@app.errorhandler(405)
def handle_405(_e):
    return not_found()


@app.after_request
def harden(r: Response) -> Response:
    # The token spends one request in a URL; no referrer means it cannot leak
    # sideways to any other host even during that request.
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/") or request.path in ("/app", "/"):
        r.headers["Cache-Control"] = "no-store"
    return r


# ---------------------------------------------------------------------------
# Sessions: a signed cookie, no server-side session store
# ---------------------------------------------------------------------------

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(pid: str, canvas_id: str, name: str, expires: float) -> str:
    payload = json.dumps(
        {"pid": pid, "cid": canvas_id, "n": name, "exp": expires},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    sig = hmac.new(session_secret(), payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}"


def read_session(cookie: str | None) -> dict | None:
    """Verify and decode a session cookie, or return None. Never raises."""
    if not cookie or "." not in cookie:
        return None
    try:
        raw, sig = cookie.split(".", 1)
        payload = _b64d(raw)
        want = hmac.new(session_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig), want):   # constant time
            return None
        data = json.loads(payload)
    except Exception:
        return None
    if float(data.get("exp", 0)) <= time.time():
        return None
    return data


def current() -> dict | None:
    return read_session(request.cookies.get(COOKIE))


def past_deadline() -> bool:
    return datetime.now(timezone.utc) >= DEADLINE


# ---------------------------------------------------------------------------
# Rate limiting the gate
# ---------------------------------------------------------------------------

# Per-instance and in-memory: it resets on a cold start and is not shared across
# instances. That is fine here — it exists to make grinding slow, and a 128-bit
# token is not guessable anyway. It is not a security boundary.
_misses: dict[str, list[float]] = {}
MISS_LIMIT, MISS_WINDOW = 20, 300.0


def rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _misses.get(ip, []) if now - t < MISS_WINDOW]
    _misses[ip] = hits
    return len(hits) >= MISS_LIMIT


def record_miss(ip: str) -> None:
    _misses.setdefault(ip, []).append(time.time())


def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "?")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

LANDING = """<!DOCTYPE html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>ECON 416 — Seating</title>
<style>body{background:#000;color:#fcfcfc;font:16px/1.6 system-ui,sans-serif;
margin:0;display:grid;place-items:center;min-height:100vh;padding:1.5rem}
main{max-width:32rem}a{color:#7c7cfc}</style>
<main><h1>ECON 416 — Seating</h1>
<p>Seat claiming is open. Your personal link is in your <b>Canvas inbox</b>.
Open it from there — it is unique to you and cannot be typed in here.</p>
<p>Lost it? Email the instructor and it will be re-sent through Canvas.</p>
</main>"""


@app.get("/")
def landing() -> Response:
    return make_response(LANDING, 200)


@app.get("/c/<token>")
def gate(token: str) -> Response:
    """THE GATE. The only place a token is accepted, ever."""
    ip = client_ip()
    if rate_limited(ip):
        return not_found()

    digest = hashlib.sha256(token.encode()).hexdigest()
    try:
        doc = db().collection("codes").document(digest).get()
    except Exception:
        return not_found()

    if not doc.exists:
        record_miss(ip)
        return not_found()

    code = doc.to_dict()
    if code.get("revoked"):
        record_miss(ip)
        return not_found()

    expires = code.get("expiresAt")
    if expires is not None:
        exp_ts = expires.timestamp() if hasattr(expires, "timestamp") else float(expires)
        if time.time() >= exp_ts:
            record_miss(ip)
            return not_found()

    # Valid. Trade the token for a cookie and get it out of the URL.
    try:
        session = make_session(
            pid=str(code["pid"]),
            canvas_id=str(code.get("canvasId", "")),
            name=str(code.get("name", "")),
            expires=min(time.time() + COOKIE_MAX_AGE, SESSION_UNTIL.timestamp()),
        )
    except Exception:
        # Fail closed. A 500 here would be both an outage and an oracle: it
        # distinguishes "something broke while checking your token" from "no
        # such token", which is the exact difference this design refuses to
        # expose. Logged so a real fault is still visible in Cloud Logging.
        app.logger.exception("gate: session issue failed")
        return not_found()
    r = redirect("/app", code=302)
    r.set_cookie(
        COOKIE, session,
        max_age=COOKIE_MAX_AGE,
        httponly=True,            # javascript cannot read it
        secure=not DEV,           # https only in production
        samesite="Lax",
        path="/",
    )
    return r


@app.get("/app")
def app_page() -> Response:
    if not current():
        return not_found()
    return send_from_directory(APP_DIR, "index.html")


# --- static, all behind the cookie ------------------------------------------

@app.get("/<any(assets,js):folder>/<path:filename>")
def static_dir(folder: str, filename: str) -> Response:
    if not current():
        return not_found()
    if ".." in filename:
        return not_found()
    return send_from_directory(APP_DIR / folder, filename)


@app.get("/style.css")
def stylesheet() -> Response:
    if not current():
        return not_found()
    return send_from_directory(APP_DIR, "style.css")


@app.get("/data/<path:filename>")
def data_file(filename: str) -> Response:
    if not current():
        return not_found()
    if filename not in DATA_FILES:      # room-photos and nothing else
        return not_found()
    return send_from_directory(APP_DIR / "data", filename)


# --- API ---------------------------------------------------------------------

@app.get("/api/me")
def api_me() -> Response:
    s = current()
    if not s:
        return not_found()
    claim = db().collection("claims").document(s["pid"]).get()
    return {
        "seatId": claim.to_dict().get("seatId") if claim.exists else None,
        "deadline": DEADLINE.isoformat(),
        "displayName": s.get("n", ""),
        "closed": past_deadline(),
    }


@app.get("/api/seats")
def api_seats() -> Response:
    """The live map. Polled by the app; carries no identifier, only `taken`.

    `mine` is the caller's own seat, folded into the same response rather than
    made a second request: without it a student who moves seats on one device
    leaves the other showing the old one indefinitely, because a client cannot
    tell "still mine" from "someone else took it" out of `taken` alone. It
    names only the reader's own seat, so it discloses nothing about anyone
    else -- the rest of the payload stays free of identifiers.
    """
    s = current()
    if not s:
        return not_found()
    seats = {}
    for d in db().collection("seats").stream():
        v = d.to_dict()
        seats[d.id] = {
            "taken": bool(v.get("taken")),
            "usable": bool(v.get("usable")),
            "reserved": bool(v.get("reserved")),
        }
    claim = db().collection("claims").document(s["pid"]).get()
    mine = claim.to_dict().get("seatId") if claim.exists else None
    return {"seats": seats, "mine": mine}


@app.post("/api/claim")
def api_claim() -> Response:
    s = current()
    if not s:
        return not_found()
    if past_deadline():
        return {"error": "closed"}, 403

    body = request.get_json(silent=True) or {}
    seat_id = body.get("seatId")
    if not isinstance(seat_id, str) or not seat_id:
        return {"error": "bad_request"}, 400

    from google.cloud import firestore
    client = db()

    @firestore.transactional
    def run(tx):
        # Every read must precede every write inside a Firestore transaction.
        seat_ref = client.collection("seats").document(seat_id)
        claim_ref = client.collection("claims").document(s["pid"])

        seat = seat_ref.get(transaction=tx)
        if not seat.exists:
            return "no_such_seat", 404
        seat_d = seat.to_dict()

        claim = claim_ref.get(transaction=tx)
        prior = claim.to_dict().get("seatId") if claim.exists else None

        if prior == seat_id:                     # already yours; nothing to do
            return "ok", 200

        old_ref = None
        if prior:
            old_ref = client.collection("seats").document(prior)
            old_ref.get(transaction=tx)          # read before any write

        if not seat_d.get("usable") or seat_d.get("reserved"):
            return "not_claimable", 409
        if seat_d.get("taken"):
            return "taken", 409

        if old_ref is not None:                  # change of seat frees the old one
            tx.update(old_ref, {"taken": False,
                                "updatedAt": firestore.SERVER_TIMESTAMP})
        tx.update(seat_ref, {"taken": True,
                             "updatedAt": firestore.SERVER_TIMESTAMP})
        tx.set(claim_ref, {
            "seatId": seat_id,
            "canvasId": s.get("cid", ""),
            "claimedAt": firestore.SERVER_TIMESTAMP,
            "source": "student",
        })
        return "ok", 200

    status, code = run(client.transaction())
    if code == 200:
        return {"ok": True, "seatId": seat_id}
    return {"error": status}, code


@app.post("/api/release")
def api_release() -> Response:
    s = current()
    if not s:
        return not_found()
    if past_deadline():
        return {"error": "closed"}, 403

    from google.cloud import firestore
    client = db()

    @firestore.transactional
    def run(tx):
        claim_ref = client.collection("claims").document(s["pid"])
        claim = claim_ref.get(transaction=tx)
        if not claim.exists:
            return "no_claim", 404
        seat_id = claim.to_dict().get("seatId")
        seat_ref = client.collection("seats").document(seat_id)
        seat_ref.get(transaction=tx)
        tx.update(seat_ref, {"taken": False,
                             "updatedAt": firestore.SERVER_TIMESTAMP})
        tx.delete(claim_ref)
        return "ok", 200

    status, code = run(client.transaction())
    return ({"ok": True}, 200) if code == 200 else ({"error": status}, code)


# NOT /healthz: Google Frontend intercepts that exact path on Cloud Run and
# answers it with its own 404 before the request ever reaches this container.
# Verified against the deployed revision -- every other path arrives fine.
@app.get("/health")
def health() -> Response:
    return {"ok": True, "deadline": DEADLINE.isoformat(), "closed": past_deadline()}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
