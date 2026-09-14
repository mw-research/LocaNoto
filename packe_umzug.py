"""Packt den Bestand einer bestehenden Installation fuer den Umzug.

    python packe_umzug.py /pfad/zur/alten/installation

Erzeugt daneben zwei Dateien: umzug-konfig.zip und umzug-daten.zip.

WAS EINE SICHERUNG NICHT ENTHAELT -- deshalb gibt es dieses Skript.
sicherung.py schreibt die Vektoren und die Raumverwaltung, mehr nicht.
Der Installationsschluessel bleibt absichtlich draussen, weil er in
eine andere Aufbewahrung gehoert als die Daten, die er lesbar macht.
Chats, Dokumente, Benutzer und Token sind ebenfalls nicht dabei.

Fuer einen Umzug braucht es aber alles. Vor allem den Schluessel:

    OHNE config/schluessel.key IST ALLES MITGEBRACHTE UNLESBAR.

Und zwar endgueltig. Die Chats sind damit verschluesselt, die
Raumschluessel sind damit verpackt, und die Raumschluessel sind Zufall
-- aus nichts wiederherstellbar.

NICHT MITGENOMMEN wird, was sich ableiten laesst: der Chroma-Ordner,
der Stichwortindex, der Listenkatalog. Der Chroma-Ordner kaeme aus
einem laufenden Betrieb ohnehin moeglicherweise auf halbem Stand --
deshalb geht der Bestand ueber eine frische Sicherung, die in
data/sicherungen liegt und mitwandert.
"""
import io
import os
import sys
import zipfile

ABLEITBAR = {"chroma_db", "keyword_index.sqlite3", "tabellen_katalog.json"}


def packe(wurzel, ziel, ueberspringen=()):
    n, bytes_ = 0, 0
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        for pfad, ordner, dateien in os.walk(wurzel):
            ordner[:] = [o for o in ordner if o not in ueberspringen]
            for d in dateien:
                if d in ueberspringen:
                    continue
                voll = os.path.join(pfad, d)
                z.write(voll, os.path.relpath(voll, wurzel))
                n += 1
                bytes_ += os.path.getsize(voll)
    return n, bytes_


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    alt = os.path.abspath(sys.argv[1])
    konfig = os.path.join(alt, "config")
    daten = os.path.join(alt, "data")
    for p in (konfig, daten):
        if not os.path.isdir(p):
            print(f"Nicht gefunden: {p}")
            return 2

    schluessel = os.path.join(konfig, "schluessel.key")
    if not os.path.exists(schluessel):
        # Kein Abbruch: er kann als Umgebungsvariable gesetzt sein. Aber
        # gesagt werden muss es, denn ohne ihn ist der Umzug wertlos und
        # das merkt man erst am Ziel.
        print("[!] config/schluessel.key fehlt. Steht der Schluessel in "
              "der Umgebung (LOCANOTO_SCHLUESSEL)? Ohne ihn ist alles "
              "Mitgebrachte unlesbar.")
        print()

    hier = os.getcwd()
    n1, b1 = packe(konfig, os.path.join(hier, "umzug-konfig.zip"))
    print(f"umzug-konfig.zip   {n1:>6} Dateien  {b1/1e6:>8.1f} MB")
    n2, b2 = packe(daten, os.path.join(hier, "umzug-daten.zip"), ABLEITBAR)
    print(f"umzug-daten.zip    {n2:>6} Dateien  {b2/1e6:>8.1f} MB")
    print()

    # Was drin ist, benannt -- damit am Ziel geprueft werden kann, ob
    # etwas fehlt, statt es zu hoffen.
    with zipfile.ZipFile(os.path.join(hier, "umzug-konfig.zip")) as z:
        namen = z.namelist()
    for n in ("schluessel.key", "raumschluessel.json", "users.json",
              "raeume.json", "tokens.json"):
        print(f"  {'ja ' if n in namen else 'NEIN'}  config/{n}")
    with zipfile.ZipFile(os.path.join(hier, "umzug-daten.zip")) as z:
        namen = z.namelist()
    for n, was in (("chats", "Chatverlaeufe"),
                   ("dokumente", "Dokumente"),
                   ("sicherungen", "Sicherungen (die Vektoren!)"),
                   ("tabellen", "Listen")):
        anzahl = sum(1 for x in namen if x.replace("\\\\", "/").startswith(n + "/"))
        print(f"  {'ja ' if anzahl else 'NEIN'}  data/{n:<14} {anzahl} Dateien"
              f"   {was}")
    print()
    if not any(x.replace("\\\\", "/").startswith("sicherungen/") for x in namen):
        print("[!] Keine Sicherung dabei. Auf der alten Installation erst")
        print("    'python sicherung.py' laufen lassen -- sonst kommen die")
        print("    Vektoren nicht mit und der Bestand muesste neu")
        print("    eingelesen werden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
