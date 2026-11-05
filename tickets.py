"""A ticket system for shared mailboxes (info@, service@, ...).

An admin switches it on for a shared mailbox (Admin > Mailboxes) and sets

  * a login for the mailbox. The worker has no user session to take one
    from, so this one is stored -- encrypted with the installation key,
    like the database accounts (sqlquellen.py). Without that key nothing
    is stored. Use an account that may read and send for this mailbox
    and nothing else.
  * the standard answer, sent at once to every new mail. {ticket},
    {subject} and {name} are filled in.
  * members: LocaNoto users who get every ticket (a notice, and the
    Tickets page)
  * forward to: mail addresses that get every new mail, with the ticket
    number in the subject

The worker runs poll_all() every TICKET_POLL_SECONDS (worker.py). A new
mail becomes ticket T-2026-0001: the sender gets the standard answer with
the number in the subject, the forward addresses get the mail, the
members a notice. A mail whose subject carries a known number of this
mailbox is added to that ticket (and reopens it) -- no second standard
answer. Machine-made mail (auto replies, mailing lists, bounces, the
mailbox itself) never gets one: two auto-responders would answer each
other without end. It is not made a ticket either.

At most once: a mail is marked as handled before anything is sent, so a
crash in between costs a standard answer, never a second one.

The very first run only notes the time; mail that was there before does
not become tickets.

    settings(server) / configure(server, ...) / poll_once(server) / poll_all()
    boxes_for(user, is_admin) / tickets_of(server) / ticket(server, id)
    update(server, id, by, assignee=None, status=None, note=None)
"""
import base64
import datetime
import json
import os
import re

import dateisperre
import geheim
import mcp
import notices
import paths
import statefiles

CONFIG = os.path.join(paths.CONFIG_DIR, "tickets.json")
STATE_DIR = os.path.join(paths.DATA_DIR, "tickets")
POLL_SECONDS = paths.env_float("TICKET_POLL_SECONDS", 60)
KEEP_CLOSED_DAYS = paths.env_int("TICKET_KEEP_DAYS", 365)
TEXT_LIMIT = 20000
SEEN_LIMIT = 5000
# Read again from a little before the last mail: mail arrives with the
# time it was received, and a slow server may file it late.
OVERLAP = datetime.timedelta(minutes=10)

STATUSES = ("open", "in_progress", "closed")

DEFAULT_ANSWER = (
    "Guten Tag {name},\n\n"
    "vielen Dank für Ihre Nachricht. Wir haben sie unter der Nummer {ticket} "
    "erfasst und melden uns so bald wie möglich.\n\n"
    "Bitte lassen Sie die Nummer im Betreff stehen, wenn Sie antworten.\n\n"
    "Mit freundlichen Grüßen")


class Refused(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# --- SETTINGS ---

def _read_config():
    try:
        with statefiles.open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_config(data):
    statefiles.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    dateisperre.schreibe_atomar(CONFIG, json.dumps(data, ensure_ascii=False, indent=1))


def settings(server):
    """The ticket settings of a mailbox, without the password."""
    c = dict(_read_config().get(server) or {})
    has_login = bool(c.pop("login", None))
    c.setdefault("enabled", False)
    c.setdefault("answer", DEFAULT_ANSWER)
    c.setdefault("members", [])
    c.setdefault("forward", [])
    c.setdefault("prefix", "T")
    c["has_login"] = has_login
    return c


def _aad(server):
    return f"tickets-login:{server}".encode("utf-8")


def configure(server, enabled, answer="", members=(), forward=(), prefix="T",
              login_user="", login_password=""):
    """Sets the ticket settings of a mailbox. (ok, message)."""
    entry = mcp.lies_konfiguration().get(server)
    if not entry or entry.get("art") == "websuche":
        return False, "Unknown mailbox."
    if entry.get("persoenlich"):
        return False, "Tickets only for shared mailboxes."
    prefix = re.sub(r"[^A-Za-z]", "", prefix or "T")[:6].upper() or "T"
    bad = [a for a in forward if not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", a)]
    if bad:
        return False, "Not a mail address: " + ", ".join(bad)
    with dateisperre.gesperrt(CONFIG):
        data = _read_config()
        old = data.get(server) or {}
        new = {"enabled": bool(enabled), "answer": str(answer or "").strip(),
               "members": sorted({m.strip() for m in members if m.strip()}),
               "forward": list(dict.fromkeys(a.strip() for a in forward if a.strip())),
               "prefix": prefix}
        if login_user or login_password:
            if not (login_user and login_password):
                return False, "User AND password for the mailbox."
            if not geheim.verfuegbar():
                return False, "Without the installation key no password is stored."
            blob = geheim.verschluessele(
                json.dumps([login_user, login_password]).encode("utf-8"), _aad(server))
            new["login"] = base64.b64encode(blob).decode("ascii")
        elif old.get("login"):
            new["login"] = old["login"]
        if new["enabled"] and not new.get("login"):
            return False, "A login for the mailbox is needed."
        data[server] = new
        _write_config(data)
    return True, "Saved."


def _login(server):
    blob = (_read_config().get(server) or {}).get("login")
    if not blob:
        raise Refused("No login stored for this mailbox.")
    raw = geheim.entschluessele(base64.b64decode(blob), _aad(server))
    user, password = json.loads(raw.decode("utf-8"))
    return user, password


def enabled_boxes():
    boxes = mcp.lies_konfiguration()
    return [s for s, c in _read_config().items()
            if c.get("enabled") and s in boxes]


def boxes_for(user, is_admin=False):
    """Mailboxes with tickets this user sees: members, and admins all."""
    return [s for s in enabled_boxes()
            if is_admin or user in (_read_config()[s].get("members") or [])]


# --- STATE ---

def _state_path(server):
    statefiles.makedirs(STATE_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", server)
    return os.path.join(STATE_DIR, f"{safe}.json")


def _state_aad(server):
    return f"tickets:{server}".encode("utf-8")


def _load(server):
    path = _state_path(server)
    if not statefiles.exists(path):
        return {"tickets": [], "seen": [], "since": None, "counter": {}}
    with statefiles.open(path, "rb") as f:
        raw = geheim.entschluessele(f.read(), _state_aad(server))
    state = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    for k, v in (("tickets", []), ("seen", []), ("since", None), ("counter", {})):
        state.setdefault(k, v)
    return state


def _save(server, state):
    limit = _now() - datetime.timedelta(days=KEEP_CLOSED_DAYS)
    state["tickets"] = [t for t in state["tickets"]
                        if t.get("status") != "closed"
                        or datetime.datetime.fromisoformat(t.get("changed") or t["created"]) > limit]
    state["seen"] = state["seen"][-SEEN_LIMIT:]
    data = json.dumps(state, ensure_ascii=False).encode("utf-8")
    with statefiles.open(_state_path(server), "wb") as f:
        f.write(geheim.verschluessele(data, _state_aad(server)))


def tickets_of(server):
    """The tickets of a mailbox, newest first, without the long text."""
    out = []
    for t in reversed(_load(server)["tickets"]):
        out.append({k: v for k, v in t.items() if k not in ("text", "events")}
                   | {"events": len(t.get("events") or [])})
    return out


def ticket(server, ticket_id):
    for t in _load(server)["tickets"]:
        if t["id"] == ticket_id:
            return t
    return None


def update(server, ticket_id, by, assignee=None, status=None, note=None):
    """Assign, set the status or add a note. Returns the ticket."""
    if status is not None and status not in STATUSES:
        raise Refused("Unknown status.")
    with dateisperre.gesperrt(_state_path(server)):
        state = _load(server)
        t = next((x for x in state["tickets"] if x["id"] == ticket_id), None)
        if t is None:
            raise Refused("Unknown ticket.")
        if assignee is not None and assignee != t.get("assignee"):
            t["assignee"] = assignee or None
            _event(t, "assigned", by, assignee or "-")
            if assignee and t["status"] == "open":
                t["status"] = "in_progress"
        if status is not None and status != t["status"]:
            t["status"] = status
            _event(t, "status", by, status)
        if note:
            _event(t, "note", by, str(note)[:4000])
        t["changed"] = _now().isoformat()
        _save(server, state)
    if assignee and assignee != by:
        notices.add(assignee, f"{t['id']}: {t['subject'] or '-'} – {by}",
                    href=_href(server, t["id"]))
    return t


def _event(t, what, by, text=""):
    t.setdefault("events", []).append(
        {"at": _now().isoformat(), "what": what, "by": by, "text": text})


def _href(server, ticket_id):
    return f"/tickets?box={server}&id={ticket_id}"


# --- POLLING ---

def _connect(server):
    user, password = _login(server)
    header = mcp.kopf_fuer(server, user, password)
    connections = mcp.verbinde({server: header},
                               ohne=set(mcp.lies_konfiguration()) - {server})
    conn = connections.get(server)
    if conn is None or not hasattr(conn, "ticket_messages"):
        raise Refused("This mailbox kind has no ticket support.")
    return conn


def poll_all(log=None):
    """One round over every mailbox with tickets. {server: count or error}."""
    out = {}
    for server in enabled_boxes():
        try:
            out[server] = poll_once(server)
        except Exception as e:
            out[server] = f"{type(e).__name__}: {e}"
            if log:
                log(f"tickets {server}: {out[server]}")
    return out


def poll_once(server, conn=None):
    """Turns new mail of one mailbox into tickets. Returns how many mails."""
    cfg = _read_config().get(server) or {}
    if not cfg.get("enabled"):
        return 0
    own = conn is None
    with dateisperre.gesperrt(_state_path(server)):
        state = _load(server)
        if not state["since"]:
            state["since"] = _now().isoformat()
            _save(server, state)
            return 0
        since = datetime.datetime.fromisoformat(state["since"]) - OVERLAP
        conn = conn or _connect(server)
        try:
            handled = 0
            seen = set(state["seen"])
            for m in conn.ticket_messages(since):
                key = str(m["key"])
                if key in seen:
                    continue
                # handled before anything goes out: at most once
                state["seen"].append(key)
                seen.add(key)
                when = m.get("when")
                if when is not None and hasattr(when, "astimezone"):
                    w = when.astimezone(datetime.timezone.utc)
                    if w > datetime.datetime.fromisoformat(state["since"]):
                        state["since"] = w.isoformat()
                _save(server, state)
                if _handle(server, cfg, state, conn, m):
                    handled += 1
                _save(server, state)
            return handled
        finally:
            if own:
                conn.schliesse()


def _number(cfg, state):
    year = str(_now().year)
    n = int(state["counter"].get(year, 0)) + 1
    state["counter"][year] = n
    return f"{cfg.get('prefix') or 'T'}-{year}-{n:04d}"


def _known(cfg, state, subject):
    prefix = re.escape(cfg.get("prefix") or "T")
    for found in re.findall(rf"\[({prefix}-\d{{4}}-\d{{4,}})\]", subject or ""):
        t = next((x for x in state["tickets"] if x["id"] == found), None)
        if t is not None:
            return t
    return None


def _fill(template, **values):
    out = str(template or "")
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _handle(server, cfg, state, conn, m):
    """One new mail: a reply to a ticket, a new ticket, or nothing."""
    sender = f"{m['name']} <{m['address']}>" if m.get("name") else (m.get("address") or "?")
    members = list(cfg.get("members") or [])
    if m.get("auto"):
        # also an out-of-office answer to the standard answer, which
        # carries the ticket number: it neither reopens nor notifies
        return False
    existing = _known(cfg, state, m.get("subject"))
    if existing is not None:
        _event(existing, "mail", sender, (m.get("text") or "")[:TEXT_LIMIT])
        if existing["status"] == "closed":
            existing["status"] = "open"
        existing["changed"] = _now().isoformat()
        for user in ([existing["assignee"]] if existing.get("assignee") else members):
            notices.add(user, f"{existing['id']}: {_reply_word(user)} – {sender}",
                        href=_href(server, existing["id"]))
        return True
    tid = _number(cfg, state)
    t = {"id": tid, "mailbox": server, "created": _now().isoformat(),
         "changed": _now().isoformat(),
         "received": (m["when"].isoformat() if hasattr(m.get("when"), "isoformat") else None),
         "from_name": m.get("name") or "", "from_address": m.get("address") or "",
         "subject": m.get("subject") or "", "text": (m.get("text") or "")[:TEXT_LIMIT],
         "status": "open", "assignee": None, "events": []}
    _event(t, "received", sender)
    state["tickets"].append(t)
    _save(server, state)

    subject = m.get("subject") or ""
    answer = cfg.get("answer") or ""
    if answer.strip():
        try:
            conn.ticket_reply(m["ref"], f"[{tid}] {subject}".strip(),
                              _fill(answer, ticket=tid, subject=subject,
                                    name=m.get("name") or ""))
            _event(t, "answered", "LocaNoto")
        except Exception as e:
            _event(t, "answer_failed", "LocaNoto", str(e)[:300])
    forward = list(cfg.get("forward") or [])
    if forward:
        try:
            conn.ticket_forward(m["ref"], forward, f"[{tid}] {subject}".strip(),
                                f"Ticket {tid} – {sender}")
            _event(t, "forwarded", "LocaNoto", ", ".join(forward))
        except Exception as e:
            _event(t, "forward_failed", "LocaNoto", str(e)[:300])
    for user in members:
        notices.add(user, f"{server}: {_new_word(user)} {tid} – {subject or '-'} ({sender})",
                    href=_href(server, tid))
    return True


def _lang(user):
    try:
        import sprache
        return sprache.gewaehlt(user)
    except Exception:
        return "de"


def _new_word(user):
    return "new ticket" if _lang(user) == "en" else "neues Ticket"


def _reply_word(user):
    return "new reply" if _lang(user) == "en" else "neue Antwort"
