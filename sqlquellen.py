"""Wer sich mit welchem Konto an der Fachdatenbank anmeldet.

Bis hierher gab es EIN Konto in der .env, und jede Frage lief darueber.
Das ist die Anordnung, bei der die Anwendung entscheidet, wer was sehen
darf -- und sie entscheidet es fuer die Datenbank mit, obwohl die es
selbst besser weiss.

In fast jedem Betrieb hat jeder Mitarbeiter ohnehin ein Datenbankkonto
mit bestimmten Rechten. Die richtige Anordnung ist deshalb umgekehrt:

    ein Raum  ->  ein Datenbankkonto mit den Rechten dieses Raums

Der Einkauf bekommt das Konto, das die Einkaufsdaten sieht. Ein
persoenlicher Raum bekommt das Konto seines Besitzers. Der allgemeine
Raum bekommt das, was alle sehen duerfen.

WAS DAS AENDERT, und es ist mehr als eine Bequemlichkeit:

  * Das SCHEMA kommt mit denselben Rechten. Das Sprachmodell sieht
    damit nur Tabellen, die dieses Konto lesen darf -- es kann also
    keine Abfrage auf etwas formulieren, das ohnehin verweigert wuerde.
  * Die Schranke liegt in der Datenbank. Versagt die Pruefung in
    sqlpruefung.py, haelt immer noch das Konto.
  * Ein Fehlgriff bleibt klein. Ein Konto mit Leserecht auf drei
    Tabellen kann drei Tabellen lesen.

DAS PASSWORT LIEGT VERSCHLUESSELT. Mit dem Schluessel des Raums, dem
es gehoert -- dieselbe Vorrichtung wie bei den Abschnitten. Wer die
Konfigurationsdatei kopiert, bekommt Geheimtext; der Schluessel liegt
auf einem anderen Volume.

Ohne Installationsschluessel wird kein Zugang gespeichert. Das ist
unbequem und richtig: ein Datenbankpasswort im Klartext in einer
JSON-Datei waere schlechter als gar kein Feature.
"""
import json
import os

import geheim
import paths

QUELLEN = os.path.join(paths.CONFIG_DIR, "sqlquellen.json")

# Was ein Zugang mitbringen kann. Fehlt etwas, gilt der Wert aus der
# Umgebung -- so genuegt in aller Regel Benutzer und Passwort, und
# Server, Port und Datenbank stehen einmal zentral.
FELDER = ("server", "port", "datenbank", "benutzer", "passwort", "hinweis")


def _leer():
    return {"zugaenge": []}


def lade():
    """Die hinterlegten Zugaenge. Bei kaputter Signatur: keine.

    Lieber keine Datenbank als eine Anmeldung mit Angaben aus einer
    Datei, die jemand danebengelegt hat.
    """
    try:
        with open(QUELLEN, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _leer()
    if not isinstance(daten, dict):
        return _leer()
    inhalt = daten.get("zugaenge")
    if not isinstance(inhalt, list):
        return _leer()
    if geheim.verfuegbar():
        if not geheim.pruefe_signatur(geheim.kanonisch(inhalt),
                                      daten.get("signatur", "")):
            return _leer()
    return {"zugaenge": inhalt}


def liste():
    return lade()["zugaenge"]


def raeume_mit_zugang():
    """Die Raeume, fuer die ein Zugang hinterlegt ist."""
    return sorted({z.get("raum") for z in liste() if z.get("raum")})


def _speichere(zugaenge):
    daten = {"zugaenge": zugaenge}
    if geheim.verfuegbar():
        daten["signatur"] = geheim.signiere(geheim.kanonisch(zugaenge))
    try:
        os.makedirs(os.path.dirname(QUELLEN), exist_ok=True)
        vorlaeufig = QUELLEN + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            json.dump(daten, f, indent=1, ensure_ascii=False)
        os.replace(vorlaeufig, QUELLEN)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    return True, "Gespeichert."


# --- SETZEN ---

def darf_setzen(raum, benutzer, ist_verwalter=False):
    """(ok, meldung). Wer darf den Zugang dieses Raums festlegen?"""
    import raeume
    if ist_verwalter:
        return True, ""
    if raum == raeume.privat_kennung(benutzer):
        # Sein eigenes Datenbankkonto kennt nur er. Ein Verwalter, der
        # es eintragen muesste, muesste es KENNEN -- und damit waere
        # aus "jeder mit seinen Rechten" wieder ein gemeinsames Konto
        # geworden, nur muehsamer.
        return True, ""
    return False, ("Den Zugang eines gemeinsamen Raums legt ein "
                   "Verwalter fest. Deinen eigenen kannst du selbst "
                   "eintragen.")


def setze(raum, angaben, benutzer="?", ist_verwalter=False):
    """Legt den Zugang eines Raums fest. (ok, meldung).

    angaben: dict mit benutzer/passwort und wahlweise
    server/port/datenbank/hinweis. Leeres dict entfernt den Zugang.
    """
    import raumschluessel
    darf, grund = darf_setzen(raum, benutzer, ist_verwalter)
    if not darf:
        return False, grund

    uebrig = [z for z in liste() if z.get("raum") != raum]
    angaben = {k: (v.strip() if isinstance(v, str) else v)
               for k, v in (angaben or {}).items() if k in FELDER}
    if not angaben.get("benutzer") and not angaben.get("passwort"):
        ok, _m = _speichere(uebrig)
        return ok, ("Zugang entfernt." if ok else _m)

    if not angaben.get("benutzer") or not angaben.get("passwort"):
        return False, ("Benutzer UND Passwort -- eines von beidem "
                       "ergibt keine Anmeldung.")

    if not raumschluessel.verfuegbar():
        return False, ("Ohne Installationsschluessel wird kein Passwort "
                       "gespeichert. Es laege sonst im Klartext in "
                       "config/sqlquellen.json -- schlechter als gar "
                       "kein Zugang.")

    eintrag = {"raum": raum}
    for k in FELDER:
        wert = angaben.get(k)
        if wert in (None, ""):
            continue
        eintrag[k] = (raumschluessel.verschluessele_text(raum, str(wert))
                      if k == "passwort" else wert)
    uebrig.append(eintrag)
    return _speichere(uebrig)


# --- LESEN ---

def zugang(raum):
    """Die Verbindungsangaben eines Raums, Passwort im Klartext. None.

    Aufgeschlossen wird erst hier, unmittelbar vor dem Verbinden. Der
    Klartext lebt damit so kurz wie moeglich und steht nirgends in
    einer Datei.
    """
    import raumschluessel
    for z in liste():
        if z.get("raum") != raum:
            continue
        aus = {k: z.get(k) for k in FELDER if z.get(k) not in (None, "")}
        pw = aus.get("passwort")
        if pw and raumschluessel.ist_verschluesselt(pw):
            try:
                aus["passwort"] = raumschluessel.entschluessele_text(raum, pw)
            except Exception:
                # Ein Passwort, das sich nicht oeffnen laesst, gehoert
                # zu einem anderen Schluessel. Keine Anmeldung mit
                # Geheimtext versuchen -- das gaebe eine
                # Fehlanmeldung, und die zaehlt bei manchen Servern
                # auf die Sperre.
                return None
        aus["raum"] = raum
        return aus
    return None


def fuer_benutzer(benutzer, notzugang=()):
    """[(raum, zugang)] -- die Zugaenge, die dieser Mensch nutzen darf.

    Reihenfolge: der eigene Raum zuerst. Wer ein eigenes Konto hat,
    soll damit arbeiten und nicht mit dem der Abteilung -- das ist der
    Sinn der Uebung.
    """
    import raeume
    erlaubt = set(raeume.lesbar(benutzer, notzugang=notzugang))
    eigener = raeume.privat_kennung(benutzer)
    aus = []
    for raum in raeume_mit_zugang():
        if raum not in erlaubt:
            continue
        z = zugang(raum)
        if z:
            aus.append((raum, z))
    aus.sort(key=lambda p: (p[0] != eigener, p[0] != raeume.ALLGEMEIN,
                            p[0]))
    return aus
