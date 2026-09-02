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

_client = None


def im_server_betrieb():
    return bool(CHROMA_HOST)


def client():
    """Der Chroma-Client dieses Prozesses.

    Einmal erzeugt und behalten: ein PersistentClient legt beim Anlegen die
    Dateien offen, und ein zweiter auf demselben Pfad ist genau der Fall,
    den dieses Modul vermeiden soll.
    """
    global _client
    if _client is None:
        if CHROMA_HOST:
            _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        else:
            _client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
    return _client


def collection(anlegen=True):
    """Die Sammlung mit den Dokumenten-Abschnitten.

    anlegen=False fuer Skripte, die auf einem vorhandenen Bestand arbeiten:
    dort ist eine leere, frisch angelegte Sammlung kein brauchbarer
    Ausgangspunkt, sondern ein Hinweis darauf, dass der Pfad nicht stimmt.
    """
    c = client()
    if anlegen:
        return c.get_or_create_collection(name=paths.COLLECTION_NAME)
    return c.get_collection(name=paths.COLLECTION_NAME)


def beschreibung():
    """Woher die Daten kommen -- fuer die Anzeige."""
    if CHROMA_HOST:
        return f"Server {CHROMA_HOST}:{CHROMA_PORT}"
    return f"Dateiablage {paths.CHROMA_DIR}"
