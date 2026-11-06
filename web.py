"""The web interface: server-rendered pages with HTMX-style fragments.

Served by server.py next to the API, from the same process and on top of
the same modules (answering, doc_actions, web_sources, accounts, ...), so
a page and an API call can never answer differently.

    /login            sign in (password or company directory)
    /                 chat; /c/<id> a given chat
    /documents        workspaces and documents: upload, move, delete
    /web              sources from the web: search, read, take over
    /tickets          tickets of shared mailboxes (web_tickets.py)
    /settings         language, instruction, presets, password, mailboxes, tokens
    /admin            users, workspaces, jobs, status (the rest: /api/v1/docs)

Pages are rendered with Jinja; interaction uses hx-* attributes. The
script that reads them (web_static/hx.js) is a small subset of htmx with
the same attribute names, written here so that no third-party script is
loaded -- the official htmx file can replace it without touching a page.
The chat answer streams through /api/v1/ask (web_static/chat.js).

Security: a strict Content-Security-Policy (scripts and styles only from
this server, nothing inline), model output rendered as Markdown with HTML
switched off, the same session cookie and CSRF header as the API.
"""
import html
import os
import re
import time
from urllib.parse import quote, urlencode

import jinja2
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from markdown_it import MarkdownIt

import accounts
import answering
import auth
import benutzer
import chats
import doc_actions
import feedback
import jobs
import llm
import mail_watch
import mailboxes
import notices
import notzugang
import pipeline
import presets
import prompts
import raeume
import sessions
import sprache
import sqlquellen
import tickets
import web_research
import web_sources
from server import (SEALED_COOKIE, COOKIE_SECURE, Principal, principal,
                    set_session_cookies)

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.getenv("UI_BRAND_NAME", "LocaNoto").strip() or "LocaNoto"
# The logo in the header, on the sign-in page and in the browser tab;
# UI_LOGO= (empty) leaves it out, a path under /static/ replaces it.
LOGO = os.getenv("UI_LOGO", "/static/logo.png").strip()
ACCENT = os.getenv("UI_ACCENT_COLOR", "").strip()

router = APIRouter(include_in_schema=False)

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(HERE, "web_templates")),
    autoescape=True, trim_blocks=True, lstrip_blocks=True)
_md = MarkdownIt("commonmark", {"html": False, "linkify": False,
                                "typographer": False}).enable("table")

# English keys, German texts. New code is English; the people using it
# mostly read German.
TEXTS = {
    "Sign in": "Anmelden", "Sign out": "Abmelden", "Name": "Name",
    "Password": "Passwort", "Sign in with the company account":
        "Mit dem Firmenkonto anmelden", "or": "oder",
    "Chat": "Chat", "Documents": "Dokumente", "Web sources": "Quellen im Netz",
    "Settings": "Einstellungen", "Admin": "Admin", "New chat": "Neuer Chat",
    "Ask a question about your documents ...":
        "Frage an deine Dokumente ...", "Send": "Senden",
    "Workspaces": "Arbeitsbereiche", "all": "alle",
    "Web search": "Websuche", "Model": "Modell", "Preset": "Voreinstellung",
    "none": "keine", "Sources": "Quellen", "page": "Seite",
    "Further passages found": "Weitere gefundene Stellen (nicht zitiert)",
    "Open in a new tab": "In neuem Tab öffnen", "Workspace": "Arbeitsbereich",
    "No such passage, or no access.": "Keine solche Fundstelle oder kein Zugriff.",
    "No passage of this page in the store.": "Kein Abschnitt zu dieser Seite im Bestand.",
    "Lists": "Listen", "List query": "Listenabfrage",
    "List folders per workspace": "Listenordner je Arbeitsbereich",
    "Folder in the container, or owncloud:/path in the file store. Empty removes it.":
        "Ordner im Container oder owncloud:/Pfad in der Dateiablage. Leer entfernt ihn.",
    "Personal folders (pattern with {benutzer})": "Persönliche Ordner (Muster mit {benutzer})",
    "Allowed roots": "Erlaubte Wurzeln", "none set (LISTEN_WURZELN)": "keine gesetzt (LISTEN_WURZELN)",
    "Read lists again": "Listen neu einlesen", "Sheets in the catalog": "Blätter im Katalog",
    "Not readable": "Nicht lesbar", "Sheet": "Blatt", "large": "groß",
    "Lists live where the departments keep them (network drive, file store); questions read them fresh. A folder belongs to a workspace: who may read the workspace sees its lists.":
        "Listen liegen dort, wo die Abteilungen sie pflegen (Netzlaufwerk, Dateiablage); jede Frage liest sie frisch. Ein Ordner gehört zu einem Arbeitsbereich: Wer den Bereich lesen darf, sieht seine Listen.",
    "Show page": "Seite zeigen", "Helpful": "Hilfreich",
    "Not helpful": "Nicht hilfreich", "Thanks.": "Danke.",
    "Draft waiting for you": "Entwurf wartet auf dich",
    "Send draft": "Entwurf senden", "Discard": "Verwerfen",
    "Sent.": "Gesendet.", "Discarded.": "Verworfen.",
    "Summary for": "Zusammenfassung für", "Save to workspace":
        "Im Arbeitsbereich ablegen", "Stored.": "Abgelegt.",
    "waits for your confirmation": "wartet auf deine Bestätigung",
    "Meeting request": "Besprechungsanfrage",
    "Appointment in your calendar": "Termin in deinem Kalender",
    "Add to calendar": "In den Kalender eintragen",
    "Send invitation": "Einladung senden",
    "Added to the calendar.": "Im Kalender eingetragen.",
    "Change appointment": "Termin ändern", "Cancel appointment": "Termin absagen",
    "Save change": "Änderung speichern", "Changed.": "Geändert.",
    "Cancelled.": "Abgesagt.",
    "Forward message": "Nachricht weiterleiten", "Forward": "Weiterleiten",
    "Move message": "Nachricht verschieben", "Moved.": "Verschoben.",
    "Automatic replies": "Abwesenheitsnotiz", "Apply": "Übernehmen", "Done.": "Erledigt.",
    "Answer invitation": "Auf Einladung antworten", "Answered.": "Geantwortet.",
    "Accept": "Zusagen", "Accept tentatively": "Vorläufig zusagen", "Decline": "Absagen",
    "From the web": "Aus dem Netz", "Take over": "Übernehmen",
    "Delete": "Löschen", "Rename": "Umbenennen",
    "Upload": "Hochladen", "into": "nach", "Project (optional)":
        "Projekt (optional)", "Describe images": "Bilder beschreiben",
    "Move to": "Verschieben nach", "Move": "Verschieben",
    "No documents yet.": "Noch keine Dokumente.",
    "Search": "Suchen", "Keywords only -- they go to search engines.":
        "Nur Stichworte – sie gehen an Suchmaschinen.",
    "Read": "Lesen", "Take over selected into my workspace":
        "Ausgewählte in meinen Arbeitsbereich übernehmen",
    "Language": "Sprache", "Save": "Speichern",
    "Database": "Datenbank", "Database of": "Datenbank von",
    "Database query": "Datenbankabfrage", "rows": "Zeilen",
    "Database access per workspace": "Datenbankzugang je Arbeitsbereich",
    "Microsoft SQL Server. Use an account with read rights only (db_datareader). Empty user and password remove the access.":
        "Microsoft SQL Server. Ein Konto nur mit Leserechten verwenden (db_datareader). Leerer Benutzer und leeres Passwort entfernen den Zugang.",
    "With database access": "Mit Datenbankzugang", "Workspace": "Arbeitsbereich",
    "Server": "Server", "Port": "Port", "Database name": "Datenbank", "User": "Benutzer",
    "Note for the model (status codes, which table holds what)":
        "Hinweis für das Modell (Statuscodes, welche Tabelle was enthält)",
    "Personal instruction": "Persönliche Anweisung",
    "Applies to every question you ask.": "Gilt für jede deiner Fragen.",
    "Change password": "Passwort ändern", "Current password":
        "Bisheriges Passwort", "New password": "Neues Passwort",
    "Mailboxes": "Postfächer", "Connect": "Verbinden",
    "connected": "verbunden", "Disconnect": "Trennen",
    "Logins are kept only in this browser session.":
        "Anmeldedaten gelten nur für diese Browsersitzung.",
    "API tokens": "API-Token", "Revoke": "Widerrufen",
    "Users": "Nutzer", "Role": "Rolle", "Create": "Anlegen",
    "Jobs": "Hintergrundläufe", "Start": "Starten", "Status": "Status",
    "Full admin area in the API": "Vollständiger Admin-Bereich in der API",
    "Members (comma separated)": "Mitglieder (durch Komma)",
    "Label": "Bezeichnung", "Saved.": "Gespeichert.",
    "Presets": "Voreinstellungen", "own": "eigene",
    "Answer from the keyword search only -- the vector search did not answer for":
        "Antwort nur aus der Stichwortsuche – die Vektorsuche hat nicht geantwortet für",
    "Your account signs in through the company directory.":
        "Dein Konto meldet sich über das Firmenverzeichnis an.",
    "Backups": "Sicherungen", "Emergency access": "Notzugang",
    "Prompts and glossary": "Prompts und Glossar", "Feedback": "Rückmeldungen",
    "Storage": "Ablage", "Back up now": "Jetzt sichern",
    "type the name to confirm": "Namen zur Bestätigung eintippen",
    "also users, chats, settings": "auch Nutzer, Chats, Einstellungen",
    "Restore": "Zurückholen", "incomplete": "unvollständig",
    "with state": "mit Zustand",
    "Type the name of the backup to confirm.":
        "Zum Bestätigen den Namen des Abzugs eintippen.",
    "Nobody holds the role notzugang -- no request can be confirmed.":
        "Niemand hat die Rolle notzugang – kein Antrag kann bestätigt werden.",
    "Open grants": "Offene Zugänge", "Close": "Schließen",
    "Requests": "Anträge", "Confirm": "Bestätigen", "Reject": "Ablehnen",
    "Request access to a personal workspace":
        "Zugang zu einem persönlichen Arbeitsbereich beantragen",
    "Reason (the second person decides on it)":
        "Grund (die zweite Person entscheidet danach)",
    "Request": "Beantragen", "Open": "Öffnen",
    "Reset to the shipped template": "Auf die mitgelieferte Vorlage zurücksetzen",
    "Glossary": "Glossar", "Archive the log?": "Protokoll archivieren?",
    "Archive": "Archivieren", "Download": "Herunterladen",
    "Questions without an answer": "Fragen ohne Antwort",
    "No storage (OpenCloud) is configured.": "Keine Ablage (OpenCloud) eingerichtet.",
    "Set up workspace folders and shares":
        "Ordner und Freigaben der Arbeitsbereiche einrichten",
    "Sync groups": "Gruppen abgleichen", "Sync documents": "Dokumente abgleichen",
    "personal": "persönlich", "Kind": "Art",
    "Address, command or Exchange server": "Adresse, Befehl oder Exchange-Server",
    "Address, command, Exchange server or IMAP server (imap.gmail.com)":
        "Adresse, Befehl, Exchange- oder IMAP-Server (imap.gmail.com)",
    "Address of a shared mailbox (only for shared ones)":
        "Adresse eines Funktionspostfachs (nur dafür)",
    "personal (everyone signs in with their own account)":
        "persönlich (jeder meldet sich mit seinem Konto an)",
    "Only for shared mailboxes": "Nur für Funktionspostfächer",
    "Search users": "Benutzer suchen", "users": "Benutzer", "Created": "Erstellt", "Documents from the database": "Dokumente aus der Datenbank",
    "Web search allowed": "Websuche erlaubt", "Web search blocked": "Websuche gesperrt",
    "Block": "Sperren", "Allow": "Erlauben",
    "Not searched with web search (not allowed there)":
        "Bei Websuche nicht durchsucht (dort gesperrt)",
    "Web search next to a workspace means: the model writes search terms while passages of that workspace are in its context, and what ends up in a search term goes to search engines. Taken-over results always land in the own workspace, never in a shared one. The general workspace is therefore blocked by default; with web search, a question over all workspaces simply leaves it out.":
        "Websuche neben einem Arbeitsbereich heißt: Das Modell formuliert Suchbegriffe, während Abschnitte dieses Bereichs im Kontext stehen – was davon in einen Suchbegriff gerät, geht an Suchmaschinen. Übernommene Treffer landen immer im eigenen Bereich, nie in einem geteilten. „Allgemein“ ist deshalb ab Werk gesperrt; eine Frage mit Websuche über alle Bereiche lässt ihn einfach aus.",
    "previous": "zurück", "next": "weiter",
    "may answer on its own (no confirmation)": "darf selbst antworten (ohne Bestätigung)",
    "add a notice under automatic answers": "Hinweis unter automatische Antworten setzen",
    "Notice": "Hinweistext", "answers on its own": "antwortet selbständig",
    "with notice": "mit Hinweis", "WITHOUT notice": "OHNE Hinweis",
    "prepares drafts": "legt Entwürfe vor",
    "Delete this chat?": "Diesen Chat löschen?",
    "Search started. You will be notified when the hits are there -- you can leave this page.":
        "Suche gestartet. Du wirst benachrichtigt, sobald die Treffer da sind – die Seite darf verlassen werden.",
    "Taking over in the background. You will be notified when the pages are stored.":
        "Übernahme läuft im Hintergrund. Du wirst benachrichtigt, sobald die Seiten gespeichert sind.",
    "No hits chosen.": "Keine Treffer ausgewählt.", "Show": "Ansehen",
    "Web search failed": "Websuche fehlgeschlagen", "Web search ready": "Websuche fertig",
    "hits": "Treffer", "Take-over failed": "Übernahme fehlgeschlagen",
    "Taken over into your workspace": "In deinen Arbeitsbereich übernommen",
    "My searches": "Meine Suchen", "running": "läuft",
    "new": "neu", "No searches yet.": "Noch keine Suchen.",
    "Search in the web": "Im Web suchen",
    "This text goes to search engines as it is:": "Dieser Text geht so an Suchmaschinen:",
    "Search runs. You will be notified -- the hits are under Web sources.":
        "Suche läuft. Du wirst benachrichtigt – die Treffer stehen unter Quellen im Netz.",
    "Searches run in the background and stay here until you delete them. Taken-over pages land in your own workspace, folder Suchergebnisse; from there they can be moved on purpose.":
        "Suchen laufen im Hintergrund und bleiben hier, bis du sie löschst. Übernommene Seiten landen in deinem eigenen Arbeitsbereich, Ordner Suchergebnisse; von dort lassen sie sich gezielt verschieben.",
    "Select all": "Alle auswählen",
    "Too many web tasks at once -- wait until one is finished.":
        "Zu viele Webaufträge gleichzeitig – bitte warten, bis einer fertig ist.",
    "Too many web tasks this hour -- try again later.":
        "Zu viele Webaufträge in dieser Stunde – bitte später noch einmal.",
    "Only hits of a finished search can be taken over.":
        "Nur Treffer einer fertigen Suche lassen sich übernehmen.",
    "Unknown task.": "Unbekannter Auftrag.", "Empty search term.": "Leerer Suchbegriff.",
    "Interrupted (server restarted).": "Abgebrochen (Server neu gestartet).",
    "No web search is set up.": "Keine Websuche eingerichtet.",
    "Delete this document?": "Dieses Dokument löschen?",
    "Ask again": "Nochmal fragen", "Cancel": "Abbrechen",
    "Last check": "Zuletzt geprüft", "never yet": "noch nie",
    "never yet -- a member has to connect the mailbox under Settings and have LocaNoto open":
        "noch nie – ein Mitglied muss das Postfach unter Einstellungen verbinden und LocaNoto offen haben",
    "Connect this mailbox under Settings: it is checked while a member with it connected has LocaNoto open.":
        "Verbinde dieses Postfach unter Einstellungen: Geprüft wird, solange ein Mitglied mit verbundenem Postfach LocaNoto offen hat.",
    "selected": "ausgewählt", "Search workspaces": "Arbeitsbereiche suchen",
    "Search user and add ...": "Benutzer suchen und hinzufügen …",
    "Search workspace and add ...": "Arbeitsbereich suchen und hinzufügen …",
    "also, visible to everybody": "außerdem, für alle sichtbar",
    "type a part of a name to see them": "einen Teil des Namens eingeben, um sie zu sehen",
    "Edit": "Bearbeiten", "Description": "Beschreibung", "Members": "Mitglieder",
    "Visible to everybody (no member list)": "Für alle sichtbar (ohne Mitgliederliste)",
    "only used when not visible to everybody": "gilt nur, wenn nicht für alle sichtbar",
    "Group from the directory or the file store (optional)":
        "Gruppe aus dem Verzeichnis oder der Dateiablage (optional)",
    "Remove the workspace? Its documents stay in the store until it is wiped.":
        "Arbeitsbereich entfernen? Seine Dokumente bleiben im Bestand, bis er geleert wird.",
    "Remove workspace": "Arbeitsbereich entfernen", "New workspace": "Neuer Arbeitsbereich",
    "Workspaces of": "Arbeitsbereiche von", "everybody": "alle",
    "Id and label.": "Kennung und Bezeichnung.",
    "The model does not see the question answerable from the database.":
        "Die Frage betrifft aus Sicht des Modells nichts in der Datenbank – keine Abfrage.",
    "No database account for this user.": "Kein Datenbankzugang für dich (Einstellungen > Meine Datenbanken).",
    "The database has no readable tables.": "Die Datenbank hat keine lesbaren Tabellen.",
    "The answer is being written ...": "Die Antwort wird geschrieben …",
    "The answer broke off.": "Die Antwort wurde abgebrochen.",
    "My databases": "Meine Datenbanken", "Databases": "Datenbanken",
    "User and password.": "Benutzer und Passwort.",
    "Sign-in to the database failed": "Anmeldung an der Datenbank fehlgeschlagen",
    "your login": "dein Login", "shared account": "gemeinsames Konto",
    "not connected": "nicht verbunden",
    "Sign in with the SQL login your database admin gave you; your rights in the database apply. The login is kept only in this browser session. LocaNoto only reads (SELECT).":
        "Mit dem SQL-Login anmelden, das du vom Datenbank-Admin bekommen hast; es gelten deine Rechte in der Datenbank. Das Login bleibt nur in dieser Browsersitzung. LocaNoto liest nur (SELECT).",
    "Databases per workspace": "Datenbanken je Arbeitsbereich",
    "Microsoft SQL Server. LocaNoto only reads (SELECT). Without user and password every member signs in with their own SQL login under Settings (kept only in the session), and the database's own rights apply per person. With user and password that account is shared by all members (stored encrypted) -- use a read-only one (db_datareader). Everything empty removes the database.":
        "Microsoft SQL Server. LocaNoto liest nur (SELECT). Ohne Benutzer und Passwort meldet sich jedes Mitglied unter Einstellungen mit seinem eigenen SQL-Login an (nur in der Sitzung), und es gelten die Rechte der Datenbank je Person. Mit Benutzer und Passwort nutzen alle Mitglieder dieses Konto (verschlüsselt gespeichert) – dafür ein reines Lesekonto (db_datareader). Alles leer entfernt die Datenbank.",
    "personal logins": "persönliche Logins", "Remove": "Entfernen",
    "Test connection": "Verbindung testen", "Connected.": "Verbunden.",
    "tables": "Tabellen", "but no readable tables": "aber keine lesbaren Tabellen",
    "Unknown database.": "Unbekannte Datenbank.",
    "No shared account: members test with their own login under Settings.":
        "Kein gemeinsames Konto: Mitglieder testen mit ihrem eigenen Login unter Einstellungen.",
    "Note for the model": "Hinweis für das Modell", "Note saved.": "Hinweis gespeichert.",
    "-- the text itself, e.g. the content of sql-hint.txt, not a file name":
        "– der Text selbst, z. B. der Inhalt von sql-hint.txt, kein Dateiname",
    "Root of the personal folders": "Wurzel der persönlichen Ordner",
    "every user gets <root>/<user name>, e.g. /mnt/listen/LISTE/anna":
        "jeder Nutzer bekommt <Wurzel>/<Benutzername>, z. B. /mnt/listen/LISTE/anna",
    "My lists": "Meine Listen", "Your folder": "Dein Ordner",
    "Subfolder (optional)": "Unterordner (optional)",
    "Excel and CSV files in this folder are read at every question that uses lists; only you see them.":
        "Excel- und CSV-Dateien in diesem Ordner werden bei jeder Frage mit Listen gelesen; nur du siehst sie.",
    "No root for personal folders is set up yet -- an admin enters it under Admin > Lists.":
        "Noch keine Wurzel für persönliche Ordner eingerichtet – ein Admin trägt sie unter Admin > Listen ein.",
    "Lists of your workspaces": "Listen deiner Arbeitsbereiche",
    "Your sheets": "Deine Blätter", "No sheets found yet.": "Noch keine Blätter gefunden.",
    "Searched.": "Gesucht.", "Sending ...": "Wird gesendet …",
    "Not sent": "Nicht gesendet",
    "The server did not answer. Look into your sent folder (or calendar) before you send it again.":
        "Der Server hat nicht geantwortet. Vor einem erneuten Senden im Ordner Gesendet (bzw. im Kalender) nachsehen.",
    "Web search proposed": "Websuche vorgeschlagen",
    "Notify me about new mail": "Bei neuer Mail benachrichtigen",
    "Checked every few minutes while LocaNoto is open in a browser tab.":
        "Geprüft alle paar Minuten, solange LocaNoto in einem Browsertab offen ist.",
    "Tickets": "Tickets", "Ticket system": "Ticketsystem",
    "Tickets of shared mailboxes": "Tickets der Funktionspostfächer",
    "No tickets.": "Keine Tickets.", "open": "offen", "in_progress": "in Arbeit",
    "closed": "erledigt", "Assigned to": "Zuständig", "nobody": "niemand",
    "Take it": "Übernehmen", "Note": "Notiz", "Add note": "Notiz hinzufügen",
    "From": "Von", "Received": "Eingegangen", "Subject": "Betreff",
    "History": "Verlauf", "Answer in the chat": "Im Chat beantworten",
    "all statuses": "alle Status", "Release": "Freigeben",
    "received": "eingegangen", "answered": "Standardantwort gesendet",
    "answer_failed": "Standardantwort fehlgeschlagen", "forwarded": "weitergeleitet",
    "forward_failed": "Weiterleitung fehlgeschlagen", "mail": "Mail",
    "assigned": "zugewiesen", "status": "Status", "note": "Notiz",
    "Ticket system on": "Ticketsystem an",
    "Standard answer ({ticket}, {subject}, {name} are filled in)":
        "Standardantwort ({ticket}, {subject}, {name} werden eingesetzt)",
    "Members (get every ticket)": "Mitglieder (bekommen jedes Ticket)",
    "Forward every new mail to (addresses, comma separated)":
        "Jede neue Mail weiterleiten an (Adressen, durch Komma)",
    "Ticket prefix": "Ticketkürzel", "Check now": "Jetzt prüfen",
    "New mail becomes a ticket: the sender gets the standard answer at once, the members a notice, the forward addresses the mail. Replies with the ticket number in the subject go to the same ticket.":
        "Neue Mail wird zum Ticket: Der Absender bekommt sofort die Standardantwort, die Mitglieder eine Benachrichtigung, die Weiterleitungsadressen die Mail. Antworten mit der Ticketnummer im Betreff landen beim selben Ticket.",
    "No login is stored. Members connect this mailbox under Settings with their own account; while one of them has LocaNoto open, the mailbox is checked every minute.":
        "Es wird keine Anmeldung gespeichert. Mitglieder verbinden dieses Postfach unter Einstellungen mit ihrem eigenen Konto; solange eine/r davon LocaNoto offen hat, wird das Postfach jede Minute geprüft.",
    "Connect this mailbox under Settings first.": "Dieses Postfach zuerst unter Einstellungen verbinden.",
    "This mailbox kind has no ticket support.": "Diese Postfachart unterstützt keine Tickets.",
    "First check: from now on new mail becomes a ticket.":
        "Erste Prüfung: Ab jetzt wird neue Mail zum Ticket.",
    "new mail(s)": "neue Mail(s)",
    "Unknown mailbox.": "Unbekanntes Postfach.",
    "Tickets only for shared mailboxes.": "Tickets nur für Funktionspostfächer.",
    "Unknown ticket.": "Unbekanntes Ticket.", "Unknown status.": "Unbekannter Status.",
}


def page_language(user=""):
    code = sprache.gewaehlt(user) if user else sprache.VORGABE
    sprache.setze(code)
    return code


def t(text):
    if sprache.aktuell() == "de":
        return TEXTS.get(text, text)
    return text


def tm(message):
    """A message from the German modules, in the page language."""
    return sprache.t(message)


def render(name, request=None, **context):
    context.setdefault("brand", BRAND)
    context.setdefault("logo", LOGO)
    context.setdefault("accent", ACCENT)
    context.update(t=t, tm=tm, lang=sprache.aktuell(),
                   csrf=(request.cookies.get("locanoto_csrf", "")
                         if request is not None else ""))
    return HTMLResponse(_env.get_template(name).render(**context))


def markdown(text):
    return _md.render(str(text or ""))


_env.filters["markdown"] = markdown

_BRACKET = re.compile(r"\[([^\[\]<>]{1,400})\]")
_CITE = re.compile(r"^(\s*)(.+?),\s*(Seiten?|S\.|[Pp]ages?|[Pp]\.)\s*(\d+)"
                   r"((?:\s*[-\u2013]\s*\d+)?\s*)$")
_CODE = re.compile(r"(<pre[\s\S]*?</pre>|<code>[\s\S]*?</code>)")


def source_link(room, file, page):
    """Address of the page that shows one passage on its own (/source)."""
    return "/source?" + urlencode({"room": room or "", "file": file, "page": page})


def answer_html(m):
    """The answer as HTML, every [file, page X] that names one of its
    sources a link that opens the passage in a tab of its own.

    Only citations of a real source become links: a page the model
    inferred would lead nowhere and pretend to be checkable. Code blocks
    stay as they are. The links are made when the page is drawn, not
    stored -- an old chat gets them too.
    """
    body = markdown(m.get("content"))
    where = {}
    for s in list(m.get("sources") or []) + list(m.get("sources_more") or []):
        name = str(s.get("file") or "").strip()
        if not name:
            continue
        target = (s.get("raum") or "", name)
        for key in (name.casefold(), name.rsplit(".", 1)[0].casefold()):
            where.setdefault((key, str(s.get("page"))), target)
    if not where:
        return body

    def part(text):
        hit = _CITE.match(text)
        if not hit:
            return text
        lead, name_html, word, page, rest = hit.groups()
        target = where.get((html.unescape(name_html).strip().casefold(), page))
        if not target:
            return text
        href = html.escape(source_link(target[0], target[1], page))
        return (f'{lead}<a class="cite" href="{href}" target="_blank" rel="noopener">'
                f'{name_html}, {word} {page}{rest.rstrip()}</a>'
                f'{rest[len(rest.rstrip()):]}')

    def bracket(hit):
        return "[" + ";".join(part(p) for p in hit.group(1).split(";")) + "]"

    return "".join(chunk if i % 2 else _BRACKET.sub(bracket, chunk)
                   for i, chunk in enumerate(_CODE.split(body)))


_env.filters["answer_html"] = answer_html
_env.globals["source_link"] = source_link


def _optional(request):
    """The signed-in user of a page, or None (then: to the sign-in page)."""
    s = sessions.verify(request.cookies.get("locanoto_session"))
    if not s:
        return None
    return Principal(s["user"], "session")


def _need(request):
    p = _optional(request)
    if p is None:
        query = request.url.query
        raise _ToLogin(request.url.path + (f"?{query}" if query else ""))
    page_language(p.name)
    return p


class _ToLogin(Exception):
    def __init__(self, path):
        self.path = path


def to_login_handler(_request, error):
    return RedirectResponse(f"/login?next={quote(error.path, safe='/')}",
                            status_code=303)


def _nav(p, active):
    return {"user": p.name, "admin": p.is_admin, "active": active,
            "tickets": bool(tickets.boxes_for(p.name, p.is_admin))}


# --- SIGN-IN ---

@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for it at the root, whatever the page says."""
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(HERE, "web_static", "favicon.ico"),
                        media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    import oidc
    page_language()
    return render("login.html", request, next=oidc.safe_next(next),
                  directory=oidc.enabled())


# --- CHAT ---

def _chat_options(p, request=None):
    from routes_account import sql_logins
    logins = sql_logins(p, request) if request is not None else {}
    emergency = notzugang.raeume_fuer(p.name)
    return {
        "workspaces": [(r, raeume.bezeichnung(r))
                       for r in raeume.lesbar(p.name, emergency)],
        "models": llm.chat_modelle(),
        "presets": [(n, presets.anzeige(n))
                    for n in presets.namen() + presets.eigene(p.name)],
        "web": bool(answering.mcp.websuche_server()),
        # workspaces whose database this user may query ("" = the one from
        # the environment)
        "sql": [(r, raeume.bezeichnung(r) if r else t("Database"))
                for r, _account in answering.sql_accounts(p.name, logins)],
    }


# An answer under way that was not updated for this long counts as broken
# off (its pod went away); a tool round may take TOOL_TIMEOUT without news.
RUN_STALE_SECONDS = 420


def _messages(p, chat_id):
    """Messages for the page: no server paths, each answer with its question."""
    out, question = [], ""
    for i, m in enumerate(chats.lade(p.name, chat_id)):
        entry = {k: v for k, v in m.items() if k != "bilder"}
        entry.update(index=i, images=len(m.get("bilder") or []))
        if m.get("laeuft"):
            fresh = time.time() - float(m.get("aktualisiert") or 0) < RUN_STALE_SECONDS
            entry["running"] = fresh
            entry["broken"] = not fresh
        elif m.get("fehler"):
            entry["broken"] = True
        if m.get("role") == "user":
            question = m.get("content", "")
        else:
            entry["question"] = question
        out.append(entry)
    return out


def _prefill(p, mail="", ticket=""):
    """A question for the chat box: from a mail notice or a ticket.

    Built here from the name in the link -- the link itself carries no
    mail text, so nothing of it lands in an access log.
    """
    if mail and mail in mail_watch.mailboxes():
        return mail_watch.question_for(p.name, mail)
    box, _, tid = ticket.partition(":")
    if box and tid and box in tickets.boxes_for(p.name, p.is_admin):
        item = tickets.ticket(box, tid)
        if item:
            sender = (f"{item['from_name']} <{item['from_address']}>"
                      if item.get("from_name") else item.get("from_address"))
            head = (f"Draft an answer to ticket {item['id']} ({sender})"
                    if sprache.gewaehlt(p.name) == "en" else
                    f"Entwirf eine Antwort auf Ticket {item['id']} ({sender})")
            return (f"{head}:\n\n{item.get('subject') or ''}\n\n"
                    f"{(item.get('text') or '')[:3000]}")
    return ""


@router.get("/")
def home(request: Request, mail: str = "", ticket: str = ""):
    p = _need(request)
    return render("chat.html", request, nav=_nav(p, "chat"),
                  chats=chats.liste(p.name), chat_id="", messages=[],
                  options=_chat_options(p, request), prefill=_prefill(p, mail, ticket))


@router.get("/c/{chat_id}")
def chat_page(chat_id: str, request: Request):
    p = _need(request)
    if chat_id not in {k for k, _t, _g in chats.liste(p.name)}:
        return RedirectResponse("/", status_code=303)
    return render("chat.html", request, nav=_nav(p, "chat"),
                  chats=chats.liste(p.name), chat_id=chat_id,
                  messages=_messages(p, chat_id), options=_chat_options(p, request))


@router.get("/ui/chats")
def chat_list(request: Request, current: str = "",
              p: Principal = Depends(principal)):
    page_language(p.name)
    return render("chat_list.html", request, chats=chats.liste(p.name),
                  chat_id=current)


@router.get("/ui/chats/{chat_id}/messages/{index}")
def chat_message(chat_id: str, index: int, request: Request,
                 p: Principal = Depends(principal)):
    page_language(p.name)
    if chat_id not in {k for k, _t, _g in chats.liste(p.name)}:
        raise HTTPException(404, "Unknown chat.")
    messages = _messages(p, chat_id)
    if index < 0:
        index += len(messages)          # -1: the last one
    if index < 0 or index >= len(messages):
        raise HTTPException(404, "No such message.")
    return render("message.html", request, m=messages[index], chat_id=chat_id)


@router.post("/ui/chats/{chat_id}/rename")
def chat_rename(chat_id: str, request: Request, title: str = Form(...),
                p: Principal = Depends(principal)):
    page_language(p.name)
    if chat_id in {k for k, _t, _g in chats.liste(p.name)}:
        chats.benenne(p.name, chat_id, answering.clean_title(title))
    return render("chat_list.html", request, chats=chats.liste(p.name),
                  chat_id=chat_id)


@router.post("/ui/chats/{chat_id}/delete")
def chat_delete(chat_id: str, request: Request,
                p: Principal = Depends(principal)):
    if chat_id in {k for k, _t, _g in chats.liste(p.name)}:
        chats.loesche(p.name, chat_id)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/"
    return response


@router.post("/ui/feedback")
def give_feedback(request: Request, kind: str = Form(...),
                  question: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    if kind in ("daumen_hoch", "daumen_runter"):
        feedback.notiere(kind, p.name, question[:2000], herkunft="web")
    return HTMLResponse(f'<span class="muted">{t("Thanks.")}</span>')


@router.post("/ui/chats/{chat_id}/drafts/{draft_id}/{action}")
def draft_action(chat_id: str, draft_id: str, action: str, request: Request,
                 p: Principal = Depends(principal)):
    """Send or discard a draft; answers with the draft as it is now.

    Every failure is shown in the draft, with its reason -- never as an
    error page: a failed mail can be sent again, an unclear one says so.
    """
    page_language(p.name)
    problem = ""
    try:
        if action == "send":
            headers = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
            mailboxes.send_draft(p.name, chat_id, draft_id, headers)
        elif action == "discard":
            mailboxes.discard_draft(p.name, chat_id, draft_id)
        else:
            raise HTTPException(404, "Unknown action.")
    except mailboxes.SendFailed:
        pass    # the draft carries state and error now
    except (ValueError, mailboxes.NotFound) as e:
        problem = str(e)
    except HTTPException:
        raise
    except Exception as e:
        problem = f"{type(e).__name__}: {e}"[:300]
    _i, draft = mailboxes.draft_of(p.name, chat_id, draft_id)
    if draft is None:
        return _notice(problem or "Unknown draft.", False)
    if problem and not draft.get("state"):
        draft = dict(draft, state="failed", error=problem)
    return render("draft.html", request, d=draft, chat_id=chat_id)


# --- DOCUMENTS ---

def _documents(p):
    emergency = notzugang.raeume_fuer(p.name)
    by_room = pipeline.dokumente(p.name, notzugang=emergency)
    writable = raeume.schreibbar(p.name, p.is_admin, emergency)
    rooms = [{"id": r, "label": raeume.bezeichnung(r),
              "files": by_room.get(r, []), "writable": r in writable}
             for r in raeume.lesbar(p.name, emergency)]
    return rooms, [(r, raeume.bezeichnung(r)) for r in writable]


@router.get("/documents")
def documents_page(request: Request):
    p = _need(request)
    rooms, targets = _documents(p)
    return render("documents.html", request, nav=_nav(p, "documents"),
                  rooms=rooms, targets=targets,
                  own=raeume.privat_kennung(p.name))


@router.get("/ui/documents")
def documents_fragment(request: Request, p: Principal = Depends(principal)):
    page_language(p.name)
    rooms, targets = _documents(p)
    return render("documents_list.html", request, rooms=rooms,
                  targets=targets)


@router.post("/ui/documents/delete")
def document_delete(request: Request, room: str = Form(...),
                    file: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    doc_actions.delete(p.name, file, room, p.is_admin)
    return documents_fragment(request, p)


@router.post("/ui/documents/move")
def document_move(request: Request, room: str = Form(...),
                  file: str = Form(...), target: str = Form(...),
                  p: Principal = Depends(principal)):
    page_language(p.name)
    doc_actions.move(p.name, file, room, target, p.is_admin)
    return documents_fragment(request, p)


# --- ONE PASSAGE IN A TAB OF ITS OWN ---

@router.get("/source")
def source_page(request: Request, room: str = "", file: str = "", page: str = ""):
    """What the search stored for this file and page, and for a PDF the
    page itself -- opened from a citation in an answer. Same checks as
    /api/v1/sources/page: a readable workspace, a document of it."""
    p = _need(request)
    emergency = notzugang.raeume_fuer(p.name)
    found = bool(room and file and raeume.darf_lesen(p.name, room, emergency)
                 and file in pipeline.dokumente(p.name, nur=[room],
                                                notzugang=emergency).get(room, []))
    texts = []
    if found:
        import store
        sml = store.sammlung(raeume.sammlung(room), anlegen=False)
        if sml is not None:
            data = sml.get(where=store.datei_filter(file),
                           include=["documents", "metadatas"])
            docs = store.klartext(room, data.get("documents") or [], p.name)
            texts = [d for d, meta in zip(docs, data.get("metadatas") or [])
                     if str((meta or {}).get("page", "")) == str(page)]
    return render("source.html", request, nav=_nav(p, "chat"), found=found,
                  room=room, room_label=raeume.bezeichnung(room) if found else "",
                  file=file, page=page, texts=texts,
                  image=found and file.lower().endswith(".pdf") and page.isdigit())


# --- WEB SOURCES ---

@router.get("/web")
def web_page(request: Request, task: str = ""):
    p = _need(request)
    return render("web.html", request, nav=_nav(p, "web"),
                  available=bool(answering.mcp.websuche_server()),
                  task=task if task.isalnum() else "")


def _task_call(fn, *args):
    try:
        return fn(*args)
    except web_research.Refused as e:
        raise HTTPException(404 if "Unknown" in str(e) else 429, t(str(e)))
    except ValueError as e:
        raise HTTPException(400, t(str(e)))


def _tasks_fragment(request, p, notice=""):
    return render("web_tasks.html", request, tasks=web_research.tasks(p.name),
                  notice=notice)


@router.get("/ui/web/tasks")
def web_tasks(request: Request, p: Principal = Depends(principal)):
    page_language(p.name)
    return _tasks_fragment(request, p)


@router.post("/ui/web/tasks")
def web_task_start(request: Request, query: str = Form(...),
                   p: Principal = Depends(principal)):
    """Starts a search in the background -- from the web page or the chat."""
    page_language(p.name)
    _task_call(web_research.start_search, p.name, query)
    return _tasks_fragment(request, p, t("Search started. You will be notified when the hits are there -- you can leave this page."))


@router.get("/ui/web/tasks/{task_id}")
def web_task(task_id: str, request: Request, p: Principal = Depends(principal)):
    page_language(p.name)
    item = _task_call(web_research.task_of, p.name, task_id, True)
    return render("web_task.html", request, task=item)


@router.post("/ui/web/tasks/{task_id}/delete")
def web_task_delete(task_id: str, request: Request,
                    p: Principal = Depends(principal)):
    page_language(p.name)
    _task_call(web_research.remove, p.name, task_id)
    return _tasks_fragment(request, p)


@router.post("/ui/web/read")
def web_read(request: Request, url: str = Form(...),
             p: Principal = Depends(principal)):
    page_language(p.name)
    try:
        text = web_sources.read(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return render("web_page_text.html", request, url=url, text=text)


@router.post("/ui/web/tasks/{task_id}/take-over")
async def web_take_over(task_id: str, request: Request,
                        p: Principal = Depends(principal)):
    """Chosen hits into the own workspace -- in the background as well."""
    page_language(p.name)
    form = await request.form()
    picks = [int(v) for v in form.getlist("pick") if str(v).isdigit()]
    if not picks:
        raise HTTPException(400, t("No hits chosen."))
    _task_call(web_research.start_take_over, p.name, task_id, picks)
    return _tasks_fragment(request, p, t("Taking over in the background. You will be notified when the pages are stored."))


@router.get("/ui/notifications")
def notifications(request: Request, p: Principal = Depends(principal)):
    """What the pages ask every few seconds: running and finished tasks,
    and notices (new mail, tickets). Also starts the mail check that is
    due -- with the logins of this browser, which the server never keeps."""
    page_language(p.name)
    items = web_research.tasks(p.name)
    finished = [t_ for t_ in items if t_["state"] != "running" and not t_.get("seen")]
    if p.via == "session":
        sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
        try:
            mail_watch.maybe_check(p.name, sealed)
        except Exception:
            pass
        try:
            tickets.maybe_poll(p.name, sealed, p.is_admin)
        except Exception:
            pass
    return JSONResponse({
        "running": sum(1 for t_ in items if t_["state"] == "running"),
        "finished": [{"id": t_["id"], "bad": t_["state"] == "failed",
                      "text": _task_line(t_)} for t_ in finished],
        "notices": notices.pending(p.name),
        "tickets": _open_tickets(p),
        "view": t("Show")})


def _open_tickets(p):
    """Open tickets nobody took yet, for the count on the Tickets tab."""
    n = 0
    for box in tickets.boxes_for(p.name, p.is_admin):
        try:
            n += sum(1 for x in tickets.tickets_of(box)
                     if x["status"] == "open" and not x.get("assignee"))
        except Exception:
            pass
    return n


@router.post("/ui/notices/shown")
async def notices_shown(request: Request, p: Principal = Depends(principal)):
    form = await request.form()
    notices.mark_shown(p.name, form.getlist("id"))
    return JSONResponse({"ok": True})


def _task_line(item):
    """One line about a task, in the page language."""
    if item["kind"] == "search":
        if item["state"] == "failed":
            return t("Web search failed") + f": {item['query']} – {t(item.get('error') or '')}"
        return t("Web search ready") + f": {item['query']} – {item.get('hit_count', 0)} " + t("hits")
    if item["state"] == "failed":
        return t("Take-over failed") + f": {t(item.get('error') or '')}"
    return (t("Taken over into your workspace") +
            f": {item.get('stored', 0)}/{len(item.get('titles') or [])} – {item['query']}")


_env.globals["task_line"] = _task_line


# --- SETTINGS ---

def _settings_context(p, request):
    entry = benutzer.eintrag(p.name) or {}
    connected = set(sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE)))
    return {
        "nav": _nav(p, "settings"), "language": sprache.gewaehlt(p.name),
        "instruction": prompts.anweisung(p.name) or "",
        "sso": entry.get("anmeldung") == "oidc",
        "presets": [(n, presets.anzeige(n), presets.ist_eigene(n))
                    for n in presets.namen() + presets.eigene(p.name)],
        "mailboxes": [dict(m, connected=m["name"] in connected,
                           watch=mail_watch.watching(p.name, m["name"]))
                      for m in mailboxes.overview()
                      if m["kind"] == "mailbox"],
        "tokens": [(k[:12], e.get("bezeichnung", ""), e.get("erstellt", ""))
                   for k, e in auth.liste() if e.get("benutzer") == p.name],
        "lists": _my_lists(p),
        "databases": _my_databases(p, request),
    }


def _my_databases(p, request):
    """The databases of the user's workspaces and how they connect."""
    from routes_account import sql_logins
    logins = sql_logins(p, request)
    out = []
    for room, z in sqlquellen.fuer_benutzer(p.name, notzugang.raeume_fuer(p.name)):
        mine = logins.get(room) or {}
        out.append({"room": room, "label": raeume.bezeichnung(room),
                    "server": z.get("server", ""), "database": z.get("datenbank", ""),
                    "mine": mine.get("benutzer", ""),
                    "shared": z.get("benutzer", "") if z.get("passwort") else ""})
    return out


def _my_lists(p):
    """The own list folder and the shared ones this user reads."""
    import listenquellen
    import tabellen
    area, folder, sub = listenquellen.own_folder(p.name)
    own = raeume.privat_kennung(p.name)
    try:
        sheets = [e for e in tabellen.sichtbar(
            tabellen.lies_katalog().get("eintraege", []), p.name)
            if e.get("raum") == own]
    except Exception:
        sheets = []
    readable = raeume.lesbar(p.name, notzugang.raeume_fuer(p.name))
    shared = [(raeume.bezeichnung(r), listenquellen.pfad_von(r)) for r in readable
              if r != own and listenquellen.pfad_von(r)]
    return {"area": area, "folder": folder, "sub": sub, "sheets": sheets,
            "shared": shared}


@router.get("/settings")
def settings_page(request: Request):
    p = _need(request)
    return render("settings.html", request, **_settings_context(p, request))


def _notice(text, ok=True):
    return HTMLResponse(f'<p class="{"ok" if ok else "error"}">'
                        f'{jinja2.utils.markupsafe.escape(text)}</p>')


@router.post("/ui/settings/language")
def set_language(request: Request, language: str = Form(...),
                 p: Principal = Depends(principal)):
    sprache.speichere(p.name, language)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/instruction")
def set_instruction(request: Request, text: str = Form(""),
                    p: Principal = Depends(principal)):
    page_language(p.name)
    ok, message = prompts.anweisung_speichern(p.name, text)
    return _notice(tm(message), ok)


@router.post("/ui/settings/password")
def set_password(request: Request, current: str = Form(...),
                 new: str = Form(...), p: Principal = Depends(principal)):
    page_language(p.name)
    ok, message, _notes = accounts.change_own_password(p.name, current, new)
    response = _notice(tm(message), ok)
    if ok:
        set_session_cookies(response, sessions.issue(p.name))
        response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/mailbox/{server}")
def connect_mailbox(server: str, request: Request, user: str = Form(""),
                    secret: str = Form(""), action: str = Form("connect"),
                    p: Principal = Depends(principal)):
    page_language(p.name)
    sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
    if action == "disconnect":
        sealed.pop(server, None)
        response = HTMLResponse("")
    else:
        header = mailboxes.header_for(server, user, secret)
        try:
            mailboxes.check(server, header)
        except mailboxes.NotFound:
            raise
        except Exception as e:
            # The reason, not just its class: "Fehler" told nobody why.
            return _notice(str(e)[:300] or type(e).__name__, ok=False)
        sealed[server] = header
        response = HTMLResponse("")
    response.set_cookie(SEALED_COOKIE, sessions.seal(p.name, sealed),
                        httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", path="/")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/sql/{room}")
def connect_database(room: str, request: Request, user: str = Form(""),
                     secret: str = Form(""), action: str = Form("connect"),
                     p: Principal = Depends(principal)):
    """The own SQL login for a workspace's database: checked once, then
    kept sealed in the session cookie like a mailbox login -- never on the
    server."""
    from routes_account import SQL_PREFIX
    import sqldb
    page_language(p.name)
    rooms = {r: z for r, z in sqlquellen.fuer_benutzer(
        p.name, notzugang.raeume_fuer(p.name))}
    if room not in rooms:
        raise HTTPException(404, "Unknown database.")
    sealed = sessions.unseal(p.name, request.cookies.get(SEALED_COOKIE))
    if action == "disconnect":
        sealed.pop(SQL_PREFIX + room, None)
    else:
        if not user.strip() or not secret:
            return _notice(t("User and password."), False)
        login = {"benutzer": user.strip(), "passwort": secret}
        access = dict(rooms[room], **login)
        try:
            sqldb.lade_schema(access)
        except Exception as e:
            return _notice(f"{t('Sign-in to the database failed')}: {str(e)[:200]}", False)
        sealed[SQL_PREFIX + room] = login
        answering.forget_schema(room)
    response = HTMLResponse("")
    response.set_cookie(SEALED_COOKIE, sessions.seal(p.name, sealed),
                        httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", path="/")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/lists")
def set_my_lists(request: Request, sub: str = Form(""), action: str = Form("save"),
                 p: Principal = Depends(principal)):
    """The own list folder (a subfolder of the admin's root) and reading again."""
    import listenquellen
    import tabellen
    page_language(p.name)
    if action == "save":
        ok, message = listenquellen.set_subfolder(p.name, sub)
        if not ok:
            return _notice(tm(message), False)
    tabellen.baue_katalog()
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/settings"
    return response


@router.post("/ui/settings/mailbox/{server}/watch")
def watch_mailbox(server: str, request: Request, on: str = Form(""),
                  p: Principal = Depends(principal)):
    if server not in mail_watch.mailboxes():
        raise HTTPException(404, "Unknown mailbox.")
    mail_watch.set_watch(p.name, server, on == "1")
    return HTMLResponse("")


@router.post("/ui/settings/token/{token_id}/revoke")
def revoke_token(token_id: str, request: Request,
                 p: Principal = Depends(principal)):
    mine = [k for k, e in auth.liste()
            if e.get("benutzer") == p.name and k.startswith(token_id)]
    if len(token_id) >= 8 and len(mine) == 1:
        auth.widerrufe(mine[0])
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/settings"
    return response


# --- ADMIN ---

def _admin_context(p):
    import sicherheit
    return {
        "nav": _nav(p, "admin"),
        "users": _user_page("", 0),
        # notzugang is assigned on the server or by the directory only
        # (see accounts.APP_ROLES).
        "roles": accounts.APP_ROLES,
        "workspaces": [(r, raeume.bezeichnung(r),
                        ", ".join(d.get("mitglieder") or []), d.get("gruppe") or "",
                        raeume.websuche_erlaubt(r))
                       for r, d in sorted(raeume.liste().items())
                       if not raeume.ist_privat(r)],
        "jobs": jobs.overview(),
        "security": sicherheit.kurz() if hasattr(sicherheit, "kurz") else "",
    }


USER_PAGE = 50
# Up to this many users the list shows them all; above it, only after a
# search -- a list of everybody is no help to find one.
USER_LIST_ALL = 20


def _user_page(query, offset):
    """One page of the user list, filtered by a part of the name.

    With thousands of accounts the page shows a search field and at most
    USER_PAGE rows instead of everyone at once.
    """
    q = str(query or "").strip().lower()
    names = [n for n in benutzer.namen() if q in n.lower()] if q else benutzer.namen()
    offset = max(0, int(offset or 0))
    rows = []
    for n in names[offset:offset + USER_PAGE]:
        entry = benutzer.eintrag(n) or {}
        rows.append((n, entry.get("rolle", "nutzer"), entry.get("anmeldung", "lokal")))
    hidden = not q and len(names) > USER_LIST_ALL
    if hidden:
        rows = []
    return {"rows": rows, "total": len(names), "offset": offset, "query": query or "",
            "hidden": hidden,
            "next": offset + USER_PAGE if offset + USER_PAGE < len(names) else None,
            "previous": max(0, offset - USER_PAGE) if offset else None}


@router.get("/ui/admin/users")
def admin_user_rows(request: Request, q: str = "", offset: int = 0,
                    p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    return render("admin_users.html", request, users=_user_page(q, offset),
                  roles=accounts.APP_ROLES)


@router.get("/ui/users/suggest")
def suggest_users(q: str = "", p: Principal = Depends(principal)):
    """Up to ten user names containing q, for fields that take user names
    (admins only: the list of accounts is not for everyone)."""
    _admin(p)
    q = q.strip().lower()
    if not q:
        return JSONResponse([])
    starts = [n for n in benutzer.namen() if n.lower().startswith(q)]
    inside = [n for n in benutzer.namen() if q in n.lower() and n not in starts]
    return JSONResponse((starts + inside)[:10])


@router.get("/admin")
def admin_page(request: Request):
    p = _need(request)
    if not p.is_admin:
        return RedirectResponse("/", status_code=303)
    return render("admin.html", request, **_admin_context(p))


def _admin(p):
    if not p.is_admin:
        raise HTTPException(403, "Admins only.")


def _back_to_admin():
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/admin"
    return response


@router.post("/ui/admin/users")
def admin_create_user(request: Request, name: str = Form(...),
                      password: str = Form(...), role: str = Form("nutzer"),
                      p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.create(name, password, role, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/users/{name}/role")
def admin_set_role(name: str, request: Request, role: str = Form(...),
                   p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.set_role(name, role, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/users/{name}/delete")
def admin_delete_user(name: str, request: Request,
                      p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    ok, message, _n = accounts.delete(name, by=p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/workspaces")
async def admin_create_workspace(request: Request,
                                 p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    form = await request.form()
    # ticked boxes, or one comma separated text as older pages send it
    members = [m.strip() for part in form.getlist("members")
               for m in str(part).split(",") if m.strip()]
    room_id, label = str(form.get("id") or "").strip(), str(form.get("label") or "").strip()
    if not room_id or not label:
        return _notice(t("Id and label."), False)
    ok, message = raeume.anlegen(room_id, label, "", members)
    if ok:
        benutzer.protokolliere("raum_angelegt", room_id, p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


def _shared_rooms():
    return [r for r in sorted(raeume.liste()) if not raeume.ist_privat(r)]


@router.get("/ui/admin/workspaces/{room}/edit")
def admin_workspace_edit(room: str, request: Request,
                         p: Principal = Depends(principal)):
    """The edit form of a workspace: label, members to tick, group, web search."""
    _admin(p)
    page_language(p.name)
    data = raeume.liste().get(room)
    if data is None or raeume.ist_privat(room):
        raise HTTPException(404, "No such workspace.")
    members = [(m, m) for m in sorted(m for m in (data.get("mitglieder") or []) if m != "*")]
    return render("admin_ws_edit.html", request, room=room,
                  label=raeume.bezeichnung(room),
                  description=data.get("beschreibung") or "",
                  open_to_all="*" in (data.get("mitglieder") or []),
                  members=members, group=data.get("gruppe") or "",
                  web=raeume.websuche_erlaubt(room))


@router.post("/ui/admin/workspaces/{room}/delete")
def admin_workspace_delete(room: str, request: Request,
                           p: Principal = Depends(principal)):
    """The same as DELETE /api/v1/admin/workspaces/{room}: its passages stay."""
    _admin(p)
    page_language(p.name)
    if room not in raeume.liste() or raeume.ist_privat(room):
        raise HTTPException(404, "No such workspace.")
    ok, message = raeume.entfernen(room)
    if ok:
        benutzer.protokolliere("raum_entfernt", room, p.name)
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/workspaces/{room}/save")
async def admin_workspace_save(room: str, request: Request,
                               p: Principal = Depends(principal)):
    """The same as PATCH /api/v1/admin/workspaces/{room}."""
    _admin(p)
    page_language(p.name)
    if room not in raeume.liste() or raeume.ist_privat(room):
        raise HTTPException(404, "No such workspace.")
    form = await request.form()
    steps = [raeume.beschriften(room, str(form.get("label") or "").strip() or None,
                                str(form.get("description") or "").strip())]
    if form.get("open") == "1":
        steps.append(raeume.fuer_alle_oeffnen(room))
    else:
        steps.append(raeume.mitglieder_setzen(
            room, [str(m) for m in form.getlist("members") if str(m).strip()]))
    steps.append(raeume.gruppe_setzen(room, str(form.get("group") or "").strip()))
    steps.append(raeume.websuche_setzen(room, form.get("web") == "1"))
    failed = [m for ok, m in steps if not ok]
    benutzer.protokolliere("raum_geaendert", room, p.name, "web page")
    if failed:
        return _notice(" ".join(tm(m) for m in failed), False)
    return _back_to_admin()


@router.get("/ui/admin/users/{name}/workspaces")
def admin_user_workspaces(name: str, request: Request,
                          p: Principal = Depends(principal)):
    """The shared workspaces to tick for one user."""
    _admin(p)
    page_language(p.name)
    if not benutzer.eintrag(name):
        raise HTTPException(404, "No such user.")
    rooms, everybody = [], []
    for r in _shared_rooms():
        members = raeume.liste()[r].get("mitglieder") or []
        if "*" in members:
            everybody.append(raeume.bezeichnung(r))
        elif name in members:
            rooms.append((r, raeume.bezeichnung(r)))
    return render("admin_user_ws.html", request, user=name, rooms=rooms,
                  everybody=everybody)


@router.get("/ui/admin/workspaces/suggest")
def suggest_workspaces(q: str = "", p: Principal = Depends(principal)):
    """Up to ten shared workspaces with a member list whose id or label
    contains q: [[id, label], ...]."""
    _admin(p)
    q = q.strip().lower()
    if not q:
        return JSONResponse([])
    out = []
    for r in _shared_rooms():
        if "*" in (raeume.liste()[r].get("mitglieder") or []):
            continue
        label = raeume.bezeichnung(r)
        if q in r.lower() or q in label.lower():
            out.append([r, label])
    out.sort(key=lambda x: (not x[1].lower().startswith(q), x[1].lower()))
    return JSONResponse(out[:10])


@router.post("/ui/admin/users/{name}/workspaces")
async def admin_user_workspaces_save(name: str, request: Request,
                                     p: Principal = Depends(principal)):
    """Adds the user to the ticked workspaces and removes them from the
    others. Workspaces visible to everybody stay as they are."""
    _admin(p)
    page_language(p.name)
    if not benutzer.eintrag(name):
        raise HTTPException(404, "No such user.")
    form = await request.form()
    if form.get("sent") != "1":
        raise HTTPException(400, "Incomplete form.")
    wanted = set(str(r) for r in form.getlist("rooms"))
    failed = []
    for r in _shared_rooms():
        members = list(raeume.liste()[r].get("mitglieder") or [])
        if "*" in members:
            continue
        has = name in members
        if (r in wanted) == has:
            continue
        new = members + [name] if r in wanted else [m for m in members if m != name]
        ok, message = raeume.mitglieder_setzen(r, new)
        if not ok:
            failed.append(tm(message))
    benutzer.protokolliere("raeume_des_nutzers", name, p.name, ", ".join(sorted(wanted)))
    if failed:
        return _notice(" ".join(failed), False)
    return _back_to_admin()


@router.post("/ui/admin/workspaces/{room}/websearch")
def admin_set_web_search(room: str, request: Request, allow: str = Form(""),
                         p: Principal = Depends(principal)):
    """The same as PATCH /api/v1/admin/workspaces/{room} with web_search."""
    _admin(p)
    page_language(p.name)
    ok, message = raeume.websuche_setzen(room, allow == "1")
    return _back_to_admin() if ok else _notice(tm(message), False)


@router.post("/ui/admin/workspaces/sql")
def admin_set_sql_account(request: Request, room: str = Form(...),
                          server: str = Form(""), port: str = Form(""),
                          database: str = Form(""), user: str = Form(""),
                          password: str = Form(""), note: str = Form(""),
                          p: Principal = Depends(principal)):
    """The same as PUT /api/v1/admin/workspaces/{room}/sql-account."""
    _admin(p)
    page_language(p.name)
    ok, message = sqlquellen.setze(room, {
        "server": server, "port": int(port) if port.strip().isdigit() else None,
        "datenbank": database, "benutzer": user, "passwort": password,
        "hinweis": note}, benutzer=p.name, ist_verwalter=True)
    if ok:
        answering.forget_schema(room)
        response = HTMLResponse("")
        response.headers["HX-Redirect"] = "/admin/databases"
        return response
    return _notice(tm(message), False)


@router.post("/ui/admin/jobs/{name}")
def admin_start_job(name: str, request: Request,
                    p: Principal = Depends(principal)):
    _admin(p)
    page_language(p.name)
    result = jobs.start(name, by=p.name)
    return _notice(tm(result.get("message", "")), result.get("started", False))
