"""Mailboxes (Exchange or MCP servers) for users and admins, without a page.

USER SIDE

    overview()                       which mailboxes exist, which need a login
    header_for(server, user, secret) the login header for one server
    check(server, header)            log in once and list the tools
    send_draft(user, chat_id, draft_id, headers)
                                     send a draft the model prepared

Credentials never stay on the server. A client sends them with each
request that needs them (or keeps them sealed in its session cookie, see
sessions.py); here they live for the duration of a call. That is the
rule the Streamlit page follows with its session memory, and it is the
only one that holds when every request may reach another pod.

Drafts: a tool that sends something is not run during an answer, it is
stored as a draft in the (encrypted) chat message. send_draft runs
exactly the stored call -- the client names it, it cannot change it --
and marks it sent, so it is sent once.

ADMIN SIDE

    templates()                      the kinds of servers (mcp.VORLAGEN)
    create(name, template, target, personal, **options)
    remove(name)
    tools(server, header=None)       what a server offers, which tools send
"""
import chats
import mcp


class NotFound(Exception):
    pass


def overview():
    out = []
    for name, a in sorted(mcp.lies_konfiguration().items()):
        out.append({"name": name,
                    "kind": "websearch" if a.get("art") == "websuche"
                    else "mailbox",
                    "transport": a.get("transport", "http"),
                    "login": mcp.anmeldeart(name),
                    "personal": bool(a.get("persoenlich")),
                    "auto_reply": bool(a.get("automatisch"))})
    return out


def header_for(server, user="", secret=""):
    if server not in mcp.lies_konfiguration():
        raise NotFound(f"No mailbox '{server}'.")
    return mcp.kopf_fuer(server, user, secret)


def check(server, header):
    """Log in once. Returns the tool names; raises on a failed login."""
    connections = mcp.verbinde({server: header},
                               ohne=set(mcp.lies_konfiguration()) - {server})
    try:
        if server not in connections:
            raise NotFound(f"No mailbox '{server}'.")
        return [t.get("name") for t in connections[server].werkzeuge()]
    finally:
        for c in connections.values():
            try:
                c.schliesse()
            except Exception:
                pass


def drafts(user, chat_id):
    """[(message_index, draft)] of a chat, with their state."""
    out = []
    for i, m in enumerate(chats.lade(user, chat_id)):
        for d in m.get("entwuerfe") or []:
            out.append((i, d))
    return out


def _find_draft(messages, draft_id):
    for m in messages:
        for d in m.get("entwuerfe") or []:
            if d.get("id") == draft_id:
                return d
    return None


def send_draft(user, chat_id, draft_id, headers):
    """Run a stored draft once. Returns the server's answer as text."""
    if chat_id not in {k for k, _t, _g in chats.liste(user)}:
        raise NotFound("Unknown chat.")
    messages = chats.lade(user, chat_id)
    draft = _find_draft(messages, draft_id)
    if draft is None:
        raise NotFound("Unknown draft.")
    if draft.get("state") in ("sent", "discarded", "sending"):
        raise ValueError(f"Draft already {draft['state']}.")
    # Claim it before sending, under the chat lock: a second click finds
    # "sending" and stops.
    import dateisperre
    with dateisperre.gesperrt(chats._index_pfad(user)):
        messages = chats.lade(user, chat_id)
        draft = _find_draft(messages, draft_id)
        if draft is None or draft.get("state"):
            raise ValueError("Draft already handled.")
        draft["state"] = "sending"
        chats.speichere(user, chat_id, messages)
    server = draft["server"]
    connections = mcp.verbinde({server: (headers or {}).get(server)},
                               ohne=set(mcp.lies_konfiguration()) - {server})
    try:
        if server not in connections:
            raise NotFound(f"No mailbox '{server}'.")
        result = connections[server].rufe(draft["werkzeug"],
                                          draft.get("argumente") or {})
    except Exception:
        _set_state(user, chat_id, draft_id, None)   # free it for a retry
        raise
    finally:
        for c in connections.values():
            try:
                c.schliesse()
            except Exception:
                pass
    _set_state(user, chat_id, draft_id, "sent")
    return str(result)


def _set_state(user, chat_id, draft_id, state):
    import dateisperre
    with dateisperre.gesperrt(chats._index_pfad(user)):
        messages = chats.lade(user, chat_id)
        draft = _find_draft(messages, draft_id)
        if draft is not None:
            if state is None:
                draft.pop("state", None)
            else:
                draft["state"] = state
            chats.speichere(user, chat_id, messages)


def discard_draft(user, chat_id, draft_id):
    if chat_id not in {k for k, _t, _g in chats.liste(user)}:
        raise NotFound("Unknown chat.")
    messages = chats.lade(user, chat_id)
    draft = _find_draft(messages, draft_id)
    if draft is None:
        raise NotFound("Unknown draft.")
    draft["state"] = "discarded"
    chats.speichere(user, chat_id, messages)


# --- ADMIN ---

def templates():
    return {k: v["beschreibung"] for k, v in mcp.VORLAGEN.items()}


def create(name, template, target, personal=True, **options):
    return mcp.lege_an(name, template, target, persoenlich=personal,
                       **options)


def remove(name):
    return mcp.entferne_postfach(name)


def tools(server, header=None):
    connections = mcp.verbinde({server: header} if header else None,
                               ohne=set(mcp.lies_konfiguration()) - {server})
    try:
        if server not in connections:
            raise NotFound(f"No mailbox '{server}'.")
        return [{"name": t.get("name"),
                 "description": t.get("beschreibung", ""),
                 "sends": mcp.sendet(server, t.get("name"))}
                for t in connections[server].werkzeuge()]
    finally:
        for c in connections.values():
            try:
                c.schliesse()
            except Exception:
                pass
