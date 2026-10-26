"""Exercises every endpoint of server.py against a real installation.

    python test_api.py                                     files, SQLite, Chroma
    SELFTEST_DATABASE=postgresql://.../postgres python test_api.py   Postgres

A temporary installation (own config and data folders, own key), models
replaced by stand-ins: a word-hash embedder (compare_search.HashEmbedder)
and a chat model that answers with a fixed text. Nothing of the
environment it runs in is used -- like selbsttest.py.

At the end every route of the app must have been called at least once;
a new endpoint without a test fails the run.
"""
import base64
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
_KEEP = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
         "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
         "LOCALAPPDATA", "PROGRAMDATA", "LANG", "TZ", "VIRTUAL_ENV",
         "SSL_CERT_FILE", "TESSDATA_PREFIX"}
_SERVER_DB = os.environ.get("SELFTEST_DATABASE", "").strip()
for _v in list(os.environ):
    if _v.upper() not in _KEEP and not _v.upper().startswith(("PYTHON", "LC_")):
        del os.environ[_v]

TMP = tempfile.mkdtemp(prefix="apitest_")
os.environ.update({"LOCANOTO_KONFIG": os.path.join(TMP, "config"),
                   "LOCANOTO_DATEN": os.path.join(TMP, "data"),
                   "COOKIE_SECURE": "0", "CHAT_MODELLE": "fake-a,fake-b",
                   "CHAT_MODEL": "fake-a", "LOGIN_ATTEMPTS": "5",
                   "API_RATE_PER_MINUTE": "100000"})
_db_name = None
if _SERVER_DB:
    import psycopg
    from urllib.parse import urlsplit, urlunsplit
    _db_name = "selftest_" + os.urandom(4).hex()
    with psycopg.connect(_SERVER_DB, autocommit=True) as _a:
        _a.execute(f'CREATE DATABASE "{_db_name}"')
    _u = urlsplit(_SERVER_DB)
    os.environ["DATABASE_URL"] = urlunsplit(
        (_u.scheme, _u.netloc, "/" + _db_name, _u.query, _u.fragment))
    os.environ["DATABASE_DIMENSIONS"] = "64"
sys.path.insert(0, HERE)

from compare_search import HashEmbedder  # noqa: E402

EMB = HashEmbedder(64)


def _fake_embed(*args, **_kw):
    return [EMB.vector(t) for t in args[1]]


class _FakeChat:
    """Stands in for every chat model call."""

    def __init__(self):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create))

    def create(self, model=None, messages=None, stream=False, **kw):
        text = "Die Pruefrist betraegt vier Jahre [Kessel.txt, Seite 1]."
        if stream:
            return iter(types.SimpleNamespace(choices=[types.SimpleNamespace(
                delta=types.SimpleNamespace(content=part))])
                for part in (text[:20], text[20:]))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="Pruefrist Kessel",
                                          tool_calls=None))])


import aufnehmen  # noqa: E402
import answering  # noqa: E402
import pipeline  # noqa: E402

aufnehmen.embed_batch = _fake_embed
pipeline.embed_batch = _fake_embed
answering.client = lambda task: _FakeChat()
answering._reranker = (None, "fusion")

import auth  # noqa: E402
import benutzer  # noqa: E402
import database  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

called = set()


@server.app.middleware("http")
async def _record(request, call_next):
    response = await call_next(request)
    route = request.scope.get("route")
    if route is not None:
        called.add((request.method, route.path))
    return response


failures = []


def check(name, condition, detail=""):
    print(("  OK   " if condition else "  FAIL ") + name
          + ("" if condition else f"  {str(detail)[:300]}"))
    if not condition:
        failures.append(name)


API = "/api/v1"
ok, _ = benutzer.anlege("markus", "Passwort-123456", rolle="admin")
benutzer.anlege("anna", "Passwort-123456")
benutzer.anlege("bert", "Passwort-123456", rolle="notzugang")
import raeume  # noqa: E402
raeume.anlegen("einkauf", "Einkauf", mitglieder=["markus", "anna"])


def client_for(user, password="Passwort-123456"):
    c = TestClient(server.app)
    r = c.post(f"{API}/auth/login", json={"username": user,
                                          "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-LocaNoto-CSRF"] = c.cookies.get("locanoto_csrf")
    return c


print(f"=== store: {'Postgres' if database.active() else 'files'} ===")
anon = TestClient(server.app)
check("health without sign-in", anon.get(f"{API}/health").json()["status"] == "ok")
check("ready", anon.get(f"{API}/ready").status_code == 200)
check("me without sign-in is 401", anon.get(f"{API}/me").status_code == 401)

# --- sign-in ---
check("wrong password is 401", anon.post(f"{API}/auth/login", json={
    "username": "anna", "password": "falsch"}).status_code == 401)
for _ in range(5):
    anon.post(f"{API}/auth/login", json={"username": "bert",
                                         "password": "falsch-falsch"})
check("too many failures block even the right password",
      anon.post(f"{API}/auth/login", json={
          "username": "bert", "password": "Passwort-123456"}).status_code == 429)

anna = client_for("anna")
markus = client_for("markus")
me = anna.get(f"{API}/me").json()
check("me", me["user"] == "anna" and not me["admin"], me)
nocsrf = TestClient(server.app)
nocsrf.cookies.update(anna.cookies)
check("changing request without CSRF header is 403",
      nocsrf.put(f"{API}/me/language", json={"language": "en"}).status_code == 403)
check("language", anna.put(f"{API}/me/language", json={"language": "en"})
      .json()["language"] == "en")

# --- token ---
r = markus.post(f"{API}/admin/tokens", json={"user": "anna", "label": "script"})
token = r.json().get("token", "")
check("admin creates a token", token.startswith("lnt_"), r.text)
tok = TestClient(server.app)
tok.headers["Authorization"] = f"Bearer {token}"
check("bearer token signs in", tok.get(f"{API}/me").json().get("via") == "token")
check("token needs no CSRF", tok.put(f"{API}/me/language",
                                     json={"language": "de"}).status_code == 200)
mine = anna.get(f"{API}/me/tokens").json()
check("own tokens listed", len(mine) == 1, mine)

# --- settings ---
check("instruction", anna.put(f"{API}/me/instruction", json={
    "text": "Antworte knapp."}).status_code == 200
    and anna.get(f"{API}/me/instruction").json()["text"] == "Antworte knapp.")
check("instruction removed",
      anna.delete(f"{API}/me/instruction").status_code == 200)
r = anna.put(f"{API}/me/presets/Kurz", json={"top_k": 3, "chat_modell": "fake-b"})
own_preset = r.json().get("name", "")
check("own preset", r.status_code == 200, r.text)
check("model outside the list refused",
      anna.put(f"{API}/me/presets/X", json={"chat_modell": "gpt-x"}).status_code == 400)
check("presets list", any(pr["name"] == own_preset
                          for pr in anna.get(f"{API}/presets").json()))
check("models", anna.get(f"{API}/models").json()["chat_models"] == ["fake-a", "fake-b"])
check("mailboxes empty", anna.get(f"{API}/mailboxes").json() == [])
check("sql accounts empty", anna.get(f"{API}/me/sql-accounts").json() == [])

# --- documents ---
own = me["own_room"]
r = anna.post(f"{API}/documents", data={"room": own, "project": "Kessel"},
              files={"file": ("Kessel.txt", b"Die Pruefrist fuer Kessel "
                              b"betraegt vier Jahre. " * 20, "text/plain")})
check("upload into own room", r.status_code == 200 and r.json()["passages"] > 0,
      r.text)
check("upload into a foreign room is 403",
      anna.post(f"{API}/documents", data={"room": "allgemein"},
                files={"file": ("x.txt", b"Text " * 50, "text/plain")})
      .status_code == 403)
docs = anna.get(f"{API}/documents").json()
check("document listed", "Kessel.txt" in docs.get(own, {}).get("files", []), docs)
check("projects", "Kessel" in anna.get(f"{API}/documents/projects").json())
check("workspaces", {w["id"] for w in anna.get(f"{API}/workspaces").json()}
      >= {own, "einkauf"})
pdf_estimate = anna.post(f"{API}/documents/image-estimate",
                         files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
check("image estimate rejects a non-PDF", pdf_estimate.status_code == 400)

# --- ask ---
r = anna.post(f"{API}/ask", json={"question": "Wie lange ist die Pruefrist?"})
body = r.json()
check("ask answers", r.status_code == 200 and "vier Jahre" in body.get("answer", ""),
      r.text)
chat_id = body.get("chat_id")
check("answer has the source",
      any(s["file"] == "Kessel.txt" for s in body["message"]["sources"]), body)
r = anna.post(f"{API}/ask?stream=true", json={"question": "Und danach?",
                                              "chat_id": chat_id})
events = [line[7:] for line in r.text.splitlines() if line.startswith("event: ")]
check("stream sends events in order",
      events[:3] == ["chat", "probes", "search"] and events[-1] == "done", events)
import io  # noqa: E402
from PIL import Image as _PILImage  # noqa: E402
_png = io.BytesIO()
_PILImage.new("RGB", (40, 30), (200, 30, 30)).save(_png, "PNG")
img = base64.b64encode(_png.getvalue()).decode()
r = anna.post(f"{API}/ask", json={"question": "Bild?", "chat_id": chat_id,
                                  "images": [{"name": "a.png",
                                              "data_base64": img}]})
check("ask with an image (unreadable image is reported, not fatal)",
      r.status_code == 200, r.text)
check("unknown model refused", anna.post(f"{API}/ask", json={
    "question": "x", "model": "gpt-x"}).status_code == 400)
check("web search without service refused", anna.post(f"{API}/ask", json={
    "question": "x", "web": True}).status_code == 400)
check("stateless ask (save=false)", anna.post(f"{API}/ask", json={
    "question": "Pruefrist?", "save": False, "history": [
        {"role": "user", "content": "Hallo"}]}).json().get("chat_id") is None)

chats = anna.get(f"{API}/chats").json()
check("chat listed", any(c["id"] == chat_id for c in chats), chats)
full = anna.get(f"{API}/chats/{chat_id}").json()
check("chat messages without server paths",
      len(full["messages"]) >= 4 and not any("bilder" in m for m in full["messages"]),
      full)
check("rename chat", anna.put(f"{API}/chats/{chat_id}", json={"title": "Kessel"})
      .json()["title"] == "Kessel")
check("someone else's chat is 404", markus.get(f"{API}/chats/{chat_id}")
      .status_code == 404)
idx = next((i for i, m in enumerate(full["messages"]) if m.get("images")), None)
r = anna.get(f"{API}/chats/{chat_id}/messages/{idx}/images/0")
check("attached image", r.status_code == 200 and len(r.content) > 50,
      r.status_code)
check("missing image is 404", anna.get(
    f"{API}/chats/{chat_id}/messages/0/images/5").status_code == 404)
check("unknown draft is 404", anna.post(
    f"{API}/chats/{chat_id}/drafts/d9_9/send", json={}).status_code == 404)
check("discard unknown draft is 404", anna.post(
    f"{API}/chats/{chat_id}/drafts/d9_9/discard").status_code == 404)
check("feedback", anna.post(f"{API}/feedback", json={
    "kind": "daumen_runter", "question": "Wie lange?"}).status_code == 200)
check("source page of a text file is 404", anna.get(
    f"{API}/sources/page", params={"room": own, "file": "Kessel.txt",
                                   "page": 1}).status_code == 404)

# --- move, delete ---
r = anna.post(f"{API}/documents/move", json={"file": "Kessel.txt",
                                              "from_room": own,
                                              "to_room": "einkauf"})
check("move into a shared room", r.status_code == 200, r.text)
docs = markus.get(f"{API}/documents").json()
check("markus sees it in einkauf",
      "Kessel.txt" in docs.get("einkauf", {}).get("files", []), docs)
r = anna.post(f"{API}/ask", json={"question": "Pruefrist Kessel",
                                  "rooms": ["einkauf"], "save": False})
check("still found after the move (text re-encrypted)",
      any(s["file"] == "Kessel.txt" for s in r.json()["message"]["sources"]),
      r.text)
check("move into a room without write access is 403", anna.post(
    f"{API}/documents/move", json={"file": "Kessel.txt", "from_room": "einkauf",
                                   "to_room": "allgemein"}).status_code == 403)

# --- web, lists ---
check("web search without service is 503", anna.post(
    f"{API}/websources/search", json={"query": "DIN"}).status_code == 503)
check("web read without service is 503", anna.post(
    f"{API}/websources/read", json={"url": "https://example.org"}).status_code == 503)
r = anna.post(f"{API}/websources/take-over", json={"pages": [{
    "title": "Norm", "url": "https://example.org/norm",
    "text": "Ausfuehrungsklassen nach DIN EN 1090. " * 10, "read": True}]})
check("take-over lands in the own room", r.status_code == 200
      and r.json()[0]["passages"] > 0, r.text)
check("lists", "sheets" in anna.get(f"{API}/lists").json())
check("own list folder not allowed without area", anna.put(
    f"{API}/me/list-folder", json={"path": "/x"}).status_code == 403)

# --- mailboxes (admin) ---
check("not admin is 403", anna.get(f"{API}/admin/users").status_code == 403)
check("mailbox templates", "exchange" in markus.get(
    f"{API}/admin/mailboxes/templates").json())
r = markus.post(f"{API}/admin/mailboxes", json={
    "name": "suche", "template": "websuche", "target": "http://127.0.0.1:9"})
check("create web search service", r.status_code == 200, r.text)
check("mailbox overview", anna.get(f"{API}/mailboxes").json()[0]["kind"] == "websearch")
check("login check to an unreachable server fails", anna.post(
    f"{API}/mailboxes/suche/login", json={"secret": "x"}).status_code == 400)
check("logout from a mailbox", anna.delete(f"{API}/mailboxes/suche/login")
      .status_code == 200)
check("tools of an unreachable server fail",
      markus.get(f"{API}/admin/mailboxes/suche/tools").status_code >= 400)
check("remove mailbox", markus.delete(f"{API}/admin/mailboxes/suche")
      .status_code == 200)

# --- admin: users, tokens ---
users = markus.get(f"{API}/admin/users").json()
check("users", {"anna", "markus", "bert"} <= {u["name"] for u in users["users"]})
check("create user", markus.post(f"{API}/admin/users", json={
    "name": "carl", "password": "Passwort-123456"}).status_code == 200)
check("role", markus.put(f"{API}/admin/users/carl/role", json={"role": "admin"})
      .status_code == 200)
check("password", markus.put(f"{API}/admin/users/carl/password", json={
    "password": "Neues-Passwort-1"}).status_code == 200)
check("delete user", markus.delete(f"{API}/admin/users/carl").status_code == 200)
check("sign user file", markus.post(f"{API}/admin/users/sign").status_code in (200, 400))
audit = markus.get(f"{API}/admin/audit").json()
check("audit log", len(audit["entries"]) > 0, audit)
check("tokens", len(markus.get(f"{API}/admin/tokens").json()) == 1)
check("revoke own token", anna.delete(f"{API}/me/tokens/{mine[0]['id']}")
      .status_code == 200)
check("revoked token no longer works", tok.get(f"{API}/me").status_code == 401)
r = markus.post(f"{API}/admin/tokens", json={"user": "anna"})
check("revoke by admin", markus.delete(
    f"{API}/admin/tokens/{markus.get(f'{API}/admin/tokens').json()[0]['id']}")
    .status_code == 200)

# --- admin: workspaces ---
check("create workspace", markus.post(f"{API}/admin/workspaces", json={
    "id": "technik", "label": "Technik", "members": ["anna"]}).status_code == 200)
r = markus.patch(f"{API}/admin/workspaces/technik", json={
    "description": "Anlagen", "web_search": True})
check("change workspace", r.status_code == 200, r.text)
ws = {w["id"]: w for w in markus.get(f"{API}/admin/workspaces").json()}
check("workspace list", ws["technik"]["web_search"] is True, ws.get("technik"))
check("sql account needs user and password", markus.put(
    f"{API}/admin/workspaces/technik/sql-account", json={"benutzer": "x"})
    .status_code == 400)
check("conflicts", markus.get(f"{API}/admin/workspaces/conflicts").status_code == 200)
check("wipe needs the id", markus.post(f"{API}/admin/workspaces/einkauf/wipe",
                                       json={"confirm": "nein"}).status_code == 400)
check("wipe", markus.post(f"{API}/admin/workspaces/technik/wipe",
                          json={"confirm": "technik"}).status_code == 200)
check("remove workspace", markus.delete(f"{API}/admin/workspaces/technik")
      .status_code == 200)

# --- admin: foreign ---
fd = markus.get(f"{API}/admin/foreign-documents").json()
check("foreign documents show ids, not names",
      all("Kessel" not in d["file_id"] for d in fd), fd)
check("foreign rooms", isinstance(markus.get(f"{API}/admin/foreign-rooms").json(), list))
if fd:
    r = markus.post(f"{API}/admin/foreign-documents/delete", json=fd[0])
    check("delete foreign by id", r.status_code == 200, r.text)
else:
    check("delete unknown foreign is 404", markus.post(
        f"{API}/admin/foreign-documents/delete",
        json={"room": "x", "file_id": "y"}).status_code == 404)

# --- admin: storage, backups ---
check("storage not configured", markus.get(f"{API}/admin/storage").json()
      == {"configured": False})
for method, path, payload in (
        ("put", "/admin/storage/mapping", {"mapping": {}}),
        ("post", "/admin/storage/adopt-accounts", {"names": []}),
        ("post", "/admin/storage/setup-rooms", None),
        ("post", "/admin/storage/setup-user/anna", None),
        ("get", "/admin/storage/plan?room=einkauf", None),
        ("post", "/admin/storage/group-sync", None)):
    r = getattr(markus, method)(API + path, **({"json": payload}
                                               if payload is not None else {}))
    check(f"storage {path} is 409 without a store", r.status_code == 409,
          r.status_code)
check("backups", "backups" in markus.get(f"{API}/admin/backups").json())
r = markus.post(f"{API}/admin/backups")
check("start backup", r.status_code == 200, r.text)
check("restore needs overwrite", markus.post(
    f"{API}/admin/backups/x/restore", json={"overwrite": False}).status_code == 400)
check("restore unknown backup fails cleanly", markus.post(
    f"{API}/admin/backups/x/restore", json={"overwrite": True}).status_code < 500)
check("delete unknown backup", markus.delete(f"{API}/admin/backups/x")
      .status_code == 400)

# --- emergency access ---
bert = TestClient(server.app)
os.environ  # (bert was rate limited above; a fresh window is not needed:
#             sign-in counts per name and address, so use a token)
bert.headers["X-LocaNoto-Token"] = auth.erzeuge("bert", "test")
check("emergency overview", "possible" in bert.get(f"{API}/admin/emergency").json())
check("anna may not see it", anna.get(f"{API}/admin/emergency").status_code == 403)
r = markus.post(f"{API}/admin/emergency/requests", json={
    "room": own, "reason": "Vertretung waehrend Urlaub"})
check("admin requests access", r.status_code == 200, r.text)
r = bert.post(f"{API}/admin/emergency/requests/confirm", json={
    "room": own, "requester": "markus"})
check("second person confirms", r.status_code == 200, r.text)
check("now markus reads anna's room", own in markus.get(f"{API}/me").json()
      ["emergency_rooms"])
check("close", bert.post(f"{API}/admin/emergency/close", json={
    "room": own, "requester": "markus"}).status_code == 200)
check("reject unknown request", bert.post(
    f"{API}/admin/emergency/requests/reject", json={
        "room": own, "requester": "markus"}).status_code == 403)

# --- content ---
names = [p["name"] for p in markus.get(f"{API}/admin/prompts").json()]
check("prompts", len(names) > 0, names)
first = names[0]
text = markus.get(f"{API}/admin/prompts/{first}").json()["text"]
check("save prompt", markus.put(f"{API}/admin/prompts/{first}",
                                json={"text": text}).status_code in (200, 400))
check("reset prompt", markus.delete(f"{API}/admin/prompts/{first}")
      .status_code in (200, 404))
check("glossary", markus.put(f"{API}/admin/glossary", json={
    "text": "PSA = Persoenliche Schutzausruestung"}).status_code == 200
    and "PSA" in markus.get(f"{API}/admin/glossary").json()["text"])
r = markus.put(f"{API}/admin/presets/schnell", json={"bezeichnung": "Schnell",
                                                     "top_k": 4})
check("shared preset", r.status_code == 200, r.text)
check("delete shared preset", markus.delete(f"{API}/admin/presets/schnell")
      .status_code == 200)

# --- feedback ---
fb = markus.get(f"{API}/admin/feedback").json()
check("feedback counted", len(fb["thumbs_down"]) >= 1, fb)
check("download feedback", "Wie lange" in markus.get(f"{API}/admin/feedback/download").text)
check("feedback files", markus.get(f"{API}/admin/feedback/files").json()["current"])
check("reencrypt", markus.post(f"{API}/admin/feedback/reencrypt").status_code == 200)
check("archive feedback", markus.post(f"{API}/admin/feedback/archive").status_code == 200)

# --- lists admin ---
check("list sources", "sources" in markus.get(f"{API}/admin/lists/sources").json())
check("put list sources", markus.put(f"{API}/admin/lists/sources",
                                     json={"sources": []}).status_code < 500)
check("rebuild lists", markus.post(f"{API}/admin/lists/rebuild").status_code == 200)
check("header row of an unknown file",
      markus.put(f"{API}/admin/lists/header", json={"file": "x.xlsx", "row": 1})
      .status_code < 500)
check("upload list", markus.post(f"{API}/admin/lists/upload", data={"area": ""},
                                 files={"file": ("a.csv", b"a;b\n1;2\n", "text/csv")})
      .status_code < 500)

# --- jobs, status ---
check("jobs", len(markus.get(f"{API}/admin/jobs").json()) >= 4)
r = markus.post(f"{API}/admin/jobs/text")
check("start job", r.status_code == 200, r.text)
check("job log", markus.get(f"{API}/admin/jobs/text/log").status_code == 200)
check("cancel job", markus.delete(f"{API}/admin/jobs/text").status_code == 200)
st = markus.get(f"{API}/admin/status").json()
check("status", "security" in st and "store" in st, st)

# --- password change ends other sessions ---
old = TestClient(server.app)
old.cookies.update(anna.cookies)
r = anna.put(f"{API}/me/password", json={"current": "Passwort-123456",
                                          "new": "Anderes-Passwort-9"})
check("own password", r.status_code == 200, r.text)
check("old session cookie is void", old.get(f"{API}/me").status_code == 401)
anna.headers["X-LocaNoto-CSRF"] = anna.cookies.get("locanoto_csrf")
check("new cookie works", anna.get(f"{API}/me").status_code == 200)
check("delete own preset", anna.delete(f"{API}/me/presets/{own_preset}")
      .status_code == 200)
check("delete chat", anna.delete(f"{API}/chats/{chat_id}").status_code == 200)
check("delete document", markus.delete(f"{API}/documents", params={
    "room": "einkauf", "file": "Kessel.txt"}).status_code == 200)
check("logout", anna.post(f"{API}/auth/logout").status_code == 200)

# --- every route called? ---
routes = {(m, r.path) for r in server.app.routes
          if hasattr(r, "methods") and r.path.startswith(API)
          for m in r.methods if m not in ("HEAD", "OPTIONS")}
routes -= {("GET", f"{API}/openapi.json"), ("GET", f"{API}/docs"),
           ("GET", f"{API}/docs/oauth2-redirect")}
missing = sorted(routes - called)
check("every endpoint was called", not missing, missing)

if _db_name:
    database.close()
    import psycopg
    with psycopg.connect(_SERVER_DB, autocommit=True) as _a:
        _a.execute(f'DROP DATABASE IF EXISTS "{_db_name}" WITH (FORCE)')
print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
