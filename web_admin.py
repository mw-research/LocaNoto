"""Admin pages of the web interface beyond users, workspaces and jobs.

    /admin/backups      list, back up now, restore (with state)
    /admin/emergency    requests and open grants; request, confirm, reject, close
    /admin/content      prompt templates and the glossary
    /admin/feedback     empty answers and thumbs down; archive
    /admin/storage      OpenCloud: status, set up workspaces, group sync
    /admin/mailboxes    mailboxes and web search services

The same functions as /api/v1/admin/..., with the same checks. The
emergency page is open to admins and to the role notzugang (the second
person who confirms).
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import benutzer
import dateisperre
import feedback
import jobs
import mailboxes
import notzugang
import owncloud
import paths
import prompts
import raeume
import sicherung
import statefiles
from server import Principal, principal
from web import _need, _nav, _notice, page_language, render, tm

router = APIRouter(include_in_schema=False)


def _page(request, emergency_ok=False):
    p = _need(request)
    if not (p.is_admin or (emergency_ok and p.is_emergency)):
        return p, RedirectResponse("/", status_code=303)
    return p, None


def _admin(p):
    if not p.is_admin:
        raise HTTPException(403, "Admins only.")


def _reload(path):
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = path
    return response


# --- BACKUPS ---

@router.get("/admin/backups")
def backups_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    return render("admin_backups.html", request, nav=_nav(p, "admin"),
                  backups=sicherung.liste(), folder=sicherung.ORDNER,
                  job=jobs.status("sicherung"))


@router.post("/ui/admin/backups/start")
def backup_start(request: Request, p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    result = jobs.start("sicherung", by=p.name)
    return _notice(tm(result.get("message", "")), result.get("started", False))


@router.post("/ui/admin/backups/restore")
def backup_restore(request: Request, name: str = Form(...),
                   confirm: str = Form(""), state: str = Form(""),
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    if confirm != name:
        return _notice("Type the name of the backup to confirm.", False)
    report = sicherung.hole_zurueck(name, zustand=bool(state))
    benutzer.protokolliere("sicherung_zurueck", name, p.name, "web")
    errors = report.get("fehler") or []
    rooms = sum((report.get("raeume") or {}).values())
    return _notice(f"{rooms} passages restored"
                   + (f", {report['zustand']} state files" if report.get("zustand") else "")
                   + (f"; problems: {errors}" if errors else "."), not errors)


# --- EMERGENCY ACCESS ---

@router.get("/admin/emergency")
def emergency_page(request: Request):
    p, away = _page(request, emergency_ok=True)
    if away:
        return away
    foreign = [r for r in raeume.liste() if raeume.ist_privat(r)
               and r != raeume.privat_kennung(p.name)]
    return render("admin_emergency.html", request, nav=_nav(p, "admin"),
                  possible=notzugang.moeglich(), open=notzugang.offene(),
                  requests=notzugang.antraege(), rooms=foreign,
                  can_request=p.is_admin, can_confirm=p.is_emergency,
                  me=p.name)


@router.post("/ui/admin/emergency/{action}")
def emergency_action(action: str, request: Request, room: str = Form(...),
                     requester: str = Form(""), reason: str = Form(""),
                     p: Principal = Depends(principal)):
    page_language(p.name)
    if not (p.is_admin or p.is_emergency):
        raise HTTPException(403, "Admins and the role notzugang only.")
    if action == "request":
        ok, message = notzugang.beantrage(room, p.name, reason)
    elif action == "confirm":
        ok, message = notzugang.bestaetige(room, requester, p.name)
    elif action == "reject":
        ok, message = notzugang.lehne_ab(room, requester, p.name, reason)
    elif action == "close":
        ok, message = notzugang.schliesse(room, requester, p.name)
    else:
        raise HTTPException(404, "Unknown action.")
    return _reload("/admin/emergency") if ok else _notice(tm(message), False)


# --- PROMPTS AND GLOSSARY ---

@router.get("/admin/content")
def content_page(request: Request, prompt: str = ""):
    p, away = _page(request)
    if away:
        return away
    names = prompts.verfuegbar()
    chosen = prompt if prompt in names else (names[0] if names else "")
    text, origin = prompts.lese(chosen) if chosen else ("", "")
    try:
        glossary = statefiles.read_text(paths.resolve_glossar())
    except OSError:
        glossary = ""
    return render("admin_content.html", request, nav=_nav(p, "admin"),
                  prompts=[(n, prompts.VORLAGEN[n].get("titel", n))
                           for n in names],
                  chosen=chosen, text=text, origin=origin, glossary=glossary)


@router.post("/ui/admin/prompts/{name}")
def save_prompt(name: str, request: Request, text: str = Form(...),
                action: str = Form("save"), p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    if name not in prompts.verfuegbar():
        raise HTTPException(404, "No such prompt.")
    if action == "reset":
        prompts.zuruecksetzen(name)
        return _reload(f"/admin/content?prompt={name}")
    ok, message = prompts.speichern(name, text)
    if ok:
        benutzer.protokolliere("prompt", name, p.name, "web")
    return _notice(tm(message), ok)


@router.post("/ui/admin/glossary")
def save_glossary(request: Request, text: str = Form(""),
                  p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    dateisperre.schreibe_atomar(paths.GLOSSAR_FILE, text)
    benutzer.protokolliere("glossar", "glossar", p.name, "web")
    return _notice("Saved.")


# --- FEEDBACK ---

@router.get("/admin/feedback")
def feedback_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    return render("admin_feedback.html", request, nav=_nav(p, "admin"),
                  counts=feedback.zaehle(),
                  empty=feedback.lese(grenze=30, art="leer"),
                  down=feedback.lese(grenze=30, art="daumen_runter"),
                  archives=feedback.ablagen())


@router.post("/ui/admin/feedback/archive")
def feedback_archive(request: Request, p: Principal = Depends(principal)):
    _admin(p)
    feedback.archiviere()
    return _reload("/admin/feedback")


# --- STORAGE ---

@router.get("/admin/storage")
def storage_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    configured = owncloud.eingerichtet()
    ok, message = owncloud.pruefe() if configured else (False, "")
    return render("admin_storage.html", request, nav=_nav(p, "admin"),
                  configured=configured, reachable=ok, message=message,
                  description=owncloud.beschreibung() if configured else "",
                  mapping=owncloud.zuordnung_wirksam() if configured else {},
                  job=jobs.status("abgleich"))


@router.post("/ui/admin/storage/{action}")
def storage_action(action: str, request: Request,
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    if not owncloud.eingerichtet():
        raise HTTPException(409, "No storage (OpenCloud) is configured.")
    if action == "setup-rooms":
        for r in sorted(raeume.liste()):
            owncloud.richte_raum_ein(r)
        return _notice("Saved.")
    if action == "group-sync":
        owncloud.gruppen_abgleich()
        return _notice("Saved.")
    if action == "sync":
        result = jobs.start("abgleich", by=p.name)
        return _notice(tm(result.get("message", "")), result.get("started"))
    raise HTTPException(404, "Unknown action.")


# --- MAILBOXES ---

@router.get("/admin/mailboxes")
def mailboxes_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    return render("admin_mailboxes.html", request, nav=_nav(p, "admin"),
                  boxes=mailboxes.overview(), templates=mailboxes.templates())


@router.post("/ui/admin/mailboxes")
def mailbox_create(request: Request, name: str = Form(...),
                   template: str = Form(...), target: str = Form(""),
                   personal: str = Form(""), mailbox: str = Form(""),
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    options = {"postfach": mailbox} if mailbox else {}
    ok, message = mailboxes.create(name, template, target, bool(personal),
                                   **options)
    if ok:
        benutzer.protokolliere("postfach", name, p.name, template)
        return _reload("/admin/mailboxes")
    return _notice(tm(message), False)


@router.post("/ui/admin/mailboxes/{name}/delete")
def mailbox_delete(name: str, request: Request,
                   p: Principal = Depends(principal)):
    _admin(p)
    mailboxes.remove(name)
    return _reload("/admin/mailboxes")
