import streamlit as st
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import time
import json
from datetime import datetime
import re
import bcrypt

import paths
import store
import keyword_index
import llm
import envcheck
from embedding import embed_batch
import ranking
import vision
import pipeline
import feedback
import prompts
import presets
import tabellen
import sqlpruefung
from textutils import strip_boilerplate
from tables import build_table_chunks

paths.bootstrap()

# 1. Werte aus der docker-compose.yml holen
thema = os.getenv("APP_TOPIC", "Allgemein")
firma = os.getenv("COMPANY_NAME", "LocaNoto")

# 2. Page Config (Browser-Tab-Titel) dynamisch machen
st.set_page_config(page_title=f"{firma} - {thema}", layout="wide")

# 3. Nur EINMAL die Überschrift auf der Seite setzen!
st.title(f"{firma} - {thema} Assistent")

# --- ZEITLIMITS ---
# Der OpenAI-Client wartet ohne timeout= bis zu 600 s. Haengt ein Aufruf,
# steht die Oberflaeche zehn Minuten ohne Rueckmeldung -- fuer den Nutzer
# nicht von "kaputt" unterscheidbar.
HELPER_TIMEOUT = paths.env_float("HELPER_TIMEOUT", 60)    # Titel

# --- MODELL-ENDPUNKTE ---
# Je Aufgabe eigene Adresse, eigener Schluessel, eigenes Modell (siehe
# llm.py). Ohne aufgabenspezifische Angaben laeuft alles wie bisher ueber
# OPENAI_BASE_URL.
chat_client = llm.client("CHAT")
title_client = llm.client("TITLE")
embed_client = llm.client("EMBEDDING")

# --- LOGIN SYSTEM ---
USER_FILE = paths.resolve_user_file()


def load_users():
    """Laedt die Benutzerdatei. Fehlt sie oder ist sie leer/kaputt, gilt das
    als 'noch keine Benutzer angelegt' -- nicht als Absturz."""
    if not os.path.exists(USER_FILE) or os.path.getsize(USER_FILE) == 0:
        return {}
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        st.error(
            f"'{os.path.basename(USER_FILE)}' ist beschaedigt und konnte nicht "
            "gelesen werden. Bitte pruefen oder loeschen und mit "
            "create_user.py neu anlegen."
        )
        st.stop()

if "username" not in st.session_state:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🔐 LocaNoto Login</h1>", unsafe_allow_html=True)
    
    users = load_users()
    if not users:
        st.warning("Keine Benutzer gefunden. Bitte führe zuerst 'create_user.py' auf dem Server aus.")
        st.stop()
        
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            login_user = st.text_input("Benutzername").strip().lower()
            login_pass = st.text_input("Passwort", type="password")
            submit_button = st.form_submit_button("Einloggen", use_container_width=True)
            
            if submit_button:
                if login_user in users:
                    # Das eingegebene Passwort mit dem gespeicherten Hash abgleichen
                    stored_hash = users[login_user].encode('utf-8')
                    if bcrypt.checkpw(login_pass.encode('utf-8'), stored_hash):
                        st.session_state["username"] = login_user
                        st.rerun()
                    else:
                        st.error("Falsches Passwort.")
                else:
                    st.error("Benutzer existiert nicht.")
    
    st.stop()

# --- ADMIN SETUP ---
admin_env = os.getenv("ADMIN_USERS", "admin")
ADMIN_USERS = [user.strip().lower() for user in admin_env.split(",")]


def is_admin():
    return st.session_state.get("username", "").lower() in ADMIN_USERS

# --- SIDEBAR (UI) ---
with st.sidebar:
    # --- NEU: LOGOUT HIER OBEN ---
    st.caption(f"👤 Angemeldet als: **{st.session_state['username']}**")
    if st.button("🚪 Ausloggen", use_container_width=True):
        del st.session_state["username"]
        st.rerun()
    st.markdown("---")
    
    

# --- KONFIGURATION (Pfade zentral aus paths.py) ---
CHATS_DIR = paths.CHATS_DIR
DOCS_DIR = paths.DOCS_DIR

def _sanitize_title(text):
    """Macht aus freiem Text einen brauchbaren Dateinamen-Bestandteil."""
    text = " ".join(text.split())
    text = re.sub(r"[^0-9A-Za-zäöüÄÖÜß _-]", "", text)
    text = re.sub(r"[ -]+", "_", text).strip("_")
    return text[:30].strip("_")


def make_chat_title(user_query, model):
    """Erzeugt die Schlagwörter für den Chat-Dateinamen.

    Der Aufruf lief bisher mit max_tokens=10. Bei einem Reasoning-Modell
    verbraucht schon der Denk-Vorspann dieses Budget, sodass content leer
    zurueckkommt -- die Datei hiess dann nur "_26-08-26.json". Ein
    Fehlerfall war das nicht, deshalb griff der bisherige except-Zweig nie.

    Jetzt: groesseres Budget, Denk-Bloecke werden entfernt, und das Ergebnis
    wird geprueft statt vorausgesetzt. Bleibt nichts uebrig, greift derselbe
    Rueckfall wie bei einem echten Fehler.
    """
    try:
        title_prompt = (
            "Fasse diese Frage in 1 bis 2 prägnanten Schlagwörtern zusammen. "
            "Antworte NUR mit den Schlagwörtern, getrennt durch Unterstriche. "
            f"Keine Einleitung, keine Satzzeichen.\nFrage: {user_query}"
        )
        resp = title_client.chat.completions.create(
            # Der Titel ist eine Nebensache -- ein kleines Modell reicht und
            # spart bei drei LLM-Aufrufen pro Frage spuerbar Zeit. Ohne
            # TITLE_MODEL bleibt es beim Chat-Modell.
            model=llm.modell("TITLE", model),
            messages=[{"role": "user", "content": title_prompt}],
            max_tokens=64,
            temperature=0.3,
            timeout=HELPER_TIMEOUT,
        )
        raw = (resp.choices[0].message.content or "")

        # Denk-Bloecke entfernen -- auch einen unabgeschlossenen, falls das
        # Token-Budget mitten im Denken endet.
        raw = re.sub(r"<think>.*?</think>", " ", raw, flags=re.S | re.I)
        raw = re.sub(r"<think>.*", " ", raw, flags=re.S | re.I)

        # Reasoning-Modelle stellen die eigentliche Antwort ans Ende.
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        keywords = _sanitize_title(lines[-1]) if lines else ""
    except Exception:
        keywords = ""

    if not keywords:
        # Rueckfall: die ersten beiden Wörter der Frage.
        keywords = _sanitize_title("_".join(re.findall(r"\w+", user_query)[:2]))

    return keywords or "Chat"


# --- CHAT-SPEICHERUNG (MULTI-USER) ---
def get_user_chat_dir():
    """Gibt den Pfad zum persönlichen Chat-Ordner des eingeloggten Nutzers zurück."""
    user_dir = os.path.join(CHATS_DIR, st.session_state["username"])
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

def get_all_chats():
    """Gibt eine nach Datum sortierte Liste aller Chat-Dateien des Nutzers zurück."""
    user_dir = get_user_chat_dir()
    files = [f for f in os.listdir(user_dir) if f.endswith('.json')]
    # Sortieren nach Änderungsdatum (neueste zuerst)
    files.sort(key=lambda x: os.path.getmtime(os.path.join(user_dir, x)), reverse=True)
    return files

def load_chat(chat_id):
    """Lädt einen bestimmten Chat anhand seiner ID aus dem Nutzer-Ordner."""
    user_dir = get_user_chat_dir()
    path = os.path.join(user_dir, chat_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # Beschaedigte Chat-Datei soll die App nicht blockieren.
            return []
    return []

def save_chat(chat_id, messages):
    """Speichert den Verlauf im Nutzer-Ordner."""
    user_dir = get_user_chat_dir()
    path = os.path.join(user_dir, chat_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

def delete_chat(chat_id):
    """Löscht eine Chat-Datei aus dem Nutzer-Ordner."""
    user_dir = get_user_chat_dir()
    path = os.path.join(user_dir, chat_id)
    if os.path.exists(path):
        os.remove(path)

# --- CHAT STATE INITIALISIEREN ---
# Welcher Chat ist gerade aktiv?
if "current_chat_id" not in st.session_state:
    existing_chats = get_all_chats()
    if existing_chats:
        st.session_state.current_chat_id = existing_chats[0]
    else:
        # Wenn es noch keine Chats gibt, erstelle eine neue ID
        st.session_state.current_chat_id = f"Chat_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

# Lade die Nachrichten für den gerade aktiven Chat
if "messages" not in st.session_state or st.session_state.get("last_loaded_chat") != st.session_state.current_chat_id:
    st.session_state.messages = load_chat(st.session_state.current_chat_id)
    st.session_state.last_loaded_chat = st.session_state.current_chat_id


# --- CHROMADB SETUP ---
@st.cache_resource
def init_chromadb():
    # Der Zugang liegt in store.py -- dieselbe Stelle, die auch die
    # Skripte und die Schnittstelle benutzen. Mit CHROMA_HOST wird daraus
    # ein Server statt einer Dateiablage, ohne dass es hier auffaellt.
    return store.client(), store.collection()

chroma_client, collection = init_chromadb()
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

# --- KEYWORD-INDEX (SQLite FTS5, plattenbasiert) ---
# Loest den fruehren In-Memory-BM25 ab. Der lud bei jedem Start den gesamten
# Korpus in den Arbeitsspeicher (hochgerechnet 8-15 GB bei 1,6 GB PDF) und war
# mit @st.cache_resource eingefroren: frisch hochgeladene Dokumente waren bis
# zum Neustart nicht keyword-suchbar, geloeschte weiterhin auffindbar.
#
# Der Hinweistext laeuft ueber den Dekorator-Parameter und NICHT ueber
# st.spinner/st.toast im Funktionsrumpf. Streamlit zeichnet Elemente aus
# gecachten Funktionen auf und spielt sie bei jedem Cache-Treffer erneut ab --
# ein Layout-Block wie st.spinner laesst sich aber nicht wiedergeben, der
# zweite Durchlauf endet mit CacheReplayClosureError. Das traf nur
# BESTEHENDE Installationen: eine frische Datenbank ist leer, betritt den
# Rebuild-Zweig nie und erzeugt daher nie ein Element.
@st.cache_resource(show_spinner="Baue Keyword-Index einmalig auf ...")
def init_keyword_index():
    """Stellt sicher, dass der Index zur Vektordatenbank passt.

    Faellt er leer aus, obwohl Chunks vorhanden sind, stammt die Datenbank aus
    einer Installation vor diesem Index -- dann einmalig nachbauen.
    """
    have = keyword_index.count()
    if have == 0 and collection.count() > 0:
        have = keyword_index.rebuild_from_collection(collection)
    return have


init_keyword_index()

# --- RERANKER SETUP ---
@st.cache_resource(show_spinner="Richte Rangfolge ein ...")
def init_reranker():
    """Waehlt den Bewerter einmal pro Prozess.

    Reihenfolge in ranking.lade_bewerter(): Rerank-Endpunkt, dann das Modell
    aus dem Image, dann keiner. Keine dieser Stufen kann den Start verhindern
    -- schlaegt eine fehl, wird die naechste genommen.

    @st.cache_resource sorgt dafuer, dass die Auswahl einmal pro
    Containerstart geschieht und nicht bei jeder Frage.
    """
    return ranking.lade_bewerter()


reranker, rerank_info = init_reranker()

# --- DOKUMENTEN-LOGIK ---
def make_document_public(filename):
    """Ändert den Status eines privaten Dokuments auf 'shared'."""
    existing_data = collection.get(
        where={
            "$and": [
                {"file_name": filename},
                {"owner": st.session_state["username"]}
            ]
        }
    )
    if existing_data and existing_data["ids"]:
        new_metadatas = []
        for meta in existing_data["metadatas"]:
            meta["access"] = "shared"
            new_metadatas.append(meta)
        collection.update(ids=existing_data["ids"], metadatas=new_metadatas)
        keyword_index.set_access(filename, st.session_state["username"], "shared")
        refresh_document_index()
        return True
    return False

def remove_pdf_if_orphaned(filename):
    """Loescht die PDF von der Platte -- aber nur, wenn kein Chunk mehr auf
    sie zeigt.

    Alle Nutzer teilen sich DOCS_DIR. Wird die Datei bedingungslos entfernt,
    verliert ein gleichnamiges geteiltes Dokument seine Quellenansicht,
    sobald jemand seine private Kopie loescht -- und umgekehrt.
    """
    if collection.get(where={"file_name": filename}, include=[])["ids"]:
        return False
    file_path = os.path.join(DOCS_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    return True


def delete_private_document(filename, owner):
    """Loescht ein privates Dokument -- ausschliesslich die Chunks des
    angegebenen Eigentuemers.

    Ohne den owner-Filter loescht der where-Ausdruck jeden Chunk mit diesem
    Dateinamen: die privaten Kopien anderer Nutzer und die des gemeinsamen
    Pools gleich mit.
    """
    collection.delete(where={"$and": [
        {"file_name": filename},
        {"access": "private"},
        {"owner": owner},
    ]})
    keyword_index.delete_document(filename, access="private", owner=owner)

    remove_pdf_if_orphaned(filename)
    refresh_document_index()


def list_foreign_private_documents(current_user):
    """(owner, file_name) aller privaten Dokumente ausser denen des Nutzers.

    Nur fuer den Admin-Verwaltungsbereich. Diese Dokumente werden bewusst
    nicht ins Retrieval aufgenommen.
    """
    data = collection.get(where={"access": "private"}, include=["metadatas"])
    seen = set()
    for m in data["metadatas"] or []:
        if not m:
            continue
        owner = m.get("owner", "")
        fname = m.get("file_name", "")
        if owner and fname and owner != current_user:
            seen.add((owner, fname))
    return sorted(seen)


def process_uploaded_pdf(uploaded_file, is_shared, sachgebiet="(Basis)"):
    """Liest ein PDF ein, speichert es dauerhaft, isoliert Tabellen und vektorisiert beides.

    sachgebiet bestimmt den Unterordner und die Metadaten der Abschnitte --
    dieselbe Zuordnung, die der Ingest aus der Ordnerstruktur ableitet. Ohne
    Angabe landet die Datei wie zuvor direkt in data/dokumente/.
    """
    access_type = "shared" if is_shared else "private"
    sachgebiet = (sachgebiet or "(Basis)").strip() or "(Basis)"
    
    # 1. PDF DAUERHAFT SPEICHERN anstatt es wegzuwerfen
    # In den Unterordner des Sachgebiets, damit ein spaeterer
    # vollstaendiger Ingest dieselbe Zuordnung findet. Blieb die Datei im
    # Wurzelverzeichnis, waere sie danach wieder "(Basis)".
    ziel_ordner = (DOCS_DIR if sachgebiet == "(Basis)"
                   else os.path.join(DOCS_DIR, sachgebiet))
    os.makedirs(ziel_ordner, exist_ok=True)
    pdf_path = os.path.join(ziel_ordner, uploaded_file.name)
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getvalue())
        
    doc = pymupdf.open(pdf_path)
    chunks = []
    metadatas = []
    ids = []
    
    
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
                    page, table, uploaded_file.name, page_num + 1, i):
                chunks.append(chunk_text)
                metadatas.append({
                    "file_name": uploaded_file.name,
                    "page": page_num + 1,
                    "folder": sachgebiet,
                    "access": access_type,
                    "owner": st.session_state["username"],
                    "type": "table"
                })
                ids.append(f"{uploaded_file.name}_{suffix}")

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
                    "file_name": uploaded_file.name,
                    "page": page_num + 1,
                    "folder": sachgebiet,
                    "access": access_type,
                    "owner": st.session_state["username"],
                    "type": "text"
                })
                ids.append(f"{uploaded_file.name}_p{page_num+1}_text_{i}")
                
    if chunks:
        # Gebuendelt vektorisieren -- vorher ging pro Chunk eine eigene
        # HTTP-Anfrage an den Modellserver.
        embeddings = embed_batch(embed_client, chunks, llm.modell("EMBEDDING"))

        keep = [i for i, v in enumerate(embeddings) if v is not None]
        if not keep:
            return

        collection.add(
            ids=[ids[i] for i in keep],
            embeddings=[embeddings[i] for i in keep],
            documents=[chunks[i] for i in keep],
            metadatas=[metadatas[i] for i in keep],
        )
        # Beide Indizes im selben Schritt fuellen, damit Vektor- und
        # Keyword-Suche nie auseinanderlaufen.
        keyword_index.add_chunks(
            ((ids[i], chunks[i], metadatas[i]) for i in keep))
        refresh_document_index()

# --- LISTEN FÜR DIE UI ---
# Gecacht, weil dieser Block auf Modulebene liegt und damit bei JEDEM
# Streamlit-Rerun laeuft -- also bei jedem Tastendruck und jedem Klick.
# Ungecacht bedeutet das einen vollstaendigen Metadaten-Scan pro Interaktion;
# bei 324.000 Chunks (Hochrechnung fuer 1,6 GB) sind das mehrere Sekunden
# Verzoegerung bei jeder Eingabe.
#
# Der Cache wird nach jeder Aenderung ueber refresh_document_index() geleert.
# Die ttl faengt zusaetzlich Aenderungen ab, die ein ANDERER Nutzer
# vorgenommen hat -- dessen Cache-Leerung erreicht diese Sitzung nicht.
@st.cache_data(ttl=60, show_spinner=False)
def load_document_index(_collection, username):
    return pipeline.dokumente(_collection, username)


def refresh_document_index():
    """Nach jeder Aenderung an Dokumenten aufrufen."""
    load_document_index.clear()


shared_files, private_files, all_folders = load_document_index(
    collection, st.session_state["username"])

# --- SIDEBAR (UI) ---
with st.sidebar:
    # --- VOREINSTELLUNG ---
    #
    # Ganz oben, weil sie alles darunter faerbt: Modell, Umfang der Treffer,
    # Sachgebiete und die Formulierung der Prompts. Ohne angelegte
    # Voreinstellungen erscheint die Auswahl nicht -- ein Feld mit genau
    # einem Eintrag ist keine Auswahl.
    _namen = presets.namen()
    if _namen:
        _wahl = st.selectbox(
            "🎛️ Voreinstellung", ["(Standard)"] + _namen,
            format_func=lambda n: (n if n == "(Standard)"
                                   else presets.lese(n)["bezeichnung"]),
            help="Buendel aus Chat-Modell, Trefferzahl, Sachgebieten und "
                 "Formulierung. Angelegt werden sie im Verwalterbereich.")
        aktives_preset = None if _wahl == "(Standard)" else _wahl
        _p = presets.lese(aktives_preset)
        if _p.get("beschreibung"):
            st.caption(_p["beschreibung"])
        st.markdown("---")
    else:
        aktives_preset = None
        _p = presets.lese(None)

    st.header("💬 Chats")
    
    # 1. Neuer Chat Button
    if st.button("➕ Neuer Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        st.session_state.messages = []
        st.rerun()

    # 2. Chat-Verlauf Dropdown
    existing_chats = get_all_chats()
    if existing_chats:
        # Wenn der aktuelle Chat noch nicht gespeichert wurde (weil noch keine Nachricht geschrieben wurde), fügen wir ihn temp. zur Liste hinzu
        if st.session_state.current_chat_id not in existing_chats:
            existing_chats.insert(0, st.session_state.current_chat_id)
            
        selected_chat = st.selectbox(
            "Vorherige Chats laden:", 
            existing_chats,
            index=existing_chats.index(st.session_state.current_chat_id),
            format_func=lambda x: x.replace(".json", "").replace("_", " ") # Macht den Namen hübscher
        )
        
        # Wechselt den Chat, wenn ein anderer im Dropdown ausgewählt wurde
        if selected_chat != st.session_state.current_chat_id:
            st.session_state.current_chat_id = selected_chat
            st.rerun()
            
        # 3. Aktuellen Chat löschen
        if st.button("🗑️ Aktuellen Chat löschen", use_container_width=True):
            delete_chat(st.session_state.current_chat_id)
            del st.session_state.current_chat_id # Zwingt das Skript, beim Rerun einen neuen Chat anzulegen oder den nächstbesten zu laden
            st.success("Chat gelöscht!")
            time.sleep(0.5)
            st.rerun()
            
    st.markdown("---")
    st.header("📚 Datenbank")
    
    # Alle verfügbaren Dokumente für den Filter sammeln
    all_available_files = list(set(shared_files + private_files))
    
    st.markdown("---")
    st.header("🎯 Dokumenten-Filter")
    # Grenzt die Suche auf die Dokumente eines Unterordners ein. Steht vor
    # dem Dokumentenfilter, weil die Auswahl bei vielen Dateien schneller
    # geht als das Zusammensuchen einzelner Dokumente.
    selected_folders = st.multiselect(
        "Sachgebiet:",
        options=all_folders,
        default=[g for g in _p["sachgebiete"] if g in all_folders],
        key=f"gebiete_{aktives_preset}",
        help="Leer lassen, um alle Sachgebiete zu durchsuchen."
    ) if all_folders else []

    selected_docs = st.multiselect(
        "Suche beschränken auf:", 
        options=all_available_files,
        default=[],
        help="Leer lassen, um in allen Dokumenten zu suchen."
    )


    # --- LISTEN ---
    #
    # Tabellendateien liegen in data/tabellen/ und werden NICHT vektorisiert:
    # eine Liste mit zehntausenden Zeilen zeilenweise einzubetten kostet
    # Stunden Modellzeit, ist beim naechsten Export veraltet, und
    # semantische Aehnlichkeit ist bei Teilenummern das falsche Werkzeug.
    #
    # Stattdessen haelt ein Katalog die Struktur, und die Zeilen werden bei
    # der Frage frisch gelesen.
    tabellen_aktiv = False
    tabellen_gross = False
    tabellen_bereiche = []
    _katalog = tabellen.lies_katalog()
    _eintraege = _katalog.get("eintraege", [])

    if _eintraege or tabellen.vorhanden() or is_admin():
        st.markdown("---")
        st.header("\U0001f4ca Listen")

        if _eintraege:
            _gross = [e for e in _eintraege if e.get("gross")]
            _klein = [e for e in _eintraege if not e.get("gross")]
            tabellen_aktiv = st.checkbox(
                "Listen mit abfragen",
                value=os.getenv("TABELLEN_DEFAULT_ON", "1").strip().lower()
                not in ("0", "false", "nein", "no"),
                help="Das Modell waehlt die passende Liste und formuliert "
                     "eine lesende Abfrage darauf. Die Zeilen werden bei "
                     "jeder Frage frisch gelesen.")
            st.caption(f"{len(_klein)} Blaetter bereit"
                       + (f", {len(_gross)} zu gross" if _gross else ""))

            # Bereiche sind die Unterordner des Listenordners -- fuer Listen
            # dasselbe, was Sachgebiete fuer Dokumente sind. Ein Pfad wird
            # dabei nirgends eingegeben: der Wurzelordner steht in der .env,
            # sonst koennte man von hier aus in jedes Verzeichnis des
            # Containers sehen.
            _bereiche = tabellen.bereiche(_eintraege)
            if len(_bereiche) > 1 and tabellen_aktiv:
                tabellen_bereiche = st.multiselect(
                    "Bereich", options=_bereiche,
                    default=[b for b in _p["listen_bereiche"]
                             if b in _bereiche],
                    key=f"listenbereich_{aktives_preset}",
                    help="Leer lassen, um alle Listen einzubeziehen.")

            if _gross and tabellen_aktiv:
                tabellen_gross = st.checkbox(
                    f"Grosse Listen einbeziehen ({len(_gross)})",
                    value=False,
                    help="Diese Blaetter haben sehr viele Zeilen und werden "
                         "bei jeder Frage vollstaendig geladen. Das kann "
                         "sehr lange dauern.")
                if tabellen_gross:
                    st.warning("Grosse Listen sind einbezogen -- eine Frage "
                               "kann dadurch deutlich laenger dauern.")
        else:
            st.caption("Dateien vorhanden, aber noch nicht eingelesen.")

        if _katalog.get("fehler"):
            with st.expander(f"Nicht lesbar ({len(_katalog['fehler'])})"):
                for datei, grund in _katalog["fehler"]:
                    st.caption(f"`{datei}` -- {grund}")

        # Neu einlesen heisst: den Ordner vollstaendig durchgehen und den
        # Katalog neu anlegen. Noetig nur, wenn Dateien dazukommen oder sich
        # Spalten aendern -- neue Zeilen wirken ohne Zutun.
        if is_admin():
            # Der Ordner laesst sich hier eintragen, statt Dateien
            # hineinzukopieren: was die Fachabteilung ohnehin pflegt, soll
            # niemand ein zweites Mal ablegen. Erreichbar ist nur, was in
            # den Container eingehaengt ist -- und gelesen werden
            # ausschliesslich Tabellendateien.
            _pfad = st.text_input(
                "Ordner", value=tabellen.pfad(),
                help="Vollstaendiger Pfad, wie er im Container gilt -- etwa "
                     "/listen. Leer lassen fuer die Vorgabe "
                     "data/tabellen/.")
            if _pfad.strip() != tabellen.pfad():
                if st.button("Ordner verknuepfen und einlesen",
                             use_container_width=True):
                    ok, meldung = tabellen.setze_pfad(_pfad)
                    if not ok:
                        st.error(meldung)
                    else:
                        with st.spinner("Lese Listen ein ..."):
                            neu, fehler = tabellen.baue_katalog()
                        st.success(f"{meldung} {len(neu['eintraege'])} "
                                   f"Blaetter eingelesen.")
                        time.sleep(1)
                        st.rerun()

            # --- HOCHLADEN ---
            #
            # Ohne das ginge es nur ueber das Terminal. Wer eine Liste hat,
            # soll sie ablegen koennen, ohne Serverzugang zu brauchen.
            if tabellen.beschreibbar():
                _hoch = st.file_uploader(
                    "Liste hochladen", accept_multiple_files=True,
                    type=[e.lstrip(".") for e in tabellen.ENDUNGEN],
                    key="listen_upload")
                if _hoch:
                    _bekannt = [b for b in tabellen.bereiche(_eintraege)
                                if b != "(Basis)"]
                    _bwahl = st.selectbox(
                        "Bereich fuer den Upload",
                        ["(Basis)"] + _bekannt + ["+ neues anlegen"],
                        key="listen_upload_bereich")
                    if _bwahl == "+ neues anlegen":
                        _bneu = st.text_input("Name des neuen Bereichs",
                                              key="listen_upload_neu")
                        _ziel_bereich = _bneu.strip()
                    else:
                        _ziel_bereich = "" if _bwahl == "(Basis)" else _bwahl

                    if st.button(f"{len(_hoch)} Datei(en) ablegen und einlesen",
                                 use_container_width=True):
                        _abgelegt, _misslungen = [], []
                        for _f in _hoch:
                            ok, meldung = tabellen.lege_ab(
                                _f.getvalue(), _f.name, _ziel_bereich)
                            (_abgelegt if ok else _misslungen).append(meldung)
                        with st.spinner("Lese Listen ein ..."):
                            neu, fehler = tabellen.baue_katalog()
                        if _abgelegt:
                            st.success("Abgelegt: " + ", ".join(_abgelegt))
                        for m in _misslungen:
                            st.error(m)
                        if _abgelegt:
                            time.sleep(1)
                            st.rerun()
            else:
                st.caption("Der Ordner ist nicht beschreibbar -- die Dateien "
                           "werden dort gepflegt, wo sie liegen.")

            if st.button("Listen neu einlesen", use_container_width=True,
                         help="Liest den Ordner vollstaendig neu ein. "
                              "Fuer geaenderte Zeilen nicht noetig."):
                with st.spinner("Lese Listen ein ..."):
                    neu, fehler = tabellen.baue_katalog()
                st.success(f"{len(neu['eintraege'])} Blaetter eingelesen"
                           + (f", {len(fehler)} nicht lesbar" if fehler else ""))
                time.sleep(1)
                st.rerun()

    # 1. NEUER UPLOAD-BEREICH
    # Beide Schreibweisen: Streamlit vergleicht die Endung mit dieser Liste,
    # und eine Datei mit der Endung .PDF wuerde sonst abgelehnt.
    uploaded_file = st.file_uploader("PDF hochladen", type=["pdf", "PDF"])
    if uploaded_file:
        # --- SACHGEBIET ---
        #
        # Die Zuordnung entsteht sonst allein aus der Ordnerstruktur, die
        # beim Ingest gilt. Ein Upload landete deshalb immer in "(Basis)"
        # und war ueber den Sachgebietsfilter nicht zu erreichen.
        _wahl = st.selectbox(
            "Sachgebiet",
            ["(Basis)"] + [g for g in all_folders if g != "(Basis)"]
            + ["+ neues anlegen"],
            help="Bestimmt, in welchem Unterordner die Datei liegt und unter "
                 "welchem Sachgebiet sie gefunden wird.")
        if _wahl == "+ neues anlegen":
            _neu = st.text_input("Name des neuen Sachgebiets").strip()
            # Ein Ordnername, nicht ein beliebiger Pfad: alles andere waere
            # eine Einladung, mit ../ aus dem Datenverzeichnis zu geraten.
            sachgebiet = re.sub(r"[^0-9A-Za-zäöüÄÖÜß _-]", "", _neu).strip()
            if _neu and not sachgebiet:
                st.warning("Der Name enthaelt nur unzulaessige Zeichen.")
        else:
            sachgebiet = _wahl

        # Nur Admins duerfen in den globalen Pool schreiben -- passend dazu,
        # dass auch nur sie daraus loeschen koennen.
        if is_admin():
            is_shared = st.checkbox("🌍 Für alle Nutzer freigeben", value=False)
        else:
            is_shared = False
            st.caption("Der Upload ist privat und nur für dich sichtbar.")
        if st.button("Hochladen & Vektorisieren", disabled=not sachgebiet):
            with st.spinner("Verarbeite PDF (das kann kurz dauern)..."):
                process_uploaded_pdf(uploaded_file, is_shared, sachgebiet)
            st.success(f"'{uploaded_file.name}' zu '{sachgebiet}' hinzugefügt!")
            refresh_document_index()
            time.sleep(1)
            st.rerun()

    st.subheader("Gemeinsamer Pool")
    if shared_files:
        # 1. Alle Dokumente auflisten (für jeden sichtbar)
        for f in shared_files:
            st.caption(f"🌍 {f}")
            
        # 2. Admin-Kontrollen (nur sichtbar, wenn man in ADMIN_USERS steht)
        if is_admin():
            st.markdown("---")
            st.caption("👑 **Admin-Bereich**")
            file_to_delete_shared = st.selectbox("Geteiltes Dokument entfernen:", shared_files)
            if st.button("🗑️ Für alle löschen", use_container_width=True):
                # Löscht das Dokument global aus der Datenbank
                collection.delete(
                    where={
                        "$and": [
                            {"file_name": file_to_delete_shared},
                            {"access": "shared"}
                        ]
                    }
                )
                keyword_index.delete_document(file_to_delete_shared, access="shared")
                remove_pdf_if_orphaned(file_to_delete_shared)
                refresh_document_index()

                st.success(f"'{file_to_delete_shared}' wurde global gelöscht!")
                time.sleep(1)
                st.rerun()
    else:
        st.caption("Keine geteilten Dokumente.")

    st.subheader("Deine privaten Dokumente")
    if private_files:
        file_to_manage = st.selectbox("Dokument verwalten:", private_files)

        col1, col2 = st.columns(2)
        with col1:
            # Freigeben schreibt in den globalen Pool -- gleiche Huerde wie
            # das Loeschen daraus, sonst koennte jeder Nutzer den Pool
            # befuellen, aber nur Admins ihn wieder aufraeumen.
            if is_admin():
                if st.button("🌍 Freigeben", use_container_width=True):
                    make_document_public(file_to_manage)
                    st.success("Freigegeben!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.button("🌍 Freigeben", use_container_width=True, disabled=True,
                          help="Nur Administratoren können Dokumente global freigeben.")
        with col2:
            if st.button("🗑️ Löschen", use_container_width=True):
                # Owner-Filter ist zwingend: ohne ihn loescht dieser Aufruf
                # JEDEN Chunk mit diesem Dateinamen -- auch die anderer
                # Nutzer und die des gemeinsamen Pools.
                delete_private_document(file_to_manage, st.session_state["username"])
                st.success("Gelöscht!")
                time.sleep(1)
                st.rerun()
    else:
        st.caption("Keine privaten Dokumente.")

    # --- ADMIN: fremde private Dokumente ---
    # Bewusst nur hier sichtbar und nie im Retrieval: Admins brauchen das
    # Loeschrecht (verwaiste Dokumente ausgeschiedener Nutzer), aber private
    # Dokumente sollen nicht in fremde Antworten einflieszen.
    if is_admin():
        foreign = list_foreign_private_documents(st.session_state["username"])
        if foreign:
            st.markdown("---")
            st.caption("👑 **Admin: private Dokumente anderer Nutzer**")
            st.caption("Nur zur Verwaltung – diese Dokumente werden nicht durchsucht.")
            label = st.selectbox(
                "Fremdes Dokument entfernen:",
                [f"{owner} / {fname}" for owner, fname in foreign],
            )
            if st.button("🗑️ Endgültig löschen", use_container_width=True):
                owner, fname = label.split(" / ", 1)
                delete_private_document(fname, owner)
                st.success(f"'{fname}' von '{owner}' gelöscht!")
                time.sleep(1)
                st.rerun()
    
    st.markdown("---")
    # Der Name des Chat-Modells laesst sich frei setzen, solange derselbe
    # Endpunkt ihn kennt -- qwen3.8 gegen gemma4 ist eine Namensfrage.
    #
    # Das Embedding-Modell stand hier ebenfalls und ist bewusst entfernt:
    # die Abschnitte im Bestand sind damit vektorisiert, ein anderes
    # vergleicht Vektoren aus einem anderen Raum. Die Suche liefert dann
    # Unsinn, ohne dass etwas fehlschlaegt -- die Antwort klingt normal und
    # zitiert die falschen Stellen. Es gehoert zum Index, nicht zur
    # Bedienung, und ein Wechsel verlangt einen neuen Ingest.
    chat_model = st.text_input(
        "Chat Modell", value=_p["chat_modell"] or llm.modell("CHAT"),
        key=f"chatmodell_{aktives_preset}")
    embed_model = llm.modell("EMBEDDING")
    with st.expander("🔌 Modell-Endpunkte"):
        st.code(llm.uebersicht() + f"\nRANGFOLGE   {rerank_info}",
                language="text")

    # --- RUECKMELDUNGEN ---
    #
    # Die Arbeitsliste fuer glossar.txt und fuer Luecken im Bestand: hier
    # steht, was gefragt wurde und nichts fand.
    if is_admin():
        zahlen = feedback.zaehle()
        gesamt = sum(zahlen.values())
        if gesamt:
            with st.expander(f"\U0001f4dd Rueckmeldungen ({gesamt})"):
                st.caption(
                    f"ohne Treffer: {zahlen['leer']} \u00b7 "
                    f"hat geholfen: {zahlen['daumen_hoch']} \u00b7 "
                    f"hat nicht geholfen: {zahlen['daumen_runter']}")
                st.caption("**Fragen ohne Treffer** -- Kandidaten fuer "
                           "glossar.txt:")
                leer = feedback.lese(grenze=15, art="leer")
                if leer:
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in leer), language="text")
                else:
                    st.caption("keine")
                schlecht = feedback.lese(grenze=15, art="daumen_runter")
                if schlecht:
                    st.caption("**Als nicht hilfreich gemeldet** -- Treffer "
                               "kamen, aber die falschen:")
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in schlecht), language="text")
                st.caption("Vollstaendig in `data/feedback.jsonl`.")

                # Beiseitelegen statt loeschen: die Arbeitsliste soll leer
                # werden, nicht die Ueberlieferung. Was Nutzer nicht
                # gefunden haben, ist die einzige Quelle fuer die Frage, ob
                # der Bestand mit der Zeit besser wird.
                if st.button("Liste abschliessen", use_container_width=True,
                             help="Legt das Protokoll unter einem Datum ab "
                                  "und beginnt ein neues. Es wird nichts "
                                  "geloescht."):
                    ziel = feedback.archiviere()
                    if ziel:
                        st.success(f"Abgelegt als `{os.path.basename(ziel)}`.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.info("Nichts abzulegen.")

                # Herunterladen statt auf den Server steigen: die Liste
                # wird ausgewertet, nicht nur angesehen, und dafuer braucht
                # man sie vollstaendig.
                if os.path.exists(feedback.DATEI):
                    with open(feedback.DATEI, "rb") as f:
                        st.download_button(
                            "Protokoll herunterladen", f.read(),
                            file_name="feedback.jsonl",
                            mime="application/x-ndjson",
                            use_container_width=True)

                alte = feedback.ablagen()
                if alte:
                    st.caption("Frueher abgelegt:")
                    wahl = st.selectbox("Ablage", alte, label_visibility="collapsed")
                    pfad = os.path.join(os.path.dirname(feedback.DATEI), wahl)
                    if os.path.exists(pfad):
                        with open(pfad, "rb") as f:
                            st.download_button(
                                f"{wahl} herunterladen", f.read(),
                                file_name=wahl, mime="application/x-ndjson",
                                use_container_width=True)

    # --- GLOSSAR ---
    #
    # Bearbeitbar im Browser, weil es laufend gepflegt wird: die Eintraege
    # entstehen aus den Fragen, die nichts gefunden haben, und wer sie
    # nachtraegt sitzt nicht am Server. Die Datei liegt unter config/ und
    # ist damit eingehaengt -- die Aenderung wirkt bei der naechsten Frage,
    # ohne Rebuild und ohne Neustart.
    if is_admin():
        with st.expander("\U0001f5e3\ufe0f Glossar bearbeiten"):
            pfad = paths.resolve_glossar()
            try:
                with open(pfad, "r", encoding="utf-8") as f:
                    inhalt = f.read()
            except OSError:
                # Noch nicht angelegt: mit der Vorlage beginnen, damit die
                # Hinweise zur Pflege gleich dabeistehen.
                vorlage = os.path.join(paths.BASE_DIR, "glossar.example.txt")
                try:
                    with open(vorlage, "r", encoding="utf-8") as f:
                        inhalt = f.read()
                except OSError:
                    inhalt = ""

            neu = st.text_area(
                "Je Zeile eine Zuordnung. Zeilen mit # sind Erlaeuterungen "
                "und kommen nicht in den Prompt.",
                value=inhalt, height=320, key="glossar_text")

            wirksam = pipeline.glossar()
            st.caption(f"Wirksam: {len(wirksam.splitlines()) if wirksam else 0} "
                       f"Zuordnungen \u00b7 `{os.path.relpath(pfad, paths.BASE_DIR)}`")

            if st.button("Glossar speichern", use_container_width=True):
                try:
                    os.makedirs(os.path.dirname(paths.GLOSSAR_FILE),
                                exist_ok=True)
                    # Erst daneben schreiben, dann umbenennen: bricht der
                    # Vorgang ab, steht die alte Datei noch vollstaendig da.
                    vorlaeufig = paths.GLOSSAR_FILE + ".neu"
                    with open(vorlaeufig, "w", encoding="utf-8",
                              newline="\n") as f:
                        f.write(neu)
                    os.replace(vorlaeufig, paths.GLOSSAR_FILE)
                    st.success("Gespeichert. Wirkt ab der naechsten Frage.")
                    time.sleep(1)
                    st.rerun()
                except OSError as e:
                    st.error(f"Konnte nicht gespeichert werden: {e}")

    # --- VOREINSTELLUNGEN VERWALTEN ---
    #
    # Angelegt werden sie von Verwaltern, ausgewaehlt von allen. Eine
    # Voreinstellung buendelt, was zusammengehoert -- wer das jedes Mal von
    # Hand umstellt, macht es entweder selten oder falsch.
    if is_admin():
        with st.expander("🎛️ Voreinstellungen verwalten"):
            vorhanden = presets.namen()
            bearbeiten = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + vorhanden,
                format_func=lambda n: (n if n == "(neu anlegen)"
                                       else presets.lese(n)["bezeichnung"]),
                key="preset_bearbeiten")
            neu = bearbeiten == "(neu anlegen)"
            werte = presets.lese(None if neu else bearbeiten)

            bez = st.text_input("Bezeichnung", value="" if neu
                                else werte["bezeichnung"],
                                key=f"pb_{bearbeiten}")
            beschr = st.text_input("Beschreibung", value=werte["beschreibung"],
                                   key=f"pd_{bearbeiten}",
                                   help="Eine Zeile, die unter der Auswahl "
                                        "steht.")
            modell = st.text_input(
                "Chat-Modell", value=werte["chat_modell"],
                key=f"pm_{bearbeiten}",
                help="Leer = das Modell aus der .env. Der Name muss dem "
                     "eingetragenen Endpunkt bekannt sein.")
            k = st.number_input("Relevante Abschnitte", min_value=0,
                                max_value=30, value=int(werte["top_k"] or 0),
                                key=f"pk_{bearbeiten}",
                                help="0 = Vorgabe aus TOP_K.")
            gebiete = st.multiselect(
                "Sachgebiete", options=all_folders,
                default=[g for g in werte["sachgebiete"] if g in all_folders],
                key=f"pg_{bearbeiten}") if all_folders else []

            bereiche = st.multiselect(
                "Listenbereiche", options=tabellen.bereiche(_eintraege),
                default=[b for b in werte["listen_bereiche"]
                         if b in tabellen.bereiche(_eintraege)],
                key=f"pl_{bearbeiten}",
                help="Unterordner des Listenordners. Leer = alle. Der "
                     "Wurzelordner selbst steht in der .env "
                     "(TABELLEN_PFAD).") if _eintraege else []

            links, rechts = st.columns(2)
            with links:
                if st.button("Speichern", key=f"psp_{bearbeiten}",
                             use_container_width=True):
                    ok, meldung = presets.speichern(bez, {
                        "bezeichnung": bez, "beschreibung": beschr,
                        "chat_modell": modell, "top_k": int(k),
                        "sachgebiete": gebiete,
                        "listen_bereiche": bereiche})
                    if ok:
                        st.success(f"Gespeichert als `{meldung}`.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(meldung)
            with rechts:
                if st.button("Entfernen", key=f"pdl_{bearbeiten}",
                             disabled=neu, use_container_width=True):
                    if presets.loesche(bearbeiten):
                        st.success("Entfernt.")
                        time.sleep(1)
                        st.rerun()

            st.caption("Eigene Prompts und ein eigenes Glossar bekommt eine "
                       "Voreinstellung ueber die Auswahl unter "
                       "\u201cPrompts bearbeiten\u201d.")

    # --- PROMPT-VORLAGEN ---
    #
    # Sie bestimmen, wonach gesucht und wie geantwortet wird -- also genau
    # das, was man im Betrieb nachschaerft. Bearbeitbar zu machen kostet
    # wenig; sie im Image zu lassen kostet fuer jede Formulierung einen
    # Rebuild.
    #
    # Nur fuer Verwalter: eine unglueckliche Formulierung wirkt auf jede
    # Antwort, die danach gegeben wird.
    if is_admin():
        with st.expander("📜 Prompts bearbeiten"):
            namen = prompts.verfuegbar()
            if not namen:
                st.caption("Keine Vorlagen gefunden.")
            else:
                # Fuer wen gilt die Fassung: fuer die ganze Installation
                # oder nur fuer eine Voreinstellung? Genau hier bekommt ein
                # Buendel seine eigene Sprache -- fuer Bedienhandbuecher ist
                # "welche Maske, welches Feld" die richtige zweite Sonde,
                # fuer Regelwerke "welcher Anhang, welche Tabelle".
                geltung = st.selectbox(
                    "Gilt fuer", ["Alle"] + presets.namen(),
                    format_func=lambda n: (n if n == "Alle"
                                           else presets.lese(n)["bezeichnung"]),
                    key="prompt_geltung")
                fuer = None if geltung == "Alle" else geltung

                gewaehlt = st.selectbox(
                    "Vorlage", namen,
                    format_func=lambda n: f"{prompts.VORLAGEN[n]['titel']} ({n})")
                angaben = prompts.VORLAGEN[gewaehlt]
                st.caption(angaben["zweck"])

                inhalt, herkunft = prompts.lese(gewaehlt, fuer)
                text = st.text_area(
                    "Platzhalter: " + ", ".join(
                        list(angaben["pflicht"]) + list(angaben["optional"])),
                    value=inhalt, height=340,
                    key=f"prompt_{gewaehlt}_{fuer}")

                st.caption({
                    "preset": "Eigene Fassung dieser Voreinstellung",
                    "eigen": "Bearbeitete Fassung aus `config/`",
                    "vorlage": "Mitgelieferte Vorlage",
                }[herkunft])

                links, rechts = st.columns(2)
                with links:
                    if st.button("Speichern", key=f"sp_{gewaehlt}_{fuer}",
                                 use_container_width=True):
                        ok, meldung = prompts.speichern(gewaehlt, text, fuer)
                        if ok:
                            st.success(meldung)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(meldung)
                with rechts:
                    # Zuruecksetzen entfernt nur die Fassung dieser Stufe.
                    # Darunter gilt dann wieder, was ohnehin gelten wuerde.
                    eigene_stufe = (herkunft == "preset" if fuer
                                    else herkunft == "eigen")
                    if st.button("Zuruecksetzen", key=f"zr_{gewaehlt}_{fuer}",
                                 disabled=not eigene_stufe,
                                 use_container_width=True):
                        if prompts.zuruecksetzen(gewaehlt, fuer):
                            st.success("Zurueckgesetzt.")
                            time.sleep(1)
                            st.rerun()

    # --- KONFIGURATION GEGEN DIE VORLAGE ---
    #
    # .env steht in der .gitignore, ein git pull fasst sie also nie an.
    # Kommt mit einem Update eine Einstellung dazu oder aendert sich ein
    # empfohlener Wert, bleibt die eigene .env, wie sie war -- und ein dort
    # eingetragener Wert schlaegt immer den Standard im Code. Genau so ist
    # eine Obergrenze ueber mehrere Updates hinweg auf einem Wert
    # stehengeblieben, der zu Ausfaellen beim Vektorisieren gefuehrt hat.
    #
    # Angezeigt werden nur Namen, nie Werte; Namen, die auf ein Geheimnis
    # hindeuten, werden gar nicht erst verglichen.
    if is_admin():
        try:
            fehlend, abweichend, unbekannt = envcheck.vergleiche()
        except Exception:
            fehlend, abweichend, unbekannt = [], [], []
        if fehlend or abweichend or unbekannt:
            with st.expander(f"⚙️ Konfiguration ({len(fehlend) + len(abweichend) + len(unbekannt)})"):
                if abweichend:
                    st.caption("**Abweichend von der Vorlage** -- gewollt oder "
                               "beim letzten Update uebersehen:")
                    st.code(chr(10).join(abweichend), language="text")
                if fehlend:
                    st.caption("**Nicht in der eigenen .env** -- es greift der "
                               "Standard aus dem Code:")
                    st.code(chr(10).join(fehlend), language="text")
                if unbekannt:
                    st.caption("**Nur in der eigenen .env** -- veraltet, oder "
                               "die Vorlage hat den Eintrag verloren:")
                    st.code(chr(10).join(unbekannt), language="text")
    # Bei dichten Regelwerken kann 5 zu wenig sein: eine vollstaendige
    # Auskunft braucht dann mehrere Tabellen aus mehreren Dokumenten
    # gleichzeitig, und die wenigen Plaetze sind nach zwei Fundstellen
    # aufgebraucht. Der Standard bleibt dennoch 5; wer mehr braucht, zieht
    # den Regler oder setzt TOP_K.
    top_k = st.slider("Relevante Abschnitte abrufen", min_value=1, max_value=30,
                      value=_p["top_k"] or paths.env_int("TOP_K", 5),
                      key=f"topk_{aktives_preset}")

# --- CHAT & RETRIEVAL ---
if collection.count() > 0:
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            # Angehaengte Bilder vor dem Text, so wie der Nutzer sie
            # geschickt hat. Fehlt die Datei -- etwa weil der Chat-Ordner
            # aufgeraeumt wurde -- wird sie stillschweigend uebergangen.
            for bild in msg.get("bilder", []):
                if os.path.exists(bild):
                    st.image(bild, width=360)
            st.write(msg["content"])
            
            # --- RUECKMELDUNG ---
            #
            # Unter jeder Antwort, nicht nur unter schlechten: die
            # Zustimmung zeigt, welche Fragen der Bestand gut traegt.
            # Kennt man nur die Fehlschlaege, weiss man nach einer
            # Aenderung nicht, ob sie etwas verbessert oder nur verschoben
            # hat.
            if msg["role"] == "assistant":
                frage_davor = next(
                    (m["content"] for m in
                     reversed(st.session_state.messages[:i])
                     if m["role"] == "user"), "")
                gegeben = st.session_state.setdefault("rueckmeldungen", set())
                schluessel = f"{st.session_state.current_chat_id}:{i}"
                if schluessel in gegeben:
                    st.caption("Danke -- vermerkt.")
                else:
                    hoch, runter, _ = st.columns([1, 1, 8])
                    for spalte, zeichen, art, text in (
                            (hoch, "\U0001f44d", "daumen_hoch", "Hat geholfen"),
                            (runter, "\U0001f44e", "daumen_runter",
                             "Hat nicht geholfen")):
                        with spalte:
                            if st.button(zeichen, key=f"fb_{art}_{schluessel}",
                                         help=text):
                                feedback.notiere(
                                    art, st.session_state["username"],
                                    frage_davor,
                                    sonden=msg.get("sonden", []),
                                    zahlen=msg.get("zahlen", {}),
                                    quellen=msg.get("sources", []))
                                gegeben.add(schluessel)
                                st.rerun()

            # --- QUELLEN DAUERHAFT ANZEIGEN ---
            if "sources" in msg and msg["sources"]:
                st.markdown("---")
                st.markdown("📚 **Verwendete Quellen:**")
                
                for source in msg["sources"]:
                    file_n = source["file"]
                    page_n = source["page"]
                    
                    with st.expander(f"📄 {file_n} (Seite {page_n})"):
                        for t in source["texts"]:
                            st.info(t)
                        
                        pdf_path = os.path.join(DOCS_DIR, file_n)
                        if os.path.exists(pdf_path) and isinstance(page_n, int):
                            # Einzigartiger Key für diese Nachricht und diese Seite
                            chk_key = f"chk_{file_n}_{page_n}_{i}"
                            
                            if st.checkbox(f"👁️ Original-Seite {page_n} als Bild laden", key=chk_key):
                                try:
                                    src_doc = pymupdf.open(pdf_path)
                                    src_page = src_doc.load_page(page_n - 1)
                                    pix = src_page.get_pixmap(dpi=150)
                                    st.image(pix.tobytes(), caption=f"Originalansicht: {file_n} - Seite {page_n}")
                                    src_doc.close()
                                except Exception as e:
                                    st.error(f"Konnte PDF nicht rendern: {e}")

    eingabe = st.chat_input(
        "Frage an die Datenbank -- Bilder koennen angehaengt werden ...",
        accept_file="multiple", file_type=vision.ERLAUBTE_TYPEN)

    if eingabe:
        # Mit accept_file liefert chat_input ein Objekt mit .text und .files
        # statt einer Zeichenkette.
        user_query = (eingabe.text or "").strip()
        angehaengt = list(eingabe.files or [])

        # --- ANGEHAENGTE BILDER BESCHREIBEN ---
        #
        # Das Sehmodell wandelt sie in Text um. Der wird an zwei Stellen
        # gebraucht: als zusaetzliche Suchsonde, damit die Dokumentensuche
        # ueberhaupt etwas zum Bild findet, und im Kontext der Antwort. Das
        # Chat-Modell selbst bekommt das Bild nicht -- es kann in dieser
        # Aufteilung ein reines Textmodell sein.
        bild_pfade, bild_texte = [], []
        for n, datei in enumerate(angehaengt):
            with st.spinner(f"Lese Bild {n + 1} von {len(angehaengt)} ..."):
                rohdaten = datei.getvalue()
                try:
                    endung = os.path.splitext(datei.name)[1].lower() or ".jpg"
                    name = (f"{st.session_state.current_chat_id[:-5]}"
                            f"_{len(st.session_state.messages)}_{n}{endung}")
                    bild_pfade.append(vision.speichern(
                        rohdaten, st.session_state["username"], name))
                    bild_texte.append(vision.beschreibe(rohdaten, user_query))
                except Exception as e:
                    st.warning(f"Bild '{datei.name}' konnte nicht gelesen "
                               f"werden: {e}")

        if not user_query and not bild_texte:
            st.stop()
        if not user_query:
            user_query = ("Was ist auf dem Bild zu sehen, und was sagt die "
                          "Dokumentation dazu?")

        st.session_state.messages.append({"role": "user", "content": user_query,
                                          "bilder": bild_pfade})
        
        # --- NEU: Dynamische Chat-Benennung beim 1. Prompt ---
        if len(st.session_state.messages) == 1:
            old_chat_id = st.session_state.current_chat_id
            date_str = datetime.now().strftime('%y-%m-%d')
            
            keywords = make_chat_title(user_query, chat_model)

            new_chat_id = f"{keywords}_{date_str}.json"
            
            # Falls die Datei exakt so schon existiert, Sekunden anhängen
            if os.path.exists(os.path.join(get_user_chat_dir(), new_chat_id)):
                new_chat_id = f"{keywords}_{datetime.now().strftime('%y-%m-%d_%H-%M-%S')}.json"
                
            st.session_state.current_chat_id = new_chat_id
            delete_chat(old_chat_id) # Alte Datums-Datei sofort löschen
        # -------------------------------------------------------
        
        save_chat(st.session_state.current_chat_id, st.session_state.messages)
        
        with st.chat_message("user"):
            st.write(user_query)

        with st.chat_message("assistant"):
            try:
                # --- 1. SUCHSONDEN ---
                verlauf = pipeline.verlaufstext(st.session_state.messages)
                with st.spinner("Analysiere Frage und generiere Such-Sonden..."):
                    search_queries, sonden_hinweis = pipeline.sonden(
                        chat_client, chat_model, user_query,
                        verlauf=verlauf, bild_texte=bild_texte,
                        preset=aktives_preset)

                if sonden_hinweis:
                    st.caption("\U0001f9e0 *Nutze Standard-Suche -- Sonden "
                               f"fehlgeschlagen: {sonden_hinweis}*")
                else:
                    st.caption("\U0001f9e0 *Multi-Query Sonden:* \n- `"
                               + "`\n- `".join(search_queries) + "`")

                # --- 2. HYBRIDE SUCHE UND RANGFOLGE ---
                with st.spinner("Führe hybride Suche (Bedeutung + Exakte Stichworte) durch..."):
                    try:
                        treffer, zahlen = pipeline.suche(
                            collection, embed_client, embed_model,
                            search_queries, st.session_state["username"], top_k,
                            dateien=selected_docs or None,
                            ordner=selected_folders or None,
                            bewerter=reranker)
                    except ValueError as e:
                        st.error(str(e))
                        st.stop()

                if not treffer:
                    # Die aussagekraeftigste Rueckmeldung ist die, fuer die
                    # niemand einen Knopf druecken muss.
                    feedback.notiere("leer", st.session_state["username"],
                                     user_query, sonden=search_queries,
                                     zahlen=zahlen)

                if treffer:
                    verfahren = ("Reranker" if reranker is not None
                                 else "Rangfolge-Fusion")
                    st.caption(f"\U0001f3af *{verfahren}: {zahlen['kandidaten']} "
                               f"Treffer aus {zahlen['ranglisten']} Ranglisten "
                               f"auf die besten {len(treffer)} destilliert.*")

                bloecke = []

                # --- LISTEN ABFRAGEN ---
                #
                # Erst entscheiden, WO die Antwort stehen koennte, dann dort
                # gezielt nachsehen -- dasselbe Vorgehen wie bei einer
                # Datenbank. Ausgefuehrt wird kein erzeugter Code, sondern
                # eine gepruefte SELECT-Anweisung gegen das eine gewaehlte
                # Blatt.
                if tabellen_aktiv and _eintraege:
                    auswahl = [e for e in _eintraege
                               if (tabellen_gross or not e.get("gross"))
                               and tabellen.im_bereich(e, tabellen_bereiche)]
                    if auswahl:
                        with st.spinner("Suche in den Listen ..."):
                            t_datei = t_blatt = t_ergebnis = ""
                            t_sql = t_grund = ""
                            try:
                                t_datei, t_blatt, t_sql = tabellen.formuliere(
                                    chat_client, chat_model, user_query,
                                    tabellen.als_text(auswahl), verlauf)
                                if not t_sql:
                                    t_grund = ("Keine der Listen passt zu "
                                               "dieser Frage.")
                            except Exception as e:
                                t_grund = f"Abfrage nicht erzeugt: {e}"

                            if t_sql:
                                try:
                                    sp, ze = tabellen.fuehre_aus(
                                        t_datei, t_blatt, t_sql)
                                    t_ergebnis = sqlpruefung.als_tabelle(sp, ze)
                                except ValueError as e:
                                    t_grund = str(e)
                                except Exception as e:
                                    t_grund = f"Liste nicht lesbar: {e}"

                        if t_ergebnis:
                            quelle = t_datei + (f"#{t_blatt}" if t_blatt else "")
                            bloecke += [
                                ("liste_abfrage", f"{quelle}\n{t_sql}"),
                                ("liste_ergebnis", t_ergebnis)]
                            with st.expander(f"\U0001f4ca Liste: {quelle}"):
                                st.code(t_sql, language="sql")
                                st.markdown(t_ergebnis)
                        elif t_grund:
                            st.caption(f"\U0001f4ca *Listen nicht verwendet: "
                                       f"{t_grund}*")

                # --- 3. KONTEXT FÜR DAS LLM ---
                dynamic_context = pipeline.kontext(treffer, bild_texte,
                                                   bloecke=bloecke)

                with st.expander("\U0001f6e0\ufe0f Debug-Röntgenblick (Was sieht das LLM?)"):
                    st.write(f"**Generierte Sonden:** {search_queries}")
                    if treffer:
                        for rang, eintrag in enumerate(treffer, 1):
                            meta = eintrag["meta"]
                            st.markdown(
                                f"**Rang {rang}** | \U0001f4c4 "
                                f"`{meta.get('file_name', '?')}` | "
                                f"\U0001f3af Sonde: *{meta.get('found_by_query', '?')}*")
                            st.caption(f"{eintrag['text'][:250]}...")
                    else:
                        st.write("Keine Chunks gefunden.")

                # --- 4. ANTWORT ---
                answer = st.write_stream(pipeline.antwort(
                    chat_client, chat_model,
                    pipeline.systemprompt(dynamic_context, aktives_preset),
                    st.session_state.messages))

                # --- 5. QUELLEN SPEICHERN ---
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": pipeline.quellen(treffer),
                    # Fuer die Rueckmeldung: ohne Sonden und Zahlen ist ein
                    # spaeteres "hat nicht geholfen" nicht auswertbar -- man
                    # sieht nicht, wonach gesucht wurde.
                    "sonden": search_queries,
                    "zahlen": zahlen,
                })
                save_chat(st.session_state.current_chat_id,
                          st.session_state.messages)

                # Neu zeichnen, damit die Nachricht durch die Chat-Schleife
                # oben laeuft und ihre Quellen-Aufklapper bekommt.
                st.rerun()

            except Exception as e:
                st.error(f"Fehler bei der Verarbeitung: {e}")

else:
    st.info("Die Datenbank ist leer. Bitte nutze dein Hintergrund-Skript, um PDFs einzulesen.")