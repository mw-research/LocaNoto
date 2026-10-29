"""API: sign-in, the own account and own settings.

    POST   /auth/login                 user + password -> session cookie
    POST   /auth/logout
    GET    /me                         who am I, what may I
    PUT    /me/password                own password (and storage password)
    PUT    /me/language                de | en
    GET    /me/instruction             personal instruction to the model
    PUT    /me/instruction
    DELETE /me/instruction
    GET    /presets                    shared and own presets
    PUT    /me/presets/{name}          create or change an own preset
    DELETE /me/presets/{name}
    GET    /me/tokens                  own API tokens (never the token itself)
    DELETE /me/tokens/{token_id}
    GET    /models                     chat models to choose from, endpoints
    GET    /mailboxes                  mailboxes and web search services
    POST   /mailboxes/{server}/login   check a login; browsers keep it sealed
    DELETE /mailboxes/{server}/login
    GET    /me/sql-accounts            database accounts this user may use
    PUT    /me/sql-account             the account of the own room
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

import accounts
import answering
import auth
import benutzer
import llm
import mailboxes
import notzugang
import presets
import prompts
import raeume
import sessions
import sprache
import sqlquellen
from server import (SEALED_COOKIE, COOKIE_SECURE, Principal,
                    clear_session_cookies, principal, set_session_cookies)

router = APIRouter()


def _client_address(request):
    # Not X-Forwarded-For: the client can write that. Behind a proxy,
    # uvicorn --proxy-headers puts the real address here.
    return request.client.host if request.client else "?"


# --- SIGN-IN ---

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


@router.post("/auth/login", tags=["account"])
def login(body: Login, request: Request, response: Response):
    """Sign in with name and password. Sets the session cookie.

    Failed attempts are counted per name and per address; after
    LOGIN_ATTEMPTS within LOGIN_WINDOW_MINUTES the answer is 429 for both,
    whether or not the password would have been right.
    """
    name = body.username.strip().lower()
    address = _client_address(request)
    if not sessions.login_attempt(name, address):
        raise HTTPException(429, "Too many failed sign-ins. Try later.",
                            headers={"Retry-After": str(
                                sessions.LOGIN_WINDOW_MINUTES * 60)})
    # The password check always runs (bcrypt time), also for directory
    # accounts -- a faster answer would tell which names those are.
    password_ok = benutzer.pruefe(name, body.password)
    entry = benutzer.lade()[0].get(name) or {}
    if entry.get("anmeldung") == "oidc" or not password_ok:
        raise HTTPException(401, "Name or password wrong.")
    sessions.login_succeeded(name, address)
    token = sessions.issue(name)
    set_session_cookies(response, token)
    benutzer.protokolliere("anmeldung", name, name, "api")
    s = sessions.verify(token)
    return {"user": name, "expires": s["expires"] if s else None}


@router.get("/auth/methods", tags=["account"])
def sign_in_methods():
    """Which ways to sign in this installation offers (no sign-in needed)."""
    import oidc
    return {"password": True, "oidc": oidc.enabled()}


OIDC_FLOW_COOKIE = "locanoto_oidc"


@router.get("/auth/oidc/login", tags=["account"])
def oidc_login(next: str = "/"):
    """Start the sign-in at the company directory (redirect)."""
    import oidc
    from fastapi.responses import RedirectResponse
    if not oidc.enabled():
        raise HTTPException(404, "No directory sign-in configured.")
    url, flow = oidc.start(next)
    response = RedirectResponse(url, status_code=302)
    # SameSite=Lax: the directory sends the browser back with a top-level
    # GET, and a Strict cookie would not come along.
    response.set_cookie(OIDC_FLOW_COOKIE, flow, max_age=oidc.FLOW_SECONDS,
                        httponly=True, secure=COOKIE_SECURE, samesite="lax",
                        path="/api/v1/auth/oidc")
    return response


@router.get("/auth/oidc/callback", tags=["account"])
def oidc_callback(request: Request, code: str = "", state: str = "",
                  error: str = ""):
    """Where the directory sends the browser back. Ends in a session."""
    import oidc
    from fastapi.responses import RedirectResponse
    if not oidc.enabled():
        raise HTTPException(404, "No directory sign-in configured.")
    if error or not code:
        raise HTTPException(401, "The directory did not sign you in.")
    try:
        name, next_path = oidc.finish(code, state,
                                      request.cookies.get(OIDC_FLOW_COOKIE))
    except oidc.Refused as e:
        raise HTTPException(403, str(e))
    # Not a redirect: a navigation chain that started at the directory
    # counts as cross-site, and the browser would not send the new
    # SameSite=Strict session cookie with it. A page of our own that moves
    # on is a same-site navigation.
    import html
    from fastapi.responses import HTMLResponse
    target = html.escape(next_path, quote=True)
    response = HTMLResponse(
        f'<!doctype html><meta http-equiv="refresh" content="0;url={target}">'
        f'<a href="{target}">Continue</a>')
    response.delete_cookie(OIDC_FLOW_COOKIE, path="/api/v1/auth/oidc")
    set_session_cookies(response, sessions.issue(name))
    return response


@router.post("/auth/logout", tags=["account"])
def logout(request: Request, response: Response,
           x_locanoto_csrf: str = Header(default="")):
    import secrets as _secrets
    expected = request.cookies.get("locanoto_csrf", "")
    if request.cookies.get("locanoto_session") and not (
            expected and _secrets.compare_digest(expected, x_locanoto_csrf)):
        raise HTTPException(403, "CSRF check failed.")
    clear_session_cookies(response)
    return {"status": "signed out"}


# --- ME ---

@router.get("/me", tags=["account"])
def me(p: Principal = Depends(principal)):
    emergency = notzugang.raeume_fuer(p.name)
    entry = benutzer.eintrag(p.name) or {}
    return {
        "user": p.name,
        "role": entry.get("rolle", "nutzer"),
        "admin": p.is_admin,
        "sign_in": entry.get("anmeldung", "lokal"),
        "via": p.via,
        "language": sprache.gewaehlt(p.name),
        "own_room": raeume.privat_kennung(p.name),
        "readable_rooms": raeume.lesbar(p.name, emergency),
        "writable_rooms": raeume.schreibbar(p.name, p.is_admin, emergency),
        "emergency_rooms": list(emergency),
    }


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=benutzer.MIN_PASSWORT, max_length=500)


@router.put("/me/password", tags=["account"])
def change_password(body: PasswordChange, response: Response,
                    p: Principal = Depends(principal)):
    if (benutzer.eintrag(p.name) or {}).get("anmeldung") == "oidc":
        raise HTTPException(400, "This account signs in through the "
                                 "company directory; change it there.")
    ok, message, notes = accounts.change_own_password(p.name, body.current,
                                                      body.new)
    if not ok:
        raise HTTPException(400, message)
    if p.via == "session":
        # The fingerprint changed, so the old cookie is void: issue anew.
        set_session_cookies(response, sessions.issue(p.name))
    return {"message": message, "storage": notes}


class Language(BaseModel):
    language: str = Field(pattern="^(de|en)$")


@router.put("/me/language", tags=["account"])
def set_language(body: Language, p: Principal = Depends(principal)):
    sprache.speichere(p.name, body.language)
    return {"language": sprache.gewaehlt(p.name)}


class Instruction(BaseModel):
    text: str = Field(max_length=4000)


@router.get("/me/instruction", tags=["account"])
def get_instruction(p: Principal = Depends(principal)):
    return {"text": prompts.anweisung(p.name) or ""}


@router.put("/me/instruction", tags=["account"])
def put_instruction(body: Instruction, p: Principal = Depends(principal)):
    ok, message = prompts.anweisung_speichern(p.name, body.text)
    if not ok:
        raise HTTPException(400, message)
    return {"text": prompts.anweisung(p.name) or ""}


@router.delete("/me/instruction", tags=["account"])
def delete_instruction(p: Principal = Depends(principal)):
    prompts.anweisung_loeschen(p.name)
    return {"text": ""}


# --- PRESETS ---

@router.get("/presets", tags=["account"])
def list_presets(p: Principal = Depends(principal)):
    return [{"name": n, "own": presets.ist_eigene(n),
             "label": presets.anzeige(n), **presets.lese(n)}
            for n in presets.namen() + presets.eigene(p.name)]


class PresetValues(BaseModel):
    chat_modell: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=30)
    listen_bereiche: list[str] | None = None
    beschreibung: str | None = None


@router.put("/me/presets/{label}", tags=["account"])
def put_own_preset(label: str, body: PresetValues,
                   p: Principal = Depends(principal)):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if values.get("chat_modell") and \
            values["chat_modell"] not in llm.chat_modelle():
        raise HTTPException(400, "Model not allowed.")
    ok, name = presets.eigene_speichern(p.name, label, values)
    if not ok:
        raise HTTPException(400, name)
    return {"name": name, **presets.lese(name)}


@router.delete("/me/presets/{name:path}", tags=["account"])
def delete_own_preset(name: str, p: Principal = Depends(principal)):
    if not presets.eigene_loeschen(name, p.name):
        raise HTTPException(404, "No such own preset.")
    return {"deleted": name}


# --- TOKENS ---

@router.get("/me/tokens", tags=["account"])
def own_tokens(p: Principal = Depends(principal)):
    return [{"id": k[:12], "label": e.get("bezeichnung", ""),
             "created": e.get("erstellt"), "valid_until": e.get("gueltig_bis"),
             "signed": e.get("gueltig")}
            for k, e in auth.liste() if e.get("benutzer") == p.name]


@router.delete("/me/tokens/{token_id}", tags=["account"])
def revoke_own_token(token_id: str, p: Principal = Depends(principal)):
    mine = [k for k, e in auth.liste()
            if e.get("benutzer") == p.name and k.startswith(token_id)]
    if len(token_id) < 8 or len(mine) != 1:
        raise HTTPException(404, "No such token.")
    auth.widerrufe(mine[0])
    return {"revoked": token_id}


# --- MODELS ---

@router.get("/models", tags=["account"])
def models(p: Principal = Depends(principal)):
    bewerter = answering.reranker()
    return {"chat_models": llm.chat_modelle(),
            "default": llm.modell("CHAT"),
            "endpoints": llm.uebersicht() if p.is_admin else None,
            "ranking": (bewerter.beschreibung()
                        if hasattr(bewerter, "beschreibung") else "fusion")}


# --- MAILBOXES ---

@router.get("/mailboxes", tags=["mailboxes"])
def list_mailboxes(request: Request, p: Principal = Depends(principal)):
    connected = set(sessions.unseal(p.name,
                                    request.cookies.get(SEALED_COOKIE)))
    return [dict(m, connected=m["name"] in connected)
            for m in mailboxes.overview()]


class MailboxLogin(BaseModel):
    user: str = Field(default="", max_length=300)
    secret: str = Field(min_length=1, max_length=2000)


@router.post("/mailboxes/{server}/login", tags=["mailboxes"])
def mailbox_login(server: str, body: MailboxLogin, request: Request,
                  response: Response, p: Principal = Depends(principal)):
    """Check a mailbox login. Nothing is stored on the server.

    Browsers (session): the login is sealed into the cookie
    locanoto_sealed and used for later questions. API clients (token):
    send the login with each question instead (POST /ask, "mailboxes").
    """
    header = mailboxes.header_for(server, body.user, body.secret)
    try:
        tools = mailboxes.check(server, header)
    except mailboxes.NotFound:
        raise
    except Exception as e:
        raise HTTPException(400, f"Not connected: {type(e).__name__}")
    if p.via == "session":
        sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
        sealed[server] = header
        response.set_cookie(SEALED_COOKIE, sessions.seal(p.name, sealed),
                            httponly=True, secure=COOKIE_SECURE,
                            samesite="strict", path="/")
    return {"server": server, "connected": True, "tools": len(tools)}


@router.delete("/mailboxes/{server}/login", tags=["mailboxes"])
def mailbox_logout(server: str, request: Request, response: Response,
                   p: Principal = Depends(principal)):
    sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
    sealed.pop(server, None)
    response.set_cookie(SEALED_COOKIE, sessions.seal(p.name, sealed),
                        httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", path="/")
    return {"server": server, "connected": False}


def mailbox_headers(p, request, given=None):
    """Headers for this request: sealed cookie plus logins sent along."""
    headers = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE)) \
        if p.via == "session" else {}
    for server, login in (given or {}).items():
        headers[server] = mailboxes.header_for(
            server, login.get("user", ""), login.get("secret", ""))
    return headers


# --- SQL ---

@router.get("/me/sql-accounts", tags=["account"])
def sql_accounts(p: Principal = Depends(principal)):
    return [{"room": r, "account": a,
             "label": raeume.bezeichnung(r) if r else "environment"}
            for r, a in answering.sql_accounts(p.name)]


class SqlAccount(BaseModel):
    benutzer: str = ""
    passwort: str = ""


@router.put("/me/sql-account", tags=["account"])
def set_own_sql_account(body: SqlAccount, p: Principal = Depends(principal)):
    """The database account of the own room. Empty removes it.

    Only name and password: the server is the one the admin set up. A
    free choice would let any user make the server connect anywhere in
    the network.
    """
    room = raeume.privat_kennung(p.name)
    ok, message = sqlquellen.setze(
        room, {k: v for k, v in body.model_dump().items() if v is not None},
        benutzer=p.name)
    if not ok:
        raise HTTPException(400, message)
    return {"room": room, "message": message}
