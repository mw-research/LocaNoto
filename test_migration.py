"""End-to-end check of the move to Postgres, without a model server.

    SELFTEST_DATABASE=postgresql://user:pw@host:5432/postgres python test_migration.py

Builds a small installation the old way (files, SQLite, Chroma) in a
temporary folder, searches it, moves it with migrate_to_postgres.py into a
throwaway database, searches again and compares with compare_search.py.
Vectors come from compare_search.HashEmbedder, so vector search is
meaningful without a model.

Passes when the migration verifies, every user and chat arrived, and the
search finds the same at full vector size: identical keyword hits, the
same first hit for every question and a hybrid overlap of at least 0.9
(passages at exactly the same distance may come in another order). A second run with shortened vectors (DATABASE_DIMENSIONS below the
model's size) shows what shortening costs on this corpus -- reported,
not required.
"""
import json
import os
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit

HERE = os.path.dirname(os.path.abspath(__file__))
DIM = 64

ROOMS = {
    "allgemein": [
        ("Betriebsanweisung.pdf", "Die Pruefristen fuer Druckbehaelter und Kessel betragen vier Jahre."),
        ("Betriebsanweisung.pdf", "Vor dem Oeffnen der Kesselklappe ist die Anlage drucklos zu machen."),
        ("Arbeitsschutz.pdf", "Schutzbrille und Gehoerschutz sind in der Halle Pflicht."),
        ("Arbeitsschutz.pdf", "Gefahrstoffe werden im Gefahrstofflager getrennt gelagert."),
        ("Qualitaet.pdf", "Toleranzen fuer Schweissnaehte richten sich nach DIN EN ISO 5817."),
        ("Qualitaet.pdf", "Die Erstmusterpruefung dokumentiert alle Masse des Bauteils."),
        ("Wartung.pdf", "Die Hydraulikpumpe wird alle 500 Betriebsstunden gewartet."),
        ("Wartung.pdf", "Filterwechsel am Kompressor erfolgt quartalsweise."),
    ],
    "einkauf": [
        ("Rahmenvertrag.pdf", "Dichtungen werden nach Rahmenvertrag 2026 beim Lieferanten Mueller beschafft."),
        ("Rahmenvertrag.pdf", "Der Rahmenvertrag sieht Staffelpreise ab 1000 Stueck vor."),
        ("Lieferanten.pdf", "Lieferantenbewertung erfolgt jaehrlich nach Qualitaet, Termintreue und Preis."),
        ("Lieferanten.pdf", "Neue Lieferanten muessen eine ISO 9001 Zertifizierung nachweisen."),
        ("Bestellung.pdf", "Bestellungen ueber 5000 Euro brauchen die Freigabe der Abteilungsleitung."),
    ],
    "@anna": [
        ("Notiz.pdf", "Persoenliche Notiz von anna zu Kabelquerschnitten im Schaltschrank."),
        ("Notiz.pdf", "Kabelkanal im Schaltschrank ist zu klein dimensioniert."),
    ],
}

QUESTIONS = [
    "Wie lange sind die Pruefristen fuer Kessel?",
    "Was muss ich vor dem Oeffnen der Kesselklappe tun?",
    "Welche Schutzausruestung ist Pflicht?",
    "Wo werden Gefahrstoffe gelagert?",
    "Welche Norm gilt fuer Toleranzen bei Schweissnaehten?",
    "Wann wird die Hydraulikpumpe gewartet?",
    "Wer liefert Dichtungen?",
    "Gibt es Staffelpreise?",
    "Wie werden Lieferanten bewertet?",
    "Welche Zertifizierung brauchen neue Lieferanten?",
    "Wer muss grosse Bestellungen freigeben?",
    "Kabelquerschnitt Schaltschrank",
    "Toleranz",
    "Filterwechsel Kompressor",
]


def seed():
    """Runs in the child without DATABASE_URL: the old installation."""
    sys.path.insert(0, HERE)
    import benutzer
    import chats
    import keyword_index
    import raeume
    import store
    from compare_search import HashEmbedder
    emb = HashEmbedder(DIM)
    benutzer.anlege("markus", "Passwort-123456", rolle="admin")
    benutzer.anlege("anna", "Passwort-123456")
    raeume.sichere_anlage_privat("anna")
    raeume.anlegen("einkauf", "Einkauf", mitglieder=["markus", "anna"])
    for room, entries in ROOMS.items():
        room = raeume.privat_kennung("anna") if room == "@anna" else room
        sml = store.sammlung(raeume.sammlung(room))
        for i, (name, text) in enumerate(entries):
            cid = f"{name}_p1_c{i}"
            meta = {"file_name": name, "page": 1, "raum": room,
                    "folder": "(Basis)", "type": "text"}
            store.schreibe(sml, [cid], documents=[text], metadatas=[meta],
                           embeddings=[emb.vector(text)])
            keyword_index.add_chunks([(cid, text, meta)])
    chats.speichere("anna", chats.neue_kennung(),
                    [{"role": "user", "content": "Kabel?"},
                     {"role": "assistant", "content": "Siehe Notiz."}],
                    titel="Kabel")


def child_counts():
    """Runs in the child with DATABASE_URL: what arrived."""
    sys.path.insert(0, HERE)
    import benutzer
    import chats
    print(json.dumps({"users": sorted(benutzer.namen()),
                      "chats_anna": len(chats.liste("anna"))}))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        return seed()
    if len(sys.argv) > 1 and sys.argv[1] == "--counts":
        return child_counts()
    server = os.environ.get("SELFTEST_DATABASE", "").strip()
    if not server:
        print("SELFTEST_DATABASE is not set (a Postgres server URL).")
        return 2
    import psycopg
    tmp = tempfile.mkdtemp(prefix="migration_")
    with open(os.path.join(tmp, "questions.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(QUESTIONS))
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("DATABASE_", "CHROMA_", "LOCANOTO_",
                                 "OWNCLOUD_", "SELFTEST_"))}
    base.update({"LOCANOTO_KONFIG": os.path.join(tmp, "config"),
                 "LOCANOTO_DATEN": os.path.join(tmp, "data"),
                 "ADMIN_USERS": "markus", "PYTHONIOENCODING": "utf-8"})

    def sh(args, env, check=True):
        r = subprocess.run([sys.executable] + args, cwd=HERE, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        if check and r.returncode != 0:
            print(r.stdout[-3000:], r.stderr[-3000:])
            raise SystemExit(f"failed: {' '.join(args)}")
        return r

    sh([__file__, "--seed"], base)
    q = os.path.join(tmp, "questions.txt")
    for user in ("markus", "anna"):
        sh(["compare_search.py", "run", q, "--user", user, "--fake-embedder",
            "--out", os.path.join(tmp, f"old_{user}.json")], base)

    ok = True
    for dims in (DIM, DIM // 2):
        name = "selftest_" + os.urandom(4).hex()
        with psycopg.connect(server, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        try:
            u = urlsplit(server)
            env = dict(base, DATABASE_URL=urlunsplit(
                (u.scheme, u.netloc, "/" + name, u.query, u.fragment)),
                DATABASE_DIMENSIONS=str(dims))
            r = sh(["migrate_to_postgres.py", "run"], env, check=False)
            verified = r.returncode == 0 and r.stdout.strip().endswith("OK")
            counts = json.loads(sh([__file__, "--counts"], env).stdout)
            print(f"--- vectors {dims} of {DIM}: migration "
                  f"{'verified' if verified else 'NOT verified'}, "
                  f"users {counts['users']}, anna's chats {counts['chats_anna']}")
            if dims == DIM:
                ok &= verified and counts["users"] == ["anna", "markus"] \
                    and counts["chats_anna"] == 1
            sys.path.insert(0, HERE)
            from compare_search import diff
            for user in ("markus", "anna"):
                sh(["compare_search.py", "run", q, "--user", user,
                    "--fake-embedder", "--out",
                    os.path.join(tmp, f"new_{user}_{dims}.json")], env)
                with open(os.path.join(tmp, f"old_{user}.json"), encoding="utf-8") as f:
                    old = json.load(f)
                with open(os.path.join(tmp, f"new_{user}_{dims}.json"), encoding="utf-8") as f:
                    new = json.load(f)
                print(f"\n[{user}]")
                m = diff(old, new)
                if dims == DIM:
                    ok &= m is not None and m["keyword"] == 1.0 \
                        and m["same_first"] == 1.0 and m["hybrid"] >= 0.9
        finally:
            with psycopg.connect(server, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
