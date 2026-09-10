"""Dokumente aus ownCloud oder Nextcloud holen -- je Raum ein Ordner.

Warum ueberhaupt: Dokumente in die Oberflaeche hochzuladen heisst, sie
zweimal zu pflegen. Die Abteilung hat ihre Handbuecher schon irgendwo
liegen, und wer sie dort aendert, aendert nicht die Kopie in LocaNoto.
Dieselbe Ueberlegung wie bei den Tabellendateien: die Anwendung soll dort
lesen, wo gepflegt wird.

Was ownCloud dabei mitbringt und wir nicht selbst bauen muessen: Rechte auf
Ordnern, Anbindung an das Verzeichnis der Firma, Versionierung,
Loeschprotokolle. Fuer eine Datenschutzpruefung ist "die Rechte liegen in
ownCloud" eine bessere Antwort als "unser Filter ist sorgfaeltig
geschrieben".

Was ownCloud NICHT loest, und was dieses Modul deshalb tut:

    Der Vektorindex muss die Rechte spiegeln. ownCloud haelt die Dateien,
    Chroma haelt die Abschnitte -- und wer fragt, bekommt Abschnitte. Zwei
    Bruecken schlagen das zusammen:

        Ordner -> Raum      welche Sammlung eine Datei fuellt
        Gruppe -> Raum      wer die Abschnitte dieser Sammlung sieht

    Ohne die zweite waere die erste nur halb: die Dateirechte lagen dann in
    ownCloud, die Abschnittsrechte in einer Datei daneben, und ein
    Abteilungswechsel haette die eine Seite geaendert und die andere nicht.

    Der Raum gehoert in den Abschnitt, die Mitgliedschaft nicht. Eine Datei
    liegt dauerhaft in einem Ordner; wer Mitglied ist, aendert sich bei
    jedem Abteilungswechsel. Die Mitgliedschaft wird deshalb nie
    mitvektorisiert, sondern bei jeder Frage aus einem Zwischenspeicher
    gelesen, den ein Abgleich nachzieht.

    Zwischenspeicher und nicht Direktabfrage: eine HTTP-Anfrage je Frage
    waere ein Rundlauf je Sonde, und bei nicht erreichbarem ownCloud stuende
    die Suche. Das kostet Aktualitaet -- wer aus einer Gruppe entfernt wird,
    kommt bis zum naechsten Abgleich noch hinein. Deshalb zeigt die
    Oberflaeche das Alter des Standes, und
    OWNCLOUD_GRUPPEN_HOECHSTALTER kann einen zu alten verwerfen.

Der Abgleich ist die eigentliche Arbeit -- und die Stelle, an der so etwas
schiefgeht. Eine GELOESCHTE Datei muss ihre Abschnitte mitnehmen, eine
VERSCHOBENE den Raum wechseln. Passiert das nicht, zeigt die Anwendung
Auskuenfte aus Dokumenten, die es nicht mehr gibt -- bei einer
DSGVO-Betrachtung der Punkt, der zuerst auffaellt.

Kein Hochladen. Die Anwendung liest aus ownCloud und schreibt nie dorthin
zurueck; ein Lesezugriff genuegt. Was ueber die Oberflaeche hochgeladen
wird, bleibt wie bisher lokal und beruehrt ownCloud nicht.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlparse

import requests

import paths

URL = os.getenv("OWNCLOUD_URL", "").strip().rstrip("/")
BENUTZER = os.getenv("OWNCLOUD_USER", "").strip()
PASSWORT = os.getenv("OWNCLOUD_PASSWORT", "")
TIMEOUT = paths.env_float("OWNCLOUD_TIMEOUT", 30)

# Die Gruppenabfrage laeuft ueber die Provisioning-Schnittstelle und
# verlangt dort Verwalterrechte -- fuer das Holen der Dateien genuegt Lesen.
# Deshalb getrennt setzbar: wer ein Konto mit weitreichenden Rechten nicht
# fuer beides benutzen will, hinterlegt es nur hier.
ADMIN_BENUTZER = os.getenv("OWNCLOUD_ADMIN_USER", "").strip() or BENUTZER
ADMIN_PASSWORT = os.getenv("OWNCLOUD_ADMIN_PASSWORT", "") or PASSWORT

# Zuordnung Raum -> Ordner. In config/, weil sie im Betrieb gepflegt wird.
ZUORDNUNG = os.path.join(paths.CONFIG_DIR, "owncloud.json")

# Verzeichnis der abgeglichenen Staende. Unter DATA_DIR und nicht unter
# INDEX_DIR: der Stand ist nicht ableitbar. Die Kennzeichen der Dateien
# (ETag) kommen vom Server, und ohne sie beginnt jeder Abgleich mit einem
# vollstaendigen Herunterladen.
STAENDE = os.path.join(paths.DATA_DIR, "owncloud")

DAV = "{DAV:}"


def eingerichtet():
    return bool(URL and BENUTZER and PASSWORT)


def beschreibung():
    """Fuer die Anzeige. Nie das Passwort."""
    if not eingerichtet():
        fehlt = [n for n, w in (("OWNCLOUD_URL", URL),
                                ("OWNCLOUD_USER", BENUTZER),
                                ("OWNCLOUD_PASSWORT", PASSWORT)) if not w]
        return "nicht eingerichtet (" + ", ".join(fehlt) + " fehlt)"
    return f"{URL} als {BENUTZER}"


def _basis():
    """Die WebDAV-Wurzel des angemeldeten Nutzers."""
    return f"{URL}/remote.php/dav/files/{quote(BENUTZER)}"


def _url(pfad):
    teile = [quote(t) for t in str(pfad).strip("/").split("/") if t]
    return _basis() + ("/" + "/".join(teile) if teile else "")


# --- ZUORDNUNG ---

def zuordnung():
    """{raum: ordner}. Leer, wenn nichts eingerichtet ist."""
    try:
        with open(ZUORDNUNG, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    raeume_ = daten.get("raeume") if isinstance(daten, dict) else None
    if not isinstance(raeume_, dict):
        return {}
    return {k: str(v).strip() for k, v in raeume_.items() if str(v).strip()}


def setze_zuordnung(neu):
    """Schreibt die Zuordnung. neu: {raum: ordner}."""
    os.makedirs(os.path.dirname(ZUORDNUNG), exist_ok=True)
    vorlaeufig = ZUORDNUNG + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump({"raeume": neu}, f, ensure_ascii=False, indent=2)
    os.replace(vorlaeufig, ZUORDNUNG)


def ordner_fuer(raum):
    return zuordnung().get(raum)


# --- ABLAGE ---

def _sicher(rel):
    """Ein Serverpfad zu einem gefahrlosen relativen Pfad.

    Die Dateinamen kommen vom Server, nicht von uns. Ein Eintrag mit ".."
    oder einem fuehrenden Schraegstrich schriebe sonst ausserhalb des
    Zwischenspeichers -- und das ist keine erfundene Sorge, sondern das
    erste, was man bei einer fremden Dateiliste pruefen muss.
    """
    teile = []
    for t in str(rel).replace("\\", "/").split("/"):
        t = t.strip()
        if not t or t in (".", ".."):
            continue
        t = re.sub(r'[<>:"|?*\x00-\x1f]', "_", t)
        teile.append(t[:150])
    return "/".join(teile)


def ablage(raum):
    """Wohin die Dateien dieses Raums kommen.

    Unterhalb von data/dokumente, damit der gewoehnliche Ingest sie findet
    und die Unterordner wie gewohnt zu Sachgebieten werden.
    """
    p = os.path.join(paths.DOCS_DIR, paths.sicherer_teil(raum))
    os.makedirs(p, exist_ok=True)
    return p


def _stand_datei(raum):
    return os.path.join(STAENDE, f"{paths.sicherer_teil(raum)}.json")


def _stand_lesen(raum):
    try:
        with open(_stand_datei(raum), "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def _stand_schreiben(raum, daten):
    os.makedirs(STAENDE, exist_ok=True)
    p = _stand_datei(raum)
    vorlaeufig = p + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    os.replace(vorlaeufig, p)


# --- WEBDAV ---

def _sitzung():
    s = requests.Session()
    s.auth = (BENUTZER, PASSWORT)
    return s


_PROPFIND = ('<?xml version="1.0"?>'
             '<d:propfind xmlns:d="DAV:">'
             '<d:prop>'
             '<d:resourcetype/><d:getcontentlength/>'
             '<d:getetag/><d:getlastmodified/>'
             '</d:prop></d:propfind>')


def pruefe():
    """(ok, meldung). Ein Griff auf die Wurzel, ohne etwas zu aendern."""
    if not eingerichtet():
        return False, beschreibung()
    try:
        with _sitzung() as s:
            a = s.request("PROPFIND", _basis(), data=_PROPFIND,
                          headers={"Depth": "0",
                                   "Content-Type": "application/xml"},
                          timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f"Nicht erreichbar: {e}"
    if a.status_code == 401:
        return False, ("Anmeldung abgelehnt. Bei aktiver "
                       "Zwei-Faktor-Anmeldung braucht es ein "
                       "App-Passwort, nicht das Anmeldepasswort.")
    if a.status_code == 404:
        return False, ("Kein WebDAV unter dieser Adresse. Erwartet wird die "
                       "Wurzel der Installation, etwa "
                       "https://cloud.firma.de")
    if a.status_code != 207:
        return False, f"Unerwartete Antwort {a.status_code}."
    return True, f"Verbunden mit {URL} als {BENUTZER}."


def _eintraege(sitzung, pfad):
    """Ein Verzeichnis: [(name, ist_ordner, groesse, etag, geaendert)]."""
    a = sitzung.request("PROPFIND", _url(pfad), data=_PROPFIND,
                        headers={"Depth": "1",
                                 "Content-Type": "application/xml"},
                        timeout=TIMEOUT)
    if a.status_code == 404:
        raise FileNotFoundError(pfad)
    a.raise_for_status()

    wurzel = urlparse(_url(pfad)).path.rstrip("/")
    aus = []
    for antwort in ET.fromstring(a.content).findall(DAV + "response"):
        href = (antwort.findtext(DAV + "href") or "").strip()
        eigen = urlparse(href).path.rstrip("/")
        if eigen == wurzel:
            continue  # das Verzeichnis selbst
        stat = antwort.find(DAV + "propstat")
        prop = stat.find(DAV + "prop") if stat is not None else None
        if prop is None:
            continue
        art = prop.find(DAV + "resourcetype")
        ordner = art is not None and art.find(DAV + "collection") is not None
        try:
            groesse = int(prop.findtext(DAV + "getcontentlength") or 0)
        except ValueError:
            groesse = 0
        aus.append((
            unquote(os.path.basename(eigen)),
            ordner,
            groesse,
            (prop.findtext(DAV + "getetag") or "").strip('"'),
            (prop.findtext(DAV + "getlastmodified") or "").strip(),
        ))
    return aus


def dateien(pfad, endungen=None, tiefe=8):
    """Alle passenden Dateien unterhalb von pfad, rekursiv.

    Depth 1 und selbst absteigen statt "Depth: infinity": das ist auf vielen
    Installationen abgeschaltet, und ein Abgleich, der davon abhaengt,
    scheitert dann ohne erkennbaren Grund.
    """
    endungen = tuple(e.lower() for e in
                     (endungen or paths.DOKUMENT_ENDUNGEN))
    gefunden = []
    with _sitzung() as s:
        offen = [(pfad.strip("/"), "", 0)]
        while offen:
            fern, rel, ebene = offen.pop(0)
            for name, ordner, groesse, etag, geaendert in _eintraege(s, fern):
                unten = f"{rel}/{name}" if rel else name
                if ordner:
                    if ebene < tiefe:
                        offen.append((f"{fern}/{name}", unten, ebene + 1))
                    continue
                if name.startswith("~$") or not name.lower().endswith(endungen):
                    continue
                gefunden.append({"rel": unten, "fern": f"{fern}/{name}",
                                 "groesse": groesse, "etag": etag,
                                 "geaendert": geaendert})
    return sorted(gefunden, key=lambda d: d["rel"])


def hole(fern, ziel):
    """Laedt eine Datei herunter. Bytes."""
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    vorlaeufig = ziel + ".teil"
    geschrieben = 0
    with _sitzung() as s:
        with s.get(_url(fern), stream=True, timeout=TIMEOUT) as a:
            a.raise_for_status()
            with open(vorlaeufig, "wb") as f:
                for stueck in a.iter_content(chunk_size=1 << 16):
                    if stueck:
                        f.write(stueck)
                        geschrieben += len(stueck)
    # Erst vollstaendig, dann an den richtigen Namen: ein abgebrochener
    # Download soll nicht als fertige Datei eingelesen werden.
    os.replace(vorlaeufig, ziel)
    return geschrieben


# --- GRUPPEN ---
#
# Die Provisioning-Schnittstelle (OCS) statt WebDAV. Sie liefert JSON, wenn
# man danach fragt, und verlangt den Kopf OCS-APIRequest -- ohne ihn
# antwortet die Installation mit einer Anmeldeseite statt mit Daten.

def _ocs(pfad, sitzung=None):
    """Ein OCS-Aufruf. Gibt den Inhalt von ocs.data zurueck."""
    url = URL + "/ocs/v1.php/cloud/" + str(pfad).lstrip("/")
    eigene = sitzung is None
    s = sitzung or requests.Session()
    if eigene:
        s.auth = (ADMIN_BENUTZER, ADMIN_PASSWORT)
    try:
        a = s.get(url, params={"format": "json"},
                  headers={"OCS-APIRequest": "true"}, timeout=TIMEOUT)
    finally:
        if eigene:
            s.close()
    if a.status_code == 401:
        raise PermissionError("Anmeldung abgelehnt.")
    a.raise_for_status()
    try:
        umschlag = a.json()["ocs"]
    except (ValueError, KeyError) as e:
        raise ValueError("Keine OCS-Antwort -- zeigt die Adresse auf die "
                         "Wurzel der Installation?") from e
    stand = (umschlag.get("meta") or {}).get("statuscode")
    # 100 (v1) und 200 (v2) heissen beide "in Ordnung". 997 heisst "nicht
    # berechtigt" -- und das ist der Fall, den man erklaeren muss: die
    # Gruppenabfrage braucht ein Verwalterkonto.
    if stand == 997:
        raise PermissionError(
            "Nicht berechtigt. Die Gruppenabfrage verlangt in ownCloud ein "
            "Konto mit Verwalterrechten -- siehe OWNCLOUD_ADMIN_USER.")
    if stand not in (100, 200):
        raise ValueError("ownCloud antwortete mit Status " + str(stand))
    return umschlag.get("data") or {}


def gruppen():
    """Die Gruppennamen der Installation, sortiert."""
    return sorted(_ocs("groups").get("groups") or [])


def _kennungen(daten):
    """Nutzerkennungen aus einer OCS-Antwort, klein geschrieben.

    Klein geschrieben, weil LocaNoto seine Kennungen so fuehrt. Stimmen die
    Namen in ownCloud und hier nicht ueberein, hilft das nicht -- dann
    braucht es eine Zuordnung, und die gibt es noch nicht. Der Abgleich
    nennt deshalb, was er gefunden hat, damit der Unterschied auffaellt.
    """
    return sorted({str(u).strip().lower() for u in (daten.get("users") or [])
                   if str(u).strip()})


def mitglieder(gruppe):
    """Die Kennungen einer Gruppe."""
    return _kennungen(_ocs("groups/" + quote(str(gruppe))))


def gruppen_zuordnung():
    """{raum: gruppenname} -- aus den Raeumen selbst.

    Die Gruppe steht im Raum und nicht in einer zweiten Zuordnungsdatei:
    ein Raum, dessen Mitgliedschaft aus einer Gruppe kommt, soll das an
    einer Stelle sagen. Zwei Dateien, die zusammen erst die Antwort geben,
    laufen irgendwann auseinander.

    Der Import steht in der Funktion, damit raeume.py dieses Modul nie
    braucht -- eine Mitgliedschaft aufzuloesen soll keine HTTP-Bibliothek
    laden.
    """
    import raeume
    return {k: e["gruppe"].strip()
            for k, e in raeume.liste().items()
            if str(e.get("gruppe") or "").strip()}


def gruppen_abgleich():
    """Holt die Mitglieder aller zugeordneten Gruppen und legt sie ab.

    Nur die zugeordneten, nicht alle: die Mitgliederliste jeder Gruppe der
    Firma abzulegen waere eine Sammlung personenbezogener Daten, fuer die
    es keinen Anlass gibt.

    Rueckgabe: Bericht als dict. Scheitert alles, bleibt der bisherige
    Stand liegen -- ein halber Stand waere schlimmer als ein alter.
    """
    zu = gruppen_zuordnung()
    if not zu:
        return {"gruppen": {}, "fehler": [], "geschrieben": False,
                "meldung": "Keine Gruppe zugeordnet."}

    gefunden, fehler = {}, []
    with requests.Session() as s:
        s.auth = (ADMIN_BENUTZER, ADMIN_PASSWORT)
        for raum, gruppe in sorted(zu.items()):
            if gruppe in gefunden:
                continue  # zwei Raeume, dieselbe Gruppe
            try:
                gefunden[gruppe] = _kennungen(
                    _ocs("groups/" + quote(str(gruppe)), sitzung=s))
            except (requests.RequestException, PermissionError,
                    ValueError) as e:
                fehler.append({"gruppe": gruppe, "raum": raum,
                               "grund": str(e)})

    if not gefunden:
        return {"gruppen": {}, "fehler": fehler, "geschrieben": False,
                "meldung": "Kein Gruppenstand geholt -- der alte gilt "
                           "weiter."}

    # Gruppen, die diesmal nicht geholt werden konnten, behalten ihren
    # letzten Stand. Sie zu leeren hiesse, ihre Mitglieder auszusperren,
    # weil eine Abfrage fehlgeschlagen ist.
    zusammen = dict(gruppen_stand().get("gruppen") or {})
    zusammen.update(gefunden)
    # Was nicht mehr zugeordnet ist, fliegt heraus.
    behalten = set(zu.values())
    zusammen = {g: m for g, m in zusammen.items() if g in behalten}

    os.makedirs(os.path.dirname(paths.GRUPPEN_DATEI), exist_ok=True)
    vorlaeufig = paths.GRUPPEN_DATEI + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump({"aktualisiert": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "gruppen": zusammen}, f, ensure_ascii=False, indent=2)
    os.replace(vorlaeufig, paths.GRUPPEN_DATEI)

    return {"gruppen": zusammen, "fehler": fehler, "geschrieben": True,
            "meldung": (str(len(gefunden)) + " Gruppen, "
                        + str(sum(len(m) for m in gefunden.values()))
                        + " Mitgliedschaften.")}


def gruppen_stand():
    """Der abgelegte Stand: {aktualisiert, gruppen, alter_minuten}."""
    try:
        with open(paths.GRUPPEN_DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    alter = None
    zeit = daten.get("aktualisiert")
    if zeit:
        try:
            gemacht = time.mktime(time.strptime(zeit, "%Y-%m-%dT%H:%M:%S"))
            alter = max(0.0, (time.time() - gemacht) / 60)
        except (ValueError, OverflowError):
            alter = None
    daten["alter_minuten"] = alter
    return daten


# --- ABGLEICH ---

def plane(raum, endungen=None):
    """Was ein Abgleich tun wuerde, ohne es zu tun.

    (neu, geaendert, entfallen, unveraendert) -- Listen von relativen
    Pfaden. Getrennt vom Ausfuehren, weil ein Abgleich Dateien loescht und
    Abschnitte entfernt: das will man vorher sehen.
    """
    ordner = ordner_fuer(raum)
    if not ordner:
        raise ValueError(f"Fuer den Raum '{raum}' ist kein Ordner "
                         f"eingerichtet.")
    fern = {d["rel"]: d for d in dateien(ordner, endungen)}
    stand = _stand_lesen(raum)

    neu, geaendert, unveraendert = [], [], []
    for rel, d in fern.items():
        alt = stand.get(rel)
        lokal = os.path.join(ablage(raum), _sicher(rel))
        if not alt or not os.path.exists(lokal):
            neu.append(rel)
        elif (alt.get("etag") != d["etag"]
              or alt.get("groesse") != d["groesse"]):
            geaendert.append(rel)
        else:
            unveraendert.append(rel)
    entfallen = [rel for rel in stand if rel not in fern]
    return neu, geaendert, sorted(entfallen), unveraendert


def abgleich(raum, endungen=None, loeschen=True, fortschritt=None):
    """Holt neue und geaenderte Dateien, entfernt entfallene.

    loeschen=False laesst entfallene Dateien liegen. Gedacht fuer den
    ersten Lauf, wenn noch nicht klar ist, ob die Zuordnung stimmt -- eine
    falsch eingerichtete Zuordnung sieht sonst aus wie "alles geloescht".

    Rueckgabe: Bericht als dict. Was hier NICHT passiert: das Einlesen.
    Der Abgleich holt Dateien, der Ingest vektorisiert sie -- getrennt,
    weil das eine Sekunden dauert und das andere Stunden.
    """
    neu, geaendert, entfallen, unveraendert = plane(raum, endungen)
    ziel = ablage(raum)
    stand = _stand_lesen(raum)
    fern = {d["rel"]: d for d in dateien(ordner_fuer(raum), endungen)}

    bericht = {"raum": raum, "ordner": ordner_fuer(raum),
               "geholt": [], "entfernt": [], "fehler": [],
               "unveraendert": len(unveraendert), "bytes": 0,
               "begonnen": time.strftime("%Y-%m-%dT%H:%M:%S")}

    for n, rel in enumerate(neu + geaendert, start=1):
        d = fern[rel]
        pfad = os.path.join(ziel, _sicher(rel))
        if fortschritt:
            fortschritt(rel, n, len(neu) + len(geaendert))
        try:
            bericht["bytes"] += hole(d["fern"], pfad)
        except (requests.RequestException, OSError) as e:
            bericht["fehler"].append({"datei": rel, "grund": str(e)})
            continue
        stand[rel] = {"etag": d["etag"], "groesse": d["groesse"],
                      "geaendert": d["geaendert"],
                      "geholt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        bericht["geholt"].append(rel)

    if loeschen:
        for rel in entfallen:
            pfad = os.path.join(ziel, _sicher(rel))
            try:
                if os.path.exists(pfad):
                    os.remove(pfad)
            except OSError as e:
                bericht["fehler"].append({"datei": rel, "grund": str(e)})
                continue
            stand.pop(rel, None)
            bericht["entfernt"].append(os.path.basename(rel))

    _stand_schreiben(raum, stand)
    bericht["beendet"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return bericht


def entferne_abschnitte(raum, dateinamen):
    """Loescht die Abschnitte entfallener Dateien aus beiden Indizes.

    Getrennt von abgleich(), weil dieser Schritt die Datenbank anfasst und
    der Abgleich nur das Dateisystem. Wer den Abgleich zum Pruefen laufen
    laesst, soll damit keine Abschnitte verlieren.

    Rueckgabe: Anzahl entfernter Abschnitte.
    """
    if not dateinamen:
        return 0
    import keyword_index
    import raeume
    import store

    sml = store.sammlung(raeume.sammlung(raum), anlegen=False)
    entfernt = 0
    for name in dateinamen:
        if sml is not None:
            try:
                ids = sml.get(where={"file_name": name}, include=[])["ids"]
                if ids:
                    sml.delete(ids=ids)
                    entfernt += len(ids)
            except Exception:
                pass
        keyword_index.delete_document(name, raum=raum)
    return entfernt


def letzter_bericht(raum):
    """Wann zuletzt abgeglichen wurde -- aus dem Stand abgeleitet."""
    stand = _stand_lesen(raum)
    if not stand:
        return None
    zeiten = [e.get("geholt") for e in stand.values() if e.get("geholt")]
    return {"dateien": len(stand),
            "zuletzt": max(zeiten) if zeiten else None}


# --- OWNCLOUD ALS ABLAGE DAHINTER ---
#
# LocaNoto steht vorn, ownCloud liegt dahinter. Wer hier einen Nutzer
# anlegt, bekommt ihn dort auch; wer hier einen Raum anlegt, bekommt dort
# einen Ordner samt Freigabe. Niemand muss in ownCloud etwas einrichten,
# und niemand muss dort etwas von Raeumen wissen.
#
# Der Baum gehoert dem DIENSTKONTO und wird nach aussen geteilt:
#
#     /LocaNoto/allgemein/          fuer alle lesbar, Verwalter schreiben
#     /LocaNoto/raeume/<raum>/      fuer die Mitglieder
#     /LocaNoto/privat/<kennung>/   nur fuer diesen einen Nutzer
#
# Die Richtung ist Absicht. Ein Ordner im EIGENEN Bereich des Nutzers waere
# fuer LocaNoto unsichtbar: WebDAV kennt nur den Bereich des angemeldeten
# Kontos, und weder ownCloud noch Nextcloud lassen einen Verwalter fremde
# Dateien darueber lesen. Ein persoenlicher Raum, den die Anwendung nicht
# durchsuchen kann, waere aber kein Raum, sondern ein Ordner.
#
# Derselbe Baum steht ohne ownCloud unter data/dokumente/ -- gleiche
# Namen, gleiche Aufteilung. Der Rueckfall ist deshalb kein Sonderfall,
# sondern derselbe Aufbau ohne Freigaben.

# Wurzel des Baums im Bereich des Dienstkontos.
WURZEL = os.getenv("OWNCLOUD_WURZEL", "").strip().strip("/") or "LocaNoto"

# OCS-Rechte, als Summe von Bits. 1 lesen, 2 aendern, 4 anlegen,
# 8 loeschen, 16 weiterverteilen.
NUR_LESEN = 1
LESEN_SCHREIBEN = 1 + 2 + 4 + 8


def _ocs_ruf(methode, pfad, daten=None, app=None):
    """Ein OCS-Aufruf mit Methode. Gibt ocs.data zurueck.

    app waehlt die Schnittstelle: None ist die Nutzerverwaltung unter
    /cloud, "files_sharing" die Freigaben. Zwei Pfade, eine Umhuellung --
    die Fehlerbehandlung soll nicht zweimal dastehen.
    """
    if app:
        url = f"{URL}/ocs/v1.php/apps/{app}/api/v1/{str(pfad).lstrip('/')}"
    else:
        url = f"{URL}/ocs/v1.php/cloud/{str(pfad).lstrip('/')}"
    with requests.Session() as s:
        s.auth = (ADMIN_BENUTZER, ADMIN_PASSWORT)
        a = s.request(methode, url, params={"format": "json"},
                      data=daten or None,
                      headers={"OCS-APIRequest": "true"}, timeout=TIMEOUT)
    if a.status_code == 401:
        raise PermissionError("Anmeldung abgelehnt.")
    a.raise_for_status()
    try:
        umschlag = a.json()["ocs"]
    except (ValueError, KeyError) as e:
        raise ValueError("Keine OCS-Antwort -- zeigt die Adresse auf die "
                         "Wurzel der Installation?") from e
    meta = umschlag.get("meta") or {}
    stand = meta.get("statuscode")
    if stand == 997:
        raise PermissionError(
            "Nicht berechtigt. Nutzer anzulegen und Ordner freizugeben "
            "verlangt in ownCloud ein Konto mit Verwalterrechten -- siehe "
            "OWNCLOUD_ADMIN_USER.")
    if stand not in (100, 200):
        raise ValueError(f"ownCloud antwortete mit Status {stand}"
                         + (f": {meta.get('message')}"
                            if meta.get("message") else ""))
    return umschlag.get("data") or {}


# --- PFADE ---

def raum_pfad(raum):
    """Der ownCloud-Ordner eines Raums im Bereich des Dienstkontos."""
    import raeume
    if raum == raeume.ALLGEMEIN:
        return f"/{WURZEL}/allgemein"
    if raeume.ist_privat(raum):
        return f"/{WURZEL}/privat/{raum[len(raeume.PRIVAT):]}"
    return f"/{WURZEL}/raeume/{paths.sicherer_teil(raum)}"


def zuordnung_wirksam():
    """{raum: ordner} -- von Hand eingetragen, sonst der Standardbaum.

    Die Handzuordnung geht vor: wer seine Abteilungsunterlagen seit Jahren
    unter /Abteilungen/Einkau/Handbuecher pflegt, soll sie dort lassen
    koennen. Fuer alle anderen Raeume ergibt sich der Ordner aus dem Namen,
    und dann muss niemand mehr etwas eintragen -- das ist der Unterschied
    zwischen "angebunden" und "eingebettet".
    """
    import raeume
    von_hand = zuordnung()
    aus = dict(von_hand)
    for k in raeume.liste():
        aus.setdefault(k, raum_pfad(k))
    aus.setdefault(raeume.ALLGEMEIN, raum_pfad(raeume.ALLGEMEIN))
    return aus


# --- ORDNER ---

def ordner_anlegen(pfad):
    """Legt einen Ordner samt Elternordnern an. True, wenn er danach steht.

    MKCOL legt genau eine Ebene an und scheitert, wenn der Elternordner
    fehlt. Deshalb Stueck fuer Stueck -- und 405 ("gibt es schon") ist
    kein Fehler, sondern das Ziel.
    """
    teile = [t for t in str(pfad).strip("/").split("/") if t]
    with _sitzung() as s:
        gebaut = ""
        for t in teile:
            gebaut += "/" + t
            a = s.request("MKCOL", _url(gebaut), timeout=TIMEOUT)
            if a.status_code in (201, 405):
                continue
            if a.status_code in (401, 403):
                raise PermissionError(
                    f"Darf {gebaut} nicht anlegen -- Rechte des Kontos "
                    f"{BENUTZER} pruefen.")
            a.raise_for_status()
    return True


# --- FREIGABEN ---

def freigaben(pfad):
    """Die Freigaben eines Ordners: [{id, art, an, rechte}]."""
    daten = _ocs_ruf("GET", "shares", app="files_sharing")
    # Die Antwort ist je nach Fassung eine Liste oder ein Umschlag.
    roh = daten if isinstance(daten, list) else (daten.get("element") or [])
    if isinstance(roh, dict):
        roh = [roh]
    ziel = "/" + str(pfad).strip("/")
    aus = []
    for e in roh:
        if str(e.get("path", "")).rstrip("/") != ziel:
            continue
        aus.append({"id": str(e.get("id")),
                    "art": int(e.get("share_type") or 0),
                    "an": str(e.get("share_with") or ""),
                    "rechte": int(e.get("permissions") or 0)})
    return aus


def freigeben(pfad, an, art="nutzer", rechte=NUR_LESEN):
    """Teilt einen Ordner mit einem Nutzer oder einer Gruppe."""
    daten = {"path": "/" + str(pfad).strip("/"),
             "shareType": 0 if art == "nutzer" else 1,
             "shareWith": an,
             "permissions": int(rechte)}
    _ocs_ruf("POST", "shares", daten=daten, app="files_sharing")
    return True


def freigabe_entfernen(kennung):
    _ocs_ruf("DELETE", f"shares/{kennung}", app="files_sharing")
    return True


def freigaben_setzen(pfad, personen, rechte=NUR_LESEN, gruppen_=()):
    """Bringt die Freigaben eines Ordners auf genau diese Menge.

    Setzen und nicht ergaenzen: wer aus einem Raum ausscheidet, verliert
    damit auch den Ordner. Ein Mitglied zu entfernen und die Freigabe
    stehen zu lassen waere die haeufigste Art, eine Rechteaenderung
    wirkungslos zu machen -- die Suche fragt den Raum nicht mehr, die
    Dateien liegen aber weiter im ownCloud des Ausgeschiedenen.

    Rueckgabe: (hinzugefuegt, entfernt).
    """
    soll_n = {str(p).strip().lower() for p in personen if str(p).strip()}
    soll_g = {str(g).strip() for g in gruppen_ if str(g).strip()}
    ist = freigaben(pfad)
    dazu, weg = 0, 0
    for f in ist:
        vorhanden = (f["an"].lower() in soll_n if f["art"] == 0
                     else f["an"] in soll_g)
        if not vorhanden and f["art"] in (0, 1):
            freigabe_entfernen(f["id"])
            weg += 1
    hat_n = {f["an"].lower() for f in ist if f["art"] == 0}
    hat_g = {f["an"] for f in ist if f["art"] == 1}
    for p in sorted(soll_n - hat_n):
        freigeben(pfad, p, "nutzer", rechte)
        dazu += 1
    for g in sorted(soll_g - hat_g):
        freigeben(pfad, g, "gruppe", rechte)
        dazu += 1
    return dazu, weg


# --- NUTZER ---

def nutzer_vorhanden(kennung):
    try:
        _ocs_ruf("GET", f"users/{kennung}")
        return True
    except ValueError:
        return False


def nutzer_anlegen(kennung, passwort, anzeigename=""):
    """Legt einen ownCloud-Nutzer an. True, wenn er danach existiert.

    Ein bereits vorhandener Nutzer ist kein Fehler: LocaNoto wird oft auf
    ein Haus gesetzt, in dem es die Leute in ownCloud laengst gibt.
    """
    if nutzer_vorhanden(kennung):
        return False, "gab es schon"
    daten = {"userid": kennung, "password": passwort}
    if anzeigename:
        daten["displayName"] = anzeigename
    _ocs_ruf("POST", "users", daten=daten)
    return True, "angelegt"


# --- DIE ABLAEUFE ---

def richte_nutzer_ein(kennung, passwort="", anzeigename=""):
    """Nutzer, persoenlicher Ordner, Freigaben. Bericht als dict.

    Scheitert nie lautstark: LocaNoto hat den Nutzer zu diesem Zeitpunkt
    schon angelegt, und ein nicht erreichbares ownCloud darf das nicht
    rueckgaengig machen. Was nicht ging, steht im Bericht und laesst sich
    nachholen -- der Ablauf ist wiederholbar.
    """
    bericht = {"kennung": kennung, "schritte": [], "fehler": []}
    if not eingerichtet():
        bericht["fehler"].append("ownCloud ist nicht eingerichtet.")
        return bericht
    import raeume

    def tu(was, f):
        try:
            ergebnis = f()
            bericht["schritte"].append(
                f"{was}: {ergebnis if isinstance(ergebnis, str) else 'ok'}")
        except Exception as e:
            bericht["fehler"].append(f"{was}: {type(e).__name__}: {e}")

    if passwort:
        tu("Nutzer", lambda: nutzer_anlegen(kennung, passwort,
                                            anzeigename)[1])
    privat = raum_pfad(raeume.privat_kennung(kennung))
    tu("persoenlicher Ordner", lambda: ordner_anlegen(privat) and "angelegt")
    tu("Freigabe persoenlich",
       lambda: "gesetzt (%d dazu, %d weg)" % freigaben_setzen(
           privat, [kennung], LESEN_SCHREIBEN))
    allgemein = raum_pfad(raeume.ALLGEMEIN)
    tu("allgemeiner Ordner",
       lambda: ordner_anlegen(allgemein) and "angelegt")
    return bericht


def richte_raum_ein(raum, rechte=None):
    """Ordner und Freigaben eines Raums. Bericht als dict.

    Die Mitglieder kommen aus der Raumverwaltung, nicht aus ownCloud: dort
    stehen sie nur, WEIL sie hier stehen. Ein persoenlicher Raum bekommt
    genau einen Leser, und zwar den aus seiner Kennung -- nicht die
    Mitgliederliste, die es dort ohnehin nicht geben darf.
    """
    bericht = {"raum": raum, "schritte": [], "fehler": []}
    if not eingerichtet():
        bericht["fehler"].append("ownCloud ist nicht eingerichtet.")
        return bericht
    import benutzer
    import raeume

    pfad = zuordnung().get(raum) or raum_pfad(raum)
    eintrag = raeume.liste().get(raum) or {}

    if raeume.ist_privat(raum):
        personen = [raum[len(raeume.PRIVAT):]]
        gruppen_ = []
        wie = LESEN_SCHREIBEN
    elif raum == raeume.ALLGEMEIN:
        # Fuer alle lesbar, aber schreiben duerfen nur Verwalter -- dieselbe
        # Regel wie in raeume.schreibbar(). Waere der Ordner fuer alle
        # beschreibbar, liefe die Regel der Anwendung ins Leere, sobald
        # jemand die Datei ueber ownCloud hineinlegt.
        alle = [n for n in benutzer.namen()]
        personen = alle
        gruppen_ = []
        wie = rechte if rechte is not None else NUR_LESEN
        for a in benutzer.admins():
            try:
                freigeben(pfad, a, "nutzer", LESEN_SCHREIBEN)
            except Exception:
                pass
    else:
        personen = list(eintrag.get("mitglieder") or [])
        if "*" in personen:
            personen = list(benutzer.namen())
        gruppen_ = [eintrag["gruppe"]] if eintrag.get("gruppe") else []
        wie = rechte if rechte is not None else LESEN_SCHREIBEN

    try:
        ordner_anlegen(pfad)
        bericht["schritte"].append(f"Ordner {pfad}")
    except Exception as e:
        bericht["fehler"].append(f"Ordner: {type(e).__name__}: {e}")
        return bericht
    try:
        dazu, weg = freigaben_setzen(pfad, personen, wie, gruppen_)
        bericht["schritte"].append(f"Freigaben: {dazu} dazu, {weg} entfernt")
    except Exception as e:
        bericht["fehler"].append(f"Freigaben: {type(e).__name__}: {e}")
    return bericht
