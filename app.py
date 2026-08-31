import streamlit as st
import pymupdf
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import time
import json
from datetime import datetime
import re
import bcrypt

import paths
import keyword_index
import llm
from embedding import embed_batch
import ranking
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
HELPER_TIMEOUT = float(os.getenv("HELPER_TIMEOUT", "60"))    # Titel, Rewrite
ANSWER_TIMEOUT = float(os.getenv("ANSWER_TIMEOUT", "300"))   # Antwort-Stream

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
    chroma_client = chromadb.PersistentClient(path=paths.CHROMA_DIR)
    collection = chroma_client.get_or_create_collection(name=paths.COLLECTION_NAME)
    return chroma_client, collection

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


def process_uploaded_pdf(uploaded_file, is_shared):
    """Liest ein PDF ein, speichert es dauerhaft, isoliert Tabellen und vektorisiert beides."""
    access_type = "shared" if is_shared else "private"
    
    # 1. PDF DAUERHAFT SPEICHERN anstatt es wegzuwerfen
    pdf_path = os.path.join(DOCS_DIR, uploaded_file.name)
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
                    "folder": "(Basis)",
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
                    "folder": "(Basis)",
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
    def files_and_folders(data):
        files, folders = set(), set()
        for m in (data.get("metadatas") or []):
            if not m:
                continue
            if m.get("file_name"):
                files.add(m["file_name"])
            if m.get("folder"):
                folders.add(m["folder"])
        return sorted(files), sorted(folders)

    shared_files, shared_folders = files_and_folders(
        _collection.get(where={"access": "shared"}, include=["metadatas"]))
    private_files, private_folders = files_and_folders(
        _collection.get(where={"$and": [{"access": "private"},
                                        {"owner": username}]},
                        include=["metadatas"]))
    return shared_files, private_files, sorted(set(shared_folders) | set(private_folders))


def refresh_document_index():
    """Nach jeder Aenderung an Dokumenten aufrufen."""
    load_document_index.clear()


shared_files, private_files, all_folders = load_document_index(
    collection, st.session_state["username"])

# --- SIDEBAR (UI) ---
with st.sidebar:
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
        default=[],
        help="Leer lassen, um alle Sachgebiete zu durchsuchen."
    ) if all_folders else []

    selected_docs = st.multiselect(
        "Suche beschränken auf:", 
        options=all_available_files,
        default=[],
        help="Leer lassen, um in allen Dokumenten zu suchen."
    )


    # 1. NEUER UPLOAD-BEREICH
    # Beide Schreibweisen: Streamlit vergleicht die Endung mit dieser Liste,
    # und eine Datei mit der Endung .PDF wuerde sonst abgelehnt.
    uploaded_file = st.file_uploader("PDF hochladen", type=["pdf", "PDF"])
    if uploaded_file:
        # Nur Admins duerfen in den globalen Pool schreiben -- passend dazu,
        # dass auch nur sie daraus loeschen koennen.
        if is_admin():
            is_shared = st.checkbox("🌍 Für alle Nutzer freigeben", value=False)
        else:
            is_shared = False
            st.caption("Der Upload ist privat und nur für dich sichtbar.")
        if st.button("Hochladen & Vektorisieren"):
            with st.spinner("Verarbeite PDF (das kann kurz dauern)..."):
                process_uploaded_pdf(uploaded_file, is_shared)
            st.success(f"'{uploaded_file.name}' erfolgreich hinzugefügt!")
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
    chat_model = st.text_input("Chat Modell", value=llm.modell("CHAT"))
    embed_model = st.text_input("Embedding Modell", value=llm.modell("EMBEDDING"))
    with st.expander("🔌 Modell-Endpunkte"):
        st.code(llm.uebersicht() + f"\nRANGFOLGE   {rerank_info}",
                language="text")
    # Bei dichten Regelwerken kann 5 zu wenig sein: eine vollstaendige
    # Auskunft braucht dann mehrere Tabellen aus mehreren Dokumenten
    # gleichzeitig, und die wenigen Plaetze sind nach zwei Fundstellen
    # aufgebraucht. Der Standard bleibt dennoch 5; wer mehr braucht, zieht
    # den Regler oder setzt TOP_K.
    top_k = st.slider("Relevante Abschnitte abrufen", min_value=1, max_value=30,
                      value=int(os.getenv("TOP_K", "5")))

# --- CHAT & RETRIEVAL ---
if collection.count() > 0:
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
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

    if user_query := st.chat_input("Stelle eine Frage an die Datenbank..."):
        
        st.session_state.messages.append({"role": "user", "content": user_query})
        
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
                # --- 1. MULTI-QUERY EXPANSION (Universell) ---
                search_queries = [user_query]
                
                with st.spinner("Analysiere Frage und generiere Such-Sonden..."):
                    history_text = ""
                    if len(st.session_state.messages) > 1:
                        history_msgs = st.session_state.messages[:-1][-3:]
                        history_text = "\nChatverlauf:\n" + "\n".join([f"{msg['role']}: {msg['content'][:300]}" for msg in history_msgs])
                    
                    rewrite_prompt = f"""Du bist ein präziser Suchbegriff-Generator für eine universelle Wissens-Datenbank.
Generiere exakt 3 verschiedene Suchanfragen für die aktuelle Nutzerfrage, um sowohl Fließtexte (wie wissenschaftliche Paper) als auch strukturierte Daten (wie Tabellen/Normen) optimal zu finden:
1. Die präzise, umformulierte Kernfrage (löse Pronomen durch echte Begriffe aus dem Chatverlauf auf).
2. Eine konzeptionelle Suche nach zugrundeliegenden Definitionen, Methoden, Parametern oder Theorien.
3. Eine hochspezifische Stichwort-Suche (Eigennamen, Fachbegriffe, genaue Maße oder Variablen aus der Frage).

{history_text}

Aktuelle Frage: {user_query}

Antworte AUSSCHLIESSLICH mit den 3 Suchanfragen, getrennt durch Zeilenumbrüche. Keine Zahlen davor, keine Einleitung."""

                    try:
                        rewrite_response = chat_client.chat.completions.create(
                            timeout=HELPER_TIMEOUT,
                            model=chat_model,
                            messages=[{"role": "user", "content": rewrite_prompt}],
                            temperature=0.1
                        )
                        generated_queries = [q.strip("- 1234567890.") for q in rewrite_response.choices[0].message.content.split("\n") if q.strip()]
                        if len(generated_queries) >= 3:
                            search_queries = generated_queries[:3]
                        st.caption(f"🧠 *Multi-Query Sonden:* \n- `" + "`\n- `".join(search_queries) + "`")
                    except Exception:
                        st.caption("🧠 *Nutze Standard-Suche (Multi-Query fehlgeschlagen)*")

                # --- 2. HYBRID-SUCHE (Vektor + Keyword/FTS5) ---
                with st.spinner("Führe hybride Suche (Bedeutung + Exakte Stichworte) durch..."):
                    # Die 3 Sonden in EINER Anfrage statt in dreien.
                    vektoren = embed_batch(embed_client, search_queries,
                                           embed_model, keep_alive=0)
                    # Sonde und Vektor gemeinsam filtern. Wuerde man nur die
                    # Vektoren zusammenschieben, verschoeben sich die Indizes
                    # und die Treffer bekaemen die falsche Sonde zugeordnet.
                    sonden = [(q, v) for q, v in zip(search_queries, vektoren)
                              if v is not None]
                    if not sonden:
                        st.error("Die Suchanfrage konnte nicht vektorisiert werden.")
                        st.stop()
                    broad_k = max(10, top_k * 3)

                    # Jede Sonde und jeder Suchweg liefert eine EIGENE
                    # Rangliste. Die Reihenfolge innerhalb der Listen ist die
                    # eigentliche Information fuer die Fusion (ranking.py) --
                    # frueher wurde sie beim Entdoppeln weggeworfen.
                    ranglisten = []

                    # A. VEKTOR-SUCHE (ChromaDB)
                    base_filter = {"$or": [{"access": {"$eq": "shared"}}, {"owner": {"$eq": st.session_state["username"]}}]}
                    conditions = [base_filter]
                    if selected_docs:
                        conditions.append({"file_name": {"$in": selected_docs}})
                    if selected_folders:
                        conditions.append({"folder": {"$in": selected_folders}})
                    where_clause = {"$and": conditions} if len(conditions) > 1 else base_filter

                    results = collection.query(
                        query_embeddings=[v for _, v in sonden],
                        n_results=broad_k,
                        where=where_clause
                    )

                    for idx, (batch_docs, batch_metas) in enumerate(
                            zip(results['documents'], results['metadatas'])):
                        probe = sonden[idx][0]
                        liste = [{"text": d, "meta": m, "probe": probe}
                                 for d, m in zip(batch_docs, batch_metas)]
                        if liste:
                            ranglisten.append(liste)

                    # B. KEYWORD-SUCHE (SQLite FTS5, plattenbasiert)
                    #
                    # Rechte- und Dokumentenfilter laufen in SQL statt
                    # nachtraeglich in Python. Dort hing der Rechtecheck an
                    # meta.get('access', 'shared') -- Chunks ohne access-Key
                    # galten damit als oeffentlich.
                    for q, _ in sonden:
                        treffer = keyword_index.search(
                            q,
                            st.session_state["username"],
                            limit=broad_k,
                            file_names=selected_docs or None,
                            folders=selected_folders or None)
                        liste = [{"text": h["text"], "meta": h["meta"], "probe": q}
                                 for h in treffer]
                        if liste:
                            ranglisten.append(liste)

                # --- 2.5 RANGFOLGE (Fusion der Ranglisten) ---
                unique_docs = {}
                if ranglisten:
                    kandidaten = sum(len(l) for l in ranglisten)
                    gewaehlt = ranking.rank(ranglisten, top_k,
                                            bewerter=reranker)

                    for text, score, item in gewaehlt:
                        # Kopie: die Metadaten kommen direkt aus ChromaDB und
                        # sollen nicht im Cache veraendert werden.
                        meta = dict(item["meta"] or {})
                        meta["found_by_query"] = item["probe"]
                        unique_docs[text] = meta

                    verfahren = ("Reranker" if reranker is not None
                                 else "Rangfolge-Fusion")
                    st.caption(f"🎯 *{verfahren}: {kandidaten} Treffer aus "
                               f"{len(ranglisten)} Ranglisten auf die besten "
                               f"{len(unique_docs)} destilliert.*")
                    
                # --- KONTEXT FÜR DAS LLM ZUSAMMENBAUEN ---
                dynamic_context = ""
                if unique_docs:
                    for doc_text, metadata in unique_docs.items():
                        file_n = metadata['file_name']
                        page_n = metadata.get('page', '?')
                        dynamic_context += f'<chunk file="{file_n}" page="{page_n}">\n{doc_text}\n</chunk>\n\n'
                else:
                    dynamic_context = "Keine relevanten Dokumenten-Abschnitte gefunden."
                # --- 2.8 DEBUG-ANSICHT ---
                with st.expander("🛠️ Debug-Röntgenblick (Was sieht das LLM?)"):
                    st.write(f"**Generierte Sonden:** {search_queries}")
                    if unique_docs:
                        for idx, (doc_text, metadata) in enumerate(unique_docs.items()):
                            st.markdown(f"**Rang {idx+1}** | 📄 `{metadata.get('file_name', '?')}` | 🎯 Sonde: *{metadata.get('found_by_query', '?')}*")
                            st.caption(f"{doc_text[:250]}...")
                    else:
                        st.write("Keine Chunks gefunden.")
                # --- 3. ANTWORT GENERIEREN ---
                # 1. Rolle aus der .env holen (mit Fallback)
                expert_role = os.getenv("EXPERT_ROLE", "Forschungsassistent für das Bauwesen")

                # 2. Prompt-Vorlage aus der Datei laden
                prompt_path = os.path.join(paths.BASE_DIR, "system_prompt.txt")
                
                try:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        raw_prompt = f.read()
                except FileNotFoundError:
                    # Notfall-Fallback, falls die Datei wirklich mal versehentlich gelöscht wird
                    raw_prompt = "Du bist ein {EXPERT_ROLE}.\n<context>\n{CONTEXT_PLATZHALTER}\n</context>\nBeantworte die Frage nur anhand des Kontexts."

                # 3. Platzhalter durch die echten Werte ersetzen
                system_prompt = raw_prompt.replace("{EXPERT_ROLE}", expert_role)
                system_prompt = system_prompt.replace("{CONTEXT_PLATZHALTER}", dynamic_context)
                
                api_messages = [{"role": "system", "content": system_prompt}]
                
                for msg in st.session_state.messages[-20:]:
                    api_messages.append({"role": msg["role"], "content": msg["content"]})
                
                # Die Antwort laufend ausgeben statt auf den kompletten Text zu
                # warten. Auf einem lokalen 27B-Modell dauert eine Antwort
                # leicht eine halbe Minute -- ohne Streaming ist das eine
                # halbe Minute leerer Bildschirm.
                stream = chat_client.chat.completions.create(
                    model=chat_model,
                    messages=api_messages,
                    stream=True,
                    timeout=ANSWER_TIMEOUT,
                )

                def token_stream():
                    for part in stream:
                        if not part.choices:
                            continue
                        delta = part.choices[0].delta
                        if delta and delta.content:
                            yield delta.content

                answer = st.write_stream(token_stream())
                
                # --- 4. QUELLEN IN DER SESSION SPEICHERN ---
                # Erst ALLE Quellen einsammeln ...
                unique_sources = {}
                for doc_text, metadata in unique_docs.items():
                    key = (metadata['file_name'], metadata.get('page', '?'))
                    if key not in unique_sources:
                        unique_sources[key] = []
                    unique_sources[key].append(doc_text)

                # ... und erst danach anhaengen und speichern. Lag dieser Block
                # innerhalb der Schleife, brach st.rerun() bereits im ersten
                # Durchlauf ab -- die Nachricht wurde mit genau einer Quelle
                # gespeichert, alle weiteren gingen verloren.
                message_data = {
                    "role": "assistant",
                    "content": answer,
                    "sources": [{"file": k[0], "page": k[1], "texts": v}
                                for k, v in unique_sources.items()]
                }

                st.session_state.messages.append(message_data)
                save_chat(st.session_state.current_chat_id, st.session_state.messages)

                # Rerun, damit die Nachricht oben durch die Chat-Schleife (mit Expandern) gezeichnet wird
                st.rerun()

            except Exception as e:
                st.error(f"Fehler bei der Verarbeitung: {e}")

else:
    st.info("Die Datenbank ist leer. Bitte nutze dein Hintergrund-Skript, um PDFs einzulesen.")