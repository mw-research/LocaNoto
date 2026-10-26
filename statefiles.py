"""State files: config and runtime state, on disk or in Postgres.

Users, workspaces, tokens, chats, presets, instructions, feedback, the
emergency-access state, the storage sync state -- every module keeps its
state in small files under CONFIG_DIR and DATA_DIR. Several application
pods cannot share those: a volume that every pod can mount (NFS, SMB) has
no locking that dateisperre.py could rely on.

With DATABASE_URL set, the files listed below live in the Postgres table
state_file instead, one row per path. The modules keep their logic and
call this module instead of open() and os.*:

    with statefiles.open(DATEI, "r", encoding="utf-8") as f: ...
    statefiles.exists(p), listdir(d), remove(p), rename(a, b), getmtime(p)

and dateisperre.schreibe_atomar / gesperrt switch over by themselves:
a write is one statement (atomic), a lock is a Postgres advisory lock,
held across pods.

WHAT STAYS ON DISK, on purpose:

  * the installation key (config/schluessel.key). The database must not
    hold the key to what it stores; on Kubernetes the key comes from a
    Secret (LOCANOTO_SCHLUESSEL).
  * uploaded documents (data/dokumente). Written once, read often, and
    large -- a shared volume serves them without locking, or OpenCloud.
  * backups (data/sicherungen) and everything under INDEX_DIR: derived,
    per pod.

Without DATABASE_URL every function is the plain file operation, so the
modules run the same code either way.
"""
import builtins
import contextlib
import hashlib
import io
import os

import database
import paths

# DATA_DIR entries that are state. Everything else under DATA_DIR stays
# on disk (documents, backups, the derived index if INDEX_DIR is unset).
DATA_STATE = ("chats", "anweisungen", "owncloud", "benutzer.log",
              "owncloud_gruppen.json", "feedback")

# Files under CONFIG_DIR that stay on disk.
_CONFIG_LOCAL = ("schluessel.key",)


def key(path):
    """The database key of a managed path ("config/...", "data/..."), else None."""
    if not database.active():
        return None
    p = os.path.abspath(path)
    for root, prefix in ((paths.CONFIG_DIR, "config"), (paths.DATA_DIR, "data")):
        root = os.path.abspath(root)
        if p == root or not p.startswith(root + os.sep):
            continue
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        first = rel.split("/", 1)[0]
        if rel.endswith(".sperre"):
            return None
        if prefix == "config" and rel in _CONFIG_LOCAL:
            return None
        if prefix == "data" and not any(
                first == s or first.startswith(s) for s in DATA_STATE):
            return None
        index = os.path.abspath(paths.INDEX_DIR)
        if p == index or p.startswith(index + os.sep):
            if index != root:
                return None
        return f"{prefix}/{rel}"
    return None


def _dir_key(path):
    """Key prefix for a managed directory ("data/chats/anna/")."""
    if not database.active():
        return None
    k = key(os.path.join(path, "x"))
    return k[:-1] if k else None


# --- READING ---

def read_bytes(path):
    k = key(path)
    if k is None:
        with builtins.open(path, "rb") as f:
            return f.read()
    row = database.connect().execute(
        "SELECT content FROM state_file WHERE path = %s", (k,)).fetchone()
    if row is None:
        raise FileNotFoundError(2, "No such file", path)
    return bytes(row[0])


def read_text(path, encoding="utf-8", errors="strict"):
    return read_bytes(path).decode(encoding, errors)


def exists(path):
    k = key(path)
    if k is None:
        return os.path.exists(path)
    con = database.connect()
    if con.execute("SELECT 1 FROM state_file WHERE path = %s", (k,)).fetchone():
        return True
    return isdir(path)


def isfile(path):
    k = key(path)
    if k is None:
        return os.path.isfile(path)
    return database.connect().execute(
        "SELECT 1 FROM state_file WHERE path = %s", (k,)).fetchone() is not None


def isdir(path):
    prefix = _dir_key(path)
    if prefix is None:
        return os.path.isdir(path)
    return database.connect().execute(
        "SELECT 1 FROM state_file WHERE path LIKE %s LIMIT 1",
        (_like(prefix) + "%",)).fetchone() is not None


def listdir(path):
    """Names in a directory, like os.listdir. Directories exist implicitly."""
    prefix = _dir_key(path)
    if prefix is None:
        return os.listdir(path)
    rows = database.connect().execute(
        "SELECT DISTINCT split_part(substr(path, %s), '/', 1) FROM state_file "
        "WHERE path LIKE %s", (len(prefix) + 1, _like(prefix) + "%"))
    names = sorted(r[0] for r in rows if r[0])
    if not names and not os.path.isdir(path):
        raise FileNotFoundError(2, "No such directory", path)
    return names


def getmtime(path):
    k = key(path)
    if k is None:
        return os.path.getmtime(path)
    row = database.connect().execute(
        "SELECT extract(epoch FROM updated) FROM state_file WHERE path = %s",
        (k,)).fetchone()
    if row is None:
        raise FileNotFoundError(2, "No such file", path)
    return float(row[0])


def getsize(path):
    k = key(path)
    if k is None:
        return os.path.getsize(path)
    row = database.connect().execute(
        "SELECT length(content) FROM state_file WHERE path = %s", (k,)).fetchone()
    if row is None:
        raise FileNotFoundError(2, "No such file", path)
    return int(row[0])


# --- WRITING ---

def write(path, data):
    """Replace the whole file. Atomic in both modes."""
    k = key(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if k is None:
        import dateisperre
        return dateisperre.schreibe_atomar(path, data)
    database.connect().execute(
        "INSERT INTO state_file (path, content, updated) VALUES (%s, %s, now()) "
        "ON CONFLICT (path) DO UPDATE SET content = EXCLUDED.content, "
        "updated = now()", (k, data))


def append(path, data):
    """Append to the end of the file (logs). Atomic per call."""
    k = key(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if k is None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with builtins.open(path, "ab") as f:
            f.write(data)
        return
    database.connect().execute(
        "INSERT INTO state_file (path, content, updated) VALUES (%s, %s, now()) "
        "ON CONFLICT (path) DO UPDATE SET "
        "content = state_file.content || EXCLUDED.content, updated = now()",
        (k, data))


def remove(path):
    k = key(path)
    if k is None:
        return os.remove(path)
    cur = database.connect().execute(
        "DELETE FROM state_file WHERE path = %s", (k,))
    if cur.rowcount == 0:
        raise FileNotFoundError(2, "No such file", path)


def rmtree(path, ignore_errors=False, onerror=None):
    """Remove a directory with everything in it (like shutil.rmtree)."""
    prefix = _dir_key(path)
    if prefix is None:
        import shutil
        return shutil.rmtree(path, ignore_errors=ignore_errors,
                             onerror=onerror)
    database.connect().execute("DELETE FROM state_file WHERE path LIKE %s",
                               (_like(prefix) + "%",))


def rename(src, dst):
    """Move a file, replacing dst (like os.replace)."""
    ks, kd = key(src), key(dst)
    if ks is None and kd is None:
        return os.replace(src, dst)
    data = read_bytes(src)
    con = database.connect()
    with con.transaction():
        write(dst, data)
        remove(src)


def makedirs(path, mode=0o777, exist_ok=False):
    """Directories are implicit in the database; on disk they are created."""
    if _dir_key(path) is None:
        os.makedirs(path, mode, exist_ok)


# --- open() ---

class _Writer(io.BytesIO):
    """Collects what is written and stores it on close."""

    def __init__(self, path, appending):
        super().__init__()
        self._path, self._appending = path, appending

    def close(self):
        if not self.closed:
            data = self.getvalue()
            (append if self._appending else write)(self._path, data)
        super().close()


def open(path, mode="r", *args, **kwargs):  # noqa: A001
    """builtins.open for managed paths; the real open() for all others.

    Supports the modes the modules use: r, rb, w, wb, a, ab.
    """
    if key(path) is None:
        return builtins.open(path, mode, *args, **kwargs)
    encoding = kwargs.get("encoding")
    errors = kwargs.get("errors")
    newline = kwargs.get("newline")
    binary = "b" in mode
    if "r" in mode and "+" not in mode:
        data = read_bytes(path)
        if binary:
            return io.BytesIO(data)
        return io.TextIOWrapper(io.BytesIO(data), encoding=encoding or "utf-8",
                                errors=errors, newline=newline)
    if "w" in mode or "a" in mode:
        writer = _Writer(path, appending="a" in mode)
        if binary:
            return writer
        return io.TextIOWrapper(writer, encoding=encoding or "utf-8",
                                errors=errors, newline=newline or "\n",
                                write_through=True)
    raise ValueError("mode not supported for state files: " + mode)


# --- LOCKS ---

def lock_id(path):
    """64-bit advisory lock id of a path."""
    k = key(path) or os.path.abspath(path)
    return int.from_bytes(hashlib.sha256(k.encode("utf-8")).digest()[:8],
                          "big", signed=True)


@contextlib.contextmanager
def advisory_lock(path):
    """Exclusive across pods, for the time of the with block."""
    con = database.connect()
    n = lock_id(path)
    con.execute("SELECT pg_advisory_lock(%s)", (n,))
    try:
        yield
    finally:
        try:
            con.execute("SELECT pg_advisory_unlock(%s)", (n,))
        except Exception:
            pass  # a lost connection has released the lock already


def _like(prefix):
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
