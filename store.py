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


def sammlung(name, anlegen=True):
    """Eine Sammlung nach Namen. None, wenn sie nicht existiert.

    None statt einer Ausnahme, weil ein Raum ohne Sammlung der normale Fall
    ist: er wurde angelegt, aber noch nichts hineingelegt. Eine Suche ueber
    drei Raeume, von denen einer leer ist, soll die anderen beiden liefern
    und nicht scheitern.

    Und None statt einer leeren, frisch angelegten Sammlung, weil das Lesen
    sonst Sammlungen anlegt -- eine Suche wuerde den Bestand veraendern.
    """
    c = client()
    if anlegen:
        return c.get_or_create_collection(name=name)
    try:
        return c.get_collection(name=name)
    except Exception:
        return None


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
        return True, "Geloescht."
    except Exception as e:
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
