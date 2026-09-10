"""Je Raum ein eigener Schluessel -- verpackt mit dem Installationsschluessel.

Der Zweck in einem Satz: wer das Datenvolume kopiert, soll Vektoren
bekommen und keinen Satz Text.

Die Trennung, auf der das beruht, ist schon gebaut. LOCANOTO_KONFIG und
LOCANOTO_DATEN sind zwei Volumes, der Abzug nimmt den Schluessel
ausdruecklich nicht mit, und LOCANOTO_SCHLUESSEL kann ihn ganz aus dem
Dateisystem heraushalten -- als Docker- oder Kubernetes-Secret liegt er
dann nirgends auf einer Platte. Eine kopierte Sicherung, ein Snapshot,
eine ausgemusterte Platte: das sind die wahrscheinlichen Faelle, und
gegen sie hilft das hier.

WARUM JE RAUM UND NICHT EINER FUER ALLES

Ein Raum ist der Behaelter, in dem etwas liegen soll. Ein eigener
Schluessel macht ihn zu einem Behaelter, den man einzeln oeffnet: ein
geleakter Raumschluessel oeffnet die anderen nicht, ein geloeschter Raum
ist mit seinem Schluessel endgueltig weg, und ein Massenabzug muss jeden
Raum einzeln aufmachen -- was sich zaehlen laesst (siehe budget.py).

WAS ES NICHT LEISTET, und das gehoert dazu:

  * Die VEKTOREN bleiben lesbar. Sie muessen vergleichbar sein, sonst
    gibt es keine Aehnlichkeitssuche, und ein HNSW-Index ueber
    Verschluesseltem ist unmoeglich. Aus einem Vektor laesst sich mit
    demselben Modell ein erheblicher Teil des Textes rekonstruieren. Wer
    das Volume hat, hat also nie "nichts".
  * Der STICHWORTINDEX braucht Klartext. Er ist ableitbar und gehoert
    deshalb auf den containerlokalen Speicher -- LOCANOTO_INDEX. Faellt
    der auf LOCANOTO_DATEN zurueck, liegt der Klartext neben dem
    Verschluesselten, und das Ganze ist Theater. Darauf weist die
    Anwendung beim Start hin.
  * Gegen einen Angreifer AUF DEM LAUFENDEN SERVER hilft nichts davon.
    Der Prozess muss entschluesseln, um zu antworten; wer den Prozess
    hat, hat den Klartext. Dagegen hilft nur, wer ueberhaupt Serverzugang
    bekommt -- und das Zaehlen in budget.py, damit ein Abzug wenigstens
    auffaellt.

Die Schluessel sind mit dem Raumnamen beglaubigt (AAD). Ein Eintrag, den
jemand von einem Raum auf einen anderen umtraegt, entschluesselt nicht --
sonst liesse sich der Behaelter durch Umbenennen oeffnen.
"""
import base64
import json
import os

import geheim
import paths

DATEI = os.path.join(paths.CONFIG_DIR, "raumschluessel.json")

# Kennung am Anfang eines verschluesselten Abschnitts. Sie unterscheidet
# ihn von einem alten, lesbaren -- ohne sie muesste man raten, und ein
# Fehlgriff saehe wie ein beschaedigter Bestand aus.
MARKE = "LNX1:"

# AES-GCM will 96 Bit. Laenger bringt nichts, kuerzer ist unsicher.
NONCE_LAENGE = 12

_schluessel = {}


def verfuegbar():
    """Laesst sich ueberhaupt verschluesseln?"""
    return geheim.verfuegbar()


def _lade():
    try:
        with open(DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    inhalt = daten.get("inhalt")
    if not isinstance(inhalt, dict):
        return {}
    if not geheim.pruefe_signatur(geheim.kanonisch(inhalt),
                                  daten.get("signatur")):
        # Von aussen veraendert. Nichts davon gilt -- ein halb
        # geglaubter Schluesselbund ist schlimmer als keiner.
        raise ValueError(
            f"{DATEI} ist veraendert worden: die Signatur passt nicht. "
            f"Die Datei wird NICHT ueberschrieben. Stelle sie aus der "
            f"Sicherung wieder her.")
    return inhalt.get("raeume") or {}


def _speichere(raeume_):
    inhalt = {"raeume": raeume_}
    daten = {"inhalt": inhalt,
             "signatur": geheim.signiere(geheim.kanonisch(inhalt))}
    os.makedirs(os.path.dirname(DATEI), exist_ok=True)
    vorlaeufig = DATEI + ".neu"
    fd = os.open(vorlaeufig, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    os.replace(vorlaeufig, DATEI)
    try:
        os.chmod(DATEI, 0o600)
    except OSError:
        pass


def schluessel(raum, anlegen=True):
    """Der Schluessel eines Raums, 32 Byte. None, wenn keiner zu holen ist.

    Wird beim ersten Gebrauch angelegt. Ein bestehender wird NIE ersetzt:
    ein neuer Schluessel macht alles Bisherige unlesbar, und zwar ohne
    Fehlermeldung -- die Abschnitte liegen ja noch da.
    """
    if not verfuegbar():
        return None
    if raum in _schluessel:
        return _schluessel[raum]

    raeume_ = _lade()
    verpackt = raeume_.get(raum)
    if verpackt:
        roh = geheim.entschluessele(base64.b64decode(verpackt),
                                    zusatz=raum.encode("utf-8"))
        if len(roh) != 32:
            raise ValueError(f"Der Schluessel fuer '{raum}' ist unbrauchbar.")
        _schluessel[raum] = roh
        return roh

    if not anlegen:
        return None
    roh = os.urandom(32)
    raeume_[raum] = base64.b64encode(
        geheim.verschluessele(roh, zusatz=raum.encode("utf-8"))).decode("ascii")
    _speichere(raeume_)
    _schluessel[raum] = roh
    return roh


def bekannt():
    """Raeume, fuer die ein Schluessel hinterlegt ist."""
    try:
        return sorted(_lade())
    except ValueError:
        return []


def entferne(raum):
    """Nimmt den Schluessel eines Raums heraus.

    Damit sind seine Abschnitte endgueltig unlesbar -- auch die, die noch
    in einem Abzug liegen. Genau dafuer ist es da: einen Raum zu loeschen
    soll mehr sein als Zeilen aus einer Datenbank zu nehmen.
    """
    raeume_ = _lade()
    if raum not in raeume_:
        return False
    raeume_.pop(raum)
    _speichere(raeume_)
    _schluessel.pop(raum, None)
    return True


def vergiss():
    """Gemerkte Schluessel aus dem Speicher werfen -- fuer Tests."""
    _schluessel.clear()


# --- DATEINAMEN ---
#
# Ein Dateiname verraet den Vorgang, ohne dass jemand die Datei oeffnet:
# "Kuendigung_Mueller_2026.pdf" steht in den Metadaten von Chroma und war
# bis hierher im Klartext lesbar, auch wenn der Abschnittstext daneben
# verschluesselt lag.
#
# Ihn einfach zu verschluesseln genuegt nicht: der Name ist zugleich der
# SCHLUESSEL, mit dem die Anwendung filtert -- Doppel erkennen, ein
# Dokument loeschen, es in einen anderen Raum verschieben, die Suche auf
# eine Auswahl eingrenzen. Verschluesselt ist er dafuer unbrauchbar, denn
# AES-GCM liefert bei jedem Aufruf ein anderes Ergebnis.
#
# Deshalb ZWEI Angaben:
#
#     file_name   der Name, verschluesselt -- zum Anzeigen
#     datei_id    ein HMAC ueber den Namen -- zum Filtern
#
# Der HMAC ist bestimmt: derselbe Name ergibt immer dieselbe Kennung,
# also funktionieren Gleichheitsfilter unveraendert. Und weil er mit dem
# Installationsschluessel gebildet wird, kann ihn niemand ohne Schluessel
# nachrechnen. Wer die Platte hat, sieht nur, DASS zwei Abschnitte zur
# selben Datei gehoeren -- nicht zu welcher.

def datei_id(name):
    """Bestimmte Kennung eines Dateinamens. Leer ohne Schluessel.

    Klein geschrieben und ohne Rand: "Angebot.pdf" und "angebot.pdf "
    sind fuer den Betrieb dieselbe Datei, und ein Filter, der sie
    unterscheidet, findet die Haelfte nicht.
    """
    sauber = str(name or "").strip().lower()
    if not sauber:
        return ""
    roh = geheim.signiere(("datei:" + sauber).encode("utf-8"))
    return roh[:32]


# --- ABSCHNITTE ---

def verschluessele_text(raum, text):
    """Klartext -> "LNX1:<base64>". Unveraendert, wenn nicht verfuegbar.

    base64 und nicht roh: Chroma legt Dokumente als Zeichenkette ab, und
    ein Bytefeld mit Nullbytes ueberlebt den Weg durch JSON nicht. Der
    Aufschlag ist ein Drittel -- gemessen an 20.608 Abschnitten rund
    10 MB, und damit die billigste Zeile dieses Moduls.
    """
    if text is None:
        return text
    k = schluessel(raum)
    if k is None:
        return text
    nonce = os.urandom(NONCE_LAENGE)
    geheimtext = _aes(k).encrypt(nonce, str(text).encode("utf-8"),
                                 raum.encode("utf-8"))
    # Das Nonce VOR den Geheimtext: encrypt() gibt es nicht zurueck, und
    # ohne es laesst sich nichts mehr entschluesseln. Es ist kein
    # Geheimnis, es darf sich nur nicht wiederholen.
    return MARKE + base64.b64encode(nonce + geheimtext).decode("ascii")


def entschluessele_text(raum, wert):
    """Zurueck zum Klartext. Alte, lesbare Abschnitte kommen unveraendert.

    Der Rueckweg ist wichtiger als er aussieht: eine Installation hat
    nach dem Umstieg beides im Bestand, und eine Frage soll beide finden.
    """
    if not isinstance(wert, str) or not wert.startswith(MARKE):
        return wert
    k = schluessel(raum, anlegen=False)
    if k is None:
        raise ValueError(f"Verschluesselter Abschnitt in '{raum}', aber "
                         f"kein Schluessel.")
    roh = base64.b64decode(wert[len(MARKE):])
    nonce, rest = roh[:NONCE_LAENGE], roh[NONCE_LAENGE:]
    return _aes(k).decrypt(nonce, rest, raum.encode("utf-8")).decode("utf-8")


def ist_verschluesselt(wert):
    return isinstance(wert, str) and wert.startswith(MARKE)


def _aes(schluessel_):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(schluessel_)
