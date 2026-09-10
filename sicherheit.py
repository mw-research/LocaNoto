"""Die Sicherheitslage auf einem Bildschirm -- ehrlich, nicht beruhigend.

Verschluesselung, die man nicht nachsehen kann, ist eine Behauptung. Hier
steht, was tatsaechlich gilt: wo der Schluessel liegt, ob Klartext neben
dem Geheimtext liegt, ob ein Massenabzug auffiele und wo das Protokoll
landet.

Jede Zeile ist (name, ok, text). ok=False heisst nicht "kaputt", sondern
"hier ist die Zusage schwaecher, als sie aussieht" -- und genau das soll
sichtbar sein, statt in einer README zu stehen, die niemand oeffnet.
"""
import os

import budget
import datentraeger
import paths
import raumschluessel


def _schluesselherkunft():
    if os.getenv("LOCANOTO_SCHLUESSEL_DATEI", "").strip():
        return True, ("Aus einem Secret. Das liegt unter /run/secrets in "
                      "tmpfs -- im Arbeitsspeicher, auf keiner Platte. "
                      "Die dichteste Form: ein kopiertes Volume, ein "
                      "Snapshot, eine ausgebaute Platte enthalten ihn "
                      "nicht.")
    if os.getenv("LOCANOTO_SCHLUESSEL", "").strip():
        return False, ("Aus der Umgebung. Das sieht dichter aus, als es "
                       "ist: der Wert steht meist in der .env und damit "
                       "auf einer Platte -- oft derselben. Dichter waere "
                       "LOCANOTO_SCHLUESSEL_DATEI mit einem Secret.")
    import geheim
    if not raumschluessel.verfuegbar():
        return False, ("Keine Verschluesselung. Der Bestand liegt im "
                       "Klartext -- wer das Datenvolume kopiert, liest "
                       "alles.")
    return True, (f"In {os.path.basename(geheim.SCHLUESSEL_DATEI)} unter "
                  f"dem Konfigurationsverzeichnis. Das ist ein ANDERES "
                  f"Volume als die Daten, und der Abzug nimmt ihn nicht "
                  f"mit. Dichter waere LOCANOTO_SCHLUESSEL als Secret: "
                  f"dann liegt er nirgends.")


def _index_getrennt():
    """Liegt der Klartext-Stichwortindex neben dem Geheimtext?

    Der wichtigste Punkt dieser Liste. FTS5 braucht Klartext -- der Index
    ist ableitbar und gehoert deshalb auf containerlokalen Speicher.
    Faellt LOCANOTO_INDEX auf LOCANOTO_DATEN zurueck (die Vorgabe!), liegt
    er neben der verschluesselten Sammlung, und die Verschluesselung ist
    Theater: wer das Volume kopiert, liest den Text aus dem Index.
    """
    getrennt = (os.path.abspath(paths.INDEX_DIR)
                != os.path.abspath(paths.DATA_DIR))
    if getrennt:
        return True, (f"Stichwortindex unter {paths.INDEX_DIR} -- getrennt "
                      f"von den Daten. Richtig so: er traegt den Text im "
                      f"Klartext, weil FTS5 nicht anders kann.")
    return False, (
        "Der Stichwortindex liegt IM Datenverzeichnis und traegt den Text "
        "im Klartext. Damit ist die Verschluesselung der Sammlung ohne "
        "Wirkung: wer das Volume kopiert, liest den Index. Setze "
        "LOCANOTO_INDEX auf einen containerlokalen Pfad -- der Index baut "
        "sich dort in Sekunden neu auf (18.600 Abschnitte je Sekunde).")


def _traeger(name, pfad):
    """Liegt dieses Verzeichnis auf einem verschluesselten Datentraeger?

    Der erste Punkt der Liste, weil er die Grundlage ist: was die
    Anwendung selbst verschluesselt, ist die zweite Schicht darueber.
    Die Originaldokumente, die Vektoren und der Stichwortindex lassen
    sich nicht verdecken -- sie muessen lesbar sein, damit gearbeitet
    werden kann. Ist die Platte offen, liest sie, wer sie ausbaut.

    "unklar" gilt hier als NICHT erfuellt. Eine Zusicherung, die auf
    Nichtwissen beruht, ist schlechter als keine: nach ihr richtet sich
    jemand.
    """
    zustand, meldung = datentraeger.lage(pfad)
    return zustand == "ja", f"{name}: {meldung}"


def _vektoren():
    return False, (
        "Die Vektoren sind NICHT verschluesselt und koennen es nicht sein "
        "-- sonst gibt es keine Aehnlichkeitssuche. Aus ihnen laesst sich "
        "mit demselben Modell ein guter Teil des Textes rekonstruieren. "
        "Wer das Datenvolume hat, hat also nie nichts. Dagegen hilft nur "
        "ein verschluesselter Datentraeger.")


def _laufender_server():
    return False, (
        "Gegen einen Angreifer AUF DEM LAUFENDEN SERVER hilft nichts "
        "davon: die Anwendung muss entschluesseln, um zu antworten. Was "
        "bleibt, ist das Zaehlen -- ein Massenabzug bricht ab und wird "
        "protokolliert.")


def lage():
    """[(name, ok, text)] -- der ganze Stand, ohne Beschoenigung."""
    zeilen = []
    zeilen.append(("Datentraeger verschluesselt",)
                  + _traeger("Daten", paths.DATA_DIR))
    an = raumschluessel.verfuegbar()
    zeilen.append((
        "Abschnitte verschluesselt", an,
        (f"Ja, je Raum ein eigener Schluessel "
         f"({len(raumschluessel.bekannt())} vergeben). Ein geleakter "
         f"Raumschluessel oeffnet die anderen nicht.")
        if an else
        "Nein -- das Paket cryptography fehlt oder kein Schluessel."))
    zeilen.append(("Installationsschluessel",) + _schluesselherkunft())
    zeilen.append(("Klartext getrennt",) + _index_getrennt())
    zeilen.append(("Vektoren",) + _vektoren())

    ok_ziel, text_ziel = budget.ziel_erreichbar()
    zeilen.append(("Entnahmebudget", budget.AKTIV,
                   budget.beschreibung() if budget.AKTIV else
                   "Aus. Ein Massenabzug faellt damit nicht auf."))
    zeilen.append(("Protokoll nach aussen", ok_ziel, text_ziel))
    zeilen.append(("Laufender Server",) + _laufender_server())
    return zeilen


def kurz():
    """Eine Zeile fuer die Seitenleiste."""
    z = lage()
    offen = [n for n, ok, _t in z if not ok]
    if not offen:
        return "alle Punkte erfuellt"
    return f"{len(offen)} von {len(z)} Punkten offen: " + ", ".join(offen)
