import chromadb
import os

import paths

print("Starte Datenbank-Migration...")
chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
collection = chroma_client.get_collection(name=paths.COLLECTION_NAME)

data = collection.get()
ids_to_update = []
new_metadatas = []

# Metadaten vorbereiten
for chunk_id, meta in zip(data['ids'], data['metadatas']):
    if "access" not in meta or "owner" not in meta:
        meta["access"] = "shared"
        meta["owner"] = "system"
        ids_to_update.append(chunk_id)
        new_metadatas.append(meta)

# In Batches (Häppchen) aufteilen und hochladen
if ids_to_update:
    BATCH_SIZE = 5000
    total_items = len(ids_to_update)
    print(f"Gefunden: {total_items} Einträge, die ein Update benötigen.")
    print(f"Teile in {BATCH_SIZE}er Blöcke auf...")
    
    for i in range(0, total_items, BATCH_SIZE):
        batch_ids = ids_to_update[i : i + BATCH_SIZE]
        batch_metas = new_metadatas[i : i + BATCH_SIZE]
        
        collection.update(ids=batch_ids, metadatas=batch_metas)
        print(f"  -> Batch {i // BATCH_SIZE + 1} erfolgreich verarbeitet ({len(batch_ids)} Einträge).")
        
    print(f"✅ {total_items} alte Text/Bild-Chunks wurden erfolgreich in den gemeinsamen Pool migriert!")
else:
    print("👍 Alles war bereits auf dem neuesten Stand.")