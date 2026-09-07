"""Benutzerverwaltung im Terminal -- nur fuer angemeldete Verwalter.

Dasselbe, was die Oberflaeche unter "Benutzer verwalten" anbietet, fuer den
Fall, dass niemand mehr hineinkommt: ein vergessenes Passwort, eine
Benutzerdatei, die von Hand geaendert wurde.

Alle Aenderungen laufen durch benutzer.py und stehen damit im Protokoll
(data/benutzer.log). Das Protokoll ist verkettet -- wer eine Zeile
entfernt, bricht die Kette, und die Pruefung sagt, an welcher Stelle.
"""
import getpass
import sys

import benutzer
import paths


def anmelden():
    if not benutzer.namen():
        print("Noch kein Benutzer angelegt. Erst 'python create_user.py'.")
        return None
    for versuch in range(3):
        name = input("Verwalter-Kennung: ").strip().lower()
        passwort = getpass.getpass("Passwort: ")
        if benutzer.pruefe(name, passwort) and benutzer.ist_admin(name):
            return name
        print(f"   Anmeldung fehlgeschlagen ({versuch + 1}/3).")
    return None


def zeige_lage():
    zustand = benutzer.zustand()
    offen = benutzer.ungueltige()
    print(f"\nBenutzerdatei: {zustand}")
    if zustand == benutzer.UNSIGNIERT:
        print("  Aus der Zeit vor den Signaturen. Punkt 5 signiert sie.")
    if offen:
        print(f"  Gesperrt, weil ohne gueltige Signatur: "
              f"{', '.join(offen)}")
    for name in benutzer.namen():
        e = benutzer.eintrag(name) or {}
        marke = "" if e.get("_gueltig", True) else "  [gesperrt]"
        print(f"  {name:<20} {e.get('rolle', '?'):<8}"
              f"{marke}")
    ok, zeilen = benutzer.protokoll_pruefen()
    print(f"Protokoll: {zeilen} Zeilen, Kette "
          + ("in Ordnung" if ok else f"GEBROCHEN ab Zeile {zeilen}"))


def frage_passwort():
    p = getpass.getpass(
        f"Passwort (mindestens {benutzer.MIN_PASSWORT} Zeichen): ")
    if p != getpass.getpass("Passwort wiederholen: "):
        print("Die Eingaben stimmen nicht ueberein.")
        return None
    return p


def main():
    paths.bootstrap()
    print("=== LocaNoto Benutzerverwaltung ===")
    von = anmelden()
    if von is None:
        print("Abgebrochen.")
        return 1
    print(f"Angemeldet als '{von}'.")

    while True:
        zeige_lage()
        print("\n1: Benutzer anlegen")
        print("2: Passwort aendern")
        print("3: Rolle aendern")
        print("4: Benutzer loeschen")
        print("5: Benutzerdatei neu signieren")
        print("6: Protokoll ansehen")
        print("7: Beenden")
        wahl = input("\nWas moechtest du tun? ").strip()

        if wahl == "1":
            name = input("Kennung: ").strip().lower()
            rolle = (input("Rolle [nutzer/admin] (nutzer): ").strip().lower()
                     or "nutzer")
            p = frage_passwort()
            if p is None:
                continue
            ok, meldung = benutzer.anlege(name, p, rolle, von=von)

        elif wahl == "2":
            name = input("Kennung: ").strip().lower()
            p = frage_passwort()
            if p is None:
                continue
            ok, meldung = benutzer.passwort_setzen(name, p, von=von)

        elif wahl == "3":
            name = input("Kennung: ").strip().lower()
            rolle = input("Neue Rolle [nutzer/admin]: ").strip().lower()
            ok, meldung = benutzer.rolle_setzen(name, rolle, von=von)

        elif wahl == "4":
            name = input("Kennung: ").strip().lower()
            if input(f"'{name}' wirklich loeschen? (j/n): ").strip().lower() != "j":
                continue
            ok, meldung = benutzer.loesche(name, von=von)

        elif wahl == "5":
            # Ausdruecklich und mit Nachfrage: neu signieren heisst, alles
            # was gerade in der Datei steht fuer richtig zu erklaeren --
            # auch einen Eintrag, den niemand ueber die Anwendung angelegt
            # hat.
            offen = benutzer.ungueltige()
            if offen:
                print(f"\n[!] Damit gelten diese Eintraege als bestaetigt "
                      f"und koennen sich anmelden: {', '.join(offen)}")
                print("    Wer sie nicht kennt, sollte sie vorher loeschen.")
            if input("Neu signieren? (j/n): ").strip().lower() != "j":
                continue
            ok, meldung = benutzer.neu_signieren(von=von)

        elif wahl == "6":
            for e in benutzer.protokoll(letzte=50):
                print(f"  {e.get('zeit','?')} {e.get('aktion',''):<14}"
                      f"{e.get('ziel',''):<18} von={e.get('von','')} "
                      f"{e.get('hinweis','')}")
            continue

        elif wahl == "7":
            return 0

        else:
            continue

        print(("[ok] " if ok else "[!] ") + meldung)


if __name__ == "__main__":
    sys.exit(main())
