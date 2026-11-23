"""Tool servers behind OAuth 2.1 (the MCP authorization standard).

    python tests/test_mcp_oauth.py

Against a stand-in that is both the provider's sign-in and the tool
server (deploy/fake_oauth_mcp.py), through LocaNoto's pages:

  * discovery: the 401 with resource_metadata, the metadata of the
    resource and of the authorization server; the older form without
    metadata; refused when PKCE is missing, the resource names another
    address or an endpoint is not https
  * dynamic registration once, the sign-in with PKCE and resource, the
    way back through the browser (flow cookie, callback, finish)
  * the token only in the sealed session cookie; renewed before it
    expires, with a rotated refresh token; dropped when it cannot be
  * the MCP session (Mcp-Session-Id) and a new one when the server ends it
  * a question: reading tools run, writing ones and those that say
    nothing become drafts; the user's own token arrives
  * the rule for which tools change something

Runs in a temporary folder with files and its own key.
"""
import base64
import json
import os
import sys
import tempfile
import time
import types
from urllib.parse import parse_qs, urlsplit

_KEEP = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
         "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
         "LOCALAPPDATA", "PROGRAMDATA", "LANG", "TZ", "VIRTUAL_ENV",
         "SSL_CERT_FILE"}
for _v in list(os.environ):
    if _v.upper() not in _KEEP and not _v.upper().startswith(("PYTHON", "LC_")):
        del os.environ[_v]
TMP = tempfile.mkdtemp(prefix="mcp_oauth_")
os.environ.update({
    "LOCANOTO_KONFIG": os.path.join(TMP, "config"),
    "LOCANOTO_DATEN": os.path.join(TMP, "data"),
    "LOCANOTO_INDEX": os.path.join(TMP, "index"),
    "LOCANOTO_SCHLUESSEL": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "COOKIE_SECURE": "0", "CHAT_MODEL": "fake", "API_RATE_PER_MINUTE": "100000"})
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "deploy"))

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  {str(detail)[:400]}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def ns(**k):
    return types.SimpleNamespace(**k)


import fake_oauth_mcp  # noqa: E402

srv, fake = fake_oauth_mcp.serve()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
MCP = BASE + "/mcp"

# --- the rule for tools that change something ---

import mcp  # noqa: E402

print("=== which tools change something ===")
for name, ann, writes in (
        ("list_messages", {"readOnlyHint": True}, False),
        ("send_mail", {"readOnlyHint": False}, True),
        ("get_message", None, False), ("mails_lesen", None, False),
        ("searchMessages", None, False), ("getCalendarView", None, False),
        ("delete_message", None, True), ("create_event", None, True),
        ("move_to_folder", None, True), ("dispatch", None, True),
        ("get_and_delete", None, True), ("purge", {"readOnlyHint": True,
                                                    "destructiveHint": True}, True)):
    check(f"{name}: {'draft' if writes else 'runs'}", mcp.schreibt(name, ann) is writes)
check("a data connector's tool runs only when marked read-only",
      mcp.schreibt("list_orders", None, streng=True)
      and not mcp.schreibt("list_orders", {"readOnlyHint": True}, streng=True))

# --- discovery ---

import mcp_oauth  # noqa: E402

print("=== discovery ===")
meta = mcp_oauth.discover(MCP)
check("from the 401 to both metadata documents",
      meta == {"resource": MCP, "authorization_endpoint": BASE + "/authorize",
               "token_endpoint": BASE + "/token",
               "registration_endpoint": BASE + "/register", "scope": "mail.read"}, meta)
check("a scope an admin entered goes first",
      mcp_oauth.discover(MCP, "Mail.Read offline_access")["scope"]
      == "Mail.Read offline_access")


class _Fake:
    def __init__(self, routes, status401=None):
        self.routes, self.status401 = routes, status401

    def get(self, url, **_k):
        data = self.routes.get(url)
        return ns(status_code=200 if data is not None else 404,
                  json=lambda: data, headers={})

    def post(self, url, **_k):
        return ns(status_code=401 if self.status401 is not None else 200,
                  headers={"www-authenticate": self.status401 or ""}, json=lambda: {})


real_http = mcp_oauth._http
o = "https://old.example"
mcp_oauth._http = lambda: _Fake({})
old = mcp_oauth.discover(o + "/mcp")
check("a server without metadata (MCP 2025-03-26): the standard paths at its origin",
      old["authorization_endpoint"] == o + "/authorize"
      and old["token_endpoint"] == o + "/token" and old["resource"] == o + "/mcp", old)
mcp_oauth._http = lambda: _Fake({
    o + "/.well-known/oauth-protected-resource/mcp": {
        "resource": o + "/mcp", "authorization_servers": ["https://login.example/tenant"]},
    "https://login.example/.well-known/openid-configuration/tenant": {
        "authorization_endpoint": "https://login.example/tenant/authorize",
        "token_endpoint": "https://login.example/tenant/token"}})
oidc_style = mcp_oauth.discover(o + "/mcp")
check("an authorization server with a path, found by OpenID discovery",
      oidc_style["token_endpoint"] == "https://login.example/tenant/token"
      and oidc_style["registration_endpoint"] == "", oidc_style)


def refused(routes, url=o + "/mcp"):
    mcp_oauth._http = lambda: _Fake(routes)
    try:
        mcp_oauth.discover(url)
        return ""
    except mcp_oauth.Refused as e:
        return str(e)


prm = {o + "/.well-known/oauth-protected-resource/mcp": {
    "resource": o + "/mcp", "authorization_servers": [o]}}
check("refused: no PKCE",
      "PKCE" in refused(dict(prm, **{o + "/.well-known/oauth-authorization-server": {
          "authorization_endpoint": o + "/a", "token_endpoint": o + "/t",
          "code_challenge_methods_supported": ["plain"]}})))
check("refused: the metadata name another resource",
      "andere Adresse" in refused({o + "/.well-known/oauth-protected-resource/mcp": {
          "resource": "https://other.example/mcp", "authorization_servers": [o]}}))
check("refused: an endpoint over plain http elsewhere",
      "unsicher" in refused(dict(prm, **{o + "/.well-known/oauth-authorization-server": {
          "authorization_endpoint": "http://evil.example/a", "token_endpoint": o + "/t"}})))
check("http only for a server on the same host over http",
      mcp_oauth._allowed("http://127.0.0.1:9/a", "http://127.0.0.1:8/mcp")
      and not mcp_oauth._allowed("http://10.0.0.1/a", "http://127.0.0.1:8/mcp")
      and not mcp_oauth._allowed("http://127.0.0.1/a", "https://127.0.0.1/mcp"))
mcp_oauth._http = real_http

# --- LocaNoto ---

from compare_search import HashEmbedder  # noqa: E402

EMB = HashEmbedder(64)


class FakeChat:
    tool_calls = []

    def __init__(self):
        self.chat = ns(completions=ns(create=self.create))

    def create(self, model=None, messages=None, stream=False, tools=None, **kw):
        if tools and FakeChat.tool_calls:
            calls, FakeChat.tool_calls = FakeChat.tool_calls, []
            return ns(choices=[ns(message=ns(content="", tool_calls=[
                ns(id=f"c{i}", function=ns(name=n, arguments=json.dumps(a)))
                for i, (n, a) in enumerate(calls)]))])
        if stream:
            return iter([ns(choices=[ns(delta=ns(content="Antwort."), finish_reason="stop")])])
        return ns(choices=[ns(message=ns(content="Mails", tool_calls=None))])


import answering  # noqa: E402
import aufnehmen  # noqa: E402
import pipeline  # noqa: E402

aufnehmen.embed_batch = lambda *a, **k: [EMB.vector(t) for t in a[1]]
pipeline.embed_batch = aufnehmen.embed_batch
answering.client = lambda task, user="": FakeChat()
answering._reranker = (None, "fusion")

import benutzer  # noqa: E402
import mailboxes  # noqa: E402
import sessions  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

benutzer.anlege("markus", "Passwort-123456", rolle="admin")
benutzer.anlege("anna", "Passwort-123456")
check("an admin enters the tool server with sign-in at the provider",
      mailboxes.create("graph", "mcp_oauth", MCP, False,
                       postfach="ki-taskforce@example.com")[0])


def client_for(user):
    c = TestClient(server.app)
    r = c.post("/api/v1/auth/login", json={"username": user, "password": "Passwort-123456"})
    assert r.status_code == 200, r.text
    c.headers["X-LocaNoto-CSRF"] = c.cookies.get("locanoto_csrf")
    return c


def sealed_raw(c):
    """The sealed cookie the browser holds now (the newest one set)."""
    values = [k.value for k in c.cookies.jar if k.name == "locanoto_sealed"]
    return values[-1] if values else ""


def put_sealed(c, value):
    """Replace the sealed cookie, as a browser would on Set-Cookie: in the
    domain the server set it for, so the next Set-Cookie replaces it."""
    domain = "testserver.local"
    for k in list(c.cookies.jar):
        if k.name == "locanoto_sealed":
            domain = k.domain or domain
            c.cookies.jar.clear(k.domain, k.path, k.name)
    c.cookies.set("locanoto_sealed", value, domain=domain, path="/")


anna = client_for("anna")
print("=== signing in ===")
page = anna.get("/settings").text
check("the settings offer 'connect with your account'",
      "/ui/settings/mailbox/graph/oauth" in page)
r = anna.get("/ui/settings/mailbox/graph/oauth", follow_redirects=False)
location = r.headers.get("location", "")
q = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
check("start: to the provider with PKCE, state and resource",
      r.status_code == 302 and location.startswith(BASE + "/authorize")
      and q.get("code_challenge_method") == "S256" and q.get("state")
      and q.get("resource") == MCP and q.get("scope") == "mail.read"
      and q.get("redirect_uri") == "http://testserver/ui/mcp-oauth/callback", location)
check("registered once, as a public client",
      ("register", "none") in fake.log and len(fake.clients) == 1)
check("no token in the URL or a cookie the page could read",
      "token" not in location.lower())

import httpx  # noqa: E402

back = httpx.get(location, follow_redirects=False).headers["location"]
check("the provider sends the browser back with a code",
      back.startswith("http://testserver/ui/mcp-oauth/callback?code="), back)
cb = anna.get(urlsplit(back).path + "?" + urlsplit(back).query)
check("callback: a page of our own moves on (same-site for the session cookie)",
      cb.status_code == 200 and "oauth/finish" in cb.text, cb.text[:200])
fin = anna.get("/ui/settings/mailbox/graph/oauth/finish", follow_redirects=False)
check("finish: back to the settings", fin.status_code == 303
      and fin.headers["location"] == "/settings")
sealed = sessions.unseal("anna", sealed_raw(anna))
check("the token is in the sealed session cookie, with what renews it",
      sealed.get("graph", {}).get("Authorization", "").startswith("Bearer ")
      and sealed.get("oauth:graph", {}).get("r"), sorted(sealed))
check("and nowhere on the server",
      not any(sealed["graph"]["Authorization"][7:] in open(os.path.join(dp, f), errors="ignore").read()
              for dp, _d, files in os.walk(TMP) for f in files))
check("the settings show it connected", "connected" in anna.get("/settings").text
      or "verbunden" in anna.get("/settings").text)
again = anna.get(urlsplit(back).path + "?" + urlsplit(back).query)
check("the way back cannot be used twice (the flow is spent)",
      "oauth/finish" not in again.text and "Anmeldung" in again.text, again.text[:200])

# --- a question ---

print("=== a question ===")
FakeChat.tool_calls = [("graph__list_messages", {"userId": "ki-taskforce@example.com"}),
                       ("graph__get_message", {"id": "1"}),
                       ("graph__delete_message", {"id": "1"}),
                       ("graph__send_mail", {"to": "x@example.com", "body": "y"})]
r = anna.post("/api/v1/ask", json={"question": "Was kam heute in die Mails?"})
body = r.json()
calls = [e for e in fake.log if e[0] == "call"]
check("reading tools ran, with the user's own token and an MCP session",
      r.status_code == 200 and ("call", "list_messages", "anna") in calls
      and ("call", "get_message", "anna") in calls
      and not any(e[0] == "no-session" for e in fake.log), (calls, body.get("detail")))
drafts = sorted(d["werkzeug"] for d in body["message"]["entwuerfe"])
kinds = {x["werkzeug"]: x.get("kind") for x in body["message"]["entwuerfe"]}
check("deleting and sending became drafts, nothing of it ran",
      drafts == ["delete_message", "send_mail"] and kinds["delete_message"] == "action"
      and not any(c[1] in ("delete_message", "send_mail") for c in calls), drafts)
check("the model was told which mailbox to name",
      "ki-taskforce@example.com" in json.dumps(body["message"]))  # in the tool call
d = next(x for x in body["message"]["entwuerfe"] if x["werkzeug"] == "delete_message")
r = anna.post(f"/api/v1/chats/{body['chat_id']}/drafts/{d['id']}/send", json={})
check("a draft runs on the user's click", r.status_code == 200
      and ("call", "delete_message", "anna") in fake.log, r.text[:200])

# --- the session ends ---

fake.sessions.clear()
FakeChat.tool_calls = [("graph__list_messages", {"userId": "ki-taskforce@example.com"})]
before = len([e for e in fake.log if e[0] == "call"])
c = mcp.Verbindung("graph", mcp.lies_konfiguration()["graph"], sealed["graph"])
c.werkzeuge()
fake.sessions.clear()
try:
    c.rufe("list_messages", {"userId": "x"})
    renewed_session = True
except mcp.Fehler:
    renewed_session = False
check("a session the server ended is opened again", renewed_session)

# --- renewing ---

print("=== renewing ===")
sealed = sessions.unseal("anna", sealed_raw(anna))
old_access, old_refresh = sealed["graph"]["Authorization"], sealed["oauth:graph"]["r"]
sealed["oauth:graph"]["e"] = int(time.time()) + 10       # about to expire
put_sealed(anna, sessions.seal("anna", sealed))
r = anna.get("/settings")
new = sessions.unseal("anna", sealed_raw(anna))
check("a token about to expire is renewed before the request",
      r.status_code == 200 and new["graph"]["Authorization"] != old_access
      and ("refresh", "anna") in fake.log, sorted(new))
check("with a new refresh token (the old one is spent)",
      new["oauth:graph"]["r"] != old_refresh and old_refresh not in fake.refresh)
FakeChat.tool_calls = [("graph__list_messages", {"userId": "ki-taskforce@example.com"})]
r = anna.post("/api/v1/ask", json={"question": "Und jetzt?"})
check("the renewed token works", r.status_code == 200
      and [e for e in fake.log if e[0] == "call"][-1] == ("call", "list_messages", "anna"))

fake.refuse_refresh = True
new["oauth:graph"]["e"] = int(time.time()) + 10
put_sealed(anna, sessions.seal("anna", new))
anna.get("/settings")
gone = sessions.unseal("anna", sealed_raw(anna))
check("a token that cannot be renewed is dropped: connect again",
      "graph" not in gone and "oauth:graph" not in gone, sorted(gone))
fake.refuse_refresh = False

# --- what else ---

print("=== the rest ===")
anna.post("/ui/settings/mailbox/graph", data={"action": "disconnect"})
left = sessions.unseal("anna", sealed_raw(anna))
check("disconnecting removes both parts", "graph" not in left and "oauth:graph" not in left,
      sorted(left))
import raeume  # noqa: E402
raeume.anlegen("einkauf", "Einkauf", mitglieder=["markus"])
mailboxes.set_access("graph", room="einkauf")
check("a user who may not see the mailbox cannot start a sign-in",
      anna.get("/ui/settings/mailbox/graph/oauth", follow_redirects=False).status_code == 404
      and "/ui/settings/mailbox/graph/oauth" not in anna.get("/settings").text)
mailboxes.set_access("graph")
check("a callback without the flow cookie is refused",
      "Anmeldung" in TestClient(server.app).get(
          "/ui/mcp-oauth/callback?code=x&state=y").text)
check("an API client sends its own token for such a server",
      mcp.kopf_fuer("graph", "", "tok") == {"Authorization": "Bearer tok"})
mailboxes.remove("graph")
check("removing the entry forgets the registration",
      "graph" not in mcp_oauth._clients())

print()
if failures:
    print(f"{len(failures)} failed:")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all passed")
