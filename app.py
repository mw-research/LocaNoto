"""Die Oberflaeche -- Anmeldung, Seitenleiste, Chat und Quellen.

Streamlit fuehrt diese Datei bei JEDER Bedienung von oben neu aus.
Was ueber einen Lauf hinaus gelten soll, gehoert deshalb in
st.session_state und nicht in eine gewoehnliche Variable.

Der Verwaltungsbereich steht in verwaltung.py und wird von hier
mit zwoelf benannten Werten aufgerufen; die Suche selbst steht in
pipeline.py und ist von der Oberflaeche unabhaengig -- api.py
benutzt dieselbe.
"""
import streamlit as st
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import contextlib
import functools
import inspect
import os
import time
from datetime import datetime
import re

import paths
import sicherheit
import store
import auth
import aufnehmen
import mcp
from aufnehmen import (raum_sammlung, _alle_raum_sammlungen,
                       _gehoert_anderem_raum,
                       process_uploaded_pdf)
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
import budget
import verwaltung
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
                      "pdf_upload_nr", "listen_upload_nr",
                      # Die Postfach-Koepfe gehoeren zu DIESER Anmeldung
                      # und zu keiner anderen. Wer sich abmeldet, weil er
                      # den Rechner verlaesst, laesst sie nicht zurueck.
                      "_postfach_koepfe")


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


def list_foreign_private_documents(current_user, notzugang_=()):
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
        # MIT BESTAETIGTEM NOTZUGANG IST DER RAUM NICHT MEHR FREMD.
        #
        # Ohne diese Angabe blieb er in der Verwaltungsliste stehen --
        # mit Kennungen statt Namen --, waehrend seine Dokumente
        # daneben in der gewoehnlichen Dokumentenverwaltung mit
        # Klarnamen auftauchten. Zweimal dasselbe, einmal lesbar und
        # einmal nicht, und der Unterschied war nicht zu erklaeren.
        #
        # Der Notzugang ist das Verfahren, mit dem jemand hineindarf.
        # Ist er bestaetigt, gilt er auch hier.
        if raeume.darf_lesen(current_user, kennung, notzugang_):
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


def fremde_raeume(current_user, notzugang_=()):
    """[(raum, anzahl)] der Raeume, die dieser Nutzer nicht lesen darf.

    Ohne Dateinamen. Das ist die Ansicht, die im strengen Betrieb bleibt:
    ein Verwalter sieht, DASS ein Raum Inhalt hat, und kann ihn als Ganzes
    loeschen -- ohne zu erfahren, was darin liegt.
    """
    aus = []
    for kennung, sml in _alle_raum_sammlungen():
        # Auch hier: ein Raum mit bestaetigtem Notzugang
        # ist nicht fremd.
        if raeume.darf_lesen(current_user, kennung,
                             notzugang_):
            continue
        try:
            anzahl = sml.count()
        except Exception:
            continue
        if anzahl:
            aus.append((kennung, anzahl))
    return sorted(aus)


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


def _feldschluessel(bereich, name):
    """Schluessel eines Eingabefeldes in der laufenden Runde.

    Streamlit haelt den Inhalt eines Feldes unter seinem Schluessel in
    der Sitzung. Ein st.rerun() leert deshalb nichts: das Feld kommt mit
    demselben Schluessel zurueck und holt sich denselben Inhalt. Den
    Inhalt nachtraeglich zu setzen verweigert Streamlit, sobald das Feld
    in diesem Lauf schon gezeichnet wurde.

    Was bleibt, ist ein NEUER Schluessel. Denselben Weg geht das
    Hochladefeld schon -- siehe pdf_upload_nr.
    """
    return f"{bereich}_{name}_{st.session_state.get('_runde_' + bereich, 0)}"


def _felder_leeren(bereich, *namen):
    """Ein Anlegen-Formular leeren. NUR nach Erfolg aufrufen.

    Nach einem Fehlschlag muessen die Felder stehen bleiben: wer sich
    beim Passwort vertippt hat, soll die Kennung nicht neu eintippen.

    Die alten Eintraege werden entfernt und nicht liegengelassen --
    sonst sammelt sich in einer langen Sitzung ein Eintrag je
    angelegtem Benutzer an. Scheitert das Entfernen, ist das nicht
    schlimm: der neue Schluessel sorgt ohnehin fuer ein leeres Feld,
    das Aufraeumen ist die Zugabe.
    """
    runde = st.session_state.get("_runde_" + bereich, 0)
    for name in namen:
        try:
            del st.session_state[f"{bereich}_{name}_{runde}"]
        except Exception:
            pass
    st.session_state["_runde_" + bereich] = runde + 1


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
def _fremdes(name, ist_verwalter, notzugang_=()):
    """(dateien, raeume) fremder Raeume -- zwei volle Metadatenabzuege.

    notzugang_ gehoert in die Signatur und nicht nur in den Rumpf: der
    Zwischenspeicher schluesselt ueber die Argumente. Ohne die Angabe
    bekaeme jemand nach einer Bestaetigung bis zu dreissig Sekunden
    lang noch die alte Antwort -- und die Bestaetigung saehe aus, als
    haette sie nicht gewirkt.
    """
    return (list_foreign_private_documents(name, notzugang_),
            fremde_raeume(name, notzugang_))


@st.cache_data(ttl=30, show_spinner=False)
def _verwaltungsstand():
    """Verzeichnisse und Zaehler fuer die Verwaltungsbereiche."""
    return {
        "bestand": paths.bestand(),
        "abzuege": sicherung.liste(),
        "rueckmeldungen": feedback.zaehle(),
        "journal": keyword_index.journal_modus(),
    }


dateien_je_raum = load_document_index(
    st.session_state["username"], tuple(mein_notzugang()))
meine_raeume = sorted(dateien_je_raum)
all_available_files = sorted({d for liste in dateien_je_raum.values()
                              for d in liste})

# --- LAEUFT GERADE EINE ANTWORT? ---
#
# Muss hier stehen und nicht weiter unten: die Seitenleiste wird gleich
# gezeichnet, und was sie sperren soll, muss vorher feststehen.
# Der Auftrag wird HIER herausgenommen und nicht erst beim Chat.
#
# Dazwischen liegen rund tausend Zeilen, und alles davon kann
# abbrechen -- ein st.stop() wegen einer gerissenen Budgetschwelle, ein
# Fehler, ein Klick auf einen anderen Zweig. Blieb der Auftrag dabei
# liegen, sah der naechste Lauf "gesperrt UND Auftrag vorhanden", heilte
# sich also nicht, und die naechste Runde genauso: die Bedienung war
# tot, bis jemand die Sitzung beendete. Genau so gemeldet worden.
#
# Als gewoehnliche Variable ueberlebt er nur diesen einen Lauf. Was auch
# immer dazwischen abbricht -- der naechste findet keinen Auftrag und
# loest die Sperre.
_auftrag = st.session_state.pop("_auftrag", None)
_antwortet = bool(st.session_state.get("_laeuft"))
if _antwortet and not _auftrag:
    # Gesperrt, aber nichts zu tun: der antwortende Lauf ist nicht bis
    # zum Ende gekommen. Abgebrochen, gestoppt, abgestuerzt -- gleich
    # welcher Grund, die Sperre darf nicht haengenbleiben. Eine Leiste,
    # die sich nach einem Fehler nie wieder bedienen laesst, waere
    # schlimmer als der Fehler.
    st.session_state["_laeuft"] = False
    _antwortet = False

# --- DIE SPERRE GILT FUER DIE GANZE LEISTE ---
#
# Gemeldet als "man kann waehrend einer Antwort wieder Sachen
# auswaehlen". Gesperrt waren bis dahin drei Dinge: die Chateingabe, der
# Schalter "Verwaltung" und das Passwortfeld. Voreinstellung,
# Raumauswahl, Dokumentauswahl, Chatwechsel, Hochladen und der ganze
# Verwaltungsbereich waren bedienbar -- und ein Klick dort reisst die
# laufende Antwort ab, weil Streamlit den Lauf abbricht und neu beginnt.
#
# Vierzig Aufrufe einzeln nachzutragen hiesse, einen zu vergessen, und
# der vergessene ist genau der Abbruch. Also eine Stelle: fuer die Dauer
# des Leistenblocks bekommen die Bedienelemente von st eine Huelle, die
# disabled=True untergeschiebt. verwaltung.py zeichnet in denselben
# Modul und ist damit mitgesperrt.
_BEDIENELEMENTE = (
    "button", "download_button", "form_submit_button", "link_button",
    "selectbox", "multiselect", "slider", "select_slider", "checkbox",
    "toggle", "radio", "number_input", "text_input", "text_area",
    "date_input", "time_input", "color_picker", "file_uploader",
    "camera_input", "data_editor", "pills", "segmented_control",
    "feedback", "chat_input")


@contextlib.contextmanager
def _bedienung_gesperrt(ja, modul=None):
    """Alle Bedienelemente von `modul` sind darin gesperrt.

    Gehuellt wird nur, was `disabled` ueberhaupt kennt -- nachgesehen und
    nicht angenommen. Ein Element ohne diesen Parameter bleibt
    unberuehrt, statt mit TypeError abzustuerzen.

    Das Zuruecksetzen steht im finally: st ist ein Modul und lebt laenger
    als dieser Lauf. Eine Huelle, die nach einer Ausnahme haengenbleibt,
    sperrte die Oberflaeche dauerhaft -- derselbe Fehler, den die
    Selbstheilung der Sperre oben schon einmal kosten musste.
    """
    modul = modul if modul is not None else st
    if not ja:
        yield
        return
    vorher = {}
    for _n in _BEDIENELEMENTE:
        _f = getattr(modul, _n, None)
        if _f is None:
            continue
        try:
            if "disabled" not in inspect.signature(_f).parameters:
                continue
        except (TypeError, ValueError):
            continue
        vorher[_n] = _f

        def _huelle(*a, _f=_f, **k):
            k["disabled"] = True
            return _f(*a, **k)

        setattr(modul, _n, functools.wraps(_f)(_huelle))
    try:
        yield
    finally:
        for _n, _f in vorher.items():
            setattr(modul, _n, _f)


# --- SIDEBAR (UI) ---
with st.sidebar, _bedienung_gesperrt(_antwortet):
    if _antwortet:
        st.warning("Antwort laeuft. Die Bedienung ist gesperrt, bis sie "
                   "fertig ist -- ein Klick jetzt wuerde sie abreissen.")

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
    # NICHT _eintraege: so heisst weiter unten der Tabellenkatalog.
    # Beides unter demselben Namen ging gut, solange die Neubelegung
    # dazwischen stand -- und fiel sie weg, stuerzte die Oberflaeche
    # beim Laden ab, weil .get() auf einem Tupel nichts findet. Das
    # ist die freundliche Fassung; bei zwei Woerterbuechern haette sie
    # stattdessen das Falsche angezeigt.
    _chatliste = get_all_chats()
    _titel = {k: t for k, t, _g in _chatliste}
    existing_chats = [k for k, _t, _g in _chatliste]
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
            
    # Die Ueberschrift "Datenbank" stand hier ohne Inhalt: darunter
    # kam sofort der Trennstrich und die naechste Ueberschrift. Ein
    # Ueberbleibsel, in allen drei Fassungen.
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
    # Umgekehrt nachschlagbar: welche Datei gehoert zu welchem Projekt.
    # Wird unten in der Dokumentenliste gebraucht und kostet nichts --
    # _projekte steht ohnehin schon da.
    _projekt_von = {d: k for k, dateien in _projekte.items() for d in dateien}
    _projekt_dateien = []
    if _projekte:
        _gewaehlt_p = st.multiselect(
            "Projekt:", options=sorted(_projekte), default=[],
            help="Nur im eigenen Raum. Leer lassen, um alles zu "
                 "durchsuchen.")
        # NICHT _p: das ist zwanzig Zeilen weiter oben die
        # Voreinstellung (presets.lese) und wird weiter unten als
        # Wörterbuch gebraucht. Eine Schleifenvariable desselben
        # Namens macht daraus eine Zeichenkette -- und die Anwendung
        # bricht mit "string indices must be integers" an einer
        # Stelle ab, die mit Projekten nichts zu tun hat.
        #
        # Aufgefallen ist es erst, als jemand den Filter tatsaechlich
        # SETZTE: ohne Auswahl laeuft die Schleife nie.
        for _pj in _gewaehlt_p:
            _projekt_dateien += _projekte[_pj]

    # Die Auswahl folgt dem, was darueber eingestellt ist. Vorher
    # standen hier IMMER alle Dateien aller Raeume -- wer Raum und
    # Projekt gesetzt hatte, bekam trotzdem den vollen Bestand
    # angeboten und musste raten, welche Datei dazugehoert. Die
    # Einstellung darueber sah dabei aus, als haette sie keine Wirkung.
    if _projekt_dateien:
        _auswahl = sorted(set(_projekt_dateien))
    elif selected_raeume:
        _auswahl = sorted({d for _rr in selected_raeume
                           for d in dateien_je_raum.get(_rr, [])})
    else:
        _auswahl = all_available_files
    selected_docs = st.multiselect(
        "Suche beschränken auf:", 
        options=_auswahl,
        default=[],
        help="Leer lassen, um in allen Dokumenten der Auswahl oben zu "
             "suchen. Die Liste zeigt nur, was zu Raum und Projekt "
             "darueber passt."
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
                        _r, _t, _pf = _z.partition("=")
                        if not _t:
                            st.error(f"'{_z}' hat kein '=' -- erwartet "
                                     f"wird 'raum = pfad'.")
                            _neu = None
                            break
                        _neu.append({"raum": _r.strip(),
                                     "pfad": _pf.strip()})
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

            # DAS EINGABEFELD FUER DEN EINEN ORDNER IST WEG.
            #
            # Es tat dasselbe wie eine Zeile "allgemein = /pfad" oben,
            # nur an anderer Stelle und ohne Raumangabe. Zwei Wege zu
            # derselben Einstellung sind einer zu viel: der eine wird
            # gepflegt, der andere nicht, und welcher gerade gilt,
            # muss man raten.
            #
            # Ein bereits gesetzter Ordner bleibt GUELTIG -- er gilt
            # weiter als Quelle des allgemeinen Raums, solange dieser
            # nicht ausdruecklich anders belegt ist (tabellen.quellen).
            # Hier steht nur, dass es ihn gibt.
            if tabellen.alter_ordner():
                st.caption(
                    f"Aus frueherer Einrichtung gilt zusaetzlich "
                    f"`allgemein = {tabellen.pfad()}`. Um ihn zu "
                    f"ersetzen, oben eine Zeile fuer `allgemein` "
                    f"eintragen.")

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
                        _bneu = st.text_input(
                            "Name des neuen Bereichs",
                            key=_feldschluessel("listen_neu", "bereich"))
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
                            _felder_leeren("listen_neu", "bereich")
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
    # Mehrere auf einmal: Raum, Projekt und der Bildschalter darunter
    # gelten dann fuer den ganzen Stapel. Wer je Datei etwas anderes
    # will, laedt einzeln -- das geht weiterhin.
    hochgeladen = st.file_uploader(
        "Dokumente hochladen", key=f"pdf_upload_{_pdf_nr}",
        type=["pdf", "PDF", "docx", "md", "markdown", "txt"],
        accept_multiple_files=True,
        help="PDF, Word, Markdown oder Text. Mehrere auf einmal moeglich; "
             "Raum und Projekt gelten dann fuer alle. Wird vektorisiert "
             "und durchsuchbar.")
    if hochgeladen:
        if len(hochgeladen) > 1:
            st.caption(f"{len(hochgeladen)} Dateien. Sie werden "
                       f"nacheinander verarbeitet.")
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
        _pdfs = [d for d in hochgeladen if d.name.lower().endswith(".pdf")]
        if _bilder and _pdfs:
            # Die Schaetzung VOR der Zustimmung, und ueber den GANZEN
            # Stapel. Sie kostet keinen Modellaufruf -- gezaehlt wird im
            # Dokument. Je Datei zu schaetzen waere hier wertlos: die
            # Zustimmung gilt fuer alle, also muss die Zahl daneben auch
            # fuer alle gelten.
            try:
                import bildtext, pymupdf as _pm
                _s = _a = 0
                for _datei in _pdfs:
                    with _pm.open(stream=_datei.getvalue(),
                                  filetype="pdf") as _d:
                        _ds, _da = bildtext.zaehle(_d)
                    _s += _ds
                    _a += _da
                if _s or _a:
                    st.caption(
                        f"\u2192 {_s} gescannte Seite(n), {_a} "
                        f"Abbildung(en) -- {_s + _a} Modellaufrufe.")
                else:
                    st.caption("\u2192 Nichts Bildliches gefunden.")
            except Exception as _e:
                st.caption(f"Nicht abschaetzbar: {_e}")

        if st.button("Hochladen & Vektorisieren"):
            raeume.sichere_anlage_privat(st.session_state["username"])
            _stand = st.empty()
            # Die Fortschrittszeile der Bildbeschreibung:
            # aufnehmen.py sagt nur Bescheid, gezeichnet wird
            # hier. Es ist die einzige Ausgabe, die die
            # Funktion frueher selbst gemacht hat.
            _bildmelder = st.empty()

            def _bildstand(nr, gesamt):
                _bildmelder.caption(
                    f"Beschreibe Bilder ... Seite {nr}/{gesamt}")

            _ergebnisse = []
            for _i, _datei in enumerate(hochgeladen, 1):
                # Der Stand VOR der Datei und nicht danach: bei einem
                # grossen Scan steht der Spinner minutenlang, und ohne
                # den Namen daneben weiss niemand, ob es noch laeuft
                # oder an welcher Stelle es haengt.
                _stand.caption(f"{_i} von {len(hochgeladen)}: {_datei.name}")
                with st.spinner(f"Verarbeite '{_datei.name}' ..."):
                    _n, _hinweis = process_uploaded_pdf(
                        _datei, ziel_raum, _projekt, _bilder,
                        benutzer_=st.session_state["username"],
                        ist_verwalter=is_admin(),
                        fortschritt=_bildstand,
                        nach_dem_schreiben=refresh_document_index)
                _ergebnisse.append((_datei.name, _n, _hinweis))
            _stand.empty()
            refresh_document_index()

            # Je Datei melden. Ein Stapel hat nicht einen Ausgang,
            # sondern einen je Datei -- von fuenf kann eine ein Scan
            # ohne Textebene sein, und "3 von 5 verarbeitet" allein
            # sagt nicht, WELCHE fehlt.
            _schlecht = [e for e in _ergebnisse if not e[1]]
            for _name, _n, _hinweis in _ergebnisse:
                if _n:
                    st.success(f"'{_name}' in "
                               f"'{raeume.bezeichnung(ziel_raum)}' — "
                               f"{_n} Abschnitte durchsuchbar.")
                else:
                    st.error(f"'{_name}' wurde NICHT durchsuchbar.")
                if _hinweis:
                    st.warning(f"{_name}: {_hinweis}")

            if _schlecht:
                # Kein Neuladen: die Dateien liegen jetzt auf der
                # Platte, sind aber in keiner Sammlung. Wer hier ein
                # gruenes "hinzugefuegt" sieht, sucht spaeter vergeblich
                # und haelt es fuer einen Fehler der Suche.
                #
                # Das Feld behaelt dabei auch die gelungenen Dateien.
                # Ein zweiter Druck verarbeitet sie erneut -- das kostet
                # Zeit, verdoppelt aber nichts: store.schreibe nimmt
                # upsert, und die Kennungen sind aus Dateiname und Seite
                # gebildet.
                st.caption(f"{len(_schlecht)} von {len(_ergebnisse)} "
                           f"liegen in der Ablage, aber kein Abschnitt "
                           f"davon steht in der Suche. Behebe die Ursache "
                           f"und lade sie erneut hoch.")
            else:
                st.session_state["pdf_upload_nr"] = _pdf_nr + 1
                time.sleep(1)
                st.rerun()

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
                # Das Projekt dazu, wo es eines gibt. Es steht in den
                # Metadaten und im Ordner -- bisher nur nicht auf dem
                # Bildschirm, und damit war es fuer den Nutzer nicht
                # vorhanden. Die Zuordnung liegt fuer den eigenen Raum
                # schon vor; der Filter oben hat sie berechnet.
                _pj = _projekt_von.get(f, "") if _r == _mein_raum_f else ""
                st.caption(f"📄 {f}" + (f"  ·  {_pj}" if _pj else ""))

            # Verwalten darf, wer den Raum schreiben darf -- und dazu
            # gehoert ein bestaetigter Notzugang.
            #
            # schreibbar() sagt das seit jeher ausdruecklich: der
            # Notzugang ist zum AUFRAEUMEN da, und dafuer genuegt Lesen
            # nicht. Uebergeben wurde er hier trotzdem nicht.
            #
            # Die Folge war ein Zustand, den niemand erklaeren kann:
            # der Raum stand mit Klarnamen in der Dokumentenverwaltung
            # und daneben mit Kennungen in der Fremdenliste, und das
            # EINZIGE, was ging, war Loeschen ueber die Kennung. Also
            # genau das, wovor die Kennungen schuetzen sollen -- der
            # Weg hinein war ja von zwei Personen bestaetigt.
            _darf = raeume.darf_schreiben(st.session_state["username"], _r,
                                          is_admin(),
                                          tuple(mein_notzugang()))
            if not _darf:
                st.caption("Nur lesen.")
                continue

            st.markdown("---")
            _datei = st.selectbox("Dokument verwalten:", _dateien,
                                  key=f"verw_{_r}")
            _spalte1, _spalte2 = st.columns(2)
            with _spalte1:
                _andere = [x for x in raeume.schreibbar(
                    st.session_state["username"], is_admin(),
                    tuple(mein_notzugang())) if x != _r]
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
            st.session_state["username"], is_admin(),
            tuple(mein_notzugang()))
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
    # --- EIGENES PASSWORT ---
    #
    # Bis hierher konnte nur ein Verwalter Passwoerter setzen. Damit ist
    # das Passwort eines Nutzers eines, das jemand anders vergeben hat
    # -- und eines, das jemand anders kennt. Wer sich damit anmeldet,
    # ist im Protokoll nicht von seinem Besitzer zu unterscheiden.
    st.markdown("---")
    with st.expander("\U0001f511 Passwort aendern"):
        # EIN FORMULAR, und das ist der Kern. Ein Textfeld uebergibt
        # seinen Inhalt erst, wenn es verlassen wird. Wer tippt und
        # dann auf einen gewoehnlichen Knopf klickt, loest beides
        # gleichzeitig aus: der Knopf ist gedrueckt, die Felder tragen
        # noch die alten Werte -- das Skript sieht einen Druck auf
        # leere Felder und meldet, es fehle etwas, obwohl alles da ist.
        #
        # In einem Formular werden alle Felder GEMEINSAM uebergeben,
        # wenn der Absendeknopf gedrueckt wird. Den Zwischenzustand
        # gibt es dann nicht. Die Anmeldemaske dieser Anwendung macht
        # es seit jeher so.
        _pwe = "eigenes_pw"
        with st.form(f"eigenes_pw_{_feldschluessel(_pwe, 'runde')}"):
            _alt = st.text_input("Bisheriges Passwort", type="password",
                                 key=_feldschluessel(_pwe, "alt"))
            _neu1 = st.text_input(
                f"Neues Passwort (mindestens {benutzer.MIN_PASSWORT} Zeichen)",
                type="password", key=_feldschluessel(_pwe, "neu1"))
            _neu2 = st.text_input("Wiederholen", type="password",
                                  key=_feldschluessel(_pwe, "neu2"))
            _pw_ab = st.form_submit_button(
                "Aendern", use_container_width=True, disabled=_antwortet)
        if _pw_ab:
            _ich = st.session_state["username"]
            if not (_alt and _neu1):
                st.error("Bitte das bisherige und das neue Passwort "
                         "eintragen.")
            elif _neu1 != _neu2:
                st.error("Die Eingaben stimmen nicht ueberein.")
            elif _neu1 == _alt:
                st.error("Das ist das bisherige Passwort.")
            elif not benutzer.pruefe(_ich, _alt):
                # Geprueft und nicht geglaubt: sonst genuegt ein
                # unbeaufsichtigter Bildschirm, um jemanden dauerhaft
                # auszusperren -- und im Protokoll stuende dabei sein
                # eigener Name.
                st.error("Das bisherige Passwort stimmt nicht.")
            else:
                _ok, _m = benutzer.passwort_setzen(_ich, _neu1, von=_ich)
                (st.success if _ok else st.error)(_m)
                if _ok:
                    # Dieselbe Ueberlegung wie im Verwalterweg: hier
                    # liegt wieder ein Klartextpasswort vor, also
                    # entsteht jetzt das ownCloud-Konto, falls es fehlt.
                    # Ein vorhandenes bleibt unangetastet.
                    _bo = {}
                    if owncloud.eingerichtet():
                        with st.spinner("Richte die Ablage ein ..."):
                            _bo = owncloud.richte_nutzer_ein(_ich, _neu1,
                                                             _ich)
                        if any("gab es schon" in _t for _t
                               in _bo.get("schritte") or []):
                            st.info("In ownCloud gilt weiter das alte "
                                    "Passwort -- das Konto gab es dort "
                                    "schon.")
                    _felder_leeren(_pwe, "alt", "neu1", "neu2")
                    time.sleep(3 if _bo.get("fehler") else 2)
                    st.rerun()

    # --- MEINE POSTFAECHER ---
    #
    # Jeder verbindet seine eigenen. Die Anmeldedaten leben nur in
    # dieser Sitzung: sie werden nicht geschrieben, nicht protokolliert
    # und nicht in die Konfiguration uebernommen. Beim Abmelden sind sie
    # weg -- dafuer steht "_postfach_koepfe" in SITZUNGSSCHLUESSEL.
    #
    # Gespeichert wird nicht Benutzer und Passwort, sondern der fertige
    # Kopf. Was im Arbeitsspeicher liegt, ist damit das, was ohnehin
    # ueber die Leitung geht.
    _pf_alle = mcp.lies_konfiguration()
    _pf_login = [n for n in sorted(_pf_alle) if mcp.braucht_anmeldung(n)]
    if _pf_alle:
        _koepfe = st.session_state.setdefault("_postfach_koepfe", {})
        _offen = sum(1 for n in _pf_login if n not in _koepfe)
        with st.expander(
                "\U0001f4ec Meine Postfächer"
                + (f" ({_offen} offen)" if _offen else "")):
            if not _pf_login:
                st.caption("Kein Postfach verlangt eine eigene Anmeldung — "
                           "alle sind ohne dein Zutun erreichbar.")
            for _n in _pf_login:
                _ang = _pf_alle[_n]
                _was = ("dein persönliches Postfach"
                        if _ang.get("persoenlich") else "Funktionspostfach")
                if _n in _koepfe:
                    _s1, _s2 = st.columns([3, 1])
                    with _s1:
                        st.markdown(f"**{_n}** · {_was} · verbunden")
                    with _s2:
                        if st.button("Trennen", key=f"pfab_{_n}",
                                     use_container_width=True):
                            _koepfe.pop(_n, None)
                            st.rerun()
                    continue

                with st.form(f"pfan_{_n}_{_feldschluessel('postfach', 'runde')}"):
                    st.markdown(f"**{_n}** · {_was}")
                    _art = mcp.anmeldeart(_n)
                    if _art == "bearer":
                        _pf_u = ""
                        _pf_g = st.text_input(
                            "Token", type="password",
                            key=_feldschluessel("postfach", f"{_n}_tok"))
                    else:
                        _pf_u = st.text_input(
                            "Benutzer",
                            key=_feldschluessel("postfach", f"{_n}_ben"))
                        _pf_g = st.text_input(
                            "Passwort", type="password",
                            key=_feldschluessel("postfach", f"{_n}_pw"))
                    _pf_ok = st.form_submit_button(
                        "Verbinden", use_container_width=True,
                        disabled=_antwortet)
                if _pf_ok:
                    if not _pf_g:
                        st.error("Bitte die Anmeldedaten eintragen.")
                    else:
                        _k = mcp.kopf_fuer(_n, _pf_u, _pf_g)
                        # ERST PROBIEREN, dann merken. Sonst faellt eine
                        # falsche Anmeldung erst bei der naechsten Frage
                        # auf -- mitten in einer Antwort, die deswegen
                        # schlechter ausfaellt.
                        _probe = mcp.verbinde({_n: _k})
                        try:
                            _w = _probe[_n].werkzeuge()
                            _koepfe[_n] = _k
                            _felder_leeren("postfach")
                            st.success(f"Verbunden. {len(_w)} Werkzeuge.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Nicht verbunden: "
                                     f"{type(e).__name__}: {e}")
                        finally:
                            for _v in _probe.values():
                                try:
                                    _v.schliesse()
                                except Exception:
                                    pass

            st.caption("Die Anmeldedaten liegen nur in dieser Sitzung und "
                       "verschwinden beim Abmelden.")

    # --- EIGENE ZUGANGSTOKEN ---
    #
    # Bisher sah niemand ausser dem Verwalter, dass ueberhaupt ein Token
    # auf seine Kennung ausgestellt ist. Ein Token traegt die Rechte
    # seines Besitzers -- wer nicht weiss, dass eines existiert, kann
    # auch nicht merken, dass es zu viele sind.
    #
    # Gezeigt wird nur, was einem gehoert: auth.liste() gibt alle
    # zurueck, gefiltert wird auf die eigene Kennung, bevor etwas auf
    # den Schirm kommt.
    #
    # Widerrufen ja, anlegen nein. Ein Widerruf nimmt nur weg, und das
    # eigene Token wegzunehmen darf jeder. Das Anlegen bleibt beim
    # Verwalter -- so haelt es create_token.py seit jeher auch.
    _meine_token = [(_h, _e) for _h, _e in auth.liste()
                    if _e.get("benutzer") == st.session_state["username"]]
    if _meine_token:
        with st.expander(f"\U0001f3ab Meine Zugangstoken "
                         f"({len(_meine_token)})"):
            st.caption(
                "Ein Token gilt fuer die HTTP-Schnittstelle und traegt "
                "deine Rechte. Den Wert selbst zeigt niemand mehr an — "
                "gespeichert ist nur sein Hashwert. Was du nicht mehr "
                "brauchst, widerrufe.")
            for _h, _e in _meine_token:
                _bis = _e.get("gueltig_bis")
                _was = _e.get("bezeichnung") or "ohne Bezeichnung"
                if _bis:
                    _was += f" · bis {_bis[:10]}"
                if not _e.get("gueltig", True):
                    # Ohne gueltige Signatur: von Hand eingetragen oder
                    # veraendert. Es gilt nicht -- und wird genau deshalb
                    # gezeigt, statt verschwiegen.
                    _was += " · **UNGÜLTIG**"
                _t1, _t2 = st.columns([4, 1])
                with _t1:
                    st.markdown(f"`{_h[:8]}` · {_was}")
                    st.caption(f"angelegt {_e.get('erstellt', '?')[:19]}")
                with _t2:
                    if st.button("🗑️", key=f"eig_token_{_h[:12]}",
                                 help="Widerrufen"):
                        # Der volle Hashwert und nicht sein Anfang:
                        # auth.widerrufe trifft bei einem mehrdeutigen
                        # Anfang absichtlich keinen.
                        if auth.widerrufe(_h) == 1:
                            st.info("Widerrufen.")
                        else:
                            st.error("Nicht widerrufen.")
                        _leeren()
                        time.sleep(1)
                        st.rerun()

    verwaltung.zeichne(
        is_admin=is_admin,
        refresh_document_index=refresh_document_index,
        aktives_preset=aktives_preset,
        _antwortet=_antwortet,
        _eintraege=_eintraege,
        _leeren=_leeren,
        _feldschluessel=_feldschluessel,
        _felder_leeren=_felder_leeren,
        _verwaltungsstand=_verwaltungsstand,
        _alle_raum_sammlungen=_alle_raum_sammlungen,
        _loeschfreigabe=_loeschfreigabe,
        _p=_p)

    # NICHT in der Verwaltung, obwohl der Schnitt ihn beim
    # Herausloesen einmal mitgenommen hatte: der Regler gehoert
    # jedem, nicht nur einem Verwalter -- und die Suche unten
    # braucht seinen Wert. In verwaltung.py gesetzt, war er hier
    # schlicht nicht vorhanden.
    # Bei dichten Regelwerken kann 5 zu wenig sein: eine vollstaendige
    # Auskunft braucht dann mehrere Tabellen aus mehreren Dokumenten
    # gleichzeitig, und die wenigen Plaetze sind nach zwei Fundstellen
    # aufgebraucht. Der Standard bleibt dennoch 5; wer mehr braucht, zieht
    # den Regler oder setzt TOP_K.
    top_k = st.slider("Relevante Abschnitte abrufen", min_value=1, max_value=30,
                      value=_p["top_k"] or paths.env_int("TOP_K", 5),
                      key=f"topk_{aktives_preset}")

    # --- QUELLE ---
    #
    # Die AGPL verlangt in Paragraph 13, dass Nutzer, die ueber ein
    # NETZ mit dieser Anwendung arbeiten, an ihren Quelltext kommen.
    # Ein Verweis genuegt dafuer, solange der laufende Stand der
    # veroeffentlichte ist -- deshalb gehen die drei Fassungen im
    # Gleichschritt.
    #
    # Das ist die einzige funktionale Aenderung, die die Umstellung
    # von MIT auf AGPL mit sich bringt.
    st.markdown("---")
    st.caption(
        "LocaNoto \u00b7 "
        "[AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) \u00b7 "
        "[Quelltext](https://github.com/mw-research/LocaNoto)")

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

            # --- ENTWUERFE, DIE AUF EINEN MENSCHEN WARTEN ---
            #
            # Ein Werkzeug, das etwas verschickt, wird nicht ausgefuehrt,
            # sondern vorgelegt. Erst der Klick hier schickt es los.
            # Welche Aufrufe das sind, entscheidet mcp.braucht_bestaetigung:
            # ohne ausdrueckliche Freischaltung des Postfachs jeder.
            for _ei, _entw in enumerate(msg.get("entwuerfe") or []):
                _eschl = f"entw_{i}_{_ei}"
                if _eschl in st.session_state.get("_gesendet", set()):
                    st.success(f"Gesendet: {_entw['werkzeug']}")
                    continue
                with st.expander(
                        f"\u270d\ufe0f Entwurf: {_entw['werkzeug']} "
                        f"({_entw['server']}) — wartet auf dich",
                        expanded=True):
                    for _k, _w in (_entw.get("argumente") or {}).items():
                        st.markdown(f"**{_k}**")
                        st.code(str(_w), language="text")
                    _s1, _s2 = st.columns(2)
                    with _s1:
                        if st.button("Senden", key=f"snd_{_eschl}",
                                     use_container_width=True):
                            _vb = mcp.verbinde(
                                st.session_state.get("_postfach_koepfe"))
                            try:
                                _erg = _vb[_entw["server"]].rufe(
                                    _entw["werkzeug"], _entw["argumente"])
                                st.session_state.setdefault(
                                    "_gesendet", set()).add(_eschl)
                                st.success(str(_erg)[:300])
                            except Exception as e:
                                st.error(f"{type(e).__name__}: {e}")
                            finally:
                                for _v in _vb.values():
                                    try:
                                        _v.schliesse()
                                    except Exception:
                                        pass
                            time.sleep(1)
                            st.rerun()
                    with _s2:
                        if st.button("Verwerfen", key=f"vrw_{_eschl}",
                                     use_container_width=True):
                            st.session_state.setdefault(
                                "_gesendet", set()).add(_eschl)
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
        accept_file="multiple", file_type=vision.ERLAUBTE_TYPEN,
        disabled=_antwortet)

    # --- ANNEHMEN, NICHT BEANTWORTEN ---
    #
    # Hier wird die Frage nur gemerkt und neu gezeichnet. Geantwortet
    # wird im naechsten Lauf -- dessen Seitenleiste ist von Anfang an
    # gesperrt, und nur so laesst sich der Antwortstrom schuetzen. Im
    # selben Lauf ginge es nicht: die Leiste steht zu diesem Zeitpunkt
    # laengst.
    #
    # Die Bilddateien gehen dabei sofort auf die Platte, denn die
    # Objekte aus chat_input ueberleben den neuen Lauf nicht. Das
    # Speichern ist schnell; die Beschreibung -- ein Modellaufruf je
    # Bild, bei einem Scan Minuten -- passiert erst danach, hinter der
    # Sperre.
    if eingabe and not st.session_state.get("_laeuft"):
        _text = (eingabe.text or "").strip()
        _pfade, _namen = [], []
        for n, datei in enumerate(eingabe.files or []):
            try:
                endung = os.path.splitext(datei.name)[1].lower() or ".jpg"
                kennung = st.session_state.current_chat_id
                name = (f"{kennung.rsplit('.', 1)[0]}"
                        f"_{len(st.session_state.messages)}_{n}{endung}")
                _pfade.append(vision.speichern(
                    datei.getvalue(), st.session_state["username"], name))
                _namen.append(datei.name)
            except Exception as e:
                st.warning(f"Bild '{datei.name}' konnte nicht gelesen "
                           f"werden: {e}")
        if not _text and not _pfade:
            st.stop()
        st.session_state["_auftrag"] = {"frage": _text, "bilder": _pfade,
                                        "namen": _namen}
        st.session_state["_laeuft"] = True
        st.rerun()

    # _auftrag wurde ganz oben herausgenommen, noch vor der
    # Seitenleiste -- siehe dort, warum.
    if _auftrag:
        user_query = _auftrag["frage"]
        bild_pfade = list(_auftrag["bilder"])

        # --- ANGEHAENGTE BILDER BESCHREIBEN ---
        #
        # Das Sehmodell wandelt sie in Text um. Der wird an zwei Stellen
        # gebraucht: als zusaetzliche Suchsonde, damit die Dokumentensuche
        # ueberhaupt etwas zum Bild findet, und im Kontext der Antwort. Das
        # Chat-Modell selbst bekommt das Bild nicht -- es kann in dieser
        # Aufteilung ein reines Textmodell sein.
        bild_texte = []
        for n, (pfad, anzeige) in enumerate(zip(bild_pfade,
                                                _auftrag["namen"])):
            with st.spinner(f"Lese Bild {n + 1} von {len(bild_pfade)} ..."):
                try:
                    with open(pfad, "rb") as _f:
                        bild_texte.append(vision.beschreibe(_f.read(),
                                                            user_query))
                except Exception as e:
                    st.warning(f"Bild '{anzeige}' konnte nicht gelesen "
                               f"werden: {e}")

        if not user_query and not bild_texte:
            st.session_state["_laeuft"] = False
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
                    except budget.Ueberzogen as e:
                        # Das Entnahmebudget ist eine ERWARTETE Grenze,
                        # kein Fehler. Ungefangen endete sie als rote
                        # Rueckverfolgung mitten im Chat -- und so sieht
                        # sie fuer den Benutzer aus wie ein Absturz. Sie
                        # hat einen Grund und nennt die Einstellung, die
                        # sie hebt; also gehoert beides hin.
                        #
                        # Eigene Klausel und nicht die darunter: Ueberzogen
                        # ist kein ValueError, es waere vorbeigeflogen.
                        st.warning(str(e))
                        st.stop()
                    except ValueError as e:
                        st.error(str(e))
                        st.stop()

                if not treffer:
                    # Die aussagekraeftigste Rueckmeldung ist die, fuer die
                    # niemand einen Knopf druecken muss.
                    feedback.notiere("leer", st.session_state["username"],
                                     user_query, sonden=search_queries,
                                     zahlen=zahlen)

                # EIN AUSGEFALLENER SUCHWEG WIRD GENANNT.
                #
                # Eine Antwort ohne Vektorsuche sieht aus wie jede
                # andere: der Stichwortindex traegt sie, formuliert
                # sauber, mit richtigen Fundstellen. In einer
                # Installation war die Vektorsuche monatelang tot --
                # die Vektoren lagen mit 2560 Dimensionen, das Modell
                # liefert 4096 -- und von aussen war nichts zu sehen.
                if zahlen.get("vektorausfall"):
                    st.error(
                        "**Die Vektorsuche hat für "
                        + ", ".join(f"`{_r}`" for _r
                                    in sorted(zahlen["vektorausfall"]))
                        + " nicht geantwortet.** Diese Antwort stützt "
                          "sich allein auf die Stichwortsuche und ist "
                          "damit schlechter, als sie sein müsste. "
                          "Grund: "
                        + "; ".join(sorted(
                            set(zahlen["vektorausfall"].values()))))

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

                # --- 3b. WERKZEUGE ---
                #
                # Ist ein Werkzeugserver eingerichtet, darf das Modell
                # vor der Antwort nachschlagen -- etwa in einem
                # Postfach. Ohne Server passiert hier nichts: kein
                # Modellaufruf, keine Werkzeugliste, kein Zeitverlust.
                #
                # Die Anmeldedaten kommen aus dem Sitzungszustand und
                # nur von dort. Sie stehen weder in der Konfiguration
                # noch auf der Platte.
                _system = pipeline.systemprompt(dynamic_context,
                                                aktives_preset)
                _zusatz, _entwuerfe = [], []
                if mcp.eingerichtet():
                    _wmelder = st.empty()
                    _verb = mcp.verbinde(
                        st.session_state.get("_postfach_koepfe"))
                    try:
                        _zusatz, _entwuerfe = pipeline.werkzeuglauf(
                            chat_client, chat_model, _system,
                            st.session_state.messages, _verb,
                            fortschritt=lambda t: _wmelder.caption(
                                "\U0001f527 " + str(t)))
                    except Exception as e:
                        # Ein Postfach, das klemmt, darf die Frage nach
                        # einem Dokument nicht mitnehmen.
                        st.warning(f"Werkzeuge nicht verfügbar: "
                                   f"{type(e).__name__}: {e}")
                    finally:
                        for _v in _verb.values():
                            try:
                                _v.schliesse()
                            except Exception:
                                pass
                    _wmelder.empty()

                # --- 4. ANTWORT ---
                answer = _strom_zeichnen(
                    pipeline.antwort(
                        chat_client, chat_model, _system,
                        st.session_state.messages, zusatz=_zusatz),
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
                    # Was verschickt haette werden koennen und nicht
                    # ausgefuehrt wurde. Es haengt an der Nachricht,
                    # damit es einen Neuaufbau der Seite ueberlebt.
                    "entwuerfe": _entwuerfe,
                })
                save_chat(st.session_state.current_chat_id,
                          st.session_state.messages)

                # Die Antwort steht -- die Bedienung darf wieder.
                st.session_state["_laeuft"] = False

                # Neu zeichnen, damit die Nachricht durch die Chat-Schleife
                # oben laeuft und ihre Quellen-Aufklapper bekommt.
                st.rerun()

            except Exception as e:
                # Auch hier loesen: eine Sperre, die einen Fehler
                # ueberlebt, macht die Anwendung unbedienbar.
                st.session_state["_laeuft"] = False
                st.error(f"Fehler bei der Verarbeitung: {e}")

else:
    st.info("Die Datenbank ist leer. Bitte nutze dein Hintergrund-Skript, um PDFs einzulesen.")