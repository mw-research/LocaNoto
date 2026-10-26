"""Move an installation from files, SQLite and Chroma to Postgres.

    python migrate_to_postgres.py check            what is where, nothing written
    python migrate_to_postgres.py run [--overwrite]
    python migrate_to_postgres.py verify           counts source against target

Runs where the old installation runs (same volumes, same key, same
CHROMA_ settings) with DATABASE_URL pointing at the new database:

    DATABASE_URL=postgresql://... python migrate_to_postgres.py run

WHAT IT MOVES, in this order:

  1. State files under CONFIG_DIR and DATA_DIR (users, tokens, workspaces,
     room keys, chats, presets, ...) -- byte for byte, signatures and
     encryption stay valid. Only what statefiles.py manages; the key file,
     documents and backups stay where they are.
  2. Every Chroma collection with ids, documents, metadata and vectors.
     Documents and file names stay encrypted; vectors are shortened to
     DATABASE_DIMENSIONS (see database.py).
  3. The keyword index, built new from the passages (blind index, see
     pg_keywords.py). Needs the installation key to read the passages.

The old data is only read. Running it twice is safe: rows are replaced,
not duplicated. Without --overwrite it refuses to write into a database
that already holds state, so a running new installation is not
overwritten by an old copy by mistake.
"""
import argparse
import builtins
import os
import sys
import time

import database
import paths
import statefiles

BATCH = 500


def _state_files_on_disk():
    """(path, key) of every file on disk that statefiles manages."""
    out = []
    for root in (paths.CONFIG_DIR, paths.DATA_DIR):
        if not os.path.isdir(root):
            continue
        for folder, _dirs, files in os.walk(root):
            for name in files:
                p = os.path.join(folder, name)
                k = statefiles.key(p)
                if k is not None:
                    out.append((p, k))
    return sorted(out, key=lambda x: x[1])


def _chroma():
    import store
    return store.client()


def _chroma_collections():
    c = _chroma()
    names = []
    for col in c.list_collections():
        names.append(col if isinstance(col, str) else col.name)
    return sorted(names)


def _read_batch(col, offset, attempts=4):
    for n in range(attempts):
        try:
            return col.get(include=["documents", "metadatas", "embeddings"],
                           limit=BATCH, offset=offset)
        except Exception:
            if n == attempts - 1:
                raise
            time.sleep(1 + n)


def _target_counts():
    con = database.connect()
    return {
        "state_files": con.execute(
            "SELECT count(*) FROM state_file").fetchone()[0],
        "passages": dict(con.execute(
            "SELECT collection, count(*) FROM passage GROUP BY 1").fetchall()),
        "keywords": con.execute("SELECT count(*) FROM keyword").fetchone()[0],
    }


def check():
    print(f"Target:  {database.describe()}")
    s = database.vector_settings()
    print(f"         vectors {s['type']}({s['dimensions']}), "
          f"{'HNSW index' if s['indexed'] else 'no index'}")
    files = _state_files_on_disk()
    print(f"Source:  {len(files)} state files under {paths.CONFIG_DIR} "
          f"and {paths.DATA_DIR}")
    c = _chroma()
    for name in _chroma_collections():
        print(f"         collection {name}: {c.get_collection(name).count()}")
    t = _target_counts()
    print(f"Target holds: {t['state_files']} state files, "
          f"{sum(t['passages'].values())} passages, {t['keywords']} keyword rows")
    return 0


def migrate_state(overwrite):
    files = _state_files_on_disk()
    existing = database.connect().execute(
        "SELECT count(*) FROM state_file").fetchone()[0]
    if existing and not overwrite:
        raise SystemExit(f"The target already holds {existing} state files. "
                         f"Use --overwrite to replace them.")
    for p, k in files:
        with builtins.open(p, "rb") as f:
            statefiles.write(p, f.read())
    print(f"state files: {len(files)} copied")
    return len(files)


def migrate_collections():
    import pg_collection
    c = _chroma()
    total = 0
    for name in _chroma_collections():
        src = c.get_collection(name)
        n = src.count()
        dst = pg_collection.get(name, create=True)
        done = 0
        while done < n:
            b = _read_batch(src, done)
            ids = b.get("ids") or []
            if not ids:
                break
            embs = b.get("embeddings")
            dst.upsert(ids=ids, documents=b.get("documents"),
                       metadatas=b.get("metadatas"),
                       embeddings=[list(map(float, e)) for e in embs]
                       if embs is not None else None)
            done += len(ids)
            print(f"\r  {name}: {done}/{n}", end="", flush=True)
        print(f"\r  {name}: {done}/{n} copied")
        total += done
    return total


def rebuild_keywords():
    import keyword_index
    import pg_collection
    pairs = [(name[len("raum_"):], pg_collection.get(name, create=False))
             for name in pg_collection.names() if name.startswith("raum_")]

    def progress(room, done, total):
        print(f"\r  keywords {room}: {done}/{total}", end="", flush=True)
    n = keyword_index.rebuild_from_raeume(pairs, progress=progress)
    print(f"\r  keyword index: {n} passages indexed" + " " * 20)
    return n


def verify():
    c = _chroma()
    t = _target_counts()
    ok = True
    for name in _chroma_collections():
        a = c.get_collection(name).count()
        b = t["passages"].get(name, 0)
        mark = "ok" if a == b else "DIFFERENT"
        ok &= a == b
        print(f"  {name:30} source {a:>8}  target {b:>8}  {mark}")
    files = _state_files_on_disk()
    missing = [k for p, k in files if not statefiles.isfile(p)]
    print(f"  state files: {len(files) - len(missing)}/{len(files)} in target")
    for k in missing[:20]:
        print(f"    missing: {k}")
    ok &= not missing
    print("OK" if ok else "DIFFERENCES FOUND")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("check", "run", "verify"))
    ap.add_argument("--overwrite", action="store_true",
                    help="replace state files already in the target")
    a = ap.parse_args()
    if not database.active():
        print("DATABASE_URL is not set -- there is no target.")
        return 2
    if a.command == "check":
        return check()
    if a.command == "verify":
        return verify()
    migrate_state(a.overwrite)
    print(f"passages: {migrate_collections()} copied")
    rebuild_keywords()
    return verify()


if __name__ == "__main__":
    sys.exit(main())
