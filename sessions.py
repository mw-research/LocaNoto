"""Sign-in sessions without server state, sealed credentials, rate limits.

SESSIONS. A session is a token signed with the installation key:

    lns1.<payload>.<signature>     payload = user, issued, expires, fingerprint

Any pod checks it without asking anyone -- nothing to share, nothing to
lose on a restart. Three things end a session before it expires:

  * the account is deleted (checked on every request),
  * the password changes or the account switches to another sign-in (the
    fingerprint is taken from the stored password hash and sign-in kind),
  * idle time: a session lives SITZUNG_MINUTEN (default 480) after the
    last renewal; the server renews it on use, at most up to
    SESSION_MAX_HOURS (default 12) after sign-in.

Logging out deletes the cookie. A stolen token stays valid until it
expires or the password changes -- the price of no server state; keep
SITZUNG_MINUTEN short where that matters.

SEALED CREDENTIALS. Mailbox logins must not be stored on the server (only
in volatile memory). With several pods the server cannot keep them in
memory between requests either. So they go back to the browser, sealed
with AES-GCM under the installation key and bound to the user, in a
cookie without expiry date (gone when the browser closes) and without
script access. Only the server can open it, only for this user, only for
SEALED_MINUTES.

RATE LIMITS. failed sign-ins per name (LOGIN_ATTEMPTS) and per address
(LOGIN_ATTEMPTS_PER_ADDRESS), counted in Postgres when DATABASE_URL is set
(so every pod sees them), else in memory. The address is the one the
server sees; behind a proxy run uvicorn with --proxy-headers and
--forwarded-allow-ips=<proxy> so it is the client's. A header the client
sends itself is never trusted.
"""
import base64
import hashlib
import json
import threading
import time

import benutzer
import database
import geheim
import paths

PREFIX = "lns1"
IDLE_MINUTES = paths.env_int("SITZUNG_MINUTEN", 480)
MAX_HOURS = paths.env_int("SESSION_MAX_HOURS", 12)
SEALED_MINUTES = paths.env_int("SEALED_MINUTES", 480)
LOGIN_ATTEMPTS = paths.env_int("LOGIN_ATTEMPTS", 10)
# Per address much higher: a whole office may sit behind one address, and
# a low limit there would let one person lock everyone out.
LOGIN_ATTEMPTS_PER_ADDRESS = paths.env_int("LOGIN_ATTEMPTS_PER_ADDRESS", 100)
LOGIN_WINDOW_MINUTES = paths.env_int("LOGIN_WINDOW_MINUTES", 15)


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def fingerprint(user):
    """Changes when the password or the kind of sign-in changes."""
    e = benutzer.lade()[0].get(user) or {}
    raw = f"{e.get('passwort', '')}|{e.get('anmeldung', 'lokal')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue(user, issued=None, now=None):
    """A fresh session token for user."""
    now = int(now or time.time())
    issued = int(issued or now)
    expires = min(now + IDLE_MINUTES * 60, issued + MAX_HOURS * 3600)
    payload = _b64(json.dumps({"u": user, "i": issued, "e": expires,
                               "f": fingerprint(user)},
                              separators=(",", ":")).encode("utf-8"))
    core = f"{PREFIX}.{payload}"
    signature = geheim.signiere(core.encode("ascii"))
    if not signature:
        raise RuntimeError("No installation key -- sessions need one.")
    return f"{core}.{signature}"


def verify(token, now=None):
    """{"user", "issued", "expires"} or None."""
    try:
        prefix, payload, signature = str(token or "").split(".")
    except ValueError:
        return None
    if prefix != PREFIX:
        return None
    if not geheim.pruefe_signatur(f"{prefix}.{payload}".encode("ascii"),
                                  signature):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    now = now or time.time()
    if now > data.get("e", 0):
        return None
    user = data.get("u", "")
    if not user or not benutzer.eintrag(user):
        return None
    if data.get("f") != fingerprint(user):
        return None
    return {"user": user, "issued": data["i"], "expires": data["e"]}


def renew(session, now=None):
    """A new token when more than a quarter of the idle time has passed."""
    now = now or time.time()
    if session["expires"] - now > IDLE_MINUTES * 60 * 0.75:
        return None
    if now - session["issued"] > MAX_HOURS * 3600:
        return None
    return issue(session["user"], issued=session["issued"], now=now)


# --- SEALED CREDENTIALS ---

def seal(user, data):
    """Encrypt a dict for this user; only this server can open it."""
    body = json.dumps({"u": user, "e": int(time.time() + SEALED_MINUTES * 60),
                       "d": data}).encode("utf-8")
    sealed = geheim.verschluessele(body, zusatz=b"sealed:" + user.encode())
    if sealed == body:
        raise RuntimeError("No installation key -- cannot seal.")
    return _b64(sealed)


def unseal(user, text):
    """The dict sealed for this user, or {} (expired, foreign, damaged)."""
    if not text:
        return {}
    try:
        body = geheim.entschluessele(_unb64(text),
                                     zusatz=b"sealed:" + user.encode())
        data = json.loads(body)
    except Exception:
        return {}
    if data.get("u") != user or time.time() > data.get("e", 0):
        return {}
    return data.get("d") or {}


# --- RATE LIMITS ---

_memory = {}
_memory_lock = threading.Lock()


def _bucket(key, window):
    return f"{key}|{int(time.time() // window)}"


def hit(key, limit, window_seconds):
    """Count one event for key; True while still within the limit."""
    bucket = _bucket(key, window_seconds)
    if database.active():
        row = database.connect().execute(
            "INSERT INTO rate_limit (bucket, hits, expires) VALUES "
            "(%s, 1, now() + make_interval(secs => %s)) "
            "ON CONFLICT (bucket) DO UPDATE SET hits = rate_limit.hits + 1 "
            "RETURNING hits", (bucket, window_seconds * 2)).fetchone()
        if row[0] == 1 and hash(bucket) % 50 == 0:
            database.connect().execute(
                "DELETE FROM rate_limit WHERE expires < now()")
        return row[0] <= limit
    with _memory_lock:
        now = time.time()
        for k in [k for k, (_n, exp) in _memory.items() if exp < now]:
            del _memory[k]
        n, exp = _memory.get(bucket, (0, now + window_seconds * 2))
        _memory[bucket] = (n + 1, exp)
        return n + 1 <= limit


def count(key, window_seconds):
    bucket = _bucket(key, window_seconds)
    if database.active():
        row = database.connect().execute(
            "SELECT hits FROM rate_limit WHERE bucket = %s",
            (bucket,)).fetchone()
        return row[0] if row else 0
    with _memory_lock:
        return _memory.get(bucket, (0, 0))[0]


def _login_limits(name, address):
    return ((f"login:name:{name}", LOGIN_ATTEMPTS),
            (f"login:addr:{address}", LOGIN_ATTEMPTS_PER_ADDRESS))


def login_blocked(name, address):
    """Too many failed sign-ins for this name or from this address?"""
    window = LOGIN_WINDOW_MINUTES * 60
    return any(count(k, window) >= limit
               for k, limit in _login_limits(name, address))


def login_failed(name, address):
    window = LOGIN_WINDOW_MINUTES * 60
    for k, limit in _login_limits(name, address):
        hit(k, limit, window)


def login_attempt(name, address):
    """Count an attempt BEFORE the password is checked. False: over limit.

    Counting afterwards let parallel requests pass the check together.
    A successful sign-in gives its count back (login_succeeded).
    """
    window = LOGIN_WINDOW_MINUTES * 60
    ok = True
    for k, limit in _login_limits(name, address):
        ok = hit(k, limit, window) and ok
    return ok


def login_succeeded(name, address):
    window = LOGIN_WINDOW_MINUTES * 60
    for k, _limit in _login_limits(name, address):
        bucket = _bucket(k, window)
        if database.active():
            database.connect().execute(
                "UPDATE rate_limit SET hits = greatest(hits - 1, 0) "
                "WHERE bucket = %s", (bucket,))
        else:
            with _memory_lock:
                n, exp = _memory.get(bucket, (0, 0))
                if n:
                    _memory[bucket] = (n - 1, exp)
