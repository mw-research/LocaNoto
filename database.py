"""Postgres connection and schema -- the shared store of the enterprise edition.

Active when DATABASE_URL is set; without it LocaNoto keeps its files,
SQLite and Chroma as before. Nothing else changes for small installations.

    DATABASE_URL=postgresql://locanoto:secret@postgres:5432/locanoto
    DATABASE_DIMENSIONS=2048

WHY POSTGRES. Several application pods can only run side by side if no
state lives on a volume that only one of them can mount. Postgres holds
vectors (pgvector), full text (tsvector) and, step by step, everything else
that lives in files today. Backups, replication and permissions are what
every IT department already knows.

VECTOR SIZE. pgvector indexes at most 2000 dimensions as `vector` and 4000
as `halfvec` (pgvector >= 0.7). qwen3-embedding:8b delivers 4096.
Qwen3-Embedding is trained for shortened vectors (Matryoshka): the first n
values, normalised again, are a valid embedding. DATABASE_DIMENSIONS sets n
once, when the schema is created; every vector written or searched is
shortened to it (shorten()). Changing it later needs a new schema.

CONNECTIONS. One connection per thread, kept and checked before use.
Streamlit runs every session in its own thread; a shared connection would
interleave their statements.

    python database.py --check     connect, migrate, print the state
"""
import json
import math
import os
import sys
import threading

import paths

URL = os.getenv("DATABASE_URL", "").strip()
DIMENSIONS = paths.env_int("DATABASE_DIMENSIONS", 2048)

# Largest dimension pgvector can index with HNSW, by type.
INDEX_LIMIT = {"vector": 2000, "halfvec": 4000}

_local = threading.local()
_schema_lock = threading.Lock()
_schema_ready = set()


def active():
    """Is the enterprise store configured?"""
    return bool(URL)


def connect():
    """The connection of this thread, autocommit, created on first use."""
    import psycopg
    con = getattr(_local, "con", None)
    if con is not None and not con.closed:
        try:
            con.execute("SELECT 1")
            return con
        except psycopg.Error:
            try:
                con.close()
            except psycopg.Error:
                pass
    con = psycopg.connect(URL, autocommit=True)
    _local.con = con
    migrate(con)
    return con


def close():
    """Close the connection of this thread (tests, shutdown)."""
    con = getattr(_local, "con", None)
    if con is not None:
        try:
            con.close()
        finally:
            _local.con = None


# --- VECTORS ---

def pgvector_version(con):
    row = con.execute("SELECT extversion FROM pg_extension "
                      "WHERE extname = 'vector'").fetchone()
    return tuple(int(x) for x in row[0].split(".")[:2]) if row else (0, 0)


def vector_type(con):
    """halfvec where pgvector supports it, otherwise vector."""
    return "halfvec" if pgvector_version(con) >= (0, 7) else "vector"


def shorten(vector, dimensions=None):
    """The first n values, normalised to length 1 (Matryoshka).

    A shorter vector is passed through unchanged -- the schema then
    rejects it, which is the right place for that error.
    """
    n = dimensions or DIMENSIONS
    v = [float(x) for x in vector]
    if len(v) <= n:
        return v
    v = v[:n]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def as_literal(vector):
    """pgvector text form: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


# --- SCHEMA ---
#
# Versions are applied in order and recorded in schema_version. A version
# is never edited after it was released -- a change is a new version.

def _versions(vtype, dims):
    index_ok = dims <= INDEX_LIMIT[vtype]
    ops = f"{vtype}_l2_ops"
    return [
        (1, [
            "CREATE EXTENSION IF NOT EXISTS vector",
            "CREATE TABLE IF NOT EXISTS setting ("
            " key text PRIMARY KEY, value jsonb NOT NULL)",
            # One row per passage. collection is the Chroma collection name
            # (raum_<id>), so every caller keeps working unchanged.
            f"CREATE TABLE IF NOT EXISTS passage ("
            f" collection text NOT NULL,"
            f" id text NOT NULL,"
            f" document text,"
            f" metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,"
            f" embedding {vtype}({dims}),"
            f" PRIMARY KEY (collection, id))",
            "CREATE INDEX IF NOT EXISTS passage_metadata "
            "ON passage USING gin (metadata jsonb_path_ops)",
            "CREATE TABLE IF NOT EXISTS collection_info ("
            " name text PRIMARY KEY,"
            " metadata jsonb NOT NULL DEFAULT '{}'::jsonb)",
            # The keyword index: a blind index, hashed terms only. The
            # text of a hit comes from passage (see pg_keywords.py).
            "CREATE TABLE IF NOT EXISTS keyword ("
            " collection text NOT NULL,"
            " chunk_id text NOT NULL,"
            " room text NOT NULL DEFAULT '',"
            " file_key text NOT NULL DEFAULT '',"
            " access text NOT NULL DEFAULT 'shared',"
            " owner text NOT NULL DEFAULT '',"
            " lexemes tsvector NOT NULL,"
            " PRIMARY KEY (collection, chunk_id))",
            "CREATE INDEX IF NOT EXISTS keyword_lexemes "
            "ON keyword USING gin (lexemes)",
            "CREATE INDEX IF NOT EXISTS keyword_room ON keyword (room)",
            "CREATE INDEX IF NOT EXISTS keyword_file ON keyword (file_key)",
        ] + ([f"CREATE INDEX IF NOT EXISTS passage_embedding "
              f"ON passage USING hnsw (embedding {ops})"] if index_ok else [])),
        (2, [
            # Config and runtime state that lived in files (statefiles.py).
            "CREATE TABLE IF NOT EXISTS state_file ("
            " path text PRIMARY KEY,"
            " content bytea NOT NULL,"
            " updated timestamptz NOT NULL DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS state_file_prefix "
            "ON state_file (path text_pattern_ops)",
        ]),
        (3, [
            # Counters for rate limits (sessions.py), shared by all pods.
            "CREATE TABLE IF NOT EXISTS rate_limit ("
            " bucket text PRIMARY KEY,"
            " hits int NOT NULL,"
            " expires timestamptz NOT NULL)",
        ]),
        (4, [
            # Background jobs (jobs.py, worker.py).
            "CREATE TABLE IF NOT EXISTS job ("
            " id bigserial PRIMARY KEY,"
            " name text NOT NULL,"
            " state text NOT NULL DEFAULT 'queued',"
            " requested_by text NOT NULL DEFAULT '',"
            " cancelled_by text,"
            " worker text,"
            " created timestamptz NOT NULL DEFAULT now(),"
            " started timestamptz,"
            " finished timestamptz,"
            " heartbeat timestamptz,"
            " exit_code int,"
            " log text NOT NULL DEFAULT '')",
            "CREATE INDEX IF NOT EXISTS job_state ON job (state, id)",
            "CREATE INDEX IF NOT EXISTS job_name ON job (name, id)",
        ]),
    ]


def migrate(con):
    """Bring the schema up to date. Safe to call often."""
    if URL in _schema_ready:
        return
    with _schema_lock:
        if URL in _schema_ready:
            return
        con.execute("CREATE EXTENSION IF NOT EXISTS vector")
        con.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                    " version int PRIMARY KEY,"
                    " applied timestamptz NOT NULL DEFAULT now())")
        # One process migrates at a time, across pods.
        con.execute("SELECT pg_advisory_lock(4711)")
        try:
            done = {r[0] for r in
                    con.execute("SELECT version FROM schema_version")}
            vtype, dims = _stored_vector_settings(con)
            for version, statements in _versions(vtype, dims):
                if version in done:
                    continue
                with con.transaction():
                    for sql in statements:
                        con.execute(sql)
                    con.execute("INSERT INTO schema_version (version) "
                                "VALUES (%s)", (version,))
                    con.execute(
                        "INSERT INTO setting (key, value) VALUES "
                        "('vector', %s) ON CONFLICT (key) DO NOTHING",
                        (json.dumps({"type": vtype, "dimensions": dims}),))
        finally:
            con.execute("SELECT pg_advisory_unlock(4711)")
        _schema_ready.add(URL)


def _stored_vector_settings(con):
    """(type, dimensions) of an existing schema, or of a new one.

    Fixed at creation: a later DATABASE_DIMENSIONS cannot change a column
    that already holds vectors, so the stored setting wins and a mismatch
    is reported by vector_settings().
    """
    try:
        row = con.execute("SELECT value FROM setting "
                          "WHERE key = 'vector'").fetchone()
    except Exception:
        row = None
    if row:
        value = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return value["type"], int(value["dimensions"])
    vtype = vector_type(con)
    return vtype, DIMENSIONS


def vector_settings():
    """{"type", "dimensions", "indexed", "configured"} of the live schema."""
    con = connect()
    vtype, dims = _stored_vector_settings(con)
    return {"type": vtype, "dimensions": dims,
            "indexed": dims <= INDEX_LIMIT[vtype],
            "configured": DIMENSIONS}


def describe():
    """Where the data lives -- for display. Never the password."""
    if not active():
        return ""
    from urllib.parse import urlsplit
    u = urlsplit(URL)
    return f"Postgres {u.hostname}:{u.port or 5432}{u.path}"


def main():
    if "--check" in sys.argv:
        if not active():
            print("DATABASE_URL is not set.")
            return 1
        connect()
        s = vector_settings()
        print(describe())
        print(f"vectors: {s['type']}({s['dimensions']}), "
              f"{'indexed (HNSW)' if s['indexed'] else 'NOT indexed'}")
        if s["dimensions"] != s["configured"]:
            print(f"note: DATABASE_DIMENSIONS={s['configured']}, schema "
                  f"was created with {s['dimensions']}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
