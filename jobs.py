"""Background jobs: ingest, images, storage sync, backup.

    start(name, by)      queue a job (once: a second start while one is
                         queued or running is refused)
    cancel(name, by)     stop it
    status(name)         {"state", ...} of the newest job of that name
    overview()           every kind of job with its newest run
    log(name, lines)     the end of its output

The jobs are the scripts in hintergrund.LAEUFE.

WITHOUT DATABASE_URL they run as before: a detached process on this
machine (hintergrund.py), state in a pid file.

WITH DATABASE_URL a job is a row in the table job. Any number of worker
processes (worker.py, one Deployment) take queued rows with
FOR UPDATE SKIP LOCKED -- each job runs exactly once, on whichever worker
is free, and the web pods never run long work themselves. The output goes
into the row as it grows, so every pod can show it. A worker writes a
heartbeat; a running job without heartbeat for HEARTBEAT_TIMEOUT seconds
counts as failed (its worker died) and can be started again.
"""
import database
import hintergrund
import paths

HEARTBEAT_TIMEOUT = paths.env_int("JOB_HEARTBEAT_TIMEOUT", 120)
LOG_MAX_CHARS = 200_000


def names():
    return list(hintergrund.LAEUFE)


def _check(name):
    if name not in hintergrund.LAEUFE:
        raise KeyError(f"Unknown job '{name}'. Known: {', '.join(names())}")


def _expire_stale(con):
    con.execute(
        "UPDATE job SET state = 'failed', finished = now(), "
        "log = log || %s WHERE state IN ('running', 'cancelling') "
        "AND heartbeat < now() - make_interval(secs => %s)",
        ("\n[worker lost -- no heartbeat]\n", HEARTBEAT_TIMEOUT))


def start(name, by="?"):
    _check(name)
    if not database.active():
        ok, message = hintergrund.starte(name)
        return {"name": name, "started": ok, "message": message}
    con = database.connect()
    with con.transaction():
        _expire_stale(con)
        # One at a time per kind; the lock makes the check-and-insert atomic.
        con.execute("SELECT pg_advisory_xact_lock(hashtext('job:' || %s))",
                    (name,))
        busy = con.execute(
            "SELECT id FROM job WHERE name = %s AND state IN "
            "('queued', 'running', 'cancelling')", (name,)).fetchone()
        if busy:
            return {"name": name, "started": False,
                    "message": "Already queued or running.", "id": busy[0]}
        job_id = con.execute(
            "INSERT INTO job (name, requested_by) VALUES (%s, %s) "
            "RETURNING id", (name, by)).fetchone()[0]
    return {"name": name, "started": True, "message": "Queued.",
            "id": job_id}


def cancel(name, by="?"):
    _check(name)
    if not database.active():
        return {"name": name, "cancelled": hintergrund.abbrechen(name)}
    con = database.connect()
    cur = con.execute(
        "UPDATE job SET state = CASE WHEN state = 'queued' THEN 'cancelled' "
        "ELSE 'cancelling' END, cancelled_by = %s, "
        "finished = CASE WHEN state = 'queued' THEN now() ELSE finished END "
        "WHERE name = %s AND state IN ('queued', 'running')", (by, name))
    return {"name": name, "cancelled": cur.rowcount > 0}


def status(name):
    _check(name)
    if not database.active():
        return {"name": name, "state": "running" if hintergrund.laeuft(name)
                else "idle"}
    con = database.connect()
    _expire_stale(con)
    row = con.execute(
        "SELECT id, state, requested_by, created, started, finished, "
        "exit_code, worker FROM job WHERE name = %s ORDER BY id DESC LIMIT 1",
        (name,)).fetchone()
    if not row:
        return {"name": name, "state": "idle"}
    keys = ("id", "state", "requested_by", "created", "started", "finished",
            "exit_code", "worker")
    return {"name": name, **{k: (v.isoformat() if hasattr(v, "isoformat")
                                 else v) for k, v in zip(keys, row)}}


def overview():
    return [dict(status(n), label=hintergrund.LAEUFE[n][2]) for n in names()]


def log(name, lines=50):
    _check(name)
    if not database.active():
        return hintergrund.protokoll(name, lines)
    row = database.connect().execute(
        "SELECT log FROM job WHERE name = %s ORDER BY id DESC LIMIT 1",
        (name,)).fetchone()
    text = row[0] if row else ""
    return "\n".join(text.splitlines()[-lines:])


# --- WORKER SIDE (worker.py) ---

def claim(worker):
    """The next queued job for this worker, or None."""
    con = database.connect()
    _expire_stale(con)
    row = con.execute(
        "UPDATE job SET state = 'running', started = now(), heartbeat = now(), "
        "worker = %s WHERE id = (SELECT id FROM job WHERE state = 'queued' "
        "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id, name",
        (worker,)).fetchone()
    return row


def beat(job_id, output=""):
    """Heartbeat plus new output. Returns True if cancelling was asked."""
    row = database.connect().execute(
        "UPDATE job SET heartbeat = now(), "
        "log = right(log || %s, %s) WHERE id = %s RETURNING state",
        (output, LOG_MAX_CHARS, job_id)).fetchone()
    return bool(row and row[0] == "cancelling")


def finish(job_id, exit_code, cancelled=False):
    database.connect().execute(
        "UPDATE job SET state = %s, exit_code = %s, finished = now() "
        "WHERE id = %s",
        ("cancelled" if cancelled else ("done" if exit_code == 0 else "failed"),
         exit_code, job_id))
