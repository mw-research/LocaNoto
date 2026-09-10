"""Den vorhandenen Bestand nachtraeglich verschluesseln.

Seit der Umstellung liegt jeder NEU geschriebene Abschnitt verschluesselt
in seiner Sammlung. Was vorher da war, liegt weiter im Klartext -- und
solange das so ist, nuetzt die Verschluesselung nichts: wer das
Datenvolume kopiert, liest den Altbestand.

    python nachverschluesseln.py --pruefen    nur zaehlen
    python nachverschluesseln.py              umschreiben

Die Vektoren werden MITGELESEN und MITGESCHRIEBEN, und das ist kein
Versehen. Der naheliegende Weg -- update(ids, documents) und die
Vektoren in Ruhe lassen -- geht nicht: Chroma bettet ein Dokument, das
man ohne Vektor uebergibt, mit seinem eigenen Vorgabemodell NEU ein. Im
Test kam prompt

    Collection expecting embedding with dimension of 8, got 384

zurueck. Bei gleicher Dimension waere es nicht aufgefallen, und der
Bestand haette danach Vektoren aus einem fremden Modell getragen --
dieselben Texte, aber eine Suche, die nichts mehr findet, ohne dass
irgendwo ein Fehler steht.

Geschrieben wird deshalb ueber store.schreibe(): das verschluesselt an
derselben Stelle wie jeder andere Schreibvorgang und halbiert den Stapel
selbst, wenn er ueber HTTP zu gross wird.

Wiederholbar: was schon verschluesselt ist, wird uebergangen. Ein
abgebrochener Lauf laesst sich einfach neu starten.

Umgeschrieben werden Abschnittstext UND Dateiname. Der Name bekommt
dabei eine bestimmte Kennung (datei_id) an die Seite, damit Loeschen,
Verschieben und die Doppelerkennung weiter ueber Gleichheit filtern
koennen -- verschluesselt allein waere er dafuer unbrauchbar.

WAS ES NICHT TUT: die Vektoren bleiben lesbar (sonst gaebe es keine
Suche), und der Stichwortindex
traegt den Text weiterhin im Klartext -- er ist ableitbar und gehoert
auf containerlokalen Speicher, siehe LOCANOTO_INDEX. was_sieht_die_platte.py
sagt nach dem Lauf, wo man steht.
"""
import sys

import paths
import raumschluessel
import store

# Wie viele Abschnitte je Griff. Mit Vektoren haengt an jedem ein
# Tausenderfeld; store.schreibe halbiert bei Bedarf nach.
STAPEL = 500


def _name_offen(meta):
    """Steht der Dateiname noch im Klartext in den Metadaten?"""
    if not meta:
        return False
    name = meta.get("file_name")
    return bool(name) and not raumschluessel.ist_verschluesselt(name)


def _sammlungen():
    """[(raum, sammlung)] ueber alle Raumsammlungen."""
    aus = []
    for name in sorted(store.namen()):
        if not name.startswith(store.VORSILBE_RAUM):
            continue
        sml = store.sammlung(name, anlegen=False)
        if sml is not None:
            aus.append((name[len(store.VORSILBE_RAUM):], sml))
    return aus


def main():
    nur_pruefen = "--pruefen" in sys.argv
    paths.bootstrap()

    if not raumschluessel.verfuegbar():
        print("Keine Verschluesselung verfuegbar -- das Paket cryptography "
              "fehlt oder es gibt keinen Installationsschluessel. Ohne den "
              "waere ein Lauf hier folgenlos.")
        return 1

    paare = _sammlungen()
    if not paare:
        print("Keine Raumsammlungen gefunden.")
        return 0

    print(f"{len(paare)} Raeume: {', '.join(k for k, _s in paare)}")
    print(f"Ablage: {store.beschreibung()}")
    print()

    gesamt_offen = gesamt_fertig = 0
    for raum, sml in paare:
        try:
            anzahl = sml.count()
        except Exception as e:
            print(f"  [!] {raum}: nicht lesbar ({e})")
            continue

        offen = fertig = gelesen = 0
        while gelesen < anzahl:
            felder = (["documents", "metadatas"] if nur_pruefen
                      else ["documents", "metadatas", "embeddings"])
            b = store.hole(sml, store.VORSILBE_RAUM + raum,
                           include=felder, limit=STAPEL, offset=gelesen)
            ids = b.get("ids") or []
            if not ids:
                break
            dokumente = b.get("documents") or []
            metas = b.get("metadatas") or []
            vektoren = b.get("embeddings")

            # Nur die noch offenen. Ein Stapel, in dem nichts zu tun ist,
            # soll gar nicht erst geschrieben werden.
            # Offen ist ein Abschnitt, wenn SEIN TEXT oder SEIN
            # DATEINAME noch im Klartext steht. Beides wandert im selben
            # Schreibvorgang; store.schreibe erledigt es.
            zu_tun = [i for i, d in enumerate(dokumente)
                      if (d and not raumschluessel.ist_verschluesselt(d))
                      or _name_offen(metas[i] if i < len(metas) else None)]
            fertig += len(ids) - len(zu_tun)
            offen += len(zu_tun)

            if zu_tun and not nur_pruefen:
                if vektoren is None or len(vektoren) != len(ids):
                    print(f"  [!] {raum}: die Sammlung gibt keine Vektoren "
                          f"heraus. Ohne sie waere das Umschreiben ein "
                          f"Neueinlesen -- abgebrochen.")
                    return 1
                # Klartext uebergeben: store.schreibe verschluesselt an
                # derselben Stelle wie jeder andere Schreibvorgang.
                store.schreibe(
                    sml,
                    [ids[i] for i in zu_tun],
                    documents=[dokumente[i] for i in zu_tun],
                    metadatas=[metas[i] if i < len(metas) else {}
                               for i in zu_tun],
                    embeddings=[vektoren[i] for i in zu_tun])
            gelesen += len(ids)
            if anzahl > 5000:
                print(f"    {raum}: {gelesen}/{anzahl}", end="\r")

        if anzahl > 5000:
            print(" " * 60, end="\r")
        marke = "zu tun" if nur_pruefen else "umgeschrieben"
        print(f"  {raum:<28} {anzahl:>7} Abschnitte, "
              f"{fertig:>7} schon verschluesselt, {offen:>7} {marke}")
        gesamt_offen += offen
        gesamt_fertig += fertig

    print()
    if nur_pruefen:
        print(f"--pruefen: {gesamt_offen} Abschnitte liegen im Klartext, "
              f"{gesamt_fertig} sind verschluesselt. Nichts geschrieben.")
        if gesamt_offen:
            print("Umschreiben: python nachverschluesseln.py")
        return 0

    print(f"{gesamt_offen} Abschnitte umgeschrieben, {gesamt_fertig} waren "
          f"es schon.")
    print()
    print("Die Vektoren bleiben lesbar, die Dateinamen in den Metadaten "
          "ebenso,")
    print("und der Stichwortindex traegt den Text weiter im Klartext.")
    print("Wo du stehst: python was_sieht_die_platte.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
