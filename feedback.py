"""Rueckmeldungen zu Antworten -- was gefehlt hat und was gewirkt hat.

Der Zweck ist nicht Statistik, sondern eine Arbeitsliste. Welche Begriffe
im Betrieb gebraucht werden und im Bestand fehlen, laesst sich nicht
ausdenken: die Frage "was passiert bei einer BANF" lief ins Leere, weil das
Handbuch "Bestellanforderung" schreibt -- und darauf kommt niemand, der
sich ein Glossar am Schreibtisch ueberlegt.

Also umgekehrt: aufschreiben, was tatsaechlich gefragt wurde und keine
Antwort fand. Nach ein paar Wochen Betrieb stehen dort die zwanzig Begriffe,
die den Grossteil der Fehlschlaege ausmachen; die restlichen tausend
Fachwoerter braucht niemand.

Drei Anlaesse werden festgehalten:

  leer          die Suche fand nichts -- ohne Zutun des Nutzers vermerkt
  daumen_runter der Nutzer sagt, die Antwort taugte nicht
  daumen_hoch   der Nutzer sagt, sie war gut

Die Zustimmung ist nicht Beifall, sondern die andere Haelfte der Auskunft:
sie zeigt, welche Fragen der Bestand gut traegt. Nur die Fehlschlaege zu
kennen sagt nichts darueber, ob eine Aenderung etwas verbessert oder nur
verschoben hat.

Eine Zeile je Ereignis (JSON Lines), angehaengt. Zwei Prozesse -- die
Oberflaeche und die Schnittstelle -- schreiben in dieselbe Datei; das
Anhaengen kurzer Zeilen ist dafuer der unempfindlichste Weg.
"""
import json
import os
from datetime import datetime, timezone

import paths

DATEI = os.path.join(paths.DATA_DIR, "feedback.jsonl")

ARTEN = ("leer", "daumen_hoch", "daumen_runter")

# Obergrenze fuer die Anzeige. Die Datei selbst waechst weiter -- sie ist
# das Protokoll, die Anzeige nur der Blick darauf.
ANZEIGE_GRENZE = paths.env_int("FEEDBACK_ANZEIGE", 50)


def notiere(art, benutzer, frage, sonden=(), zahlen=None, quellen=(),
            herkunft="oberflaeche"):
    """Haelt ein Ereignis fest. Scheitert nie lautstark.

    Eine Rueckmeldung ist Beiwerk: wenn sie sich nicht schreiben laesst --
    Platte voll, Datei gesperrt --, darf das die Antwort nicht kosten, die
    der Nutzer gerade bekommen hat.
    """
    if art not in ARTEN:
        return False
    eintrag = {
        "zeitpunkt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "art": art,
        "benutzer": benutzer,
        "frage": (frage or "")[:2000],
        "sonden": list(sonden)[:10],
        "zahlen": zahlen or {},
        # Nur Datei und Seite, nicht die Abschnitte selbst: die stehen im
        # Bestand und wuerden das Protokoll unbrauchbar gross machen.
        "quellen": [{"file": q.get("file"), "page": q.get("page")}
                    for q in list(quellen)[:20]],
        "herkunft": herkunft,
    }
    try:
        os.makedirs(os.path.dirname(DATEI), exist_ok=True)
        with open(DATEI, "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def lese(grenze=None, art=None):
    """Die letzten Eintraege, neueste zuerst.

    Gelesen wird die ganze Datei. Bei einem Protokoll dieser Groesse ist das
    schneller als jede Buchhaltung darueber -- und es gibt keinen zweiten
    Ort, der mit ihr aus dem Takt geraten koennte.
    """
    grenze = ANZEIGE_GRENZE if grenze is None else grenze
    if not os.path.exists(DATEI):
        return []
    eintraege = []
    try:
        with open(DATEI, "r", encoding="utf-8", errors="replace") as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    e = json.loads(zeile)
                except json.JSONDecodeError:
                    # Eine abgebrochene Zeile -- etwa bei einem Absturz
                    # mitten im Schreiben. Sie kostet einen Eintrag, nicht
                    # das Protokoll.
                    continue
                if art and e.get("art") != art:
                    continue
                eintraege.append(e)
    except OSError:
        return []
    return list(reversed(eintraege))[:grenze]


def zaehle():
    """Anzahl je Art -- fuer die Uebersicht."""
    zahlen = {a: 0 for a in ARTEN}
    for e in lese(grenze=10 ** 9):
        art = e.get("art")
        if art in zahlen:
            zahlen[art] += 1
    return zahlen
