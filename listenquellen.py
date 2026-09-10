"""Woher die Listen kommen -- und wer welche sieht.

Listen werden nicht hochgeladen. Sie liegen dort, wo die Fachabteilung
sie ohnehin pflegt: auf einem Netzlaufwerk, in einem Abteilungsordner, im
persoenlichen Laufwerk. Wer dort Zeilen ergaenzt und speichert, soll sie
in der naechsten Frage sehen -- ohne Einlesen, ohne Knopf. Ein Upload
waere eine zweite Kopie, die ab dem ersten Tag von der ersten abweicht.

Bisher gab es dafuer EINEN Ordner und darunter "Bereiche" -- die oberste
Ebene an Unterordnern. Ein Bereich war ein Filter und keine Berechtigung:
wer die Liste eingrenzte, sah weniger, wer es liess, sah alles. Fuer
Preislisten geht das. Fuer die Inventur einer Tochtergesellschaft oder
die Personalplanung nicht.

Eine Quelle gehoert deshalb zu einem RAUM
-----------------------------------------
Genau denselben Raeumen wie die Dokumente. Kein zweites
Berechtigungssystem daneben -- das erste, das jemand vergisst mitzupflegen,
ist das, durch das die Daten abfliessen.

    {"raum": "allgemein", "pfad": "/mnt/listen/allgemein"}
    {"raum": "einkauf",   "pfad": "/srv/abteilung/einkauf/listen"}
    {"raum": "@privat",   "pfad": "/mnt/heim/{benutzer}/Listen"}

Gefiltert wird mit raeume.lesbar() -- dieselbe Funktion, die ueber die
Sammlungen und den Stichwortindex entscheidet.

Der Platzhalter statt einer Eingabe je Person
---------------------------------------------
Die naheliegende Loesung waere: jeder traegt seinen Pfad selbst ein. Sie
ist falsch, und zwar aus einem Grund, der sich nicht wegprogrammieren
laesst.

Der Container liest mit EINER Kennung. Damit "/mnt/heim/anna/Listen"
ueberhaupt erreichbar ist, muss "/mnt/heim" eingehaengt sein -- mit einem
Dienstkonto, das alle Heimlaufwerke lesen kann. Traegt nun jemand
"/mnt/heim/anna/Listen" als SEINE Quelle ein, liest die Anwendung das
bereitwillig: sie hat die Rechte, sie prueft nur, was jemand tippt.

Mit dem Platzhalter tippt niemand einen Pfad. Der Verwalter hinterlegt
das Muster EINMAL, und die Quelle jedes Nutzers ergibt sich aus seinem
Namen. Damit ist der ganze Fehlerraum weg -- kein "../", kein fremdes
Heimlaufwerk, kein /app/data. Und es ist weniger Arbeit, nicht mehr.

Was das NICHT leistet
---------------------
Das Heimlaufwerk ist "nur fuer mich" -- gegenueber Kollegen am Dateiserver.
Gegenueber der Anwendung nicht: sie liest es mit dem Dienstkonto. Die
Trennung zwischen den Nutzern macht ab da LocaNoto, nicht der Dateiserver.

Das ist derselbe Grad an Zusicherung wie beim persoenlichen Raum, und er
ist ehrlich zu nennen und nicht zu verschweigen: wer die Anwendung
umgeht, umgeht auch diese Trennung. Wer sie benutzt, kommt an fremde
Listen nicht heran.
"""
import json
import os
import re

import geheim
import paths

QUELLEN = os.path.join(paths.CONFIG_DIR, "listenquellen.json")

# Der Raum, der fuer JEDEN seinen eigenen meint. Ein Eintrag deckt damit
# alle Heimlaufwerke ab, statt einer je Person.
MUSTER_RAUM = "@privat"
PLATZHALTER = "{benutzer}"

# Wurzeln, unterhalb derer Quellen liegen duerfen. Leer = keine
# Einschraenkung ausser den eigenen Verzeichnissen unten.
#
#   LISTEN_WURZELN=/mnt/listen:/srv/abteilungen:/mnt/heim
WURZELN = [w.strip().rstrip("/") for w in
           re.split(r"[:,;]", os.getenv("LISTEN_WURZELN", "") or "")
           if w.strip()]


def _eigene_verzeichnisse():
    """Die Verzeichnisse der Anwendung selbst -- dort nie hineinlesen.

    Nicht aus Vorsicht, sondern gegen einen bestimmten Fehlgriff: eine
    Quelle auf das Datenverzeichnis nimmt die Tabellen aus data/dokumente
    in den Katalog auf -- ohne Raum, mit ihren Spaltenwerten, fuer jeden
    sichtbar, der den betreffenden Raum lesen darf. Ein Tippfehler
    genuegt, und die Trennung, die daneben mit Schluesseln durchgesetzt
    wird, ist an dieser Stelle offen.
    """
    aus = []
    for p in (paths.DATA_DIR, paths.CONFIG_DIR, paths.INDEX_DIR):
        try:
            aus.append(os.path.realpath(p))
        except OSError:
            pass
    return aus


def pruefe_pfad(p):
    """Darf hier gelesen werden? (ok, meldung).

    Ein Muster wird mit dem Platzhalter geprueft: der Pfad muss auch dann
    noch unter einer erlaubten Wurzel liegen.
    """
    p = (p or "").strip()
    if not p:
        return False, "Kein Pfad angegeben."
    probe = p.replace(PLATZHALTER, "platzhalter")
    if not os.path.isabs(probe):
        return False, "Ein absoluter Pfad, bitte -- relative Angaben " \
                      "haengen davon ab, wo der Prozess gerade steht."
    echt = os.path.realpath(probe)

    for eigen in _eigene_verzeichnisse():
        if echt == eigen or echt.startswith(eigen + os.sep):
            return False, (f"'{p}' liegt in einem Verzeichnis der "
                           f"Anwendung ({eigen}). Dort stehen die Daten "
                           f"aller Raeume -- eine Listenquelle darauf "
                           f"haette sie an den Raeumen vorbei gelesen.")

    if WURZELN:
        if not any(echt == w or echt.startswith(w + os.sep)
                   for w in (os.path.realpath(x) for x in WURZELN)):
            return False, (f"'{p}' liegt unter keiner der erlaubten "
                           f"Wurzeln ({', '.join(WURZELN)}). "
                           f"LISTEN_WURZELN legt sie fest.")
    return True, ""


# --- ABLAGE ---

def _leer():
    return {"quellen": []}


def lade():
    """Die hinterlegten Quellen. Bei kaputter Signatur: keine.

    Lieber keine Listen als Listen aus einer Datei, die jemand
    danebengelegt hat. Eine untergeschobene Quelle waere ein Pfad, den
    die Anwendung mit ihren Rechten ausliest.
    """
    try:
        with open(QUELLEN, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _leer()
    if not isinstance(daten, dict):
        return _leer()
    inhalt = daten.get("quellen")
    if not isinstance(inhalt, list):
        return _leer()
    if geheim.verfuegbar():
        if not geheim.pruefe_signatur(geheim.kanonisch(inhalt),
                                      daten.get("signatur", "")):
            return _leer()
    return {"quellen": inhalt}


def liste():
    return lade()["quellen"]


def speichere(quellen):
    """Schreibt die Quellen. (ok, meldung)."""
    sauber = []
    for q in quellen or []:
        raum = str(q.get("raum") or "").strip()
        p = str(q.get("pfad") or "").strip()
        if not raum or not p:
            continue
        ok, meldung = pruefe_pfad(p)
        if not ok:
            return False, meldung
        if raum != MUSTER_RAUM and PLATZHALTER in p:
            return False, (f"{PLATZHALTER} ergibt nur bei "
                           f"'{MUSTER_RAUM}' einen Sinn -- ein fester "
                           f"Raum hat nur einen Ordner.")
        if raum == MUSTER_RAUM and PLATZHALTER not in p:
            return False, (f"'{MUSTER_RAUM}' braucht {PLATZHALTER} im "
                           f"Pfad. Ohne ihn zeigten alle "
                           f"persoenlichen Raeume auf denselben Ordner "
                           f"und jeder saehe die Listen aller.")
        sauber.append({"raum": raum, "pfad": p})

    daten = {"quellen": sauber}
    if geheim.verfuegbar():
        daten["signatur"] = geheim.signiere(geheim.kanonisch(sauber))
    try:
        os.makedirs(os.path.dirname(QUELLEN), exist_ok=True)
        vorlaeufig = QUELLEN + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            json.dump(daten, f, indent=1, ensure_ascii=False)
        os.replace(vorlaeufig, QUELLEN)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    return True, f"{len(sauber)} Quelle(n) gespeichert."


# --- AUFLOESEN ---

def aufgeloest(benutzer=None):
    """[(raum, pfad)] mit aufgeloestem Platzhalter.

    benutzer=None loest das Muster fuer ALLE bekannten Nutzer auf -- so
    baut der Verwalter einen Katalog, der jedem seine eigenen Listen
    zeigt und keinem die der anderen. Mit Namen bleibt nur dessen
    eigener uebrig; das braucht die Oberflaeche, wenn sie nur nachsehen
    will, ob fuer diesen einen ueberhaupt etwas da ist.
    """
    import raeume
    aus = []
    for q in liste():
        raum, p = q.get("raum"), q.get("pfad") or ""
        if raum != MUSTER_RAUM:
            aus.append((raum, p))
            continue
        if benutzer:
            namen = [benutzer]
        else:
            try:
                import benutzer as _b
                namen = _b.namen()
            except Exception:
                namen = []
        for name in namen:
            aus.append((raeume.privat_kennung(name),
                        p.replace(PLATZHALTER, _dateiname(name))))
    return aus


def _dateiname(name):
    """Der Nutzername, wie er in einem Pfad stehen darf.

    Nicht kosmetisch: ohne das waere der Platzhalter eine Einladung. Ein
    Nutzer namens "../../etc" ergaebe einen Pfad ausserhalb jeder
    Wurzel, und angelegt wird ein Nutzer von einem Verwalter -- also von
    jemandem, dem man Rechte gegeben hat, aber nicht diese.
    """
    sauber = re.sub(r"[^0-9A-Za-z._-]", "", str(name or "").strip())
    return sauber.strip(".") or "unbekannt"


def fuer_benutzer(benutzer, notzugang=()):
    """[(raum, pfad)] -- nur die Quellen, die dieser Mensch lesen darf."""
    import raeume
    erlaubt = set(raeume.lesbar(benutzer, notzugang=notzugang))
    return [(r, p) for r, p in aufgeloest() if r in erlaubt]


def beschreibung():
    """Ein Satz fuer die Oberflaeche."""
    q = liste()
    if not q:
        return "Keine Listenquellen hinterlegt."
    muster = sum(1 for x in q if x.get("raum") == MUSTER_RAUM)
    fest = len(q) - muster
    teile = []
    if fest:
        teile.append(f"{fest} feste Quelle(n)")
    if muster:
        teile.append("persoenliche Ordner je Nutzer")
    return " und ".join(teile) + "."
