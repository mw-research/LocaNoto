"""Oberflaechensprache: Deutsch oder Englisch, je Nutzer.

    t("Gespeichert.")                 -> "Saved." bei Englisch
    t(f"{n} Dateien geholt")          -> "3 files fetched" (ueber ein Muster)

DER DEUTSCHE TEXT IST DER SCHLUESSEL. Der Code bleibt so lesbar, wie er
war, Deutsch braucht keine Tabelle, und ein Text ohne Uebersetzung
erscheint auf Deutsch statt als leere Stelle oder Fehler. Die englischen
Texte stehen in sprache_en.json:

    {"texte":  {"Gespeichert.": "Saved."},
     "muster": {"{} Dateien geholt": "{} files fetched"}}

"muster" sind Texte mit eingesetzten Werten (f-Strings). Jedes {} steht
fuer einen Wert; die englische Fassung setzt sie in derselben
Reihenfolge ein, oder mit {0}, {1} ... in einer anderen. Ein Muster
braucht festen Text neben den Platzhaltern -- eines nur aus {} passte
auf alles.

WELCHE SPRACHE GILT, haelt dieser Faden. Streamlit fuehrt jede Sitzung
in einem eigenen Faden aus, und die Schnittstelle jede Anfrage: setze()
am Anfang eines Laufs genuegt, und niemand reicht die Sprache durch.
Gespeichert wird die Wahl je Nutzer in config/sprachen.json -- keine
Berechtigung, nur eine Vorliebe, deshalb ohne Signatur.

Was noch nicht uebersetzt ist: python uebersetzen.py --fehlend
"""
import json
import os
import re
import threading
from functools import lru_cache

import dateisperre
import paths
import statefiles

SPRACHEN = {"de": "Deutsch", "en": "English"}
VORGABE = (os.getenv("LOCANOTO_SPRACHE", "de").strip().lower() or "de")
if VORGABE not in SPRACHEN:
    VORGABE = "de"

TABELLE = os.path.join(paths.BASE_DIR, "sprache_en.json")
WAHL = os.path.join(paths.CONFIG_DIR, "sprachen.json")

_jetzt = threading.local()


# --- WELCHE SPRACHE ---

def setze(code):
    """Die Sprache dieses Fadens. Unbekanntes wird die Vorgabe."""
    _jetzt.code = code if code in SPRACHEN else VORGABE


def aktuell():
    return getattr(_jetzt, "code", VORGABE)


def gewaehlt(benutzer):
    """Die gespeicherte Sprache eines Nutzers, sonst die Vorgabe."""
    try:
        with statefiles.open(WAHL, encoding="utf-8") as f:
            code = (json.load(f) or {}).get(str(benutzer or "").lower())
    except (OSError, ValueError):
        code = None
    return code if code in SPRACHEN else VORGABE


def speichere(benutzer, code):
    """Merkt sich die Sprache eines Nutzers. (ok, meldung)."""
    if code not in SPRACHEN:
        return False, f"Unbekannte Sprache: {code}"
    benutzer = str(benutzer or "").lower()
    if not benutzer:
        return False, "Kein Nutzer."
    with dateisperre.gesperrt(WAHL):
        try:
            with statefiles.open(WAHL, encoding="utf-8") as f:
                daten = json.load(f) or {}
        except (OSError, ValueError):
            daten = {}
        daten[benutzer] = code
        dateisperre.schreibe_atomar(WAHL, json.dumps(daten, indent=1))
    return True, ""


# --- UEBERSETZEN ---

@lru_cache(maxsize=1)
def _tabelle():
    try:
        with statefiles.open(TABELLE, encoding="utf-8") as f:
            daten = json.load(f) or {}
    except (OSError, ValueError):
        daten = {}
    texte = dict(daten.get("texte") or {})
    muster = []
    for de, en in (daten.get("muster") or {}).items():
        if not re.sub(r"\{\}", "", de).strip():
            continue  # nur Platzhalter -- passte auf jeden Text
        teile = de.split("{}")
        regel = re.compile("^" + "(.*?)".join(re.escape(x) for x in teile)
                           + "$", re.S)
        muster.append((len(teile[0]) + len(teile[-1]), regel, en))
    # Das Muster mit dem meisten festen Text zuerst: "Raum {} geloescht"
    # schlaegt "{} geloescht".
    muster.sort(key=lambda m: -m[0])
    return texte, muster


def _einsetzen(en, werte):
    if re.search(r"\{\d+\}", en):
        return re.sub(r"\{(\d+)\}",
                      lambda m: werte[int(m.group(1))]
                      if int(m.group(1)) < len(werte) else m.group(0), en)
    teile = en.split("{}")
    aus = teile[0]
    for i, rest in enumerate(teile[1:]):
        aus += (werte[i] if i < len(werte) else "") + rest
    return aus


@lru_cache(maxsize=8192)
def _englisch(text):
    texte, muster = _tabelle()
    if text in texte:
        return texte[text]
    for _laenge, regel, en in muster:
        m = regel.match(text)
        if m:
            # Eingesetzte Werte koennen selbst Meldungen sein.
            return _einsetzen(en, [_englisch(w) for w in m.groups()])
    return text


def t(text):
    """Der Text in der Sprache dieses Fadens."""
    if aktuell() == "de" or not isinstance(text, str) or not text:
        return text
    return _englisch(text)


def uebersetzt(funktion=None):
    """format_func fuer Auswahlfelder: zeigt uebersetzt, Werte bleiben.

    Die Werte einer Auswahl vergleicht der Code mit deutschen Texten;
    uebersetzt wird deshalb nur, was angezeigt wird.
    """
    if funktion is None:
        return lambda wert: t(str(wert))
    return lambda wert: t(funktion(wert))
