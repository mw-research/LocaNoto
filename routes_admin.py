"""API: the admin area -- everything verwaltung.py and the admin parts of
the chat page offer.

Users        GET/POST /admin/users, PUT .../role, PUT .../password,
             DELETE /admin/users/{name}, POST /admin/users/sign,
             GET /admin/audit
Tokens       GET/POST /admin/tokens, DELETE /admin/tokens/{id}
Workspaces   GET/POST /admin/workspaces, PATCH/DELETE /admin/workspaces/{id},
             POST .../wipe, PUT .../sql-account, GET /admin/workspaces/conflicts
Foreign      GET /admin/foreign-documents, POST /admin/foreign-documents/delete,
             GET /admin/foreign-rooms
Storage      GET /admin/storage, PUT /admin/storage/mapping,
             POST /admin/storage/adopt-accounts, POST /admin/storage/setup-rooms,
             POST /admin/storage/setup-user/{name}, GET /admin/storage/plan,
             POST /admin/storage/group-sync
Backups      GET/POST /admin/backups, POST .../{name}/restore, DELETE .../{name}
Emergency    GET /admin/emergency, POST /admin/emergency/requests,
             POST .../confirm, POST .../reject, POST /admin/emergency/close
Content      GET /admin/prompts, GET/PUT/DELETE /admin/prompts/{name},
             GET/PUT /admin/glossary, PUT/DELETE /admin/presets/{name}
Feedback     GET /admin/feedback, POST .../archive, GET .../files,
             GET .../download, POST .../reencrypt
Lists        PUT /admin/lists/header, GET/PUT /admin/lists/sources,
             POST /admin/lists/upload, POST /admin/lists/rebuild
Mailboxes    GET /admin/mailboxes/templates, POST /admin/mailboxes,
             DELETE /admin/mailboxes/{name}, GET /admin/mailboxes/{name}/tools
Jobs         GET /admin/jobs, POST/DELETE /admin/jobs/{name}, GET .../log
Status       GET /admin/status

Admins only, except the emergency-access confirmation, which belongs to
the role notzugang (two different people, see notzugang.py).
Every change goes through the same functions as the pages, so their
checks and their audit entries apply.
"""
import os

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     UploadFile)
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import accounts
import auth
import benutzer
import doc_actions
import feedback
import jobs
import listenquellen
import mailboxes
import notzugang
import owncloud
import paths
import pipeline
import presets
import prompts
import raeume
import sicherung
import sqlquellen
import statefiles
import tabellen
from server import Principal, admin, principal

router = APIRouter(prefix="/admin")


def _ok(result, status=400):
    """(ok, message) of the old functions -> message or HTTP error."""
    ok, message = result[0], result[1]
    if not ok:
        raise HTTPException(status, message)
    return message


# --- USERS ---

@router.get("/users", tags=["admin"])
def users(p: Principal = Depends(admin)):
    state = benutzer.zustand()
    return {"file_state": state,
            "invalid_entries": benutzer.ungueltige(),
            "users": [{"name": n, **{k: v for k, v in
                                     (benutzer.eintrag(n) or {}).items()
                                     if not k.startswith("_")}}
                      for n in benutzer.namen()]}


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=benutzer.MIN_PASSWORT, max_length=500)
    role: str = "nutzer"


@router.post("/users", tags=["admin"])
def create_user(body: NewUser, p: Principal = Depends(admin)):
    ok, message, notes = accounts.create(body.name, body.password, body.role,
                                         by=p.name)
    if not ok:
        raise HTTPException(400, message)
    return {"message": message, "storage": notes}


class Role(BaseModel):
    role: str


@router.put("/users/{name}/role", tags=["admin"])
def set_role(name: str, body: Role, p: Principal = Depends(admin)):
    ok, message, _n = accounts.set_role(name, body.role, by=p.name)
    if not ok:
        raise HTTPException(400, message)
    return {"message": message}


class Password(BaseModel):
    password: str = Field(min_length=benutzer.MIN_PASSWORT, max_length=500)


@router.put("/users/{name}/password", tags=["admin"])
def set_password(name: str, body: Password, p: Principal = Depends(admin)):
    ok, message, notes = accounts.set_password(name, body.password, by=p.name)
    if not ok:
        raise HTTPException(400, message)
    return {"message": message, "storage": notes}


@router.delete("/users/{name}", tags=["admin"])
def delete_user(name: str, p: Principal = Depends(admin)):
    ok, message, notes = accounts.delete(name, by=p.name)
    if not ok:
        raise HTTPException(400, message)
    return {"message": message, "storage": notes}


@router.post("/users/sign", tags=["admin"])
def sign_users(p: Principal = Depends(admin)):
    """Sign the user file (after an update from an unsigned one)."""
    return {"message": _ok(benutzer.neu_signieren(von=p.name))}


@router.get("/audit", tags=["admin"])
def audit(last: int = Query(default=100, ge=1, le=5000),
          p: Principal = Depends(admin)):
    """The hash-chained audit log and whether the chain is intact."""
    check = benutzer.protokoll_pruefen()
    return {"chain": check, "entries": benutzer.protokoll(last)}


# --- TOKENS ---

@router.get("/tokens", tags=["admin"])
def tokens(p: Principal = Depends(admin)):
    return [{"id": k[:12], "user": e.get("benutzer"),
             "label": e.get("bezeichnung", ""), "created": e.get("erstellt"),
             "valid_until": e.get("gueltig_bis"), "signed": e.get("gueltig")}
            for k, e in auth.liste()]


class NewToken(BaseModel):
    user: str
    label: str = Field(default="", max_length=100)
    days: int | None = Field(default=None, ge=1, le=3650)


@router.post("/tokens", tags=["admin"])
def create_token(body: NewToken, p: Principal = Depends(admin)):
    """A token for the admin's own account. Returns it once.

    Not for other users: a token for someone else would let an admin act
    as that person -- read a personal workspace without the two-person
    emergency access. Tokens for other accounts (service accounts) are
    made with create_token.py on the server, where it is logged who did.
    """
    if body.user != p.name:
        raise HTTPException(403, "Tokens only for your own account; for "
                                 "others use create_token.py on the server.")
    token = auth.erzeuge(body.user, body.label, body.days)
    benutzer.protokolliere("token", body.user, p.name, body.label)
    return {"token": token, "user": body.user}


@router.delete("/tokens/{token_id}", tags=["admin"])
def revoke_token(token_id: str, p: Principal = Depends(admin)):
    if len(token_id) < 8:
        raise HTTPException(400, "Give at least 8 characters of the id.")
    matches = [k for k, _e in auth.liste() if k.startswith(token_id)]
    if len(matches) != 1:
        raise HTTPException(404 if not matches else 409,
                            "No such token." if not matches
                            else "Ambiguous id; give more characters.")
    auth.widerrufe(matches[0])
    benutzer.protokolliere("token_widerrufen", token_id, p.name)
    return {"revoked": 1}


# --- WORKSPACES ---

@router.get("/workspaces", tags=["admin"])
def all_workspaces(p: Principal = Depends(admin)):
    out = []
    for room, data in sorted(raeume.liste().items()):
        sml = doc_actions._collection(room, create=False)
        try:
            passages = sml.count() if sml is not None else 0
        except Exception:
            passages = None
        members, from_groups = raeume.mitglieder_gesamt(room)
        out.append({"id": room, "label": raeume.bezeichnung(room),
                    "description": data.get("beschreibung", ""),
                    "personal": raeume.ist_privat(room),
                    "members": data.get("mitglieder"),
                    "effective_members": members,
                    "group": data.get("gruppe"), "from_groups": from_groups,
                    "web_search": raeume.websuche_erlaubt(room),
                    "list_folder": listenquellen.pfad_von(room),
                    "sql_account": bool(sqlquellen.zugang(room)),
                    "passages": passages})
    return out


class NewWorkspace(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    members: list[str] | None = None


@router.post("/workspaces", tags=["admin"])
def create_workspace(body: NewWorkspace, p: Principal = Depends(admin)):
    message = _ok(raeume.anlegen(body.id, body.label, body.description,
                                 body.members))
    storage = owncloud.richte_raum_ein(body.id) \
        if owncloud.eingerichtet() else None
    benutzer.protokolliere("raum_angelegt", body.id, p.name)
    return {"message": message, "storage": storage}


class WorkspaceChange(BaseModel):
    label: str | None = None
    description: str | None = None
    members: list[str] | None = None
    open_to_all: bool | None = None
    group: str | None = None
    web_search: bool | None = None
    list_folder: str | None = None


@router.patch("/workspaces/{room}", tags=["admin"])
def change_workspace(room: str, body: WorkspaceChange,
                     p: Principal = Depends(admin)):
    if room not in raeume.liste():
        raise HTTPException(404, "No such workspace.")
    messages = []
    if body.label is not None or body.description is not None:
        messages.append(_ok(raeume.beschriften(room, body.label,
                                               body.description)))
    if body.open_to_all:
        messages.append(_ok(raeume.fuer_alle_oeffnen(room)))
    elif body.members is not None:
        messages.append(_ok(raeume.mitglieder_setzen(room, body.members)))
    if body.group is not None:
        messages.append(_ok(raeume.gruppe_setzen(room, body.group)))
    if body.web_search is not None:
        messages.append(_ok(raeume.websuche_setzen(room, body.web_search)))
    if body.list_folder is not None:
        messages.append(_ok(listenquellen.setze_raum(
            room, body.list_folder, benutzer=p.name, ist_verwalter=True)))
        tabellen.baue_katalog()
    benutzer.protokolliere("raum_geaendert", room, p.name,
                           ", ".join(k for k, v in body.model_dump().items()
                                     if v is not None))
    return {"messages": messages}


@router.delete("/workspaces/{room}", tags=["admin"])
def remove_workspace(room: str, p: Principal = Depends(admin)):
    """Remove the workspace; its passages stay (see /wipe)."""
    message = _ok(raeume.entfernen(room))
    benutzer.protokolliere("raum_entfernt", room, p.name)
    return {"message": message}


class Wipe(BaseModel):
    confirm: str = Field(description="repeat the workspace id")


@router.post("/workspaces/{room}/wipe", tags=["admin"])
def wipe_workspace(room: str, body: Wipe, p: Principal = Depends(admin)):
    """Delete every passage of a workspace. Cannot be undone."""
    try:
        ok, message, failed = doc_actions.wipe_room(p.name, True, room,
                                                    body.confirm)
    except ValueError as e:
        raise HTTPException(400, str(e))
    benutzer.protokolliere("raum_geleert", room, p.name)
    return {"ok": ok, "message": message, "storage_failures": failed,
            "latest_backup": (sicherung.liste() or [[None]])[0][0]}


class SqlAccount(BaseModel):
    benutzer: str = ""
    passwort: str = ""
    server: str | None = None
    port: int | None = None
    datenbank: str | None = None
    hinweis: str | None = None


@router.put("/workspaces/{room}/sql-account", tags=["admin"])
def set_sql_account(room: str, body: SqlAccount,
                    p: Principal = Depends(admin)):
    message = _ok(sqlquellen.setze(
        room, {k: v for k, v in body.model_dump().items() if v is not None},
        benutzer=p.name, ist_verwalter=True))
    return {"message": message}


@router.get("/workspaces/conflicts", tags=["admin"])
def workspace_conflicts(p: Principal = Depends(admin)):
    """Users whose names map to the same personal room."""
    return raeume.konflikte(benutzer.namen())


# --- FOREIGN ROOMS (delete without insight) ---

@router.get("/foreign-documents", tags=["admin"])
def foreign_documents(p: Principal = Depends(admin)):
    return [{"room": r, "file_id": f}
            for r, f in doc_actions.foreign_documents(p.name, True)]


class ForeignDelete(BaseModel):
    room: str
    file_id: str


@router.post("/foreign-documents/delete", tags=["admin"])
def delete_foreign_document(body: ForeignDelete, p: Principal = Depends(admin)):
    message, report = doc_actions.delete_foreign(p.name, True, body.room,
                                                 body.file_id)
    return {"message": message, "passages": report.get("abschnitte")}


@router.get("/foreign-rooms", tags=["admin"])
def foreign_rooms(p: Principal = Depends(admin)):
    return [{"room": r, "passages": n}
            for r, n in doc_actions.foreign_rooms(p.name, True)]


# --- STORAGE (OpenCloud) ---

def _storage_admin(p: Principal = Depends(admin)):
    if not owncloud.eingerichtet():
        raise HTTPException(409, "No storage (OpenCloud) is configured.")
    return p


@router.get("/storage", tags=["admin"])
def storage(p: Principal = Depends(admin)):
    if not owncloud.eingerichtet():
        return {"configured": False}
    ok, message = owncloud.pruefe()
    return {"configured": True, "reachable": ok, "message": message,
            "description": owncloud.beschreibung(),
            "mapping": owncloud.zuordnung(),
            "effective": owncloud.zuordnung_wirksam(),
            "last_sync": {r: owncloud.letzter_bericht(r)
                          for r in raeume.liste()},
            "managed_accounts": sorted(owncloud.verwaltete_konten())}


class Mapping(BaseModel):
    mapping: dict[str, str]


@router.put("/storage/mapping", tags=["admin"])
def set_mapping(body: Mapping, p: Principal = Depends(_storage_admin)):
    owncloud.setze_zuordnung(body.mapping)
    return {"mapping": owncloud.zuordnung()}


class Names(BaseModel):
    names: list[str]


@router.post("/storage/adopt-accounts", tags=["admin"])
def adopt_accounts(body: Names, p: Principal = Depends(_storage_admin)):
    added, skipped = owncloud.konten_uebernehmen(body.names)
    return {"adopted": added, "skipped": skipped}


@router.post("/storage/setup-rooms", tags=["admin"])
def setup_rooms(p: Principal = Depends(_storage_admin)):
    return {r: owncloud.richte_raum_ein(r) for r in sorted(raeume.liste())}


@router.post("/storage/setup-user/{name}", tags=["admin"])
def setup_user(name: str, p: Principal = Depends(_storage_admin)):
    if not benutzer.eintrag(name):
        raise HTTPException(404, "No such user.")
    return owncloud.richte_nutzer_ein(name)


@router.get("/storage/plan", tags=["admin"])
def storage_plan(room: str, p: Principal = Depends(_storage_admin)):
    """Dry run of a sync: new, changed, removed, unchanged files."""
    new, changed, removed, unchanged = owncloud.plane(room)
    return {"new": new, "changed": changed, "removed": removed,
            "unchanged": len(unchanged) if hasattr(unchanged, "__len__")
            else unchanged}


@router.post("/storage/group-sync", tags=["admin"])
def group_sync(p: Principal = Depends(_storage_admin)):
    return owncloud.gruppen_abgleich()


# --- BACKUPS ---

@router.get("/backups", tags=["admin"])
def backups(p: Principal = Depends(admin)):
    return {"folder": sicherung.ORDNER, "keep": sicherung.BEHALTEN,
            "backups": [list(b) for b in sicherung.liste()],
            "running": jobs.status("sicherung")}


@router.post("/backups", tags=["admin"])
def start_backup(p: Principal = Depends(admin)):
    return jobs.start("sicherung", by=p.name)


class Restore(BaseModel):
    overwrite: bool = Field(description="must be true: replaces data")
    room: str | None = None
    state: bool = Field(default=False,
                        description="also users, chats and settings "
                                    "(backups of a Postgres installation)")


@router.post("/backups/{name}/restore", tags=["admin"])
def restore_backup(name: str, body: Restore, p: Principal = Depends(admin)):
    if not body.overwrite:
        raise HTTPException(400, "Set overwrite=true -- a restore replaces "
                                 "the current state.")
    report = sicherung.hole_zurueck(name, nur_raum=body.room,
                                    zustand=body.state)
    benutzer.protokolliere("sicherung_zurueck", name, p.name, body.room or "")
    return report


@router.delete("/backups/{name}", tags=["admin"])
def delete_backup(name: str, force: bool = False,
                  p: Principal = Depends(admin)):
    return {"message": _ok(sicherung.entferne(name, trotzdem=force))}


# --- EMERGENCY ACCESS ---

def _emergency_viewer(p: Principal = Depends(principal)):
    if not (p.is_admin or p.is_emergency):
        raise HTTPException(403, "Admins and the role notzugang only.")
    return p


@router.get("/emergency", tags=["emergency"])
def emergency(p: Principal = Depends(_emergency_viewer)):
    return {"possible": notzugang.moeglich(),
            "description": notzugang.beschreibung(),
            "open": notzugang.offene(), "requests": notzugang.antraege()}


class EmergencyRequest(BaseModel):
    room: str
    reason: str = Field(min_length=10, max_length=500)


@router.post("/emergency/requests", tags=["emergency"])
def request_emergency(body: EmergencyRequest, p: Principal = Depends(admin)):
    return {"message": _ok(notzugang.beantrage(body.room, p.name,
                                               body.reason))}


class EmergencyDecision(BaseModel):
    room: str
    requester: str
    reason: str = ""


@router.post("/emergency/requests/confirm", tags=["emergency"])
def confirm_emergency(body: EmergencyDecision,
                      p: Principal = Depends(_emergency_viewer)):
    return {"message": _ok(notzugang.bestaetige(body.room, body.requester,
                                                p.name), 403)}


@router.post("/emergency/requests/reject", tags=["emergency"])
def reject_emergency(body: EmergencyDecision,
                     p: Principal = Depends(_emergency_viewer)):
    return {"message": _ok(notzugang.lehne_ab(body.room, body.requester,
                                              p.name, body.reason), 403)}


@router.post("/emergency/close", tags=["emergency"])
def close_emergency(body: EmergencyDecision,
                    p: Principal = Depends(_emergency_viewer)):
    return {"message": _ok(notzugang.schliesse(body.room, body.requester,
                                               p.name), 404)}


# --- PROMPTS, GLOSSARY, PRESETS ---

@router.get("/prompts", tags=["content"])
def list_prompts(p: Principal = Depends(admin)):
    return [{"name": n, "title": prompts.VORLAGEN[n].get("titel", n)}
            for n in prompts.verfuegbar()]


def _check_preset(preset):
    if preset is not None and preset not in presets.namen():
        raise HTTPException(404, "No such preset.")


@router.get("/prompts/{name}", tags=["content"])
def get_prompt(name: str, preset: str | None = None,
               p: Principal = Depends(admin)):
    _check_preset(preset)
    if name not in prompts.verfuegbar():
        raise HTTPException(404, "No such prompt.")
    text, origin = prompts.lese(name, preset)
    return {"name": name, "preset": preset, "text": text, "origin": origin}


class PromptText(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


@router.put("/prompts/{name}", tags=["content"])
def put_prompt(name: str, body: PromptText, preset: str | None = None,
               p: Principal = Depends(admin)):
    _check_preset(preset)
    if name not in prompts.verfuegbar():
        raise HTTPException(404, "No such prompt.")
    message = _ok(prompts.speichern(name, body.text, preset))
    benutzer.protokolliere("prompt", name, p.name, preset or "")
    return {"message": message}


@router.delete("/prompts/{name}", tags=["content"])
def reset_prompt(name: str, preset: str | None = None,
                 p: Principal = Depends(admin)):
    _check_preset(preset)
    if name not in prompts.verfuegbar() or \
            not prompts.zuruecksetzen(name, preset):
        raise HTTPException(404, "Nothing to reset.")
    return {"message": "Reset to the shipped template."}


@router.get("/glossary", tags=["content"])
def get_glossary(p: Principal = Depends(admin)):
    path = paths.resolve_glossar()
    try:
        text = statefiles.read_text(path)
    except OSError:
        text = ""
    return {"text": text, "entries": len(pipeline.glossar() or {})}


@router.put("/glossary", tags=["content"])
def put_glossary(body: PromptText, p: Principal = Depends(admin)):
    import dateisperre
    dateisperre.schreibe_atomar(paths.GLOSSAR_FILE, body.text)
    benutzer.protokolliere("glossar", "glossar", p.name)
    return {"entries": len(pipeline.glossar() or {})}


class SharedPreset(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=120)
    beschreibung: str = ""
    chat_modell: str = ""
    top_k: int = Field(default=0, ge=0, le=30)
    listen_bereiche: list[str] = Field(default_factory=list)


@router.put("/presets/{name}", tags=["content"])
def put_shared_preset(name: str, body: SharedPreset,
                      p: Principal = Depends(admin)):
    message = _ok(presets.speichern(name, body.model_dump()))
    return {"message": message, "preset": presets.lese(name)}


@router.delete("/presets/{name}", tags=["content"])
def delete_shared_preset(name: str, p: Principal = Depends(admin)):
    if name not in presets.namen() or not presets.loesche(name):
        raise HTTPException(404, "No such preset.")
    return {"deleted": name}


# --- FEEDBACK ---

@router.get("/feedback", tags=["feedback"])
def get_feedback(limit: int = Query(default=15, ge=1, le=1000),
                 p: Principal = Depends(admin)):
    return {"counts": feedback.zaehle(),
            "empty": feedback.lese(grenze=limit, art="leer"),
            "thumbs_down": feedback.lese(grenze=limit, art="daumen_runter")}


@router.post("/feedback/archive", tags=["feedback"])
def archive_feedback(p: Principal = Depends(admin)):
    return {"archived_as": feedback.archiviere()}


@router.get("/feedback/files", tags=["feedback"])
def feedback_files(p: Principal = Depends(admin)):
    return {"current": statefiles.exists(feedback.DATEI),
            "archives": feedback.ablagen()}


@router.get("/feedback/download", tags=["feedback"],
            response_class=PlainTextResponse)
def download_feedback(file: str | None = None, p: Principal = Depends(admin)):
    """The log as JSON lines (decrypted). Without file: the current one."""
    if not file:
        return PlainTextResponse(feedback.als_text())
    if file not in feedback.ablagen():
        raise HTTPException(404, "No such archive.")
    path = os.path.join(os.path.dirname(feedback.DATEI), file)
    return PlainTextResponse(statefiles.read_text(path, errors="replace"))


@router.post("/feedback/reencrypt", tags=["feedback"])
def reencrypt_feedback(p: Principal = Depends(admin)):
    before = feedback.klartextzeilen()
    result = feedback.neu_verschluesseln()
    return {"plain_lines_before": before, "result": result}


# --- LISTS ---

class HeaderRow(BaseModel):
    file: str
    sheet: str = ""
    row: int = Field(ge=0)


@router.put("/lists/header", tags=["lists"])
def set_header_row(body: HeaderRow, p: Principal = Depends(admin)):
    result = tabellen.setze_kopfzeile(body.file, body.sheet, body.row)
    tabellen.baue_katalog()
    return {"result": result}


@router.get("/lists/sources", tags=["lists"])
def list_sources(p: Principal = Depends(admin)):
    return {"sources": listenquellen.liste(),
            "description": listenquellen.beschreibung(),
            "old_folder": tabellen.alter_ordner()}


class ListSources(BaseModel):
    sources: list[dict]


@router.put("/lists/sources", tags=["lists"])
def put_list_sources(body: ListSources, p: Principal = Depends(admin)):
    message = _ok(listenquellen.speichere(body.sources))
    tabellen.baue_katalog()
    return {"message": message}


@router.post("/lists/upload", tags=["lists"])
def upload_list(file: UploadFile = File(...), area: str = Form(""),
                p: Principal = Depends(admin)):
    if not tabellen.beschreibbar():
        raise HTTPException(409, "The list folder is read-only.")
    message = _ok(tabellen.lege_ab(file.file.read(),
                                   file.filename or "list.xlsx", area))
    tabellen.baue_katalog()
    return {"message": message}


@router.post("/lists/rebuild", tags=["lists"])
def rebuild_lists(p: Principal = Depends(admin)):
    catalog, unreadable = tabellen.baue_katalog()
    return {"sheets": len(catalog.get("eintraege", [])),
            "unreadable": [list(f) for f in unreadable]}


# --- MAILBOXES ---

@router.get("/mailboxes/templates", tags=["mailboxes"])
def mailbox_templates(p: Principal = Depends(admin)):
    return mailboxes.templates()


class NewMailbox(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    template: str
    target: str = Field(default="", description="address, command or "
                                                 "Exchange server")
    personal: bool = True
    options: dict = Field(default_factory=dict,
                          description="postfach, automatisch, hinweis, "
                                      "hinweis_anhaengen, sendet, textfeld")


@router.post("/mailboxes", tags=["mailboxes"])
def create_mailbox(body: NewMailbox, p: Principal = Depends(admin)):
    message = _ok(mailboxes.create(body.name, body.template, body.target,
                                   body.personal, **body.options))
    benutzer.protokolliere("postfach", body.name, p.name, body.template)
    return {"message": message}


@router.delete("/mailboxes/{name}", tags=["mailboxes"])
def delete_mailbox(name: str, p: Principal = Depends(admin)):
    return {"message": _ok(mailboxes.remove(name), 404)}


@router.get("/mailboxes/{name}/tools", tags=["mailboxes"])
def mailbox_tools(name: str, p: Principal = Depends(admin)):
    return mailboxes.tools(name)


# --- JOBS ---

@router.get("/jobs", tags=["jobs"])
def list_jobs(p: Principal = Depends(admin)):
    return jobs.overview()


@router.post("/jobs/{name}", tags=["jobs"])
def start_job(name: str, p: Principal = Depends(admin)):
    return jobs.start(name, by=p.name)


@router.delete("/jobs/{name}", tags=["jobs"])
def cancel_job(name: str, p: Principal = Depends(admin)):
    return jobs.cancel(name, by=p.name)


@router.get("/jobs/{name}/log", tags=["jobs"],
            response_class=PlainTextResponse)
def job_log(name: str, lines: int = Query(default=50, ge=1, le=5000),
            p: Principal = Depends(admin)):
    return PlainTextResponse(jobs.log(name, lines))


# --- STATUS ---

@router.get("/status", tags=["status"])
def status(p: Principal = Depends(admin)):
    import budget
    import database
    import envcheck
    import geheim
    import keyword_index
    import sicherheit
    import store
    out = {"security": sicherheit.lage(),
           "encryption": geheim.beschreibung(),
           "store": store.beschreibung(),
           "keyword_index": keyword_index.journal_modus(),
           "storage_roots": paths.wurzeln(),
           "budget": budget.beschreibung(),
           "env_drift": envcheck.vergleiche()}
    if database.active():
        out["database"] = database.vector_settings()
    return out
