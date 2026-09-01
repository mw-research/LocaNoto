"""Vergleicht die .env mit der mitgelieferten Vorlage.

Hintergrund: .env steht in der .gitignore, ein git pull fasst sie also nie
an. Geaendert wird nur .env.example. Kommt mit einem Update eine neue
Einstellung dazu oder aendert sich ein empfohlener Wert, merkt das niemand --
die eigene .env bleibt, wie sie war, und ein dort eingetragener Wert schlaegt
immer den Standard im Code.

Genau so ist eine Obergrenze fuer Tabellen-Chunks ueber mehrere Updates
hinweg auf einem Wert stehengeblieben, der zu Ausfaellen beim Vektorisieren
gefuehrt hat -- sichtbar erst nach tausenden Seiten Ingest.

Dieses Modul vergleicht beide Dateien und meldet die Unterschiede. Es
entscheidet nichts und aendert nichts; viele Abweichungen sind gewollt
(Firmenname, Port, Modellnamen). Es macht sie nur sichtbar.

Werte werden nie angezeigt. Bei Namen, die auf ein Geheimnis hindeuten,
findet nicht einmal ein Vergleich statt.
"""
import os
import re

import paths

# Namen, die ein Geheimnis enthalten koennen -- weder vergleichen noch nennen.
_GEHEIM = re.compile(r"(KEY|PASS|SECRET|TOKEN|CREDENTIAL)", re.I)

# Abweichungen, die im Normalfall gewollt sind und sonst nur Rauschen erzeugen.
_ERWARTET_ABWEICHEND = {
    "APP_PORT", "APP_TOPIC", "COMPANY_NAME", "EXPERT_ROLE", "CONTAINER_NAME",
    "ADMIN_USERS", "OPENAI_BASE_URL", "SQL_SERVER", "SQL_USER", "SQL_DB",
    "SQL_TABLES", "SQL_HINWEIS",
}


def _lies(pfad, auch_auskommentiert=False):
    """Schluessel-Wert-Paare aus einer .env-artigen Datei."""
    werte = {}
    if not os.path.exists(pfad):
        return werte
    with open(pfad, encoding="utf-8", errors="replace") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            if zeile.startswith("#"):
                if not auch_auskommentiert:
                    continue
                zeile = zeile.lstrip("#").strip()
            if "=" not in zeile:
                continue
            name, wert = zeile.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                continue
            werte[name] = wert.strip()
    return werte


def vergleiche():
    """(fehlend, abweichend, unbekannt) -- jeweils nur Namen, nie Werte.

    fehlend    in der Vorlage gesetzt, in der eigenen .env nicht vorhanden.
               Unkritisch: dann greift der Standard aus dem Code.
    abweichend in beiden gesetzt, aber mit unterschiedlichem Wert. Das ist
               der Fall, der still zu falschem Verhalten fuehrt.
    unbekannt  in der eigenen .env gesetzt, in der Vorlage gar nicht
               vorgesehen -- weder gesetzt noch auskommentiert. Entweder ist
               die Einstellung veraltet, oder die Vorlage hat sie verloren.
               Der zweite Fall ist genau so vorgekommen: beim Angleichen der
               Repositories wurde ein ganzer Abschnitt ueberschrieben, und
               ohne diese Meldung faellt so etwas erst auf, wenn jemand die
               Funktion neu einrichten will.
    """
    eigene = _lies(os.path.join(paths.BASE_DIR, ".env"))
    vorlage = _lies(os.path.join(paths.BASE_DIR, ".env.example"))
    # Auskommentierte Zeilen der Vorlage zaehlen als "vorgesehen".
    vorgesehen = set(_lies(os.path.join(paths.BASE_DIR, ".env.example"),
                           auch_auskommentiert=True))

    fehlend, abweichend, unbekannt = [], [], []
    for name, wert in vorlage.items():
        if _GEHEIM.search(name):
            continue
        if name not in eigene:
            fehlend.append(name)
        elif eigene[name] != wert and name not in _ERWARTET_ABWEICHEND:
            abweichend.append(name)

    for name in eigene:
        if not _GEHEIM.search(name) and name not in vorgesehen:
            unbekannt.append(name)

    return sorted(fehlend), sorted(abweichend), sorted(unbekannt)
