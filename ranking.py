"""Kandidaten aus Vektor- und Keyword-Suche zu einer Rangfolge verschmelzen.

Standardverfahren ist Reciprocal Rank Fusion (RRF). Es braucht kein Modell:
kein Download beim ersten Start, keine Ladezeit, keine GPU, keine
Netzabhaengigkeit. Der bisherige CrossEncoder holte sein Modell beim ersten
Start von HuggingFace -- war der Dienst nicht erreichbar, startete die App
nicht.

RRF bewertet nicht den Inhalt, sondern die Uebereinstimmung der Ranglisten:
ein Chunk, den mehrere Sonden und beide Suchwege weit oben finden, gewinnt
gegen einen, der nur in einer Liste ganz vorne steht. Das ist genau die
Information, die eine Multi-Query-Suche mit zwei Suchpfaden ohnehin erzeugt
und die vorher weggeworfen wurde -- der CrossEncoder sah nur noch die
entdoppelte Menge ohne jede Rangfolge.

Der CrossEncoder bleibt als Option erhalten (RERANKER_MODEL setzen). Der
Import passiert bewusst erst bei Bedarf, damit ohne ihn weder
sentence_transformers noch torch geladen werden.
"""
import os

# Daempfungskonstante aus der urspruenglichen RRF-Veroeffentlichung. Sie
# verhindert, dass Platz 1 einer einzelnen Liste alles andere erschlaegt.
RRF_K = int(os.getenv("RRF_K", "60"))

# Leer = kein Modell, reines RRF. Gesetzt = zusaetzlich CrossEncoder.
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "").strip()
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


def _load_cross_encoder():
    """Laedt den CrossEncoder -- nur wenn RERANKER_MODEL gesetzt ist."""
    from sentence_transformers import CrossEncoder  # bewusst lokal
    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)


def rank(ranked_lists, top_k, cross_encoder=None):
    """Liefert die besten top_k Kandidaten.

    Ohne cross_encoder entscheidet allein RRF. Mit cross_encoder wird RRF als
    Vorfilter benutzt und nur die engere Auswahl vom Modell bewertet -- das
    haelt die Modellkosten unabhaengig von der Kandidatenzahl.
    """
    fusioniert = reciprocal_rank_fusion(ranked_lists)
    if not fusioniert:
        return []

    if cross_encoder is None:
        return fusioniert[:top_k]

    vorauswahl = fusioniert[:max(top_k * 3, 20)]
    # Gegen die Sonde bewerten, die den Chunk gefunden hat -- nicht gegen die
    # Originalfrage. Bei einer Multi-Query-Suche ist die Sonde der praezisere
    # Bezugspunkt.
    paare = [[item["probe"], text] for text, _, item in vorauswahl]
    werte = cross_encoder.predict(paare)

    neu = sorted(zip(werte, vorauswahl), key=lambda x: x[0], reverse=True)
    return [(text, float(score), item) for score, (text, _, item) in neu[:top_k]]
