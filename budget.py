"""Wie viel darf in einer Stunde entschluesselt werden -- und wer merkt es.

Gegen einen Angreifer auf dem laufenden Server hilft Verschluesselung
nicht: der Prozess muss entschluesseln, um zu antworten, und wer den
Prozess hat, hat den Klartext. Das ist keine Luecke in der Umsetzung,
das ist Arithmetik.

Was geht, ist das Abziehen LAUT und LANGSAM zu machen statt unmoeglich.
Eine Frage kostet gut hundert Abschnitte je Raum. Wer den Bestand
ausleert, braucht Zehntausende aus allen. Der Unterschied ist so gross,
dass eine Schwelle dazwischen passt, ohne dem Betrieb im Weg zu stehen --
vorausgesetzt, sie ist an dem ausgerichtet, was eine Frage WIRKLICH
kostet. Siehe die Rechnung bei MAX_ABSCHNITTE; die erste Fassung lag um
den Faktor neun daneben und brach mitten im Betrieb ab.

Gezaehlt wird in einem gleitenden Fenster:

    ABSCHNITTE   wie viele entschluesselt wurden -- JE RAUM
    RAEUME       wie viele VERSCHIEDENE dabei geoeffnet wurden

Die erste Zahl gilt je Raum und nicht ueber alle summiert. Sonst
verkuerzt jede zusaetzliche Leseberechtigung die Reichweite: dieselbe
Frage kostet bei fuenf Raeumen das Fuenffache, und die Schwelle reisst
nach einem Fuenftel der Fragen. Wer mehr darf, koennte weniger
arbeiten -- und eine Schwelle, die den Berechtigtsten zuerst trifft,
schuetzt nichts, sie stoert nur.

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

# Schwellen je Fenster. Sie sollen einen Abzug treffen und keinen
# fleissigen Menschen.
#
# DIE ERSTE FASSUNG TRAF DEN FLEISSIGEN MENSCHEN. Sie stand bei 4.000
# und rechnete mit "zwoelf Abschnitten je Frage", also rund 300 Fragen
# in der Stunde. Die Annahme war falsch. Was eine Frage wirklich kostet,
# steht in pipeline.suche:
#
#     breit = max(10, top_k * 3)        36 Kandidaten bei TOP_K=12
#     mal drei Sonden                   die Suche fragt mehrfach
#
# Das sind 108 Abschnitte je Frage und Raum, nicht zwoelf. Die Schwelle
# lag damit bei 37 Fragen in der Stunde statt bei 300. Gemessen, nicht
# geschaetzt: im Lasttest brach sie nach genau 37 Fragen, bei 3.996
# gebuchten Abschnitten.
#
# Die Zahl gilt JE RAUM, seit je Raum gezaehlt wird. Vorher lief die
# Summe ueber alle Raeume, und dann kostete dieselbe Frage bei fuenf
# Raeumen das Fuenffache -- die Schwelle traf den zuerst, der am
# meisten lesen durfte.
#
# DER NEUE WERT KOMMT VON DER ANDEREN SEITE. Eine Antwort braucht rund
# 35 Sekunden. Mehr als etwa hundert Fragen in der Stunde kann ein
# Mensch also gar nicht stellen, und das nur, wenn er zwischen den
# Antworten weder liest noch nachdenkt. Hundert Fragen sind rund 11.000
# Abschnitte. 20.000 liegt sicher darueber und ist von keinem Menschen
# an einer Tastatur zu erreichen.
#
# Weich wird der Schutz dadurch nicht: ein Skript mit acht parallelen
# Anfragen schafft gemessene 11 Fragen je Minute, also gut 1.200
# Abschnitte. Es reisst die Schwelle nach etwa siebzehn Minuten -- lange
# bevor ein Bestand von Bedeutung draussen ist. Der Tausch ist eindeutig
# richtig: sie trifft seltener den Falschen und immer noch den Richtigen.
FENSTER_MINUTEN = paths.env_int("BUDGET_FENSTER_MINUTEN", 60)
MAX_ABSCHNITTE = paths.env_int("BUDGET_ABSCHNITTE", 20000)
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


def stand(benutzer=None, raum=None):
    """(abschnitte, raeume) im laufenden Fenster.

    Ohne raum ist die erste Zahl der GROESSTE Raum und nicht die Summe:
    gezaehlt wird je Raum, also ist der groesste der, der als naechstes
    an die Schwelle stoesst. Eine Summe stuende neben MAX_ABSCHNITTE und
    liesse die Anzeige naeher am Limit aussehen, als sie ist.
    """
    with _sperre:
        jetzt = _jetzt()
        _aufraeumen(jetzt)
        passend = [e for e in _ereignisse
                   if benutzer is None or e[1] == benutzer]
        raeume_ = {e[2] for e in passend}
        if raum is not None:
            return sum(e[3] for e in passend if e[2] == raum), len(raeume_)
        je_raum = [sum(e[3] for e in passend if e[2] == r) for r in raeume_]
        return (max(je_raum) if je_raum else 0), len(raeume_)


def zaehle(benutzer, raum, anzahl, wartung=False):
    """Bucht eine Entnahme. Wirft Ueberzogen, wenn die Schwelle reisst.

    Gezaehlt wird JE NUTZER und nicht insgesamt: sonst brechen zwanzig
    fleissige Kollegen gemeinsam eine Schwelle, die fuer einen gedacht
    war, und die Anwendung steht mitten am Vormittag.

    Die Menge zaehlt zusaetzlich JE RAUM. Sonst trifft dieselbe Schwelle
    denjenigen zuerst, der am meisten lesen darf -- siehe den Kopf des
    Moduls. Die Breite bleibt ueber alle Raeume gezaehlt; genau sie ist
    das Zeichen, auf das es ankommt.
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
    # "20.000 Abschnitte aufgeschlossen, Grund: Indexaufbau" und kann
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
        summe = sum(e[3] for e in eigene if e[2] == raum)
        raeume_ = len({e[2] for e in eigene})

    zu_viel = None
    if MAX_ABSCHNITTE and summe > MAX_ABSCHNITTE:
        zu_viel = (f"{summe} Abschnitte aus '{raum}' in "
                   f"{FENSTER_MINUTEN} Minuten "
                   f"(Schwelle {MAX_ABSCHNITTE} je Raum)")
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
    teile = [f"{a}/{MAX_ABSCHNITTE} Abschnitte (groesster Raum)",
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
