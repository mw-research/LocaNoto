"""Warum findet die Listenabfrage nichts?

Gibt Struktur und Modellantwort aus -- KEINE Zelleninhalte, keine
Beispielwerte, keine Ergebniszeilen. Was hier auf dem Bildschirm landet,
darf weitergegeben werden.

    docker compose exec -T locanoto_bot python /app/listen_diagnose.py "Deine Frage"
"""
import sys

import llm
import paths
import tabellen

paths.bootstrap()

frage = sys.argv[1] if len(sys.argv) > 1 else ""

print("=" * 64)
print("1. ORDNER UND KATALOG")
print("=" * 64)
print(f"  Listenordner:  {tabellen.pfad()}")
print(f"  Katalogdatei:  {tabellen.KATALOG}")

k = tabellen.lies_katalog()
e = k.get("eintraege") or []
f = k.get("fehler") or []
print(f"  Blaetter im Katalog: {len(e)}")
if f:
    print(f"  NICHT LESBAR: {len(f)}")
    for datei, grund in f[:10]:
        print(f"     {datei}: {grund}")

if not e:
    print("\n  >>> Der Katalog ist LEER. Damit wird die Listensuche gar")
    print("      nicht erst angefragt -- das erklaert 'kein einziges'.")
    print("      Naechster Schritt: 'Listen neu einlesen' und die")
    print("      Fehlerliste oben ansehen.")
    sys.exit(0)

print()
print("=" * 64)
print("2. WELCHE BLAETTER WERDEN UEBERHAUPT ANGEFRAGT?")
print("=" * 64)
# Der Filter aus app.py: als "gross" markierte Blaetter bleiben aussen vor,
# solange der Haken fuer grosse Listen nicht gesetzt ist.
grosse = [x for x in e if x.get("gross")]
klein = [x for x in e if not x.get("gross")]
print(f"  GROSS_AB = {tabellen.GROSS_AB} Zeilen")
print(f"  regulaer angefragt: {len(klein)} Blaetter")
print(f"  nur mit Haken 'grosse Listen': {len(grosse)} Blaetter")
if grosse and not klein:
    print("\n  >>> ALLE Blaetter sind als 'gross' markiert. Ohne den Haken")
    print("      'Auch grosse Listen durchsuchen' wird KEIN Blatt")
    print("      angefragt. Das erklaert 'kein einziges'.")
for x in grosse[:12]:
    print(f"     gross: {x['datei']}#{x.get('blatt','')} "
          f"({x['zeilen']} Zeilen)")

print()
print("  Bereiche:", ", ".join(tabellen.bereiche(e)) or "(keine)")
for x in e:
    print(f"     {x['datei']}#{x.get('blatt','')}  "
          f"{len(x['spalten'])} Spalten, {x['zeilen']} Zeilen, "
          f"Kopfzeile {x.get('kopfzeile')}")

print()
print("=" * 64)
print("3. KATALOGTEXT FUERS MODELL")
print("=" * 64)
t_alle = tabellen.als_text(e)
t_klein = tabellen.als_text(klein)
print(f"  Grenze TABELLEN_KATALOG_MAX_CHARS = {tabellen.KATALOG_MAX_CHARS}")
print(f"  alle Blaetter:      {len(t_alle):>7} Zeichen"
      + ("   >>> GEKUERZT" if "gekuerzt" in t_alle else "   vollstaendig"))
print(f"  nur die kleinen:    {len(t_klein):>7} Zeichen"
      + ("   >>> GEKUERZT" if "gekuerzt" in t_klein else "   vollstaendig"))
print(f"  BEISPIELE_BIS={tabellen.BEISPIELE_BIS}  "
      f"BEISPIELE={tabellen.BEISPIELE_MAX}")

if not frage:
    print("\n  Fuer Teil 4 eine Frage als Argument mitgeben.")
    sys.exit(0)

print()
print("=" * 64)
print("4. WAS ANTWORTET DAS MODELL?")
print("=" * 64)
print(f"  Frage: {frage}")
auswahl = klein or e
try:
    c = llm.client("CHAT")
    m = llm.modell("CHAT")
    print(f"  Modell: {m}")
    datei, blatt, sql = tabellen.formuliere(
        c, m, frage, tabellen.als_text(auswahl))
except Exception as ex:
    print(f"\n  >>> FEHLER beim Fragen: {type(ex).__name__}: {ex}")
    sys.exit(1)

if not datei:
    print("\n  >>> Das Modell hat KEINE ABFRAGE zurueckgegeben.")
    print("      Es hat sich also fuer 'keine der Listen passt'")
    print("      entschieden. Genau das ergibt 'kein einziges Ergebnis'.")
    print("      Gruende, in dieser Reihenfolge pruefen:")
    print("        * steht oben bei 3. >>> GEKUERZT? Dann sieht es die")
    print("          hinteren Blaetter nicht und liest mitten in einer")
    print("          abgeschnittenen Spaltenzeile.")
    print("        * passt die Frage zu einem Spaltennamen aus 2.?")
    print("      Zum Vergleich dieselbe Frage mit nur EINEM Blatt:")
    try:
        d2, b2, s2 = tabellen.formuliere(
            c, m, frage, tabellen.als_text(auswahl[:1]))
        print(f"        mit 1 Blatt ({auswahl[0]['datei']}): "
              + (f"BLATT {d2}#{b2}, SQL vorhanden" if d2
                 else "auch KEINE ABFRAGE"))
    except Exception as ex:
        print(f"        Fehler: {ex}")
    sys.exit(0)

print(f"  gewaehlt: BLATT {datei}#{blatt}")
print(f"  SQL-Laenge: {len(sql)} Zeichen")
bekannt = {(x["datei"], x.get("blatt") or "") for x in e}
if (datei, blatt or "") not in bekannt:
    print("\n  >>> Das gewaehlte Blatt steht NICHT im Katalog. Das Modell")
    print("      hat einen Namen erfunden oder abgeschnitten gelesen.")
    print(f"      Bekannt sind: {sorted(d for d, _b in bekannt)[:10]}")
    sys.exit(0)

try:
    spalten, zeilen = tabellen.fuehre_aus(datei, blatt, sql)
except Exception as ex:
    print(f"\n  >>> Die Abfrage lief nicht: {type(ex).__name__}: {ex}")
    print("      (SQL wird hier nicht ausgegeben -- es kann Suchwerte")
    print("       aus der Frage enthalten.)")
    sys.exit(0)

print(f"  Ergebnis: {len(zeilen)} Zeilen, {len(spalten)} Spalten")
if not zeilen:
    print("\n  >>> Blatt und SQL waren da, aber das Ergebnis ist leer.")
    print("      Dann ist es kein Routing-, sondern ein WHERE-Problem:")
    print("      das Modell hat auf dem RICHTIGEN Blatt nach dem")
    print("      falschen Wert gefiltert.")
else:
    print("\n  >>> Diese Frage funktioniert. Zeilen werden hier absichtlich")
    print("      nicht ausgegeben.")
