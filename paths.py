"""Zentrale Pfad-Definition und Bootstrap.

Alle Skripte und die App teilen sich diese Pfade. Die Basis ist bewusst der
Ort dieser Datei und NICHT os.getcwd() -- damit ist es egal, aus welchem
Verzeichnis ein Skript gestartet wird.

Der Bestand gehoert nicht in den Container. Drei Wurzeln, jede einzeln
setzbar, weil sie verschiedene Anforderungen haben:

    LOCANOTO_DATEN   Nutzerdaten und Quellen -- Dokumente, Chats,
                     Rueckmeldungen, Protokolle. Gehoert auf den
                     persistenten Speicher: das ist der Bestand, der einen
                     neuen Container ueberleben muss.

    LOCANOTO_KONFIG  Konfiguration -- Nutzer, Token, Schluessel, Raeume,
                     Prompts. Ebenfalls persistent, aber getrennt: hier
                     liegt das eine Geheimnis, mit dem alles lesbar ist,
                     und eine Sicherung der Dokumente soll es nicht
                     mitnehmen.

    LOCANOTO_INDEX   Vektordatenbank, Stichwortindex, Listenkatalog,
                     Kennungen laufender Prozesse. Gehoert auf ein Volume
                     mit einem ECHTEN DATEISYSTEM -- eine Platte, ein
                     Blockgeraet, ein PersistentVolume mit
                     ReadWriteOnce -- und ausdruecklich NICHT in den
                     Container.

                     Zwei Dinge sind hier zu unterscheiden, und ihre
                     Verwechslung ist der haeufigste Fehler beim
                     Aufsetzen:

                     PERSISTENT heisst nicht DATEIFREIGABE. Ein
                     PersistentVolume auf Blockspeicher (Ceph RBD, iSCSI,
                     EBS, local PV, eine angeschlossene Platte) traegt ein
                     ext4 oder xfs, und darauf laeuft SQLite einwandfrei.
                     Eine Freigabe ueber NFS oder SMB traegt es nicht:
                     SQLite im WAL-Betrieb braucht gemeinsamen Speicher im
                     selben Dateisystem, den es dort nicht gibt, und die
                     Dateisperren sind unzuverlaessig. Das Ergebnis ist
                     kein Fehler, sondern ein beschaedigter Index.

                     Der Container ist dafuer auch kein Ort. Seine
                     Schreibschicht ueberlebt einen Neustart des Pods
                     nicht -- der Bestand waere nach jedem Ausrollen weg,
                     und ein Neueinlesen kostet Stunden Modellzeit. Der
                     Pod soll nur das Geruest sein.

                     Zwei Dinge muessen dabei zusammenkommen: genau ein
                     Prozess schreibt (also eine Instanz der Anwendung
                     oder Chroma als eigener Dienst mit eigenem Volume),
                     und das Volume traegt ein Dateisystem statt einer
                     Freigabe. Die Prozesskennungen (PID) sind derselbe
                     Fall: sie gelten nur auf ihrem Rechner, ein zweiter
                     Pod duerfte dasselbe Verzeichnis nicht sehen.

                     Der Stichwortindex allein waere ersetzbar -- er baut
                     sich aus den Sammlungen neu auf, gemessen 18.600
                     Abschnitte je Sekunde. Die Vektordatenbank ist es
                     nicht.

Ohne diese Variablen bleibt alles, wo es war: data/ und config/ neben dem
Code. Ein Update verschiebt nichts von selbst.
"""
import os
import re

# --- TELEMETRIE ABSCHALTEN ---
# ChromaDB sendet standardmaessig anonymisierte Nutzungsdaten nach aussen.
# Fuer eine Anwendung, die ohne Netzzugang laufen soll, ist das ein offener
# Kanal. Hier gesetzt statt in jedem Skript einzeln: alle Einstiegspunkte
# importieren paths, und setdefault laesst eine bewusste Vorgabe von aussen
# unangetastet.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_ANONYMIZED_TELEMETRY", "False")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _wurzel(name, standard):
    """Ein Verzeichnis aus der Umgebung, oder der Standard neben dem Code.

    Ein leerer Wert gilt als nicht gesetzt -- docker compose reicht nicht
    gesetzte Variablen als leere Strings durch, und ein leerer Pfad waere
    das Wurzelverzeichnis.
    """
    wert = os.getenv(name, "").strip()
    return wert or standard


DATA_DIR = _wurzel("LOCANOTO_DATEN", os.path.join(BASE_DIR, "data"))
DOCS_DIR = os.path.join(DATA_DIR, "dokumente")
CHATS_DIR = os.path.join(DATA_DIR, "chats")

# Ableitbare Zwischenstaende. Standard ist DATA_DIR, damit eine bestehende
# Installation unveraendert weiterlaeuft -- ein Update, das die
# Vektordatenbank an einen anderen Ort legt, faende dort nichts vor und
# stuende ohne Fehlermeldung mit leeren Sammlungen da.
INDEX_DIR = _wurzel("LOCANOTO_INDEX", DATA_DIR)
CHROMA_DIR = os.path.join(INDEX_DIR, "chroma_db")

# Tabellendateien -- Bestands- und Preislisten. Sie werden nicht
# vektorisiert, sondern bei der Frage gelesen; siehe tabellen.py.
#
# TABELLEN_PFAD zeigt den Ordner woanders hin. Gedacht fuer den Fall, dass
# die Listen in einem Netzlaufwerk der Firma liegen und dort von den
# Fachabteilungen gepflegt werden: dann wird dieses Verzeichnis in den
# Container eingehaengt, und niemand muss Dateien zweimal ablegen. Eine
# Nur-Lese-Einhaengung genuegt -- die Anwendung schreibt dort nicht hinein.
TABELLEN_DIR = os.getenv("TABELLEN_PFAD", "").strip() or os.path.join(
    DATA_DIR, "tabellen")

# Benutzerdatei bewusst NICHT unter data/: dieser Ordner wird zwischen
# Installationen weitergegeben, und Passwort-Hashes haben darin nichts zu
# suchen. config/ wird als Verzeichnis gemountet -- ein Bind-Mount auf eine
# einzelne Datei bricht, sobald ein Werkzeug sie ersetzt statt sie zu
# ueberschreiben.
CONFIG_DIR = _wurzel("LOCANOTO_KONFIG", os.path.join(BASE_DIR, "config"))
USER_FILE = os.path.join(CONFIG_DIR, "users.json")

# Aeltere Installationen legten die Datei im Wurzelverzeichnis ab.
_LEGACY_USER_FILE = os.path.join(BASE_DIR, "users.json")

# Sprachgebrauch des Betriebs. Unter config/, weil das Verzeichnis eingehaengt
# ist: die Datei wird laufend gepflegt und soll dafuer weder Serverzugang noch
# einen Rebuild brauchen. Die Vorlage glossar.example.txt bleibt beim Code.
GLOSSAR_FILE = os.path.join(CONFIG_DIR, "glossar.txt")
_LEGACY_GLOSSAR = os.path.join(BASE_DIR, "glossar.txt")

COLLECTION_NAME = "pdf_documents"


def _beschreibbar(d):
    """Laesst sich in diesem Verzeichnis wirklich schreiben?

    makedirs allein genuegt nicht: existiert das Verzeichnis bereits,
    meldet es Erfolg, auch wenn niemand hineinschreiben darf. Genau so
    sieht ein eingehaengtes Volume aus, dessen Freigabe die Kennung des
    Prozesses auf "nobody" abbildet.
    """
    probe = os.path.join(d, ".schreibprobe")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True, ""
    except OSError as e:
        return False, str(e)


def bootstrap():
    """Legt die data/- und config/-Struktur an, falls sie fehlt. Idempotent.

    Schlaegt das fehl, endet es mit einer AUSKUNFT und nicht mit einem
    Traceback. Der Anlass: in einem Cluster brach ein Container nach
    einer Sekunde ab, wieder und wieder, und zu sehen war nur
    "Init:CrashLoopBackOff". Die Ursache -- ein Volume, in das der
    Prozess nicht schreiben darf -- stand nirgends, obwohl sie hier
    genau bekannt ist.
    """
    schlecht = []
    for d in (DATA_DIR, DOCS_DIR, CHATS_DIR, INDEX_DIR, CHROMA_DIR,
              CONFIG_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            schlecht.append((d, str(e)))
            continue
        ok, grund = _beschreibbar(d)
        if not ok:
            schlecht.append((d, grund))

    if schlecht:
        zeilen = ["", "Diese Verzeichnisse sind nicht beschreibbar:", ""]
        for d, grund in schlecht:
            zeilen.append(f"    {d}")
            zeilen.append(f"        {grund}")
        try:
            wer = f"uid={os.getuid()} gid={os.getgid()}"
        except AttributeError:
            wer = "unbekannte Kennung"
        zeilen += [
            "",
            f"Der Prozess laeuft als {wer}.",
            "",
            "Haeufigster Grund bei einem eingehaengten Volume: die",
            "Freigabe bildet root auf 'nobody' ab (root_squash). Dann",
            "gehoert das Verzeichnis jemand anderem, und alles Schreiben",
            "scheitert -- auch das Anlegen der Unterordner.",
            "",
            "Abhilfe, je nach Umgebung:",
            "  * im Pod securityContext.fsGroup auf die Gruppe der",
            "    Freigabe setzen, oder runAsUser auf deren Kennung",
            "  * die Freigabe ohne root_squash exportieren",
            "  * ein anderes Volume nehmen",
            "",
        ]
        raise SystemExit("\n".join(zeilen))
    try:
        # Der Listenordner kann ausserhalb liegen und nur lesbar eingehaengt
        # sein. Dass er sich nicht anlegen laesst, ist dann kein Fehler.
        os.makedirs(TABELLEN_DIR, exist_ok=True)
    except OSError:
        pass
    return DATA_DIR


# Zwischengespeicherte Gruppen aus ownCloud: {gruppe: [nutzer]}. Unter
# DATA_DIR und nicht unter INDEX_DIR, obwohl sie ableitbar ist -- ableiten
# heisst hier "ownCloud fragen", und wenn ownCloud gerade nicht antwortet,
# ist der letzte bekannte Stand das, womit weitergearbeitet wird. Ein
# Verlust bei jedem Containerwechsel waere eine Anwendung, in der nach
# einem Neustart niemand mehr in seinen Abteilungsraum kommt.
#
# Der Pfad steht hier und nicht in owncloud.py, damit raeume.py ihn lesen
# kann, ohne owncloud.py zu importieren: die Aufloesung einer
# Mitgliedschaft soll nie eine HTTP-Bibliothek anfassen.
GRUPPEN_DATEI = os.path.join(DATA_DIR, "owncloud_gruppen.json")


def sicherer_teil(name):
    """Ein Name als einzelner, gefahrloser Pfadbestandteil.

    Fuer alles, was von aussen kommt und zu einem Ordnernamen wird -- eine
    Raumkennung, ein Eintrag aus einer fremden Dateiliste. Ohne das genuegt
    ein ".." um aus dem Datenverzeichnis zu geraten.
    """
    t = re.sub(r'[^0-9A-Za-z._-]+', "_", str(name or "").strip())
    t = t.strip("._-")
    return t[:120] or "unbenannt"


def sicherer_dateiname(name):
    """Ein hochgeladener Dateiname, gefahrlos, aber noch lesbar.

    Nicht sicherer_teil(): der ist fuer Raumkennungen gedacht und macht
    aus 'Handbuch Übersicht.pdf' ein 'Handbuch__bersicht.pdf'. Ein
    Dateiname wird angezeigt, in Metadaten gefuehrt und wiedererkannt --
    Umlaute gehoeren dazu.

    Weg muss nur, was ein Pfad daraus machen wuerde: Verzeichnisanteile,
    Trennzeichen, Steuerzeichen und die beiden Sondernamen. Der Browser
    schickt zwar ueblicherweise nur den Basisnamen, aber "ueblicherweise"
    ist bei einem Wert, der zu einem Pfad wird, kein Verlass.
    """
    roh = str(name or "").replace("\\", "/")
    roh = roh.split("/")[-1]
    roh = "".join(z for z in roh if ord(z) >= 32 and z not in '<>:"|?*')
    roh = roh.strip().strip(".")
    return roh[:180] or "unbenannt"


def raum_ordner(raum):
    """Der eigene Ablageordner eines Raums unter data/dokumente.

    Dieselbe Zuordnung, die owncloud.ablage() beim Holen verwendet -- damit
    ein Dokument denselben Ort hat, ob es hochgeladen oder abgeglichen
    wurde. Der Ordner sagt, zu welchem Raum eine Datei gehoert; ohne ihn
    sagt es nur der Dateiname, und Dateinamen wiederholen sich.
    """
    return os.path.join(DOCS_DIR, sicherer_teil(raum))


def freier_name(ordner, dateiname):
    """Ein Pfad in diesem Ordner, der noch keine Datei ueberschreibt.

    'Angebot.pdf' -> 'Angebot (2).pdf' -> 'Angebot (3).pdf'. Gebraucht im
    gemeinsamen Wurzelbereich, in dem noch Dateien aus der Zeit vor den
    Raeumen liegen: dort kann ein Upload auf den Namen eines Dokuments
    treffen, das einem anderen Raum gehoert. Ihn zu ueberschreiben waere
    ein stiller Verlust -- die Abschnitte des anderen Raums zeigten
    danach auf einen fremden Inhalt.
    """
    ziel = os.path.join(ordner, dateiname)
    if not os.path.exists(ziel):
        return ziel
    stamm, endung = os.path.splitext(dateiname)
    for n in range(2, 1000):
        ziel = os.path.join(ordner, f"{stamm} ({n}){endung}")
        if not os.path.exists(ziel):
            return ziel
    return os.path.join(ordner, f"{stamm} ({os.getpid()}){endung}")


def finde_dokument(dateiname, bevorzugt=None, ausser=()):
    """Der Pfad zu einem Dokument, egal in welchem Unterordner es liegt.

    Die Metadaten halten nur den Dateinamen, nicht den Pfad. Solange alles
    direkt in data/dokumente lag, genuegte ein join -- mit Sachgebieten und
    erst recht mit aus ownCloud geholten Ordnern liegt fast nichts mehr
    dort. Ohne diese Suche zeigt die Quellenansicht dann keine Seite an,
    ohne zu sagen warum.

    bevorzugt und ausser sind der Grund, warum die Suche nicht mehr nur
    nach dem Namen geht. Sie tat es, und das war ein Leck: zwei Raeume
    duerfen dieselbe 'Angebot.pdf' haben, os.walk fand irgendeine davon,
    und die Quellenansicht zeigte zu einem Treffer im eigenen Raum die
    Seite aus dem Dokument eines anderen. Niemandem faellt das auf -- der
    Dateiname stimmt ja.

        bevorzugt   zuerst hier suchen: der Ordner des eigenen Raums.
        ausser      hier nie suchen: die Ordner der anderen Raeume.
    """
    name = os.path.basename(str(dateiname or ""))
    if not name:
        return None

    if bevorzugt and os.path.isdir(bevorzugt):
        direkt = os.path.join(bevorzugt, name)
        if os.path.exists(direkt):
            return direkt
        for wurzel, _unter, dateien in os.walk(bevorzugt):
            if name in dateien:
                return os.path.join(wurzel, name)

    gesperrt = {os.path.normpath(p) for p in ausser if p}
    direkt = os.path.join(DOCS_DIR, name)
    if os.path.exists(direkt):
        return direkt
    for wurzel, unter, dateien in os.walk(DOCS_DIR):
        # Die gesperrten Ordner aus der Liste nehmen, statt den Treffer
        # hinterher zu verwerfen: os.walk steigt sonst hinein, und ein
        # Unterordner eines fremden Raums waere weiter erreichbar.
        unter[:] = [u for u in unter
                    if os.path.normpath(os.path.join(wurzel, u))
                    not in gesperrt]
        if name in dateien:
            return os.path.join(wurzel, name)
    return None


# --- BESTANDSAUFNAHME ---
#
# Welcher Zustand wo liegt, in einer Liste. Nicht als Bequemlichkeit: bei
# einer Frage nach der Datenhaltung ist "schau in die docker-compose.yaml
# und in fuenf Module" keine Antwort. Klasse und Ort gehoeren auf einen
# Bildschirm.
#
# klasse:
#   quelle         wird gepflegt, nur gelesen -- Netzspeicher richtig
#   nutzerdaten    muss den Container ueberleben -- persistent
#   konfiguration  ebenso, aber getrennt aufzubewahren
#   index          ableitbar, containerlokal -- siehe Kopf dieser Datei

BESTAND = (
    ("Dokumente", "quelle", "DOCS_DIR", True),
    ("Listen (Tabellendateien)", "quelle", "TABELLEN_DIR", True),
    ("Chatverlaeufe", "nutzerdaten", "CHATS_DIR", True),
    ("Rueckmeldungen", "nutzerdaten", ("DATA_DIR", "feedback.jsonl"), False),
    ("Benutzerprotokoll", "nutzerdaten", ("DATA_DIR", "benutzer.log"), False),
    ("Benutzer", "konfiguration", ("CONFIG_DIR", "users.json"), False),
    ("Zugangstoken", "konfiguration", ("CONFIG_DIR", "tokens.json"), False),
    ("Schluessel", "konfiguration", ("CONFIG_DIR", "schluessel.key"), False),
    ("Raeume", "konfiguration", ("CONFIG_DIR", "raeume.json"), False),
    ("Voreinstellungen", "konfiguration", ("CONFIG_DIR", "presets"), True),
    ("Vektordatenbank", "index", "CHROMA_DIR", True),
    ("Stichwortindex", "index", ("INDEX_DIR", "keyword_index.sqlite3"), False),
    ("Listenkatalog", "index", ("INDEX_DIR", "tabellen_katalog.json"), False),
)


def _groesse(pfad, ordner):
    """Bytes und Anzahl. (0, 0), wenn es nichts gibt."""
    if not os.path.exists(pfad):
        return 0, 0
    if not ordner:
        try:
            return os.path.getsize(pfad), 1
        except OSError:
            return 0, 0
    summe, anzahl = 0, 0
    for wurzel, _unter, dateien in os.walk(pfad):
        for name in dateien:
            try:
                summe += os.path.getsize(os.path.join(wurzel, name))
                anzahl += 1
            except OSError:
                pass
    return summe, anzahl


def bestand():
    """Der gesamte Zustand: [(bezeichnung, klasse, pfad, bytes, anzahl)]."""
    hier = globals()
    zeilen = []
    for bezeichnung, klasse, ort, ordner in BESTAND:
        if isinstance(ort, tuple):
            pfad = os.path.join(hier[ort[0]], ort[1])
        else:
            pfad = hier[ort]
        gr, n = _groesse(pfad, ordner)
        zeilen.append((bezeichnung, klasse, pfad, gr, n))
    return zeilen


def wurzeln():
    """Die drei Wurzeln und ob sie von aussen gesetzt sind."""
    return (
        ("Daten", DATA_DIR, bool(os.getenv("LOCANOTO_DATEN", "").strip())),
        ("Konfiguration", CONFIG_DIR,
         bool(os.getenv("LOCANOTO_KONFIG", "").strip())),
        ("Index", INDEX_DIR, bool(os.getenv("LOCANOTO_INDEX", "").strip())),
    )


def resolve_prompt(name):
    """Effektiver Pfad zu einer Prompt-Vorlage.

    config/ zuerst: dort liegt die im Betrieb bearbeitete Fassung, und das
    Verzeichnis ist eingehaengt. Fehlt sie, gilt die mitgelieferte neben dem
    Code.
    """
    eigen = os.path.join(CONFIG_DIR, name)
    if os.path.exists(eigen):
        return eigen
    return os.path.join(BASE_DIR, name)


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


# Formate, die vektorisiert werden koennen. PDFs gehen ueber pymupdf mit
# Seiten und Tabellenerkennung, alles andere ueber lesen.py mit
# Abschnitten -- siehe dort, warum das getrennt bleibt.
DOKUMENT_ENDUNGEN = (".pdf", ".docx", ".md", ".markdown", ".txt")


def dokument_dateien(ordner=None, endungen=None):
    """Alle lesbaren Dokumente unterhalb von data/dokumente."""
    endungen = tuple(e.lower() for e in (endungen or DOKUMENT_ENDUNGEN))
    ordner = ordner or DOCS_DIR
    gefunden = []
    for wurzel, _, dateien in os.walk(ordner):
        for name in dateien:
            if name.lower().endswith(endungen) and not name.startswith("~$"):
                gefunden.append(os.path.join(wurzel, name))
    return sorted(gefunden)


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
