"""Self-test, part 00: Isolation from the installation, the check helpers, a throw-away installation.

Runs only through tests/selftest.py, after the parts before it.
"""
import io, json, os, random, shutil, sys, tempfile, types

# Eine Meldung darf den Lauf nie beenden. Die Windows-Konsole kann nicht
# jedes Zeichen ausgeben -- eine Ligatur aus der Texterkennung brachte
# den Selbsttest dort zum Absturz, gerade als eine Pruefung anschlug und
# ihren Fund nennen wollte. Nicht darstellbare Zeichen kommen als \u....
try:
    sys.stdout.reconfigure(errors="backslashreplace")
except (AttributeError, ValueError):
    pass

# --- ISOLATION ERZWINGEN ---
#
# Ohne das schreibt dieser Test in die BETRIEBSDATENBANK. store.py
# liest CHROMA_HOST beim Import in eine Modulkonstante; ist die Variable
# gesetzt -- im Container ist sie das --, spricht der Client den
# Chroma-Dienst an, und ein umgebogenes paths.CHROMA_DIR aendert daran
# nichts. Genau das ist beim ersten Lauf auf einem Server passiert: der
# Test wollte Testvektoren nach raum_allgemein schreiben. Gerettet hat
# nur die Dimensionspruefung von Chroma.
#
# Deshalb hier, VOR jedem Import von store: die Variable weg. Und
# darunter eine Wache, die abbricht, falls doch ein Server antwortet.
for _v in ("CHROMA_HOST", "CHROMA_CLOUD_KEY", "CHROMA_SSL", "CHROMA_TOKEN"):
    os.environ.pop(_v, None)

# Im laufenden Pod sieht der Test dessen Umgebung: die echte Ablage, die
# Datenbank, Listen- und Sicherungsordner, die Sitzungsdauer. Mit ihr lud
# er Testdateien in die echte OpenCloud und zaehlte Einstellungen des
# Betriebs als Fehlschlag. Er soll ueberall laufen wie auf einem leeren
# Rechner und nichts nach draussen schreiben -- also bleibt von der
# Umgebung nur, was Betriebssystem und Python brauchen.
_SYSTEM = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG",
           "LANGUAGE", "TZ", "TMPDIR", "TEMP", "TMP", "HOSTNAME",
           "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
           "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
           "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
           "SSL_CERT_FILE", "SSL_CERT_DIR", "TESSDATA_PREFIX",
           "VIRTUAL_ENV"}
_SYSTEM_PRAEFIX = ("PYTHON", "LC_", "HF_", "TRANSFORMERS_", "TORCH", "OMP_",
                   "MKL_", "CUDA", "NVIDIA", "XDG_", "PROGRAMFILES",
                   "COMMONPROGRAMFILES")
# A Postgres server for the enterprise store, test-only. The test creates
# its own database there and drops it at the end.
_SELFTEST_DB = os.environ.get("SELFTEST_DATABASE", "").strip()
_entfernt = sorted(v for v in os.environ
                   if v.upper() not in _SYSTEM
                   and not v.upper().startswith(_SYSTEM_PRAEFIX))
for _v in _entfernt:
    del os.environ[_v]
tmp = tempfile.mkdtemp(prefix="ende_")
os.environ["ADMIN_USERS"] = "markus"
import paths
import statefiles
import database
if _SELFTEST_DB:
    import psycopg
    from urllib.parse import urlsplit, urlunsplit
    _db_name = "selftest_" + os.urandom(4).hex()
    with psycopg.connect(_SELFTEST_DB, autocommit=True) as _admin:
        _admin.execute(f'CREATE DATABASE "{_db_name}"')
    _u = urlsplit(_SELFTEST_DB)
    database.DIMENSIONS = 32  # the fake vectors below (DIM)
    database.URL = urlunsplit((_u.scheme, _u.netloc, "/" + _db_name,
                               _u.query, _u.fragment))

    def _drop_test_db():
        database.close()
        try:
            with psycopg.connect(_SELFTEST_DB, autocommit=True) as _admin:
                _admin.execute(f'DROP DATABASE IF EXISTS "{_db_name}" '
                               f'WITH (FORCE)')
        except Exception as _e:
            print(f"(test database {_db_name} not dropped: {_e})")
    import atexit
    atexit.register(_drop_test_db)
for n, u in (("CONFIG_DIR", "konfig"), ("DATA_DIR", "daten")):
    setattr(paths, n, os.path.join(tmp, u)); statefiles.makedirs(getattr(paths, n))
paths.DOCS_DIR = os.path.join(paths.DATA_DIR, "dokumente"); statefiles.makedirs(paths.DOCS_DIR)
paths.CHATS_DIR = os.path.join(paths.DATA_DIR, "chats")
paths.INDEX_DIR = paths.DATA_DIR
paths.CHROMA_DIR = os.path.join(paths.DATA_DIR, "chroma_db")
paths.USER_FILE = os.path.join(paths.CONFIG_DIR, "users.json")
paths.GRUPPEN_DATEI = os.path.join(paths.DATA_DIR, "gruppen.json")

import geheim, benutzer, raeume, chats, store, keyword_index, pipeline, feedback
geheim.SCHLUESSEL_DATEI = os.path.join(paths.CONFIG_DIR, "schluessel.key")
benutzer.PROTOKOLL = os.path.join(paths.DATA_DIR, "benutzer.log")
benutzer._datei = lambda: paths.USER_FILE
raeume.DATEI = os.path.join(paths.CONFIG_DIR, "raeume.json")
keyword_index.DB_PATH = os.path.join(paths.DATA_DIR, "kw.sqlite3")
feedback.DATEI = os.path.join(paths.DATA_DIR, "feedback.jsonl")
store.CHROMA_HOST = ""          # falls doch etwas durchkam
store._client = None
store.vergiss()

_ablage = store.beschreibung()
if database.active():
    # Enterprise store: only ever a database this test created itself.
    if "/selftest_" not in _ablage:
        print("ABBRUCH: Dieser Test wuerde gegen " + _ablage + " schreiben.")
        sys.exit(2)
elif "Dateiablage" not in _ablage:
    print("ABBRUCH: Dieser Test wuerde gegen " + _ablage
          + " schreiben.")
    print("Er darf ausschliesslich auf einer eigenen Dateiablage "
          "laufen -- niemals gegen den Betrieb.")
    sys.exit(2)
if not database.active() and not _ablage.endswith(paths.CHROMA_DIR):
    print(f"ABBRUCH: Ablage {_ablage} liegt nicht im Testverzeichnis.")
    sys.exit(2)
import owncloud as _oc_wache
if _oc_wache.eingerichtet():
    print("ABBRUCH: Eine Dateiablage ist eingerichtet -- der Test wuerde "
          "dort Dateien ablegen.")
    sys.exit(2)

ok = []
gescheitert = []


def pruef(was, bedingung, zusatz=""):
    ok.append(bool(bedingung))
    if not bedingung:
        gescheitert.append(f"{was}{'  ' + str(zusatz) if zusatz else ''}")
    print(f"  {'OK  ' if bedingung else 'FEHL'} {was}{'  ' + str(zusatz) if zusatz else ''}")


# Laeuft der Test im Betrieb, darf er dessen Umgebung nicht sehen -- sonst
# schreibt er in die echte Ablage und haengt am Zustand der Installation.
pruef("der Test laeuft ohne die Umgebung des Betriebs",
      not any(v.startswith(("OWNCLOUD_", "SQL_", "TABELLEN_", "SICHERUNG_",
                            "SITZUNG_", "LOCANOTO_", "CHAT_", "OPENAI_"))
              for v in os.environ)
      and not _oc_wache.eingerichtet(),
      f"{len(_entfernt)} Variablen entfernt")


def _fremd_scheitert(roh):
    """Oeffnet ein anderer Raumschluessel den Geheimtext? Er darf nicht."""
    import raumschluessel
    raumschluessel.schluessel("allgemein")
    try:
        raumschluessel.entschluessele_text("allgemein", roh)
        return False
    except Exception:
        return True


def _budget_laeuft(wer, raum, je, wie_oft, wartung=False):
    """True, wenn alle Buchungen durchgehen."""
    import budget
    try:
        for i in range(wie_oft):
            budget.zaehle(wer, raum or f"raum{i}", je, wartung=wartung)
        return True
    except budget.Ueberzogen:
        return False
