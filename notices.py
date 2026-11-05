"""Notices for one user: new mail, new tickets, replies to tickets.

    add(user, text, href="", key=None)   one notice; with key, a newer one
                                         replaces an unshown one of that key
    pending(user)                        not yet shown, oldest first
    mark_shown(user, ids)

The pages ask /ui/notifications every few seconds and show each pending
notice once (web_static/hx.js), then mark it shown. A notice holds a
short text and a link inside LocaNoto -- never a mail body.

Stored per user and encrypted like the chats (CHATS_DIR/<user>/notices.json),
so every server pod sees the same list.
"""
import datetime
import json
import os
import uuid

import dateisperre
import geheim
import paths
import statefiles

KEEP = 50


def _path(user):
    folder = os.path.join(paths.CHATS_DIR, user)
    statefiles.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "notices.json")


def _aad(user):
    return f"notices:{user}".encode("utf-8")


def _load(user):
    path = _path(user)
    if not statefiles.exists(path):
        return []
    try:
        with statefiles.open(path, "rb") as f:
            raw = geheim.entschluessele(f.read(), _aad(user))
        items = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(user, items):
    data = json.dumps(items[-KEEP:], ensure_ascii=False).encode("utf-8")
    with statefiles.open(_path(user), "wb") as f:
        f.write(geheim.verschluessele(data, _aad(user)))


def add(user, text, href="", key=None):
    """Adds a notice for user. Returns its id."""
    item = {"id": uuid.uuid4().hex[:12], "text": str(text)[:400],
            "href": str(href or ""), "key": key, "shown": False,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with dateisperre.gesperrt(_path(user)):
        items = _load(user)
        if key:
            items = [n for n in items if n.get("shown") or n.get("key") != key]
        items.append(item)
        _save(user, items)
    return item["id"]


def pending(user):
    return [{k: n[k] for k in ("id", "text", "href")}
            for n in _load(user) if not n.get("shown")]


def mark_shown(user, ids):
    ids = set(ids or [])
    if not ids:
        return
    with dateisperre.gesperrt(_path(user)):
        items = _load(user)
        for n in items:
            if n["id"] in ids:
                n["shown"] = True
        _save(user, items)
