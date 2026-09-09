"""Raeume: wer darf welche Abschnitte sehen.

Bisher trug jeder Abschnitt zwei Merkmale, access und owner, und die Suche
haengte an jede Abfrage den Filter "access = shared ODER owner = ich". Das
hat zwei Nachteile, einen gemessenen und einen grundsaetzlichen.

Gemessen: dieser Filter trifft rund drei Viertel der Sammlung, und Chroma
muss die Kandidatenliste erst aufbauen. Bei 60.000 Abschnitten kostet er
70 ms gegenueber 2,4 ms ohne Filter -- und er waechst mit dem Bestand.
Getrennte Sammlungen beantworten dieselbe Frage in 3,5 ms.

Grundsaetzlich: die Grenze liegt in einem Abfrageparameter. Wer den Filter
einmal vergisst, sieht alles. Mit getrennten Sammlungen ist die Grenze die
Sammlung selbst; eine nicht abgefragte Sammlung kann nichts preisgeben.

Und "privat gegen geteilt" ist die falsche Koernung. In einer Firma ist die
nuetzliche Grenze fast nie die Person, sondern die Zustaendigkeit. Deshalb
gibt es hier nur einen Begriff: den Raum. Ein persoenlicher Ablageort ist
ein Raum mit einem Mitglied, "Einkauf" ein Raum mit fuenfzig. Damit waechst
die Zahl der Sammlungen mit der Zahl der Zustaendigkeiten, nicht mit der
Zahl der Nutzer.

Was hier NICHT steht: die Mitgliedschaft in den Abschnitten. Der Raum einer
Datei ist bestaendig und darf in die Metadaten; wer Mitglied ist, aendert
sich bei jedem Abteilungswechsel. Mitgliedschaft wird deshalb bei jeder
Frage frisch gelesen.

Zwei Quellen, und sie ergaenzen sich:

    "mitglieder"  von Hand gepflegt, in dieser Datei
    "gruppe"      der Name einer ownCloud-Gruppe

Ist eine Gruppe eingetragen, kommen ihre Mitglieder aus dem
Zwischenspeicher hinzu, den owncloud.gruppen_abgleich() nachzieht. Die
Vereinigung und nicht die Ersetzung: ein Verwalter, den die Firma nicht in
der Abteilungsgruppe fuehrt, soll sich nicht selbst aussperren, indem er
eine Gruppe eintraegt.

Gelesen wird der Zwischenspeicher, nicht ownCloud. Eine HTTP-Anfrage je
Frage waere ein Rundlauf je Sonde, und bei nicht erreichbarem ownCloud
stuende die Suche. Der Preis ist Aktualitaet: wer aus einer Gruppe
entfernt wird, kommt bis zum naechsten Abgleich noch hinein. Wem das zu
lang ist, setzt OWNCLOUD_GRUPPEN_HOECHSTALTER -- dann gilt ein zu alter
Stand nicht mehr, und die Gruppenmitgliedschaften fallen weg, bis wieder
abgeglichen wurde.
"""
import json
import os
import re
import time

import paths

# Ab welchem Alter ein Gruppenstand nicht mehr gilt, in Minuten. 0 heisst:
# kein Hoechstalter.
#
# Eine Abwaegung ohne richtige Antwort, und sie gehoert dem Betreiber:
# verfaellt der Stand, sperrt ein nicht erreichbares ownCloud alle aus
# ihren Abteilungsraeumen aus. Verfaellt er nicht, behaelt ein
# ausgeschiedener Mitarbeiter seinen Zugang bis zum naechsten Abgleich.
# Voreingestellt ist "arbeitsfaehig bleiben", weil eine ausgesperrte Firma
# in den meisten Haeusern der schwerere Ausfall ist. Der eigene Raum und
# von Hand eingetragene Mitglieder sind davon ohnehin nicht betroffen.
GRUPPEN_HOECHSTALTER = paths.env_int("OWNCLOUD_GRUPPEN_HOECHSTALTER", 0)

# Strenger Betrieb: niemand erfaehrt etwas ueber die persoenlichen Raeume
# anderer -- auch kein Verwalter, und auch nicht die Dateinamen.
#
# In manchen Branchen gilt "jeder weiss nur, was er wissen muss", und dort
# ist schon ein Dateiname eine Auskunft: "Angebot_Kunde_Meier_2026.pdf"
# verraet den Vorgang, ohne dass jemand die Datei oeffnet. Verwalter sehen
# dann nur noch, DASS ein Raum Inhalt hat, und koennen ihn als Ganzes
# loeschen -- ein Loeschrecht ohne jedes Leserecht.
#
# Ausgeschaltet bleibt es die Voreinstellung, weil ein Verwalter, der eine
# verwaiste Ablage aufraeumen soll, sonst blind arbeitet.
PRIVAT_STRENG = paths.env_int("PRIVAT_STRENG", 0)

DATEI = os.path.join(paths.CONFIG_DIR, "raeume.json")

# Der Raum, in dem alles liegt, was bisher access="shared" war.
ALLGEMEIN = "allgemein"

# Vorsilbe der persoenlichen Raeume. Sie macht sie in Listen erkennbar und
# verhindert, dass ein Nutzer namens "einkauf" den Abteilungsraum kapert.
PRIVAT = "privat_"


# --- SPEICHER ---
#
# Nur diese beiden Funktionen kennen die Ablage. Laeuft die Anwendung
# spaeter gegen eine verwaltete Datenbank, wird hier getauscht und sonst
# nichts -- dasselbe Verfahren wie bei store.py und der Vektordatenbank.

def _lade():
    try:
        with open(DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {"raeume": {}}
    if not isinstance(daten.get("raeume"), dict):
        return {"raeume": {}}
    return daten


def _speichere(daten):
    os.makedirs(os.path.dirname(DATEI), exist_ok=True)
    vorlaeufig = DATEI + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    # Erst schreiben, dann umbenennen: ein Absturz mitten im Schreiben
    # hinterlaesst sonst eine halbe Datei, und dann ist kein Raum mehr
    # lesbar -- also auch keine Rechte mehr pruefbar.
    os.replace(vorlaeufig, DATEI)


# --- KENNUNGEN ---

def sichere_kennung(text):
    """Aus einer Eingabe eine als Sammlungsname brauchbare Kennung.

    Chroma erlaubt Buchstaben, Ziffern, Punkt, Strich und Unterstrich und
    verlangt drei Zeichen. Umlaute werden ersetzt statt entfernt, damit
    "Prüfung" nicht zu "prfung" wird.
    """
    t = (text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t[:120]


def privat_kennung(benutzer):
    return PRIVAT + sichere_kennung(benutzer)


def kennungskonflikt(name, vorhandene):
    """Kollidiert der persoenliche Raum dieses Namens mit einem anderen?

    Rueckgabe: der bereits vergebene Name, oder None.

    sichere_kennung() ist verlustbehaftet -- sie muss es sein, weil ein
    Raumname in einen Sammlungsnamen passen muss. "m.wilhelm" und
    "m_wilhelm" werden beide zu "m_wilhelm", und damit bekaemen zwei
    verschiedene Menschen denselben persoenlichen Raum: jeder saehe die
    Unterlagen des anderen, koennte sie verschieben und loeschen.

    Deshalb wird die Kollision beim Anlegen abgewiesen, statt die Kennung
    eindeutig zu machen. Ein Namensschema wie privat_m_wilhelm_1a2b3c waere
    zwar kollisionsfrei, aber in der Raumverwaltung nicht mehr lesbar -- und
    es wuerde die persoenlichen Raeume aller bestehenden Nutzer umbenennen,
    also deren Ablage vom Namen trennen. Der Preis dafuer ist hoeher als der
    Nutzen: dass zwei Kennungen ueberhaupt so aehnlich sind, ist ein
    Sonderfall, den man beim Anlegen bemerken soll.
    """
    ziel = privat_kennung(name)
    name = (name or "").strip().lower()
    for andere in vorhandene:
        if (andere or "").strip().lower() == name:
            continue
        if privat_kennung(andere) == ziel:
            return andere
    return None


def konflikte(namen):
    """Bestehende Kollisionen: [(kennung, [name, name, ...])].

    Fuer die Anzeige. Ein Bestand kann sie schon enthalten, wenn die Nutzer
    angelegt wurden, bevor beim Anlegen geprueft wurde.
    """
    nach_kennung = {}
    for n in namen:
        nach_kennung.setdefault(privat_kennung(n), []).append(n)
    return sorted((k, sorted(v)) for k, v in nach_kennung.items()
                  if len(v) > 1)


def ist_privat(kennung):
    return str(kennung).startswith(PRIVAT)


def sammlung(kennung):
    """Name der Chroma-Sammlung eines Raums."""
    return "raum_" + kennung


# --- LESEN ---

def liste():
    """Alle Raeume: {kennung: {bezeichnung, beschreibung, mitglieder}}.

    Der allgemeine Raum steht immer darin, auch wenn die Datei fehlt. Ohne
    ihn gaebe es nach einer Neuinstallation keinen Ort fuer Dokumente, und
    der erste Upload muesste den Nutzer nach einem Raum fragen, den es noch
    nicht gibt.
    """
    daten = _lade()["raeume"]
    if ALLGEMEIN not in daten:
        daten = dict(daten)
        daten[ALLGEMEIN] = {"bezeichnung": "Allgemein",
                            "beschreibung": "Fuer alle sichtbar.",
                            "mitglieder": ["*"]}
    return daten


def raum(kennung):
    return liste().get(kennung)


def bezeichnung(kennung):
    r = raum(kennung)
    if r:
        return r.get("bezeichnung") or kennung
    return kennung


# --- GRUPPEN AUS OWNCLOUD ---
#
# Nur gelesen, nie geholt: das Holen ist Sache von owncloud.py. Dieses
# Modul faellt damit nicht aus, wenn ownCloud nicht antwortet, und braucht
# keine HTTP-Bibliothek.

def gruppenstand():
    """({gruppe: [kennung]}, alter_in_minuten). Leer, wenn nichts da ist."""
    try:
        with open(paths.GRUPPEN_DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}, None
    if not isinstance(daten, dict):
        return {}, None
    gruppen = daten.get("gruppen")
    if not isinstance(gruppen, dict):
        return {}, None
    alter = None
    zeit = daten.get("aktualisiert")
    if zeit:
        try:
            gemacht = time.mktime(time.strptime(zeit, "%Y-%m-%dT%H:%M:%S"))
            alter = max(0.0, (time.time() - gemacht) / 60)
        except (ValueError, OverflowError):
            alter = None
    return gruppen, alter


def stand_gueltig():
    """Gilt der Gruppenstand noch? (ok, alter, grund)."""
    gruppen, alter = gruppenstand()
    if not gruppen:
        return False, alter, "kein Stand vorhanden"
    if GRUPPEN_HOECHSTALTER and (alter is None
                                 or alter > GRUPPEN_HOECHSTALTER):
        return False, alter, (f"aelter als {GRUPPEN_HOECHSTALTER} Minuten "
                              f"(OWNCLOUD_GRUPPEN_HOECHSTALTER)")
    return True, alter, ""


def gruppenmitglieder(kennung):
    """Die Mitglieder, die dieser Raum aus seiner ownCloud-Gruppe zieht."""
    eintrag = liste().get(kennung) or {}
    gruppe = str(eintrag.get("gruppe") or "").strip()
    if not gruppe:
        return []
    ok, _alter, _grund = stand_gueltig()
    if not ok:
        return []
    gruppen, _alter = gruppenstand()
    return list(gruppen.get(gruppe) or [])


def mitglieder_gesamt(kennung):
    """(aus_datei, aus_gruppe) -- fuer die Anzeige und zum Pruefen."""
    eintrag = liste().get(kennung) or {}
    von_hand = [m for m in (eintrag.get("mitglieder") or []) if m != "*"]
    return sorted(set(von_hand)), sorted(set(gruppenmitglieder(kennung)))


def _darf(eintrag, benutzer, kennung=None):
    """Darf dieser Nutzer den Raum lesen?

    Vereinigung aus beiden Quellen. Die Gruppe ERSETZT die Handliste nicht:
    ein Verwalter, den die Firma nicht in der Abteilungsgruppe fuehrt, soll
    sich nicht selbst aussperren, indem er eine Gruppe eintraegt.
    """
    # Ein persoenlicher Raum hat genau einen Leser, und der steht in der
    # Kennung. Die Mitgliederliste und die Gruppe werden hier NICHT
    # gelesen -- und zwar bewusst nicht nur, weil kein Weg sie dort
    # eintragen soll, sondern weil dann kein Weg mehr genuegt:
    #
    #   * anlegen("privat_bob", mitglieder=[...]) legte einen Raum an, der
    #     aussah wie der persoenliche von bob. Existierte bob noch nicht,
    #     bekam er beim Anlegen seines Zugangs keinen eigenen mehr -- und
    #     was er fuer privat hielt, lasen die eingetragenen Mitglieder.
    #   * mitglieder_setzen("privat_anna", [...]), gruppe_setzen() und
    #     fuer_alle_oeffnen() machten aus einem bestehenden persoenlichen
    #     Raum einen geteilten. Ohne dass die Besitzerin es erfuhr.
    #   * eine von Hand bearbeitete raeume.json taete dasselbe.
    #
    # Die drei Wege sind zusaetzlich verschlossen (siehe anlegen,
    # mitglieder_setzen, gruppe_setzen). Diese Pruefung ist die, die auch
    # dann noch haelt, wenn ein vierter dazukommt.
    if kennung and ist_privat(kennung):
        return sichere_kennung(benutzer) == kennung[len(PRIVAT):]
    mitglieder = eintrag.get("mitglieder") or []
    if "*" in mitglieder or benutzer in mitglieder:
        return True
    if kennung and benutzer in gruppenmitglieder(kennung):
        return True
    return False


def lesbar(benutzer):
    """Die Raeume, die dieser Nutzer lesen darf -- Kennungen, sortiert.

    Der persoenliche Raum ist immer dabei, auch bevor er angelegt wurde:
    sonst waere der erste eigene Upload nicht wiederfindbar, weil der Raum
    zwar Abschnitte hat, aber noch nicht in der Datei steht.
    """
    erlaubt = {k for k, v in liste().items() if _darf(v, benutzer, k)}
    erlaubt.add(privat_kennung(benutzer))
    return sorted(erlaubt)


def schreibbar(benutzer):
    """Raeume, in die dieser Nutzer ablegen darf.

    Vorlaeufig gleich den lesbaren. Getrennt gehalten, weil die
    Unterscheidung kommt, sobald ownCloud die Rechte liefert -- dort ist
    Lesen und Schreiben zweierlei.
    """
    return lesbar(benutzer)


def darf_lesen(benutzer, kennung):
    return kennung in lesbar(benutzer)


def darf_verwalten(benutzer, kennung, ist_verwalter=False):
    """Darf dieser Nutzer den Raum bearbeiten und darin loeschen?

    Ein persoenlicher Raum gehoert genau einem Nutzer. Im strengen Betrieb
    kommt auch ein Verwalter nicht hinein -- er darf ihn dann als Ganzes
    loeschen, aber nicht darin blaettern.
    """
    if ist_privat(kennung):
        if kennung == privat_kennung(benutzer):
            return True
        return bool(ist_verwalter) and not PRIVAT_STRENG
    if kennung == ALLGEMEIN:
        return bool(ist_verwalter)
    return kennung in schreibbar(benutzer) or bool(ist_verwalter)


def darf_dateien_sehen(benutzer, kennung, ist_verwalter=False):
    """Darf dieser Nutzer die Dateinamen dieses Raums sehen?

    Getrennt von darf_lesen, weil im strengen Betrieb schon ein Dateiname
    eine Auskunft ist. Wer den Raum lesen darf, sieht die Namen ohnehin --
    diese Frage betrifft nur die Verwaltungsansicht.
    """
    if darf_lesen(benutzer, kennung):
        return True
    if ist_privat(kennung) and PRIVAT_STRENG:
        return False
    return bool(ist_verwalter)


# --- SCHREIBEN ---

def anlegen(kennung, bezeichnung_, beschreibung="", mitglieder=None):
    """(ok, meldung). Legt keine Sammlung an -- das tut der erste Upload."""
    kennung = sichere_kennung(kennung)
    if len(kennung) < 3:
        return False, "Kennung zu kurz (mindestens drei Zeichen)."
    if ist_privat(kennung):
        # Persoenliche Raeume entstehen nur ueber sichere_anlage_privat --
        # mit dem Zugang ihres Besitzers und mit ihm als einzigem
        # Mitglied. Von Hand angelegt saehe der Raum genauso aus, haette
        # aber die Mitglieder, die der Anlegende eintraegt.
        return False, (f"'{PRIVAT}' ist den persoenlichen Raeumen "
                       f"vorbehalten. Sie entstehen mit dem Zugang ihres "
                       f"Besitzers, nicht von Hand.")
    if kennung in _lade()["raeume"] or kennung == ALLGEMEIN:
        return False, "Diesen Raum gibt es schon."
    daten = _lade()
    daten["raeume"][kennung] = {
        "bezeichnung": (bezeichnung_ or kennung).strip(),
        "beschreibung": (beschreibung or "").strip(),
        "mitglieder": sorted(set(mitglieder or [])),
    }
    _speichere(daten)
    return True, kennung


def sichere_anlage_privat(benutzer):
    """Legt den persoenlichen Raum an, falls er fehlt. Gibt die Kennung."""
    kennung = privat_kennung(benutzer)
    daten = _lade()
    if kennung not in daten["raeume"]:
        daten["raeume"][kennung] = {
            "bezeichnung": f"Privat ({benutzer})",
            "beschreibung": "Nur fuer diesen Nutzer sichtbar.",
            "mitglieder": [benutzer],
        }
        _speichere(daten)
    return kennung


def _materialisiere(daten, kennung):
    """Schreibt einen bisher nur gedachten Raum in die Datei.

    Der allgemeine Raum entsteht in liste() aus dem Nichts, damit eine
    Neuinstallation einen Ort fuer Dokumente hat. Solange er nur gedacht
    ist, laesst er sich aber nicht bearbeiten -- und genau das braucht man,
    um ihm eine Mitgliederliste zu geben.
    """
    if kennung in daten["raeume"]:
        return True
    gedacht = liste().get(kennung)
    if not gedacht:
        return False
    daten["raeume"][kennung] = dict(gedacht)
    return True


def mitglieder_setzen(kennung, mitglieder):
    """Setzt die Mitglieder. "*" darin heisst: alle.

    Auch fuer den allgemeinen Raum: "jeder sieht alles" ist eine Vorgabe,
    keine Notwendigkeit. Wo der Grundsatz "nur was man wissen muss" gilt,
    bekommt auch er eine Liste.
    """
    daten = _lade()
    if not _materialisiere(daten, kennung):
        return False, "Unbekannter Raum."
    if ist_privat(kennung):
        return False, ("Ein persoenlicher Raum hat genau einen Leser -- "
                       "seinen Besitzer. Daran laesst sich nichts "
                       "eintragen. Soll etwas daraus geteilt werden, "
                       "verschiebt es der Besitzer in einen anderen Raum.")
    daten["raeume"][kennung]["mitglieder"] = sorted(set(mitglieder or []))
    _speichere(daten)
    if kennung == ALLGEMEIN and "*" not in (mitglieder or []):
        return True, ("Gespeichert. Der allgemeine Raum ist damit nicht "
                      "mehr fuer alle sichtbar.")
    return True, "Gespeichert."


def fuer_alle_oeffnen(kennung):
    """Setzt einen Raum zurueck auf "alle duerfen lesen"."""
    return mitglieder_setzen(kennung, ["*"])


def beschriften(kennung, bezeichnung_=None, beschreibung=None):
    daten = _lade()
    if not _materialisiere(daten, kennung):
        return False, "Unbekannter Raum."
    if bezeichnung_ is not None:
        daten["raeume"][kennung]["bezeichnung"] = bezeichnung_.strip()
    if beschreibung is not None:
        daten["raeume"][kennung]["beschreibung"] = beschreibung.strip()
    _speichere(daten)
    return True, "Gespeichert."


def gruppe_setzen(kennung, gruppe):
    """Traegt die ownCloud-Gruppe eines Raums ein, oder loescht sie."""
    daten = _lade()
    if not _materialisiere(daten, kennung):
        return False, "Unbekannter Raum."
    if ist_privat(kennung):
        return False, ("Ein persoenlicher Raum bekommt keine Gruppe -- "
                       "sonst lesen ihn alle ihre Mitglieder.")
    gruppe = str(gruppe or "").strip()
    if gruppe:
        daten["raeume"][kennung]["gruppe"] = gruppe
    else:
        daten["raeume"][kennung].pop("gruppe", None)
    _speichere(daten)
    return True, ("Gruppe entfernt." if not gruppe
                  else f"Mitgliedschaft kommt jetzt aus '{gruppe}'.")


def entfernen(kennung):
    """Nimmt den Raum aus der Verwaltung. Die Sammlung bleibt.

    Absichtlich getrennt: ein versehentlich entfernter Raum ist ueber die
    Datei wiederherstellbar, eine geloeschte Sammlung nicht. Wer die Daten
    wirklich los will, loescht die Sammlung ausdruecklich.
    """
    if kennung == ALLGEMEIN:
        return False, "Der allgemeine Raum bleibt."
    daten = _lade()
    if kennung not in daten["raeume"]:
        return False, "Unbekannter Raum."
    del daten["raeume"][kennung]
    _speichere(daten)
    return True, "Entfernt."
