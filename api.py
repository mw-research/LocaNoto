"""HTTP-Schnittstelle zu derselben Suche, die auch die Oberflaeche benutzt.

Gedacht fuer Bedienung ohne Browser: eine Frage aus dem Terminal, ein
Skript, das einen Bestand prueft. Die Antworten kommen aus pipeline.py --
denselben Funktionen wie in der Oberflaeche. Zwei getrennte Umsetzungen
wuerden auf dieselbe Frage verschieden antworten, und der Unterschied
faellt erst auf, wenn ihn jemand sucht.

Zugang ueber ein Token im Kopf der Anfrage:

    curl -H "X-LocaNoto-Token: lnt_..." http://127.0.0.1:8600/status

Das Token bildet auf eine Kennung ab, und diese Kennung geht als benutzer
in die Suche. Die Trennung zwischen privaten und geteilten Dokumenten gilt
damit hier genauso wie in der Oberflaeche -- ohne Sonderbehandlung, ohne
einen Schalter, der sie umgeht.

Betrieb: uvicorn api:app --host 0.0.0.0 --port 8600
"""
import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import paths
import auth
import llm
import pipeline
import feedback
import ranking
import store

paths.bootstrap()

app = FastAPI(
    title="LocaNoto",
    description=__doc__,
    version="1.0",
    # Die Bedienoberflaeche der Schnittstelle bleibt erreichbar: sie ist die
    # knappste Dokumentation, die nicht veralten kann.
    docs_url="/hilfe",
    redoc_url=None,
)

# --- MEHRPROZESSBETRIEB ---
#
# Ohne Chroma-Server greifen Oberflaeche und Schnittstelle auf dieselben
# Dateien zu. Das ist der Fall, fuer den die Dateiablage nicht gebaut ist:
# die Folge waere kein sauberer Fehler, sondern ein beschaedigter Index.
# Deshalb hier ein Abbruch beim Start statt eines stillen Risikos.
#
# CHROMA_EINZELN=1 hebt die Sperre auf -- fuer den Fall, dass die
# Schnittstelle nachweislich allein laeuft.
if not store.im_server_betrieb() and os.getenv("CHROMA_EINZELN", "").strip() != "1":
    raise RuntimeError(
        "Die Schnittstelle braucht einen Chroma-Server (CHROMA_HOST), solange "
        "die Oberflaeche auf denselben Bestand zugreift. Zwei Prozesse auf "
        "derselben Dateiablage beschaedigen den Index. Laeuft die "
        "Schnittstelle nachweislich allein, hebt CHROMA_EINZELN=1 die Sperre "
        "auf.")

chat_client = llm.client("CHAT")
embed_client = llm.client("EMBEDDING")
CHAT_MODELL = llm.modell("CHAT")
EMBED_MODELL = llm.modell("EMBEDDING")

STANDARD_TOP_K = paths.env_int("TOP_K", 5)

# Der Bewerter wird einmal gewaehlt, nicht je Anfrage: die erste Stufe
# spricht zur Pruefung einmal mit dem Endpunkt, und das gehoert nicht in
# den Weg jeder Frage.
_bewerter, BEWERTER_INFO = ranking.lade_bewerter()


def benutzer(x_locanoto_token: str = Header(default="")):
    """Kennung zum Token. Ohne gueltiges Token endet die Anfrage hier.

    401 und nicht 403: der Aufrufer hat sich nicht ausgewiesen. Der Grund
    wird bewusst nicht genauer benannt -- ob ein Token unbekannt oder
    abgelaufen ist, geht den Aufrufer nichts an und hilft nur beim Raten.
    """
    kennung = auth.pruefe(x_locanoto_token)
    if not kennung:
        raise HTTPException(status_code=401, detail="Kein gueltiges Token.",
                            headers={"WWW-Authenticate": "Token"})
    return kennung


class Frage(BaseModel):
    frage: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=0, ge=0, le=30,
                       description="0 = Vorgabe aus TOP_K")
    dateien: list[str] | None = Field(
        default=None, description="nur in diesen Dokumenten suchen")
    sachgebiete: list[str] | None = Field(
        default=None, description="nur in diesen Unterordnern suchen")
    verlauf: list[dict] | None = Field(
        default=None,
        description="frueherer Austausch als [{'role','content'}], "
                    "damit Rueckbezuege aufgeloest werden koennen")
    quellen_texte: bool = Field(
        default=False,
        description="die vollstaendigen Abschnitte mitliefern. Ohne das nur "
                    "Datei und Seite -- ein Tabellenabschnitt ist mehrere "
                    "Kilobyte gross, und im Terminal ueberdeckt er die "
                    "Antwort, um die es ging")


@app.get("/gesundheit")
def gesundheit():
    """Lebenszeichen ohne Token -- fuer den Healthcheck des Containers."""
    return {"status": "ok"}


@app.get("/status")
def status(kennung: str = Depends(benutzer)):
    """Was diese Installation gerade benutzt."""
    sammlung = store.collection()
    geteilt, privat, sachgebiete = pipeline.dokumente(sammlung, kennung)
    return {
        "benutzer": kennung,
        "abschnitte": sammlung.count(),
        "dokumente": {"geteilt": len(geteilt), "privat": len(privat)},
        "sachgebiete": sachgebiete,
        "ablage": store.beschreibung(),
        "rangfolge": BEWERTER_INFO,
        "modelle": {"chat": CHAT_MODELL, "embedding": EMBED_MODELL},
    }


@app.get("/dokumente")
def dokumente(kennung: str = Depends(benutzer)):
    """Welche Dokumente diese Kennung sehen darf."""
    geteilt, privat, sachgebiete = pipeline.dokumente(store.collection(), kennung)
    return {"geteilt": geteilt, "privat": privat, "sachgebiete": sachgebiete}


def _suchen(anfrage, kennung):
    """Gemeinsamer Teil beider Antwortwege."""
    verlauf_text = pipeline.verlaufstext(anfrage.verlauf or [],
                                         ohne_letzte=False)
    sonden, hinweis = pipeline.sonden(chat_client, CHAT_MODELL, anfrage.frage,
                                      verlauf=verlauf_text)
    try:
        treffer, zahlen = pipeline.suche(
            store.collection(), embed_client, EMBED_MODELL, sonden, kennung,
            anfrage.top_k or STANDARD_TOP_K,
            dateien=anfrage.dateien, ordner=anfrage.sachgebiete,
            bewerter=_bewerter)
    except ValueError as e:
        # Der Embedding-Endpunkt antwortet nicht. 503, weil es an einem
        # nachgelagerten Dienst liegt und ein spaeterer Versuch klappen kann.
        raise HTTPException(status_code=503, detail=str(e))

    if not treffer:
        # Auch ueber die Schnittstelle gestellte Fragen gehoeren in die
        # Arbeitsliste -- eine Luecke im Bestand ist keine Frage der
        # Bedienung.
        feedback.notiere("leer", kennung, anfrage.frage, sonden=sonden,
                         zahlen=zahlen, herkunft="schnittstelle")

    nachrichten = list(anfrage.verlauf or []) + [
        {"role": "user", "content": anfrage.frage}]
    system = pipeline.systemprompt(pipeline.kontext(treffer))
    return sonden, hinweis, treffer, zahlen, nachrichten, system


@app.post("/frage")
def frage(anfrage: Frage,
          strom: bool = Query(default=False,
                              description="Antwort stueckweise als "
                                          "text/event-stream"),
          kennung: str = Depends(benutzer)):
    """Beantwortet eine Frage aus den Dokumenten dieser Kennung."""
    sonden, hinweis, treffer, zahlen, nachrichten, system = _suchen(
        anfrage, kennung)

    if not strom:
        text = "".join(pipeline.antwort(chat_client, CHAT_MODELL, system,
                                        nachrichten))
        return {"antwort": text,
                "quellen": _quellen(treffer, anfrage.quellen_texte),
                "sonden": sonden,
                "sonden_hinweis": hinweis,
                "zahlen": zahlen}

    def ereignisse():
        # Erst die Sonden, dann der Text, zum Schluss die Quellen. So sieht
        # der Aufrufer sofort, wonach gesucht wurde, und bekommt die
        # Fundstellen, wenn die Antwort steht.
        yield _sse("sonden", {"sonden": sonden, "hinweis": hinweis,
                              "zahlen": zahlen})
        for stueck in pipeline.antwort(chat_client, CHAT_MODELL, system,
                                       nachrichten):
            yield _sse("text", {"text": stueck})
        yield _sse("quellen",
                   {"quellen": _quellen(treffer, anfrage.quellen_texte)})

    return StreamingResponse(ereignisse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _quellen(treffer, mit_texten):
    """Fundstellen, auf Wunsch mit den Abschnitten selbst."""
    quellen = pipeline.quellen(treffer)
    if mit_texten:
        return quellen
    return [{"file": q["file"], "page": q["page"],
             "abschnitte": len(q["texts"])} for q in quellen]


def _sse(art, nutzlast):
    return f"event: {art}\ndata: {json.dumps(nutzlast, ensure_ascii=False)}\n\n"
