"""API: workspaces, documents, web sources, lists.

    GET    /workspaces                    rooms this user may read
    GET    /documents                     documents per readable room
    GET    /documents/projects            folders of the own room
    POST   /documents                     upload one document (multipart)
    POST   /documents/image-estimate      how many images an upload would describe
    DELETE /documents                     delete a document from one room
    POST   /documents/move                move a document to another room
    POST   /websources/search             search the web (only the term leaves)
    POST   /websources/read               a page as plain text
    POST   /websources/take-over          pages into the OWN room
    POST   /websources/tasks              start a search in the background
    GET    /websources/tasks              the own searches and take-overs
    GET    /websources/tasks/{id}         one, with its hits (marks it seen)
    DELETE /websources/tasks/{id}
    POST   /websources/tasks/{id}/take-over   chosen hits, in the background
    GET    /websources/notifications      finished, not yet looked at
    POST   /workspace-notes               a summary or note as a document
    GET    /files                         files created for this user
    GET    /files/{name}                  download one
    DELETE /files/{name}
    GET    /lists                         sheets this user may query
    PUT    /me/list-folder                the own list folder

There is no download of original files. The pages do not offer one
either; a source is shown as text passage and page image. A download
would pass the extraction budget (budget.py) in one request.
"""
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     UploadFile)
from fastapi.responses import Response
from pydantic import BaseModel, Field

import aufnehmen
import doc_actions
import listenquellen
import notzugang
import paths
import pipeline
import raeume
import tabellen
import web_research
import web_sources
import created_files
import workspace_notes
from server import Principal, principal

router = APIRouter()

UPLOAD_MAX_MB = paths.env_int("AUFNAHME_MAX_MB", 200)


# --- WORKSPACES ---

@router.get("/workspaces", tags=["documents"])
def workspaces(p: Principal = Depends(principal)):
    emergency = notzugang.raeume_fuer(p.name)
    with_data = {r for r, _s in pipeline.sammlungen(p.name,
                                                    notzugang=emergency)}
    writable = set(raeume.schreibbar(p.name, p.is_admin, emergency))
    return [{"id": r, "label": raeume.bezeichnung(r),
             "description": (raeume.raum(r) or {}).get("beschreibung", ""),
             "personal": raeume.ist_privat(r),
             "own": r == raeume.privat_kennung(p.name),
             "emergency": r in emergency,
             "has_data": r in with_data, "writable": r in writable,
             "web_search": raeume.websuche_erlaubt(r)}
            for r in raeume.lesbar(p.name, emergency)]


# --- DOCUMENTS ---

@router.get("/documents", tags=["documents"])
def documents(room: list[str] | None = Query(default=None),
              p: Principal = Depends(principal)):
    by_room = pipeline.dokumente(p.name, nur=room,
                                 notzugang=notzugang.raeume_fuer(p.name))
    return {r: {"label": raeume.bezeichnung(r), "files": files}
            for r, files in sorted(by_room.items())}


@router.get("/documents/projects", tags=["documents"])
def projects(room: str | None = None, p: Principal = Depends(principal)):
    """Folders of a room as projects -- for narrowing a question."""
    room = room or raeume.privat_kennung(p.name)
    return pipeline.projekte(p.name, room,
                             notzugang=notzugang.raeume_fuer(p.name))


@router.post("/documents", tags=["documents"])
def upload(file: UploadFile = File(...), room: str = Form(...),
           project: str = Form(""), images: bool = Form(False),
           vision: bool = Form(False), p: Principal = Depends(principal)):
    """Store, split and index one document in a room the user may write.

    images: describe figures and scanned pages with the vision model
    (see /documents/image-estimate first). vision: read pages the OCR
    could not read with the vision model.
    """
    content = file.file.read(UPLOAD_MAX_MB * 1024 * 1024 + 1)
    if len(content) > UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Larger than {UPLOAD_MAX_MB} MB.")
    if not content:
        raise HTTPException(400, "Empty file.")
    report = {}
    import llm
    try:
        with llm.acting_for(p.name):
            passages, note = aufnehmen.process_uploaded_pdf(
                aufnehmen.Datei(file.filename or "unnamed", content), room,
                project, images, benutzer_=p.name, ist_verwalter=p.is_admin,
                streng=True, sehmodell=vision, bericht=report)
    except aufnehmen.KeinRecht as e:
        raise HTTPException(403, str(e))
    return {"file": file.filename, "room": room, "passages": passages,
            "searchable": bool(passages),
            "ocr_pages": report.get("ocr_seiten", 0),
            "unreadable_pages": report.get("unlesbar", []), "note": note}


@router.post("/documents/image-estimate", tags=["documents"])
def image_estimate(file: UploadFile = File(...),
                   p: Principal = Depends(principal)):
    """Scanned pages and figures a PDF has -- each one a vision call."""
    import bildtext
    import pymupdf
    data = file.file.read(UPLOAD_MAX_MB * 1024 * 1024 + 1)
    if len(data) > UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Larger than {UPLOAD_MAX_MB} MB.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Not a readable PDF.")
    try:
        pages, figures = bildtext.zaehle(doc)
    finally:
        doc.close()
    return {"scanned_pages": pages, "figures": figures}


@router.delete("/documents", tags=["documents"])
def delete_document(room: str, file: str, p: Principal = Depends(principal)):
    message, report = doc_actions.delete(p.name, file, room, p.is_admin)
    return {"file": file, "room": room,
            "passages": report.get("abschnitte"),
            "storage": report.get("owncloud"), "message": message}


class Move(BaseModel):
    file: str = Field(min_length=1)
    from_room: str
    to_room: str


@router.post("/documents/move", tags=["documents"])
def move_document(body: Move, p: Principal = Depends(principal)):
    message = doc_actions.move(p.name, body.file, body.from_room,
                               body.to_room, p.is_admin)
    return {"message": message}


# --- WEB SOURCES ---

class WebSearch(BaseModel):
    query: str = Field(min_length=1, max_length=300,
                       description="goes to search engines -- keywords "
                                   "only, no internal names or numbers")
    count: int = Field(default=10, ge=1, le=20)


@router.post("/websources/search", tags=["web"])
def web_search(body: WebSearch, p: Principal = Depends(principal)):
    return [{"title": h["titel"], "url": h["adresse"], "excerpt": h["text"],
             "query": h.get("anfrage", "")}
            for h in web_sources.search(body.query, body.count)]


class WebRead(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/websources/read", tags=["web"])
def web_read(body: WebRead, p: Principal = Depends(principal)):
    """The page as plain text, fetched by the server -- not the browser."""
    try:
        text = web_sources.read(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"url": body.url, "text": text, "characters": len(text)}


class WebPage(BaseModel):
    title: str = ""
    url: str
    text: str = ""
    read: bool = Field(default=False,
                       description="text is the full page as read before")
    query: str = ""


class TakeOver(BaseModel):
    pages: list[WebPage] = Field(min_length=1, max_length=20)


@router.post("/websources/take-over", tags=["web"])
def web_take_over(body: TakeOver, p: Principal = Depends(principal)):
    """Pages become documents in the user's OWN room, folder Suchergebnisse.

    Never into a shared room: from there they can be moved on purpose
    (POST /documents/move).
    """
    return web_sources.take_over(p.name, [pg.model_dump() for pg in body.pages])


class WebTask(BaseModel):
    query: str = Field(min_length=2, max_length=200,
                       description="goes to search engines -- keywords only")
    count: int = Field(default=web_research.COUNT_DEFAULT, ge=1, le=30)


def _task_call(fn, *args):
    try:
        return fn(*args)
    except web_research.Refused as e:
        raise HTTPException(404 if "Unknown" in str(e) else 429, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/websources/tasks", tags=["web"])
def web_task_start(body: WebTask, p: Principal = Depends(principal)):
    """Starts a web search that runs on its own; poll the task or
    /websources/notifications. Results stay until the task is deleted."""
    return _task_call(web_research.start_search, p.name, body.query, body.count)


@router.get("/websources/tasks", tags=["web"])
def web_task_list(p: Principal = Depends(principal)):
    return web_research.tasks(p.name)


@router.get("/websources/tasks/{task_id}", tags=["web"])
def web_task(task_id: str, p: Principal = Depends(principal)):
    return _task_call(web_research.task_of, p.name, task_id, True)


@router.delete("/websources/tasks/{task_id}", tags=["web"])
def web_task_delete(task_id: str, p: Principal = Depends(principal)):
    _task_call(web_research.remove, p.name, task_id)
    return {"deleted": task_id}


class TaskPicks(BaseModel):
    picks: list[int] = Field(min_length=1, max_length=30,
                             description="positions in the task's hits, from 0")


@router.post("/websources/tasks/{task_id}/take-over", tags=["web"])
def web_task_take_over(task_id: str, body: TaskPicks,
                       p: Principal = Depends(principal)):
    """Chosen hits into the OWN room, read and stored in the background."""
    return _task_call(web_research.start_take_over, p.name, task_id, body.picks)


@router.get("/websources/notifications", tags=["web"])
def web_notifications(p: Principal = Depends(principal)):
    items = web_research.tasks(p.name)
    return {"running": sum(1 for t in items if t["state"] == "running"),
            "finished": [dict(id=t["id"], kind=t["kind"], state=t["state"],
                              text=web_research.summary(t))
                         for t in items if t["state"] != "running" and not t.get("seen")]}


# --- SUMMARIES AND NOTES ---

class Note(BaseModel):
    room: str = Field("", description="empty: the own room")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=workspace_notes.MAX_TEXT)
    source: str = Field("", max_length=300,
                        description="what it is based on, shown in the document")


@router.post("/workspace-notes", tags=["documents"])
def create_note(body: Note, p: Principal = Depends(principal)):
    """Store a summary or note as a Markdown document in a room the user
    may write (folder Zusammenfassungen); it is searchable right away."""
    try:
        return workspace_notes.store(p.name, body.room, body.title, body.text,
                                     body.source)
    except workspace_notes.NotWritable as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- CREATED FILES ---

_MEDIA = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "pdf": "application/pdf"}


@router.get("/files", tags=["documents"])
def created_file_list(p: Principal = Depends(principal)):
    """Files LocaNoto created for this user (Excel, Word, PDF, PowerPoint)."""
    return created_files.names(p.name)


@router.get("/files/{name}", tags=["documents"])
def created_file(name: str, p: Principal = Depends(principal)):
    from urllib.parse import quote
    try:
        data = created_files.read(p.name, name)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "No such file.")
    ext = name.rsplit(".", 1)[-1].lower()
    return Response(content=data, media_type=_MEDIA.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{quote(name)}"})


@router.delete("/files/{name}", tags=["documents"])
def delete_created_file(name: str, p: Principal = Depends(principal)):
    try:
        found = created_files.delete(p.name, name)
    except ValueError:
        found = False
    if not found:
        raise HTTPException(404, "No such file.")
    return {"deleted": name}


# --- LISTS ---

@router.get("/lists", tags=["lists"])
def lists(p: Principal = Depends(principal)):
    catalog = tabellen.lies_katalog()
    entries = tabellen.sichtbar(catalog.get("eintraege", []), p.name,
                                notzugang.raeume_fuer(p.name))
    out = {"sheets": [{k: e.get(k) for k in ("datei", "blatt", "bereich",
                                             "zeilen", "spalten", "gross",
                                             "raum") if k in e}
                      for e in entries],
           "areas": tabellen.bereiche(entries)}
    if p.is_admin:
        out["unreadable"] = catalog.get("fehler", [])
        out["folder"] = tabellen.pfad()
    return out


class ListFolder(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


@router.put("/me/list-folder", tags=["lists"])
def set_own_list_folder(body: ListFolder, p: Principal = Depends(principal)):
    """The own list folder; it must lie inside the area the admin allows."""
    if not listenquellen.eigener_bereich(p.name):
        raise HTTPException(403, "No own list folder is allowed here.")
    ok, message = listenquellen.setze_raum(raeume.privat_kennung(p.name),
                                           body.path, benutzer=p.name)
    if not ok:
        raise HTTPException(400, message)
    tabellen.baue_katalog()
    return {"message": message}
