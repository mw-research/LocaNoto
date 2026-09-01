import pymupdf
import chromadb
import os
import base64
from PIL import Image
import io

import paths
import keyword_index
import llm
from tables import bild_kontext

print("Starte nachträgliche Bild-Vektorisierung...")

# --- KONFIGURATION ---
paths.bootstrap()
ORDNER_NAME = paths.DOCS_DIR
# Bildbeschreibung und Vektorisierung koennen auf getrennten Servern
# liegen -- VISION_BASE_URL und EMBEDDING_BASE_URL steuern das.
VISION_MODEL = llm.modell("VISION")
EMBEDDING_MODEL = llm.modell("EMBEDDING")
vision_client = llm.client("VISION")

# Schwellen für den Größenfilter (siehe Kommentar an der Prüfstelle).
#
# Die Vorgaben sind an technischen Zeichnungen kalibriert. Bei einem
# Software-Handbuch liegen Bildschirmausschnitte deutlich darunter -- ein
# Dialogfenster misst schnell nur 250x260 Pixel. Deshalb einstellbar.
MIN_LONG_EDGE = paths.env_int("MIN_LONG_EDGE", 400)
MIN_AREA = paths.env_int("MIN_AREA", 120_000)

client = llm.client("EMBEDDING")

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
chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
collection = chroma_client.get_collection(name=paths.COLLECTION_NAME)
kw = keyword_index.connect()


def folder_of(pdf_pfad):
    """Unterordner relativ zu data/dokumente, als Sachgebiet nutzbar."""
    rel = os.path.relpath(os.path.dirname(pdf_pfad), ORDNER_NAME)
    return "(Basis)" if rel in (".", "") else rel.replace(os.sep, "/")

# Rekursiv, damit Unterordner als Sachgebiet dienen koennen (siehe
# folder_of), und unabhaengig von der Gross-/Kleinschreibung der Endung.
pdf_dateien = paths.pdf_dateien(ORDNER_NAME)

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

# Wird an den Prompt angehaengt, sobald Text um die Abbildung herum gefunden
# wurde. Ohne ihn beschreibt das Modell nur Geometrie: es sieht den
# freigeschnittenen Ausschnitt und weiss weder, welche Groesse auf einer Achse
# steht, noch zu welchem Regelwerk die Abbildung gehoert.
KONTEXT_ZUSATZ = """
Diese Abbildung steht in folgendem Zusammenhang. Nutze ihn, um zu benennen, WAS
dargestellt ist -- nicht nur, wie es aussieht:

{kontext}
"""

# Bereits verarbeitete Bild-Referenzen ueber das gesamte Dokument.
#
# Manche PDFs teilen sich ein gemeinsames Ressourcen-Verzeichnis: dann meldet
# JEDE Seite saemtliche Bilder des Dokuments. Beobachtet an einem Handbuch mit
# 7833 Seiten, das auf jeder Seite dieselben 2040 Bilder auswies -- ohne
# Entdopplung waeren das 16 Millionen Durchlaeufe und jeder Screenshot 7833-mal
# in der Datenbank.
gesehene_bilder = set()


# --- VERARBEITUNG ---
for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    ordner = folder_of(pdf_pfad)
    print(f"\n⏳ Durchsuche '{dateiname}' nach Bildern...")
    
    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        images_found = 0
        
        for page_num in range(total_pages):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]

                # 1. Steht das Bild ueberhaupt auf DIESER Seite?
                #
                # get_images() listet den Inhalt des Ressourcen-Verzeichnisses,
                # nicht das, was gezeichnet wird. Teilen sich alle Seiten ein
                # Verzeichnis, meldet jede Seite alles. get_image_bbox liefert
                # dann ein unendliches Rechteck -- daran ist zu erkennen, dass
                # das Bild hier nicht vorkommt.
                #
                # Die Pruefung steht bewusst vor allem anderen: sie braucht
                # weder eine Datenbankabfrage noch das Entpacken des Bildes.
                try:
                    bbox = page.get_image_bbox(img_info)
                except Exception:
                    continue
                if bbox.is_empty or bbox.is_infinite:
                    continue

                # 2. Dasselbe Bild nur einmal, auch wenn es mehrfach vorkommt.
                if xref in gesehene_bilder:
                    continue
                gesehene_bilder.add(xref)

                images_found += 1
                # Wir bauen eine spezielle ID für Bilder, um Doppelungen zu vermeiden
                chunk_id = f"{dateiname}_p{page_num+1}_img{img_index}"

                # Check: Ist das Bild schon in der Datenbank?
                existing = collection.get(ids=[chunk_id])
                if existing and len(existing['ids']) > 0:
                    continue # Bild wurde schon verarbeitet

                print(f"   🖼️ Analysiere Bild {img_index+1} auf Seite {page_num+1}...")

                # Bildunterschrift und umgebender Text. Ohne sie sieht das
                # Sehmodell nur den freigeschnittenen Ausschnitt und beschreibt
                # Geometrie statt Bedeutung -- welche Groesse, welches
                # Regelwerk, welcher Zusammenhang steht ausserhalb des Bildes.
                try:
                    kontext = bild_kontext(page, bbox, dateiname, page_num + 1)
                except Exception:
                    kontext = f"Abbildung aus {dateiname}, Seite {page_num + 1}"

                # Bild extrahieren
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                # --- NEU: BILD-OPTIMIERUNG MIT PILLOW ---
                try:
                    # Bild in den Arbeitsspeicher laden
                    image = Image.open(io.BytesIO(image_bytes))
                    width, height = image.size
                    
                    # 1. GRÖSSENFILTER: Kleine Grafiken überspringen
                    #    (Logos, Icons, Trennlinien)
                    #
                    # Bewusst NICHT "width < 400 or height < 400": technische
                    # Dokumente enthalten viele breite, flache Detailzeichnungen.
                    # Eine Mindestgröße auf BEIDEN Kanten verwirft davon einen
                    # erheblichen Teil als "Logo".
                    # Lange Kante + Fläche trifft Logos, behält aber Zeichnungen.
                    if max(width, height) < MIN_LONG_EDGE or width * height < MIN_AREA:
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
                    vision_response = vision_client.chat.completions.create(
                        model=VISION_MODEL,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": VISION_PROMPT + KONTEXT_ZUSATZ.format(kontext=kontext)},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ]
                            }
                        ]
                    )
                    
                    bild_beschreibung = vision_response.choices[0].message.content
                    
                    # Den Text für den Chat-Kontext aufbereiten
                    # Der Kontext steht mit im Chunk, nicht nur im Prompt: er
                    # ist der Suchanker. Eine reine Geometriebeschreibung
                    # trifft keine Fachfrage -- dieselbe Erfahrung wie bei den
                    # Tabellen, wo die Zeile ueber der Tabelle der wirksamste
                    # Anker im Korpus ist.
                    finaler_text = ("KONTEXT ZUM BILD: " + kontext + "\n\n"
                                    "[BILD-BESCHREIBUNG]: " + str(bild_beschreibung))
                    
                    # 2. Beschreibung vektorisieren
                    vector = get_embedding(finaler_text)
                    
                    # 3. Als neuen Chunk in ChromaDB speichern (mit speziellem Typ "image")
                    #
                    # access/owner MÜSSEN gesetzt sein: die Vektorsuche filtert
                    # mit {"$or": [{"access": ...}, {"owner": ...}]}. Chunks ohne
                    # diese Keys matchen nie und sind damit unsichtbar.
                    bild_meta = {"file_name": dateiname, "page": page_num + 1,
                                 "folder": ordner, "access": "shared",
                                 "owner": "system", "source": "uploaded_pdfs",
                                 "type": "image"}
                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[finaler_text],
                        # access/owner MÜSSEN gesetzt sein: die Vektorsuche filtert
                        # mit {"$or": [{"access": ...}, {"owner": ...}]}. Chunks ohne
                        # diese Keys matchen nie und sind damit unsichtbar -- in der
                        # diese Keys matchen nie und sind damit unsichtbar.
                        metadatas=[bild_meta]
                    )
                    keyword_index.add_chunks(
                        [(chunk_id, finaler_text, bild_meta)], con=kw)
                except Exception as e:
                    print(f"   [!] Fehler bei der Bildanalyse auf Seite {page_num+1}: {e}")
                    
        print(f"✅ FERTIG mit '{dateiname}'. Insgesamt {images_found} Bilder gefunden.")
        
    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}")

kw.close()

# --- VRAM CLEANUP ---
print("\nGebe VRAM frei...")
try:
    client.embeddings.create(
        input=["Cleanup"], model=EMBEDDING_MODEL, encoding_format="float",
        extra_body={"drop_params": True, "keep_alive": 0}
    )
except Exception:
    # Das Freigeben des VRAM ist optional. Ein Fehler an dieser Stelle
    # darf einen abgeschlossenen Ingest nicht als gescheitert ausweisen.
    pass

print("🚀 ALLE BILDER SIND INDEXIERT!")