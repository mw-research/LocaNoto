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
                   "API_RATE_PER_MINUTE": "100000",
                   "OIDC_ISSUER": "https://idp.test",
                   "OIDC_CLIENT_ID": "locanoto",
                   "OIDC_REDIRECT_URI":
                       "http://testserver/api/v1/auth/oidc/callback",
                   "OIDC_ADMIN_GROUPS": "locanoto-admins"})
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

    text_override = None
    # (tool name, arguments): the next call that is offered tools calls
    # this one, once -- the way a model would.
    tool_call = None

    def create(self, model=None, messages=None, stream=False, **kw):
        if kw.get("tools") and _FakeChat.tool_call:
            name, arguments = _FakeChat.tool_call
            _FakeChat.tool_call = None
            call = types.SimpleNamespace(id="call1", function=types.SimpleNamespace(
                name=name, arguments=json.dumps(arguments)))
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", tool_calls=[call]))])
        text = (_FakeChat.text_override
                or "Die Pruefrist betraegt vier Jahre [Kessel.txt, Seite 1].")
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
answering.client = lambda task, user="": _FakeChat()
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


# --- llm.GuardedClient: several endpoints, rate limits ---
import llm  # noqa: E402


class _Limited(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"status {status}")
        self.status_code = status
        self.response = types.SimpleNamespace(
            status_code=status,
            headers={"retry-after": str(retry_after)} if retry_after else {})


def _endpoint(name, script):
    """A fake endpoint that answers from script: "ok" or an exception."""
    log = []

    def create(**kw):
        log.append(kw)
        step = script.pop(0) if script else "ok"
        if step != "ok":
            raise step
        return name
    c = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
        embeddings=types.SimpleNamespace(create=create))
    return c, log


print("=== model access ===")
llm.RATE_MAX_WAIT, llm.COOLDOWN = 3, 30
a, log_a = _endpoint("a", [_Limited(429)])
b, log_b = _endpoint("b", [])
g = llm.GuardedClient("T1", [("a", a), ("b", b)])
check("429 at one endpoint goes to the next",
      g.chat.completions.create(model="m") == "b")
check("the limited endpoint rests",
      g.chat.completions.create(model="m") == "b" and len(log_a) == 1)
c1, log_c = _endpoint("c", [_Limited(429, 0.2), _Limited(429, 0.2)])
g = llm.GuardedClient("T2", [("c", c1)])
check("a single endpoint waits a rate limit out",
      g.embeddings.create(input=["x"], model="m") == "c" and len(log_c) == 3)
d, log_d = _endpoint("d", [_Limited(500)])
g = llm.GuardedClient("T3", [("d", d)])
try:
    g.chat.completions.create(model="m")
    check("a broken single endpoint is not retried", False)
except _Limited:
    check("a broken single endpoint is not retried", len(log_d) == 1)
e, log_e = _endpoint("e", [ValueError("bad request")])
f, log_f = _endpoint("f", [])
g = llm.GuardedClient("T4", [("e", e), ("f", f)])
try:
    g.chat.completions.create(model="m")
    check("a request error is not sent elsewhere", False)
except ValueError:
    check("a request error is not sent elsewhere", not log_f)
h, log_h = _endpoint("h", [_Limited(429, 5)] * 5)
g = llm.GuardedClient("T5", [("h", h)])
llm.RATE_MAX_WAIT = 0.5
try:
    g.chat.completions.create(model="m")
    check("waiting stops at LLM_RATE_MAX_WAIT", False)
except _Limited:
    check("waiting stops at LLM_RATE_MAX_WAIT", llm.STATS["T5"]["rate_limited"] >= 1)
k, log_k = _endpoint("k", [])
g = llm.GuardedClient("T6", [("k", k)])
llm.SEND_USER = "pseudonym"
with llm.acting_for("anna"):
    g.chat.completions.create(model="m")
llm.SEND_USER = "off"
alias = log_k[0].get("user", "")
check("pseudonym instead of the name", alias.startswith("u-")
      and "anna" not in alias and alias == llm.pseudonym("anna"), log_k)
k2, log_k2 = _endpoint("k2", [])
llm.SEND_USER = "pseudonym"
llm.for_user(llm.GuardedClient("T7", [("k2", k2)]), "bert").embeddings.create(
    input=["x"], model="m")
llm.SEND_USER = "off"
check("a client for a user sends his pseudonym",
      log_k2[0].get("user") == llm.pseudonym("bert"), log_k2)
check("several addresses from the settings", llm.endpoints("CHAT") ==
      [(llm.basis_url("CHAT"), llm.api_key("CHAT"))])


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

r = anon.get("/favicon.ico")
check("the browser tab icon", r.status_code == 200 and r.content[:4] == bytes([0, 0, 1, 0]))
_login_page = anon.get("/login").text
check("the logo on the sign-in page and as tab icon",
      "/static/logo.png" in _login_page and "/static/favicon.ico" in _login_page)
check("the logo file is served", anon.get("/static/logo.png").status_code == 200)

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
check("no admin token for someone else (would bypass emergency access)",
      markus.post(f"{API}/admin/tokens", json={"user": "anna"}).status_code == 403)
token = auth.erzeuge("anna", "script")      # as create_token.py does
r = markus.post(f"{API}/admin/tokens", json={"user": "markus", "label": "own"})
check("admin creates an own token", r.json().get("token", "").startswith("lnt_"),
      r.text)
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
_cited = body["message"]["sources"][0]
_page_html = anna.get(f"/c/{chat_id}").text
check("a citation in the answer opens the passage in a tab of its own",
      'class="cite"' in _page_html and 'target="_blank"' in _page_html
      and "/source?room=" in _page_html, _page_html[-800:])
_src = anna.get("/source", params={"room": _cited["raum"], "file": "Kessel.txt",
                                   "page": _cited["page"]})
check("the source page shows the stored passage", _src.status_code == 200
      and "betraegt vier Jahre" in _src.text, _src.text[-500:])
check("not to someone without access to the workspace",
      "betraegt vier Jahre" not in markus.get("/source", params={
          "room": _cited["raum"], "file": "Kessel.txt", "page": _cited["page"]}).text)
_anon_src = TestClient(server.app).get("/source", params={"room": "x", "file": "a b.pdf",
                                                          "page": "2"},
                                       follow_redirects=False)
check("signed out, the source link leads to the sign-in and back to the same passage",
      _anon_src.status_code == 303 and "next=/source%3Froom%3Dx" in _anon_src.headers["location"],
      _anon_src.headers.get("location"))

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
# --- summaries into a workspace (workspace_notes.py) ---
_summary = {"title": "Kessel Pruefung Zusammenfassung",
            "text": "Die Pruefrist fuer Kessel betraegt vier Jahre. "
                    "Naechste Pruefung im Maerz durch den Sachverstaendigen Huber.",
            "source": "dieser Chat"}
_FakeChat.tool_call = ("workspace__save_summary", dict(_summary, room=own))
r = anna.post(f"{API}/ask", json={"question": "Lege bitte eine Zusammenfassung "
                                              "davon in meinem Bereich ab",
                                  "chat_id": chat_id})
_msg = r.json().get("message") or {}
_draft = (_msg.get("entwuerfe") or [{}])[0]
_files = anna.get(f"{API}/documents").json().get(own, {}).get("files", [])
check("a summary becomes a draft and nothing is stored yet",
      _draft.get("server") == "workspace" and _draft.get("ziel")
      and not any("Kessel Pruefung" in f for f in _files), _msg)
check("a question about something else offers no tool round",
      __import__("workspace_notes").offered("Wie lange ist die Pruefrist?", {})
      is False)
r = anna.post(f"{API}/chats/{chat_id}/drafts/{_draft.get('id')}/send", json={})
_files = anna.get(f"{API}/documents").json().get(own, {}).get("files", [])
check("confirming stores it as a document of the room",
      r.status_code == 200 and any(f.startswith("Kessel Pruefung") and f.endswith(".md")
                                   for f in _files), (r.text, _files))
check("a confirmed draft does not run twice", anna.post(
    f"{API}/chats/{chat_id}/drafts/{_draft.get('id')}/send", json={}).status_code == 409)
_FakeChat.text_override = "Sachverstaendiger Huber pruefte im Maerz."
r = anna.post(f"{API}/ask", json={"question": "Wer prueft den Kessel im Maerz?",
                                  "save": False})
_FakeChat.text_override = None
check("the stored summary is found by the search",
      any(s_["file"].startswith("Kessel Pruefung")
          for s_ in r.json()["message"]["sources"]), r.json()["message"]["sources"])
_FakeChat.tool_call = ("workspace__save_summary", dict(_summary, room="allgemein"))
r = anna.post(f"{API}/ask", json={"question": "Speichere das im allgemeinen Bereich",
                                  "chat_id": chat_id})
_d2 = (r.json()["message"].get("entwuerfe") or [{}])[0]
check("confirming into a room without write permission is refused",
      anna.post(f"{API}/chats/{chat_id}/drafts/{_d2.get('id')}/send", json={})
      .status_code == 409)
r = anna.post(f"{API}/workspace-notes", json={"title": "Notiz Kessel",
                                              "text": "Ventil tauschen."})
check("a note through the API lands in the own room",
      r.status_code == 200 and r.json()["room"] == own and r.json()["passages"] > 0,
      r.text)
check("a note into a foreign room is 403", anna.post(
    f"{API}/workspace-notes", json={"room": "allgemein", "title": "x",
                                    "text": "y"}).status_code == 403)
_FakeChat.text_override = None
r = anna.post(f"{API}/chats/{chat_id}/summary", json={})
check("summary of a chat comes back without storing",
      r.status_code == 200 and r.json()["title"] and r.json()["stored"] is None, r.text)
r = anna.post(f"{API}/chats/{chat_id}/summary", json={"room": own,
                                                      "title": "Chat Kessel"})
check("and is stored when a room is given",
      r.status_code == 200 and (r.json()["stored"] or {}).get("passages", 0) > 0, r.text)
check("summary of someone else's chat is 404", markus.post(
    f"{API}/chats/{chat_id}/summary", json={}).status_code == 404)

# Calendar drafts as the tool loop stores them (the Exchange side is
# tested in selbsttest.py): the page shows the line with the day and
# its own button.
import chats as _chats_mod  # noqa: E402
_msgs = _chats_mod.lade("anna", chat_id)
_msgs[-1].setdefault("entwuerfe", []).extend([
    {"id": "dk1", "server": "box", "werkzeug": "meeting_request",
     "vorschau": "Statik Halle 3 | Mi 12.11.2026 14:00-15:00 | an: huber@test.de",
     "argumente": {"subject": "Statik Halle 3"}},
    {"id": "dk2", "server": "box", "werkzeug": "calendar_add",
     "vorschau": "Fokuszeit | Do 13.11.2026 08:00-09:30",
     "argumente": {"subject": "Fokuszeit"}}])
_chats_mod.speichere("anna", chat_id, _msgs)
_page = anna.get(f"/c/{chat_id}").text
_composer = _page[_page.find('<form id="ask"'):][:200]
check("the question form is no ask-again button (a click on Send would ask again)",
      "data-retry=" not in _composer and "data-retry-label=" in _composer, _composer)
check("calendar drafts show the day and their own buttons",
      "Statik Halle 3 | Mi 12.11.2026 14:00-15:00" in _page
      and ("Einladung senden" in _page or "Send invitation" in _page)
      and ("In den Kalender eintragen" in _page or "Add to calendar" in _page),
      _page[-1500:])

# An answer under way shows as such and follows itself; a broken one offers
# "ask again" (answering._Run, chat.js follow).
import time as _time_t  # noqa: E402
_msgs = _chats_mod.lade("anna", chat_id)
_chats_mod.speichere("anna", chat_id, _msgs + [
    {"role": "assistant", "content": "Teil", "unvollstaendig": True, "laeuft": True,
     "status": "Suche", "aktualisiert": _time_t.time(), "run": "r1"}])
_page = anna.get(f"/c/{chat_id}").text
check("an answer under way shows with its text and follows itself",
      'data-running="1"' in _page and "Teil" in _page, _page[-1200:])
_msgs2 = _chats_mod.lade("anna", chat_id)
_msgs2[-1]["aktualisiert"] = _time_t.time() - 3600
_chats_mod.speichere("anna", chat_id, _msgs2)
_page = anna.get(f"/c/{chat_id}").text
check("an answer that stopped long ago offers ask again",
      "data-retry" in _page and 'data-running="1"' not in _page, _page[-1200:])
_chats_mod.speichere("anna", chat_id, _msgs)

# A web search the model proposed waits like a mail, with its exact text.
_msgs = _chats_mod.lade("anna", chat_id)
_msgs[-1]["entwuerfe"].append(
    {"id": "dw1", "server": "websuche", "werkzeug": "web_suchen", "kind": "web",
     "argumente": {"anfrage": "DIN EN 1090 Ausfuehrungsklassen"}})
_chats_mod.speichere("anna", chat_id, _msgs)
_page = anna.get(f"/c/{chat_id}").text
check("a proposed web search shows its text and a confirm button",
      'data-web-draft="dw1"' in _page and "DIN EN 1090 Ausfuehrungsklassen" in _page,
      _page[-1500:])
check("a web search draft is not sent like a mail",
      anna.post(f"{API}/chats/{chat_id}/drafts/dw1/send", json={}).status_code == 409)
# A draft that cannot be sent says why, in the draft -- no error page.
r = anna.post(f"/ui/chats/{chat_id}/drafts/dk2/send")
check("a failed draft shows the reason and can be tried again",
      r.status_code == 200 and ("Nicht gesendet" in r.text or "Not sent" in r.text)
      and ("In den Kalender eintragen" in r.text or "Add to calendar" in r.text), r.text[:500])
r = anna.post(f"/ui/chats/{chat_id}/drafts/dk2/discard")
check("and can be discarded", r.status_code == 200
      and ("Verworfen" in r.text or "Discarded" in r.text), r.text[:300])
check("a discarded draft is not discarded twice",
      anna.post(f"{API}/chats/{chat_id}/drafts/dk2/discard").status_code == 409)

# --- database access in the web pages ---
r = markus.post("/ui/admin/workspaces/sql", data={
    "room": "einkauf", "server": "db.invalid", "port": "1433",
    "database": "DemoERP", "user": "locanoto_lesen", "password": "Lese-Passwort-1",
    "note": "Status O = offen"})
import sqlquellen as _sqlq_t  # noqa: E402
check("admin sets a workspace's database account in the Databases tab",
      r.status_code == 200 and "db.invalid" in markus.get("/admin/databases").text,
      r.text[:300])
r = markus.post("/ui/admin/workspaces/sql", data={
    "room": "allgemein", "server": "db.invalid", "port": "1433", "database": "DemoERP"})
check("a database without a shared account: personal logins",
      r.status_code == 200 and "allgemein" in _sqlq_t.raeume_mit_zugang()
      and not (_sqlq_t.zugang("allgemein") or {}).get("passwort"), r.text[:300])
_set = anna.get("/settings").text
check("members see it under My databases with a login form",
      "/ui/settings/sql/allgemein" in _set, _set[-1500:])
r = anna.post("/ui/settings/sql/allgemein", data={"user": "anna_sql", "secret": "x"})
check("a wrong personal login is refused and not kept",
      r.status_code == 200 and ("fehlgeschlagen" in r.text or "failed" in r.text)
      and "/ui/settings/sql/allgemein" in anna.get("/settings").text, r.text[:300])
check("only readable workspaces", anna.post("/ui/settings/sql/geheimraum",
                                            data={"user": "x", "secret": "y"}).status_code == 404)
markus.post("/ui/admin/workspaces/sql", data={"room": "allgemein"})
check("only admins set database accounts", anna.post("/ui/admin/workspaces/sql", data={
    "room": "einkauf", "user": "x", "password": "y"}).status_code == 403)
_chatpage = anna.get(f"/c/{chat_id}").text
check("the chat offers the database for members of that workspace",
      'name="sql"' in _chatpage, _chatpage[-800:])
r = anna.post(f"{API}/ask", json={"question": "Welche Auftraege sind offen?",
                                  "chat_id": chat_id, "sql": True, "sql_room": "einkauf"})
_sqlmsg = r.json().get("message") or {}
check("the database result is kept with the answer (here: unreachable server)",
      r.status_code == 200 and (_sqlmsg.get("sql") or {}).get("reason"), _sqlmsg.get("sql"))
_msgs = _chats_mod.lade("anna", chat_id)
_msgs[-1]["sql"] = {"query": "SELECT TOP 200 AuftragsNr FROM dbo.Auftraege WHERE Status = 'O'",
                    "rows": 2}
_chats_mod.speichere("anna", chat_id, _msgs)
_page = anna.get(f"/c/{chat_id}").text
check("the page shows the database query under the answer",
      "WHERE Status = &#39;O&#39;" in _page or "WHERE Status = 'O'" in _page, _page[-1200:])
markus.post("/ui/admin/workspaces/sql", data={"room": "einkauf", "user": "", "password": ""})

# --- files created on request (created_files.py), all four kinds ---
_made = {}
for _kind, _args in (
        ("xlsx", {"sheets": [{"name": "Auftraege", "columns": ["Nr", "Wert"],
                              "rows": [["24001", "120,50"]]}]}),
        ("docx", {"text": "# Ergebnis\n- offen: 2"}),
        ("pdf", {"text": "# Ergebnis\n\n| Nr | Wert |\n|---|---|\n| 24001 | 120,50 |"}),
        ("pptx", {"slides": [{"title": "Stand", "bullets": ["zwei offen"]}]})):
    _FakeChat.tool_call = ("files__create_file", dict(_args, kind=_kind, title=f"Demo {_kind}"))
    r = anna.post(f"{API}/ask", json={"question": f"Erstelle eine {_kind}-Datei dazu",
                                      "chat_id": chat_id})
    _made[_kind] = (r.json().get("message") or {}).get("files") or []
check("Excel, Word, PDF and PowerPoint files are created from the chat",
      all(_made[k] == [f"Demo {k}.{k}"] for k in _made), _made)
r = anna.get(f"{API}/files/Demo%20pdf.pdf")
check("a created file downloads with its type",
      r.status_code == 200 and r.content.startswith(b"%PDF")
      and r.headers["content-type"] == "application/pdf", r.status_code)
check("created files are listed", "Demo xlsx.xlsx" in anna.get(f"{API}/files").json())
check("someone else's created file is 404",
      markus.get(f"{API}/files/Demo%20pdf.pdf").status_code == 404)
check("a created file can be deleted",
      anna.delete(f"{API}/files/Demo%20docx.docx").status_code == 200
      and "Demo docx.docx" not in anna.get(f"{API}/files").json())
_page = anna.get(f"/c/{chat_id}").text
check("the answer links the created file", "/api/v1/files/Demo%20xlsx.xlsx" in _page,
      _page[-600:])

# --- shared mailbox that answers on its own, set up in the web page ---
r = markus.post("/ui/admin/mailboxes", data={
    "name": "info", "template": "exchange", "target": "owa.test",
    "mailbox": "info@test.invalid", "auto": "1", "notice": "1",
    "notice_text": "Automatically written."})
_boxes = {b["name"]: b for b in markus.get(f"{API}/mailboxes").json()}
_mbpage = markus.get("/admin/mailboxes").text
check("a shared mailbox may answer on its own, with the notice",
      r.status_code == 200 and _boxes.get("info", {}).get("auto_reply") is True
      and ("answers on its own" in _mbpage or "antwortet selbständig" in _mbpage),
      (r.text[:200], _boxes))
import mcp as _mcp_t  # noqa: E402
check("the notice text is stored with it",
      _mcp_t.lies_konfiguration()["info"].get("hinweis") == "Automatically written."
      and _mcp_t.hinweis_an("info"))

# --- ticket system of the shared mailbox (tickets.py) ---
import datetime as _dt_t  # noqa: E402
import tickets as _tk  # noqa: E402
r = markus.post("/ui/admin/mailboxes/info/tickets", data={
    "enabled": "1", "answer": "Danke, {name}. Nummer {ticket}.", "members": "anna",
    "forward": "", "prefix": "T"})
check("admin switches the ticket system on for a shared mailbox, no login stored",
      r.status_code == 200 and _tk.settings("info")["enabled"]
      and "login" not in _tk._read_config()["info"], r.text[:300])
check("only admins set it up", anna.post("/ui/admin/mailboxes/info/tickets", data={
    "enabled": "1"}).status_code == 403)
check("the admin page shows the ticket settings",
      "/ui/admin/mailboxes/info/tickets" in markus.get("/admin/mailboxes").text)


class _TicketBox:
    def __init__(self):
        self.mails, self.replies = [], []

    def ticket_messages(self, since, limit=50):
        return [m for m in self.mails if m["when"] > since]

    def ticket_reply(self, ref, subject, body):
        self.replies.append((subject, body))

    def ticket_forward(self, *_a):
        pass

    def schliesse(self):
        pass


_tb = _TicketBox()
_tk.poll_once("info", _tb)
_tb.mails.append({"key": "<k1@kunde>", "ref": "R1", "name": "Kunde",
                  "when": _dt_t.datetime.now(_dt_t.timezone.utc) + _dt_t.timedelta(seconds=5),
                  "address": "kunde@firma.invalid", "subject": "Pumpe defekt",
                  "text": "Bitte um Rueckruf.", "auto": False})
_tk.poll_once("info", _tb)
_tid = _tk.tickets_of("info")[0]["id"]
check("a new mail gets the standard answer with its number",
      _tb.replies == [(f"[{_tid}] Pumpe defekt", f"Danke, Kunde. Nummer {_tid}.")], _tb.replies)
n = anna.get("/ui/notifications").json()
check("a new ticket is a notice for the members, counted on the tab",
      any(_tid in x["text"] for x in n["notices"]) and n["tickets"] == 1, n)
anna.post("/ui/notices/shown", data={"id": [x["id"] for x in n["notices"]]})
check("a notice shows once", not anna.get("/ui/notifications").json()["notices"])
_tp = anna.get("/tickets").text
check("members see the tickets and the tab",
      _tid in _tp and "Pumpe defekt" in _tp and 'href="/tickets"' in _tp, _tp[-800:])
# (no further sign-in here: the sign-in limit counts this test's failed ones)
import web as _web_t  # noqa: E402
_bert = types.SimpleNamespace(name="bert", is_admin=False)
check("users without the mailbox do not",
      _tk.boxes_for("bert") == [] and not _web_t._nav(_bert, "chat")["tickets"])
r = anna.post(f"/ui/tickets/info/{_tid}", data={"action": "take"})
check("taking a ticket", r.status_code == 200
      and _tk.ticket("info", _tid)["assignee"] == "anna"
      and _tk.ticket("info", _tid)["status"] == "in_progress")
anna.post(f"/ui/tickets/info/{_tid}", data={"action": "note", "note": "Rueckruf morgen"})
anna.post(f"/ui/tickets/info/{_tid}", data={"action": "status", "status": "closed"})
_one = anna.get("/tickets", params={"box": "info", "id": _tid, "status": "all"}).text
check("a ticket with its history", "Rueckruf morgen" in _one and "Bitte um Rueckruf." in _one,
      _one[:800])
_home = anna.get("/", params={"ticket": f"info:{_tid}"}).text
check("answer in the chat puts the ticket into the question box",
      "Bitte um Rueckruf." in _home and _tid in _home)
check("another user's ticket does not",
      _web_t._prefill(_bert, "", f"info:{_tid}") == "")
r = markus.post("/ui/admin/mailboxes/info/tickets/check")
check("check now without a connected mailbox says so",
      r.status_code == 200 and ("Einstellungen" in r.text or "Settings" in r.text), r.text[:300])
markus.post("/ui/admin/mailboxes/info/delete")

# --- user search instead of one long list ---
_rows = markus.get("/ui/admin/users", params={"q": "ann"}).text
check("the user list filters by name", "anna" in _rows and "markus" not in _rows, _rows[:400])
check("user names are suggested while typing",
      markus.get("/ui/users/suggest", params={"q": "an"}).json()[:1] == ["anna"])
check("only admins search users", anna.get("/ui/users/suggest", params={"q": "a"})
      .status_code == 403)

# --- workspaces and their members in the admin page ---
_adm = markus.get("/admin").text
check("the admin page has a search over workspaces and search choosers",
      'data-filter="#ws-table"' in _adm and "data-chooser" in _adm
      and "/ui/admin/workspaces/einkauf/edit" in _adm, _adm[-1500:])
_ed = markus.get("/ui/admin/workspaces/einkauf/edit").text
check("editing a workspace shows its members, not everybody",
      'name="members" value="anna"' in _ed and 'value="bert"' not in _ed
      and "/ui/users/suggest" in _ed, _ed[:1500])
r = markus.post("/ui/admin/workspaces/einkauf/save", data={
    "label": "Einkauf", "description": "Bestellwesen",
    "members": ["markus", "anna", "bert"]})
check("members are saved from the pick list",
      r.status_code == 200 and set(raeume.liste()["einkauf"]["mitglieder"])
      == {"markus", "anna", "bert"}
      and raeume.liste()["einkauf"].get("beschreibung") == "Bestellwesen", r.text[:300])
_uw = markus.get("/ui/admin/users/bert/workspaces").text
check("a user's workspaces with a search to add more",
      'name="rooms" value="einkauf"' in _uw and "/ui/admin/workspaces/suggest" in _uw, _uw[:1200])
check("workspaces are suggested by a part of the name",
      ["einkauf", "Einkauf"] in markus.get("/ui/admin/workspaces/suggest", params={"q": "kau"}).json())
r = markus.post("/ui/admin/users/bert/workspaces", data={"sent": "1"})
check("unticked: the user leaves the workspace, the others stay",
      r.status_code == 200 and set(raeume.liste()["einkauf"]["mitglieder"])
      == {"markus", "anna"}, raeume.liste()["einkauf"])
check("only admins edit workspaces",
      anna.post("/ui/admin/workspaces/einkauf/save", data={"label": "x"}).status_code == 403)
r = markus.post("/ui/admin/workspaces", data={"id": "pickprobe", "label": "Probe",
                                              "members": ["anna", "bert"]})
check("a new workspace with members ticked",
      r.status_code == 200 and set(raeume.liste().get("pickprobe", {}).get("mitglieder") or [])
      == {"anna", "bert"}, r.text[:300])
markus.post("/ui/admin/workspaces/pickprobe/delete")
check("and removed again", "pickprobe" not in raeume.liste())

# --- web search per workspace ---
markus.post("/ui/admin/workspaces/einkauf/websearch", data={"allow": "1"})
check("an admin allows web search for a workspace in the page",
      raeume.websuche_erlaubt("einkauf"))
markus.post("/ui/admin/workspaces/einkauf/websearch", data={"allow": "0"})
check("and blocks it again", not raeume.websuche_erlaubt("einkauf"))
_ws_real = answering.mcp.websuche_server
answering.mcp.websuche_server = lambda: {"websuche"}
try:
    _set = answering.resolve("anna", answering.Request(question="x", web=True))
    check("with web search over all workspaces, blocked ones are left out",
          "einkauf" in _set["web_excluded"]
          and "einkauf" not in {r_ for r_, _c in _set["pairs"]}, _set["web_excluded"])
    try:
        answering.resolve("anna", answering.Request(question="x", web=True,
                                                    rooms=["einkauf"]))
        check("a blocked workspace chosen on purpose is refused", False)
    except answering.Refused as e:
        check("a blocked workspace chosen on purpose is refused", e.status == 403)
finally:
    answering.mcp.websuche_server = _ws_real

# --- web pages (web.py) ---
_FakeChat.text_override = "Antwort <script>alert(1)</script> **fett**"
r = anna.post(f"{API}/ask", json={"question": "HTML?", "chat_id": chat_id})
_FakeChat.text_override = None
page = anon.get("/", follow_redirects=False)
check("pages without sign-in go to /login",
      page.status_code == 303 and page.headers["location"].startswith("/login"))
check("login page", "data-login" in anon.get("/login").text)
for path in ("/", f"/c/{chat_id}", "/documents", "/web", "/settings"):
    r = anna.get(path)
    check(f"page {path}", r.status_code == 200 and "<main" in r.text
          and "script-src 'self'" in r.headers.get("content-security-policy", ""),
          r.status_code)
check("admin page only for admins",
      anna.get("/admin", follow_redirects=False).status_code == 303
      and markus.get("/admin").status_code == 200)
frag = anna.get(f"/ui/chats/{chat_id}/messages/-1").text
check("model HTML is never HTML", "<script>" not in frag
      and "&lt;script&gt;" in frag and "<strong>fett</strong>" in frag, frag[:300])
check("chat list fragment", chat_id in anna.get("/ui/chats").text)
check("someone else's message fragment is 404",
      markus.get(f"/ui/chats/{chat_id}/messages/0").status_code == 404)
check("feedback form", "Danke" in anna.post("/ui/feedback", data={
    "kind": "daumen_hoch", "question": "HTML?"}).text
      or "Thanks" in anna.post("/ui/feedback", data={
          "kind": "daumen_hoch", "question": "HTML?"}).text)
check("form without CSRF header is refused",
      nocsrf.post("/ui/feedback", data={"kind": "daumen_hoch",
                                        "question": "x"}).status_code == 403)
check("documents fragment", "Kessel.txt" in anna.get("/ui/documents").text)
check("static files", anon.get("/static/hx.js").status_code == 200)
for path in ("/admin/backups", "/admin/emergency", "/admin/content",
             "/admin/feedback", "/admin/storage", "/admin/mailboxes"):
    r = markus.get(path)
    check(f"admin page {path}", r.status_code == 200 and "subnav" in r.text,
          r.status_code)
    check(f"admin page {path} not for users",
          anna.get(path, follow_redirects=False).status_code == 303)
check("admin form refused to a user", anna.post(
    "/ui/admin/glossary", data={"text": "x"}).status_code == 403)
check("glossary form", "Saved" in markus.post(
    "/ui/admin/glossary", data={"text": "PSA = Schutzausruestung"}).text
    or "Gespeichert" in markus.post(
        "/ui/admin/glossary", data={"text": "PSA = Schutzausruestung"}).text)
check("restore needs the typed name", "error" in markus.post(
    "/ui/admin/backups/restore", data={"name": "x", "confirm": "y"}).text)

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
# background web search: start, notice, look at, take over
import time  # noqa: E402
check("a background search without service is 503", anna.post(
    f"{API}/websources/tasks", json={"query": "DIN"}).status_code == 503)
import web_sources as _wsrc
_ws_saved = (_wsrc.search, answering.mcp.websuche_server)
_wsrc.search = lambda q, n: [{"nr": 1, "titel": "Norm", "adresse": "https://example.org/norm",
                              "text": "Ausfuehrungsklassen nach DIN EN 1090. " * 10, "anfrage": q}]
answering.mcp.websuche_server = lambda: {"websuche"}
try:
    r = anna.post("/ui/web/tasks", data={"query": "DIN EN 1090"})
    check("a search starts from the page (or the chat button)",
          r.status_code == 200 and "DIN EN 1090" in r.text, r.text[:300])
    _task_id = anna.get(f"{API}/websources/tasks").json()[0]["id"]
    for _ in range(100):
        if anna.get(f"{API}/websources/tasks").json()[0]["state"] != "running":
            break
        time.sleep(0.05)
    n = anna.get("/ui/notifications").json()
    check("a finished search is a notice with a link to it",
          n["running"] == 0 and n["finished"][0]["id"] == _task_id, n)
    check("not someone else's", markus.get(f"{API}/websources/tasks/{_task_id}").status_code == 404)
    r = anna.get(f"/ui/web/tasks/{_task_id}")
    check("the hits show with a choice", r.status_code == 200 and 'name="pick"' in r.text
          and "example.org/norm" in r.text, r.text[:300])
    check("looked at: no notice any more", not anna.get("/ui/notifications").json()["finished"])
    r = anna.post(f"/ui/web/tasks/{_task_id}/take-over", data={"pick": "0"})
    check("take-over starts in the background", r.status_code == 200, r.text[:300])
    for _ in range(200):
        _all = anna.get(f"{API}/websources/tasks").json()
        if _all[0]["state"] != "running":
            break
        time.sleep(0.05)
    check("and reports what was stored", _all[0]["kind"] == "take_over"
          and _all[0]["state"] == "done" and _all[0]["stored"] == 1, _all[0])
    check("the web page loads the task list", 'hx-get="/ui/web/tasks"' in anna.get("/web").text)
    check("a task can be deleted", anna.delete(f"{API}/websources/tasks/{_task_id}").status_code == 200
          and anna.get(f"{API}/websources/tasks/{_task_id}").status_code == 404)
finally:
    _wsrc.search, answering.mcp.websuche_server = _ws_saved
check("lists", "sheets" in anna.get(f"{API}/lists").json())
check("own list folder not allowed without area", anna.put(
    f"{API}/me/list-folder", json={"path": "/x"}).status_code == 403)

# --- lists from a folder (admin page) ---
_list_dir = os.path.join(TMP, "listen", "einkauf")
os.makedirs(_list_dir, exist_ok=True)
with open(os.path.join(_list_dir, "Lieferanten.csv"), "w", encoding="utf-8") as _f:
    _f.write("Lieferant;Ort;Bewertung\nMueller;Wuerzburg;A\nSchmidt;Schweinfurt;B\n")
check("the lists page is for admins", markus.get("/admin/lists").status_code == 200
      and anna.get("/admin/lists", follow_redirects=False).status_code == 303)
r = markus.post("/ui/admin/lists/folder", data={"room": "einkauf", "path": _list_dir})
check("a list folder is set for a workspace", r.status_code == 200
      and r.headers.get("HX-Redirect") == "/admin/lists", r.text[:300])
_lp = markus.get("/admin/lists").text
check("and its sheets are in the catalog", "Lieferanten.csv" in _lp and _list_dir in _lp,
      _lp[-600:])
check("lists of a workspace only for its members",
      "Lieferanten.csv" in json.dumps(anna.get(f"{API}/lists").json()))
r = markus.post("/ui/admin/lists/folder", data={"room": "einkauf", "path": "relativ/pfad"})
check("a relative folder is refused with a reason", r.status_code == 200
      and "HX-Redirect" not in r.headers and "absolut" in r.text.lower(), r.text[:300])
markus.post("/ui/admin/lists/folder", data={"room": "einkauf", "path": ""})

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
check("the emergency role is not handed out in the app", markus.put(
    f"{API}/admin/users/carl/role", json={"role": "notzugang"}).status_code == 400
    and markus.post(f"{API}/admin/users", json={
        "name": "puppe", "password": "Passwort-123456",
        "role": "notzugang"}).status_code == 400)
check("password", markus.put(f"{API}/admin/users/carl/password", json={
    "password": "Neues-Passwort-1"}).status_code == 200)
carl_token = auth.erzeuge("carl", "script")
check("delete user", markus.delete(f"{API}/admin/users/carl").status_code == 200)
gone = TestClient(server.app)
gone.headers["X-LocaNoto-Token"] = carl_token
check("a deleted user's token no longer works", gone.get(f"{API}/me")
      .status_code == 401)
check("and was revoked", not any(e.get("benutzer") == "carl"
                                 for _k, e in auth.liste()))
check("sign user file", markus.post(f"{API}/admin/users/sign").status_code in (200, 400))
audit = markus.get(f"{API}/admin/audit").json()
check("audit log", len(audit["entries"]) > 0, audit)
check("tokens", len(markus.get(f"{API}/admin/tokens").json()) == 2)
check("revoke own token", anna.delete(f"{API}/me/tokens/{mine[0]['id']}")
      .status_code == 200)
check("revoked token no longer works", tok.get(f"{API}/me").status_code == 401)
check("ambiguous token id is refused", markus.delete(
    f"{API}/admin/tokens/zzzzzzzz").status_code == 404)
check("revoke by admin", markus.delete(
    f"{API}/admin/tokens/{markus.get(f'{API}/admin/tokens').json()[0]['id']}")
    .status_code == 200)
check("preset names cannot leave the folder", markus.delete(
    f"{API}/admin/presets/..").status_code in (404, 405)
    and markus.get(f"{API}/admin/prompts/system_prompt.txt",
                   params={"preset": "../.."}).status_code == 404)
import oidc as _oidc  # noqa: E402
check("no open redirect with control characters",
      _oidc.safe_next("/\t/evil.example") == "/"
      and _oidc.safe_next("/\\evil") == "/" and _oidc.safe_next("/c/x") == "/c/x")

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
import sicherung  # noqa: E402
_backup = sicherung.sichere()
check("backup written", _backup.get("name") and not _backup.get("fehler"),
      _backup)
if database.active():
    check("backup holds the state (users, chats, settings)",
          _backup.get("zustand", 0) > 0, _backup)
r = markus.post(f"{API}/admin/backups/{_backup['name']}/restore",
                json={"overwrite": True, "state": database.active()})
check("restore", r.status_code == 200 and not r.json().get("fehler")
      and (not database.active() or r.json().get("zustand", 0) > 0), r.text)
check("still signed in after restoring the state",
      markus.get(f"{API}/me").status_code == 200)
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
check("logout from another site is refused (CSRF)",
      nocsrf.post(f"{API}/auth/logout").status_code == 403)
check("logout", anna.post(f"{API}/auth/logout").status_code == 200)

# --- sign-in through the directory (OIDC), with a stand-in provider ---
import time as _time  # noqa: E402
from urllib.parse import parse_qs, urlsplit as _split  # noqa: E402

import jwt as _jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa  # noqa: E402

import oidc  # noqa: E402

_idp_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
oidc.discovery = lambda: {"issuer": "https://idp.test",
                          "authorization_endpoint": "https://idp.test/auth",
                          "token_endpoint": "https://idp.test/token",
                          "jwks_uri": "https://idp.test/keys"}
oidc.signing_key = lambda token: _idp_key.public_key()
_next_claims = {}
oidc.exchange = lambda code, verifier: {"id_token": _jwt.encode(
    dict({"iss": "https://idp.test", "aud": "locanoto",
          "iat": int(_time.time()), "exp": int(_time.time()) + 300},
         **_next_claims), _idp_key, algorithm="RS256")}


def directory_sign_in(claims, next_path="/", tamper_state=False):
    c = TestClient(server.app, follow_redirects=False)
    r = c.get(f"{API}/auth/oidc/login", params={"next": next_path})
    q = parse_qs(_split(r.headers["location"]).query)
    _next_claims.clear()
    _next_claims.update(claims, nonce=q["nonce"][0])
    state = "falsch" if tamper_state else q["state"][0]
    return c, c.get(f"{API}/auth/oidc/callback",
                    params={"code": "abc", "state": state})


print("=== directory sign-in ===")
check("methods", anon.get(f"{API}/auth/methods").json() == {
    "password": True, "oidc": True})
r = TestClient(server.app, follow_redirects=False).get(f"{API}/auth/oidc/login")
loc = r.headers.get("location", "")
check("login sends to the directory with PKCE",
      r.status_code == 302 and loc.startswith("https://idp.test/auth?")
      and "code_challenge_method=S256" in loc, loc)
dora, r = directory_sign_in({"sub": "s-dora", "preferred_username":
                             "Dora@firma.de",
                             "groups": ["locanoto-admins", "grp-einkauf"]},
                            next_path="//evil.example/x")
check("callback signs in", r.status_code == 200 and "locanoto_session" in r.cookies,
      r.text)
check("no open redirect", 'url=/"' in r.text, r.text)
dora.headers["X-LocaNoto-CSRF"] = dora.cookies.get("locanoto_csrf")
me_d = dora.get(f"{API}/me").json()
check("account from the directory, role from its groups",
      me_d.get("user") == "dora" and me_d.get("admin")
      and me_d.get("sign_in") == "oidc", me_d)
markus.patch(f"{API}/admin/workspaces/einkauf", json={"group": "grp-einkauf"})
check("workspace membership through a directory group",
      "einkauf" in dora.get(f"{API}/me").json()["readable_rooms"])
check("directory account cannot use a password", anon.post(
    f"{API}/auth/login", json={"username": "dora", "password": "x" * 12})
    .status_code == 401)
_c, r = directory_sign_in({"sub": "s-other", "preferred_username": "dora"})
check("same name, other directory identity is refused", r.status_code == 403,
      r.text)
_c, r = directory_sign_in({"sub": "s-anna", "preferred_username": "anna"})
check("a local account is not taken over", r.status_code == 403, r.text)
_c, r = directory_sign_in({"sub": "s-dora", "preferred_username": "dora"},
                          tamper_state=True)
check("wrong state is refused", r.status_code == 403, r.text)
_c, r = directory_sign_in({"sub": "s-dora", "preferred_username": "dora",
                           "groups": []})
check("role follows the directory (no admin group: user)",
      not _c.get(f"{API}/me").json().get("admin"))
check("and the workspace goes with the group",
      "einkauf" not in _c.get(f"{API}/me").json()["readable_rooms"])

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
