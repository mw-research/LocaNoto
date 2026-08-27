"""Modell-Endpunkte je Aufgabe.

Bisher liefen alle Aufrufe ueber eine einzige Adresse (OPENAI_BASE_URL). Wer
das Chat-Modell bei einem Anbieter und die Embeddings lokal betreiben will,
brauchte dafuer einen vorgeschalteten Proxy.

Hier bekommt jede Aufgabe ihre eigene Adresse, ihren eigenen Schluessel und
ihren eigenen Modellnamen. Nicht gesetzte Werte fallen auf OPENAI_BASE_URL
und OPENAI_API_KEY zurueck -- eine bestehende Konfiguration mit nur diesen
beiden Variablen verhaelt sich also unveraendert.

Aufgaben (Praefix in der .env):

    CHAT       Antwort und Umformulierung der Suchanfrage
    TITLE      Benennung des Chats
    EMBEDDING  Vektorisierung von Chunks und Suchanfragen
    VISION     Bildbeschreibung im Ingest
    SQL        Erzeugung der Datenbankabfrage (nur Handbuch-Variante)

Je Aufgabe:

    <AUFGABE>_MODEL        Modell- bzw. Deployment-Name
    <AUFGABE>_BASE_URL     Adresse; leer = OPENAI_BASE_URL
    <AUFGABE>_API_KEY      Schluessel; leer = OPENAI_API_KEY
    <AUFGABE>_API_VERSION  nur fuer Azure OpenAI; gesetzt = Azure-Client

Beispiel: Chat ueber Azure, alles andere lokal ueber Ollama.

    OPENAI_BASE_URL=http://ollama:11434/v1
    OPENAI_API_KEY=ollama

    CHAT_MODEL=gpt-4o
    CHAT_BASE_URL=https://meine-instanz.openai.azure.com
    CHAT_API_KEY=...
    CHAT_API_VERSION=2024-10-21
"""
import os

from openai import OpenAI

STANDARD_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:4000")
STANDARD_API_KEY = os.getenv("OPENAI_API_KEY", "Dein_Platzhalter_Key")

# Modellnamen, falls die Umgebung nichts vorgibt.
STANDARD_MODELLE = {
    "CHAT": "qwen3.8:27b",
    "TITLE": "",           # leer = Chat-Modell verwenden
    "EMBEDDING": "qwen3-embedding:4b",
    "VISION": "qwen3-vl:32b",
    "SQL": "",             # leer = Chat-Modell verwenden
}

# Ein Client je Endpunkt statt je Aufruf. Zwei Aufgaben auf derselben Adresse
# teilen sich damit die Verbindung.
_clients = {}


def _wert(aufgabe, feld, standard=""):
    return os.getenv(f"{aufgabe.upper()}_{feld}", standard).strip()


def basis_url(aufgabe):
    return _wert(aufgabe, "BASE_URL") or STANDARD_BASE_URL


def api_key(aufgabe):
    return _wert(aufgabe, "API_KEY") or STANDARD_API_KEY


def modell(aufgabe, rueckfall=None):
    """Modellname der Aufgabe.

    Ist keiner gesetzt, greift der uebergebene Rueckfall und danach der
    Standard aus STANDARD_MODELLE.
    """
    name = _wert(aufgabe, "MODEL")
    if name:
        return name
    if rueckfall:
        return rueckfall
    return STANDARD_MODELLE.get(aufgabe.upper(), "")


def client(aufgabe):
    """Client fuer die Aufgabe, zwischengespeichert je Endpunkt.

    Ist <AUFGABE>_API_VERSION gesetzt, wird ein Azure-Client erzeugt: Azure
    OpenAI erwartet Adresse, Schluessel und Version in anderer Form als die
    OpenAI-kompatiblen Server.
    """
    base = basis_url(aufgabe)
    key = api_key(aufgabe)
    version = _wert(aufgabe, "API_VERSION")

    schluessel = (base, key, version)
    if schluessel in _clients:
        return _clients[schluessel]

    if version:
        from openai import AzureOpenAI  # nur bei Azure-Nutzung geladen
        c = AzureOpenAI(azure_endpoint=base, api_key=key, api_version=version)
    else:
        c = OpenAI(base_url=base, api_key=key)

    _clients[schluessel] = c
    return c


def uebersicht():
    """Zeilenweise Darstellung der aufgeloesten Endpunkte, ohne Schluessel."""
    zeilen = []
    for aufgabe in ("CHAT", "TITLE", "EMBEDDING", "VISION", "SQL"):
        name = modell(aufgabe) or "(Chat-Modell)"
        art = "Azure" if _wert(aufgabe, "API_VERSION") else "OpenAI-kompatibel"
        zeilen.append(f"{aufgabe:<10} {name:<28} {basis_url(aufgabe)}  [{art}]")
    return "\n".join(zeilen)
