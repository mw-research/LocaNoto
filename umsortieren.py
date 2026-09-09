"""Den bestehenden Bestand in Raeume umsortieren -- ohne neu zu vektorisieren.

Bis jetzt lagen alle Abschnitte in einer Sammlung, unterschieden durch die
Merkmale access und owner. Mit Raeumen entscheidet die Sammlung, wer etwas
sehen kann. Dieses Skript verschiebt die vorhandenen Abschnitte dorthin.

Wichtig: die Vektoren werden mitgenommen, nicht neu berechnet. Chroma gibt
sie mit include=["embeddings"] heraus, und collection.add() nimmt sie
entgegen. Ein Neueinlesen von 20.000 Abschnitten waere Stunden GPU-Zeit
fuer ein Ergebnis, das schon vorliegt.

Die alte Sammlung bleibt stehen. Sie ist der Rueckweg, wenn an der
Umsortierung etwas nicht stimmt, und sie kostet nur Platz. Wer sie los will,
loescht sie ausdruecklich -- in der Oberflaeche unter Raeume.

Aufruf:  python umsortieren.py [--pruefen] [--erneut]

--pruefen zaehlt nur und schreibt nichts.
--erneut  laeuft auch dann, wenn die Raeume schon existieren. Ohne das
          bricht ein zweiter Lauf ab, denn er wuerde aus der alten
          Sammlung zurueckholen, was seither geloescht oder in einen
          anderen Raum verschoben wurde.
"""
import sys

import keyword_index
import paths
import raeume
import store

# Wie viele Abschnitte je Griff AUS der alten Sammlung geholt werden. Das
# Schreiben teilt store.schreibe selbst auf -- dort gilt ueber HTTP eine
# Groessengrenze, die von der Vektorlaenge des Modells abhaengt.
STAPEL = 2000


def ziel(meta):
    """In welchen Raum gehoert dieser Abschnitt?"""
    zugang = (meta.get("access") or "shared").strip()
    besitzer = (meta.get("owner") or "").strip()
    if zugang == "shared" or not besitzer or besitzer == "system":
        return raeume.ALLGEMEIN
    return raeume.privat_kennung(besitzer)


def main():
    nur_pruefen = "--pruefen" in sys.argv
    paths.bootstrap()

    try:
        alt = store.collection(anlegen=False)
    except Exception as e:
        print(f"Die alte Sammlung '{paths.COLLECTION_NAME}' ist nicht "
              f"lesbar: {e}")
        return 1

    gesamt = alt.count()
    print(f"Alte Sammlung: {gesamt} Abschnitte ({store.beschreibung()})")
    if not gesamt:
        print("Nichts zu tun.")
        return 0

    # --- 1. Durchgang: zaehlen ---
    #
    # Erst zaehlen, dann schreiben. Wer vorher nicht weiss, wie viele
    # Raeume entstehen und wie gross sie werden, merkt einen Fehler in der
    # Zuordnung erst, wenn der Bestand schon verteilt ist.
    verteilung = {}
    gelesen = 0
    while gelesen < gesamt:
        batch = alt.get(include=["metadatas"], limit=STAPEL, offset=gelesen)
        ids = batch.get("ids") or []
        if not ids:
            break
        for meta in batch.get("metadatas") or []:
            k = ziel(meta or {})
            verteilung[k] = verteilung.get(k, 0) + 1
        gelesen += len(ids)

    print("\nGeplante Verteilung:")
    for k in sorted(verteilung, key=lambda x: -verteilung[x]):
        print(f"  {k:<40} {verteilung[k]:>7}  -> {raeume.sammlung(k)}")

    # --- SCHON EINMAL GELAUFEN? ---
    #
    # Ein zweiter Lauf ist nicht harmlos. Die alte Sammlung bleibt
    # absichtlich stehen, und sie kennt nur den Stand von damals: was
    # seither geloescht wurde, kaeme zurueck, und ein Dokument, das
    # inzwischen in einen beschraenkten Raum verschoben wurde, laege
    # danach wieder im allgemeinen. Beides ohne Fehlermeldung.
    #
    # Beim ersten Mal ist das kein Thema -- da gibt es nichts zu
    # ueberschreiben. Danach muss man es ausdruecklich wollen.
    schon_da = [k for k in verteilung
                if store.sammlung(raeume.sammlung(k), anlegen=False)
                is not None]
    erneut = "--erneut" in sys.argv
    if schon_da and not nur_pruefen and not erneut:
        print("")
        print(f"Diese Raeume gibt es schon: {', '.join(sorted(schon_da))}")
        print("Ein zweiter Lauf holt aus der alten Sammlung alles "
              "zurueck, was seither")
        print("  * geloescht wurde, und")
        print("  * in einen anderen Raum verschoben wurde.")
        print("")
        print("Ist die Umsortierung durch, loesche die alte Sammlung "
              "in der Oberflaeche")
        print("unter 'Raeume verwalten' -- dann kann das nicht mehr "
              "passieren.")
        print("")
        print("Trotzdem laufen lassen: python umsortieren.py --erneut")
        return 1

    if nur_pruefen:
        print("\n--pruefen: nichts geschrieben.")
        return 0

    # --- 2. Raeume anlegen ---
    for k in verteilung:
        if k == raeume.ALLGEMEIN:
            continue
        if raeume.ist_privat(k):
            benutzer = k[len(raeume.PRIVAT):]
            raeume.sichere_anlage_privat(benutzer)
        else:
            raeume.anlegen(k, k)

    # --- 3. Umsortieren ---
    sammlungen = {k: store.sammlung(raeume.sammlung(k)) for k in verteilung}
    geschrieben = {k: 0 for k in verteilung}
    uebersprungen = 0
    gelesen = 0

    while gelesen < gesamt:
        # store.hole: Chroma kann den Vektorleser einer Sammlung nicht
        # aufbauen, solange das Segment noch nicht abgelegt ist. Hier
        # waere das ein Abbruch mitten in der Umsortierung.
        batch = store.hole(alt, paths.COLLECTION_NAME,
                           include=["documents", "metadatas", "embeddings"],
                           limit=STAPEL, offset=gelesen)
        ids = batch.get("ids") or []
        if not ids:
            break
        dokumente = batch.get("documents") or []
        metas = batch.get("metadatas") or []
        vektoren = batch.get("embeddings")
        if vektoren is None or len(vektoren) != len(ids):
            print("Die Vektoren fehlen -- ohne sie waere das ein "
                  "Neueinlesen. Abbruch.")
            return 1

        # Nach Ziel buendeln, damit je Raum ein Aufruf genuegt.
        haufen = {}
        for i, kennung in enumerate(ids):
            meta = dict(metas[i] if i < len(metas) else {})
            k = ziel(meta)
            meta["raum"] = k
            haufen.setdefault(k, ([], [], [], []))
            h = haufen[k]
            h[0].append(kennung)
            h[1].append(dokumente[i] if i < len(dokumente) else "")
            h[2].append(meta)
            h[3].append(vektoren[i])

        for k, (kids, docs, ms, vs) in haufen.items():
            sml = sammlungen.get(k) or store.sammlung(raeume.sammlung(k))
            sammlungen[k] = sml
            try:
                # store.schreibe statt sml.upsert: ueber HTTP lehnt der
                # Server eine zu grosse Anfrage ab, und wie gross zu gross
                # ist, haengt an der Vektorlaenge. Die Funktion halbiert
                # den Stapel, bis er durchgeht. upsert, damit ein zweiter
                # Lauf nichts verdoppelt.
                geschrieben[k] = geschrieben.get(k, 0) + store.schreibe(
                    sml, kids, documents=docs, metadatas=ms, embeddings=vs)
            except Exception as e:
                uebersprungen += len(kids)
                print(f"  [!] {k}: {e}")

        gelesen += len(ids)
        print(f"  {gelesen}/{gesamt}")

    print("\nGeschrieben:")
    for k in sorted(geschrieben, key=lambda x: -geschrieben[x]):
        print(f"  {k:<40} {geschrieben[k]:>7}")
    if uebersprungen:
        print(f"  nicht geschrieben: {uebersprungen}")

    # --- 4. Stichwortindex neu aufbauen ---
    #
    # Er muss mit, denn er filtert jetzt nach Raum, und die alte Tabelle hat
    # die Spalte nicht. Der Aufbau geht aus den Sammlungen, also ohne Modell
    # und ohne die Originaldateien.
    #
    # ALLE Raeume, nicht nur die aus der Umsortierung. rebuild_from_raeume
    # beginnt mit dem Leeren der Tabelle -- bekaeme es nur die eben
    # befuellten, verloere jeder Raum, der nach der Umsortierung entstanden
    # ist, seine Stichwortzeilen. Die Suche faende dort dann nur noch ueber
    # Vektoren, und das faellt niemandem auf, weil sie trotzdem antwortet.
    print("\nStichwortindex wird neu aufgebaut...")
    alle = dict(sammlungen)
    for k in raeume.liste():
        if k not in alle:
            sml = store.sammlung(raeume.sammlung(k), anlegen=False)
            if sml is not None:
                alle[k] = sml
    n = keyword_index.rebuild_from_raeume(
        [(k, alle[k]) for k in sorted(alle) if alle[k] is not None],
        progress=lambda raum, done, total: None)
    print(f"  {n} Abschnitte im Stichwortindex.")

    print("\nFertig. Die alte Sammlung bleibt unangetastet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
