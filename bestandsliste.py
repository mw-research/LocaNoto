"""Was liegt in dieser Installation? -- python bestandsliste.py

Gedacht fuer einen Umzug: VORHER im alten Container laufen lassen,
NACHHER im neuen Pod, und die beiden Ausgaben nebeneinanderlegen.

Ohne das ist ein Umzug eine Hoffnung. Die Anwendung startet, die
Oberflaeche sieht aus wie immer, und dass einem Raum die Haelfte seiner
Abschnitte fehlt, faellt Wochen spaeter auf -- wenn jemand etwas sucht,
das er sicher hochgeladen hat, und es nicht mehr findet. Zu dem
Zeitpunkt ist die alte Installation abgeschaltet.

Gezaehlt wird das, was sich vergleichen laesst, und sonst nichts. Keine
Inhalte, keine Dateinamen im Klartext -- eine Bestandsliste, die man
per Nachricht verschickt, soll nicht selbst zur Auskunft werden.
"""
import os
import sys

import paths


def _dimension(sammlung):
    """Wie viele Zahlen ein Vektor dieser Sammlung hat. None, wenn leer.

    Ohne Modellserver: gelesen wird ein einziger vorhandener Vektor.
    Das ist die Angabe, die beim Umzug gefehlt hat -- die Abschnitte
    kamen vollzaehlig an, und niemand fragte, ob sie zum Modell der
    neuen Installation passen.
    """
    try:
        res = sammlung.get(limit=1, include=["embeddings"])
    except Exception:
        return None
    # KEIN Wahrheitswert auf dem Ergebnis: Chroma liefert ein
    # numpy-Array, und dessen Wahrheitswert ist mehrdeutig. Die erste
    # Fassung schrieb "(res.get(...) or [None])[0]" und warf genau
    # daran -- und ein zu weiter Fangarm verschluckte es. Also derselbe
    # Fehler, den dieser Umbau abstellt, im Umbau selbst.
    e = res.get("embeddings")
    if e is None or len(e) == 0:
        return None
    return len(e[0])


def zaehle_ordner(pfad):
    """(Dateien, Bytes). (0, 0), wenn es ihn nicht gibt."""
    if not os.path.isdir(pfad):
        return 0, 0
    n = b = 0
    for wurzel, _u, dateien in os.walk(pfad):
        for d in dateien:
            try:
                b += os.path.getsize(os.path.join(wurzel, d))
                n += 1
            except OSError:
                pass
    return n, b


def main():
    paths.bootstrap()
    print("=" * 62)
    print("BESTANDSLISTE")
    print("=" * 62)

    # --- ABSCHNITTE JE RAUM ---
    #
    # Die Zahl, auf die es ankommt. Alles andere laesst sich am
    # Dateisystem nachzaehlen; was in den Sammlungen steht, nicht.
    print("\nAbschnitte je Raum")
    gesamt = 0
    try:
        import store
        import raeume
        namen = sorted(n for n in store.namen() if n.startswith("raum_"))
        masse = []
        if not namen:
            print("  (keine Sammlungen)")
        for name in namen:
            kennung = name[len("raum_"):]
            try:
                sml = store.sammlung(name, anlegen=False)
                n = sml.count() if sml is not None else 0
            except Exception as e:
                print(f"  {kennung:<24} FEHLER: {type(e).__name__}")
                continue
            gesamt += n
            bez = ""
            try:
                bez = raeume.bezeichnung(kennung)
            except Exception:
                pass
            # DIE DIMENSION GEHOERT DANEBEN.
            #
            # Diese Liste wird vor und nach jedem Rollout gefahren und
            # zaehlte Abschnitte. In einer Installation lagen sie mit
            # 2560 Dimensionen, waehrend das Modell 4096 liefert: jede
            # Vektorabfrage schlug fehl, die Antworten kamen weiter aus
            # dem Stichwortindex, und die Zahl stimmte an jedem Punkt.
            # Eine Zahl beweist, dass etwas liegt -- nicht, dass es
            # passt.
            masse.append((kennung, _dimension(sml)))
            print(f"  {kennung:<24} {n:>8}   {bez}")
        print(f"  {'SUMME':<24} {gesamt:>8}")

        _dims = {d for _k, d in masse if d}
        if _dims:
            print("\nDimension der Vektoren je Raum")
            for _k, _d in masse:
                print(f"  {_k:<24} {_d if _d else '(leer)'}")
            if len(_dims) > 1:
                print("\n  >>> ACHTUNG: die Raeume haben VERSCHIEDENE "
                      "Dimensionen.")
                print("      Wer aus einem anderen Bestand uebernommen "
                      "wurde, traegt die Vektoren")
                print("      seines alten Modells. Fuer diese Raeume "
                      "schlaegt JEDE Vektorabfrage")
                print("      fehl -- die Suche laeuft dann allein ueber "
                      "den Stichwortindex, und")
                print("      von aussen sieht das aus wie eine normale "
                      "Antwort.")
                print("      Abhilfe: die betroffenen Dokumente neu "
                      "einlesen.")
    except Exception as e:
        print(f"  Sammlungen nicht lesbar: {type(e).__name__}: {e}")

    # --- DATEIEN ---
    print("\nDateien")
    for was, pfad in (("Dokumente", paths.DOCS_DIR),
                      ("Chatverlaeufe", paths.CHATS_DIR),
                      ("Listen", paths.TABELLEN_DIR),
                      ("Sicherungen",
                       os.path.join(paths.DATA_DIR, "sicherungen"))):
        n, b = zaehle_ordner(pfad)
        print(f"  {was:<24} {n:>8} Dateien   {b/1e6:>9.1f} MB")

    # --- WAS DEN UMZUG ENTSCHEIDET ---
    #
    # Ohne schluessel.key ist alles Mitgebrachte unlesbar, ohne
    # raumschluessel.json ebenso -- und beide zusammen sind die Stelle,
    # an der ein Umzug still scheitert.
    print("\nKonfiguration")
    for datei in ("schluessel.key", "raumschluessel.json", "users.json",
                  "raeume.json", "tokens.json", "owncloud.json"):
        p = os.path.join(paths.CONFIG_DIR, datei)
        da = os.path.exists(p)
        gr = os.path.getsize(p) if da else 0
        print(f"  {datei:<24} {'ja' if da else 'FEHLT':>8}   {gr:>7} Byte")

    # Benutzer und Raeume als Zahl, nicht als Liste: eine
    # Bestandsliste soll sich verschicken lassen.
    try:
        import benutzer
        print(f"  {'Benutzer angelegt':<24} {len(benutzer.namen()):>8}")
    except Exception:
        pass
    try:
        import raeume
        print(f"  {'Raeume angelegt':<24} {len(raeume.liste()):>8}")
    except Exception:
        pass

    print("\nAblage:", end=" ")
    try:
        import store
        print(store.beschreibung())
    except Exception as e:
        print(f"nicht feststellbar ({type(e).__name__})")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
