"""Baut den Keyword-Index aus der bestehenden Vektordatenbank neu auf.

Noetig fuer Installationen, deren ChromaDB aelter ist als der FTS5-Index --
also wenn der Bestand mit dem frueheren In-Memory-BM25 aufgebaut wurde.

Die App macht das beim ersten Start automatisch. Dieses Skript ist fuer den
Fall, dass man den Aufbau lieber vorab und ausserhalb der Weboberflaeche
laufen laesst, oder wenn der Index nach einem Eingriff von Hand nicht mehr
zur Datenbank passt.
"""
import chromadb

import paths
import keyword_index

paths.bootstrap()

chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
collection = chroma_client.get_or_create_collection(name=paths.COLLECTION_NAME)

total = collection.count()
print(f"Vektordatenbank enthaelt {total:,} Chunks.")
print(f"Keyword-Index vorher    : {keyword_index.count():,} Chunks")

if total == 0:
    print("Nichts zu tun.")
    raise SystemExit(0)


def show(done, tot):
    print(f"   ... {done:,} / {tot:,}", end="\r")


written = keyword_index.rebuild_from_collection(collection, progress=show)
print(" " * 40, end="\r")
print(f"Keyword-Index nachher   : {written:,} Chunks")
print(f"Indexdatei              : {keyword_index.DB_PATH}")
print("Fertig.")
