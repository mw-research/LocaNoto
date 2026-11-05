"""Exchange-Postfaecher direkt anbinden, ohne Server dazwischen.

LocaNoto spricht sonst MCP -- JSON-RPC ueber HTTP oder stdio, siehe
mcp.py. Exchange spricht EWS: SOAP ueber HTTPS, mit NTLM oder Basic.
Dieses Modul uebersetzt zwischen beidem, innerhalb des Prozesses.

DAMIT KEIN ZWEITER DIENST NOETIG IST. Wer ein Postfach anbinden will,
traegt die Adresse des Exchange-Servers ein und meldet sich an; es gibt
keinen weiteren Behaelter, kein zweites Abbild und keine zweite Stelle,
an der Anmeldedaten vorbeikommen.

NACH AUSSEN SIEHT ES AUS WIE EIN WERKZEUGSERVER. Diese Klasse hat
dieselben drei Methoden wie mcp.Verbindung -- werkzeuge(), rufe(),
schliesse(). Alles, was darueber liegt, kennt den Unterschied nicht:
der Werkzeugkreis in pipeline.py, die Bestaetigung vor dem Senden, der
Hinweis unter automatischen Antworten, die Anmeldung in der Sitzung.
Wer spaeter ein anderes Postfach oder ein Ticketsystem anbindet, nimmt
wieder mcp.py -- die Wege stehen nebeneinander und nicht hintereinander.

ANMELDEDATEN KOMMEN JE AUFRUF MIT und werden nirgends abgelegt. Sie
stehen im Kopf, den die Sitzung mitgibt, und sind mit ihr weg.

DIE BIBLIOTHEK WIRD ERST BEIM ERSTEN ZUGRIFF GELADEN. Eine Anlage ohne
Postfach laedt exchangelib nie.
"""
import base64
import datetime
import hashlib
import json
import re
from urllib.parse import urlsplit

import local_time
import paths

# Wie viele Nachrichten hoechstens vom Server geholt werden, bevor
# gefiltert wird. Ohne Grenze zieht "die letzten 30 Tage" ein ganzes
# Postfach durch die Leitung, und das Modell sieht davon ohnehin nur
# die ersten paar.
HOLGRENZE = paths.env_int("POSTFACH_HOLGRENZE", 200)

# Wie viel Text einer Nachricht in die Liste kommt. Der Volltext ist
# ein eigenes Werkzeug -- eine Uebersicht ueber zwanzig Nachrichten
# darf nicht zwanzig vollstaendige Mails in den Prompt legen.
TEXTAUSZUG = paths.env_int("POSTFACH_TEXTAUSZUG", 400)

ZEITLIMIT = paths.env_float("POSTFACH_TIMEOUT", 60)

# After an error while sending: how far back the sent folder is searched
# for the message (check_sent).
SENT_LOOKBACK_MINUTES = 15


class Fehler(Exception):
    """Das Postfach hat nicht oder falsch geantwortet."""


# --- KURZKENNUNGEN ---
#
# EWS-Kennungen sind ueber hundert Zeichen lang. Zwanzig davon in einer
# Uebersicht kosten mehr Prompt als die Nachrichten selbst, deshalb
# bekommt jede Nachricht eine kurze Kennung, und die lange bleibt hier.
#
# Das ist ein Zwischenspeicher und kein Bestand: nach einem Neustart
# ist er leer. Eine unbekannte Kennung endet darum nicht im falschen
# Empfaenger, sondern in einer Fehlermeldung -- siehe _lange_kennung().
#
# The short id is derived from the long one, so the same message gets
# the same short id in every pod and every question. And the ids a
# connection hands out are kept with the chat answer (new_ids,
# answering.py) and loaded again for the next question and for a draft
# (load_ids): with two server pods, "answer that mail" or the click on a
# draft may reach a pod that never listed the mail.
_KENNUNGEN = {}
_KENNUNG_GRENZE = 5000


def _merke_kennung(server, lang):
    roh = json.dumps([server, lang], ensure_ascii=False, default=str)
    kurz = "m" + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:8]
    if len(_KENNUNGEN) >= _KENNUNG_GRENZE and kurz not in _KENNUNGEN:
        for alt in list(_KENNUNGEN)[:_KENNUNG_GRENZE // 2]:
            _KENNUNGEN.pop(alt, None)
    _KENNUNGEN[kurz] = (server, lang)
    return kurz


def remember(conn, lang):
    """A short id for a message of conn, also recorded in conn.new_ids."""
    bereich = conn._bereich()
    kurz = _merke_kennung(bereich, lang)
    sink = getattr(conn, "new_ids", None)
    if isinstance(sink, dict):
        sink[kurz] = [bereich, list(lang) if isinstance(lang, tuple) else lang]
    return kurz


def load_ids(known):
    """Short ids kept with a chat ({short: [scope, long]}) back into the cache."""
    for kurz, entry in (known or {}).items():
        try:
            bereich, lang = entry
        except (TypeError, ValueError):
            continue
        if isinstance(lang, list):
            lang = tuple(lang)
        _KENNUNGEN[str(kurz)] = (bereich, lang)


def _lange_kennung(server, kurz):
    eintrag = _KENNUNGEN.get(str(kurz or "").strip())
    if not eintrag:
        raise Fehler(
            f"Unbekannte Kennung '{kurz}'. Sie stammt aus einer frueheren "
            f"Sitzung oder von einem anderen Postfach. Die Nachricht "
            f"zuerst erneut heraussuchen.")
    # Die Kennung gehoert zu EINEM Postfach. Wer sie in einem anderen
    # benutzt, bekommt sie nicht ausgeliefert -- gesendet wuerde sonst
    # mit fremden Anmeldedaten an einen Bezug, der hier nicht steht.
    if eintrag[0] != server:
        raise Fehler(f"Die Kennung '{kurz}' gehoert nicht zu '{server}'.")
    return eintrag[1]


# --- WERKZEUGE ---
#
# Fest aufgeschrieben und nicht vom Server erfragt: Exchange meldet
# keine Werkzeuge, es hat eine feste Schnittstelle. Was hier steht, ist
# damit zugleich die vollstaendige Liste dessen, was LocaNoto an einem
# Postfach tun kann.
#
# DIE NAMEN SIND DIE, DIE IN mcp.VORLAGEN UNTER "sendet" STEHEN. Wer
# einen aendert, aendert beide Stellen -- sonst laeuft ein Sendewerkzeug
# ohne Rueckfrage.
WERKZEUGE = (
    {
        "name": "mails_lesen",
        "beschreibung": (
            "Nachrichten aus dem Postfach {label} heraussuchen. Ohne "
            "Einschraenkung kommen die neuesten. Fuer 'was hat X "
            "geschrieben' das Feld 'von' setzen, fuer 'die letzten 24 "
            "Stunden' das Feld 'stunden'. Gibt Datum, Absender, Betreff "
            "und einen Textanfang je Nachricht zurueck, dazu eine "
            "Kennung fuer den Volltext und fuer Antworten."),
        "schema": {
            "type": "object",
            "properties": {
                "von": {"type": "string", "description":
                        "Absender: Name oder Adresse, Teil genuegt."},
                "suchtext": {"type": "string", "description":
                             "Kommt in Betreff oder Text vor."},
                "stunden": {"type": "integer", "description":
                            "Nur Nachrichten aus den letzten so vielen "
                            "Stunden. 24 fuer 'seit gestern'."},
                "anzahl": {"type": "integer", "description":
                           "Hoechstens so viele. Vorgabe 20."},
                "ordner": {"type": "string", "enum":
                           ["posteingang", "gesendet"], "description":
                           "Vorgabe posteingang."},
            },
        },
    },
    {
        "name": "mail_volltext",
        "beschreibung": (
            "Den vollstaendigen Text einer Nachricht aus {label} holen, "
            "samt Empfaengern und Kopienempfaengern. Die Kennung stammt "
            "aus mails_lesen."),
        "schema": {
            "type": "object",
            "properties": {
                "kennung": {"type": "string"},
            },
            "required": ["kennung"],
        },
    },
    {
        "name": "mail_senden",
        "beschreibung": (
            "Eine neue Nachricht aus dem Postfach {label} verschicken."),
        "schema": {
            "type": "object",
            "properties": {
                "an": {"type": "string", "description":
                       "Empfaenger, mehrere durch Komma getrennt."},
                "kopie": {"type": "string"},
                "betreff": {"type": "string"},
                "body": {"type": "string", "description":
                         "Der Text der Nachricht."},
                "anhaenge": {"type": "array", "items": {"type": "string"},
                             "description":
                             "Attachments, by file name: documents of the user's "
                             "own workspace, or images of this chat as "
                             "chat-image-1, chat-image-2, ... Nothing else."},
            },
            "required": ["an", "betreff", "body"],
        },
    },
    {
        "name": "antwort_senden",
        "beschreibung": (
            "Auf eine Nachricht in {label} antworten. Die Kennung stammt "
            "aus mails_lesen; Betreff und Empfaenger ergeben sich aus "
            "der urspruenglichen Nachricht."),
        "schema": {
            "type": "object",
            "properties": {
                "kennung": {"type": "string"},
                "body": {"type": "string", "description":
                         "Der Text der Antwort."},
                "allen": {"type": "boolean", "description":
                          "Auch an alle Kopienempfaenger. Vorgabe nein."},
            },
            "required": ["kennung", "body"],
        },
    },
    # Reading only, like mails_lesen: nothing here changes the calendar,
    # so nothing needs a confirmation.
    {
        "name": "mail_thread",
        "beschreibung": (
            "Den ganzen Verlauf (alle Nachrichten zum selben Betreff, "
            "Posteingang und Gesendet, aelteste zuerst) zu einer Nachricht "
            "aus {label} holen -- fuer 'fasse die Konversation zusammen'. "
            "Zitierte Vorgaenger sind aus jeder Nachricht entfernt. Die "
            "Kennung stammt aus mails_lesen."),
        "schema": {
            "type": "object",
            "properties": {
                "kennung": {"type": "string"},
            },
            "required": ["kennung"],
        },
    },
    {
        "name": "calendar_events",
        "beschreibung": (
            "Termine aus dem Kalender von {label} heraussuchen, auch "
            "Serientermine. Heute ist {today}. Ohne Angaben: die naechsten "
            "7 Tage ab heute. Fuer 'naechste Woche' oder 'am 12.' das Feld "
            "'from' auf den ersten Tag setzen und 'days' auf die Anzahl "
            "Tage. Gibt je Termin Zeit, Betreff, Ort und Organisator "
            "zurueck, dazu eine Kennung fuer calendar_event."),
        "schema": {
            "type": "object",
            "properties": {
                "from": {"type": "string", "description":
                         "Erster Tag, JJJJ-MM-TT. Vorgabe heute."},
                "days": {"type": "integer", "description":
                         "Wie viele Tage ab 'from'. Vorgabe 7, hoechstens 92."},
                "text": {"type": "string", "description":
                         "Kommt in Betreff, Ort oder Organisator vor."},
                "count": {"type": "integer", "description":
                          "Hoechstens so viele. Vorgabe 50."},
            },
        },
    },
    {
        "name": "calendar_event",
        "beschreibung": (
            "Einen Termin aus {label} im Einzelnen: Teilnehmer mit Zu- oder "
            "Absage, Ort, Beschreibung. Die Kennung stammt aus "
            "calendar_events."),
        "schema": {
            "type": "object",
            "properties": {
                "kennung": {"type": "string"},
            },
            "required": ["kennung"],
        },
    },
)

_TERMIN_FELDER = {
    "subject": {"type": "string", "description": "Betreff."},
    "start": {"type": "string", "description":
              "Beginn in Ortszeit, 'JJJJ-MM-TT HH:MM'. Nur 'JJJJ-MM-TT' "
              "heisst ganztaegig."},
    "end": {"type": "string", "description":
            "Ende, 'JJJJ-MM-TT HH:MM' oder nur 'HH:MM' am selben Tag; bei "
            "ganztaegig der letzte Tag. Ohne Ende: 'duration'."},
    "duration": {"type": "integer", "description":
                 "Dauer in Minuten, wenn kein Ende angegeben ist. Vorgabe 60."},
    "all_day": {"type": "boolean", "description": "Ganztaegig."},
    "location": {"type": "string", "description": "Ort oder Raum."},
    "body": {"type": "string", "description": "Beschreibung, Tagesordnung."},
}

WERKZEUGE = WERKZEUGE + (
    {
        "name": "calendar_add",
        "beschreibung": (
            "Einen Termin NUR in den Kalender von {label} eintragen, ohne "
            "jemanden einzuladen ('trag mir ... ein', 'blocke mir ...'). "
            "Heute ist {today}. Der Nutzer bestaetigt vor dem Eintragen."),
        "schema": {"type": "object", "properties": dict(_TERMIN_FELDER),
                   "required": ["subject", "start"]},
    },
    {
        "name": "meeting_request",
        "beschreibung": (
            "Eine Besprechungsanfrage aus {label} an andere verschicken: "
            "Einladung mit Zeit, Ort und Text, der Termin steht danach auch "
            "im eigenen Kalender. Heute ist {today}. Teilnehmer als "
            "Mailadressen -- nicht raten; unbekannte Adressen erst "
            "erfragen. Der Nutzer bestaetigt vor dem Versand."),
        "schema": {"type": "object", "properties": dict(
            _TERMIN_FELDER,
            attendees={"type": "string", "description":
                       "Teilnehmer, Mailadressen durch Komma."},
            optional_attendees={"type": "string", "description":
                                "Optionale Teilnehmer, Mailadressen."}),
            "required": ["subject", "start", "attendees"]},
    },
)

SENDEWERKZEUGE = ("mail_senden", "antwort_senden")

# Writing to a calendar always waits for a person, also in a mailbox that
# may send on its own: an invitation goes out to people, and an entry in
# the own calendar at the wrong day is found only when it is too late.
KALENDERWERKZEUGE = ("calendar_add", "meeting_request")

# How long one message of a thread may be, and the whole thread. The tool
# loop cuts every result at 8000 characters (pipeline.werkzeuglauf), so
# the newest messages would otherwise be the ones that fall off.
THREAD_MESSAGE = paths.env_int("POSTFACH_VERLAUF_NACHRICHT", 2500)
THREAD_TOTAL = paths.env_int("POSTFACH_VERLAUF_GESAMT", 7500)


def ews_adresse(ziel):
    """Aus dem, was der Verwalter eintraegt, eine EWS-Adresse machen.

    Eingetragen wird 'owa.firma.de', die vollstaendige Adresse oder das,
    was im Browser steht (https://owa.firma.de/owa/auth/logon.aspx).
    Alles soll gehen -- wer den Pfad kennt, tippt ihn, und wer nicht,
    muss ihn nicht kennen.
    """
    ziel = str(ziel or "").strip()
    if not ziel:
        return ""
    if "://" not in ziel:
        ziel = "https://" + ziel
    teile = urlsplit(ziel)
    # EWS lives at the root of every Exchange server. Whatever path came
    # with the address -- the OWA sign-in page, or "/EWS/..." appended to
    # it by an earlier version of this function -- only the part from
    # "/EWS/" on is kept, and without it the standard path.
    pfad = teile.path
    stelle = pfad.lower().find("/ews/")
    pfad = pfad[stelle:] if stelle >= 0 else "/EWS/Exchange.asmx"
    return f"{teile.scheme}://{teile.netloc}{pfad}"


class Postfach:
    """Ein Exchange-Postfach, nach aussen wie ein Werkzeugserver.

    Gleiche Form wie mcp.Verbindung, damit alles darueber -- der
    Werkzeugkreis, die Bestaetigung vor dem Senden, der Hinweis -- nicht
    zwischen beiden unterscheiden muss.
    """

    def __init__(self, name, angaben, zusatz_kopf=None):
        self.name = name
        self.angaben = dict(angaben or {})
        self.zusatz_kopf = dict(zusatz_kopf or {})
        self._konto = None
        # Short ids handed out by this connection (remember()); answering
        # keeps them with the answer.
        self.new_ids = {}
        # Set by whoever knows user and chat (answering, mailboxes.send_draft):
        # callable(names) -> [(name, bytes, mime)], see attachments.py.
        # Without it no attachment goes out.
        self.attachment_source = None

    # --- ANMELDUNG ---

    def _zugang(self):
        """(Benutzer, Passwort) aus dem Kopf der Sitzung.

        Gespeichert wird in der Sitzung der fertige Kopf und nicht das
        Passwort -- so steht es in app.py, und so bleibt es. EWS
        braucht beides einzeln, also wird hier zurueckgerechnet. Das
        Passwort entsteht dabei nur als lokale Variable dieses Aufrufs.
        """
        wert = str(self.zusatz_kopf.get("Authorization") or "")
        if not wert.lower().startswith("basic "):
            raise Fehler(
                f"{self.name}: nicht angemeldet. Das Postfach unter "
                f"'Meine Postfaecher' verbinden.")
        try:
            roh = base64.b64decode(wert.split(None, 1)[1]).decode("utf-8")
        except Exception:
            raise Fehler(f"{self.name}: Anmeldedaten nicht lesbar.")
        benutzer, _, passwort = roh.partition(":")
        if not benutzer or not passwort:
            raise Fehler(f"{self.name}: Anmeldedaten unvollstaendig.")
        return benutzer, passwort

    def adresse(self):
        """Das Postfach, das diese Verbindung oeffnet.

        Das eingetragene, sonst das des Anmeldenden. So laeuft ein
        Funktionspostfach ueber die Stellvertretung -- jeder meldet sich
        mit SEINEN Daten an, und Exchange entscheidet, ob er hineindarf.
        Und ein persoenlicher Eintrag ohne Adresse dient allen Nutzern:
        jeder oeffnet darin sein eigenes Postfach.
        """
        eingetragen = str(self.angaben.get("postfach") or "").strip()
        adresse = eingetragen or self._zugang()[0]
        if "@" not in adresse:
            raise Fehler(
                f"{self.name}: '{adresse}' ist keine Postfachadresse. "
                f"Mit der vollstaendigen Mailadresse anmelden.")
        return adresse

    def _bereich(self):
        """Wozu eine Kurzkennung gehoert: Eintrag UND Postfachadresse.

        Der Eintrag allein reicht nicht. Einen persoenlichen Eintrag
        teilen sich alle Nutzer; hinge die Kennung nur an seinem Namen,
        loeste die Kennung aus Annas Postfach auch in Bernds Sitzung auf.
        """
        return f"{self.name}:{self.adresse().lower()}"

    def _verbindung(self):
        if self._konto is not None:
            return self._konto
        try:
            from exchangelib import (Account, Configuration, Credentials,
                                     DELEGATE)
            from exchangelib.protocol import BaseProtocol
        except ImportError:
            raise Fehler(
                f"{self.name}: exchangelib fehlt im Abbild. "
                f"'pip install exchangelib' oder das Abbild erneuern.")

        benutzer, passwort = self._zugang()
        BaseProtocol.TIMEOUT = ZEITLIMIT
        adresse = self.adresse()
        zugang = Credentials(username=benutzer, password=passwort)
        url = ews_adresse(self.angaben.get("url"))
        # The installation's time zone, not the container's: in a
        # container that is UTC, and every appointment was an hour off.
        tz = _zeitzone()
        try:
            if url:
                konfig = Configuration(service_endpoint=url,
                                       credentials=zugang)
                self._konto = Account(primary_smtp_address=adresse,
                                      config=konfig, autodiscover=False,
                                      access_type=DELEGATE,
                                      default_timezone=tz)
            else:
                # Ohne Adresse sucht exchangelib den Server selbst. Das
                # ist der bequeme Weg und der langsame; er steht hier
                # als Rueckfall, nicht als Vorgabe.
                self._konto = Account(primary_smtp_address=adresse,
                                      credentials=zugang, autodiscover=True,
                                      access_type=DELEGATE,
                                      default_timezone=tz)
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")
        return self._konto

    # --- WERKZEUGE ---

    def werkzeuge(self):
        """Die feste Liste -- aber erst, nachdem der Server geantwortet hat.

        Der Zugriff vorweg ist kein Beiwerk: an dieser Stelle wird die
        Anmeldung erprobt, bevor sie gemerkt wird. Ohne ihn faellt ein
        falsches Passwort erst mitten in einer Antwort auf.
        """
        konto = self._verbindung()
        try:
            _ = konto.inbox.total_count
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")
        # Die geoeffnete Adresse und nicht der Name des Eintrags: bei einem
        # gemeinsamen Eintrag hiesse er fuer jeden Nutzer "postfach", und
        # das Modell wuesste nicht, wessen Post es liest.
        label = self.adresse()
        # The model needs today's date to turn "next Tuesday" into a day.
        heute = _heute(_zeitzone(konto))
        today = f"{_WOCHENTAGE[heute.weekday()]}, {heute:%Y-%m-%d}"
        attachable = []
        if self.attachment_source is not None and hasattr(self.attachment_source, "available"):
            try:
                attachable = self.attachment_source.available()
            except Exception:
                attachable = []
        out = []
        for w in WERKZEUGE:
            text = w["beschreibung"].format(label=label, today=today)
            if w["name"] == "mail_senden":
                text += (" Attachable now: " + ", ".join(attachable[:30])
                         + (" ..." if len(attachable) > 30 else "") + "."
                         if attachable else " No files can be attached now.")
            out.append({"server": self.name, "name": w["name"],
                        "beschreibung": text, "schema": w["schema"]})
        return out

    def rufe(self, name, argumente=None):
        a = dict(argumente or {})
        if name == "mails_lesen":
            return self._lesen(a)
        if name == "mail_volltext":
            return self._volltext(a)
        if name == "mail_thread":
            return self._thread(a)
        if name == "calendar_events":
            return self._events(a)
        if name == "calendar_event":
            return self._event(a)
        if name == "calendar_add":
            return self._anlegen(a, einladen=False)
        if name == "meeting_request":
            return self._anlegen(a, einladen=True)
        if name == "mail_senden":
            return self._senden(a)
        if name == "antwort_senden":
            return self._antworten(a)
        raise Fehler(f"{self.name}: kein Werkzeug namens '{name}'.")

    def pruefe_entwurf(self, name, argumente=None):
        """Before a call becomes a draft: is it complete? Raises Fehler.

        Returns a line for the person who confirms ("Di 11.11.2026
        14:00-15:00 ..."), or None for tools without a check. Checked
        here and not only when it runs: the model can still correct a
        wrong date, the person on the button can no longer.
        """
        if name == "mail_senden" and (argumente or {}).get("anhaenge"):
            files = self._anhaenge(argumente["anhaenge"])
            return ("Anhänge: " + ", ".join(f"{n} ({len(d) // 1024 + 1} KB)"
                                            for n, d, _m in files))
        if name == "antwort_senden" and (argumente or {}).get("anhaenge"):
            raise Fehler("Anhänge gehen nur mit einer neuen Nachricht (mail_senden).")
        if name not in KALENDERWERKZEUGE:
            return None
        return _termin_vorschau(_termin_angaben(argumente or {},
                                                name == "meeting_request"))

    def schliesse(self):
        if self._konto is not None:
            try:
                self._konto.protocol.close()
            except Exception:
                pass
            self._konto = None

    # --- LESEN ---

    def _ordner(self, wahl):
        """(Ordner, Bezeichnung). Die Bezeichnung geht in die Ausgabe.

        Sie wird mitgegeben und nicht spaeter aus dem Ordner
        zurueckgerechnet: ein Vergleich zweier Ordnerobjekte sagt
        nicht verlaesslich, welches gemeint war.
        """
        konto = self._verbindung()
        if str(wahl or "").lower().startswith("ges"):
            return konto.sent, "Gesendet"
        return konto.inbox, "Posteingang"

    def _lesen(self, a):
        from exchangelib import EWSDateTime, UTC

        anzahl = max(1, min(int(a.get("anzahl") or 20), 100))
        von = str(a.get("von") or "").strip().lower()
        such = str(a.get("suchtext") or "").strip().lower()
        ordner, ordnername = self._ordner(a.get("ordner"))

        abfrage = ordner.all()
        stunden = a.get("stunden")
        if stunden:
            grenze = (EWSDateTime.now(tz=UTC)
                      - datetime.timedelta(hours=max(1, int(stunden))))
            abfrage = abfrage.filter(datetime_received__gte=grenze)
        try:
            posten = list(
                abfrage.only("datetime_received", "subject", "sender",
                             "to_recipients", "is_read", "text_body")
                .order_by("-datetime_received")[:HOLGRENZE])
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")

        # Gefiltert wird hier und nicht im Server: eine EWS-Einschraenkung
        # auf den Absender trifft nur die Adresse, nicht den angezeigten
        # Namen -- und gefragt wird nach dem Namen.
        zeilen = []
        for m in posten:
            absender = _absender(m)
            text = (getattr(m, "text_body", "") or "").strip()
            betreff = (getattr(m, "subject", "") or "").strip()
            if von and von not in absender.lower():
                continue
            if such and such not in f"{betreff}\n{text}".lower():
                continue
            kurz = remember(self, m.id)
            zeilen.append(
                f"[{kurz}] {_datum(_lokal(getattr(m, 'datetime_received', None)))} | "
                f"von: {absender} | {betreff or '(ohne Betreff)'}"
                + (f"\n    {_zusammen(text, TEXTAUSZUG)}" if text else ""))
            if len(zeilen) >= anzahl:
                break

        if not zeilen:
            return "Keine Nachricht passt."
        kopf = (f"{len(zeilen)} Nachricht(en) aus {ordnername}, "
                f"neueste zuerst:")
        return kopf + "\n" + "\n".join(zeilen)

    def _volltext(self, a):
        konto = self._verbindung()
        kennung = _lange_kennung(self._bereich(), a.get("kennung"))
        try:
            m = konto.inbox.get(id=kennung)
        except Exception:
            try:
                m = konto.sent.get(id=kennung)
            except Exception as e:
                raise Fehler(f"{self.name}: Nachricht nicht gefunden "
                             f"({_kurz(e)}).")
        an = ", ".join(_adressen(getattr(m, "to_recipients", None)))
        kopie = ", ".join(_adressen(getattr(m, "cc_recipients", None)))
        teile = [f"Datum:   {_datum(_lokal(getattr(m, 'datetime_received', None)))}",
                 f"Von:     {_absender(m)}",
                 f"An:      {an or '-'}"]
        if kopie:
            teile.append(f"Kopie:   {kopie}")
        teile.append(f"Betreff: {getattr(m, 'subject', '') or ''}")
        teile.append("")
        teile.append((getattr(m, "text_body", "") or "").strip()
                     or "(kein Text)")
        return "\n".join(teile)

    def _nachricht(self, kennung):
        """A message of this mailbox by its short id, inbox or sent."""
        konto = self._verbindung()
        lang = _lange_kennung(self._bereich(), kennung)
        try:
            return konto.inbox.get(id=lang)
        except Exception:
            try:
                return konto.sent.get(id=lang)
            except Exception as e:
                raise Fehler(f"{self.name}: Nachricht nicht gefunden "
                             f"({_kurz(e)}).")

    def _thread(self, a):
        """Every message with the same subject, oldest first.

        By subject and not by EWS conversation: a conversation breaks when
        someone answers from another client or forwards, the subject
        mostly survives. Quoted predecessors are cut from each message --
        otherwise the third answer carries the whole thread again.
        """
        konto = self._verbindung()
        erste = self._nachricht(a.get("kennung"))
        grund = _grundbetreff(getattr(erste, "subject", "") or "")
        posten = [erste]
        if grund:
            felder = ("datetime_received", "subject", "sender", "text_body")
            for ordner in (konto.inbox, konto.sent):
                try:
                    posten += list(ordner.filter(subject__contains=grund)
                                   .only(*felder)
                                   .order_by("-datetime_received")[:30])
                except Exception as e:
                    raise Fehler(f"{self.name}: {_kurz(e)}")
        gesehen, liste = set(), []
        for m in posten:
            schluessel = getattr(m, "id", None) or id(m)
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            if _grundbetreff(getattr(m, "subject", "") or "") != grund:
                continue      # "contains" also finds longer subjects
            liste.append(m)
        liste.sort(key=lambda m: _zeitwert(getattr(m, "datetime_received", None)))

        teile, rest = [], THREAD_TOTAL
        # Newest first into the budget, so a long thread loses its
        # beginning and not its current state.
        for m in reversed(liste):
            text = _ohne_zitat(getattr(m, "text_body", "") or "")
            text = text[:THREAD_MESSAGE] + ("..." if len(text) > THREAD_MESSAGE else "")
            block = (f"--- {_datum(_lokal(getattr(m, 'datetime_received', None)))} | "
                     f"von: {_absender(m)}\n{text or '(kein Text)'}")
            if len(block) > rest and teile:
                teile.append(f"--- (aeltere Nachrichten weggelassen: "
                             f"{len(liste) - len(teile)})")
                break
            teile.append(block[:rest])
            rest -= len(block)
        teile.reverse()
        return (f"Verlauf '{grund or '(ohne Betreff)'}': {len(liste)} "
                f"Nachricht(en), aelteste zuerst.\n" + "\n".join(teile))

    # --- KALENDER ---

    def _events(self, a):
        from exchangelib import EWSDateTime

        konto = self._verbindung()
        tz = _zeitzone(konto)
        tag = _tag(a.get("from")) or _heute(tz)
        tage = max(1, min(int(a.get("days") or 7), 92))
        anzahl = max(1, min(int(a.get("count") or 50), 200))
        such = str(a.get("text") or "").strip().lower()
        beginn = EWSDateTime(tag.year, tag.month, tag.day, tzinfo=tz)
        ende = beginn + datetime.timedelta(days=tage)
        try:
            posten = list(
                konto.calendar.view(start=beginn, end=ende, max_items=HOLGRENZE)
                .only("subject", "start", "end", "location", "organizer",
                      "is_all_day", "is_cancelled"))
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")
        posten.sort(key=lambda t: _zeitwert(getattr(t, "start", None)))

        zeilen = []
        for t in posten:
            betreff = (getattr(t, "subject", "") or "").strip()
            ort = (getattr(t, "location", "") or "").strip()
            org = _person(getattr(t, "organizer", None))
            if such and such not in f"{betreff}\n{ort}\n{org}".lower():
                continue
            kurz = remember(self, t.id)
            zeilen.append(
                f"[{kurz}] {_zeitspanne(t, tz)} | {betreff or '(ohne Betreff)'}"
                + (f" | Ort: {ort}" if ort else "")
                + (f" | Organisator: {org}" if org else "")
                + (" | ABGESAGT" if getattr(t, "is_cancelled", False) else ""))
            if len(zeilen) >= anzahl:
                break
        letzter = tag + datetime.timedelta(days=tage - 1)
        spanne = f"{tag:%d.%m.%Y} bis {letzter:%d.%m.%Y}"
        if not zeilen:
            return f"Keine Termine vom {spanne}."
        return (f"{len(zeilen)} Termin(e) vom {spanne}, Zeiten in {tz}:\n"
                + "\n".join(zeilen))

    def _event(self, a):
        konto = self._verbindung()
        lang = _lange_kennung(self._bereich(), a.get("kennung"))
        try:
            t = konto.calendar.get(id=lang)
        except Exception as e:
            raise Fehler(f"{self.name}: Termin nicht gefunden ({_kurz(e)}).")
        tz = _zeitzone(konto)
        teile = [f"Betreff:    {getattr(t, 'subject', '') or '(ohne Betreff)'}",
                 f"Zeit:       {_zeitspanne(t, tz)}"]
        for titel, wert in (("Ort", getattr(t, "location", "")),
                            ("Organisator", _person(getattr(t, "organizer", None)))):
            if wert:
                teile.append(f"{titel + ':':<11} {wert}")
        if getattr(t, "is_cancelled", False):
            teile.append("ABGESAGT")
        for titel, feld in (("Teilnehmer", "required_attendees"),
                            ("Optional", "optional_attendees")):
            leute = [_teilnehmer(x) for x in (getattr(t, feld, None) or [])]
            if leute:
                teile.append(f"{titel + ':':<11} " + "; ".join(leute))
        text = (getattr(t, "text_body", "") or "").strip()
        if text:
            teile += ["", text[:4000]]
        return "\n".join(teile)

    def _anlegen(self, a, einladen):
        """An entry in the own calendar; with einladen, invitations go out."""
        from exchangelib import CalendarItem, EWSDate, EWSDateTime
        from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY, SEND_TO_NONE

        t = _termin_angaben(a, einladen)
        konto = self._verbindung()
        tz = _zeitzone(konto)
        if t["ganztags"]:
            beginn = EWSDate(t["beginn"].year, t["beginn"].month, t["beginn"].day)
            ende = EWSDate(t["ende"].year, t["ende"].month, t["ende"].day)
        else:
            beginn, ende = (EWSDateTime(x.year, x.month, x.day, x.hour, x.minute,
                                        tzinfo=tz) for x in (t["beginn"], t["ende"]))
        try:
            termin = CalendarItem(
                account=konto, folder=konto.calendar, subject=t["betreff"],
                start=beginn, end=ende, is_all_day=t["ganztags"],
                location=t["ort"] or None, body=t["text"] or None,
                required_attendees=t["teilnehmer"] or None,
                optional_attendees=t["optional"] or None)
            termin.save(send_meeting_invitations=(
                SEND_TO_ALL_AND_SAVE_COPY if einladen else SEND_TO_NONE))
        except Exception as e:
            raise Fehler(f"{self.name}: nicht angelegt ({_kurz(e)}).")
        vorschau = _termin_vorschau(t)
        if einladen:
            return f"Einladung verschickt: {vorschau}"
        return f"Im Kalender eingetragen: {vorschau}"

    # --- SENDEN ---
    #
    # Ob ueberhaupt gesendet werden darf, steht NICHT hier. Das
    # entscheidet mcp.braucht_bestaetigung an einer Stelle fuer alle
    # Postfaecher. Hier wird nur ausgefuehrt, was schon entschieden ist.

    def _anhaenge(self, names):
        """The attachment files, read through attachment_source. Raises Fehler."""
        if not names:
            return []
        if self.attachment_source is None:
            raise Fehler("Anhänge sind hier nicht möglich.")
        try:
            return self.attachment_source(names if isinstance(names, list) else [names])
        except ValueError as e:
            raise Fehler(str(e))

    def _senden(self, a):
        from exchangelib import FileAttachment, Mailbox, Message

        konto = self._verbindung()
        an = _liste(a.get("an"))
        if not an:
            raise Fehler("Kein Empfaenger angegeben.")
        # Read before anything is sent: a missing file stops the mail,
        # not the other way round.
        files = self._anhaenge(a.get("anhaenge"))
        try:
            m = Message(
                account=konto,
                subject=str(a.get("betreff") or ""),
                body=str(a.get("body") or ""),
                to_recipients=[Mailbox(email_address=x) for x in an],
                cc_recipients=[Mailbox(email_address=x)
                               for x in _liste(a.get("kopie"))] or None)
            for name, data, _mime in files:
                m.attach(FileAttachment(name=name, content=data))
            m.send_and_save()
        except Exception as e:
            raise Fehler(f"{self.name}: nicht gesendet ({_kurz(e)}).")
        return (f"Gesendet an {', '.join(an)}."
                + (f" Anhänge: {', '.join(n for n, _d, _m in files)}." if files else ""))

    def _antworten(self, a):
        konto = self._verbindung()
        kennung = _lange_kennung(self._bereich(), a.get("kennung"))
        try:
            m = konto.inbox.get(id=kennung)
        except Exception as e:
            raise Fehler(f"{self.name}: Nachricht nicht gefunden "
                         f"({_kurz(e)}).")
        text = str(a.get("body") or "")
        betreff = getattr(m, "subject", "") or ""
        if not betreff.lower().startswith("re:"):
            betreff = "Re: " + betreff
        try:
            if a.get("allen"):
                m.reply_all(subject=betreff, body=text)
            else:
                m.reply(subject=betreff, body=text)
        except Exception as e:
            raise Fehler(f"{self.name}: nicht gesendet ({_kurz(e)}).")
        return f"Antwort an {_absender(m)} gesendet."

    # --- DID IT GO OUT? ---

    def check_sent(self, name, argumente=None):
        """After an error: is the mail in the sent folder, the entry in the
        calendar? True only when it is found; a timeout after the server
        took a mail is no failure, and a second click would send it twice.
        """
        from exchangelib import EWSDateTime, UTC

        a = dict(argumente or {})
        konto = self._verbindung()
        if name in KALENDERWERKZEUGE:
            t = _termin_angaben(a, name == "meeting_request")
            tz = _zeitzone(konto)
            b = t["beginn"]
            beginn = EWSDateTime(b.year, b.month, b.day,
                                 getattr(b, "hour", 0), getattr(b, "minute", 0),
                                 tzinfo=tz)
            posten = konto.calendar.view(
                start=beginn - datetime.timedelta(minutes=1),
                end=beginn + datetime.timedelta(minutes=1)).only("subject")
            return any(" ".join(str(getattr(x, "subject", "") or "").split())
                       == t["betreff"] for x in posten)
        if name not in SENDEWERKZEUGE:
            return False
        if name == "mail_senden":
            betreff = _grundbetreff(str(a.get("betreff") or ""))
            an = {x.lower() for x in _liste(a.get("an"))}
        else:
            original = self._nachricht(a.get("kennung"))
            betreff = _grundbetreff(getattr(original, "subject", "") or "")
            an = set()
        seit = (EWSDateTime.now(tz=UTC)
                - datetime.timedelta(minutes=SENT_LOOKBACK_MINUTES))
        posten = (konto.sent.filter(datetime_created__gte=seit)
                  .only("subject", "to_recipients")[:50])
        for x in posten:
            if _grundbetreff(getattr(x, "subject", "") or "") != betreff:
                continue
            ziele = {y.lower() for y in _adressen(getattr(x, "to_recipients", None))}
            if not an or an & ziele:
                return True
        return False

    # --- NEW MAIL (mail_watch.py) ---

    def new_messages(self, since, limit=20):
        """[(received, sender, subject)] newer than since (aware), newest first."""
        from exchangelib import EWSDateTime

        konto = self._verbindung()
        try:
            posten = list(
                konto.inbox.filter(datetime_received__gt=EWSDateTime.from_datetime(since))
                .only("datetime_received", "subject", "sender")
                .order_by("-datetime_received")[:limit])
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")
        return [(getattr(m, "datetime_received", None), _absender(m),
                 (getattr(m, "subject", "") or "").strip())
                for m in posten]

    # --- TICKETS (tickets.py) ---

    def ticket_messages(self, since, limit=50):
        """Inbox messages received after since (aware), oldest first, as
        dicts: key, ref, when, name, address, subject, text, auto."""
        from exchangelib import EWSDateTime

        konto = self._verbindung()
        try:
            posten = list(
                konto.inbox.filter(datetime_received__gt=EWSDateTime.from_datetime(since))
                .only("datetime_received", "subject", "sender", "text_body",
                      "message_id", "headers")
                .order_by("datetime_received")[:limit])
        except Exception as e:
            raise Fehler(f"{self.name}: {_kurz(e)}")
        out = []
        for m in posten:
            s = getattr(m, "sender", None)
            headers = {str(getattr(h, "name", "")).lower(): str(getattr(h, "value", ""))
                       for h in (getattr(m, "headers", None) or [])}
            address = (getattr(s, "email_address", "") or "") if s else ""
            out.append({
                "key": getattr(m, "message_id", None) or m.id,
                "ref": m.id,
                "when": getattr(m, "datetime_received", None),
                "name": (getattr(s, "name", "") or "") if s else "",
                "address": address,
                "subject": (getattr(m, "subject", "") or "").strip(),
                "text": (getattr(m, "text_body", "") or "").strip(),
                "auto": is_automatic(headers, address, self.adresse()),
            })
        return out

    def ticket_reply(self, ref, subject, body):
        """Answer the sender of an inbox message."""
        konto = self._verbindung()
        try:
            konto.inbox.get(id=ref).reply(subject=subject, body=body)
        except Exception as e:
            raise Fehler(f"{self.name}: nicht gesendet ({_kurz(e)}).")

    def ticket_forward(self, ref, to, subject, body):
        """Forward an inbox message to addresses."""
        from exchangelib import Mailbox

        konto = self._verbindung()
        try:
            konto.inbox.get(id=ref).forward(
                subject=subject, body=body,
                to_recipients=[Mailbox(email_address=x) for x in to])
        except Exception as e:
            raise Fehler(f"{self.name}: nicht weitergeleitet ({_kurz(e)}).")


# Mail that must not get an automatic answer (RFC 3834 and what large
# senders use): answering it starts a loop between two machines.
_NO_REPLY = re.compile(r"^(mailer-daemon|postmaster|no-?reply|do-?not-?reply|"
                       r"bounce[s]?|notifications?)\b", re.I)


def is_automatic(headers, address, own=""):
    """Is a message machine-made (auto reply, list, bounce) or our own?"""
    h = {str(k).lower(): str(v).lower().strip() for k, v in (headers or {}).items()}
    address = str(address or "").lower()
    if own and address == str(own).lower():
        return True
    if h.get("auto-submitted", "no") not in ("", "no"):
        return True
    if h.get("x-auto-response-suppress", "") and any(
            w in h["x-auto-response-suppress"] for w in ("all", "autoreply", "oof")):
        return True
    if h.get("precedence", "") in ("bulk", "junk", "list", "auto_reply"):
        return True
    if "list-id" in h or "list-unsubscribe" in h:
        return True
    return bool(_NO_REPLY.match(address.split("@")[0])) if address else True


# --- KLEINKRAM ---

def _kurz(fehler):
    """Fehlertext ohne Anhang.

    exchangelib legt gelegentlich die gesamte SOAP-Antwort in die
    Meldung. Die gehoert nicht in einen Prompt und erst recht nicht in
    eine Meldung auf dem Bildschirm.
    """
    text = str(fehler).strip().splitlines()
    return f"{type(fehler).__name__}: {(text[0] if text else '')[:200]}"


def _absender(nachricht):
    s = getattr(nachricht, "sender", None)
    if s is None:
        return "(unbekannt)"
    name = getattr(s, "name", "") or ""
    adresse = getattr(s, "email_address", "") or ""
    if name and adresse and name != adresse:
        return f"{name} <{adresse}>"
    return name or adresse or "(unbekannt)"


def _adressen(mailboxen):
    aus = []
    for m in (mailboxen or []):
        aus.append(getattr(m, "email_address", "") or getattr(m, "name", ""))
    return [x for x in aus if x]


def _liste(wert):
    if isinstance(wert, (list, tuple)):
        roh = list(wert)
    else:
        roh = str(wert or "").replace(";", ",").split(",")
    return [str(x).strip() for x in roh if str(x).strip()]


def _datum(wert):
    if wert is None:
        return "-"
    try:
        return wert.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(wert)[:16]


_WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _zeitzone(konto=None):
    """The installation's time zone (TIMEZONE, local_time.py).

    Not the container's: that is UTC, and appointments were an hour off.
    """
    from exchangelib import EWSTimeZone
    try:
        return EWSTimeZone(local_time.zone_name())
    except Exception:
        pass
    try:
        tz = konto.default_timezone if konto is not None else None
        if tz is not None:
            return tz
    except Exception:
        pass
    return EWSTimeZone.localzone()


def _lokal(wert):
    """A received time in the installation's zone, for the model."""
    if wert is None or not hasattr(wert, "astimezone"):
        return wert
    try:
        return wert.astimezone(local_time.zone())
    except Exception:
        return wert


def _heute(tz):
    from exchangelib import EWSDateTime
    jetzt = EWSDateTime.now(tz=tz)
    return datetime.date(jetzt.year, jetzt.month, jetzt.day)


def _tag(wert):
    """'2026-11-04' or '04.11.2026' as a date; empty gives None."""
    wert = str(wert or "").strip()
    if not wert:
        return None
    for form in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.datetime.strptime(wert, form).date()
        except ValueError:
            pass
    raise Fehler(f"'{wert}' ist kein Datum. Erwartet: JJJJ-MM-TT.")


def _zeitpunkt(wert, feld):
    """'2026-11-11 14:00' (also with T, or 11.11.2026 14:00) -> naive
    datetime; a date alone -> date. In the mailbox's local time."""
    wert = " ".join(str(wert or "").replace("T", " ").split())
    for form in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.datetime.strptime(wert, form)
        except ValueError:
            pass
    tag = _tag(wert) if wert else None
    if tag is None:
        raise Fehler(f"'{feld}' fehlt. Erwartet: JJJJ-MM-TT HH:MM.")
    return tag


def _termin_angaben(a, einladen):
    """The checked fields of calendar_add / meeting_request. Raises Fehler.

    ende is exclusive: for an all-day entry the day after the last one,
    the way Exchange stores it.
    """
    betreff = " ".join(str(a.get("subject") or "").split())
    if not betreff:
        raise Fehler("Kein Betreff angegeben.")
    beginn = _zeitpunkt(a.get("start"), "start")
    ganztags = bool(a.get("all_day")) or not isinstance(beginn, datetime.datetime)
    if ganztags:
        beginn = datetime.date(beginn.year, beginn.month, beginn.day)
        letzter = beginn
        if str(a.get("end") or "").strip():
            e = _zeitpunkt(a.get("end"), "end")
            letzter = datetime.date(e.year, e.month, e.day)
        if letzter < beginn:
            raise Fehler("Der letzte Tag liegt vor dem ersten.")
        ende = letzter + datetime.timedelta(days=1)
    else:
        roh = str(a.get("end") or "").strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", roh):
            h, m = (int(x) for x in roh.split(":"))
            try:
                ende = beginn.replace(hour=h, minute=m)
            except ValueError:
                raise Fehler(f"'{roh}' ist keine Uhrzeit.")
        elif roh:
            ende = _zeitpunkt(roh, "end")
            if not isinstance(ende, datetime.datetime):
                raise Fehler("'end' braucht eine Uhrzeit, JJJJ-MM-TT HH:MM.")
        else:
            try:
                minuten = int(a.get("duration") or 60)
            except (TypeError, ValueError):
                raise Fehler("'duration' ist keine Zahl von Minuten.")
            if not 5 <= minuten <= 14 * 24 * 60:
                raise Fehler("'duration' zwischen 5 Minuten und 14 Tagen.")
            ende = beginn + datetime.timedelta(minutes=minuten)
        if ende <= beginn:
            raise Fehler("Das Ende liegt nicht nach dem Beginn.")
    heute = local_time.today()
    tag = beginn.date() if isinstance(beginn, datetime.datetime) else beginn
    if not (heute - datetime.timedelta(days=366) <= tag
            <= heute + datetime.timedelta(days=5 * 366)):
        raise Fehler(f"'{beginn}' liegt nicht in einem sinnvollen Zeitraum.")

    teilnehmer = _liste(a.get("attendees"))
    optional = _liste(a.get("optional_attendees"))
    falsch = [x for x in teilnehmer + optional
              if not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", x)]
    if falsch:
        raise Fehler("Keine Mailadresse: " + ", ".join(falsch)
                     + ". Adressen nicht raten -- beim Nutzer nachfragen.")
    if einladen and not teilnehmer:
        raise Fehler("Eine Besprechungsanfrage braucht Teilnehmer (attendees).")
    if not einladen and (teilnehmer or optional):
        raise Fehler("calendar_add laedt niemanden ein. Fuer Teilnehmer "
                     "meeting_request verwenden.")
    return {"betreff": betreff, "beginn": beginn, "ende": ende,
            "ganztags": ganztags,
            "ort": " ".join(str(a.get("location") or "").split()),
            "text": str(a.get("body") or "").strip(),
            "teilnehmer": teilnehmer, "optional": optional}


def _termin_vorschau(t):
    """'Baubesprechung | Di 11.11.2026 14:00-15:30 | Ort: ... | an: ...'"""
    b, e = t["beginn"], t["ende"]
    if t["ganztags"]:
        letzter = e - datetime.timedelta(days=1)
        zeit = f"{_WOCHENTAGE[b.weekday()]} {b:%d.%m.%Y} ganztaegig"
        if letzter > b:
            zeit += f" bis {_WOCHENTAGE[letzter.weekday()]} {letzter:%d.%m.%Y}"
    elif e.date() == b.date():
        zeit = f"{_WOCHENTAGE[b.weekday()]} {b:%d.%m.%Y %H:%M}-{e:%H:%M}"
    else:
        zeit = (f"{_WOCHENTAGE[b.weekday()]} {b:%d.%m.%Y %H:%M} bis "
                f"{_WOCHENTAGE[e.weekday()]} {e:%d.%m.%Y %H:%M}")
    teile = [t["betreff"], zeit]
    if t["ort"]:
        teile.append(f"Ort: {t['ort']}")
    if t["teilnehmer"]:
        teile.append("an: " + ", ".join(t["teilnehmer"]))
    if t["optional"]:
        teile.append("optional: " + ", ".join(t["optional"]))
    return " | ".join(teile)


def _zeitwert(wert):
    """Sort key for dates and times with and without zone; None last."""
    if wert is None:
        return (1, 0.0)
    if hasattr(wert, "timestamp") and hasattr(wert, "hour"):
        try:
            return (0, wert.timestamp())
        except Exception:
            pass
    try:
        return (0, datetime.datetime(wert.year, wert.month, wert.day,
                                     tzinfo=datetime.timezone.utc).timestamp())
    except Exception:
        return (1, 0.0)


def _zeitspanne(termin, tz):
    """'Di 04.11.2026 09:00-10:30', 'Mi 05.11.2026 ganztaegig', ..."""
    beginn = getattr(termin, "start", None)
    ende = getattr(termin, "end", None)
    if beginn is None:
        return "-"
    ganztags = bool(getattr(termin, "is_all_day", False)) or not hasattr(beginn, "hour")
    if hasattr(beginn, "hour"):
        try:
            beginn = beginn.astimezone(tz)
            ende = ende.astimezone(tz) if ende is not None else None
        except Exception:
            pass
    if ganztags:
        erster = datetime.date(beginn.year, beginn.month, beginn.day)
        # Exchange gives the end of an all-day entry as the next midnight.
        letzter = erster
        if ende is not None:
            letzter = (datetime.date(ende.year, ende.month, ende.day)
                       - datetime.timedelta(days=1))
        text = f"{_WOCHENTAGE[erster.weekday()]} {erster:%d.%m.%Y} ganztaegig"
        if letzter > erster:
            text += f" bis {_WOCHENTAGE[letzter.weekday()]} {letzter:%d.%m.%Y}"
        return text
    text = f"{_WOCHENTAGE[beginn.weekday()]} {beginn:%d.%m.%Y %H:%M}"
    if ende is None:
        return text
    if (ende.year, ende.month, ende.day) == (beginn.year, beginn.month, beginn.day):
        return f"{text}-{ende:%H:%M}"
    return f"{text} bis {_WOCHENTAGE[ende.weekday()]} {ende:%d.%m.%Y %H:%M}"


def _person(mailbox):
    if mailbox is None:
        return ""
    name = getattr(mailbox, "name", "") or ""
    adresse = getattr(mailbox, "email_address", "") or ""
    if name and adresse and name != adresse:
        return f"{name} <{adresse}>"
    return name or adresse


# Exchange's answers to an invitation, as they show up in a list.
_ANTWORTEN = {"Accept": "zugesagt", "Decline": "abgesagt",
              "Tentative": "vorlaeufig", "NoResponseReceived": "keine Antwort",
              "Organizer": "Organisator", "Unknown": ""}


def _teilnehmer(attendee):
    wer = _person(getattr(attendee, "mailbox", None)) or "(unbekannt)"
    antwort = _ANTWORTEN.get(str(getattr(attendee, "response_type", "") or ""), "")
    return f"{wer} ({antwort})" if antwort else wer


_PRAEFIX = re.compile(r"^\s*((re|aw|wg|fw|fwd|antw|tr|sv|vs)\s*(\[\d+\])?\s*:\s*)+",
                      re.I)


def _grundbetreff(betreff):
    """The subject without Re:/AW:/WG:/Fwd: in front, as many as there are."""
    return _PRAEFIX.sub("", str(betreff or "")).strip()


_ZITAT_BEGINN = re.compile(
    r"^\s*(-{2,}\s*(original message|urspr(ü|ue)ngliche nachricht|"
    r"original-nachricht)|_{8,}\s*$)", re.I)
_ZITAT_KOPF = re.compile(r"^\s*\**(von|from)\s*:\**\s*\S", re.I)
_ZITAT_FOLGE = re.compile(r"^\s*\**(gesendet|sent|datum|date|an|to|betreff|subject)"
                          r"\s*:", re.I)
_ZITAT_SCHRIEB = re.compile(r"^\s*(am|on)\s.+\s(schrieb|wrote)\b.*:\s*$", re.I)


def _ohne_zitat(text):
    """A mail without the messages it quotes.

    Cut at the first line that starts a quote the way mail programs
    write it: "-----Original Message-----", a block of "Von:" followed by
    "Gesendet:"/"An:", or "Am ... schrieb ...:". Lines starting with ">"
    go as well.
    """
    zeilen = str(text or "").replace("\r\n", "\n").split("\n")
    aus = []
    for i, z in enumerate(zeilen):
        if (_ZITAT_BEGINN.match(z) or _ZITAT_SCHRIEB.match(z)
                or (_ZITAT_KOPF.match(z)
                    and any(_ZITAT_FOLGE.match(x) for x in zeilen[i + 1:i + 4]))):
            break
        if z.lstrip().startswith(">"):
            continue
        aus.append(z)
    return "\n".join(aus).strip()


def _zusammen(text, grenze):
    """Ein Textanfang in einer Zeile.

    Zeilenumbrueche raus: die Uebersicht ist zeilenweise aufgebaut, und
    eine Mail mit Absaetzen wuerde sie auseinanderreissen.
    """
    eins = " ".join(str(text or "").split())
    return eins[:grenze] + ("..." if len(eins) > grenze else "")


# --- PROBE ---

def main():
    """python postfach.py <name>

    Meldet sich an einem eingerichteten Exchange-Postfach an und zeigt,
    was es sieht. Gebraucht beim Einrichten: hier faellt eine falsche
    Serveradresse auf, bevor sie im Chat als 'das Modell weiss nichts'
    erscheint.

    Anmeldedaten werden ABGEFRAGT und nicht aus der Umgebung gelesen.
    Ueber die Befehlszeile stuenden sie in der Prozessliste und in der
    Verlaufsdatei der Shell; als Umgebungsvariable gehoerten sie in
    .env.example, und von dort wandert ein Passwort irgendwann in eine
    .env und damit in den Container.
    """
    import getpass
    import sys
    import mcp

    paths.bootstrap()
    name = next((a for a in sys.argv[1:] if not a.startswith("-")), "")
    konf = mcp.lies_konfiguration()
    if name not in konf:
        print("Eingerichtet sind: " + (", ".join(sorted(konf)) or "keine"))
        print("Aufruf: python postfach.py <name>")
        return 2

    benutzer = input("Mailadresse: ").strip()
    passwort = getpass.getpass("Passwort: ")
    if not benutzer or not passwort:
        print("Ohne Anmeldedaten geht nichts.")
        return 2

    p = Postfach(name, konf[name], mcp.kopf_fuer(name, benutzer, passwort))
    try:
        wz = p.werkzeuge()
        print(f"Angemeldet. {len(wz)} Werkzeuge:")
        for w in wz:
            marke = ("[SENDET]" if w["name"] in SENDEWERKZEUGE else "[liest] ")
            print(f"  {marke} {w['name']}")
        print()
        print(p.rufe("mails_lesen", {"anzahl": 5}))
    except Exception as e:
        print(f"[!] {e}")
        return 1
    finally:
        p.schliesse()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
