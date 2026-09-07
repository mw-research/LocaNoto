"""Baut den Keyword-Index aus der bestehenden Vektordatenbank neu auf.

Noetig fuer Installationen, deren ChromaDB aelter ist als der FTS5-Index --
also wenn der Bestand mit dem frueheren In-Memory-BM25 aufgebaut wurde.

Die App macht das beim ersten Start automatisch. Dieses Skript ist fuer den
Fall, dass man den Aufbau lieber vorab und ausserhalb der Weboberflaeche
laufen laesst, oder wenn der Index nach einem Eingriff von Hand nicht mehr
zur Datenbank passt.
"""

import paths
import store
import raeume
import keyword_index

paths.bootstrap()

# Alle Raeume, nicht einer: der Stichwortindex liegt in einer Tabelle und
# filtert beim Lesen nach Raum. Ein Index, der nur einen Raum kennt, laesst
# die anderen stumm -- ohne Fehlermeldung, es fehlen einfach Treffer.
paare = []
for _kennung in raeume.liste():
    _sml = store.sammlung(raeume.sammlung(_kennung), anlegen=False)
    if _sml is not None:
        paare.append((_kennung, _sml))

if not paare:
    print("Keine Raum-Sammlungen gefunden. Erst umsortieren.py laufen "
          "lassen.")
    raise SystemExit(1)

for _k, _s in paare:
    print(f"  {_k:<40} {_s.count():>8,} Abschnitte")

total = sum(_s.count() for _k, _s in paare)
print(f"Vektordatenbank enthaelt {total:,} Chunks.")
print(f"Keyword-Index vorher    : {keyword_index.count():,} Chunks")

if total == 0:
    print("Nichts zu tun.")
    raise SystemExit(0)


def zeige(raum, done, tot):
    print(f"   {raum}: {done:,} / {tot:,}", end="\r")


written = keyword_index.rebuild_from_raeume(paare, progress=zeige)
print(" " * 40, end="\r")
print(f"Keyword-Index nachher   : {written:,} Chunks")
print(f"Indexdatei              : {keyword_index.DB_PATH}")
print("Fertig.")
