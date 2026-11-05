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
and marks it sent, so it is sent once. A summary for a workspace
(workspace_notes, server "workspace") is a draft of the same kind.

When the server does not answer in time, a mail may still have gone out.
Before reporting a failure send_draft looks into the sent folder (the
calendar for an entry): found means sent. Not found means failed, and
the draft can be sent again; could not look means "unclear" -- the user
is told to check the sent folder before sending again. Every outcome is
kept in the draft (state, result or error), so the next question in the
chat knows it (pipeline.history_for_model).

ADMIN SIDE

    templates()                      the kinds of servers (mcp.VORLAGEN)
    create(name, template, target, personal, **options)
    remove(name)
    tools(server, header=None)       what a server offers, which tools send
"""
import attachments
import chats
import mcp
import workspace_notes


class NotFound(Exception):
    pass


class SendFailed(Exception):
    """A draft did not go out (state "failed") or may have ("unclear")."""

    def __init__(self, message, state):
        super().__init__(message)
        self.state = state


NOTICE_DEFAULT = mcp.HINWEIS_VORGABE


def overview():
    out = []
    for name, a in sorted(mcp.lies_konfiguration().items()):
        out.append({"name": name,
                    "kind": "websearch" if a.get("art") == "websuche"
                    else "mailbox",
                    "transport": a.get("transport", "http"),
                    "login": mcp.anmeldeart(name),
                    "personal": bool(a.get("persoenlich")),
                    "mailbox": a.get("postfach") or "",
                    "auto_reply": bool(a.get("automatisch")),
                    "notice": bool(a.get("automatisch")) and mcp.hinweis_an(name)})
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
    if draft.get("state") in DONE:
        raise ValueError(f"Draft already {draft['state']}.")
    if draft.get("kind") == "web":
        raise ValueError("A web search is confirmed in the chat.")
    # Claim it before sending, under the chat lock: a second click finds
    # "sending" and stops.
    import dateisperre
    with dateisperre.gesperrt(chats._index_pfad(user)):
        messages = chats.lade(user, chat_id)
        draft = _find_draft(messages, draft_id)
        if draft is None or draft.get("state") in DONE:
            raise ValueError("Draft already handled.")
        draft["state"] = "sending"
        draft.pop("error", None)
        chats.speichere(user, chat_id, messages)
    server = draft["server"]
    if server == workspace_notes.SERVER:
        # Built in, no login: it stores as the user who confirms, with
        # the permissions they have at the moment of the click.
        connections = {server: workspace_notes.Tools(user)}
    else:
        connections = mcp.verbinde({server: (headers or {}).get(server)},
                                   ohne=set(mcp.lies_konfiguration()) - {server})
        for c in connections.values():
            if hasattr(c, "attachment_source"):
                c.attachment_source = attachments.source(user, chat_id)
    import postfach
    known = {}
    for m in messages:
        known.update(m.get("ids") or {})
    postfach.load_ids(known)
    try:
        if server not in connections:
            raise NotFound(f"No mailbox '{server}'.")
        result = connections[server].rufe(draft["werkzeug"],
                                          draft.get("argumente") or {})
    except (ValueError, NotFound) as e:
        # Refused before anything went out (a permission, a missing
        # field): the caller says why; the draft may be confirmed again.
        _set_state(user, chat_id, draft_id, "failed", error=str(e)[:300])
        raise
    except Exception as e:
        state, text = _after_error(connections.get(server), draft, e)
        _set_state(user, chat_id, draft_id, state,
                   **({"result": text} if state == "sent" else {"error": text}))
        if state == "sent":
            return text
        raise SendFailed(text, state)
    finally:
        for c in connections.values():
            try:
                c.schliesse()
            except Exception:
                pass
    _set_state(user, chat_id, draft_id, "sent", result=str(result)[:500])
    return str(result)


DONE = ("sent", "discarded", "sending")

# Errors that come before anything is handed to the server: nothing can
# have gone out, there is nothing to look for.
BEFORE_SENDING = ("nicht angemeldet", "Anmeldedaten", "Unbekannte Kennung",
                  "gehoert nicht zu", "Kein Empfaenger", "Anhänge",
                  "kein Werkzeug", "exchangelib fehlt", "keine Postfachadresse",
                  "Anmeldung abgelehnt", "Keine Mailadresse", "Kein Betreff",
                  "ist kein Datum", "fehlt. Erwartet")


def _after_error(connection, draft, error):
    """(state, text) after a failed call: sent after all, failed, unclear."""
    text = str(error)[:300] or type(error).__name__
    check = getattr(connection, "check_sent", None)
    if check is None or isinstance(error, NotFound) or any(
            w in text for w in BEFORE_SENDING):
        return "failed", text
    try:
        found = check(draft["werkzeug"], draft.get("argumente") or {})
    except Exception:
        return "unclear", text
    if found:
        return "sent", ("Sent. (The server answered too late; the message "
                        "is in the sent folder.)")
    return "failed", text


def _set_state(user, chat_id, draft_id, state, **fields):
    import dateisperre
    with dateisperre.gesperrt(chats._index_pfad(user)):
        messages = chats.lade(user, chat_id)
        draft = _find_draft(messages, draft_id)
        if draft is not None:
            if state is None:
                draft.pop("state", None)
            else:
                draft["state"] = state
            for k, v in fields.items():
                draft[k] = v
            chats.speichere(user, chat_id, messages)


def discard_draft(user, chat_id, draft_id):
    if chat_id not in {k for k, _t, _g in chats.liste(user)}:
        raise NotFound("Unknown chat.")
    messages = chats.lade(user, chat_id)
    draft = _find_draft(messages, draft_id)
    if draft is None:
        raise NotFound("Unknown draft.")
    if draft.get("state") in DONE:
        raise ValueError(f"Draft already {draft['state']}.")
    draft["state"] = "discarded"
    chats.speichere(user, chat_id, messages)


def draft_of(user, chat_id, draft_id):
    """(message_index, draft) or (None, None)."""
    for i, d in drafts(user, chat_id):
        if d.get("id") == draft_id:
            return i, d
    return None, None


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
