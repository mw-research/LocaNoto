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

WEB SEARCH ON CONFIRMATION. Without the web switch the model may still
propose a web search (if a workspace asked allows it): the call becomes
a draft like a mail, showing the exact search text. Confirming it asks
again with web_draft set: the search runs with that text, and the answer
continues the chat without a new question.

AN ANSWER THAT IS UNDER WAY IS IN THE CHAT. From the start it stands
there as a message marked "laeuft", with the status and the text so far,
updated every few seconds (_Run). The page that asked may go away -- the
API keeps answering in a thread (routes_chat) --, and whoever opens the
chat, in any pod, sees the answer grow and then the finished one. The
finished answer replaces exactly that message, so a question asked
meanwhile is not lost.

TOOL RESULTS STAY WITH THE ANSWER ("tool_log", "ids"), so the next
question still knows the mails it listed (pipeline.history_for_model)
and their short ids still resolve, in any pod.
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
import json
import logging
import os
import re
import threading
import time

import attachments
import budget
import chats
import created_files
import db_files
import feedback
import llm
import mcp
import notzugang
import paths
import pipeline
import postfach
import presets
import raeume
import ranking
import sqldb
import sqlpruefung
import sqlquellen
import tabellen
import workspace_notes

HELPER_TIMEOUT = paths.env_float("HELPER_TIMEOUT", 60)
STANDARD_TOP_K = paths.env_int("TOP_K", 5)
PARTIAL_SAVE_SECONDS = 2.0
DEFAULT_IMAGE_QUESTION = ("Was ist auf dem Bild zu sehen, und was sagt die "
                          "Dokumentation dazu?")

_log = logging.getLogger("locanoto.answering")
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
    web_draft: str | None = None        # confirmed web search draft of this chat
    retry: bool = False                 # answer the last question of chat_id again
    sql_logins: dict = dataclasses.field(default_factory=dict)
    # {room: {"benutzer", "passwort"}} -- personal SQL logins of this
    # session, like mailbox logins never stored


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
    web_excluded = []
    if req.web:
        if not web_servers:
            raise Refused(400, "No web search is set up.")
        # The rooms asked -- the chosen ones, else all readable. The model
        # writes the search term with their passages in its context, so
        # every one of them has to allow it.
        readable = raeume.lesbar(user, emergency)
        asked = [r for r in readable if not req.rooms or r in req.rooms]
        closed = [r for r in asked if not raeume.websuche_erlaubt(r)]
        if closed and req.rooms:
            # chosen on purpose: say so instead of quietly dropping it
            raise Refused(403, "Web search is not allowed next to: "
                          + ", ".join(closed))
        if closed:
            # "all workspaces": this question leaves out the ones that do
            # not allow web search (by default the shared "allgemein"),
            # and the answer says so.
            open_rooms = [r for r in asked if r not in closed]
            if not open_rooms:
                raise Refused(403, "Web search is not allowed next to: "
                              + ", ".join(closed))
            pairs = pipeline.sammlungen(user, nur=open_rooms, notzugang=emergency)
            web_excluded = closed
    return {"model": model, "top_k": int(top_k), "areas": areas,
            "pairs": pairs, "files": files or None, "emergency": emergency,
            "web_servers": web_servers, "web_excluded": web_excluded}


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

def sql_access(room, logins=None):
    """The connection of a room: the personal login of this session if
    there is one (the database's rights per person), else the shared
    account the admin stored. None without either."""
    access = sqlquellen.zugang(room) if room else None
    mine = (logins or {}).get(room) if room else None
    if mine and mine.get("benutzer") and mine.get("passwort"):
        return dict(access or {}, benutzer=mine["benutzer"],
                    passwort=mine["passwort"])
    return access


def sql_accounts(user, logins=None):
    """[(room, account_user)] the user may query with; "" = environment."""
    out = []
    for r, z in sqlquellen.fuer_benutzer(user, notzugang=notzugang.raeume_fuer(user)):
        access = sql_access(r, logins)
        if access and access.get("benutzer") and access.get("passwort"):
            out.append((r, access["benutzer"]))
    if sqldb.ist_konfiguriert():
        out.append(("", ""))
    return out


_schema_cache = {}


def sql_schema(room, access=None):
    """(schema, error) of an account, kept for an hour like the page does.

    Per room AND account: with personal logins two people see different
    tables of the same database."""
    if access is None and room:
        access = sqlquellen.zugang(room)
    key = (room, (access or {}).get("benutzer", ""))
    hit = _schema_cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1], hit[2]
    if not sqldb.ist_konfiguriert(access):
        result = ("", "")
    else:
        try:
            result = (sqldb.lade_schema(access), "")
        except Exception as e:
            result = ("", f"{type(e).__name__}: {e}")
    _schema_cache[key] = (time.time(),) + result
    return result


def forget_schema(room):
    for key in [k for k in _schema_cache if k[0] == room]:
        _schema_cache.pop(key, None)


# A question about the database itself ("what does our ERP look like",
# "which tables are there") gets no query, but the table list answers it.
_ASKS_FOR_STRUCTURE = re.compile(
    r"\b(aufbau|struktur\w*|datenmodell|schema|tabelle\w*|spalte\w*|felder|"
    r"erp|datenbank\w*|database|tables?|columns?|structure)\b", re.I)
SCHEMA_CHARS = 6000


def _sql_block(user, req, question, model, history_text):
    rooms = {r for r, _a in sql_accounts(user, req.sql_logins)}
    room = req.sql_room if req.sql_room is not None else \
        (next(iter(sorted(rooms - {""})), "") if rooms else None)
    if room is None or room not in rooms:
        return [], {"reason": "No database account for this user."}
    where = {"room": room}
    access = sql_access(room, req.sql_logins) if room else None
    schema, error = sql_schema(room, access)
    if not schema:
        # The driver's reason, not just "no connection": a wrong host, a
        # network policy and a wrong password each need another fix.
        return [], dict(where, reason=f"No database connection: {error[:300]}" if error
                        else "The database has no readable tables.")
    try:
        query = sqldb.formuliere(client("SQL", user), llm.modell("SQL", model),
                                 question, schema, history_text,
                                 hinweis_raum=(access or {}).get("hinweis", ""))
    except Exception as e:
        return [], dict(where, reason=f"Query not generated: {e}")
    if not query:
        # "none": nothing went wrong, the question is not one for the
        # database -- the page does not mention it under every answer
        blocks = []
        if _ASKS_FOR_STRUCTURE.search(question or ""):
            blocks = [("datenbank_aufbau", schema[:SCHEMA_CHARS])]
        return blocks, dict(where, none=True, structure=bool(blocks),
                            reason="The model does not see the question "
                                   "answerable from the database.")
    try:
        columns, rows = sqldb.fuehre_aus(query, zugang=access)
    except ValueError as e:
        return [], dict(where, query=query, reason=str(e))
    except Exception as e:
        return [], dict(where, query=query, reason=f"Database error: {e}")
    first = None
    if not rows and _SEARCHES_TEXT.search(query):
        # Nothing found by name: "Absperrhähne" may be "Kugelhahn DN25" in
        # the ERP. One broader try; the first result stands if it fails.
        try:
            wider = sqldb.formuliere(client("SQL", user), llm.modell("SQL", model),
                                     question, schema, history_text,
                                     hinweis_raum=(access or {}).get("hinweis", ""),
                                     vorher=query)
            if wider and wider.strip() != query.strip():
                columns2, rows2 = sqldb.fuehre_aus(wider, zugang=access)
                first, query, columns, rows = query, wider, columns2, rows2
        except Exception:
            pass
    # Files in binary columns, released paths and links (db_files.py)
    try:
        rows, found = db_files.collect(user, columns, rows)
    except Exception as e:
        found = db_files.Found()
        found.notes.append(f"Dokumente nicht gelesen: {type(e).__name__}")
    table = sqldb.als_tabelle(columns, rows)
    info = dict(where, query=query, account=(access or {}).get("benutzer", ""),
                rows=len(rows))
    if first:
        info["first_query"] = first
    blocks = [("datenbank_abfrage", query), ("datenbank_ergebnis", table)]
    for name, text in found.texts:
        blocks.append(("datenbank_dokument", f"{name}\n{text}"))
    if found.files:
        info["files"] = found.files
    if found.links:
        info["links"] = found.links
    if found.notes:
        info["file_notes"] = found.notes[:10]
    return blocks, info


# A query that looks for something by its name (LIKE, a word in quotes --
# not a status code like 'O').
_SEARCHES_TEXT = re.compile(r"\bLIKE\b|N?'[^']*[A-Za-zÄÖÜäöüß]{3,}[^']*'", re.I)


def sql_note(info):
    """For the answer: a database is connected, and what came of it.

    The database is no tool the model calls -- LocaNoto asks it before the
    answer. Without this the model only sees its tool list (mailbox, web,
    files), concludes it has no access to the ERP and says so, even with
    the result in front of it.
    """
    if not info or "room" not in info:
        return ""
    label = raeume.bezeichnung(info["room"]) if info["room"] else "eigene Datenbank"
    text = (f"\n<datenbank_hinweis>\nAngebunden ist die Datenbank (ERP) des "
            f"Arbeitsbereichs {label}, Microsoft SQL Server, nur lesend. LocaNoto "
            "fragt sie zu jeder Frage selbst ab, bevor du antwortest. Sage nie, "
            "du haettest keinen Zugriff auf die Datenbank oder das ERP.\n")
    if "rows" in info:
        text += ("Unten stehen <datenbank_abfrage> und <datenbank_ergebnis>: das "
                 "echte, aktuelle Ergebnis dieser Abfrage. Antworte daraus und sage, "
                 "dass die Angaben aus der Datenbank stammen.\n")
        if info.get("files"):
            text += ("Dokumente aus der Datenbank liegen dem Nutzer unter der Antwort "
                     "zum Oeffnen bereit: " + ", ".join(info["files"]) + ". Sage ihm das. "
                     "Den Text von PDFs findest du in <datenbank_dokument>.\n")
        if info.get("links"):
            text += ("Links aus der Datenbank stehen ebenfalls unter der Antwort: "
                     + ", ".join(info["links"][:5]) + ".\n")
        if info.get("file_notes"):
            text += ("Nicht angeboten: " + "; ".join(info["file_notes"]) + ".\n")
    elif info.get("structure"):
        text += ("Zu dieser Frage lief keine Abfrage; unten steht in "
                 "<datenbank_aufbau> der Aufbau der Datenbank (Tabellen und "
                 "Spalten). Beschreibe ihn daraus.\n")
    elif info.get("none"):
        text += ("Zu dieser Frage lief keine Abfrage, weil sie nicht nach Daten "
                 "fragt. Fragt der Nutzer doch nach Daten, sage das und schlage "
                 "eine Frage nach konkreten Daten vor.\n")
    else:
        text += ("Die Abfrage zu dieser Frage ist fehlgeschlagen: "
                 f"{str(info.get('reason') or '')[:300]}. Sage das dem Nutzer.\n")
    return text + "</datenbank_hinweis>\n"


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


# --- WEB SEARCH ON CONFIRMATION ---

class _Every:
    """Every tool of a server waits for a person (werkzeuglauf: confirm)."""

    def __contains__(self, _name):
        return True


WEB_HINT = ("Websuche: nur vorschlagen, wenn die Dokumente die Frage nicht "
            "beantworten oder nach aktuellen oder externen Informationen "
            "gefragt ist. Der Nutzer sieht den Suchtext und bestaetigt ihn; "
            "der Suchtext darf keine vertraulichen Angaben aus den Dokumenten "
            "enthalten.")


# When the web search is offered without the switch (WEB_TOOL): "auto"
# when the question sounds like it, when the documents gave nothing, or
# when a mailbox is connected (then the tool round runs anyway). Offering
# it costs a model call before the answer; "always" pays it every time.
_ASKS_FOR_WEB = re.compile(
    r"\b(web|internet|online|netz|google|recherch\w*|aktuell\w*|neueste\w*|"
    r"news|nachrichten|homepage|website|webseite|search|latest|current)\b", re.I)


def _web_on_confirmation(user, req, settings, question="", hits=(),
                         mailbox=False):
    """May the model propose a web search here? Not with the switch on
    (then it searches directly), not without a chat to keep the draft,
    not if no workspace asked allows web search."""
    if req.web or not req.save or not settings["web_servers"]:
        return False
    mode = (os.getenv("WEB_TOOL") or "auto").strip().lower()
    if mode == "off":
        return False
    if mode != "always" and not (mailbox or not hits
                                 or _ASKS_FOR_WEB.search(question or "")):
        return False
    emergency = settings["emergency"]
    asked = [r for r in raeume.lesbar(user, emergency)
             if not req.rooms or r in req.rooms]
    return any(raeume.websuche_erlaubt(r) for r in asked)


def _claim_web_draft(user, chat_id, draft_id):
    """Marks a web search draft as confirmed, once. Returns it."""
    import dateisperre
    import mailboxes
    with dateisperre.gesperrt(chats._index_pfad(user)):
        messages = chats.lade(user, chat_id)
        draft = mailboxes._find_draft(messages, draft_id)
        if draft is None or draft.get("kind") != "web":
            raise Refused(404, "Unknown web search draft.")
        if draft.get("state") in ("sent", "discarded", "sending"):
            raise Refused(409, f"Draft already {draft['state']}.")
        draft["state"] = "sent"
        chats.speichere(user, chat_id, messages)
    return draft


def _chat_ids(messages):
    known = {}
    for m in messages:
        known.update(m.get("ids") or {})
    return known


def _describe(connections, web_confirm):
    """One line per tool server for the model: what it is."""
    out = []
    for name, c in connections.items():
        if name == workspace_notes.SERVER:
            out.append("Zusammenfassungen als Dokument ablegen (als Entwurf)")
        elif name == created_files.SERVER:
            out.append("Dateien erstellen (Excel, Word, PDF, PowerPoint)")
        elif hasattr(c, "adresse"):
            try:
                addr = c.adresse()
            except Exception:
                addr = name
            kind = ("Mails lesen und als Entwurf senden"
                    if not hasattr(c, "_events") else
                    "Mails und Kalender lesen; Mails, Termine und Einladungen "
                    "als Entwurf")
            out.append(f"Postfach {name} ({addr}): {kind}")
        elif web_confirm and getattr(c, "confirm", None) is not None:
            out.append(f"Websuche {name} (nur nach Bestaetigung des Nutzers)")
        else:
            out.append(f"Werkzeugserver {name}")
    return out


def _unconnected(req):
    """Mailboxes that need a login this request does not carry."""
    return [n for n, a in mcp.lies_konfiguration().items()
            if a.get("art") != "websuche" and mcp.braucht_anmeldung(n)
            and n not in (req.mailboxes or {})]


# --- AN ANSWER UNDER WAY, IN THE CHAT ---

class _Run:
    """The message of an answer while it is written (see module doc)."""

    def __init__(self, user, chat_id):
        import uuid
        self.user, self.chat_id = user, chat_id
        self.id = uuid.uuid4().hex[:12]
        self.status, self.text, self.last = "", "", 0.0

    def _put(self, message):
        """Replaces this run's message in the stored chat, or appends it."""
        import dateisperre
        message = dict(message, run=self.id)
        try:
            with dateisperre.gesperrt(chats._index_pfad(self.user)):
                stored = chats.lade(self.user, self.chat_id)
                for i, m in enumerate(stored):
                    if m.get("run") == self.id:
                        stored[i] = message
                        break
                else:
                    stored.append(message)
                chats.speichere(self.user, self.chat_id, stored)
        except Exception:
            _log.exception("could not save the answer under way")

    def _running(self):
        return {"role": "assistant", "content": self.text, "unvollstaendig": True,
                "laeuft": True, "status": self.status[:300],
                "aktualisiert": time.time()}

    def start(self):
        self._put(self._running())
        self.last = time.time()

    def update(self, status=None, text=None, force=False):
        if status is not None:
            self.status = str(status)
        if text is not None:
            self.text = text
        if force or time.time() - self.last >= PARTIAL_SAVE_SECONDS:
            self.last = time.time()
            self._put(self._running())

    def fail(self, error):
        self._put({"role": "assistant", "content": self.text,
                   "unvollstaendig": True, "fehler": str(error)[:300]})

    def finish(self, message):
        self._put(message)


def _status_of(event, data):
    """One line for the message under way, from an event."""
    if event == "probes":
        return " · ".join(data.get("probes") or [])
    if event == "search":
        return f"{data.get('hits', 0)} / {data.get('candidates', 0)}"
    if event == "tool":
        return data.get("progress") or ""
    if event == "sql":
        return "SQL: " + (data.get("query") or data.get("reason") or "")
    return None


# --- THE FLOW ---

def ask(user, req):
    """Answer a question. Yields (event, data); see the module docstring.

    Every failure ends in an "error" event, also one in the middle of the
    streamed answer (the model server answering 500): a stream that just
    stops looks like a hang. retry=true answers the last question again.
    """
    try:
        yield from _ask(user, req)
    except Refused as e:
        yield "error", {"status": e.status, "detail": e.detail}
    except budget.Ueberzogen as e:
        yield "error", {"status": 429, "detail": str(e),
                        "reason": "budget",
                        "retry_after": budget.FENSTER_MINUTEN * 60}
    except Exception as e:
        _log.exception("answer failed for %s", user)
        yield "error", {"status": 502, "retry": True,
                        "detail": f"{type(e).__name__}: {str(e)[:300]}"}


def _ask(user, req):
    if req.web_draft:
        # A confirmed web search: like a question with the switch on.
        req = dataclasses.replace(req, web=True)
    settings = resolve(user, req)
    model = settings["model"]

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

    web_draft = None
    if req.retry:
        # The last answer failed or broke off: drop it, ask again.
        if not (req.save and chat_id):
            raise Refused(400, "Only a saved chat can be asked again.")
        while messages and messages[-1].get("role") == "assistant" and (
                messages[-1].get("unvollstaendig") or messages[-1].get("fehler")):
            messages.pop()
        if not messages or messages[-1].get("role") != "user":
            raise Refused(409, "The last answer is complete.")
        chats.speichere(user, chat_id, messages)
        question = messages[-1].get("content") or ""
        yield "chat", {"chat_id": chat_id, "new": False,
                       "title": chats.titel(user, chat_id)}
        image_texts = []
    elif req.web_draft:
        if not (req.save and chat_id):
            raise Refused(400, "A web search draft belongs to a chat.")
        web_draft = _claim_web_draft(user, chat_id, req.web_draft)
        messages = chats.lade(user, chat_id)
        question = next((m.get("content") or "" for m in reversed(messages)
                         if m.get("role") == "user"), "")
        yield "chat", {"chat_id": chat_id, "new": False,
                       "title": chats.titel(user, chat_id)}
        image_texts = []
    else:
        question, image_texts = yield from _new_question(
            user, req, chat_id, new_chat, messages, model)
    run = _Run(user, chat_id) if req.save else None
    if run:
        run.start()
    try:
        for event, data in _answer(user, req, settings, chat_id, messages,
                                   question, image_texts, web_draft, run):
            if run and event not in ("text", "done", "error"):
                status = _status_of(event, data)
                if status is not None:
                    run.update(status=status)
            yield event, data
    except Exception as e:
        if run:
            run.fail(f"{type(e).__name__}: {e}")
        raise


def _new_question(user, req, chat_id, new_chat, messages, model):
    """Images, the question into the chat, the chat event."""
    import vision
    question = (req.question or "").strip()
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
    return question, image_texts


def _answer(user, req, settings, chat_id, messages, question, image_texts,
            web_draft, run=None):
    """Search, tools and the answer to the last question of messages."""
    model = settings["model"]

    # 1. probes
    history_text = pipeline.verlaufstext(messages)
    probes, note = pipeline.sonden(client("CHAT", user), model, question,
                                   verlauf=history_text,
                                   bild_texte=image_texts, preset=req.preset)
    yield "probes", {"probes": probes, "note": note}
    if settings["web_excluded"]:
        yield "tool", {"progress": "Web search: left out of this question: "
                                   + ", ".join(raeume.bezeichnung(r)
                                               for r in settings["web_excluded"])}

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
    sql_info = None
    if req.sql:
        sql_blocks, info = _sql_block(user, req, question, model, history_text)
        blocks += sql_blocks
        sql_info = info
        yield "sql", info
    list_blocks, info = _list_blocks(user, req, question, model,
                                     history_text, settings["areas"])
    blocks += list_blocks
    list_info = info
    if info:
        yield "lists", info

    # 4. context, tools (mailboxes, web search)
    system = pipeline.systemprompt(
        pipeline.kontext(hits, image_texts, bloecke=blocks), req.preset,
        benutzer=user)
    system += sql_note(sql_info)
    extra, drafts = [], []
    connections = {}
    notes = []
    web_confirm = False
    if mcp.eingerichtet():
        unconnected = _unconnected(req)
        web_confirm = _web_on_confirmation(
            user, req, settings, question, hits,
            mailbox=any(n in (req.mailboxes or {}) for n in mcp.lies_konfiguration()
                        if n not in settings["web_servers"]))
        if unconnected:
            # Not offered at all -- a tool that can only fail would be
            # called and fail on every question.
            system += ("\nPostfaecher ohne Anmeldung in dieser Sitzung: "
                       + ", ".join(unconnected) + ". Nur wenn nach Mail oder "
                       "Kalender gefragt ist: der Nutzer verbindet sie unter "
                       "Einstellungen > Postfaecher.\n")
        skip = set(unconnected)
        if not (req.web or web_confirm):
            skip |= set(settings["web_servers"])
        connections = mcp.verbinde(
            {k: v for k, v in (req.mailboxes or {}).items()}, ohne=skip)
        if web_confirm:
            for name in settings["web_servers"]:
                if name in connections:
                    connections[name].confirm = _Every()
            system += "\n" + WEB_HINT + "\n"
    if req.save and chat_id:
        postfach.load_ids(_chat_ids(messages))
    for c in connections.values():
        # attachments only from the own workspace and this chat
        if hasattr(c, "attachment_source"):
            c.attachment_source = attachments.source(user, chat_id if req.save else None)
    first = []
    if web_draft is not None:
        # The confirmed search runs with exactly the text the person saw.
        server, tool = web_draft.get("server"), web_draft.get("werkzeug")
        args = web_draft.get("argumente") or {}
        call_id = "web_" + str(web_draft.get("id"))
        yield "tool", {"progress": f"{server}: {tool}"}
        try:
            if server not in connections:
                raise RuntimeError("web search not available")
            result = str(connections[server].rufe(tool, args) or "")
        except Exception as e:
            result = f"Fehler: {e}"
        first = [{"role": "assistant", "content": "",
                  "tool_calls": [{"id": call_id, "type": "function",
                                  "function": {"name": f"{server}__{tool}",
                                               "arguments": json.dumps(args, ensure_ascii=False)}}]},
                 {"role": "tool", "tool_call_id": call_id, "content": result[:8000]}]
        extra = list(first)
        # Only the confirmed text goes out: no further searches in this
        # round (the mailboxes stay).
        for name in settings["web_servers"]:
            c = connections.pop(name, None)
            if c is not None:
                try:
                    c.schliesse()
                except Exception:
                    pass
    if req.save and workspace_notes.offered(question, connections):
        connections[workspace_notes.SERVER] = workspace_notes.Tools(user)
    file_tools = None
    if req.save and created_files.offered(question, connections):
        file_tools = created_files.Tools(user)
        connections[created_files.SERVER] = file_tools
    described = _describe(connections, web_confirm)
    system += pipeline.tools_preamble(described)
    if connections:
        progress = []
        try:
            extra, drafts = pipeline.werkzeuglauf(
                client("CHAT", user), model, system, messages, connections,
                fortschritt=lambda t: progress.append(str(t)), vorab=first,
                hinweise=notes)
        except Exception as e:
            progress.append(f"Tools not available: {type(e).__name__}: {e}")
            notes.append(f"Werkzeuge nicht verfuegbar: {type(e).__name__}")
        finally:
            for c in connections.values():
                try:
                    c.schliesse()
                except Exception:
                    pass
        for p in progress:
            yield "tool", {"progress": p}
    system += pipeline.answer_tool_note(extra, described, drafts)
    if notes:
        system += ("\n<werkzeughinweise>\n" + "\n".join(notes[:10])
                   + "\nBetrifft die Frage diese Werkzeuge: dem Nutzer sagen, "
                     "was nicht ging. Nichts erfinden.\n</werkzeughinweise>\n")

    # 5. the answer, saved every few seconds while it grows
    parts = []
    if run:
        run.update(status="", force=True)
    try:
        for piece in pipeline.antwort(client("CHAT", user), model, system,
                                      messages, zusatz=extra):
            piece = piece if isinstance(piece, str) else str(piece)
            parts.append(piece)
            yield "text", {"text": piece}
            if run:
                run.update(text="".join(parts))
    except Exception as e:
        # The model server failed mid-answer (a 500 through the gateway).
        # What came stays, marked; "ask again" replaces it.
        _log.exception("answer stream failed for %s", user)
        if run:
            run.text = "".join(parts)
            run.fail(f"{type(e).__name__}: {str(e)[:200]}")
        yield "error", {"status": 502, "retry": bool(req.save),
                        "chat_id": chat_id,
                        "detail": f"{type(e).__name__}: {str(e)[:300]}"}
        return

    for i, d in enumerate(drafts):
        d["id"] = f"d{len(messages)}_{i}"
        if d.get("server") in settings["web_servers"]:
            d["kind"] = "web"
        if d.get("server") == workspace_notes.SERVER:
            # The room's name for the person who confirms; the id alone
            # says little about where the summary will be readable.
            room = (d.get("argumente") or {}).get("room") \
                or raeume.privat_kennung(user)
            d["ziel"] = raeume.bezeichnung(room)
    answer = "".join(parts)
    cited, others = pipeline.cited_sources(
        pipeline.quellen(hits), answer,
        tools_used=any(m.get("tool_calls") for m in extra))
    message = {"role": "assistant", "content": answer,
               "sources": cited, "sources_more": others, "sonden": probes,
               "zahlen": numbers, "entwuerfe": drafts,
               "web": pipeline.webtreffer(extra, settings["web_servers"]),
               "modell": model}
    if file_tools is not None and file_tools.created:
        message["files"] = list(file_tools.created)
    if extra:
        # What the tools returned, for the next question (see module doc).
        message["tool_log"] = pipeline.tool_log(extra)
    ids = {}
    for c in connections.values():
        ids.update(getattr(c, "new_ids", None) or {})
    if ids:
        message["ids"] = ids
    if web_draft is not None:
        message["web_search"] = (web_draft.get("argumente") or {})
    if settings["web_excluded"]:
        message["web_excluded"] = [raeume.bezeichnung(r)
                                   for r in settings["web_excluded"]]
    if list_info and list_info.get("sheets"):
        # Like the database query: which sheet, which query, how many rows.
        message["lists"] = {"sheets": [{k: s.get(k) for k in ("sheet", "query", "rows", "reason")}
                                       for s in list_info["sheets"]]}
    if sql_info:
        # The query stays with the answer: it is what the numbers rest on,
        # as a source page is for a quote.
        message["sql"] = {k: sql_info[k] for k in ("query", "rows", "reason", "none", "files", "links")
                          if k in sql_info}
    messages.append(message)
    if run:
        run.finish(message)
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
