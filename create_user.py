"""Ersten Benutzer anlegen -- und danach nur noch als Verwalter.

Vorher legte dieses Skript ohne jede Nachfrage einen Zugang an. Wer es
starten konnte, war drin, und nichts hielt es fest.

Jetzt gilt: solange es keinen Benutzer gibt, ist der erste Aufruf die
Einrichtung -- er legt einen Verwalter an, denn es gibt noch nichts zu
schuetzen. Ab dem zweiten Benutzer verlangt jeder Aufruf die Anmeldung
eines vorhandenen Verwalters, und jede Aenderung steht im Protokoll.

Die Grenze bleibt, was sie ist: wer Dateizugriff hat, kommt an den
Schluessel und damit an alles. Siehe benutzer.py. Was dieses Skript
leistet, ist den gewoehnlichen Weg zu verschliessen und den
ungewoehnlichen sichtbar zu machen.
"""
import getpass
import sys

import benutzer
import paths


def anmelden():
    """Kennung eines angemeldeten Verwalters, oder None.

    Bei leerer Benutzerdatei gibt es niemanden zum Anmelden -- dann ist der
    Aufruf die Einrichtung.
    """
    if not benutzer.namen():
        return "einrichtung"

    for versuch in range(3):
        name = input("Verwalter-Kennung: ").strip().lower()
        passwort = getpass.getpass("Passwort: ")
        if benutzer.pruefe(name, passwort) and benutzer.ist_admin(name):
            return name
        # Nicht sagen, was falsch war. "Kennung unbekannt" und "kein
        # Verwalter" sind Auskuenfte, die man nicht verschenken muss.
        print(f"   Anmeldung fehlgeschlagen ({versuch + 1}/3).")
    return None


def main():
    paths.bootstrap()
    print("--- LocaNoto: Benutzer anlegen ---")

    zustand = benutzer.zustand()
    if zustand == benutzer.UNSIGNIERT:
        print("\n[!] Die Benutzerdatei stammt aus der Zeit vor den "
              "Signaturen.")
        print("    Sie wird beim Speichern signiert. Danach kann ein von "
              "Hand")
        print("    eingetragener Benutzer sich nicht mehr anmelden.")
    elif zustand == benutzer.MANIPULIERT:
        offen = benutzer.ungueltige()
        print("\n[!] Die Benutzerdatei wurde ausserhalb der Anwendung "
              "geaendert.")
        if offen:
            print(f"    Ohne gueltige Signatur und damit gesperrt: "
                  f"{', '.join(offen)}")
        print("    Mit 'python manage_users.py' pruefen und, wenn gewollt, "
              "neu signieren.")

    von = anmelden()
    if von is None:
        print("Abgebrochen.")
        return 1

    if von == "einrichtung":
        print("\nNoch kein Benutzer vorhanden -- dieser wird Verwalter.")
        rolle = "admin"
    else:
        print(f"\nAngemeldet als '{von}'.")
        rolle = (input("Rolle [nutzer/admin] (nutzer): ").strip().lower()
                 or "nutzer")

    name = input("Neue Kennung: ").strip().lower()
    passwort = getpass.getpass(
        f"Passwort (mindestens {benutzer.MIN_PASSWORT} Zeichen): ")
    if passwort != getpass.getpass("Passwort wiederholen: "):
        print("Die Eingaben stimmen nicht ueberein.")
        return 1

    ok, meldung = benutzer.anlege(name, passwort, rolle, von=von)
    print(("[ok] " if ok else "[!] ") + meldung)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
