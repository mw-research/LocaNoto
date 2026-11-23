"""Was macht welche Datei, und woher kommt ihr Wert?

    python scripts/module_map.py              die Uebersicht
    python scripts/module_map.py --tabelle    die Tabelle fuer REFERENZ.md

Eine Uebersicht, die jemand von Hand pflegt, ist nach dem naechsten Modul
falsch -- und niemand merkt es, weil eine Beschreibung nicht abstuerzt.
Diese hier wird gelesen, nicht erinnert: Zeilen, Abhaengigkeiten,
Umgebungsvariablen und der erste Satz des Dateikopfs kommen aus dem Code
selbst.

Die Schichten sind das Einzige, was hier von Hand steht (SCHICHT unten),
denn sie sind eine Aussage ueber die Absicht und nicht ueber den Code.
Der Selbsttest prueft, dass jede Datei in genau einer Schicht steht --
eine neue faellt damit auf, statt still herauszufallen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ast
import io

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Die Absicht, nicht die Messung. Wer eine Datei hinzufuegt, traegt sie
# hier ein -- der Selbsttest besteht darauf.
SCHICHT = {
    "Einstiege": (
        "api", "ingest", "ingest_images", "abgleich",
        "einrichten", "sicherung", "spiegeln", "websuche",
        "rebuild_index", "migrate_to_postgres",
        "server", "routes_account", "routes_chat",
        "routes_documents", "routes_admin", "worker", "web",
        "web_admin", "doctor", "trustbundle",
        "reembed", "web_tickets",
    ),
    "Fachlogik": (
        "pipeline", "ranking", "tabellen", "listenquellen", "owncloud",
        "aufnehmen",
        "lesen", "tables", "textutils", "vision", "bildtext", "sqldb", "db_files",
        "sqlpruefung", "sqlquellen", "chats", "feedback", "notzugang",
        "prompts", "presets", "hintergrund", "envcheck", "mcp",
        "postfach", "ocr", "answering", "doc_actions", "web_sources",
        "mailboxes", "accounts", "sessions", "jobs", "metrics", "oidc",
        "auth", "sicherheit", "datentraeger", "workspace_notes",
        "attachments", "imap_mailbox", "created_files", "web_research",
        "notices", "mail_watch", "tickets", "external_model", "mcp_oauth",
    ),
    "Bestand": (
        "store", "keyword_index", "raeume", "benutzer", "raumschluessel",
        "budget", "pg_collection", "pg_keywords", "vector_columns",
    ),
    "Grundlage": ("paths", "geheim", "llm", "embedding",
                  "dateisperre", "sprache", "database", "statefiles",
                  "local_time"),
}


# Folders with files of their own kind. Their layer is the folder; a
# file there is named with it (scripts/create_user).
ORDNER = {"scripts": "Werkzeuge", "tests": "Tests"}
RANG = ("Grundlage", "Bestand", "Fachlogik", "Einstiege", "Werkzeuge", "Tests")


def _dateien(basis):
    """(name, path) of every module: the root first, then the folders."""
    aus = []
    for ordner in ("",) + tuple(ORDNER):
        pfad = os.path.join(basis, ordner)
        for d in sorted(os.listdir(pfad)):
            if d.endswith(".py") and not d.startswith("_"):
                name = f"{ordner}/{d[:-3]}" if ordner else d[:-3]
                aus.append((name, os.path.join(pfad, d)))
    return aus


def lies(basis=BASIS):
    """Die gemessene Landkarte: je Modul Zeilen, Kanten, Umgebung, Kopf."""
    dateien = _dateien(basis)
    # what an import names -> the module; a root module wins
    eigene = {}
    for name, _p in reversed(dateien):
        eigene[name.rsplit("/", 1)[-1]] = name
    karte = {}
    for name_d, pfad in dateien:
        quelle = io.open(pfad, encoding="utf-8").read()
        baum = ast.parse(quelle)
        nutzt, umgebung = set(), set()
        for k in ast.walk(baum):
            if isinstance(k, ast.Import):
                for a in k.names:
                    if a.name.split(".")[0] in eigene:
                        nutzt.add(eigene[a.name.split(".")[0]])
            elif isinstance(k, ast.ImportFrom):
                if k.module and k.module.split(".")[0] in eigene:
                    nutzt.add(eigene[k.module.split(".")[0]])
            elif isinstance(k, ast.Call):
                ruf = ast.unparse(k.func)
                if ruf in ("os.getenv", "os.environ.get", "paths.env_int",
                           "paths.env_float", "paths.env_bool"):
                    if k.args and isinstance(k.args[0], ast.Constant):
                        umgebung.add(str(k.args[0].value))
        nutzt.discard(name_d)
        karte[name_d] = {
            "zeilen": quelle.count("\n") + 1,
            "nutzt": nutzt,
            "umgebung": sorted(umgebung),
            "kopf": (ast.get_docstring(baum) or "").split("\n")[0],
        }
    for name, i in karte.items():
        i["benutzt_von"] = sorted(n for n, j in karte.items()
                                  if name in j["nutzt"])
        if "/" in name:
            i["schicht"] = ORDNER[name.split("/")[0]]
        else:
            i["schicht"] = next((s for s, m in SCHICHT.items() if name in m), "?")
    return karte


def tabelle(karte):
    """Die Tabelle fuer REFERENZ.md -- erzeugt, nicht gepflegt."""
    zeilen = ["| Datei | Aufgabe | liest aus der `.env` | liefert an |",
              "|---|---|---|---|"]
    for schicht in RANG:
        zeilen.append(f"| **{schicht}** | | | |")
        teil = sorted((n for n, i in karte.items() if i["schicht"] == schicht),
                      key=lambda n: -karte[n]["zeilen"])
        for name in teil:
            i = karte[name]
            umg = ", ".join(f"`{v}`" for v in i["umgebung"][:3])
            if len(i["umgebung"]) > 3:
                umg += f" +{len(i['umgebung']) - 3}"
            an = ", ".join(f"`{v}`" for v in i["benutzt_von"][:4]) or "—"
            if len(i["benutzt_von"]) > 4:
                an += f" +{len(i['benutzt_von']) - 4}"
            zeilen.append(f"| `{name}.py` | {i['kopf']} | {umg or '—'} | {an} |")
    return "\n".join(zeilen)


def main():
    karte = lies()
    if "--tabelle" in sys.argv:
        print(tabelle(karte))
        return
    print(f"{'Modul':<24}{'Zeilen':>7}  {'Schicht':<12}benutzt von")
    print("-" * 96)
    for name in sorted(karte, key=lambda n: -karte[n]["zeilen"]):
        i = karte[name]
        von = ", ".join(i["benutzt_von"]) or "--"
        print(f"{name:<24}{i['zeilen']:>7}  {i['schicht']:<12}{von[:52]}")
    print(f"\n{len(karte)} Module, "
          f"{sum(len(i['nutzt']) for i in karte.values())} Kanten, "
          f"{len({v for i in karte.values() for v in i['umgebung']})} "
          f"Umgebungsvariablen.")


if __name__ == "__main__":
    main()
