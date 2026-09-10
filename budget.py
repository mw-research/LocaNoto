"""Wie viel darf in einer Stunde entschluesselt werden -- und wer merkt es.

Gegen einen Angreifer auf dem laufenden Server hilft Verschluesselung
nicht: der Prozess muss entschluesseln, um zu antworten, und wer den
Prozess hat, hat den Klartext. Das ist keine Luecke in der Umsetzung,
das ist Arithmetik.

Was geht, ist das Abziehen LAUT und LANGSAM zu machen statt unmoeglich.
Eine Frage braucht ein Dutzend Abschnitte aus ein bis drei Raeumen. Wer
den Bestand ausleert, braucht Zehntausende aus allen. Der Unterschied ist
so gross, dass eine Schwelle dazwischen passt, ohne dem Betrieb im Weg zu
stehen.

Gezaehlt wird in einem gleitenden Fenster:

    ABSCHNITTE   wie viele entschluesselt wurden
    RAEUME       wie viele VERSCHIEDENE dabei geoeffnet wurden

Die zweite Zahl ist die aussagekraeftigere. Ein Mitarbeiter, der viel
arbeitet, liest viele Abschnitte aus wenigen Raeumen. Wer alle Raeume
anfasst, tut etwas anderes.

Reisst eine Schwelle, wird abgebrochen und protokolliert -- nicht nur
protokolliert. Ein Alarm, den niemand liest, waehrend der Abzug
weiterlaeuft, ist kein Schutz, sondern eine Notiz.

DAS PROTOKOLL GEHOERT WOANDERSHIN. Auf demselben Server raeumt der
Angreifer es mit auf. PROTOKOLL_ZIEL nimmt einen zweiten Ort:

    PROTOKOLL_ZIEL=/mnt/anderswo/locanoto.log     eine Datei
    PROTOKOLL_ZIEL=udp://protokoll.firma.de:514   syslog
    PROTOKOLL_ZIEL=-                              stdout, fuer den
                                                  Log-Sammler des Clusters

Ohne Ziel bleibt es beim Protokoll neben den Daten. Das ist besser als
nichts und schlechter als ein zweiter Rechner; die Anwendung sagt es.
"""
import json
import os
import socket
import sys
import threading
import time

import paths

# Schwellen je Fenster. Grosszuegig gewaehlt: sie sollen einen Abzug
# treffen und keinen fleissigen Menschen. Gemessen an einer gewoehnlichen
# Frage -- zwoelf Abschnitte, ein bis drei Raeume -- sind 4.000
# Abschnitte rund 300 Fragen in der Stunde.
FENSTER_MINUTEN = paths.env_int("BUDGET_FENSTER_MINUTEN", 60)
MAX_ABSCHNITTE = paths.env_int("BUDGET_ABSCHNITTE", 4000)
MAX_RAEUME = paths.env_int("BUDGET_RAEUME", 25)

# 0 schaltet ab. Ausdruecklich moeglich, weil eine Schwelle, die im
# Betrieb stoert, sonst umgangen statt angepasst wird -- und eine
# umgangene Schwelle ist schlechter als eine abgeschaltete, weil sie
# Sicherheit vortaeuscht.
AKTIV = MAX_ABSCHNITTE > 0 or MAX_RAEUME > 0

ZIEL = os.getenv("PROTOKOLL_ZIEL", "").strip()

_sperre = threading.Lock()
_ereignisse = []          # [(zeit, benutzer, raum, anzahl)]
_gemeldet = {}            # benutzer -> zuletzt gemeldet, damit es nicht spammt


class Ueberzogen(Exception):
    """Das Budget ist aufgebraucht. Der Aufrufer soll abbrechen."""


def _jetzt():
    return time.time()


def _aufraeumen(jetzt):
    grenze = jetzt - FENSTER_MINUTEN * 60
    while _ereignisse and _ereignisse[0][0] < grenze:
        _ereignisse.pop(0)


def stand(benutzer=None):
    """(abschnitte, raeume) im laufenden Fenster."""
    with _sperre:
        jetzt = _jetzt()
        _aufraeumen(jetzt)
        passend = [e for e in _ereignisse
                   if benutzer is None or e[1] == benutzer]
        return sum(e[3] for e in passend), len({e[2] for e in passend})


def zaehle(benutzer, raum, anzahl, wartung=False):
    """Bucht eine Entnahme. Wirft Ueberzogen, wenn die Schwelle reisst.

    Gezaehlt wird JE NUTZER und nicht insgesamt: sonst brechen zwanzig
    fleissige Kollegen gemeinsam eine Schwelle, die fuer einen gedacht
    war, und die Anwendung steht mitten am Vormittag.
    """
    if anzahl <= 0:
        return

    # WARTUNG zaehlt nicht mit, wird aber festgehalten.
    #
    # Die Schwelle trennt "jemand arbeitet" von "jemand raeumt ab". Der
    # Neuaufbau des Stichwortindex ist keins von beidem: er liest den
    # ganzen Bestand, weil das seine Aufgabe ist, und er traegt nichts
    # nach draussen -- der Klartext geht in eine Datei auf derselben
    # Maschine, die ohnehin gleich alles enthaelt.
    #
    # Zaehlte er mit, waere die Folge nicht mehr Sicherheit, sondern
    # eine Anwendung, die bei jedem Bestand ueber 4.000 Abschnitten
    # nicht mehr startet -- und zwar genau dann, wenn der Index fehlt:
    # nach einem Umzug, nach dem Einspielen eines Abzugs, bei einer
    # frischen Installation. Eine Schwelle, die den Normalbetrieb
    # unmoeglich macht, wird abgeschaltet, und dann schuetzt sie nichts
    # mehr.
    #
    # Sie faellt trotzdem nicht unter den Tisch: das Protokoll bekommt
    # den Eintrag mit der vollen Zahl. Wer spaeter nachliest, sieht
    # "20.608 Abschnitte aufgeschlossen, Grund: Indexaufbau" und kann
    # pruefen, ob zu dieser Zeit ein Start stattfand.
    if wartung:
        melde("wartung_klartext", benutzer,
              {"raum": raum, "abschnitte": int(anzahl),
               "grund": "Aufbau des Stichwortindex -- nicht auf das "
                        "Budget angerechnet"})
        return

    if not AKTIV:
        return
    with _sperre:
        jetzt = _jetzt()
        _aufraeumen(jetzt)
        _ereignisse.append((jetzt, benutzer, raum, int(anzahl)))
        eigene = [e for e in _ereignisse if e[1] == benutzer]
        summe = sum(e[3] for e in eigene)
        raeume_ = len({e[2] for e in eigene})

    zu_viel = None
    if MAX_ABSCHNITTE and summe > MAX_ABSCHNITTE:
        zu_viel = (f"{summe} Abschnitte in {FENSTER_MINUTEN} Minuten "
                   f"(Schwelle {MAX_ABSCHNITTE})")
    elif MAX_RAEUME and raeume_ > MAX_RAEUME:
        zu_viel = (f"{raeume_} verschiedene Raeume in {FENSTER_MINUTEN} "
                   f"Minuten (Schwelle {MAX_RAEUME})")
    if not zu_viel:
        return

    melde("budget_ueberzogen", benutzer,
          {"raum": raum, "abschnitte": summe, "raeume": raeume_,
           "grund": zu_viel})
    raise Ueberzogen(
        f"Das Entnahmebudget ist aufgebraucht: {zu_viel}. Die Anwendung "
        f"bricht hier ab und hat es protokolliert. Ist das ein "
        f"berechtigter Lauf -- ein Abzug, eine Auswertung --, hebt "
        f"BUDGET_ABSCHNITTE die Schwelle.")


# --- PROTOKOLL ---

def melde(art, benutzer, angaben=None):
    """Schreibt ein Ereignis -- an das aeussere Ziel UND in die Kette.

    Scheitert nie lautstark: ein nicht erreichbarer Protokollrechner darf
    die Anwendung nicht anhalten. Er darf nur nicht dazu fuehren, dass
    gar nichts festgehalten wird -- deshalb immer auch die Kette
    daneben.
    """
    eintrag = {"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "art": art, "benutzer": benutzer,
               "wirt": socket.gethostname()}
    eintrag.update(angaben or {})
    zeile = json.dumps(eintrag, ensure_ascii=False)

    try:
        import benutzer as _b
        _b.protokolliere(art, str((angaben or {}).get("raum") or "-"),
                         von=benutzer,
                         hinweis=str((angaben or {}).get("grund") or "")[:200])
    except Exception:
        pass
    _nach_aussen(zeile)


def _nach_aussen(zeile):
    if not ZIEL:
        return
    try:
        if ZIEL == "-":
            print("LOCANOTO " + zeile, file=sys.stderr, flush=True)
            return
        if ZIEL.startswith("udp://"):
            wirt, _, hafen = ZIEL[len("udp://"):].partition(":")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # <13> ist user.notice. Kein Anspruch auf vollstaendiges
                # RFC 5424 -- jeder Sammler versteht diese Form.
                s.sendto(("<13>LOCANOTO " + zeile).encode("utf-8")[:1400],
                         (wirt, int(hafen or 514)))
            finally:
                s.close()
            return
        with open(ZIEL, "a", encoding="utf-8") as f:
            f.write(zeile + "\n")
    except Exception:
        # Ein nicht erreichbares Ziel ist kein Grund, die Antwort
        # ausfallen zu lassen. Dass es nicht erreichbar ist, sagt die
        # Oberflaeche unter "Sicherheit".
        pass


def beschreibung():
    """Kurzer Stand fuer die Anzeige."""
    if not AKTIV:
        return "Entnahmebudget: aus"
    a, r = stand()
    teile = [f"{a}/{MAX_ABSCHNITTE} Abschnitte",
             f"{r}/{MAX_RAEUME} Raeume",
             f"Fenster {FENSTER_MINUTEN} min"]
    teile.append("Protokoll nach " + (ZIEL if ZIEL else "NUR neben die Daten"))
    return " · ".join(teile)


def ziel_erreichbar():
    """(ok, meldung) -- laesst sich das aeussere Ziel beschreiben?"""
    if not ZIEL:
        return False, ("Kein aeusseres Protokollziel. Auf demselben Server "
                       "raeumt ein Angreifer das Protokoll mit auf -- "
                       "PROTOKOLL_ZIEL nimmt eine Datei ausserhalb des "
                       "Datenverzeichnisses, ein syslog oder '-' fuer den "
                       "Log-Sammler.")
    if ZIEL == "-":
        return True, "Protokoll nach stdout (Log-Sammler)."
    if ZIEL.startswith("udp://"):
        return True, f"Protokoll nach {ZIEL} (ungeprueft -- UDP antwortet nicht)."
    try:
        with open(ZIEL, "a", encoding="utf-8"):
            pass
    except OSError as e:
        return False, f"{ZIEL} ist nicht beschreibbar: {e}"
    if os.path.abspath(ZIEL).startswith(os.path.abspath(paths.DATA_DIR)):
        return False, (f"{ZIEL} liegt IM Datenverzeichnis. Wer die Daten "
                       f"holt, holt das Protokoll mit -- ein zweiter Ort "
                       f"waere der Sinn.")
    return True, f"Protokoll nach {ZIEL}."
