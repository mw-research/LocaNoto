"""Compute the vectors of every passage again -- for a new embedding model.

    python reembed.py                 fill what is missing (the job
                                      "Vektoren neu berechnen")
    python reembed.py --status        how far each model is
    python reembed.py --drop-unused   remove vectors of models no longer set
    python reembed.py --adopt         the model was only renamed: take the
                                      stored vectors as its own

Only with Postgres (DATABASE_URL). Without it, a new model means reading
the documents again ("Dokumente neu einlesen").

The text of every passage is stored (encrypted per workspace), and it is
exactly the text that was embedded. So a new model needs no PDF, no OCR
and no image description -- only the embedding calls, which are the cheap
part. How the columns and the switch work: vector_columns.py.

The job fills, for EMBEDDING_MODEL and EMBEDDING_NEXT_MODEL, every passage
that has no vector of that model yet, in batches of REEMBED_BATCH. It is
safe to stop: the next run continues where this one stopped. Passages
that change while it runs are written with the vector of the running
model and an empty one of the other; a later run fills those.

Load on the model server: REEMBED_PAUSE seconds between batches, and
REEMBED_HOURS (e.g. 20-6) lets it work only in that window -- outside it
the job waits. EMBED_PARALLEL and EMBED_BATCH_SIZE apply as in the ingest.
"""
import argparse
import datetime
import os
import sys
import time

import paths

paths.bootstrap()

import database  # noqa: E402
import llm  # noqa: E402
import store  # noqa: E402
import vector_columns  # noqa: E402
from embedding import embed_batch  # noqa: E402

BATCH = paths.env_int("REEMBED_BATCH", 256)
PAUSE = paths.env_float("REEMBED_PAUSE", 0)
HOURS = os.getenv("REEMBED_HOURS", "").strip()


def window(hours=HOURS, now=None):
    """True when the job may work now. "20-6" spans midnight; empty: always."""
    if not hours:
        return True
    try:
        start, end = (int(x) for x in hours.split("-", 1))
    except ValueError:
        print(f"REEMBED_HOURS='{hours}' is not 'from-to' (e.g. 20-6); ignored.")
        return True
    h = (now or datetime.datetime.now()).hour
    return start <= h < end if start < end else (h >= start or h < end)


def _wait_for_window():
    told = False
    while not window():
        if not told:
            print(f"Outside REEMBED_HOURS ({HOURS}) -- waiting.", flush=True)
            told = True
        time.sleep(60)


def _client_for(model):
    """Client of the task that serves this model."""
    if model == vector_columns.next_model() and model != vector_columns.current_model():
        task = "EMBEDDING_NEXT" if os.getenv("EMBEDDING_NEXT_BASE_URL", "").strip() \
            else "EMBEDDING"
        return llm.client(task)
    return llm.client("EMBEDDING")


def fill(slot, model, client=None, embed=None, batch=None, pause=None, say=print):
    """Gives every passage without a vector in slot one from model.

    Returns (filled, failed). Keyset order (collection, id), one pass; rows
    that fail are skipped in this pass and tried again in the next run.
    """
    con = database.connect()
    client = client or _client_for(model)
    embed = embed or (lambda texts: embed_batch(client, texts, model))
    batch = batch or BATCH
    pause = PAUSE if pause is None else pause
    dims = int(vector_columns.columns(refresh=True)[slot]["dimensions"])
    vtype = vector_columns.columns()[slot]["type"]
    last = ("", "")
    filled = failed = 0
    total = con.execute(f"SELECT count(*) FROM passage WHERE {slot} IS NULL "
                        "AND document IS NOT NULL").fetchone()[0]
    say(f"{model}: {total} passages without a vector.")
    while True:
        _wait_for_window()
        rows = con.execute(
            f"SELECT collection, id, document FROM passage WHERE {slot} IS NULL "
            "AND document IS NOT NULL AND (collection, id) > (%s, %s) "
            "ORDER BY collection, id LIMIT %s", (last[0], last[1], batch)).fetchall()
        if not rows:
            break
        last = (rows[-1][0], rows[-1][1])
        texts, keep = [], []
        for collection, pid, doc in rows:
            room = collection[len(store.VORSILBE_RAUM):] \
                if collection.startswith(store.VORSILBE_RAUM) else ""
            try:
                text = store.klartext(room, [doc], benutzer="reembed", wartung=True)[0]
            except Exception as e:
                failed += 1
                say(f"   [!] {collection}/{pid}: not readable ({type(e).__name__})")
                continue
            texts.append(text)
            keep.append((collection, pid, doc))
        vectors = embed(texts) if texts else []
        with con.transaction():
            for (collection, pid, doc), vec in zip(keep, vectors):
                if vec is None:
                    failed += 1
                    continue
                # Only if the text is still the one embedded.
                cur = con.execute(
                    f"UPDATE passage SET {slot} = %s::{vtype} WHERE collection = %s "
                    f"AND id = %s AND document = %s AND {slot} IS NULL",
                    (database.as_literal(database.shorten(vec, dims)),
                     collection, pid, doc))
                filled += cur.rowcount
        say(f"   {filled}/{total}" + (f", {failed} failed" if failed else ""), )
        if pause:
            time.sleep(pause)
    return filled, failed


def status(say=print):
    rows = vector_columns.progress()
    for r in rows:
        say(f"{r['role']:<7} {r['model']:<40} {r['filled']}/{r['total']}"
            f" ({r['slot']})")
    return rows


def run(say=print):
    current, upcoming = vector_columns.current_model(), vector_columns.next_model()
    vector_columns.active()  # refuses a model without vectors
    if upcoming and upcoming != current:
        vector_columns.prepare(upcoming)
    failed = 0
    for model in [current] + ([upcoming] if upcoming and upcoming != current else []):
        slot = vector_columns.slot_of(model)
        failed += fill(slot, model, say=say)[1]
    rows = status(say)
    nxt = [r for r in rows if r["role"] == "next"]
    if nxt and nxt[0]["filled"] >= nxt[0]["total"]:
        say(f"\nEvery passage has a vector of {upcoming}. Next: set "
            f"EMBEDDING_MODEL={upcoming} (with its address and key), remove "
            f"EMBEDDING_NEXT_*, roll out, and run this job once more.")
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--drop-unused", action="store_true")
    ap.add_argument("--adopt", action="store_true")
    a = ap.parse_args(argv)
    if not database.active():
        print("Only with Postgres (DATABASE_URL). Without it a new embedding "
              "model means reading the documents again (ingest.py).")
        return 1
    try:
        if a.status:
            status()
            return 0
        if a.adopt:
            print(f"Column {vector_columns.adopt()} now counts as "
                  f"{vector_columns.current_model()}.")
            return 0
        if a.drop_unused:
            gone = vector_columns.drop_unused()
            print("Removed: " + (", ".join(gone) if gone else "nothing"))
            return 0
        return 1 if run() else 0
    except vector_columns.ModelChanged as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
