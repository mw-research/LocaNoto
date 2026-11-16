"""The connector interface and the SQL connector, without an ERP.

    python test_connector.py

Starts real connectors on local ports and talks to them the way LocaNoto
does (mcp.Verbindung over HTTP):

  * the kit: handshake with instructions, tool list with read-only marks,
    logins from the Authorization header, tables as structured results
  * the SQL connector on SQLite: describe, query, row limit, time limit,
    refused statements, the database itself opened read-only
  * what each SQL dialect adds to the check (quoting the reader does not
    know)
  * LocaNoto's side: a connector entry belongs to a workspace, its
    instructions reach the model, a tool that is not marked read-only
    becomes a draft, tables are listed for the answer
  * with SELFTEST_DATABASE (a Postgres server URL): the same against
    PostgreSQL, including the read-only connection

Runs in a temporary folder with files and its own key.
"""
import base64
import json
import os
import sqlite3
import sys
import tempfile
import threading
import types

TMP = tempfile.mkdtemp(prefix="connector_")
PG_URL = os.environ.pop("SELFTEST_DATABASE", "")
os.environ.pop("DATABASE_URL", None)
os.environ.update({
    "LOCANOTO_KONFIG": os.path.join(TMP, "config"),
    "LOCANOTO_DATEN": os.path.join(TMP, "data"),
    "LOCANOTO_INDEX": os.path.join(TMP, "index"),
    "LOCANOTO_SCHLUESSEL": base64.urlsafe_b64encode(os.urandom(32)).decode(),
})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "connectors"))

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  {str(detail)[:300]}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def ns(**k):
    return types.SimpleNamespace(**k)


def start(connector):
    """Serve a connector on a free local port; returns its /mcp address."""
    srv = connector.server(port=0, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/mcp"


# --- the kit ---

import kit  # noqa: E402

demo = kit.Connector("demo", instructions="Lagerbestand der Demo.")
seen = {}


@demo.tool("stock", "Bestand eines Artikels.",
           {"type": "object", "properties": {"article": {"type": "string"}}})
def _stock(args, login):
    seen["login"] = (login.kind, login.user, login.secret)
    return kit.table(["article", "quantity"], [[args.get("article"), 7]],
                     source="demo warehouse")


@demo.tool("book_out", "Bucht einen Artikel aus.",
           {"type": "object", "properties": {"article": {"type": "string"}}},
           read_only=False)
def _book_out(args, login):
    seen.setdefault("booked", []).append(args.get("article"))
    return "ausgebucht"


@demo.tool("fails", "Scheitert.")
def _fails(args, login):
    raise kit.Refused("Das geht so nicht.")


hello = demo.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]
check("kit: the handshake says what the connector is for",
      hello["instructions"] == "Lagerbestand der Demo." and hello["serverInfo"]["name"] == "demo")
listed = {t["name"]: t for t in demo.handle(
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
check("kit: every tool says whether it only reads",
      listed["stock"]["annotations"]["readOnlyHint"] is True
      and listed["book_out"]["annotations"]["readOnlyHint"] is False)
check("kit: a notification gets no answer, an unknown method an error",
      demo.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
      and "error" in demo.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}))
basic = "Basic " + base64.b64encode("anna:geheim:mit:doppelpunkt".encode()).decode()
called = demo.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "stock", "arguments": {"article": "WA-104"}}},
                     basic)["result"]
check("kit: the user's login reaches the tool",
      seen["login"] == ("basic", "anna", "geheim:mit:doppelpunkt"), seen)
check("kit: a table comes as text for the model and as structured result",
      "| WA-104 | 7 |" in called["content"][0]["text"]
      and called["structuredContent"] == {"columns": ["article", "quantity"],
                                          "rows": [["WA-104", 7]],
                                          "source": "demo warehouse", "truncated": False},
      called)
check("kit: a bearer token, and no login at all",
      kit.login_from("Bearer abc").secret == "abc" and not kit.login_from(""))
refused = demo.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "fails"}})["result"]
check("kit: a refusal is the tool's answer, marked as error",
      refused["isError"] and refused["content"][0]["text"] == "Das geht so nicht.")
import datetime  # noqa: E402
import decimal  # noqa: E402
check("kit: cells become something JSON carries",
      [kit.plain(v) for v in (decimal.Decimal("1.5"), datetime.date(2026, 11, 14),
                              b"abc", None, float("nan"))]
      == [1.5, "2026-11-14", "[3 bytes]", None, "nan"])

# --- the SQL connector on SQLite ---

DB = os.path.join(TMP, "erp.sqlite")
with sqlite3.connect(DB) as _c:
    _c.executescript("""
        CREATE TABLE Artikel (ArtikelNr TEXT, Bezeichnung TEXT, Preis REAL);
        CREATE TABLE Lagerplaetze (ArtikelNr TEXT, Lager TEXT, Platz TEXT, Menge INTEGER);
        CREATE TABLE Gehaelter (Name TEXT, Betrag REAL);
        INSERT INTO Artikel VALUES ('DB-100', 'Druckbehälter 50 l', 1250.5),
                                   ('SV-200', 'Sicherheitsventil 10 bar', 89.9),
                                   ('WA-104', 'Werbeartikel', 4.2);
        INSERT INTO Lagerplaetze VALUES ('DB-100', 'Halle 1', 'A-03', 12),
                                        ('SV-200', 'Halle 1', 'B-11', 140),
                                        ('WA-104', 'Büro', 'Schrank', 1);
        INSERT INTO Gehaelter VALUES ('Meier', 5000);
    """)
os.environ.update({"SQL_KIND": "sqlite", "SQL_DATABASE": DB,
                   "CONNECTOR_NAME": "erp",
                   "CONNECTOR_ABOUT": "ERP der Musterfirma: Artikel und Lager.",
                   "SQL_NOTE": "Menge in Stück."})
import sql_connector  # noqa: E402

text = sql_connector.describe_text()
check("sql: describe lists tables and columns, with the note",
      "Artikel(ArtikelNr TEXT, Bezeichnung TEXT, Preis REAL)" in text
      and "Lagerplaetze(" in text and "Menge in Stück." in text, text)
check("sql: describe narrows to a table",
      "Lagerplaetze(" in sql_connector.describe_text(only="lager")
      and "Artikel(" not in sql_connector.describe_text(only="lager"))
os.environ["SQL_TABLES"] = "Artikel, Lagerplaetze"
check("sql: SQL_TABLES limits what is described",
      "Gehaelter" not in sql_connector.describe_text())
os.environ.pop("SQL_TABLES")

columns, rows, truncated = sql_connector.run(
    "SELECT a.Bezeichnung, l.Platz, l.Menge FROM Artikel a "
    "JOIN Lagerplaetze l ON l.ArtikelNr = a.ArtikelNr WHERE a.ArtikelNr = 'SV-200'")
check("sql: a query returns its rows",
      columns == ["Bezeichnung", "Platz", "Menge"]
      and rows == [["Sicherheitsventil 10 bar", "B-11", 140]] and not truncated, rows)
check("sql: a query in a markdown block with a semicolon runs too",
      sql_connector.run("```sql\nSELECT count(*) FROM Artikel;\n```")[1] == [[3]])
os.environ["SQL_MAX_ROWS"] = "2"
_c2, _r2, _t2 = sql_connector.run("SELECT ArtikelNr FROM Artikel ORDER BY ArtikelNr")
check("sql: more rows than the limit are cut and marked",
      len(_r2) == 2 and _t2 is True, (_r2, _t2))
os.environ.pop("SQL_MAX_ROWS")


def refused(sql):
    try:
        sql_connector.run(sql)
        return ""
    except kit.Refused as e:
        return str(e)


for bad in ("DELETE FROM Artikel",
            "SELECT 1; DROP TABLE Artikel",
            "SELECT 1 AS [x'] DELETE FROM Artikel -- [y']",
            "SELECT 1 AS \"x'\" DELETE FROM Artikel WHERE 1 = 1 OR \"y'\" = 1",
            "INSERT INTO Artikel VALUES ('x', 'y', 1)",
            "PRAGMA table_info(Artikel)",
            "ATTACH DATABASE 'x.db' AS x"):
    check(f"sql: refused: {bad[:44]}", "abgelehnt" in refused(bad), refused(bad))
check("sql: the rows are still all there",
      sql_connector.run("SELECT count(*) FROM Artikel")[1] == [[3]])

# SQLite itself is opened read-only: the check of the text is not alone.
_con = sql_connector.connect()
try:
    _con.execute("DELETE FROM Artikel")
    wrote = True
except Exception:
    wrote = False
finally:
    _con.close()
check("sql: the connection itself cannot write", not wrote)

os.environ["SQL_TIMEOUT"] = "1"
slow = refused("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
               "SELECT count(*) FROM c")
check("sql: a query that never ends is stopped", "abgebrochen" in slow, slow)
os.environ.pop("SQL_TIMEOUT")

# What each dialect adds: ways to write a string the reader does not know.
for kind, bad in (
        ("postgres", "SELECT $$a'$$ AS x, 1 AS \"y'\""),
        ("postgres", "SELECT E'a\\'' AS x"),
        ("postgres", "SELECT set_config('default_transaction_read_only', 'off', false)"),
        ("postgres", "SELECT pg_read_file('/etc/passwd')"),
        ("mysql", "SELECT 'a\\'' AS x"),
        ("mysql", "SELECT 1 # ' "),
        ("mysql", "SELECT load_file('/etc/passwd')"),
        ("oracle", "SELECT q'[a']' AS x FROM dual"),
        ("oracle", "SELECT utl_http.request('http://x') FROM dual")):
    check(f"sql ({kind}): refused: {bad[:40]}", sql_connector.refusal(bad, kind) != "",
          sql_connector.refusal(bad, kind))
for kind, good in (
        ("postgres", "SELECT name FROM kunden WHERE ort = 'Würzburg' LIMIT 5"),
        ("mysql", "SELECT `name` FROM `kunden` WHERE ort LIKE '%burg' LIMIT 5"),
        ("oracle", "SELECT name FROM kunden WHERE ROWNUM <= 5"),
        ("mssql", "SELECT TOP 5 pfad FROM belege WHERE pfad LIKE '\\\\fs01\\belege%'")):
    check(f"sql ({kind}): passes: {good[:40]}", sql_connector.refusal(good, kind) == "",
          sql_connector.refusal(good, kind))

# Every user with their own database account.
os.environ["SQL_LOGIN"] = "user"
try:
    sql_connector._account(kit.Login())
    own = "no refusal"
except kit.Refused as e:
    own = str(e)
check("sql: with SQL_LOGIN=user a call without login is refused",
      "eigenen Datenbankkonto" in own, own)
check("sql: and the user's login is the database login",
      sql_connector._account(kit.Login("basic", "anna", "pw")) == ("anna", "pw"))
os.environ.pop("SQL_LOGIN")

# --- LocaNoto's side ---

import paths  # noqa: E402

paths.bootstrap()
import benutzer  # noqa: E402
import mcp  # noqa: E402
import mailboxes  # noqa: E402
import mail_watch  # noqa: E402
import pipeline  # noqa: E402
import raeume  # noqa: E402
import answering  # noqa: E402

benutzer.anlege("markus", "Passwort-123456", rolle="admin")
benutzer.anlege("anna", "Passwort-123456")
benutzer.anlege("bert", "Passwort-123456")
raeume.anlegen("lager", "Lager", mitglieder=["anna"])

erp_url = start(sql_connector.build())
demo_url = start(demo)
check("an admin enters a connector for a workspace",
      mailboxes.create("erp", "connector", erp_url, room="lager")[0])
check("and one that every user signs in to",
      mailboxes.create("demo", "connector_login", demo_url)[0])
entry = mcp.lies_konfiguration()["erp"]
check("a connector is never personal and never sends mail on its own",
      entry["persoenlich"] is False and entry["art"] == "connector"
      and not mailboxes.create("x", "connector", erp_url, True, owner="anna",
                               automatisch=True)[0] is False
      and "owner" not in mcp.lies_konfiguration()["x"]
      and not mcp.lies_konfiguration()["x"].get("automatisch"))
mailboxes.remove("x")
kinds = {m["name"]: m["kind"] for m in mailboxes.overview()}
check("it is listed as a data connector, not as a mailbox",
      kinds == {"erp": "connector", "demo": "connector"}
      and mail_watch.mailboxes() == [], (kinds, mail_watch.mailboxes()))
check("only the members of its workspace see it",
      mailboxes.visible_to("anna", "erp") and not mailboxes.visible_to("bert", "erp")
      and not mailboxes.visible_to("markus", "erp")
      and mailboxes.visible_to("bert", "demo"))

connections = mcp.verbinde({"demo": {"Authorization": basic}})
tools = {t["function"]["name"] for t in mcp.als_werkzeugliste(connections)}
check("LocaNoto reads the tools of both connectors",
      {"erp__describe", "erp__query", "demo__stock", "demo__book_out"} <= tools, tools)
check("the connector's own words about itself are read at the handshake",
      "ERP der Musterfirma" in connections["erp"].instructions
      and "describe" in connections["erp"].instructions)
check("tools that are not marked read-only wait for a person",
      connections["demo"].confirm == {"book_out"} and connections["erp"].confirm == set())
described = answering._describe(connections, False)
check("the model is told what each connector is for",
      any("Datenanschluss erp: ERP der Musterfirma" in d for d in described), described)


class Model:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.chat = ns(completions=ns(create=self.create))

    def create(self, **_k):
        calls = self.rounds.pop(0) if self.rounds else []
        return ns(choices=[ns(message=ns(content="", tool_calls=[
            ns(id=f"t{i}", function=ns(name=n, arguments=a))
            for i, (n, a) in enumerate(calls)]))])


chat = [{"role": "user", "content": "Wo liegt das Sicherheitsventil, und buche eins aus."}]
query = "SELECT Platz, Menge FROM Lagerplaetze WHERE ArtikelNr = 'SV-200'"
extra, drafts = pipeline.werkzeuglauf(
    Model([[("erp__describe", "{}")],
           [("erp__query", json.dumps({"sql": query})),
            ("demo__book_out", json.dumps({"article": "SV-200"})),
            ("erp__query", json.dumps({"sql": "DELETE FROM Lagerplaetze"}))]]),
    "m", "sys", chat, connections)
results = [m["content"] for m in extra if m["role"] == "tool"]
check("the model reads the schema and gets the rows of its query",
      "Lagerplaetze(" in results[0] and "| B-11 | 140 |" in results[1], results[:2])
check("the writing tool was not run: it is a draft for the user",
      "booked" not in seen and [d["werkzeug"] for d in drafts] == ["book_out"]
      and drafts[0].get("kind") == "connector"
      and "NICHT ausgefuehrt" in results[2], (seen, drafts))
check("a statement that writes comes back as refused, to the model",
      "abgelehnt" in results[3], results[3])
calls = connections["erp"].tables
check("the query is listed for the answer: which system, which query, how many rows",
      calls == [{"server": "erp", "tool": "query", "query": query, "rows": 1,
                 "source": "erp (SQLite)", "truncated": False}], calls)
check("the user's login went to the connector that asks for one",
      connections["demo"].rufe("stock", {"article": "DB-100"})
      and seen["login"] == ("basic", "anna", "geheim:mit:doppelpunkt"))
for c in connections.values():
    c.schliesse()

# --- PostgreSQL ---

if PG_URL:
    import psycopg
    from urllib.parse import urlsplit

    u = urlsplit(PG_URL)
    with psycopg.connect(PG_URL, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS connector_test CASCADE")
        admin.execute("CREATE SCHEMA connector_test")
        admin.execute("CREATE TABLE connector_test.auftraege "
                      "(nr int, firma text, betrag numeric, termin date)")
        admin.execute("INSERT INTO connector_test.auftraege VALUES "
                      "(1001, 'Meier GmbH', 1250.50, '2026-11-20'), "
                      "(1002, 'Schulz AG', 89.90, '2026-12-01')")
    os.environ.update({"SQL_KIND": "postgres", "SQL_HOST": u.hostname,
                       "SQL_PORT": str(u.port or 5432),
                       "SQL_DATABASE": u.path.lstrip("/") or "postgres",
                       "SQL_USER": u.username or "postgres",
                       "SQL_PASSWORD": u.password or ""})
    pg_text = sql_connector.describe_text(only="connector_test")
    check("postgres: describe", "connector_test.auftraege(nr integer, firma text" in pg_text,
          pg_text)
    c, r, t = sql_connector.run("SELECT firma, betrag, termin FROM connector_test.auftraege "
                                "WHERE nr = 1001")
    result = kit.table(c, r)
    check("postgres: a query, with numbers and dates as JSON carries them",
          result["rows"] == [["Meier GmbH", 1250.5, "2026-11-20"]], result)
    check("postgres: a writing statement is refused by the check",
          "abgelehnt" in refused("UPDATE connector_test.auftraege SET betrag = 0"))
    pg = sql_connector.connect()
    try:
        pg.execute("CREATE TABLE connector_test.x (i int)")
        pg_wrote = "written"
    except Exception as e:
        pg_wrote = str(e)
    finally:
        sql_connector._close(pg)
    check("postgres: the connection is read-only in the database too",
          "read-only" in pg_wrote, pg_wrote)
    os.environ["SQL_TIMEOUT"] = "1"
    check("postgres: a slow query is stopped",
          "abgebrochen" in refused("SELECT count(*) FROM generate_series(1, 2000000000)"),
          refused("SELECT 1"))
    os.environ.pop("SQL_TIMEOUT")
    with psycopg.connect(PG_URL, autocommit=True) as admin:
        admin.execute("DROP SCHEMA connector_test CASCADE")
else:
    print("  --   PostgreSQL skipped (SELFTEST_DATABASE not set)")

print()
if failures:
    print(f"{len(failures)} failed:")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all passed")
