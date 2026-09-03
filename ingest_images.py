import pymupdf
import os
import base64
from PIL import Image
import io
import time
from concurrent.futures import ThreadPoolExecutor

import paths
import store
import keyword_index
import llm
from embedding import embed_batch
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

# Gleichzeitig laufende Bildanalysen.
#
# Eine Beschreibung dauert bei einem lokalen Sehmodell rund eine Minute, und
# der Prozess wartet dabei ausschliesslich auf Antwort. Mehrere offene
# Anfragen lassen den Modellserver sie zusammen abarbeiten und seine
# Grafikkarten auslasten -- die Beschleunigung entsteht dort, nicht hier.
#
# Die sinnvolle Obergrenze richtet sich nach dem Server: zu viele gleichzeitige
# Anfragen erzeugen dort nur eine Warteschlange oder Zeitueberschreitungen.
# 1 stellt das fruehere Verhalten her.
VISION_PARALLEL = max(1, paths.env_int("VISION_PARALLEL", 4))

# Wiederholungen bei voruebergehenden Fehlern des Modellservers.
#
# Beobachtet im Betrieb: "Cannot connect to host", 504 vom vorgeschalteten
# nginx, Zeitueberschreitungen. Solche Ausfaelle treffen einzelne Anfragen,
# nicht den Lauf -- ohne Wiederholung waeren die betroffenen Bilder in diesem
# Durchgang verloren und muessten ueber einen erneuten Start nachgeholt werden.
VISION_VERSUCHE = max(1, paths.env_int("VISION_VERSUCHE", 3))
VISION_WARTEN = paths.env_float("VISION_WARTEN", 5)

# Zeitlimit je Bildanfrage.
#
# Ohne Angabe wartet der Client den Standard von 600 Sekunden ab. Ist der
# Sehmodell-Server nicht erreichbar, steht der Lauf damit zehn Minuten je
# Buendel still, ohne eine Zeile auszugeben -- von aussen nicht von einem
# Absturz zu unterscheiden. Eine Minute reicht fuer eine Bildbeschreibung
# reichlich; laenger heisst, dass etwas nicht stimmt.
VISION_TIMEOUT = paths.env_float("VISION_TIMEOUT", 120)

client = llm.client("EMBEDDING")

def get_embedding(text, model=EMBEDDING_MODEL):
    """Vektorisiert die Bildbeschreibung.

    Ueber embed_batch, damit hier dieselbe Behandlung greift wie im Textlauf:
    Zeitlimit, Kuerzung bei zu langem Text und Einzel-Rueckfall. Der eigene
    Aufruf hatte keines davon -- eine haengende Anfrage blockierte den Strang
    bis zum Standard von 600 Sekunden.
    """
    return embed_batch(client, [text], model)[0]

# Bewusst ohne Anlegen: eine frisch erzeugte, leere Sammlung waere
# hier kein Ausgangspunkt, sondern ein Hinweis auf den falschen Pfad.
collection = store.collection(anlegen=False)
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

def beschreibe(aufgabe):
    """Bildbeschreibung und Vektor zu einer Aufgabe.

    Laeuft in einem eigenen Strang und fasst nichts an, was sich mehrere
    teilen -- weder die Datenbank noch den Keyword-Index. Zurueck kommt nur
    das Ergebnis; geschrieben wird spaeter im Hauptstrang.
    """
    chunk_id, image_url, kontext, meta = aufgabe
    for versuch in range(1, VISION_VERSUCHE + 1):
        try:
            return _einmal_beschreiben(chunk_id, image_url, kontext, meta)
        except Exception as e:
            if versuch >= VISION_VERSUCHE or not _voruebergehend(e):
                print(f"   [!] Bildanalyse fehlgeschlagen ({chunk_id}): "
                      f"{str(e)[:160]}")
                fehlgeschlagen.append(chunk_id)
                return None
            # Ansteigend warten: ist der Dienst gerade am Neustarten, hilft
            # ein sofortiger zweiter Versuch nicht.
            time.sleep(VISION_WARTEN * versuch)
    return None


def _voruebergehend(e):
    """Unterscheidet einen Ausfall des Dienstes von einer schlechten Anfrage.

    Bei 500, 502, 504, einem abgelehnten Verbindungsaufbau oder einer
    Zeitueberschreitung lohnt ein zweiter Versuch. Bei einer abgelehnten
    Anfrage -- etwa einem zu grossen Bild -- nicht.
    """
    t = str(e).lower()
    return any(w in t for w in (
        "cannot connect", "connection", "timed out", "timeout",
        "500", "502", "503", "504", "gateway", "unavailable",
        "internalservererror",
        # Eine leere Antwort kommt meist von einem Dienst, der gerade nicht
        # bei sich ist -- ein zweiter Versuch lohnt.
        "keine beschreibung"))


def _einmal_beschreiben(chunk_id, image_url, kontext, meta):
    """Ein einzelner Versuch. Fehler gehen an beschreibe() zurueck."""
    antwort = vision_client.chat.completions.create(
        model=VISION_MODEL,
        timeout=VISION_TIMEOUT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": VISION_PROMPT + KONTEXT_ZUSATZ.format(kontext=kontext)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
    )
    beschreibung = (antwort.choices[0].message.content or "").strip()

    # Eine leere Antwort ist kein Ergebnis. Ohne diese Pruefung landete
    # "[BILD-BESCHREIBUNG]: None" als Chunk im Index -- vektorisiert,
    # durchsuchbar und wertlos. Beobachtet an einem Endpunkt, der eine
    # Anfrage nach vier Sekunden als erfolgreich zurueckgab, waehrend ein
    # echter Durchlauf desselben Bildes Minuten braucht.
    if not beschreibung:
        raise ValueError("Sehmodell: keine Beschreibung erhalten.")

    # Der Kontext steht mit im Chunk, nicht nur im Prompt: er ist der
    # Suchanker. Eine reine Geometriebeschreibung trifft keine Fachfrage --
    # dieselbe Erfahrung wie bei den Tabellen, wo die Zeile ueber der
    # Tabelle der wirksamste Anker im Korpus ist.
    text = ("KONTEXT ZUM BILD: " + kontext + chr(10) + chr(10) +
            "[BILD-BESCHREIBUNG]: " + beschreibung)
    return chunk_id, text, get_embedding(text), meta


def verarbeite(aufgaben):
    """Beschreibt eine Reihe von Bildern gleichzeitig und speichert sie."""
    if not aufgaben:
        return 0
    if VISION_PARALLEL <= 1:
        ergebnisse = [beschreibe(a) for a in aufgaben]
    else:
        with ThreadPoolExecutor(max_workers=VISION_PARALLEL) as pool:
            ergebnisse = list(pool.map(beschreibe, aufgaben))
    return schreibe(ergebnisse)


def schreibe(ergebnisse):
    """Speichert die fertigen Beschreibungen -- nur aus dem Hauptstrang.

    ChromaDB und der Keyword-Index vertragen keine gleichzeitigen Schreiber,
    deshalb sammelt der Lauf die Ergebnisse und legt sie gebuendelt ab. Das
    spart nebenbei eine Datenbankabfrage je Bild.
    """
    fertig = [e for e in ergebnisse if e]
    if not fertig:
        return 0
    collection.add(
        ids=[e[0] for e in fertig],
        embeddings=[e[2] for e in fertig],
        documents=[e[1] for e in fertig],
        metadatas=[e[3] for e in fertig],
    )
    keyword_index.add_chunks([(e[0], e[1], e[3]) for e in fertig], con=kw)

    # Erfolge gehoerten bisher nicht ins Protokoll -- nur Fehlschlaege. Damit
    # liess sich aus dem Log nicht ablesen, ob ueberhaupt etwas ankommt; die
    # einzige Auskunft war die Zahl der Abschnitte in der Datenbank.
    print(f"   [+] {len(fertig)} von {len(ergebnisse)} Bildern gespeichert: "
          + ", ".join(e[0] for e in fertig), flush=True)
    return len(fertig)


# Bereits verarbeitete Bild-Referenzen ueber das gesamte Dokument.
#
# Manche PDFs teilen sich ein gemeinsames Ressourcen-Verzeichnis: dann meldet
# JEDE Seite saemtliche Bilder des Dokuments. Beobachtet an einem Handbuch mit
# 7833 Seiten, das auf jeder Seite dieselben 2040 Bilder auswies -- ohne
# Entdopplung waeren das 16 Millionen Durchlaeufe und jeder Screenshot 7833-mal
# in der Datenbank.
gesehene_bilder = set()

# Bilder, die auch nach allen Versuchen keine Beschreibung bekommen haben.
# Ein erneuter Start holt sie nach -- ihre Chunk-IDs stehen ja nicht in der
# Datenbank -- aber das muss jemand wissen.
fehlgeschlagen = []


# --- VERARBEITUNG ---
for pdf_pfad in pdf_dateien:
    dateiname = os.path.basename(pdf_pfad)
    ordner = folder_of(pdf_pfad)
    print(f"\n⏳ Durchsuche '{dateiname}' nach Bildern...")
    
    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        images_found = 0
        # Bereits beschriebene Bilder werden uebersprungen. Ohne Zaehler
        # schweigt das Protokoll darueber, und die Rechnung "gefunden minus
        # verworfen" ergibt scheinbar zu wenige Bilder -- genau so haben wir
        # einen fehlerfreien Lauf fuer kaputt gehalten.
        bereits_da = 0
        gespeichert = 0
        aufgaben = []
        
        # Lebenszeichen. Ohne das meldet sich der Lauf nur, wenn zufaellig
        # ein Bild gefunden wird -- in einem Handbuch mit tausenden Seiten
        # koennen dazwischen viertelstundenlang bildfreie Seiten liegen, und
        # ein arbeitender Lauf sieht dann aus wie ein haengender.
        MELDE_ALLE = paths.env_int("SEITEN_MELDUNG", 100)

        for page_num in range(total_pages):
            if MELDE_ALLE and page_num and page_num % MELDE_ALLE == 0:
                print(f"   ... Seite {page_num} von {total_pages}, "
                      f"{images_found} Bilder bisher, {bereits_da} davon "
                      f"schon beschrieben", flush=True)
            page = doc[page_num]

            # Torwaechter: steht auf dieser Seite ueberhaupt ein Bild?
            #
            # get_images() liefert das Ressourcen-Verzeichnis. Teilt sich ein
            # PDF eines fuer alle Seiten, sind das jedes Mal saemtliche Bilder
            # des Dokuments -- bei einem Handbuch mit 7833 Seiten 2040 Stueck
            # je Seite, fuer die anschliessend je ein get_image_bbox() faellig
            # waere. Gemessen: 31 Seiten pro Minute, fast alles davon fuer
            # Bilder, die gar nicht auf der Seite stehen.
            #
            # get_image_info() liest stattdessen den Seiteninhalt und nennt
            # nur die tatsaechlichen Platzierungen. Ist die Liste leer, kann
            # auch kein Eintrag des Verzeichnisses auf dieser Seite stehen.
            # Gemessen: 47000 Seiten pro Minute.
            #
            # Bewusst nur als Frage benutzt, nicht als Quelle: auf einigen
            # Seiten nennt get_image_info eine andere xref als das
            # Verzeichnis, und der Index im Verzeichnis steckt in der
            # chunk_id. Wer die Bilder von dort naehme, veraenderte die IDs
            # und machte die bereits beschriebenen Bilder zu Dubletten.
            if not page.get_image_info():
                continue

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
                    bereits_da += 1
                    continue  # schon beschrieben, aus einem frueheren Lauf

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
                # access/owner MUESSEN gesetzt sein: die Vektorsuche filtert
                # ueber diese Keys -- fehlen sie, matcht ein Chunk nie.
                bild_meta = {"file_name": dateiname, "page": page_num + 1,
                             "folder": ordner, "access": "shared",
                             "owner": "system", "source": "uploaded_pdfs",
                             "type": "image"}
                aufgaben.append((chunk_id, image_url, kontext, bild_meta))

                # Ein Vielfaches der Strangzahl, damit beim Schreiben keine
                # Luecke entsteht, in der niemand mehr auf den Server wartet.
                if len(aufgaben) >= VISION_PARALLEL * 3:
                    gespeichert += verarbeite(aufgaben)
                    aufgaben = []

        gespeichert += verarbeite(aufgaben)
        aufgaben = []
        print(f"FERTIG mit '{dateiname}': {images_found} Bilder gefunden, "
              f"{gespeichert} neu beschrieben, {bereits_da} schon vorhanden.")
        
    except Exception as e:
        print(f"❌ FEHLER beim Öffnen von '{dateiname}': {e}")

kw.close()

if fehlgeschlagen:
    print()
    print(f"[!] {len(fehlgeschlagen)} Bilder ohne Beschreibung. Haeufigste "
          f"Ursache: der Sehmodell-Server war zeitweise nicht erreichbar.")
    print("    Ein erneuter Start von ingest_images.py holt sie nach; "
          "bereits beschriebene Bilder werden uebersprungen.")
    print("    Haeufen sich die Ausfaelle, VISION_PARALLEL verkleinern.")
    for cid in fehlgeschlagen[:10]:
        print(f"      {cid}")
    if len(fehlgeschlagen) > 10:
        print(f"      ... und {len(fehlgeschlagen) - 10} weitere")

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