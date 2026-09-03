"""Voreinstellungen: benannte Buendel aus Modell, Umfang und Formulierung.

Dieselbe Anlage taugt fuer verschiedene Anwendungen, aber nicht mit
denselben Einstellungen. Ein Bestand aus Bedienhandbuechern braucht andere
Suchsonden als eine Sammlung von Regelwerken, ein knappes Modell reicht fuer
Nachschlagefragen und nicht fuer Zusammenhaenge. Wer das jedes Mal von Hand
umstellt, macht es entweder selten oder falsch.

Eine Voreinstellung buendelt deshalb, was zusammengehoert:

    config/presets/<name>/
        preset.json        Bezeichnung, Chat-Modell, TOP_K, Sachgebiete
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

import paths

ORDNER = os.path.join(paths.CONFIG_DIR, "presets")

# Dateien, die eine Voreinstellung mitbringen kann.
VORLAGEN = ("system_prompt.txt", "search_prompt.txt", "sql_prompt.txt",
            "glossar.txt")

# Was in preset.json steht, mit den Vorgaben fuer fehlende Angaben.
FELDER = {
    "bezeichnung": "",
    "beschreibung": "",
    "chat_modell": "",
    "top_k": 0,
    "sachgebiete": [],
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
    if not os.path.isdir(ORDNER):
        return []
    return sorted(d for d in os.listdir(ORDNER)
                  if os.path.isfile(os.path.join(ORDNER, d, "preset.json")))


def lese(name):
    """Die Angaben einer Voreinstellung, mit Vorgaben aufgefuellt."""
    werte = dict(FELDER)
    if not name:
        return werte
    p = os.path.join(ORDNER, name, "preset.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            gelesen = json.load(f)
    except (OSError, json.JSONDecodeError):
        return werte
    if isinstance(gelesen, dict):
        for k in FELDER:
            if k in gelesen:
                werte[k] = gelesen[k]
    werte["bezeichnung"] = werte["bezeichnung"] or name
    return werte


def speichern(name, werte):
    """Legt eine Voreinstellung an oder aendert sie. (ok, meldung)."""
    name = _kennung(name)
    if not name:
        return False, "Bitte eine Bezeichnung angeben."
    ziel = os.path.join(ORDNER, name)
    daten = {k: werte.get(k, v) for k, v in FELDER.items()}
    try:
        os.makedirs(ziel, exist_ok=True)
        vorlaeufig = os.path.join(ziel, "preset.json.neu")
        with open(vorlaeufig, "w", encoding="utf-8", newline="\n") as f:
            json.dump(daten, f, indent=2, ensure_ascii=False)
        os.replace(vorlaeufig, os.path.join(ziel, "preset.json"))
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    return True, name


def loesche(name):
    """Entfernt eine Voreinstellung samt ihrer Vorlagen."""
    ziel = os.path.join(ORDNER, name)
    if not os.path.isdir(ziel):
        return False
    try:
        for d in os.listdir(ziel):
            os.remove(os.path.join(ziel, d))
        os.rmdir(ziel)
    except OSError:
        return False
    return True


def vorlage_pfad(name, datei):
    """Pfad einer Vorlage innerhalb einer Voreinstellung, oder None.

    None heisst: diese Voreinstellung bringt die Datei nicht mit, es gilt
    die naechste Stufe der Kette.
    """
    if not name or datei not in VORLAGEN:
        return None
    p = os.path.join(ORDNER, name, datei)
    return p if os.path.exists(p) else None
