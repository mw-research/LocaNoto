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
import sprache
from sprache import t as tx
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
                       process_uploaded_pdf, dokument_pfad,
                       entferne_dokument, NichtGefunden)
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
    st.error(tx("Installationsschlüssel ist nicht lesbar."))
    st.code(_schl_meldung, language="text")
    st.caption(tx("LocaNoto hält hier an – sonst würden Chatverläufe im Klartext überschrieben."))
    st.stop()

# 1. Werte aus der docker-compose.yml holen
thema = os.getenv("APP_TOPIC", "Allgemein")
firma = os.getenv("COMPANY_NAME", "LocaNoto")

# 2. Page Config (Browser-Tab-Titel) dynamisch machen
st.set_page_config(page_title=f"{firma} - {thema}", layout="wide")


def _sprache_festlegen():
    """Die Sprache dieses Laufs: in der Sitzung gewaehlt, sonst die
    gespeicherte des Nutzers, sonst die Vorgabe der Installation."""
    _wer_s = st.session_state.get("username")
    if _wer_s and "_sprache" not in st.session_state:
        st.session_state["_sprache"] = sprache.gewaehlt(_wer_s)
    sprache.setze(st.session_state.get("_sprache") or sprache.VORGABE)


def _sprachwahl(schluessel, speichern_fuer=None):
    """Umschalter Deutsch/English. Gespeichert, sobald jemand angemeldet ist."""
    _jetzt = sprache.aktuell()
    _neu = st.radio(tx("🌐 Sprache / Language"), list(sprache.SPRACHEN),
                    index=list(sprache.SPRACHEN).index(_jetzt),
                    format_func=sprache.uebersetzt(sprache.SPRACHEN.get),
                    horizontal=True, key=schluessel)
    if _neu != _jetzt:
        st.session_state["_sprache"] = _neu
        if speichern_fuer:
            sprache.speichere(speichern_fuer, _neu)
        else:
            # Vor der Anmeldung umgeschaltet: gilt fuer den, der sich
            # gleich anmeldet -- und nur dann wird es gemerkt.
            st.session_state["_sprache_vor_anmeldung"] = True
        st.rerun()


_sprache_festlegen()

# 3. Nur EINMAL die Überschrift auf der Seite setzen!
st.title(tx(f"{firma} - {thema} Assistent"))

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
        _sprache_festlegen()


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
    st.markdown(tx("<h1 style='text-align: center; margin-top: 10vh;'>Bei LocaNoto anmelden</h1>"), unsafe_allow_html=True)

    if st.session_state.pop("sitzung_lief_ab", False):
        st.info(tx(f'Sitzung nach {SITZUNG_MINUTEN} Minuten ohne Eingabe beendet.'))

    zustand = benutzer.zustand()
    if zustand == benutzer.LEER:
        st.warning(tx("Keine Benutzer gefunden. Führe zuerst 'create_user.py' auf dem Server aus."))
        st.stop()
    if zustand == benutzer.MANIPULIERT:
        # Kein Abbruch: die Anmeldung der bestehenden Nutzer funktioniert
        # weiter. Was nicht funktioniert, ist die Anmeldung eines von Hand
        # eingetragenen Zugangs -- und genau das soll hier stehen.
        gesperrt = benutzer.ungueltige()
        st.error(tx("Benutzerdatei wurde außerhalb von LocaNoto geändert.")
                 + (tx(f" Gesperrt: {', '.join(gesperrt)}.") if gesperrt else ""))

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        _sprachwahl("sprache_anmeldung")
        with st.form("login_form"):
            login_user = st.text_input(tx("Benutzername")).strip().lower()
            login_pass = st.text_input(tx("Passwort"), type="password")
            submit_button = st.form_submit_button(tx("Anmelden"), use_container_width=True)

            if submit_button:
                # Eine Meldung fuer beide Faelle. "Benutzer existiert nicht"
                # verriet, welche Kennungen es gibt -- die halbe Arbeit fuer
                # jemanden, der Passwoerter durchprobiert.
                if benutzer.pruefe(login_user, login_pass):
                    st.session_state["username"] = login_user
                    st.session_state["letzte_tat"] = time.time()
                    # Auf der Anmeldeseite umgeschaltet: das gilt und
                    # wird gemerkt. Sonst die gespeicherte Wahl.
                    if st.session_state.pop("_sprache_vor_anmeldung",
                                            False):
                        sprache.speichere(login_user,
                                          st.session_state["_sprache"])
                    else:
                        st.session_state["_sprache"] = \
                            sprache.gewaehlt(login_user)
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
                    st.error(tx("Anmeldung fehlgeschlagen."))

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
    st.caption(tx(f"👤 Angemeldet als: **{st.session_state['username']}**"))
    if st.button(tx("Abmelden"), use_container_width=True):
        beende_sitzung()
        st.rerun()
    _sprachwahl("sprache_leiste", st.session_state["username"])
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
            "Gib dieser Frage einen kurzen Titel: hoechstens sechs Woerter, "
            "die markantesten Begriffe zuerst, in der Sprache der Frage. "
            "Antworte NUR mit dem Titel, ohne Anfuehrungszeichen.\n"
            f"Frage: {user_query}"
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
        keywords = _titel_bereinigen(lines[-1]) if lines else ""
    except Exception:
        keywords = ""

    if not keywords:
        # Rueckfall: die ersten Woerter der Frage.
        keywords = _titel_bereinigen(" ".join(user_query.split()[:6]))

    return keywords or "Chat"


def _titel_bereinigen(text):
    """Ein Titel fuer die Chat-Liste: ein Satz, hoechstens 60 Zeichen.

    Er steht verschluesselt im Chat-Verzeichnis, nicht im Dateinamen --
    Leerzeichen und Satzzeichen sind deshalb kein Problem mehr.
    """
    text = " ".join(str(text or "").replace("_", " ").split())
    text = text.strip(" \"'„“”‚‘’*#.:;-")
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0] + " …"
    return text


def _titel_anzeige(titel):
    """Wie ein Titel in der Liste steht. Alte Titel hiessen
    "Druckbehaelter_Pruefung 26-10-26" -- ohne Unterstriche und ohne
    angehaengtes Datum liest sich das als Titel."""
    t = re.sub(r"[ _]\d{2}-\d{2}-\d{2}$", "", str(titel or ""))
    return " ".join(t.replace("_", " ").split()) or "Chat"


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


_BILD_MD = re.compile(r"!\[")


def _ohne_fremdbilder(text):
    """Ein Bild aus einer fremden Adresse wird ein gewoehnlicher Link.

    Markdown-Bilder laedt der Browser von selbst. Steht in einer Antwort
    ![](https://irgendwo/?d=...), ruft er die Adresse auf, ohne dass
    jemand klickt -- und was in der Adresse steht, ist dann draussen.
    Seit es die Websuche gibt, kann fremder Text das Modell genau dazu
    anstiften. Ein Link wird erst durch einen Klick aufgerufen.
    """
    # Jedes "![" und nicht nur die Form mit Klammer: Markdown kennt auch
    # Bilder mit Verweis, ![x][1] und weiter unten [1]: https://...
    return _BILD_MD.sub("[Bild: ", text or "")


def _md_roh(text):
    """Fremder Text fuer eine Markdown-Stelle: alles Steuernde maskiert.

    Titel und Ausschnitte aus dem Netz stehen in Beschriftungen, die
    Markdown auswerten. Ohne Maskieren wuerde ein Titel mit ![](...) ein
    Bild nachladen.
    """
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", str(text or ""))


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
    text = _ohne_fremdbilder(text)
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
        tx("Stichwortindex konnte nicht aufgebaut werden – Suche nur über Vektoren, wörtliche Treffer können fehlen. Nachholen mit `python rebuild_index.py`.\n\nGrund: ") + str(_index_fehler)[:400])

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
    # ownCloud zieht mit. Sonst laege die Datei dort weiter im alten
    # Raum, und dessen naechster Abgleich holte sie als neu zurueck --
    # ein aus einem geteilten Raum herausgenommenes Dokument stuende
    # wieder darin.
    ok, m = owncloud.verschiebe(von_raum, quelle, nach_raum, ziel)
    if not ok:
        return (f" ACHTUNG: {m} Der naechste Abgleich holt die Datei in "
                f"'{raeume.bezeichnung(von_raum)}' zurueck.")
    return ""


# "Seite" und "page": antwortet das Modell auf Englisch, zitiert es so.
_QUELLENMUSTER = re.compile(
    r"\[([^\[\]]{1,120}?),\s*(Seite|S\.|[Pp]age|[Pp]\.)\s*(\d+)\]")


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
        name, wort, seite = (treffer.group(1).strip(), treffer.group(2),
                             treffer.group(3).strip())
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
            return f"[{name}, {wort} {seite}](quelle?t={_tk})"
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
        return f"[{name}, {wort} {seite}](#q{nr}-{k})"

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
    st.warning(tx(f'{zahl:,} Abschnitte. Nicht rückgängig zu machen.'))
    try:
        _abz = sicherung.liste()
        if _abz:
            st.caption(tx(f"Neuester Abzug: {_abz[0][0]}"))
        else:
            st.caption(tx("KEIN Abzug vorhanden – danach endgültig."))
    except Exception:
        pass
    st.caption(tx("Zum Bestätigen die Kennung des Arbeitsbereichs eintippen:"))
    st.code(kennung, language=None)
    eingabe = st.text_input(tx("Kennung"), key=f"{key}_text",
                            label_visibility="collapsed",
                            placeholder=kennung)
    return eingabe.strip() == kennung


def loesche_dokument(filename, raum, kennung_statt_name=False):
    """Loescht ein Dokument aus genau einem Raum. (ok, meldung).

    Der Weg selbst steht in aufnehmen.entferne_dokument -- derselbe, den
    die Schnittstelle unter DELETE /dokumente nimmt. Die Rechte prueft
    hier die Oberflaeche: sie zeigt den Knopf nur, wo geloescht werden
    darf.
    """
    try:
        meldung, _bericht = entferne_dokument(
            filename, raum, kennung_statt_name=kennung_statt_name)
    except NichtGefunden as e:
        return False, str(e)
    refresh_document_index()
    return True, meldung


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
# Wie viele gelesene Seiten eine Sitzung im Speicher behaelt.
_WEB_PUFFER_MAX = 20


def _web_lesen(adresse):
    """(text, fehler) -- die ganze Seite, je Sitzung gepuffert.

    Gelesen wird ueber den Websuche-Dienst, nicht vom Browser: als reiner
    Text, ohne Skripte, ohne Bilder, und die Seite sieht den Server statt
    des Nutzers. Gepuffert, damit Lesen und Uebernehmen dieselbe Fassung
    meinen -- uebernommen wird, was gelesen wurde.
    """
    puffer = st.session_state.setdefault("_web_puffer", {})
    if adresse in puffer:
        return puffer[adresse], ""
    vb = mcp.verbinde(ohne=set(mcp.lies_konfiguration())
                      - mcp.websuche_server())
    text, fehler = None, "Kein Websuche-Server erreichbar."
    try:
        for v in vb.values():
            try:
                text = v.rufe("seite_lesen",
                              {"adresse": adresse}).split("\n\n", 1)[-1]
                break
            except Exception as e:
                fehler = f"{type(e).__name__}: {e}"
    finally:
        for v in vb.values():
            try:
                v.schliesse()
            except Exception:
                pass
    if text is None:
        return None, fehler
    while len(puffer) >= _WEB_PUFFER_MAX:
        puffer.pop(next(iter(puffer)))
    puffer[adresse] = text
    return text, ""


def _web_vorschau(treffer, schluessel):
    """Lesen vor dem Uebernehmen: Knopf, Original, gepufferter Text."""
    offen = st.session_state.setdefault("_web_offen", set())
    adresse = treffer["adresse"]
    l, r = st.columns(2)
    with l:
        if adresse in offen:
            if st.button(tx("Schließen"), key=f"zu_{schluessel}",
                         use_container_width=True):
                offen.discard(adresse)
                st.rerun()
        elif st.button(tx("Lesen"), key=f"lesen_{schluessel}",
                       use_container_width=True,
                       help=tx("Seite als reiner Text, über die Websuche geholt.")):
            offen.add(adresse)
            st.rerun()
    with r:
        st.link_button(tx("Original ↗"), adresse, use_container_width=True,
                       help=tx("Öffnet die Seite direkt in deinem Browser, nicht über den Server."))
    if adresse in offen:
        with st.spinner(tx("Lese ...")):
            text, fehler = _web_lesen(adresse)
        if text is None:
            st.warning(tx(f"Nicht lesbar: {fehler}"))
        else:
            # Ein Textfeld und kein Markdown: fremder Text darf hier
            # nichts nachladen und nichts formatieren.
            st.text_area(tx("Inhalt"), text, height=420, disabled=True,
                         key=f"inhalt_{schluessel}",
                         label_visibility="collapsed")
            st.caption(tx(f"{len(text):,} Zeichen".replace(",", ".")))


def _web_uebernehmen(treffer):
    """Treffer der Websuche als Dokumente in den eigenen Raum.

    Die ganze Seite, und zwar die gelesene, wenn sie gelesen wurde.
    Geht das Lesen nicht, bleibt der Auszug. Wohin, entscheidet
    aufnehmen: immer der eigene Raum.
    """
    for _w in treffer:
        _wtext, _fehler = _web_lesen(_w["adresse"])
        if _wtext is None:
            _wtext = _w["text"]
        try:
            _wn, _wh, _wname = aufnehmen.webseite_aufnehmen(
                _w["titel"], _w["adresse"], _wtext,
                anfrage=_w.get("anfrage", ""),
                benutzer_=st.session_state["username"])
            (st.success if _wn else st.warning)(f"{_wname}: {_wh}")
        except Exception as e:
            st.error(f"{_md_roh(_w['titel'])}: {type(e).__name__}: {e}")
    refresh_document_index()


with st.sidebar, _bedienung_gesperrt(_antwortet):
    if _antwortet:
        st.warning(tx("Antwort läuft – Bedienung gesperrt, bis sie fertig ist."))

    # --- VOREINSTELLUNG ---
    #
    # Ganz oben, weil sie alles darunter faerbt: Modell, Umfang der Treffer,
    # Sachgebiete und die Formulierung der Prompts. Ohne angelegte
    # Voreinstellungen erscheint die Auswahl nicht -- ein Feld mit genau
    # einem Eintrag ist keine Auswahl.
    _namen = presets.namen() + presets.eigene(st.session_state["username"])
    if _namen:
        _wahl = st.selectbox(
            tx("Voreinstellung"), ["(Standard)"] + _namen,
            format_func=sprache.uebersetzt(lambda n: (n if n == "(Standard)"
                                   else presets.anzeige(n))),
            help=tx("Bündel aus Chat-Modell, Trefferzahl, Sachgebieten und Formulierung; anzulegen im Admin-Bereich."))
        aktives_preset = None if _wahl == "(Standard)" else _wahl
        _p = presets.lese(aktives_preset)
        if _p.get("beschreibung"):
            st.caption(tx(_p["beschreibung"]))
        st.markdown("---")
    else:
        aktives_preset = None
        _p = presets.lese(None)

    st.header(tx("Chats"))
    
    # 1. Neuer Chat Button
    if st.button(tx("Neuer Chat"), use_container_width=True):
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
            tx("Frühere Chats:"),
            existing_chats,
            index=existing_chats.index(st.session_state.current_chat_id),
            format_func=sprache.uebersetzt(
                lambda x: _titel_anzeige(_titel.get(x, "Chat")))
        )
        
        # Wechselt den Chat, wenn ein anderer im Dropdown ausgewählt wurde
        if selected_chat != st.session_state.current_chat_id:
            st.session_state.current_chat_id = selected_chat
            st.rerun()
            
        # 3. Aktuellen Chat löschen
        if st.button(tx("Chat löschen"), use_container_width=True):
            delete_chat(st.session_state.current_chat_id)
            del st.session_state.current_chat_id # Zwingt das Skript, beim Rerun einen neuen Chat anzulegen oder den nächstbesten zu laden
            st.success(tx("Chat gelöscht."))
            time.sleep(0.5)
            st.rerun()
            
    # Die Ueberschrift "Datenbank" stand hier ohne Inhalt: darunter
    # kam sofort der Trennstrich und die naechste Ueberschrift. Ein
    # Ueberbleibsel, in allen drei Fassungen.
    st.markdown("---")
    st.header(tx("Dokumentfilter"))

    # --- RAUM ---
    #
    # Zuerst der Raum, weil er die groebste Einschraenkung ist: er
    # entscheidet, welche Sammlungen ueberhaupt gefragt werden. Leer
    # gelassen werden alle erlaubten durchsucht -- das ist der Normalfall
    # und soll keine Klicks kosten.
    raum_optionen = [r for r, _s in meine_sammlungen()]
    selected_raeume = st.multiselect(
        tx("Arbeitsbereich:"),
        options=raum_optionen,
        default=[],
        format_func=sprache.uebersetzt(raeume.bezeichnung),
        help=tx("Leer lassen → alle deine Arbeitsbereiche werden durchsucht.")
    ) if len(raum_optionen) > 1 else []

    # --- WEBSUCHE ---
    #
    # Nur wenn ein Websuche-Server eingerichtet ist, und nur auf Wunsch.
    # Gesucht wird dann ohne Rueckfrage -- das Einschalten ist die
    # Entscheidung. Ob es neben den gefragten Raeumen sein darf, steht
    # am Raum: das Modell formuliert den Suchbegriff mit deren
    # Abschnitten im Kontext. Gefragt sind die gewaehlten Raeume, ohne
    # Wahl alle erlaubten -- und dann muessen es alle erlauben.
    _web_server = mcp.websuche_server()
    _web_frei = False
    if _web_server:
        if st.toggle(tx("Websuche"), key="_websuche_an",
                     help=tx("Reichen die Dokumente nicht, sucht das Modell im Netz; hinaus geht nur der Suchbegriff.")):
            _web_zu = [r for r in (selected_raeume or raum_optionen)
                       if not raeume.websuche_erlaubt(r)]
            if _web_zu:
                st.caption(tx("🌐 Nicht freigegeben neben: ")
                           + ", ".join(raeume.bezeichnung(r)
                                       for r in _web_zu)
                           + tx(" — oben nur freigegebene Arbeitsbereiche wählen."))
            else:
                _web_frei = True
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
            tx("Projekt:"), options=sorted(_projekte), default=[],
            help=tx("Nur in deinem Arbeitsbereich. Leer lassen → alles wird durchsucht."), format_func=sprache.uebersetzt())
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
        tx("Suche beschränken auf:"), 
        options=_auswahl,
        default=[],
        help=tx("Leer lassen → alle Dokumente der Auswahl oben werden durchsucht.")
    , format_func=sprache.uebersetzt())
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
        st.header(tx("Datenbank"))

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
                tx("Zugang"), _wahlen,
                format_func=sprache.uebersetzt(lambda r: (raeume.bezeichnung(r) if r
                                       else "Vorgabe aus der Umgebung")),
                key="sql_zugang")
        else:
            sql_raum = _wahlen[0] if _wahlen else ""
        _z = sqlquellen.zugang(sql_raum) if sql_raum else None
        if _z:
            st.caption(tx(f"Angemeldet als `{_z.get('benutzer')}`"))

        sql_schema, sql_fehler = lade_sql_schema(sql_raum)
        if sql_fehler:
            # Kurz und im Klartext. Die Meldung des Treibers nennt
            # Adresse und Zustand der Verbindung -- das gehoert nicht
            # auf den Bildschirm jedes Nutzers.
            st.warning(tx("Keine Datenbankverbindung – Antworten nur aus den Dokumenten."))
            if is_admin():
                with st.expander(tx("Treibermeldung")):
                    st.code(sql_fehler, language="text")
            if st.button(tx("Neu verbinden"), use_container_width=True):
                lade_sql_schema.clear()
                st.rerun()
        elif sql_schema:
            sql_aktiv = st.toggle(
                tx("Datenbank einbeziehen"),
                value=paths.env_flag("SQL_DEFAULT_ON", False),
                key="sql_an",
                help=tx("Das Modell schreibt eine SELECT-Abfrage, ausgeführt mit dem Konto oben."))

    if (_eintraege or tabellen.vorhanden() or is_admin()
            or listenquellen.liste()):
        st.markdown("---")
        st.header(tx("Listen"))

        if _eintraege:
            _gross = [e for e in _eintraege if e.get("gross")]
            _klein = [e for e in _eintraege if not e.get("gross")]
            tabellen_aktiv = st.checkbox(
                tx("Listen mit abfragen"),
                value=os.getenv("TABELLEN_DEFAULT_ON", "1").strip().lower()
                not in ("0", "false", "nein", "no"),
                help=tx("Das Modell wählt die passende Liste und fragt sie bei jeder Frage frisch ab."))
            st.caption(tx(f'{len(_klein)} Blätter bereit')
                       + (tx(f', {len(_gross)} zu groß') if _gross else ""))

            # Bereiche sind die Unterordner des Listenordners -- fuer Listen
            # dasselbe, was Sachgebiete fuer Dokumente sind. Ein Pfad wird
            # dabei nirgends eingegeben: der Wurzelordner steht in der .env,
            # sonst koennte man von hier aus in jedes Verzeichnis des
            # Containers sehen.
            _bereiche = tabellen.bereiche(_eintraege)
            if len(_bereiche) > 1 and tabellen_aktiv:
                tabellen_bereiche = st.multiselect(
                    tx("Listenbereich"), options=_bereiche,
                    default=[b for b in _p["listen_bereiche"]
                             if b in _bereiche],
                    key=f"listenbereich_{aktives_preset}",
                    help=tx("Leer lassen → alle Listen werden einbezogen."), format_func=sprache.uebersetzt())

            if _gross and tabellen_aktiv:
                tabellen_gross = st.checkbox(
                    tx(f'Große Listen einbeziehen ({len(_gross)})'),
                    value=False,
                    help=tx("Sehr viele Zeilen, bei jeder Frage ganz geladen → Fragen können sehr lange dauern."))
                if tabellen_gross:
                    st.warning(tx("Große Listen einbezogen – Fragen dauern deutlich länger."))
        else:
            st.caption(tx("Dateien vorhanden, noch nicht eingelesen."))

        # --- ERKANNTE BLAETTER ---
        #
        # Die Kopfzeilenerkennung liegt meistens richtig. Wo nicht, ist der
        # Katalog fuer diese Datei falsch -- Spalten heissen dann s_1 statt
        # "Bezeichnung", und das Modell antwortet zwar richtig, kann seine
        # Auskunft aber nicht benennen. Deshalb sichtbar und korrigierbar.
        if _eintraege:
            with st.expander(tx(f'Erkannte Blätter ({len(_eintraege)})')):
                for _e in _eintraege:
                    _kenn = _e["datei"] + (f"#{_e['blatt']}" if _e["blatt"]
                                           else "")
                    _kopf = int(_e.get("kopfzeile", 0))
                    _felder = [s["feld"] for s in _e["spalten"]]
                    _namenlos = sum(1 for s in _e["spalten"]
                                    if not s["name"] or
                                    s["name"].lower().startswith(
                                        ("unnamed", "spalte ")))
                    st.markdown(tx(f"**{_kenn}** · Kopfzeile {_kopf + 1} "
                                f"· {_e['zeilen']} Zeilen"))
                    if _namenlos:
                        st.warning(tx(f'{_namenlos} von {len(_felder)} Spalten ohne Namen – vermutlich falsche Kopfzeile.'))
                    st.caption(tx(", ".join(_felder[:10])
                               + (" ..." if len(_felder) > 10 else "")))

                    if is_admin():
                        _neu = st.number_input(
                            tx("Kopfzeile"), min_value=1, max_value=50,
                            value=_kopf + 1, key=f"kopf_{_kenn}",
                            help=tx("Zeile mit den Spaltennamen, ab 1 gezählt."))
                        if int(_neu) - 1 != _kopf:
                            if st.button(tx("Übernehmen und neu einlesen"),
                                         key=f"kopfb_{_kenn}",
                                         use_container_width=True):
                                tabellen.setze_kopfzeile(
                                    _e["datei"], _e["blatt"], int(_neu) - 1)
                                with st.spinner(tx("Lese neu ein ...")):
                                    tabellen.baue_katalog()
                                st.rerun()
                    st.markdown("---")

        if _katalog.get("fehler"):
            with st.expander(tx(f"Nicht lesbar ({len(_katalog['fehler'])})")):
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
            with st.expander(tx("Mein Listenordner"), expanded=False):
                st.caption(
                    tx(f'Nur du siehst die Listen aus diesem Ordner. Er muss in `{_mein_bereich}` liegen.'))
                _mp_alt = listenquellen.pfad_von(_mein_raum) or _mein_bereich
                _mp = st.text_input(tx("Ordner"), value=_mp_alt,
                                    key="mein_listenordner")
                if st.button(tx("Übernehmen"), use_container_width=True,
                             key="mein_listenordner_b"):
                    _ok_mp, _m_mp = listenquellen.setze_raum(
                        _mein_raum, _mp,
                        benutzer=st.session_state.get("username", "?"))
                    if not _ok_mp:
                        st.error(tx(_m_mp))
                    else:
                        with st.spinner(tx("Lese Listen ein ...")):
                            tabellen.baue_katalog()
                        st.success(tx("Übernommen."))
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
            with st.expander(tx("Mein Datenbankzugang"),
                             expanded=False):
                st.caption(
                    tx("Dein eigenes Konto an der Fachdatenbank → Fragen laufen mit deinen Rechten."))
                _mz_b = st.text_input(tx("Benutzer"),
                                      value=_mz.get("benutzer", ""),
                                      key="mein_sql_b")
                _mz_p = st.text_input(tx("Passwort"),
                                      value=_mz.get("passwort", ""),
                                      type="password", key="mein_sql_p")
                if st.button(tx("Übernehmen"), use_container_width=True,
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
            with st.expander(tx("Listenquellen je Arbeitsbereich"), expanded=False):
                st.caption(
                    tx(f'Eine Zeile je Quelle: **arbeitsbereich = pfad**. Der Arbeitsbereich bestimmt, wer die Listen sieht. `{listenquellen.MUSTER_RAUM}` = persönlicher Arbeitsbereich jedes Nutzers; der Pfad braucht dann `{listenquellen.PLATZHALTER}` für den Anmeldenamen.'))
                _vorlage = "\n".join(
                    f"{q['raum']} = {q['pfad']}"
                    for q in listenquellen.liste())
                _eingabe = st.text_area(
                    tx("Quellen"), value=_vorlage, height=140,
                    placeholder=tx("allgemein = /mnt/listen/allgemein\n"
                                "einkauf = /srv/abteilung/einkauf\n")
                                + listenquellen.MUSTER_RAUM
                                + tx(" = /mnt/heim/")
                                + listenquellen.PLATZHALTER + tx("/Listen"),
                    key="listenquellen_text")
                st.caption(
                    tx("LocaNoto liest das persönliche Laufwerk per Dienstkonto – Nutzer trennt nur LocaNoto, wie beim persönlichen Arbeitsbereich."))
                if st.button(tx("Speichern und einlesen"),
                             use_container_width=True,
                             key="listenquellen_speichern"):
                    _neu = []
                    for _z in (_eingabe or "").splitlines():
                        _z = _z.strip()
                        if not _z or _z.startswith("#"):
                            continue
                        _r, _t, _pf = _z.partition("=")
                        if not _t:
                            st.error(tx(f"'{_z}' hat kein '=' -- erwartet: 'arbeitsbereich = pfad'."))
                            _neu = None
                            break
                        _neu.append({"raum": _r.strip(),
                                     "pfad": _pf.strip()})
                    if _neu is not None:
                        ok, meldung = listenquellen.speichere(_neu)
                        if not ok:
                            st.error(tx(meldung))
                        else:
                            with st.spinner(tx("Lese Listen ein ...")):
                                _k, _f = tabellen.baue_katalog()
                            st.success(tx(f"{meldung} {len(_k['eintraege'])} Blätter."))
                            time.sleep(1)
                            st.rerun()
                if listenquellen.WURZELN:
                    st.caption(tx("Erlaubte Wurzeln (LISTEN_WURZELN): ")
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
                    tx(f'Aus früherer Einrichtung gilt zusätzlich `allgemein = {tabellen.pfad()}`. Zum Ersetzen oben eine Zeile für `allgemein` eintragen.'))

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
                    tx("Liste hochladen"), accept_multiple_files=True,
                    type=[e.lstrip(".") for e in tabellen.ENDUNGEN],
                    key=f"listen_upload_{_nr}")
                if _hoch:
                    _bekannt = [b for b in tabellen.bereiche(_eintraege)
                                if b != "(Basis)"]
                    _bwahl = st.selectbox(
                        tx("Hochladen in"),
                        ["(Basis)"] + _bekannt + ["+ neues anlegen"],
                        key="listen_upload_bereich", format_func=sprache.uebersetzt())
                    if _bwahl == "+ neues anlegen":
                        _bneu = st.text_input(
                            tx("Name des neuen Bereichs"),
                            key=_feldschluessel("listen_neu", "bereich"))
                        _ziel_bereich = _bneu.strip()
                    else:
                        _ziel_bereich = "" if _bwahl == "(Basis)" else _bwahl

                    if st.button(tx(f'{len(_hoch)} Datei(en) hochladen'),
                                 use_container_width=True):
                        _abgelegt, _misslungen = [], []
                        for _f in _hoch:
                            ok, meldung = tabellen.lege_ab(
                                _f.getvalue(), _f.name, _ziel_bereich)
                            (_abgelegt if ok else _misslungen).append(meldung)
                        with st.spinner(tx("Lese Listen ein ...")):
                            neu, fehler = tabellen.baue_katalog()
                        if _abgelegt:
                            st.success(tx("Abgelegt: ") + ", ".join(_abgelegt))
                        for m in _misslungen:
                            st.error(tx(m))
                        if _abgelegt:
                            st.session_state["listen_upload_nr"] = _nr + 1
                            _felder_leeren("listen_neu", "bereich")
                            time.sleep(1)
                            st.rerun()
            else:
                st.caption(tx("Ordner ist nicht beschreibbar – Dateien dort pflegen, wo sie liegen."))

            if st.button(tx("Listen neu einlesen"), use_container_width=True,
                         help=tx("Liest den Ordner komplett neu ein – für geänderte Zeilen nicht nötig.")):
                with st.spinner(tx("Lese Listen ein ...")):
                    neu, fehler = tabellen.baue_katalog()
                st.success(tx(f"{len(neu['eintraege'])} Blätter eingelesen")
                           + (tx(f", {len(fehler)} nicht lesbar") if fehler else ""))
                time.sleep(1)
                st.rerun()

    st.markdown("---")
    st.header(tx("Dokumente"))

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
        tx("Dokumente hochladen"), key=f"pdf_upload_{_pdf_nr}",
        type=["pdf", "PDF", "docx", "md", "markdown", "txt",
              "tif", "tiff", "TIF", "TIFF", "jpg", "jpeg", "JPG", "JPEG",
              "png", "PNG"],
        accept_multiple_files=True,
        help=tx("PDF, Word, Markdown, Text oder Scan (TIFF, JPG, PNG). Mehrere Dateien → Arbeitsbereich und Projekt gelten für alle."))
    if hochgeladen:
        if len(hochgeladen) > 1:
            st.caption(tx(f'{len(hochgeladen)} Dateien, werden nacheinander verarbeitet.'))
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
            tx("Arbeitsbereich"), _ziele, index=_ziele.index(_mein),
            format_func=sprache.uebersetzt(raeume.bezeichnung),
            help=tx("Legt fest, wer das Dokument findet."))
        if ziel_raum == _mein:
            st.caption(tx("Nur für dich sichtbar."))
        else:
            _m = (raeume.raum(ziel_raum) or {}).get("mitglieder") or []
            st.caption(tx("Sichtbar für alle.") if "*" in _m
                       else tx(f"Sichtbar für {len(_m)} Mitglieder."))

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
                tx("Projekt (optional)"), value="", key="upload_projekt",
                help=tx("Sortiert in deinem Arbeitsbereich. Vorhandene: ")
                     + (", ".join(_bekannt) if _bekannt else tx("noch keine")))

        # Ein Schalter und keine Selbstverstaendlichkeit: ein
        # Modellaufruf je Bild, bei einem 200-Seiten-Scan also
        # Minuten. Wer das nicht erwartet, haelt die Anwendung fuer
        # haengengeblieben.
        _bilder = st.checkbox(
            tx("Bilder und Scans beschreiben"),
            value=False, key="upload_bilder",
            help=tx("Für Schaubilder und gescannte Seiten ohne lesbaren Text; ein Modellaufruf je Bild."))
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
                    # Gescannte Seiten liest zuerst die Texterkennung;
                    # das Sehmodell bekommt nur die, an denen sie
                    # scheitert. Die Zahl ist deshalb eine Obergrenze.
                    st.caption(
                        tx(f'→ {_a} Abbildung(en), {_a} Modellaufrufe.')
                        + (tx(f' Dazu {_s} gescannte Seite(n); das Sehmodell liest nur, was die Texterkennung nicht schafft (höchstens {_s} Aufrufe).') if _s else ""))
                else:
                    st.caption(tx("→ Keine Abbildungen gefunden."))
            except Exception as _e:
                st.caption(tx(f'Nicht abschätzbar: {_e}'))

        if st.button(tx("Hochladen & einlesen")):
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
            _scan_offen = []
            for _i, _datei in enumerate(hochgeladen, 1):
                # Der Stand VOR der Datei und nicht danach: bei einem
                # grossen Scan steht der Spinner minutenlang, und ohne
                # den Namen daneben weiss niemand, ob es noch laeuft
                # oder an welcher Stelle es haengt.
                _stand.caption(f"{_i} von {len(hochgeladen)}: {_datei.name}")
                _bericht = {}
                with st.spinner(tx(f"Verarbeite '{_datei.name}' ...")):
                    _n, _hinweis = process_uploaded_pdf(
                        _datei, ziel_raum, _projekt, _bilder,
                        benutzer_=st.session_state["username"],
                        ist_verwalter=is_admin(),
                        fortschritt=_bildstand,
                        nach_dem_schreiben=refresh_document_index,
                        bericht=_bericht)
                _ergebnisse.append((_datei.name, _n, _hinweis))
                # Seiten, die die Texterkennung nicht las und das
                # Sehmodell noch nicht versucht hat: die bietet der Knopf
                # darunter an.
                if (_bericht.get("unlesbar")
                        and not _bericht.get("sehmodell")):
                    _scan_offen.append(_datei.name)
            _stand.empty()
            refresh_document_index()

            # Je Datei melden. Ein Stapel hat nicht einen Ausgang,
            # sondern einen je Datei -- von fuenf kann eine ein Scan
            # ohne Textebene sein, und "3 von 5 verarbeitet" allein
            # sagt nicht, WELCHE fehlt.
            _schlecht = [e for e in _ergebnisse if not e[1]]
            for _name, _n, _hinweis in _ergebnisse:
                if _n:
                    st.success(tx(f"'{_name}' in "
                               f"'{raeume.bezeichnung(ziel_raum)}' — "
                               f"{_n} Abschnitte durchsuchbar."))
                else:
                    st.error(tx(f"'{_name}' wurde NICHT durchsuchbar."))
                if _hinweis:
                    st.warning(f"{_name}: {_hinweis}")

            if _scan_offen:
                st.session_state["_scan_offen"] = {
                    "namen": _scan_offen, "raum": ziel_raum,
                    "projekt": _projekt}
            else:
                st.session_state.pop("_scan_offen", None)
            if _schlecht or _scan_offen:
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
                if _schlecht and not _scan_offen:
                    st.caption(tx(f'{len(_schlecht)} von {len(_ergebnisse)} liegen in der Ablage, aber nicht in der Suche. Ursache beheben und neu hochladen.'))
            else:
                st.session_state["pdf_upload_nr"] = _pdf_nr + 1
                time.sleep(1)
                st.rerun()

        # --- ZWEITER DURCHGANG: DAS SEHMODELL ---
        #
        # Fuer die Seiten, an denen die Texterkennung gescheitert ist.
        # Ein eigener Knopf und keine Selbstverstaendlichkeit: ein
        # Modellaufruf je Seite, und wo das Modell nichts erkennt,
        # schreibt es einen plausiblen Wert hin, der nicht dasteht. Die
        # Fundstellen sind deshalb als "vom Sehmodell gelesen" markiert.
        _offen_s = st.session_state.get("_scan_offen") or {}
        _zu_lesen = [d for d in hochgeladen
                     if d.name in (_offen_s.get("namen") or [])]
        if _zu_lesen:
            st.info(tx(f'{len(_zu_lesen)} Datei(en): gescannte Seiten nicht lesbar.'))
            if st.button(tx(f'Mit Sehmodell lesen ({len(_zu_lesen)})'),
                         use_container_width=True,
                         help=tx("Ein Modellaufruf je Seite; Fundstellen werden als 'vom Sehmodell gelesen' markiert.")):
                _sm_melder = st.empty()
                _alle_gut = True
                for _datei in _zu_lesen:
                    _bericht = {}
                    with st.spinner(tx(f"Sehmodell liest '{_datei.name}' ...")):
                        _n, _hinweis = process_uploaded_pdf(
                            _datei, _offen_s["raum"],
                            _offen_s.get("projekt", ""), False,
                            benutzer_=st.session_state["username"],
                            ist_verwalter=is_admin(),
                            fortschritt=lambda nr, ges: _sm_melder.caption(
                                f"Sehmodell ... Seite {nr}/{ges}"),
                            nach_dem_schreiben=refresh_document_index,
                            sehmodell=True, bericht=_bericht)
                    if _bericht.get("unlesbar") or not _n:
                        _alle_gut = False
                        st.warning(f"{_datei.name}: {_hinweis}")
                    else:
                        st.success(tx(f"'{_datei.name}' — {_n} Abschnitte "
                                   f"durchsuchbar."))
                _sm_melder.empty()
                st.session_state.pop("_scan_offen", None)
                refresh_document_index()
                if _alle_gut:
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
        with st.expander(tx("Nachtragen und neu einlesen")):
            for _name, (_skript, _log, _titel) in hintergrund.LAEUFE.items():
                _aktiv = hintergrund.laeuft(_name)
                if _aktiv:
                    st.caption(tx(f'**{_titel}** läuft.'))
                    st.code(hintergrund.protokoll(_name, 8) or "(noch keine "
                            "Ausgabe)", language="text")
                    if st.button(tx("Abbrechen"), key=f"stop_{_name}",
                                 use_container_width=True):
                        hintergrund.abbrechen(_name)
                        st.rerun()
                else:
                    if st.button(tx(_titel), key=f"start_{_name}",
                                 use_container_width=True,
                                 help=tx(f'Startet {_skript} im Hintergrund; Verarbeitetes wird übersprungen.')):
                        ok, meldung = hintergrund.starte(_name)
                        if ok:
                            st.success(tx(meldung))
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(tx(meldung))
                    _letzte = hintergrund.protokoll(_name, 3)
                    if _letzte:
                        st.caption(tx("Zuletzt:"))
                        st.code(_letzte, language="text")
                st.markdown("---")
            st.caption(tx("Anzeige aktualisiert sich beim nächsten Klick."))

    # --- DOKUMENTE JE RAUM ---
    #
    # Vorher standen hier zwei Listen, "gemeinsamer Pool" und "deine
    # privaten Dokumente", und dazu ein Admin-Bereich fuer die privaten
    # Dokumente anderer. Das waren drei Sonderfaelle eines einzigen
    # Gedankens: in welchem Raum liegt das Dokument.
    st.subheader(tx("Gespeicherte Dokumente"))
    _raum_liste = [r for r, _s in meine_sammlungen()]
    if not _raum_liste:
        st.caption(tx("Noch keine Dokumente."))
    for _r in _raum_liste:
        _dateien = dateien_je_raum.get(_r, [])
        with st.expander(f"{raeume.bezeichnung(_r)} ({len(_dateien)})",
                         expanded=(len(_raum_liste) == 1)):
            if not _dateien:
                st.caption(tx("Leer."))
                continue
            for f in _dateien:
                # Das Projekt dazu, wo es eines gibt. Es steht in den
                # Metadaten und im Ordner -- bisher nur nicht auf dem
                # Bildschirm, und damit war es fuer den Nutzer nicht
                # vorhanden. Die Zuordnung liegt fuer den eigenen Raum
                # schon vor; der Filter oben hat sie berechnet.
                _pj = _projekt_von.get(f, "") if _r == _mein_raum_f else ""
                st.caption(tx(f"📄 {f}" + (f"  ·  {_pj}" if _pj else "")))

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
                st.caption(tx("Nur lesen."))
                continue

            st.markdown("---")
            _datei = st.selectbox(tx("Dokument verwalten:"), _dateien,
                                  key=f"verw_{_r}", format_func=sprache.uebersetzt())
            _spalte1, _spalte2 = st.columns(2)
            with _spalte1:
                _andere = [x for x in raeume.schreibbar(
                    st.session_state["username"], is_admin(),
                    tuple(mein_notzugang())) if x != _r]
                _nach = st.selectbox(tx("verschieben nach:"),
                                     ["-"] + _andere,
                                     format_func=sprache.uebersetzt(lambda x: (
                                         "-" if x == "-"
                                         else raeume.bezeichnung(x))),
                                     key=f"nach_{_r}")
                if st.button(tx("Verschieben"), key=f"vsch_{_r}",
                             disabled=(_nach == "-"),
                             use_container_width=True):
                    ok, meldung = verschiebe_dokument(_datei, _r, _nach)
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()
            with _spalte2:
                if st.button(tx("Löschen"), key=f"del_{_r}",
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
            st.caption(tx("👑 **Admin: Dokumente in fremden Arbeitsbereichen**"))
            st.caption(tx("Nur zur Admin-Bereich – deine Suche übergeht diese Dokumente."))
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
                tx("Arbeitsbereich"), sorted(_je_raum),
                format_func=sprache.uebersetzt(lambda r: (f"{raeume.bezeichnung(r)} "
                                       f"({len(_je_raum[r])})")),
                key="fremd_raum")
            _name_f = st.selectbox(
                tx("Eintrag"), sorted(_je_raum[_wahl_r]),
                format_func=sprache.uebersetzt(lambda k: k[:16] + "..."), key="fremd_datei")
            st.caption(
                tx("Kennungen statt Namen. Inhalt nur über den Notzugang."))
            # Kein Zusammensetzen und Wiederzerlegen einer Beschriftung:
            # ein Dateiname mit " / " darin zerbrach das vorher, und
            # zwar still -- geloescht wurde dann etwas anderes oder
            # nichts.
            _raum_f = _wahl_r
            if st.button(tx("Endgültig löschen"), use_container_width=True):
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
            st.caption(tx("👑 **Admin: fremde persönliche Arbeitsbereiche**"))
            st.caption(tx("Ohne Dateinamen (`PRIVAT_STRENG` ist an). Nur als Ganzes löschbar."))
            _zahlen = dict(_stille)
            _wahl_s = st.selectbox(
                tx("Arbeitsbereich"), [r for r, _n in _stille],
                format_func=sprache.uebersetzt(lambda r: (raeume.bezeichnung(r) + " – "
                                       + format(_zahlen[r], ",")
                                       + " Abschnitte")),
                key="streng_wahl")
            _ok_s = _loeschfreigabe(_wahl_s, _zahlen[_wahl_s], "streng")
            if st.button(tx("Arbeitsbereich leeren"),
                         use_container_width=True, disabled=not _ok_s):
                ok, meldung = store.loesche(raeume.sammlung(_wahl_s))
                keyword_index.delete_document_by_raum(_wahl_s)
                (st.success if ok else st.error)(meldung)
                # Auch der ownCloud-Ordner -- sonst holte der Abgleich den
                # Inhalt zurueck. Ohne Dateinamen in der Meldung, wie
                # ueberall im strengen Betrieb.
                _n_oc, _f_oc = owncloud.leere_raumordner(_wahl_s)
                if _f_oc:
                    st.warning(tx(f'{len(_f_oc)} Einträge in ownCloud nicht gelöscht – der nächste Abgleich holt sie zurück.'))
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
    st.header(tx("Einstellungen"))
    _modelle = llm.chat_modelle()
    _vorgabe = (_p["chat_modell"] if _p["chat_modell"] in _modelle
                else _modelle[0])
    if _p["chat_modell"] and _p["chat_modell"] not in _modelle:
        st.caption(tx(f"Modell `{_p['chat_modell']}` ist nicht freigegeben "
                      f"→ `{_modelle[0]}` wird benutzt."))
    # Nur eine Auswahl, wenn es etwas zu waehlen gibt. Frei eintippen
    # laesst sich kein Modell mehr: ein Tippfehler waere erst bei der
    # naechsten Frage ein Fehler.
    chat_model = (st.selectbox(tx("Modell"), _modelle,
                               index=_modelle.index(_vorgabe),
                               key=f"chatmodell_{aktives_preset}", format_func=sprache.uebersetzt())
                  if len(_modelle) > 1 else _modelle[0])
    embed_model = llm.modell("EMBEDDING")
    with st.expander(tx("Modell-Endpunkte")):
        # beschreibung() statt rerank_info: der Schnappschuss vom Start
        # wuerde "Endpunkt" zeigen, wenn der laengst ausgefallen ist -- oder
        # "Modell aus dem Image", wenn der Endpunkt laengst wieder da ist.
        _rangfolge = (reranker.beschreibung()
                      if hasattr(reranker, "beschreibung") else rerank_info)
        st.code(llm.uebersicht() + "\nRANGFOLGE   " + _rangfolge,
                language="text")
        if getattr(reranker, "endpunkt_erreichbar", lambda: True)() is False:
            st.warning(tx("Rerank-Endpunkt antwortet nicht – Rangfolge vorerst aus der Fusion, neuer Versuch automatisch."))

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
    with st.expander(tx("Passwort ändern")):
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
            _alt = st.text_input(tx("Bisheriges Passwort"), type="password",
                                 key=_feldschluessel(_pwe, "alt"))
            _neu1 = st.text_input(
                tx(f'Neues Passwort (mind. {benutzer.MIN_PASSWORT} Zeichen)'),
                type="password", key=_feldschluessel(_pwe, "neu1"))
            _neu2 = st.text_input(tx("Wiederholen"), type="password",
                                  key=_feldschluessel(_pwe, "neu2"))
            _pw_ab = st.form_submit_button(
                tx("Ändern"), use_container_width=True, disabled=_antwortet)
        if _pw_ab:
            _ich = st.session_state["username"]
            if not (_alt and _neu1):
                st.error(tx("Bisheriges und neues Passwort eintragen."))
            elif _neu1 != _neu2:
                st.error(tx("Eingaben stimmen nicht überein."))
            elif _neu1 == _alt:
                st.error(tx("Neues Passwort ist gleich dem bisherigen."))
            elif not benutzer.pruefe(_ich, _alt):
                # Geprueft und nicht geglaubt: sonst genuegt ein
                # unbeaufsichtigter Bildschirm, um jemanden dauerhaft
                # auszusperren -- und im Protokoll stuende dabei sein
                # eigener Name.
                st.error(tx("Bisheriges Passwort ist falsch."))
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
                        with st.spinner(tx("Richte Ablage ein ...")):
                            _bo = owncloud.richte_nutzer_ein(_ich, _neu1,
                                                             _ich)
                        if any("gab es schon" in _t for _t
                               in _bo.get("schritte") or []):
                            # Das Konto bestand: mitgeaendert wird es nur,
                            # wenn LocaNoto es verwaltet.
                            _ok_p, _m_p = owncloud.passwort_setzen(_ich,
                                                                   _neu1)
                            if _m_p:
                                (st.info if _ok_p else st.warning)(_m_p)
                    _felder_leeren(_pwe, "alt", "neu1", "neu2")
                    time.sleep(3 if _bo.get("fehler") else 2)
                    st.rerun()

    # --- MEINE ANWEISUNG ---
    #
    # Fuer jeden, nicht nur fuer Verwalter. Die Vorlagen selbst bleiben
    # beim Verwalter -- sie wirken auf alle Antworten. Die Anweisung hier
    # wirkt nur auf die eigenen und haengt an der Vorlage an, statt sie zu
    # ersetzen.
    with st.expander(tx("Meine Anweisung")):
        st.caption(
            tx("Wie LocaNoto dir antworten soll, z. B. „Antworte knapp, mit Tabellen.“ Gilt für alle deine Antworten, auch per Schnittstelle."))
        _anw = "anweisung"
        with st.form(f"anweisung_{_feldschluessel(_anw, 'runde')}"):
            _anw_text = st.text_area(
                tx("Anweisung"), value=prompts.anweisung(
                    st.session_state["username"]),
                max_chars=prompts.ANWEISUNG_MAX, height=140,
                key=_feldschluessel(_anw, "text"),
                label_visibility="collapsed")
            _a1, _a2 = st.columns(2)
            with _a1:
                _anw_ok = st.form_submit_button(
                    tx("Speichern"), use_container_width=True)
            with _a2:
                _anw_weg = st.form_submit_button(
                    tx("Entfernen"), use_container_width=True)
        if _anw_ok or _anw_weg:
            _ok, _m = prompts.anweisung_speichern(
                st.session_state["username"], "" if _anw_weg else _anw_text)
            (st.success if _ok else st.error)(_m)
            if _ok:
                _felder_leeren(_anw, "text")
                time.sleep(1)
                st.rerun()

    # --- MEINE VOREINSTELLUNGEN ---
    #
    # Jeder legt seine eigenen an: Modell, Trefferzahl, Listenbereiche.
    # Prompts gehoeren nicht hinein -- die bleiben bei den Admins, und
    # verfeinert wird mit der eigenen Anweisung darueber.
    with st.expander(tx("Meine Voreinstellungen")):
        _ich_p = st.session_state["username"]
        _eigene_p = presets.eigene(_ich_p)
        for _ep in _eigene_p:
            _ew = presets.lese(_ep)
            _l, _r = st.columns([4, 1])
            _l.markdown(f"**{_md_roh(_ew['bezeichnung'])}**  \n"
                        + _md_roh(f"{_ew['chat_modell'] or llm.modell('CHAT')}"
                                  f" · {_ew['top_k'] or '–'}"))
            if _r.button(tx("Löschen"), key=f"ep_weg_{_ep}"):
                presets.eigene_loeschen(_ep, _ich_p)
                st.rerun()
        with st.form("eigene_voreinstellung", clear_on_submit=True):
            _ep_name = st.text_input(tx("Name"))
            _ep_modell = (st.selectbox(tx("Modell"), llm.chat_modelle(), format_func=sprache.uebersetzt())
                          if len(llm.chat_modelle()) > 1 else "")
            _ep_k = st.number_input(tx("Abschnitte je Frage (0 = Vorgabe)"),
                                    min_value=0, max_value=30, value=0)
            _ep_bereiche = []
            try:
                _ep_alle = tabellen.bereiche(tabellen.sichtbar(
                    tabellen.lies_katalog().get("eintraege", []), _ich_p))
            except Exception:
                _ep_alle = []
            if len(_ep_alle) > 1:
                _ep_bereiche = st.multiselect(tx("Listenbereiche"), _ep_alle,
                                              format_func=sprache.uebersetzt())
            if st.form_submit_button(tx("Speichern"),
                                     use_container_width=True):
                _ok_ep, _m_ep = presets.eigene_speichern(_ich_p, _ep_name, {
                    "chat_modell": _ep_modell, "top_k": int(_ep_k),
                    "listen_bereiche": _ep_bereiche})
                if _ok_ep:
                    st.success(tx("Gespeichert → oben unter Voreinstellung wählbar."))
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(tx(_m_ep))

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
    # IMMER sichtbar, auch ohne eingerichtetes Postfach. Fehlte der
    # Bereich, sah ein Nutzer von der Mailanbindung nichts -- sichtbar
    # war sie nur unter "Verwaltung", und das las sich, als sei sie den
    # Verwaltern vorbehalten.
    _koepfe = st.session_state.setdefault("_postfach_koepfe", {})
    _offen = sum(1 for n in _pf_login if n not in _koepfe)
    with st.expander(
            tx("Meine Postfächer")
            + (tx(f" ({_offen} offen)") if _offen else "")):
        if not _pf_alle:
            st.caption(
                tx("Noch kein Postfach eingerichtet. Ein Admin hinterlegt den Exchange-Server unter Admin-Bereich → Postfächer; dann verbindest du hier dein Postfach."))
        else:
            if not _pf_login:
                st.caption(tx("Alle Postfächer sind ohne eigene Anmeldung erreichbar."))
            for _n in _pf_login:
                _ang = _pf_alle[_n]
                _was = ("dein persönliches Postfach"
                        if _ang.get("persoenlich") else "Funktionspostfach")
                if _n in _koepfe:
                    _s1, _s2 = st.columns([3, 1])
                    with _s1:
                        st.markdown(tx(f"**{_n}** · {_was} · verbunden"))
                    with _s2:
                        if st.button(tx("Trennen"), key=f"pfab_{_n}",
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
                            tx("Token"), type="password",
                            key=_feldschluessel("postfach", f"{_n}_tok"))
                    else:
                        # Exchange will die vollstaendige Mailadresse.
                        # "Benutzer" laedt dort zum Kuerzel ein, und das
                        # scheitert erst beim Verbinden.
                        _ist_ex = _ang.get("transport") == "exchange"
                        _pf_u = st.text_input(
                            tx("Mailadresse") if _ist_ex else tx("Benutzer"),
                            placeholder=(tx("vorname.nachname@firma.de")
                                         if _ist_ex else ""),
                            key=_feldschluessel("postfach", f"{_n}_ben"))
                        _pf_g = st.text_input(
                            tx("Passwort"), type="password",
                            key=_feldschluessel("postfach", f"{_n}_pw"))
                    _pf_ok = st.form_submit_button(
                        tx("Verbinden"), use_container_width=True,
                        disabled=_antwortet)
                if _pf_ok:
                    if not _pf_g:
                        st.error(tx("Bitte Anmeldedaten eintragen."))
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
                            st.success(tx(f"Verbunden. {len(_w)} Werkzeuge."))
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(tx(f"Nicht verbunden: "
                                     f"{type(e).__name__}: {e}"))
                        finally:
                            for _v in _probe.values():
                                try:
                                    _v.schliesse()
                                except Exception:
                                    pass

            st.caption(tx("Anmeldedaten gelten nur für diese Sitzung."))

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
        with st.expander(tx(f'Meine Zugangstoken ({len(_meine_token)})')):
            st.caption(
                tx("Ein Token gilt für die HTTP-Schnittstelle mit deinen Rechten und wird nur einmal angezeigt. Nicht mehr Benötigtes widerrufen."))
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
                    st.caption(tx(f"angelegt {_e.get('erstellt', '?')[:19]}"))
                with _t2:
                    if st.button("🗑️", key=f"eig_token_{_h[:12]}",
                                 help=tx("Widerrufen")):
                        # Der volle Hashwert und nicht sein Anfang:
                        # auth.widerrufe trifft bei einem mehrdeutigen
                        # Anfang absichtlich keinen.
                        if auth.widerrufe(_h) == 1:
                            st.info(tx("Widerrufen."))
                        else:
                            st.error(tx("Nicht widerrufen."))
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
    top_k = st.slider(tx("Abschnitte abrufen"), min_value=1, max_value=30,
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
        tx("LocaNoto \u00b7 "
        "[AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) \u00b7 "
        "[Quelltext](https://github.com/mw-research/LocaNoto)"))

# --- QUELLEN IM NETZ SUCHEN ---
#
# Wie bei NotebookLM: ein Thema, eine Trefferliste, anhaken,
# uebernehmen -- ohne dass eine Antwort entsteht. Hier braucht es
# keine Freigabe am Raum: den Suchbegriff tippt der Nutzer selbst,
# das Modell formuliert nichts aus den Abschnitten eines Raums.
# Uebernommen wird immer in den eigenen Raum. Vor dem Chat und
# unabhaengig vom Bestand: gerade wer noch nichts hat, sammelt.
if _web_server:
    with st.expander(tx("Quellen im Netz")):
        with st.form("quellen_suche"):
            _qs_anfrage = st.text_input(
                tx("Thema"), placeholder=tx("Stichworte, z. B. DIN EN 1090 "
                                     "Ausführungsklassen"),
                help=tx("Geht an Suchmaschinen – nur Stichworte, keine internen Namen oder Zahlen."))
            _qs_los = st.form_submit_button(tx("Suchen"),
                                            disabled=_antwortet)
        if _qs_los and (_qs_anfrage or "").strip():
            _qs_vb = mcp.verbinde(ohne=set(mcp.lies_konfiguration())
                                  - _web_server)
            try:
                with st.spinner(tx("Suche ...")):
                    _qs_text = next(iter(_qs_vb.values())).rufe(
                        "web_suchen", {"anfrage": _qs_anfrage,
                                       "anzahl": 10, "lesen": 0})
                st.session_state["_quellen"] = \
                    pipeline.webtreffer_aus_text(_qs_text)
            except Exception as e:
                st.error(tx(f"Suche nicht möglich: {type(e).__name__}: {e}"))
            finally:
                for _v in _qs_vb.values():
                    try:
                        _v.schliesse()
                    except Exception:
                        pass
        _qs = st.session_state.get("_quellen") or []
        if _qs:
            _qs_wahl = []
            for _qk, _q in enumerate(_qs):
                if st.checkbox(f"**{_md_roh(_q['titel'])}**",
                               key=f"qs_{_q['adresse']}"):
                    _qs_wahl.append(_q)
                st.caption(tx(_md_roh(_q["adresse"]) + "  \n"
                           + _md_roh(_q["text"][:300])))
                _web_vorschau(_q, f"qs_{_qk}")
                st.divider()
            st.caption(tx("Landet in deinem persönlichen Arbeitsbereich, Ordner Suchergebnisse. Von dort in geteilte Arbeitsbereiche verschieben."))
            if _qs_wahl and st.button(
                    tx(f'{len(_qs_wahl)} übernehmen'),
                    key="qs_ueb", disabled=_antwortet):
                _web_uebernehmen(_qs_wahl)

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
                st.write(_ohne_fremdbilder(_quellen_klickbar(
                    msg["content"], msg.get("sources"), i)))
            else:
                st.write(msg["content"])
            if msg.get("unvollstaendig"):
                # Ein Zwischenstand, dessen Strom abgebrochen ist. Ohne
                # diesen Hinweis saehe ein mitten im Satz endender Text
                # wie eine fertige Antwort aus -- und das waere
                # schlimmer als der Verlust, weil es niemand bemerkt.
                st.caption(tx("⚠️ Abgebrochen – Antwort unvollständig. Frage erneut stellen."))
            
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
                    st.caption(tx("Danke -- vermerkt."))
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
                    st.success(tx(f"Gesendet: {_entw['werkzeug']}"))
                    continue
                with st.expander(
                        tx(f"Entwurf: {_entw['werkzeug']} ({_entw['server']}) — wartet auf dich"),
                        expanded=True):
                    for _k, _w in (_entw.get("argumente") or {}).items():
                        st.markdown(f"**{_k}**")
                        st.code(str(_w), language="text")
                    _s1, _s2 = st.columns(2)
                    with _s1:
                        if st.button(tx("Senden"), key=f"snd_{_eschl}",
                                     use_container_width=True):
                            _vb = mcp.verbinde(
                                st.session_state.get("_postfach_koepfe"))
                            try:
                                _erg = _vb[_entw["server"]].rufe(
                                    _entw["werkzeug"], _entw["argumente"])
                                st.session_state.setdefault(
                                    "_gesendet", set()).add(_eschl)
                                st.success(tx(str(_erg)[:300]))
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
                        if st.button(tx("Verwerfen"), key=f"vrw_{_eschl}",
                                     use_container_width=True):
                            st.session_state.setdefault(
                                "_gesendet", set()).add(_eschl)
                            st.rerun()

            # --- QUELLEN DAUERHAFT ANZEIGEN ---
            if "sources" in msg and msg["sources"]:
                st.markdown("---")
                st.markdown(tx("📚 **Quellen:**"))
                
                # All sources start closed. The first one used to open
                # under every answer: with long passages the page grew
                # after each answer and jumped to its end, wherever one
                # had scrolled to. A citation in the text still jumps to
                # its anchor (see _quellen_klickbar); one click opens it.
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
                    # Aus einem Scan gelesen? Dann steht es dabei --
                    # Zahlen darin koennen falsch erkannt sein.
                    _herk = {"ocr": " · aus Texterkennung",
                             "sehmodell": " · vom Sehmodell gelesen"}.get(
                        source.get("herkunft"), "")
                    with st.expander(tx(f'{file_n} (Seite {page_n}){_herk}'),
                                     expanded=False):
                        for t in source["texts"]:
                            st.info(tx(t))
                        
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
                            
                            if st.checkbox(tx(f'Originalseite {page_n} als Bild'), key=chk_key):
                                try:
                                    src_doc = pymupdf.open(pdf_path)
                                    src_page = src_doc.load_page(page_n - 1)
                                    pix = src_page.get_pixmap(dpi=150)
                                    st.image(pix.tobytes(), caption=f"Originalansicht: {file_n} - Seite {page_n}")
                                    src_doc.close()
                                except Exception as e:
                                    st.error(tx(f'PDF nicht darstellbar: {e}'))

            # --- AUS DEM NETZ ---
            #
            # Getrennt von den Dokumenten und mit Haekchen: was bleiben
            # soll, wird ein Dokument im EIGENEN Raum -- im Ordner
            # Suchergebnisse, mit Quelle und Abrufdatum. In einen
            # geteilten Raum nur durch Verschieben.
            if msg.get("web"):
                st.markdown(tx("🌐 **Aus dem Netz:**"))
                _web_wahl = []
                for _wk, _w in enumerate(msg["web"]):
                    with st.expander(f"🌐 [{_w['nr']}] "
                                     f"{_md_roh(_w['titel'])}"):
                        st.caption(tx(_md_roh(_w["adresse"])))
                        st.text(_w["text"][:600])
                        _web_vorschau(_w, f"{i}_{_wk}")
                    if st.checkbox(tx(f"[{_w['nr']}] übernehmen"),
                                   key=f"web_{i}_{_wk}"):
                        _web_wahl.append(_w)
                if _web_wahl and st.button(
                        tx(f'{len(_web_wahl)} übernehmen'),
                        key=f"webueb_{i}", disabled=_antwortet):
                    _web_uebernehmen(_web_wahl)

    eingabe = st.chat_input(
        tx("Frage an die Datenbank (Bilder möglich) ..."),
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
                st.warning(tx(f"Bild '{datei.name}' nicht lesbar: {e}"))
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
            with st.spinner(tx(f"Lese Bild {n + 1} von {len(bild_pfade)} ...")):
                try:
                    with open(pfad, "rb") as _f:
                        bild_texte.append(vision.beschreibe(_f.read(),
                                                            user_query))
                except Exception as e:
                    st.warning(tx(f"Bild '{anzeige}' nicht lesbar: {e}"))

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
            _titel = make_chat_title(user_query, chat_model)

        save_chat(st.session_state.current_chat_id,
                  st.session_state.messages, _titel)
        
        with st.chat_message("user"):
            st.write(user_query)

        with st.chat_message("assistant"):
            try:
                # --- 1. SUCHSONDEN ---
                verlauf = pipeline.verlaufstext(st.session_state.messages)
                with st.spinner(tx("Frage wird analysiert...")):
                    search_queries, sonden_hinweis = pipeline.sonden(
                        chat_client, chat_model, user_query,
                        verlauf=verlauf, bild_texte=bild_texte,
                        preset=aktives_preset)

                if sonden_hinweis:
                    st.caption(tx(f'🧠 *Standardsuche – Sonden fehlgeschlagen: {sonden_hinweis}*'))
                else:
                    st.caption(tx("🧠 *Suchsonden:* \n- `")
                               + "`\n- `".join(search_queries) + "`")

                # --- 2. HYBRIDE SUCHE UND RANGFOLGE ---
                with st.spinner(tx("Suche läuft...")):
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
                        st.warning(tx(str(e)))
                        st.stop()
                    except ValueError as e:
                        st.error(tx(str(e)))
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
                        tx("**Die Vektorsuche hat für ")
                        + ", ".join(f"`{_r}`" for _r
                                    in sorted(zahlen["vektorausfall"]))
                        + tx(" nicht geantwortet.** Antwort nur aus der Stichwortsuche, daher ungenauer. Grund: ")
                        + "; ".join(sorted(
                            set(zahlen["vektorausfall"].values()))))

                if treffer:
                    verfahren = ("Reranker" if reranker is not None
                                 else "Rangfolge-Fusion")
                    st.caption(tx(f"🎯 *{verfahren}: {zahlen['kandidaten']} Treffer aus {zahlen['ranglisten']} Ranglisten → die besten {len(treffer)}.*"))

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
                    with st.spinner(tx("Frage Datenbank ab...")):
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
                        with st.expander(tx("Datenbankabfrage")):
                            st.code(abfrage, language="sql")
                            st.caption(
                                tx(f"Konto: "
                                f"{(_sqz or {}).get('benutzer') or 'Vorgabe'}"))
                    elif sql_grund:
                        st.caption(tx("\U0001f5c4\ufe0f *" + sql_grund + "*"))

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
                        with st.spinner(tx("Suche in Listen ...")):
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
                                st.caption(tx("\U0001f4ca *" + quelle + ": "
                                           + _t["grund"] + "*"))
                                continue
                            if not _t["zeilen"]:
                                # Kein Treffer ist eine Auskunft, aber
                                # keine, die in den Kontext gehoert: eine
                                # leere Tabelle im Prompt liest sich fuer
                                # das Modell wie ein Beleg fuer "gibt es
                                # nicht".
                                st.caption("\U0001f4ca *" + quelle
                                           + tx(": keine passende Zeile.*"))
                                continue
                            _mit += 1
                            _tab = sqlpruefung.als_tabelle(_t["spalten"],
                                                           _t["zeilen"])
                            bloecke += [
                                ("liste_abfrage",
                                 quelle + chr(10) + _t["sql"]),
                                ("liste_ergebnis", _tab)]
                            with st.expander(
                                    tx(f"Liste: {quelle} ({len(_t['zeilen'])} Zeilen)")
                                    + ("" if _t.get("gewaehlt")
                                       else tx(" — zusätzlich gefunden"))):
                                st.code(_t["sql"], language="sql")
                                st.markdown(_tab)
                        if not _mit and _grund:
                            st.caption(tx("\U0001f4ca *Listen nicht verwendet: ")
                                       + _grund + "*")

                # --- 3. KONTEXT FÜR DAS LLM ---
                dynamic_context = pipeline.kontext(treffer, bild_texte,
                                                   bloecke=bloecke)

                with st.expander(tx("Debug: Was sieht das LLM?")):
                    st.write(tx(f'**Suchsonden:** {search_queries}'))
                    if treffer:
                        for rang, eintrag in enumerate(treffer, 1):
                            meta = eintrag["meta"]
                            st.markdown(
                                tx(f"**Rang {rang}** | \U0001f4c4 "
                                f"`{meta.get('file_name', '?')}` | "
                                f"\U0001f3af Sonde: *{meta.get('found_by_query', '?')}*"))
                            st.caption(f"{eintrag['text'][:250]}...")
                    else:
                        st.write(tx("Keine Abschnitte gefunden."))

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
                _system = pipeline.systemprompt(
                    dynamic_context, aktives_preset,
                    benutzer=st.session_state["username"])
                _zusatz, _entwuerfe = [], []
                if mcp.eingerichtet():
                    _wmelder = st.empty()
                    _verb = mcp.verbinde(
                        st.session_state.get("_postfach_koepfe"),
                        ohne=(() if _web_frei else _web_server))
                    try:
                        _zusatz, _entwuerfe = pipeline.werkzeuglauf(
                            chat_client, chat_model, _system,
                            st.session_state.messages, _verb,
                            fortschritt=lambda t: _wmelder.caption(
                                "\U0001f527 " + str(t)))
                    except Exception as e:
                        # Ein Postfach, das klemmt, darf die Frage nach
                        # einem Dokument nicht mitnehmen.
                        st.warning(tx(f"Werkzeuge nicht verfügbar: "
                                   f"{type(e).__name__}: {e}"))
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
                    # Was die Websuche gefunden hat -- getrennt von den
                    # Dokumenten, und zum Uebernehmen in einen Raum.
                    "web": pipeline.webtreffer(_zusatz, _web_server),
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
                st.error(tx(f"Fehler bei der Verarbeitung: {e}"))

else:
    st.info(tx("Datenbank ist leer – PDFs per Hintergrund-Skript einlesen."))