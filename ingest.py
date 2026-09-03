"""Batch-Vektorisierung der PDFs aus data/dokumente.

Verarbeitet Tabellen und Fliesstext getrennt: Tabellen werden als ein
unzerteilter Chunk mit der Bildunterschrift darueber abgelegt und
anschliessend aus dem Seitentext geschwaerzt, damit sie nicht ein zweites
Mal als zerlaufener Fliesstext im Index landen.

Der Lauf ist unterbrechbar und setzt auf Seiten-Ebene wieder auf: er beginnt
bei der zuletzt geschriebenen Seite, nicht bei der ersten. Alles davor ist
abgeschlossen.

Das Wiederaufsetzen auf Datei-Ebene waere gefaehrlich -- ein mitten in einem
Dokument abgebrochener Lauf haette es beim naechsten Start als erledigt
betrachtet und die fehlenden Seiten nie nachgetragen. Auf Seiten-Ebene
entfaellt das, und zugleich muss nicht jedes Mal das gesamte Dokument erneut
durch die Tabellenerkennung.

Innerhalb der begonnenen Seite entscheidet weiterhin die Chunk-ID: was schon
in der Datenbank steht, wird nicht erneut vektorisiert.
"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import re

import paths
import store
import keyword_index
import llm
from embedding import embed_batch
from textutils import strip_boilerplate
from tables import build_table_chunks, table_caption
import lesen

print("Starte Batch-Hintergrund-Vektorisierung...")

# --- KONFIGURATION ---
paths.bootstrap()
ORDNER_NAME = paths.DOCS_DIR
EMBEDDING_MODEL = llm.modell("EMBEDDING")
client = llm.client("EMBEDDING")

collection = store.collection()
kw = keyword_index.connect()

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

# Rekursiv, damit Unterordner als Sachgebiet dienen koennen (siehe
# folder_of), und unabhaengig von der Gross-/Kleinschreibung der Endung.
dokumente = paths.dokument_dateien(ORDNER_NAME)

if not dokumente:
    print(f"Keine PDFs in '{ORDNER_NAME}' gefunden.")
    raise SystemExit(0)

print(f"Insgesamt {len(dokumente)} Dokumente gefunden. "
      f"Starte Verarbeitung...\n")


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


def letzte_seite(dateiname, bekannt):
    """Hoechste Seitenzahl, zu der bereits Chunks vorliegen.

    Alles davor ist abgeschlossen und muss nicht erneut gelesen werden. Die
    Textextraktion selbst ist zwar schnell, die Tabellenerkennung aber nicht:
    ohne diese Abkuerzung laeuft find_tables ueber jede Seite des Dokuments,
    auch wenn nur eine Handvoll Chunks nachzutragen ist. Bei einem Bestand von
    13.598 Seiten dauert das eine halbe Stunde, in der nichts entsteht.

    Bewusst die hoechste Seite und nicht die Menge der bekannten Seiten:
    Zwischenspeicherung erfolgt alle 256 Chunks, sodass die zuletzt
    geschriebene Seite mitten in der Verarbeitung stehen kann. Alles davor ist
    sicher vollstaendig -- diese eine Seite wird erneut gelesen.
    """
    hoechste = 0
    vorspann = dateiname + "_p"
    for cid in bekannt:
        if not cid.startswith(vorspann):
            continue
        rest = cid[len(vorspann):]
        ziffern = rest.split("_", 1)[0]
        if ziffern.isdigit():
            hoechste = max(hoechste, int(ziffern))
    return hoechste


# Ein Text-Chunk gilt als reine Kopfzeile, wenn er kurz ist UND sein Inhalt
# bereits in einer Tabellen-Ueberschrift derselben Seite steht. Beide
# Bedingungen zusammen: die Laenge allein wuerde auch echte kurze Absaetze
# treffen, die Enthaltensein-Pruefung allein auch laengeren Fliesstext, der
# eine Ueberschrift zufaellig zitiert.
MAX_KOPFZEILE_CHARS = paths.env_int("MAX_KOPFZEILE_CHARS", 200)


def _vergleichsform(text):
    """Kleinschreibung, ohne Ziffern und Sonderzeichen -- damit die gedruckte
    Seitenzahl den Vergleich nicht verhindert."""
    return " ".join(re.sub(r"[^a-zA-ZäöüÄÖÜß ]", " ", text).lower().split())


def ist_nur_ueberschrift(chunk, ueberschriften):
    if not ueberschriften or len(chunk) > MAX_KOPFZEILE_CHARS:
        return False
    kern = _vergleichsform(chunk)
    if len(kern) < 10:
        return True
    return any(kern in _vergleichsform(u) for u in ueberschriften)


# Ueber den ganzen Lauf mitgezaehlt: bei tausenden Seiten geht eine einzelne
# Fehlermeldung in der Ausgabe unter, und das Ergebnis waere eine
# Wissensbasis mit Luecken, von denen niemand weiss.
uebersprungen = []


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
        fehlend = [ids[i] for i in range(len(ids)) if vectors[i] is None]
        uebersprungen.extend(fehlend)
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
for pdf_pfad in dokumente:
    dateiname = os.path.basename(pdf_pfad)
    ordner = folder_of(pdf_pfad)

    bekannt = existing_chunk_ids(dateiname)
    ab_seite = letzte_seite(dateiname, bekannt)

    print(f"⏳ VERARBEITE: '{dateiname}' [{ordner}]"
          + (f" -- {len(bekannt)} Chunks vorhanden, weiter ab Seite {ab_seite}"
             if bekannt else ""))

    # --- WORD, MARKDOWN, TEXT ---
    #
    # Diese Formate haben keine Seiten und keine Tabellenflaechen. Ein
    # Abschnitt tritt an die Stelle einer Seite: gezaehlt, in den Metadaten,
    # in der Quellenangabe. Der Wiederanlauf ueber bekannte Chunk-IDs
    # funktioniert dabei unveraendert.
    if lesen.unterstuetzt(dateiname):
        try:
            pending, neu = [], 0
            for nummer, _titel, text in lesen.abschnitte(pdf_pfad):
                basis_meta = {"file_name": dateiname, "page": nummer,
                              "folder": ordner, "access": "shared",
                              "owner": "system"}
                for i, chunk in enumerate(text_splitter.split_text(text)):
                    chunk_id = f"{dateiname}_p{nummer}_c{i}"
                    if chunk_id not in bekannt:
                        pending.append((chunk_id, chunk,
                                        dict(basis_meta, type="text")))
                if len(pending) >= 256:
                    neu += flush(pending, dateiname)
                    pending = []
            neu += flush(pending, dateiname)
            if neu:
                print(f"✅ ABGESCHLOSSEN: '{dateiname}' -- {neu} neue Chunks.\n")
            else:
                print(f"⏩ ÜBERSPRUNGEN: '{dateiname}' war bereits "
                      f"vollständig.\n")
        except Exception as e:
            print(f"❌ FEHLER beim Lesen von '{dateiname}': {e}\n")
        continue

    try:
        doc = pymupdf.open(pdf_pfad)
        total_pages = len(doc)
        pending = []
        neu = 0

        for page_num in range(total_pages):
            # Seiten vor der zuletzt geschriebenen sind abgeschlossen. Der
            # Sprung spart die Tabellenerkennung, nicht nur das Einlesen.
            if page_num + 1 < ab_seite:
                continue

            page = doc[page_num]
            basis_meta = {"file_name": dateiname, "page": page_num + 1,
                          "folder": ordner, "access": "shared",
                          "owner": "system"}

            # --- TABELLEN ISOLIEREN UND ANREICHERN ---
            ueberschriften = []
            tables = page.find_tables()
            for i, table in enumerate(tables):
                try:
                    # Ueberschrift voranstellen und uebergrosse Tabellen
                    # aufteilen -- siehe tables.py. Bleibt eine Tabelle unter
                    # dem Limit, ist die Chunk-ID unveraendert.
                    ueberschriften.append(
                        table_caption(page, table, dateiname, page_num + 1))
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
                    # Auf Anhangseiten bleibt nach dem Schwaerzen der Tabelle
                    # oft nur die laufende Kopfzeile uebrig -- Normbezeichnung
                    # und Tabellentitel, ohne einen einzigen Wert. Weil BM25
                    # auf Laenge normalisiert, rankt so ein Chunk ueber der
                    # Tabelle, die er benennt, und belegt deren Platz.
                    #
                    # Seit die Tabelle ihre Ueberschrift selbst traegt, steht
                    # sein gesamter Inhalt bereits in dem Chunk, mit dem er
                    # konkurriert. Er transportiert nichts Eigenes mehr.
                    if ist_nur_ueberschrift(chunk, ueberschriften):
                        continue
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

if uebersprungen:
    print()
    print(f"⚠️  {len(uebersprungen)} Chunks konnten NICHT vektorisiert werden "
          f"und fehlen in der Wissensbasis.")
    print("   Haeufigste Ursache: der Chunk ueberschreitet das Kontextfenster "
          "des Embedding-Servers.")
    print("   Dann MAX_TABLE_CHARS verkleinern und ingest.py erneut starten --"
          " vorhandene Chunks werden uebersprungen.")
    for cid in uebersprungen[:10]:
        print(f"     {cid}")
    if len(uebersprungen) > 10:
        print(f"     ... und {len(uebersprungen) - 10} weitere")
else:
    print("🚀 FERTIG! Alle Dokumente sind in der Datenbank.")
