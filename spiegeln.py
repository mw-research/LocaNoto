"""Vorhandene Dokumente nach ownCloud hochladen -- python spiegeln.py

    python spiegeln.py --pruefen        nur zeigen, was hochginge
    python spiegeln.py                  hochladen
    python spiegeln.py einkauf          nur dieser Raum
    python spiegeln.py --ueberschreiben gleichnamige dort ersetzen

WOFUER. Der Abgleich holt aus ownCloud herunter. Der umgekehrte Weg
fehlte, und er wird an genau zwei Stellen gebraucht:

  1. NACH EINEM UMZUG. Der Bestand kommt ueber die Baender, ownCloud
     ist frisch und leer. Die Dokumente sind da, die Quellenansicht
     funktioniert -- aber in der Ablage, die die Leute oeffnen, liegt
     nichts.

  2. NACH DEM NACHRUESTEN. Eine Installation, die vorher ohne
     ownCloud lief, hat ihren ganzen Bestand nur lokal.

WARUM DAS NICHT EGAL IST. Der Zweck der Anbindung ist, dass alles
Gespeicherte auf entkoppeltem Speicher liegt. Dokumente, die nur im
Datenband liegen, sind genau das, was die Anbindung vermeiden soll.

UND WARUM DER STAND MITGESCHRIEBEN WIRD. Der Abgleich fuehrt Buch
darueber, was er aus ownCloud geholt hat, und loescht lokal, was dort
nicht mehr auftaucht -- samt Abschnitten. Nach einem Umzug ist das
eine geladene Waffe: die mitgebrachte Standsdatei nennt Dateien, die
in der NEUEN ownCloud nie lagen, und der naechste naechtliche Lauf
haelt jede davon fuer entfallen.

Deshalb schreibt dieses Skript den Stand am Ende neu, aus dem, was
danach wirklich dort liegt. Wer nur hochlaedt und das vergisst, hat
die Dateien in ownCloud und verliert sie in der Nacht darauf.
"""
import argparse
import os
import sys

import paths
import raeume


def _fremde_ordner(raum):
    """Die Ablageordner der ANDEREN Raeume, absolut.

    Gebraucht nur fuer den allgemeinen Raum: der liegt im Wurzelbereich
    von data/dokumente, und darunter liegen die Unterordner der uebrigen
    Raeume. Ohne diese Liste wuerde das Spiegeln des allgemeinen Raums
    die Dokumente aller anderen gleich mit nach oben laden -- in seinen
    Ordner, fuer seine Mitglieder sichtbar.

    Das waere kein Schoenheitsfehler, sondern ein Rechtebruch: der
    allgemeine Raum ist fuer alle sichtbar, ein Abteilungsraum nicht.
    """
    import raeume
    aus = set()
    for r in raeume.liste():
        if r == raeume.ALLGEMEIN:
            continue
        aus.add(os.path.normpath(os.path.join(paths.DOCS_DIR,
                                              paths.sicherer_teil(r))))
    return aus


def _dateien(wurzel, ausser=()):
    """[(vollpfad, relativ)] unterhalb von wurzel, ohne die Ordner in ausser."""
    ausser = {os.path.normpath(a) for a in ausser}
    aus = []
    for pfad, unter, dateien in os.walk(wurzel):
        unter[:] = [u for u in unter
                    if os.path.normpath(os.path.join(pfad, u)) not in ausser]
        for d in dateien:
            if d.startswith("."):
                continue
            voll = os.path.join(pfad, d)
            aus.append((voll, os.path.relpath(voll, wurzel).replace("\\", "/")))
    return sorted(aus)


def spiegle(raum, ueberschreiben=False, pruefen=False, sagen=print):
    """(hochgeladen, uebersprungen, fehler)."""
    import owncloud

    # zuordnung_wirksam und NICHT ordner_fuer: das kennt nur von Hand
    # eingetragene Zuordnungen. Der Standardbaum -- den einrichten.py
    # anlegt und in den jeder Upload schreibt -- kommt dort nicht vor,
    # und ohne Handzuordnung waere jeder Raum uebersprungen worden.
    ziel = owncloud.zuordnung_wirksam().get(raum)
    if not ziel:
        sagen(f"  {raum}: kein Ordner zugeordnet -- uebersprungen.")
        return 0, 0, 0

    quelle = owncloud.ablage(raum)
    # Im Wurzelbereich -- also beim allgemeinen Raum -- liegen die
    # Ordner der anderen Raeume daneben. Sie gehoeren nicht mit hoch.
    import raeume as _r
    dateien = _dateien(quelle,
                       _fremde_ordner(raum) if raum == _r.ALLGEMEIN else ())
    if not dateien:
        sagen(f"  {raum}: nichts lokal.")
        return 0, 0, 0

    sagen(f"  {raum}: {len(dateien)} Datei(en) -> {ziel}")
    if pruefen:
        for _v, rel in dateien[:20]:
            sagen(f"      {rel}")
        if len(dateien) > 20:
            sagen(f"      ... und {len(dateien) - 20} weitere")
        return 0, len(dateien), 0

    hoch = uebersprungen = fehler = 0
    for n, (voll, rel) in enumerate(dateien, start=1):
        fern = ziel.rstrip("/") + "/" + rel
        ok, meldung = owncloud.lege_ab(voll, fern,
                                       ueberschreiben=ueberschreiben)
        if ok:
            hoch += 1
        elif "liegt dort schon" in meldung:
            # Kein Fehler: dort liegt bereits etwas dieses Namens. Ob
            # es dasselbe ist, weiss hier niemand -- und blind zu
            # ueberschreiben, was jemand von Hand abgelegt hat, waere
            # schlimmer als es stehen zu lassen.
            uebersprungen += 1
        else:
            fehler += 1
            sagen(f"      [!] {rel}: {meldung}")
        if n % 25 == 0:
            sagen(f"      {n}/{len(dateien)}")
    return hoch, uebersprungen, fehler


def stand_neu(raum, sagen=print):
    """Schreibt die Standsdatei aus dem, was jetzt in ownCloud liegt.

    Ohne das haelt der naechste Abgleich alles fuer entfallen, was in
    der mitgebrachten Standsdatei steht und dort nie lag -- und
    entfernt es lokal samt Abschnitten.
    """
    import owncloud
    import time

    ordner = owncloud.zuordnung_wirksam().get(raum)
    if not ordner:
        return 0
    fern = {d["rel"]: d for d in owncloud.dateien(ordner)}
    stand = {rel: {"etag": d["etag"], "groesse": d["groesse"],
                   "geaendert": d["geaendert"],
                   "geholt": time.strftime("%Y-%m-%dT%H:%M:%S")}
             for rel, d in fern.items()}
    owncloud._stand_schreiben(raum, stand)
    sagen(f"  {raum}: Stand neu geschrieben, {len(stand)} Eintraege.")
    return len(stand)


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("raum", nargs="?", default="",
                   help="nur diesen Raum (ohne Angabe: alle zugeordneten)")
    p.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, nichts hochladen")
    p.add_argument("--ueberschreiben", action="store_true",
                   help="gleichnamige Dateien in ownCloud ersetzen")
    args = p.parse_args()

    paths.bootstrap()
    import owncloud
    if not owncloud.eingerichtet():
        print("ownCloud ist nicht eingerichtet (OWNCLOUD_URL, "
              "OWNCLOUD_USER, OWNCLOUD_PASSWORT).")
        return 2

    ok, meldung = owncloud.pruefe()
    print(meldung)
    if not ok:
        return 2

    raeume_ = ([args.raum] if args.raum
               else sorted(owncloud.zuordnung_wirksam()))
    if not raeume_:
        print("Kein Raum hat einen ownCloud-Ordner zugeordnet.")
        return 2

    print()
    print("=" * 62)
    print("PRUEFLAUF -- es wird nichts hochgeladen." if args.pruefen
          else "SPIEGELN nach ownCloud")
    print("=" * 62)

    gesamt = [0, 0, 0]
    for raum in raeume_:
        if raum not in raeume.liste():
            print(f"  {raum}: kein solcher Raum -- uebersprungen.")
            continue
        h, u, f = spiegle(raum, args.ueberschreiben, args.pruefen)
        gesamt[0] += h
        gesamt[1] += u
        gesamt[2] += f

    print()
    if args.pruefen:
        print(f"{gesamt[1]} Datei(en) wuerden hochgeladen.")
        print("Ohne --pruefen wird es getan.")
        return 0

    print(f"{gesamt[0]} hochgeladen, {gesamt[1]} uebersprungen "
          f"(lagen schon dort), {gesamt[2]} Fehler.")
    print()
    print("Stand fuer den Abgleich:")
    for raum in raeume_:
        if raum in raeume.liste():
            stand_neu(raum)
    print()
    print("Der naechste Abgleich sieht diese Dateien damit als "
          "unveraendert und nicht als entfallen.")
    return 1 if gesamt[2] else 0


if __name__ == "__main__":
    sys.exit(main())
