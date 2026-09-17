"""HTTP-Schnittstelle zu derselben Suche, die auch die Oberflaeche benutzt.

Gedacht fuer Bedienung ohne Browser: eine Frage aus dem Terminal, ein
Skript, das einen Bestand prueft. Die Antworten kommen aus pipeline.py --
denselben Funktionen wie in der Oberflaeche. Zwei getrennte Umsetzungen
wuerden auf dieselbe Frage verschieden antworten, und der Unterschied
faellt erst auf, wenn ihn jemand sucht.

Zugang ueber ein Token im Kopf der Anfrage:

    curl -H "X-LocaNoto-Token: lnt_..." http://127.0.0.1:8600/status

Das Token bildet auf eine Kennung ab, und diese Kennung geht als benutzer
in die Suche. Durchsucht werden genau die Raeume, in denen sie Mitglied
ist -- ohne Sonderbehandlung und ohne einen Schalter, der das umgeht. Eine
mitgegebene Raumliste kann nur einschraenken; ein Raum ausserhalb der
Berechtigung wird still verworfen.

Betrieb: uvicorn api:app --host 0.0.0.0 --port 8600
"""
import json
import os

from fastapi import (Depends, FastAPI, File, Form, Header,
                     HTTPException, Query, UploadFile)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import paths
import auth
import llm
import pipeline
import raeume
import geheim
import feedback
import presets
import tabellen
import sqlpruefung
import ranking
import store
import budget
import aufnehmen
import benutzer as benutzer_datei

paths.bootstrap()

# Ohne lesbaren Schluessel gar nicht erst starten: die Schnittstelle
# schreibt Rueckmeldungen, und die wuerden im Klartext neben den
# verschluesselten landen. Ein Lesefehler ist behebbar, ein
# ueberschriebener Bestand nicht.
_schl_zustand, _schl_meldung = geheim.zustand()
if _schl_zustand == "unlesbar":
    raise SystemExit("Installationsschluessel nicht lesbar: "
                     + _schl_meldung)

# Unter welchem Praefix die Schnittstelle von aussen steht.
#
# Im Cluster schneidet Traefik "/api" ab, bevor die Anfrage hier
# ankommt. Die Routen stimmen damit -- die erzeugten Adressen nicht:
# die Oberflaeche unter /hilfe holte ihr Schema von "/openapi.json"
# statt "/api/openapi.json" und blieb leer, und "Try it out" schickte
# an "/aufnehmen" statt "/api/aufnehmen". Die Schnittstelle war also da
# und liess sich nicht ansehen.
#
# Als Umgebungsvariable und nicht als Startparameter: dieselbe
# Einstellung gilt dann fuer Compose und fuer Kubernetes, und sie steht
# dort, wo alle anderen auch stehen. Leer heisst: direkt erreichbar.
API_WURZELPFAD = os.getenv("API_WURZELPFAD", "").strip().rstrip("/")

app = FastAPI(
    title="LocaNoto",
    description=__doc__,
    version="1.0",
    # Die Bedienoberflaeche der Schnittstelle bleibt erreichbar: sie ist die
    # knappste Dokumentation, die nicht veralten kann.
    docs_url="/hilfe",
    redoc_url=None,
    root_path=API_WURZELPFAD,
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


@app.exception_handler(budget.Ueberzogen)
def budget_aufgebraucht(anfrage, fehler):
    """429 statt 500: das ist kein Fehler, das ist eine Schwelle.

    Ungefangen wurde daraus ein Serverfehler ohne Text -- fuer den
    Aufrufer nicht von einem Absturz zu unterscheiden, und in der
    Oberflaeche eine rote Rueckverfolgung mitten im Chat. Die Meldung
    sagt, was los ist und welche Einstellung es hebt; sie gehoert
    weitergereicht und nicht verschluckt.

    429 und nicht 403: die Anfrage war berechtigt, es waren nur zu
    viele. Retry-After nennt den Rest des Fensters -- frueher hat es
    keinen Zweck, und Raten kostet nur weitere Versuche.
    """
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": str(fehler), "grund": "entnahmebudget"},
        headers={"Retry-After": str(budget.FENSTER_MINUTEN * 60)})


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
    raeume: list[str] | None = Field(
        default=None,
        description="nur in diesen Raeumen suchen. Ohne Angabe alle, die "
                    "die Kennung lesen darf -- siehe /raeume. Ein Raum "
                    "ausserhalb der Berechtigung wird still verworfen, "
                    "nicht abgewiesen: eine Fehlermeldung waere die "
                    "Auskunft, dass es ihn gibt.")
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
        description="Voreinstellung: Chat-Modell, Trefferzahl, "
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
    paare = pipeline.sammlungen(kennung)
    nach_raum = pipeline.dokumente(kennung)
    return {
        "benutzer": kennung,
        "abschnitte": sum(sml.count() for _r, sml in paare),
        "raeume": {r: {"bezeichnung": raeume.bezeichnung(r),
                       "abschnitte": sml.count(),
                       "dokumente": len(nach_raum.get(r, []))}
                   for r, sml in paare},
        "ablage": store.beschreibung(),
        "rangfolge": (_bewerter.beschreibung()
                      if hasattr(_bewerter, "beschreibung") else BEWERTER_INFO),
        "modelle": {"chat": CHAT_MODELL, "embedding": EMBED_MODELL},
        "voreinstellungen": presets.namen(),
        "listen": _listenstand(kennung),
    }


def _listenstand(kennung=""):
    """Was der Listenkatalog fuer DIESEN Anrufer hergibt.

    Auch die blosse Zahl gehoert gefiltert. "412 Blaetter" gegenueber
    "6 Blaetter" ist bereits eine Auskunft darueber, was es sonst noch
    gibt.
    """
    katalog = tabellen.lies_katalog()
    eintraege = tabellen.sichtbar(katalog.get("eintraege", []), kennung)
    return {
        "blaetter": len(eintraege),
        "gross": sum(1 for e in eintraege if e.get("gross")),
        "bereiche": tabellen.bereiche(eintraege),
        "nicht_lesbar": len(katalog.get("fehler", [])),
        "ordner": tabellen.pfad(),
    }


@app.get("/dokumente")
def dokumente(kennung: str = Depends(benutzer)):
    """Welche Dokumente diese Kennung sehen darf -- nach Raum."""
    nach_raum = pipeline.dokumente(kennung)
    return {"raeume": {r: {"bezeichnung": raeume.bezeichnung(r),
                           "dateien": d}
                       for r, d in sorted(nach_raum.items())}}


@app.get("/raeume")
def raeume_liste(kennung: str = Depends(benutzer)):
    """Die Raeume, die diese Kennung lesen darf.

    Bewusst nur die eigenen: eine Liste aller Raeume waere schon eine
    Auskunft -- welche Abteilungen es gibt und wie sie heissen.
    """
    erlaubt = raeume.lesbar(kennung)
    vorhanden = {r for r, _s in pipeline.sammlungen(kennung)}
    return {"raeume": [{"kennung": r,
                        "bezeichnung": raeume.bezeichnung(r),
                        "beschreibung": (raeume.raum(r) or {}).get(
                            "beschreibung", ""),
                        "privat": raeume.ist_privat(r),
                        "hat_daten": r in vorhanden}
                       for r in erlaubt]}


def _listen_abfragen(anfrage, modell, verlauf_text, kennung):
    """Fragt die Tabellendateien ab. Rueckgabe: (bloecke, auskunft).

    Scheitert etwas, bleibt es bei den Dokumenten. Eine Liste, die nicht
    passt, ist kein Grund, die Frage unbeantwortet zu lassen.
    """
    if not anfrage.listen:
        return [], None
    katalog = tabellen.lies_katalog()
    # Gefiltert wie die Sammlungen: raeume.lesbar entscheidet, nicht der
    # Bereich. Ein Bereich ist ein Unterordner und war nie eine
    # Berechtigung.
    auswahl = [e for e in tabellen.sichtbar(katalog.get("eintraege", []),
                                            kennung)
               if (anfrage.listen_gross or not e.get("gross"))
               and tabellen.im_bereich(e, anfrage.listen_bereiche or [])]
    if not auswahl:
        return [], None

    try:
        # Mehrere Blaetter statt eines: dieselbe Frage gilt bei einem
        # gewachsenen Listenordner oft mehreren zugleich. Die Schnittstelle
        # nimmt denselben Weg wie die Oberflaeche -- zwei Auffassungen
        # davon, wie eine Listenfrage beantwortet wird, waeren eine zu
        # viel.
        ergebnisse = tabellen.abfragen(
            chat_client, modell, anfrage.frage, auswahl, verlauf_text)
    except Exception as e:
        return [], {"grund": f"Abfrage nicht erzeugt: {e}"}
    if not ergebnisse:
        return [], {"grund": "Keine der Listen passt zu dieser Frage."}

    bloecke, auskunft = [], []
    for t in ergebnisse:
        quelle = t["datei"] + (f"#{t['blatt']}" if t["blatt"] else "")
        eintrag = {"blatt": quelle, "abfrage": t["sql"],
                   "zeilen": len(t["zeilen"])}
        if t["grund"]:
            eintrag["grund"] = t["grund"]
            auskunft.append(eintrag)
            continue
        auskunft.append(eintrag)
        if not t["zeilen"]:
            # Eine leere Tabelle gehoert nicht in den Kontext: sie liest
            # sich fuer das Modell wie ein Beleg dafuer, dass es das
            # Gesuchte nicht gibt. Gemeldet wird sie trotzdem.
            continue
        bloecke += [("liste_abfrage",
                     quelle + chr(10) + t["sql"]),
                    ("liste_ergebnis",
                     sqlpruefung.als_tabelle(t["spalten"], t["zeilen"]))]
    if not bloecke:
        return [], {"blaetter": auskunft,
                    "grund": "Keine der Listen lieferte eine Zeile."}
    return bloecke, {"blaetter": auskunft}


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
    if not anfrage.listen_bereiche:
        anfrage.listen_bereiche = p["listen_bereiche"]

    verlauf_text = pipeline.verlaufstext(anfrage.verlauf or [],
                                         ohne_letzte=False)
    sonden, hinweis = pipeline.sonden(chat_client, modell, anfrage.frage,
                                      verlauf=verlauf_text,
                                      preset=anfrage.preset)
    try:
        treffer, zahlen = pipeline.suche(
            pipeline.sammlungen(kennung, nur=anfrage.raeume),
            embed_client, EMBED_MODELL, sonden, kennung,
            top_k, dateien=anfrage.dateien,
            bewerter=_bewerter)
    except ValueError as e:
        # Der Embedding-Endpunkt antwortet nicht. 503, weil es an einem
        # nachgelagerten Dienst liegt und ein spaeterer Versuch klappen kann.
        raise HTTPException(status_code=503, detail=str(e))

    bloecke, listen_auskunft = _listen_abfragen(anfrage, modell,
                                                verlauf_text, kennung)

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
    # raum bleibt auch ohne Texte dabei: er sagt, welche gleichnamige
    # Datei gemeint ist, und er entscheidet, ob ein Dateiname spaeter ins
    # Rueckmeldungsprotokoll darf (siehe feedback._quelle).
    return [{"file": q["file"], "page": q["page"], "raum": q.get("raum"),
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


# --- AUFNEHMEN ---
#
# Derselbe Weg wie in der Oberflaeche: aufnehmen.process_uploaded_pdf.
# Nicht eine zweite Fassung davon -- zwei Ingestwege, von denen einer
# nachgezogen wird und der andere nicht, waeren der Anfang davon, dass
# ein Dokument je nach Eingang anders im Bestand liegt.
#
# Moeglich ist das ueberhaupt nur mit Chroma als Dienst. Ohne ihn
# schrieben Oberflaeche und Schnittstelle in dieselben Dateien; die
# Startsperre oben laesst die Schnittstelle dann gar nicht erst laufen.

AUFNAHME_MAX_MB = paths.env_int("AUFNAHME_MAX_MB", 200)


class _Hochgeladen:
    """Was aufnehmen.py von einer Datei braucht: ihren Namen und Bytes.

    Mehr benutzt die Funktion nicht -- gemessen, nicht angenommen. Genau
    deshalb ist ein Upload aus dem Browser und einer aus einer
    HTTP-Anfrage dort ununterscheidbar.
    """

    def __init__(self, name, inhalt):
        self.name = name
        self._inhalt = inhalt

    def getvalue(self):
        return self._inhalt


@app.post("/aufnehmen")
def aufnehmen_(datei: UploadFile = File(...),
               raum: str = Form(...),
               projekt: str = Form(""),
               bilder: bool = Form(False),
               kennung: str = Depends(benutzer)):
    """Ein Dokument aufnehmen: ablegen, zerlegen, vektorisieren.

    Ein Dokument je Anfrage. Ein Stapel in einer Anfrage haette einen
    einzigen Ausgang fuer zweihundert Dateien; so bekommt jede ihren
    eigenen. Der Aufruf dauert so lange wie das Einlesen -- bei einem
    grossen Scan Minuten. Das Zeitlimit gehoert auf die Client-Seite.

    Die Rolle kommt aus der signierten Benutzerdatei und nicht aus dem
    Token: ein Token weist einen Nutzer aus, was er darf steht woanders.
    Fuer den haeufigsten Fall ist das der Unterschied -- in den
    allgemeinen Raum darf nur ein Verwalter schreiben.

    403 statt einer stillen Umleitung: die Oberflaeche ersetzt einen
    unerlaubten Raum durch den eigenen, weil man dort sieht, wo etwas
    gelandet ist. Ueber HTTP waere dasselbe ein 200 fuer einen Stapel,
    der vollstaendig woanders liegt.
    """
    inhalt = datei.file.read()
    if len(inhalt) > AUFNAHME_MAX_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Groesser als {AUFNAHME_MAX_MB} MB "
                   f"(AUFNAHME_MAX_MB).")
    if not inhalt:
        raise HTTPException(status_code=400, detail="Leere Datei.")

    try:
        anzahl, hinweis = aufnehmen.process_uploaded_pdf(
            _Hochgeladen(datei.filename or "unbenannt", inhalt),
            raum, projekt, bilder,
            benutzer_=kennung,
            ist_verwalter=benutzer_datei.ist_admin(kennung),
            streng=True)
    except aufnehmen.KeinRecht as e:
        raise HTTPException(status_code=403, detail=str(e))

    # 200 auch bei null Abschnitten, und der Hinweis sagt warum. Ein
    # Scan ohne Textebene ist kein Fehler der Anfrage -- sie ist
    # angekommen, die Datei liegt ab, nur durchsuchbar ist sie nicht.
    # Ein 4xx dafuer hiesse, der Aufrufer haette etwas falsch gemacht.
    return {"datei": datei.filename, "raum": raum,
            "abschnitte": anzahl, "durchsuchbar": bool(anzahl),
            "hinweis": hinweis}


@app.get("/voreinstellungen")
def voreinstellungen(kennung: str = Depends(benutzer)):
    """Welche Voreinstellungen es gibt und was sie setzen."""
    return [{"name": n, **{k: v for k, v in presets.lese(n).items()
                           if k != "beschreibung" or v}}
            for n in presets.namen()]
