"""Aus ownCloud abgleichen: Gruppen, Dokumente, Einlesen.

    python abgleich.py --pruefen              was sich geaendert hat
    python abgleich.py --pruefen einkauf      nur dieser Raum
    python abgleich.py                        holen, dann einlesen
    python abgleich.py --nur-gruppen          nur die Mitgliedschaften
    python abgleich.py --nur-holen            holen, nicht einlesen
    python abgleich.py --ohne-loeschen        entfallene Dateien behalten

Drei Dinge, in dieser Reihenfolge, und die Reihenfolge ist Absicht:

  1. GRUPPEN. Wer in welcher ownCloud-Gruppe ist, also wer die Abschnitte
     eines Raums sehen darf. Sekunden, ein Aufruf je Gruppe.
  2. DOKUMENTE. Neue und geaenderte holen, entfallene samt Abschnitten
     entfernen.
  3. EINLESEN. Vektorisieren, was neu ist.

Die Gruppen zuerst, weil sie das Billigste und das Dringendste sind: wer
aus einer Abteilung ausgeschieden ist, soll deren Unterlagen nicht mehr
finden -- und darauf soll man nicht warten muessen, bis Stunden Ingest
durch sind.

Zwei Schritte, absichtlich getrennt: das Holen dauert Sekunden, das
Einlesen Stunden. Wer nur wissen will, ob sich etwas geaendert hat, soll
nicht warten, und wer einen Ingest anstoesst, soll wissen wofuer.

--pruefen fasst nichts an. Das ist der Lauf, mit dem man eine neue
Zuordnung ueberprueft: eine falsch eingerichtete sieht sonst aus wie
"alles geloescht", und dann sind die Abschnitte schon weg.

Gedacht fuer einen Zeitplan auf dem Server, etwa naechtlich:

    0 3 * * *  docker compose exec -T locanoto_bot python abgleich.py
"""
import argparse
import os
import subprocess
import sys

import benutzer
import owncloud
import paths
import raeume


def gruppen(nur_zeigen=False):
    """Mitgliedschaften nachziehen. Anzahl der Fehler."""
    zu = owncloud.gruppen_zuordnung()
    if not zu:
        print("\nKeine Raumgruppe eingetragen -- Mitgliedschaften bleiben, "
              "wie sie in config/raeume.json stehen.")
        return 0

    print("\n=== Mitgliedschaften ===")
    for raum, gruppe in sorted(zu.items()):
        print(f"  {raum:<24} <- Gruppe '{gruppe}'")

    if nur_zeigen:
        stand = owncloud.gruppen_stand()
        alter = stand.get("alter_minuten")
        print(f"  Stand: {stand.get('aktualisiert') or 'keiner'}"
              + (f" ({alter:.0f} min alt)" if alter is not None else ""))
        return 0

    bericht = owncloud.gruppen_abgleich()
    print(f"  {bericht['meldung']}")
    for f in bericht["fehler"]:
        print(f"  [!] Gruppe '{f['gruppe']}': {f['grund']}")
    if bericht["geschrieben"]:
        for gruppe, leute in sorted(bericht["gruppen"].items()):
            print(f"      {gruppe}: {len(leute)} Mitglieder"
                  + (f" -- {', '.join(leute[:8])}" if leute else ""))
        # Die Kennungen kommen aus ownCloud und muessen zu den hier
        # angelegten passen. Tun sie es nicht, sieht alles richtig aus und
        # niemand kommt in seinen Raum -- deshalb hier nachgesehen.
        bekannt = set(benutzer.namen())
        fremd = sorted({k for leute in bericht["gruppen"].values()
                        for k in leute} - bekannt)
        if fremd:
            print(f"  Hinweis: {len(fremd)} Kennungen aus ownCloud sind "
                  f"hier nicht angelegt und wirken deshalb nicht: "
                  f"{', '.join(fremd[:10])}")
    return len(bericht["fehler"])


def zeige_plan(raum):
    """(neu, geaendert, entfallen). Gibt aus, was ein Abgleich tun wuerde."""
    ordner = owncloud.ordner_fuer(raum)
    print(f"\n=== Raum '{raum}' <- {ordner} ===")
    try:
        neu, geaendert, entfallen, unveraendert = owncloud.plane(raum)
    except Exception as e:
        print(f"  [!] {e}")
        return None
    print(f"  unveraendert: {len(unveraendert)}")
    for beschriftung, liste in (("neu", neu), ("geaendert", geaendert),
                                ("entfallen", entfallen)):
        if liste:
            print(f"  {beschriftung}: {len(liste)}")
            for rel in liste[:20]:
                print(f"      {rel}")
            if len(liste) > 20:
                print(f"      ... und {len(liste) - 20} weitere")
    if not (neu or geaendert or entfallen):
        print("  Nichts zu tun.")
    return neu, geaendert, entfallen


def einlesen(raum):
    """Startet ingest.py fuer den Ordner dieses Raums.

    Als eigener Prozess und nicht als Import: ingest.py ist ein Skript, das
    beim Laden Verbindungen aufbaut und Ausgaben schreibt. Zweimal im selben
    Prozess ausgefuehrt waere das ein Zustand, den niemand vorhergesehen
    hat.
    """
    umgebung = dict(os.environ)
    umgebung["INGEST_RAUM"] = raum
    umgebung["INGEST_ORDNER"] = owncloud.ablage(raum)
    print(f"\n--- Einlesen: Raum '{raum}' aus {umgebung['INGEST_ORDNER']} ---")
    return subprocess.call(
        [sys.executable, "-u", os.path.join(paths.BASE_DIR, "ingest.py")],
        cwd=paths.BASE_DIR, env=umgebung)


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("raum", nargs="?",
                   help="nur diesen Raum abgleichen (ohne Angabe alle "
                        "eingerichteten)")
    p.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, was sich geaendert hat")
    p.add_argument("--nur-gruppen", action="store_true",
                   help="nur die Mitgliedschaften nachziehen")
    p.add_argument("--nur-holen", action="store_true",
                   help="Dateien holen, aber nicht einlesen")
    p.add_argument("--ohne-loeschen", action="store_true",
                   help="entfallene Dateien und ihre Abschnitte behalten")
    args = p.parse_args()

    paths.bootstrap()

    ok, meldung = owncloud.pruefe()
    print(meldung)
    if not ok:
        return 1

    # Immer zuerst, auch wenn kein Ordner zugeordnet ist: Gruppen und
    # Dokumente sind zwei Zuordnungen, und die eine kann ohne die andere
    # gepflegt sein.
    fehler_gruppen = gruppen(nur_zeigen=args.pruefen)
    if args.nur_gruppen:
        return 1 if fehler_gruppen else 0

    zuordnung = owncloud.zuordnung()
    if not zuordnung:
        print(f"\nKeine Zuordnung eingerichtet. Erwartet wird "
              f"{owncloud.ZUORDNUNG} mit Eintraegen der Form")
        print('  {"raeume": {"allgemein": "/Dokumente/LocaNoto"}}')
        print("\nOder in der Oberflaeche unter 'ownCloud'.")
        return 1

    if args.raum:
        kennung = raeume.sichere_kennung(args.raum)
        if kennung not in zuordnung:
            print(f"\nFuer '{kennung}' ist kein Ordner eingerichtet. "
                  f"Vorhanden: {', '.join(sorted(zuordnung))}")
            return 1
        auswahl = [kennung]
    else:
        auswahl = sorted(zuordnung)

    if args.pruefen:
        for raum in auswahl:
            zeige_plan(raum)
        print("\n--pruefen: nichts geholt, nichts geloescht, nichts "
              "eingelesen.")
        return 0

    fehler = fehler_gruppen
    for raum in auswahl:
        plan = zeige_plan(raum)
        if plan is None:
            fehler += 1
            continue
        neu, geaendert, entfallen = plan
        if not (neu or geaendert or entfallen):
            continue

        bericht = owncloud.abgleich(
            raum, loeschen=not args.ohne_loeschen,
            fortschritt=lambda rel, n, ges: print(f"      [{n}/{ges}] {rel}"))
        print(f"  geholt: {len(bericht['geholt'])} "
              f"({bericht['bytes'] / 1e6:.1f} MB), "
              f"entfernt: {len(bericht['entfernt'])}")
        for f in bericht["fehler"]:
            print(f"  [!] {f['datei']}: {f['grund']}")
            fehler += 1

        # Die Abschnitte entfallener Dateien MUESSEN mit. Bleiben sie
        # stehen, antwortet die Anwendung weiter aus Dokumenten, die es
        # nicht mehr gibt -- und niemand sieht, woran es liegt.
        if bericht["entfernt"]:
            weg = owncloud.entferne_abschnitte(raum, bericht["entfernt"])
            print(f"  Abschnitte entfernter Dateien geloescht: {weg}")

        if bericht["geholt"] and not args.nur_holen:
            if einlesen(raum) != 0:
                print("  [!] Das Einlesen endete mit einem Fehler.")
                fehler += 1

    if args.nur_holen:
        print("\n--nur-holen: nicht eingelesen. Spaeter mit "
              "'python abgleich.py' oder ueber die Oberflaeche.")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
