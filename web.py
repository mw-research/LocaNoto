"""The web interface: server-rendered pages with HTMX-style fragments.

Served by server.py next to the API, from the same process and on top of
the same modules (answering, doc_actions, web_sources, accounts, ...), so
a page and an API call can never answer differently.

    /login            sign in (password or company directory)
    /                 chat; /c/<id> a given chat
    /documents        workspaces and documents: upload, move, delete
    /web              sources from the web: search, read, take over
    /settings         language, instruction, presets, password, mailboxes, tokens
    /admin            users, workspaces, jobs, status (the rest: /api/v1/docs)

Pages are rendered with Jinja; interaction uses hx-* attributes. The
script that reads them (web_static/hx.js) is a small subset of htmx with
the same attribute names, written here so that no third-party script is
loaded -- the official htmx file can replace it without touching a page.
The chat answer streams through /api/v1/ask (web_static/chat.js).

Security: a strict Content-Security-Policy (scripts and styles only from
this server, nothing inline), model output rendered as Markdown with HTML
switched off, the same session cookie and CSRF header as the API.
"""
import os
import time

import jinja2
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markdown_it import MarkdownIt

import accounts
import answering
import auth
import benutzer
import chats
import doc_actions
import feedback
import jobs
import llm
import mailboxes
import notzugang
import pipeline
import presets
import prompts
import raeume
import sessions
import sprache
import web_sources
from server import (SEALED_COOKIE, COOKIE_SECURE, Principal, principal,
                    set_session_cookies)

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.getenv("UI_BRAND_NAME", "LocaNoto").strip() or "LocaNoto"
ACCENT = os.getenv("UI_ACCENT_COLOR", "").strip()

router = APIRouter(include_in_schema=False)

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(HERE, "web_templates")),
    autoescape=True, trim_blocks=True, lstrip_blocks=True)
_md = MarkdownIt("commonmark", {"html": False, "linkify": False,
                                "typographer": False}).enable("table")

# English keys, German texts. New code is English; the people using it
# mostly read German.
TEXTS = {
    "Sign in": "Anmelden", "Sign out": "Abmelden", "Name": "Name",
    "Password": "Passwort", "Sign in with the company account":
        "Mit dem Firmenkonto anmelden", "or": "oder",
    "Chat": "Chat", "Documents": "Dokumente", "Web sources": "Quellen im Netz",
    "Settings": "Einstellungen", "Admin": "Admin", "New chat": "Neuer Chat",
    "Ask a question about your documents ...":
        "Frage an deine Dokumente ...", "Send": "Senden",
    "Workspaces": "Arbeitsbereiche", "all": "alle",
    "Web search": "Websuche", "Model": "Modell", "Preset": "Voreinstellung",
    "none": "keine", "Sources": "Quellen", "page": "Seite",
    "Show page": "Seite zeigen", "Helpful": "Hilfreich",
    "Not helpful": "Nicht hilfreich", "Thanks.": "Danke.",
    "Draft waiting for you": "Entwurf wartet auf dich",
    "Send draft": "Entwurf senden", "Discard": "Verwerfen",
    "Sent.": "Gesendet.", "Discarded.": "Verworfen.",
    "From the web": "Aus dem Netz", "Take over": "Übernehmen",
    "Delete": "Löschen", "Rename": "Umbenennen",
    "Upload": "Hochladen", "into": "nach", "Project (optional)":
        "Projekt (optional)", "Describe images": "Bilder beschreiben",
    "Move to": "Verschieben nach", "Move": "Verschieben",
    "No documents yet.": "Noch keine Dokumente.",
    "Search": "Suchen", "Keywords only -- they go to search engines.":
        "Nur Stichworte – sie gehen an Suchmaschinen.",
    "Read": "Lesen", "Take over selected into my workspace":
        "Ausgewählte in meinen Arbeitsbereich übernehmen",
    "Language": "Sprache", "Save": "Speichern",
    "Personal instruction": "Persönliche Anweisung",
    "Applies to every question you ask.": "Gilt für jede deiner Fragen.",
    "Change password": "Passwort ändern", "Current password":
        "Bisheriges Passwort", "New password": "Neues Passwort",
    "Mailboxes": "Postfächer", "Connect": "Verbinden",
    "connected": "verbunden", "Disconnect": "Trennen",
    "Logins are kept only in this browser session.":
        "Anmeldedaten gelten nur für diese Browsersitzung.",
    "API tokens": "API-Token", "Revoke": "Widerrufen",
    "Users": "Nutzer", "Role": "Rolle", "Create": "Anlegen",
    "Jobs": "Hintergrundläufe", "Start": "Starten", "Status": "Status",
    "Full admin area in the API": "Vollständiger Admin-Bereich in der API",
    "Members (comma separated)": "Mitglieder (durch Komma)",
    "Label": "Bezeichnung", "Saved.": "Gespeichert.",
    "Presets": "Voreinstellungen", "own": "eigene",
    "Answer from the keyword search only -- the vector search did not answer for":
        "Antwort nur aus der Stichwortsuche – die Vektorsuche hat nicht geantwortet für",
    "Your account signs in through the company directory.":
        "Dein Konto meldet sich über das Firmenverzeichnis an.",
    "Backups": "Sicherungen", "Emergency access": "Notzugang",
    "Prompts and glossary": "Prompts und Glossar", "Feedback": "Rückmeldungen",
    "Storage": "Ablage", "Back up now": "Jetzt sichern",
    "type the name to confirm": "Namen zur Bestätigung eintippen",
    "also users, chats, settings": "auch Nutzer, Chats, Einstellungen",
    "Restore": "Zurückholen", "incomplete": "unvollständig",
    "with state": "mit Zustand",
    "Type the name of the backup to confirm.":
        "Zum Bestätigen den Namen des Abzugs eintippen.",
    "Nobody holds the role notzugang -- no request can be confirmed.":
        "Niemand hat die Rolle notzugang – kein Antrag kann bestätigt werden.",
    "Open grants": "Offene Zugänge", "Close": "Schließen",
    "Requests": "Anträge", "Confirm": "Bestätigen", "Reject": "Ablehnen",
    "Request access to a personal workspace":
        "Zugang zu einem persönlichen Arbeitsbereich beantragen",
    "Reason (the second person decides on it)":
        "Grund (die zweite Person entscheidet danach)",
    "Request": "Beantragen", "Open": "Öffnen",
    "Reset to the shipped template": "Auf die mitgelieferte Vorlage zurücksetzen",
    "Glossary": "Glossar", "Archive the log?": "Protokoll archivieren?",
    "Archive": "Archivieren", "Download": "Herunterladen",
    "Questions without an answer": "Fragen ohne Antwort",
    "No storage (OpenCloud) is configured.": "Keine Ablage (OpenCloud) eingerichtet.",
    "Set up workspace folders and shares":
        "Ordner und Freigaben der Arbeitsbereiche einrichten",
    "Sync groups": "Gruppen abgleichen", "Sync documents": "Dokumente abgleichen",
    "personal": "persönlich", "Kind": "Art",
    "Address, command or Exchange server": "Adresse, Befehl oder Exchange-Server",
    "Address of a shared mailbox (only for shared ones)":
        "Adresse eines Funktionspostfachs (nur dafür)",
    "personal (everyone signs in with their own account)":
        "persönlich (jeder meldet sich mit seinem Konto an)",
    "Delete this chat?": "Diesen Chat löschen?",
    "Delete this document?": "Dieses Dokument löschen?",
}


def page_language(user=""):
    code = sprache.gewaehlt(user) if user else sprache.VORGABE
    sprache.setze(code)
    return code


def t(text):
    if sprache.aktuell() == "de":
        return TEXTS.get(text, text)
    return text


def tm(message):
    """A message from the German modules, in the page language."""
    return sprache.t(message)


def render(name, request=None, **context):
    context.setdefault("brand", BRAND)
    context.setdefault("accent", ACCENT)
    context.update(t=t, tm=tm, lang=sprache.aktuell(),
                   csrf=(request.cookies.get("locanoto_csrf", "")
                         if request is not None else ""))
    return HTMLResponse(_env.get_template(name).render(**context))


def markdown(text):
    return _md.render(str(text or ""))


_env.filters["markdown"] = markdown


def _optional(request):
    """The signed-in user of a page, or None (then: to the sign-in page)."""
    s = sessions.verify(request.cookies.get("locanoto_session"))
    if not s:
        return None
    return Principal(s["user"], "session")


def _need(request):
    p = _optional(request)
    if p is None:
        raise _ToLogin(request.url.path)
    page_language(p.name)
    return p


class _ToLogin(Exception):
    def __init__(self, path):
        self.path = path


def to_login_handler(_request, error):
    return RedirectResponse(f"/login?next={error.path}", status_code=303)


def _nav(p, active):
    return {"user": p.name, "admin": p.is_admin, "active": active}


# --- SIGN-IN ---

@router.get("/login")
def login_page(request: Request, next: str = "/"):
    import oidc
    page_language()
    return render("login.html", request, next=oidc.safe_next(next),
                  directory=oidc.enabled())


# --- CHAT ---

def _chat_options(p):
    emergency = notzugang.raeume_fuer(p.name)
    return {
        "workspaces": [(r, raeume.bezeichnung(r))
                       for r in raeume.lesbar(p.name, emergency)],
        "models": llm.chat_modelle(),
        "presets": [(n, presets.anzeige(n))
                    for n in presets.namen() + presets.eigene(p.name)],
        "web": bool(answering.mcp.websuche_server()),
    }


def _messages(p, chat_id):
    """Messages for the page: no server paths, each answer with its question."""
    out, question = [], ""
    for i, m in enumerate(chats.lade(p.name, chat_id)):
        entry = {k: v for k, v in m.items() if k != "bilder"}
        entry.update(index=i, images=len(m.get("bilder") or []))
        if m.get("role") == "user":
            question = m.get("content", "")
        else:
            entry["question"] = question
        out.append(entry)
    return out


@router.get("/")
def home(request: Request):
    p = _need(request)
    return render("chat.html", request, nav=_nav(p, "chat"),
                  chats=chats.liste(p.name), chat_id="", messages=[],
                  options=_chat_options(p))


@router.get("/c/{chat_id}")
def chat_page(chat_id: str, request: Request):
    p = _need(request)
    if chat_id not in {k for k, _t, _g in chats.liste(p.name)}:
        return RedirectResponse("/", status_code=303)
    return render("chat.html", request, nav=_nav(p, "chat"),
                  chats=chats.liste(p.name), chat_id=chat_id,
                  messages=_messages(p, chat_id), options=_chat_options(p))


@router.get("/ui/chats")
def chat_list(request: Request, current: str = "",
              p: Principal = Depends(principal)):
    page_language(p.name)
    return render("chat_list.html", request, chats=chats.liste(p.name),
                  chat_id=current)


@router.get("/ui/chats/{chat_id}/messages/{index}")
def chat_message(chat_id: str, index: int, request: Request,
                 p: Principal = Depends(principal)):
    page_language(p.name)
    if chat_id not in {k for k, _t, _g in chats.liste(p.name)}:
        raise HTTPException(404, "Unknown chat.")
    messages = _messages(p, chat_id)
    if index < 0:
        index += len(messages)          # -1: the last one
    if index < 0 or index >= len(messages):
        raise HTTPException(404, "No such message.")
    return render("message.html", request, m=messages[index], chat_id=chat_id)


@router.post("/ui/chats/{chat_id}/rename")
def chat_rename(chat_id: str, request: Request, title: str = Form(...),
                p: Principal = Depends(principal)):
    page_language(p.name)
    if chat_id in {k for k, _t, _g in chats.liste(p.name)}:
        chats.benenne(p.name, chat_id, answering.clean_title(title))
    return render("chat_list.html", request, chats=chats.liste(p.name),
                  chat_id=chat_id)


@router.post("/ui/chats/{chat_id}/delete")
def chat_delete(chat_id: str, request: Request,
                p: Principal = Depends(principal)):
    if chat_id in {k for k, _t, _g in chats.liste(p.name)}:
        chats.loesche(p.name, chat_id)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/"
    return response


@router.post("/ui/feedback")
def give_feedback(request: Request, kind: str = Form(...),
                  question: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    if kind in ("daumen_hoch", "daumen_runter"):
        feedback.notiere(kind, p.name, question[:2000], herkunft="web")
    return HTMLResponse(f'<span class="muted">{t("Thanks.")}</span>')


@router.post("/ui/chats/{chat_id}/drafts/{draft_id}/{action}")
def draft_action(chat_id: str, draft_id: str, action: str, request: Request,
                 p: Principal = Depends(principal)):
    page_language(p.name)
    if action == "send":
        headers = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
        try:
            mailboxes.send_draft(p.name, chat_id, draft_id, headers)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return HTMLResponse(f'<span class="ok">{t("Sent.")}</span>')
    mailboxes.discard_draft(p.name, chat_id, draft_id)
    return HTMLResponse(f'<span class="muted">{t("Discarded.")}</span>')


# --- DOCUMENTS ---

def _documents(p):
    emergency = notzugang.raeume_fuer(p.name)
    by_room = pipeline.dokumente(p.name, notzugang=emergency)
    writable = raeume.schreibbar(p.name, p.is_admin, emergency)
    rooms = [{"id": r, "label": raeume.bezeichnung(r),
              "files": by_room.get(r, []), "writable": r in writable}
             for r in raeume.lesbar(p.name, emergency)]
    return rooms, [(r, raeume.bezeichnung(r)) for r in writable]


@router.get("/documents")
def documents_page(request: Request):
    p = _need(request)
    rooms, targets = _documents(p)
    return render("documents.html", request, nav=_nav(p, "documents"),
                  rooms=rooms, targets=targets,
                  own=raeume.privat_kennung(p.name))


@router.get("/ui/documents")
def documents_fragment(request: Request, p: Principal = Depends(principal)):
    page_language(p.name)
    rooms, targets = _documents(p)
    return render("documents_list.html", request, rooms=rooms,
                  targets=targets)


@router.post("/ui/documents/delete")
def document_delete(request: Request, room: str = Form(...),
                    file: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    doc_actions.delete(p.name, file, room, p.is_admin)
    return documents_fragment(request, p)


@router.post("/ui/documents/move")
def document_move(request: Request, room: str = Form(...),
                  file: str = Form(...), target: str = Form(...),
                  p: Principal = Depends(principal)):
    page_language(p.name)
    doc_actions.move(p.name, file, room, target, p.is_admin)
    return documents_fragment(request, p)


# --- WEB SOURCES ---

@router.get("/web")
def web_page(request: Request):
    p = _need(request)
    return render("web.html", request, nav=_nav(p, "web"),
                  available=bool(answering.mcp.websuche_server()))


@router.post("/ui/web/search")
def web_search(request: Request, query: str = Form(...),
               p: Principal = Depends(principal)):
    page_language(p.name)
    hits = web_sources.search(query, 10)
    return render("web_results.html", request, hits=hits)


@router.post("/ui/web/read")
def web_read(request: Request, url: str = Form(...),
             p: Principal = Depends(principal)):
    page_language(p.name)
    try:
        text = web_sources.read(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return render("web_page_text.html", request, url=url, text=text)


@router.post("/ui/web/take-over")
async def web_take_over(request: Request, p: Principal = Depends(principal)):
    page_language(p.name)
    form = await request.form()
    pages = []
    for key in form.keys():
        if key.startswith("pick_"):
            n = key[5:]
            pages.append({"title": form.get(f"title_{n}", ""),
                          "url": form.get(f"url_{n}", ""),
                          "text": form.get(f"text_{n}", ""),
                          "query": form.get(f"query_{n}", "")})
    import starlette.concurrency
    result = await starlette.concurrency.run_in_threadpool(
        web_sources.take_over, p.name, pages)
    return render("web_taken.html", request, result=result)


# --- SETTINGS ---

def _settings_context(p, request):
    entry = benutzer.eintrag(p.name) or {}
    connected = set(sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE)))
    return {
        "nav": _nav(p, "settings"), "language": sprache.gewaehlt(p.name),
        "instruction": prompts.anweisung(p.name) or "",
        "sso": entry.get("anmeldung") == "oidc",
        "presets": [(n, presets.anzeige(n), presets.ist_eigene(n))
                    for n in presets.namen() + presets.eigene(p.name)],
        "mailboxes": [dict(m, connected=m["name"] in connected)
                      for m in mailboxes.overview()
                      if m["kind"] == "mailbox"],
        "tokens": [(k[:12], e.get("bezeichnung", ""), e.get("erstellt", ""))
                   for k, e in auth.liste() if e.get("benutzer") == p.name],
    }


@router.get("/settings")
def settings_page(request: Request):
    p = _need(request)
    return render("settings.html", request, **_settings_context(p, request))


def _notice(text, ok=True):
    return HTMLResponse(f'<p class="{"ok" if ok else "error"}">'
                        f'{jinja2.utils.markupsafe.escape(text)}</p>')


@router.post("/ui/settings/language")
def set_language(request: Request, language: str = Form(...),
                 p: Principal = Depends(principal)):
    sprache.speichere(p.name, language)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/instruction")
def set_instruction(request: Request, text: str = Form(""),
                    p: Principal = Depends(principal)):
    page_language(p.name)
    ok, message = prompts.anweisung_speichern(p.name, text)
    return _notice(tm(message), ok)


@router.post("/ui/settings/password")
def set_password(request: Request, current: str = Form(...),
                 new: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    ok, message, _notes = accounts.change_own_password(p.name, current, new)
    response = _notice(tm(message), ok)
    if ok:
        set_session_cookies(response, sessions.issue(p.name))
        response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/mailbox/{server}")
def connect_mailbox(server: str, request: Request, user: str = Form(""),
                    secret: str = Form(""), action: str = Form("connect"),
                    p: Principal = Depends(principal)):
    page_language(p.name)
    sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
    if action == "disconnect":
        sealed.pop(server, None)
        response = HTMLResponse("")
    else:
        header = mailboxes.header_for(server, user, secret)
        try:
            mailboxes.check(server, header)
        except mailboxes.NotFound:
            raise
        except Exception as e:
            return _notice(f"{type(e).__name__}", ok=False)
        sealed[server] = header
        response = HTMLResponse("")
    response.set_cookie(SEALED_COOKIE, sessions.seal(p.name, sealed),
                        httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", path="/")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/token/{token_id}/revoke")
def revoke_token(token_id: str, request: Request,
                 p: Principal = Depends(principal)):
    mine = [k for k, e in auth.liste()
            if e.get("benutzer") == p.name and k.startswith(token_id)]
    if len(token_id) >= 8 and len(mine) == 1:
        auth.widerrufe(mine[0])
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/settings"
    return response


# --- ADMIN ---

def _admin_context(p):
    import sicherheit
    return {
        "nav": _nav(p, "admin"),
        "users": [(n, (benutzer.eintrag(n) or {}).get("rolle", "nutzer"),
                   (benutzer.eintrag(n) or {}).get("anmeldung", "lokal"))
                  for n in benutzer.namen()],
        # notzugang is assigned on the server or by the directory only
        # (see accounts.APP_ROLES).
        "roles": accounts.APP_ROLES,
        "workspaces": [(r, raeume.bezeichnung(r),
                        ", ".join(d.get("mitglieder") or []), d.get("gruppe") or "")
                       for r, d in sorted(raeume.liste().items())
                       if not raeume.ist_privat(r)],
        "jobs": jobs.overview(),
        "security": sicherheit.kurz() if hasattr(sicherheit, "kurz") else "",
    }


@router.get("/admin")
def admin_page(request: Request):
    p = _need(request)
    if not p.is_admin:
        return RedirectResponse("/", status_code=303)
    return render("admin.html", request, **_admin_context(p))


def _admin(p):
    if not p.is_admin:
        raise HTTPException(403, "Admins only.")


def _back_to_admin():
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/admin"
    return response


@router.post("/ui/admin/users")
def admin_create_user(request: Request, name: str = Form(...),
                      password: str = Form(...), role: str = Form("nutzer"),
                      p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.create(name, password, role, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/users/{name}/role")
def admin_set_role(name: str, request: Request, role: str = Form(...),
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.set_role(name, role, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/users/{name}/delete")
def admin_delete_user(name: str, request: Request,
                      p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.delete(name, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/workspaces")
def admin_create_workspace(request: Request, id: str = Form(...),
                           label: str = Form(...), members: str = Form(""),
                           p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message = raeume.anlegen(
        id, label, "", [m.strip() for m in members.split(",") if m.strip()])
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/jobs/{name}")
def admin_start_job(name: str, request: Request,
                    p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    result = jobs.start(name, by=p.name)
    return _notice(tm(result.get("message", "")), result.get("started", False))
