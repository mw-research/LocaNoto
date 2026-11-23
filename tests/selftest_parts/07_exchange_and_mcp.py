"""Self-test, part 07: Exchange: address, calendar, threads, workspace notes; Exchange as a tool server; notices.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- EWS ADDRESS FROM WHAT PEOPLE PASTE ---
import postfach as _pfa
for _ein, _aus in (
        ("owa.test", "https://owa.test/EWS/Exchange.asmx"),
        ("https://owa.test/owa/auth/logon.aspx", "https://owa.test/EWS/Exchange.asmx"),
        ("https://owa.test/owa/auth/logon.aspx?url=https%3a%2f%2fowa.test%2fowa%2f&reason=0",
         "https://owa.test/EWS/Exchange.asmx"),
        ("owa.test/owa/", "https://owa.test/EWS/Exchange.asmx"),
        ("https://owa.test:8443/ews/exchange.asmx", "https://owa.test:8443/ews/exchange.asmx"),
        # stored by the old version: repaired when connecting
        ("https://owa.test/owa/auth/logon.aspx/EWS/Exchange.asmx",
         "https://owa.test/EWS/Exchange.asmx"),
        ("", "")):
    pruef(f"EWS-Adresse aus '{_ein}'", _pfa.ews_adresse(_ein) == _aus,
          _pfa.ews_adresse(_ein))

# --- CALENDAR AND THREADS OF AN EXCHANGE MAILBOX ---
#
# Against stand-ins for exchangelib and the account: the shape of the
# answers, time zones, all-day entries, the search, quotes cut from a
# thread. Whether a real Exchange answers the calls the same way needs a
# real mailbox.
import base64 as _b64c
import datetime
import mcp as _mcp_w
import types as _tyc
import zoneinfo as _zic
import postfach as _pfc

_tz_c = _zic.ZoneInfo("Europe/Berlin")


class _EwsDt(datetime.datetime):
    pass


class _EwsDate(datetime.date):
    pass


_angelegt = []


class _Kalendereintrag:
    def __init__(self, **felder):
        self.felder = felder

    def save(self, send_meeting_invitations=None):
        self.id = f"NEU{len(_angelegt)}"
        _angelegt.append((self.felder, send_meeting_invitations))


_echtes_ews = sys.modules.get("exchangelib")
_echtes_ews_items = sys.modules.get("exchangelib.items")
sys.modules["exchangelib"] = _tyc.SimpleNamespace(
    EWSDateTime=_EwsDt, EWSDate=_EwsDate, UTC=datetime.timezone.utc,
    CalendarItem=_Kalendereintrag,
    EWSTimeZone=_tyc.SimpleNamespace(localzone=lambda: _tz_c))
sys.modules["exchangelib.items"] = _tyc.SimpleNamespace(
    SEND_TO_ALL_AND_SAVE_COPY="SendToAllAndSaveCopy", SEND_TO_NONE="SendToNone",
    SEND_TO_CHANGED_AND_SAVE_COPY="SendToChangedAndSaveCopy")


def _ns(**k):
    return _tyc.SimpleNamespace(**k)


class _Abfrage(list):
    def only(self, *_f):
        return self

    def order_by(self, *_f):
        return self


class _Ordner:
    def __init__(self, posten):
        self.posten = posten

    def get(self, id):
        for x in self.posten:
            if x.id == id:
                return x
        raise KeyError(id)

    def filter(self, subject__contains=""):
        return _Abfrage(x for x in self.posten if subject__contains in x.subject)

    def view(self, start, end, max_items=None):
        return _Abfrage(t for t in self.posten if start <= _pfc_beginn(t) < end)


def _pfc_beginn(t):
    b = t.start
    if not hasattr(b, "hour"):
        return datetime.datetime(b.year, b.month, b.day, tzinfo=_tz_c)
    return b


_heute_c = datetime.datetime.now(_tz_c).date()
_morgen_c = _heute_c + datetime.timedelta(days=1)
_utc = datetime.timezone.utc
_m9 = datetime.datetime(_morgen_c.year, _morgen_c.month, _morgen_c.day, 9, 0,
                        tzinfo=_tz_c).astimezone(_utc)
_termine = [
    _ns(id="T1", subject="Baubesprechung Halle 3", start=_m9,
        end=_m9 + datetime.timedelta(minutes=90), location="Raum 2.14",
        organizer=_ns(name="Huber", email_address="huber@test.de"),
        is_all_day=False, is_cancelled=False, text_body="Tagesordnung: Statik",
        required_attendees=[_ns(mailbox=_ns(name="Anna", email_address="anna@test.de"),
                                response_type="Accept")],
        optional_attendees=[]),
    _ns(id="T2", subject="Messe", start=_morgen_c + datetime.timedelta(days=1),
        end=_morgen_c + datetime.timedelta(days=3), location="", organizer=None,
        is_all_day=True, is_cancelled=False),
    _ns(id="T3", subject="Jour fixe", start=_m9 + datetime.timedelta(hours=5),
        end=_m9 + datetime.timedelta(hours=6), location="", organizer=None,
        is_all_day=False, is_cancelled=True),
    _ns(id="T4", subject="Zu weit weg", start=_m9 + datetime.timedelta(days=40),
        end=_m9 + datetime.timedelta(days=40, hours=1), location="",
        organizer=None, is_all_day=False, is_cancelled=False),
]
_t0 = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=_utc)
_mails = [
    _ns(id="M1", subject="Angebot Meier", datetime_received=_t0,
        sender=_ns(name="Meier", email_address="meier@test.de"),
        text_body="Anbei das Angebot ueber 12.400 EUR."),
    _ns(id="M3", subject="AW: Angebot Meier", datetime_received=_t0
        + datetime.timedelta(days=2),
        sender=_ns(name="Meier", email_address="meier@test.de"),
        text_body="Einverstanden, Lieferung KW 47.\n\nVon: Anna\nGesendet: Mo\n"
                  "An: Meier\nBetreff: Angebot Meier\n\nGEHEIMER ALTTEXT"),
    _ns(id="M9", subject="Angebot Meier Nachtrag", datetime_received=_t0,
        sender=_ns(name="X", email_address="x@test.de"), text_body="anders"),
]
_gesendet = [
    _ns(id="M2", subject="RE: Angebot Meier", datetime_received=_t0
        + datetime.timedelta(days=1),
        sender=_ns(name="Anna", email_address="anna@test.de"),
        text_body="Bitte 3 % Skonto.\n> Anbei das Angebot\n"),
]
_pfk = _pfc.Postfach("box", {"postfach": "anna@test.de"}, {
    "Authorization": "Basic " + _b64c.b64encode(b"anna@test.de:pw").decode()})
_pfk._konto = _ns(default_timezone=_tz_c, calendar=_Ordner(_termine),
                  inbox=_Ordner(_mails), sent=_Ordner(_gesendet),
                  protocol=_ns(close=lambda: None))
_pfk._konto.inbox.total_count = 3

_wz_c = {w["name"]: w for w in _pfk.werkzeuge()}
pruef("Kalender und Verlauf stehen in der Werkzeugliste, lesend",
      {"calendar_events", "calendar_event", "mail_thread"} <= set(_wz_c)
      and not set(_wz_c) & {"calendar_events", "calendar_event", "mail_thread"}
      & set(_pfc.SENDEWERKZEUGE))
pruef("das Modell erfaehrt das heutige Datum",
      f"{_heute_c:%Y-%m-%d}" in _wz_c["calendar_events"]["beschreibung"])
_ev = _pfk.rufe("calendar_events", {})
pruef("Termine der naechsten 7 Tage in Ortszeit",
      "09:00-10:30 | Baubesprechung Halle 3 | Ort: Raum 2.14" in _ev
      and "Zu weit weg" not in _ev, _ev)
pruef("ganztaegige Termine ueber mehrere Tage",
      "ganztaegig bis" in _ev and "Messe" in _ev, _ev)
pruef("abgesagte Termine sind markiert", "Jour fixe | ABGESAGT" in _ev, _ev)
pruef("Suche im Kalender",
      _pfk.rufe("calendar_events", {"text": "huber"}).count("\n[") == 1)
_ev40 = _pfk.rufe("calendar_events", {"from": str(_heute_c), "days": 45})
pruef("Zeitraum frei waehlbar", "Zu weit weg" in _ev40, _ev40)
_kz = _ev.split("]", 1)[0].split("[", 1)[1]
_det = _pfk.rufe("calendar_event", {"kennung": _kz})
pruef("Termin im Einzelnen mit Zusage",
      "Anna <anna@test.de> (zugesagt)" in _det and "Statik" in _det, _det)
try:
    _pfk.rufe("calendar_events", {"from": "naechsten Dienstag"})
    pruef("ein Nicht-Datum wird abgewiesen", False)
except _pfc.Fehler as _e:
    pruef("ein Nicht-Datum wird abgewiesen", "JJJJ-MM-TT" in str(_e))

_km = _pfc._merke_kennung(_pfk._bereich(), "M1")
_vl = _pfk.rufe("mail_thread", {"kennung": _km})
pruef("Verlauf: Posteingang und Gesendet, aelteste zuerst",
      _vl.index("12.400") < _vl.index("Skonto") < _vl.index("KW 47"), _vl)
pruef("Verlauf ohne zitierte Vorgaenger und ohne fremde Betreffe",
      "GEHEIMER ALTTEXT" not in _vl and "> Anbei" not in _vl
      and "anders" not in _vl and "3 Nachricht(en)" in _vl, _vl)
pruef("Betreff ohne Re/AW/WG",
      _pfc._grundbetreff("AW: WG: RE[2]: Angebot Meier") == "Angebot Meier")
pruef("Zitat nach 'Am ... schrieb ...:' faellt weg",
      _pfc._ohne_zitat("Danke!\nAm 3.11. schrieb Meier:\nalt") == "Danke!")
# --- creating entries and invitations ---
_tag_c = (_heute_c + datetime.timedelta(days=8))
_tag_s = f"{_tag_c:%Y-%m-%d}"
_vs = _pfk.pruefe_entwurf("meeting_request", {
    "subject": "Statik Halle 3", "start": f"{_tag_s} 14:00", "end": "15:30",
    "location": "Raum 2.14", "attendees": "huber@test.de, meier@test.de"})
pruef("eine Besprechungsanfrage zeigt Wochentag, Zeit, Ort und Teilnehmer",
      f"{_pfc._WOCHENTAGE[_tag_c.weekday()]} {_tag_c:%d.%m.%Y} 14:00-15:30" in _vs
      and "Raum 2.14" in _vs and "huber@test.de, meier@test.de" in _vs, _vs)
for _arg_f, _grund_f in (
        ({"subject": "x", "start": "naechsten Dienstag 14 Uhr",
          "attendees": "a@test.de"}, "ein Datum in Worten"),
        ({"subject": "x", "start": f"{_tag_s} 14:00", "end": "13:00",
          "attendees": "a@test.de"}, "ein Ende vor dem Beginn"),
        ({"subject": "x", "start": f"{_tag_s} 14:00",
          "attendees": "Herr Huber"}, "ein Name statt einer Adresse"),
        ({"subject": "x", "start": f"{_tag_s} 14:00"}, "eine Anfrage ohne Teilnehmer"),
        ({"subject": "x", "start": "2041-01-01 10:00",
          "attendees": "a@test.de"}, "ein Datum in fernster Zukunft")):
    try:
        _pfk.pruefe_entwurf("meeting_request", _arg_f)
        pruef(f"abgewiesen: {_grund_f}", False)
    except _pfc.Fehler:
        pruef(f"abgewiesen: {_grund_f}", True)
try:
    _pfk.pruefe_entwurf("calendar_add", {"subject": "x", "start": f"{_tag_s} 9:00",
                                         "attendees": "a@test.de"})
    pruef("ein eigener Termin laedt niemanden ein", False)
except _pfc.Fehler as _e:
    pruef("ein eigener Termin laedt niemanden ein", "meeting_request" in str(_e))
pruef("Lesewerkzeuge brauchen keine Vorpruefung",
      _pfk.pruefe_entwurf("mails_lesen", {}) is None)

_erg_k = _pfk.rufe("calendar_add", {"subject": "Fokuszeit", "start": f"{_tag_s} 08:00",
                                    "duration": 90})
_f_k, _send_k = _angelegt[-1]
pruef("ein eigener Termin wird eingetragen, ohne Einladung",
      _send_k == "SendToNone" and not _f_k["required_attendees"]
      and _f_k["start"].tzinfo is _tz_c
      and (_f_k["end"] - _f_k["start"]) == datetime.timedelta(minutes=90)
      and "eingetragen" in _erg_k, (_f_k, _send_k))
_pfk.rufe("meeting_request", {"subject": "Statik", "start": f"{_tag_s} 14:00",
                              "end": "15:00", "attendees": "huber@test.de",
                              "optional_attendees": "meier@test.de",
                              "body": "Tagesordnung"})
_f_m, _send_m = _angelegt[-1]
pruef("eine Besprechungsanfrage verschickt Einladungen an alle",
      _send_m == "SendToAllAndSaveCopy"
      and _f_m["required_attendees"] == ["huber@test.de"]
      and _f_m["optional_attendees"] == ["meier@test.de"]
      and _f_m["body"] == "Tagesordnung", (_f_m, _send_m))
_pfk.rufe("calendar_add", {"subject": "Messe", "start": _tag_s,
                           "end": f"{_tag_c + datetime.timedelta(days=2):%Y-%m-%d}"})
_f_g, _ = _angelegt[-1]
pruef("ganztaegig ueber drei Tage: Ende ist der Tag danach",
      _f_g["is_all_day"] and isinstance(_f_g["start"], _EwsDate)
      and (_f_g["end"] - _f_g["start"]).days == 3, _f_g)
pruef("eine Einladung nennt ihre Kennung, fuer spaetere Aenderungen",
      "Kennung [m" in _pfk.rufe("meeting_request", {
          "subject": "Kennung", "start": f"{_tag_s} 16:00",
          "attendees": "huber@test.de"}))

# --- changing and cancelling an appointment ---


def _wirft(aufruf):
    """True if the call is refused with postfach.Fehler."""
    try:
        aufruf()
    except _pfc.Fehler:
        return True
    return False


class _Termin(_tyc.SimpleNamespace):
    def save(self, update_fields=None, send_meeting_invitations=None):
        self.saved = (list(update_fields or []), send_meeting_invitations)
        self.required_attendees = [
            _ns(mailbox=_ns(name="", email_address=x), response_type="")
            if isinstance(x, str) else x for x in (self.required_attendees or [])]

    def cancel(self, **k):
        self.cancelled_with = k
        self.is_cancelled = True

    def decline(self, **k):
        self.declined_with = k
        self.my_response_type = "Decline"

    def accept(self, **k):
        self.accepted_with = k
        self.my_response_type = "Accept"

    def tentatively_accept(self, **k):
        self.tentative_with = k
        self.my_response_type = "Tentative"

    def move_to_trash(self, **k):
        self.trashed_with = k


def _person_c(name, adresse, antwort="NoResponseReceived"):
    return _ns(mailbox=_ns(name=name, email_address=adresse), response_type=antwort)


_b10 = datetime.datetime(_tag_c.year, _tag_c.month, _tag_c.day, 11, 0, tzinfo=_tz_c)
_t_rod = _Termin(id="T10", subject="Faschingsanfang", start=_b10,
                 end=_b10 + datetime.timedelta(hours=1), location="Büro 1.1.34",
                 organizer=_ns(name="Anna", email_address="anna@test.de"),
                 my_response_type="Organizer", is_all_day=False, is_cancelled=False,
                 required_attendees=[_person_c("Rodolfo", "rodolfo@test.de", "Accept")],
                 optional_attendees=[])
_t_vla = _Termin(id="T11", subject="Faschingsanfang", start=_b10,
                 end=_b10 + datetime.timedelta(hours=1), location="Büro 1.1.34",
                 organizer=_ns(name="Anna", email_address="anna@test.de"),
                 my_response_type="Organizer", is_all_day=False, is_cancelled=False,
                 required_attendees=[_person_c("Vlad", "vlad@test.de")],
                 optional_attendees=[])
_t_fremd = _Termin(id="T12", subject="Jour fixe Huber", start=_b10,
                   end=_b10 + datetime.timedelta(hours=1), location="",
                   organizer=_ns(name="Huber", email_address="huber@test.de"),
                   my_response_type="Accept", is_all_day=False, is_cancelled=False,
                   required_attendees=[_person_c("Anna", "anna@test.de", "Accept")],
                   optional_attendees=[])
_t_eigen = _Termin(id="T13", subject="Fokuszeit", start=_b10,
                   end=_b10 + datetime.timedelta(hours=2), location="",
                   organizer=None, my_response_type="Organizer", is_all_day=False,
                   is_cancelled=False, required_attendees=[], optional_attendees=[])
_termine.extend([_t_rod, _t_vla, _t_fremd, _t_eigen])
_k10, _k11, _k12, _k13 = (_pfc.remember(_pfk, x) for x in ("T10", "T11", "T12", "T13"))

_vu = _pfk.pruefe_entwurf("calendar_update", {"kennung": _k10,
                                              "add_attendees": "vlad@test.de"})
pruef("Termin aendern: die Vorschau zeigt alle Teilnehmer und wer neu ist",
      "an: rodolfo@test.de, vlad@test.de" in _vu and "neu dabei: vlad@test.de" in _vu
      and "11:00-12:00" in _vu and "bisher" not in _vu, _vu)
_eu = _pfk.rufe("calendar_update", {"kennung": _k10, "add_attendees": "vlad@test.de"})
pruef("nur Teilnehmer dazu: Einladung nur an die Neuen, die Alten behalten ihre Zusage",
      _t_rod.saved == (["required_attendees", "optional_attendees"],
                       "SendToChangedAndSaveCopy")
      and _t_rod.required_attendees[0].response_type == "Accept"
      and _pfc._emails(_t_rod.required_attendees) == ["rodolfo@test.de", "vlad@test.de"]
      and "geaendert" in _eu, (_t_rod.saved, _eu))
pruef("danach als erledigt erkennbar",
      _pfk.check_sent("calendar_update", {"kennung": _k10, "add_attendees": "vlad@test.de"}))
_vc = _pfk.pruefe_entwurf("calendar_cancel", {"kennung": _k11})
pruef("Termin absagen: die Vorschau nennt, wer die Absage bekommt",
      "Absage an: vlad@test.de" in _vc and "Faschingsanfang" in _vc, _vc)
_pfk.rufe("calendar_cancel", {"kennung": _k11, "body": "Zusammengelegt."})
pruef("der Organisator sagt ab: Absage an alle, mit Text",
      _t_vla.cancelled_with == {"new_body": "Zusammengelegt."}
      and _pfk.check_sent("calendar_cancel", {"kennung": _k11}), _t_vla)
pruef("ein abgesagter Termin wird nicht noch einmal abgesagt",
      _wirft(lambda: _pfk.pruefe_entwurf(
          "calendar_cancel", {"kennung": _k11})))
_pfk.rufe("calendar_update", {"kennung": _k10, "start": f"{_tag_s} 14:00"})
pruef("neue Zeit: Dauer bleibt, Aktualisierung an alle",
      _t_rod.saved[1] == "SendToAllAndSaveCopy" and "start" in _t_rod.saved[0]
      and _t_rod.start.hour == 14 and _t_rod.end - _t_rod.start == datetime.timedelta(hours=1),
      (_t_rod.saved, _t_rod.start, _t_rod.end))
pruef("einen fremden Termin aendert nur der Organisator",
      _wirft(lambda: _pfk.pruefe_entwurf("calendar_update", {"kennung": _k12,
                                                             "location": "Raum 1"})))
pruef("einen fremden Termin absagen heisst: dem Organisator absagen",
      "Absage an den Organisator Huber" in _pfk.pruefe_entwurf(
          "calendar_cancel", {"kennung": _k12}))
_pfk.rufe("calendar_cancel", {"kennung": _k13})
pruef("ein eigener Eintrag ohne Teilnehmer geht ohne Nachricht in den Papierkorb",
      getattr(_t_eigen, "trashed_with", None) == {"send_meeting_cancellations": "SendToNone"})
pruef("eine Aenderung ohne Aenderung wird abgewiesen",
      _wirft(lambda: _pfk.pruefe_entwurf("calendar_update", {"kennung": _k10})))
pruef("wer nicht dabei ist, kann nicht entfernt werden",
      _wirft(lambda: _pfk.pruefe_entwurf("calendar_update", {
          "kennung": _k10, "remove_attendees": "niemand@test.de"})))

# --- answering an invitation ---
_t_einl = _Termin(id="T14", subject="Projekttreffen", start=_b10 + datetime.timedelta(days=1),
                  end=_b10 + datetime.timedelta(days=1, hours=1), location="Raum 3",
                  organizer=_ns(name="Huber", email_address="huber@test.de"),
                  my_response_type="NoResponseReceived", is_all_day=False,
                  is_cancelled=False, required_attendees=[_person_c("Anna", "anna@test.de")],
                  optional_attendees=[])
_termine.append(_t_einl)
_k14 = _pfc.remember(_pfk, "T14")
_ev_o = _pfk.rufe("calendar_events", {"from": str(_tag_c), "days": 3})
pruef("eine unbeantwortete Einladung steht als 'Antwort offen' im Kalender",
      "Projekttreffen | Ort: Raum 3 | Organisator: Huber <huber@test.de> | Antwort offen"
      in _ev_o, _ev_o)
_vr = _pfk.pruefe_entwurf("calendar_respond", {"kennung": _k14, "response": "accept"})
pruef("Zusagen: die Vorschau nennt Termin und Organisator",
      _vr.startswith("Zusagen: Projekttreffen") and "Antwort an Huber" in _vr, _vr)
_pfk.rufe("calendar_respond", {"kennung": _k14, "response": "tentative",
                               "body": "Komme evtl. später."})
pruef("vorlaeufig zusagen mit Text, danach als erledigt erkennbar",
      _t_einl.tentative_with == {"body": "Komme evtl. später."}
      and _pfk.check_sent("calendar_respond", {"kennung": _k14, "response": "tentative"})
      and not _pfk.check_sent("calendar_respond", {"kennung": _k14, "response": "accept"}))
_pfk.rufe("calendar_respond", {"kennung": _k14, "response": "accept"})
pruef("zusagen", _t_einl.accepted_with == {} and _t_einl.my_response_type == "Accept")
pruef("auf die eigene Einladung antwortet man nicht",
      _wirft(lambda: _pfk.pruefe_entwurf("calendar_respond",
                                         {"kennung": _k10, "response": "accept"})))
pruef("nur accept, tentative oder decline",
      _wirft(lambda: _pfk.pruefe_entwurf("calendar_respond",
                                         {"kennung": _k14, "response": "vielleicht"})))

# --- address book ---
_gal = [("Vladyslav Borysenko", "vladyslav.borysenko@thws.de", "IDEE", "Wiss. Mitarbeiter",
         "+49 9721 940-1"),
        ("Rodolfo Cacacho", "rodolfo.cacacho@thws.de", "IDEE", "", ""),
        ("Vlad Tester", "vlad.tester@thws.de", "", "", "")]


def _resolve(names, return_full_contact_data=False, search_scope=None):
    q = names[0].lower()
    hits = [(_ns(name=n, email_address=m),
             _ns(display_name=n, department=d, job_title=t,
                 phone_numbers=[_ns(phone_number=ph)] if ph else []))
            for n, m, d, t, ph in _gal if q in n.lower()]
    if not hits:
        raise RuntimeError("ErrorNameResolutionNoResults")
    return hits


_pfk._konto.protocol.resolve_names = _resolve
_al = _pfk.rufe("address_lookup", {"query": "Borysenko"})
pruef("Adressbuch: Name, Adresse, Abteilung, Telefon",
      "Vladyslav Borysenko <vladyslav.borysenko@thws.de>" in _al and "IDEE" in _al
      and "Tel. +49 9721 940-1" in _al, _al)
pruef("Adressbuch: niemand gefunden",
      "Niemand" in _pfk.rufe("address_lookup", {"query": "Unbekannt"}))
_arg_ab = {"subject": "Faschingsanfang", "start": f"{_tag_s} 11:00",
           "attendees": "Vladyslav Borysenko, rodolfo.cacacho@thws.de"}
_vs_ab = _pfk.pruefe_entwurf("meeting_request", _arg_ab)
pruef("Einladung: Namen werden im Entwurf zu Adressen, die Vorschau sagt es",
      _arg_ab["attendees"] == "vladyslav.borysenko@thws.de, rodolfo.cacacho@thws.de"
      and "Adressbuch: Vladyslav Borysenko = vladyslav.borysenko@thws.de" in _vs_ab, _vs_ab)
try:
    _pfk.pruefe_entwurf("meeting_request", {"subject": "x", "start": f"{_tag_s} 11:00",
                                            "attendees": "Vlad"})
    pruef("ein mehrdeutiger Name wird nicht geraten", False)
except _pfc.Fehler as _e:
    pruef("ein mehrdeutiger Name wird nicht geraten",
          "mehrdeutig" in str(_e) and "vlad.tester@thws.de" in str(_e), str(_e))
pruef("ein unbekannter Name wird nicht geraten",
      _wirft(lambda: _pfk.pruefe_entwurf("mail_senden", {"an": "Niemand Bekannt",
                                                          "betreff": "x", "body": "y"})))

# --- free/busy ---
_mo = _heute_c + datetime.timedelta(days=(7 - _heute_c.weekday()))       # next Monday


def _at(day, h, m=0):
    return datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=_tz_c)


def _free_busy(accounts, start, end, requested_view=None):
    out = []
    for who, _kind, _x in accounts:
        if who == "anna@test.de":
            out.append(_ns(calendar_events=[_ns(start=_at(_mo, 9), end=_at(_mo, 12),
                                                busy_type="Busy")]))
        elif who == "vladyslav.borysenko@thws.de":
            out.append(_ns(calendar_events=[_ns(start=_at(_mo, 13), end=_at(_mo, 15),
                                                busy_type="Tentative"),
                                            _ns(start=_at(_mo, 15), end=_at(_mo, 16),
                                                busy_type="Free")]))
        else:
            out.append(RuntimeError("no free/busy"))
    return iter(out)


_pfk._konto.protocol.get_free_busy_info = _free_busy
_fb = _pfk.rufe("calendar_free", {"attendees": "Vladyslav Borysenko, extern@firma.de",
                                  "from": f"{_mo:%Y-%m-%d}", "days": 1})
pruef("Frei/Gebucht: gemeinsame Lücken in der Arbeitszeit, Name aufgelöst",
      "08:00–09:00" in _fb and "12:00–13:00" in _fb and "15:00–17:00" in _fb
      and "09:00" not in _fb.split("Belegt:")[0].replace("08:00–09:00", ""), _fb)
pruef("Frei/Gebucht: wer keine Angaben liefert, wird genannt",
      "Keine Frei/Gebucht-Angaben für: extern@firma.de" in _fb, _fb)

# --- attachments, read state, forward, move ---
import created_files as _cf_m  # noqa: E402


class _Mail(_tyc.SimpleNamespace):
    def save(self, update_fields=None):
        self.saved = list(update_fields or [])

    def forward(self, **k):
        self.forwarded = k

    def move(self, folder):
        self.moved_to = folder


_pdf_m = _cf_m.build_pdf("Angebot", "Angebot 4711 über 12.400 EUR, Lieferung KW 47")
_m5 = _Mail(id="M5", subject="Angebot Meier", datetime_received=_t0, is_read=True,
            sender=_ns(name="Meier", email_address="meier@test.de"), text_body="Anbei.",
            attachments=[_ns(name="Angebot.pdf", content=_pdf_m),
                         _ns(name="notiz.txt", content="Liefertermin bestätigt".encode()),
                         _ns(name="Alte Nachricht", item=_ns(subject="Anfrage"))])
_mails.append(_m5)
_k5 = _pfc._merke_kennung(_pfk._bereich(), "M5")
_att = _pfk.rufe("mail_attachments", {"kennung": _k5})
pruef("Anhänge: Liste mit dem Text von PDF und Textdatei, eingebettete Mail benannt",
      "Angebot.pdf" in _att and "12.400 EUR" in _att and "Liefertermin bestätigt" in _att
      and "eingebettete Nachricht: Anfrage" in _att, _att)
_pfk.rufe("mail_mark", {"kennung": _k5, "read": False})
pruef("als ungelesen markiert", _m5.is_read is False and _m5.saved == ["is_read"])
_arg_fw = {"kennung": _k5, "an": "Rodolfo Cacacho", "body": "Zur Info"}
_vf = _pfk.pruefe_entwurf("mail_forward", _arg_fw)
pruef("Weiterleiten: Vorschau mit Betreff, aufgelöster Adresse und Anhängen",
      "WG: Angebot Meier" in _vf and "rodolfo.cacacho@thws.de" in _vf
      and "mit Anhängen: Angebot.pdf" in _vf, _vf)
_pfk.rufe("mail_forward", _arg_fw)
pruef("Weiterleiten: an die Adresse, mit Text",
      _m5.forwarded["to_recipients"] == ["rodolfo.cacacho@thws.de"]
      and _m5.forwarded["subject"] == "WG: Angebot Meier" and _m5.forwarded["body"] == "Zur Info",
      _m5.forwarded)
_pfk._konto.trash = _ns(name="Gelöschte Elemente")
_pfk._konto.msg_folder_root = _ns(walk=lambda: [_ns(name="Projekte"), _ns(name="Archiv")])
_vm = _pfk.pruefe_entwurf("mail_move", {"kennung": _k5, "ordner": "archiv"})
pruef("Verschieben: Vorschau nennt Mail und Ziel", "Angebot Meier" in _vm and "→ Archiv" in _vm, _vm)
_pfk.rufe("mail_move", {"kennung": _k5, "ordner": "papierkorb"})
pruef("in den Papierkorb heißt: Gelöschte Elemente, wiederherstellbar",
      _m5.moved_to.name == "Gelöschte Elemente")
pruef("ein unbekannter Ordner wird abgewiesen",
      _wirft(lambda: _pfk.pruefe_entwurf("mail_move", {"kennung": _k5, "ordner": "Gibtsnicht"})))

# --- out of office ---
_echte_settings = sys.modules.get("exchangelib.settings")
sys.modules["exchangelib.settings"] = _tyc.SimpleNamespace(OofSettings=lambda **k: _ns(**k))
_pfk._konto.oof_settings = _ns(state="Scheduled", start=_at(_mo, 0), end=_at(_mo, 18),
                               internal_reply="<p>Bin <b>unterwegs</b></p>", external_reply="")
_oof = _pfk.rufe("out_of_office", {})
pruef("Abwesenheitsnotiz lesen: Zustand, Zeitraum, Text ohne HTML",
      "geplant" in _oof and "Bin unterwegs" in _oof, _oof)
_vo = _pfk.pruefe_entwurf("out_of_office_set", {
    "state": "on", "start": f"{_mo:%Y-%m-%d}", "end": f"{_mo + datetime.timedelta(days=4):%Y-%m-%d}",
    "internal_reply": "Ich bin bis Freitag nicht im Haus."})
pruef("Abwesenheitsnotiz setzen: Vorschau mit Zeitraum und Text",
      f"{_mo:%d.%m.%Y} 00:00" in _vo and "23:59" in _vo and "nicht im Haus" in _vo, _vo)
_pfk.rufe("out_of_office_set", {"state": "on", "start": f"{_mo:%Y-%m-%d}",
                                "end": f"{_mo + datetime.timedelta(days=4):%Y-%m-%d}",
                                "internal_reply": "Ich bin bis Freitag nicht im Haus."})
_os = _pfk._konto.oof_settings
pruef("geplant, mit Zeitraum in Ortszeit, außen derselbe Text",
      _os.state == "Scheduled" and _os.start.hour == 0 and _os.end.hour == 23
      and _os.external_reply == _os.internal_reply and _os.external_audience == "All", _os)
_pfk.rufe("out_of_office_set", {"state": "off"})
pruef("ausschalten", _pfk._konto.oof_settings.state == "Disabled")
pruef("einschalten ohne Text wird abgewiesen",
      _wirft(lambda: _pfk.pruefe_entwurf("out_of_office_set", {"state": "on"})))
if _echte_settings is None:
    del sys.modules["exchangelib.settings"]
else:
    sys.modules["exchangelib.settings"] = _echte_settings

if _echtes_ews is None:
    del sys.modules["exchangelib"]
else:
    sys.modules["exchangelib"] = _echtes_ews
if _echtes_ews_items is None:
    del sys.modules["exchangelib.items"]
else:
    sys.modules["exchangelib.items"] = _echtes_ews_items

# --- calendar entries always wait for a person ---
_konfig_alt = _mcp_w.KONFIG
_mcp_w.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_kalender.json")
# An entry as created before the calendar existed: its own list of
# sending tools does not know the calendar, and it may answer on its own.
io.open(_mcp_w.KONFIG, "w", encoding="utf-8").write(json.dumps({
    "info": {"transport": "exchange", "anmeldung": "basic",
             "postfach": "info@test.de", "persoenlich": False,
             "automatisch": True, "hinweis_anhaengen": False,
             "textfeld": "body", "sendet": ["mail_senden", "antwort_senden"]}}))
pruef("Kalendereintraege gelten auch in alten Eintraegen als sendend",
      _mcp_w.sendet("info", "meeting_request") and _mcp_w.sendet("info", "calendar_add"))
pruef("und warten auch im automatischen Postfach auf einen Menschen",
      _mcp_w.braucht_bestaetigung("info", "meeting_request", {})
      and _mcp_w.braucht_bestaetigung("info", "calendar_add", {}))
pruef("Lesen im Kalender bleibt ohne Rueckfrage",
      not _mcp_w.braucht_bestaetigung("info", "calendar_events", {}))
pruef("Weiterleiten, Verschieben, Abwesenheitsnotiz: auch in alten Eintraegen mit Rueckfrage",
      _mcp_w.braucht_bestaetigung("info", "mail_move", {})
      and _mcp_w.braucht_bestaetigung("info", "out_of_office_set", {})
      and _mcp_w.sendet("info", "mail_forward"))
pruef("Adressbuch, Frei/Gebucht, Anhaenge, Markieren ohne Rueckfrage",
      not any(_mcp_w.braucht_bestaetigung("info", _w, {})
              for _w in ("address_lookup", "calendar_free", "mail_attachments", "mail_mark",
                         "out_of_office")))
os.remove(_mcp_w.KONFIG)
_mcp_w.KONFIG = _konfig_alt


class _PruefServer:
    name = "box"
    confirm = ("meeting_request",)

    def werkzeuge(self):
        return [{"server": "box", "name": "meeting_request", "beschreibung": "",
                 "schema": {"type": "object"}}]

    def pruefe_entwurf(self, name, argumente):
        if not argumente.get("attendees"):
            raise ValueError("Teilnehmer fehlen.")
        return "Statik | Mi 12.11.2026 14:00-15:00"

    def rufe(self, name, argumente=None):
        raise AssertionError("must not run")


class _ZweiRunden:
    def __init__(self):
        self.runde = 0
        self.chat = _tyc.SimpleNamespace(completions=_tyc.SimpleNamespace(
            create=self.create))

    def create(self, **kw):
        self.runde += 1
        argumente = ('{"subject": "Statik"}' if self.runde == 1
                     else '{"subject": "Statik", "attendees": "a@test.de"}')
        rufe = None
        if self.runde <= 2:
            rufe = [_ns(id=f"c{self.runde}", function=_ns(
                name="box__meeting_request", arguments=argumente))]
        return _ns(choices=[_ns(message=_ns(content="", tool_calls=rufe))])


_zz, _ze = pipeline.werkzeuglauf(_ZweiRunden(), "m", "system",
                                 [{"role": "user", "content": "lade ein"}],
                                 {"box": _PruefServer()})
_antw_z = [m["content"] for m in _zz if m.get("role") == "tool"]
pruef("ein unvollstaendiger Entwurf geht zum Korrigieren ans Modell zurueck",
      "Teilnehmer fehlen" in _antw_z[0] and len(_ze) == 1
      and _ze[0]["vorschau"].startswith("Statik | Mi"), (_antw_z, _ze))

# --- SUMMARIES INTO A WORKSPACE (workspace_notes.py) ---
import workspace_notes as _wsn

pruef("Ablegen wird ohne Postfach nur angeboten, wenn danach gefragt wird",
      _wsn.offered("Lege eine Zusammenfassung ab", {})
      and not _wsn.offered("Wie hoch ist die Last?", {})
      and _wsn.offered("Wie hoch ist die Last?", {"box": object()}))


class _WzClient:
    """Calls save_summary once, then answers."""

    def __init__(self):
        self.runde = 0
        self.chat = _tyc.SimpleNamespace(completions=_tyc.SimpleNamespace(
            create=self.create))

    def create(self, **kw):
        self.runde += 1
        rufe = None
        if self.runde == 1:
            rufe = [_ns(id="c1", function=_ns(
                name="workspace__save_summary",
                arguments='{"title": "T", "text": "x"}'))]
        return _ns(choices=[_ns(message=_ns(content="", tool_calls=rufe))])


class _WzServer:
    name = "workspace"
    confirm = ("save_summary",)
    gerufen = []

    def werkzeuge(self):
        return [{"server": "workspace", "name": "save_summary",
                 "beschreibung": "", "schema": {"type": "object"}}]

    def rufe(self, name, argumente=None):
        self.gerufen.append(name)
        return "abgelegt"


_wz_zusatz, _wz_entw = pipeline.werkzeuglauf(
    _WzClient(), "m", "system", [{"role": "user", "content": "lege ab"}],
    {"workspace": _WzServer()})
pruef("Ablegen laeuft nicht im Werkzeugkreis, es wird ein Entwurf",
      not _WzServer.gerufen and len(_wz_entw) == 1
      and _wz_entw[0]["werkzeug"] == "save_summary", (_WzServer.gerufen, _wz_entw))
pruef("der Name 'workspace' ist fuer Postfaecher reserviert",
      _mcp_w.lege_an("workspace", "exchange", "owa.test")[0] is False)

# --- EXCHANGE SPRICHT KEIN MCP, UND DAS DARF NIRGENDS AUFFALLEN ---
#
# Ein Exchange-Postfach laeuft nicht ueber JSON-RPC, sondern ueber
# postfach.py im selben Prozess. Alles darueber -- Werkzeugliste,
# Bestaetigung vor dem Senden, Hinweis, Anmeldung in der Sitzung --
# unterscheidet die beiden Wege nicht. Diese Pruefungen halten das fest.
import postfach as _pf0

_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_exchange.json")
_js0.dump({"markus": {"transport": "exchange", "anmeldung": "basic",
                      "url": "https://owa.test/EWS/Exchange.asmx",
                      "persoenlich": True, "textfeld": "body",
                      "sendet": list(_pf0.SENDEWERKZEUGE)},
           "info": {"transport": "exchange", "anmeldung": "basic",
                    "postfach": "info@test.de", "persoenlich": False,
                    "automatisch": True, "textfeld": "body",
                    "sendet": list(_pf0.SENDEWERKZEUGE)},
           "irgendein": {"transport": "http", "url": "http://z",
                         "anmeldung": "keine"}},
          statefiles.open(_mcp0.KONFIG, "w", encoding="utf-8"))

_vb1 = _mcp0.verbinde({})
pruef("ein Exchange-Postfach wird kein JSON-RPC-Server",
      isinstance(_vb1["markus"], _pf0.Postfach),
      type(_vb1["markus"]).__name__)
pruef("ein MCP-Server bleibt einer",
      isinstance(_vb1["irgendein"], _mcp0.Verbindung),
      type(_vb1["irgendein"]).__name__)
pruef("beide Bauarten haben dieselben drei Methoden",
      all(callable(getattr(_vb1[_n], _m, None))
          for _n in ("markus", "irgendein")
          for _m in ("werkzeuge", "rufe", "schliesse")))

# DIE WICHTIGSTE: jedes Werkzeug, das etwas verschickt, wird auch als
# solches erkannt. Faellt eines heraus, laeuft es ohne Rueckfrage --
# und eine verschickte Nachricht kommt nicht zurueck.
_erkannt = {_w["name"] for _w in _pf0.WERKZEUGE
            if _mcp0.sendet("markus", _w["name"])}
pruef("genau die Sende- und Kalenderwerkzeuge gelten als sendend",
      _erkannt == set(_pf0.SENDEWERKZEUGE) | set(_pf0.CONFIRM_TOOLS),
      sorted(_erkannt))

_namen = {_w["name"] for _w in _pf0.WERKZEUGE}
pruef("die Vorlage nennt nur Werkzeuge, die es wirklich gibt",
      set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"]) <= _namen,
      sorted(set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"]) - _namen))
pruef("und sie nennt alle, die senden",
      set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"])
      == set(_pf0.SENDEWERKZEUGE))

# Der Hinweis unter einer automatischen Antwort braucht ein Feld, in
# das er passt. Steht in der Vorlage ein Feld, das kein Sendewerkzeug
# hat, faellt das automatische Antworten aus -- lautlos.
_feld = _mcp0.VORLAGEN["exchange"]["angaben"]["textfeld"]
_ohne_feld = sorted(_w["name"] for _w in _pf0.WERKZEUGE
                    if _w["name"] in _pf0.SENDEWERKZEUGE
                    and _feld not in (_w["schema"].get("properties") or {}))
pruef("jedes Sendewerkzeug hat das Feld, in das der Hinweis kommt",
      not _ohne_feld, _ohne_feld)

# Gegenprobe am freigeschalteten Postfach: mit dem Feld laeuft es
# durch, ohne das Feld wird bestaetigt statt gesendet.
_ja1, _g1 = _mcp0.darf_automatisch("info", "mail_senden", {"body": "x"})
pruef("mit Textfeld antwortet ein freigeschaltetes Postfach selbst", _ja1, _g1)
_ja2, _g2 = _mcp0.darf_automatisch("info", "mail_senden", {"text": "x"})
pruef("ohne Textfeld wird bestaetigt statt gesendet", not _ja2, _g2)
pruef("ein persoenliches Postfach antwortet auch mit Feld nicht selbst",
      not _mcp0.darf_automatisch("markus", "mail_senden", {"body": "x"})[0])

# ANMELDEDATEN KOMMEN AUS DER SITZUNG UND SONST NIRGENDWOHER.
_ohne_kopf = _pf0.Postfach("markus", {"transport": "exchange"})
try:
    _ohne_kopf._zugang()
    _griff = "durchgelassen"
except _pf0.Fehler:
    _griff = "abgewiesen"
pruef("ohne Anmeldung wird kein Postfach geoeffnet",
      _griff == "abgewiesen", _griff)

_mit_kopf = _pf0.Postfach("markus", {"transport": "exchange"},
                          _mcp0.kopf_fuer("markus", "m@test.de", "geheim"))
pruef("die Anmeldedaten stammen aus dem Kopf dieser Sitzung",
      _mit_kopf._zugang() == ("m@test.de", "geheim"))

# Eine Kurzkennung gehoert zu EINEM Postfach. Sonst ginge eine Antwort
# mit den Daten des einen an den Bezug des anderen.
_kz = _pf0._merke_kennung("markus", "AAAA")
pruef("eine Kurzkennung loest im eigenen Postfach auf",
      _pf0._lange_kennung("markus", _kz) == "AAAA")
try:
    _pf0._lange_kennung("info", _kz)
    _fremd = "durchgelassen"
except _pf0.Fehler:
    _fremd = "abgewiesen"
pruef("und in einem fremden nicht", _fremd == "abgewiesen", _fremd)

# EIN FUNKTIONSPOSTFACH BRAUCHT SEINE EIGENE ADRESSE. Ohne sie oeffnet
# es das Postfach dessen, der sich gerade anmeldet: jeder saehe seine
# eigene Post unter fremdem Namen, und eine automatische Antwort ginge
# aus dem falschen Postfach hinaus.
_okA, _mA = _mcp0.lege_an("t_ohne", "exchange", "owa.test", persoenlich=False)
pruef("ein Funktionspostfach ohne eigene Adresse wird abgewiesen",
      not _okA, _mA)
_okB, _mB = _mcp0.lege_an("t_mit", "exchange", "owa.test", persoenlich=False,
                          postfach="info2@test.de")
pruef("mit eigener Adresse wird es angelegt", _okB, _mB)
pruef("der eingetragene Server wird zur EWS-Adresse ergaenzt",
      _mcp0.lies_konfiguration()["t_mit"]["url"]
      == "https://owa.test/EWS/Exchange.asmx",
      _mcp0.lies_konfiguration()["t_mit"]["url"])
# Ein persoenliches darf ohne Adresse -- dort ist die des Anmeldenden
# die richtige.
_okC, _mC = _mcp0.lege_an("t_pers", "exchange", "", persoenlich=True)
pruef("ein persoenliches Postfach geht auch ohne beides", _okC, _mC)

# EIN PERSOENLICHER EINTRAG DIENT ALLEN. Mit fester Adresse waere er das
# Postfach einer einzigen Person, und alle anderen bekaemen von Exchange
# eine Absage.
_okD, _mD = _mcp0.lege_an("t_pers_fest", "exchange", "owa.test",
                          persoenlich=True, postfach="chef@test.de")
pruef("ein persoenlicher Eintrag mit fester Adresse wird abgewiesen",
      not _okD, _mD)

# Zwei Nutzer, derselbe Eintrag: jeder oeffnet sein eigenes Postfach,
# und eine Kurzkennung aus dem einen loest im anderen nicht auf.
_pA = _pf0.Postfach("postfach", {"transport": "exchange"},
                    _mcp0.kopf_fuer("markus", "anna@test.de", "geheim1"))
_pB = _pf0.Postfach("postfach", {"transport": "exchange"},
                    _mcp0.kopf_fuer("markus", "bernd@test.de", "geheim2"))
# In try: fehlt eine der Methoden, soll die Pruefung FALLEN und den
# Grund nennen, statt den ganzen Lauf abzubrechen.
try:
    _adr = (_pA.adresse(), _pB.adresse())
except Exception as e:
    _adr = f"{type(e).__name__}: {e}"
pruef("ein gemeinsamer Eintrag oeffnet je Nutzer dessen eigenes Postfach",
      _adr == ("anna@test.de", "bernd@test.de"), _adr)
try:
    _kzA = _pf0._merke_kennung(_pA._bereich(), "ANNA-NACHRICHT")
    try:
        _pf0._lange_kennung(_pB._bereich(), _kzA)
        _quer = "durchgelassen"
    except _pf0.Fehler:
        _quer = "abgewiesen"
    _eigen = _pf0._lange_kennung(_pA._bereich(), _kzA) == "ANNA-NACHRICHT"
except Exception as e:
    _quer, _eigen = f"{type(e).__name__}: {e}", False
pruef("eine Kurzkennung aus Annas Postfach loest in Bernds Sitzung nicht auf",
      _quer == "abgewiesen" and _eigen, _quer)

# "Meine Postfaecher" steht fuer JEDEN Nutzer da, auch bevor ein Postfach
# eingerichtet ist. Hing der Aufklapper an "es gibt eines", sah ein Nutzer
# von der Mailanbindung nichts -- sichtbar war nur die Einrichtung unter
# "Verwaltung", und das las sich, als sei sie Verwaltern vorbehalten.
_eltern = {}
_mp_bedingt = []

statefiles.remove(_mcp0.KONFIG)
_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# --- DER HINWEIS UNTER AUTOMATISCHEN ANTWORTEN IST ABSCHALTBAR ---
#
# Vorgabe ist an: wer nichts sagt, bekommt ihn. Abschalten ist eine
# ausdrueckliche Handlung -- ein Empfaenger, der nicht erfaehrt, dass
# niemand die Nachricht gelesen hat, kann sie nicht einordnen.
#
# Ein bestaetigter Entwurf bekommt keinen: er ist gelesen.
import json as _js
import mcp as _mcp2

_mcp2.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_probe.json")


def _postfach(**angaben):
    _js.dump({"pf": dict(angaben)},
             statefiles.open(_mcp2.KONFIG, "w", encoding="utf-8"))


_arg = {"body": "Guten Tag"}

_postfach(automatisch=True, sendet=["senden"], textfeld="body")
pruef("ohne Angabe steht der Hinweis unter der Nachricht",
      "--" in _mcp2.mit_hinweis("pf", _arg)["body"])
pruef("und automatisch senden ist erlaubt",
      _mcp2.darf_automatisch("pf", "senden", _arg)[0])

_postfach(automatisch=True, sendet=["senden"], textfeld="body",
          hinweis_anhaengen=False)
pruef("abgeschaltet bleibt die Nachricht unveraendert",
      _mcp2.mit_hinweis("pf", _arg)["body"] == "Guten Tag")
pruef("und automatisch senden bleibt erlaubt",
      _mcp2.darf_automatisch("pf", "senden", _arg)[0])

# Die Richtung des Zweifels bleibt: ohne Freischaltung wird bestaetigt,
# und mit Hinweis, aber ohne Textfeld, ebenfalls -- sonst ginge eine
# Nachricht ohne den Hinweis hinaus, den der Betreiber verlangt hat.
_postfach(automatisch=False, sendet=["senden"], textfeld="body",
          hinweis_anhaengen=False)
pruef("ohne Freischaltung wird weiterhin bestaetigt",
      _mcp2.braucht_bestaetigung("pf", "senden", _arg))

_postfach(automatisch=True, sendet=["senden"], hinweis_anhaengen=True)
pruef("und mit Hinweis, aber ohne Textfeld, auch",
      _mcp2.braucht_bestaetigung("pf", "senden", {"x": 1}))

statefiles.remove(_mcp2.KONFIG)
_mcp2.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")
