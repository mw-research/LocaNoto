"""Die alte gemeinsame Sammlung loeschen -- nach einer Gegenprobe.

Vor den Raeumen lagen alle Abschnitte in einer Sammlung namens
pdf_documents, unterschieden durch die Merkmale access und owner.
umsortieren.py hat sie in die Raumsammlungen kopiert und die alte
absichtlich stehen lassen: sie war der Rueckweg, falls an der
Umsortierung etwas nicht stimmt.

Ist der Rueckweg nicht mehr noetig, kostet sie nur Platz -- und mehr als
das: sie verdoppelt jeden Abzug, und ihre Abschnitte liegen im Klartext,
weil nachverschluesseln.py nur Raumsammlungen anfasst. Wer das
Datenvolume kopiert, liest sie.

    python altbestand_loeschen.py --pruefen    nur nachrechnen
    python altbestand_loeschen.py              loeschen

GEPRUEFT WIRD VORHER, und zwar mit der Frage, auf die es ankommt: liegt
JEDE Kennung aus der alten Sammlung auch in einer Raumsammlung? Nicht
"sind es gleich viele" -- zwei gleich grosse Mengen koennen verschiedene
sein. Fehlt auch nur eine, wird nicht geloescht und die Zahl genannt.

Der Abzug wird ebenfalls verlangt. Loeschen ist der eine Vorgang, der
sich nicht zurueckdrehen laesst, und "ich dachte, da ist eine Sicherung"
ist die haeufigste Erklaerung danach.
"""
import sys

import paths
import sicherung
import store

STAPEL = 2000


def kennungen(sml, name):
    """Alle Chunk-Kennungen einer Sammlung."""
    aus, gelesen = set(), 0
    gesamt = sml.count()
    while gelesen < gesamt:
        b = store.hole(sml, name, include=[], limit=STAPEL, offset=gelesen)
        ids = b.get("ids") or []
        if not ids:
            break
        aus.update(ids)
        gelesen += len(ids)
    return aus


def main():
    nur_pruefen = "--pruefen" in sys.argv
    paths.bootstrap()

    try:
        alt = store.collection(anlegen=False)
    except Exception:
        print(f"Die alte Sammlung '{paths.COLLECTION_NAME}' gibt es nicht "
              f"(mehr). Nichts zu tun.")
        return 0

    anzahl = alt.count()
    print(f"Alte Sammlung '{paths.COLLECTION_NAME}': {anzahl} Abschnitte")
    if not anzahl:
        print("Leer. Sie kann weg.")
        if not nur_pruefen:
            store.loesche(paths.COLLECTION_NAME)
            print("Geloescht.")
        return 0

    print("Lese die Kennungen ...")
    alte = kennungen(alt, paths.COLLECTION_NAME)
    in_raeumen = set()
    for name in sorted(store.namen()):
        if not name.startswith(store.VORSILBE_RAUM):
            continue
        sml = store.sammlung(name, anlegen=False)
        if sml is None:
            continue
        k = kennungen(sml, name)
        in_raeumen |= k
        print(f"  {name:<30} {len(k):>7} Abschnitte")

    fehlend = alte - in_raeumen
    print()
    print(f"  in der alten Sammlung:      {len(alte):>7}")
    print(f"  davon in einem Raum:        {len(alte) - len(fehlend):>7}")
    print(f"  NUR in der alten Sammlung:  {len(fehlend):>7}")

    if fehlend:
        print()
        print("Es wird NICHT geloescht. Diese Abschnitte gibt es sonst")
        print("nirgends -- sie waeren danach weg:")
        for k in sorted(fehlend)[:10]:
            print(f"    {k}")
        if len(fehlend) > 10:
            print(f"    ... und {len(fehlend) - 10} weitere")
        print()
        print("Erst umsortieren: python umsortieren.py --erneut")
        return 1

    print()
    print("Jeder Abschnitt der alten Sammlung liegt auch in einem Raum.")

    if nur_pruefen:
        print("--pruefen: nichts geloescht.")
        print("Loeschen: python altbestand_loeschen.py")
        return 0

    # Ein Abzug muss dasein, und zwar ein vollstaendiger.
    abzuege = [s for _n, _p, _g, s in sicherung.liste()
               if s.get("vollstaendig") and not s.get("fehler")]
    if not abzuege:
        print()
        print("KEIN vollstaendiger Abzug vorhanden. Erst sichern:")
        print("    python sicherung.py")
        print("Loeschen ist der eine Vorgang, der sich nicht zurueckdrehen")
        print("laesst.")
        return 1
    print(f"Vollstaendiger Abzug vorhanden ({len(abzuege)} Stueck).")

    store.loesche(paths.COLLECTION_NAME)
    print()
    print(f"'{paths.COLLECTION_NAME}' geloescht -- {anzahl} Abschnitte, "
          f"die doppelt lagen.")
    print("Der naechste Abzug wird etwa halb so gross.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
