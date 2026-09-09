"""Benutzer, Rollen und ein Protokoll, das Aenderungen sichtbar macht.

Vorher: config/users.json war eine Zuordnung Name -> bcrypt-Hash, und wer
Verwalter ist, stand in ADMIN_USERS in der .env. Zwei Skripte
(create_user.py, manage_users.py) schrieben ohne jede Nachfrage in die
Datei -- wer sie starten konnte, legte sich einen Zugang an, und nichts
hielt es fest.

Drei Aenderungen, und eine ehrliche Grenze.

1. DIE ROLLE STEHT IN DER DATEI, nicht in der Umgebung. Eine
   Umgebungsvariable laesst sich am Container setzen, ohne die
   Benutzerdatei anzufassen -- damit war Verwalter zu werden eine Frage von
   docker run -e. Der Wert aus ADMIN_USERS gilt nur noch beim Umstieg von
   der alten Datei und beim ersten Start.

2. JEDER EINTRAG IST EINZELN SIGNIERT. Nicht verschluesselt -- der
   Inhalt ist kein Geheimnis, Namen und bcrypt-Hashes. Aber ein von Hand
   hinzugefuegter oder veraenderter Eintrag hat keine gueltige Signatur,
   und ein Eintrag ohne gueltige Signatur kann sich NICHT ANMELDEN.

   Einzeln und nicht ueber die ganze Datei, und das ist der Kern: eine
   Signatur ueber alles zusammen liesse einem Angreifer die Wahl, sie
   durch bloszes Beschaedigen der Datei zu brechen und damit alle
   auszusperren. So trifft ein gefaelschter Eintrag nur sich selbst --
   wer vorher angelegt wurde, arbeitet unveraendert weiter.

   Zusaetzlich eine Signatur ueber die Namensliste. Sie kann ein
   Loeschen von aussen nicht verhindern, macht es aber sichtbar.

3. AENDERUNGEN WERDEN PROTOKOLLIERT, verkettet. Jeder Eintrag traegt den
   Hash des vorherigen; eine geloeschte oder geaenderte Zeile bricht die
   Kette und faellt bei der Pruefung auf.

DIE GRENZE: Wer Dateizugriff auf config/ hat, kann den Schluessel lesen,
die Benutzerdatei aendern und neu signieren -- und das Protokoll neu
aufbauen. Nichts auf dieser Ebene kann das verhindern. Was hier steht,
verschiebt die Huerde von "ein Skript starten" auf "Schluessel lesen und
Signatur faelschen", und macht den gewoehnlichen Weg nachvollziehbar. Die
wirkliche Grenze ist, wer ueberhaupt an den Server kommt, und eine
verschluesselte Platte.
"""
import hashlib
import json
import os
import time

import bcrypt

import geheim
import paths

PROTOKOLL = os.path.join(paths.DATA_DIR, "benutzer.log")

# "notzugang" ist bewusst KEINE Steigerung von "admin", sondern etwas
# daneben: die Rolle darf nichts, ausser den Notzugang eines Verwalters zu
# einem persoenlichen Raum zu bestaetigen. Sie gehoert deshalb nicht in
# die IT, sondern woandershin -- Geschaeftsfuehrung, Personalrat, wer auch
# immer. Koennten Verwalter sich selbst bestaetigen, waere das Ganze eine
# Formalie: die IT genehmigte sich den Blick in fremde Ablagen selbst.
ROLLEN = ("admin", "notzugang", "nutzer")
MIN_PASSWORT = 8

# Zustaende der Benutzerdatei
SIGNIERT = "signiert"
UNSIGNIERT = "unsigniert"      # alte Datei, noch nie signiert
MANIPULIERT = "manipuliert"    # Namensliste passt nicht zur Signatur
LEER = "leer"


def _datei():
    return paths.resolve_user_file()


def _admins_aus_umgebung():
    roh = os.getenv("ADMIN_USERS", "admin")
    return [x.strip().lower() for x in roh.split(",") if x.strip()]


# --- LESEN ---

def _eintrag_daten(name, e):
    """Die Felder, die eine Signatur beglaubigt.

    Nur diese drei: Name, Passwort-Hash, Rolle. Zeitstempel und "von" sind
    Beiwerk -- sie sollen sich nachtragen lassen, ohne die Signatur zu
    brechen. Der Name gehoert dazu, damit ein Eintrag nicht unter einem
    anderen Namen wiederverwendet werden kann.
    """
    return geheim.kanonisch({
        "name": name,
        "passwort": e.get("passwort") or "",
        "rolle": e.get("rolle") or "nutzer",
    })


def lade():
    """(nutzer, zustand).

    Jeder Eintrag traegt zusaetzlich "_gueltig": ob seine Signatur passt.
    Der Schluessel beginnt mit einem Unterstrich und wird nie geschrieben
    -- er entsteht beim Lesen und ist nichts, was in der Datei stehen
    sollte.

    Auch eine alte Datei kommt in dieser Form zurueck; der Aufrufer soll
    das Format nicht kennen muessen.
    """
    p = _datei()
    try:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            return {}, LEER
        with open(p, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}, MANIPULIERT

    # --- altes Format: Name -> Hash ---
    if isinstance(daten, dict) and "nutzer" not in daten:
        umgebung = _admins_aus_umgebung()
        nutzer = {}
        for name, hashwert in daten.items():
            if not isinstance(hashwert, str):
                continue
            nutzer[name] = {
                "passwort": hashwert,
                "rolle": "admin" if name.lower() in umgebung else "nutzer",
                "_gueltig": False,
            }
        return nutzer, (UNSIGNIERT if nutzer else LEER)

    roh = daten.get("nutzer") if isinstance(daten, dict) else None
    if not isinstance(roh, dict):
        return {}, MANIPULIERT

    nutzer = {}
    for name, e in roh.items():
        if not isinstance(e, dict):
            continue
        e = dict(e)
        e["_gueltig"] = geheim.pruefe_signatur(_eintrag_daten(name, e),
                                               e.get("signatur") or "")
        nutzer[name] = e

    # Die Signatur ueber die Namensliste erkennt ein Loeschen von aussen.
    # Verhindern kann sie es nicht -- ein fehlender Eintrag ist einfach
    # weg. Sichtbar machen ist hier das Erreichbare.
    liste_ok = geheim.pruefe_signatur(geheim.kanonisch(sorted(nutzer)),
                                      daten.get("namensliste") or "")
    return nutzer, (SIGNIERT if liste_ok else MANIPULIERT)


def zustand():
    return lade()[1]


def namen():
    return sorted(lade()[0])


def eintrag(name):
    e = lade()[0].get((name or "").strip().lower())
    if not e:
        return None
    return {k: v for k, v in e.items() if k != "passwort"}


def _nachsichtig(zustand_):
    """Gilt der Umstiegsnachlass?

    Eine Datei aus der Zeit vor den Signaturen hat keine. Wuerde sie streng
    behandelt, waere nach dem Update niemand mehr angemeldet -- ein Update
    darf niemanden aussperren. Nach dem einmaligen Signieren gilt die
    strenge Regel.
    """
    return zustand_ in (UNSIGNIERT, LEER)


def pruefe(name, passwort):
    """Passt das Passwort, und ist der Eintrag echt?

    Zwei Bedingungen, und die zweite ist der Zweck der Signatur: ein von
    Hand in die Datei geschriebener Eintrag hat keine gueltige und kommt
    deshalb nicht herein, auch wenn sein bcrypt-Hash stimmt.

    Der bcrypt-Vergleich laeuft trotzdem immer, auch bei unbekanntem Namen
    und bei ungueltiger Signatur. Ein frueher Ausstieg antwortet messbar
    schneller und verraet damit, welche Namen es gibt.
    """
    name = (name or "").strip().lower()
    nutzer, z = lade()
    e = nutzer.get(name) or {}
    hashwert = e.get("passwort") or ""
    blind = "$2b$12$" + "." * 53
    ziel = hashwert if hashwert.startswith("$2") else blind
    try:
        passt = bcrypt.checkpw(passwort.encode("utf-8"),
                               ziel.encode("utf-8"))
    except (ValueError, TypeError):
        passt = False
    if not (passt and hashwert):
        return False
    if _nachsichtig(z):
        return True
    if not e.get("_gueltig"):
        protokolliere("abgewiesen", name, "anmeldung",
                      "Eintrag ohne gueltige Signatur")
        return False
    return True


def ist_admin(name):
    """Verwalter?

    Ein Eintrag ohne gueltige Signatur ist es nie -- selbst wenn "admin"
    darin steht. Beim Umstiegsnachlass greift ADMIN_USERS, damit die
    Installation nicht ohne Verwalter dasteht.
    """
    name = (name or "").strip().lower()
    nutzer, z = lade()
    if _nachsichtig(z):
        return name in _admins_aus_umgebung()
    e = nutzer.get(name) or {}
    return bool(e.get("_gueltig")) and e.get("rolle") == "admin"


def hat_rolle(name, rolle):
    """Traegt dieser Nutzer diese Rolle? Ohne gueltige Signatur nie.

    Der Umstiegsnachlass gilt hier NICHT: ADMIN_USERS macht jemanden zum
    Verwalter, wenn die Benutzerdatei noch aus der Zeit vor den Signaturen
    stammt. Fuer den Notzugang waere das der falsche Weg -- eine
    Umgebungsvariable laesst sich am Container setzen, und dann bestaetigt
    sich der Verwalter seinen Notzugang doch wieder selbst.
    """
    name = (name or "").strip().lower()
    nutzer, _z = lade()
    e = nutzer.get(name) or {}
    return bool(e.get("_gueltig")) and e.get("rolle") == rolle


def traeger(rolle):
    """Alle Nutzer mit dieser Rolle, mit gueltiger Signatur."""
    nutzer, _z = lade()
    return sorted(n for n, e in nutzer.items()
                  if e.get("_gueltig") and e.get("rolle") == rolle)


def admins():
    nutzer, z = lade()
    if _nachsichtig(z):
        return sorted(n for n in nutzer if n in _admins_aus_umgebung())
    return sorted(n for n, e in nutzer.items()
                  if e.get("_gueltig") and e.get("rolle") == "admin")


def ungueltige():
    """Namen mit fehlender oder falscher Signatur -- fuer die Anzeige."""
    nutzer, z = lade()
    if _nachsichtig(z):
        return []
    return sorted(n for n, e in nutzer.items() if not e.get("_gueltig"))


# --- SCHREIBEN ---

def _speichere(nutzer):
    rein = {}
    for name, e in nutzer.items():
        e = {k: v for k, v in e.items() if k != "_gueltig"}
        e["signatur"] = geheim.signiere(_eintrag_daten(name, e))
        rein[name] = e
    daten = {
        "version": 2,
        "namensliste": geheim.signiere(geheim.kanonisch(sorted(rein))),
        "nutzer": rein,
    }
    p = _datei()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    vorlaeufig = p + ".neu"
    fd = os.open(vorlaeufig, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    os.replace(vorlaeufig, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _jetzt():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def anlege(name, passwort, rolle="nutzer", von="?"):
    """(ok, meldung)."""
    name = (name or "").strip().lower()
    if not name or not name.replace("_", "").replace("-", "").replace(".", "").isalnum():
        return False, "Nur Buchstaben, Ziffern, Punkt, Strich, Unterstrich."
    if rolle not in ROLLEN:
        return False, f"Rolle muss eine von {', '.join(ROLLEN)} sein."
    if len(passwort or "") < MIN_PASSWORT:
        return False, f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen."

    nutzer, _z = lade()
    if name in nutzer:
        return False, f"'{name}' gibt es schon."

    # Der persoenliche Raum wird aus dem Namen gebildet, und dabei gehen
    # Zeichen verloren: "m.wilhelm" und "m_wilhelm" ergeben denselben Raum.
    # Zwei Menschen wuerden sich dann eine private Ablage teilen, ohne es zu
    # merken. Siehe raeume.kennungskonflikt().
    try:
        import raeume
        andere = raeume.kennungskonflikt(name, nutzer)
    except Exception:
        andere = None
    if andere:
        return False, (f"'{name}' und '{andere}' ergaeben denselben "
                       f"persoenlichen Raum ({raeume.privat_kennung(name)}) "
                       f"-- beide saehen die Unterlagen des anderen. Bitte "
                       f"eine Kennung waehlen, die sich um mehr als ein "
                       f"Sonderzeichen unterscheidet.")
    nutzer[name] = {
        "passwort": bcrypt.hashpw(passwort.encode("utf-8"),
                                  bcrypt.gensalt()).decode("utf-8"),
        "rolle": rolle,
        "angelegt": _jetzt(),
        "von": von,
    }
    _speichere(nutzer)
    protokolliere("angelegt", name, von, f"rolle={rolle}")

    # Der eigene Raum entsteht mit dem Zugang, nicht erst mit dem ersten
    # Upload. Wo "jeder weiss nur, was er wissen muss" gilt, ist der eigene
    # Ablageort kein Zubehoer, sondern die Voraussetzung dafuer, ueberhaupt
    # arbeiten zu koennen -- er soll nicht davon abhaengen, dass jemand die
    # richtige Stelle in der Oberflaeche findet.
    #
    # Import in der Funktion: raeume braucht benutzer nicht, und umgekehrt
    # soll das Anlegen eines Nutzers nicht an einer Importreihenfolge
    # haengen.
    try:
        import raeume
        raeume.sichere_anlage_privat(name)
    except Exception as e:
        protokolliere("hinweis", name, von, f"eigener Raum fehlt: {e}")

    return True, f"'{name}' angelegt ({rolle})."


def passwort_setzen(name, passwort, von="?"):
    name = (name or "").strip().lower()
    if len(passwort or "") < MIN_PASSWORT:
        return False, f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen."
    nutzer, _z = lade()
    if name not in nutzer:
        return False, f"'{name}' gibt es nicht."
    nutzer[name]["passwort"] = bcrypt.hashpw(
        passwort.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    nutzer[name]["geaendert"] = _jetzt()
    _speichere(nutzer)
    protokolliere("passwort", name, von)
    return True, f"Passwort von '{name}' geaendert."


def rolle_setzen(name, rolle, von="?"):
    name = (name or "").strip().lower()
    if rolle not in ROLLEN:
        return False, f"Rolle muss eine von {', '.join(ROLLEN)} sein."
    nutzer, _z = lade()
    if name not in nutzer:
        return False, f"'{name}' gibt es nicht."
    # Den letzten Verwalter nicht herabsetzen: danach koennte niemand mehr
    # Nutzer anlegen, und die Datei liesse sich nur noch von Hand
    # reparieren.
    if rolle != "admin" and admins() == [name]:
        return False, "Das ist der letzte Verwalter."
    nutzer[name]["rolle"] = rolle
    nutzer[name]["geaendert"] = _jetzt()
    _speichere(nutzer)
    protokolliere("rolle", name, von, f"rolle={rolle}")
    return True, f"'{name}' ist jetzt {rolle}."


def loesche(name, von="?"):
    name = (name or "").strip().lower()
    nutzer, _z = lade()
    if name not in nutzer:
        return False, f"'{name}' gibt es nicht."
    if admins() == [name]:
        return False, "Das ist der letzte Verwalter."
    del nutzer[name]
    _speichere(nutzer)
    protokolliere("geloescht", name, von)
    return True, (f"'{name}' geloescht. Chatverlauf und persoenlicher Raum "
                  f"bleiben bestehen und muessen getrennt entfernt werden.")


def neu_signieren(von="?"):
    """Nimmt die Datei wie sie ist und signiert sie neu.

    Fuer den Umstieg von der alten Datei und fuer den Fall, dass jemand von
    Hand eingegriffen hat und das Ergebnis behalten will. Ausdruecklich ein
    eigener Schritt: eine automatische Neusignatur bei jedem Start machte
    die Signatur wertlos.
    """
    nutzer, z = lade()
    if not nutzer:
        return False, "Keine Benutzer gefunden."
    vorher = [n for n, e in nutzer.items() if not e.get("_gueltig")]
    _speichere(nutzer)
    protokolliere("neu_signiert", "-", von,
                  f"vorher={z}, ohne_signatur={len(vorher)}")
    if vorher and z != UNSIGNIERT:
        return True, (f"{len(nutzer)} Benutzer signiert. Darunter "
                      f"{len(vorher)} ohne gueltige Signatur -- diese "
                      f"gelten damit als bestaetigt: "
                      f"{', '.join(sorted(vorher))}")
    return True, f"{len(nutzer)} Benutzer neu signiert."


# --- PROTOKOLL ---
#
# Verkettet: jeder Eintrag traegt den Hash des vorherigen. Eine geloeschte
# oder geaenderte Zeile bricht die Kette. Das verhindert nichts, aber es
# macht ein Aufraeumen im Nachhinein sichtbar -- und genau darum geht es
# bei einem Protokoll.

def _letzte_kette():
    try:
        with open(PROTOKOLL, "r", encoding="utf-8") as f:
            letzte = ""
            for zeile in f:
                if zeile.strip():
                    letzte = zeile
        if letzte:
            return json.loads(letzte).get("kette", "")
    except (OSError, ValueError):
        pass
    return ""


def protokolliere(aktion, ziel, von="?", hinweis=""):
    eintrag_ = {"zeit": _jetzt(), "aktion": aktion, "ziel": ziel,
                "von": von, "hinweis": hinweis}
    vorher = _letzte_kette()
    eintrag_["kette"] = hashlib.sha256(
        vorher.encode("utf-8") + geheim.kanonisch(eintrag_)).hexdigest()
    try:
        os.makedirs(os.path.dirname(PROTOKOLL), exist_ok=True)
        with open(PROTOKOLL, "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag_, ensure_ascii=False) + "\n")
    except OSError:
        pass


def protokoll(letzte=50):
    try:
        with open(PROTOKOLL, "r", encoding="utf-8") as f:
            zeilen = [z for z in f if z.strip()]
    except OSError:
        return []
    eintraege = []
    for z in zeilen[-letzte:]:
        try:
            eintraege.append(json.loads(z))
        except ValueError:
            eintraege.append({"zeit": "?", "aktion": "unlesbar", "ziel": "-",
                              "von": "-", "hinweis": z.strip()[:80]})
    return eintraege


def protokoll_pruefen():
    """(ok, zeile). ok=False nennt die erste Zeile, an der die Kette bricht."""
    try:
        with open(PROTOKOLL, "r", encoding="utf-8") as f:
            zeilen = [z for z in f if z.strip()]
    except OSError:
        return True, 0
    vorher = ""
    for n, z in enumerate(zeilen, start=1):
        try:
            e = json.loads(z)
        except ValueError:
            return False, n
        kette = e.pop("kette", "")
        erwartet = hashlib.sha256(
            vorher.encode("utf-8") + geheim.kanonisch(e)).hexdigest()
        if kette != erwartet:
            return False, n
        vorher = kette
    return True, len(zeilen)
