"""Zugangstoken fuer die Schnittstelle.

Die Suche braucht eine Kennung: aus ihr baut pipeline.suche() den
Rechtefilter, der private Dokumente von geteilten trennt. Ueber die
Oberflaeche liefert sie die Anmeldung. Ueber die Schnittstelle muss sie
irgendwoher kommen -- und darf nicht der Aufrufer selbst bestimmen, sonst
liest jedes Skript die privaten Dokumente aller Nutzer.

Warum ein Token und nicht das Passwort:

- Ein Passwort im Terminal landet in der Shell-Historie und in Skripten.
- bcrypt ist absichtlich langsam. Bei jedem einzelnen Aufruf ist das ein
  spuerbarer Aufschlag ohne Gegenwert.
- Ein Token laesst sich einzeln widerrufen, ohne dass jemand sein Passwort
  wechseln muss.

Warum SHA-256 und nicht bcrypt fuer die Ablage: bcrypt gibt es, weil
Passwoerter erratbar sind und Rechenzeit das Durchprobieren verteuern soll.
Ein Token aus 32 zufaelligen Bytes ist nicht erratbar; Streckung bringt
dort nichts und kostet nur. Gespeichert wird trotzdem nur der Hashwert --
wer die Datei liest, hat damit noch keinen Zugang.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import paths

TOKEN_FILE = os.path.join(paths.CONFIG_DIR, "tokens.json")

# Praefix, damit ein Token in einem Protokoll oder einer Zwischenablage als
# solches erkennbar ist -- und von einer Suche nach verirrten Geheimnissen
# gefunden werden kann.
PRAEFIX = "lnt_"


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _jetzt():
    return datetime.now(timezone.utc).replace(microsecond=0)


def laden():
    """Alle Eintraege. Fehlt die Datei, gibt es eben noch keine Token."""
    if not os.path.exists(TOKEN_FILE) or os.path.getsize(TOKEN_FILE) == 0:
        return {}
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        # Eine beschaedigte Datei darf nicht dazu fuehren, dass jeder
        # hereinkommt. Keine Token heisst: kein Zugang.
        return {}
    return daten if isinstance(daten, dict) else {}


def speichern(daten):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen. Bricht der Vorgang ab, steht
    # die alte Datei noch vollstaendig da statt halb.
    vorlaeufig = TOKEN_FILE + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)
    os.replace(vorlaeufig, TOKEN_FILE)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        # Auf manchen Dateisystemen nicht setzbar. Kein Grund abzubrechen.
        pass


def erzeuge(benutzer, bezeichnung="", tage=None):
    """Legt ein Token an und gibt es im Klartext zurueck -- einmalig.

    Gespeichert wird nur der Hashwert. Geht das Token verloren, laesst es
    sich nicht wiederherstellen, sondern nur ersetzen.
    """
    token = PRAEFIX + secrets.token_urlsafe(32)
    daten = laden()
    eintrag = {
        "benutzer": benutzer.strip().lower(),
        "bezeichnung": bezeichnung.strip(),
        "erstellt": _jetzt().isoformat(),
    }
    if tage:
        eintrag["gueltig_bis"] = (_jetzt() + timedelta(days=int(tage))).isoformat()
    daten[_hash(token)] = eintrag
    speichern(daten)
    return token


def pruefe(token):
    """Kennung zum Token, oder None.

    Nachgeschlagen wird ueber den Hashwert. Ein Woerterbuch-Zugriff auf
    einen 256-Bit-Schluessel gibt keine ausnutzbare Zeitinformation preis --
    anders als ein zeichenweiser Vergleich des Klartexts.
    """
    if not token:
        return None
    eintrag = laden().get(_hash(token.strip()))
    if not eintrag:
        return None

    bis = eintrag.get("gueltig_bis")
    if bis:
        try:
            if datetime.fromisoformat(bis) < _jetzt():
                return None
        except ValueError:
            # Unlesbares Datum gilt als abgelaufen, nicht als unbegrenzt.
            return None
    return eintrag.get("benutzer") or None


def liste():
    """Alle Token als (kennung, eintrag) -- ohne die Token selbst."""
    return sorted(laden().items(), key=lambda p: p[1].get("erstellt", ""))


def widerrufe(kennung):
    """Entfernt ein Token anhand des Anfangs seines Hashwerts.

    Rueckgabe: Anzahl der entfernten Eintraege. Passt der Anfang auf
    mehrere, wird keiner entfernt -- eine mehrdeutige Angabe soll nicht
    zufaellig das falsche Token treffen.
    """
    daten = laden()
    treffer = [h for h in daten if h.startswith(kennung)]
    if len(treffer) != 1:
        return len(treffer)
    del daten[treffer[0]]
    speichern(daten)
    return 1
