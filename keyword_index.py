"""Plattenbasierter Keyword-Index auf SQLite FTS5.

Ersetzt den In-Memory-BM25 (rank_bm25). Der hielt den gesamten Korpus im
Arbeitsspeicher und legte pro Chunk ein dict in BM25Okapi.doc_freqs an --
bei rund 324.000 Chunks (Hochrechnung fuer 1,6 GB PDF) sind das 8-15 GB RAM,
die bei jedem Start neu aufgebaut werden muessen.

FTS5 liegt auf der Platte, wird beim Ingest geschrieben und live abgefragt.
Damit entfaellt zugleich der Cache-Invalidierungsfehler: der alte Index war
mit @st.cache_resource eingefroren, sodass frisch hochgeladene Dokumente bis
zum Neustart nicht keyword-suchbar waren und geloeschte weiterhin
auftauchten.

Kein Stemming -- genau wie der bisherige Tokenizer re.findall(r'\w+'), also
keine Regression. Fuer deutsche Komposita gleicht die Praefix-Suche das
teilweise aus ("Toleranz*" findet "Toleranzen", "Toleranzangaben").
"""
import os
import re
import sqlite3

import paths

DB_PATH = os.path.join(paths.DATA_DIR, "keyword_index.sqlite3")

# Ab dieser Laenge wird ein Suchbegriff als Praefix gesucht. Kuerzere Begriffe
# ergaeben zu unspezifische Treffer ("der*", "und*").
_PREFIX_MIN_LEN = 5

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    chunk_id  UNINDEXED,
    file_name UNINDEXED,
    page      UNINDEXED,
    access    UNINDEXED,
    owner     UNINDEXED,
    folder    UNINDEXED,
    doc_type  UNINDEXED,
    text,
    tokenize = "unicode61 remove_diacritics 2"
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # WAL: Leser blockieren einander und den Schreiber nicht.
    con.execute("PRAGMA journal_mode=WAL")
    # Ohne Wartezeit bricht ein gleichzeitiger Schreibzugriff sofort mit
    # "database is locked" ab, statt kurz zu warten. Sobald neben der
    # Oberflaeche ein zweiter Prozess arbeitet -- die Schnittstelle, ein
    # laufender Ingest --, trifft das sonst irgendwann zu.
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(_SCHEMA)
    return con


def count(con=None):
    own = con is None
    con = con or connect()
    try:
        return con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    finally:
        if own:
            con.close()


def add_chunks(rows, con=None):
    """rows: Iterable von (chunk_id, text, metadata-dict)."""
    own = con is None
    con = con or connect()
    try:
        payload = []
        for chunk_id, text, meta in rows:
            meta = meta or {}
            payload.append((
                chunk_id,
                meta.get("file_name", ""),
                str(meta.get("page", "")),
                meta.get("access", "shared"),
                meta.get("owner", ""),
                meta.get("folder", ""),
                meta.get("type", ""),
                text or "",
            ))
        if not payload:
            return 0
        con.executemany(
            "INSERT INTO chunks (chunk_id, file_name, page, access, owner, "
            "folder, doc_type, text) VALUES (?,?,?,?,?,?,?,?)", payload)
        con.commit()
        return len(payload)
    finally:
        if own:
            con.close()


def delete_document(file_name, access=None, owner=None, con=None):
    """Entfernt Eintraege eines Dokuments. Spiegelt die Filter der
    Chroma-Loeschung, damit beide Indizes deckungsgleich bleiben."""
    own = con is None
    con = con or connect()
    try:
        sql = "DELETE FROM chunks WHERE file_name = ?"
        args = [file_name]
        if access is not None:
            sql += " AND access = ?"
            args.append(access)
        if owner is not None:
            sql += " AND owner = ?"
            args.append(owner)
        con.execute(sql, args)
        con.commit()
    finally:
        if own:
            con.close()


def set_access(file_name, owner, new_access, con=None):
    """Haelt den Index nach einer Freigabe aktuell."""
    own = con is None
    con = con or connect()
    try:
        con.execute("UPDATE chunks SET access = ? WHERE file_name = ? AND owner = ?",
                    (new_access, file_name, owner))
        con.commit()
    finally:
        if own:
            con.close()


def build_match_query(text):
    """Baut aus freiem Text einen sicheren FTS5-MATCH-Ausdruck.

    Jeder Begriff wird in Anfuehrungszeichen gesetzt, damit FTS5-Operatoren
    im Nutzertext (AND, OR, NOT, NEAR, *, ^, :) nicht als Syntax gedeutet
    werden und keine Fehler ausloesen.
    """
    terms = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    if not terms:
        return None
    parts = []
    for t in terms:
        if len(t) >= _PREFIX_MIN_LEN:
            parts.append('"%s"*' % t.replace('"', ""))
        else:
            parts.append('"%s"' % t.replace('"', ""))
    return " OR ".join(parts)


def search(query_text, username, limit=5, file_names=None, folders=None, con=None):
    """BM25-gerankte Keyword-Suche mit Rechtefilter.

    Der Rechtefilter laeuft in SQL statt wie bisher nachtraeglich in Python.
    Dort war er auf meta.get('access', 'shared') angewiesen -- Chunks ohne
    access-Key galten damit als oeffentlich.
    """
    match = build_match_query(query_text)
    if not match:
        return []

    own = con is None
    con = con or connect()
    try:
        sql = ["SELECT chunk_id, file_name, page, access, owner, folder, "
               "doc_type, text, bm25(chunks) AS score FROM chunks "
               "WHERE chunks MATCH ? AND (access = 'shared' OR owner = ?)"]
        args = [match, username]

        if file_names:
            sql.append("AND file_name IN (%s)" % ",".join("?" * len(file_names)))
            args.extend(file_names)
        if folders:
            sql.append("AND folder IN (%s)" % ",".join("?" * len(folders)))
            args.extend(folders)

        # bm25() liefert negative Werte, kleiner ist besser.
        sql.append("ORDER BY score LIMIT ?")
        args.append(limit)

        out = []
        for r in con.execute(" ".join(sql), args):
            out.append({
                "chunk_id": r[0],
                "text": r[7],
                "score": r[8],
                "meta": {"file_name": r[1], "page": _as_int(r[2]),
                         "access": r[3], "owner": r[4],
                         "folder": r[5], "type": r[6]},
            })
        return out
    except sqlite3.OperationalError:
        # Unbrauchbarer MATCH-Ausdruck -- lieber keine Keyword-Treffer als
        # eine gescheiterte Anfrage. Die Vektorsuche laeuft weiter.
        return []
    finally:
        if own:
            con.close()


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def rebuild_from_collection(collection, batch_size=5000, progress=None):
    """Baut den Index vollstaendig aus einer bestehenden ChromaDB neu auf.

    Fuer Installationen, deren Vektordatenbank aelter ist als dieser Index.
    """
    con = connect()
    try:
        con.execute("DELETE FROM chunks")
        con.commit()

        total = collection.count()
        done = 0
        while done < total:
            batch = collection.get(include=["documents", "metadatas"],
                                   limit=batch_size, offset=done)
            ids = batch.get("ids") or []
            if not ids:
                break
            add_chunks(zip(ids, batch.get("documents") or [],
                           batch.get("metadatas") or []), con=con)
            done += len(ids)
            if progress:
                progress(done, total)
        return done
    finally:
        con.close()
