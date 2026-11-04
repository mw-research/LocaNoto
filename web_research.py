"""Web searches and take-overs that run in the background, with notice.

    start_search(user, query, count)        -> task (search runs on its own)
    start_take_over(user, task_id, picks)   -> task (reads and stores pages)
    tasks(user) / task(user, id, seen=True) / remove(user, id)
    unseen(user)                            -> finished tasks not yet looked at

A search started in the chat or on the web page keeps running when the
user switches pages; its results stay with the user until removed, and a
finished one shows as a notice wherever they are (the pages ask
/ui/notifications every few seconds). Taking pages over into the own
workspace is a task of the same kind, so "is it done?" has an answer.

The task list is a state file per user, encrypted like the chats, so
every server pod sees it. The work runs in the pod that took the
request; a task that was running in a pod that went away counts as
failed after STALE_MINUTES.

Limits, so that many users do not get the search engines to block the
one address they all come from: at most RUNNING_PER_USER tasks per user
at a time and PER_HOUR an hour, at most PARALLEL searches per pod; and
the search service answers the same search from its cache
(WEBSUCHE_CACHE_SEKUNDEN).
"""
import datetime
import json
import os
import threading
import uuid

import dateisperre
import geheim
import paths
import statefiles

COUNT_DEFAULT = paths.env_int("WEB_RESEARCH_HITS", 25)
RUNNING_PER_USER = paths.env_int("WEB_RESEARCH_RUNNING", 2)
PER_HOUR = paths.env_int("WEB_RESEARCH_PER_HOUR", 30)
PARALLEL = paths.env_int("WEB_RESEARCH_PARALLEL", 4)
KEEP = 30
STALE_MINUTES = 10

_slots = threading.BoundedSemaphore(max(1, PARALLEL))


class Refused(Exception):
    """Too many tasks, or a task that does not exist."""


def _path(user):
    folder = os.path.join(paths.CHATS_DIR, user)
    statefiles.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "web_research.json")


def _aad(user):
    return f"web-research:{user}".encode("utf-8")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _load(user):
    path = _path(user)
    if not statefiles.exists(path):
        return []
    try:
        with statefiles.open(path, "rb") as f:
            raw = geheim.entschluessele(f.read(), _aad(user))
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (OSError, ValueError):
        return []


def _save(user, items):
    data = json.dumps(items[:KEEP], ensure_ascii=False).encode("utf-8")
    with statefiles.open(_path(user), "wb") as f:
        f.write(geheim.verschluessele(data, _aad(user)))


def _expire(items):
    limit = _now() - datetime.timedelta(minutes=STALE_MINUTES)
    for t in items:
        if t["state"] == "running" and datetime.datetime.fromisoformat(t["started"]) < limit:
            t.update(state="failed", error="Interrupted (server restarted).",
                     finished=_now().isoformat(), seen=False)
    return items


def _update(user, task_id, **fields):
    with dateisperre.gesperrt(_path(user)):
        items = _load(user)
        for t in items:
            if t["id"] == task_id:
                t.update(fields)
        _save(user, items)


def _new(user, kind, **fields):
    with dateisperre.gesperrt(_path(user)):
        items = _expire(_load(user))
        running = [t for t in items if t["state"] == "running"]
        if len(running) >= RUNNING_PER_USER:
            raise Refused("Too many web tasks at once -- wait until one is finished.")
        hour = _now() - datetime.timedelta(hours=1)
        if sum(1 for t in items if datetime.datetime.fromisoformat(t["started"]) > hour) >= PER_HOUR:
            raise Refused("Too many web tasks this hour -- try again later.")
        task = dict(id=uuid.uuid4().hex[:10], kind=kind, state="running",
                    started=_now().isoformat(), finished=None, seen=False,
                    error="", **fields)
        items.insert(0, task)
        _save(user, items)
    return task


def _run(user, task_id, work):
    def target():
        with _slots:
            try:
                result = work()
            except Exception as e:
                _update(user, task_id, state="failed", error=str(e)[:300],
                        finished=_now().isoformat())
                return
            _update(user, task_id, state="done", finished=_now().isoformat(), **result)
    threading.Thread(target=target, daemon=True, name=f"web-{task_id}").start()


# --- starting ---

def start_search(user, query, count=None, wait=False):
    """Starts a search; returns the task. wait=True runs it here (tests)."""
    import mcp
    import web_sources
    query = " ".join(str(query or "").split())[:200]
    if len(query) < 2:
        raise ValueError("Empty search term.")
    if not mcp.websuche_server():
        raise web_sources.Unavailable("No web search is set up.")
    count = max(1, min(30, int(count or COUNT_DEFAULT)))
    task = _new(user, "search", query=query, count=count, hits=[])

    def work():
        return {"hits": web_sources.search(query, count)}
    if wait:
        _update(user, task["id"], state="done", finished=_now().isoformat(), **work())
        return task_of(user, task["id"])
    _run(user, task["id"], work)
    return task


def start_take_over(user, task_id, picks, wait=False):
    """Takes chosen hits of a finished search into the own workspace."""
    import web_sources
    source = task_of(user, task_id)
    if source["kind"] != "search" or source["state"] != "done":
        raise Refused("Only hits of a finished search can be taken over.")
    hits = source.get("hits") or []
    pages = [dict(hits[i], query=source["query"]) for i in sorted(set(picks))
             if isinstance(i, int) and 0 <= i < len(hits)]
    if not pages:
        raise ValueError("No hits chosen.")
    task = _new(user, "take_over", query=source["query"], source=task_id,
                titles=[p.get("titel") or p.get("adresse") for p in pages], result=[])

    def work():
        result = web_sources.take_over(user, [
            {"title": p.get("titel"), "url": p.get("adresse"), "text": p.get("text"),
             "query": p.get("query")} for p in pages])
        return {"result": result}
    if wait:
        _update(user, task["id"], state="done", finished=_now().isoformat(), **work())
        return task_of(user, task["id"])
    _run(user, task["id"], work)
    return task


# --- reading ---

def tasks(user):
    """All tasks of the user, newest first, without the hits themselves."""
    with dateisperre.gesperrt(_path(user)):
        items = _expire(_load(user))
    return [{k: v for k, v in t.items() if k not in ("hits", "result")}
            | {"hit_count": len(t.get("hits") or []),
               "stored": sum(1 for r in t.get("result") or [] if r.get("passages"))}
            for t in items]


def task_of(user, task_id, seen=False):
    with dateisperre.gesperrt(_path(user)):
        items = _expire(_load(user))
        for t in items:
            if t["id"] == task_id:
                if seen and t["state"] != "running" and not t.get("seen"):
                    t["seen"] = True
                    _save(user, items)
                return t
    raise Refused("Unknown task.")


def unseen(user):
    """Finished tasks the user has not looked at -- for the notice."""
    return [t for t in tasks(user) if t["state"] != "running" and not t.get("seen")]


def mark_seen(user, task_ids=None):
    with dateisperre.gesperrt(_path(user)):
        items = _load(user)
        for t in items:
            if t["state"] != "running" and (task_ids is None or t["id"] in task_ids):
                t["seen"] = True
        _save(user, items)


def remove(user, task_id):
    with dateisperre.gesperrt(_path(user)):
        items = _load(user)
        left = [t for t in items if t["id"] != task_id]
        if len(left) == len(items):
            raise Refused("Unknown task.")
        _save(user, left)


def summary(t):
    """One line for a notice."""
    if t["kind"] == "search":
        if t["state"] == "failed":
            return f"Web search '{t['query']}' failed: {t.get('error')}"
        return f"Web search '{t['query']}': {t.get('hit_count', len(t.get('hits') or []))} hits"
    if t["state"] == "failed":
        return f"Take-over failed: {t.get('error')}"
    return f"Taken over into your workspace: {t.get('stored', 0)} of {len(t.get('titles') or [])} pages"
