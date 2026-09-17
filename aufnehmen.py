"""Ein Dokument aufnehmen -- fuer beide Eingaenge derselbe Weg.

Lesen, Tabellen abtrennen, Abbildungen beschreiben lassen,
vektorisieren, in beide Indizes schreiben und die Datei ablegen --
lokal und, wenn eingerichtet, in ownCloud.

WARUM EIGEN: das stand in app.py, und app.py importiert streamlit.
Damit war dieser Weg weder von der Schnittstelle noch vom Selbsttest
erreichbar -- ein Masseningest ueber HTTP war nicht moeglich, und die
teuerste Funktion der Anwendung war zugleich die einzige ungetestete.

Herausgeloest wurde verbatim. Gebraucht wurden vierzehn Namen aus
app.py, davon acht aus streamlit: sechsmal der Benutzername aus dem
Sitzungszustand, einmal eine Fortschrittszeile, einmal eine Warnung.
Sie sind jetzt Parameter. Vom Dateiobjekt braucht die Funktion .name
und .getvalue() -- mehr nicht, weshalb ein Upload aus der Oberflaeche
und einer aus einer HTTP-Anfrage hier ununterscheidbar sind.

DER EINE UNTERSCHIED zwischen den Eingaengen steht in `streng`. Ein
Raum, in den der Nutzer nicht schreiben darf, wurde bisher still durch
seinen eigenen ersetzt. In der Oberflaeche ist das freundlich: man
sieht, wo es gelandet ist. Ueber HTTP waere es falsch -- ein Stapel von
200 Dokumenten laege vollstaendig woanders, und die Antwort hiesse
200 OK. Deshalb dort streng=True und eine Abweisung.
"""
import os
import re

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter

import keyword_index
import lesen
import llm
import paths
import raeume
import store
from embedding import embed_batch
from tables import build_table_chunks
from textutils import strip_boilerplate

DOCS_DIR = paths.DOCS_DIR
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500,
                                               chunk_overlap=200)
embed_client = llm.client("EMBEDDING")


class KeinRecht(Exception):
    """Der Nutzer darf in diesen Raum nicht schreiben.

    Gibt es nur mit streng=True. Die Oberflaeche weicht stattdessen auf
    den eigenen Raum aus, weil man dort sieht, wo etwas gelandet ist.
    """


def raum_sammlung(kennung, anlegen=True):
    """Die Sammlung eines Raums."""
    return store.sammlung(raeume.sammlung(kennung), anlegen=anlegen)

def _alle_raum_sammlungen():
    """[(raum, sammlung)] ueber ALLE Raeume -- nur fuer den Indexaufbau.

    Nicht fuer die Suche: dort entscheidet die Berechtigung, welche
    Sammlungen gefragt werden. Der Stichwortindex dagegen enthaelt alles
    und filtert beim Lesen.
    """
    paare = []
    for kennung in raeume.liste():
        sml = raum_sammlung(kennung, anlegen=False)
        if sml is not None:
            paare.append((kennung, sml))
    return paare

def _gehoert_anderem_raum(filename, raum):
    """Fuehrt ein ANDERER Raum bereits ein Dokument dieses Namens?

    Gefragt vor dem Ueberschreiben im gemeinsamen Wurzelbereich. Bei einer
    Sammlung, die nicht antwortet, lautet die Antwort ja: dann wird
    ausgewichen statt ueberschrieben. Ein ueberfluessiges 'Angebot (2).pdf'
    ist ein Schoenheitsfehler, ein ueberschriebenes Dokument nicht.
    """
    for k, sml in _alle_raum_sammlungen():
        if k == raum:
            continue
        try:
            if sml.get(where=store.datei_filter(filename),
                       include=[])["ids"]:
                return True
        except Exception:
            return True
    return False

def _speichern_chunks(chunks, metadatas, ids, raum,
                      nach_dem_schreiben=None):
    """Vektorisiert die Abschnitte und legt sie in beiden Indizes ab.

    Herausgeloest, weil beide Wege sie brauchen -- der ueber pymupdf
    fuer PDFs und der ueber lesen.py fuer Word und Markdown. Zweimal
    geschrieben waere es die Sorte Verdopplung, bei der eine Haelfte
    irgendwann nachgezogen wird und die andere nicht.
    """
    if not chunks:
        # Kein einziger Abschnitt. Bei einem PDF heisst das fast immer:
        # gescannt, ohne Textebene. Frueher endete die Funktion hier
        # stillschweigend, und die Oberflaeche meldete trotzdem
        # "hinzugefuegt" -- die Datei lag danach auf der Platte, in
        # keiner Sammlung und in keiner Indexzeile. Auffallen konnte das
        # erst, wenn jemand danach suchte und nichts fand.
        return 0, ("Kein Text gefunden. Bei einem PDF heisst das meist: "
                   "es ist ein Scan ohne Textebene. Ein solches Dokument "
                   "muss durch eine Texterkennung, bevor es durchsuchbar "
                   "wird -- oder ueber ingest_images.py als Abbildung "
                   "beschrieben werden.")
    # Gebuendelt vektorisieren -- vorher ging pro Chunk eine eigene
    # HTTP-Anfrage an den Modellserver.
    embeddings = embed_batch(embed_client, chunks, llm.modell("EMBEDDING"))

    keep = [i for i, v in enumerate(embeddings) if v is not None]
    if not keep:
        grund = getattr(embed_batch, "letzter_fehler", None)
        return 0, ("Kein Abschnitt liess sich vektorisieren -- der "
                   "Modellserver hat nichts geliefert."
                   + (f" ({type(grund).__name__}: {grund})" if grund else ""))

    # store.schreibe statt add: ein grosses Dokument kann in einem Aufruf
    # die Groessengrenze des Chroma-Servers ueberschreiten -- gegen eine
    # Dateiablage faellt das nie auf, ueber HTTP schon.
    store.schreibe(
        raum_sammlung(raum),
        [ids[i] for i in keep],
        documents=[chunks[i] for i in keep],
        metadatas=[metadatas[i] for i in keep],
        embeddings=[embeddings[i] for i in keep],
    )
    # Beide Indizes im selben Schritt fuellen, damit Vektor- und
    # Keyword-Suche nie auseinanderlaufen.
    keyword_index.add_chunks(
        ((ids[i], chunks[i], metadatas[i]) for i in keep))
    if nach_dem_schreiben:
        nach_dem_schreiben()
    fehlend = len(chunks) - len(keep)
    return len(keep), (f"{fehlend} von {len(chunks)} Abschnitten liessen "
                       f"sich nicht vektorisieren und fehlen."
                       if fehlend else "")

def process_uploaded_pdf(uploaded_file, raum, projekt="",
                         bilder=False, *, benutzer_,
                         ist_verwalter=False, streng=False,
                         fortschritt=None,
                         nach_dem_schreiben=None):
    """Liest ein Dokument ein, speichert es dauerhaft, isoliert Tabellen und
    vektorisiert beides.

    raum bestimmt, in welche Sammlung die Abschnitte gehen -- und damit,
    wer sie sehen kann -- und das ist die einzige Einteilung, die es
    noch gibt. Sachgebiete sind entfallen: ein Sachgebiet war ein
    Unterordner, der die Suche einschraenkte, ohne ein Recht zu sein. Zwei
    Filter, von denen der eine aussieht wie der andere und keine Grenze
    zieht, sind einer zu viel.

    Rueckgabe: (geschriebene Abschnitte, Hinweis). 0 heisst, dass nichts
    gespeichert wurde -- der Hinweis sagt warum. Die Oberflaeche muss das
    auswerten: vorher meldete sie in jedem Fall "hinzugefuegt", und ein
    Scan ohne Textebene lag danach auf der Platte, aber in keiner
    Sammlung.
    """
    # Die Ablage entscheidet sich hier und nicht in der Oberflaeche: ein
    # Raum, in den dieser Nutzer nicht schreiben darf, wird durch den
    # eigenen ersetzt statt abgewiesen. Das ist die Stelle, an der das
    # Recht wirklich haengt -- die Oberflaeche bietet nur an.
    # streng=True weist ab, statt auszuweichen -- siehe Modulkopf.
    if raum not in raeume.schreibbar(benutzer_, ist_verwalter):
        if streng:
            raise KeinRecht(
                f"'{benutzer_}' darf nicht in den Raum '{raum}' schreiben.")
        raum = raeume.sichere_anlage_privat(benutzer_)
    
    # 1. PDF DAUERHAFT SPEICHERN anstatt es wegzuwerfen
    #
    # In den Ordner des RAUMS. Der Grund ist ein Datenverlust: bis
    # hierher ging jeder Upload nach data/dokumente/<name>, gleich in
    # welchen Raum seine Abschnitte gingen. Lud jemand eine 'Angebot.pdf'
    # hoch, die es in einem anderen Raum schon gab, wurde die dortige
    # Datei ueberschrieben -- ohne Warnung, und die Abschnitte des
    # anderen Raums zeigten danach auf einen fremden Inhalt.
    #
    # Der allgemeine Raum behaelt den Wurzelbereich: dort liegt der
    # bestehende Bestand, und ein Ingest ueber data/dokumente soll ihn
    # weiter als "(Basis)" und nicht als Sachgebiet "allgemein" sehen.
    dateiname = paths.sicherer_dateiname(uploaded_file.name)
    ziel_ordner = (DOCS_DIR if raum == raeume.ALLGEMEIN
                   else paths.raum_ordner(raum))
    # Ein Projektordner sortiert innerhalb des Raums. Der Name wird
    # entschaerft, nicht abgelehnt: wer "Angebot / Meier" tippt, meint
    # einen Ordner und keinen Pfad.
    projekt = re.sub(r"[^0-9A-Za-zäöüÄÖÜß _-]", "", str(projekt or "")).strip()
    if projekt:
        ziel_ordner = os.path.join(ziel_ordner, projekt)
    os.makedirs(ziel_ordner, exist_ok=True)

    # Im Wurzelbereich kann trotzdem noch etwas im Weg liegen -- eine
    # Datei aus der Zeit vor den Raeumen, die einem anderen Raum gehoert.
    # Dann ausweichen statt ueberschreiben. Der Hinweis nennt keinen Raum:
    # dass eine Datei dieses Namens existiert, ist schon genug Auskunft.
    pdf_path = os.path.join(ziel_ordner, dateiname)
    name_hinweis = ""
    if os.path.exists(pdf_path) and _gehoert_anderem_raum(dateiname, raum):
        pdf_path = paths.freier_name(ziel_ordner, dateiname)
        dateiname = os.path.basename(pdf_path)
        name_hinweis = (f"Eine Datei dieses Namens liegt bereits in der "
                        f"Ablage und gehoert nicht zu diesem Raum. "
                        f"Gespeichert als '{dateiname}'.")

    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getvalue())

    # UND nach ownCloud, wenn der Raum dort einen Ordner hat.
    #
    # Die lokale Kopie bleibt: der Ingest liest sie, die Quellenansicht
    # zeigt sie, und ein spaeterer Abgleich wuerde sie ohnehin wieder
    # herunterladen. Sie ist die Arbeitskopie, nicht die Ablage.
    #
    # Scheitert das Ablegen, ist der Upload trotzdem nutzbar -- er ist
    # nur nicht dort, wo der Nutzer ihn erwartet. Das muss er erfahren,
    # sonst sucht er ihn spaeter in ownCloud und findet nichts.
    wolke_hinweis = ""
    try:
        import owncloud
        if owncloud.eingerichtet():
            # Der Pfad RELATIV zur Ablage des Raums und nicht der
            # blosse Dateiname: sonst faellt der Projektordner weg und
            # in ownCloud liegt alles flach nebeneinander. Das Projekt
            # ist dann nur noch in den Metadaten -- also nirgends, wo
            # jemand es sieht.
            #
            # Und ordner_fuer statt raum_pfad: der Abgleich liest von
            # dort. Wer eine Handzuordnung eingetragen hat, schriebe
            # sonst woanders hin, als spaeter gelesen wird.
            ok_oc, meldung_oc = owncloud.lege_ab(
                pdf_path, owncloud.ziel_pfad(raum, pdf_path))
            if not ok_oc:
                wolke_hinweis = f"Nicht in ownCloud abgelegt: {meldung_oc}"
    except Exception as e:
        wolke_hinweis = f"Nicht in ownCloud abgelegt: {e}"

    chunks = []
    metadatas = []
    ids = []

    # --- WORD, MARKDOWN, TEXT ---
    #
    # Ohne Seiten und ohne Tabellenflaechen; ein Abschnitt tritt an die
    # Stelle einer Seite. Siehe lesen.py.
    if lesen.unterstuetzt(dateiname):
        for nummer, _titel, text in lesen.abschnitte(pdf_path):
            for i, chunk in enumerate(text_splitter.split_text(text)):
                chunks.append(chunk)
                metadatas.append({
                    "file_name": dateiname, "page": nummer,
                    "raum": raum, "folder": projekt,
                    "access": "shared" if raum == raeume.ALLGEMEIN
                              else "private",
                    "owner": benutzer_, "type": "text"})
                ids.append(f"{dateiname}_p{nummer}_c{i}")
        _n, _h = _speichern_chunks(chunks, metadatas, ids, raum,
                                   nach_dem_schreiben)
        return _n, " ".join(
            x for x in (_h, name_hinweis, wolke_hinweis) if x)

    doc = pymupdf.open(pdf_path)
    
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # --- 1. TABELLEN EXTRAHIEREN ---
        # Gleiche Aufbereitung wie im Batch-Ingest (tables.py): die Zeile
        # ueber der Tabelle wird vorangestellt, uebergrosse Tabellen werden
        # geteilt. Vorher stand hier nur "Tabelle von Seite N" ohne Kontext,
        # wodurch hochgeladene Dokumente schlechter auffindbar waren als die
        # per Skript eingelesenen.
        tables = page.find_tables()
        for i, table in enumerate(tables):
            for suffix, chunk_text in build_table_chunks(
                    page, table, dateiname, page_num + 1, i):
                chunks.append(chunk_text)
                metadatas.append({
                    "file_name": dateiname,
                    "page": page_num + 1,
                    "raum": raum,
                    "folder": projekt,
                    "owner": benutzer_,
                    "type": "table"
                })
                ids.append(f"{dateiname}_{suffix}")

            # Die Fläche der Tabelle für den normalen Text-Extraktor schwärzen
            page.add_redact_annot(table.bbox)
        
        # Schwärzungen anwenden (nur im RAM, die Originaldatei bleibt intakt)
        page.apply_redactions()
        
        # --- 2. RESTLICHEN TEXT EXTRAHIEREN ---
        text = strip_boilerplate(page.get_text())
        if text.strip(): # Nur wenn nach dem Schwärzen noch Text übrig ist
            splits = text_splitter.split_text(text)
            for i, split in enumerate(splits):
                chunks.append(split)
                metadatas.append({
                    "file_name": dateiname,
                    "page": page_num + 1,
                    "raum": raum,
                    "folder": projekt,
                    "owner": benutzer_,
                    "type": "text"
                })
                ids.append(f"{dateiname}_p{page_num+1}_text_{i}")
                
    # --- BILDER ---
    #
    # Zwei Faelle, die verschieden sind: eine gescannte Seite ohne
    # Textebene findet die Suche gar nicht -- nicht wenig, sondern
    # nichts. Eine Abbildung in einem Textdokument findet sie, nur
    # nicht das, was allein im Bild steht.
    #
    # Beides wird zu einem gewoehnlichen Abschnitt mit type="image".
    # Die Beschreibung ersetzt das Bild nicht, sie macht es
    # auffindbar.
    bild_hinweis = ""
    if bilder:
        try:
            import bildtext
            for _seite, _text, _art in bildtext.beschreibungen(
                    doc, dateiname, fortschritt):
                chunks.append(_text)
                metadatas.append({
                    "file_name": dateiname,
                    "page": _seite,
                    "raum": raum,
                    "folder": projekt,
                    "owner": benutzer_,
                    # Die Art steht mit drin: bei einer gescannten
                    # Seite IST die Beschreibung der Inhalt, bei einer
                    # Abbildung ergaenzt sie den Text daneben. Wer
                    # spaeter nachsieht, woher eine Auskunft kommt,
                    # soll den Unterschied sehen.
                    "type": "image", "bildart": _art,
                })
                ids.append(f"{dateiname}_p{_seite}_bild_{len(ids)}")
        except Exception as e:
            bild_hinweis = f"Bilder nicht beschrieben: {e}"

    _n, _h = _speichern_chunks(chunks, metadatas, ids, raum,
                               nach_dem_schreiben)
    return _n, " ".join(
        x for x in (_h, name_hinweis, wolke_hinweis, bild_hinweis) if x)
