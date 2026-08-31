"""Embedding-Aufrufe, gebuendelt.

Bisher ging pro Chunk eine eigene HTTP-Anfrage an den Modellserver. Bei rund
324.000 Chunks (Hochrechnung fuer 1,6 GB PDF) und 150 ms Roundtrip sind das
etwa 13 Stunden -- fast ausschliesslich Wartezeit auf dem Netzwerk, nicht
Rechenzeit im Modell.

Gebuendelt sinkt das auf einen Bruchteil. Die Batchgroesse ist bewusst
konservativ: zu grosse Batches lassen den Server bei langen Chunks in
Timeouts laufen.
"""
import os

DEFAULT_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))

# Ohne timeout= wartet der Client bis zu 600 s. Ein haengender Batch soll den
# Ingest nicht stundenlang blockieren -- der Einzel-Rueckfall arbeitet ihn
# danach ohnehin nach.
DEFAULT_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "120"))

# Untergrenze, ab der nicht weiter gekuerzt wird. Bleibt ein Chunk auch so zu
# gross, liegt der Fehler woanders und soll sichtbar werden.
MIN_KUERZUNG_CHARS = int(os.getenv("EMBED_MIN_CHARS", "400"))


def _ist_kontextfehler(e):
    """Erkennt die Rueckmeldung eines Servers, dem der Text zu lang ist.

    Die Formulierung unterscheidet sich je nach Server und Proxy, deshalb
    ueber Stichworte statt ueber einen Fehlertyp.
    """
    t = str(e).lower()
    return any(w in t for w in (
        "context window", "contextwindow", "exceed_context",
        "exceeds the available context", "maximum context",
        "too long", "context length"))


def _embed_einzeln(client, text, model, extra, timeout):
    """Vektorisiert einen Text und kuerzt ihn, falls der Server ihn ablehnt.

    Nicht der gespeicherte Chunk wird gekuerzt, sondern nur die Fassung, die
    zur Vektorberechnung geht. In ChromaDB und im Keyword-Index steht
    weiterhin der vollstaendige Text -- das Sprachmodell bekommt also die
    ganze Tabelle zu sehen, nur der Vektor stammt aus ihrem Anfang.

    Das ist deutlich besser als die Alternative: bisher wurde ein zu langer
    Chunk komplett verworfen und fehlte in der Wissensbasis.
    """
    versuch = text
    gekuerzt = False
    while True:
        try:
            resp = client.embeddings.create(
                input=[versuch], model=model, timeout=timeout,
                encoding_format="float", extra_body=extra)
            return resp.data[0].embedding, gekuerzt
        except Exception as e:
            if not _ist_kontextfehler(e) or len(versuch) <= MIN_KUERZUNG_CHARS:
                raise
            # Zwei Drittel statt Haelfte: naeher an der Grenze, damit moeglichst
            # viel vom Text in den Vektor eingeht.
            versuch = versuch[:max(MIN_KUERZUNG_CHARS, len(versuch) * 2 // 3)]
            gekuerzt = True


def embed_batch(client, texts, model, batch_size=None, keep_alive=None,
                progress=None):
    """Vektorisiert eine Liste von Texten und behaelt die Reihenfolge bei.

    Faellt ein Batch aus (zu lang, Serverfehler), wird er einzeln
    nachgearbeitet. Andernfalls wuerde ein einzelner fehlerhafter Chunk den
    gesamten Batch verwerfen.
    """
    texts = list(texts)
    if not texts:
        return []

    batch_size = batch_size or DEFAULT_BATCH_SIZE
    extra = {"drop_params": True}
    if keep_alive is not None:
        extra["keep_alive"] = keep_alive

    out = [None] * len(texts)
    for start in range(0, len(texts), batch_size):
        chunk = texts[start:start + batch_size]
        cleaned = [t.replace("\n", " ") for t in chunk]
        try:
            resp = client.embeddings.create(
                input=cleaned, model=model, timeout=DEFAULT_TIMEOUT,
                encoding_format="float", extra_body=extra)
            # Die API darf die Reihenfolge aendern -- ueber .index zuordnen.
            for item in resp.data:
                out[start + item.index] = item.embedding
        except Exception:
            for i, single in enumerate(cleaned):
                try:
                    vektor, gekuerzt = _embed_einzeln(
                        client, single, model, extra, DEFAULT_TIMEOUT)
                    out[start + i] = vektor
                    if gekuerzt:
                        print(f"   [i] Chunk {start + i} war fuer das "
                              f"Kontextfenster zu lang -- Vektor aus dem "
                              f"Anfang des Textes, gespeichert wird der "
                              f"vollstaendige Text.")
                except Exception as e:
                    print(f"   [!] Embedding fehlgeschlagen (Chunk "
                          f"{start + i}): {e}")
        if progress:
            progress(min(start + batch_size, len(texts)), len(texts))

    return out


def embed_one(client, text, model, keep_alive=None):
    vectors = embed_batch(client, [text], model, batch_size=1,
                          keep_alive=keep_alive)
    return vectors[0] if vectors else None
