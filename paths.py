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

# --- TELEMETRIE ABSCHALTEN ---
# ChromaDB sendet standardmaessig anonymisierte Nutzungsdaten nach aussen.
# Fuer eine Anwendung, die ohne Netzzugang laufen soll, ist das ein offener
# Kanal. Hier gesetzt statt in jedem Skript einzeln: alle Einstiegspunkte
# importieren paths, und setdefault laesst eine bewusste Vorgabe von aussen
# unangetastet.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_ANONYMIZED_TELEMETRY", "False")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DIR = os.path.join(DATA_DIR, "dokumente")
CHATS_DIR = os.path.join(DATA_DIR, "chats")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")

# Benutzerdatei bewusst NICHT unter data/: dieser Ordner wird zwischen
# Installationen weitergegeben, und Passwort-Hashes haben darin nichts zu
# suchen. config/ wird als Verzeichnis gemountet -- ein Bind-Mount auf eine
# einzelne Datei bricht, sobald ein Werkzeug sie ersetzt statt sie zu
# ueberschreiben.
CONFIG_DIR = os.path.join(BASE_DIR, "config")
USER_FILE = os.path.join(CONFIG_DIR, "users.json")

# Aeltere Installationen legten die Datei im Wurzelverzeichnis ab.
_LEGACY_USER_FILE = os.path.join(BASE_DIR, "users.json")

# Sprachgebrauch des Betriebs. Unter config/, weil das Verzeichnis eingehaengt
# ist: die Datei wird laufend gepflegt und soll dafuer weder Serverzugang noch
# einen Rebuild brauchen. Die Vorlage glossar.example.txt bleibt beim Code.
GLOSSAR_FILE = os.path.join(CONFIG_DIR, "glossar.txt")
_LEGACY_GLOSSAR = os.path.join(BASE_DIR, "glossar.txt")

COLLECTION_NAME = "pdf_documents"


def bootstrap():
    """Legt die data/- und config/-Struktur an, falls sie fehlt. Idempotent."""
    for d in (DATA_DIR, DOCS_DIR, CHATS_DIR, CHROMA_DIR, CONFIG_DIR):
        os.makedirs(d, exist_ok=True)
    return DATA_DIR


def resolve_glossar():
    """Effektiver Pfad zum Glossar.

    config/glossar.txt ist der Ort, an dem es gepflegt wird. Eine Datei
    neben dem Code wird weiterverwendet, wenn dort keine liegt -- so bleibt
    eine bestehende Installation lesbar, die sie noch beim Code hat.
    """
    if os.path.exists(GLOSSAR_FILE):
        return GLOSSAR_FILE
    if os.path.exists(_LEGACY_GLOSSAR):
        return _LEGACY_GLOSSAR
    return GLOSSAR_FILE


def env_int(name, standard):
    """Ganzzahl aus der Umgebung, wobei ein leerer Wert als "nicht gesetzt"
    gilt.

    os.getenv liefert bei einer gesetzten, aber leeren Variablen "" statt des
    Standards -- und docker-compose setzt jede aufgefuehrte Variable, auch
    wenn sie in der .env fehlt. int("") wuerde abbrechen.

    Damit kann die compose-Datei die Werte durchreichen, ohne sie zu
    verdoppeln: der Standard steht dann nur noch im Code.
    """
    wert = os.getenv(name, "").strip()
    if not wert:
        return standard
    try:
        return int(wert)
    except ValueError:
        return standard


def env_float(name, standard):
    wert = os.getenv(name, "").strip()
    if not wert:
        return standard
    try:
        return float(wert)
    except ValueError:
        return standard


def pdf_dateien(ordner=None):
    """Alle PDFs unterhalb von data/dokumente, rekursiv und sortiert.

    Bewusst ueber os.walk statt glob: glob ist auf Linux von der
    Gross-/Kleinschreibung abhaengig, sodass eine Datei mit der Endung .PDF
    stillschweigend uebergangen wurde -- ohne Meldung, sie fehlte einfach in
    der Wissensbasis. Ein zweites glob-Muster fuer .PDF waere keine Loesung,
    weil dieselbe Datei auf Windows dann doppelt gefunden wird.
    """
    ordner = ordner or DOCS_DIR
    gefunden = []
    for wurzel, _, dateien in os.walk(ordner):
        for name in dateien:
            if name.lower().endswith(".pdf"):
                gefunden.append(os.path.join(wurzel, name))
    return sorted(gefunden)


def resolve_user_file():
    """Effektiver Pfad zur Benutzerdatei.

    Neue Installationen nutzen config/users.json. Bestehende Installationen
    mit einer gefuellten users.json im Wurzelverzeichnis werden nicht
    ausgesperrt -- deren Datei wird weiterverwendet.
    """
    if os.path.exists(USER_FILE):
        return USER_FILE
    if os.path.exists(_LEGACY_USER_FILE) and os.path.getsize(_LEGACY_USER_FILE) > 0:
        return _LEGACY_USER_FILE
    return USER_FILE
