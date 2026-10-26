"""Chroma-compatible collections on Postgres + pgvector.

store.sammlung() returns one of these instead of a Chroma collection when
DATABASE_URL is set. It implements exactly what LocaNoto calls on a
collection -- add, upsert, get, query, delete, count, name -- with the
same arguments and the same result shape, so the search pipeline, the
upload path and the backups stay unchanged.

Distances are squared Euclidean, like Chroma's default ("l2") that every
LocaNoto collection was created with. The pipeline merges result lists
from several workspaces by distance, so the measure has to be the same
everywhere.

Filters (where=) support what LocaNoto uses: equality, $in, $or, $and.
Anything else raises ValueError instead of silently matching too much.
"""
import json

import database

_INCLUDE_DEFAULT = ("documents", "metadatas")


class PgCollection:
    """One collection: the rows of table passage with this name."""

    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata or {}

    # --- writing ---

    def add(self, ids, documents=None, metadatas=None, embeddings=None):
        self._write(ids, documents, metadatas, embeddings, replace=False)

    def upsert(self, ids, documents=None, metadatas=None, embeddings=None):
        self._write(ids, documents, metadatas, embeddings, replace=True)

    def _write(self, ids, documents, metadatas, embeddings, replace):
        ids = list(ids)
        if not ids:
            return
        con = database.connect()
        rows = []
        for i, pid in enumerate(ids):
            doc = documents[i] if documents is not None else None
            meta = metadatas[i] if metadatas is not None else None
            emb = embeddings[i] if embeddings is not None else None
            rows.append((pid, doc, meta, emb))
        with con.transaction():
            with con.cursor() as cur:
                for pid, doc, meta, emb in rows:
                    vec = (database.as_literal(database.shorten(emb))
                           if emb is not None else None)
                    meta_json = json.dumps(meta or {}) if meta is not None else None
                    if not replace:
                        # Chroma ignores an id that already exists (with a
                        # warning); so does this.
                        cur.execute(
                            "INSERT INTO passage (collection, id, document, "
                            "metadata, embedding) VALUES (%s, %s, %s, "
                            "COALESCE(%s::jsonb, '{}'::jsonb), %s) "
                            "ON CONFLICT (collection, id) DO NOTHING",
                            (self.name, pid, doc, meta_json, vec))
                        continue
                    # upsert: what is not given stays as it was, like Chroma
                    cur.execute(
                        "INSERT INTO passage (collection, id, document, "
                        "metadata, embedding) VALUES (%s, %s, %s, "
                        "COALESCE(%s::jsonb, '{}'::jsonb), %s) "
                        "ON CONFLICT (collection, id) DO UPDATE SET "
                        "document = COALESCE(EXCLUDED.document, passage.document), "
                        "metadata = CASE WHEN %s::jsonb IS NULL "
                        "THEN passage.metadata ELSE EXCLUDED.metadata END, "
                        "embedding = COALESCE(EXCLUDED.embedding, passage.embedding)",
                        (self.name, pid, doc, meta_json, vec, meta_json))

    # --- reading ---

    def count(self):
        return database.connect().execute(
            "SELECT count(*) FROM passage WHERE collection = %s",
            (self.name,)).fetchone()[0]

    def get(self, ids=None, where=None, limit=None, offset=None,
            include=_INCLUDE_DEFAULT, where_document=None):
        if where_document:
            raise ValueError("where_document is not supported")
        cond, args = self._conditions(ids, where)
        sql = (f"SELECT id, document, metadata, embedding FROM passage "
               f"WHERE {cond} ORDER BY id")
        if limit is not None:
            sql += " LIMIT %s"
            args.append(int(limit))
        if offset:
            sql += " OFFSET %s"
            args.append(int(offset))
        rows = database.connect().execute(sql, args).fetchall()
        return _result([rows], include, nested=False)

    def query(self, query_embeddings, n_results=10, where=None,
              include=("documents", "metadatas", "distances"),
              where_document=None):
        if where_document:
            raise ValueError("where_document is not supported")
        con = database.connect()
        vtype = database.vector_settings()["type"]
        results = []
        for q in query_embeddings:
            cond, args = self._conditions(None, where)
            vec = database.as_literal(database.shorten(q))
            sql = (f"SELECT id, document, metadata, embedding, "
                   f"(embedding <-> %s::{vtype}) ^ 2 AS distance "
                   f"FROM passage WHERE {cond} AND embedding IS NOT NULL "
                   f"ORDER BY embedding <-> %s::{vtype}, id LIMIT %s")
            rows = con.execute(sql, [vec] + args + [vec, int(n_results)]).fetchall()
            results.append(rows)
        return _result(results, include, nested=True)

    # --- deleting ---

    def delete(self, ids=None, where=None):
        if ids is None and where is None:
            raise ValueError("delete needs ids or where")
        cond, args = self._conditions(ids, where)
        database.connect().execute(f"DELETE FROM passage WHERE {cond}", args)

    # --- filters ---

    def _conditions(self, ids, where):
        parts, args = ["collection = %s"], [self.name]
        if ids is not None:
            parts.append("id = ANY(%s)")
            args.append(list(ids))
        if where:
            sql, wargs = translate_where(where)
            parts.append(sql)
            args.extend(wargs)
        return " AND ".join(parts), args


def translate_where(where):
    """A Chroma where-filter as SQL on passage.metadata. (sql, args)."""
    if not isinstance(where, dict) or not where:
        raise ValueError(f"unsupported filter: {where!r}")
    if len(where) > 1:
        return translate_where({"$and": [{k: v} for k, v in where.items()]})
    (key, value), = where.items()
    if key in ("$and", "$or"):
        parts = [translate_where(w) for w in value]
        joiner = " AND " if key == "$and" else " OR "
        return ("(" + joiner.join(p[0] for p in parts) + ")",
                [a for p in parts for a in p[1]])
    if key.startswith("$"):
        raise ValueError(f"unsupported operator: {key}")
    if isinstance(value, dict):
        (op, operand), = value.items()
        if op == "$in":
            if not operand:
                return "FALSE", []
            return ("(" + " OR ".join(["metadata @> %s::jsonb"] * len(operand))
                    + ")", [json.dumps({key: v}) for v in operand])
        if op == "$eq":
            return "metadata @> %s::jsonb", [json.dumps({key: operand})]
        raise ValueError(f"unsupported operator: {op}")
    return "metadata @> %s::jsonb", [json.dumps({key: value})]


def _vector(value):
    if value is None:
        return None
    if isinstance(value, str):
        return [float(x) for x in value.strip("[]").split(",") if x]
    return [float(x) for x in value]


def _result(groups, include, nested):
    """Rows in Chroma's result shape."""
    include = set(include or ())
    out = {"ids": [], "documents": None, "metadatas": None,
           "embeddings": None, "distances": None}
    for key in ("documents", "metadatas", "embeddings", "distances"):
        if key in include:
            out[key] = []
    for rows in groups:
        ids = [r[0] for r in rows]
        docs = [r[1] for r in rows]
        metas = [r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}")
                 for r in rows]
        embs = [_vector(r[3]) for r in rows]
        dists = [float(r[4]) for r in rows] if rows and len(rows[0]) > 4 else []
        if nested:
            out["ids"].append(ids)
            for key, values in (("documents", docs), ("metadatas", metas),
                                ("embeddings", embs), ("distances", dists)):
                if out[key] is not None:
                    out[key].append(values)
        else:
            out["ids"] = ids
            for key, values in (("documents", docs), ("metadatas", metas),
                                ("embeddings", embs)):
                if out[key] is not None:
                    out[key] = values
    return out


# --- collection management (store.namen / sammlung / loesche) ---

def get(name, create=True):
    """The collection, or None if it does not exist and create is False."""
    con = database.connect()
    row = con.execute("SELECT metadata FROM collection_info WHERE name = %s",
                      (name,)).fetchone()
    if row is None:
        if not create:
            return None
        con.execute("INSERT INTO collection_info (name) VALUES (%s) "
                    "ON CONFLICT (name) DO NOTHING", (name,))
        return PgCollection(name)
    meta = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    return PgCollection(name, meta)


def names():
    return [r[0] for r in database.connect().execute(
        "SELECT name FROM collection_info ORDER BY name")]


def drop(name):
    con = database.connect()
    with con.transaction():
        con.execute("DELETE FROM passage WHERE collection = %s", (name,))
        con.execute("DELETE FROM collection_info WHERE name = %s", (name,))
