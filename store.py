"""Zugang zur Vektordatenbank -- an einer Stelle.

Bisher legte jedes Skript seinen eigenen PersistentClient an. Das geht,
solange immer nur ein Prozess arbeitet. Sobald neben der Oberflaeche eine
zweite Bedienung steht, schreiben zwei Prozesse in dieselben Dateien --
dafuer ist die Dateiablage nicht gebaut. Die Folge waere kein sauberer
Fehler, sondern ein beschaedigter Index, und der faellt erst auf, wenn
Antworten fehlen.

Ist CHROMA_HOST gesetzt, spricht die Anwendung stattdessen einen
Chroma-Server an. Dann sind Oberflaeche, Schnittstelle und die
Ingest-Skripte allesamt Clients, und wer schreiben darf, entscheidet der
Server statt des Zufalls.

Ohne CHROMA_HOST bleibt es bei der Dateiablage -- richtig, solange nur ein
Prozess zugreift, und die Voreinstellung fuer eine Einzelinstallation.
"""
import os
import time

import chromadb

import paths

CHROMA_HOST = os.getenv("CHROMA_HOST", "").strip()
CHROMA_PORT = paths.env_int("CHROMA_PORT", 8000)

# --- FREMDBETRIEB ---
#
# Bis hierher gab es zwei Faelle: Dateiablage im Container oder ein
# Chroma-Server daneben. Beides laeuft beim Betreiber. Wer die Datenbank
# stattdessen verwaltet einkaufen will -- gehostetes Chroma oder ein
# Server bei einem Anbieter --, braucht zwei Dinge mehr: TLS und ein
# Zugangsmerkmal.
#
# Ohne Token ist ein erreichbarer Chroma-Server offen. Er kennt keine
# Nutzer; wer ihn erreicht, darf alles, auch Sammlungen loeschen. Solange
# er im selben Docker-Netz steht, deckt das Netz ihn ab. Sobald er darueber
# hinaus erreichbar ist, ist das Zugangsmerkmal nicht optional.
CHROMA_SSL = os.getenv("CHROMA_SSL", "").strip().lower() in ("1", "true",
                                                             "ja", "yes")
CHROMA_TOKEN = os.getenv("CHROMA_TOKEN", "").strip()
# Chroma erwartet das Merkmal in X-Chroma-Token; hinter einem Proxy ist es
# manchmal Authorization. Deshalb einstellbar statt festgelegt.
CHROMA_TOKEN_HEADER = (os.getenv("CHROMA_TOKEN_HEADER", "").strip()
                       or "X-Chroma-Token")

# Gehostetes Chroma. Eigener Client, weil dort Mandant und Datenbank an die
# Stelle von Wirt und Port treten.
CHROMA_CLOUD_KEY = os.getenv("CHROMA_CLOUD_KEY", "").strip()
CHROMA_CLOUD_TENANT = os.getenv("CHROMA_CLOUD_TENANT", "").strip()
CHROMA_CLOUD_DATABASE = (os.getenv("CHROMA_CLOUD_DATABASE", "").strip()
                         or "locanoto")

_client = None


def im_server_betrieb():
    return bool(CHROMA_HOST or CHROMA_CLOUD_KEY)


def client():
    """Der Chroma-Client dieses Prozesses.

    Einmal erzeugt und behalten: ein PersistentClient legt beim Anlegen die
    Dateien offen, und ein zweiter auf demselben Pfad ist genau der Fall,
    den dieses Modul vermeiden soll.
    """
    global _client
    if _client is None:
        if CHROMA_CLOUD_KEY:
            _client = chromadb.CloudClient(
                tenant=CHROMA_CLOUD_TENANT or None,
                database=CHROMA_CLOUD_DATABASE,
                api_key=CHROMA_CLOUD_KEY)
        elif CHROMA_HOST:
            kopf = ({CHROMA_TOKEN_HEADER: CHROMA_TOKEN}
                    if CHROMA_TOKEN else None)
            _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT,
                                          ssl=CHROMA_SSL, headers=kopf)
        else:
            _client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
    return _client


def collection(anlegen=True):
    """Die alte, gemeinsame Sammlung -- nur noch fuer die Umsortierung.

    Vor den Raeumen lagen alle Abschnitte hier, unterschieden durch die
    Merkmale access und owner. Neuer Code nimmt sammlung() mit einem
    Raumnamen; diese Funktion bleibt, damit die Umsortierung den alten
    Bestand lesen kann.
    """
    c = client()
    if anlegen:
        return c.get_or_create_collection(name=paths.COLLECTION_NAME)
    return c.get_collection(name=paths.COLLECTION_NAME)


# Gefundene Sammlungen behalten.
#
# get_collection() ist ein HTTP-Aufruf. Streamlit fuehrt das Skript bei
# JEDEM Klick von oben nach unten aus, und die Sammlungen werden dabei an
# mehreren Stellen aufgeloest -- gemessen 13 bis 16 Rundlaeufe je Klick,
# nur um Handles zu holen, die sich nie aendern.
#
# Nur ERFOLGE werden behalten. Ein None -- die Sammlung gibt es noch nicht
# -- darf nicht haengen bleiben, sonst waere ein Raum nach seinem ersten
# Upload bis zum Neustart leer. Wer loescht, raeumt hier mit auf.
_sammlungen = {}


def vergiss(name=None):
    """Gemerkte Handles verwerfen -- alle oder eines."""
    if name is None:
        _sammlungen.clear()
    else:
        _sammlungen.pop(name, None)


def _segment_fehlt(fehler):
    t = str(fehler).lower()
    return "nothing found on disk" in t or "segment reader" in t


def hole(sml, name=None, versuche=3, **kw):
    """sml.get(**kw) -- mit Wiederholung gegen einen Chroma-Fehlschlag.

    Der Fehlschlag, um den es geht:

        Error creating hnsw segment reader: Nothing found on disk

    Chroma legt das Vektorsegment einer Sammlung verzoegert ab. Wird eine
    kleine Sammlung gelesen, bevor das geschehen ist, findet der Leser die
    Datei nicht. Gemessen an 40 Laeufen des Selbsttests: zwei Fehlschlaege
    -- und jeder kostete einen ganzen Raum.

    Wiederholen allein genuegt nicht: der Leser merkt sich den Zustand,
    und derselbe Client scheitert wieder, auch nach einer Pause. Deshalb
    dazwischen neu verbinden. Bringt das nichts (Serverbetrieb), wird
    nicht sinnlos wiederholt, sondern der Fehler weitergegeben -- dort
    entscheidet der Server, wann er ablegt.

    name ist der Sammlungsname. Ohne ihn wird nach dem Neuverbinden das
    alte Handle weiterbenutzt; das geht meist, aber mit Namen ist es
    sauber.
    """
    letzter = None
    for versuch in range(max(1, versuche)):
        try:
            return sml.get(**kw)
        except Exception as e:
            letzter = e
            if not _segment_fehlt(e):
                raise
            time.sleep(0.2 * (versuch + 1))
            if not neu_verbinden():
                raise
            if name:
                frisch = sammlung(name, anlegen=False)
                if frisch is not None:
                    sml = frisch
    raise letzter


def neu_verbinden():
    """Verwirft den Client samt aller Handles. True, wenn das etwas bringt.

    Gebraucht fuer einen einzigen Fehlschlag, der sich anders nicht
    beheben laesst:

        Error creating hnsw segment reader: Nothing found on disk

    Bei der Dateiablage legt Chroma das Vektorsegment einer Sammlung
    verzoegert ab. Wird eine kleine Sammlung gelesen, bevor das geschehen
    ist, findet der Leser die Datei nicht -- und er merkt sich diesen
    Zustand: eine Wiederholung mit demselben Client scheitert genauso,
    auch nach einer Pause. Erst ein neuer Client liest den Bestand aus
    dem Journal und baut das Segment auf.

    Nur bei der Dateiablage. Im Serverbetrieb entscheidet der Server, wann
    er ablegt; einen neuen HTTP-Client aufzubauen aendert daran nichts,
    und ein Wiederverbinden mitten in einem Ablauf waere dort nur ein
    weiterer Weg, etwas kaputtzumachen.
    """
    global _client
    if im_server_betrieb():
        return False
    _sammlungen.clear()
    _client = None
    try:
        # Der offizielle Weg. Chroma merkt sich das System je Pfad -- ein
        # zweiter PersistentClient auf denselben Ordner bekaeme genau das
        # alte zurueck, und ein von Hand gestopptes System bleibt im
        # Zwischenspeicher liegen: der naechste Client scheitert dann mit
        # "Could not connect to tenant". Nur das Leeren des
        # Zwischenspeichers baut wirklich neu auf.
        from chromadb.api.shared_system_client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        return False
    client()
    return True


def sammlung(name, anlegen=True):
    """Eine Sammlung nach Namen. None, wenn sie nicht existiert.

    None statt einer Ausnahme, weil ein Raum ohne Sammlung der normale Fall
    ist: er wurde angelegt, aber noch nichts hineingelegt. Eine Suche ueber
    drei Raeume, von denen einer leer ist, soll die anderen beiden liefern
    und nicht scheitern.

    Und None statt einer leeren, frisch angelegten Sammlung, weil das Lesen
    sonst Sammlungen anlegt -- eine Suche wuerde den Bestand veraendern.
    """
    gemerkt = _sammlungen.get(name)
    if gemerkt is not None:
        return gemerkt
    c = client()
    if anlegen:
        sml = c.get_or_create_collection(name=name)
    else:
        try:
            sml = c.get_collection(name=name)
        except Exception:
            return None
    _sammlungen[name] = sml
    return sml


# --- SCHREIBEN ---
#
# Der Grund fuer diese Funktion ist ein Fehlgriff, den man gegen eine
# Dateiablage nicht sieht: dort nimmt Chroma jeden Stapel an, egal wie
# gross. Ueber HTTP nicht -- der Server lehnt eine zu grosse Anfrage mit
# "Payload too large" ab.
#
# Wie gross zu gross ist, haengt an Vektorlaenge und Textmenge und damit am
# Modell und am Bestand. Eine feste Zahl waere also entweder unnoetig klein
# oder irgendwann wieder zu gross. Deshalb halbiert diese Funktion den
# Stapel, wenn genau dieser Fehler kommt, und nur dann: bei jedem anderen
# Fehler wird weitergegeben, statt sich in tausend kleine Anfragen zu
# zerlegen, die alle scheitern.

SCHREIBSTAPEL = paths.env_int("CHROMA_SCHREIBSTAPEL", 500)


def _zu_gross(fehler):
    t = str(fehler).lower()
    return "too large" in t or "413" in t or "request entity" in t


# --- ABSCHNITTE VERSCHLUESSELT ABLEGEN ---
#
# Hier und nirgends sonst, weil schreibe() die einzige Schreibstelle ist.
# Was durch sie geht, liegt verschluesselt; was daran vorbeigeht, faellt
# beim Lesen auf -- der Rueckweg nimmt unverschluesselte Abschnitte an,
# aber die Oberflaeche zaehlt sie.

VORSILBE_RAUM = "raum_"


def raum_von(sammlung):
    """Die Raumkennung zu einer Sammlung. Leer, wenn es keine ist.

    Der Raum ist der Schluesselbund: jeder hat seinen eigenen, und er ist
    mit dem Namen beglaubigt. Deshalb muss hier stehen, zu welchem Raum
    ein Abschnitt gehoert -- der Aufrufer soll es nicht mitgeben muessen
    und dabei falsch liegen koennen.
    """
    name = getattr(sammlung, "name", "") or ""
    return name[len(VORSILBE_RAUM):] if name.startswith(VORSILBE_RAUM) else ""


def _verschluesselt(raum, dokumente):
    """Dokumente fuer die Ablage. Schon Verschluesseltes bleibt, wie es ist.

    Das "bleibt, wie es ist" ist nicht Bequemlichkeit, sondern noetig:
    beim Einspielen einer Sicherung kommt der Geheimtext aus dem Abzug
    zurueck. Ihn erneut zu verschluesseln waere eine zweite Schicht, die
    beim Lesen nur die erste abnimmt -- und dann stuende Kauderwelsch in
    der Antwort.
    """
    if not raum or not dokumente:
        return dokumente
    import raumschluessel
    if not raumschluessel.verfuegbar():
        return dokumente
    return [d if raumschluessel.ist_verschluesselt(d)
            else raumschluessel.verschluessele_text(raum, d)
            for d in dokumente]


def klartext(sammlung_oder_raum, dokumente, benutzer="?", wartung=False):
    """Dokumente zurueck im Klartext. Alte, lesbare bleiben unveraendert.

    benutzer geht in das Entnahmebudget: gezaehlt wird, wer wie viel aus
    wie vielen Raeumen holt. Eine Frage sind ein Dutzend Abschnitte aus
    ein bis drei Raeumen; wer den Bestand ausleert, faellt damit auf.
    """
    raum = (sammlung_oder_raum if isinstance(sammlung_oder_raum, str)
            else raum_von(sammlung_oder_raum))
    if not raum or not dokumente:
        return dokumente
    import raumschluessel
    zu_zaehlen = sum(1 for d in dokumente
                     if raumschluessel.ist_verschluesselt(d))
    if zu_zaehlen:
        import budget
        budget.zaehle(benutzer, raum, zu_zaehlen, wartung=wartung)
    return [raumschluessel.entschluessele_text(raum, d) for d in dokumente]


def umschluesseln(von_raum, nach_raum, dokumente, benutzer="?"):
    """Abschnitte von einem Raum in einen anderen umschluesseln.

    Gebraucht beim Verschieben und beim Umsortieren. Ohne das truege der
    Geheimtext weiter die Beglaubigung des alten Raums und liesse sich im
    neuen nicht mehr oeffnen -- ein Dokument, das nach dem Verschieben
    unlesbar ist, und niemand saehe warum.
    """
    return _verschluesselt(nach_raum,
                           klartext(von_raum, dokumente, benutzer))


def datei_filter(namen):
    """Ein Chroma-Filter auf einen oder mehrere Dateinamen.

    Trifft BEIDE Zustaende: Abschnitte mit datei_id (nach der
    Umstellung) und solche, die noch den Klarnamen tragen. Ein Bestand
    hat waehrend der Umstellung beides, und ein Filter, der nur eine
    Haelfte findet, loescht oder verschiebt auch nur eine Haelfte -- das
    faellt beim Loeschen sofort auf und beim Verschieben erst Wochen
    spaeter.

    Ohne Schluessel bleibt es beim Klarnamen; dann ist ohnehin nichts
    verschluesselt.
    """
    if isinstance(namen, str):
        namen = [namen]
    namen = [n for n in namen if n]
    if not namen:
        return None
    import raumschluessel
    kennungen = [k for k in (raumschluessel.datei_id(n) for n in namen) if k]
    nach_namen = ({"file_name": namen[0]} if len(namen) == 1
                  else {"file_name": {"$in": list(namen)}})
    if not kennungen:
        return nach_namen
    nach_id = ({"datei_id": kennungen[0]} if len(kennungen) == 1
               else {"datei_id": {"$in": kennungen}})
    return {"$or": [nach_id, nach_namen]}


def _metadaten_verdeckt(raum, metadatas):
    """Metadaten fuer die Ablage: Name verschluesselt, Kennung dazu.

    Der Klarname faellt weg, nicht nur ergaenzt. Ihn "sicherheitshalber"
    stehen zu lassen waere genau der Fehler, den die Uebung vermeiden
    soll -- dann steht er weiter in der Datenbank, und die Kennung
    daneben ist nur Zierde.
    """
    if not raum or not metadatas:
        return metadatas
    import raumschluessel
    if not raumschluessel.verfuegbar():
        return metadatas
    aus = []
    for m in metadatas:
        m = dict(m or {})
        name = m.get("file_name")
        if name and not raumschluessel.ist_verschluesselt(name):
            m["datei_id"] = raumschluessel.datei_id(name)
            m["file_name"] = raumschluessel.verschluessele_text(raum, name)
        aus.append(m)
    return aus


def metadaten_umschluesseln(von_raum, nach_raum, metadatas):
    """Dateinamen von einem Raum in den anderen umschluesseln.

    Das Gegenstueck zu umschluesseln() fuer die Metadaten. Ohne das
    bleibt der Name mit dem ALTEN Raum beglaubigt, waehrend der Abschnitt
    im neuen liegt -- _metadaten_verdeckt laesst einen bereits
    verschluesselten Wert stehen und merkt nicht, dass er zum falschen
    Schluessel gehoert.

    Sichtbar wird das erst spaeter und an einer Stelle, die nichts damit
    zu tun zu haben scheint: unter der Antwort steht "(nicht lesbar)"
    statt des Dateinamens, und die Fundstelle ist damit wertlos.
    """
    return _metadaten_verdeckt(nach_raum,
                               metadaten_klartext(von_raum, metadatas))


def metadaten_klartext(raum, metadatas, benutzer="?"):
    """Metadaten zurueck mit lesbarem Dateinamen.

    Ohne das stuende unter der Antwort "LNX1:OiD8..." statt
    "Betriebsanweisung.pdf", und die Quellenangabe waere wertlos.
    """
    if not raum or not metadatas:
        return metadatas
    import raumschluessel
    aus = []
    for m in metadatas:
        m = dict(m or {})
        name = m.get("file_name")
        if raumschluessel.ist_verschluesselt(name):
            try:
                m["file_name"] = raumschluessel.entschluessele_text(raum, name)
            except Exception:
                # Ein Name, der sich nicht oeffnen laesst, darf die
                # Antwort nicht kosten. Die Fundstelle bleibt brauchbar,
                # die Beschriftung nicht.
                m["file_name"] = "(nicht lesbar)"
        aus.append(m)
    return aus


def schreibe(sammlung, ids, documents=None, metadatas=None, embeddings=None,
             stapel=None, ersetzen=True, fortschritt=None):
    """Schreibt Abschnitte in Stapeln. Anzahl der geschriebenen.

    ersetzen=True nimmt upsert: ein zweiter Lauf verdoppelt nichts und
    scheitert nicht an bekannten Kennungen. False nimmt add -- dort ist
    eine bekannte Kennung ein Fehler, und manchmal ist das gewollt.
    """
    n = len(ids)
    if not n:
        return 0
    # Verschluesseln VOR dem Aufteilen: sonst traegt jeder Stapel die
    # Entscheidung erneut, und einer davon vergisst sie irgendwann.
    _raum = raum_von(sammlung)
    documents = _verschluesselt(_raum, documents)
    metadatas = _metadaten_verdeckt(_raum, metadatas)
    stapel = max(1, stapel or SCHREIBSTAPEL)
    geschrieben = 0
    a = 0
    while a < n:
        teil = min(stapel, n - a)
        while True:
            try:
                _schreibe_teil(sammlung, ids[a:a + teil],
                               documents, metadatas, embeddings, a, teil,
                               ersetzen)
                break
            except Exception as e:
                if teil > 1 and _zu_gross(e):
                    # Halbieren und noch einmal. Der kleinere Stapel gilt
                    # ab hier weiter -- sonst laeuft man bei jedem
                    # Durchgang erneut in die Grenze.
                    teil = max(1, teil // 2)
                    stapel = teil
                    continue
                raise
        a += teil
        geschrieben += teil
        if fortschritt:
            fortschritt(geschrieben, n)
    return geschrieben


def _schreibe_teil(sammlung, kennungen, documents, metadatas, embeddings,
                   ab, wie_viele, ersetzen):
    args = {"ids": list(kennungen)}
    if documents is not None:
        args["documents"] = list(documents[ab:ab + wie_viele])
    if metadatas is not None:
        args["metadatas"] = list(metadatas[ab:ab + wie_viele])
    if embeddings is not None:
        args["embeddings"] = list(embeddings[ab:ab + wie_viele])
    (sammlung.upsert if ersetzen else sammlung.add)(**args)


def namen():
    """Die Namen aller vorhandenen Sammlungen."""
    try:
        return sorted(x.name for x in client().list_collections())
    except Exception:
        return []


def loesche(name):
    """Loescht eine Sammlung samt Inhalt. (ok, meldung)."""
    try:
        client().delete_collection(name=name)
        vergiss(name)
        return True, "Geloescht."
    except Exception as e:
        vergiss(name)
        return False, str(e)


def beschreibung():
    """Woher die Daten kommen -- fuer die Anzeige.

    Das Zugangsmerkmal wird genannt, aber nicht gezeigt: ob eines gesetzt
    ist, gehoert auf den Bildschirm, sein Wert nicht.
    """
    if CHROMA_CLOUD_KEY:
        return (f"Gehostet ({CHROMA_CLOUD_TENANT or 'Vorgabe'}/"
                f"{CHROMA_CLOUD_DATABASE})")
    if CHROMA_HOST:
        schema = "https" if CHROMA_SSL else "http"
        merkmal = " mit Token" if CHROMA_TOKEN else " OHNE Token"
        return f"Server {schema}://{CHROMA_HOST}:{CHROMA_PORT}{merkmal}"
    return f"Dateiablage {paths.CHROMA_DIR}"
