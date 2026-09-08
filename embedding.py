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
from concurrent.futures import ThreadPoolExecutor

import paths

DEFAULT_BATCH_SIZE = paths.env_int("EMBED_BATCH_SIZE", 64)

# Ohne timeout= wartet der Client bis zu 600 s. Ein haengender Batch soll den
# Ingest nicht stundenlang blockieren -- der Einzel-Rueckfall arbeitet ihn
# danach ohnehin nach.
DEFAULT_TIMEOUT = paths.env_float("EMBED_TIMEOUT", 120)

# Untergrenze, ab der nicht weiter gekuerzt wird. Bleibt ein Chunk auch so zu
# gross, liegt der Fehler woanders und soll sichtbar werden.
MIN_KUERZUNG_CHARS = paths.env_int("EMBED_MIN_CHARS", 400)

# Gleichzeitig offene Anfragen an den Modellserver.
#
# Der Prozess wartet die meiste Zeit auf Antwort, nicht auf eigene Rechenzeit.
# Mehrere offene Anfragen lassen den Server sie zusammen abarbeiten und seine
# Grafikkarten besser auslasten. Die sinnvolle Obergrenze liegt beim Server,
# nicht hier -- zu hohe Werte erzeugen dort nur eine Warteschlange oder
# Zeitueberschreitungen. 1 stellt das frühere Verhalten her.
PARALLEL = max(1, paths.env_int("EMBED_PARALLEL", 2))


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
                progress=None, timeout=None, nacharbeit=True):
    """Vektorisiert eine Liste von Texten und behaelt die Reihenfolge bei.

    Faellt ein Batch aus, WEIL EIN TEXT ZU LANG IST, wird er einzeln
    nachgearbeitet und der zu lange Text gekuerzt -- sonst verwuerfe ein
    einzelner Chunk den ganzen Batch.

    Bei jedem anderen Fehler -- Zeitueberschreitung, Serverfehler, Netz
    -- hilft die Einzelnacharbeit nicht, sie multipliziert nur die
    Wartezeit. Das war ein echter Fehler: bei drei Sonden und 120 s
    Zeitlimit kostete ein haengender Endpunkt 120 s fuer den Batch und
    dann dreimal 120 s einzeln -- acht Minuten, bevor ueberhaupt eine
    Meldung erschien. Solche Fehler gehen jetzt sofort weiter.

    nacharbeit=False schaltet die Nacharbeit ganz ab. Fuer die Suche
    richtig: drei kurze Sonden koennen das Kontextfenster nicht
    ueberschreiten, dort ist jede Nacharbeit reine Wartezeit.

    timeout ueberschreibt DEFAULT_TIMEOUT -- die Suche darf ein
    kuerzeres Zeitlimit haben als der Ingest, dort wartet niemand zu.
    """
    texts = list(texts)
    if not texts:
        return []

    batch_size = batch_size or DEFAULT_BATCH_SIZE
    zeitlimit = DEFAULT_TIMEOUT if timeout is None else timeout
    extra = {"drop_params": True}
    if keep_alive is not None:
        extra["keep_alive"] = keep_alive

    out = [None] * len(texts)
    fehler = []

    def ein_batch(start):
        """Vektorisiert einen Abschnitt und schreibt ihn an seine feste Stelle.

        Jeder Abschnitt kennt seinen Startindex. Deshalb koennen mehrere
        gleichzeitig laufen, ohne dass die Reihenfolge durcheinandergeraet --
        geschrieben wird immer an dieselbe Position in out.
        """
        chunk = texts[start:start + batch_size]
        cleaned = [t.replace(chr(10), " ") for t in chunk]
        try:
            resp = client.embeddings.create(
                input=cleaned, model=model, timeout=zeitlimit,
                encoding_format="float", extra_body=extra)
            # Die API darf die Reihenfolge aendern -- ueber .index zuordnen.
            for item in resp.data:
                out[start + item.index] = item.embedding
            return
        except Exception as e:
            fehler.append(e)
            # Nur ein Kontextfehler laesst sich einzeln retten. Bei allem
            # anderen -- Zeitueberschreitung, 5xx, Netz -- wiederholte die
            # Nacharbeit dieselbe Wartezeit je Text, ohne je zu helfen.
            if not nacharbeit:
                print(f"   [!] Embedding fehlgeschlagen "
                      f"({type(e).__name__}: {str(e)[:200]})")
                return
            if not _ist_kontextfehler(e):
                print(f"   [!] Embedding fehlgeschlagen "
                      f"({type(e).__name__}: {str(e)[:200]})")
                return

        for i, single in enumerate(cleaned):
            try:
                vektor, gekuerzt = _embed_einzeln(
                    client, single, model, extra, zeitlimit)
                out[start + i] = vektor
                if gekuerzt:
                    print(f"   [i] Chunk {start + i} war fuer das "
                          f"Kontextfenster zu lang -- Vektor aus dem "
                          f"Anfang des Textes, gespeichert wird der "
                          f"vollstaendige Text.")
            except Exception as e:
                fehler.append(e)
                print(f"   [!] Embedding fehlgeschlagen (Chunk "
                      f"{start + i}): {e}")

    starts = list(range(0, len(texts), batch_size))

    if PARALLEL <= 1 or len(starts) <= 1:
        for n, start in enumerate(starts, 1):
            ein_batch(start)
            if progress:
                progress(min(n * batch_size, len(texts)), len(texts))
    else:
        fertig = 0
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            for _ in pool.map(ein_batch, starts):
                fertig += 1
                if progress:
                    progress(min(fertig * batch_size, len(texts)), len(texts))

    # Den letzten Fehler mitgeben: der Aufrufer soll den Grund nennen
    # koennen statt nur 'konnte nicht vektorisiert werden'.
    if fehler:
        embed_batch.letzter_fehler = fehler[-1]
    else:
        embed_batch.letzter_fehler = None
    return out


def embed_one(client, text, model, keep_alive=None):
    vectors = embed_batch(client, [text], model, batch_size=1,
                          keep_alive=keep_alive)
    return vectors[0] if vectors else None
