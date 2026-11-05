"""Runs the background jobs queued in Postgres (see jobs.py).

    python worker.py              until stopped
    python worker.py --once       one job if there is one, then exit

One Deployment of these, as many replicas as jobs should run at the same
time. Each takes the next queued job, runs its script, writes the output
and a heartbeat into the row every few seconds, and stops the script when
an admin cancels it. SIGTERM (a pod being moved) stops the running
script and gives the job back as failed, so it can be started again.

Beside the jobs, every worker checks the shared mailboxes with a ticket
system every TICKET_POLL_SECONDS (tickets.py). Several workers do not
answer a mail twice: a mailbox is checked under a lock that holds across
pods, and a mail is marked handled before anything is sent.
"""
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import database
import hintergrund
import jobs
import paths
import tickets

POLL_SECONDS = paths.env_float("WORKER_POLL_SECONDS", 3)
BEAT_SECONDS = 5

_stop = threading.Event()


def run(job_id, name, worker):
    script = hintergrund.LAEUFE[name][0]
    proc = subprocess.Popen(
        [sys.executable, "-u", script], cwd=paths.BASE_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    buffer, lock = [], threading.Lock()

    def read():
        for line in proc.stdout:
            with lock:
                buffer.append(line)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    cancelled = False
    while proc.poll() is None:
        time.sleep(BEAT_SECONDS)
        with lock:
            out, buffer[:] = "".join(buffer), []
        if jobs.beat(job_id, out) or _stop.is_set():
            cancelled = not _stop.is_set()
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
    reader.join(5)
    with lock:
        out = "".join(buffer)
    jobs.beat(job_id, out + f"\n[exit {proc.returncode} on {worker}]\n")
    jobs.finish(job_id, proc.returncode, cancelled=cancelled)


def ticket_loop():
    """Shared mailboxes with tickets, every TICKET_POLL_SECONDS."""
    while not _stop.wait(max(10.0, tickets.POLL_SECONDS)):
        try:
            done = tickets.poll_all(log=lambda t: print(t, flush=True))
        except Exception as e:
            print(f"tickets: {type(e).__name__}: {e}", flush=True)
            continue
        for server, n in done.items():
            if isinstance(n, int) and n:
                print(f"tickets {server}: {n} new mail(s)", flush=True)


def main():
    if not database.active():
        print("DATABASE_URL is not set -- without it jobs run in place "
              "(hintergrund.py) and no worker is needed.")
        return 2
    worker = f"{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    once = "--once" in sys.argv
    if not once and tickets.POLL_SECONDS > 0:
        threading.Thread(target=ticket_loop, daemon=True, name="tickets").start()
    print(f"worker {worker} waiting for jobs", flush=True)
    while not _stop.is_set():
        claimed = jobs.claim(worker)
        if claimed:
            job_id, name = claimed
            print(f"job {job_id}: {name}", flush=True)
            run(job_id, name, worker)
        elif once:
            break
        else:
            _stop.wait(POLL_SECONDS)
        if once:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
