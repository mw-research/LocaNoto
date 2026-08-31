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
     Netzzugriff. Das ist der Rueckfall, wenn kein Endpunkt gesetzt ist oder
     der Endpunkt nicht antwortet.

  3. Gar keiner. Dann entscheidet allein die Fusion aus Stufe 1.

Keine dieser Stufen darf den Start verhindern: schlaegt eine fehl, wird die
naechste genommen.
"""
import os

# Daempfungskonstante aus der urspruenglichen RRF-Veroeffentlichung. Sie
# begrenzt den Vorsprung, den Platz 1 einer einzelnen Liste erhaelt.
RRF_K = int(os.getenv("RRF_K", "60"))

# --- Stufe 1: Rerank-Endpunkt ---
# Gesetzt = wird zuerst versucht. Der Pfad /rerank wird angehaengt, sofern die
# Adresse ihn nicht schon enthaelt.
RERANKER_BASE_URL = os.getenv("RERANKER_BASE_URL", "").strip()
RERANKER_API_KEY = os.getenv("RERANKER_API_KEY", "").strip()
# Modellname am Endpunkt. Ohne Angabe wird RERANKER_MODEL verwendet.
RERANKER_API_MODEL = os.getenv("RERANKER_API_MODEL", "").strip()
RERANKER_TIMEOUT = float(os.getenv("RERANKER_TIMEOUT", "30"))

# --- Stufe 2: Modell im Image (Dockerfile) ---
# Leer setzen = kein lokales Modell; dann bleibt nur die Fusion.
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip()
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "1024"))


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


def _api_bewerte(paare):
    """Bewertet ueber den Rerank-Endpunkt.

    Das Schema (query + documents rein, results mit index und
    relevance_score raus) ist bei LiteLLM, Jina, TEI und vLLM gleich.

    Eine Anfrage traegt genau eine query. Die Sonde ist bei einer
    Multi-Query-Suche aber je Kandidat verschieden, deshalb wird nach Sonde
    gruppiert -- bei drei Sonden also hoechstens drei Anfragen statt einer
    pro Kandidat.
    """
    import httpx  # kommt ohnehin mit dem OpenAI-Client

    kopf = {"Content-Type": "application/json"}
    if RERANKER_API_KEY:
        kopf["Authorization"] = f"Bearer {RERANKER_API_KEY}"
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
            antwort.raise_for_status()
            daten = antwort.json()
            for treffer in daten.get("results", []):
                platz = treffer.get("index")
                if platz is None or platz >= len(eintraege):
                    continue
                werte[eintraege[platz][0]] = float(
                    treffer.get("relevance_score", treffer.get("score", 0.0)))
    return werte


def _lade_cross_encoder():
    """Laedt den CrossEncoder aus dem Modellverzeichnis des Images."""
    from sentence_transformers import CrossEncoder  # bewusst lokal
    modell = CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)
    return lambda paare: modell.predict(paare)


def lade_bewerter():
    """Waehlt den Bewerter nach der Reihenfolge Endpunkt, Modell, keiner.

    Rueckgabe: (bewerter_oder_None, beschreibung). Die Beschreibung ist fuer
    die Anzeige gedacht und nennt auch den Grund, wenn eine Stufe uebersprungen
    wurde.
    """
    if RERANKER_BASE_URL:
        try:
            bewerter = _api_bewerte
            # Einmal gegen den Endpunkt sprechen, damit ein falscher Pfad oder
            # ein nicht erreichbarer Dienst sofort auffaellt und nicht erst
            # bei der ersten Frage eines Nutzers.
            bewerter([["test", "test"]])
            return bewerter, f"Endpunkt {_rerank_url()}"
        except Exception as e:
            grund = f"Endpunkt nicht nutzbar ({type(e).__name__}: {e})"
    else:
        grund = None

    if RERANKER_MODEL:
        try:
            return _lade_cross_encoder(), (
                f"Modell aus dem Image ({RERANKER_MODEL})"
                + (f" -- {grund}" if grund else ""))
        except Exception as e:
            grund = ((grund + "; ") if grund else "") + \
                    f"Modell nicht ladbar ({type(e).__name__}: {e})"

    return None, "nur Rangfolge-Fusion" + (f" -- {grund}" if grund else "")


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

    neu = sorted(zip(werte, vorauswahl), key=lambda x: x[0], reverse=True)
    return [(text, float(score), item) for score, (text, _, item) in neu[:top_k]]
