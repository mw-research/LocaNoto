"""The LocaNoto server: every function as an HTTP API under /api/v1.

    uvicorn server:app --host 0.0.0.0 --port 8700

Everything the Streamlit pages can do is reachable here, for users and
admins: asking (also streamed), chats, documents, workspaces, web sources,
mailboxes and drafts, the SQL source, lists, settings, and the whole admin
area. The interactive reference is at /api/v1/docs.

SIGN-IN, three ways, all ending in the same user name and the same
permission checks:

  * API token  -- header X-LocaNoto-Token: lnt_... or
                  Authorization: Bearer lnt_...  (scripts, integrations)
  * session    -- POST /api/v1/auth/login sets the cookie locanoto_session
                  (browsers). Changing requests then need the header
                  X-LocaNoto-CSRF with the value of the cookie locanoto_csrf.
  * OIDC       -- /api/v1/auth/oidc/login (Entra ID, Keycloak, ...), see
                  oidc.py; ends in a session as above.

What a user may do is read on every request from the signed user file,
never from the token: a token says who, the user file says what.

STATELESS. No request depends on the pod that served the previous one:
sessions are signed tokens, mailbox logins are sealed in a cookie,
everything else is in Postgres (DATABASE_URL). Run as many replicas as
needed behind a load balancer.

The old API (api.py, German paths) keeps working next to this one.
"""
import os
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

import auth
import benutzer
import budget
import database
import geheim
import paths
import sessions

API_PREFIX = "/api/v1"
ROOT_PATH = os.getenv("API_WURZELPFAD", "").strip().rstrip("/")
RATE_PER_MINUTE = paths.env_int("API_RATE_PER_MINUTE", 240)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1").strip() != "0"
SESSION_COOKIE = "locanoto_session"
CSRF_COOKIE = "locanoto_csrf"
SEALED_COOKIE = "locanoto_sealed"

paths.bootstrap()
_key_state, _key_message = geheim.zustand()
if _key_state == "unlesbar":
    raise SystemExit("Installation key not readable: " + _key_message)

app = FastAPI(
    title="LocaNoto API",
    version="1.0",
    description=__doc__,
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=None,
    openapi_url=f"{API_PREFIX}/openapi.json",
    root_path=ROOT_PATH,
)


# --- WHO IS ASKING ---

class Principal:
    """The signed-in user of a request."""

    def __init__(self, name, via):
        self.name = name
        self.via = via                       # "token" | "session"
        self.is_admin = benutzer.ist_admin(name)
        self.is_emergency = benutzer.hat_rolle(name, "notzugang")

    def require_admin(self):
        if not self.is_admin:
            raise HTTPException(403, "Admins only.")


def _bearer(authorization):
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def principal(request: Request,
              x_locanoto_token: str = Header(default=""),
              authorization: str = Header(default=""),
              x_locanoto_csrf: str = Header(default="")):
    """The user of this request, or 401."""
    token = x_locanoto_token or _bearer(authorization)
    if token:
        name = auth.pruefe(token)
        if not name:
            raise HTTPException(401, "No valid token.",
                                headers={"WWW-Authenticate": "Bearer"})
        p = Principal(name, "token")
    else:
        s = sessions.verify(request.cookies.get(SESSION_COOKIE))
        if not s:
            raise HTTPException(401, "Not signed in.",
                                headers={"WWW-Authenticate": "Bearer"})
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            expected = request.cookies.get(CSRF_COOKIE, "")
            if not expected or not secrets.compare_digest(
                    expected, x_locanoto_csrf or ""):
                raise HTTPException(403, "CSRF check failed.")
        renewed = sessions.renew(s)
        if renewed:
            request.state.renewed_session = renewed
        p = Principal(s["user"], "session")
    if not sessions.hit(f"api:{p.name}", RATE_PER_MINUTE, 60):
        raise HTTPException(429, "Too many requests.",
                            headers={"Retry-After": "60"})
    request.state.user = p.name
    return p


def admin(p: Principal = Depends(principal)):
    p.require_admin()
    return p


def set_session_cookies(response, token):
    """Session cookie (no script access) and the CSRF cookie (readable)."""
    response.set_cookie(SESSION_COOKIE, token, httponly=True,
                        secure=COOKIE_SECURE, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24),
                        httponly=False, secure=COOKIE_SECURE,
                        samesite="strict", path="/")


def clear_session_cookies(response):
    for name in (SESSION_COOKIE, CSRF_COOKIE, SEALED_COOKIE):
        response.delete_cookie(name, path="/")


@app.middleware("http")
async def _headers(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
    renewed = getattr(request.state, "renewed_session", None)
    if renewed:
        response.set_cookie(SESSION_COOKIE, renewed, httponly=True,
                            secure=COOKIE_SECURE, samesite="strict",
                            path="/")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["Server-Timing"] = f"app;dur={(time.time() - started) * 1000:.0f}"
    return response


# --- ERRORS ---

@app.exception_handler(budget.Ueberzogen)
def _budget(_request, error):
    return JSONResponse(status_code=429,
                        content={"detail": str(error), "reason": "budget"},
                        headers={"Retry-After": str(budget.FENSTER_MINUTEN * 60)})


def _register_errors():
    import answering
    import doc_actions
    import mailboxes
    import web_sources

    def handler(status):
        def h(_request, error):
            return JSONResponse(status_code=status,
                                content={"detail": str(error)})
        return h
    import mcp
    # A tool server (mailbox, web search) that does not answer is a
    # problem behind this server: 502, with its message.
    for cls, status in ((doc_actions.Denied, 403), (doc_actions.NotFound, 404),
                        (mailboxes.NotFound, 404),
                        (web_sources.Unavailable, 503), (mcp.Fehler, 502)):
        app.add_exception_handler(cls, handler(status))

    def refused(_request, error):
        return JSONResponse(status_code=error.status,
                            content={"detail": error.detail})
    app.add_exception_handler(answering.Refused, refused)


# --- HEALTH ---

@app.get(f"{API_PREFIX}/health", tags=["status"])
def health():
    """Liveness: the process answers. No sign-in."""
    return {"status": "ok"}


@app.get(f"{API_PREFIX}/ready", tags=["status"])
def ready():
    """Readiness: the database answers (if one is configured)."""
    if database.active():
        try:
            database.connect().execute("SELECT 1")
        except Exception as e:
            return JSONResponse(status_code=503,
                                content={"status": "database",
                                         "detail": type(e).__name__})
    return {"status": "ok"}


# --- ROUTES ---

def _include():
    import routes_account
    import routes_admin
    import routes_chat
    import routes_documents
    for module, tag in ((routes_account, "account"), (routes_chat, "chat"),
                        (routes_documents, "documents"),
                        (routes_admin, "admin")):
        app.include_router(module.router, prefix=API_PREFIX)


_register_errors()
_include()
