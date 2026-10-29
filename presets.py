"""Voreinstellungen: benannte Buendel aus Modell, Umfang und Formulierung.

Dieselbe Anlage taugt fuer verschiedene Anwendungen, aber nicht mit
denselben Einstellungen. Ein Bestand aus Bedienhandbuechern braucht andere
Suchsonden als eine Sammlung von Regelwerken, ein knappes Modell reicht fuer
Nachschlagefragen und nicht fuer Zusammenhaenge. Wer das jedes Mal von Hand
umstellt, macht es entweder selten oder falsch.

Eine Voreinstellung buendelt deshalb, was zusammengehoert:

    config/presets/<name>/
        preset.json        Bezeichnung, Chat-Modell, TOP_K
        system_prompt.txt  optional
        search_prompt.txt  optional
        sql_prompt.txt     optional
        glossar.txt        optional

Fehlt eine Datei, gilt die aus config/, sonst die mitgelieferte -- dieselbe
Kette wie bisher, nur um eine Stufe verlaengert.

Was bewusst NICHT hineingehoert:

Das Embedding-Modell. Die Abschnitte im Bestand sind mit einem bestimmten
Modell vektorisiert; ein anderes vergleicht Vektoren aus einem anderen Raum.
Die Suche liefert dann Unsinn, ohne dass etwas fehlschlaegt -- die Antwort
klingt normal und zitiert die falschen Stellen. Das Embedding-Modell gehoert
zum Index, nicht zur Bedienung, und ein Wechsel verlangt einen neuen Ingest.

Adressen und Schluessel. Wohin die Fragen gehen, ist Sache der Installation
und steht in der .env. Eine Auswahlliste in der Oberflaeche ist der falsche
Ort fuer diese Entscheidung.
"""
import json
import os
import re

import dateisperre
import paths
import statefiles

ORDNER = os.path.join(paths.CONFIG_DIR, "presets")

# Eigene Voreinstellungen je Nutzer: Modell, Trefferzahl, Listenbereiche.
# Ohne Prompt-Dateien -- Prompts bleiben Sache der Admins, Nutzer
# verfeinern mit ihrer Anweisung (prompts.anweisung).
#
#   config/presets_nutzer/<kennung>/<name>.json
#
# Ihre Kennung ist "@<kennung>/<name>". Gemeinsame Namen koennen kein "@"
# enthalten (_kennung), die beiden kommen sich also nie in die Quere.
NUTZER_ORDNER = os.path.join(paths.CONFIG_DIR, "presets_nutzer")
EIGEN = "@"

# Dateien, die eine Voreinstellung mitbringen kann.
VORLAGEN = ("system_prompt.txt", "search_prompt.txt", "sql_prompt.txt",
            "glossar.txt")

# Was in preset.json steht, mit den Vorgaben fuer fehlende Angaben.
FELDER = {
    "bezeichnung": "",
    "beschreibung": "",
    "chat_modell": "",
    "top_k": 0,
    # Welche Unterordner des Listenordners diese Voreinstellung benutzt.
    # Ein Pfad steht hier bewusst nicht: der Wurzelordner ist Sache der
    # Installation (TABELLEN_PFAD), sonst koennte eine Voreinstellung auf
    # jedes Verzeichnis im Container zeigen -- auch auf config/.
    "listen_bereiche": [],
}


def _kennung(bezeichnung):
    """Ordnername aus einer Bezeichnung -- ohne Ueberraschungen im Pfad."""
    k = re.sub(r"[^0-9A-Za-z._-]+", "-", bezeichnung.strip().lower())
    return k.strip("-.")[:40]


def namen():
    """Vorhandene Voreinstellungen, alphabetisch."""
    if not statefiles.isdir(ORDNER):
        return []
    return sorted(d for d in statefiles.listdir(ORDNER)
                  if statefiles.isfile(os.path.join(ORDNER, d, "preset.json")))


def ist_eigene(name):
    return str(name or "").startswith(EIGEN)


def _eigene_datei(name):
    """Pfad einer eigenen Voreinstellung, oder None bei krummer Kennung."""
    nutzer, _, kurz = str(name)[len(EIGEN):].partition("/")
    if (not nutzer or not kurz or _kennung(nutzer) != nutzer
            or _kennung(kurz) != kurz):
        return None
    return os.path.join(NUTZER_ORDNER, nutzer, kurz + ".json")


def eigene(benutzer):
    """Die eigenen Voreinstellungen eines Nutzers, als Kennungen."""
    k = _kennung(str(benutzer or ""))
    ordner = os.path.join(NUTZER_ORDNER, k)
    if not k or not statefiles.isdir(ordner):
        return []
    return sorted(f"{EIGEN}{k}/{d[:-5]}" for d in statefiles.listdir(ordner)
                  if d.endswith(".json"))


def gehoert(name, benutzer):
    k = _kennung(str(benutzer or ""))
    return (bool(k) and ist_eigene(name)
            and _eigene_datei(name) is not None
            and str(name)[len(EIGEN):].partition("/")[0] == k)


def erlaubt(name, benutzer):
    """Darf dieser Nutzer die Voreinstellung benutzen?"""
    return not name or name in namen() or gehoert(name, benutzer)


def eigene_speichern(benutzer, bezeichnung, werte):
    """Legt eine eigene Voreinstellung an oder aendert sie. (ok, kennung)."""
    k, kurz = _kennung(str(benutzer or "")), _kennung(str(bezeichnung or ""))
    if not k or not kurz:
        return False, "Bitte eine Bezeichnung angeben."
    daten = {f: werte.get(f, v) for f, v in FELDER.items()}
    daten["bezeichnung"] = str(bezeichnung).strip()
    try:
        dateisperre.schreibe_atomar(
            os.path.join(NUTZER_ORDNER, k, kurz + ".json"),
            json.dumps(daten, indent=2, ensure_ascii=False))
    except OSError as e:
        return False, f'Speichern fehlgeschlagen: {e}'
    return True, f"{EIGEN}{k}/{kurz}"


def eigene_loeschen(name, benutzer):
    """Entfernt eine eigene Voreinstellung -- nur die des Nutzers selbst."""
    if not gehoert(name, benutzer):
        return False
    pfad = _eigene_datei(name)
    try:
        statefiles.remove(pfad)
    except (OSError, TypeError):
        return False
    return True


def lese(name):
    """Die Angaben einer Voreinstellung, mit Vorgaben aufgefuellt."""
    werte = dict(FELDER)
    if not name:
        return werte
    p = (_eigene_datei(name) if ist_eigene(name)
         else os.path.join(ORDNER, name, "preset.json"))
    if not p:
        return werte
    try:
        with statefiles.open(p, "r", encoding="utf-8") as f:
            gelesen = json.load(f)
    except (OSError, json.JSONDecodeError):
        return werte
    if isinstance(gelesen, dict):
        for k in FELDER:
            if k in gelesen:
                werte[k] = gelesen[k]
    werte["bezeichnung"] = werte["bezeichnung"] or name
    return werte


def anzeige(name):
    """Name fuer die Auswahl; eigene mit Kennzeichen."""
    if not name:
        return ""
    b = lese(name)["bezeichnung"]
    return f"{b} (eigene)" if ist_eigene(name) else b


def speichern(name, werte):
    """Legt eine Voreinstellung an oder aendert sie. (ok, meldung)."""
    name = _kennung(name)
    if not name:
        return False, "Bitte eine Bezeichnung angeben."
    ziel = os.path.join(ORDNER, name)
    daten = {k: werte.get(k, v) for k, v in FELDER.items()}
    try:
        dateisperre.schreibe_atomar(
            os.path.join(ziel, "preset.json"),
            json.dumps(daten, indent=2, ensure_ascii=False))
    except OSError as e:
        return False, f'Speichern fehlgeschlagen: {e}'
    return True, name


def loesche(name):
    """Entfernt eine Voreinstellung samt ihrer Vorlagen."""
    # Only a real preset name: "..", "../x" would leave the preset folder.
    if name not in namen():
        return False
    ziel = os.path.join(ORDNER, name)
    if not statefiles.isdir(ziel):
        return False
    try:
        for d in statefiles.listdir(ziel):
            statefiles.remove(os.path.join(ziel, d))
        statefiles.rmdir(ziel)
    except OSError:
        return False
    return True


def vorlage_pfad(name, datei):
    """Pfad einer Vorlage innerhalb einer Voreinstellung, oder None.

    None heisst: diese Voreinstellung bringt die Datei nicht mit, es gilt
    die naechste Stufe der Kette.
    """
    if ist_eigene(name):
        return None  # eigene bringen keine Prompt-Dateien mit
    if not name or datei not in VORLAGEN:
        return None
    p = os.path.join(ORDNER, name, datei)
    return p if statefiles.exists(p) else None
