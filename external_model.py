"""Internal and external language model: which one writes an answer.

An answer is made in several model calls: the chat title, the search
terms, the SQL query, the choice of a list, the tool calls -- and at the
end the answer itself. Every call before the answer runs on the model in
the house. Only the answer can go to an external model (Azure OpenAI,
OpenAI, or anything an OpenAI-compatible gateway reaches), and the choice
is made right before it, when it is known what lies in the context.

THE RULE. The answer goes out only when every part of its context is
released for it by the operator: each workspace a passage comes from, the
database, the lists, each mailbox and data connector a tool of was
called, the web search. And only when the chat has had no internal answer
(the history goes along), no image is in it, and the user did not ask for
internal ("/intern", the switch in the chat, a keyword). Anything that
cannot be checked counts as not released. The default is internal
everywhere; "external" is an allowance, never a requirement.

    configured()                      EXTERN_BASE_URL and EXTERN_MODEL set
    settings() / save(data, by)       the operator's release, signed
    take_command(question)            (asked_internal, question without "/intern")
    decide(...)                       {"external", "model", "why"}

Without EXTERN_* nothing of this is active: no page, no switch, every
answer as before.

SETTINGS (config/external_model.json, signed with the installation key;
an unsigned or broken file counts as "everything internal")

    no_source     a chat without any source (no passage, no tool, no data)
    rooms         {workspace: True} -- shared workspaces released
    personal      personal workspaces released
    database      results of the database query
    lists         results of list queries
    web           results of the web search
    tools         {server: True} -- mailboxes and data connectors released
    house_texts   glossary and personal instruction go along (else left
                  out of the external system prompt)
    keywords      words in a question that keep its answer internal
"""
import json
import os
import re

import benutzer
import dateisperre
import geheim
import paths
import raeume
import statefiles

SETTINGS = os.path.join(paths.CONFIG_DIR, "external_model.json")
TASK = "EXTERN"

DEFAULT_KEYWORDS = ["intern", "internal", "vertraulich", "confidential",
                    "geheim", "secret"]

DEFAULTS = {"no_source": False, "rooms": {}, "personal": False,
            "database": False, "lists": False, "web": False, "tools": {},
            "house_texts": False, "keywords": DEFAULT_KEYWORDS}

# What a reason in decide() means; the page translates the words.
REASONS = {
    "asked": "asked for by the user",
    "keyword": "keyword in the question",
    "history": "earlier answer in this chat internal",
    "image": "image in the chat",
    "no_source": "chat without a source",
    "room": "workspace",
    "unknown_source": "passage of unknown origin",
    "database": "database",
    "lists": "lists",
    "web": "web search",
    "tool": "tool",
    "external_failed": "external model not reachable",
}


def configured():
    """Is an external model set up? Not the general fallback address:
    without its own EXTERN_BASE_URL there is no external model."""
    return bool(os.getenv("EXTERN_BASE_URL", "").strip()
                and os.getenv("EXTERN_MODEL", "").strip())


def model():
    return os.getenv("EXTERN_MODEL", "").strip()


def client():
    import llm
    return llm.client(TASK)


# --- SETTINGS ---

def _clean(data):
    """The settings with only known keys, in their types."""
    data = data if isinstance(data, dict) else {}
    out = dict(DEFAULTS)
    for key in ("no_source", "personal", "database", "lists", "web",
                "house_texts"):
        out[key] = data.get(key) is True
    for key in ("rooms", "tools"):
        value = data.get(key) if isinstance(data.get(key), dict) else {}
        out[key] = {str(k): True for k, v in value.items() if v is True}
    words = data.get("keywords")
    if isinstance(words, list):
        out["keywords"] = [w for w in (str(x).strip().lower() for x in words)
                           if w and len(w) <= 40][:50]
    return out


def settings():
    """The operator's release. Missing, unsigned or broken: all internal."""
    try:
        with statefiles.open(SETTINGS, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULTS)
    data = raw.get("settings") if isinstance(raw, dict) else None
    if not isinstance(data, dict) or not geheim.pruefe_signatur(
            geheim.kanonisch(data), raw.get("signature") or ""):
        return dict(DEFAULTS)
    return _clean(data)


def save(data, by="?"):
    """Store the release. (ok, message)."""
    if geheim.schluessel() is None:
        return False, "No installation key: the settings cannot be signed."
    data = _clean(data)
    text = json.dumps({"settings": data,
                       "signature": geheim.signiere(geheim.kanonisch(data))},
                      ensure_ascii=False, indent=1)
    statefiles.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    dateisperre.schreibe_atomar(SETTINGS, text, 0o600)
    released = sorted(k for k in ("no_source", "personal", "database", "lists",
                                  "web") if data[k])
    released += [f"room:{r}" for r in sorted(data["rooms"])]
    released += [f"tool:{s}" for s in sorted(data["tools"])]
    benutzer.protokolliere("extern_freigabe", "external_model", by,
                           ", ".join(released) or "nichts")
    return True, "Saved."


# --- WHAT THE USER ASKED FOR ---

_COMMAND = re.compile(r"^\s*/intern(?:al)?\b[\s:,.-]*", re.I)


def take_command(question):
    """(asked_internal, question): "/intern" at the start is a command,
    not part of the question."""
    question = question or ""
    m = _COMMAND.match(question)
    if not m:
        return False, question
    return True, question[m.end():].strip()


# German endings a keyword may carry: "vertrauliche", "internen",
# "geheimes". Not any continuation -- "international" is not "intern".
_ENDINGS = r"(?:e|en|em|er|es|n|s)?"


def keyword_in(question, words):
    """The first keyword that stands as a word in the question, or ""."""
    text = (question or "").lower()
    for w in words or ():
        if re.search(r"(?<!\w)" + re.escape(w) + _ENDINGS + r"(?!\w)", text):
            return w
    return ""


# --- THE DECISION ---

def called_servers(extra):
    """Tool servers whose tools ran in this answer (from the tool messages)."""
    import mcp
    out = []
    for m in extra or ():
        for call in m.get("tool_calls") or ():
            server, _name = mcp.teile_namen((call.get("function") or {}).get("name"))
            if server and server not in out:
                out.append(server)
    return out


def decide(question, hits=(), blocks=(), extra=(), image_texts=(),
           history=(), asked=False, web_servers=(), builtin=()):
    """Which model writes this answer.

    Returns {"external": bool, "model": name or "", "why": [[kind, name], ...]}
    -- why holds every reason it stays internal; empty when external. None
    when no external model is set up (then nothing is shown either).
    """
    if not configured():
        return None
    s = settings()
    why = []

    def add(kind, name=""):
        if [kind, name] not in why:
            why.append([kind, name])

    if asked:
        add("asked")
    word = keyword_in(question, s["keywords"])
    if word:
        add("keyword", word)
    # Earlier answers: the history goes along. An answer without a route
    # (from before, or one that broke off) counts as internal.
    if any(m.get("role") == "assistant"
           and not (m.get("route") or {}).get("external") for m in history or ()):
        add("history")
    if image_texts:
        add("image")

    sources = False
    for h in hits or ():
        sources = True
        room = str((h.get("meta") or {}).get("raum") or "")
        if not room:
            add("unknown_source")
        elif raeume.ist_privat(room):
            if not s["personal"]:
                add("room", raeume.bezeichnung(room))
        elif not s["rooms"].get(room):
            add("room", raeume.bezeichnung(room))
    for name, _content in blocks or ():
        sources = True
        name = str(name)
        if name.startswith("datenbank"):
            if not s["database"]:
                add("database")
        elif name.startswith("liste"):
            if not s["lists"]:
                add("lists")
        else:
            add("unknown_source")
    for server in called_servers(extra):
        if server in builtin:
            continue          # LocaNoto's own tools bring no data in
        sources = True
        if server in web_servers:
            if not s["web"]:
                add("web")
        elif not s["tools"].get(server):
            add("tool", server)
    if not sources and not image_texts and not s["no_source"]:
        add("no_source")

    external = not why
    return {"external": external, "model": model() if external else "",
            "why": why}
