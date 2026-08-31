"""Batch-Vektorisierung der PDFs aus data/dokumente.

Verarbeitet Tabellen und Fliesstext getrennt: Tabellen werden als ein
unzerteilter Chunk mit der Bildunterschrift darueber abgelegt und
anschliessend aus dem Seitentext geschwaerzt, damit sie nicht ein zweites
Mal als zerlaufener Fliesstext im Index landen.

Der Lauf ist unterbrechbar. Wiederaufsetzen geschieht auf Chunk-Ebene, nicht
auf Datei-Ebene: die Textextraktion laeuft erneut, sie dauert nur
Millisekunden pro Seite. Vektorisiert wird nur, was noch fehlt -- das ist der
zeitintensive Teil. Ein abgebrochener Lauf hinterlaesst damit kein halb
indexiertes Dokument, das beim naechsten Start als erledigt gilt.
"""
import pymupdf
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os

import paths
import keyword_index
import llm
from embedding import embed_batch
from textutils import strip_boilerplate
from tables import build_table_chunks

print("Starte Batch-Hintergrund-Vektorisierung...")

# --- KONFIGURATION ---
paths.bootstrap()
ORDNER_NAME = paths.DOCS_DIR
EMBEDDING_MODEL = llm.modell("EMBEDDING")
client = llm.client("EMBEDDING")

chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
collection = chroma_client.get_or_create_collection(name=paths.COLLECTION_NAME)
kw = keyword_index.connect()

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

# Rekursiv, damit Unterordner als Sachgebiet dienen koennen (siehe
# folder_of), und unabhaengig von der Gross-/Kleinschreibung der Endung.
pdf_dateien = paths.pdf_dateien(ORDNER_NAME)

if not pdf_dateien:
    print(f"Keine PDFs in '{ORDNER_NAME}' gefunden.")
    raise SystemExit(0)

print(f"Insgesamt {len(pdf_dateien)} PDFs gefunden. Starte Verarbeitung...\n")


def folder_of(pdf_pfad):
    """Unterordner relativ zu data/dokumente, als Sachgebiet nutzbar.

    PDFs direkt im Wurzelverzeichnis bekommen '(Basis)', damit der Filter in
    der App auch sie als Gruppe anbieten kann.
    """
    rel = os.path.relpath(os.path.dirname(pdf_pfad), ORDNER_NAME)
    return "(Basis)" if rel in (".", "") else rel.replace(os.sep, "/")


def existing_chunk_ids(dateiname):
    """IDs, die fuer dieses Dokument bereits in der Datenbank stehen."""
    try:
        return set(collection.get(where={"file_name": dateiname},
                                  include=[])["ids"])
    except Exception:
        return set()


def flush(pending, dateiname):
    """Vektorisiert und speichert die gesammelten Chunks eines Dokuments."""
    if not pending:
        return 0

    ids = [p[0] for p in pending]
    texts = [p[1] for p in pending]
    metas = [p[2] for p in pending]

    def show(done, total):
        print(f"   ... vektorisiere {done}/{total} Chunks", end="\r")

    vectors = embed_batch(client, texts, EMBEDDING_MODEL, progress=show)
    print(" " * 60, end="\r")

    # Chunks ohne Vektor (dauerhafter Serverfehler) ueberspringen, statt den
    # ganzen Lauf abzubrechen.
    keep = [i for i, v in enumerate(vectors) if v is not None]
    if len(keep) < len(ids):
        print(f"   [!] {len(ids) - len(keep)} Chunks ohne Vektor uebersprungen.")
    if not keep:
        return 0

    collection.add(
        ids=[ids[i] for i in keep],
        embeddings=[vectors[i] for i in keep],
        documents=[texts[i] for i in keep],
        metadatas=[metas[i] for i in keep],
    )
    keyword_index.add_chunks(
        ((ids[i], texts[i], metas[i]) for i in keep), con=kw)
    return len(keep)


# --- VERARBEITUNG ---
for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    ordner = folder_of(pdf_pfad)

    bekannt = existing_chunk_ids(dateiname)

    print(f"⏳ VERARBEITE: '{dateiname}' [{ordner}]"
          + (f" -- {len(bekannt)} Chunks bereits vorhanden" if bekannt else ""))

    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        pending = []
        neu = 0

        for page_num in range(total_pages):
            page = doc[page_num]
            basis_meta = {"file_name": dateiname, "page": page_num + 1,
                          "folder": ordner, "access": "shared",
                          "owner": "system"}

            # --- TABELLEN ISOLIEREN UND ANREICHERN ---
            tables = page.find_tables()
            for i, table in enumerate(tables):
                try:
                    # Ueberschrift voranstellen und uebergrosse Tabellen
                    # aufteilen -- siehe tables.py. Bleibt eine Tabelle unter
                    # dem Limit, ist die Chunk-ID unveraendert.
                    for suffix, chunk_text in build_table_chunks(
                            page, table, dateiname, page_num + 1, i):
                        chunk_id = f"{dateiname}_{suffix}"
                        if chunk_id not in bekannt:
                            pending.append((chunk_id, chunk_text,
                                            dict(basis_meta, type="table")))

                    page.add_redact_annot(pymupdf.Rect(table.bbox))
                except Exception as e:
                    print(f"   [!] Fehler bei Tabelle auf Seite {page_num+1}: {e}")

            # Schwärzungen anwenden
            page.apply_redactions()

            # --- RESTLICHEN TEXT AUSLESEN ---
            page_text = strip_boilerplate(page.get_text())
            if page_text.strip():
                for i, chunk in enumerate(text_splitter.split_text(page_text)):
                    chunk_id = f"{dateiname}_p{page_num+1}_c{i}"
                    if chunk_id not in bekannt:
                        pending.append((chunk_id, chunk,
                                        dict(basis_meta, type="text")))

            # Regelmaessig wegschreiben, damit nach einem Abbruch nur die
            # letzten Seiten erneut verarbeitet werden muessen.
            if len(pending) >= 256:
                neu += flush(pending, dateiname)
                pending = []

            if (page_num + 1) % 100 == 0:
                print(f"   ... Fortschritt: {page_num + 1} / {total_pages} Seiten")

        neu += flush(pending, dateiname)
        doc.close()

        if neu:
            print(f"✅ ABGESCHLOSSEN: '{dateiname}' -- {neu} neue Chunks.\n")
        else:
            print(f"⏩ ÜBERSPRUNGEN: '{dateiname}' war bereits vollständig.\n")

    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}\n")

kw.close()

# --- VRAM CLEANUP ---
print("Gebe VRAM frei...")
try:
    client.embeddings.create(
        input=["Cleanup"], model=EMBEDDING_MODEL, encoding_format="float",
        extra_body={"drop_params": True, "keep_alive": 0}
    )
except Exception:
    pass

print("🚀 FERTIG! Alle Dokumente sind in der Datenbank.")
