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
    if p.startswith("owncloud:"):
        # Eine Quelle in der angebundenen Instanz. Die Wurzeln und die
        # Sperre auf die eigenen Verzeichnisse gelten hier nicht: es
        # ist kein Dateisystempfad, und was das Dienstkonto dort
        # erreicht, entscheidet ownCloud.
        import owncloud
        if not owncloud.eingerichtet():
            return False, ("Fuer eine ownCloud-Quelle muss die Anbindung "
                           "eingerichtet sein (OWNCLOUD_URL, "
                           "OWNCLOUD_USER, OWNCLOUD_PASSWORT).")
        if not p[len("owncloud:"):].strip("/"):
            return False, "Kein Pfad hinter 'owncloud:'."
        return True, ""

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

    fehler = _ueberlappung(sauber)
    if fehler:
        return False, fehler

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

def _feste_wurzel(p):
    """Der Teil eines Pfades vor dem Platzhalter.

    Fuer ein Muster ist das der Ordner, unter dem ALLE persoenlichen
    Ordner liegen -- also der Bereich, den dieses eine Muster belegt.
    """
    kopf = (p or "").split(PLATZHALTER, 1)[0]
    kopf = kopf.rstrip("/").rstrip("\\")
    try:
        return os.path.realpath(kopf) if kopf else ""
    except OSError:
        return kopf


def _enthaelt(oben, unten):
    return bool(oben) and (unten == oben or unten.startswith(oben + os.sep))


def _ueberlappung(quellen):
    """Liegt eine Quelle in einer anderen? Meldung, sonst "".

    Der Fall, um den es geht, ist nicht ausgedacht: wer

        allgemein = /mnt/heim
        @privat   = /mnt/heim/{benutzer}/Listen

    eintraegt, hat die persoenlichen Ordner ALLER in den allgemeinen
    Raum gelegt -- jeder sieht dann jede persoenliche Liste, und die
    zweite Zeile daneben sieht so aus, als sei alles geregelt.

    Das faellt nicht auf: es gibt keine Fehlermeldung, die Listen
    erscheinen, und dass sie bei den Falschen erscheinen, sieht nur
    der, dem sie gehoeren -- und der sieht sie ja auch bei sich.

    Auch bei GLEICHEM Raum abgelehnt. Dann waere es kein
    Berechtigungsfehler, aber jede Datei stuende zweimal im Katalog,
    und das Modell bekaeme dieselbe Liste doppelt zur Auswahl.
    """
    import raeume
    for i, a in enumerate(quellen):
        for b in quellen[i + 1:]:
            # Das Muster und ein einzelner persoenlicher Raum liegen
            # zwangslaeufig ineinander -- der eigene Eintrag steht ja
            # im eigenen Bereich. Das ist kein Konflikt, sondern eine
            # UEBERSTEUERUNG: wer seinen Ordner selbst eintraegt,
            # bekommt ihn statt des Musters.
            arten = {a["raum"], b["raum"]}
            if MUSTER_RAUM in arten and any(
                    raeume.ist_privat(r) for r in arten):
                continue
            oben, unten = _feste_wurzel(a["pfad"]), _feste_wurzel(b["pfad"])
            if _enthaelt(oben, unten) or _enthaelt(unten, oben):
                if a["raum"] == b["raum"]:
                    return (f"'{a['pfad']}' und '{b['pfad']}' liegen "
                            f"ineinander. Jede Datei stuende zweimal im "
                            f"Katalog -- der aeussere Ordner genuegt.")
                return (f"'{b['pfad']}' liegt in '{a['pfad']}'. Damit "
                        f"laesen die Dateien des inneren Ordners AUCH "
                        f"unter '{a['raum']}' -- die Trennung waere "
                        f"aufgehoben, ohne dass es auffiele. Die Ordner "
                        f"muessen nebeneinanderliegen.")
    return ""


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
    eigene = {q.get("raum") for q in liste()
              if raeume.ist_privat(str(q.get("raum") or ""))}
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
            kennung = raeume.privat_kennung(name)
            if kennung in eigene:
                # Dieser Nutzer hat seinen Ordner selbst eingetragen.
                # Beides zu nehmen ergaebe jede Datei zweimal im
                # Katalog -- und zwar in demselben Raum, also ohne dass
                # es als Doppelung auffiele.
                continue
            aus.append((kennung, p.replace(PLATZHALTER, _dateiname(name))))
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


# --- EINE QUELLE JE RAUM, DORT WO DER RAUM ENTSTEHT ---
#
# Der Textblock in den Einstellungen ist der Weg fuer jemanden, der
# alle Quellen auf einmal sieht. Im Betrieb entsteht eine Quelle aber
# nicht dort, sondern beim Anlegen eines Raums: wer "Einkauf"
# einrichtet, weiss in diesem Moment, wo dessen Listen liegen -- und
# nur dann. Muss er es sich fuer spaeter merken, bleibt das Feld leer.
#
# WER WAS SETZEN DARF, und warum das nicht gleich ist:
#
# Der Container liest mit EINER Kennung. Duerfte jeder einen
# beliebigen Pfad eintragen, koennte er den Ordner einer fremden
# Abteilung eintragen -- die Anwendung hat die Rechte und prueft nur,
# was jemand tippt. Deshalb:
#
#   Verwalter   jeder Pfad unterhalb von LISTEN_WURZELN
#   Nutzer      nur innerhalb seines EIGENEN Bereichs, also unterhalb
#               des Ordners, den das Muster fuer ihn ergibt
#
# Damit kann jemand seinen persoenlichen Ordner umbenennen oder einen
# Unterordner waehlen -- aber nicht in den Bereich eines anderen
# zeigen. Das ist der Unterschied zwischen "meine Ablage anpassen" und
# "mir Zugriff geben".


def eigener_bereich(benutzer):
    """Der Ordner, den das Muster fuer diesen Nutzer ergibt. "" ohne Muster."""
    for q in liste():
        if q.get("raum") == MUSTER_RAUM:
            p = (q.get("pfad") or "").replace(PLATZHALTER,
                                              _dateiname(benutzer))
            try:
                return os.path.realpath(p)
            except OSError:
                return p
    return ""


def darf_setzen(raum, benutzer, ist_verwalter=False):
    """(ok, meldung) -- darf dieser Mensch die Quelle dieses Raums setzen?"""
    import raeume
    if ist_verwalter:
        return True, ""
    if raum == raeume.privat_kennung(benutzer):
        return True, ""
    return False, ("Die Quelle eines gemeinsamen Raums setzt ein "
                   "Verwalter. Deinen eigenen Ordner kannst du selbst "
                   "eintragen.")


def setze_raum(raum, pfad, benutzer="?", ist_verwalter=False):
    """Traegt die Quelle EINES Raums ein oder entfernt sie. (ok, meldung).

    Leerer Pfad heisst: Eintrag weg. Das ist kein Sonderfall, sondern
    der Normalfall beim Abschalten -- ein Raum ohne Listenordner ist
    zulaessig.
    """
    import raeume
    darf, grund = darf_setzen(raum, benutzer, ist_verwalter)
    if not darf:
        return False, grund

    quellen = [q for q in liste() if q.get("raum") != raum]
    pfad = (pfad or "").strip()
    if not pfad:
        ok, meldung = speichere(quellen)
        return ok, ("Quelle entfernt." if ok else meldung)

    if PLATZHALTER in pfad and raum != MUSTER_RAUM:
        return False, (f"{PLATZHALTER} gehoert zum Muster fuer die "
                       f"persoenlichen Raeume, nicht zu einem einzelnen.")

    # Ein Nutzer darf nur in seinem eigenen Bereich bleiben. Geprueft
    # wird der AUFGELOESTE Pfad: "meinordner/../../fremd" sieht sonst
    # harmlos aus.
    if not ist_verwalter and not raeume.ist_privat(raum):
        return False, "Nur Verwalter."
    if not ist_verwalter:
        bereich = eigener_bereich(benutzer)
        try:
            echt = os.path.realpath(pfad)
        except OSError:
            echt = pfad
        if not bereich:
            return False, ("Fuer persoenliche Ordner ist kein Muster "
                           "hinterlegt. Ein Verwalter traegt es einmal "
                           "ein, danach kannst du deinen Ordner selbst "
                           "waehlen.")
        if not _enthaelt(bereich, echt):
            return False, (f"Nur innerhalb deines eigenen Bereichs "
                           f"({bereich}). Ein anderer Ordner waere ein "
                           f"Zugriff, den dir niemand gegeben hat.")

    quellen.append({"raum": raum, "pfad": pfad})
    return speichere(quellen)


def pfad_von(raum):
    """Der eingetragene Pfad eines Raums, oder ""."""
    for q in liste():
        if q.get("raum") == raum:
            return q.get("pfad") or ""
    return ""


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
