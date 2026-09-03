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
import presets
import tabellen
import sqlpruefung
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
    preset: str | None = Field(
        default=None,
        description="Voreinstellung: Chat-Modell, Trefferzahl, Sachgebiete, "
                    "Listenbereiche und eigene Prompts. Namen siehe "
                    "/voreinstellungen. Einzeln uebergebene Werte gehen vor.")
    listen: bool = Field(
        default=True,
        description="Tabellendateien mit abfragen, sofern ein Katalog "
                    "vorliegt")
    listen_bereiche: list[str] | None = Field(
        default=None,
        description="nur diese Unterordner des Listenordners abfragen. "
                    "Leer = alle, oder die der Voreinstellung.")
    listen_gross: bool = Field(
        default=False,
        description="auch Blaetter einbeziehen, die als gross gelten. Sie "
                    "werden bei jeder Frage vollstaendig geladen -- das "
                    "kann sehr lange dauern.")


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
        "voreinstellungen": presets.namen(),
        "listen": _listenstand(),
    }


def _listenstand():
    """Was der Listenkatalog hergibt -- oder warum nicht."""
    katalog = tabellen.lies_katalog()
    eintraege = katalog.get("eintraege", [])
    return {
        "blaetter": len(eintraege),
        "gross": sum(1 for e in eintraege if e.get("gross")),
        "bereiche": tabellen.bereiche(eintraege),
        "nicht_lesbar": len(katalog.get("fehler", [])),
        "ordner": tabellen.VERZEICHNIS,
    }


@app.get("/dokumente")
def dokumente(kennung: str = Depends(benutzer)):
    """Welche Dokumente diese Kennung sehen darf."""
    geteilt, privat, sachgebiete = pipeline.dokumente(store.collection(), kennung)
    return {"geteilt": geteilt, "privat": privat, "sachgebiete": sachgebiete}


def _listen_abfragen(anfrage, modell, verlauf_text):
    """Fragt die Tabellendateien ab. Rueckgabe: (bloecke, auskunft).

    Scheitert etwas, bleibt es bei den Dokumenten. Eine Liste, die nicht
    passt, ist kein Grund, die Frage unbeantwortet zu lassen.
    """
    if not anfrage.listen:
        return [], None
    katalog = tabellen.lies_katalog()
    auswahl = [e for e in katalog.get("eintraege", [])
               if (anfrage.listen_gross or not e.get("gross"))
               and tabellen.im_bereich(e, anfrage.listen_bereiche or [])]
    if not auswahl:
        return [], None

    try:
        datei, blatt, sql = tabellen.formuliere(
            chat_client, modell, anfrage.frage,
            tabellen.als_text(auswahl), verlauf_text)
    except Exception as e:
        return [], {"grund": f"Abfrage nicht erzeugt: {e}"}
    if not sql:
        return [], {"grund": "Keine der Listen passt zu dieser Frage."}

    try:
        spalten, zeilen = tabellen.fuehre_aus(datei, blatt, sql)
    except ValueError as e:
        return [], {"grund": str(e), "abfrage": sql}
    except Exception as e:
        return [], {"grund": f"Liste nicht lesbar: {e}", "abfrage": sql}

    ergebnis = sqlpruefung.als_tabelle(spalten, zeilen)
    quelle = datei + (f"#{blatt}" if blatt else "")
    return ([("liste_abfrage", f"{quelle}\n{sql}"),
             ("liste_ergebnis", ergebnis)],
            {"blatt": quelle, "abfrage": sql, "zeilen": len(zeilen)})


def _suchen(anfrage, kennung):
    """Gemeinsamer Teil beider Antwortwege."""
    # Die Voreinstellung liefert die Vorgaben; ein ausdruecklich
    # uebergebener Wert geht vor. Wer sie nennt, will ihr Buendel -- wer
    # zusaetzlich top_k setzt, meint es so.
    if anfrage.preset and anfrage.preset not in presets.namen():
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Voreinstellung. Vorhanden: "
                   f"{', '.join(presets.namen()) or 'keine'}")
    p = presets.lese(anfrage.preset)
    modell = p["chat_modell"] or CHAT_MODELL
    top_k = anfrage.top_k or p["top_k"] or STANDARD_TOP_K
    gebiete = anfrage.sachgebiete or p["sachgebiete"] or None
    if not anfrage.listen_bereiche:
        anfrage.listen_bereiche = p["listen_bereiche"]

    verlauf_text = pipeline.verlaufstext(anfrage.verlauf or [],
                                         ohne_letzte=False)
    sonden, hinweis = pipeline.sonden(chat_client, modell, anfrage.frage,
                                      verlauf=verlauf_text,
                                      preset=anfrage.preset)
    try:
        treffer, zahlen = pipeline.suche(
            store.collection(), embed_client, EMBED_MODELL, sonden, kennung,
            top_k, dateien=anfrage.dateien, ordner=gebiete,
            bewerter=_bewerter)
    except ValueError as e:
        # Der Embedding-Endpunkt antwortet nicht. 503, weil es an einem
        # nachgelagerten Dienst liegt und ein spaeterer Versuch klappen kann.
        raise HTTPException(status_code=503, detail=str(e))

    bloecke, listen_auskunft = _listen_abfragen(anfrage, modell, verlauf_text)

    if not treffer and not bloecke:
        # Auch ueber die Schnittstelle gestellte Fragen gehoeren in die
        # Arbeitsliste -- eine Luecke im Bestand ist keine Frage der
        # Bedienung.
        feedback.notiere("leer", kennung, anfrage.frage, sonden=sonden,
                         zahlen=zahlen, herkunft="schnittstelle")

    nachrichten = list(anfrage.verlauf or []) + [
        {"role": "user", "content": anfrage.frage}]
    system = pipeline.systemprompt(
        pipeline.kontext(treffer, bloecke=bloecke), anfrage.preset)
    return (sonden, hinweis, treffer, zahlen, nachrichten, system, modell,
            listen_auskunft)


@app.post("/frage")
def frage(anfrage: Frage,
          strom: bool = Query(default=False,
                              description="Antwort stueckweise als "
                                          "text/event-stream"),
          kennung: str = Depends(benutzer)):
    """Beantwortet eine Frage aus den Dokumenten dieser Kennung."""
    (sonden, hinweis, treffer, zahlen, nachrichten, system, modell,
     listen) = _suchen(anfrage, kennung)

    if not strom:
        text = "".join(pipeline.antwort(chat_client, modell, system,
                                        nachrichten))
        return {"antwort": text,
                "quellen": _quellen(treffer, anfrage.quellen_texte),
                "liste": listen,
                "sonden": sonden,
                "sonden_hinweis": hinweis,
                "zahlen": zahlen}

    def ereignisse():
        # Erst die Sonden, dann der Text, zum Schluss die Quellen. So sieht
        # der Aufrufer sofort, wonach gesucht wurde, und bekommt die
        # Fundstellen, wenn die Antwort steht.
        yield _sse("sonden", {"sonden": sonden, "hinweis": hinweis,
                              "zahlen": zahlen, "liste": listen})
        for stueck in pipeline.antwort(chat_client, modell, system,
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


class Rueckmeldung(BaseModel):
    art: str = Field(description="daumen_hoch oder daumen_runter")
    frage: str = Field(min_length=1, max_length=2000)
    sonden: list[str] = Field(default_factory=list)
    quellen: list[dict] = Field(default_factory=list)


@app.post("/rueckmeldung")
def rueckmeldung(eintrag: Rueckmeldung, kennung: str = Depends(benutzer)):
    """Haelt fest, ob eine Antwort geholfen hat.

    Dieselbe Liste wie die Daumen in der Oberflaeche. Wer die Schnittstelle
    benutzt, faellt sonst aus der Auswertung heraus -- und das sind gerade
    die Faelle, in denen jemand die Anlage ernsthaft ausprobiert.
    """
    if not feedback.notiere(eintrag.art, kennung, eintrag.frage,
                            sonden=eintrag.sonden, quellen=eintrag.quellen,
                            herkunft="schnittstelle"):
        raise HTTPException(status_code=400,
                            detail=f"Unbekannte Art. Erlaubt: "
                                   f"{', '.join(feedback.ARTEN)}")
    return {"status": "vermerkt"}


@app.get("/voreinstellungen")
def voreinstellungen(kennung: str = Depends(benutzer)):
    """Welche Voreinstellungen es gibt und was sie setzen."""
    return [{"name": n, **{k: v for k, v in presets.lese(n).items()
                           if k != "beschreibung" or v}}
            for n in presets.namen()]
