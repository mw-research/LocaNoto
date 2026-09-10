"""Liest der Code eine Variable, die die Compose-Datei nicht durchreicht?

Der Fehler, den das findet, ist stumm: die Variable steht in der .env,
der Code liest sie, und im Container kommt sie nie an. Dann gilt still
die Vorgabe, und niemand sucht dort.
"""
import glob
import io
import os
import re
import sys

# Ohne Argument das Verzeichnis DIESER Datei -- nicht ein fester
# Pfad: sonst prueft ein Spiegel den Hauptstand und meldet 'alles
# in Ordnung' fuer einen Bestand, den er gar nicht angesehen hat.
WURZEL = (sys.argv[1] if len(sys.argv) > 1
          else os.path.dirname(os.path.abspath(__file__)))

# Was der Code liest.
gelesen = {}
for p in glob.glob(os.path.join(WURZEL, "*.py")):
    t = io.open(p, encoding="utf-8").read()
    for m in re.finditer(r'(?:os\.getenv|paths\.env_int|paths\.env_float)'
                         r'\(\s*["\']([A-Z][A-Z0-9_]+)["\']', t):
        gelesen.setdefault(m.group(1), set()).add(os.path.basename(p))

# Was die Compose-Datei durchreicht.
compose = io.open(os.path.join(WURZEL, "docker-compose.yaml"),
                  encoding="utf-8").read()
durchgereicht = set(re.findall(r'\$\{([A-Z][A-Z0-9_]+)', compose))
gesetzt = set(re.findall(r'^\s*-\s*([A-Z][A-Z0-9_]+)=', compose, re.M))

# Was in der Vorlage erklaert ist.
vorlage = io.open(os.path.join(WURZEL, ".env.example"), encoding="utf-8").read()
erklaert = set(re.findall(r'^#?\s*([A-Z][A-Z0-9_]+)=', vorlage, re.M))

# Variablen, die nicht aus der .env kommen: von Docker, Python oder
# Bibliotheken gesetzt, oder Pfade, die die Compose-Datei selbst bestimmt.
EIGEN = {
    "HOME", "PATH", "PWD", "USER", "TMPDIR", "TEMP", "TMP",
    "HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
    "SENTENCE_TRANSFORMERS_HOME", "ANONYMIZED_TELEMETRY",
    "CHROMA_ANONYMIZED_TELEMETRY", "STREAMLIT_BROWSER_GATHER_USAGE_STATS",
    "LOCANOTO_DATEN", "LOCANOTO_KONFIG", "LOCANOTO_INDEX",
    "INGEST_ORDNER", "INGEST_RAUM", "LOCANOTO_SCHLUESSEL",
    # Absichtlich NICHT durchgereicht: das waere ein Verwalterpasswort in
    # der .env, also in einer Datei auf der Platte. Fuer eine
    # unbeaufsichtigte Einrichtung gehoeren sie an den einzelnen Aufruf:
    #   docker compose exec -e LOCANOTO_ERSTER_VERWALTER=markus     #       -e LOCANOTO_ERSTES_PASSWORT=... locanoto_bot python einrichten.py
    "LOCANOTO_ERSTER_VERWALTER", "LOCANOTO_ERSTES_PASSWORT",
}

fehlt_compose = sorted(k for k in gelesen
                       if k not in durchgereicht and k not in gesetzt
                       and k not in EIGEN)
fehlt_vorlage = sorted(k for k in gelesen
                       if k not in erklaert and k not in EIGEN)

# Eine Pflichtvariable in der Compose-Datei legt JEDEN compose-Befehl
# lahm, nicht nur den Dienst, der sie braucht: Compose loest die ganze
# Datei auf, auch ohne --profile. Genau so wurde einmal eine laufende
# Installation blockiert, die ownCloud gar nicht benutzt.
pflicht = re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", compose)
if pflicht:
    print(f">>> {len(pflicht)} PFLICHTVARIABLEN in der Compose-Datei:")
    for k in sorted(set(pflicht)):
        print(f"      {k}")
    print("    Sie blockieren jeden compose-Befehl, auch bei nicht")
    print("    gestartetem Profil. Besser ${NAME:-} und den Fehler dort")
    print("    entstehen lassen, wo er hingehoert.")
    print()

print(f"{len(gelesen)} Variablen werden im Code gelesen.")
if fehlt_compose:
    print(f"\n>>> {len(fehlt_compose)} kommen NICHT im Container an:")
    for k in fehlt_compose:
        print(f"      {k:<32} gelesen in {', '.join(sorted(gelesen[k]))}")
else:
    print("Alle erreichen den Container.")

if fehlt_vorlage:
    print(f"\n{len(fehlt_vorlage)} stehen nicht in .env.example:")
    for k in fehlt_vorlage:
        print(f"      {k:<32} {', '.join(sorted(gelesen[k]))}")

sys.exit(1 if (fehlt_compose or pflicht) else 0)
