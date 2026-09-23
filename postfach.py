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
import uuid

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

ZEITLIMIT = paths.env_float("POSTFACH_TIMEOUT", 30)


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
_KENNUNGEN = {}
_KENNUNG_GRENZE = 500


def _merke_kennung(server, lang):
    kurz = "m" + uuid.uuid4().hex[:8]
    if len(_KENNUNGEN) >= _KENNUNG_GRENZE:
        for alt in list(_KENNUNGEN)[:_KENNUNG_GRENZE // 2]:
            _KENNUNGEN.pop(alt, None)
    _KENNUNGEN[kurz] = (server, lang)
    return kurz


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
)

SENDEWERKZEUGE = ("mail_senden", "antwort_senden")


def ews_adresse(ziel):
    """Aus dem, was der Verwalter eintraegt, eine EWS-Adresse machen.

    Eingetragen wird 'owa.firma.de' oder die vollstaendige Adresse.
    Beides soll gehen -- wer den Pfad kennt, tippt ihn, und wer nicht,
    muss ihn nicht kennen.
    """
    ziel = str(ziel or "").strip().rstrip("/")
    if not ziel:
        return ""
    if not ziel.startswith(("http://", "https://")):
        ziel = "https://" + ziel
    if "/ews/" not in ziel.lower():
        ziel += "/EWS/Exchange.asmx"
    return ziel


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
        # Welches Postfach geoeffnet wird: das eingetragene, sonst das
        # des Anmeldenden. So laeuft ein Funktionspostfach ueber die
        # Stellvertretung -- jeder meldet sich mit SEINEN Daten an, und
        # Exchange entscheidet, ob er hineindarf. Ein gemeinsames
        # Passwort braucht es dafuer nicht.
        adresse = str(self.angaben.get("postfach") or "").strip() or benutzer
        if "@" not in adresse:
            raise Fehler(
                f"{self.name}: '{adresse}' ist keine Postfachadresse. "
                f"Mit der vollstaendigen Mailadresse anmelden.")
        zugang = Credentials(username=benutzer, password=passwort)
        url = ews_adresse(self.angaben.get("url"))
        try:
            if url:
                konfig = Configuration(service_endpoint=url,
                                       credentials=zugang)
                self._konto = Account(primary_smtp_address=adresse,
                                      config=konfig, autodiscover=False,
                                      access_type=DELEGATE)
            else:
                # Ohne Adresse sucht exchangelib den Server selbst. Das
                # ist der bequeme Weg und der langsame; er steht hier
                # als Rueckfall, nicht als Vorgabe.
                self._konto = Account(primary_smtp_address=adresse,
                                      credentials=zugang, autodiscover=True,
                                      access_type=DELEGATE)
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
        label = self.angaben.get("postfach") or self.name
        return [{"server": self.name, "name": w["name"],
                 "beschreibung": w["beschreibung"].format(label=label),
                 "schema": w["schema"]}
                for w in WERKZEUGE]

    def rufe(self, name, argumente=None):
        a = dict(argumente or {})
        if name == "mails_lesen":
            return self._lesen(a)
        if name == "mail_volltext":
            return self._volltext(a)
        if name == "mail_senden":
            return self._senden(a)
        if name == "antwort_senden":
            return self._antworten(a)
        raise Fehler(f"{self.name}: kein Werkzeug namens '{name}'.")

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
            kurz = _merke_kennung(self.name, m.id)
            zeilen.append(
                f"[{kurz}] {_datum(getattr(m, 'datetime_received', None))} | "
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
        kennung = _lange_kennung(self.name, a.get("kennung"))
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
        teile = [f"Datum:   {_datum(getattr(m, 'datetime_received', None))}",
                 f"Von:     {_absender(m)}",
                 f"An:      {an or '-'}"]
        if kopie:
            teile.append(f"Kopie:   {kopie}")
        teile.append(f"Betreff: {getattr(m, 'subject', '') or ''}")
        teile.append("")
        teile.append((getattr(m, "text_body", "") or "").strip()
                     or "(kein Text)")
        return "\n".join(teile)

    # --- SENDEN ---
    #
    # Ob ueberhaupt gesendet werden darf, steht NICHT hier. Das
    # entscheidet mcp.braucht_bestaetigung an einer Stelle fuer alle
    # Postfaecher. Hier wird nur ausgefuehrt, was schon entschieden ist.

    def _senden(self, a):
        from exchangelib import Message, Mailbox

        konto = self._verbindung()
        an = _liste(a.get("an"))
        if not an:
            raise Fehler("Kein Empfaenger angegeben.")
        try:
            m = Message(
                account=konto,
                subject=str(a.get("betreff") or ""),
                body=str(a.get("body") or ""),
                to_recipients=[Mailbox(email_address=x) for x in an],
                cc_recipients=[Mailbox(email_address=x)
                               for x in _liste(a.get("kopie"))] or None)
            m.send_and_save()
        except Exception as e:
            raise Fehler(f"{self.name}: nicht gesendet ({_kurz(e)}).")
        return f"Gesendet an {', '.join(an)}."

    def _antworten(self, a):
        konto = self._verbindung()
        kennung = _lange_kennung(self.name, a.get("kennung"))
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
