"""A stand-in for a tool server behind OAuth 2.1 (the MCP authorization
standard), for tests and the demo -- Exchange Online through Microsoft
Graph is the real case it imitates.

    python deploy/fake_oauth_mcp.py [port]       # default 8790

One process plays both parts:

  the authorization server
    GET  /.well-known/oauth-authorization-server   metadata (RFC 8414)
    POST /register                                 dynamic registration (RFC 7591)
    GET  /authorize                                checks client, redirect,
                                                   PKCE S256 and resource; signs
                                                   in the user named by
                                                   ?login_hint (default "anna")
                                                   and sends the browser back
    POST /token                                    authorization_code with
                                                   PKCE; refresh_token, rotated
  the tool server (the resource)
    GET  /.well-known/oauth-protected-resource/mcp metadata (RFC 9728)
    POST /mcp                                      MCP; without a valid token
                                                   401 with WWW-Authenticate;
                                                   a session (Mcp-Session-Id)
                                                   from initialize on

Tools of a mail server: list_messages (marked read-only), get_message (no
annotations), send_mail (marked writing), delete_message (no
annotations). Every answer names the signed-in user, so a test sees whose
token arrived. Access tokens live TOKEN_SECONDS (env FAKE_TOKEN_SECONDS,
default 3600).

Nothing here is secure; it only follows the protocol.
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = {}        # client_id -> redirect_uris
        self.codes = {}          # code -> {client, redirect, challenge, resource, user}
        self.access = {}         # token -> (user, expires)
        self.refresh = {}        # token -> (user, client)
        self.sessions = set()
        self.log = []            # what happened, for tests
        self.token_seconds = int(os.getenv("FAKE_TOKEN_SECONDS", "3600"))
        self.refuse_refresh = False


TOOLS = [
    {"name": "list_messages", "description": "Lists the messages of a mailbox.",
     "inputSchema": {"type": "object", "properties": {"userId": {"type": "string"}},
                     "required": ["userId"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "get_message", "description": "Reads one message.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}},
    {"name": "send_mail", "description": "Sends a mail.",
     "inputSchema": {"type": "object", "properties": {"to": {"type": "string"},
                                                      "body": {"type": "string"}}},
     "annotations": {"readOnlyHint": False}},
    {"name": "delete_message", "description": "Deletes a message.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}},
]


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        @property
        def base(self):
            return f"http://{self.headers.get('Host')}"

        def _send(self, code, data=None, headers=None):
            raw = json.dumps(data).encode() if data is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/.well-known/oauth-protected-resource/mcp":
                return self._send(200, {"resource": self.base + "/mcp",
                                        "authorization_servers": [self.base],
                                        "scopes_supported": ["mail.read"]})
            if u.path == "/.well-known/oauth-authorization-server":
                return self._send(200, {
                    "issuer": self.base,
                    "authorization_endpoint": self.base + "/authorize",
                    "token_endpoint": self.base + "/token",
                    "registration_endpoint": self.base + "/register",
                    "code_challenge_methods_supported": ["S256"]})
            if u.path == "/authorize":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                with state.lock:
                    ok = (q.get("client_id") in state.clients
                          and q.get("redirect_uri") in state.clients[q["client_id"]]
                          and q.get("code_challenge_method") == "S256"
                          and q.get("code_challenge")
                          and q.get("resource") == self.base + "/mcp"
                          and q.get("response_type") == "code")
                    if not ok:
                        state.log.append(("authorize-refused", q))
                        return self._send(400, {"error": "invalid_request"})
                    code = secrets.token_urlsafe(16)
                    state.codes[code] = {"client": q["client_id"],
                                         "redirect": q["redirect_uri"],
                                         "challenge": q["code_challenge"],
                                         "resource": q["resource"],
                                         "user": q.get("login_hint") or "anna"}
                    state.log.append(("authorize", q.get("scope", "")))
                target = q["redirect_uri"] + "?" + urlencode({"code": code,
                                                              "state": q.get("state", "")})
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlsplit(self.path)
            if u.path == "/register":
                data = json.loads(self._body() or b"{}")
                cid = "client-" + secrets.token_hex(4)
                with state.lock:
                    state.clients[cid] = list(data.get("redirect_uris") or [])
                    state.log.append(("register", data.get("token_endpoint_auth_method")))
                return self._send(201, {"client_id": cid,
                                        "redirect_uris": data.get("redirect_uris")})
            if u.path == "/token":
                form = {k: v[0] for k, v in parse_qs(self._body().decode()).items()}
                with state.lock:
                    if form.get("grant_type") == "authorization_code":
                        c = state.codes.pop(form.get("code", ""), None)
                        verifier = form.get("code_verifier", "")
                        challenge = base64.urlsafe_b64encode(
                            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                        if (not c or c["client"] != form.get("client_id")
                                or c["redirect"] != form.get("redirect_uri")
                                or c["challenge"] != challenge):
                            state.log.append(("token-refused", "code"))
                            return self._send(400, {"error": "invalid_grant"})
                        user = c["user"]
                    elif form.get("grant_type") == "refresh_token":
                        r = state.refresh.pop(form.get("refresh_token", ""), None)
                        if not r or state.refuse_refresh or r[1] != form.get("client_id"):
                            state.log.append(("token-refused", "refresh"))
                            return self._send(400, {"error": "invalid_grant"})
                        user = r[0]
                        state.log.append(("refresh", user))
                    else:
                        return self._send(400, {"error": "unsupported_grant_type"})
                    access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
                    state.access[access] = (user, time.time() + state.token_seconds)
                    state.refresh[refresh] = (user, form.get("client_id"))
                return self._send(200, {"access_token": access, "token_type": "Bearer",
                                        "expires_in": state.token_seconds,
                                        "refresh_token": refresh})
            if u.path == "/mcp":
                return self._mcp()
            self._send(404, {"error": "not found"})

        def _mcp(self):
            auth = self.headers.get("Authorization", "")
            token = auth[7:] if auth.lower().startswith("bearer ") else ""
            with state.lock:
                user, until = state.access.get(token, (None, 0))
            if not user or until < time.time():
                return self._send(401, {"error": "unauthorized"}, {
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base}'
                                        f'/.well-known/oauth-protected-resource/mcp"'})
            message = json.loads(self._body() or b"{}")
            method, number = message.get("method"), message.get("id")
            if method == "initialize":
                session = secrets.token_hex(8)
                with state.lock:
                    state.sessions.add(session)
                return self._send(200, {"jsonrpc": "2.0", "id": number, "result": {
                    "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mail", "version": "1"}}},
                    {"Mcp-Session-Id": session})
            session = self.headers.get("Mcp-Session-Id", "")
            with state.lock:
                known = session in state.sessions
            if not known:
                with state.lock:
                    state.log.append(("no-session", method))
                # As the standard says: no session id at all is a bad
                # request, an id the server no longer knows is 404.
                return self._send(404 if session else 400,
                                  {"error": "unknown session" if session
                                   else "missing session"})
            if number is None:
                return self._send(202)
            if method == "tools/list":
                return self._send(200, {"jsonrpc": "2.0", "id": number,
                                        "result": {"tools": TOOLS}})
            if method == "tools/call":
                p = message.get("params") or {}
                with state.lock:
                    state.log.append(("call", p.get("name"), user))
                text = (f"[{user}] {p.get('name')} "
                        f"{json.dumps(p.get('arguments') or {}, ensure_ascii=False)}: "
                        f"Betreff: Angebot Kessel, von: meier@example.com")
                return self._send(200, {"jsonrpc": "2.0", "id": number, "result": {
                    "content": [{"type": "text", "text": text}], "isError": False}})
            return self._send(200, {"jsonrpc": "2.0", "id": number, "result": {}})

    return Handler


def serve(port=0, host="127.0.0.1"):
    """(server, state); the server runs in a thread."""
    state = State()
    srv = ThreadingHTTPServer((host, port), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    srv, _state = serve(port, "0.0.0.0")
    print(f"Fake OAuth MCP server on port {port}: /mcp", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
