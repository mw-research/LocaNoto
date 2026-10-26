"""Keyword search on Postgres -- the enterprise counterpart of keyword_index.

keyword_index.py hands every call over to this module when DATABASE_URL is
set. Same functions, same arguments, same result shape.

NO PLAIN TEXT IN THE DATABASE. The SQLite index holds plain text and is
therefore kept on container-local storage, away from the encrypted
passages (see raumschluessel.py). A Postgres table is shared storage, so
the same index there would put plain text next to the cipher text. This
one is a blind index instead:

  * every term is stored as a keyed hash (HMAC) under a key derived from
    the room key -- the same word gives different tokens in different
    rooms, and nothing is readable without the room key;
  * the text of a hit is not stored here at all; it comes from the
    encrypted passage (table passage) and is decrypted for the answer;
  * file names are stored as raumschluessel.datei_id, never in clear.

What it still reveals: how often a token occurs and which passages share
one. Someone with the database and a good guess of the corpus could try
frequency analysis. That is far less than plain text, and it is the
price of searching without the key at hand in the database.

Matching follows the SQLite FTS5 index it replaces: no stemming, accents
removed, every term ORed, terms of five letters or more also as prefix
("Toleranz" finds "Toleranzen"). Prefixes cannot be matched on hashes,
so every word of five letters or more is stored with each of its
prefixes from five letters on. Ranking uses ts_rank_cd instead of BM25;
compare_search.py measures whether that changes results.
"""
import hashlib
import hmac
import re
import unicodedata

import database

PREFIX_MIN_LEN = 5
# Longer words are indexed and searched by their first 32 letters. Keeps
# compound words from producing dozens of prefix tokens each.
MAX_TERM_LEN = 32
# Without an installation key nothing is encrypted anyway; tokens are then
# hashed with this fixed key so both cases share one code path.
_PLAIN_KEY = b"locanoto-keyword-index"
_TOKEN_CONTEXT = b"keyword-index:v1"
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

def fold(text):
    """Lower case without diacritics -- what FTS5 'remove_diacritics 2' does."""
    nfkd = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def terms(text):
    """The words of a text as FTS5 unicode61 would split them."""
    return [t[:MAX_TERM_LEN] for t in _WORD.findall(fold(text))]


def _token_key(room, create):
    # Not cached here: raumschluessel caches the room key and forgets it
    # when a room is removed; a second cache would outlive that.
    import raumschluessel
    room_key = (raumschluessel.schluessel(room, anlegen=create)
                if room and raumschluessel.verfuegbar() else None)
    return hmac.new(room_key or _PLAIN_KEY, _TOKEN_CONTEXT,
                    hashlib.sha256).digest()


def _token(key, kind, term):
    return hmac.new(key, (kind + term).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def document_vector(room, text):
    """tsvector literal of a passage: hashed words and prefixes, with positions."""
    key = _token_key(room, create=True)
    positions = {}
    for pos, word in enumerate(terms(text), start=1):
        pos = min(pos, 16383)  # Postgres' limit for positions
        if len(word) < PREFIX_MIN_LEN:
            tokens = [_token(key, "w:", word)]
        else:
            tokens = [_token(key, "p:", word[:n])
                      for n in range(PREFIX_MIN_LEN, len(word) + 1)]
        for t in tokens:
            positions.setdefault(t, []).append(pos)
    return " ".join(f"'{t}':" + ",".join(map(str, p[:256]))
                    for t, p in positions.items())


def query_for(room, text):
    """tsquery string for one room, or None if the text has no words."""
    words = terms(text)
    if not words:
        return None
    key = _token_key(room, create=False)
    tokens = []
    for w in words:
        tokens.append(_token(key, "w:", w) if len(w) < PREFIX_MIN_LEN
                      else _token(key, "p:", w))
    return " | ".join(f"'{t}'" for t in dict.fromkeys(tokens))


def file_key(name):
    """What the index stores instead of a file name."""
    import raumschluessel
    return raumschluessel.datei_id(name) or str(name or "").strip().lower()


def _collection(room):
    import raeume
    return raeume.sammlung(room)


# --- WRITING ---

def count():
    return database.connect().execute(
        "SELECT count(*) FROM keyword").fetchone()[0]


def reset():
    database.connect().execute("TRUNCATE keyword")


def add_chunks(rows, readable_name):
    """rows: (chunk_id, text, metadata). readable_name(meta) -> file name."""
    payload = []
    for chunk_id, text, meta in rows:
        meta = meta or {}
        room = meta.get("raum", "") or ""
        payload.append((_collection(room), chunk_id, room,
                        file_key(readable_name(meta)),
                        meta.get("access", "shared"), meta.get("owner", ""),
                        document_vector(room, text)))
    if not payload:
        return 0
    con = database.connect()
    with con.transaction():
        with con.cursor() as cur:
            cur.executemany(
                "INSERT INTO keyword (collection, chunk_id, room, file_key, "
                "access, owner, lexemes) VALUES (%s, %s, %s, %s, %s, %s, "
                "%s::tsvector) ON CONFLICT (collection, chunk_id) DO UPDATE "
                "SET room = EXCLUDED.room, file_key = EXCLUDED.file_key, "
                "access = EXCLUDED.access, owner = EXCLUDED.owner, "
                "lexemes = EXCLUDED.lexemes", payload)
    return len(payload)


def delete_document(file_name, access=None, owner=None, room=None):
    sql, args = ["DELETE FROM keyword WHERE file_key = %s"], [file_key(file_name)]
    for column, value in (("access", access), ("owner", owner),
                          ("room", room)):
        if value is not None:
            sql.append(f"AND {column} = %s")
            args.append(value)
    database.connect().execute(" ".join(sql), args)


def delete_by_room(room):
    database.connect().execute("DELETE FROM keyword WHERE room = %s", (room,))


def set_access(file_name, owner, new_access):
    database.connect().execute(
        "UPDATE keyword SET access = %s WHERE file_key = %s AND owner = %s",
        (new_access, file_key(file_name), owner))


# --- READING ---

def rows_per_room():
    """[(room, rows)] -- for diagnostics."""
    return database.connect().execute(
        "SELECT COALESCE(NULLIF(room, ''), '(leer)'), count(*) FROM keyword "
        "GROUP BY 1 ORDER BY 2 DESC").fetchall()


def rows_for_file(file_name):
    return database.connect().execute(
        "SELECT count(*) FROM keyword WHERE file_key = %s",
        (file_key(file_name),)).fetchone()[0]


def search(query_text, username, limit=5, file_names=None, rooms=None):
    """Ranked keyword search with the same permission filter as FTS5."""
    con = database.connect()
    access_filter = rooms is None
    if rooms is None:
        rooms = [r[0] for r in con.execute(
            "SELECT DISTINCT room FROM keyword WHERE room <> ''")]
    rooms = [r for r in rooms if r]
    if not rooms:
        return []  # no rooms means no access, not no filter
    pairs = [(r, q) for r in rooms for q in [query_for(r, query_text)] if q]
    if not pairs:
        return []
    sql = ["SELECT k.room, k.chunk_id, k.access, k.owner, p.document, "
           "p.metadata, ts_rank_cd(k.lexemes, q.query::tsquery) AS score "
           "FROM unnest(%s::text[], %s::text[]) AS q(room, query) "
           "JOIN keyword k ON k.room = q.room "
           "AND k.lexemes @@ q.query::tsquery "
           "JOIN passage p ON p.collection = k.collection AND p.id = k.chunk_id"]
    args = [[r for r, _ in pairs], [q for _, q in pairs]]
    if access_filter:
        sql.append("WHERE (k.access = 'shared' OR k.owner = %s)")
        args.append(username)
    if file_names:
        sql.append("AND" if access_filter else "WHERE")
        sql.append("k.file_key = ANY(%s)")
        args.append([file_key(n) for n in file_names])
    sql.append("ORDER BY score DESC, k.chunk_id LIMIT %s")
    args.append(int(limit))

    import raumschluessel
    import store
    out = []
    for room, chunk_id, access, owner, document, meta, score in \
            con.execute(" ".join(sql), args):
        try:
            text = raumschluessel.entschluessele_text(room, document)
        except Exception:
            continue  # a passage that cannot be opened is no hit
        meta = store.metadaten_klartext(room, [meta or {}])[0]
        out.append({
            "chunk_id": chunk_id, "text": text or "",
            # FTS5's bm25() is negative, smaller is better; callers sort
            # on that. ts_rank_cd is positive, larger is better.
            "score": -float(score),
            "meta": {"file_name": meta.get("file_name", ""),
                     "page": _as_int(meta.get("page", "")),
                     "access": access, "owner": owner,
                     "folder": meta.get("folder", ""),
                     "type": meta.get("type", ""), "raum": room},
        })
    return out


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v
