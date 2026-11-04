"""Which vector column belongs to which embedding model (Postgres only).

A passage keeps its text; its vector depends on the embedding model. To
change the model, the vectors are computed again from the stored text --
no document is read, OCRed or described again. Table passage has two
vector columns ("slots") for that:

    embedding      the vectors of one model
    embedding_b    the vectors of another one, filled in the background

Which model made which column is stored in setting 'vector_columns'.
Every process searches and writes the column of ITS model (EMBEDDING_MODEL)
-- so during a rolling update, old and new pods each stay consistent, and
there is no moment in which a question is answered with vectors of the
wrong model.

Changing the model:

    1. EMBEDDING_NEXT_MODEL=<new model> (and EMBEDDING_NEXT_BASE_URL,
       EMBEDDING_NEXT_API_KEY if it runs elsewhere), restart the worker.
    2. Start the job "Vektoren neu berechnen" (reembed.py). It fills the
       second column batch by batch, can be stopped and started again and,
       with REEMBED_HOURS, works only at night. Search keeps using the old
       model meanwhile; uploads in that time are picked up by the job.
    3. When it reports every passage done: EMBEDDING_MODEL=<new model>,
       EMBEDDING_NEXT_* removed, roll out. Run the job once more -- it
       fills what was uploaded during the rollout.
    4. The old column stays until a later change needs the slot, or
       `python reembed.py --drop-unused` frees it. Until then, going back
       is only a change of EMBEDDING_MODEL.

A model with no column of its own is refused with ModelChanged instead of
searching vectors of another model: that would answer, but with passages
that have nothing to do with the question.
"""
import json
import os
import threading
import time

import database
import llm
import paths

SLOTS = ("embedding", "embedding_b")
CACHE_SECONDS = 30

_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()


class ModelChanged(RuntimeError):
    """EMBEDDING_MODEL has no vectors in the database."""


def current_model():
    return llm.modell("EMBEDDING").strip()


def next_model():
    return os.getenv("EMBEDDING_NEXT_MODEL", "").strip()


def next_dimensions():
    return paths.env_int("EMBEDDING_NEXT_DIMENSIONS", database.DIMENSIONS)


def _read(con):
    row = con.execute("SELECT value FROM setting WHERE key = 'vector_columns'"
                      ).fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def _write(con, value):
    con.execute("INSERT INTO setting (key, value) VALUES ('vector_columns', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (json.dumps(value),))
    _cache["at"] = 0.0


def columns(refresh=False):
    """{slot: {"model", "type", "dimensions"}} of the live schema.

    An installation from before this module has one column and no record;
    its vectors were made by the model it runs with, so that is recorded.
    """
    with _lock:
        if not refresh and _cache["value"] is not None \
                and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["value"]
        con = database.connect()
        value = _read(con)
        if value is None:
            vtype, dims = database._stored_vector_settings(con)
            con.execute(
                "INSERT INTO setting (key, value) VALUES ('vector_columns', %s) "
                "ON CONFLICT (key) DO NOTHING",
                (json.dumps({"embedding": {"model": current_model(), "type": vtype,
                                           "dimensions": dims}}),))
            value = _read(con)
        _cache.update(at=time.monotonic(), value=value)
        return value


def slot_of(model):
    for slot, info in columns().items():
        if info.get("model") == model:
            return slot
    return None


def active():
    """(slot, type, dimensions) for this process's EMBEDDING_MODEL."""
    model = current_model()
    cols = columns()
    for slot, info in cols.items():
        if info.get("model") == model:
            return slot, info["type"], int(info["dimensions"])
    cols = columns(refresh=True)
    for slot, info in cols.items():
        if info.get("model") == model:
            return slot, info["type"], int(info["dimensions"])
    known = ", ".join(sorted(i.get("model", "?") for i in cols.values()))
    raise ModelChanged(
        f"EMBEDDING_MODEL is '{model}', but the stored vectors were made with "
        f"{known}. Set EMBEDDING_MODEL back, or compute the vectors for the new "
        f"model first: EMBEDDING_NEXT_MODEL={model} and the job "
        f"'Vektoren neu berechnen' (reembed.py).")


def others(slot):
    """The other columns that exist -- emptied when a passage gets a new
    vector, so the job computes them again for the new text."""
    return [s for s in columns() if s != slot]


def prepare(model, dimensions=None):
    """The column for model, created when needed. Returns the slot.

    A free slot is taken; if there is none, a slot whose model is neither
    EMBEDDING_MODEL nor EMBEDDING_NEXT_MODEL is emptied and reused.
    """
    con = database.connect()
    con.execute("SELECT pg_advisory_lock(4712)")
    try:
        cols = dict(columns(refresh=True))
        for slot, info in cols.items():
            if info.get("model") == model:
                return slot
        free = [s for s in SLOTS if s not in cols]
        if not free:
            keep = {current_model(), next_model()}
            free = [s for s, i in cols.items() if i.get("model") not in keep]
            if not free:
                raise RuntimeError("Both vector columns are in use by "
                                   "EMBEDDING_MODEL and EMBEDDING_NEXT_MODEL.")
            _drop(con, free[0], cols)
        slot = free[0]
        vtype = database.vector_type(con)
        dims = int(dimensions or next_dimensions())
        with con.transaction():
            con.execute(f"ALTER TABLE passage ADD COLUMN IF NOT EXISTS {slot} "
                        f"{vtype}({dims})")
            if dims <= database.INDEX_LIMIT[vtype]:
                con.execute(f"CREATE INDEX IF NOT EXISTS passage_{slot} ON passage "
                            f"USING hnsw ({slot} {vtype}_l2_ops)")
            cols[slot] = {"model": model, "type": vtype, "dimensions": dims}
            _write(con, cols)
        return slot
    finally:
        con.execute("SELECT pg_advisory_unlock(4712)")


def _drop(con, slot, cols):
    if slot not in SLOTS:
        raise ValueError(slot)
    with con.transaction():
        # Its index goes with it; prepare() adds column and index again,
        # with the size of the next model.
        con.execute(f"ALTER TABLE passage DROP COLUMN IF EXISTS {slot}")
        cols.pop(slot, None)
        _write(con, cols)


def drop_unused():
    """Frees columns whose model is neither EMBEDDING_MODEL nor
    EMBEDDING_NEXT_MODEL. Returns the models whose vectors were removed."""
    con = database.connect()
    keep = {current_model(), next_model()} - {""}
    cols = dict(columns(refresh=True))
    if current_model() not in {i.get("model") for i in cols.values()}:
        raise ModelChanged("EMBEDDING_MODEL has no vectors -- nothing is removed.")
    gone = []
    for slot, info in list(cols.items()):
        if info.get("model") not in keep:
            _drop(con, slot, cols)
            gone.append(info.get("model"))
    return gone


def progress():
    """[{slot, model, filled, total, role}] -- role: active, next or unused."""
    con = database.connect()
    total = con.execute("SELECT count(*) FROM passage WHERE document IS NOT NULL"
                        ).fetchone()[0]
    out = []
    for slot, info in columns(refresh=True).items():
        filled = con.execute(f"SELECT count(*) FROM passage WHERE {slot} IS NOT NULL"
                             ).fetchone()[0]
        role = ("active" if info.get("model") == current_model() else
                "next" if info.get("model") == next_model() else "unused")
        out.append({"slot": slot, "model": info.get("model"), "filled": filled,
                    "total": total, "role": role})
    return out


def adopt():
    """Declares the vectors in the active column as made by EMBEDDING_MODEL.

    Only for a renamed model (same weights, other name, e.g. a new tag on
    the model server). For a different model this makes search answer
    with wrong passages."""
    con = database.connect()
    cols = dict(columns(refresh=True))
    if len(cols) != 1:
        raise RuntimeError("Only with a single vector column.")
    (slot, info), = cols.items()
    info["model"] = current_model()
    _write(con, cols)
    return slot
