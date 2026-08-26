import pymupdf
import chromadb
from openai import OpenAI
import os

import paths
import glob
import base64
from PIL import Image
import io
import re

print("Starte In-Place Formel-Update in ChromaDB...")

# --- KONFIGURATION ---
ORDNER_NAME = paths.DOCS_DIR
VISION_MODEL = "qwen3-vl:32b"
EMBEDDING_MODEL = "qwen3-embedding:4b"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "Dein_Platzhalter_Key"), 
    base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:4000")
)

# ChromaDB laden
chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
collection = chroma_client.get_collection(name=paths.COLLECTION_NAME)

# Dein strikter Formel-Prompt aus transcribe_formulas.py
PROMPT = (
    "Transkribiere die mathematische Formel oder Tabelle im Bild als reines LaTeX. "
    "Gib AUSSCHLIESSLICH den LaTeX-Ausdruck aus - keine Erklaerung, kein "
    "Gedankengang, kein Codeblock, keine $-Zeichen. Deutsche Woerter als "
    "\\text{...}. Brueche \\frac{}{}, Summen \\sum, Durchschnitt \\varnothing, "
    "Multiplikation \\cdot. Alle Klammern schliessen. Nur die Formel."
)

# --- DEINE SICHERHEITSFUNKTIONEN ---
def clean_latex(raw):
    txt = raw
    # abgeschlossene Denk-Bloecke entfernen
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    if "</think>" in txt:
        txt = txt.split("</think>")[-1]
    txt = txt.replace("<think>", "")
    txt = re.sub(r"```(?:latex|tex)?", "", txt)
    txt = txt.strip().strip("$").strip()
    
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    cand = [l for l in lines if "\\" in l]
    if cand:
        txt = max(cand, key=len)
    elif lines:
        txt = lines[-1]
    return txt.strip()

def balanced(s):
    if s.count("{") != s.count("}"):
        return False
    if s.count(r"\left") != s.count(r"\right"):
        return False
    return True

def get_embedding(text, model=EMBEDDING_MODEL):
    text = text.replace("\n", " ")
    response = client.embeddings.create(
        input=[text],
        model=model,
        encoding_format="float", 
        extra_body={"drop_params": True}
    )
    return response.data[0].embedding

# --- VERARBEITUNG ---
pdf_dateien = glob.glob(os.path.join(ORDNER_NAME, "*.pdf"))

for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    print(f"\n🔄 Überprüfe Bilder in '{dateiname}'...")
    
    try:
        doc = pymupdf.open(pdf_pfad)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            
            for img_index, img_info in enumerate(image_list):
                chunk_id = f"{dateiname}_p{page_num+1}_img{img_index}"
                
                # Check: Existiert das Bild schon in der DB?
                existing = collection.get(ids=[chunk_id])
                if not existing or len(existing['ids']) == 0:
                    continue # Überspringen, falls nicht vorhanden
                
                print(f"   📐 Erzeuge LaTeX für Bild {img_index+1} auf Seite {page_num+1}...")
                
                # Bild extrahieren und vorbereiten
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                image = Image.open(io.BytesIO(base_image["image"]))
                
                if image.mode in ("RGBA", "P"):
                    image = image.convert("RGB")
                    
                buffered = io.BytesIO()
                image.save(buffered, format="JPEG", quality=95)
                base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
                image_url = f"data:image/jpeg;base64,{base64_image}"
                
                try:
                    # Vision API anfragen
                    vision_response = client.chat.completions.create(
                        model=VISION_MODEL,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": PROMPT},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ]
                            }
                        ]
                    )
                    
                    raw_content = vision_response.choices[0].message.content
                    latex_code = clean_latex(raw_content)
                    
                    if not latex_code or not balanced(latex_code):
                        print("   [!] Fehler: LaTeX unbalanciert oder leer, überspringe.")
                        continue
                        
                    # Finalen Text bauen und als Update in die DB schieben
                    finaler_text = f"Formel/Tabelle (LaTeX): $$ {latex_code} $$"
                    vector = get_embedding(finaler_text)
                    
                    # UPDATE statt ADD -> Überschreibt die alte Beschreibung lautlos
                    collection.update(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[finaler_text]
                    )
                    print("   ✅ Erfolgreich aktualisiert!")
                    
                except Exception as e:
                    print(f"   [!] Fehler bei der API-Anfrage: {e}")
                    
    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}")

print("🚀 ALLE FORMELN IN DER DATENBANK SIND NUN SAUBERES LATEX!")