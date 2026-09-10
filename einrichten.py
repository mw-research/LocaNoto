"""Von null auf lauffaehig -- ein Lauf, der sagt, was er tut.

Gedacht fuer den ersten Start einer frischen Installation:

    docker compose --profile owncloud up -d
    docker compose exec -T locanoto_bot python einrichten.py

Der Reihe nach:

    1. Warten, bis ownCloud antwortet. Beim ersten Start richtet es sich
       selbst ein und braucht dafuer eine Weile -- ohne Warten liefe
       Schritt 3 in einen Fehler, der wie ein Konfigurationsproblem
       aussieht und keins ist.
    2. Den Installationsschluessel erzeugen, falls es keinen gibt.
    3. Den ersten Verwalter anlegen -- in LocaNoto und in ownCloud.
    4. Den Ordnerbaum in ownCloud anlegen und freigeben.
    5. Die Sicherheitslage zeigen und sagen, was der Betreiber noch tun
       muss.

    Die Reihenfolge von 3 und 4 ist keine Geschmacksfrage: der
    gemeinsame Ordner wird an ALLE Nutzer freigegeben. Legt man ihn an,
    bevor es einen gibt, wird er an niemanden freigegeben -- und der
    Lauf meldet trotzdem Erfolg.

WIEDERHOLBAR. Was schon steht, bleibt: ein vorhandener Schluessel wird
NIE ersetzt (das machte alles Bisherige unlesbar), ein vorhandener
Nutzer nicht ueberschrieben, vorhandene Ordner bleiben. Ein
abgebrochener Lauf laesst sich einfach neu starten.

--ohne-owncloud laesst die Schritte 1 und 3 weg. Fuer eine Installation,
die ownCloud nicht mitbringt oder ein vorhandenes im Haus benutzt.
"""
import argparse
import getpass
import os
import sys
import time

import paths


def sagt(text=""):
    print(text, flush=True)


def schritt(nr, was):
    sagt()
    sagt(f"--- {nr}. {was} ---")


def warte_auf_owncloud(sekunden=300):
    """Wartet, bis die Instanz antwortet. True, wenn sie es tut."""
    import owncloud
    if not owncloud.eingerichtet():
        sagt("  ownCloud ist in der .env nicht eingetragen "
             "(OWNCLOUD_URL, OWNCLOUD_USER, OWNCLOUD_PASSWORT).")
        return False
    sagt(f"  Warte auf {owncloud.URL} ...")
    t0 = time.time()
    letzter = ""
    while time.time() - t0 < sekunden:
        try:
            ok, meldung = owncloud.pruefe()
            if ok:
                sagt(f"  Erreichbar nach {time.time() - t0:.0f}s: {meldung}")
                return True
            letzter = meldung
        except Exception as e:
            letzter = f"{type(e).__name__}: {e}"
        time.sleep(5)
    sagt(f"  Nach {sekunden}s nicht erreichbar. Zuletzt: {letzter}")
    sagt("  Beim allerersten Start richtet ownCloud sich selbst ein; das")
    sagt("  dauert. 'docker compose logs -f owncloud' zeigt, wie weit es")
    sagt("  ist. Danach diesen Lauf einfach wiederholen.")
    return False


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ohne-owncloud", action="store_true",
                   help="Ordner und Konten in ownCloud nicht anlegen")
    p.add_argument("--verwalter", default="",
                   help="Kennung des ersten Verwalters")
    p.add_argument("--passwort", default="",
                   help="sein Passwort. Ohne Angabe wird gefragt; in "
                        "einem Skript besser ueber die Umgebung, damit "
                        "es nicht in der Befehlsgeschichte steht")
    p.add_argument("--warten", type=int, default=300,
                   help="Sekunden auf ownCloud (Vorgabe 300)")
    args = p.parse_args()

    paths.bootstrap()
    sagt("=" * 66)
    sagt("LOCANOTO EINRICHTEN")
    sagt("=" * 66)

    # --- 1. ownCloud ---
    oc_da = False
    if not args.ohne_owncloud:
        schritt(1, "ownCloud")
        oc_da = warte_auf_owncloud(args.warten)
        if not oc_da:
            sagt("  Weiter ohne ownCloud -- alles andere wird trotzdem "
                 "eingerichtet, und der Rest laesst sich spaeter in der "
                 "Oberflaeche nachholen.")
    else:
        schritt(1, "ownCloud uebersprungen (--ohne-owncloud)")

    # --- 2. Schluessel ---
    schritt(2, "Installationsschluessel")
    import geheim
    # VOR dem Aufruf nachsehen: zustand() erzeugt den Schluessel, wenn es
    # keinen gibt. Ueber das Aenderungsdatum zu gehen war falsch -- ein
    # zweiter Lauf in derselben Minute meldete ihn wieder als neu, und
    # eine Aufforderung, die auch beim zehnten Mal kommt, liest niemand
    # mehr.
    gab_es_schon = os.path.exists(geheim.SCHLUESSEL_DATEI)
    zustand, meldung = geheim.zustand()
    if zustand == "unlesbar":
        sagt(f"  ABBRUCH: {meldung}")
        return 2
    sagt(f"  {meldung}")
    neu_erzeugt = (zustand == "ok" and not gab_es_schon
                   and os.path.exists(geheim.SCHLUESSEL_DATEI))
    if neu_erzeugt:
        sagt("  Neu erzeugt. SICHERE IHN JETZT -- ohne ihn sind alle")
        sagt("  Chatverlaeufe und der verschluesselte Bestand endgueltig")
        sagt("  unlesbar, ohne eine einzige Fehlermeldung.")

    import benutzer
    import raeume

    # --- 3. Erster Verwalter ---
    schritt(3, "Erster Verwalter")
    vorhandene = benutzer.namen()
    if vorhandene:
        sagt(f"  Es gibt schon {len(vorhandene)} Zugaenge "
             f"({', '.join(vorhandene[:5])}). Kein neuer angelegt.")
    else:
        name = args.verwalter.strip() or os.getenv(
            "LOCANOTO_ERSTER_VERWALTER", "").strip()
        passwort = args.passwort or os.getenv("LOCANOTO_ERSTES_PASSWORT", "")
        if not name:
            try:
                name = input("  Kennung des ersten Verwalters: ").strip()
            except EOFError:
                name = ""
        if name and not passwort:
            try:
                passwort = getpass.getpass("  Passwort: ")
            except (EOFError, OSError):
                passwort = ""
        if not name or not passwort:
            sagt("  Uebersprungen -- ohne Kennung und Passwort geht es "
                 "nicht. Nachholen: python create_user.py")
        else:
            ok, meldung = benutzer.anlege(name, passwort, "admin",
                                          von="einrichtung")
            sagt(f"  {'+' if ok else '!'} {meldung}")
            if ok and oc_da:
                import owncloud
                b = owncloud.richte_nutzer_ein(name, passwort, name)
                for s in b["schritte"]:
                    sagt(f"      {s}")
                for f in b["fehler"]:
                    sagt(f"      [!] {f}")

    # Der Baum ZULETZT, und das ist keine Kosmetik: der
    # allgemeine Ordner wird mit allen Nutzern geteilt, und
    # solange es keinen gibt, teilt er sich mit niemandem. Vor
    # dem Anlegen des Verwalters ausgefuehrt, waere der erste
    # Lauf unvollstaendig und erst der zweite richtig -- eine
    # Einrichtung, die man zweimal starten muss, ist keine.
    if oc_da:
        schritt(4, "Ordner und Freigaben in ownCloud")
        import owncloud
        for raum in sorted(set(list(raeume.liste()) + [raeume.ALLGEMEIN])):
            b = owncloud.richte_raum_ein(raum)
            zeichen = "!" if b["fehler"] else "+"
            sagt(f"  [{zeichen}] {raum}: "
                 + (" · ".join(b["schritte"]) if b["schritte"]
                    else str(b["fehler"][:1])))
    else:
        schritt(4, "Ordnerbaum uebersprungen")
        sagt(f"  Ohne ownCloud liegt derselbe Baum lokal unter "
             f"{paths.DOCS_DIR} -- gleiche Namen, gleiche Aufteilung, "
             f"nur ohne Freigaben.")

    # --- 5. Lage ---
    schritt(5, "Sicherheitslage")
    import sicherheit
    offen = []
    for name_, ok, text in sicherheit.lage():
        sagt(f"  [{'ok' if ok else '!!'}] {name_}")
        if not ok:
            offen.append((name_, text))
    if offen:
        sagt()
        sagt("  Offen, und in dieser Reihenfolge zu erledigen:")
        for i, (name_, text) in enumerate(offen, 1):
            sagt(f"    {i}. {name_}")
            for zeile in _umbrechen(text, 62):
                sagt(f"       {zeile}")

    sagt()
    sagt("=" * 66)
    sagt(f"Oberflaeche:  http://localhost:{os.getenv('APP_PORT', '8501')}")
    if oc_da:
        import owncloud
        sagt(f"ownCloud:     {owncloud.URL}")
    sagt()
    sagt("Als naechstes:")
    sagt("  * Den Installationsschluessel wegsichern (siehe oben).")
    sagt("  * Dokumente nach data/dokumente/ legen und einlesen:")
    sagt("      docker compose exec locanoto_bot python ingest.py")
    sagt("  * Den Stand jederzeit nachsehen:")
    sagt("      docker compose exec -T locanoto_bot python "
         "was_sieht_die_platte.py")
    return 0


def _umbrechen(text, breite):
    zeilen, zeile = [], ""
    for wort in str(text).split():
        if len(zeile) + len(wort) + 1 > breite:
            zeilen.append(zeile)
            zeile = wort
        else:
            zeile = (zeile + " " + wort).strip()
    if zeile:
        zeilen.append(zeile)
    return zeilen


if __name__ == "__main__":
    sys.exit(main())
