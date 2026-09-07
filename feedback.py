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

Eine Zeile je Ereignis, angehaengt. Zwei Prozesse -- die Oberflaeche und
die Schnittstelle -- schreiben in dieselbe Datei; das Anhaengen kurzer
Zeilen ist dafuer der unempfindlichste Weg.

Jede Zeile ist verschluesselt (siehe geheim.py) und base64-kodiert, damit
sie eine Zeile bleibt. Das ist nicht uebertrieben: hier stehen die Fragen
der Mitarbeiter im Wortlaut, mit Namen daneben. Wer nur die Chats
verschluesselt und diese Datei offen liegen laesst, hat eine Mitschrift
derselben Fragen an einer zweiten Stelle.

Alte, unverschluesselte Zeilen werden weiter gelesen -- eine Umstellung
soll das Protokoll nicht abschneiden.
"""
import base64
import json
import os
from datetime import datetime, timezone

import geheim
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
        roh = json.dumps(eintrag, ensure_ascii=False).encode("utf-8")
        zeile = base64.b64encode(geheim.verschluessele(roh)).decode("ascii")
        with open(DATEI, "a", encoding="utf-8") as f:
            f.write(zeile + "\n")
        return True
    except OSError:
        return False


def _zeile_lesen(zeile):
    """Eine Protokollzeile zu einem Eintrag. None, wenn unlesbar.

    Beide Formen: verschluesselt und base64-kodiert, oder eine alte Zeile
    im Klartext. Erkannt wird das an der Zeile selbst, nicht an einem
    Schalter -- eine Datei hat nach der Umstellung beides.
    """
    if zeile.startswith("{"):
        try:
            return json.loads(zeile)
        except json.JSONDecodeError:
            return None
    try:
        roh = geheim.entschluessele(base64.b64decode(zeile, validate=True))
        return json.loads(roh.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def als_text(grenze=10 ** 9):
    """Das Protokoll als lesbares JSON Lines -- fuer den Download.

    Entschluesselt, weil ein Verwalter, der es herunterlaedt, es auswerten
    will. Die Verschluesselung schuetzt die Datei auf der Platte, nicht die
    Auskunft an den, der sie ohnehin auf dem Bildschirm sieht.
    """
    zeilen = [json.dumps(e, ensure_ascii=False)
              for e in reversed(lese(grenze=grenze))]
    return ("\n".join(zeilen) + "\n").encode("utf-8") if zeilen else b""


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
                e = _zeile_lesen(zeile)
                if e is None:
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


def klartextzeilen():
    """Wie viele Zeilen noch unverschluesselt daliegen."""
    if not os.path.exists(DATEI):
        return 0
    offen = 0
    try:
        with open(DATEI, "r", encoding="utf-8", errors="replace") as f:
            for zeile in f:
                if zeile.strip().startswith("{"):
                    offen += 1
    except OSError:
        return 0
    return offen


def neu_verschluesseln():
    """Schreibt das Protokoll vollstaendig verschluesselt neu.

    Fuer den Umstieg: bestehende Zeilen bleiben sonst im Klartext liegen und
    werden nur weiter gelesen. Die Reihenfolge bleibt, der Inhalt bleibt --
    was sich aendert, ist die Form auf der Platte.

    Rueckgabe: (ok, Anzahl neu geschriebener Zeilen).
    """
    if not os.path.exists(DATEI):
        return True, 0
    eintraege = list(reversed(lese(grenze=10 ** 9)))
    if not eintraege:
        return True, 0
    vorlaeufig = DATEI + ".neu"
    try:
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            for e in eintraege:
                roh = json.dumps(e, ensure_ascii=False).encode("utf-8")
                f.write(base64.b64encode(
                    geheim.verschluessele(roh)).decode("ascii") + "\n")
        os.replace(vorlaeufig, DATEI)
    except OSError:
        return False, 0
    return True, len(eintraege)


def archiviere():
    """Legt das Protokoll beiseite und beginnt ein neues.

    Bewusst kein Loeschen. Die Liste haelt fest, was Nutzer nicht gefunden
    haben -- fragt in einem halben Jahr jemand, ob der Bestand besser
    geworden ist, ist sie die einzige Quelle, die das beantwortet. Die
    Arbeitsliste soll leer werden, nicht die Ueberlieferung.

    Rueckgabe: Pfad der Ablage, oder None wenn nichts abzulegen war.
    """
    if not os.path.exists(DATEI) or os.path.getsize(DATEI) == 0:
        return None
    stamm, endung = os.path.splitext(DATEI)
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ziel = f"{stamm}-{tag}{endung}"
    # Zweimal am selben Tag ist kein Fehler, aber auch kein Grund, die erste
    # Ablage zu ueberschreiben.
    n = 2
    while os.path.exists(ziel):
        ziel = f"{stamm}-{tag}-{n}{endung}"
        n += 1
    try:
        os.replace(DATEI, ziel)
    except OSError:
        return None
    return ziel


def ablagen():
    """Die bereits beiseitegelegten Protokolle, neueste zuerst."""
    ordner = os.path.dirname(DATEI)
    stamm = os.path.basename(os.path.splitext(DATEI)[0]) + "-"
    if not os.path.isdir(ordner):
        return []
    return sorted((d for d in os.listdir(ordner)
                   if d.startswith(stamm) and d.endswith(".jsonl")),
                  reverse=True)


def zaehle():
    """Anzahl je Art -- fuer die Uebersicht."""
    zahlen = {a: 0 for a in ARTEN}
    for e in lese(grenze=10 ** 9):
        art = e.get("art")
        if art in zahlen:
            zahlen[art] += 1
    return zahlen
