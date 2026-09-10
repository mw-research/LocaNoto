import geheim
import paths
import raumschluessel
import store
print("cryptography+Schluessel:", raumschluessel.verfuegbar())
print("Schluesselzustand:", geheim.zustand()[0], "|", geheim.zustand()[1][:60])
print("Konfig:", paths.CONFIG_DIR)
print("Raumschluessel hinterlegt fuer:", raumschluessel.bekannt())
sml = store.sammlung("raum_allgemein", anlegen=False)
print("Sammlung:", sml is not None, "| raum_von():", repr(store.raum_von(sml)))
d = sml.get(limit=2, include=["documents", "metadatas"])
for t in d["documents"]:
    print("  gespeichert:", repr(t[:40]))
print("  hat datei_id:", [("datei_id" in (m or {})) for m in d["metadatas"]])
print("  file_name:", [str((m or {}).get("file_name"))[:30] for m in d["metadatas"]])
probe = store._verschluesselt("allgemein", ["Testtext"])
print("Verschluesseln einer Probe:", repr(probe[0][:30]))
