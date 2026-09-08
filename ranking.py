"""Kandidaten aus Vektor- und Keyword-Suche zu einer Rangfolge verschmelzen.

Zwei Stufen:

1. Reciprocal Rank Fusion (RRF) ueber alle Ranglisten. Sie bewertet nicht den
   Inhalt, sondern die Uebereinstimmung der Listen: ein Chunk, den mehrere
   Sonden und beide Suchwege weit oben finden, gewinnt gegen einen, der nur
   in einer Liste vorne steht. Das ist genau die Information, die eine
   Multi-Query-Suche mit zwei Suchpfaden ohnehin erzeugt und die vorher
   weggeworfen wurde -- der Reranker sah nur noch die entdoppelte Menge ohne
   jede Rangfolge.

2. Ein Reranker bewertet die engere Auswahl inhaltlich. Dadurch haengt seine
   Rechenzeit an top_k statt an der Kandidatenzahl.

Fuer Stufe 2 gibt es drei Moeglichkeiten, in dieser Reihenfolge:

  1. Ein Rerank-Endpunkt ueber HTTP (RERANKER_BASE_URL). Damit laesst sich
     das Modell wie die uebrigen austauschen, ohne das Image neu zu bauen --
     lokal, bei einem Anbieter oder ueber Azure. Erwartet wird das
     Cohere-artige Schema, das LiteLLM, Jina, TEI und vLLM gleichermaszen
     sprechen: POST auf /rerank mit query und documents, zurueck kommen
     results mit index und relevance_score.

  2. Das CrossEncoder-Modell aus dem Image (RERANKER_MODEL). Es wird beim
     Bauen hineingeladen, HF_HUB_OFFLINE=1 verhindert danach jeden
     Netzzugriff. Es ist der Bewerter, wenn KEIN Endpunkt gesetzt ist -- und
     nur auf Wunsch (RERANKER_RUECKFALL=image) der Ersatz, wenn ein gesetzter
     Endpunkt gerade nicht antwortet.

  3. Gar keiner. Dann entscheidet allein die Fusion aus Stufe 1.

Keine dieser Stufen darf den Start verhindern, und keine Entscheidung ist
endgueltig: faellt der Endpunkt aus, wird er nach einer Wartezeit erneut
versucht. Eine einmal beim Start gescheiterte Probe hatte frueher fuer die
gesamte Laufzeit das CPU-Modell eingeschaltet -- Minuten je Frage, ohne
dass jemand den Grund sah.
"""
import os

import paths

# Daempfungskonstante aus der urspruenglichen RRF-Veroeffentlichung. Sie
# begrenzt den Vorsprung, den Platz 1 einer einzelnen Liste erhaelt.
RRF_K = paths.env_int("RRF_K", 60)

# --- Stufe 1: Rerank-Endpunkt ---
# Gesetzt = wird zuerst versucht. Der Pfad /rerank wird angehaengt, sofern die
# Adresse ihn nicht schon enthaelt.
# Die Adresse ist bewusst OHNE Rueckfall auf OPENAI_BASE_URL: sie ist der
# Schalter, mit dem diese Stufe eingeschaltet wird. Faellt sie zurueck, wuerde
# bei jedem Start ein Rerank-Aufruf gegen den allgemeinen Modellserver
# versucht, der dort nichts zu suchen hat.
RERANKER_BASE_URL = os.getenv("RERANKER_BASE_URL", "").strip()

# Der Schluessel faellt auf OPENAI_API_KEY zurueck -- aber nur, wenn der
# Endpunkt auf denselben Wirt zeigt. Siehe _schluessel(): ein gehosteter
# Dienst soll nicht den Schluessel des eigenen Gateways bekommen.
# Modellname am Endpunkt. Ohne Angabe wird RERANKER_MODEL verwendet.
RERANKER_API_MODEL = os.getenv("RERANKER_API_MODEL", "").strip()
RERANKER_TIMEOUT = paths.env_float("RERANKER_TIMEOUT", 30)

# --- Stufe 2: Modell im Image (Dockerfile) ---
# Leer setzen = kein lokales Modell; dann bleibt nur die Fusion.
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip()
RERANKER_MAX_LENGTH = paths.env_int("RERANKER_MAX_LENGTH", 1024)


def reciprocal_rank_fusion(ranked_lists, k=None):
    """Verschmilzt mehrere Ranglisten zu einer.

    ranked_lists: Iterable von Listen aus dicts mit 'text', 'meta', 'probe'.
    Jede Liste ist bereits sortiert (beste zuerst).

    Rueckgabe: Liste aus (text, score, item), beste zuerst.
    """
    k = RRF_K if k is None else k
    scores = {}
    best = {}

    for lst in ranked_lists:
        for rang, item in enumerate(lst):
            text = item["text"]
            scores[text] = scores.get(text, 0.0) + 1.0 / (k + rang + 1)
            # Fuer die Quellenanzeige die Sonde behalten, die den Chunk am
            # weitesten oben gefunden hat.
            if text not in best or rang < best[text][0]:
                best[text] = (rang, item)

    reihenfolge = sorted(scores, key=lambda t: scores[t], reverse=True)
    return [(t, scores[t], best[t][1]) for t in reihenfolge]


def _rerank_url():
    basis = RERANKER_BASE_URL.rstrip("/")
    return basis if basis.endswith("/rerank") else basis + "/rerank"


def _gleicher_wirt(a, b):
    """Zeigen zwei Adressen auf denselben Wirt?"""
    from urllib.parse import urlparse
    if not a or not b:
        return False
    return (urlparse(a).hostname or "").lower() == \
           (urlparse(b).hostname or "").lower()


def _schluessel():
    """Der Schluessel fuer den Rerank-Endpunkt.

    Rueckfall auf OPENAI_API_KEY NUR, wenn der Endpunkt auf denselben Wirt
    zeigt wie OPENAI_BASE_URL. Wer alles ueber ein Gateway faehrt, soll den
    Schluessel nicht zweimal eintragen muessen -- wer aber einen gehosteten
    Dienst eintraegt, soll ihm nicht versehentlich den Schluessel des
    eigenen Gateways schicken. Ein Zugangsschluessel, der an einen fremden
    Dienst geht, ist dort angekommen; zurueckholen laesst er sich nicht.
    """
    eigen = os.getenv("RERANKER_API_KEY", "").strip()
    if eigen:
        return eigen
    if _gleicher_wirt(RERANKER_BASE_URL, os.getenv("OPENAI_BASE_URL", "")):
        return os.getenv("OPENAI_API_KEY", "").strip()
    return ""


def _api_bewerte(paare):
    """Bewertet ueber den Rerank-Endpunkt.

    Hinein geht query und documents, heraus kommen Treffer mit index und
    relevance_score. Dieses Schema sprechen LiteLLM, Cohere, Jina, Together,
    TEI und vLLM gleichermaszen -- sie sind nur uneins darueber, wie die
    Liste heisst: "results" bei den meisten, "data" bei Voyage und
    Mixedbread.

    Beide werden gelesen. Findet sich KEINE der beiden, wird abgebrochen
    statt Nullen zurueckzugeben: eine Rangfolge, in der jeder Kandidat den
    Wert 0.0 hat, ist keine Rangfolge, sondern Zufall -- und sie faellt
    niemandem auf, weil kein Fehler erscheint. Ein Abbruch dagegen laesst
    die Fusionsreihenfolge stehen und steht in der Seitenleiste.

    Eine Anfrage traegt genau eine query. Die Sonde ist bei einer
    Multi-Query-Suche aber je Kandidat verschieden, deshalb wird nach Sonde
    gruppiert -- bei drei Sonden also hoechstens drei Anfragen statt einer
    pro Kandidat.
    """
    import httpx  # kommt ohnehin mit dem OpenAI-Client

    kopf = {"Content-Type": "application/json"}
    schluessel = _schluessel()
    if schluessel:
        kopf["Authorization"] = f"Bearer {schluessel}"
    modell = RERANKER_API_MODEL or RERANKER_MODEL

    nach_sonde = {}
    for i, (sonde, text) in enumerate(paare):
        nach_sonde.setdefault(sonde, []).append((i, text))

    werte = [0.0] * len(paare)
    with httpx.Client(timeout=RERANKER_TIMEOUT) as http:
        for sonde, eintraege in nach_sonde.items():
            antwort = http.post(_rerank_url(), headers=kopf, json={
                "model": modell,
                "query": sonde,
                "documents": [t for _, t in eintraege],
                "top_n": len(eintraege),
            })
            if antwort.status_code >= 400:
                # Den Rumpf mitnehmen: "401" allein sagt nichts, "invalid
                # api key" oder "model not found" beantwortet die Frage.
                raise RuntimeError(
                    f"HTTP {antwort.status_code} von {_rerank_url()}: "
                    f"{antwort.text[:300]}")
            daten = antwort.json()
            treffer_liste = daten.get("results")
            if treffer_liste is None:
                treffer_liste = daten.get("data")
            if treffer_liste is None:
                raise RuntimeError(
                    f"Antwort von {_rerank_url()} enthaelt weder 'results' "
                    f"noch 'data' -- Schluessel: "
                    f"{sorted(daten)[:8]}. Passt die Adresse zu einem "
                    f"Rerank-Dienst?")
            if not treffer_liste and eintraege:
                raise RuntimeError(
                    f"{_rerank_url()} hat {len(eintraege)} Abschnitte "
                    f"bekommen und keinen bewertet.")
            for treffer in treffer_liste:
                platz = treffer.get("index")
                if platz is None or platz >= len(eintraege):
                    continue
                wert = treffer.get("relevance_score")
                if wert is None:
                    wert = treffer.get("score", 0.0)
                werte[eintraege[platz][0]] = float(wert)
    return werte


def _lade_cross_encoder():
    """Laedt den CrossEncoder aus dem Modellverzeichnis des Images."""
    from sentence_transformers import CrossEncoder  # bewusst lokal
    modell = CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)
    return lambda paare: modell.predict(paare)


# --- Rueckfall und Wiederholung ---
#
# Was passiert, wenn der Endpunkt gesetzt ist, aber gerade nicht antwortet?
#
#   fusion   Die Reihenfolge aus der Fusion bleibt stehen, und beim naechsten
#            Aufruf wird der Endpunkt wieder versucht. Voreinstellung.
#   image    Das CPU-Modell aus dem Image bewertet stattdessen.
#
# Warum "fusion" die Voreinstellung ist und nicht "image": das CPU-Modell
# braucht fuer die 36 Kandidatenpaare einer Frage auf einem gewoehnlichen
# Server ein bis zwei Minuten. Wer einen Endpunkt eingerichtet hat, hat eine
# Grafikkarte dafuer -- und ein Ausfall des Endpunkts ist bei einem Server,
# der Modelle nach fuenf Minuten Ruhe entlaedt, kein Ausnahmefall, sondern
# jeder Morgen. Zwei Minuten Wartezeit sehen fuer den Nutzer aus wie ein
# Haenger; eine Antwort in Fusionsreihenfolge sieht aus wie eine Antwort.
RERANKER_RUECKFALL = (os.getenv("RERANKER_RUECKFALL", "").strip().lower()
                      or "fusion")

# Nach wie vielen Sekunden ein ausgefallener Endpunkt erneut versucht wird.
# Nicht bei jedem Aufruf: sonst wartet jede Frage RERANKER_TIMEOUT lang auf
# einen Dienst, der gerade nicht da ist.
RERANKER_ERNEUT = paths.env_float("RERANKER_ERNEUT", 60)


class Bewerter:
    """Ein Bewerter, der nach einem Ausfall zum Endpunkt zurueckfindet.

    Der Vorgaenger entschied beim Start ein einziges Mal: Endpunkt oder
    Modell aus dem Image. Schlug die Probe fehl -- weil das Rerank-Modell auf
    dem GPU-Server gerade entladen war und zum Aufwachen laenger als das
    Zeitlimit brauchte --, blieb es fuer die gesamte Laufzeit beim
    CPU-Modell. Jede Frage kostete dann Minuten, und niemand sah, woran es
    lag: die Anzeige sagte "Modell aus dem Image", und das klang wie eine
    Einstellung, nicht wie ein Fehler.

    Jetzt wird bei jedem Aufruf entschieden. Faellt der Endpunkt aus, gilt
    der Rueckfall (RERANKER_RUECKFALL), und nach RERANKER_ERNEUT Sekunden
    wird der Endpunkt wieder versucht. beschreibung() nennt den Zustand von
    JETZT, nicht den vom Start.
    """

    def __init__(self):
        import threading
        self._sperre = threading.Lock()
        self._modell = None
        self._modell_fehler = None
        self._ausfall_zeit = None
        self._ausfall_grund = ""
        self._zuletzt_endpunkt = None   # True/False: hat der letzte Aufruf
                                        # den Endpunkt erreicht?
        self.startprobe = None

    # --- Entscheidungen ---

    def _endpunkt_dran(self):
        if not RERANKER_BASE_URL:
            return False
        if self._ausfall_zeit is None:
            return True
        import time
        return (time.time() - self._ausfall_zeit) >= RERANKER_ERNEUT

    def _modell_holen(self):
        """Das CPU-Modell, einmal geladen. None, wenn es nicht ladbar ist."""
        if not RERANKER_MODEL or self._modell_fehler:
            return None
        with self._sperre:
            if self._modell is None and not self._modell_fehler:
                try:
                    self._modell = _lade_cross_encoder()
                except Exception as e:
                    self._modell_fehler = f"{type(e).__name__}: {e}"
        return self._modell

    # --- Aufruf ---

    def __call__(self, paare):
        """Bewertungen zu den Paaren -- oder None, wenn gerade keine zu
        haben sind. None heisst fuer rank(): Fusionsreihenfolge behalten."""
        import time
        if self._endpunkt_dran():
            try:
                werte = _api_bewerte(paare)
                self._ausfall_zeit = None
                self._ausfall_grund = ""
                self._zuletzt_endpunkt = True
                # Die Probe vom Start war ein Hinweis; sobald der Endpunkt
                # einmal geantwortet hat, ist er erledigt.
                self.startprobe = None
                return werte
            except Exception as e:
                self._ausfall_zeit = time.time()
                self._ausfall_grund = f"{type(e).__name__}: {e}"
                self._zuletzt_endpunkt = False
                if RERANKER_RUECKFALL != "image":
                    return None
        elif RERANKER_BASE_URL and RERANKER_RUECKFALL != "image":
            # Endpunkt ausgefallen, Wartezeit noch nicht um.
            self._zuletzt_endpunkt = False
            return None

        modell = self._modell_holen()
        if modell is None:
            return None
        self._zuletzt_endpunkt = False
        return modell(paare)

    # --- Anzeige ---

    def beschreibung(self):
        """Der Zustand von jetzt, fuer die Seitenleiste."""
        import time
        if RERANKER_BASE_URL:
            if self._ausfall_zeit is None:
                stand = f"Endpunkt {_rerank_url()}"
                if self.startprobe:
                    stand += f" -- {self.startprobe}"
                return stand
            wieder = max(0, int(RERANKER_ERNEUT
                                - (time.time() - self._ausfall_zeit)))
            ersatz = ("Modell aus dem Image" if RERANKER_RUECKFALL == "image"
                      and RERANKER_MODEL else "nur Rangfolge-Fusion")
            return (f"Endpunkt {_rerank_url()} AUSGEFALLEN "
                    f"({self._ausfall_grund}) -- vorlaeufig {ersatz}, "
                    f"naechster Versuch in {wieder} s")
        if RERANKER_MODEL and not self._modell_fehler:
            return f"Modell aus dem Image ({RERANKER_MODEL})"
        grund = f" -- {self._modell_fehler}" if self._modell_fehler else ""
        return "nur Rangfolge-Fusion" + grund

    def endpunkt_erreichbar(self):
        return bool(RERANKER_BASE_URL) and self._ausfall_zeit is None


def lade_bewerter():
    """Richtet den Bewerter ein. Rueckgabe: (bewerter, beschreibung).

    Die Beschreibung ist ein Schnappschuss vom Start. Wer den Zustand von
    jetzt will, ruft bewerter.beschreibung() -- sie aendert sich, sobald der
    Endpunkt ausfaellt oder zurueckkommt.

    Die Probe beim Start bleibt, aber sie ENTSCHEIDET nichts mehr. Sie
    zeigt einen falschen Pfad oder einen falschen Schluessel sofort in der
    Seitenleiste, statt erst bei der ersten Frage eines Nutzers. Schlaegt
    sie fehl, weil das Modell gerade aufwacht, ist das ein Hinweis -- und
    beim naechsten Aufruf ein neuer Versuch.
    """
    if not RERANKER_BASE_URL and not RERANKER_MODEL:
        return None, "nur Rangfolge-Fusion"

    b = Bewerter()
    if RERANKER_BASE_URL:
        try:
            _api_bewerte([["test", "test"]])
            b.startprobe = None
        except Exception as e:
            import time
            b._ausfall_zeit = time.time()
            b._ausfall_grund = f"{type(e).__name__}: {e}"
            b.startprobe = f"Probe beim Start fehlgeschlagen ({b._ausfall_grund})"
    return b, b.beschreibung()


def rank(ranked_lists, top_k, bewerter=None):
    """Liefert die besten top_k Kandidaten.

    Ohne bewerter entscheidet allein RRF. Mit bewerter wird RRF als Vorfilter
    benutzt und nur die engere Auswahl bewertet. Die Rechenzeit des Bewerters
    bleibt damit unabhaengig von der Kandidatenzahl.

    Schlaegt der Bewerter zur Laufzeit fehl -- Netzaussetzer, Dienst neu
    gestartet --, bleibt die Reihenfolge aus der Fusion stehen, statt dass die
    Frage unbeantwortet bleibt.
    """
    fusioniert = reciprocal_rank_fusion(ranked_lists)
    if not fusioniert:
        return []

    if bewerter is None:
        return fusioniert[:top_k]

    vorauswahl = fusioniert[:max(top_k * 3, 20)]
    # Gegen die Sonde bewerten, die den Chunk gefunden hat -- nicht gegen die
    # Originalfrage. Bei einer Multi-Query-Suche ist die Sonde der praezisere
    # Bezugspunkt.
    paare = [[item["probe"], text] for text, _, item in vorauswahl]
    try:
        werte = bewerter(paare)
    except Exception:
        return fusioniert[:top_k]
    # None heisst: gerade keine Bewertung zu haben -- der Endpunkt ist
    # ausgefallen und der Rueckfall ist "fusion". Dann bleibt die Reihenfolge
    # aus der Fusion stehen, statt dass die Frage unbeantwortet bleibt.
    if werte is None:
        return fusioniert[:top_k]

    neu = sorted(zip(werte, vorauswahl), key=lambda x: x[0], reverse=True)
    return [(text, float(score), item) for score, (text, _, item) in neu[:top_k]]
