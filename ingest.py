import pymupdf
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
import os
import glob

print("Starte Batch-Hintergrund-Vektorisierung...")

# --- KONFIGURATION ---
ORDNER_NAME = "dokumente" # <--- Hier sucht das Skript nach PDFs

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "Dein_Platzhalter_Key"), 
    base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:4000")
)

def get_embedding(text, model="qwen3-embedding:4b"):
    text = text.replace("\n", " ")
    response = client.embeddings.create(
        input=[text],
        model=model,
        encoding_format="float", 
        extra_body={"drop_params": True}
    )
    return response.data[0].embedding

# ChromaDB Setup
db_path = os.path.join(os.getcwd(), "chroma_db")
chroma_client = chromadb.PersistentClient(path=db_path)
collection = chroma_client.get_or_create_collection(name="pdf_documents")

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

# Prüfen, ob der Ordner existiert
if not os.path.exists(ORDNER_NAME):
    os.makedirs(ORDNER_NAME)
    print(f"Ordner '{ORDNER_NAME}' wurde erstellt. Bitte lege PDFs hinein und starte neu.")
    exit()

# Alle PDFs im Ordner finden
pdf_dateien = glob.glob(os.path.join(ORDNER_NAME, "*.pdf"))

if not pdf_dateien:
    print(f"Keine PDFs im Ordner '{ORDNER_NAME}' gefunden.")
    exit()

print(f"Insgesamt {len(pdf_dateien)} PDFs gefunden. Starte Verarbeitung...\n")

# --- VERARBEITUNG ---
for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    
    # 1. Sicherheits-Check: Ist das PDF schon in der Datenbank?
    existing = collection.get(where={"file_name": dateiname})
    if existing and len(existing['ids']) > 0:
        print(f"⏩ ÜBERSPRINGE: '{dateiname}' ist bereits in der Datenbank.")
        continue # Springt sofort zum nächsten PDF

    print(f"⏳ VERARBEITE: '{dateiname}' ...")
    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        
        for page_num in range(total_pages):
            page = doc[page_num]
            
          # --- NEU: TABELLEN ISOLIEREN UND ANREICHERN ---
            tables = page.find_tables()
            for i, table in enumerate(tables):
                try:
                    md_table = table.to_markdown()
                    
                    # SICHERER ZUGRIFF: y0 ist immer der 2. Wert im Tuple (Index 1)
                    y0 = table.bbox[1]
                    
                    # Bounding-Box direkt über der Tabelle abgreifen
                    header_rect = pymupdf.Rect(0, max(0, y0 - 150), page.rect.width, y0)
                    table_context = page.get_text("text", clip=header_rect).replace("\n", " ").strip()
                    
                    if not table_context or len(table_context) < 5:
                        table_context = f"Tabelle aus {dateiname}, Seite {page_num + 1}"
                    
                    chunk_text = f"KONTEXT ZUR TABELLE: {table_context}\n\nTABELLE (Seite {page_num + 1}):\n{md_table}"
                    chunk_id = f"{dateiname}_p{page_num+1}_table_{i}"
                    
                    
                    vector = get_embedding(chunk_text)
                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk_text],
                        metadatas=[{"file_name": dateiname, "page": page_num + 1, "access": "shared", "owner": "system", "type": "table"}]
                    )
                    
                    page.add_redact_annot(pymupdf.Rect(table.bbox))
                except Exception as e:
                    print(f"   [!] Fehler bei Tabelle auf Seite {page_num+1}: {e}")
            
            # Schwärzungen anwenden
            page.apply_redactions()

            # --- RESTLICHEN TEXT AUSLESEN ---
            page_text = page.get_text()
            if not page_text.strip():
                continue
                
            chunks = text_splitter.split_text(page_text)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{dateiname}_p{page_num+1}_c{i}"
                try:
                    vector = get_embedding(chunk)
                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{"file_name": dateiname, "page": page_num + 1, "access": "shared", "owner": "system", "type": "text"}]
                    )
                except Exception as e:
                    print(f"   [!] Fehler bei Text auf Seite {page_num+1}: {e}")
                    
            # Fortschrittsanzeige für große Dokumente
            if (page_num + 1) % 100 == 0:
                print(f"   ... Fortschritt: {page_num + 1} / {total_pages} Seiten")
                
        print(f"✅ ABGESCHLOSSEN: '{dateiname}' wurde erfolgreich indexiert.\n")
        
    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}\n")

# --- VRAM CLEANUP ---
print("Gebe VRAM frei...")
try:
    client.embeddings.create(
        input=["Cleanup"], model="qwen3-embedding:4b", encoding_format="float",
        extra_body={"drop_params": True, "keep_alive": 0}
    )
except:
    pass

print("🚀 FERTIG! Alle Dokumente sind in der Datenbank.")