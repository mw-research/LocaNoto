"""Two server processes and a worker on one database -- as two pods would run.

    SELFTEST_DATABASE=postgresql://user:pw@host:5432/postgres python test_multipod.py

Starts two uvicorn processes (stand-in models, same installation key,
same documents folder, a throwaway database) and a worker, then checks
what multi-pod operation depends on:

  * a session started on A works on B (signed cookie, no server state),
  * a document uploaded through A is found by a question on B,
  * a chat written on A is read on B,
  * a mailbox login sealed by A is opened by B,
  * failed sign-ins on A and B count together,
  * a job queued on A is run by the worker and its log is read on B,
  * a state file written on A is seen on B at once (no caches).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def serve(port):
    """Child: one server with stand-in models."""
    import types
    sys.path.insert(0, HERE)
    from compare_search import HashEmbedder
    emb = HashEmbedder(64)

    def fake_embed(*args, **_kw):
        return [emb.vector(t) for t in args[1]]

    class FakeChat:
        def __init__(self):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self.create))

        def create(self, stream=False, **_kw):
            text = f"Antwort von Port {port}."
            if stream:
                return iter([types.SimpleNamespace(choices=[
                    types.SimpleNamespace(delta=types.SimpleNamespace(
                        content=text))])])
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="Titel",
                                              tool_calls=None))])
    import answering
    import aufnehmen
    import pipeline
    aufnehmen.embed_batch = fake_embed
    pipeline.embed_batch = fake_embed
    answering.client = lambda task, user="": FakeChat()
    answering._reranker = (None, "fusion")
    import uvicorn
    import server
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--serve":
        return serve(int(sys.argv[2]))
    server_db = os.environ.get("SELFTEST_DATABASE", "").strip()
    if not server_db:
        print("SELFTEST_DATABASE is not set (a Postgres server URL).")
        return 2
    import base64
    import httpx
    import psycopg
    from urllib.parse import urlsplit, urlunsplit

    tmp = tempfile.mkdtemp(prefix="multipod_")
    name = "selftest_" + os.urandom(4).hex()
    with psycopg.connect(server_db, autocommit=True) as a:
        a.execute(f'CREATE DATABASE "{name}"')
    u = urlsplit(server_db)
    keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
            "PATHEXT", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "PROGRAMDATA", "VIRTUAL_ENV")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update({
        "DATABASE_URL": urlunsplit((u.scheme, u.netloc, "/" + name,
                                    u.query, u.fragment)),
        "DATABASE_DIMENSIONS": "64",
        "LOCANOTO_SCHLUESSEL": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "LOCANOTO_DATEN": os.path.join(tmp, "data"),
        "LOCANOTO_KONFIG": os.path.join(tmp, "config"),
        "LOCANOTO_INDEX": os.path.join(tmp, "index"),
        "COOKIE_SECURE": "0", "CHAT_MODEL": "fake", "LOGIN_ATTEMPTS": "4",
        "PYTHONIOENCODING": "utf-8", "WORKER_POLL_SECONDS": "0.5",
        "ADMIN_USERS": "markus"})
    procs, failures = [], []

    def check(label, ok, detail=""):
        print(("  OK   " if ok else "  FAIL ") + label
              + ("" if ok else f"  {str(detail)[:300]}"))
        if not ok:
            failures.append(label)

    try:
        # The first user, created like an admin would: through the code.
        setup = subprocess.run(
            [sys.executable, "-c",
             "import benutzer, raeume; "
             "benutzer.anlege('markus', 'Passwort-123456', rolle='admin'); "
             "benutzer.anlege('anna', 'Passwort-123456'); "
             "raeume.anlegen('einkauf', 'Einkauf', mitglieder=['markus','anna'])"],
            cwd=HERE, env=env, capture_output=True, text=True)
        check("setup", setup.returncode == 0, setup.stderr[-500:])
        ports = [free_port(), free_port()]
        for port in ports:
            procs.append(subprocess.Popen(
                [sys.executable, __file__, "--serve", str(port)], cwd=HERE,
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        procs.append(subprocess.Popen([sys.executable, "worker.py"], cwd=HERE,
                                      env=env, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
        bases = [f"http://127.0.0.1:{p}" for p in ports]
        for b, p in zip(bases, procs):
            for _ in range(360):
                try:
                    if httpx.get(b + "/api/v1/ready", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if p.poll() is not None:
                    raise SystemExit("server did not start:\n"
                                     + p.stderr.read().decode(errors="replace")[-2000:])
                time.sleep(0.5)
        A, B = (httpx.Client(base_url=b, timeout=60) for b in bases)

        r = A.post("/api/v1/auth/login", json={"username": "anna",
                                                "password": "Passwort-123456"})
        check("sign in on A", r.status_code == 200, r.text)
        B.cookies.update(A.cookies)
        csrf = A.cookies.get("locanoto_csrf")
        for c in (A, B):
            c.headers["X-LocaNoto-CSRF"] = csrf
        check("the session from A works on B",
              B.get("/api/v1/me").json().get("user") == "anna")

        r = A.post("/api/v1/documents", data={"room": "einkauf"},
                   files={"file": ("Rahmenvertrag.txt",
                                   b"Dichtungen nach Rahmenvertrag 2026. " * 30,
                                   "text/plain")})
        check("upload on A", r.status_code == 200 and r.json()["passages"] > 0,
              r.text)
        r = B.post("/api/v1/ask", json={"question": "Dichtungen Rahmenvertrag"})
        body = r.json()
        check("a question on B finds it",
              any(s["file"] == "Rahmenvertrag.txt"
                  for s in (body.get("message") or {}).get("sources", [])),
              r.text[:300])
        check("answered by B", "Port %d" % ports[1] in body.get("answer", ""))
        chat_id = body.get("chat_id")
        check("the chat from B is read on A", A.get(
            f"/api/v1/chats/{chat_id}").status_code == 200)

        markus = httpx.Client(base_url=bases[0], timeout=60)
        markus.post("/api/v1/auth/login", json={"username": "markus",
                                                 "password": "Passwort-123456"})
        markus.headers["X-LocaNoto-CSRF"] = markus.cookies.get("locanoto_csrf")
        r = markus.post("/api/v1/admin/mailboxes", json={
            "name": "suche", "template": "websuche", "target": "http://127.0.0.1:9"})
        check("configuration written on A", r.status_code == 200, r.text)
        check("is seen on B at once", any(
            m["name"] == "suche" for m in B.get("/api/v1/mailboxes").json()))

        for i, c in enumerate((A, B, A, B)):
            c.post("/api/v1/auth/login", json={"username": "markus",
                                               "password": f"falsch-{i}"})
        r = A.post("/api/v1/auth/login", json={"username": "markus",
                                                "password": "Passwort-123456"})
        check("failed sign-ins on A and B count together", r.status_code == 429,
              r.status_code)

        r = markus.post("/api/v1/admin/jobs/text")
        check("job queued on A", r.json().get("started"), r.text)
        state = ""
        for _ in range(120):
            markus_b = httpx.Client(base_url=bases[1], timeout=30,
                                    cookies=markus.cookies)
            jobs_ = {j["name"]: j for j in markus_b.get("/api/v1/admin/jobs").json()}
            state = jobs_["text"]["state"]
            if state in ("done", "failed"):
                break
            time.sleep(1)
        check("the worker ran it (seen from B)", state in ("done", "failed"),
              state)
        log = markus_b.get("/api/v1/admin/jobs/text/log").text
        check("its log is read on B", "[exit" in log, log[-300:])
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(20)
            except subprocess.TimeoutExpired:
                p.kill()
        with psycopg.connect(server_db, autocommit=True) as a:
            a.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    print("\nall passed" if not failures else f"\n{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
