"""Installationsschluessel: verschluesseln, entschluesseln, signieren.

Bisher lagen Chatverlaeufe und Rueckmeldungen als lesbares JSON auf der
Platte. Wer an das Dateiverzeichnis kam, las mit -- ohne Anmeldung, ohne
Spur, an der Anwendung vorbei.

Der Schluessel gehoert der Installation, nicht dem Nutzer. Das ist eine
Entscheidung mit Folgen, und sie ist bewusst so getroffen:

  + Ein Passwortwechsel laesst die Chats lesbar. Bei einem aus dem Passwort
    abgeleiteten Schluessel waere jeder vergessene Zugang ein endgueltiger
    Verlust aller Verlaeufe dieses Nutzers.
  + Die Schnittstelle und die Hintergrundlaeufe koennen mitlesen und
    -schreiben. Sie haben kein Passwort.
  - Ein Verwalter mit Zugriff auf den Server kann entschluesseln.

Was das schuetzt und was nicht -- klar gesagt, damit niemand es fuer mehr
haelt, als es ist:

  Es schuetzt gegen den Blick in die Dateien: eine Sicherung, die in
  falsche Haende geraet, ein kopiertes Volume, ein Blick ins
  Datenverzeichnis. Das ist der haeufige Fall.

  Es schuetzt NICHT gegen jemanden, der den Schluessel lesen kann -- also
  gegen jeden mit Dateizugriff auf config/. Dagegen hilft nur, wer
  ueberhaupt an den Server kommt, und eine verschluesselte Platte.

Der Text der Dokumente selbst ist nicht verschluesselt und kann es nicht
sein: er muss durchsuchbar bleiben, und ChromaDB legt ihn neben dem Vektor
ab. Dafuer ist die Verschluesselung des Datentraegers zustaendig, nicht
diese Datei.
"""
import base64
import hashlib
import hmac
import json
import os

import paths

SCHLUESSEL_DATEI = os.path.join(paths.CONFIG_DIR, "schluessel.key")

# Kennung am Anfang jeder verschluesselten Datei. Sie unterscheidet einen
# verschluesselten Inhalt von einem alten, lesbaren -- ohne sie muesste man
# raten, und ein Fehlgriff sieht wie ein beschaedigter Chat aus.
MARKE = b"LNC1"
NONCE_LAENGE = 12

_schluessel = None
_aes = None


def verfuegbar():
    """Ist die Verschluesselung einsatzbereit?

    False heisst: das Paket cryptography fehlt. Dann wird weiter im Klartext
    geschrieben, und die Oberflaeche sagt es. Ein Abbruch waere hier falsch
    -- er machte eine bestehende Installation unbenutzbar, ohne dass jemand
    dadurch sicherer waere.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
    except Exception:
        return False
    return schluessel() is not None


def schluessel():
    """Der Installationsschluessel, 32 Byte. None, wenn keiner zu holen ist.

    Reihenfolge: Umgebung, dann Datei, dann neu erzeugen. Die Umgebung geht
    vor, damit der Schluessel als Docker-Secret uebergeben werden kann und
    gar nicht erst im Dateisystem liegt.
    """
    global _schluessel
    if _schluessel is not None:
        return _schluessel

    aus_umgebung = os.getenv("LOCANOTO_SCHLUESSEL", "").strip()
    if aus_umgebung:
        try:
            roh = base64.urlsafe_b64decode(aus_umgebung + "=" * (-len(aus_umgebung) % 4))
        except Exception:
            roh = aus_umgebung.encode("utf-8")
        # Auf 32 Byte bringen, ohne einen zu kurzen Wert stillschweigend
        # aufzufuellen: eine Ableitung ist ehrlicher als ein Nullpolster.
        _schluessel = roh if len(roh) == 32 else hashlib.sha256(roh).digest()
        return _schluessel

    try:
        with open(SCHLUESSEL_DATEI, "rb") as f:
            roh = base64.urlsafe_b64decode(f.read().strip())
        if len(roh) == 32:
            _schluessel = roh
            return _schluessel
    except (OSError, ValueError):
        pass

    return _erzeuge()


def _erzeuge():
    """Legt einen neuen Schluessel an. None, wenn das nicht geht.

    Nur beim ersten Start. Danach nie wieder: ein neuer Schluessel macht
    alles Bisherige unlesbar, und zwar ohne Fehlermeldung -- die Dateien
    sind ja noch da.
    """
    global _schluessel
    roh = os.urandom(32)
    try:
        os.makedirs(os.path.dirname(SCHLUESSEL_DATEI), exist_ok=True)
        vorlaeufig = SCHLUESSEL_DATEI + ".neu"
        # 0600 vor dem Schreiben, nicht danach: zwischen Anlegen und
        # chmod liegt sonst ein Moment, in dem die Datei fuer alle lesbar
        # ist.
        fd = os.open(vorlaeufig, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.urlsafe_b64encode(roh))
        os.replace(vorlaeufig, SCHLUESSEL_DATEI)
        try:
            os.chmod(SCHLUESSEL_DATEI, 0o600)
        except OSError:
            # Auf Windows-Dateisystemen ohne POSIX-Rechte nicht moeglich.
            pass
    except OSError:
        return None
    _schluessel = roh
    return _schluessel


def _cipher():
    global _aes
    if _aes is None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        k = schluessel()
        if k is None:
            return None
        _aes = AESGCM(k)
    return _aes


# --- VERSCHLUESSELN ---

def verschluessele(daten, zusatz=b""):
    """Bytes -> Bytes. Gibt die Eingabe unveraendert zurueck, wenn die
    Verschluesselung nicht bereit ist.

    zusatz wird mit beglaubigt, aber nicht mitgeschrieben. Damit laesst
    sich ein Inhalt an seinen Ort binden: ein Chat, der aus einem fremden
    Ordner eingespielt wird, entschluesselt nicht.
    """
    if not isinstance(daten, bytes):
        daten = str(daten).encode("utf-8")
    c = _cipher() if verfuegbar() else None
    if c is None:
        return daten
    nonce = os.urandom(NONCE_LAENGE)
    return MARKE + nonce + c.encrypt(nonce, daten, zusatz)


def entschluessele(daten, zusatz=b""):
    """Bytes -> Bytes. Alte, unverschluesselte Inhalte kommen unveraendert
    zurueck.

    Der Rueckweg ist wichtiger als er aussieht: eine Installation hat nach
    dem Umstieg beides auf der Platte, und ein Chat von letzter Woche soll
    sich weiter oeffnen lassen. Beim naechsten Speichern ist er
    verschluesselt.
    """
    if not daten:
        return daten
    if not daten.startswith(MARKE):
        return daten
    c = _cipher()
    if c is None:
        raise ValueError("Verschluesselter Inhalt, aber kein Schluessel.")
    nonce = daten[len(MARKE):len(MARKE) + NONCE_LAENGE]
    rest = daten[len(MARKE) + NONCE_LAENGE:]
    try:
        return c.decrypt(nonce, rest, zusatz)
    except Exception as e:
        # InvalidTag heisst: veraendert, falscher Schluessel, oder an einer
        # Stelle gelesen, an die der Inhalt nicht gehoert. Als ValueError
        # weitergegeben, damit die Aufrufer einen Fehlschlag behandeln
        # koennen, ohne cryptography zu kennen.
        raise ValueError("Inhalt nicht entschluesselbar.") from e


def ist_verschluesselt(daten):
    return bool(daten) and daten.startswith(MARKE)


# --- SIGNIEREN ---
#
# Verschluesselung verbirgt, eine Signatur deckt auf. Fuer die
# Benutzerdatei ist Letzteres das Richtige: ihr Inhalt ist kein Geheimnis
# -- Namen und bcrypt-Hashes --, aber eine Veraenderung von aussen soll
# auffallen.

def signiere(daten):
    """Hex-Signatur ueber Bytes. Leerer String ohne Schluessel."""
    k = schluessel()
    if k is None:
        return ""
    if not isinstance(daten, bytes):
        daten = str(daten).encode("utf-8")
    return hmac.new(k, daten, hashlib.sha256).hexdigest()


def pruefe_signatur(daten, signatur):
    """Passt die Signatur? compare_digest, nicht ==.

    Ein gewoehnlicher Vergleich bricht beim ersten falschen Zeichen ab und
    verraet damit ueber die Laufzeit, wie weit man richtig geraten hat.
    """
    erwartet = signiere(daten)
    if not erwartet or not signatur:
        return False
    return hmac.compare_digest(erwartet, str(signatur))


def kanonisch(objekt):
    """Bytes eines Objekts, stabil ueber Neustarts hinweg.

    sort_keys und ohne Leerzeichen: ohne das haengt die Signatur an der
    Reihenfolge der Schluessel im Speicher, und dieselben Daten ergaeben
    nach einem Neustart eine andere.
    """
    return json.dumps(objekt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def beschreibung():
    """Woher der Schluessel kommt -- fuer die Anzeige. Nie sein Wert."""
    if not verfuegbar():
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
        except Exception:
            return "aus (Paket cryptography fehlt)"
        return "aus (kein Schluessel schreibbar)"
    if os.getenv("LOCANOTO_SCHLUESSEL", "").strip():
        return "an (Schluessel aus der Umgebung)"
    return f"an (Schluessel in {os.path.basename(SCHLUESSEL_DATEI)})"
