"""Eine Datei aendern, ohne dass ein gleichzeitiger Schreiber es verschluckt.

Streamlit bedient alle Sitzungen in einem Prozess, jede in einem eigenen
Faden. Wer eine Datei liest, im Speicher aendert und zurueckschreibt,
ueberschreibt dabei, was ein anderer Faden inzwischen geschrieben hat.
Dazu kommen Skripte wie create_user.py, die per kubectl exec in einem
eigenen Prozess laufen.

gesperrt() schliesst beides aus: eine Fadensperre fuer diesen Prozess
und eine Dateisperre fuer alle anderen. Lesen-Aendern-Schreiben gehoert
vollstaendig hinein; reines Lesen braucht sie nicht, weil
schreibe_atomar() nie eine halbe Datei hinterlaesst.

schreibe_atomar() schreibt in eine Zwischendatei mit eigenem Namen und
benennt sie dann um. Der eigene Name ist noetig: bei einem festen Namen
wie "users.json.neu" schreiben zwei Faeden in DIESELBE Zwischendatei.
"""
import contextlib
import os
import tempfile
import threading
import time

_FAEDEN = {}
_FAEDEN_SPERRE = threading.Lock()
_TIEFE = threading.local()


def _faden_sperre(pfad):
    with _FAEDEN_SPERRE:
        return _FAEDEN.setdefault(pfad, threading.RLock())


def _sperre_datei(fd):
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    except ImportError:
        pass
    # Windows: msvcrt.locking gibt nach zehn Versuchen auf. Hier wird
    # weiter gewartet -- aufgeben hiesse, ohne Sperre zu schreiben.
    import msvcrt
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            return
        except OSError:
            time.sleep(0.05)


def _entsperre_datei(fd):
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    except ImportError:
        pass
    import msvcrt
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextlib.contextmanager
def gesperrt(pfad):
    """Exklusiver Zugriff auf pfad, ueber Faeden und Prozesse hinweg.

    Verschachtelt im selben Faden erlaubt: die innere Anforderung
    derselben Datei geht sofort durch. Ohne das haengte ein Faden an
    seiner eigenen Sperre.
    """
    pfad = os.path.abspath(pfad)
    faden = _faden_sperre(pfad)
    with faden:
        tiefen = getattr(_TIEFE, "werte", None)
        if tiefen is None:
            tiefen = _TIEFE.werte = {}
        tiefen[pfad] = tiefen.get(pfad, 0) + 1
        fd = None
        try:
            if tiefen[pfad] == 1:
                os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
                fd = os.open(pfad + ".sperre", os.O_RDWR | os.O_CREAT, 0o600)
                _sperre_datei(fd)
            yield
        finally:
            if fd is not None:
                _entsperre_datei(fd)
                os.close(fd)
            tiefen[pfad] -= 1


def schreibe_atomar(pfad, text, modus=None):
    """Schreibt text nach pfad, ganz oder gar nicht.

    modus=0o600 fuer Dateien, die niemand ausser der Anwendung lesen
    soll. Die Zwischendatei entsteht bereits mit 0600; ohne modus
    bekommt das Ergebnis die ueblichen Rechte.
    """
    verzeichnis = os.path.dirname(os.path.abspath(pfad))
    os.makedirs(verzeichnis, exist_ok=True)
    fd, zwischen = tempfile.mkstemp(
        prefix=os.path.basename(pfad) + ".", suffix=".neu", dir=verzeichnis)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if modus is None:
            maske = os.umask(0)
            os.umask(maske)
            modus_ = 0o666 & ~maske
        else:
            modus_ = modus
        try:
            os.chmod(zwischen, modus_)
        except OSError:
            pass
        os.replace(zwischen, pfad)
    except BaseException:
        try:
            os.remove(zwischen)
        except OSError:
            pass
        raise
