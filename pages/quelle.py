"""Eine Fundstelle allein -- ohne alles drumherum.

Gedacht fuer den Verweis in einer Antwort: ein Klick oeffnet die
Quelle in einem eigenen Tab, damit man sie neben dem Gespraech
liegen lassen kann. Im Hauptfenster bleibt die Frage stehen.

Die Berechtigung kommt aus einem Ticket (quellticket.py) und nicht
aus der Anmeldung: ein neuer Tab ist eine neue Sitzung. Ein Ticket
nennt genau eine Fundstelle und gilt Minuten -- die Anmeldung
mitzugeben hiesse, sie in jede Antwort zu schreiben.

Die Seite taucht in keiner Navigation auf; das schaltet
.streamlit/config.toml ab. Wer die Adresse ohne Ticket aufruft, sieht
nichts als den Hinweis darauf.
"""
import os

import streamlit as st

import paths
import quellticket
import raeume
import store

st.set_page_config(page_title="Quelle", page_icon="\U0001f4c4",
                   layout="centered")

_t = quellticket.loese_ein(st.query_params.get("t", ""))
if not _t:
    st.title("\U0001f4c4 Quelle")
    st.warning(
        "Kein gueltiges Ticket. Diese Seite oeffnet sich ueber den "
        "Verweis unter einer Antwort -- und der gilt nur kurz. "
        "Stelle die Frage noch einmal und klicke den Verweis erneut.")
    st.stop()

st.title("\U0001f4c4 " + _t["datei"])
st.caption(f"Seite {_t['seite']} · Raum "
           f"{raeume.bezeichnung(_t['raum'])}")


# --- DER TEXT, DEN DIE SUCHE GESEHEN HAT ---
#
# Nicht die Datei neu einlesen, sondern zeigen, was im Bestand steht:
# genau das hat die Antwort gestuetzt. Weicht beides voneinander ab --
# weil jemand die Datei inzwischen ersetzt hat --, ist der Unterschied
# selbst die Auskunft.
@st.cache_data(ttl=300, show_spinner=False)
def _abschnitte(raum, datei, seite):
    sml = store.sammlung(raeume.sammlung(raum), anlegen=False)
    if sml is None:
        return []
    try:
        daten = sml.get(where=store.datei_filter(datei),
                        include=["documents", "metadatas"])
    except Exception:
        return []
    texte = store.klartext(raum, daten.get("documents") or [],
                           _t["benutzer"])
    metas = daten.get("metadatas") or []
    aus = []
    for i, m in enumerate(metas):
        if str((m or {}).get("page", "")) != str(seite):
            continue
        if i < len(texte):
            aus.append(texte[i])
    return aus


_texte = _abschnitte(_t["raum"], _t["datei"], _t["seite"])
if _texte:
    for _x in _texte:
        st.info(_x)
else:
    st.caption("Kein Abschnitt zu dieser Seite im Bestand.")

# --- DIE SEITE ALS BILD ---
#
# Nur bei PDFs: bei Word oder Markdown ist "Seite" eine
# Abschnittsnummer, und pymupdf kann die Datei ohnehin nicht oeffnen.
_pfad = ""
for _w, _u, _dateien in os.walk(paths.DOCS_DIR):
    if _t["datei"] in _dateien:
        _kandidat = os.path.join(_w, _t["datei"])
        # Der Raum entscheidet, welche gleichnamige Datei gemeint ist.
        if paths.sicherer_teil(_t["raum"]) in _kandidat.replace("\\", "/") \
                or _t["raum"] == raeume.ALLGEMEIN:
            _pfad = _kandidat
            break

if _pfad and _t["datei"].lower().endswith(".pdf"):
    try:
        import pymupdf
        with pymupdf.open(_pfad) as _doc:
            _nr = int(_t["seite"]) - 1
            if 0 <= _nr < len(_doc):
                _bild = _doc.load_page(_nr).get_pixmap(dpi=150)
                st.image(_bild.tobytes(),
                         caption=f"{_t['datei']} · Seite {_t['seite']}")
    except Exception as _e:
        st.caption(f"Die Seite laesst sich nicht darstellen: {_e}")
