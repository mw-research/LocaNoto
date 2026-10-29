"""Is this installation complete? One check per part, in plain words.

    python doctor.py [--en] [--json]

Runs inside the server container (the installer calls it after every
install and upgrade; an admin can call it any time). Checks, in order:

    key          the installation key is there and readable
    database     Postgres answers, schema and vector settings
    chat model   the chat endpoint answers
    embeddings   the embedding endpoint answers, with enough dimensions
    web search   the web search service answers (if switched on)
    file store   OpenCloud answers and accepts the app token (if on)
    address      the public address answers over HTTPS with a trusted
                 certificate (LOCANOTO_PUBLIC_URL)

Every failed line says what to do about it. Exit code 0 when all checks
that apply pass.
"""
import json
import os
import ssl
import sys
import urllib.request

EN = "--en" in sys.argv or os.getenv("LOCANOTO_LANG", "") == "en"
results = []


def say(de, en):
    return en if EN else de


def check(name, ok, detail="", fix=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail,
                    "fix": "" if ok else fix})


def run():
    import geheim
    state, message = geheim.zustand()
    check(say("Schlüssel", "key"), state not in ("unlesbar", "fehlt"),
          message, say("LOCANOTO_SCHLUESSEL fehlt oder ist falsch -- im "
                       "Installer `--upgrade` laufen lassen.",
                       "LOCANOTO_SCHLUESSEL missing or wrong -- run the "
                       "installer with --upgrade."))

    import database
    if database.active():
        try:
            database.connect()
            s = database.vector_settings()
            check(say("Datenbank", "database"), True,
                  f"{database.describe()} · {s['type']}({s['dimensions']})")
        except Exception as e:
            check(say("Datenbank", "database"), False, type(e).__name__,
                  say("Postgres läuft nicht oder DATABASE_URL stimmt nicht.",
                      "Postgres is down or DATABASE_URL is wrong."))
    else:
        check(say("Datenbank", "database"), True,
              say("Dateiablage (ohne DATABASE_URL)", "file store (no DATABASE_URL)"))

    import llm
    try:
        r = llm.client("CHAT").chat.completions.create(
            model=llm.modell("CHAT"),
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1, timeout=60)
        check(say("Chat-Modell", "chat model"), bool(r.choices),
              f"{llm.modell('CHAT')} @ {llm.basis_url('CHAT')}")
    except Exception as e:
        check(say("Chat-Modell", "chat model"), False,
              f"{llm.modell('CHAT')} @ {llm.basis_url('CHAT')}: "
              f"{type(e).__name__}",
              say("Adresse, Schlüssel oder Modellname des Chat-Modells prüfen "
                  "(CHAT_BASE_URL / OPENAI_BASE_URL, CHAT_MODEL).",
                  "Check address, key or name of the chat model "
                  "(CHAT_BASE_URL / OPENAI_BASE_URL, CHAT_MODEL)."))

    try:
        e = llm.client("EMBEDDING").embeddings.create(
            model=llm.modell("EMBEDDING"), input=["ping"], timeout=60)
        dims = len(e.data[0].embedding)
        need = database.DIMENSIONS if database.active() else 0
        check(say("Embeddings", "embeddings"), dims >= need,
              f"{llm.modell('EMBEDDING')}: {dims}"
              + (f" ≥ {need}" if need else ""),
              say(f"Das Modell liefert {dims} Werte, die Datenbank erwartet "
                  f"{need}. DATABASE_DIMENSIONS vor dem ersten Start kleiner "
                  f"setzen oder ein anderes Modell wählen.",
                  f"The model returns {dims} values, the database expects "
                  f"{need}. Set DATABASE_DIMENSIONS lower before the first "
                  f"start or choose another model."))
    except Exception as ex:
        check(say("Embeddings", "embeddings"), False, type(ex).__name__,
              say("Adresse oder Name des Embedding-Modells prüfen "
                  "(EMBEDDING_BASE_URL, EMBEDDING_MODEL).",
                  "Check address or name of the embedding model "
                  "(EMBEDDING_BASE_URL, EMBEDDING_MODEL)."))

    import mcp
    servers = mcp.websuche_server()
    if servers:
        import mailboxes
        name = sorted(servers)[0]
        try:
            tools = mailboxes.check(name, {})
            check(say("Websuche", "web search"), "web_suchen" in tools,
                  ", ".join(tools))
        except Exception as e:
            check(say("Websuche", "web search"), False, type(e).__name__,
                  say("Dienst websuche/searxng läuft nicht oder ist nicht "
                      "erreichbar.",
                      "The websuche/searxng service is down or unreachable."))

    import owncloud
    if owncloud.eingerichtet():
        ok, message = owncloud.pruefe()
        check(say("Dateiablage", "file store"), ok, message,
              say("OpenCloud läuft nicht oder das App-Token fehlt -- "
                  "Installer mit --upgrade erneut laufen lassen.",
                  "OpenCloud is down or the app token is missing -- run "
                  "the installer with --upgrade."))

    url = os.getenv("LOCANOTO_PUBLIC_URL", "").strip().rstrip("/")
    if url:
        try:
            ctx = ssl.create_default_context(
                cafile=os.getenv("SSL_CERT_FILE") or None)
            with urllib.request.urlopen(url + "/api/v1/health", timeout=20,
                                        context=ctx) as r:
                check(say("Adresse", "address"), r.status == 200, url)
        except Exception as e:
            reason = getattr(e, "reason", e)
            check(say("Adresse", "address"), False, f"{url}: {reason}",
                  say("Name zeigt nicht auf diesen Rechner (DNS), Port 443 "
                      "gesperrt, oder das Zertifikat ist (noch) nicht "
                      "ausgestellt.",
                      "The name does not point here (DNS), port 443 is "
                      "blocked, or the certificate is not issued (yet)."))


def main():
    try:
        run()
    except Exception as e:
        check("doctor", False, f"{type(e).__name__}: {e}")
    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for r in results:
            mark = "OK  " if r["ok"] else "FEHLT" if not EN else "FAIL"
            print(f"  {mark:5} {r['check']:<14} {r['detail']}")
            if r["fix"]:
                print(f"        → {r['fix']}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
