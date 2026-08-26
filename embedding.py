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


def embed_batch(client, texts, model, batch_size=None, keep_alive=None,
                progress=None):
    """Vektorisiert eine Liste von Texten und behaelt die Reihenfolge bei.

    Faellt ein Batch aus (zu lang, Serverfehler), wird er einzeln
    nachgearbeitet, damit ein einzelner problematischer Chunk nicht 63
    unschuldige mitreisst.
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
                input=cleaned, model=model,
                encoding_format="float", extra_body=extra)
            # Die API darf die Reihenfolge aendern -- ueber .index zuordnen.
            for item in resp.data:
                out[start + item.index] = item.embedding
        except Exception:
            for i, single in enumerate(cleaned):
                try:
                    resp = client.embeddings.create(
                        input=[single], model=model,
                        encoding_format="float", extra_body=extra)
                    out[start + i] = resp.data[0].embedding
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
