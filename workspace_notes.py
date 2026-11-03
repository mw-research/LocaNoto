"""Summaries and notes that become documents of a workspace.

    store(user, room, title, text, source="")   -> {"room", "file", "passages", "note"}
    summarize_chat(user, chat_id, model=None)    -> {"title", "text", "source"}
    Tools(user)                                  the built-in tool server

A summary is stored like an upload: as a Markdown file in the folder
"Zusammenfassungen" of the room, split, embedded and searchable for
everyone who may read that room -- the same way, the same encryption, the
same file store sync (aufnehmen.process_uploaded_pdf). Only rooms the
user may write; an own room is always there.

THE MODEL PROPOSES, A PERSON STORES. In a chat the model gets one tool,
save_summary. Calling it does not store anything: like a mail, it becomes
a draft that shows room, title and text, and only the user's click runs
it (mailboxes.send_draft). A summary of a mail thread in a shared room is
mail content in front of every member of that room -- that is a decision,
not a side effect of a question.

WHEN THE TOOL IS OFFERED. Every tool round costs a model call before the
answer. With a mailbox connected that round runs anyway and the tool is
simply one more; without one it is offered only when the question asks
for something like it (WORKSPACE_TOOL=auto, the default), always
(always) or never (off).
"""
import datetime
import os
import re

import paths

SERVER = "workspace"
TOOL = "save_summary"
FOLDER = "Zusammenfassungen"
MAX_TEXT = 200_000
MAX_CHAT = paths.env_int("SUMMARY_MAX_CHAT_CHARS", 40_000)

_ASKS_FOR_IT = re.compile(
    r"zusammenfass|zusammengefasst|ablegen|ablage|abspeicher|speicher|notiz|"
    r"protokoll|festhalten|summar|save|store|minutes|note", re.I)


class NotWritable(Exception):
    """The user may not store documents in this room."""


class NotFound(Exception):
    pass


def offered(question, connections):
    mode = os.getenv("WORKSPACE_TOOL", "auto").strip().lower()
    if mode == "off":
        return False
    if mode == "always" or connections:
        return True
    return bool(_ASKS_FOR_IT.search(question or ""))


def writable(user):
    """[(room, label)] the user may store in; the own room first."""
    import benutzer
    import raeume
    own = raeume.sichere_anlage_privat(user)
    rooms = raeume.schreibbar(user, benutzer.ist_admin(user))
    ordered = [own] + sorted(r for r in rooms if r != own)
    return [(r, raeume.bezeichnung(r)) for r in ordered if r in rooms or r == own]


def store(user, room, title, text, source=""):
    """One summary as a document of room. Raises NotWritable, ValueError."""
    import aufnehmen
    import benutzer
    import llm
    title = " ".join(str(title or "").split())[:200]
    text = str(text or "").strip()
    if not title:
        raise ValueError("A title is needed.")
    if not text:
        raise ValueError("The summary is empty.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Longer than {MAX_TEXT} characters.")
    rooms = dict(writable(user))
    room = room or next(iter(rooms))
    if room not in rooms:
        raise NotWritable(f"No permission to store in '{room}'.")
    now = datetime.datetime.now()
    # The time in the name: two summaries with the same title are two
    # documents. With the same name the second would count as the file
    # that is already there and not be stored.
    name = paths.sicherer_dateiname(f"{title[:80]} ({now:%Y-%m-%d %H%M}).md")
    head = [f"# {title}", "", f"- Erstellt: {now:%Y-%m-%d %H:%M} von {user} "
                              f"mit LocaNoto"]
    if source:
        head.append(f"- Grundlage: {' '.join(str(source).split())[:300]}")
    content = "\n".join(head) + "\n\n---\n\n" + text + "\n"
    try:
        with llm.acting_for(user):
            passages, note = aufnehmen.process_uploaded_pdf(
                aufnehmen.Datei(name, content.encode("utf-8")), room, FOLDER,
                benutzer_=user, ist_verwalter=benutzer.ist_admin(user),
                streng=True)
    except aufnehmen.KeinRecht as e:
        raise NotWritable(str(e))
    return {"room": room, "file": name, "passages": passages, "note": note}


# --- SUMMARY OF A CHAT ---

_PROMPT = """Fasse das folgende Gespraech fuer eine Ablage zusammen, die andere spaeter durchsuchen.
Erste Zeile: ein kurzer, sprechender Titel ohne Praefix und ohne Anfuehrungszeichen.
Dann eine Leerzeile, dann die Zusammenfassung in Markdown:
- worum es ging,
- Ergebnisse und Entscheidungen,
- Zahlen, Fristen, Termine, Namen genau so wie im Gespraech,
- offene Punkte.
Nichts erfinden, was nicht im Gespraech steht. Sprache des Gespraechs."""


def summarize_chat(user, chat_id, model=None):
    """The model's summary of one of the user's chats. Raises NotFound."""
    import answering
    import chats
    import llm
    if chat_id not in {k for k, _t, _g in chats.liste(user)}:
        raise NotFound("Unknown chat.")
    lines = []
    for m in chats.lade(user, chat_id):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            who = "Frage" if m["role"] == "user" else "Antwort"
            lines.append(f"{who}: {m['content'].strip()}")
    transcript = "\n\n".join(lines)[-MAX_CHAT:]
    if not transcript:
        raise ValueError("The chat is empty.")
    model = model if model in llm.chat_modelle() else llm.modell("CHAT")
    reply = answering.client("CHAT", user).chat.completions.create(
        model=model, timeout=answering.HELPER_TIMEOUT,
        messages=[{"role": "system", "content": _PROMPT},
                  {"role": "user", "content": transcript}])
    out = (reply.choices[0].message.content or "").strip()
    chat_title = chats.titel(user, chat_id)
    head, _, body = out.partition("\n")
    title = head.strip().strip("#*\"' ").strip()
    if not body.strip():
        title, body = chat_title, out
    return {"title": title[:200] or chat_title, "text": body.strip(),
            "source": f"Chat '{chat_title}'"}


# --- THE TOOL ---

class Tools:
    """The built-in tool server: werkzeuge(), rufe(), schliesse() like
    mcp.Verbindung, so the tool loop and the drafts treat it the same.

    confirm names the tools the loop must not run but turn into drafts.
    """

    name = SERVER
    confirm = (TOOL,)

    def __init__(self, user):
        self.user = user

    def werkzeuge(self):
        rooms = writable(self.user)
        listing = "; ".join(f"{r} = {label}" for r, label in rooms)
        return [{
            "server": SERVER, "name": TOOL,
            "beschreibung": (
                "Eine Zusammenfassung oder Notiz als Dokument in einem "
                "Arbeitsbereich ablegen, damit sie dort durchsuchbar ist. Nur "
                "wenn der Nutzer das ausdruecklich will ('lege ab', 'speichere "
                "eine Zusammenfassung', 'halte fest'). 'text' ist die fertige "
                "Zusammenfassung in Markdown, die du aus dem Gespraech oder "
                "einem E-Mail-Verlauf (mail_thread) schreibst -- vollstaendig, "
                "mit Zahlen, Fristen und Namen, nichts erfunden. Der Nutzer "
                "sieht sie vor dem Ablegen und bestaetigt. Arbeitsbereiche: "
                + listing),
            "schema": {
                "type": "object",
                "properties": {
                    "room": {"type": "string", "enum": [r for r, _l in rooms],
                             "description": "Vorgabe: der eigene, " + rooms[0][0]},
                    "title": {"type": "string",
                              "description": "Kurzer, sprechender Titel."},
                    "text": {"type": "string",
                             "description": "Die Zusammenfassung, Markdown."},
                    "source": {"type": "string", "description":
                               "Worauf sie beruht, z. B. 'E-Mail-Verlauf "
                               "Angebot Meier, 12.-14.10.' oder 'dieser Chat'."},
                },
                "required": ["title", "text"],
            },
        }]

    def rufe(self, name, argumente=None):
        if name != TOOL:
            raise ValueError(f"{SERVER}: no tool '{name}'.")
        a = dict(argumente or {})
        try:
            r = store(self.user, a.get("room"), a.get("title"), a.get("text"),
                      a.get("source") or "")
        except NotWritable as e:
            raise ValueError(str(e))
        import raeume
        return (f"Abgelegt als '{r['file']}' in {raeume.bezeichnung(r['room'])}, "
                f"Ordner {FOLDER} ({r['passages']} Abschnitte durchsuchbar).")

    def schliesse(self):
        pass
