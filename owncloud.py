"""Dokumente aus OpenCloud, oCIS, ownCloud oder Nextcloud -- je Raum ein Ordner.

"ownCloud" steht in diesem Modul fuer alle vier. Dateien und Freigaben
gehen ueberall gleich (WebDAV, OCS-Freigaben). Nur Nutzer und Gruppen
nicht: OpenCloud und oCIS fuehren sie ueber die Graph-Schnittstelle,
ownCloud 10 und Nextcloud ueber OCS. Welche Art Server dahinter steht,
sieht ist_graph() einmal nach.

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

import dateisperre
import paths

URL = os.getenv("OWNCLOUD_URL", "").strip().rstrip("/")
BENUTZER = os.getenv("OWNCLOUD_USER", "").strip()
PASSWORT = os.getenv("OWNCLOUD_PASSWORT", "")
TIMEOUT = paths.env_float("OWNCLOUD_TIMEOUT", 30)

# Das Zertifikat der Ablage pruefen. Abschalten nur fuer das mitgelieferte
# OpenCloud im selben Compose-Netz: es bringt ein selbst ausgestelltes
# Zertifikat mit, und der Weg dorthin verlaesst den Rechner nicht.
TLS_PRUEFEN = os.getenv("OWNCLOUD_TLS_PRUEFEN", "1").strip() != "0"

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

# Die ownCloud-Konten, die LocaNoto verwaltet. Nur diese loescht LocaNoto
# mit einem Benutzer mit, und nur bei diesen setzt es ein neues Passwort
# auch dort. Ein Konto, das es vorher schon gab, kann einem Menschen
# gehoeren, der es fuer alles andere im Haus benutzt; es zu loeschen
# nahme ihm seine Dateien.
KONTEN = os.path.join(paths.CONFIG_DIR, "owncloud_konten.json")

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
    dateisperre.schreibe_atomar(
        ZUORDNUNG, json.dumps({"raeume": neu}, ensure_ascii=False, indent=2))


def ordner_fuer(raum):
    """Der Ordner, der fuer diesen Raum gilt. None, wenn es ihn nicht gibt.

    Handzuordnung geht vor, sonst der Standardbaum -- also dasselbe, was
    zuordnung_wirksam() fuer alle Raeume liefert.

    Frueher stand hier zuordnung().get(raum), also NUR die Handzuordnung.
    Das war eine Funktion mit zwei Bedeutungen, und im Betrieb kam dabei
    heraus: der naechtliche Abgleich meldete fuer jeden Raum "kein Ordner
    eingerichtet", obwohl die Ordner standen und kurz zuvor etwas
    hineingeladen worden war. owncloud.json gibt es in einer
    eingebetteten Installation naemlich gar nicht.

    Wer die rohe Handzuordnung braucht -- die Oberflaeche, um
    "(Standard)" danebenzuschreiben --, ruft zuordnung().
    """
    return zuordnung_wirksam().get(raum)


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

    DER ALLGEMEINE RAUM IST DIE AUSNAHME und behaelt den Wurzelbereich.
    Genauso legt der Upload ab (siehe app.py): dort liegt der gewachsene
    Bestand, und ein Ingest ueber data/dokumente soll ihn als "(Basis)"
    sehen und nicht als Sachgebiet "allgemein".

    Vorher stand hier ein Unterordner, und die beiden Stellen waren sich
    uneinig. Sichtbar wurde es beim Spiegeln -- es fand im Unterordner
    nichts, waehrend die Dokumente im Wurzelbereich lagen. Schlimmer
    waere der Abgleich gewesen: er haette dieselben Dateien in den
    Unterordner geholt, neben die vorhandenen. Zweimal dasselbe
    Dokument, zweimal vektorisiert, zweimal in jeder Antwort -- das
    faellt nicht auf, es macht die Antworten nur langsam schlechter.
    """
    import raeume
    p = (paths.DOCS_DIR if raum == raeume.ALLGEMEIN
         else os.path.join(paths.DOCS_DIR, paths.sicherer_teil(raum)))
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
    # Oberflaeche und Zeitplan (spiegeln.py) koennen denselben Raum
    # zugleich abgleichen. Mit festem Zwischennamen schrieben beide in
    # DIESELBE Zwischendatei.
    dateisperre.schreibe_atomar(
        _stand_datei(raum), json.dumps(daten, ensure_ascii=False, indent=2))


# --- WEBDAV ---

def _neue_sitzung(auth):
    """Jede Verbindung zur Ablage entsteht hier -- mit derselben Pruefung."""
    s = requests.Session()
    s.auth = auth
    s.verify = TLS_PRUEFEN
    return s


def _sitzung():
    return _neue_sitzung((BENUTZER, PASSWORT))


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
        return False, ("Anmeldung abgelehnt. OpenCloud und oCIS nehmen "
                       "ein App-Token an, nicht das Anmeldepasswort; "
                       "ebenso ownCloud und Nextcloud bei aktiver "
                       "Zwei-Faktor-Anmeldung.")
    if a.status_code == 404:
        return False, ("Kein WebDAV unter dieser Adresse. Erwartet: Wurzel der Installation, etwa https://cloud.firma.de")
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


def stand(fern):
    """(groesse, etag) einer einzelnen Datei, oder None.

    Gebraucht fuer Listen, die in ownCloud liegen: die Zusage lautet,
    dass ergaenzte Zeilen in der naechsten Frage wirken. Bei einer
    lokalen Datei kostet das ein stat(); hier ist es ein PROPFIND, und
    das etag ist die Angabe, an der eine Aenderung haengt.

    dateien() ueber den ganzen Ordner waere der einfachere Weg und der
    falsche: er kostet einen Rundlauf JE VERZEICHNIS, auch wenn nur
    eine Datei gefragt ist.
    """
    try:
        with _sitzung() as s:
            for name, ordner, groesse, etag, _g in _eintraege(s, fern):
                if not ordner:
                    return groesse, etag
    except Exception:
        return None
    return None


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


def lege_ab(quelle, fern, ueberschreiben=False):
    """Legt eine Datei in ownCloud ab. (ok, meldung).

    Bis hierher schrieb die Anwendung NIE nach ownCloud zurueck -- der
    Weg ging nur hinein. Das war richtig, solange ownCloud eine fremde
    Ablage war, die jemand anders pflegt.

    Seit LocaNoto den Ordnerbaum selbst anlegt und freigibt, ist es
    falsch: der Nutzer bekommt einen Ordner privat/<kennung>/, der leer
    bleibt, waehrend seine hochgeladenen Dateien woanders liegen. Zwei
    Ablagen fuer dieselbe Sache, und niemand sieht die zweite.

    Der Zweck der ganzen Anbindung ist, dass alles Gespeicherte auf
    entkoppeltem Speicher liegt und nicht neben dem Abbild. Ein Upload,
    der das nicht tut, hebt ihn auf.
    """
    if not eingerichtet():
        return False, "ownCloud ist nicht eingerichtet."
    ordner_anlegen(os.path.dirname(fern))
    try:
        with _sitzung() as s:
            if not ueberschreiben:
                # Nicht blind ueberschreiben: derselbe Dateiname kann
                # dort schon etwas anderes sein, das jemand haendisch
                # abgelegt hat.
                a = s.request("PROPFIND", _url(fern), data=_PROPFIND,
                              headers={"Depth": "0",
                                       "Content-Type": "application/xml"},
                              timeout=TIMEOUT)
                if a.status_code == 207:
                    return False, (f"'{os.path.basename(fern)}' liegt dort "
                                   f"schon. Nicht ueberschrieben.")
            daten = (quelle if isinstance(quelle, (bytes, bytearray))
                     else open(quelle, "rb").read())
            a = s.put(_url(fern), data=daten, timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f"Nicht abgelegt: {e}"
    if a.status_code not in (200, 201, 204):
        return False, f"Nicht abgelegt, ownCloud antwortete {a.status_code}."
    return True, f"In ownCloud abgelegt: {fern}"


# --- LOESCHEN UND VERSCHIEBEN ---
#
# Was in LocaNoto geloescht oder verschoben wird, geschieht in ownCloud
# mit. Ohne das holte der naechste Abgleich die Datei zurueck: er
# behandelt eine Datei, die in ownCloud liegt und lokal fehlt, als neu
# (siehe plane()). Ein geloeschtes Dokument stand dann am Morgen wieder
# in der Suche, und ein aus einem geteilten Raum herausgenommenes wieder
# in dem geteilten Raum.
#
# Geloescht wird ueber WebDAV DELETE. ownCloud legt die Datei dabei in
# seinen Papierkorb, solange die Papierkorb-App aktiv ist (Vorgabe); von
# dort laesst sie sich wiederherstellen.

def fern_pfad(raum, dateiname, lokal=""):
    """Wo die ownCloud-Fassung dieser Datei liegt.

    Mit lokalem Pfad dieselbe Abbildung wie beim Hochladen (ziel_pfad).
    Ohne ihn -- die lokale Kopie fehlt -- hilft der Stand des Abgleichs:
    er kennt den Pfad jeder geholten Datei. Gibt es dort genau einen
    Eintrag dieses Namens, ist es der; sonst der Name direkt im Ordner
    des Raums.
    """
    if lokal:
        return ziel_pfad(raum, lokal)
    wurzel = (ordner_fuer(raum) or raum_pfad(raum)).rstrip("/")
    treffer = [rel for rel in _stand_lesen(raum)
               if os.path.basename(rel) == dateiname]
    rel = treffer[0] if len(treffer) == 1 else dateiname
    return f"{wurzel}/{rel.lstrip('/')}"


def entferne(raum, dateiname, lokal=""):
    """Loescht die ownCloud-Fassung einer Datei dieses Raums.

    (ok, meldung). Eine Datei, die dort nicht liegt, ist kein Fehler --
    nicht jeder Raum hat einen ownCloud-Ordner, und nicht jede Datei kam
    ueber ihn. Ein Fehler ist, wenn sie dort liegt und bleibt: dann holt
    der naechste Abgleich sie zurueck, und das muss die Oberflaeche sagen.
    """
    if not eingerichtet():
        return True, ""
    fern = fern_pfad(raum, dateiname, lokal)
    try:
        with _sitzung() as s:
            a = s.delete(_url(fern), timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f'In ownCloud nicht gelöscht ({type(e).__name__}).'
    if a.status_code == 404:
        return True, ""
    if a.status_code in (200, 204):
        return True, f'Auch in ownCloud gelöscht: {fern}'
    return False, f'In ownCloud nicht gelöscht, Antwort: {a.status_code}.'


def verschiebe(von_raum, von_lokal, nach_raum, nach_lokal):
    """Verschiebt die ownCloud-Fassung in den Ordner des Zielraums.

    (ok, meldung). WebDAV MOVE, ohne zu ueberschreiben: liegt am Ziel
    schon eine Datei dieses Namens, bleibt alles, wie es ist, und das
    wird gesagt.
    """
    if not eingerichtet():
        return True, ""
    von = ziel_pfad(von_raum, von_lokal)
    nach = ziel_pfad(nach_raum, nach_lokal)
    if von == nach:
        return True, ""
    try:
        ordner_anlegen(os.path.dirname(nach))
        with _sitzung() as s:
            a = s.request("MOVE", _url(von),
                          headers={"Destination": _url(nach),
                                   "Overwrite": "F"},
                          timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f"In ownCloud nicht verschoben ({type(e).__name__})."
    if a.status_code == 404:
        return True, ""
    if a.status_code in (201, 204):
        return True, f"Auch in ownCloud verschoben: {nach}"
    if a.status_code == 412:
        return False, (f"In ownCloud nicht verschoben: '{os.path.basename(nach)}' gibt es am Ziel schon.")
    return False, f'In ownCloud nicht verschoben, Antwort: {a.status_code}.'


# --- GRUPPEN ---
#
# Die Provisioning-Schnittstelle (OCS) statt WebDAV. Sie liefert JSON, wenn
# man danach fragt, und verlangt den Kopf OCS-APIRequest -- ohne ihn
# antwortet die Installation mit einer Anmeldeseite statt mit Daten.

def _ocs(pfad, sitzung=None):
    """Ein OCS-Aufruf. Gibt den Inhalt von ocs.data zurueck."""
    url = URL + "/ocs/v1.php/cloud/" + str(pfad).lstrip("/")
    eigene = sitzung is None
    s = sitzung or _neue_sitzung((ADMIN_BENUTZER, ADMIN_PASSWORT))
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
        raise ValueError("Keine OCS-Antwort – zeigt die Adresse auf die Wurzel der Installation?") from e
    stand = (umschlag.get("meta") or {}).get("statuscode")
    # 100 (v1) und 200 (v2) heissen beide "in Ordnung". 997 heisst "nicht
    # berechtigt" -- und das ist der Fall, den man erklaeren muss: die
    # Gruppenabfrage braucht ein Verwalterkonto.
    if stand == 997:
        raise PermissionError(
            "Nicht berechtigt: Die Gruppenabfrage braucht ein ownCloud-Admin-Konto (OWNCLOUD_ADMIN_USER).")
    if stand not in (100, 200):
        raise ValueError("ownCloud antwortete mit Status " + str(stand))
    return umschlag.get("data") or {}


def gruppen():
    """Die Gruppennamen der Installation, sortiert."""
    if ist_graph():
        return sorted(str(g.get("displayName") or "")
                      for g in (_graph("GET", "groups") or {}).get("value", [])
                      if g.get("displayName"))
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
    if ist_graph():
        return _graph_mitglieder(gruppe)
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
    with _neue_sitzung((ADMIN_BENUTZER, ADMIN_PASSWORT)) as s:
        for raum, gruppe in sorted(zu.items()):
            if gruppe in gefunden:
                continue  # zwei Raeume, dieselbe Gruppe
            try:
                if ist_graph():
                    gefunden[gruppe] = _graph_mitglieder(gruppe)
                else:
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

    dateisperre.schreibe_atomar(
        paths.GRUPPEN_DATEI,
        json.dumps({"aktualisiert": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "gruppen": zusammen}, ensure_ascii=False, indent=2))

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
        raise ValueError(f"Für Arbeitsbereich '{raum}' ist kein Ordner eingerichtet.")
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
    with _neue_sitzung((ADMIN_BENUTZER, ADMIN_PASSWORT)) as s:
        a = s.request(methode, url, params={"format": "json"},
                      data=daten or None,
                      headers={"OCS-APIRequest": "true"}, timeout=TIMEOUT)
    if a.status_code == 401:
        raise PermissionError("Anmeldung abgelehnt.")
    a.raise_for_status()
    try:
        umschlag = a.json()["ocs"]
    except (ValueError, KeyError) as e:
        raise ValueError("Keine OCS-Antwort – zeigt die Adresse auf die Wurzel der Installation?") from e
    meta = umschlag.get("meta") or {}
    stand = meta.get("statuscode")
    if stand == 997:
        raise PermissionError(
            "Nicht berechtigt: Benutzer anlegen und Ordner freigeben braucht ein ownCloud-Admin-Konto (OWNCLOUD_ADMIN_USER).")
    if stand not in (100, 200):
        raise ValueError(f"ownCloud antwortete mit Status {stand}"
                         + (f": {meta.get('message')}"
                            if meta.get("message") else ""))
    return umschlag.get("data") or {}


# --- GRAPH (OpenCloud, oCIS) ---
#
# Dort gibt es /ocs/v1.php/cloud nicht mehr -- Nutzer und Gruppen stehen
# unter /graph/v1.0. Angemeldet wird mit einem App-Token als Passwort; die
# Anmeldung mit dem echten Passwort ist dort fuer den Betrieb abgeschaltet.

# Welche Art Server unter einer Adresse steht, je URL gemerkt. Nur eine
# Antwort wird gemerkt, kein Fehler: ein Server, der gerade startet, soll
# beim naechsten Mal noch einmal gefragt werden.
_GRAPH = {}

# Kennungen, die OpenCloud und oCIS annehmen: Anfang Buchstabe oder
# Unterstrich, danach Buchstaben, Ziffern, Punkt, Strich, Unterstrich.
# LocaNoto selbst erlaubt mehr (Umlaute, Ziffer vorn) -- solche Konten
# lehnt der Server ab, und das soll vorher und verstaendlich gesagt sein.
_GRAPH_KENNUNG = re.compile(r"[a-z_][a-z0-9_.-]*")


def ist_graph():
    """True bei OpenCloud und oCIS, False bei ownCloud 10 und Nextcloud."""
    if URL not in _GRAPH:
        with _neue_sitzung((ADMIN_BENUTZER, ADMIN_PASSWORT)) as s:
            a = s.get(f"{URL}/graph/v1.0/me", timeout=TIMEOUT)
        if a.status_code == 401:
            raise PermissionError("Anmeldung abgelehnt.")
        if a.status_code == 404:
            _GRAPH[URL] = False
        elif a.ok:
            # ownCloud 10 leitet unbekannte Pfade auf eine Anmeldeseite
            # um: 200, aber HTML.
            try:
                _GRAPH[URL] = "id" in a.json()
            except ValueError:
                _GRAPH[URL] = False
        else:
            a.raise_for_status()
    return _GRAPH[URL]


def _graph(methode, pfad, daten=None, params=None):
    """Ein Graph-Aufruf als Verwalter. dict, {} ohne Inhalt, None bei 404."""
    with _neue_sitzung((ADMIN_BENUTZER, ADMIN_PASSWORT)) as s:
        a = s.request(methode, f"{URL}/graph/v1.0/{str(pfad).lstrip('/')}",
                      json=daten, params=params, timeout=TIMEOUT)
    if a.status_code == 404:
        return None
    if a.status_code in (401, 403):
        raise PermissionError(
            "Nicht berechtigt: Benutzer und Gruppen verwalten braucht ein Admin-Konto (OWNCLOUD_ADMIN_USER).")
    if not a.ok:
        try:
            grund = a.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            grund = a.text[:200]
        raise ValueError(f"Antwort {a.status_code}: {grund}")
    if not a.content:
        return {}
    return a.json()


def _graph_mitglieder(gruppe):
    """Die Kennungen einer Gruppe, klein geschrieben."""
    daten = _graph("GET", "groups/" + quote(str(gruppe), safe=""),
                   params={"$expand": "members"})
    if daten is None:
        raise ValueError(f"Gruppe '{gruppe}' gibt es nicht.")
    return sorted({str(m.get("onPremisesSamAccountName") or "").lower()
                   for m in daten.get("members") or []}
                  - {""})


# --- PFADE ---

def raum_pfad(raum):
    """Der ownCloud-Ordner eines Raums im Bereich des Dienstkontos."""
    import raeume
    if raum == raeume.ALLGEMEIN:
        return f"/{WURZEL}/allgemein"
    if raeume.ist_privat(raum):
        return f"/{WURZEL}/privat/{raum[len(raeume.PRIVAT):]}"
    return f"/{WURZEL}/raeume/{paths.sicherer_teil(raum)}"


def ziel_pfad(raum, lokal):
    """Wohin eine lokale Datei dieses Raums in ownCloud gehoert.

    Der Pfad RELATIV zur Ablage des Raums bleibt erhalten. Wer nur den
    Dateinamen nimmt, verliert den Projektordner -- dann liegt in
    ownCloud alles flach nebeneinander, und das Projekt steht nur noch
    in den Metadaten, also nirgends, wo es jemand sieht.

    Die Wurzel kommt aus ordner_fuer(): Handzuordnung zuerst, sonst der
    Standardbaum -- dieselbe, aus der der Abgleich liest. Wer hier
    raum_pfad() nimmt, schreibt bei einer eingetragenen Handzuordnung
    woanders hin, als spaeter gelesen wird.
    """
    wurzel = ordner_fuer(raum) or raum_pfad(raum)
    rel = os.path.relpath(lokal, ablage(raum)).replace("\\", "/")
    return wurzel.rstrip("/") + "/" + rel.lstrip("./")


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
                    f'Darf {gebaut} nicht anlegen -- Rechte des Kontos {BENUTZER} prüfen.')
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


def _unbekannt(fehler):
    """Lehnt die Ablage ab, weil es den Empfaenger dort nicht gibt?

    OCS antwortet dann mit Status 998 ("user not found"). Nach einem
    Umzug auf eine neue Ablage ist das der Normalfall: Konten entstehen
    erst beim naechsten Passwortsetzen.
    """
    text = str(fehler).lower()
    return isinstance(fehler, ValueError) and ("998" in text
                                               or "not found" in text)


def freigaben_setzen(pfad, personen, rechte=NUR_LESEN, gruppen_=(),
                     ohne_konto=None):
    """Bringt die Freigaben eines Ordners auf genau diesen Stand.

    personen ist eine Liste (dann gilt rechte fuer alle) ODER eine
    Zuordnung {kennung: rechte}. Zwei Stufen im selben Ordner sind kein
    Sonderfall: im allgemeinen Raum lesen alle und schreiben nur
    Verwalter -- dieselbe Regel wie in raeume.schreibbar().

    SETZEN und nicht ergaenzen, und zwar in drei Richtungen:

      * wer nicht mehr dazugehoert, verliert die Freigabe. Ein Mitglied
        zu entfernen und die Freigabe stehen zu lassen waere die
        haeufigste Art, eine Rechteaenderung wirkungslos zu machen: die
        Suche fragt den Raum nicht mehr, die Dateien laegen aber weiter
        im ownCloud des Ausgeschiedenen.
      * wer dazukommt, bekommt sie.
      * wessen RECHTE sich geaendert haben, bekommt die neuen. Das war
        zuerst vergessen -- ein zum Nutzer zurueckgestufter Verwalter
        behielt sein Schreibrecht, und jeder Lauf legte obendrein eine
        zweite Freigabe an.

    Wen es in der Ablage (noch) nicht gibt, der wird uebersprungen und in
    ohne_konto (eine Liste, falls uebergeben) vermerkt -- statt mit ihm
    die Freigaben aller anderen abzubrechen. Seine Freigabe folgt, wenn
    sein Konto entsteht (passwort_setzen).

    Rueckgabe: (hinzugefuegt, entfernt).
    """
    if isinstance(personen, dict):
        soll_n = {str(k).strip().lower(): int(v)
                  for k, v in personen.items() if str(k).strip()}
    else:
        soll_n = {str(p).strip().lower(): int(rechte)
                  for p in personen if str(p).strip()}
    soll_g = {str(g).strip(): int(rechte) for g in gruppen_ if str(g).strip()}

    ist = freigaben(pfad)
    dazu, weg = 0, 0
    hat_n, hat_g = {}, {}
    for f in ist:
        if f["art"] == 0:
            soll = soll_n.get(f["an"].lower())
        elif f["art"] == 1:
            soll = soll_g.get(f["an"])
        else:
            continue
        # Weg, wenn nicht mehr vorgesehen ODER mit anderen Rechten. Ein
        # Entfernen und Neuanlegen ist hier richtiger als ein Aendern:
        # die OCS-Fassungen unterscheiden sich darin, und ein Fehlgriff
        # liesse das alte Recht stehen.
        if soll is None or soll != f["rechte"]:
            freigabe_entfernen(f["id"])
            weg += 1
            continue
        (hat_n if f["art"] == 0 else hat_g)[
            f["an"].lower() if f["art"] == 0 else f["an"]] = f["rechte"]

    for k, r in sorted(soll_n.items()):
        if k not in hat_n:
            try:
                freigeben(pfad, k, "nutzer", r)
            except ValueError as e:
                if not _unbekannt(e):
                    raise
                if ohne_konto is not None:
                    ohne_konto.append(k)
                continue
            dazu += 1
    for g, r in sorted(soll_g.items()):
        if g not in hat_g:
            try:
                freigeben(pfad, g, "gruppe", r)
            except ValueError as e:
                if not _unbekannt(e):
                    raise
                if ohne_konto is not None:
                    ohne_konto.append(f"Gruppe {g}")
                continue
            dazu += 1
    return dazu, weg


# --- NUTZER ---

def nutzer_vorhanden(kennung):
    if ist_graph():
        return _graph("GET", "users/" + quote(str(kennung), safe="")) \
            is not None
    try:
        _ocs_ruf("GET", f"users/{kennung}")
        return True
    except ValueError:
        return False


# --- VERWALTETE KONTEN ---

def verwaltete_konten():
    """Die Kennungen der Konten, die LocaNoto in ownCloud verwaltet."""
    try:
        with open(KONTEN, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return set()
    return {str(k).lower() for k in (daten.get("konten") or [])}


def _konten_aendern(dazu=(), weg=()):
    with dateisperre.gesperrt(KONTEN):
        k = (verwaltete_konten() | {str(x).lower() for x in dazu}) \
            - {str(x).lower() for x in weg}
        dateisperre.schreibe_atomar(
            KONTEN, json.dumps({"konten": sorted(k)}, indent=1))


def geschuetzt(kennung):
    """Das Dienst- und das Verwalterkonto fasst LocaNoto nie an.

    Heisst ein LocaNoto-Nutzer zufaellig wie eines von beiden -- "admin"
    ist der naheliegende Fall --, loeschte das Loeschen dieses Nutzers
    sonst das Konto, mit dem LocaNoto selbst in ownCloud arbeitet.
    """
    k = str(kennung or "").lower()
    return k in {BENUTZER.lower(), ADMIN_BENUTZER.lower()} - {""}


def verwaltet(kennung):
    return (not geschuetzt(kennung)
            and str(kennung or "").lower() in verwaltete_konten())


def konten_uebernehmen(kennungen):
    """Bestehende Konten als von LocaNoto verwaltet vermerken.

    Fuer Installationen, in denen LocaNoto die Konten angelegt hat, bevor
    es sich das merkte. Ausdruecklich ein Schritt des Verwalters: nur er
    weiss, ob die Konten dieser ownCloud LocaNoto gehoeren oder dem Haus.
    Rueckgabe: (uebernommen, uebersprungen) als Listen.
    """
    dazu, aus = [], []
    for k in sorted({str(x).lower() for x in kennungen}):
        if geschuetzt(k):
            aus.append(f"{k} (Dienstkonto)")
            continue
        try:
            if nutzer_vorhanden(k):
                dazu.append(k)
            else:
                aus.append(f"{k} (kein Konto in ownCloud)")
        except Exception as e:
            aus.append(f"{k} ({type(e).__name__})")
    if dazu:
        _konten_aendern(dazu=dazu)
    return dazu, aus


def konto_loeschen(kennung):
    """Loescht das ownCloud-Konto eines geloeschten Benutzers. (ok, meldung).

    Nur ein verwaltetes Konto. Mit ihm gehen seine eigenen Dateien und
    alle Freigaben an ihn. Der persoenliche Ordner im Bereich des
    Dienstkontos bleibt -- so wie der persoenliche Raum in LocaNoto
    bleibt, bis ein Verwalter ihn leert.
    """
    if not eingerichtet():
        return True, ""
    if geschuetzt(kennung):
        return False, (f"'{kennung}' ist das ownCloud-Dienstkonto von LocaNoto – nicht gelöscht.")
    if not verwaltet(kennung):
        return False, (f"ownCloud-Konto '{kennung}' wird nicht von LocaNoto verwaltet und bleibt bestehen. Übernehmen unter ownCloud -> Konten.")
    try:
        if nutzer_vorhanden(kennung):
            if ist_graph():
                _graph("DELETE", "users/" + quote(str(kennung), safe=""))
            else:
                _ocs_ruf("DELETE", f"users/{kennung}")
    except Exception as e:
        return False, f'ownCloud-Konto nicht gelöscht ({type(e).__name__}: {e}).'
    _konten_aendern(weg=[kennung])
    return True, f"Auch das ownCloud-Konto '{kennung}' ist gelöscht."


def passwort_setzen(kennung, passwort):
    """Setzt das Passwort eines verwalteten Kontos. (ok, meldung)."""
    if not eingerichtet():
        return True, ""
    try:
        # Kein Konto dort: nach einem Umzug in eine neue Ablage der
        # Normalfall, denn Passwoerter lassen sich nicht mitnehmen. Dann
        # entsteht es jetzt, mit diesem Passwort -- niemandem wird dabei
        # etwas weggenommen.
        if not geschuetzt(kennung) and not nutzer_vorhanden(kennung):
            nutzer_anlegen(kennung, passwort)
            nachgezogen = freigaben_nachziehen(kennung)
            return True, ("In ownCloud neu angelegt, mit diesem Passwort"
                          + (f"; Freigaben in {nachgezogen} Raeumen "
                             f"nachgezogen." if nachgezogen else "."))
        if not verwaltet(kennung):
            return False, ("In ownCloud gilt weiter das alte Passwort – LocaNoto verwaltet dieses Konto nicht.")
        if ist_graph():
            _graph("PATCH", "users/" + quote(str(kennung), safe=""),
                   daten={"passwordProfile": {"password": passwort}})
        else:
            _ocs_ruf("PUT", f"users/{kennung}",
                     daten={"key": "password", "value": passwort})
    except Exception as e:
        # ownCloud hat eine eigene Passwortregel. Lehnt sie ab, steht der
        # Grund in der Meldung.
        return False, f'In ownCloud nicht geändert ({type(e).__name__}: {e}).'
    return True, "Auch in ownCloud geändert."


def freigaben_nachziehen(kennung):
    """Die Raumordner, die dieser Nutzer lesen darf, an ihn freigeben.

    Fuer ein Konto, das gerade erst entstanden ist -- vorher hat die
    Ablage seine Freigaben abgelehnt (freigaben_setzen: ohne_konto).
    Wiederholbar wie richte_raum_ein. Anzahl der Raeume ohne Fehler.
    """
    import raeume
    zahl = 0
    for raum in raeume.lesbar(kennung):
        try:
            if not richte_raum_ein(raum).get("fehler"):
                zahl += 1
        except Exception:
            pass
    return zahl


def leere_raumordner(raum):
    """Legt den Inhalt des ownCloud-Ordners eines Raums in den Papierkorb.

    Fuer "Daten loeschen": ohne das holte der naechste Abgleich jede Datei
    des Raums als neu zurueck. Der Ordner selbst und seine Freigaben
    bleiben -- der Raum besteht ja weiter.

    Rueckgabe: (anzahl, fehler).
    """
    if not eingerichtet():
        return 0, []
    ordner = ordner_fuer(raum) or raum_pfad(raum)
    weg, fehler = 0, []
    try:
        with _sitzung() as s:
            for name, _o, _g, _e, _d in _eintraege(s, ordner):
                a = s.delete(_url(f"{ordner.rstrip('/')}/{name}"),
                             timeout=TIMEOUT)
                if a.status_code in (200, 204, 404):
                    weg += 1
                else:
                    fehler.append(f"{name}: {a.status_code}")
    except FileNotFoundError:
        return 0, []
    except requests.RequestException as e:
        fehler.append(f"{type(e).__name__}")
    # Der Stand des Abgleichs kennt die Dateien noch. Leer heisst: beim
    # naechsten Lauf gibt es nichts zu entfernen und nichts zu holen.
    try:
        os.remove(_stand_datei(raum))
    except OSError:
        pass
    return weg, fehler


def nutzer_anlegen(kennung, passwort, anzeigename=""):
    """Legt einen ownCloud-Nutzer an. True, wenn er danach existiert.

    Ein bereits vorhandener Nutzer ist kein Fehler: LocaNoto wird oft auf
    ein Haus gesetzt, in dem es die Leute in ownCloud laengst gibt.
    """
    if nutzer_vorhanden(kennung):
        return False, "gab es schon"
    if ist_graph():
        if not _GRAPH_KENNUNG.fullmatch(str(kennung)):
            raise ValueError(
                f"'{kennung}' ist als Kennung für OpenCloud und oCIS ungültig: Buchstabe am Anfang, dann nur a-z, 0-9, Punkt, Strich, Unterstrich.")
        # Der Anzeigename ist dort Pflicht.
        _graph("POST", "users", daten={
            "onPremisesSamAccountName": kennung,
            "displayName": anzeigename or kennung,
            "passwordProfile": {"password": passwort}})
    else:
        daten = {"userid": kennung, "password": passwort}
        if anzeigename:
            daten["displayName"] = anzeigename
        _ocs_ruf("POST", "users", daten=daten)
    # Ab hier gehoert das Konto LocaNoto: es loescht und aendert es mit.
    _konten_aendern(dazu=[kennung])
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
           privat, [kennung], LESEN_SCHREIBEN, ohne_konto=[]))
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
        # Fuer alle lesbar, aber schreiben duerfen nur Verwalter --
        # dieselbe Regel wie in raeume.schreibbar(). Waere der Ordner fuer
        # alle beschreibbar, liefe die Regel der Anwendung ins Leere,
        # sobald jemand die Datei ueber ownCloud hineinlegt.
        #
        # Beides in EINER Zuordnung und nicht als zweiter Aufruf: eine
        # Extraschleife legte bei jedem Lauf eine weitere Freigabe an,
        # weil sie nicht nachsah, ob es sie schon gibt.
        verwalter = set(benutzer.admins())
        personen = {n: (LESEN_SCHREIBEN if n in verwalter
                        else (rechte if rechte is not None else NUR_LESEN))
                    for n in benutzer.namen()}
        gruppen_ = []
        wie = rechte if rechte is not None else NUR_LESEN
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
        ohne = []
        dazu, weg = freigaben_setzen(pfad, personen, wie, gruppen_,
                                     ohne_konto=ohne)
        bericht["schritte"].append(f"Freigaben: {dazu} dazu, {weg} entfernt")
        if ohne:
            # Kein Fehler: der Raum steht, und wer noch kein Konto hat,
            # bekommt seine Freigabe, sobald es entsteht.
            bericht["schritte"].append(
                "Noch ohne Konto in der Ablage, Freigabe folgt mit dem "
                "Konto: " + ", ".join(ohne))
    except Exception as e:
        bericht["fehler"].append(f"Freigaben: {type(e).__name__}: {e}")
    return bericht
