"""Self-test, part 05: Tokens, the API behind a prefix, mailbox credentials, SQL, IMAP/SMTP, attachments, created files.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- JEDER SIEHT NUR SEINE EIGENEN TOKEN ---
#
# Bisher sah niemand ausser dem Verwalter, dass ueberhaupt ein Token auf
# seine Kennung ausgestellt ist. Ein Token traegt die Rechte seines
# Besitzers -- wer nicht weiss, dass eines existiert, kann auch nicht
# merken, dass es zu viele sind.
#
# Die Anzeige haengt an einer Eigenschaft: auth.liste() gibt ALLE
# zurueck, und die Trennung ist der Filter darauf. Der wird mit echten
# Token durchgespielt.
import auth as _auth

# Ausdruecklich in den Wegwerfbestand, wie bei den anderen auch. Der
# Pfad entsteht beim Import aus paths.CONFIG_DIR und zeigt hier schon
# richtig -- ihn trotzdem zu setzen kostet nichts und schliesst aus,
# dass dieser Test je an echte Token kommt.
_auth.TOKEN_FILE = os.path.join(paths.CONFIG_DIR, "tokens.json")

_t_markus = _auth.erzeuge("markus", "Masseningest")
_t_anna = _auth.erzeuge("anna", "Laptop")
pruef("ein Token kommt genau einmal heraus",
      isinstance(_t_markus, str) and _t_markus != _t_anna)
pruef("und weist seinen Besitzer aus",
      _auth.pruefe(_t_markus) == "markus"
      and _auth.pruefe(_t_anna) == "anna")


def _meine(wer):
    """Derselbe Filter wie in der Oberflaeche."""
    return [(h, e) for h, e in _auth.liste() if e.get("benutzer") == wer]


pruef("jeder sieht nur seine eigenen",
      [e["bezeichnung"] for _h, e in _meine("markus")] == ["Masseningest"]
      and [e["bezeichnung"] for _h, e in _meine("anna")] == ["Laptop"],
      [(h[:6], e.get("benutzer")) for h, e in _auth.liste()])

# Und der Widerruf trifft genau eines. Der volle Hashwert wird
# uebergeben und nicht sein Anfang: auth.widerrufe trifft bei einem
# mehrdeutigen Anfang absichtlich keinen.
_h_anna = _meine("anna")[0][0]
pruef("ein Widerruf trifft genau eines", _auth.widerrufe(_h_anna) == 1)
pruef("und danach gilt es nicht mehr", _auth.pruefe(_t_anna) is None)
pruef("das fremde bleibt unberuehrt", _auth.pruefe(_t_markus) == "markus")
_auth.widerrufe(_meine("markus")[0][0])


# --- DIE SCHNITTSTELLE LAESST SICH AUCH HINTER EINEM PRAEFIX ANSEHEN ---
#
# FastAPI liefert unter /hilfe eine bedienbare Oberflaeche -- die
# knappste Dokumentation, die nicht veralten kann. Im Cluster steht sie
# hinter /api, weil Traefik das Praefix abschneidet. Ohne root_path holt
# die Seite ihr Schema von "/openapi.json" statt "/api/openapi.json" und
# bleibt leer; "Try it out" schickt an die falsche Adresse. Die
# Schnittstelle war da und liess sich nicht ansehen.
_apiq = _datei("api.py")
pruef("die Schnittstelle kennt ihren Wurzelpfad",
      "API_WURZELPFAD" in _apiq and "root_path=API_WURZELPFAD" in _apiq)
pruef("und die Bedienoberflaeche bleibt erreichbar",
      'docs_url="/hilfe"' in _apiq)

# --- DAS ABBILD SAGT, AUS WELCHEM STAND ES GEBAUT WURDE ---
#
# Ausgerollt wird der wandernde Kennzeichner, und aus dessen Digest kam
# niemand auf den Commit zurueck: im Cluster liess sich nur feststellen,
# dass das Abbild NEUER ist. Genau diese Verwechslung hat zwei Rollouts
# zuvor gebissen -- zwei Ablagen bauen unabhaengig, "neuer als vorher"
# galt fuer beide, und nur eine trug die Korrektur.
_bau = _datei(os.path.join(".github", "workflows", "abbild.yml"))
pruef("das Abbild traegt den Commit als Marke",
      "org.opencontainers.image.revision=${{ github.sha }}" in _bau)


# --- ANMELDEDATEN GEHEN NUR AN IHR EIGENES POSTFACH ---
#
# verbinde() nahm frueher EINEN Kopf und gab ihn an jeden Server weiter.
# Bei einem persoenlichen Postfach und mehreren Funktionspostfaechern
# waere damit das Passwort des Nutzers an jeden eingerichteten Server
# gegangen -- auch an die, mit denen er nichts zu tun hat.
import json as _js0
import mcp as _mcp0

_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_koepfe.json")
_js0.dump({"persoenlich": {"transport": "http", "url": "http://x",
                           "anmeldung": "basic"},
           "info": {"transport": "http", "url": "http://y",
                    "anmeldung": "keine"}},
          statefiles.open(_mcp0.KONFIG, "w", encoding="utf-8"))

pruef("ein persoenliches Postfach verlangt eine Anmeldung",
      _mcp0.braucht_anmeldung("persoenlich"))
pruef("ein Funktionspostfach mit Dienstkonto nicht",
      not _mcp0.braucht_anmeldung("info"))

_kopf = _mcp0.kopf_fuer("persoenlich", "markus", "geheim")
pruef("Benutzer und Passwort werden zu einem Basic-Kopf",
      _kopf.get("Authorization", "").startswith("Basic "), _kopf)

_vb0 = _mcp0.verbinde({"persoenlich": _kopf})
pruef("der Kopf erreicht sein Postfach",
      _vb0["persoenlich"].zusatz_kopf == _kopf)
pruef("und KEIN anderes",
      _vb0["info"].zusatz_kopf == {}, _vb0["info"].zusatz_kopf)

# Und die Oberflaeche reicht eine Zuordnung durch, keinen einzelnen Kopf.

statefiles.remove(_mcp0.KONFIG)
_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# --- SQL: TEMPLATE SHIPPED, ROOM NOTE REACHES THE MODEL ---
import sqldb as _sqd
import types as _tys


class _SqlClient:
    gesehen = []

    def __init__(self):
        self.chat = _tys.SimpleNamespace(completions=_tys.SimpleNamespace(
            create=self.create))

    def create(self, **kw):
        _SqlClient.gesehen.append(kw["messages"][0]["content"])
        return _tys.SimpleNamespace(choices=[_tys.SimpleNamespace(
            message=_tys.SimpleNamespace(content="SELECT 1 FROM dbo.Auftraege"))])


pruef("die Vorlage fuer Datenbankabfragen wird mitgeliefert",
      os.path.exists(os.path.join(_ROOT,
                                  "sql_prompt.txt")))
_sq = _sqd.formuliere(_SqlClient(), "m", "Welche Auftraege sind offen?",
                      "dbo.Auftraege(AuftragsNr int, Status nvarchar)",
                      hinweis_raum="Status 'O' heisst offen.")
pruef("der Hinweis des Arbeitsbereichs steht im Prompt",
      _sq.startswith("SELECT") and "Status 'O' heisst offen." in _SqlClient.gesehen[-1]
      and "dbo.Auftraege(AuftragsNr int" in _SqlClient.gesehen[-1],
      _SqlClient.gesehen[-1][-300:])

# --- IMAP/SMTP MAILBOX (imap_mailbox.py) against stand-in servers ---
import base64 as _b64i
import email as _emi
import email.policy as _empi
import imap_mailbox as _imb
import postfach as _pfi
from email.message import EmailMessage as _EMi


def _mail_i(uid, frm, subject, body, date, msgid, refs=""):
    m = _EMi()
    m["From"], m["To"], m["Subject"] = frm, "anna@example.com", subject
    m["Date"], m["Message-ID"] = date, msgid
    if refs:
        m["References"] = refs
    m.set_content(body)
    return uid, m.as_bytes()


_MAILS_I = {
    "INBOX": [
        _mail_i(b"1", "Meier <meier@example.com>", "Angebot Ölpumpe",
                "Anbei das Angebot über 12.400 EUR.", "Mon, 12 Oct 2026 08:00:00 +0200", "<a1@x>"),
        _mail_i(b"3", "Meier <meier@example.com>", "AW: Angebot Ölpumpe",
                "Einverstanden.\n\nAm 13.10. schrieb Anna:\n> alt", "Wed, 14 Oct 2026 08:00:00 +0200",
                "<a3@x>", "<a1@x> <a2@x>"),
        _mail_i(b"4", "Shop <news@shop.example>", "Newsletter", "Angebote",
                "Thu, 15 Oct 2026 08:00:00 +0200", "<n4@x>"),
    ],
    "INBOX-ATT": [],
    "Sent": [
        _mail_i(b"2", "anna@example.com", "RE: Angebot Ölpumpe", "Bitte 3 % Skonto.",
                "Tue, 13 Oct 2026 08:00:00 +0200", "<a2@x>", "<a1@x>"),
    ],
}


class _FakeImap:
    log = []

    def __init__(self, host, port, ssl_context=None, timeout=None):
        _FakeImap.log.append(("connect", host, port))
        self.folder = None

    def login(self, user, password):
        if password != "app-pass":
            raise _imb.imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        _FakeImap.log.append(("login", user))

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "Sent"',
                      b'(\\HasNoChildren \\Trash) "/" "Papierkorb"',
                      b'(\\HasNoChildren) "/" "Archiv"']

    def select(self, folder, readonly=False):
        self.folder = folder.strip('"')
        return "OK", [b"1"]

    def uid(self, command, *args):
        mails = _MAILS_I.get(self.folder, [])
        if command == "SEARCH":
            words = list(args)
            hits = []
            for uid, raw in mails:
                m = _emi.message_from_bytes(raw, policy=_empi.default)
                ok = True
                for key in ("FROM", "SUBJECT", "TEXT"):
                    if key in words:
                        value = words[words.index(key) + 1].strip('"').lower()
                        field = {"FROM": m["From"], "SUBJECT": m["Subject"]}.get(key, raw.decode())
                        ok = ok and value in str(field).lower()
                if ok:
                    hits.append(uid)
            return "OK", [b" ".join(hits)]
        if command == "FETCH":
            for uid, raw in mails:
                if uid == args[0] or uid.decode() == args[0]:
                    return "OK", [(b"1 (BODY[] {n}", raw), b")"]
            return "OK", []
        if command in ("STORE", "MOVE"):
            _FakeImap.log.append((command, self.folder) + tuple(
                a.decode() if isinstance(a, bytes) else a for a in args))
            return "OK", []
        raise AssertionError(command)

    def append(self, folder, flags, when, data):
        _FakeImap.log.append(("append", folder))
        return "OK", []

    def logout(self):
        pass


class _FakeSmtp:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        _FakeSmtp.sent.append(msg)

    def quit(self):
        pass


def _wirft_i(call):
    try:
        call()
    except _pfi.Fehler:
        return True
    return False


_real_imap, _real_smtp = _imb.imaplib.IMAP4_SSL, _imb.smtplib.SMTP
_imb.imaplib.IMAP4_SSL, _imb.smtplib.SMTP = _FakeImap, _FakeSmtp
try:
    pruef("IMAP target: SMTP host derived, ports by default",
          _imb.parse_target("imap.gmail.com") == ("imap.gmail.com", 993, "smtp.gmail.com", 587)
          and _imb.parse_target("imap.gmx.net, mail.gmx.net:465")
          == ("imap.gmx.net", 993, "mail.gmx.net", 465))
    _head = {"Authorization": "Basic " + _b64i.b64encode(b"anna@example.com:app-pass").decode()}
    _box = _imb.ImapMailbox("mail", {"transport": "imap", "imap_host": "imap.example.com",
                                     "imap_port": 993, "smtp_host": "smtp.example.com",
                                     "smtp_port": 587}, _head)
    _tools_i = {w["name"] for w in _box.werkzeuge()}
    pruef("IMAP mailbox: logs in and offers the mail tools, no calendar",
          _tools_i == set(_imb.TOOLS), _tools_i)
    _lst = _box.rufe("mails_lesen", {"von": "meier"})
    pruef("IMAP: messages by sender, newest first",
          _lst.index("AW: Angebot") < _lst.index("Anbei das Angebot") and "Newsletter" not in _lst,
          _lst)
    pruef("IMAP: a search word with umlauts is matched in the app",
          "Ölpumpe" in _box.rufe("mails_lesen", {"suchtext": "Ölpumpe"})
          and "Newsletter" not in _box.rufe("mails_lesen", {"suchtext": "Ölpumpe"}))
    _k_i = _lst.split("]", 1)[0].split("[", 1)[1]
    _thr = _box.rufe("mail_thread", {"kennung": _k_i})
    pruef("IMAP: the thread over inbox and sent, oldest first, without quotes",
          _thr.index("12.400") < _thr.index("Skonto") < _thr.index("Einverstanden")
          and "> alt" not in _thr and "3 Nachricht(en)" in _thr, _thr)
    _box.attachment_source = lambda names: [("Angebot.pdf", b"%PDF-1.4 test", "application/pdf")]
    _out_i = _box.rufe("mail_senden", {"an": "meier@example.com", "betreff": "Unterlagen",
                                       "body": "Anbei.", "anhaenge": ["Angebot.pdf"]})
    _sent_i = _FakeSmtp.sent[-1]
    pruef("IMAP: a new mail goes out with its attachment and a copy in Sent",
          "Anhänge: Angebot.pdf" in _out_i
          and [a.get_filename() for a in _sent_i.iter_attachments()] == ["Angebot.pdf"]
          and ("append", '"Sent"') in _FakeImap.log, (_out_i, _FakeImap.log[-3:]))
    _box.rufe("antwort_senden", {"kennung": _k_i, "body": "Danke."})
    _rep_i = _FakeSmtp.sent[-1]
    pruef("IMAP: a reply carries In-Reply-To, References and Re:",
          _rep_i["In-Reply-To"] == "<a3@x>" and "<a1@x>" in _rep_i["References"]
          and _rep_i["Subject"].startswith("AW:") and _rep_i["To"] == "meier@example.com",
          (_rep_i["Subject"], _rep_i["To"]))
    # attachments, read state, forward, move
    _att_m = _EMi()
    _att_m["From"], _att_m["To"], _att_m["Subject"] = ("Lieferant <l@example.com>",
                                                       "anna@example.com", "Lieferschein 24004")
    _att_m["Date"], _att_m["Message-ID"] = "Fri, 16 Oct 2026 08:00:00 +0200", "<l5@x>"
    _att_m.set_content("Anbei der Lieferschein.")
    _att_m.add_attachment("Lieferung vollständig, 3 Paletten".encode(), maintype="text",
                          subtype="plain", filename="lieferschein.txt")
    _MAILS_I["INBOX"].append((b"5", _att_m.as_bytes()))
    _k5_i = _pfi.remember(_box, ("INBOX", "5"))
    _ai = _box.rufe("mail_attachments", {"kennung": _k5_i})
    pruef("IMAP: attachments listed with their text",
          "lieferschein.txt" in _ai and "3 Paletten" in _ai, _ai)
    _box.rufe("mail_mark", {"kennung": _k5_i, "read": True})
    pruef("IMAP: marked read with the Seen flag",
          ("STORE", "INBOX", "5", "+FLAGS", "(\\Seen)") in _FakeImap.log, _FakeImap.log[-2:])
    _vfi = _box.pruefe_entwurf("mail_forward", {"kennung": _k5_i, "an": "meier@example.com"})
    pruef("IMAP: forward preview with subject and attachment",
          "WG: Lieferschein 24004" in _vfi and "lieferschein.txt" in _vfi, _vfi)
    _box.rufe("mail_forward", {"kennung": _k5_i, "an": "meier@example.com", "body": "Zur Info"})
    _fw_i = _FakeSmtp.sent[-1]
    pruef("IMAP: forwarded with the original text and its attachment",
          _fw_i["Subject"] == "WG: Lieferschein 24004" and "Anbei der Lieferschein" in
          _fw_i.get_body().get_content()
          and [a.get_filename() for a in _fw_i.iter_attachments()] == ["lieferschein.txt"],
          _fw_i["Subject"])
    pruef("IMAP: a forward to a name without address is refused (no address book)",
          _wirft_i(lambda: _box.pruefe_entwurf("mail_forward", {"kennung": _k5_i,
                                                                 "an": "Herr Meier"})))
    _vmi = _box.pruefe_entwurf("mail_move", {"kennung": _k5_i, "ordner": "papierkorb"})
    pruef("IMAP: the trash is found by its special-use flag",
          "→ Papierkorb" in _vmi, _vmi)
    _box.rufe("mail_move", {"kennung": _k5_i, "ordner": "archiv"})
    pruef("IMAP: moved with MOVE into the archive",
          ("MOVE", "INBOX", "5", '"Archiv"') in _FakeImap.log, _FakeImap.log[-2:])
    _box.schliesse()
    _bad = _imb.ImapMailbox("mail", {"imap_host": "x", "smtp_host": "y"}, {
        "Authorization": "Basic " + _b64i.b64encode(b"anna@example.com:wrong").decode()})
    try:
        _bad.werkzeuge()
        pruef("IMAP: a wrong password is refused", False)
    except _pfi.Fehler as _e:
        pruef("IMAP: a wrong password is refused", "abgelehnt" in str(_e))
finally:
    _imb.imaplib.IMAP4_SSL, _imb.smtplib.SMTP = _real_imap, _real_smtp

# --- attachments only from the own workspace and the chat ---
import attachments as _att
_own_a = raeume.sichere_anlage_privat("markus")
_dir_a = paths.raum_ordner(_own_a)
statefiles.makedirs(_dir_a, exist_ok=True)
with statefiles.open(os.path.join(_dir_a, "Angebot-markus.txt"), "wb") as _f:
    _f.write(b"own file")
_real_docs = pipeline.dokumente
pipeline.dokumente = lambda user, nur=None, notzugang=(): (
    {_own_a: ["Angebot-markus.txt"]} if user == "markus" else {})
try:
    _files_a = _att.resolve("markus", None, ["Angebot-markus.txt"])
    pruef("a document of the own workspace can be attached",
          _files_a == [("Angebot-markus.txt", b"own file", "text/plain")], _files_a)
    try:
        _att.resolve("markus", None, ["Vertrag-aus-Einkauf.pdf"])
        pruef("a file outside the own workspace cannot be attached", False)
    except ValueError as _e:
        pruef("a file outside the own workspace cannot be attached",
              "Not attachable" in str(_e) and "Angebot-markus.txt" in str(_e))
    try:
        _att.resolve("anna", None, ["Angebot-markus.txt"])
        pruef("nor one of someone else's workspace", False)
    except ValueError:
        pruef("nor one of someone else's workspace", True)
finally:
    pipeline.dokumente = _real_docs

# --- CREATED FILES (created_files.py) ---
import io as _io_c
import zipfile as _zip_c
import created_files as _cf

_x_name, _x_data = _cf.build("xlsx", "Offene Auftraege", {"sheets": [{
    "name": "Meier", "columns": ["AuftragsNr", "Wert"], "rows": [["24001", "1.234,50"], [24002, 99]]}]})
import openpyxl as _opx
_ws_c = _opx.load_workbook(_io_c.BytesIO(_x_data)).active
pruef("an Excel file with header row and numbers as numbers",
      _x_name == "Offene Auftraege.xlsx" and _ws_c["A1"].value == "AuftragsNr"
      and _ws_c["A2"].value == 24001 and _ws_c["B2"].value == 1234.5,
      (_ws_c["A2"].value, _ws_c["B2"].value))
_d_name, _d_data = _cf.build("docx", "Bericht", {"text": "# Teil 1\n- Punkt **wichtig**\n\n| A | B |\n|---|---|\n| 1 | 2 |"})
import docx as _dx
_doc_c = _dx.Document(_io_c.BytesIO(_d_data))
pruef("a Word file with heading, list and table from Markdown",
      any(p.text == "Teil 1" for p in _doc_c.paragraphs) and len(_doc_c.tables) == 1
      and _doc_c.tables[0].cell(1, 1).text == "2")
try:
    _p_name, _p_data = _cf.build("pptx", "Vortrag", {"slides": [
        {"title": "Ergebnis", "bullets": ["eins", "zwei"], "notes": "sagen"}]})
    pruef("a PowerPoint file with title slide and content slide",
          _zip_c.is_zipfile(_io_c.BytesIO(_p_data)) and _p_name == "Vortrag.pptx")
except ImportError:
    pruef("a PowerPoint file (python-pptx missing here, tested in the image)", True)
for _bad_c, _why in ((("csv", "x", {}), "unknown kind"), (("xlsx", "", {"sheets": [{}]}), "no title"),
                     (("docx", "x", {}), "no text")):
    try:
        _cf.build(*_bad_c)
        pruef(f"refused: {_why}", False)
    except ValueError:
        pruef(f"refused: {_why}", True)
_stored_c = _cf.store("markus", _x_name, _x_data)
_again_c = _cf.store("markus", _x_name, _x_data)
_raw_c = statefiles.read_bytes(os.path.join(paths.CHATS_DIR, "markus", "dateien", _stored_c))
pruef("created files are stored encrypted, a second one with the same name numbered",
      _cf.read("markus", _stored_c) == _x_data and _again_c == "Offene Auftraege (2).xlsx"
      and b"AuftragsNr" not in _raw_c and _x_data[:2] not in _raw_c[:2], _again_c)
try:
    _cf.read("anna", _stored_c)
    pruef("someone else's created file is not readable", False)
except FileNotFoundError:
    pruef("someone else's created file is not readable", True)
try:
    _cf.read("markus", "../../anna/dateien/x.xlsx")
    pruef("a path in a file name does not leave the own folder", False)
except (FileNotFoundError, ValueError):
    pruef("a path in a file name does not leave the own folder", True)
_cf.delete("markus", _again_c)
