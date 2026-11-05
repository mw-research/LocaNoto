"""Mail, calendar and tickets without a mail server.

    python test_mail_tools.py

Checks, against stand-ins for the model and the mailbox:

  * the calendar in the system prompt (today, weekdays)
  * tool results stay in the chat history, draft outcomes too
  * the tool loop: a model that times out leaves a note instead of
    silence; a web search waits for the person; a mail that timed out
    but is in the sent folder counts as sent
  * short message ids are stable and survive a chat (other pods)
  * draft sending: sent after a timeout, failed, unclear -- never a 500
  * new-mail notices
  * the ticket system: standard answer, forward, notices, replies to a
    ticket, machine mail ignored, nothing answered twice

Runs in a temporary folder with files (no Postgres) and its own key.
"""
import base64
import datetime
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mailtools_")
os.environ.pop("DATABASE_URL", None)
os.environ.update({
    "LOCANOTO_KONFIG": os.path.join(TMP, "config"),
    "LOCANOTO_DATEN": os.path.join(TMP, "data"),
    "LOCANOTO_INDEX": os.path.join(TMP, "index"),
    "LOCANOTO_SCHLUESSEL": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "TIMEZONE": "Europe/Berlin",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import types  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def ns(**k):
    return types.SimpleNamespace(**k)


# --- calendar in the prompt ---

import local_time  # noqa: E402

at = datetime.datetime(2026, 11, 4, 9, 30, tzinfo=local_time.zone())   # a Wednesday
block = local_time.calendar_block("de", at)
check("calendar: today with weekday and date", "Mittwoch, der 04.11.2026" in block, block[:200])
check("calendar: today marked in the table", "[Mi 04.11.2026]" in block)
check("calendar: next Tuesday and Friday readable",
      "Di 10.11.2026" in block and "Fr 06.11.2026" in block and "Fr 13.11.2026" in block)
check("calendar: English", "Wednesday" in local_time.calendar_block("en", at))

import pipeline  # noqa: E402

check("system prompt carries the calendar", "<kalender>" in pipeline.systemprompt("ctx"))

# --- history with tool results ---

call = {"id": "c1", "type": "function",
        "function": {"name": "box__mails_lesen", "arguments": "{}"}}
send = {"id": "c2", "type": "function",
        "function": {"name": "box__mail_senden", "arguments": "{}"}}
log = pipeline.tool_log([
    {"role": "assistant", "content": "", "tool_calls": [call, send]},
    {"role": "tool", "tool_call_id": "c1", "content": "[m1] 04.11.2026 | von: Meier | Angebot"},
    {"role": "tool", "tool_call_id": "c2", "content": "NICHT ausgefuehrt. Entwurf."},
])
chat = [
    {"role": "user", "content": "Welche Mails kamen heute?"},
    {"role": "assistant", "content": "Eine Mail von Meier.", "tool_log": log,
     "entwuerfe": [{"id": "d1", "call_id": "c2", "state": "sent", "result": "Gesendet an a@b.de."}]},
    {"role": "user", "content": "Was stand in der Mail?"},
]
h = pipeline.history_for_model(chat)
roles = [m["role"] for m in h]
check("history: tool calls and results before the answer",
      roles == ["user", "assistant", "tool", "tool", "assistant", "user"], roles)
check("history: the listed mail is still known",
      any("Angebot" in (m.get("content") or "") for m in h if m["role"] == "tool"))
check("history: a confirmed draft reads as executed",
      any("bestaetigt" in (m.get("content") or "") and "Gesendet an a@b.de" in m["content"]
          for m in h if m["role"] == "tool"))
old = [dict(chat[1]) for _ in range(5)]
h2 = pipeline.history_for_model([chat[0]] + old + [chat[2]])
check("history: only the last few answers bring their tools",
      sum(1 for m in h2 if m["role"] == "tool") == 2 * pipeline.TOOL_LOG_TURNS)


# --- the tool loop ---

class Model:
    """A chat client that answers with prepared tool calls, or fails."""

    def __init__(self, rounds=None, fail=None):
        self.rounds = list(rounds or [])
        self.fail = fail
        self.chat = ns(completions=ns(create=self.create))

    def create(self, **_k):
        if self.fail:
            raise self.fail
        calls = self.rounds.pop(0) if self.rounds else []
        tool_calls = [ns(id=f"t{i}", function=ns(name=n, arguments=a))
                      for i, (n, a) in enumerate(calls)]
        return ns(choices=[ns(message=ns(content="", tool_calls=tool_calls))])


class Box:
    def __init__(self, name="box", send_error=None, found=False):
        self.name = name
        self.send_error = send_error
        self.found = found
        self.sent = []
        self.new_ids = {}

    def werkzeuge(self):
        return [{"server": self.name, "name": n, "beschreibung": n,
                 "schema": {"type": "object", "properties": {}}}
                for n in ("mails_lesen", "mail_senden", "web_suchen")]

    def rufe(self, name, args):
        if name == "mail_senden":
            self.sent.append(args)
            if self.send_error:
                raise self.send_error
            return "Gesendet."
        return f"{name} ok"

    def check_sent(self, _name, _args):
        return self.found

    def schliesse(self):
        pass


import mcp  # noqa: E402

notes = []
extra, drafts = pipeline.werkzeuglauf(Model(fail=TimeoutError("slow")), "m", "sys", chat,
                                      {"box": Box()}, hinweise=notes)
check("tool loop: a slow model leaves a note, not silence",
      any("nicht nutzbar" in n for n in notes) and extra == [] and drafts == [], notes)

web = Box("web")
web.confirm = type("Every", (), {"__contains__": lambda self, n: True})()
extra, drafts = pipeline.werkzeuglauf(
    Model([[("web__web_suchen", '{"anfrage": "Normen Druckbehaelter"}')]]), "m", "sys",
    chat, {"web": web})
check("tool loop: a web search waits for the person",
      len(drafts) == 1 and drafts[0]["argumente"]["anfrage"] == "Normen Druckbehaelter"
      and drafts[0]["call_id"] == "t0", drafts)
check("tool loop: the model is told nothing was searched",
      any("NICHT ausgefuehrt" in (m.get("content") or "") for m in extra if m["role"] == "tool"))

# a mailbox that may send on its own: the send times out, but the mail is out
mcp.schreibe_konfiguration({"box": {"transport": "exchange", "postfach": "info@test.de",
                                    "persoenlich": False, "automatisch": True,
                                    "hinweis_anhaengen": False,
                                    "sendet": ["mail_senden", "antwort_senden"]}})
late = Box(send_error=TimeoutError("read timeout"), found=True)
extra, _d = pipeline.werkzeuglauf(
    Model([[("box__mail_senden", '{"an": "a@test.de", "betreff": "x", "body": "y"}')]]),
    "m", "sys", chat, {"box": late})
check("tool loop: a timed-out mail found in the sent folder counts as sent",
      any((m.get("content") or "").startswith("Gesendet.") for m in extra if m["role"] == "tool"),
      extra)

# --- short ids ---

import postfach  # noqa: E402

a1 = postfach._merke_kennung("box:info@test.de", "LONG-EWS-ID")
a2 = postfach._merke_kennung("box:info@test.de", "LONG-EWS-ID")
check("short ids: the same message gets the same id", a1 == a2)
conn = ns(_bereich=lambda: "box:anna@test.de", new_ids={})
k = postfach.remember(conn, ("INBOX", "42"))
postfach._KENNUNGEN.clear()
postfach.load_ids(conn.new_ids)
check("short ids: kept with the chat, they resolve in another pod",
      postfach._lange_kennung("box:anna@test.de", k) == ("INBOX", "42"))
try:
    postfach._lange_kennung("box:bernd@test.de", k)
    check("short ids: not usable for another mailbox", False)
except postfach.Fehler:
    check("short ids: not usable for another mailbox", True)

check("machine mail: auto reply", postfach.is_automatic({"Auto-Submitted": "auto-replied"}, "a@b.de"))
check("machine mail: list", postfach.is_automatic({"List-Id": "<x>"}, "a@b.de"))
check("machine mail: no-reply sender", postfach.is_automatic({}, "noreply@shop.de"))
check("machine mail: the mailbox itself", postfach.is_automatic({}, "info@test.de", "info@test.de"))
check("machine mail: a person is none", not postfach.is_automatic({"Precedence": ""}, "kunde@firma.de"))

# --- sending drafts ---

import chats  # noqa: E402
import mailboxes  # noqa: E402

user = "anna"
chat_id = chats.neue_kennung()


def with_draft(draft_id):
    chats.speichere(user, chat_id, [
        {"role": "user", "content": "Schreib Meier"},
        {"role": "assistant", "content": "Entwurf liegt bereit.",
         "entwuerfe": [{"id": draft_id, "server": "box", "werkzeug": "mail_senden",
                        "argumente": {"an": "meier@test.de", "betreff": "Angebot", "body": "Hallo"}}]},
    ], "Test")


real_connect = mcp.verbinde


def send_with(box, draft_id):
    mcp.verbinde = lambda *_a, **_k: {"box": box}
    try:
        return mailboxes.send_draft(user, chat_id, draft_id, {})
    finally:
        mcp.verbinde = real_connect


with_draft("d1")
result = send_with(Box(send_error=TimeoutError("read timeout"), found=True), "d1")
_i, d = mailboxes.draft_of(user, chat_id, "d1")
check("draft: timed out but in the sent folder -> sent", d["state"] == "sent" and "sent folder" in result, d)

with_draft("d2")
try:
    send_with(Box(send_error=TimeoutError("read timeout"), found=False), "d2")
    check("draft: not in the sent folder -> failed", False)
except mailboxes.SendFailed as e:
    _i, d = mailboxes.draft_of(user, chat_id, "d2")
    check("draft: not in the sent folder -> failed, may be sent again",
          e.state == "failed" and d["state"] == "failed" and "timeout" in d["error"], d)
ok_box = Box()
send_with(ok_box, "d2")
_i, d = mailboxes.draft_of(user, chat_id, "d2")
check("draft: a failed draft can be sent again, once", d["state"] == "sent" and len(ok_box.sent) == 1)
try:
    send_with(Box(), "d2")
    check("draft: never twice", False)
except ValueError:
    check("draft: never twice", True)


class Blind(Box):
    def check_sent(self, *_a):
        raise ConnectionError("gone")


with_draft("d3")
try:
    send_with(Blind(send_error=TimeoutError("read timeout")), "d3")
except mailboxes.SendFailed as e:
    check("draft: cannot look -> unclear", e.state == "unclear")

with_draft("d4")
looked = []


class Watched(Box):
    def check_sent(self, *_a):
        looked.append(1)
        return False


try:
    send_with(Watched(send_error=postfach.Fehler("box: nicht angemeldet.")), "d4")
except mailboxes.SendFailed as e:
    check("draft: not signed in -> failed without looking", e.state == "failed" and not looked)

# --- new mail notices ---

import mail_watch  # noqa: E402
import notices  # noqa: E402


class Inbox(Box):
    def __init__(self, mails):
        super().__init__()
        self.mails = mails

    def new_messages(self, since, limit=20):
        return [m for m in self.mails if m[0] > since][:limit]


now = datetime.datetime.now(datetime.timezone.utc)
inbox = Inbox([(now + datetime.timedelta(minutes=1), "Meier <meier@test.de>", "Angebot")])
mcp.verbinde = lambda *_a, **_k: {"box": inbox}
try:
    first = mail_watch.check_one(user, "box", {})
    second = mail_watch.check_one(user, "box", {})
    third = mail_watch.check_one(user, "box", {})
finally:
    mcp.verbinde = real_connect
pend = notices.pending(user)
check("new mail: the first check only notes the time", first == 0)
check("new mail: a notice with sender and subject",
      second == 1 and len(pend) == 1 and "Meier: Angebot" in pend[0]["text"]
      and pend[0]["href"] == "/?mail=box", pend)
check("new mail: the same mail is not announced twice", third == 0)
notices.mark_shown(user, [n["id"] for n in pend])
check("notices: shown once", notices.pending(user) == [])

# --- tickets ---

import tickets  # noqa: E402


class Shared(Box):
    def __init__(self):
        super().__init__("info")
        self.mails, self.replies, self.forwards = [], [], []

    def ticket_messages(self, since, limit=50):
        return [m for m in self.mails if m["when"] > since][:limit]

    def ticket_reply(self, ref, subject, body):
        self.replies.append((ref, subject, body))

    def ticket_forward(self, ref, to, subject, body):
        self.forwards.append((ref, list(to), subject))


mcp.schreibe_konfiguration({"info": {"transport": "exchange", "postfach": "info@test.de",
                                     "persoenlich": False},
                            "mine": {"transport": "exchange", "persoenlich": True}})
ok, msg = tickets.configure("mine", True)
check("tickets: not for a personal mailbox", not ok)
ok, msg = tickets.configure("info", True, "Hallo {name}, Ihre Nummer: {ticket}",
                            ["anna", "bernd"], ["team@test.de"], "T")
check("tickets: switched on, no login stored", ok and "login" not in tickets._read_config()["info"], msg)
check("tickets: members see the mailbox, others not",
      tickets.boxes_for("anna") == ["info"] and tickets.boxes_for("carl") == []
      and tickets.boxes_for("carl", is_admin=True) == ["info"])

box = Shared()
check("tickets: the first run only notes the time", tickets.poll_once("info", box) == 0)
try:
    tickets.poll_once("info")
    check("tickets: no check without a member's login", False)
except tickets.Refused:
    check("tickets: no check without a member's login", True)
t0 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
box.mails.append({"key": "<a1@kunde>", "ref": "R1", "when": t0, "name": "Kunde",
                  "address": "kunde@firma.de", "subject": "Reklamation Pumpe",
                  "text": "Die Pumpe ist defekt.", "auto": False})
box.mails.append({"key": "<a2@shop>", "ref": "R2", "when": t0, "name": "Shop",
                  "address": "newsletter@shop.de", "subject": "Angebote",
                  "text": "...", "auto": True})
check("tickets: one new mail handled", tickets.poll_once("info", box) == 1)
year = datetime.datetime.now(datetime.timezone.utc).year
tid = f"T-{year}-0001"
check("tickets: the sender gets the standard answer with the number",
      box.replies == [("R1", f"[{tid}] Reklamation Pumpe", f"Hallo Kunde, Ihre Nummer: {tid}")],
      box.replies)
check("tickets: forwarded to the team", box.forwards == [("R1", ["team@test.de"], f"[{tid}] Reklamation Pumpe")])
check("tickets: every member gets a notice",
      all(any(tid in n["text"] for n in notices.pending(u)) for u in ("anna", "bernd")))
check("tickets: machine mail is no ticket and gets no answer",
      len(tickets.tickets_of("info")) == 1 and len(box.replies) == 1)
check("tickets: nothing is answered twice", tickets.poll_once("info", box) == 0 and len(box.replies) == 1)

tickets.update("info", tid, "anna", status="closed")
box.mails.append({"key": "<a3@kunde>", "ref": "R3", "when": t0 + datetime.timedelta(seconds=1),
                  "name": "Kunde", "address": "kunde@firma.de",
                  "subject": f"AW: [{tid}] Reklamation Pumpe", "text": "Noch eine Frage.", "auto": False})
tickets.poll_once("info", box)
t = tickets.ticket("info", tid)
check("tickets: a reply goes to the ticket and reopens it",
      t["status"] == "open" and t["events"][-1]["what"] == "mail" and len(tickets.tickets_of("info")) == 1)
check("tickets: no second standard answer", len(box.replies) == 1)
t = tickets.update("info", tid, "bernd", assignee="bernd")
check("tickets: taking it sets in progress", t["assignee"] == "bernd" and t["status"] == "in_progress")

# checked from a member's open page, with the login of that session
polled = []
real_poll = tickets.poll_once
tickets.poll_once = lambda server, conn=None, header=None: polled.append((server, header))
try:
    started = tickets.maybe_poll("anna", {"info": {"Authorization": "Basic x"}})
    again = tickets.maybe_poll("anna", {"info": {"Authorization": "Basic x"}})
    other = tickets.maybe_poll("carl", {"info": {"Authorization": "Basic x"}})
    import time as _time
    for _ in range(50):
        if polled:
            break
        _time.sleep(0.05)
finally:
    tickets.poll_once = real_poll
check("tickets: a member's page checks with the session's login",
      started == ["info"] and polled == [("info", {"Authorization": "Basic x"})], (started, polled))
check("tickets: not again within the minute, not for non-members", again == [] and other == [])

print()
if failures:
    print(f"{len(failures)} FAILED: " + "; ".join(failures))
    sys.exit(1)
print("all checks passed")
