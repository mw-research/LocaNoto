"""Tickets of shared mailboxes in the web interface (tickets.py).

    /tickets                      the tickets of the mailboxes one is member of
    /tickets?box=...&id=...       one ticket: text, history, take it, status, note
    POST /ui/tickets/{box}/{id}   take, release, set status, add a note

Members of a mailbox's ticket system see its tickets; admins see all.
"Answer in the chat" opens the chat with the ticket as the question; the
answer goes out through the user's own mailbox tools, as a draft.
"""
import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import quote

import local_time
import tickets
from server import Principal, principal
from web import _env, _nav, _need, _notice, page_language, render, t

router = APIRouter(include_in_schema=False)


def _local(iso):
    """'05.11.2026 14:32' in the installation's time zone."""
    if not iso:
        return ""
    try:
        return datetime.datetime.fromisoformat(iso).astimezone(
            local_time.zone()).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(iso)[:16]


_env.filters["local_time"] = _local


@router.get("/tickets")
def tickets_page(request: Request, box: str = "", id: str = "", status: str = ""):
    p = _need(request)
    boxes = tickets.boxes_for(p.name, p.is_admin)
    if not boxes:
        return RedirectResponse("/", status_code=303)
    box = box if box in boxes else boxes[0]
    items = tickets.tickets_of(box)
    if status in tickets.STATUSES:
        items = [x for x in items if x["status"] == status]
    elif status != "all":
        items = [x for x in items if x["status"] != "closed"]
    current = tickets.ticket(box, id) if id else None
    import sessions
    from server import SEALED_COOKIE
    connected = box in sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
    return render("tickets.html", request, nav=_nav(p, "tickets"), boxes=boxes,
                  box=box, items=items, status=status, current=current,
                  statuses=tickets.STATUSES, me=p.name,
                  connected=connected, check=tickets.status(box))


@router.post("/ui/tickets/{box}/{ticket_id}")
def ticket_change(box: str, ticket_id: str, request: Request,
                  action: str = Form(""), status: str = Form(""),
                  note: str = Form(""), p: Principal = Depends(principal)):
    page_language(p.name)
    if box not in tickets.boxes_for(p.name, p.is_admin):
        raise HTTPException(404, "Unknown mailbox.")
    try:
        if action == "take":
            tickets.update(box, ticket_id, p.name, assignee=p.name)
        elif action == "release":
            tickets.update(box, ticket_id, p.name, assignee="")
        elif action == "status":
            tickets.update(box, ticket_id, p.name, status=status)
        elif action == "note" and note.strip():
            tickets.update(box, ticket_id, p.name, note=note.strip())
    except tickets.Refused as e:
        return _notice(t(str(e)), False)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = (f"/tickets?box={quote(box)}"
                                       f"&id={quote(ticket_id)}")
    return response
