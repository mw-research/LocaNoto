"""Lange Laeufe aus der Oberflaeche anstossen und beobachten.

Eine Bildbeschreibung dauert Minuten, ein vollstaendiger Ingest Stunden.
Beides im Streamlit-Ablauf auszufuehren hiesse, den Nutzer vor einem
Fortschrittsbalken sitzen zu lassen, der eine Sitzung nicht ueberlebt --
ein Seitenwechsel, ein Neuladen, und der Lauf ist weg.

Deshalb als eigener Prozess, so wie man ihn sonst von Hand startet. Er
haengt an nichts: die Oberflaeche darf neu laden, der Nutzer darf sich
abmelden, der Lauf laeuft weiter und schreibt in seine Protokolldatei.

Was hier NICHT passiert: eine Warteschlange, mehrere gleichzeitige Laeufe,
Wiederaufnahme nach einem Neustart des Containers. Wer das braucht, braucht
einen Arbeiter neben der Anwendung -- und der ist etwas anderes als ein
Knopf.
"""
import os
import subprocess
import sys

import paths

# name -> (Skript, Protokoll, Beschriftung)
LAEUFE = {
    "bilder": ("ingest_images.py", "ingest_images.log",
               "Bilder nachtragen"),
    "text": ("ingest.py", "ingest.log",
             "Dokumente neu einlesen"),
}


def _pid_datei(name):
    return os.path.join(paths.DATA_DIR, f"lauf_{name}.pid")


def protokoll_pfad(name):
    return os.path.join(paths.DATA_DIR, LAEUFE[name][1])


def laeuft(name):
    """Laeuft dieser Lauf gerade? Raeumt eine verwaiste Kennung auf."""
    p = _pid_datei(name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        # Signal 0 prueft nur, ob der Prozess existiert.
        os.kill(pid, 0)
        return True
    except OSError:
        # Der Lauf ist beendet oder abgestuerzt. Die Kennung bleibt sonst
        # liegen und blockiert jeden weiteren Start.
        try:
            os.remove(p)
        except OSError:
            pass
        return False


def starte(name):
    """Startet den Lauf abgekoppelt. (ok, meldung)."""
    if name not in LAEUFE:
        return False, "Unbekannter Lauf."
    if laeuft(name):
        return False, "Laeuft bereits."

    skript, _, _ = LAEUFE[name]
    pfad = os.path.join(paths.BASE_DIR, skript)
    if not os.path.exists(pfad):
        return False, f"{skript} nicht gefunden."

    try:
        log = open(protokoll_pfad(name), "w", encoding="utf-8")
    except OSError as e:
        return False, f"Protokoll nicht schreibbar: {e}"

    try:
        # -u, damit das Protokoll mitwaechst statt erst am Ende zu
        # erscheinen. start_new_session loest den Prozess von der
        # Oberflaeche: laedt sie neu, laeuft er weiter.
        vorgang = subprocess.Popen(
            [sys.executable, "-u", skript],
            cwd=paths.BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    except OSError as e:
        log.close()
        return False, f"Konnte nicht gestartet werden: {e}"

    try:
        with open(_pid_datei(name), "w", encoding="utf-8") as f:
            f.write(str(vorgang.pid))
    except OSError:
        pass
    return True, "Gestartet."


def abbrechen(name):
    """Beendet den Lauf. Bereits Geschriebenes bleibt erhalten."""
    p = _pid_datei(name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)
    except (OSError, ValueError):
        return False
    try:
        os.remove(p)
    except OSError:
        pass
    return True


def protokoll(name, zeilen=15):
    """Die letzten Zeilen des Protokolls."""
    try:
        with open(protokoll_pfad(name), "r", encoding="utf-8",
                  errors="replace") as f:
            return "".join(f.readlines()[-zeilen:])
    except OSError:
        return ""
