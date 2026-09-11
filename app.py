import streamlit as st
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import time
from datetime import datetime
import re

import paths
import sicherheit
import store
import keyword_index
import listenquellen
import quellticket
import sqldb
import sqlquellen
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
import lesen
import raeume
import owncloud
import sicherung
import benutzer
import notzugang
import chats
import geheim
import hintergrund
import sqlpruefung
from textutils import strip_boilerplate
from tables import build_table_chunks

paths.bootstrap()

# --- SCHLUESSEL DA? ---
#
# Anhalten statt weiterlaufen, und zwar bevor irgendetwas geschrieben
# wird. Ohne Schluessel liest die Anwendung keinen verschluesselten
# Chat -- sie wuerde ihn fuer leer halten und beim naechsten Speichern
# im Klartext ueberschreiben. Aus einem behebbaren Lesefehler waere
# damit ein Datenverlust geworden.
_schl_zustand, _schl_meldung = geheim.zustand()
if _schl_zustand == "unlesbar":
    st.error("Der Installationsschluessel ist nicht lesbar.")
    st.code(_schl_meldung, language="text")
    st.caption("Die Anwendung haelt hier an. Liefe sie weiter, "
               "wuerde sie vorhandene Chatverlaeufe fuer leer "
               "halten und beim naechsten Speichern im Klartext "
               "ueberschreiben.")
    st.stop()

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
sql_client = llm.client("SQL")


@st.cache_data(ttl=3600, show_spinner="Lese die Struktur der Datenbank...")
def lade_sql_schema(raum=""):
    """Tabellen und Spalten, gelesen MIT DEN RECHTEN DIESES RAUMS.

    Die Struktur wird nicht gepflegt, sondern gelesen -- damit stimmt
    sie auch dann noch, wenn dort eine Spalte hinzukommt.

    Der Raum steht im Schluessel, nicht der Zugang: ein Passwort
    gehoert in keinen Zwischenspeicher-Schluessel. Und je Raum ein
    eigener Eintrag ist noetig, weil zwei Konten verschiedene Tabellen
    sehen -- ein gemeinsamer Zwischenspeicher zeigte dem einen das
    Schema des anderen.

    Eine Stunde gehalten, weil sich ein Schema selten aendert, eine
    Aenderung aber ohne Neustart ankommen soll. Auch der ERFOLGLOSE
    Versuch wird gehalten: sonst wartet jeder Seitenaufbau erneut
    SQL_TIMEOUT Sekunden auf einen Server, der nicht antwortet.
    """
    z = sqlquellen.zugang(raum) if raum else None
    if not sqldb.ist_konfiguriert(z):
        return "", ""
    try:
        return sqldb.lade_schema(z), ""
    except Exception as e:
        return "", str(e)

# --- LOGIN SYSTEM ---
#
# Passwortpruefung, Rollen und das Protokoll liegen in benutzer.py -- die
# Oberflaeche entscheidet nichts davon selbst. Vorher stand die
# bcrypt-Pruefung hier, eine zweite in create_user.py und eine dritte in
# manage_users.py; wer eine davon aenderte, aenderte die anderen nicht mit.
# Nach dieser Zeit ohne Klick ist die Sitzung vorbei. Vorher gab es keine
# Grenze: ein offener Browser an einem Arbeitsplatz blieb angemeldet, bis
# jemand von Hand ausloggte oder der Container neu startete.
SITZUNG_MINUTEN = paths.env_int("SITZUNG_MINUTEN", 480)


def sitzung_abgelaufen():
    if SITZUNG_MINUTEN <= 0:
        return False
    letzte = st.session_state.get("letzte_tat")
    if letzte is None:
        return False
    return (time.time() - letzte) > SITZUNG_MINUTEN * 60


# Was zu einer Sitzung gehoert -- an EINER Stelle. Vorher stand die
# Liste beim Ablauf, und der Abmeldeknopf loeschte nur den Namen: der
# Chat des Vorgaengers blieb im Sitzungszustand stehen. Wer sich danach
# am selben Browser anmeldete, sah dessen Verlauf samt Bildern -- und
# die erste eigene Frage speicherte ihn unter dem neuen Namen. Die
# Verschluesselung half nicht: die Kopie war fuer den Neuen
# verschluesselt.
# Eine gueltige Bescheinigung aus der Adresszeile gilt wie eine
# Anmeldung. Geprueft wird sie in benutzer.pruefe_merkzettel: Frist,
# Unterschrift, und ob es den Zugang ueberhaupt noch gibt -- ein
# geloeschter Zugang ist sofort draussen, auch wenn die Frist laeuft.
if "username" not in st.session_state:
    _wer = benutzer.pruefe_merkzettel(st.query_params.get("sitzung", ""))
    if _wer:
        st.session_state["username"] = _wer
        st.session_state["letzte_tat"] = time.time()


SITZUNGSSCHLUESSEL = ("username", "letzte_tat", "current_chat_id",
                      "messages", "last_loaded_chat", "chat_besitzer",
                      "pdf_upload_nr", "listen_upload_nr")


def beende_sitzung():
    """Alles vergessen, was zu dieser Anmeldung gehoert."""
    for schluessel in SITZUNGSSCHLUESSEL:
        st.session_state.pop(schluessel, None)
    # Auch die Bescheinigung aus der Adresszeile. Ohne das waere
    # Abmelden eine Geste: der naechste Aufbau loeste sie wieder ein,
    # und wer sich abmeldet, weil er den Rechner verlaesst, waere
    # weiter angemeldet.
    try:
        del st.query_params["sitzung"]
    except (KeyError, Exception):
        pass


if "username" in st.session_state and sitzung_abgelaufen():
    beende_sitzung()
    st.session_state["sitzung_lief_ab"] = True

if "username" not in st.session_state:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🔐 LocaNoto Login</h1>", unsafe_allow_html=True)

    if st.session_state.pop("sitzung_lief_ab", False):
        st.info(f"Die Sitzung war laenger als {SITZUNG_MINUTEN} Minuten "
                f"ohne Eingabe und wurde beendet.")

    zustand = benutzer.zustand()
    if zustand == benutzer.LEER:
        st.warning("Keine Benutzer gefunden. Bitte führe zuerst "
                   "'create_user.py' auf dem Server aus.")
        st.stop()
    if zustand == benutzer.MANIPULIERT:
        # Kein Abbruch: die Anmeldung der bestehenden Nutzer funktioniert
        # weiter. Was nicht funktioniert, ist die Anmeldung eines von Hand
        # eingetragenen Zugangs -- und genau das soll hier stehen.
        gesperrt = benutzer.ungueltige()
        st.error("Die Benutzerdatei wurde ausserhalb der Anwendung "
                 "geändert."
                 + (f" Gesperrt: {', '.join(gesperrt)}." if gesperrt else ""))

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            login_user = st.text_input("Benutzername").strip().lower()
            login_pass = st.text_input("Passwort", type="password")
            submit_button = st.form_submit_button("Einloggen", use_container_width=True)

            if submit_button:
                # Eine Meldung fuer beide Faelle. "Benutzer existiert nicht"
                # verriet, welche Kennungen es gibt -- die halbe Arbeit fuer
                # jemanden, der Passwoerter durchprobiert.
                if benutzer.pruefe(login_user, login_pass):
                    st.session_state["username"] = login_user
                    st.session_state["letzte_tat"] = time.time()
                    # Befristete Bescheinigung in die Adresszeile, damit
                    # ein Neuladen nicht wieder vor der Anmeldemaske
                    # endet. Nur wenn der Betreiber es eingeschaltet
                    # hat -- sie steht sichtbar in der Adresse, und wer
                    # die Adresse weitergibt, gibt die Anmeldung mit.
                    _zettel = benutzer.merkzettel(login_user)
                    if _zettel:
                        st.query_params["sitzung"] = _zettel
                    st.rerun()
                else:
                    st.error("Anmeldung fehlgeschlagen.")

    st.stop()

st.session_state["letzte_tat"] = time.time()

# Jeder Nutzer hat einen eigenen Raum, und zwar von der Anmeldung an
# und nicht erst nach dem ersten Upload. Vorher war er nur gedacht:
# die Suche nahm ihn mit, in der Verwaltung stand er nicht, und ein
# Abzug haette ihn uebergangen.
raeume.sichere_anlage_privat(st.session_state["username"])


# --- ADMIN ---
#
# Die Rolle steht in der Benutzerdatei und ist mitsigniert. ADMIN_USERS aus
# der Umgebung greift nur noch, solange die Datei aus der Zeit vor den
# Signaturen stammt -- eine Umgebungsvariable laesst sich am Container
# setzen, ohne die Benutzerdatei anzufassen, und war damit ein Weg, sich
# Verwalterrechte zu geben.
def _oc_bericht(bericht, was):
    """Zeigt, was in ownCloud geschehen ist -- und was nicht.

    Nie als Fehlschlag des Ganzen: der Nutzer beziehungsweise der Raum ist
    in LocaNoto zu diesem Zeitpunkt schon angelegt, und ein nicht
    erreichbares ownCloud darf das nicht rueckgaengig machen. Was fehlt,
    steht hier und laesst sich mit "Ablage einrichten" nachholen -- der
    Ablauf ist wiederholbar.
    """
    if not owncloud.eingerichtet():
        return
    if bericht.get("schritte"):
        st.caption("ownCloud: " + " · ".join(bericht["schritte"]))
    for f in bericht.get("fehler") or []:
        st.warning("ownCloud: " + f)
    if bericht.get("fehler"):
        st.caption(f"{was} ist in LocaNoto angelegt. Die Ablage in ownCloud "
                   f"laesst sich unter *ownCloud* nachholen.")


def is_admin():
    return _ist_verwalter(st.session_state.get("username", ""))


# --- SIDEBAR (UI) ---
with st.sidebar:
    # --- NEU: LOGOUT HIER OBEN ---
    st.caption(f"👤 Angemeldet als: **{st.session_state['username']}**")
    if st.button("🚪 Ausloggen", use_container_width=True):
        beende_sitzung()
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


# --- CHAT-SPEICHERUNG ---
#
# Liegt in chats.py: verschluesselt, und der Titel steht in der Datei statt
# im Dateinamen. Vorher hiess ein Verlauf "Pruefristen_Kessel_26-08-26.json"
# -- damit verriet schon das Verzeichnis, worum es ging, ohne dass jemand
# eine Datei oeffnen musste.
def get_user_chat_dir():
    return chats.ordner(st.session_state["username"])


def get_all_chats():
    """[(kennung, titel, geaendert)], neueste zuerst."""
    return chats.liste(st.session_state["username"])


def load_chat(chat_id):
    return chats.lade(st.session_state["username"], chat_id)


def save_chat(chat_id, messages, titel=None):
    chats.speichere(st.session_state["username"], chat_id, messages, titel)


def _anzeigefertig(text):
    """Markdown, das AUCH halbfertig richtig aussieht.

    Ein Codeblock beginnt mit ``` und endet mit ```. Waehrend er
    geschrieben wird, ist der zweite noch nicht da -- und Markdown
    zeigt bis dahin rohen Text mit drei Anfuehrungszeichen davor.
    Gerade bei Code ist das die haesslichste Art zu warten: man sieht
    eine Minute lang Zeilen ohne Einrueckung und ohne Faerbung, und
    erst am Ende springt alles in Form.

    Eine ungerade Zahl von Zaeunen bekommt deshalb einen
    Schlusszaun -- nur fuer die Anzeige. Gespeichert wird der
    unveraenderte Text.
    """
    if text.count("```") % 2:
        return text + "\n" + "``" + "`"
    return text


def _strom_zeichnen(strom, kennung, bisher, takt=2.0):
    """Zeichnet die Antwort waehrend sie entsteht. Gibt sie zurueck.

    Ersetzt st.write_stream: das kann den Text nicht anfassen, bevor
    es ihn zeigt, und genau das ist hier noetig -- ein halber
    Codeblock muss beim Zeichnen geschlossen werden, beim Speichern
    nicht.

    Der Mitschnitt bleibt: alle paar Sekunden wird abgelegt, was schon
    da ist. Bricht der Lauf ab, ist die Antwort nicht verloren.
    """
    platz = st.empty()
    teile = []
    letzte = time.time()
    for stueck in strom:
        teile.append(stueck if isinstance(stueck, str) else str(stueck))
        platz.markdown(_anzeigefertig("".join(teile)))
        if time.time() - letzte >= takt:
            letzte = time.time()
            try:
                save_chat(kennung, bisher + [{"role": "assistant",
                                              "content": "".join(teile),
                                              "unvollstaendig": True}])
            except Exception:
                # Ein misslungener Zwischenstand darf die Antwort nicht
                # kosten -- sie laeuft ja gerade.
                pass
    ganz = "".join(teile)
    platz.markdown(_anzeigefertig(ganz))
    return ganz


def _mitschreiben(strom, kennung, bisher, takt=2.0):
    """Gibt den Strom weiter UND legt ihn unterwegs ab.

    Der Anlass ist ein beobachteter Verlust: eine Antwort war beim
    Schreiben zu sehen, verschwand mitten im Strom, und nach dem
    Neuladen war sie nicht da. Der Grund liegt im Ablauf, nicht in der
    Ursache des Abbruchs -- gespeichert wurde erst NACH dem letzten
    Stueck. Bricht der Skriptlauf vorher ab, laeuft die Speicherzeile
    nie, und es gibt kein Ereignis, an dem sich das nachholen liesse.

    Was den Lauf abbricht, ist dabei zweitrangig: eine unterbrochene
    WebSocket-Verbindung, ein Neustart des Pods, ein geschlossener
    Browser. Gegen alle drei hilft dasselbe -- unterwegs ablegen.

    Der Takt ist ein Kompromiss: jedes Stueck einzeln waere bei einer
    langen Antwort ein Schreibvorgang je Wort, gar nicht ist der
    Zustand von vorher. Zwei Sekunden kosten bei einer halben Minute
    Antwort rund fuenfzehn kleine Schreibvorgaenge.

    Ein so abgelegter Zwischenstand ist als unvollstaendig markiert.
    Ohne die Markierung saehe ein abgebrochener Satz wie eine fertige
    Antwort aus -- und das waere schlimmer als der Verlust, weil
    niemand es bemerkt.
    """
    teile = []
    letzte = time.time()
    for stueck in strom:
        teile.append(stueck if isinstance(stueck, str) else str(stueck))
        yield stueck
        if time.time() - letzte >= takt:
            letzte = time.time()
            try:
                save_chat(kennung, bisher + [{"role": "assistant",
                                              "content": "".join(teile),
                                              "unvollstaendig": True}])
            except Exception:
                # Ein misslungener Zwischenstand darf die Antwort nicht
                # kosten -- sie laeuft ja gerade.
                pass


def delete_chat(chat_id):
    chats.loesche(st.session_state["username"], chat_id)


def chat_titel(chat_id):
    return chats.titel(st.session_state["username"], chat_id)


# --- WESSEN CHAT LIEGT HIER? ---
#
# Zweite Sicherung neben beende_sitzung(): der Sitzungszustand kann
# einen Chat tragen, der einem anderen gehoert -- nach einem Abbruch,
# einem Browser, der die Sitzung wiederherstellt, einem Fehler in einer
# kuenftigen Aenderung. Gehoert er nicht dem Angemeldeten, wird er
# verworfen statt weitergeschrieben.
if st.session_state.get("chat_besitzer") != st.session_state["username"]:
    for schluessel in ("current_chat_id", "messages", "last_loaded_chat"):
        st.session_state.pop(schluessel, None)
    st.session_state["chat_besitzer"] = st.session_state["username"]

# --- CHAT STATE INITIALISIEREN ---
# Welcher Chat ist gerade aktiv?
if "current_chat_id" not in st.session_state:
    vorhanden = get_all_chats()
    if vorhanden:
        st.session_state.current_chat_id = vorhanden[0][0]
    else:
        # Die Kennung ist zufaellig und sagt nichts. Der Titel entsteht nach
        # der ersten Frage und steht in der Datei, nicht im Dateinamen.
        st.session_state.current_chat_id = chats.neue_kennung()

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
    return store.client()

chroma_client = init_chromadb()


def raum_sammlung(kennung, anlegen=True):
    """Die Sammlung eines Raums."""
    return store.sammlung(raeume.sammlung(kennung), anlegen=anlegen)


def mein_notzugang():
    """Fremde persoenliche Raeume, in die dieser Nutzer gerade darf.

    Ein Notzugang muss von zwei Personen getragen sein und gilt 24
    Stunden -- siehe notzugang.py. Hier wird er EINMAL geholt und von da
    an weitergereicht, damit es genau eine Stelle gibt, an der die
    Ausnahme entsteht.
    """
    if not st.session_state.get("username"):
        return []
    return _notzugang_raeume(st.session_state["username"])


def meine_sammlungen(nur=None):
    """[(raum, sammlung)] fuer den angemeldeten Nutzer."""
    return pipeline.sammlungen(st.session_state["username"], nur=nur,
                               notzugang=mein_notzugang())


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
    if not keyword_index.schema_aktuell():
        # Ein Index von vor den Raeumen hat keine Raumspalte und kann
        # deshalb nicht nach Raum filtern. Er wird aus den Sammlungen neu
        # aufgebaut -- ohne Modell, ohne die Originaldateien.
        return keyword_index.rebuild_from_raeume(_alle_raum_sammlungen())

    # Zahlen vergleichen statt nur "ist er leer": schreibt ein anderer
    # Prozess in die Sammlungen -- ein abgekoppelter Ingest, ein CronJob im
    # Cluster --, dann erreicht er diesen Index nicht. Ohne die Pruefung
    # fehlen dessen Treffer bis zum naechsten Start, und niemand sieht
    # warum, weil die Vektorsuche ja antwortet.
    paare = _alle_raum_sammlungen()
    passt, im_index, in_sammlungen = keyword_index.passt_zu(paare)
    if not passt:
        return keyword_index.rebuild_from_raeume(paare)
    return im_index


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


# Der Indexaufbau darf den Start nicht verhindern.
#
# Er verbessert die Suche, er ist keine Voraussetzung fuer sie: ohne
# Stichwortindex antwortet die Anwendung weiter ueber die Vektoren, nur
# schlechter bei woertlichen Treffern. Bisher beendete jeder Fehler an
# dieser Stelle -- volle Platte, ein Netzlaufwerk ohne Sperren, eine
# gerissene Schwelle -- die gesamte Anwendung mit einer Fehlerseite. Der
# Schaden war jedes Mal um Groessenordnungen groesser als die Ursache.
try:
    init_keyword_index()
except Exception as _index_fehler:
    st.warning(
        "Der Stichwortindex konnte nicht aufgebaut werden. Gesucht wird "
        "vorerst nur ueber die Vektoren -- Antworten kommen, woertliche "
        "Treffer koennen fehlen. Nachholen mit `python rebuild_index.py`."
        "\n\nGrund: " + str(_index_fehler)[:400])

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
def verschiebe_dokument(filename, von_raum, nach_raum):
    """Verschiebt ein Dokument samt Abschnitten in einen anderen Raum.

    Das ist der Nachfolger der Freigabe. Fruher wurde ein Merkmal in den
    Metadaten umgeschrieben -- ein Zeichen, und aus privat wurde
    oeffentlich. Jetzt wandern die Abschnitte tatsaechlich in eine andere
    Sammlung, weil die Sammlung die Grenze ist.

    Die Vektoren werden mitgenommen, nicht neu berechnet: sie liegen vor,
    und ein Neueinlesen waere Modellzeit fuer ein vorhandenes Ergebnis.
    """
    quelle = raum_sammlung(von_raum, anlegen=False)
    if quelle is None:
        return False, "Der Ausgangsraum hat keine Daten."
    # store.hole und nicht quelle.get: Chroma kann das Vektorsegment einer
    # Sammlung noch nicht abgelegt haben und den Leser dann nicht aufbauen.
    # Ohne die Wiederholung schluege das Verschieben mit einem Rueckverfolg
    # in der Oberflaeche fehl -- und der Nutzer wuesste nur, dass es nicht
    # ging.
    daten = store.hole(quelle, raeume.sammlung(von_raum),
                       where=store.datei_filter(filename),
                       include=["documents", "metadatas", "embeddings"])
    ids = daten.get("ids") or []
    if not ids:
        return False, "Keine Abschnitte gefunden."
    vektoren = daten.get("embeddings")
    if vektoren is None or len(vektoren) != len(ids):
        return False, ("Die Vektoren fehlen -- ohne sie waere das ein "
                       "Neueinlesen.")

    metas = []
    for m in daten.get("metadatas") or []:
        meta = dict(m or {})
        meta["raum"] = nach_raum
        # access und owner bleiben als Herkunftsangabe stehen, sie steuern
        # aber nichts mehr. Sie zu loeschen wuerde nur die Frage "wer hat
        # das hochgeladen" unbeantwortbar machen.
        metas.append(meta)

    # Der DATEINAME wandert mit umgeschluesselt, nicht nur der Text.
    # Er ist mit dem Raum beglaubigt, in dem er lag; unveraendert
    # uebernommen laesst er sich im Zielraum nicht mehr oeffnen, und
    # _metadaten_verdeckt merkt das nicht -- die Funktion sieht einen
    # verschluesselten Wert und laesst ihn stehen. Auffallen wuerde es
    # erst Wochen spaeter unter einer Antwort, als "(nicht lesbar)"
    # anstelle der Quelle.
    metas = store.metadaten_umschluesseln(von_raum, nach_raum, metas)

    ziel = raum_sammlung(nach_raum)
    # Umschluesseln: der Geheimtext ist mit dem Raum beglaubigt, in dem
    # er lag. Unveraendert uebernommen liesse er sich im neuen Raum nie
    # wieder oeffnen -- ein Dokument, das nach dem Verschieben stumm
    # unlesbar ist, und niemand saehe warum.
    _docs = store.umschluesseln(von_raum, nach_raum,
                                daten.get("documents") or [],
                                st.session_state.get("username", "?"))
    store.schreibe(ziel, ids, documents=_docs,
                   metadatas=metas, embeddings=vektoren)
    quelle.delete(ids=ids)

    keyword_index.delete_document(filename, raum=von_raum)
    # In den Stichwortindex geht beides im Klartext -- Text UND Name.
    # Mit verdecktem Namen faende der Dokumentfilter die Datei nicht
    # mehr und ein spaeteres Loeschen liesse ihre Abschnitte stehen.
    keyword_index.add_chunks(
        zip(ids, store.klartext(von_raum, daten.get("documents") or [],
                                st.session_state.get("username", "?")),
            store.metadaten_klartext(nach_raum, metas)))
    refresh_document_index()

    # Die Datei geht mit. Seit jeder Raum seinen eigenen Ablageordner hat,
    # waeren die Abschnitte sonst im neuen Raum und die Datei im alten --
    # und der alte ist fuer den neuen gesperrt. Die Quellenansicht zeigte
    # dann keine Seite mehr, ohne zu sagen warum. Umgekehrt bliebe ein
    # freigegebenes Dokument koerperlich im persoenlichen Ordner liegen.
    nachsatz = _verschiebe_datei(filename, von_raum, nach_raum)
    return True, (f"Nach '{raeume.bezeichnung(nach_raum)}' verschoben."
                  + nachsatz)


def _verschiebe_datei(filename, von_raum, nach_raum):
    """Bringt die Datei in den Ordner des Zielraums. Rueckgabe: Nachsatz.

    Ist am Ziel schon eine Datei dieses Namens, bleibt sie liegen und die
    Datei wird NICHT verschoben: umbenennen ginge nicht, weil der
    Dateiname in den Metadaten jedes Abschnitts steht und dort der
    Schluessel ist. Lieber eine fehlende Seitenansicht als ein Bestand,
    in dem Abschnitt und Datei auseinanderlaufen -- und gesagt wird es.
    """
    quelle = dokument_pfad(filename, von_raum)
    if not quelle or not os.path.exists(quelle):
        return ""

    def basis(raum):
        return (DOCS_DIR if raum == raeume.ALLGEMEIN
                else paths.raum_ordner(raum))

    try:
        rel = os.path.relpath(os.path.dirname(quelle), basis(von_raum))
    except ValueError:
        rel = "."
    # Ein Dokument aus der Zeit vor den Raeumen liegt im Wurzelbereich und
    # damit ausserhalb des Ordners seines Raums. Dann kein Unterordner.
    if rel.startswith("..") or rel in (".", ""):
        rel = ""
    ziel_ordner = os.path.join(basis(nach_raum), rel) if rel \
        else basis(nach_raum)
    ziel = os.path.join(ziel_ordner, os.path.basename(quelle))
    if os.path.normpath(ziel) == os.path.normpath(quelle):
        return ""
    if os.path.exists(ziel):
        return (" Die Datei blieb liegen: am Ziel gibt es bereits eine "
                "gleichen Namens. Die Originalseite laesst sich dort "
                "nicht anzeigen.")
    try:
        os.makedirs(ziel_ordner, exist_ok=True)
        os.replace(quelle, ziel)
    except OSError as e:
        return f" Die Datei liess sich nicht mitnehmen ({e})."
    return ""


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


def fremde_ordner(eigener_raum):
    """Die Ablageordner ALLER anderen Raeume.

    Dorthin darf keine Suche nach einem Dateinamen greifen. Zwei Raeume
    duerfen dieselbe 'Angebot.pdf' fuehren, und welche davon gemeint ist,
    entscheidet der Raum -- nicht die Reihenfolge, in der os.walk sie
    findet.
    """
    return [paths.raum_ordner(k) for k in raeume.liste()
            if k != eigener_raum]


def dokument_pfad(filename, raum):
    """Der Pfad zu einem Dokument AUS SICHT eines Raums.

    Erst im eigenen Ordner, dann im gemeinsamen Wurzelbereich -- dort
    liegen die Dateien aus der Zeit vor den Raeumen. Die Ordner der
    anderen Raeume bleiben aussen vor.
    """
    return paths.finde_dokument(filename, bevorzugt=paths.raum_ordner(raum),
                                ausser=fremde_ordner(raum)) or ""


def remove_pdf_if_orphaned(filename, raum=None):
    """Loescht die Datei von der Platte -- aber nur, wenn kein Abschnitt
    mehr auf sie zeigt.

    Alle Raeume teilen sich DOCS_DIR. Wird die Datei bedingungslos
    entfernt, verliert ein gleichnamiges Dokument in einem anderen Raum
    seine Quellenansicht.

    raum sagt, WESSEN Datei gemeint ist. Ohne ihn wurde nur
    DOCS_DIR/<name> geloescht -- alles in einem Sachgebiets- oder
    Raumordner blieb liegen, und der Bestand wuchs mit Dateien, auf die
    kein Abschnitt mehr zeigte.
    """
    for _raum, sml in _alle_raum_sammlungen():
        try:
            if sml.get(where=store.datei_filter(filename),
                       include=[])["ids"]:
                return False
        except Exception:
            # Lieber die Datei behalten als sie einem Raum wegnehmen,
            # dessen Sammlung gerade nicht antwortet.
            return False
    file_path = (dokument_pfad(filename, raum) if raum
                 else os.path.join(DOCS_DIR, filename))
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    return True


_QUELLENMUSTER = re.compile(
    r"\[([^\[\]]{1,120}?),\s*(?:Seite|S\.)\s*(\d+)\]")


def _quellen_klickbar(text, quellen, nr):
    """Macht "[Datei, Seite 12]" im Antworttext anklickbar.

    Zwei Dinge auf einmal, weil eines allein nicht genuegt:
    der Anker (#q...) springt an die Stelle, der Abfrageparameter
    (?quelle=...) loest einen Lauf aus, in dem sich der richtige
    Aufklapper oeffnet. Ohne den Anker landet man oben, ohne den
    Parameter vor einem zugeklappten Kasten.

    Nur Verweise, zu denen es WIRKLICH eine Quelle gibt, werden zu
    Verweisen. Ein Modell nennt gelegentlich eine Seite, die es aus dem
    Zusammenhang erschlossen hat; ein Link, der ins Leere fuehrt, ist
    schlechter als gar keiner, weil er Nachpruefbarkeit vortaeuscht.
    """
    if not quellen or not text:
        return text

    wohin = {}
    for k, q in enumerate(quellen):
        name = str(q.get("file") or "").strip().lower()
        seite = str(q.get("page") or "").strip()
        if name:
            wohin[(name, seite)] = k

    def ersetze(treffer):
        name, seite = treffer.group(1).strip(), treffer.group(2).strip()
        k = wohin.get((name.lower(), seite))
        if k is None:
            return treffer.group(0)
        # EIN EIGENER TAB, mit einem Ticket statt einer Anmeldung.
        #
        # Ein neuer Tab ist eine neue Sitzung -- dort ist niemand
        # angemeldet. Die Anmeldung mitzugeben waere der naheliegende
        # Weg und der falsche: sie stuende in jedem Quellenverweis,
        # also in jeder Antwort, und wer eine Antwort weiterleitet,
        # gaebe seine Anmeldung mit.
        #
        # Ein Ticket nennt genau eine Fundstelle und gilt Minuten. Es
        # entsteht beim ZEICHNEN, nicht beim Speichern: ein alter Chat
        # traegt weiter den blossen Text und bekommt beim Ansehen ein
        # frisches.
        _tk = quellticket.stelle_aus(
            (quellen[k] or {}).get("raum") or raeume.ALLGEMEIN,
            name, seite, st.session_state.get("username", ""))
        if _tk:
            return f"[{name}, Seite {seite}](quelle?t={_tk})"
        # Ohne Schluessel kein Ticket -- dann bleibt die Sprungmarke.
        #
        # Mit "?quelle=..." war es fuer den Browser ein Verweis auf
        # eine ANDERE Adresse, und Streamlit oeffnet solche in einem
        # neuen Tab. Dort ist die Sitzung leer -- man landete also bei
        # der Anmeldemaske statt bei der Fundstelle. Die Bequemlichkeit
        # kostete genau das, wofuer sie gedacht war.
        #
        # Eine reine Sprungmarke bleibt im Tab. Der Preis: der
        # Aufklapper geht nicht von selbst auf -- dafuer braeuchte der
        # Server den Klick, und ein Klick, der den Server erreicht, ist
        # eine Navigation. Springen und einmal klicken ist besser als
        # springen, sich neu anmelden und dann suchen.
        return f"[{name}, Seite {seite}](#q{nr}-{k})"

    # NICHT in Codebloecke hineinschreiben. Dort ist "[a, Seite 3]"
    # kein Beleg, sondern Code -- ein Markdown-Verweis mittendrin
    # zerstoert ihn, und beim Kopieren merkt man es erst, wenn es
    # nicht laeuft.
    aus, offen = [], False
    for teil in text.split("```"):
        aus.append(teil if offen else _QUELLENMUSTER.sub(ersetze, teil))
        offen = not offen
    return "```".join(aus)


def _loeschfreigabe(kennung, zahl, key):
    """Freigabe fuer einen Loeschvorgang, der einen ganzen Raum trifft.

    Ein Haken war zu wenig, und zwar aus einem bestimmten Grund: er
    haengt an seinem eigenen Schluessel, nicht am Ziel. Wer ihn fuer
    Raum A setzt und danach im Auswahlfeld auf Raum B wechselt, hat
    eine gesetzte Freigabe fuer einen Raum, den er nie bestaetigt hat
    -- ein Klick, und B ist leer.
    #
    Die Kennung einzutippen bindet die Freigabe an das Ziel. Sie laesst
    sich nicht stehen lassen: wechselt die Auswahl, passt der Text
    nicht mehr. Und sie zwingt dazu, den Namen zu LESEN, statt eine
    Gewohnheitsbewegung auszufuehren.

    Ein Abzug ist die einzige Umkehr. Deshalb steht sein Alter dabei --
    "vor drei Wochen" ist eine andere Auskunft als "heute Nacht".
    """
    st.warning(f"{zahl:,} Abschnitte. Nicht rueckgaengig zu machen.")
    try:
        _abz = sicherung.liste()
        if _abz:
            st.caption(f"Neuester Abzug: {_abz[0][0]}")
        else:
            st.caption("KEIN Abzug vorhanden. Danach ist es endgueltig.")
    except Exception:
        pass
    st.caption("Zum Bestaetigen die Kennung des Raums eintippen:")
    st.code(kennung, language=None)
    eingabe = st.text_input("Kennung", key=f"{key}_text",
                            label_visibility="collapsed",
                            placeholder=kennung)
    return eingabe.strip() == kennung


def loesche_dokument(filename, raum, kennung_statt_name=False):
    """Loescht ein Dokument aus genau einem Raum.

    Der Raum ist nicht optional. Ohne ihn traefe der Loeschbefehl jeden
    Abschnitt dieses Dateinamens -- auch die in anderen Raeumen, auf die
    der Loeschende gar keinen Zugriff hat.
    """
    sml = raum_sammlung(raum, anlegen=False)
    if sml is None:
        return False, "Der Raum hat keine Daten."
    if kennung_statt_name:
        # Der Verwalter hat nur die Kennung, nicht den Namen -- das ist
        # der Sinn. Geloescht wird ueber sie. Stichwortindex und Datei
        # brauchen den Namen, den es hier nicht gibt; beides holt der
        # naechste Aufbau nach: der Index entsteht aus den Sammlungen,
        # und eine Datei ohne Abschnitte faellt beim Aufraeumen weg.
        sml.delete(where={"datei_id": filename})
        refresh_document_index()
        return True, (f"Eintrag {filename[:12]}... aus "
                      f"'{raeume.bezeichnung(raum)}' entfernt.")
    sml.delete(where=store.datei_filter(filename))
    keyword_index.delete_document(filename, raum=raum)
    remove_pdf_if_orphaned(filename, raum)
    refresh_document_index()
    return True, f"'{filename}' aus '{raeume.bezeichnung(raum)}' entfernt."


def list_foreign_private_documents(current_user):
    """(raum, file_name) fremder Raeume -- nur wo das erlaubt ist.

    Fuer den Verwaltungsbereich, damit verwaiste Ablagen ausgeschiedener
    Mitarbeiter loeschbar bleiben. Aufgelistet werden Raum und Dateiname,
    nie der Inhalt: ein Loeschrecht ist kein Leserecht.

    Im strengen Betrieb (PRIVAT_STRENG) faellt auch der Dateiname weg. Dort
    gilt "jeder weiss nur, was er wissen muss", und ein Dateiname ist eine
    Auskunft: "Angebot_Kunde_Meier.pdf" verraet den Vorgang, ohne dass
    jemand die Datei oeffnet. Was dann bleibt, steht in fremde_raeume() --
    Raum und Anzahl.
    """
    seen = set()
    for kennung, sml in _alle_raum_sammlungen():
        if raeume.darf_lesen(current_user, kennung):
            continue
        if not raeume.darf_dateien_sehen(current_user, kennung,
                                         ist_verwalter=is_admin()):
            continue
        try:
            data = sml.get(include=["metadatas"])
        except Exception:
            continue
        # GRIFF OHNE EINSICHT.
        #
        # Der Verwalter soll eine verwaiste Ablage aufraeumen koennen,
        # ohne zu erfahren, worum es ging. Ein Dateiname verraet den
        # Vorgang -- "Kuendigung_Mueller_2026.pdf" muss dafuer niemand
        # oeffnen. Wer den Inhalt wirklich braucht, geht ueber den
        # Notzugang, und dann stehen zwei Namen im Protokoll.
        #
        # datei_id ist dafuer das Mittel: eine bestimmte Kennung je
        # DATEI, aus dem Namen abgeleitet und nicht umkehrbar.
        #
        # Der Geheimtext des Namens taugt NICHT dafuer, obwohl er
        # danach aussieht: er traegt einen zufaelligen Nonce, ist also
        # je ABSCHNITT verschieden. Die Liste zeigte damit acht
        # Eintraege fuer eine Datei -- und ein Loeschen traf genau
        # einen Abschnitt davon, sichtbar nur daran, dass die Datei
        # danach noch da war.
        for m in data.get("metadatas") or []:
            if not m:
                continue
            kenn = m.get("datei_id") or ""
            if not kenn:
                # Abschnitte aus der Zeit vor der Verschluesselung
                # tragen keine Kennung. Ohne diesen Zweig waere die
                # Liste bei einem alten Bestand einfach leer -- und der
                # Verwalter suchte den Fehler bei den Rechten.
                #
                # Der Name liegt dort ohnehin im Klartext; ihn zu
                # hashen gibt denselben Griff wie ueberall und
                # verraet nichts, was nicht schon offen laege.
                import raumschluessel
                kenn = raumschluessel.datei_id(m.get("file_name") or "")
            if kenn:
                seen.add((kennung, kenn))
    return sorted(seen)


def fremde_raeume(current_user):
    """[(raum, anzahl)] der Raeume, die dieser Nutzer nicht lesen darf.

    Ohne Dateinamen. Das ist die Ansicht, die im strengen Betrieb bleibt:
    ein Verwalter sieht, DASS ein Raum Inhalt hat, und kann ihn als Ganzes
    loeschen -- ohne zu erfahren, was darin liegt.
    """
    aus = []
    for kennung, sml in _alle_raum_sammlungen():
        if raeume.darf_lesen(current_user, kennung):
            continue
        try:
            anzahl = sml.count()
        except Exception:
            continue
        if anzahl:
            aus.append((kennung, anzahl))
    return sorted(aus)


def process_uploaded_pdf(uploaded_file, raum, projekt="",
                         bilder=False):
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
    if raum not in raeume.schreibbar(st.session_state["username"],
                                     is_admin()):
        raum = raeume.sichere_anlage_privat(st.session_state["username"])
    
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
    if os.path.exists(pdf_path) and _gehoert_anderem_raum(dateiname, raum):
        pdf_path = paths.freier_name(ziel_ordner, dateiname)
        dateiname = os.path.basename(pdf_path)
        st.warning(f"Eine Datei dieses Namens liegt bereits in der Ablage "
                   f"und gehoert nicht zu diesem Raum. Gespeichert als "
                   f"'{dateiname}'.")

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
            ok_oc, meldung_oc = owncloud.lege_ab(
                pdf_path,
                owncloud.raum_pfad(raum) + "/" + os.path.basename(pdf_path))
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
                    "owner": st.session_state["username"], "type": "text"})
                ids.append(f"{dateiname}_p{nummer}_c{i}")
        _n, _h = _speichern_chunks(chunks, metadatas, ids, raum)
        return _n, " ".join(x for x in (_h, wolke_hinweis) if x)

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
                    "owner": st.session_state["username"],
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
                    "owner": st.session_state["username"],
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
            _melder = st.empty()

            def _stand(nr, gesamt):
                _melder.caption(f"Beschreibe Bilder ... Seite {nr}/{gesamt}")

            for _seite, _text, _art in bildtext.beschreibungen(
                    doc, dateiname, _stand):
                chunks.append(_text)
                metadatas.append({
                    "file_name": dateiname,
                    "page": _seite,
                    "raum": raum,
                    "folder": projekt,
                    "owner": st.session_state["username"],
                    # Die Art steht mit drin: bei einer gescannten
                    # Seite IST die Beschreibung der Inhalt, bei einer
                    # Abbildung ergaenzt sie den Text daneben. Wer
                    # spaeter nachsieht, woher eine Auskunft kommt,
                    # soll den Unterschied sehen.
                    "type": "image", "bildart": _art,
                })
                ids.append(f"{dateiname}_p{_seite}_bild_{len(ids)}")
            _melder.empty()
        except Exception as e:
            bild_hinweis = f"Bilder nicht beschrieben: {e}"

    _n, _h = _speichern_chunks(chunks, metadatas, ids, raum)
    return _n, " ".join(x for x in (_h, wolke_hinweis, bild_hinweis) if x)


def _speichern_chunks(chunks, metadatas, ids, raum):
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
    refresh_document_index()
    fehlend = len(chunks) - len(keep)
    return len(keep), (f"{fehlend} von {len(chunks)} Abschnitten liessen "
                       f"sich nicht vektorisieren und fehlen."
                       if fehlend else "")

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
def load_document_index(username, notzugang_=()):
    return pipeline.dokumente(username, notzugang=list(notzugang_))


def refresh_document_index():
    """Nach jeder Aenderung an Dokumenten aufrufen."""
    load_document_index.clear()
    _leeren()


# --- ANZEIGEWERTE ZWISCHENSPEICHERN ---
#
# Streamlit fuehrt dieses Skript bei JEDEM Klick von oben nach unten aus,
# und st.expander ist nicht traege: sein Inhalt laeuft mit, ob er offen ist
# oder nicht. Ein Klick auf irgendeinen Knopf kostete deshalb eine
# PROPFIND-Anfrage an ownCloud, mehrere vollstaendige Metadatenabzuege ueber
# HTTP, drei Verzeichnisdurchlaeufe und rund zwanzig HMAC-Pruefungen der
# Benutzerdatei -- fuer Zahlen, die sich in dieser Sekunde nicht geaendert
# haben.
#
# Die Haltbarkeiten sind danach gewaehlt, wie schnell eine Aenderung
# sichtbar werden MUSS, nicht danach, was billig waere:
#
#   Rechte          5 s   -- eine entzogene Rolle soll schnell greifen
#   eigene Zahlen  15 s   -- Anzeige, nach einem Upload ohnehin geleert
#   Verwaltung     30 s   -- Verzeichnisse, Abzuege, Rueckmeldungen
#   ownCloud       60 s   -- eine Anfrage ueber das Netz

def _unvollstaendig(stand):
    """Fehlte diesem Abzug beim Sichern ein Raum?

    Aeltere Abzuege haben die Angabe 'vollstaendig' nicht -- ihr Fehlen
    heisst nicht "unvollstaendig", sondern "damals nicht vermerkt". Also
    zaehlt hier nur ein ausdruecklich vermerkter Fehlschlag.
    """
    return bool(stand.get("fehler")) or stand.get("vollstaendig") is False


def _leeren():
    """Nach jeder Aenderung an Dokumenten oder Raeumen aufrufen."""
    _zahl_abschnitte.clear()
    _fremdes.clear()
    _verwaltungsstand.clear()
    _notzugang_raeume.clear()
    store.vergiss()


@st.cache_data(ttl=15, show_spinner=False)
def _notzugang_raeume(name):
    """Die freigegebenen Raeume -- kurz zwischengespeichert.

    15 Sekunden, wie die eigenen Zahlen: die Datei wird sonst bei jedem
    Klick gelesen und ihre Signatur geprueft. Kurz genug, dass ein
    geschlossener Zugang sofort zu ist -- und wer ihn schliesst, leert
    ohnehin.
    """
    return notzugang.raeume_fuer(name)


@st.cache_data(ttl=5, show_spinner=False)
def _ist_verwalter(name):
    """Rolle aus der signierten Benutzerdatei -- hoechstens alle 5 s neu.

    is_admin() wird je Durchlauf zwanzigmal gefragt, und jede Frage las die
    Datei und prueft eine HMAC-Signatur je Eintrag.
    """
    return benutzer.ist_admin(name)


@st.cache_data(ttl=15, show_spinner=False)
def _zahl_abschnitte(name, raeume_liste):
    """Wie viele Abschnitte dieser Nutzer sehen kann."""
    return sum(sml.count() for _r, sml in pipeline.sammlungen(name))


@st.cache_data(ttl=30, show_spinner=False)
def _fremdes(name, ist_verwalter):
    """(dateien, raeume) fremder Raeume -- zwei volle Metadatenabzuege."""
    return (list_foreign_private_documents(name), fremde_raeume(name))


@st.cache_data(ttl=30, show_spinner=False)
def _verwaltungsstand():
    """Verzeichnisse und Zaehler fuer die Verwaltungsbereiche."""
    return {
        "bestand": paths.bestand(),
        "abzuege": sicherung.liste(),
        "rueckmeldungen": feedback.zaehle(),
        "journal": keyword_index.journal_modus(),
    }


@st.cache_data(ttl=60, show_spinner=False)
def _owncloud_stand():
    """Erreichbarkeit von ownCloud -- eine Anfrage ueber das Netz.

    Sie stand bisher im Aufbau der Seitenleiste und lief damit bei jedem
    Klick. Ist ownCloud langsam oder nicht erreichbar, wartete die ganze
    Oberflaeche darauf.
    """
    if not owncloud.eingerichtet():
        return False, owncloud.beschreibung()
    return owncloud.pruefe()


dateien_je_raum = load_document_index(
    st.session_state["username"], tuple(mein_notzugang()))
meine_raeume = sorted(dateien_je_raum)
all_available_files = sorted({d for liste in dateien_je_raum.values()
                              for d in liste})

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
        st.session_state.current_chat_id = chats.neue_kennung()
        st.session_state.messages = []
        st.rerun()

    # 2. Chat-Verlauf Dropdown
    #
    # Die Kennung ist zufaellig, der Titel kommt aus dem verschluesselten
    # Verzeichnis. Angezeigt wird der Titel, ausgewaehlt die Kennung.
    _eintraege = get_all_chats()
    _titel = {k: t for k, t, _g in _eintraege}
    existing_chats = [k for k, _t, _g in _eintraege]
    if existing_chats or st.session_state.current_chat_id:
        # Ein noch nicht gespeicherter Chat steht nicht im Verzeichnis --
        # ohne ihn faende die Auswahl ihren eigenen Eintrag nicht.
        if st.session_state.current_chat_id not in existing_chats:
            existing_chats.insert(0, st.session_state.current_chat_id)
            _titel.setdefault(st.session_state.current_chat_id, "Neuer Chat")

        selected_chat = st.selectbox(
            "Vorherige Chats laden:",
            existing_chats,
            index=existing_chats.index(st.session_state.current_chat_id),
            format_func=lambda x: _titel.get(x, "Chat")
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
    st.markdown("---")
    st.header("🎯 Dokumenten-Filter")

    # --- RAUM ---
    #
    # Zuerst der Raum, weil er die groebste Einschraenkung ist: er
    # entscheidet, welche Sammlungen ueberhaupt gefragt werden. Leer
    # gelassen werden alle erlaubten durchsucht -- das ist der Normalfall
    # und soll keine Klicks kosten.
    raum_optionen = [r for r, _s in meine_sammlungen()]
    selected_raeume = st.multiselect(
        "Raum:",
        options=raum_optionen,
        default=[],
        format_func=raeume.bezeichnung,
        help="Leer lassen, um alle Räume zu durchsuchen, die du sehen "
             "darfst."
    ) if len(raum_optionen) > 1 else []
    # --- PROJEKT ---
    #
    # Eine Stufe zwischen Raum und Datei, und nur im eigenen Raum. Es
    # schraenkt ueber die DATEIEN ein und nicht ueber einen eigenen
    # Filter: dann gibt es genau einen Weg, auf dem die Suche
    # eingegrenzt wird, und keinen zweiten, den jemand zu pflegen
    # vergisst.
    _mein_raum_f = raeume.privat_kennung(st.session_state["username"])
    _projekte = {k: v for k, v in
                 pipeline.projekte(st.session_state["username"],
                                   _mein_raum_f,
                                   notzugang=mein_notzugang()).items() if k}
    _projekt_dateien = []
    if _projekte:
        _gewaehlt_p = st.multiselect(
            "Projekt:", options=sorted(_projekte), default=[],
            help="Nur im eigenen Raum. Leer lassen, um alles zu "
                 "durchsuchen.")
        for _p in _gewaehlt_p:
            _projekt_dateien += _projekte[_p]

    selected_docs = st.multiselect(
        "Suche beschränken auf:", 
        options=all_available_files,
        default=[],
        help="Leer lassen, um in allen Dokumenten zu suchen."
    )
    # Ein gewaehltes Projekt wirkt wie eine Dateiauswahl. Beides
    # zugleich waere ein Widerspruch, den niemand aufloest -- deshalb
    # gewinnt die ausdrueckliche Dateiauswahl.
    if _projekt_dateien and not selected_docs:
        selected_docs = _projekt_dateien


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
    # GEFILTERT, und zwar hier und nicht erst bei der Abfrage: an dieser
    # Liste haengen die Anzeige, die Bereichsauswahl und die Abfrage.
    # Wird nur die Abfrage gefiltert, verraet die Anzeige daneben
    # weiterhin, welche Listen es gibt -- und Dateinamen wie
    # "Kuendigungen_2026.xlsx" sind fuer sich schon die Auskunft.
    _eintraege = tabellen.sichtbar(_katalog.get("eintraege", []),
                                   st.session_state.get("username", ""))

    # --- DATENBANK ---
    #
    # Der Abschnitt erscheint nur, wenn eine Verbindung hinterlegt ist
    # -- entweder aus der Umgebung oder als Zugang eines Raums.
    sql_aktiv = False
    sql_schema = ""
    sql_raum = ""
    _zugaenge = sqlquellen.fuer_benutzer(st.session_state["username"],
                                         notzugang=mein_notzugang())
    if _zugaenge or sqldb.ist_konfiguriert():
        st.markdown("---")
        st.header("\U0001f5c4\ufe0f Datenbank")

        # DER EIGENE ZUGANG STEHT VORN und ist die Vorgabe. Ein
        # persoenliches Konto umfasst in aller Regel die Rechte der
        # Raeume, in denen jemand ist -- umgekehrt gilt das nicht: ein
        # Raumkonto ist auf den Raum zugeschnitten.
        #
        # Automatisch alle Konten nacheinander zu versuchen waere
        # bequem und falsch: dieselbe Frage liefe noch einmal mit
        # fremden Rechten, und niemand saehe, mit welchem Konto die
        # Antwort entstand.
        _wahlen = [r for r, _z in _zugaenge]
        if sqldb.ist_konfiguriert():
            _wahlen.append("")
        if len(_wahlen) > 1:
            sql_raum = st.selectbox(
                "Zugang", _wahlen,
                format_func=lambda r: (raeume.bezeichnung(r) if r
                                       else "Vorgabe aus der Umgebung"),
                key="sql_zugang")
        else:
            sql_raum = _wahlen[0] if _wahlen else ""
        _z = sqlquellen.zugang(sql_raum) if sql_raum else None
        if _z:
            st.caption(f"Angemeldet als `{_z.get('benutzer')}`")

        sql_schema, sql_fehler = lade_sql_schema(sql_raum)
        if sql_fehler:
            # Kurz und im Klartext. Die Meldung des Treibers nennt
            # Adresse und Zustand der Verbindung -- das gehoert nicht
            # auf den Bildschirm jedes Nutzers.
            st.warning("Keine Verbindung zur Datenbank. Die Antworten "
                       "stammen allein aus den Dokumenten.")
            if is_admin():
                with st.expander("Meldung des Treibers"):
                    st.code(sql_fehler, language="text")
            if st.button("Erneut verbinden", use_container_width=True):
                lade_sql_schema.clear()
                st.rerun()
        elif sql_schema:
            sql_aktiv = st.toggle(
                "Datenbank einbeziehen",
                value=paths.env_flag("SQL_DEFAULT_ON", False),
                key="sql_an",
                help="Das Modell formuliert eine SELECT-Abfrage. "
                     "Ausgefuehrt wird sie mit dem Konto oben.")

    if (_eintraege or tabellen.vorhanden() or is_admin()
            or listenquellen.liste()):
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

        # --- ERKANNTE BLAETTER ---
        #
        # Die Kopfzeilenerkennung liegt meistens richtig. Wo nicht, ist der
        # Katalog fuer diese Datei falsch -- Spalten heissen dann s_1 statt
        # "Bezeichnung", und das Modell antwortet zwar richtig, kann seine
        # Auskunft aber nicht benennen. Deshalb sichtbar und korrigierbar.
        if _eintraege:
            with st.expander(f"Erkannte Blaetter ({len(_eintraege)})"):
                for _e in _eintraege:
                    _kenn = _e["datei"] + (f"#{_e['blatt']}" if _e["blatt"]
                                           else "")
                    _kopf = int(_e.get("kopfzeile", 0))
                    _felder = [s["feld"] for s in _e["spalten"]]
                    _namenlos = sum(1 for s in _e["spalten"]
                                    if not s["name"] or
                                    s["name"].lower().startswith(
                                        ("unnamed", "spalte ")))
                    st.markdown(f"**{_kenn}** · Kopfzeile {_kopf + 1} "
                                f"· {_e['zeilen']} Zeilen")
                    if _namenlos:
                        st.warning(f"{_namenlos} von {len(_felder)} Spalten "
                                   f"ohne Namen -- vermutlich die falsche "
                                   f"Kopfzeile.")
                    st.caption(", ".join(_felder[:10])
                               + (" ..." if len(_felder) > 10 else ""))

                    if is_admin():
                        _neu = st.number_input(
                            "Kopfzeile", min_value=1, max_value=50,
                            value=_kopf + 1, key=f"kopf_{_kenn}",
                            help="Die Zeile mit den Spaltennamen, von 1 "
                                 "gezaehlt.")
                        if int(_neu) - 1 != _kopf:
                            if st.button("Uebernehmen und neu einlesen",
                                         key=f"kopfb_{_kenn}",
                                         use_container_width=True):
                                tabellen.setze_kopfzeile(
                                    _e["datei"], _e["blatt"], int(_neu) - 1)
                                with st.spinner("Lese neu ein ..."):
                                    tabellen.baue_katalog()
                                st.rerun()
                    st.markdown("---")

        if _katalog.get("fehler"):
            with st.expander(f"Nicht lesbar ({len(_katalog['fehler'])})"):
                for datei, grund in _katalog["fehler"]:
                    st.caption(f"`{datei}` -- {grund}")

        # --- MEIN EIGENER ORDNER ---
        #
        # Fuer jeden, nicht nur fuer Verwalter: der persoenliche
        # Listenordner ist der einzige, den sein Besitzer besser kennt
        # als die IT. Er darf ihn deshalb selbst eintragen -- aber nur
        # INNERHALB seines Bereichs.
        #
        # Der Grund fuer die Grenze ist derselbe wie ueberall hier: der
        # Container liest mit einer Kennung. Ein frei waehlbarer Pfad
        # waere kein "meine Ablage anpassen", sondern "mir Zugriff
        # geben" -- die Anwendung hat die Rechte und prueft nur, was
        # jemand tippt.
        _mein_raum = raeume.privat_kennung(
            st.session_state.get("username", ""))
        _mein_bereich = listenquellen.eigener_bereich(
            st.session_state.get("username", ""))
        if _mein_bereich:
            with st.expander("\U0001f4c1 Mein Listenordner", expanded=False):
                st.caption(
                    f"Nur du siehst die Listen aus diesem Ordner. Er "
                    f"muss innerhalb von `{_mein_bereich}` liegen -- ein "
                    f"anderer waere ein Zugriff, den dir niemand "
                    f"gegeben hat.")
                _mp_alt = listenquellen.pfad_von(_mein_raum) or _mein_bereich
                _mp = st.text_input("Ordner", value=_mp_alt,
                                    key="mein_listenordner")
                if st.button("Uebernehmen", use_container_width=True,
                             key="mein_listenordner_b"):
                    _ok_mp, _m_mp = listenquellen.setze_raum(
                        _mein_raum, _mp,
                        benutzer=st.session_state.get("username", "?"))
                    if not _ok_mp:
                        st.error(_m_mp)
                    else:
                        with st.spinner("Lese die Listen ein ..."):
                            tabellen.baue_katalog()
                        st.success("Uebernommen.")
                        time.sleep(1)
                        st.rerun()

        # --- MEIN DATENBANKZUGANG ---
        #
        # Sein Datenbankkonto kennt nur er selbst. Muesste ein
        # Verwalter es eintragen, muesste er es KENNEN -- und damit
        # waere aus "jeder mit seinen Rechten" wieder ein gemeinsames
        # Konto geworden, nur muehsamer.
        if sqldb.ist_konfiguriert() or sqlquellen.liste():
            _mz = sqlquellen.zugang(_mein_raum) or {}
            with st.expander("\U0001f5c4\ufe0f Mein Datenbankzugang",
                             expanded=False):
                st.caption(
                    "Dein eigenes Konto an der Fachdatenbank. Fragen "
                    "laufen dann mit DEINEN Rechten -- und das Modell "
                    "sieht nur die Tabellen, die du sehen darfst.")
                _mz_b = st.text_input("Benutzer",
                                      value=_mz.get("benutzer", ""),
                                      key="mein_sql_b")
                _mz_p = st.text_input("Passwort",
                                      value=_mz.get("passwort", ""),
                                      type="password", key="mein_sql_p")
                if st.button("Uebernehmen", use_container_width=True,
                             key="mein_sql_ok"):
                    _ok_mz, _m_mz = sqlquellen.setze(
                        _mein_raum, {"benutzer": _mz_b, "passwort": _mz_p},
                        benutzer=st.session_state.get("username", "?"))
                    (st.success if _ok_mz else st.error)(_m_mz)
                    if _ok_mz:
                        time.sleep(1)
                        st.rerun()

        # Neu einlesen heisst: den Ordner vollstaendig durchgehen und den
        # Katalog neu anlegen. Noetig nur, wenn Dateien dazukommen oder sich
        # Spalten aendern -- neue Zeilen wirken ohne Zutun.
        if is_admin():
            # --- QUELLEN JE RAUM ---
            #
            # Eine Zeile je Quelle: "raum = pfad". Ein Textfeld und kein
            # Formular je Zeile, weil Verwalter das einmal einrichten und
            # danach jahrelang nicht anfassen -- und weil sich so das
            # Ganze auf einen Blick lesen laesst, statt sich durch
            # aufgeklappte Zeilen zu arbeiten.
            with st.expander("Listenquellen je Raum", expanded=False):
                st.caption(
                    "Eine Zeile je Quelle: **raum = pfad**. Der Raum "
                    "entscheidet, wer die Listen sieht -- dieselbe "
                    "Berechtigung wie bei den Dokumenten. "
                    f"`{listenquellen.MUSTER_RAUM}` steht fuer den "
                    "persoenlichen Raum JEDES Nutzers; der Pfad braucht "
                    f"dann `{listenquellen.PLATZHALTER}`, das durch den "
                    "jeweiligen Anmeldenamen ersetzt wird.")
                _vorlage = "\n".join(
                    f"{q['raum']} = {q['pfad']}"
                    for q in listenquellen.liste())
                _eingabe = st.text_area(
                    "Quellen", value=_vorlage, height=140,
                    placeholder="allgemein = /mnt/listen/allgemein\n"
                                "einkauf = /srv/abteilung/einkauf\n"
                                + listenquellen.MUSTER_RAUM
                                + " = /mnt/heim/"
                                + listenquellen.PLATZHALTER + "/Listen",
                    key="listenquellen_text")
                st.caption(
                    "Das persoenliche Laufwerk ist gegenueber Kollegen "
                    "am Dateiserver privat, gegenueber dieser Anwendung "
                    "nicht: sie liest es mit ihrem Dienstkonto. Die "
                    "Trennung zwischen den Nutzern macht ab hier "
                    "LocaNoto -- derselbe Grad an Zusicherung wie beim "
                    "persoenlichen Raum.")
                if st.button("Quellen speichern und einlesen",
                             use_container_width=True,
                             key="listenquellen_speichern"):
                    _neu = []
                    for _z in (_eingabe or "").splitlines():
                        _z = _z.strip()
                        if not _z or _z.startswith("#"):
                            continue
                        _r, _t, _p = _z.partition("=")
                        if not _t:
                            st.error(f"'{_z}' hat kein '=' -- erwartet "
                                     f"wird 'raum = pfad'.")
                            _neu = None
                            break
                        _neu.append({"raum": _r.strip(),
                                     "pfad": _p.strip()})
                    if _neu is not None:
                        ok, meldung = listenquellen.speichere(_neu)
                        if not ok:
                            st.error(meldung)
                        else:
                            with st.spinner("Lese Listen ein ..."):
                                _k, _f = tabellen.baue_katalog()
                            st.success(f"{meldung} "
                                       f"{len(_k['eintraege'])} Blaetter.")
                            time.sleep(1)
                            st.rerun()
                if listenquellen.WURZELN:
                    st.caption("Erlaubte Wurzeln (LISTEN_WURZELN): "
                               + ", ".join(f"`{w}`"
                                           for w in listenquellen.WURZELN))

            # Der eine Ordner von frueher. Er gilt weiter, solange oben
            # keine Quelle steht -- dann als Quelle des allgemeinen
            # Raums. Eine Umstellung, die am ersten Tag alle Listen
            # verschwinden liesse, wuerde zurueckgedreht statt
            # verstanden.
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
                # Der Schluessel traegt eine laufende Nummer: Streamlit
                # behaelt die Datei im Feld, bis das Widget einen neuen
                # bekommt. Ohne das steht die abgelegte Datei weiter da,
                # als sei nichts geschehen.
                _nr = st.session_state.setdefault("listen_upload_nr", 0)
                _hoch = st.file_uploader(
                    "Liste hochladen", accept_multiple_files=True,
                    type=[e.lstrip(".") for e in tabellen.ENDUNGEN],
                    key=f"listen_upload_{_nr}")
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
                            st.session_state["listen_upload_nr"] = _nr + 1
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
    # Wie beim Listen-Upload: ohne wechselnden Schluessel bleibt die Datei
    # nach dem Verarbeiten im Feld stehen.
    _pdf_nr = st.session_state.setdefault("pdf_upload_nr", 0)
    uploaded_file = st.file_uploader(
        "Dokument hochladen", key=f"pdf_upload_{_pdf_nr}",
        type=["pdf", "PDF", "docx", "md", "markdown", "txt"],
        help="PDF, Word, Markdown oder Text. Wird vektorisiert und "
             "durchsuchbar.")
    if uploaded_file:
        # --- RAUM ---
        #
        # Der Raum entscheidet, wer das Dokument sehen kann. Vorgabe ist
        # der eigene: wer nicht nachdenkt, teilt nichts. Der allgemeine
        # Raum bleibt Admins vorbehalten -- passend dazu, dass auch nur sie
        # daraus loeschen koennen.
        _mein = raeume.privat_kennung(st.session_state["username"])
        # schreibbar() haelt die Regel selbst: der allgemeine Raum nur
        # fuer Verwalter, ein persoenlicher nur fuer seinen Besitzer.
        _ziele = raeume.schreibbar(st.session_state["username"], is_admin())
        if _mein not in _ziele:
            _ziele.insert(0, _mein)
        ziel_raum = st.selectbox(
            "Raum", _ziele, index=_ziele.index(_mein),
            format_func=raeume.bezeichnung,
            help="Bestimmt, wer das Dokument finden kann.")
        if ziel_raum == _mein:
            st.caption("Nur für dich sichtbar.")
        else:
            _m = (raeume.raum(ziel_raum) or {}).get("mitglieder") or []
            st.caption("Sichtbar für alle." if "*" in _m
                       else f"Sichtbar für {len(_m)} Mitglieder.")

        # PROJEKT -- nur im eigenen Raum, und nur zum Sortieren.
        #
        # Wer viele Vorgaenge hat, will eine Frage zu Projekt B
        # stellen, ohne dass A mitantwortet. Das ist keine
        # Rechtefrage, sondern eine der Menge: ein Modell, das zwoelf
        # Abschnitte aus fuenf Vorgaengen bekommt, mischt sie.
        #
        # Geteilt wird ueber Raeume. Ein Ordner, der aussieht wie ein
        # Recht und keines ist, war schon einmal da und hiess
        # Sachgebiet.
        _projekt = ""
        if ziel_raum == _mein:
            _bekannt = [p for p in pipeline.projekte(
                st.session_state["username"], _mein) if p]
            _projekt = st.text_input(
                "Projekt (optional)", value="", key="upload_projekt",
                help="Sortiert im eigenen Raum. Vorhandene: "
                     + (", ".join(_bekannt) if _bekannt else "noch keine"))

        # Ein Schalter und keine Selbstverstaendlichkeit: ein
        # Modellaufruf je Bild, bei einem 200-Seiten-Scan also
        # Minuten. Wer das nicht erwartet, haelt die Anwendung fuer
        # haengengeblieben.
        _bilder = st.checkbox(
            "Abbildungen und gescannte Seiten beschreiben",
            value=False, key="upload_bilder",
            help="Fuer PDFs ohne Textebene und fuer Schaubilder. "
                 "Kostet einen Modellaufruf je Bild.")
        if _bilder and uploaded_file.name.lower().endswith(".pdf"):
            # Die Schaetzung VOR der Zustimmung. Sie kostet keinen
            # Modellaufruf -- gezaehlt wird im Dokument.
            try:
                import bildtext, pymupdf as _pm
                with _pm.open(stream=uploaded_file.getvalue(),
                              filetype="pdf") as _d:
                    _s, _a = bildtext.zaehle(_d)
                if _s or _a:
                    st.caption(
                        f"\u2192 {_s} gescannte Seite(n), {_a} "
                        f"Abbildung(en) -- {_s + _a} Modellaufrufe.")
                else:
                    st.caption("\u2192 Nichts Bildliches gefunden.")
            except Exception as _e:
                st.caption(f"Nicht abschaetzbar: {_e}")

        if st.button("Hochladen & Vektorisieren"):
            with st.spinner("Verarbeite Dokument (das kann kurz dauern)..."):
                raeume.sichere_anlage_privat(st.session_state["username"])
                _n, _hinweis = process_uploaded_pdf(
                    uploaded_file, ziel_raum, _projekt, _bilder)
            refresh_document_index()
            if _n:
                st.success(f"'{uploaded_file.name}' in "
                           f"'{raeume.bezeichnung(ziel_raum)}' — "
                           f"{_n} Abschnitte durchsuchbar.")
                if _hinweis:
                    st.warning(_hinweis)
                st.session_state["pdf_upload_nr"] = _pdf_nr + 1
                time.sleep(1)
                st.rerun()
            else:
                # Kein Erfolg melden und NICHT neu laden: die Datei liegt
                # jetzt auf der Platte, ist aber in keiner Sammlung. Wer
                # hier ein gruenes "hinzugefuegt" sieht, sucht spaeter
                # vergeblich und haelt es fuer einen Fehler der Suche.
                st.error(f"'{uploaded_file.name}' wurde NICHT durchsuchbar.")
                st.warning(_hinweis or "Kein Abschnitt gespeichert.")
                st.caption("Die Datei liegt in der Ablage, aber kein "
                           "Abschnitt davon steht in der Suche. Behebe die "
                           "Ursache und lade sie erneut hoch.")

    # --- LANGE LAEUFE ---
    #
    # Der Upload vektorisiert Text und Tabellen. Bilder bleiben aussen vor:
    # eine Beschreibung dauert Minuten, und ein Dokument mit zehn
    # Abbildungen wuerde den Knopf eine Stunde blockieren, waehrend der
    # Nutzer vor einem Spinner sitzt.
    #
    # Deshalb hier, als eigener Prozess, der die Sitzung ueberlebt.
    if is_admin():
        with st.expander("🔄 Nachtragen und neu einlesen"):
            for _name, (_skript, _log, _titel) in hintergrund.LAEUFE.items():
                _aktiv = hintergrund.laeuft(_name)
                if _aktiv:
                    st.caption(f"**{_titel}** laeuft.")
                    st.code(hintergrund.protokoll(_name, 8) or "(noch keine "
                            "Ausgabe)", language="text")
                    if st.button("Abbrechen", key=f"stop_{_name}",
                                 use_container_width=True):
                        hintergrund.abbrechen(_name)
                        st.rerun()
                else:
                    if st.button(_titel, key=f"start_{_name}",
                                 use_container_width=True,
                                 help=f"Startet {_skript} als eigenen "
                                      f"Vorgang. Bereits Verarbeitetes wird "
                                      f"uebersprungen; die Oberflaeche "
                                      f"bleibt benutzbar."):
                        ok, meldung = hintergrund.starte(_name)
                        if ok:
                            st.success(meldung)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(meldung)
                    _letzte = hintergrund.protokoll(_name, 3)
                    if _letzte:
                        st.caption("Zuletzt:")
                        st.code(_letzte, language="text")
                st.markdown("---")
            st.caption("Die Anzeige aktualisiert sich beim naechsten Klick.")

    # --- DOKUMENTE JE RAUM ---
    #
    # Vorher standen hier zwei Listen, "gemeinsamer Pool" und "deine
    # privaten Dokumente", und dazu ein Admin-Bereich fuer die privaten
    # Dokumente anderer. Das waren drei Sonderfaelle eines einzigen
    # Gedankens: in welchem Raum liegt das Dokument.
    st.subheader("Dokumente")
    _raum_liste = [r for r, _s in meine_sammlungen()]
    if not _raum_liste:
        st.caption("Noch keine Dokumente.")
    for _r in _raum_liste:
        _dateien = dateien_je_raum.get(_r, [])
        with st.expander(f"{raeume.bezeichnung(_r)} ({len(_dateien)})",
                         expanded=(len(_raum_liste) == 1)):
            if not _dateien:
                st.caption("Leer.")
                continue
            for f in _dateien:
                st.caption(f"📄 {f}")

            # Verwalten darf, wer den Raum schreiben darf.
            _darf = raeume.darf_schreiben(st.session_state["username"], _r,
                                          is_admin())
            if not _darf:
                st.caption("Nur lesen.")
                continue

            st.markdown("---")
            _datei = st.selectbox("Dokument verwalten:", _dateien,
                                  key=f"verw_{_r}")
            _spalte1, _spalte2 = st.columns(2)
            with _spalte1:
                _andere = [x for x in raeume.schreibbar(
                    st.session_state["username"], is_admin()) if x != _r]
                _nach = st.selectbox("verschieben nach:",
                                     ["-"] + _andere,
                                     format_func=lambda x: (
                                         "-" if x == "-"
                                         else raeume.bezeichnung(x)),
                                     key=f"nach_{_r}")
                if st.button("Verschieben", key=f"vsch_{_r}",
                             disabled=(_nach == "-"),
                             use_container_width=True):
                    ok, meldung = verschiebe_dokument(_datei, _r, _nach)
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()
            with _spalte2:
                if st.button("🗑️ Löschen", key=f"del_{_r}",
                             use_container_width=True):
                    ok, meldung = loesche_dokument(_datei, _r)
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()

    # --- ADMIN: fremde Raeume ---
    #
    # Bewusst nur Raum und Dateiname, nie der Inhalt: Admins brauchen das
    # Loeschrecht fuer verwaiste Ablagen ausgeschiedener Mitarbeiter, aber
    # ein Loeschrecht ist kein Leserecht.
    if is_admin():
        foreign, _alle_fremd = _fremdes(
            st.session_state["username"], is_admin())
        _stille = [(r, n) for r, n in _alle_fremd
                   if r not in {x for x, _f in foreign}]

        if foreign:
            st.markdown("---")
            st.caption("👑 **Admin: Dokumente in fremden Räumen**")
            st.caption("Nur zur Verwaltung – diese Dokumente werden für "
                       "dich nicht durchsucht.")
            # ZWEISTUFIG, nach Raum. Eine flache Liste aller Dateien
            # aller Nutzer ist bei zwanzig Kollegen keine Uebersicht
            # mehr, sondern eine Wand -- und sie zeigt jedem Verwalter
            # beim blossen Aufklappen, woran alle anderen arbeiten.
            # Erst der Raum, dann die Datei: dann sieht man nur, wonach
            # man gesucht hat.
            _je_raum = {}
            for _r, _f in foreign:
                _je_raum.setdefault(_r, []).append(_f)
            _wahl_r = st.selectbox(
                "Raum", sorted(_je_raum),
                format_func=lambda r: (f"{raeume.bezeichnung(r)} "
                                       f"({len(_je_raum[r])})"),
                key="fremd_raum")
            _name_f = st.selectbox(
                "Eintrag", sorted(_je_raum[_wahl_r]),
                format_func=lambda k: k[:16] + "...", key="fremd_datei")
            st.caption(
                "Kennungen statt Namen: ein Dateiname verraet den "
                "Vorgang. Wer den Inhalt braucht, geht ueber den "
                "Notzugang -- dann stehen zwei Namen im Protokoll.")
            # Kein Zusammensetzen und Wiederzerlegen einer Beschriftung:
            # ein Dateiname mit " / " darin zerbrach das vorher, und
            # zwar still -- geloescht wurde dann etwas anderes oder
            # nichts.
            _raum_f = _wahl_r
            if st.button("🗑️ Endgültig löschen", use_container_width=True):
                ok, meldung = loesche_dokument(_name_f, _raum_f,
                                               kennung_statt_name=True)
                (st.success if ok else st.error)(meldung)
                time.sleep(1)
                st.rerun()

        # --- STRENGER BETRIEB ---
        #
        # Persoenliche Raeume anderer erscheinen hier ohne Dateinamen: dort
        # gilt "jeder weiss nur, was er wissen muss", und ein Dateiname ist
        # eine Auskunft. Was bleibt, ist ein Loeschrecht ohne Leserecht --
        # der Raum als Ganzes, mit Anzahl, ohne Inhalt.
        if _stille:
            st.markdown("---")
            st.caption("👑 **Admin: fremde persönliche Räume**")
            st.caption("Ohne Dateinamen – der strenge Betrieb "
                       "(`PRIVAT_STRENG`) ist eingeschaltet. Löschbar nur "
                       "als Ganzes.")
            _zahlen = dict(_stille)
            _wahl_s = st.selectbox(
                "Raum", [r for r, _n in _stille],
                format_func=lambda r: (raeume.bezeichnung(r) + " – "
                                       + format(_zahlen[r], ",")
                                       + " Abschnitte"),
                key="streng_wahl")
            _ok_s = _loeschfreigabe(_wahl_s, _zahlen[_wahl_s], "streng")
            if st.button("🗑️ Raum leeren",
                         use_container_width=True, disabled=not _ok_s):
                ok, meldung = store.loesche(raeume.sammlung(_wahl_s))
                keyword_index.delete_document_by_raum(_wahl_s)
                (st.success if ok else st.error)(meldung)
                refresh_document_index()
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
        # beschreibung() statt rerank_info: der Schnappschuss vom Start
        # wuerde "Endpunkt" zeigen, wenn der laengst ausgefallen ist -- oder
        # "Modell aus dem Image", wenn der Endpunkt laengst wieder da ist.
        _rangfolge = (reranker.beschreibung()
                      if hasattr(reranker, "beschreibung") else rerank_info)
        st.code(llm.uebersicht() + "\nRANGFOLGE   " + _rangfolge,
                language="text")
        if getattr(reranker, "endpunkt_erreichbar", lambda: True)() is False:
            st.warning("Der Rerank-Endpunkt antwortet gerade nicht. Die "
                       "Rangfolge kommt vorlaeufig aus der Fusion; der "
                       "Endpunkt wird von selbst wieder versucht.")

    # --- RUECKMELDUNGEN ---
    #
    # Die Arbeitsliste fuer glossar.txt und fuer Luecken im Bestand: hier
    # steht, was gefragt wurde und nichts fand.
    # --- VERWALTUNG ---
    #
    # Vierzehn Aufklapper untereinander sind kein Menue, sondern eine
    # Wand. Das meiste davon braucht ein Verwalter an einem
    # gewoehnlichen Tag nie -- also erst auf Zuruf.
    #
    # Ein Aufklapper um die Aufklapper ginge nicht: Streamlit laesst
    # sie nicht ineinander. Und ein Schalter je Gruppe waere
    # gefaehrlich -- dann liefe nur der gewaehlte Block, und einer,
    # der eine Angabe aus einem anderen benutzt, ginge still kaputt.
    _vw = False
    if is_admin():
        st.markdown("---")
        _vw = st.toggle("\U0001f6e0\ufe0f Verwaltung", value=False,
                        key="verwaltung_offen",
                        help="Benutzer, Raeume, Sicherung, Prompts und "
                             "alles Weitere zum Einrichten.")
    if _vw:
        zahlen = _verwaltungsstand()["rueckmeldungen"]
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
                    # Entschluesselt: auf der Platte liegt es
                    # verschluesselt, ausgewertet wird es im Klartext.
                    st.download_button(
                        "Protokoll herunterladen", feedback.als_text(),
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
    # --- BENUTZER VERWALTEN ---
    #
    # Vorher gab es das nur im Terminal, und dort ohne jede Nachfrage: wer
    # create_user.py starten konnte, legte sich einen Zugang an. Jetzt
    # verlangt das Skript die Anmeldung eines Verwalters -- und derselbe
    # Vorgang steht hier, weil ein Verwalter dafuer nicht auf den Server
    # steigen sollte.
    if _vw:
        st.caption("**Zugaenge**")
    if _vw:
        with st.expander("👥 Benutzer verwalten"):
            _zustand = benutzer.zustand()
            _gesperrt = benutzer.ungueltige()

            if _zustand == benutzer.UNSIGNIERT:
                st.warning(
                    "Die Benutzerdatei stammt aus der Zeit vor den "
                    "Signaturen. Bis sie signiert ist, gilt weiter "
                    "`ADMIN_USERS` aus der `.env`, und ein von Hand "
                    "eingetragener Zugang käme herein.")
                if st.button("Jetzt signieren", use_container_width=True):
                    ok, meldung = benutzer.neu_signieren(
                        von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()
            elif _zustand == benutzer.MANIPULIERT:
                st.error(
                    "Die Benutzerdatei wurde außerhalb der Anwendung "
                    "geändert."
                    + (f" Gesperrt, weil ohne gültige Signatur: "
                       f"{', '.join(_gesperrt)}." if _gesperrt else
                       " Es fehlt oder es kam ein Eintrag hinzu."))

            # Kollidierende Kennungen: zwei Nutzer, ein persoenlicher
            # Raum. Beim Anlegen wird das jetzt abgewiesen -- ein
            # Bestand kann es aber schon enthalten.
            _konflikte = raeume.konflikte(benutzer.namen())
            if _konflikte:
                st.error(
                    "Diese Kennungen teilen sich einen persoenlichen Raum "
                    "und sehen damit die Unterlagen des jeweils anderen: "
                    + "; ".join(
                        f"{', '.join(n)} -> {k}" for k, n in _konflikte)
                    + ". Eine der Kennungen umbenennen (neu anlegen, "
                    + "Dokumente verschieben, alte loeschen).")

            for _n in benutzer.namen():
                _e = benutzer.eintrag(_n) or {}
                _marke = "" if _e.get("_gueltig", True) else "  GESPERRT"
                st.caption(f"**{_n}** · {_e.get('rolle', '?')}"
                           f"{_marke}")

            st.markdown("---")
            _wahl = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + benutzer.namen(),
                key="benutzer_wahl")

            if _wahl == "(neu anlegen)":
                _name = st.text_input("Kennung", key="benutzer_neu_name")
                _rolle = st.selectbox(
                    "Rolle", list(benutzer.ROLLEN),
                    index=list(benutzer.ROLLEN).index("nutzer"),
                    key="benutzer_neu_rolle",
                    help="admin verwaltet Nutzer, Räume und den gemeinsamen Bestand. notzugang darf NICHTS davon — die Rolle bestätigt nur den Notzugang eines Verwalters zu einem persönlichen Raum, und gehört deshalb an jemanden, der kein Verwalter ist.")
                _pw1 = st.text_input(
                    f"Passwort (mindestens {benutzer.MIN_PASSWORT} Zeichen)",
                    type="password", key="benutzer_neu_pw1")
                _pw2 = st.text_input("Passwort wiederholen", type="password",
                                     key="benutzer_neu_pw2")
                if st.button("Benutzer anlegen", use_container_width=True,
                             disabled=not (_name.strip() and _pw1)):
                    if _pw1 != _pw2:
                        st.error("Die Eingaben stimmen nicht überein.")
                    else:
                        ok, meldung = benutzer.anlege(
                            _name, _pw1, _rolle,
                            von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)
                        if ok:
                            # ownCloud zieht mit: Konto, persoenlicher
                            # Ordner, Freigabe nur an ihn, dazu der
                            # gemeinsame Ordner. Der Nutzer muss dort
                            # nichts einrichten -- das ist der Sinn von
                            # "eingebettet".
                            with st.spinner("Richte die Ablage ein ..."):
                                _b = owncloud.richte_nutzer_ein(
                                    _name, _pw1, _name)
                            _oc_bericht(_b, "Der Zugang")
                            _leeren()
                            time.sleep(2 if _b.get("fehler") else 1)
                            st.rerun()
            else:
                _e = benutzer.eintrag(_wahl) or {}
                st.caption(f"Angelegt: {_e.get('angelegt', 'unbekannt')} "
                           f"· von: {_e.get('von', 'unbekannt')}")
                # Der Rueckfall geht ueber den NAMEN und nicht ueber eine
                # Zahl: als "notzugang" dazukam, waere aus dem frueheren
                # Index 1 ("nutzer") still die neue Rolle geworden.
                _neue_rolle = st.selectbox(
                    "Rolle", list(benutzer.ROLLEN),
                    index=(list(benutzer.ROLLEN).index(_e.get("rolle"))
                           if _e.get("rolle") in benutzer.ROLLEN
                           else list(benutzer.ROLLEN).index("nutzer")),
                    key=f"benutzer_rolle_{_wahl}",
                    help="admin verwaltet Nutzer, Räume und den gemeinsamen Bestand. notzugang darf NICHTS davon — die Rolle bestätigt nur den Notzugang eines Verwalters zu einem persönlichen Raum, und gehört deshalb an jemanden, der kein Verwalter ist.")
                if _neue_rolle != _e.get("rolle"):
                    if st.button("Rolle übernehmen", use_container_width=True,
                                 key=f"benutzer_rs_{_wahl}"):
                        ok, meldung = benutzer.rolle_setzen(
                            _wahl, _neue_rolle,
                            von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)
                        time.sleep(1)
                        st.rerun()

                _pw1 = st.text_input("Neues Passwort", type="password",
                                     key=f"benutzer_pw1_{_wahl}")
                _pw2 = st.text_input("Wiederholen", type="password",
                                     key=f"benutzer_pw2_{_wahl}")
                if st.button("Passwort setzen", use_container_width=True,
                             disabled=not _pw1, key=f"benutzer_pws_{_wahl}"):
                    if _pw1 != _pw2:
                        st.error("Die Eingaben stimmen nicht überein.")
                    else:
                        ok, meldung = benutzer.passwort_setzen(
                            _wahl, _pw1, von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)

                # Loeschen entfernt den Zugang, nicht die Daten. Chats und
                # der persoenliche Raum bleiben -- wer beides in einem Klick
                # zusammenlegt, loescht irgendwann mehr als gemeint.
                _sicher = st.checkbox(f"'{_wahl}' wirklich löschen",
                                      key=f"benutzer_x_{_wahl}")
                if st.button("Benutzer löschen", use_container_width=True,
                             disabled=not _sicher,
                             key=f"benutzer_del_{_wahl}"):
                    ok, meldung = benutzer.loesche(
                        _wahl, von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    if ok:
                        time.sleep(1)
                        st.rerun()

            # --- PROTOKOLL ---
            #
            # Verkettet: jeder Eintrag traegt den Hash des vorherigen. Eine
            # entfernte Zeile bricht die Kette, und die Pruefung sagt, an
            # welcher Stelle. Das verhindert nichts -- es macht ein
            # Aufraeumen im Nachhinein sichtbar.
            st.markdown("---")
            _kette_ok, _zeilen = benutzer.protokoll_pruefen()
            if _kette_ok:
                st.caption(f"Protokoll: {_zeilen} Einträge, Kette in Ordnung.")
            else:
                st.error(f"Das Protokoll ist ab Zeile {_zeilen} verändert "
                         f"oder es fehlt eine Zeile.")
            _log = benutzer.protokoll(letzte=20)
            if _log:
                st.code(chr(10).join(
                    f"{e.get('zeit', '?')}  {e.get('aktion', ''):<12} "
                    f"{e.get('ziel', ''):<16} von={e.get('von', '')} "
                    f"{e.get('hinweis', '')}".rstrip()
                    for e in reversed(_log)), language="text")

    # --- VERSCHLUESSELUNG ---
    #
    # Was verschluesselt ist, was nicht, und warum. Steht in der
    # Oberflaeche, weil ein Zustand, den man nur im Quelltext nachlesen
    # kann, bei einer Datenschutzfrage nicht hilft.
    if _vw:
        with st.expander("🔐 Verschlüsselung"):
            st.caption(f"Zustand: **{geheim.beschreibung()}**")
            if not geheim.verfuegbar():
                st.error(
                    "Chats, Anhänge und Rückmeldungen liegen im Klartext. "
                    "Ohne das Paket `cryptography` im Image kann nicht "
                    "verschlüsselt werden — `requirements.txt` prüfen und "
                    "neu bauen.")
            else:
                st.caption(
                    "Verschlüsselt: Chatverläufe samt Titeln, angehängte "
                    "Bilder, das Rückmeldungsprotokoll. Signiert: "
                    "Benutzerdatei und Zugangstoken, je Eintrag einzeln.")
                st.caption(
                    "**Nicht** verschlüsselt: der Text der Dokumente in der "
                    "Vektordatenbank. Er muss durchsuchbar bleiben und liegt "
                    "neben dem Vektor. Dafür ist die Verschlüsselung des "
                    "Datenträgers zuständig.")

            _offen_chats = chats.zaehle_klartext(st.session_state["username"])
            if _offen_chats:
                st.warning(f"{_offen_chats} eigene Chatdateien noch im "
                           f"Klartext. Sie werden beim nächsten Öffnen "
                           f"übernommen.")

            _offen_fb = feedback.klartextzeilen()
            if _offen_fb:
                st.warning(f"Im Rückmeldungsprotokoll stehen {_offen_fb} "
                           f"Zeilen noch im Klartext.")
                if st.button("Protokoll neu verschlüsseln",
                             use_container_width=True):
                    ok, anzahl = feedback.neu_verschluesseln()
                    if ok:
                        st.success(f"{anzahl} Zeilen neu geschrieben.")
                    else:
                        st.error("Konnte nicht geschrieben werden.")
                    time.sleep(1)
                    st.rerun()

            # Die Grenze ausdruecklich nennen. Ein Verwalter, der glaubt,
            # die Verschluesselung schuetze auch gegen jemanden mit
            # Serverzugang, traegt eine falsche Auskunft weiter.
            st.caption(
                "Der Schlüssel gehört der Installation, nicht dem Nutzer: "
                "ein Passwortwechsel lässt die Chats lesbar, und wer "
                "Dateizugriff auf `config/` hat, kann entschlüsseln. Das "
                "schützt gegen eine abgeflossene Sicherung oder ein "
                "kopiertes Volume, nicht gegen Serverzugang.")

    # --- NOTZUGANG ---
    #
    # Sichtbar fuer Verwalter UND fuer Traeger der Rolle, aber mit
    # verschiedenen Knoepfen: der eine beantragt, der andere bestaetigt.
    # Offene Zugaenge sieht jeder von beiden -- eine Kontrolle, von der nur
    # der weiss, der sie hat, kontrolliert nichts.
    _kann_bestaetigen = benutzer.hat_rolle(
        st.session_state["username"], "notzugang")
    if is_admin() or _kann_bestaetigen:
        _antraege = notzugang.antraege()
        _offen = notzugang.offene()
        _marke = ""
        if _kann_bestaetigen and _antraege:
            _marke = f" — {len(_antraege)} zu bestätigen"
        elif _offen:
            _marke = f" — {len(_offen)} offen"
        with st.expander("🔓 Notzugang" + _marke):
            st.caption(
                "Ein persönlicher Raum ist auch für Verwalter zu. Ist "
                "sein Besitzer nicht mehr erreichbar, führt der Weg "
                "hinein über **zwei Personen**: ein Verwalter beantragt, "
                "ein Träger der Rolle *notzugang* bestätigt. Danach gilt "
                f"er {notzugang.STUNDEN} Stunden. Beide Namen stehen im "
                "Protokoll.")
            st.caption(f"Stand: {notzugang.beschreibung()}")

            # --- offene Zugaenge, fuer beide Seiten sichtbar ---
            if _offen:
                st.markdown("**Gerade offen**")
                for _z in _offen:
                    _rest = max(0, (_z["bis"] - int(time.time())) // 60)
                    st.warning(
                        f"`{_z['raum']}` — {_z['von']}, bestätigt von "
                        f"{_z['durch']}, noch {_rest // 60} h {_rest % 60} min"
                        + (f"\n\n„{_z['grund']}\"" if _z.get("grund") else ""))
                    if st.button("Jetzt schließen",
                                 key=f"nzs_{_z['raum']}_{_z['von']}",
                                 use_container_width=True):
                        _ok, _m = notzugang.schliesse(
                            _z["raum"], _z["von"],
                            durch=st.session_state["username"])
                        (st.success if _ok else st.error)(_m)
                        _leeren()
                        time.sleep(1)
                        st.rerun()

            # --- bestaetigen ---
            if _kann_bestaetigen:
                st.markdown("---")
                st.markdown("**Anträge**")
                if not _antraege:
                    st.caption("Keine offenen Anträge.")
                for _a in _antraege:
                    st.info(f"**{_a['von']}** möchte in `{_a['raum']}`"
                            + (f"\n\n„{_a['grund']}\"" if _a.get("grund")
                               else ""))
                    _s1, _s2 = st.columns(2)
                    with _s1:
                        if st.button("Bestätigen",
                                     key=f"nzb_{_a['raum']}_{_a['von']}",
                                     use_container_width=True):
                            _ok, _m = notzugang.bestaetige(
                                _a["raum"], _a["von"],
                                st.session_state["username"])
                            (st.success if _ok else st.error)(_m)
                            _leeren()
                            time.sleep(1)
                            st.rerun()
                    with _s2:
                        if st.button("Ablehnen",
                                     key=f"nza_{_a['raum']}_{_a['von']}",
                                     use_container_width=True):
                            _ok, _m = notzugang.lehne_ab(
                                _a["raum"], _a["von"],
                                st.session_state["username"])
                            (st.info if _ok else st.error)(_m)
                            _leeren()
                            time.sleep(1)
                            st.rerun()

            # --- beantragen ---
            if is_admin():
                st.markdown("---")
                st.markdown("**Zugang beantragen**")
                if not notzugang.moeglich():
                    st.error(
                        "Niemand trägt die Rolle *notzugang*. Ohne eine "
                        "zweite Person lässt sich kein Notzugang "
                        "bestätigen — das ist der Sinn der Sache. Vergib "
                        "die Rolle unter *Benutzer verwalten*, und zwar "
                        "an jemanden, der KEIN Verwalter ist.")
                else:
                    _fremde_privat = sorted(
                        k for k in raeume.liste() if raeume.ist_privat(k)
                        and k != raeume.privat_kennung(
                            st.session_state["username"]))
                    if not _fremde_privat:
                        st.caption("Es gibt keine fremden persönlichen "
                                   "Räume.")
                    else:
                        _ziel = st.selectbox("Raum", _fremde_privat,
                                             key="nz_ziel")
                        _grund = st.text_area(
                            "Grund", key="nz_grund",
                            help="Steht im Protokoll und ist das, was die "
                                 "zweite Person beurteilt.")
                        if st.button("Notzugang beantragen",
                                     use_container_width=True):
                            _ok, _m = notzugang.beantrage(
                                _ziel, st.session_state["username"], _grund)
                            (st.success if _ok else st.error)(_m)
                            if _ok:
                                _leeren()
                                time.sleep(1)
                                st.rerun()

            st.caption(
                "**Die ehrliche Grenze:** das ist eine Kontrolle in der "
                "Anwendung. Wer Serverzugang hat, liest die Sammlung eines "
                "persönlichen Raums, ohne diese Freigabe zu beachten — die "
                "Abschnitte liegen dort im Klartext, weil sie durchsuchbar "
                "sein müssen. Der Notzugang schützt gegen den Verwalter, "
                "der im Alltag klickt, nicht gegen den, der sich einloggt.")

    # --- RAEUME VERWALTEN ---
    #
    # Ein Raum ist eine Sammlung und eine Mitgliederliste. Die Sammlung
    # entsteht beim ersten Upload, nicht hier: ein Raum ohne Inhalt braucht
    # keine Sammlung, und eine leere anzulegen wuerde jede Suche mit einer
    # weiteren Abfrage belasten.
    if _vw:
        with st.expander("🚪 Räume verwalten"):
            _alle = raeume.liste()
            _bekannt = benutzer.namen()
            _mit_daten = {r: sml.count()
                          for r, sml in _alle_raum_sammlungen()}

            for _k, _e in sorted(_alle.items()):
                _m = _e.get("mitglieder") or []
                _wer = "alle" if "*" in _m else f"{len(_m)} Mitglieder"
                if _e.get("gruppe"):
                    _wer += f" + Gruppe {_e['gruppe']}"
                st.caption(f"**{_e.get('bezeichnung') or _k}** · "
                           f"{_wer} · "
                           f"{_mit_daten.get(_k, 0):,} Abschnitte "
                           f"· `{_k}`")

            st.markdown("---")
            _bearbeiten = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + sorted(_alle),
                format_func=lambda n: (
                    n if n == "(neu anlegen)"
                    else (_alle.get(n, {}).get("bezeichnung") or n)),
                key="raum_bearbeiten")

            if _bearbeiten == "(neu anlegen)":
                _name = st.text_input("Bezeichnung", key="raum_neu_name")
                _besch = st.text_input("Beschreibung (optional)",
                                       key="raum_neu_besch")
                _mitglieder = st.multiselect(
                    "Mitglieder", _bekannt, key="raum_neu_mit",
                    help="Nur diese Nutzer sehen die Dokumente des Raums.")
                if st.button("Raum anlegen", use_container_width=True,
                             disabled=not _name.strip()):
                    ok, meldung = raeume.anlegen(_name, _name, _besch,
                                                 _mitglieder)
                    if ok:
                        st.success(f"Raum '{_name}' angelegt.")
                        with st.spinner("Richte die Ablage ein ..."):
                            _b = owncloud.richte_raum_ein(meldung)
                        _oc_bericht(_b, "Der Raum")
                        refresh_document_index()
                        time.sleep(2 if _b.get("fehler") else 1)
                        st.rerun()
                    else:
                        st.error(meldung)
            else:
                _e = _alle.get(_bearbeiten, {})
                _m = _e.get("mitglieder") or []
                if "*" in _m:
                    st.caption("Dieser Raum ist für alle sichtbar. Eine "
                               "Mitgliederliste gilt hier nicht.")
                _name = st.text_input("Bezeichnung",
                                      value=_e.get("bezeichnung") or "",
                                      key=f"raum_b_{_bearbeiten}")
                _besch = st.text_input("Beschreibung",
                                       value=_e.get("beschreibung") or "",
                                       key=f"raum_d_{_bearbeiten}")
                # Ein persoenlicher Raum gehoert genau einem Nutzer.
                # Mitglieder hinzuzufuegen waere eine Hintertuer, und im
                # strengen Betrieb widerspricht sie dem Zweck.
                _ist_privat = raeume.ist_privat(_bearbeiten)
                if _ist_privat:
                    st.caption(
                        "Persönlicher Raum – nur sein Eigentümer sieht "
                        "ihn. Eine Mitgliederliste gibt es hier nicht."
                        + (" Löschbar als Ganzes unter *fremde "
                           "persönliche Räume*." if raeume.PRIVAT_STRENG
                           else ""))
                    _neu_m = [x for x in _m if x != "*"]
                else:
                    _neu_m = st.multiselect(
                        "Mitglieder",
                        sorted(set(_bekannt) | {x for x in _m if x != "*"}),
                        default=[x for x in _m if x != "*"],
                        key=f"raum_m_{_bearbeiten}",
                        disabled=("*" in _m))
                    # "Fuer alle sichtbar" ist eine Vorgabe, keine
                    # Notwendigkeit. Wo der Grundsatz "nur was man wissen
                    # muss" gilt, bekommt auch der allgemeine Raum eine
                    # Liste.
                    if "*" in _m:
                        if st.button("Auf eine Mitgliederliste umstellen",
                                     use_container_width=True,
                                     key=f"raum_zu_{_bearbeiten}",
                                     help="Danach sehen nur noch die "
                                          "eingetragenen Nutzer diesen "
                                          "Raum."):
                            raeume.mitglieder_setzen(
                                _bearbeiten,
                                [st.session_state["username"]])
                            st.success("Umgestellt. Jetzt Mitglieder "
                                       "eintragen.")
                            time.sleep(1)
                            st.rerun()
                    elif st.button("Wieder für alle öffnen",
                                   use_container_width=True,
                                   key=f"raum_auf_{_bearbeiten}"):
                        raeume.fuer_alle_oeffnen(_bearbeiten)
                        st.success("Für alle sichtbar.")
                        time.sleep(1)
                        st.rerun()
                # --- MITGLIEDSCHAFT AUS OWNCLOUD ---
                #
                # Vereinigung, nicht Ersetzung: ein Verwalter, den die
                # Firma nicht in der Abteilungsgruppe fuehrt, soll sich
                # nicht selbst aussperren, indem er eine Gruppe eintraegt.
                _gruppe_alt = str(_e.get("gruppe") or "")
                _gruppe = st.text_input(
                    "ownCloud-Gruppe (optional)", value=_gruppe_alt,
                    key=f"raum_g_{_bearbeiten}",
                    help="Ihre Mitglieder kommen zu den oben "
                         "eingetragenen hinzu. Leer lassen, um die "
                         "Mitgliedschaft nur hier zu pflegen.")
                if _gruppe.strip():
                    _von_hand, _aus_gruppe = raeume.mitglieder_gesamt(
                        _bearbeiten)
                    _gueltig, _alter, _grund = raeume.stand_gueltig()
                    if not _gueltig:
                        st.warning(
                            f"Der Gruppenstand gilt nicht ({_grund}) -- "
                            f"die Mitglieder dieser Gruppe kommen gerade "
                            f"NICHT herein. Der Abgleich laeuft unter "
                            f"*Nachtragen und neu einlesen*.")
                    else:
                        st.caption(
                            "Aus der Gruppe: "
                            + (", ".join(_aus_gruppe) if _aus_gruppe
                               else "niemand")
                            + (f" -- Stand {_alter:.0f} min alt"
                               if _alter is not None else ""))
                        _unbekannt = [x for x in _aus_gruppe
                                      if x not in _bekannt]
                        if _unbekannt:
                            # Der Fall, in dem alles richtig aussieht und
                            # trotzdem niemand hereinkommt.
                            st.warning(
                                f"Nicht als Benutzer angelegt und damit "
                                f"wirkungslos: {', '.join(_unbekannt)}")

                # --- LISTENORDNER ---
                #
                # Hier und nicht in den allgemeinen Einstellungen: wer
                # einen Raum einrichtet, weiss in diesem Moment, wo
                # dessen Listen liegen. Muss er es sich fuer spaeter
                # merken, bleibt das Feld leer -- und die Listensuche
                # fuer diesen Raum entsteht nie.
                _lq_alt = listenquellen.pfad_von(_bearbeiten)
                _lq = st.text_input(
                    "Listenordner (xlsx, csv)", value=_lq_alt,
                    key=f"raum_lq_{_bearbeiten}",
                    help="Vollstaendiger Pfad, wie er im Container gilt "
                         "-- etwa /mnt/abteilungen/einkauf/listen. Die "
                         "Dateien bleiben, wo sie sind; niemand muss sie "
                         "ein zweites Mal ablegen. Leer = keine Listen "
                         "fuer diesen Raum.")
                if listenquellen.WURZELN:
                    st.caption("Erlaubt unterhalb von: "
                               + ", ".join(f"`{w}`"
                                           for w in listenquellen.WURZELN))

                # --- DATENBANKZUGANG ---
                #
                # Ein Konto je Raum, mit den Rechten dieses Raums. Damit
                # kommt auch das Schema mit diesen Rechten, und das
                # Sprachmodell sieht nur Tabellen, die es lesen darf.
                _sqz = sqlquellen.zugang(_bearbeiten) or {}
                with st.expander("Datenbankzugang dieses Raums",
                                 expanded=False):
                    st.caption(
                        "Ein Konto mit genau den Rechten, die dieser "
                        "Raum haben soll -- idealerweise nur lesend. "
                        "Leer = der Raum benutzt den Zugang aus der "
                        "Umgebung.")
                    _sq_b = st.text_input("Benutzer",
                                          value=_sqz.get("benutzer", ""),
                                          key=f"sqb_{_bearbeiten}")
                    _sq_p = st.text_input(
                        "Passwort", value=_sqz.get("passwort", ""),
                        type="password", key=f"sqp_{_bearbeiten}")
                    _sq_d = st.text_input(
                        "Datenbank (leer = Vorgabe)",
                        value=_sqz.get("datenbank", ""),
                        key=f"sqd_{_bearbeiten}")
                    st.caption(
                        "Das Passwort wird mit dem Schluessel dieses "
                        "Raums verschluesselt abgelegt. Ohne "
                        "Installationsschluessel wird es gar nicht "
                        "gespeichert.")

                if st.button("Speichern", use_container_width=True,
                             key=f"raum_s_{_bearbeiten}"):
                    if (_sq_b != _sqz.get("benutzer", "")
                            or _sq_p != _sqz.get("passwort", "")
                            or _sq_d != _sqz.get("datenbank", "")):
                        _ok_sq, _m_sq = sqlquellen.setze(
                            _bearbeiten,
                            {"benutzer": _sq_b, "passwort": _sq_p,
                             "datenbank": _sq_d},
                            benutzer=st.session_state.get("username", "?"),
                            ist_verwalter=True)
                        (st.success if _ok_sq else st.error)(_m_sq)
                    if _lq.strip() != _lq_alt:
                        _ok_lq, _m_lq = listenquellen.setze_raum(
                            _bearbeiten, _lq,
                            benutzer=st.session_state.get("username", "?"),
                            ist_verwalter=True)
                        if not _ok_lq:
                            st.error(_m_lq)
                        else:
                            with st.spinner("Lese die Listen ein ..."):
                                _k, _f = tabellen.baue_katalog()
                            st.caption(f"{len(_k['eintraege'])} Blaetter "
                                       f"im Katalog.")
                    raeume.beschriften(_bearbeiten, _name, _besch)
                    if "*" not in _m and not _ist_privat:
                        raeume.mitglieder_setzen(_bearbeiten, _neu_m)
                    if _gruppe.strip() != _gruppe_alt:
                        raeume.gruppe_setzen(_bearbeiten, _gruppe)
                    st.success("Gespeichert.")
                    # Die Freigabe zieht mit -- SETZEN, nicht ergaenzen.
                    # Ein Mitglied zu entfernen und die Freigabe stehen zu
                    # lassen waere die haeufigste Art, eine
                    # Rechteaenderung wirkungslos zu machen: die Suche
                    # fragt den Raum nicht mehr, die Dateien liegen aber
                    # weiter im ownCloud des Ausgeschiedenen.
                    with st.spinner("Ziehe die Freigaben nach ..."):
                        _b = owncloud.richte_raum_ein(_bearbeiten)
                    _oc_bericht(_b, "Der Raum")
                    refresh_document_index()
                    time.sleep(2 if _b.get("fehler") else 1)
                    st.rerun()

                # Entfernen und Loeschen sind zwei Dinge. Das erste nimmt
                # den Raum aus der Verwaltung und laesst die Daten liegen,
                # das zweite loescht sie. Ein Knopf fuer beides waere ein
                # Knopf, den man einmal zu oft drueckt.
                if _bearbeiten != raeume.ALLGEMEIN:
                    st.markdown("---")
                    _sp1, _sp2 = st.columns(2)
                    with _sp1:
                        if st.button("Raum entfernen",
                                     use_container_width=True,
                                     key=f"raum_e_{_bearbeiten}",
                                     help="Nimmt den Raum aus der "
                                          "Verwaltung. Die Dokumente "
                                          "bleiben erhalten."):
                            ok, meldung = raeume.entfernen(_bearbeiten)
                            (st.success if ok else st.error)(meldung)
                            refresh_document_index()
                            time.sleep(1)
                            st.rerun()
                    with _sp2:
                        _zahl = _mit_daten.get(_bearbeiten, 0)
                        # Derselbe Mechanismus wie im strengen
                        # Betrieb. Hier haengt der Haken zwar am Raum
                        # und bleibt beim Wechsel nicht stehen -- aber
                        # zwei verschiedene Freigaben fuer denselben
                        # Vorgang sind eine zu viel: die schwaechere
                        # wird zur Gewohnheit, und die Gewohnheit
                        # traegt man zur staerkeren hinueber.
                        _sicher = _loeschfreigabe(
                            _bearbeiten, _zahl, f"raum_x_{_bearbeiten}")
                        if st.button("Daten löschen",
                                     use_container_width=True,
                                     disabled=not _sicher,
                                     key=f"raum_l_{_bearbeiten}"):
                            ok, meldung = store.loesche(
                                raeume.sammlung(_bearbeiten))
                            keyword_index.delete_document_by_raum(_bearbeiten)
                            (st.success if ok else st.error)(meldung)
                            refresh_document_index()
                            time.sleep(1)
                            st.rerun()

            # --- ALTBESTAND ---
            #
            # Eine Installation von vor den Raeumen hat ihre Abschnitte noch
            # in der gemeinsamen Sammlung. Der Hinweis steht hier, damit man
            # es sieht, ohne ins Protokoll zu schauen.
            try:
                _alt_zahl = store.collection(anlegen=False).count()
            except Exception:
                _alt_zahl = 0
            if _alt_zahl:
                st.markdown("---")
                st.warning(
                    f"In der alten, gemeinsamen Sammlung liegen noch "
                    f"{_alt_zahl:,} Abschnitte. Sie werden nicht mehr "
                    f"durchsucht. `python umsortieren.py --pruefen` zeigt, "
                    f"wohin sie gehören, `python umsortieren.py` verschiebt "
                    f"sie — ohne neu zu vektorisieren.")

    # --- OWNCLOUD ---
    #
    # Ein Ordner in ownCloud wird auf einen Raum abgebildet. Damit liegen
    # die Dokumente dort, wo sie gepflegt werden, und die Rechte auf dem
    # Ordner sind die von ownCloud -- die Mitgliedschaft des Raums
    # entscheidet dann, wer die daraus gebauten Abschnitte sieht.
    if _vw:
        st.caption("**Betrieb**")
    if _vw:
        with st.expander("☁️ ownCloud"):
            _ok, _meldung = _owncloud_stand()
            (st.success if _ok else st.warning)(_meldung)

            if not owncloud.eingerichtet():
                st.caption(
                    "Einzurichten in der `.env`: `OWNCLOUD_URL` (die Wurzel, "
                    "etwa `https://cloud.firma.de`), `OWNCLOUD_USER` und "
                    "`OWNCLOUD_PASSWORT`. Bei aktiver Zwei-Faktor-Anmeldung "
                    "braucht es ein **App-Passwort**, nicht das "
                    "Anmeldepasswort. Für das reine Holen von Dateien "
                    "genügt Lesezugriff. Damit LocaNoto die Ablage selbst "
                    "einrichtet — Konten anlegen, Ordner erzeugen, "
                    "freigeben —, braucht `OWNCLOUD_ADMIN_USER` in "
                    "ownCloud **Verwalterrechte**. Das ist viel Macht in "
                    "einem Dienstkonto; wer sie nicht geben will, richtet "
                    "Konten und Ordner dort von Hand ein und trägt hier "
                    "nur die Zuordnung ein.")
            else:
                _zu = owncloud.zuordnung()
                _wirksam = owncloud.zuordnung_wirksam()
                for _r, _o in sorted(_wirksam.items()):
                    _b = owncloud.letzter_bericht(_r)
                    _stand = (f"{_b['dateien']} Dateien, zuletzt "
                              f"{(_b['zuletzt'] or '?')[:16]}"
                              if _b else "noch nicht abgeglichen")
                    st.caption(f"**{raeume.bezeichnung(_r)}** "
                               f"· `{_o}`"
                               + ("" if _r in _zu else " *(Standard)*")
                               + f" · {_stand}")
                st.caption(
                    "Ohne eigenen Eintrag gilt der Standardbaum unter "
                    f"`/{owncloud.WURZEL}/`. Eine Zuordnung von Hand "
                    "geht vor — für Bestände, die seit Jahren woanders "
                    "liegen.")

                st.markdown("---")
                _raum_wahl = st.selectbox(
                    "Raum", sorted(raeume.liste()),
                    format_func=raeume.bezeichnung, key="oc_raum")
                _ordner = st.text_input(
                    "Ordner in ownCloud", value=_zu.get(_raum_wahl, ""),
                    placeholder="/Abteilungen/Einkauf/Handbücher",
                    key=f"oc_ordner_{_raum_wahl}",
                    help="Pfad relativ zum Wurzelverzeichnis des "
                         "angemeldeten Kontos. Unterordner werden zu "
                         "Sachgebieten.")
                _sp1, _sp2 = st.columns(2)
                with _sp1:
                    if st.button("Zuordnung speichern",
                                 use_container_width=True,
                                 disabled=not _ordner.strip()):
                        _zu[_raum_wahl] = _ordner.strip()
                        owncloud.setze_zuordnung(_zu)
                        st.success("Gespeichert.")
                        time.sleep(1)
                        st.rerun()
                with _sp2:
                    if st.button("Zuordnung entfernen",
                                 use_container_width=True,
                                 disabled=_raum_wahl not in _zu,
                                 help="Der Raum wird nicht mehr "
                                      "abgeglichen. Bereits geholte "
                                      "Dateien und ihre Abschnitte "
                                      "bleiben."):
                        _zu.pop(_raum_wahl, None)
                        owncloud.setze_zuordnung(_zu)
                        st.success("Entfernt.")
                        time.sleep(1)
                        st.rerun()

            # --- ABLAGE EINRICHTEN ---
            #
            # Nachholen, was beim Anlegen nicht ging -- weil ownCloud
            # gerade nicht erreichbar war, oder weil die Installation
            # aelter ist als diese Anbindung. Der Ablauf ist wiederholbar:
            # vorhandene Ordner bleiben, Freigaben werden auf den Soll-
            # Stand gebracht, nicht ergaenzt.
            if owncloud.eingerichtet():
                st.markdown("---")
                st.markdown("**Ablage einrichten**")
                st.caption(
                    f"Legt unter `/{owncloud.WURZEL}/` je Raum einen Ordner "
                    f"an und teilt ihn mit seinen Mitgliedern — den "
                    f"gemeinsamen mit allen (nur lesend, schreiben dürfen "
                    f"Verwalter), einen persönlichen nur mit seinem "
                    f"Besitzer. Wiederholbar: was schon steht, bleibt.")
                if st.button("Für alle Räume einrichten",
                             use_container_width=True):
                    _gut, _schlecht = 0, []
                    with st.spinner("Richte ein ..."):
                        for _r in sorted(raeume.liste()):
                            _b = owncloud.richte_raum_ein(_r)
                            if _b.get("fehler"):
                                _schlecht.append(
                                    f"{_r}: {_b['fehler'][0]}")
                            else:
                                _gut += 1
                    st.success(f"{_gut} Räume eingerichtet.")
                    for _f in _schlecht[:10]:
                        st.warning(_f)
                    _leeren()

                _wer = st.selectbox(
                    "Einzelnen Zugang nachziehen",
                    ["-"] + benutzer.namen(), key="oc_nutzer")
                if _wer != "-" and st.button(
                        "Persönliche Ablage einrichten",
                        use_container_width=True):
                    with st.spinner("Richte ein ..."):
                        # Ohne Passwort: das Konto gibt es entweder schon,
                        # oder es wird beim Anlegen erzeugt. Hier ein
                        # Passwort zu erfinden waere ein zweites Geheimnis
                        # fuer denselben Menschen.
                        _b = owncloud.richte_nutzer_ein(_wer)
                    _oc_bericht(_b, "Der Zugang")
                    if not _b.get("fehler"):
                        st.success(f"Ablage für '{_wer}' steht.")

                # --- PRUEFEN ---
                #
                # Vor dem ersten Abgleich, und zwar nicht aus Vorsicht,
                # sondern weil eine falsch eingerichtete Zuordnung genau
                # wie "alles geloescht" aussieht: der Ordner ist leer,
                # also gilt jede bekannte Datei als entfallen. Danach sind
                # die Abschnitte weg.
                if _raum_wahl in _zu:
                    st.markdown("---")
                    if st.button("Änderungen prüfen",
                                 use_container_width=True,
                                 key=f"oc_pruef_{_raum_wahl}"):
                        try:
                            with st.spinner("Frage ownCloud ab ..."):
                                _neu, _geae, _entf, _unv = owncloud.plane(
                                    _raum_wahl)
                            st.caption(f"unverändert: {len(_unv)}")
                            for _titel, _liste in (("neu", _neu),
                                                   ("geändert", _geae),
                                                   ("entfallen", _entf)):
                                if _liste:
                                    st.caption(f"**{_titel}: "
                                               f"{len(_liste)}**")
                                    st.code(chr(10).join(_liste[:30]),
                                            language="text")
                            if not (_neu or _geae or _entf):
                                st.info("Nichts zu tun.")
                        except Exception as e:
                            st.error(f"Abfrage fehlgeschlagen: {e}")

                # --- MITGLIEDSCHAFTEN ---
                st.markdown("---")
                _gz = owncloud.gruppen_zuordnung()
                _gueltig, _alter, _grund = raeume.stand_gueltig()
                if _gz:
                    for _r, _g in sorted(_gz.items()):
                        _vh, _ag = raeume.mitglieder_gesamt(_r)
                        st.caption(f"**{raeume.bezeichnung(_r)}** "
                                   f"· Gruppe `{_g}` · "
                                   f"{len(_ag)} aus der Gruppe, "
                                   f"{len(_vh)} von Hand")
                    if _gueltig:
                        st.caption("Gruppenstand: "
                                   + (f"{_alter:.0f} Minuten alt"
                                      if _alter is not None
                                      else "unbekannt"))
                    else:
                        st.warning(f"Gruppenstand gilt nicht: {_grund}. "
                                   f"Bis zum nächsten Abgleich wirken "
                                   f"nur die von Hand eingetragenen "
                                   f"Mitglieder.")
                    if st.button("Mitgliedschaften jetzt nachziehen",
                                 use_container_width=True):
                        with st.spinner("Frage ownCloud ab ..."):
                            _b = owncloud.gruppen_abgleich()
                        (st.success if _b["geschrieben"]
                         else st.warning)(_b["meldung"])
                        for _f in _b["fehler"]:
                            st.error(f"Gruppe '{_f['gruppe']}': "
                                     f"{_f['grund']}")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.caption(
                        "Noch keine Raumgruppe eingetragen. Sie gehört "
                        "in den Raum selbst — unter *Räume "
                        "verwalten*, Feld ownCloud-Gruppe. Die "
                        "Gruppenabfrage braucht in ownCloud ein Konto mit "
                        "Verwalterrechten (`OWNCLOUD_ADMIN_USER`); "
                        "für die Dateien genügt Lesen.")

                st.caption(
                    "Der eigentliche Abgleich läuft abgekoppelt — unter "
                    "*Nachtragen und neu einlesen*, Eintrag „Aus ownCloud "
                    "abgleichen“. Er holt neue und geänderte Dateien, "
                    "entfernt die Abschnitte entfallener und liest "
                    "anschließend ein. Für den Dauerbetrieb gehört das in "
                    "einen Zeitplan auf dem Server: "
                    "`docker compose exec -T locanoto_bot python "
                    "abgleich.py`")

    # --- SICHERUNG DER VEKTORDATENBANK ---
    #
    # Der einzige Zustand, der nicht ableitbar ist und trotzdem nicht auf
    # den Netzspeicher gehoert: SQLite plus binaere Indexdateien. Deshalb
    # der laufende Bestand auf lokalem oder Blockspeicher und ein Abzug
    # davon auf dem persistenten Speicher.
    #
    # Gelesen wird ueber die Schnittstelle, nicht als Dateikopie: eine
    # Kopie mitten in einem Schreibvorgang ist ein Abzug, der sich nicht
    # zurueckholen laesst -- und das zeigt sich erst beim Zurueckholen.
    if _vw:
        with st.expander("🗃️ Sicherung der Vektordatenbank"):
            _abzuege = _verwaltungsstand()["abzuege"]
            st.caption(f"Ablage: `{sicherung.ORDNER}`"
                       + (f" · es werden "
                          f"{sicherung.BEHALTEN} Abzüge behalten"
                          if sicherung.BEHALTEN else
                          " · alle Abzüge werden behalten"))

            if not _abzuege:
                st.warning(
                    "Noch kein Abzug. Ohne einen wäre der Verlust der "
                    "Vektordatenbank ein vollständiges Neueinlesen — "
                    "Stunden Modellzeit für ein Ergebnis, das schon "
                    "vorlag.")
            else:
                st.code(chr(10).join(
                    f"{_n:<22} {_gr / 1e6:9.1f} MB  "
                    f"{_st.get('abschnitte', '?'):>8} Abschnitte  "
                    f"{len(_st.get('raeume') or {})} Räume"
                    + ("   UNVOLLSTÄNDIG" if _unvollstaendig(_st) else "")
                    for _n, _p, _gr, _st in _abzuege), language="text")
                if any(_unvollstaendig(_st) for _n, _p, _gr, _st in _abzuege):
                    st.warning(
                        "Bei einem Abzug ließen sich nicht alle Räume "
                        "lesen. Er ist von außen nicht von einem "
                        "vollständigen zu unterscheiden — deshalb steht es "
                        "hier. Ein neuer Abzug behebt es; der letzte "
                        "vollständige wird nicht weggeräumt.")

            _laeuft = hintergrund.laeuft("sicherung")
            if _laeuft:
                st.caption("Ein Abzug läuft gerade.")
                st.code(hintergrund.protokoll("sicherung", 6) or "...",
                        language="text")
            elif st.button("Jetzt sichern", use_container_width=True,
                           help="Läuft abgekoppelt weiter, auch wenn die "
                                "Oberfläche neu lädt."):
                _ok, _meldung = hintergrund.starte("sicherung")
                (st.success if _ok else st.error)(_meldung)
                time.sleep(1)
                st.rerun()

            # --- ZURUECKHOLEN ---
            #
            # Bewusst mit Haken und in einem eigenen Schritt: ein Abzug
            # ueberschreibt vorhandene Abschnitte. Wer ihn einspielt, weil
            # er die Liste sehen wollte, verliert Arbeit.
            if _abzuege:
                st.markdown("---")
                _wahl = st.selectbox(
                    "Abzug einspielen", [_n for _n, _p, _g, _s in _abzuege],
                    key="sich_wahl")
                _st = dict(_abzuege[[_n for _n, _p, _g, _s
                                     in _abzuege].index(_wahl)][3])
                st.caption(
                    f"{_st.get('abschnitte', '?')} Abschnitte in "
                    + ", ".join(sorted((_st.get('raeume') or {}))))
                if _unvollstaendig(_st):
                    _fehlten = ", ".join(
                        _f.get("raum", "?") for _f in (_st.get("fehler") or [])
                    ) or "unbekannt"
                    st.error(
                        f"Dieser Abzug ist unvollständig — beim Sichern "
                        f"ließen sich diese Räume nicht lesen: {_fehlten}. "
                        f"Eingespielt wird nur, was er hat. Gibt es einen "
                        f"neueren vollständigen, nimm den.")
                _sicher = st.checkbox(
                    "Vorhandene Abschnitte dürfen überschrieben werden",
                    key="sich_ok")
                if st.button("Einspielen", use_container_width=True,
                             disabled=not _sicher):
                    with st.spinner("Spiele ein — das dauert länger als "
                                    "das Sichern, weil der Suchindex neu "
                                    "gebaut wird ..."):
                        _b = sicherung.hole_zurueck(_wahl)
                    for _r, _n2 in sorted(_b["raeume"].items()):
                        st.caption(f"{_r}: {_n2} Abschnitte")
                    for _f in _b["fehler"]:
                        st.error(str(_f))
                    if not _b["fehler"]:
                        st.success("Eingespielt. Der Stichwortindex baut "
                                   "sich beim nächsten Start neu auf.")
                    refresh_document_index()

            st.caption(
                "Der Abzug enthält Abschnitte, Metadaten **und die "
                "Vektoren** — ein Einspielen braucht kein Modell und "
                "keinen Endpunkt. Gemessen: 20.500 Abschnitte in 2,6 s "
                "(112 MB), Einspielen 29 s. Hochgerechnet auf 324.000 "
                "Abschnitte: rund 40 s und 1,8 GB, Einspielen etwa acht "
                "Minuten. Der Schlüssel geht **nicht** mit in den Abzug — "
                "er gehört in eine andere Aufbewahrung als die Daten, die "
                "er lesbar macht.")

    # --- SICHERHEITSLAGE ---
    #
    # Verschluesselung, die man nicht nachsehen kann, ist eine
    # Behauptung. Hier steht, was tatsaechlich gilt -- einschliesslich
    # dessen, was sie NICHT leistet. Ein offener Punkt heisst nicht
    # "kaputt", sondern "hier ist die Zusage schwaecher, als sie
    # aussieht".
    if _vw:
        st.caption("**Lage**")
    if _vw:
        _lage = sicherheit.lage()
        _offen = [n for n, _ok, _t in _lage if not _ok]
        with st.expander(f"\U0001f512 Sicherheitslage "
                         f"({len(_lage) - len(_offen)}/{len(_lage)})"):
            for _name, _ok, _text in _lage:
                st.markdown(("✅ " if _ok else "⚠️ ") + f"**{_name}**")
                st.caption(_text)
            st.caption(
                "Die letzten drei Punkte lassen sich nicht schließen, "
                "sondern nur eingrenzen: Vektoren müssen vergleichbar "
                "bleiben, und wer den laufenden Prozess hat, hat den "
                "Klartext. Dagegen hilft ein verschlüsselter Datenträger "
                "und wenige Menschen mit Serverzugang.")

    # --- SPEICHERORTE ---
    #
    # Wo welcher Zustand liegt, auf einem Bildschirm. Bei einer Frage nach
    # der Datenhaltung ist "schau in die docker-compose.yaml und in fuenf
    # Module" keine Antwort.
    if _vw:
        with st.expander("💾 Speicherorte"):
            for _name, _pfad, _gesetzt in paths.wurzeln():
                st.caption(f"**{_name}** · `{_pfad}` · "
                           + ("von außen gesetzt" if _gesetzt
                              else "Standard neben dem Code"))

            st.markdown("---")
            _klassen = {
                "quelle": "Quellen — werden gepflegt, nur gelesen",
                "nutzerdaten": "Nutzerdaten — müssen den Container "
                               "überleben",
                "konfiguration": "Konfiguration — getrennt aufzubewahren",
                "index": "Ableitbar — gehört auf die lokale Platte",
            }
            _bestand = _verwaltungsstand()["bestand"]
            for _klasse, _beschriftung in _klassen.items():
                st.caption(f"**{_beschriftung}**")
                _zeilen = [z for z in _bestand if z[1] == _klasse]
                st.code(chr(10).join(
                    f"{_b:<26} {_gr / 1e6:9.2f} MB {_n:>6} Dateien  {_p}"
                    for _b, _k, _p, _gr, _n in _zeilen), language="text")

            _modus = _verwaltungsstand()["journal"]
            if _modus.lower() != "wal":
                # Der stille Rueckfall. PRAGMA journal_mode=WAL schlaegt
                # nicht fehl, wenn das Dateisystem es nicht kann -- SQLite
                # bleibt beim alten Modus und sagt nichts. Genau das
                # passiert auf einem Netzlaufwerk.
                st.error(
                    f"Der Stichwortindex läuft im Journalmodus `{_modus}` "
                    f"statt `wal`. Das heißt fast immer: er liegt auf "
                    f"einem Netzlaufwerk, wo SQLite den WAL-Betrieb nicht "
                    f"aufsetzen kann. Setze `LOCANOTO_INDEX` auf ein "
                    f"containerlokales Verzeichnis — der Index baut sich "
                    f"dort in Sekunden neu auf.")
            else:
                st.caption(f"Stichwortindex: Journalmodus `{_modus}`.")

            st.caption(
                "Ableitbares gehört nicht auf den Netzspeicher: "
                "Vektordatenbank und Stichwortindex sind SQLite-Dateien, "
                "und der WAL-Betrieb braucht gemeinsamen Speicher im "
                "selben Dateisystem — über NFS oder SMB gibt es den nicht, "
                "und die Dateisperren sind unzuverlässig. Der Verlust "
                "kostet nichts: der Stichwortindex baut sich mit rund "
                "18.600 Abschnitten je Sekunde neu auf.")

    if _vw:
        st.caption("**Inhalte**")
    if _vw:
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
    if _vw:
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
    if _vw:
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
    if _vw:
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
#
# Gezaehlt wird ueber die Raeume dieses Nutzers: wer in keinem Raum etwas
# hat, dem hilft die Meldung "noch keine Dokumente" -- und nicht die
# Auskunft, dass anderswo etwas liegt.
_bestand = _zahl_abschnitte(st.session_state["username"],
                            tuple(meine_raeume))
if _bestand > 0:
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            # Angehaengte Bilder vor dem Text, so wie der Nutzer sie
            # geschickt hat. Fehlt die Datei -- etwa weil der Chat-Ordner
            # aufgeraeumt wurde -- wird sie stillschweigend uebergangen.
            for bild in msg.get("bilder", []):
                # Nicht st.image(pfad): die Datei ist verschluesselt, und
                # Streamlit wuerde nur Bytes sehen, die kein Bild sind.
                rohbild = vision.lade(bild)
                if rohbild:
                    st.image(rohbild, width=360)
            if msg["role"] == "assistant":
                st.write(_quellen_klickbar(msg["content"],
                                           msg.get("sources"), i))
            else:
                st.write(msg["content"])
            if msg.get("unvollstaendig"):
                # Ein Zwischenstand, dessen Strom abgebrochen ist. Ohne
                # diesen Hinweis saehe ein mitten im Satz endender Text
                # wie eine fertige Antwort aus -- und das waere
                # schlimmer als der Verlust, weil es niemand bemerkt.
                st.caption("\u26a0\ufe0f Abgebrochen -- die Antwort ist "
                           "unvollstaendig. Frage noch einmal stellen.")
            
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
                
                # Kein Abfrageparameter mehr (siehe _quellen_klickbar).
                # Der erste Aufklapper steht offen: nach dem Sprung
                # sieht man damit sofort Text und nicht nur eine
                # geschlossene Leiste.
                _gewuenscht = ""
                for _k, source in enumerate(msg["sources"]):
                    file_n = source["file"]
                    page_n = source["page"]
                    
                    # Ein leerer Anker davor: darauf springt der
                    # Browser, wenn der Verweis im Text angeklickt
                    # wurde. Streamlit vergibt keine eigenen
                    # Sprungmarken fuer Aufklapper.
                    _ziel = f"{i}-{_k}"
                    st.markdown(f'<div id="q{_ziel}"></div>',
                                unsafe_allow_html=True)
                    with st.expander(f"📄 {file_n} (Seite {page_n})",
                                     expanded=(_gewuenscht == _ziel
                                               or _k == 0)):
                        for t in source["texts"]:
                            st.info(t)
                        
                        # Nicht join(DOCS_DIR, name): mit Sachgebieten und
                        # erst recht mit aus ownCloud geholten Ordnern liegt
                        # kaum ein Dokument noch direkt dort. Und nicht
                        # allein nach dem Namen: der Raum entscheidet,
                        # welche 'Angebot.pdf' gemeint ist.
                        pdf_path = dokument_pfad(
                            file_n, source.get("raum") or raeume.ALLGEMEIN)
                        # Nur bei PDFs: bei Word oder Markdown ist "Seite"
                        # eine Abschnittsnummer, und pymupdf kann die Datei
                        # ohnehin nicht oeffnen.
                        if (file_n.lower().endswith(".pdf")
                                and os.path.exists(pdf_path)
                                and isinstance(page_n, int)):
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
                    kennung = st.session_state.current_chat_id
                    name = (f"{kennung.rsplit('.', 1)[0]}"
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
        
        # --- BENENNUNG BEIM ERSTEN PROMPT ---
        #
        # Frueher wurde dafuer die Datei umbenannt: neue Datei schreiben,
        # alte loeschen, und der Titel stand im Namen. Jetzt aendert sich
        # nur ein Eintrag im verschluesselten Verzeichnis -- die Datei
        # heisst weiter nach ihrer zufaelligen Kennung.
        _titel = None
        if len(st.session_state.messages) == 1:
            _titel = (f"{make_chat_title(user_query, chat_model)} "
                      f"{datetime.now().strftime('%y-%m-%d')}")

        save_chat(st.session_state.current_chat_id,
                  st.session_state.messages, _titel)
        
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
                            meine_sammlungen(nur=selected_raeume or None),
                            embed_client, embed_model,
                            search_queries, st.session_state["username"], top_k,
                            dateien=selected_docs or None,
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

                # --- DATENBANK ABFRAGEN ---
                #
                # Das Modell formuliert die Abfrage selbst; geprueft
                # wird sie in sqlpruefung.py. Ausgefuehrt wird sie mit
                # dem gewaehlten Konto -- die Schranke liegt damit in
                # der Datenbank und nicht allein in der Pruefung.
                #
                # Scheitert hier etwas, wird es vermerkt und die
                # Antwort entsteht allein aus den Dokumenten. Eine
                # halbe Antwort ist besser als ein Abbruch.
                bloecke = []
                if sql_aktiv and sql_schema:
                    _sqz = (sqlquellen.zugang(sql_raum) if sql_raum
                            else None)
                    abfrage, sql_ergebnis, sql_grund = "", "", ""
                    with st.spinner("Frage die Datenbank ab..."):
                        try:
                            abfrage = sqldb.formuliere(
                                sql_client, llm.modell("SQL", chat_model),
                                user_query, sql_schema, verlauf)
                            if not abfrage:
                                sql_grund = ("Das Modell sieht die Frage "
                                             "nicht durch die Datenbank "
                                             "beantwortbar.")
                        except Exception as e:
                            sql_grund = f"Abfrage nicht erzeugt: {e}"
                        if abfrage:
                            try:
                                spalten, zeilen = sqldb.fuehre_aus(
                                    abfrage, zugang=_sqz)
                                sql_ergebnis = sqldb.als_tabelle(spalten,
                                                                 zeilen)
                            except ValueError as e:
                                # Die Pruefung hat abgelehnt -- die
                                # Abfrage hat die Datenbank nie erreicht.
                                sql_grund = str(e)
                            except Exception as e:
                                sql_grund = f"Datenbankfehler: {e}"
                    if sql_ergebnis:
                        bloecke += [("datenbank_abfrage", abfrage),
                                    ("datenbank_ergebnis", sql_ergebnis)]
                        with st.expander("\U0001f5c4\ufe0f Datenbankabfrage"):
                            st.code(abfrage, language="sql")
                            st.caption(
                                f"Konto: "
                                f"{(_sqz or {}).get('benutzer') or 'Vorgabe'}")
                    elif sql_grund:
                        st.caption("\U0001f5c4\ufe0f *" + sql_grund + "*")

                # --- LISTEN ABFRAGEN ---
                #
                # Erst entscheiden, WO die Antwort stehen koennte, dann dort
                # gezielt nachsehen -- dasselbe Vorgehen wie bei einer
                # Datenbank. Ausgefuehrt wird kein erzeugter Code, sondern
                # je Blatt eine gepruefte SELECT-Anweisung.
                if tabellen_aktiv and _eintraege:
                    auswahl = [e for e in _eintraege
                               if (tabellen_gross or not e.get("gross"))
                               and tabellen.im_bereich(e, tabellen_bereiche)]
                    if auswahl:
                        # Mehrere Blaetter statt eines. Eine Frage wie
                        # "welche Saegeblaetter gibt es" gilt bei einem
                        # gewachsenen Listenordner mehreren Blaettern
                        # zugleich -- ein Jahrgang je Blatt, ein Standort
                        # je Datei. Ein einziges zu waehlen beantwortet
                        # sie halb, und man sieht es der Antwort nicht an.
                        _erg, _grund = [], ""
                        with st.spinner("Suche in den Listen ..."):
                            try:
                                _erg = tabellen.abfragen(
                                    chat_client, chat_model, user_query,
                                    auswahl, verlauf)
                                if not _erg:
                                    _grund = ("Keine der Listen passt zu "
                                              "dieser Frage.")
                            except Exception as e:
                                _grund = f"Abfrage nicht erzeugt: {e}"

                        _mit = 0
                        for _t in _erg:
                            quelle = _t["datei"] + (f"#{_t['blatt']}"
                                                    if _t["blatt"] else "")
                            if _t["grund"]:
                                st.caption("\U0001f4ca *" + quelle + ": "
                                           + _t["grund"] + "*")
                                continue
                            if not _t["zeilen"]:
                                # Kein Treffer ist eine Auskunft, aber
                                # keine, die in den Kontext gehoert: eine
                                # leere Tabelle im Prompt liest sich fuer
                                # das Modell wie ein Beleg fuer "gibt es
                                # nicht".
                                st.caption("\U0001f4ca *" + quelle
                                           + ": keine passende Zeile.*")
                                continue
                            _mit += 1
                            _tab = sqlpruefung.als_tabelle(_t["spalten"],
                                                           _t["zeilen"])
                            bloecke += [
                                ("liste_abfrage",
                                 quelle + chr(10) + _t["sql"]),
                                ("liste_ergebnis", _tab)]
                            with st.expander(
                                    f"\U0001f4ca Liste: {quelle} "
                                    f"({len(_t['zeilen'])} Zeilen)"
                                    + ("" if _t.get("gewaehlt")
                                       else " — zusätzlich gefunden")):
                                st.code(_t["sql"], language="sql")
                                st.markdown(_tab)
                        if not _mit and _grund:
                            st.caption("\U0001f4ca *Listen nicht verwendet: "
                                       + _grund + "*")

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
                answer = _strom_zeichnen(
                    pipeline.antwort(
                        chat_client, chat_model,
                        pipeline.systemprompt(dynamic_context,
                                              aktives_preset),
                        st.session_state.messages),
                    st.session_state.current_chat_id,
                    list(st.session_state.messages))

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