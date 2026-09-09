"""Warum ist ein eingelesenes Dokument nicht abrufbar?

Geht den Abrufpfad in der Reihenfolge durch, in der er brechen kann:
Raumrechte -> Sammlung -> Metadaten -> Stichwortindex -> Filter.

    docker compose exec -T locanoto_bot python - BENUTZER [DATEINAME] \
        < raum_diagnose.py

Gibt Struktur aus, keine Dokumentinhalte.
"""
import sys
import warnings

# openpyxl meldet zu jeder Arbeitsmappe mit Druckbereich
# eine Warnung -- hier nur Rauschen vor dem Ergebnis.
warnings.filterwarnings("ignore")

import keyword_index
import paths
import pipeline
import raeume
import store

paths.bootstrap()

wer = sys.argv[1] if len(sys.argv) > 1 else ""
gesucht = sys.argv[2] if len(sys.argv) > 2 else ""
if not wer:
    print("Benutzerkennung als erstes Argument angeben.")
    sys.exit(2)

print("=" * 66)
print(f"1. WELCHE RAEUME DARF '{wer}' LESEN?")
print("=" * 66)
alle = raeume.liste()
lesbar = raeume.lesbar(wer)
print(f"  angelegt insgesamt: {len(alle)}")
for k in sorted(set(list(alle) + lesbar)):
    e = alle.get(k) or {}
    marke = "LESBAR " if k in lesbar else "gesperrt"
    print(f"  {marke}  {k:<28} Mitglieder={e.get('mitglieder')} "
          f"Gruppe={e.get('gruppe') or '-'}"
          + ("  [nicht in raeume.json]" if k not in alle else ""))

print()
print("=" * 66)
print("2. SAMMLUNGEN")
print("=" * 66)
namen = store.namen()
print(f"  in der Datenbank: {sorted(namen)}")
paare = pipeline.sammlungen(wer)
print(f"  fuer die Suche herangezogen: {[r for r, _s in paare]}")
fehlt = [k for k in lesbar
         if store.sammlung(raeume.sammlung(k), anlegen=False) is None]
if fehlt:
    print(f"  ohne Sammlung (noch nichts hochgeladen): {fehlt}")
verwaist = [n for n in namen if n.startswith("raum_")
            and n[len("raum_"):] not in alle]
if verwaist:
    print(f"  >>> Sammlung OHNE Raumeintrag: {verwaist}")
    print("      Diese Abschnitte findet niemand -- der Raum steht nicht")
    print("      in raeume.json, also ist er fuer keinen lesbar.")

print()
print("=" * 66)
print("3. WAS LIEGT DRIN?")
print("=" * 66)
nach_raum, ordner = pipeline.dokumente(wer)
for r, dateien in sorted(nach_raum.items()):
    print(f"  {r:<28} {len(dateien)} Dateien")
print(f"  Sachgebiete insgesamt: {sorted(ordner)}")

treffer_raum = None
if gesucht:
    print()
    print(f"  Suche nach '{gesucht}' in ALLEN Sammlungen:")
    for n in sorted(namen):
        sml = store.sammlung(n, anlegen=False)
        if sml is None:
            continue
        try:
            d = store.hole(sml, n, where={"file_name": gesucht},
                           include=["metadatas"])
        except Exception as e:
            print(f"     {n}: nicht lesbar ({e})")
            continue
        ids = d.get("ids") or []
        if not ids:
            continue
        m = (d.get("metadatas") or [{}])[0] or {}
        print(f"     {n}: {len(ids)} Abschnitte  "
              f"raum={m.get('raum')!r} folder={m.get('folder')!r} "
              f"access={m.get('access')!r} owner={m.get('owner')!r}")
        treffer_raum = n[len("raum_"):] if n.startswith("raum_") else n
        if not m.get("raum"):
            print("        >>> KEIN raum in den Metadaten. Die "
                  "Stichwortsuche filtert nach Raum und wirft das heraus.")
        if treffer_raum not in lesbar:
            print(f"        >>> Der Raum '{treffer_raum}' ist fuer "
                  f"'{wer}' NICHT lesbar.")

print()
print("=" * 66)
print("4. STICHWORTINDEX")
print("=" * 66)
con = keyword_index.connect()
print(f"  Zeilen gesamt: {keyword_index.count(con)}")
print(f"  Journalmodus: {keyword_index.journal_modus(con)}")
try:
    for r, n in con.execute(
            "SELECT COALESCE(raum,'(leer)'), COUNT(*) FROM chunks "
            "GROUP BY 1 ORDER BY 2 DESC"):
        marke = "" if r in lesbar or r == "(leer)" else "   [nicht lesbar]"
        if r == "(leer)":
            marke = "   >>> ohne Raum -- faellt aus jeder Suche heraus"
        print(f"     raum={r:<28} {n:>7} Zeilen{marke}")
except Exception as e:
    print(f"  Abfrage fehlgeschlagen: {e}")
if gesucht:
    n = con.execute("SELECT COUNT(*) FROM chunks WHERE file_name = ?",
                    (gesucht,)).fetchone()[0]
    print(f"  Zeilen fuer '{gesucht}': {n}")
    if not n:
        print("     >>> Nicht im Stichwortindex. Vektorsuche findet es,")
        print("         Stichwortsuche nicht.")

print()
print("=" * 66)
print("5. FILTER DER OBERFLAECHE")
print("=" * 66)
print("  Der Sachgebietsfilter wird aus dem aktiven Preset VORBELEGT.")
try:
    import presets
    for name in presets.namen():
        w = presets.lese(name) or {}
        g = w.get("sachgebiete") or []
        if g:
            fehlend = [x for x in g if x not in ordner]
            print(f"     Preset '{name}': Sachgebiete {g}"
                  + (f"   >>> davon unbekannt: {fehlend}" if fehlend else ""))
        else:
            print(f"     Preset '{name}': kein Sachgebietsfilter")
except Exception as e:
    print(f"     Presets nicht lesbar: {e}")
print()
print("  Ist bei einem Preset ein Sachgebiet vorbelegt, das ein neu")
print("  hochgeladenes Dokument NICHT hat, wird dieses Dokument")
print("  stillschweigend aus der Suche gefiltert.")
