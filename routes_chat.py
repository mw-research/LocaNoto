"""API: asking, chats, drafts, feedback, source pages.

    POST   /ask                       answer a question; ?stream=true for SSE
    GET    /chats                     own chats, newest first
    GET    /chats/{id}                messages of a chat
    PUT    /chats/{id}                rename
    DELETE /chats/{id}
    GET    /chats/{id}/messages/{i}/images/{j}    an attached image
    POST   /chats/{id}/drafts/{draft}/send        send a prepared mail
    POST   /chats/{id}/drafts/{draft}/discard
    POST   /feedback                  thumbs up / down on an answer
    GET    /sources/page              a PDF page of a source as PNG

The answer flow is answering.ask -- the same for every front end. Server
paths never leave the server: attached images are addressed by message
and position, not by where they lie.
"""
import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

import answering
import aufnehmen
import chats
import feedback
import mailboxes
import notzugang
import raeume
import statefiles
import vision
from routes_account import mailbox_headers
from server import Principal, principal

router = APIRouter()

MAX_IMAGE_BYTES = 15 * 1024 * 1024


class Image(BaseModel):
    name: str = Field(max_length=200)
    data_base64: str


class MailboxLogin(BaseModel):
    user: str = ""
    secret: str


class AskBody(BaseModel):
    question: str = Field(default="", max_length=8000)
    chat_id: str | None = Field(
        default=None, description="continue this chat; empty starts a new one")
    images: list[Image] = Field(default_factory=list, max_length=8)
    rooms: list[str] | None = Field(
        default=None, description="only these rooms; others are dropped "
                                  "silently (an error would tell they exist)")
    files: list[str] | None = None
    project: str | None = Field(default=None,
                                description="folder in the own room")
    preset: str | None = None
    model: str | None = None
    top_k: int = Field(default=0, ge=0, le=30)
    sql: bool = False
    sql_room: str | None = None
    lists: bool = True
    list_areas: list[str] | None = None
    lists_large: bool = False
    web: bool = False
    mailboxes: dict[str, MailboxLogin] = Field(
        default_factory=dict,
        description="mailbox logins for this question only; never stored")
    history: list[dict] | None = Field(
        default=None, description="with save=false: earlier messages")
    save: bool = Field(default=True, description="keep the chat")
    source_texts: bool = Field(default=True,
                               description="include the passages")


def _request(p, body, http_request):
    images = []
    for img in body.images:
        try:
            data = base64.b64decode(img.data_base64, validate=True)
        except ValueError:
            raise HTTPException(400, f"Image '{img.name}' is not base64.")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, f"Image '{img.name}' is too large.")
        images.append((img.name, data))
    return answering.Request(
        question=body.question, chat_id=body.chat_id, images=images,
        rooms=body.rooms, files=body.files, project=body.project,
        preset=body.preset, model=body.model, top_k=body.top_k,
        sql=body.sql, sql_room=body.sql_room, lists=body.lists,
        list_areas=body.list_areas, lists_large=body.lists_large,
        web=body.web,
        mailboxes=mailbox_headers(p, http_request,
                                  {k: v.model_dump()
                                   for k, v in body.mailboxes.items()}),
        history=body.history, save=body.save)


def public_message(m, with_texts=True):
    """A stored message as the API shows it: no server paths."""
    out = {k: v for k, v in m.items() if k != "bilder"}
    if m.get("bilder"):
        out["images"] = len(m["bilder"])
    if not with_texts and out.get("sources"):
        out["sources"] = [{k: v for k, v in s.items() if k != "texts"}
                          | {"passages": len(s.get("texts") or [])}
                          for s in out["sources"]]
    return out


@router.post("/ask", tags=["chat"])
def ask(body: AskBody, http_request: Request,
        stream: bool = Query(default=False,
                             description="answer as text/event-stream"),
        p: Principal = Depends(principal)):
    """Answer a question from the documents this user may read.

    Everything the chat page does: images (described by the vision
    model), search probes, hybrid search, database and lists, mailbox and
    web search tools, the streamed answer, the chat saved with sources.

    With stream=true the events of answering.ask arrive as server-sent
    events (chat, probes, search, sql, lists, tool, text, done, error).
    """
    req = _request(p, body, http_request)
    if not stream:
        status, result = answering.answer(p.name, req)
        if status != 200:
            raise HTTPException(status, result.get("detail"))
        if result.get("message"):
            result["message"] = public_message(result["message"],
                                               body.source_texts)
        return result

    def events():
        for event, data in answering.ask(p.name, req):
            if event == "done":
                data = dict(data, message=public_message(
                    data["message"], body.source_texts))
            yield (f"event: {event}\n"
                   f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n")

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- CHATS ---

def _own_chat(p, chat_id):
    if chat_id not in {k for k, _t, _g in chats.liste(p.name)}:
        raise HTTPException(404, "Unknown chat.")


@router.get("/chats", tags=["chat"])
def list_chats(p: Principal = Depends(principal)):
    return [{"id": k, "title": t, "changed": g}
            for k, t, g in chats.liste(p.name)]


@router.get("/chats/{chat_id}", tags=["chat"])
def get_chat(chat_id: str, p: Principal = Depends(principal)):
    _own_chat(p, chat_id)
    return {"id": chat_id, "title": chats.titel(p.name, chat_id),
            "messages": [public_message(m)
                         for m in chats.lade(p.name, chat_id)]}


class Rename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.put("/chats/{chat_id}", tags=["chat"])
def rename_chat(chat_id: str, body: Rename, p: Principal = Depends(principal)):
    _own_chat(p, chat_id)
    chats.benenne(p.name, chat_id, answering.clean_title(body.title))
    return {"id": chat_id, "title": chats.titel(p.name, chat_id)}


@router.delete("/chats/{chat_id}", tags=["chat"])
def delete_chat(chat_id: str, p: Principal = Depends(principal)):
    _own_chat(p, chat_id)
    chats.loesche(p.name, chat_id)
    return {"deleted": chat_id}


@router.get("/chats/{chat_id}/messages/{index}/images/{position}",
            tags=["chat"])
def chat_image(chat_id: str, index: int, position: int,
               p: Principal = Depends(principal)):
    _own_chat(p, chat_id)
    messages = chats.lade(p.name, chat_id)
    try:
        path = messages[index]["bilder"][position]
    except (IndexError, KeyError, TypeError):
        raise HTTPException(404, "No such image.")
    data = vision.lade(path)
    if data is None:
        raise HTTPException(404, "Image not readable.")
    return Response(content=data, media_type="image/jpeg")


# --- DRAFTS ---

class SendDraft(BaseModel):
    mailboxes: dict[str, MailboxLogin] = Field(default_factory=dict)


@router.post("/chats/{chat_id}/drafts/{draft_id}/send", tags=["mailboxes"])
def send_draft(chat_id: str, draft_id: str, body: SendDraft,
               http_request: Request, p: Principal = Depends(principal)):
    """Send exactly the stored draft, once. Its content cannot be changed."""
    headers = mailbox_headers(p, http_request,
                              {k: v.model_dump()
                               for k, v in body.mailboxes.items()})
    try:
        result = mailboxes.send_draft(p.name, chat_id, draft_id, headers)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"sent": draft_id, "result": result[:2000]}


@router.post("/chats/{chat_id}/drafts/{draft_id}/discard", tags=["mailboxes"])
def discard_draft(chat_id: str, draft_id: str,
                  p: Principal = Depends(principal)):
    mailboxes.discard_draft(p.name, chat_id, draft_id)
    return {"discarded": draft_id}


# --- FEEDBACK ---

class Feedback(BaseModel):
    kind: str = Field(description="daumen_hoch or daumen_runter")
    question: str = Field(min_length=1, max_length=2000)
    probes: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)


@router.post("/feedback", tags=["chat"])
def give_feedback(body: Feedback, p: Principal = Depends(principal)):
    if body.kind not in ("daumen_hoch", "daumen_runter") or \
            not feedback.notiere(body.kind, p.name, body.question,
                                 sonden=body.probes, quellen=body.sources,
                                 herkunft="schnittstelle"):
        raise HTTPException(400, "kind must be daumen_hoch or daumen_runter.")
    return {"status": "noted"}


# --- SOURCE PAGES ---

@router.get("/sources/page", tags=["chat"])
def source_page(room: str, file: str, page: int = Query(ge=1),
                dpi: int = Query(default=150, ge=50, le=300),
                p: Principal = Depends(principal)):
    """One page of a source PDF as image -- only from a readable room."""
    emergency = notzugang.raeume_fuer(p.name)
    if not raeume.darf_lesen(p.name, room, emergency):
        raise HTTPException(404, "No such source.")
    # The file must be a document of THIS room. The path lookup alone
    # would also find files of removed workspaces lying on the disk.
    import pipeline
    if file not in pipeline.dokumente(p.name, nur=[room],
                                      notzugang=emergency).get(room, []):
        raise HTTPException(404, "No such source.")
    path = aufnehmen.dokument_pfad(file, room)
    if not file.lower().endswith(".pdf") or not path \
            or not statefiles.exists(path):
        raise HTTPException(404, "No such source.")
    import pymupdf
    try:
        doc = pymupdf.open(path)
        try:
            png = doc.load_page(page - 1).get_pixmap(dpi=dpi).tobytes("png")
        finally:
            doc.close()
    except (ValueError, IndexError, RuntimeError):
        raise HTTPException(404, "No such page.")
    return Response(content=png, media_type="image/png")
