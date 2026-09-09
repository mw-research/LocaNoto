"""Notzugang zu einem persoenlichen Raum -- von zwei Personen getragen.

Ein persoenlicher Raum gehoert genau einem Nutzer. Kein Verwalter kommt
hinein, auch nicht lesend; er darf ihn nur als Ganzes loeschen. Das ist
richtig, solange der Nutzer erreichbar ist -- und genau dann falsch, wenn
er es nicht mehr ist. Jemand scheidet aus, faellt laenger aus, und in
seiner Ablage liegt das eine Angebot, das die Firma braucht.

Dafuer gibt es hier einen Weg hinein. Er ist absichtlich unbequem:

    1. Ein Verwalter BEANTRAGT den Zugang zu genau einem Raum, mit Grund.
    2. Ein Traeger der Rolle "notzugang" BESTAETIGT ihn -- mit seiner
       eigenen Anmeldung, nicht mit einem Haken beim Verwalter.
    3. Danach gilt er 24 Stunden und erlischt von selbst.

Warum zwei ROLLEN und nicht zwei Verwalter: koennten Verwalter einander
bestaetigen, waere es eine Formalie -- die IT genehmigte sich den Blick in
fremde Ablagen selbst. Die Rolle "notzugang" darf sonst nichts und gehoert
deshalb woandershin: Geschaeftsfuehrung, Personalrat, wer auch immer im
Haus dafuer steht. Zwei Personen, zwei Anmeldungen, beide Namen im
Protokoll.

Warum keine geteilte Losung: ein Geheimnis identifiziert niemanden, laesst
sich weitergeben und ist, wenn es verloren geht, genau dann weg, wenn es
gebraucht wird. Eine Rolle laesst sich entziehen, ein Geheimnis nicht.

DIE EHRLICHE GRENZE. Das hier ist eine Kontrolle IN der Anwendung. Wer den
Server hat, liest die Sammlung eines persoenlichen Raums ohne diese Datei
zu beachten -- die Abschnitte liegen dort im Klartext, weil sie
durchsuchbar sein muessen. Der Notzugang schuetzt also gegen den
Verwalter, der im Alltag klickt, und nicht gegen den, der sich einloggt.
Dagegen hilft nur, wer ueberhaupt Serverzugang hat, und eine
verschluesselte Platte. Das gehoert gesagt, damit niemand die Zusage fuer
groesser haelt, als sie ist.

Die Datei ist mitsigniert (siehe geheim.py). Ohne das genuegte ein
Texteditor auf config/, um sich selbst einen Zugang einzutragen -- und
dann waere der zweite Mensch wieder ueberfluessig.
"""
import json
import os
import time

import benutzer
import geheim
import paths
import raeume

DATEI = os.path.join(paths.CONFIG_DIR, "notzugang.json")

# Wie lange ein bestaetigter Zugang gilt, in Stunden. Lang genug, um in
# Ruhe zu sichten und zu verschieben, kurz genug, dass niemand vergisst,
# dass er offen steht.
STUNDEN = paths.env_int("NOTZUGANG_STUNDEN", 24)

# Wie lange ein unbestaetigter Antrag stehen bleibt, in Tagen. Ein Antrag,
# den seit einer Woche niemand bestaetigt hat, ist keiner mehr -- er ist
# ein vergessener Eintrag, der beim naechsten Blick Verwirrung stiftet.
ANTRAG_TAGE = paths.env_int("NOTZUGANG_ANTRAG_TAGE", 7)


def _jetzt():
    return int(time.time())


def _leer():
    return {"antraege": [], "zugaenge": []}


def _lade():
    """Der Bestand, um abgelaufene bereinigt. Nie eine Ausnahme.

    Eine unlesbare oder unsignierte Datei gilt als leer. Das ist die
    sichere Richtung: im Zweifel gibt es keinen Notzugang, und niemand
    kommt in einen fremden persoenlichen Raum. Der umgekehrte Fehlgriff
    waere ein Zugang, den niemand bestaetigt hat.
    """
    try:
        with open(DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return _leer()
    if not isinstance(daten, dict):
        return _leer()
    inhalt = daten.get("inhalt")
    if not isinstance(inhalt, dict):
        return _leer()
    if not geheim.pruefe_signatur(geheim.kanonisch(inhalt),
                                  daten.get("signatur")):
        # Von aussen veraendert. Alles verwerfen und nicht etwa den Teil
        # behalten, der plausibel aussieht.
        return _leer()
    jetzt = _jetzt()
    return {
        "antraege": [a for a in inhalt.get("antraege") or []
                     if isinstance(a, dict)
                     and a.get("gestellt", 0) > jetzt - ANTRAG_TAGE * 86400],
        "zugaenge": [z for z in inhalt.get("zugaenge") or []
                     if isinstance(z, dict) and z.get("bis", 0) > jetzt],
    }


def _speichere(inhalt):
    os.makedirs(os.path.dirname(DATEI), exist_ok=True)
    daten = {"inhalt": inhalt,
             "signatur": geheim.signiere(geheim.kanonisch(inhalt))}
    vorlaeufig = DATEI + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    os.replace(vorlaeufig, DATEI)


def moeglich():
    """Gibt es ueberhaupt jemanden, der bestaetigen koennte?

    Ohne Traeger der Rolle ist der Notzugang nicht "aus", sondern
    unbenutzbar -- und das soll die Oberflaeche sagen koennen, bevor
    jemand einen Antrag stellt, den niemand bestaetigen kann.
    """
    return bool(benutzer.traeger("notzugang"))


# --- BEANTRAGEN ---

def beantrage(raum, von, grund):
    """Ein Verwalter beantragt Zugang zu einem persoenlichen Raum."""
    grund = (grund or "").strip()
    if not raeume.ist_privat(raum):
        return False, ("Der Notzugang gilt nur fuer persoenliche Raeume. "
                       "In alle anderen kommt ein Verwalter ohnehin.")
    if raum == raeume.privat_kennung(von):
        return False, "Das ist dein eigener Raum."
    if not benutzer.ist_admin(von):
        return False, "Nur Verwalter koennen einen Notzugang beantragen."
    if len(grund) < 10:
        return False, ("Bitte einen Grund angeben. Er steht im Protokoll "
                       "und ist das, was die zweite Person beurteilt.")
    if not moeglich():
        return False, ("Es gibt niemanden mit der Rolle 'notzugang'. Ohne "
                       "eine zweite Person laesst sich kein Notzugang "
                       "bestaetigen -- das ist der Sinn der Sache.")

    daten = _lade()
    if any(a["raum"] == raum and a["von"] == von for a in daten["antraege"]):
        return False, "Dieser Antrag steht bereits."
    daten["antraege"].append({"raum": raum, "von": von, "grund": grund[:500],
                              "gestellt": _jetzt()})
    _speichere(daten)
    benutzer.protokolliere("notzugang_beantragt", raum, von=von,
                           hinweis=grund[:200])
    return True, ("Beantragt. Ein Traeger der Rolle 'notzugang' muss ihn "
                  "bestaetigen: " + ", ".join(benutzer.traeger("notzugang")))


def antraege():
    """Offene Antraege, aelteste zuerst."""
    return sorted(_lade()["antraege"], key=lambda a: a.get("gestellt", 0))


# --- BESTAETIGEN ---

def bestaetige(raum, von, durch):
    """Der zweite Mensch bestaetigt. Erst hier entsteht der Zugang."""
    if not benutzer.hat_rolle(durch, "notzugang"):
        return False, "Nur die Rolle 'notzugang' kann bestaetigen."
    if durch == von:
        return False, ("Beantragen und Bestaetigen muessen zwei Personen "
                       "sein.")
    daten = _lade()
    passend = [a for a in daten["antraege"]
               if a["raum"] == raum and a["von"] == von]
    if not passend:
        return False, "Diesen Antrag gibt es nicht (mehr)."
    antrag = passend[0]
    daten["antraege"] = [a for a in daten["antraege"] if a is not antrag]
    jetzt = _jetzt()
    daten["zugaenge"].append({
        "raum": raum, "von": von, "durch": durch,
        "grund": antrag.get("grund", ""),
        "ab": jetzt, "bis": jetzt + STUNDEN * 3600})
    _speichere(daten)
    benutzer.protokolliere("notzugang_bestaetigt", raum, von=durch,
                           hinweis=f"fuer {von}: {antrag.get('grund', '')[:150]}")
    return True, f"Bestaetigt. Der Zugang gilt {STUNDEN} Stunden."


def lehne_ab(raum, von, durch, grund=""):
    if not benutzer.hat_rolle(durch, "notzugang"):
        return False, "Nur die Rolle 'notzugang' kann ablehnen."
    daten = _lade()
    vorher = len(daten["antraege"])
    daten["antraege"] = [a for a in daten["antraege"]
                         if not (a["raum"] == raum and a["von"] == von)]
    if len(daten["antraege"]) == vorher:
        return False, "Diesen Antrag gibt es nicht (mehr)."
    _speichere(daten)
    benutzer.protokolliere("notzugang_abgelehnt", raum, von=durch,
                           hinweis=f"fuer {von}: {(grund or '')[:150]}")
    return True, "Abgelehnt."


# --- NUTZEN ---

def raeume_fuer(name):
    """Die persoenlichen Raeume, in die dieser Verwalter gerade darf.

    Ausdruecklich als Liste zurueckgegeben und nicht in raeume.lesbar()
    hineingerechnet: der Aufrufer muss sie weiterreichen, damit ein
    vergessener Aufruf keinen Notzugang bekommt, sondern keinen. Die
    sichere Richtung ist die, die nichts oeffnet.
    """
    return sorted({z["raum"] for z in _lade()["zugaenge"]
                   if z.get("von") == name})


def offene():
    """Alle gerade gueltigen Zugaenge -- fuer die Anzeige.

    Sichtbar fuer jeden Verwalter und jeden Traeger der Rolle: ein
    Notzugang, von dem nur der weiss, der ihn hat, waere die Kontrolle,
    die niemand kontrolliert.
    """
    return sorted(_lade()["zugaenge"], key=lambda z: z.get("bis", 0))


def schliesse(raum, von, durch="?"):
    """Beendet einen Zugang vor Ablauf."""
    daten = _lade()
    vorher = len(daten["zugaenge"])
    daten["zugaenge"] = [z for z in daten["zugaenge"]
                         if not (z["raum"] == raum and z["von"] == von)]
    if len(daten["zugaenge"]) == vorher:
        return False, "Dieser Zugang steht nicht offen."
    _speichere(daten)
    benutzer.protokolliere("notzugang_geschlossen", raum, von=durch,
                           hinweis=f"fuer {von}")
    return True, "Geschlossen."


def beschreibung():
    """Kurzer Stand fuer die Seitenleiste."""
    traeger_ = benutzer.traeger("notzugang")
    if not traeger_:
        return ("nicht einsatzbereit -- niemand traegt die Rolle "
                "'notzugang'")
    daten = _lade()
    teile = [f"{len(traeger_)} Person(en) koennen bestaetigen"]
    if daten["antraege"]:
        teile.append(f"{len(daten['antraege'])} Antrag/Antraege offen")
    if daten["zugaenge"]:
        teile.append(f"{len(daten['zugaenge'])} Zugang/Zugaenge gueltig")
    return " · ".join(teile)
