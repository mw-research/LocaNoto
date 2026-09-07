"""Chatverlaeufe -- verschluesselt, mit dem Titel in der Datei statt im Namen.

Vorher lag jeder Verlauf als lesbares JSON unter data/chats/<nutzer>/, und
der Dateiname war der Titel: "Pruefristen_Kessel_26-08-26.json". Damit
verriet schon das Verzeichnis, worum es ging -- ein Inhaltsverzeichnis der
Fragen, ohne dass jemand eine Datei oeffnen musste.

Deshalb zwei Aenderungen, die zusammengehoeren:

  1. Der Inhalt ist verschluesselt (siehe geheim.py).
  2. Der Dateiname ist bedeutungslos. Der Titel steht in der Datei und im
     Verzeichnis -- und das ist ebenfalls verschluesselt.

Nur eines von beidem waere halb: ein verschluesselter Inhalt unter einem
sprechenden Namen ist wie ein verschlossener Aktenschrank mit beschrifteten
Schubladen.

Die Kennung ist zufaellig und bleibt. Sie geht als Zusatzdatum in die
Verschluesselung ein, zusammen mit dem Nutzernamen: eine Chatdatei, die in
einen fremden Ordner kopiert wird, entschluesselt dort nicht.

Altbestand wird beim ersten Zugriff uebernommen -- Titel aus dem alten
Dateinamen, Inhalt neu verschluesselt geschrieben, alte Datei entfernt.
Fehlt der Schluessel, laeuft alles weiter im Klartext; geheim.py gibt die
Daten dann unveraendert durch.
"""
import json
import os
import re
import secrets
import time

import geheim
import paths

INDEX = "verzeichnis"
KENNUNG = re.compile(r"^c_[0-9a-f]{16}\.json$")


def ordner(benutzer):
    p = os.path.join(paths.CHATS_DIR, benutzer)
    os.makedirs(p, exist_ok=True)
    return p


def neue_kennung():
    return f"c_{secrets.token_hex(8)}.json"


def _zusatz(benutzer, kennung):
    return f"chat:{benutzer}:{kennung}".encode("utf-8")


# --- VERZEICHNIS ---

def _index_pfad(benutzer):
    return os.path.join(ordner(benutzer), INDEX)


def _index_lesen(benutzer):
    try:
        with open(_index_pfad(benutzer), "rb") as f:
            roh = geheim.entschluessele(f.read(),
                                        _zusatz(benutzer, INDEX))
        daten = json.loads(roh.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        # Auch ein beschaedigtes Verzeichnis darf die Anwendung nicht
        # anhalten: die Verlaeufe selbst sind noch da, und ihre Titel
        # stehen darin.
        return {}
    return daten if isinstance(daten, dict) else {}


def _index_schreiben(benutzer, daten):
    roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
    p = _index_pfad(benutzer)
    vorlaeufig = p + ".neu"
    with open(vorlaeufig, "wb") as f:
        f.write(geheim.verschluessele(roh, _zusatz(benutzer, INDEX)))
    os.replace(vorlaeufig, p)


# --- ALTBESTAND ---

def _titel_aus_name(name):
    """"Pruefristen_Kessel_26-08-26.json" -> "Pruefristen Kessel 26-08-26"."""
    return name[:-5].replace("_", " ").strip() or "Chat"


def uebernimm_alt(benutzer):
    """Alte Chatdateien in das neue Format bringen. Anzahl der uebernommenen.

    Laeuft bei jedem Aufruf von liste(), findet aber nach dem ersten Mal
    nichts mehr -- ein Verzeichnislauf ueber eine Handvoll Dateien.
    """
    o = ordner(benutzer)
    index = _index_lesen(benutzer)
    uebernommen = 0
    for name in sorted(os.listdir(o)):
        if not name.endswith(".json") or KENNUNG.match(name):
            continue
        alt = os.path.join(o, name)
        try:
            with open(alt, "rb") as f:
                roh = f.read()
            nachrichten = json.loads(
                geheim.entschluessele(roh).decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(nachrichten, dict):
            nachrichten = nachrichten.get("nachrichten") or []
        kennung = neue_kennung()
        try:
            _schreibe(benutzer, kennung, nachrichten,
                      _titel_aus_name(name),
                      os.path.getmtime(alt))
        except OSError:
            continue
        index[kennung] = {"titel": _titel_aus_name(name),
                          "geaendert": os.path.getmtime(alt)}
        try:
            os.remove(alt)
        except OSError:
            pass
        uebernommen += 1
    if uebernommen:
        _index_schreiben(benutzer, index)
    return uebernommen


# --- LESEN UND SCHREIBEN ---

def _schreibe(benutzer, kennung, nachrichten, titel, geaendert=None):
    inhalt = {"titel": titel, "geaendert": geaendert or time.time(),
              "nachrichten": nachrichten}
    roh = json.dumps(inhalt, ensure_ascii=False).encode("utf-8")
    p = os.path.join(ordner(benutzer), kennung)
    vorlaeufig = p + ".neu"
    with open(vorlaeufig, "wb") as f:
        f.write(geheim.verschluessele(roh, _zusatz(benutzer, kennung)))
    os.replace(vorlaeufig, p)


def _lies(benutzer, kennung):
    p = os.path.join(ordner(benutzer), kennung)
    try:
        with open(p, "rb") as f:
            roh = geheim.entschluessele(f.read(),
                                        _zusatz(benutzer, kennung))
        daten = json.loads(roh.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if isinstance(daten, list):
        # Sehr alter Bestand: nur die Nachrichtenliste, ohne Umschlag.
        return {"titel": "Chat", "geaendert": 0, "nachrichten": daten}
    return daten if isinstance(daten, dict) else None


def liste(benutzer):
    """[(kennung, titel, geaendert)], neueste zuerst.

    Titel kommen aus dem Verzeichnis. Fehlt einer dort -- etwa weil das
    Verzeichnis verlorenging --, wird die Datei geoeffnet und der Eintrag
    nachgetragen. Das ist der Rueckweg, der ohne Verzeichnis noch
    funktioniert.
    """
    uebernimm_alt(benutzer)
    o = ordner(benutzer)
    index = _index_lesen(benutzer)
    vorhanden = [n for n in os.listdir(o) if KENNUNG.match(n)]

    geaendert_index = False
    for kennung in vorhanden:
        if kennung in index:
            continue
        daten = _lies(benutzer, kennung) or {}
        index[kennung] = {"titel": daten.get("titel") or "Chat",
                          "geaendert": daten.get("geaendert")
                          or os.path.getmtime(os.path.join(o, kennung))}
        geaendert_index = True

    # Eintraege ohne Datei entfernen, sonst waechst das Verzeichnis um
    # Verlaeufe, die es nicht mehr gibt.
    for kennung in [k for k in index if k not in vorhanden]:
        del index[kennung]
        geaendert_index = True

    if geaendert_index:
        try:
            _index_schreiben(benutzer, index)
        except OSError:
            pass

    eintraege = [(k, v.get("titel") or "Chat", v.get("geaendert") or 0)
                 for k, v in index.items()]
    eintraege.sort(key=lambda x: x[2], reverse=True)
    return eintraege


def lade(benutzer, kennung):
    """Die Nachrichten eines Verlaufs. Leere Liste, wenn nichts zu holen."""
    daten = _lies(benutzer, kennung)
    if not daten:
        return []
    nachrichten = daten.get("nachrichten")
    return nachrichten if isinstance(nachrichten, list) else []


def titel(benutzer, kennung, rueckfall="Neuer Chat"):
    return (_index_lesen(benutzer).get(kennung, {}).get("titel")
            or rueckfall)


def speichere(benutzer, kennung, nachrichten, titel=None):
    """Schreibt den Verlauf und haelt das Verzeichnis nach."""
    index = _index_lesen(benutzer)
    vorher = index.get(kennung, {})
    name = titel or vorher.get("titel") or "Chat"
    jetzt = time.time()
    _schreibe(benutzer, kennung, nachrichten, name, jetzt)
    index[kennung] = {"titel": name, "geaendert": jetzt}
    _index_schreiben(benutzer, index)


def benenne(benutzer, kennung, neuer_titel):
    """Nur der Titel, ohne die Datei anzufassen.

    Vorher hiess Umbenennen: Datei neu schreiben, alte loeschen. Jetzt ist
    der Name der Datei bedeutungslos -- also aendert sich nur ein Eintrag
    im Verzeichnis.
    """
    index = _index_lesen(benutzer)
    eintrag = index.setdefault(kennung, {})
    eintrag["titel"] = neuer_titel or eintrag.get("titel") or "Chat"
    eintrag.setdefault("geaendert", time.time())
    _index_schreiben(benutzer, index)


def loesche(benutzer, kennung):
    """Verlauf und Verzeichniseintrag entfernen."""
    p = os.path.join(ordner(benutzer), kennung)
    try:
        os.remove(p)
    except OSError:
        pass
    index = _index_lesen(benutzer)
    if kennung in index:
        del index[kennung]
        try:
            _index_schreiben(benutzer, index)
        except OSError:
            pass


def zaehle_klartext(benutzer):
    """Wie viele Verlaeufe noch unverschluesselt daliegen -- fuer die Anzeige."""
    o = ordner(benutzer)
    offen = 0
    for name in os.listdir(o):
        if not (name.endswith(".json") or name == INDEX):
            continue
        try:
            with open(os.path.join(o, name), "rb") as f:
                if not geheim.ist_verschluesselt(f.read(8)):
                    offen += 1
        except OSError:
            pass
    return offen
