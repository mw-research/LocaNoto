"""In welchem Blatt und in welcher Spalte steht ein Begriff -- und wie
geschrieben?

    docker compose exec -T locanoto_bot python - saege < listen_suche.py

Gibt aus: Blatt, Spalte, Zahl der Treffer und die verschiedenen
SCHREIBWEISEN des gefundenen Wortes. Keine Zeilen, keine Teilenummern,
keine Preise -- nur das eine Wort, das gepasst hat.

Gedacht fuer den Fall, dass eine Abfrage null Zeilen liefert und niemand
weiss, ob das Blatt falsch war oder der Suchbegriff.
"""
import collections
import re
import sys
import unicodedata
import warnings

# openpyxl meldet zu jeder Arbeitsmappe mit Druckbereich eine Warnung.
# Bei 28 Blaettern sind das mehr Zeilen als Ergebnis.
warnings.filterwarnings("ignore")

import paths
import tabellen

paths.bootstrap()

begriff = sys.argv[1] if len(sys.argv) > 1 else ""
if not begriff:
    print("Suchbegriff als Argument angeben, z. B. saege")
    sys.exit(2)


def falte(text):
    """Klein, ohne Akzente, ae fuer ä -- damit jede Schreibweise passt."""
    t = str(text).lower()
    t = (t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss"))
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


ziel = falte(begriff)
print(f"Suche nach '{begriff}' (gefaltet: '{ziel}')")
print(f"Grenze TABELLEN_KATALOG_MAX_CHARS = {tabellen.KATALOG_MAX_CHARS}")
print("Unicode-LIKE im Abbild: "
      + ("JA" if hasattr(tabellen, "_unicode_funktionen") else "NEIN -- "
         "der Container hat den Stand von vor der Reparatur"))
print()

eintraege = tabellen.lies_katalog().get("eintraege") or []
gesamt = 0
print(f"{len(eintraege)} Blaetter -- jedes wird aus der Datei gelesen, "
      f"das dauert.")
for nr, e in enumerate(eintraege, 1):
    kennung = e["datei"] + (f"#{e['blatt']}" if e["blatt"] else "")
    print(f"  [{nr}/{len(eintraege)}] {kennung}", flush=True)
    try:
        con = tabellen._lade(e["datei"], e.get("blatt"))
    except Exception as ex:
        print(f"  [!] {kennung}: {ex}")
        continue
    zeile = con.execute("SELECT * FROM daten LIMIT 0")
    spalten = [d[0] for d in zeile.description]
    for s in spalten:
        schreibweisen = collections.Counter()
        treffer = 0
        for (wert,) in con.execute(f'SELECT "{s}" FROM daten'):
            if wert is None:
                continue
            text = str(wert)
            if ziel not in falte(text):
                continue
            treffer += 1
            # Nur das WORT, das gepasst hat -- nicht die Zelle. Eine
            # Bezeichnung traegt Masse, Nummern und manchmal Preise.
            for w in re.findall(r"[^\s,;/|]+", text):
                if ziel in falte(w):
                    schreibweisen[w] += 1
        if treffer:
            gesamt += treffer
            print(f"     >>> Spalte '{s}': {treffer} Zeilen")
            for w, n in schreibweisen.most_common(6):
                print(f"           {n:>5}x  {w}")

print()
if not gesamt:
    print(">>> Der Begriff kommt in KEINEM Blatt vor. Dann liegt es nicht")
    print("    an der Abfrage -- probiere einen kuerzeren Stamm.")
else:
    print(f">>> {gesamt} Zeilen insgesamt. Steht oben nur EIN Blatt, muss")
    print("    das Modell genau dieses waehlen; stehen mehrere da, braucht")
    print("    es den Mehrblattlauf (TABELLEN_BLAETTER).")
