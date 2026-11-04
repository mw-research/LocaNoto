"""Changing the embedding model on Postgres, end to end, without a model server.

    SELFTEST_DATABASE=postgresql://user:pw@host:5432/postgres python test_reembed.py

Creates a throw-away database, stores passages with vectors of model A,
computes the vectors of model B in the background column (reembed.py),
switches EMBEDDING_MODEL to B and checks that search finds the same with
B -- and that a model without vectors is refused instead of answering
from vectors of another one. The two "models" are compare_search's
HashEmbedder, once on the text and once on the text reversed word by
word, so their vectors differ and each finds only with its own queries.
"""
import os
import sys
import tempfile
import uuid
from urllib.parse import urlsplit, urlunsplit

HERE = os.path.dirname(os.path.abspath(__file__))
DIM = 64

PASSAGES = [
    ("Betriebsanweisung.pdf", "Die Pruefristen fuer Druckbehaelter und Kessel betragen vier Jahre."),
    ("Arbeitsschutz.pdf", "Schutzbrille und Gehoerschutz sind in der Halle Pflicht."),
    ("Qualitaet.pdf", "Toleranzen fuer Schweissnaehte richten sich nach DIN EN ISO 5817."),
    ("Wartung.pdf", "Die Hydraulikpumpe wird alle 500 Betriebsstunden gewartet."),
    ("Wartung.pdf", "Filterwechsel am Kompressor erfolgt quartalsweise."),
    ("Rahmenvertrag.pdf", "Dichtungen werden nach Rahmenvertrag 2026 beim Lieferanten Mueller beschafft."),
]
QUESTIONS = {"Pruefristen Kessel": 0, "Schutzbrille Halle": 1, "Schweissnaehte Toleranzen": 2,
             "Hydraulikpumpe Betriebsstunden": 3, "Filterwechsel Kompressor": 4,
             "Dichtungen Lieferant": 5}

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main():
    server = os.environ.get("SELFTEST_DATABASE", "").strip()
    if not server:
        print("SELFTEST_DATABASE is not set (a Postgres server URL).")
        return 2
    import psycopg
    name = "reembed_" + uuid.uuid4().hex[:8]
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        u = urlsplit(server)
        tmp = tempfile.mkdtemp(prefix="reembed_")
        os.environ.update({
            "DATABASE_URL": urlunsplit((u.scheme, u.netloc, "/" + name, u.query, "")),
            "DATABASE_DIMENSIONS": str(DIM), "EMBEDDING_NEXT_DIMENSIONS": str(DIM),
            "LOCANOTO_KONFIG": os.path.join(tmp, "config"),
            "LOCANOTO_DATEN": os.path.join(tmp, "data"),
            "EMBEDDING_MODEL": "hash-a"})
        for k in ("EMBEDDING_NEXT_MODEL", "REEMBED_HOURS"):
            os.environ.pop(k, None)
        run()
    finally:
        import database
        database.close()
        with psycopg.connect(server, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    print(f"=== {'all passed' if not failures else str(len(failures)) + ' failed'} ===")
    return 1 if failures else 0


def run():
    sys.path.insert(0, HERE)
    import paths
    paths.bootstrap()
    import database
    import raeume
    import reembed
    import store
    import vector_columns
    from compare_search import HashEmbedder

    h = HashEmbedder(DIM)

    def model_a(text):
        return h.vector(text)

    def model_b(text):
        return h.vector(" ".join(reversed(text.split())) + " b")

    sml = store.sammlung(raeume.sammlung("allgemein"))
    ids = [f"{f}_c{i}" for i, (f, _t) in enumerate(PASSAGES)]
    store.schreibe(sml, ids, documents=[t for _f, t in PASSAGES],
                   metadatas=[{"file_name": f, "raum": "allgemein"} for f, _t in PASSAGES],
                   embeddings=[model_a(t) for _f, t in PASSAGES])

    def first_hits(model):
        found = {}
        for q, want in QUESTIONS.items():
            r = sml.query(query_embeddings=[model(q)], n_results=1)
            found[q] = r["ids"][0][0] == ids[want]
        return found

    check("model A finds every passage with its own vectors", all(first_hits(model_a).values()),
          first_hits(model_a))
    check("the column of model A is recorded",
          vector_columns.columns(refresh=True) == {"embedding": {
              "model": "hash-a", "type": database.vector_type(database.connect()),
              "dimensions": DIM}}, vector_columns.columns())

    os.environ["EMBEDDING_NEXT_MODEL"] = "hash-b"
    slot = vector_columns.prepare("hash-b")
    filled, failed = reembed.fill(slot, "hash-b", embed=lambda ts: [model_b(t) for t in ts],
                                  batch=4, say=lambda *_: None)
    check("the job computes model B for every passage, in batches",
          slot == "embedding_b" and filled == len(PASSAGES) and failed == 0, (slot, filled, failed))
    check("search still uses model A meanwhile", all(first_hits(model_a).values()))
    check("a second run has nothing left to do",
          reembed.fill(slot, "hash-b", embed=lambda ts: [model_b(t) for t in ts],
                       say=lambda *_: None) == (0, 0))

    new_text = "Die Hydraulikpumpe wird alle 250 Betriebsstunden gewartet."
    store.schreibe(sml, [ids[3]], documents=[new_text],
                   metadatas=[{"file_name": "Wartung.pdf", "raum": "allgemein"}],
                   embeddings=[model_a(new_text)])
    roles = {r["role"]: r for r in vector_columns.progress()}
    check("a passage changed meanwhile loses its stale vector of model B",
          roles["next"]["filled"] == len(PASSAGES) - 1, roles)
    got = []
    reembed.fill(slot, "hash-b", embed=lambda ts: got.extend(ts) or [model_b(t) for t in ts],
                 say=lambda *_: None)
    check("and the next run embeds its NEW text (decrypted, not the stored ciphertext)",
          got == [new_text], got)
    raw = database.connect().execute(
        "SELECT document FROM passage WHERE id = %s", (ids[3],)).fetchone()[0]
    check("the text in the table stays encrypted", "Hydraulikpumpe" not in raw, raw[:40])

    os.environ["EMBEDDING_MODEL"] = "hash-b"
    os.environ.pop("EMBEDDING_NEXT_MODEL")
    vector_columns._cache["at"] = 0.0
    check("after the switch model B finds every passage", all(first_hits(model_b).values()),
          first_hits(model_b))
    check("and writes go to its column", vector_columns.active()[0] == "embedding_b")

    os.environ["EMBEDDING_MODEL"] = "hash-c"
    try:
        sml.query(query_embeddings=[model_a("Kessel")], n_results=1)
        check("a model without vectors is refused", False)
    except vector_columns.ModelChanged:
        check("a model without vectors is refused", True)
    check("reading passages without their vectors still works",
          sml.get(ids=[ids[0]])["ids"] == [ids[0]])
    os.environ["EMBEDDING_MODEL"] = "hash-b"

    check("the vectors of model A are removed on request",
          vector_columns.drop_unused() == ["hash-a"]
          and set(vector_columns.columns(refresh=True)) == {"embedding_b"})
    check("search with model B is unaffected", all(first_hits(model_b).values()))

    os.environ["EMBEDDING_NEXT_MODEL"] = "hash-a"
    slot2 = vector_columns.prepare("hash-a")
    reembed.fill(slot2, "hash-a", embed=lambda ts: [model_a(t) for t in ts], say=lambda *_: None)
    os.environ["EMBEDDING_MODEL"] = "hash-a"
    os.environ.pop("EMBEDDING_NEXT_MODEL")
    vector_columns._cache["at"] = 0.0
    check("a further change takes the freed column again", slot2 == "embedding"
          and all(first_hits(model_a).values()), slot2)


if __name__ == "__main__":
    sys.exit(main())
