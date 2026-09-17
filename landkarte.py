"""Was macht welche Datei, und woher kommt ihr Wert?

    python landkarte.py              die Uebersicht
    python landkarte.py --tabelle    die Tabelle fuer das README

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
import ast
import io
import os
import sys

BASIS = os.path.dirname(os.path.abspath(__file__))

# Die Absicht, nicht die Messung. Wer eine Datei hinzufuegt, traegt sie
# hier ein -- der Selbsttest besteht darauf.
SCHICHT = {
    "Einstiege": (
        "app", "verwaltung", "api", "ingest", "ingest_images", "abgleich",
        "einrichten", "sicherung", "selbsttest", "lasttest", "spiegeln",
        "create_user", "create_token", "manage_users", "bestandsliste",
        "packe_umzug", "rebuild_index", "raum_diagnose",
        "listen_diagnose", "was_sieht_die_platte", "pruefe_env", "landkarte",
    ),
    "Fachlogik": (
        "pipeline", "ranking", "tabellen", "listenquellen", "owncloud",
        "lesen", "tables", "textutils", "vision", "bildtext", "sqldb",
        "sqlpruefung", "sqlquellen", "chats", "feedback", "notzugang",
        "prompts", "presets", "quellticket", "hintergrund", "envcheck", "mcp",
        "auth", "sicherheit", "datentraeger",
    ),
    "Bestand": (
        "store", "keyword_index", "raeume", "benutzer", "raumschluessel",
        "budget",
    ),
    "Grundlage": ("paths", "geheim", "llm", "embedding"),
}


def lies(basis=BASIS):
    """Die gemessene Landkarte: je Modul Zeilen, Kanten, Umgebung, Kopf."""
    dateien = sorted(d for d in os.listdir(basis)
                     if d.endswith(".py") and not d.startswith("_"))
    eigene = {d[:-3] for d in dateien}
    karte = {}
    for d in dateien:
        quelle = io.open(os.path.join(basis, d), encoding="utf-8").read()
        baum = ast.parse(quelle)
        nutzt, umgebung = set(), set()
        for k in ast.walk(baum):
            if isinstance(k, ast.Import):
                for a in k.names:
                    if a.name.split(".")[0] in eigene:
                        nutzt.add(a.name.split(".")[0])
            elif isinstance(k, ast.ImportFrom):
                if k.module and k.module.split(".")[0] in eigene:
                    nutzt.add(k.module.split(".")[0])
            elif isinstance(k, ast.Call):
                ruf = ast.unparse(k.func)
                if ruf in ("os.getenv", "os.environ.get", "paths.env_int",
                           "paths.env_float", "paths.env_bool"):
                    if k.args and isinstance(k.args[0], ast.Constant):
                        umgebung.add(str(k.args[0].value))
        nutzt.discard(d[:-3])
        karte[d[:-3]] = {
            "zeilen": quelle.count("\n") + 1,
            "nutzt": nutzt,
            "umgebung": sorted(umgebung),
            "kopf": (ast.get_docstring(baum) or "").split("\n")[0],
        }
    for name, i in karte.items():
        i["benutzt_von"] = sorted(n for n, j in karte.items()
                                  if name in j["nutzt"])
        i["schicht"] = next((s for s, m in SCHICHT.items() if name in m), "?")
    return karte


def tabelle(karte):
    """Die Tabelle fuer das README -- erzeugt, nicht gepflegt."""
    zeilen = ["| Datei | Aufgabe | liest aus der `.env` | liefert an |",
              "|---|---|---|---|"]
    for schicht in ("Grundlage", "Bestand", "Fachlogik", "Einstiege"):
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
