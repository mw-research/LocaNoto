import pymupdf
import chromadb
from openai import OpenAI
import os
import glob
import base64
from PIL import Image
import io
print("Starte nachträgliche Bild-Vektorisierung...")

# --- KONFIGURATION ---
ORDNER_NAME = "dokumente" 
VISION_MODEL = "qwen3-vl:32b"
EMBEDDING_MODEL = "qwen3-embedding:4b"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "Dein_Platzhalter_Key"), 
    base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:4000")
)

def get_embedding(text, model=EMBEDDING_MODEL):
    text = text.replace("\n", " ")
    response = client.embeddings.create(
        input=[text],
        model=model,
        encoding_format="float", 
        extra_body={"drop_params": True}
    )
    return response.data[0].embedding

# ChromaDB laden (verbindet sich mit deiner bestehenden Datenbank!)
db_path = os.path.join(os.getcwd(), "chroma_db")
chroma_client = chromadb.PersistentClient(path=db_path)
collection = chroma_client.get_collection(name="pdf_documents")

pdf_dateien = glob.glob(os.path.join(ORDNER_NAME, "*.pdf"))

if not pdf_dateien:
    print(f"Keine PDFs im Ordner '{ORDNER_NAME}' gefunden.")
    exit()

# Prompt
VISION_PROMPT = """
Analysiere dieses Bild aus einem Dokument. Erstelle eine umfassende, neutrale und hochdetaillierte Textbeschreibung aller sichtbaren Inhalte, damit diese in einer Text-Datenbank optimal durchsuchbar werden.
- Extrahiere sämtlichen relevanten Text.
- Beschreibe bei Diagrammen, Graphen oder Schaubildern die Achsen, Werte, Trends und Kernaussagen.
- Erfasse bei Tabellen die grundlegende Struktur und die wichtigsten Datenpunkte.
- Beschreibe bei Fotos, Illustrationen oder Skizzen das zentrale Motiv und alle relevanten Details.
Übersetze den kompletten Informationsgehalt des Bildes so präzise in Textform, dass eine Person, die das Bild nicht sieht, keine einzige fachliche Information verpasst. Erfinde keine Informationen hinzu.
"""

# --- VERARBEITUNG ---
for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    print(f"\n⏳ Durchsuche '{dateiname}' nach Bildern...")
    
    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        images_found = 0
        
        for page_num in range(total_pages):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            
            for img_index, img_info in enumerate(image_list):
                images_found += 1
                # Wir bauen eine spezielle ID für Bilder, um Doppelungen zu vermeiden
                chunk_id = f"{dateiname}_p{page_num+1}_img{img_index}"
                
                # Check: Ist das Bild schon in der Datenbank?
                existing = collection.get(ids=[chunk_id])
                if existing and len(existing['ids']) > 0:
                    continue # Bild wurde schon verarbeitet
                
                print(f"   🖼️ Analysiere Bild {img_index+1} auf Seite {page_num+1}...")
                
                # Bild extrahieren
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                # --- NEU: BILD-OPTIMIERUNG MIT PILLOW ---
                try:
                    # Bild in den Arbeitsspeicher laden
                    image = Image.open(io.BytesIO(image_bytes))
                    width, height = image.size
                    
                    # 1. MÜLL-FILTER: Ignoriere winzige Bilder (Logos, Icons, Trennlinien)
                    if width < 400 or height < 400:
                        print(f"   ⏩ Überspringe winziges Bild ({width}x{height} px) - vermutlich ein Logo.")
                        continue
                    
                    # 2. RESIZING: Wir normieren die längste Seite auf 1024 Pixel.
                    # Kleine Bilder werden vergrößert (damit das Modell die Patches besser lesen kann),
                    # riesige Bilder werden verkleinert (um VRAM zu sparen).
                    target_max = 1024
                    ratio = target_max / max(width, height)
                    
                    if ratio != 1.0:
                        new_width = int(width * ratio)
                        new_height = int(height * ratio)
                        # LANCZOS ist der beste Algorithmus, um Schriften beim Skalieren scharf zu halten
                        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Wenn PDFs transparente Bilder (PNG) haben, müssen wir sie für JPEGs in RGB konvertieren
                    if image.mode in ("RGBA", "P"):
                        image = image.convert("RGB")
                        
                    # Das optimierte Bild wieder in Bytes umwandeln
                    buffered = io.BytesIO()
                    image.save(buffered, format="JPEG", quality=95)
                    optimized_bytes = buffered.getvalue()
                    
                    # In Base64 umwandeln für die Vision API
                    base64_image = base64.b64encode(optimized_bytes).decode('utf-8')
                    image_url = f"data:image/jpeg;base64,{base64_image}"
                    
                except Exception as e:
                    print(f"   [!] Fehler bei der Bildoptimierung: {e}")
                    continue
                # ----------------------------------------
                try:
                    # 1. Bild an Qwen3-VL senden
                    vision_response = client.chat.completions.create(
                        model=VISION_MODEL,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": VISION_PROMPT},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ]
                            }
                        ]
                    )
                    
                    bild_beschreibung = vision_response.choices[0].message.content
                    
                    # Den Text für den Chat-Kontext aufbereiten
                    finaler_text = f"[BILD-BESCHREIBUNG]: {bild_beschreibung}"
                    
                    # 2. Beschreibung vektorisieren
                    vector = get_embedding(finaler_text)
                    
                    # 3. Als neuen Chunk in ChromaDB speichern (mit speziellem Typ "image")
                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[finaler_text],
                        metadatas=[{"file_name": dateiname, "page": page_num + 1, "source": "uploaded_pdfs", "type": "image"}]
                    )
                except Exception as e:
                    print(f"   [!] Fehler bei der Bildanalyse auf Seite {page_num+1}: {e}")
                    
        print(f"✅ FERTIG mit '{dateiname}'. Insgesamt {images_found} Bilder gefunden.")
        
    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}")

# --- VRAM CLEANUP ---
print("\nGebe VRAM frei...")
try:
    client.embeddings.create(
        input=["Cleanup"], model=EMBEDDING_MODEL, encoding_format="float",
        extra_body={"drop_params": True, "keep_alive": 0}
    )
except:
    pass

print("🚀 ALLE BILDER SIND INDEXIERT!")