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

import dateisperre
import geheim
import paths
import presets

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
    "tabellen_prompt.txt": {
        "titel": "Listenabfrage",
        "zweck": "Welche Liste zur Frage passt und wie darin gesucht wird.",
        "pflicht": ("{KATALOG}", "{FRAGE}", "{MARKER}"),
        "optional": ("{HISTORY}",),
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


def eigener_pfad(name, preset=None):
    """Die bearbeitete Fassung.

    Mit preset gehoert sie zu einer Voreinstellung, sonst gilt sie fuer die
    ganze Installation.
    """
    if preset and not presets.ist_eigene(preset):
        return os.path.join(presets.ORDNER, preset, name)
    return os.path.join(paths.CONFIG_DIR, name)


def verfuegbar():
    """Welche Vorlagen diese Installation kennt.

    sql_prompt.txt gibt es nur dort, wo eine Datenbank angebunden ist --
    eine Vorlage anzubieten, die nichts steuert, waere irrefuehrend.
    """
    return [n for n in VORLAGEN
            if os.path.exists(vorlage_pfad(n)) or os.path.exists(eigener_pfad(n))]


def lese(name, preset=None):
    """(text, herkunft) -- herkunft ist "preset", "eigen" oder "vorlage".

    Dieselbe Kette wie zur Laufzeit: Voreinstellung, dann config/, dann die
    mitgelieferte Fassung. Wer eine Voreinstellung bearbeitet und dort noch
    keine eigene Fassung hat, bekommt die naechste Stufe vorgelegt -- also
    das, was gerade tatsaechlich gilt.
    """
    stufen = []
    if preset:
        stufen.append((eigener_pfad(name, preset), "preset"))
    stufen.append((eigener_pfad(name), "eigen"))
    stufen.append((vorlage_pfad(name), "vorlage"))
    for pfad, herkunft in stufen:
        if not os.path.exists(pfad):
            continue
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                return f.read(), herkunft
        except OSError:
            continue
    return "", "vorlage"


def pruefe(name, text):
    """(ok, meldung) -- fehlende Pflicht-Platzhalter werden benannt."""
    angaben = VORLAGEN.get(name)
    if not angaben:
        return False, "Unbekannte Vorlage."
    if not text.strip():
        return False, "Vorlage darf nicht leer sein."
    fehlend = [p for p in angaben["pflicht"] if p not in text]
    if fehlend:
        return False, ("Es fehlt: " + ", ".join(fehlend) +
                       ". Ohne diesen Platzhalter kommt der Inhalt nicht im "
                       "Prompt an, und die Antwort entsteht ohne ihn -- ohne "
                       "Fehlermeldung.")
    return True, ""


def speichern(name, text, preset=None):
    """Legt die bearbeitete Fassung ab. (ok, meldung)."""
    ok, meldung = pruefe(name, text)
    if not ok:
        return False, meldung
    try:
        # Erst daneben schreiben, dann umbenennen: bricht der Vorgang ab,
        # steht die alte Fassung noch vollstaendig da.
        dateisperre.schreibe_atomar(eigener_pfad(name, preset), text)
    except OSError as e:
        return False, f'Speichern fehlgeschlagen: {e}'
    return True, "Gespeichert. Wirkt ab der nächsten Frage."


def zuruecksetzen(name, preset=None):
    """Entfernt die bearbeitete Fassung; die naechste Stufe gilt wieder."""
    p = eigener_pfad(name, preset)
    if not os.path.exists(p):
        return False
    try:
        os.remove(p)
    except OSError:
        return False
    return True


# --- PERSOENLICHE ANWEISUNG ---
#
# Jeder Nutzer kann LocaNoto sagen, wie er seine Antworten haben will:
# "knapp", "mit Tabellen", "nenne immer die Norm". Die Anweisung wird an
# den Antwortprompt angehaengt -- sie ERGAENZT die Vorlagen und ersetzt
# keine. Was dort an Regeln steht (Quellen nennen, nichts erfinden), gilt
# weiter; widerspricht die Anweisung, sagt der angehaengte Text, was
# vorgeht.
#
# Sie wirkt nur auf die eigenen Antworten. Was gesucht und gefunden wird,
# entscheiden die Raeume, nicht der Prompt -- eine Anweisung kann daran
# nichts aendern.
#
# Abgelegt verschluesselt, wie die Chats: was jemand ueber seine Arbeit
# schreibt, ist so viel Auskunft wie ein Chatverlauf.

ANWEISUNG_MAX = paths.env_int("ANWEISUNG_MAX_ZEICHEN", 2000)


def _anweisung_pfad(benutzer):
    return os.path.join(paths.DATA_DIR, "anweisungen",
                        paths.sicherer_teil(benutzer) + ".txt")


def _anweisung_zusatz(benutzer):
    # Beglaubigt mit dem Namen: eine Datei, die jemand unter einem anderen
    # Namen ablegt, entschluesselt nicht.
    return f"anweisung:{benutzer}".encode("utf-8")


def anweisung(benutzer):
    """Die persoenliche Anweisung dieses Nutzers. "" wenn keine."""
    if not benutzer:
        return ""
    try:
        with open(_anweisung_pfad(benutzer), "rb") as f:
            roh = geheim.entschluessele(f.read(), _anweisung_zusatz(benutzer))
        return roh.decode("utf-8").strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


def anweisung_speichern(benutzer, text):
    """(ok, meldung). Leer heisst: die Anweisung entfernen."""
    text = str(text or "").strip()
    if not text:
        anweisung_loeschen(benutzer)
        return True, "Anweisung entfernt."
    if len(text) > ANWEISUNG_MAX:
        return False, (f'Höchstens {ANWEISUNG_MAX} Zeichen – es sind {len(text)}.')
    roh = geheim.verschluessele(text.encode("utf-8"),
                                _anweisung_zusatz(benutzer))
    dateisperre.schreibe_atomar(_anweisung_pfad(benutzer), roh, 0o600)
    return True, "Gespeichert. Gilt ab der nächsten Frage."


def anweisung_loeschen(benutzer):
    try:
        os.remove(_anweisung_pfad(benutzer))
    except OSError:
        pass


def mit_anweisung(system, benutzer):
    """Der Antwortprompt mit angehaengter Anweisung dieses Nutzers."""
    text = anweisung(benutzer)
    if not text:
        return system
    return (system.rstrip() + "\n\n"
            "## Persoenliche Anweisung dieses Nutzers\n"
            "Der Nutzer wuenscht fuer seine Antworten zusaetzlich das "
            "Folgende. Es ergaenzt die Regeln oben und hebt keine davon "
            "auf; widerspricht es ihnen, gelten die Regeln oben.\n\n"
            + text + "\n")
