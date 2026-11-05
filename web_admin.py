"""Admin pages of the web interface beyond users, workspaces and jobs.

    /admin/backups      list, back up now, restore (with state)
    /admin/emergency    requests and open grants; request, confirm, reject, close
    /admin/content      prompt templates and the glossary
    /admin/feedback     empty answers and thumbs down; archive
    /admin/storage      OpenCloud: status, set up workspaces, group sync
    /admin/mailboxes    mailboxes and web search services; ticket system of
                        shared mailboxes (tickets.py)
    /admin/lists        list folders per workspace, catalog, read again
    /admin/databases    SQL databases per workspace: shared account or personal logins

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
import listenquellen
import mailboxes
import notzugang
import owncloud
import paths
import prompts
import raeume
import sicherung
import sqlquellen
import statefiles
import tabellen
import tickets
from server import Principal, principal
from web import _need, _nav, _notice, page_language, render, t, tm

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


# --- LISTS ---

@router.get("/admin/lists")
def lists_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    catalog = tabellen.lies_katalog()
    sheets = sorted(tabellen.sichtbar(catalog.get("eintraege", []), p.name),
                    key=lambda e: (e.get("raum") or "", e.get("datei") or "",
                                   e.get("blatt") or ""))
    folders = [(r, raeume.bezeichnung(r), listenquellen.pfad_von(r))
               for r in sorted(raeume.liste()) if not raeume.ist_privat(r)]
    return render("admin_lists.html", request, nav=_nav(p, "admin"),
                  folders=folders, sheets=sheets,
                  errors=catalog.get("fehler") or [],
                  pattern=listenquellen.pfad_von(listenquellen.MUSTER_RAUM),
                  pattern_room=listenquellen.MUSTER_RAUM,
                  roots=listenquellen.WURZELN,
                  description=tm(listenquellen.beschreibung()))


@router.post("/ui/admin/lists/folder")
def lists_folder(request: Request, room: str = Form(...), path: str = Form(""),
                 p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    if room != listenquellen.MUSTER_RAUM and room not in raeume.liste():
        raise HTTPException(404, "Unknown workspace.")
    if room == listenquellen.MUSTER_RAUM and path.strip() \
            and listenquellen.PLATZHALTER not in path:
        # The root of the personal folders: each user gets <root>/<name>.
        path = path.strip().rstrip("/") + "/" + listenquellen.PLATZHALTER
    ok, message = listenquellen.setze_raum(room, path, benutzer=p.name,
                                           ist_verwalter=True)
    if not ok:
        return _notice(tm(message), False)
    tabellen.baue_katalog()
    return _reload("/admin/lists")


@router.post("/ui/admin/lists/rebuild")
def lists_rebuild(request: Request, p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    tabellen.baue_katalog()
    return _reload("/admin/lists")


# --- DATABASES ---

@router.get("/admin/databases")
def databases_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    entries = []
    for z in sqlquellen.liste():
        room = z.get("raum")
        entries.append({"room": room, "label": raeume.bezeichnung(room),
                        "server": z.get("server", ""), "port": z.get("port", ""),
                        "database": z.get("datenbank", ""),
                        "shared": z.get("benutzer", "") if z.get("passwort") else ""})
    targets = [(r, raeume.bezeichnung(r)) for r in sorted(raeume.liste())
               if not raeume.ist_privat(r)]
    return render("admin_databases.html", request, nav=_nav(p, "admin"),
                  entries=entries, targets=targets)


@router.post("/ui/admin/databases/{room}/test")
def database_test(room: str, request: Request, p: Principal = Depends(principal)):
    """Connects with the stored settings and reads the table list."""
    import answering
    import sqldb
    _admin(p)
    page_language(p.name)
    access = sqlquellen.zugang(room)
    if not access:
        return _notice(t("Unknown database."), False)
    if not (access.get("benutzer") and access.get("passwort")):
        return _notice(t("No shared account: members test with their own login under Settings."))
    try:
        schema = sqldb.lade_schema(access)
    except Exception as e:
        return _notice(f"{type(e).__name__}: {str(e)[:400]}", False)
    answering.forget_schema(room)
    tables = sum(1 for line in (schema or "").splitlines() if line.strip())
    return _notice(t("Connected.") + (f" {tables} " + t("tables") if tables else "")
                   + (" " + t("but no readable tables") if not schema else ""), bool(schema))


# --- MAILBOXES ---

@router.get("/admin/mailboxes")
def mailboxes_page(request: Request):
    p, away = _page(request)
    if away:
        return away
    boxes = mailboxes.overview()
    shared = [b["name"] for b in boxes
              if b["kind"] == "mailbox" and not b["personal"]]
    return render("admin_mailboxes.html", request, nav=_nav(p, "admin"),
                  boxes=boxes, templates=mailboxes.templates(),
                  notice_default=mailboxes.NOTICE_DEFAULT,
                  ticket_boxes=[(n, tickets.settings(n)) for n in shared])


@router.post("/ui/admin/mailboxes/{name}/tickets")
def mailbox_tickets(name: str, request: Request, enabled: str = Form(""),
                    answer: str = Form(""), members: str = Form(""),
                    forward: str = Form(""), prefix: str = Form("T"),
                    p: Principal = Depends(principal)):
    """Ticket system of a shared mailbox (tickets.configure)."""
    _admin(p)
    page_language(p.name)
    split = lambda text: [x.strip() for x in text.replace(";", ",").split(",") if x.strip()]
    ok, message = tickets.configure(
        name, bool(enabled), answer, split(members), split(forward), prefix)
    if ok:
        benutzer.protokolliere("tickets", name, p.name, "on" if enabled else "off")
        return _reload("/admin/mailboxes")
    return _notice(t(message), False)


@router.post("/ui/admin/mailboxes/{name}/tickets/check")
def mailbox_tickets_check(name: str, request: Request,
                          p: Principal = Depends(principal)):
    """Checks the mailbox now, with the admin's own login from the session
    (Settings > Mailboxes) -- the same a member's open page does every minute."""
    _admin(p)
    page_language(p.name)
    import sessions
    from server import SEALED_COOKIE
    header = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE)).get(name)
    try:
        first = not tickets._load(name).get("since")
        n = tickets.poll_once(name, header=header)
    except Exception as e:
        return _notice(t(str(e)[:300]) or type(e).__name__, False)
    if first:
        return _notice(t("First check: from now on new mail becomes a ticket."))
    return _notice(f"{n} " + t("new mail(s)"))


@router.post("/ui/admin/mailboxes")
def mailbox_create(request: Request, name: str = Form(...),
                   template: str = Form(...), target: str = Form(""),
                   personal: str = Form(""), mailbox: str = Form(""),
                   auto: str = Form(""), notice: str = Form(""),
                   notice_text: str = Form(""),
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    options = {"postfach": mailbox} if mailbox else {}
    # The same three settings as in the classic page: a shared mailbox may
    # answer on its own, by default with a notice under each such mail.
    # mcp.lege_an drops "automatisch" for personal mailboxes.
    options.update(automatisch=bool(auto), hinweis_anhaengen=bool(notice),
                   hinweis=notice_text.strip() or None)
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
