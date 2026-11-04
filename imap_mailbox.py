"""Mailboxes over IMAP and SMTP: Gmail, GMX, web.de, own mail servers.

The same tools as an Exchange mailbox (postfach.py) -- mails_lesen,
mail_volltext, mail_thread, mail_senden, antwort_senden -- with the same
names, so the confirmation before sending, the notice under automatic
answers and attachments (attachments.py) work unchanged. No calendar:
IMAP has none.

Entry (mcp.lege_an, template "imap"), target "imap-host[:port], smtp-host[:port]":

    imap.gmail.com                       -> IMAP 993, SMTP smtp.gmail.com:587
    imap.gmx.net, mail.gmx.net:465       -> SMTP over TLS from the start

Credentials come with each call, like for Exchange (the session's login
header) and are never stored. Every connection is encrypted and the
server certificate checked against the trust bundle.

Limits of the providers, not of this module: Gmail accepts an app
password (with 2-step verification) but not the account password;
Microsoft 365 and Outlook.com have switched password sign-in off for
IMAP and SMTP altogether.
"""
import datetime
import email
import email.header
import email.policy
import email.utils
import imaplib
import re
import smtplib
import ssl
from email.message import EmailMessage

import paths
import postfach

TIMEOUT = paths.env_float("POSTFACH_TIMEOUT", 30)
FETCH_LIMIT = paths.env_int("POSTFACH_HOLGRENZE", 200)
TOOLS = ("mails_lesen", "mail_volltext", "mail_thread", "mail_senden", "antwort_senden")


def parse_target(target):
    """"imap.host[:port], smtp.host[:port]" -> (imap host, port, smtp host, port)."""
    parts = [p.strip() for p in str(target or "").split(",") if p.strip()]
    if not parts:
        raise ValueError("IMAP server missing, e.g. imap.gmail.com")

    def split(text, default):
        host, _, port = text.partition(":")
        return host.strip(), int(port) if port.strip().isdigit() else default

    imap_host, imap_port = split(parts[0], 993)
    if len(parts) > 1:
        smtp_host, smtp_port = split(parts[1], 587)
    else:
        smtp_host = re.sub(r"^imap\.", "smtp.", imap_host)
        smtp_port = 587
    return imap_host, imap_port, smtp_host, smtp_port


def _decode(value):
    """A header as text, encoded words resolved."""
    try:
        return str(email.header.make_header(email.header.decode_header(value or "")))
    except Exception:
        return str(value or "")


def _sender(msg):
    name, addr = email.utils.parseaddr(_decode(msg.get("From", "")))
    return f"{name} <{addr}>" if name and addr and name != addr else (name or addr or "(unbekannt)")


def _date(msg):
    try:
        return email.utils.parsedate_to_datetime(msg.get("Date"))
    except Exception:
        return None


def _text(msg):
    """The plain text of a message; HTML stripped when there is no text part."""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        part = None
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        content = re.sub(r"(?is)<(script|style).*?</\1>", " ", content)
        content = re.sub(r"(?s)<br\s*/?>|</p>", "\n", content)
        content = re.sub(r"(?s)<[^>]+>", " ", content)
        content = re.sub(r"[ \t]+", " ", content)
    return content.strip()


class ImapMailbox:
    """An IMAP/SMTP mailbox, outwardly like postfach.Postfach."""

    def __init__(self, name, angaben, zusatz_kopf=None):
        self.name = name
        self.angaben = dict(angaben or {})
        self.zusatz_kopf = dict(zusatz_kopf or {})
        self.attachment_source = None
        self._imap = None
        self._folders = None

    # --- login ---

    def _zugang(self):
        return postfach.Postfach._zugang(self)

    def adresse(self):
        return postfach.Postfach.adresse(self)

    def _bereich(self):
        return f"{self.name}:{self.adresse().lower()}"

    def _context(self):
        return ssl.create_default_context()

    def _connect(self):
        if self._imap is not None:
            return self._imap
        user, password = self._zugang()
        host, port = self.angaben.get("imap_host"), int(self.angaben.get("imap_port") or 993)
        try:
            imap = imaplib.IMAP4_SSL(host, port, ssl_context=self._context(), timeout=TIMEOUT)
            imap.login(user, password)
        except imaplib.IMAP4.error as e:
            raise postfach.Fehler(f"{self.name}: Anmeldung abgelehnt ({_short(e)}).")
        except Exception as e:
            raise postfach.Fehler(f"{self.name}: {_short(e)}")
        self._imap = imap
        return imap

    def schliesse(self):
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # --- tools ---

    def werkzeuge(self):
        """The tool list -- after a successful login, like for Exchange."""
        self._select("INBOX")
        label = self.adresse()
        attachable = []
        if self.attachment_source is not None and hasattr(self.attachment_source, "available"):
            try:
                attachable = self.attachment_source.available()
            except Exception:
                attachable = []
        out = []
        for w in postfach.WERKZEUGE:
            if w["name"] not in TOOLS:
                continue
            text = w["beschreibung"].format(label=label, today=datetime.date.today())
            if w["name"] == "mail_senden":
                text += (" Attachable now: " + ", ".join(attachable[:30]) + "."
                         if attachable else " No files can be attached now.")
            out.append({"server": self.name, "name": w["name"], "beschreibung": text,
                        "schema": w["schema"]})
        return out

    def pruefe_entwurf(self, name, argumente=None):
        return postfach.Postfach.pruefe_entwurf(self, name, argumente)

    def _anhaenge(self, names):
        return postfach.Postfach._anhaenge(self, names)

    def rufe(self, name, argumente=None):
        a = dict(argumente or {})
        if name == "mails_lesen":
            return self._list(a)
        if name == "mail_volltext":
            return self._full(a)
        if name == "mail_thread":
            return self._thread(a)
        if name == "mail_senden":
            return self._send_new(a)
        if name == "antwort_senden":
            return self._reply(a)
        raise postfach.Fehler(f"{self.name}: kein Werkzeug namens '{name}'.")

    # --- reading ---

    def _sent_folder(self):
        """The folder flagged \\Sent (RFC 6154), else a usual name."""
        if self._folders is None:
            typ, lines = self._connect().list()
            self._folders = []
            for line in lines or []:
                text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
                m = re.match(r'\((?P<flags>[^)]*)\) "?(?P<sep>[^" ]*)"? (?P<name>.+)$', text)
                if m:
                    self._folders.append((m.group("flags"), m.group("name").strip().strip('"')))
        for flags, name in self._folders:
            if "\\Sent" in flags:
                return name
        for flags, name in self._folders:
            if name.lower() in ("sent", "gesendet", "sent items", "gesendete elemente",
                                "inbox.sent", "inbox/sent"):
                return name
        return None

    def _select(self, folder):
        imap = self._connect()
        typ, _data = imap.select(_quote(folder), readonly=True)
        if typ != "OK":
            raise postfach.Fehler(f"{self.name}: Ordner {folder} nicht lesbar.")
        return imap

    def _search(self, folder, *criteria):
        """UIDs matching criteria (ASCII only -- IMAP quoted strings are)."""
        imap = self._select(folder)
        typ, data = imap.uid("SEARCH", *(criteria or ("ALL",)))
        if typ != "OK":
            raise postfach.Fehler(f"{self.name}: Suche abgelehnt.")
        return (data[0] or b"").split()

    def _find(self, folder, since=None, sender="", text="", subject=""):
        """[(uid, message)] newest first; what the server cannot search for
        (words with umlauts) is matched here instead."""
        criteria, local = [], {}
        if since:
            criteria += ["SINCE", since.strftime("%d-%b-%Y")]
        for key, value, word in (("from", sender, "FROM"), ("text", text, "TEXT"),
                                 ("subject", subject, "SUBJECT")):
            if not value:
                continue
            if value.isascii():
                criteria += [word, _quote(value)]
            else:
                local[key] = value.lower()
        uids = self._search(folder, *criteria)[-(FETCH_LIMIT if not local else 100):]
        out = []
        for uid in reversed(uids):
            msg = self._fetch(folder, uid)
            if "from" in local and local["from"] not in _sender(msg).lower():
                continue
            if "subject" in local and local["subject"] not in _decode(msg.get("Subject")).lower():
                continue
            if "text" in local and local["text"] not in (
                    _decode(msg.get("Subject")) + "\n" + _text(msg)).lower():
                continue
            out.append((uid, msg))
        return out

    def _fetch(self, folder, uid, what="(BODY.PEEK[])"):
        imap = self._select(folder)
        typ, data = imap.uid("FETCH", uid, what)
        for item in data or []:
            if isinstance(item, tuple) and len(item) > 1:
                return email.message_from_bytes(item[1], policy=email.policy.default)
        raise postfach.Fehler(f"{self.name}: Nachricht nicht gefunden.")

    def _list(self, a):
        count = max(1, min(int(a.get("anzahl") or 20), 100))
        sender = str(a.get("von") or "").strip()
        text = str(a.get("suchtext") or "").strip()
        sent = str(a.get("ordner") or "").lower().startswith("ges")
        folder = (self._sent_folder() if sent else "INBOX") or "INBOX"
        hours = a.get("stunden")
        since = (datetime.date.today() - datetime.timedelta(hours=max(1, int(hours)))
                 if hours else None)
        lines = []
        for uid, msg in self._find(folder, since=since, sender=sender, text=text):
            when = _date(msg)
            short = postfach._merke_kennung(self._bereich(), (folder, uid.decode()))
            body = _text(msg)
            lines.append(f"[{short}] {postfach._datum(when)} | von: {_sender(msg)} | "
                         f"{_decode(msg.get('Subject')) or '(ohne Betreff)'}"
                         + (f"\n    {postfach._zusammen(body, postfach.TEXTAUSZUG)}" if body else ""))
            if len(lines) >= count:
                break
        if not lines:
            return "Keine Nachricht passt."
        return f"{len(lines)} Nachricht(en) aus {folder}, neueste zuerst:\n" + "\n".join(lines)

    def _message(self, short):
        folder, uid = postfach._lange_kennung(self._bereich(), short)
        return folder, uid, self._fetch(folder, uid)

    def _full(self, a):
        _folder, _uid, msg = self._message(a.get("kennung"))
        parts = [f"Datum:   {postfach._datum(_date(msg))}",
                 f"Von:     {_sender(msg)}",
                 f"An:      {_decode(msg.get('To')) or '-'}"]
        if msg.get("Cc"):
            parts.append(f"Kopie:   {_decode(msg.get('Cc'))}")
        parts += [f"Betreff: {_decode(msg.get('Subject'))}", "", _text(msg) or "(kein Text)"]
        return "\n".join(parts)

    def _thread(self, a):
        _folder, _uid, first = self._message(a.get("kennung"))
        base = postfach._grundbetreff(_decode(first.get("Subject")))
        found = [first]
        if base:
            for folder in ["INBOX", self._sent_folder()]:
                if not folder:
                    continue
                found += [m for _uid, m in self._find(folder, subject=base)[:30]]
        seen, messages = set(), []
        for m in found:
            key = m.get("Message-ID") or id(m)
            if key in seen or postfach._grundbetreff(_decode(m.get("Subject"))) != base:
                continue
            seen.add(key)
            messages.append(m)
        messages.sort(key=lambda m: postfach._zeitwert(_date(m)))
        blocks, rest = [], postfach.THREAD_TOTAL
        for m in reversed(messages):
            body = postfach._ohne_zitat(_text(m))
            body = body[:postfach.THREAD_MESSAGE] + ("..." if len(body) > postfach.THREAD_MESSAGE else "")
            block = f"--- {postfach._datum(_date(m))} | von: {_sender(m)}\n{body or '(kein Text)'}"
            if len(block) > rest and blocks:
                blocks.append(f"--- (aeltere Nachrichten weggelassen: {len(messages) - len(blocks)})")
                break
            blocks.append(block[:rest])
            rest -= len(block)
        blocks.reverse()
        return (f"Verlauf '{base or '(ohne Betreff)'}': {len(messages)} Nachricht(en), "
                f"aelteste zuerst.\n" + "\n".join(blocks))

    # --- sending ---

    def _deliver(self, msg):
        user, password = self._zugang()
        host = self.angaben.get("smtp_host")
        port = int(self.angaben.get("smtp_port") or 587)
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, context=self._context(), timeout=TIMEOUT)
            else:
                server = smtplib.SMTP(host, port, timeout=TIMEOUT)
                server.starttls(context=self._context())
            try:
                server.login(user, password)
                server.send_message(msg)
            finally:
                server.quit()
        except smtplib.SMTPAuthenticationError as e:
            raise postfach.Fehler(f"{self.name}: Anmeldung beim Versand abgelehnt ({_short(e)}).")
        except Exception as e:
            raise postfach.Fehler(f"{self.name}: nicht gesendet ({_short(e)}).")
        # Gmail files sent mail by itself; other servers need a copy.
        if "gmail" not in str(host).lower():
            folder = self._sent_folder()
            if folder:
                try:
                    self._connect().append(_quote(folder), "\\Seen", None, msg.as_bytes())
                except Exception:
                    pass   # sent is sent; a missing copy is no reason to fail

    def _new_message(self, to, cc, subject, body, files):
        msg = EmailMessage()
        msg["From"] = self.adresse()
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=self.adresse().split("@")[-1])
        msg.set_content(body)
        for name, data, mime in files:
            main, _, sub = mime.partition("/")
            msg.add_attachment(data, maintype=main or "application",
                               subtype=sub or "octet-stream", filename=name)
        return msg

    def _send_new(self, a):
        to = postfach._liste(a.get("an"))
        if not to:
            raise postfach.Fehler("Kein Empfaenger angegeben.")
        files = self._anhaenge(a.get("anhaenge"))
        msg = self._new_message(to, postfach._liste(a.get("kopie")),
                                str(a.get("betreff") or ""), str(a.get("body") or ""), files)
        self._deliver(msg)
        return (f"Gesendet an {', '.join(to)}."
                + (f" Anhänge: {', '.join(n for n, _d, _m in files)}." if files else ""))

    def _reply(self, a):
        if a.get("anhaenge"):
            raise postfach.Fehler("Anhänge gehen nur mit einer neuen Nachricht (mail_senden).")
        _folder, _uid, original = self._message(a.get("kennung"))
        reply_to = email.utils.parseaddr(original.get("Reply-To") or original.get("From"))[1]
        cc = []
        if a.get("allen"):
            own = self.adresse().lower()
            for field in ("To", "Cc"):
                for _n, addr in email.utils.getaddresses([original.get(field, "")]):
                    if addr and addr.lower() not in (own, reply_to.lower()):
                        cc.append(addr)
        subject = _decode(original.get("Subject"))
        if not subject.lower().startswith(("re:", "aw:")):
            subject = "Re: " + subject
        msg = self._new_message([reply_to], cc, subject, str(a.get("body") or ""), [])
        if original.get("Message-ID"):
            msg["In-Reply-To"] = original["Message-ID"]
            msg["References"] = ((original.get("References") or "") + " "
                                 + original["Message-ID"]).strip()
        self._deliver(msg)
        return f"Antwort an {reply_to} gesendet."


def _quote(text):
    """An IMAP string argument."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short(error):
    lines = str(error).strip().splitlines()
    return f"{type(error).__name__}: {(lines[0] if lines else '')[:200]}"

