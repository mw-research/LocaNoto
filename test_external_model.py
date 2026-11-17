"""Internal and external model: which one writes an answer.

    python test_external_model.py

Runs real questions through answering.ask with two stand-in models that
record every call: the internal one and the external one. The external
one must see nothing but the answer of a question whose every source is
released -- that is the check this file exists for.

  * the decision: each reason on its own (workspace, database, lists,
    tools, web, images, history, "/intern", the switch, keywords)
  * the external answer: one call, without glossary and personal
    instruction unless released, no pseudonym of the user
  * the chat stays internal after an internal answer
  * the external model fails: the internal one answers, with a note
  * the settings: signed; a changed file means everything internal
  * without EXTERN_*: nothing changes
  * the admin page and the API

Runs in a temporary folder with files and its own key.
"""
import base64
import json
import os
import sys
import tempfile
import types

_KEEP = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
         "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
         "LOCALAPPDATA", "PROGRAMDATA", "LANG", "TZ", "VIRTUAL_ENV",
         "SSL_CERT_FILE"}
for _v in list(os.environ):
    if _v.upper() not in _KEEP and not _v.upper().startswith(("PYTHON", "LC_")):
        del os.environ[_v]
TMP = tempfile.mkdtemp(prefix="external_")
os.environ.update({
    "LOCANOTO_KONFIG": os.path.join(TMP, "config"),
    "LOCANOTO_DATEN": os.path.join(TMP, "data"),
    "LOCANOTO_INDEX": os.path.join(TMP, "index"),
    "LOCANOTO_SCHLUESSEL": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "COOKIE_SECURE": "0", "CHAT_MODEL": "intern-a", "API_RATE_PER_MINUTE": "100000",
    "EXTERN_BASE_URL": "https://extern.invalid/v1", "EXTERN_API_KEY": "sk-test",
    "EXTERN_MODEL": "gross-1"})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  {str(detail)[:400]}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def ns(**k):
    return types.SimpleNamespace(**k)


class Recorder:
    """A chat model that records every call; streams with finish_reason."""

    def __init__(self, name, answer):
        self.name, self.answer, self.calls, self.fail = name, answer, [], None
        self.chat = ns(completions=ns(create=self.create))

    def create(self, model=None, messages=None, stream=False, **kw):
        self.calls.append({"model": model, "stream": stream, "kw": kw,
                           "system": (messages or [{}])[0].get("content") or "",
                           "messages": messages or []})
        if self.fail:
            raise self.fail
        if stream:
            text = self.answer
            return iter(ns(choices=[ns(delta=ns(content=part), finish_reason=end)])
                        for part, end in ((text[:10], None), (text[10:], "stop")))
        return ns(choices=[ns(message=ns(content="Pruefrist Kessel", tool_calls=None))])

    def answers(self):
        return [c for c in self.calls if c["stream"]]


from compare_search import HashEmbedder  # noqa: E402

EMB = HashEmbedder(64)


def _embed(*args, **_kw):
    return [EMB.vector(t) for t in args[1]]


INTERNAL = Recorder("intern", "Intern: vier Jahre [Kessel.txt, Seite 1].")
EXTERNAL = Recorder("extern", "Extern: vier Jahre [Kessel.txt, Seite 1].")

import aufnehmen  # noqa: E402
import answering  # noqa: E402
import external_model  # noqa: E402
import pipeline  # noqa: E402

aufnehmen.embed_batch = _embed
pipeline.embed_batch = _embed
answering.client = lambda task, user="": INTERNAL
answering._reranker = (None, "fusion")
external_model.client = lambda: EXTERNAL

import benutzer  # noqa: E402
import paths  # noqa: E402
import prompts  # noqa: E402
import raeume  # noqa: E402
import statefiles  # noqa: E402

benutzer.anlege("markus", "Passwort-123456", rolle="admin")
benutzer.anlege("anna", "Passwort-123456")
raeume.anlegen("einkauf", "Einkauf", mitglieder=["markus", "anna"])
for room, name, text in (
        ("allgemein", "Kessel.txt", "Die Pruefrist fuer Kessel betraegt vier Jahre. " * 6),
        ("einkauf", "Preise.txt", "Der Einkaufspreis fuer Kessel betraegt 1250 Euro. " * 6)):
    n, note = aufnehmen.process_uploaded_pdf(aufnehmen.Datei(name, text.encode()),
                                             room, benutzer_="markus", ist_verwalter=True)
    assert n, note
with statefiles.open(os.path.join(paths.CONFIG_DIR, "glossar.txt"), "w",
                     encoding="utf-8") as f:
    f.write("GLOSSARWORT: Begriff des Hauses\n")
prompts.anweisung_speichern("anna", "ANWEISUNGSWORT bitte immer kurz.")


def ask(question, **kw):
    INTERNAL.calls.clear()
    EXTERNAL.calls.clear()
    status, body = answering.answer("anna", answering.Request(question=question, **kw))
    assert status == 200, body
    return body


def release(**kw):
    data = dict(external_model.DEFAULTS, **kw)
    ok, message = external_model.save(data, by="markus")
    assert ok, message


# --- not released: internal ---

print("=== nothing released ===")
b = ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
route = b["message"]["route"]
check("the answer is internal by default",
      route["external"] is False and ["room", "Allgemein"] in route["why"], route)
check("the external model saw nothing", EXTERNAL.calls == [], EXTERNAL.calls)
check("the internal one wrote it, with glossary and personal instruction",
      len(INTERNAL.answers()) == 1 and "GLOSSARWORT" in INTERNAL.answers()[0]["system"]
      and "ANWEISUNGSWORT" in INTERNAL.answers()[0]["system"])
first_chat = b["chat_id"]

# --- released: external, and only the answer ---

print("=== Allgemein released ===")
release(rooms={"allgemein": True})
b = ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
route = b["message"]["route"]
check("with every source released the external model answers",
      route == {"external": True, "model": "gross-1", "why": []}
      and b["message"]["modell"] == "gross-1" and b["answer"].startswith("Extern"), route)
check("the external model got exactly one call: the answer",
      len(EXTERNAL.calls) == 1 and EXTERNAL.calls[0]["stream"]
      and EXTERNAL.calls[0]["model"] == "gross-1", EXTERNAL.calls)
check("everything before the answer ran internally",
      INTERNAL.calls and not INTERNAL.answers(), INTERNAL.calls)
ext_system = EXTERNAL.calls[0]["system"]
check("it got the passage it answers from",
      "Pruefrist fuer Kessel" in ext_system and "Einkaufspreis" not in ext_system)
check("glossary and personal instruction stay home unless released",
      "GLOSSARWORT" not in ext_system and "ANWEISUNGSWORT" not in ext_system)
check("no user name or pseudonym goes along",
      "user" not in EXTERNAL.calls[0]["kw"] and "anna" not in ext_system)
external_chat = b["chat_id"]

release(rooms={"allgemein": True}, house_texts=True)
ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
check("released, they go along",
      EXTERNAL.calls and "GLOSSARWORT" in EXTERNAL.calls[0]["system"]
      and "ANWEISUNGSWORT" in EXTERNAL.calls[0]["system"])
release(rooms={"allgemein": True})

# --- what keeps an answer internal ---

print("=== reasons to stay internal ===")
b = ask("Und wie teuer ist ein Kessel?", rooms=["allgemein", "einkauf"])
check("a workspace that is not released keeps it internal",
      not EXTERNAL.calls and ["room", "Einkauf"] in b["message"]["route"]["why"],
      b["message"]["route"])
b = ask("Und wie oft?", chat_id=first_chat, rooms=["allgemein"])
check("after an internal answer the chat stays internal",
      not EXTERNAL.calls and ["history", ""] in b["message"]["route"]["why"],
      b["message"]["route"])
b = ask("Und die aeussere Pruefung?", chat_id=external_chat, rooms=["allgemein"])
check("after external answers it may continue externally",
      len(EXTERNAL.answers()) == 1, b["message"]["route"])
b = ask("/intern Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
check("/intern at the start: internal, and the command is not part of the question",
      not EXTERNAL.calls and ["asked", ""] in b["message"]["route"]["why"]
      and b["events"]["chat"]["chat_id"]
      and answering.chats.lade("anna", b["chat_id"])[0]["content"]
      == "Wie lang ist die Pruefrist fuer Kessel?", b["message"]["route"])
intern_chat = b["chat_id"]
b = ask("Und wie oft?", chat_id=intern_chat, rooms=["allgemein"])
check("and the chat stays internal", not EXTERNAL.calls)
b = ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"], intern=True)
check("the switch in the chat: internal",
      not EXTERNAL.calls and ["asked", ""] in b["message"]["route"]["why"])
b = ask("Wie lang ist die vertrauliche Pruefrist fuer Kessel?", rooms=["allgemein"])
check("a keyword in the question: internal",
      not EXTERNAL.calls and ["keyword", "vertraulich"] in b["message"]["route"]["why"],
      b["message"]["route"])
b = ask("Gilt die Pruefrist fuer Kessel international?", rooms=["allgemein"])
check("a keyword counts only as a word ('international' is not 'intern')",
      len(EXTERNAL.calls) == 1, b["message"]["route"])

# --- the decision on its own ---

print("=== the decision ===")
hit = {"meta": {"raum": "allgemein"}, "text": "x"}
d = external_model.decide


def why(**kw):
    return (d(kw.pop("question", "Frage"), **kw) or {}).get("why")


tool_call = lambda server, tool="t": [{"role": "assistant", "content": "", "tool_calls": [
    {"id": "1", "type": "function", "function": {"name": f"{server}__{tool}", "arguments": "{}"}}]}]
check("a passage of unknown origin", ["unknown_source", ""] in why(hits=[{"meta": {}}]))
check("a personal workspace unless released",
      ["room", raeume.bezeichnung(raeume.privat_kennung("anna"))]
      in why(hits=[{"meta": {"raum": raeume.privat_kennung("anna")}}]))
check("the database", why(hits=[hit], blocks=[("datenbank_ergebnis", "| a |")])
      == [["database", ""]])
check("the lists", why(blocks=[("liste_ergebnis", "| a |")]) == [["lists", ""]])
check("a block of an unknown kind", why(blocks=[("neu", "x")]) == [["unknown_source", ""]])
check("a mailbox or a data connector whose tool ran",
      why(hits=[hit], extra=tool_call("erp")) == [["tool", "erp"]])
check("the web search", why(hits=[hit], extra=tool_call("websuche", "web_suchen"),
                            web_servers={"websuche"}) == [["web", ""]])
check("LocaNoto's own tools bring nothing in",
      why(hits=[hit], extra=tool_call("workspace"), builtin=("workspace",)) == [])
check("an image in the chat", ["image", ""] in why(hits=[hit], image_texts=["Bild"]))
check("a chat without a source unless released", why() == [["no_source", ""]])
check("an answer of an earlier version (no route) counts as internal",
      ["history", ""] in why(hits=[hit], history=[{"role": "assistant", "content": "x"}]))
release(rooms={"allgemein": True}, database=True, lists=True, web=True,
        tools={"erp": True}, no_source=True, personal=True)
check("everything released: external",
      why(hits=[hit], blocks=[("datenbank_ergebnis", "x"), ("liste_ergebnis", "y")],
          extra=tool_call("erp") + tool_call("websuche"), web_servers={"websuche"}) == []
      and why() == [])
check("/intern and /internal, at the start only",
      external_model.take_command("/intern  Frage") == (True, "Frage")
      and external_model.take_command("/Internal: Frage") == (True, "Frage")
      and external_model.take_command("Frage /intern") == (False, "Frage /intern")
      and external_model.take_command("/internet") == (False, "/internet"))

# --- the external model fails ---

print("=== the external model fails ===")
EXTERNAL.fail = ConnectionError("down")
b = ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
check("the internal model answers, and it says why",
      b["answer"].startswith("Intern") and len(INTERNAL.answers()) == 1
      and b["message"]["route"]["why"] == [["external_failed", ""]], b["message"]["route"])
check("with the full internal prompt", "GLOSSARWORT" in INTERNAL.answers()[0]["system"])
EXTERNAL.fail = None

# --- the settings ---

print("=== the settings ===")
release(rooms={"allgemein": True})
with open(external_model.SETTINGS, encoding="utf-8") as f:
    raw = json.load(f)
raw["settings"]["rooms"]["einkauf"] = True
with open(external_model.SETTINGS, "w", encoding="utf-8") as f:
    json.dump(raw, f)
check("a changed settings file counts as: nothing released",
      external_model.settings() == external_model.DEFAULTS)
release(rooms={"allgemein": True}, keywords=["  Streng ", ""], tools={"x": "yes"})
s = external_model.settings()
check("only known keys and types are kept",
      s["keywords"] == ["streng"] and s["tools"] == {} and s["rooms"] == {"allgemein": True})
check("each change of the release is in the user log",
      any(e.get("aktion") == "extern_freigabe" for e in benutzer.protokoll(letzte=50)))

import llm  # noqa: E402

seen = []
g = llm.GuardedClient("EXTERN", [("x", ns(chat=ns(completions=ns(
    create=lambda **kw: seen.append(kw) or "ok"))))])
llm.SEND_USER = "pseudonym"
with llm.acting_for("anna"):
    g.chat.completions.create(model="m")
llm.SEND_USER = "off"
check("the client of the external model never sends a pseudonym", "user" not in seen[0], seen)

# --- the pages ---

print("=== pages and API ===")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


def client_for(user):
    c = TestClient(server.app)
    r = c.post("/api/v1/auth/login", json={"username": user, "password": "Passwort-123456"})
    assert r.status_code == 200, r.text
    c.headers["X-LocaNoto-CSRF"] = c.cookies.get("locanoto_csrf")
    return c


markus, anna = client_for("markus"), client_for("anna")
page = markus.get("/admin/external").text
check("the admin page lists the sources with the model",
      "gross-1" in page and 'name="room" value="einkauf"' in page
      and 'name="no_source"' in page and 'name="keywords"' in page)
r = markus.post("/ui/admin/external", data={"room": ["einkauf"], "database": "1",
                                            "keywords": "geheim, intern"})
s = external_model.settings()
check("saving the page releases exactly what is ticked",
      r.status_code == 200 and s["rooms"] == {"einkauf": True} and s["database"]
      and not s["web"] and s["keywords"] == ["geheim", "intern"], s)
check("a user cannot change it",
      anna.post("/ui/admin/external", data={"web": "1"}).status_code == 403
      and anna.put("/api/v1/admin/external-model", json={"web": True}).status_code == 403
      and not external_model.settings()["web"])
r = markus.put("/api/v1/admin/external-model", json={"rooms": {"allgemein": True}})
check("the API sets the release", r.status_code == 200
      and markus.get("/api/v1/admin/external-model").json()["settings"]["rooms"]
      == {"allgemein": True}, r.text)
check("the chat page offers the switch", 'name="intern"' in anna.get("/").text)
r = anna.post("/api/v1/ask", json={"question": "Wie lang ist die Pruefrist fuer Kessel?",
                                    "rooms": ["allgemein"], "intern": True})
check("the API takes intern=true", r.status_code == 200
      and r.json()["message"]["route"]["why"] == [["asked", ""]], r.text[:300])
html = anna.get(f"/c/{r.json()['chat_id']}").text
check("under the answer: which model and why",
      "Beantwortet vom internen Modell" in html or "Answered by the internal model" in html)

# --- without EXTERN_* ---

print("=== not set up ===")
os.environ.pop("EXTERN_BASE_URL")
b = ask("Wie lang ist die Pruefrist fuer Kessel?", rooms=["allgemein"])
check("without EXTERN_BASE_URL nothing changes: no route, internal answer",
      "route" not in b["message"] and not EXTERNAL.calls and len(INTERNAL.answers()) == 1)
check("no switch in the chat", 'name="intern"' not in anna.get("/").text)
check("the admin page says how to set it up",
      "EXTERN_BASE_URL" in markus.get("/admin/external").text)

print()
if failures:
    print(f"{len(failures)} failed:")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all passed")
