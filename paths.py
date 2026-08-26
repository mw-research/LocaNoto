"""Zentrale Pfad-Definition und Bootstrap.

Alle Skripte und die App teilen sich diese Pfade. Die Basis ist bewusst der
Ort dieser Datei und NICHT os.getcwd() -- damit ist es egal, aus welchem
Verzeichnis ein Skript gestartet wird.

Layout (identisch mit dem data/-Ordner, der zwischen Installationen
weitergegeben wird):

    <repo>/
        users.json
        data/
            dokumente/
            chats/
            chroma_db/
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DIR = os.path.join(DATA_DIR, "dokumente")
CHATS_DIR = os.path.join(DATA_DIR, "chats")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")

USER_FILE = os.path.join(BASE_DIR, "users.json")

COLLECTION_NAME = "pdf_documents"


def bootstrap():
    """Legt die data/-Struktur an, falls sie fehlt. Idempotent."""
    for d in (DATA_DIR, DOCS_DIR, CHATS_DIR, CHROMA_DIR):
        os.makedirs(d, exist_ok=True)
    return DATA_DIR
