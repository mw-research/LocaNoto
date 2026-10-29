"""The whole way from a question to a saved answer, as a stream of events.

The Streamlit page grew this flow inside its own code: images, probes,
search, SQL, lists, tools (mailboxes, web search), the streamed answer,
partial saves, the chat title. The API had only a part of it. This module
is the one place for all of it, so the API and any other front end answer
the same question the same way.

    for event, data in answering.ask("anna", answering.Request(question="...")):
        ...

Events, in this order (each optional except the last):

    chat      {"chat_id", "title", "new"}
    images    {"described": n, "failed": [names]}
    probes    {"probes", "note"}
    search    {"hits", "candidates", "rankings", "vector_outage"}
    sql       {"query", "account", "rows"} or {"reason"}
    lists     {"sheets": [...]} or {"reason"}
    tool      {"progress"}
    text      {"text"}                         -- many, the answer in pieces
    done      {"message", "chat_id"}           -- the saved assistant message
    error     {"status", "detail"}             -- instead of done

CREDENTIALS. Mailbox credentials come with the request (Request.mailboxes)
and are only held for its duration -- never written, never logged, never
put into a chat. That is the same rule the Streamlit page follows with its
session memory, and the only one that holds with several pods.

PERMISSIONS are checked here, not by the caller: rooms through
pipeline.sammlungen (membership and confirmed emergency access), the
model against llm.chat_modelle(), the preset through presets.erlaubt, the
web search against the rooms asked, the SQL account through
sqlquellen.fuer_benutzer.
"""
import dataclasses
import re
import threading
import time

import budget
import chats
import feedback
import llm
import mcp
import notzugang
import paths
import pipeline
import presets
import raeume
import ranking
import sqldb
import sqlpruefung
import sqlquellen
import tabellen

HELPER_TIMEOUT = paths.env_float("HELPER_TIMEOUT", 60)
STANDARD_TOP_K = paths.env_int("TOP_K", 5)
PARTIAL_SAVE_SECONDS = 2.0
DEFAULT_IMAGE_QUESTION = ("Was ist auf dem Bild zu sehen, und was sagt die "
                          "Dokumentation dazu?")

_clients = {}
_clients_lock = threading.Lock()
_reranker = None


def client(task, user=""):
    """The client of a task; with user, its calls are made on his behalf.

    The user goes in explicitly and not through a context variable: the
    streamed answer resumes this generator in a fresh context per piece.
    """
    with _clients_lock:
        if task not in _clients:
            _clients[task] = llm.client(task)
        c = _clients[task]
    return llm.for_user(c, user) if user else c


def reranker():
    """The reranker, chosen once per process (the first call probes it)."""
    global _reranker
    if _reranker is None:
        _reranker = ranking.lade_bewerter()
    return _reranker[0]


@dataclasses.dataclass
class Request:
    question: str = ""
    chat_id: str | None = None          # None: a new chat
    images: list = dataclasses.field(default_factory=list)  # [(name, bytes)]
    rooms: list | None = None           # None: every readable room
    files: list | None = None           # only these documents
    project: str | None = None          # folder in the own room
    preset: str | None = None
    model: str | None = None
    top_k: int = 0
    sql: bool = False
    sql_room: str | None = None         # "" = account from the environment
    lists: bool = True
    list_areas: list | None = None
    lists_large: bool = False
    web: bool = False
    mailboxes: dict = dataclasses.field(default_factory=dict)  # {server: header}
    history: list | None = None         # for stateless calls (save=False)
    save: bool = True


class Refused(Exception):
    """The request cannot be served as asked. status is an HTTP status."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# --- SETTINGS OF A REQUEST ---

def resolve(user, req):
    """Checks a request and fills in the defaults. Raises Refused."""
    if req.preset and not presets.erlaubt(req.preset, user):
        raise Refused(400, "Unknown preset.")
    p = presets.lese(req.preset)
    allowed_models = llm.chat_modelle()
    model = req.model or p.get("chat_modell") or llm.modell("CHAT")
    if model not in allowed_models:
        if req.model:
            raise Refused(400, "Model not allowed. Allowed: "
                          + ", ".join(allowed_models))
        model = llm.modell("CHAT")
    top_k = req.top_k or p.get("top_k") or STANDARD_TOP_K
    areas = req.list_areas or p.get("listen_bereiche") or []
    emergency = notzugang.raeume_fuer(user)
    pairs = pipeline.sammlungen(user, nur=req.rooms or None,
                                notzugang=emergency)
    files = list(req.files or [])
    if req.project is not None:
        own = raeume.privat_kennung(user)
        project_files = pipeline.projekte(user, own, notzugang=emergency) \
            .get(req.project, [])
        files = sorted(set(files) & set(project_files)) if files \
            else project_files
        if not files:
            raise Refused(404, "Unknown project or no documents in it.")
    web_servers = mcp.websuche_server()
    if req.web:
        if not web_servers:
            raise Refused(400, "No web search is set up.")
        # The rooms asked -- the chosen ones, else all readable. The model
        # writes the search term with their passages in its context, so
        # every one of them has to allow it.
        readable = raeume.lesbar(user, emergency)
        asked = [r for r in readable if not req.rooms or r in req.rooms]
        closed = [r for r in asked if not raeume.websuche_erlaubt(r)]
        if closed:
            raise Refused(403, "Web search is not allowed next to: "
                          + ", ".join(closed))
    return {"model": model, "top_k": int(top_k), "areas": areas,
            "pairs": pairs, "files": files or None, "emergency": emergency,
            "web_servers": web_servers}


# --- CHAT TITLE ---

def chat_title(question, model, user=""):
    """A short title for the chat list; the first words when the model fails."""
    words = ""
    try:
        prompt = ("Gib dieser Frage einen kurzen Titel: hoechstens sechs "
                  "Woerter, die markantesten Begriffe zuerst, in der Sprache "
                  "der Frage. Antworte NUR mit dem Titel, ohne "
                  "Anfuehrungszeichen.\n"
                  f"Frage: {question}")
        resp = client("TITLE", user).chat.completions.create(
            model=llm.modell("TITLE", model),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64, temperature=0.3, timeout=HELPER_TIMEOUT)
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"<think>.*?</think>", " ", raw, flags=re.S | re.I)
        raw = re.sub(r"<think>.*", " ", raw, flags=re.S | re.I)
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        words = clean_title(lines[-1]) if lines else ""
    except Exception:
        words = ""
    return words or clean_title(" ".join(question.split()[:6])) or "Chat"


def clean_title(text):
    text = " ".join(str(text or "").replace("_", " ").split())
    text = text.strip(" \"'„“”‚‘’*#.:;-")
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0] + " …"
    return text


# --- SQL AND LISTS ---

def sql_accounts(user):
    """[(room, account_user)] the user may query with; "" = environment."""
    out = [(r, (z or {}).get("benutzer", ""))
           for r, z in sqlquellen.fuer_benutzer(
               user, notzugang=notzugang.raeume_fuer(user))]
    if sqldb.ist_konfiguriert():
        out.append(("", ""))
    return out


_schema_cache = {}


def sql_schema(room):
    """(schema, error) of an account, kept for an hour like the page does."""
    hit = _schema_cache.get(room)
    if hit and time.time() - hit[0] < 3600:
        return hit[1], hit[2]
    access = sqlquellen.zugang(room) if room else None
    if not sqldb.ist_konfiguriert(access):
        result = ("", "")
    else:
        try:
            result = (sqldb.lade_schema(access), "")
        except Exception as e:
            result = ("", f"{type(e).__name__}: {e}")
    _schema_cache[room] = (time.time(),) + result
    return result


def _sql_block(user, req, question, model, history_text):
    rooms = {r for r, _a in sql_accounts(user)}
    room = req.sql_room if req.sql_room is not None else \
        (next(iter(sorted(rooms - {""})), "") if rooms else None)
    if room is None or room not in rooms:
        return [], {"reason": "No database account for this user."}
    schema, error = sql_schema(room)
    if not schema:
        return [], {"reason": "No database connection." if error
                    else "The database has no readable tables."}
    access = sqlquellen.zugang(room) if room else None
    try:
        query = sqldb.formuliere(client("SQL", user), llm.modell("SQL", model),
                                 question, schema, history_text)
    except Exception as e:
        return [], {"reason": f"Query not generated: {e}"}
    if not query:
        return [], {"reason": "The model does not see the question "
                              "answerable from the database."}
    try:
        columns, rows = sqldb.fuehre_aus(query, zugang=access)
    except ValueError as e:
        return [], {"query": query, "reason": str(e)}
    except Exception as e:
        return [], {"query": query, "reason": f"Database error: {e}"}
    table = sqldb.als_tabelle(columns, rows)
    return ([("datenbank_abfrage", query), ("datenbank_ergebnis", table)],
            {"query": query, "account": (access or {}).get("benutzer", ""),
             "rows": len(rows)})


def _list_blocks(user, req, question, model, history_text, areas):
    if not req.lists:
        return [], None
    catalog = tabellen.lies_katalog()
    entries = [e for e in tabellen.sichtbar(catalog.get("eintraege", []), user)
               if (req.lists_large or not e.get("gross"))
               and tabellen.im_bereich(e, areas)]
    if not entries:
        return [], None
    try:
        results = tabellen.abfragen(client("CHAT", user), model, question,
                                    entries, history_text)
    except Exception as e:
        return [], {"reason": f"Query not generated: {e}"}
    if not results:
        return [], {"reason": "None of the lists fits this question."}
    blocks, sheets = [], []
    for t in results:
        source = t["datei"] + (f"#{t['blatt']}" if t["blatt"] else "")
        sheet = {"sheet": source, "query": t["sql"], "rows": len(t["zeilen"]),
                 "chosen": bool(t.get("gewaehlt", True))}
        if t["grund"]:
            sheet["reason"] = t["grund"]
        sheets.append(sheet)
        if t["grund"] or not t["zeilen"]:
            # An empty table reads to the model like proof that something
            # does not exist; it is reported, not put into the context.
            continue
        table = sqlpruefung.als_tabelle(t["spalten"], t["zeilen"])
        sheet["table"] = table
        blocks += [("liste_abfrage", source + chr(10) + t["sql"]),
                   ("liste_ergebnis", table)]
    return blocks, {"sheets": sheets}


# --- THE FLOW ---

def ask(user, req):
    """Answer a question. Yields (event, data); see the module docstring."""
    try:
        yield from _ask(user, req)
    except Refused as e:
        yield "error", {"status": e.status, "detail": e.detail}
    except budget.Ueberzogen as e:
        yield "error", {"status": 429, "detail": str(e),
                        "reason": "budget",
                        "retry_after": budget.FENSTER_MINUTEN * 60}


def _ask(user, req):
    import vision
    settings = resolve(user, req)
    model = settings["model"]
    question = (req.question or "").strip()

    # The chat: an own one or a new one. Never someone else's -- chat
    # files live under the user's name, so a foreign id is just unknown.
    messages, new_chat = [], False
    chat_id = req.chat_id
    if req.save:
        if chat_id:
            if chat_id not in {k for k, _t, _g in chats.liste(user)}:
                raise Refused(404, "Unknown chat.")
            messages = chats.lade(user, chat_id)
        else:
            chat_id, new_chat = chats.neue_kennung(), True
    else:
        messages = [{"role": m["role"], "content": m["content"]}
                    for m in (req.history or [])
                    if m.get("role") in ("user", "assistant")]

    # Images: stored with the chat, described by the vision model. The
    # description is a probe and context; the chat model gets text only.
    image_paths, image_texts, failed = [], [], []
    for n, (name, data) in enumerate(req.images or []):
        try:
            ext = (re.search(r"\.[A-Za-z0-9]{1,5}$", name or "") or [".jpg"])[0]
            if req.save:
                image_paths.append(vision.speichern(
                    data, user, f"{chat_id}_{len(messages)}_{n}{ext.lower()}"))
            image_texts.append(vision.beschreibe(data, question))
        except Exception:
            failed.append(name)
    if req.images:
        yield "images", {"described": len(image_texts), "failed": failed}
    if not question and not image_texts:
        raise Refused(400, "Empty question.")
    if not question:
        question = DEFAULT_IMAGE_QUESTION

    user_message = {"role": "user", "content": question}
    if image_paths:
        user_message["bilder"] = image_paths
    messages.append(user_message)
    title = None
    if req.save:
        if len(messages) == 1:
            title = chat_title(question, model, user)
        chats.speichere(user, chat_id, messages, title)
        yield "chat", {"chat_id": chat_id, "new": new_chat,
                       "title": title or chats.titel(user, chat_id)}

    # 1. probes
    history_text = pipeline.verlaufstext(messages)
    probes, note = pipeline.sonden(client("CHAT", user), model, question,
                                   verlauf=history_text,
                                   bild_texte=image_texts, preset=req.preset)
    yield "probes", {"probes": probes, "note": note}

    # 2. hybrid search
    try:
        hits, numbers = pipeline.suche(
            settings["pairs"], client("EMBEDDING", user), llm.modell("EMBEDDING"),
            probes, user, settings["top_k"], dateien=settings["files"],
            bewerter=reranker())
    except ValueError as e:
        raise Refused(503, str(e))
    if not hits:
        feedback.notiere("leer", user, question, sonden=probes,
                         zahlen=numbers, herkunft="schnittstelle")
    yield "search", {"hits": len(hits),
                     "candidates": numbers.get("kandidaten", 0),
                     "rankings": numbers.get("ranglisten", 0),
                     "vector_outage": numbers.get("vektorausfall") or {}}

    # 3. database and lists
    blocks = []
    if req.sql:
        sql_blocks, info = _sql_block(user, req, question, model, history_text)
        blocks += sql_blocks
        yield "sql", info
    list_blocks, info = _list_blocks(user, req, question, model,
                                     history_text, settings["areas"])
    blocks += list_blocks
    if info:
        yield "lists", info

    # 4. context, tools (mailboxes, web search)
    system = pipeline.systemprompt(
        pipeline.kontext(hits, image_texts, bloecke=blocks), req.preset,
        benutzer=user)
    extra, drafts = [], []
    if mcp.eingerichtet():
        progress = []
        connections = mcp.verbinde(
            {k: v for k, v in (req.mailboxes or {}).items()},
            ohne=(() if req.web else settings["web_servers"]))
        try:
            extra, drafts = pipeline.werkzeuglauf(
                client("CHAT", user), model, system, messages, connections,
                fortschritt=lambda t: progress.append(str(t)))
        except Exception as e:
            progress.append(f"Tools not available: {type(e).__name__}: {e}")
        finally:
            for c in connections.values():
                try:
                    c.schliesse()
                except Exception:
                    pass
        for p in progress:
            yield "tool", {"progress": p}

    # 5. the answer, saved every few seconds while it grows
    parts, last = [], time.time()
    for piece in pipeline.antwort(client("CHAT", user), model, system, messages,
                                  zusatz=extra):
        piece = piece if isinstance(piece, str) else str(piece)
        parts.append(piece)
        yield "text", {"text": piece}
        if req.save and time.time() - last >= PARTIAL_SAVE_SECONDS:
            last = time.time()
            try:
                chats.speichere(user, chat_id, messages + [{
                    "role": "assistant", "content": "".join(parts),
                    "unvollstaendig": True}])
            except Exception:
                pass  # a failed partial save must not cost the answer

    for i, d in enumerate(drafts):
        d["id"] = f"d{len(messages)}_{i}"
    message = {"role": "assistant", "content": "".join(parts),
               "sources": pipeline.quellen(hits), "sonden": probes,
               "zahlen": numbers, "entwuerfe": drafts,
               "web": pipeline.webtreffer(extra, settings["web_servers"]),
               "modell": model}
    messages.append(message)
    if req.save:
        chats.speichere(user, chat_id, messages)
    yield "done", {"message": message, "chat_id": chat_id}


def answer(user, req):
    """ask() collected into one result: (status, body)."""
    out = {"events": {}}
    text = []
    for event, data in ask(user, req):
        if event == "text":
            text.append(data["text"])
        elif event == "tool":
            out["events"].setdefault("tool", []).append(data["progress"])
        elif event == "error":
            return data.get("status", 500), data
        else:
            out["events"][event] = data
    done = out["events"].pop("done", {})
    out["answer"] = "".join(text)
    out["message"] = done.get("message")
    out["chat_id"] = done.get("chat_id")
    return 200, out
