"""Prompt-Vorlagen lesen, pruefen und ablegen.

Die Vorlagen bestimmen, wonach gesucht und wie geantwortet wird. Sie
gehoeren damit zu den Dingen, die man im Betrieb nachschaerft -- und nicht
zu denen, fuer die man sich auf den Server setzt und ein Image neu baut.

Deshalb dieselbe Aufteilung wie beim Glossar: die Fassung im Repository ist
die Vorlage, die eigene liegt unter config/ und damit im eingehaengten
Verzeichnis. Fehlt dort eine Datei, gilt die Vorlage.

Warum die Pruefung: in den Vorlagen stehen Platzhalter, die vor dem Aufruf
ersetzt werden. Verschwindet {CONTEXT_PLATZHALTER} aus dem Antwortprompt,
bekommt das Sprachmodell die gefundenen Abschnitte nicht mehr -- es
antwortet dann aus dem, was es ohnehin zu wissen glaubt, mit erfundenen
Fundstellen und ohne jede Fehlermeldung. Das ist der teuerste Tippfehler,
den diese Anwendung kennt, und deshalb wird er beim Speichern abgelehnt.
"""
import os

import paths

# Je Vorlage: Anzeigename, Zweck, und welche Platzhalter darin vorkommen
# muessen. Optionale duerfen fehlen -- wer kein Glossar benutzt, braucht
# {GLOSSAR} nicht.
VORLAGEN = {
    "system_prompt.txt": {
        "titel": "Antwort",
        "zweck": "Wie geantwortet wird: Rolle, Regeln, Umgang mit Quellen.",
        "pflicht": ("{CONTEXT_PLATZHALTER}",),
        "optional": ("{EXPERT_ROLE}", "{GLOSSAR}"),
    },
    "search_prompt.txt": {
        "titel": "Suchsonden",
        "zweck": "Wonach gesucht wird: aus der Frage werden Suchanfragen.",
        "pflicht": ("{FRAGE}",),
        "optional": ("{HISTORY}", "{GLOSSAR}"),
    },
    "sql_prompt.txt": {
        "titel": "Datenbankabfrage",
        "zweck": "Wie aus der Frage eine lesende SQL-Abfrage wird.",
        "pflicht": ("{SCHEMA}", "{FRAGE}", "{MARKER}"),
        "optional": ("{HINWEIS}", "{HISTORY}"),
    },
}


def vorlage_pfad(name):
    """Die mitgelieferte Fassung, neben dem Code."""
    return os.path.join(paths.BASE_DIR, name)


def eigener_pfad(name):
    """Die bearbeitete Fassung, im eingehaengten Verzeichnis."""
    return os.path.join(paths.CONFIG_DIR, name)


def verfuegbar():
    """Welche Vorlagen diese Installation kennt.

    sql_prompt.txt gibt es nur dort, wo eine Datenbank angebunden ist --
    eine Vorlage anzubieten, die nichts steuert, waere irrefuehrend.
    """
    return [n for n in VORLAGEN
            if os.path.exists(vorlage_pfad(n)) or os.path.exists(eigener_pfad(n))]


def lese(name):
    """(text, eigen) -- eigen sagt, ob die bearbeitete Fassung gilt."""
    p = eigener_pfad(name)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read(), True
        except OSError:
            pass
    try:
        with open(vorlage_pfad(name), "r", encoding="utf-8") as f:
            return f.read(), False
    except OSError:
        return "", False


def pruefe(name, text):
    """(ok, meldung) -- fehlende Pflicht-Platzhalter werden benannt."""
    angaben = VORLAGEN.get(name)
    if not angaben:
        return False, "Unbekannte Vorlage."
    if not text.strip():
        return False, "Die Vorlage darf nicht leer sein."
    fehlend = [p for p in angaben["pflicht"] if p not in text]
    if fehlend:
        return False, ("Es fehlt: " + ", ".join(fehlend) +
                       ". Ohne diesen Platzhalter kommt der Inhalt nicht im "
                       "Prompt an, und die Antwort entsteht ohne ihn -- ohne "
                       "Fehlermeldung.")
    return True, ""


def speichern(name, text):
    """Legt die bearbeitete Fassung ab. (ok, meldung)."""
    ok, meldung = pruefe(name, text)
    if not ok:
        return False, meldung
    try:
        os.makedirs(paths.CONFIG_DIR, exist_ok=True)
        # Erst daneben schreiben, dann umbenennen: bricht der Vorgang ab,
        # steht die alte Fassung noch vollstaendig da.
        ziel = eigener_pfad(name)
        vorlaeufig = ziel + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(vorlaeufig, ziel)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    return True, "Gespeichert. Wirkt ab der naechsten Frage."


def zuruecksetzen(name):
    """Entfernt die bearbeitete Fassung; die Vorlage gilt wieder."""
    p = eigener_pfad(name)
    if not os.path.exists(p):
        return False
    try:
        os.remove(p)
    except OSError:
        return False
    return True
