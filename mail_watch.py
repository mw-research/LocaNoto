"""New mail in a user's mailboxes, as notices, while LocaNoto is open.

Mailbox logins are never stored on the server (sessions.py): they live
sealed in the browser's cookie. So a mailbox is checked when that
browser asks for notices (/ui/notifications, every 20 seconds) and the
last check is older than MAIL_CHECK_MINUTES. The check runs in a thread;
the page does not wait for Exchange. With every LocaNoto tab closed
nothing is checked -- the shared mailbox of a ticket system is checked
by the worker instead (tickets.py), with a login of its own.

    watching(user, server) / set_watch(user, server, on)   default on
    maybe_check(user, headers)    starts a check if one is due

The first check of a mailbox only notes the time: no notice for the
mail that was there before.
"""
import datetime
import json
import os
import threading
from urllib.parse import quote

import dateisperre
import geheim
import mcp
import notices
import paths
import statefiles

CHECK_MINUTES = paths.env_float("MAIL_CHECK_MINUTES", 5)
SHOW_SUBJECTS = 3

_running = set()
_lock = threading.Lock()


def _path(user):
    folder = os.path.join(paths.CHATS_DIR, user)
    statefiles.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "mail_watch.json")


def _aad(user):
    return f"mail-watch:{user}".encode("utf-8")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _load(user):
    path = _path(user)
    if not statefiles.exists(path):
        return {}
    try:
        with statefiles.open(path, "rb") as f:
            raw = geheim.entschluessele(f.read(), _aad(user))
        state = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(user, state):
    with statefiles.open(_path(user), "wb") as f:
        f.write(geheim.verschluessele(json.dumps(state).encode("utf-8"), _aad(user)))


def mailboxes():
    """The configured mailboxes (not web search services)."""
    return [n for n, a in mcp.lies_konfiguration().items()
            if a.get("art") != "websuche"]


def watching(user, server):
    return bool(_load(user).get("watch", {}).get(server, True))


def set_watch(user, server, on):
    with dateisperre.gesperrt(_path(user)):
        state = _load(user)
        state.setdefault("watch", {})[server] = bool(on)
        _save(user, state)


def maybe_check(user, headers):
    """Starts a check of the user's connected mailboxes if one is due."""
    boxes = set(mailboxes())
    servers = [s for s in (headers or {}) if s in boxes and watching(user, s)]
    if not servers or CHECK_MINUTES <= 0:
        return False
    with dateisperre.gesperrt(_path(user)):
        state = _load(user)
        last = state.get("checked")
        if last and (_now() - datetime.datetime.fromisoformat(last)
                     < datetime.timedelta(minutes=CHECK_MINUTES)):
            return False
        state["checked"] = _now().isoformat()
        _save(user, state)
    with _lock:
        if user in _running:
            return False
        _running.add(user)
    logins = {s: headers[s] for s in servers}
    threading.Thread(target=_check, args=(user, logins), daemon=True,
                     name=f"mail-watch-{user}").start()
    return True


def _check(user, logins):
    try:
        for server, header in logins.items():
            try:
                check_one(user, server, header)
            except Exception:
                pass    # not reachable now: the next check tries again
    finally:
        with _lock:
            _running.discard(user)


def check_one(user, server, header):
    """Looks for mail newer than the last check; a notice if there is some."""
    seen = _load(user).get("seen", {}).get(server)
    connections = mcp.verbinde({server: header},
                               ohne=set(mcp.lies_konfiguration()) - {server})
    conn = connections.get(server)
    if conn is None or not hasattr(conn, "new_messages"):
        return 0
    try:
        if not seen:
            _set_seen(user, server, _now())
            return 0
        since = datetime.datetime.fromisoformat(seen)
        found = conn.new_messages(since)
    finally:
        conn.schliesse()
    if not found:
        return 0
    newest = max((w for w, _s, _t in found if w is not None), default=_now())
    _set_seen(user, server, newest)
    notices.add(user, notice_text(user, server, found),
                href=f"/?mail={quote(server)}", key=f"mail:{server}")
    return len(found)


def _set_seen(user, server, when):
    with dateisperre.gesperrt(_path(user)):
        state = _load(user)
        state.setdefault("seen", {})[server] = when.astimezone(
            datetime.timezone.utc).isoformat()
        _save(user, state)


def notice_text(user, server, found):
    import sprache
    en = sprache.gewaehlt(user) == "en"
    n = len(found)
    if en:
        head = f"{server}: {n} new message{'s' if n != 1 else ''}"
    else:
        head = f"{server}: {n} neue Nachricht{'en' if n != 1 else ''}"
    parts = []
    for _w, sender, subject in found[:SHOW_SUBJECTS]:
        name = sender.split("<")[0].strip() or sender
        parts.append(f"{name}: {subject or '-'}")
    more = " …" if n > SHOW_SUBJECTS else ""
    return head + " – " + "; ".join(parts) + more


def question_for(user, server):
    """The question a click on a mail notice puts into the chat box."""
    import sprache
    if sprache.gewaehlt(user) == "en":
        return f"What is new in the mailbox {server}? Summarise the new messages."
    return f"Was ist neu im Postfach {server}? Fasse die neuen Nachrichten zusammen."
