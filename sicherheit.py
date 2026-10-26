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
        return True, ("Aus einem Secret (/run/secrets, nur im Arbeitsspeicher). Sicherste Form.")
    if os.getenv("LOCANOTO_SCHLUESSEL", "").strip():
        return False, ("Aus der Umgebung (meist .env auf derselben Platte). Sicherer: LOCANOTO_SCHLUESSEL_DATEI mit einem Secret.")
    import geheim
    if not raumschluessel.verfuegbar():
        return False, ("Keine Verschlüsselung: Wer das Datenvolume kopiert, liest alles.")
    return True, (f'In {os.path.basename(geheim.SCHLUESSEL_DATEI)} im Konfigurationsverzeichnis – getrennt von den Daten und nicht im Abzug. Sicherer: LOCANOTO_SCHLUESSEL als Secret.')


def _index_getrennt():
    """Liegt der Klartext-Stichwortindex neben dem Geheimtext?

    Der wichtigste Punkt dieser Liste. FTS5 braucht Klartext -- der Index
    ist ableitbar und gehoert deshalb auf containerlokalen Speicher.
    Faellt LOCANOTO_INDEX auf LOCANOTO_DATEN zurueck (die Vorgabe!), liegt
    er neben der verschluesselten Sammlung, und die Verschluesselung ist
    Theater: wer das Volume kopiert, liest den Text aus dem Index.
    """
    import keyword_index
    wo = keyword_index.STICHWORT_DIR
    getrennt = (os.path.abspath(wo) != os.path.abspath(paths.DATA_DIR)
                and not os.path.abspath(wo).startswith(
                    os.path.abspath(paths.DATA_DIR) + os.sep))
    if getrennt:
        return True, (f'Stichwortindex unter {wo}, getrennt von den Daten und im Klartext (FTS5).')
    return False, (
        "Stichwortindex liegt im Datenverzeichnis und enthält Klartext – Verschlüsselung wirkungslos. LOCANOTO_STICHWORTINDEX auf einen containerlokalen Pfad setzen.")


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
        "Vektoren sind nicht verschlüsselt und verraten viel vom Text – dagegen hilft nur ein verschlüsselter Datenträger.")


def _laufender_server():
    return False, (
        "Gegen Angreifer auf dem laufenden Server hilft das nicht; Massenabzüge werden aber abgebrochen und protokolliert.")


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
