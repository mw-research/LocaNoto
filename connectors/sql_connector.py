"""Data connector for SQL databases: PostgreSQL, MySQL/MariaDB, Microsoft SQL
Server, Oracle, SQLite.

    python connectors/sql_connector.py            # serves on CONNECTOR_PORT (8000)
    python connectors/sql_connector.py --check    # connect once, list the tables

One connector serves one database. LocaNoto's language model gets two
tools: "describe" (which tables and columns there are) and "query" (one
read-only SELECT). It writes the query itself -- so the query is not
trusted, and three things stand between it and the data:

 1. The database account. Give it read rights on what may be read and
    nothing else; this is the only barrier that holds when the others
    fail, and it can only be set in the database.
 2. The check of the statement (sqlpruefung.py, the same LocaNoto uses
    for its built-in database access) plus what each dialect adds:
    exactly one SELECT, no statement that changes data or the session.
 3. The connection itself is read-only where the database offers it
    (PostgreSQL, MySQL, Oracle, SQLite), every query has a time limit
    and a row limit.

SETTINGS (environment)

  SQL_KIND        postgres | mysql | mssql | oracle | sqlite
  SQL_HOST, SQL_PORT, SQL_DATABASE   (sqlite: SQL_DATABASE is the file)
  SQL_USER, SQL_PASSWORD   the read account -- or:
  SQL_LOGIN=user  every user signs in to LocaNoto's entry with their own
                  database account (Basic); the connector connects with
                  it, so the database decides what each person sees
  SQL_TABLES      only these tables are described (comma separated,
                  "table" or "schema.table"). NOT an access limit: a
                  query can name what the account may read.
  SQL_NOTE        a sentence about the data for the model ("Status O =
                  open"), goes out with "describe"
  SQL_MAX_ROWS    rows returned per query (200)
  SQL_TIMEOUT     seconds per query (20)
  CONNECTOR_NAME  the name the connector reports (sql)
  CONNECTOR_ABOUT what this database is, for the model ("ERP of Muster
                  GmbH: articles, orders, stock")

DRIVERS. PostgreSQL (psycopg) and SQL Server (pymssql) are in the
LocaNoto image; SQLite is part of Python. MySQL/MariaDB needs PyMySQL,
Oracle needs oracledb -- add them to an image of your own
(FROM ghcr.io/..., RUN pip install pymysql).
"""
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlpruefung                                    # noqa: E402
from kit import Connector, Refused, table              # noqa: E402

KINDS = ("postgres", "mysql", "mssql", "oracle", "sqlite")
DEFAULT_PORT = {"postgres": 5432, "mysql": 3306, "mssql": 1433, "oracle": 1521}


def _env(name, default=""):
    return os.getenv(name, default).strip()


def _env_int(name, default):
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


class Settings:
    """Read from the environment when asked, so a test can change them."""

    @property
    def kind(self):
        return _env("SQL_KIND").lower()

    @property
    def host(self):
        return _env("SQL_HOST")

    @property
    def port(self):
        return _env_int("SQL_PORT", DEFAULT_PORT.get(self.kind, 0))

    @property
    def database(self):
        return _env("SQL_DATABASE")

    @property
    def per_user(self):
        return _env("SQL_LOGIN").lower() == "user"

    @property
    def tables(self):
        return [t.strip().lower() for t in _env("SQL_TABLES").split(",") if t.strip()]

    @property
    def max_rows(self):
        return max(1, _env_int("SQL_MAX_ROWS", 200))

    @property
    def timeout(self):
        return max(1, _env_int("SQL_TIMEOUT", 20))


S = Settings()

# How much of the schema goes to the model in one answer.
SCHEMA_CHARS = 12000


# --- CONNECTING ---

def _account(login):
    if S.per_user:
        if not login or not login.user:
            raise Refused("Für diese Datenbank meldet sich jeder mit seinem "
                          "eigenen Datenbankkonto an (Einstellungen → "
                          "Verbinden). Es ist keine Anmeldung dabei.")
        return login.user, login.secret
    return _env("SQL_USER"), os.getenv("SQL_PASSWORD", "")


def _driver(module, package):
    try:
        return __import__(module)
    except ImportError:
        raise Refused(f"Der Treiber für {S.kind} fehlt in diesem Abbild "
                      f"(pip install {package}).")


def connect(login=None):
    """A read-only connection to the configured database."""
    kind = S.kind
    if kind not in KINDS:
        raise Refused(f"SQL_KIND ist nicht gesetzt oder unbekannt "
                      f"({', '.join(KINDS)}).")
    if kind == "sqlite":
        con = _sqlite_open()
        con.set_authorizer(_sqlite_read_only)
        end = time.monotonic() + S.timeout
        con.set_progress_handler(lambda: time.monotonic() > end, 5000)
        return con
    user, password = _account(login)
    if kind == "postgres":
        psycopg = _driver("psycopg", "psycopg[binary]")
        con = psycopg.connect(
            host=S.host, port=S.port, dbname=S.database, user=user,
            password=password, connect_timeout=S.timeout,
            options=(f"-c default_transaction_read_only=on "
                     f"-c statement_timeout={S.timeout * 1000}"))
        con.read_only = True
        return con
    if kind == "mysql":
        pymysql = _driver("pymysql", "pymysql")
        con = pymysql.connect(
            host=S.host, port=S.port, database=S.database, user=user,
            password=password, connect_timeout=S.timeout,
            read_timeout=S.timeout, write_timeout=S.timeout, charset="utf8mb4")
        cur = con.cursor()
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        for limit in (f"SET SESSION MAX_EXECUTION_TIME={S.timeout * 1000}",   # MySQL
                      f"SET SESSION max_statement_time={S.timeout}"):         # MariaDB
            try:
                cur.execute(limit)
            except Exception:
                pass
        cur.execute("START TRANSACTION READ ONLY")
        return con
    if kind == "mssql":
        pymssql = _driver("pymssql", "pymssql")
        return pymssql.connect(
            server=S.host, port=S.port, user=user, password=password,
            database=S.database, timeout=S.timeout, login_timeout=S.timeout,
            as_dict=False)
    oracledb = _driver("oracledb", "oracledb")
    con = oracledb.connect(user=user, password=password,
                           dsn=f"{S.host}:{S.port}/{S.database}")
    con.call_timeout = S.timeout * 1000
    con.cursor().execute("SET TRANSACTION READ ONLY")
    return con


def _sqlite_open():
    """The SQLite file, opened read-only (mode=ro)."""
    import pathlib
    path = S.database
    if not path or not os.path.isfile(path):
        raise Refused("SQL_DATABASE zeigt auf keine SQLite-Datei.")
    return sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro",
                           uri=True, check_same_thread=False)


_SQLITE_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _sqlite_read_only(action, *_rest):
    return sqlite3.SQLITE_OK if action in _SQLITE_ALLOWED else sqlite3.SQLITE_DENY


def _close(con):
    try:
        con.rollback()
    except Exception:
        pass
    try:
        con.close()
    except Exception:
        pass


# --- THE CHECK OF A QUERY ---
#
# sqlpruefung.pruefe_abfrage reads a statement the way T-SQL and SQLite
# quote. Each other dialect has ways to write a string that this reader
# does not know -- and where the check and the database disagree about
# where a string ends, a second statement hides. A generated SELECT needs
# none of them, so they are refused outright.
_DIALECT_RULES = {
    "postgres": (
        (re.compile(r"\\"), "Backslash"),                       # E'..\'..'
        (re.compile(r"\$[A-Za-z_0-9]*\$"), "Dollar-Anführungszeichen"),
        (re.compile(r"\b(set_config|pg_read_\w+|pg_ls_\w+|pg_stat_file|"
                    r"lo_import|lo_export|dblink\w*|pg_sleep\w*|"
                    r"pg_terminate_backend|pg_cancel_backend|pg_reload_conf|"
                    r"query_to_xml\w*|pg_advisory\w*)\s*\(", re.I), "Funktion"),
    ),
    "mysql": (
        (re.compile(r"\\"), "Backslash"),                       # 'a\'b'
        (re.compile(r"#"), "Kommentar"),
        (re.compile(r"\b(load_file|sleep|benchmark|get_lock|release_lock|"
                    r"sys_exec|sys_eval)\s*\(", re.I), "Funktion"),
    ),
    "oracle": (
        (re.compile(r"\bn?q'", re.I), "q-Anführungszeichen"),
        (re.compile(r"\b(utl_\w+|dbms_\w+|httpuritype|sys\.\w+)", re.I),
         "Paket"),
    ),
    "mssql": (),
    "sqlite": (),
}


def refusal(sql, kind=None):
    """Why this statement is not run, or ""."""
    ok, why = sqlpruefung.pruefe_abfrage(sql)
    if not ok:
        return why
    for pattern, what in _DIALECT_RULES.get(kind or S.kind, ()):
        if pattern.search(sql):
            return f"{what} nicht zulässig"
    return ""


def run(sql, login=None):
    """(columns, rows, truncated) of one checked query."""
    sql = sqlpruefung.bereinige(sql)
    why = refusal(sql)
    if why:
        raise Refused(f"Abfrage abgelehnt: {why}. Erlaubt ist genau ein "
                      f"SELECT, das nur liest.")
    con = connect(login)
    try:
        cur = con.cursor()
        cur.execute(sql)
        columns = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(S.max_rows + 1)
    except Refused:
        raise
    except Exception as e:
        text = " ".join(str(e).split())[:400]
        if "interrupt" in text.lower() or "timeout" in text.lower():
            raise Refused(f"Abfrage abgebrochen: länger als {S.timeout} s. "
                          f"Enger fassen.")
        raise Refused(f"Die Datenbank hat die Abfrage nicht ausgeführt: {text}")
    finally:
        _close(con)
    return columns, [list(r) for r in rows[:S.max_rows]], len(rows) > S.max_rows


# --- THE SCHEMA ---

_SCHEMA_SQL = {
    "postgres": ("SELECT table_schema, table_name, column_name, data_type "
                 "FROM information_schema.columns WHERE table_schema NOT IN "
                 "('pg_catalog', 'information_schema') "
                 "ORDER BY table_schema, table_name, ordinal_position"),
    "mysql": ("SELECT table_schema, table_name, column_name, data_type "
              "FROM information_schema.columns WHERE table_schema = DATABASE() "
              "ORDER BY table_schema, table_name, ordinal_position"),
    "mssql": ("SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
              "FROM INFORMATION_SCHEMA.COLUMNS "
              "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"),
    "oracle": ("SELECT owner, table_name, column_name, data_type "
               "FROM all_tab_columns WHERE owner NOT IN ('SYS', 'SYSTEM', "
               "'XDB', 'MDSYS', 'CTXSYS', 'OUTLN', 'DBSNMP', 'WMSYS', "
               "'ORDSYS', 'ORDDATA', 'LBACSYS', 'GSMADMIN_INTERNAL', "
               "'APPQOSSYS', 'AUDSYS', 'OJVMSYS', 'DVSYS', 'OLAPSYS') "
               "ORDER BY owner, table_name, column_id"),
}


def schema(login=None):
    """{"schema.table": [(column, type), ...]} of what the account sees."""
    # SQLite: its own connection without the authorizer -- that one is for
    # the model's queries, and PRAGMA table_info is not a SELECT.
    con = _sqlite_open() if S.kind == "sqlite" else connect(login)
    try:
        cur = con.cursor()
        out = {}
        if S.kind == "sqlite":
            names = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                out[name] = [(r[1], r[2] or "") for r in
                             cur.execute(f"PRAGMA table_info({quoted})")]
            return out
        cur.execute(_SCHEMA_SQL[S.kind])
        for owner, name, column, kind in cur.fetchall():
            out.setdefault(f"{owner}.{name}", []).append((column, str(kind or "")))
        return out
    except Refused:
        raise
    except Exception as e:
        raise Refused("Die Datenbank ließ sich nicht lesen: "
                      + " ".join(str(e).split())[:300])
    finally:
        _close(con)


def describe_text(login=None, only=""):
    tables = schema(login)
    wanted = S.tables
    if wanted:
        tables = {t: c for t, c in tables.items()
                  if t.lower() in wanted or t.split(".")[-1].lower() in wanted}
    only = str(only or "").strip().lower()
    if only:
        tables = {t: c for t, c in tables.items() if only in t.lower()}
    if not tables:
        return "Keine Tabellen gefunden, die dieses Konto lesen darf."
    lines, used, left = [], 0, 0
    for name, columns in tables.items():
        line = f"{name}({', '.join(f'{c} {k}'.strip() for c, k in columns)})"
        if used + len(line) > SCHEMA_CHARS:
            left += 1
            continue
        lines.append(line)
        used += len(line)
    head = f"Datenbank ({S.kind}), {len(tables)} Tabellen:"
    note = _env("SQL_NOTE")
    tail = (f"\n({left} weitere Tabellen nicht gezeigt -- mit dem Argument "
            f"\"table\" gezielt nachsehen.)" if left else "")
    return (head + "\n" + "\n".join(lines) + tail
            + (f"\nHinweis: {note}" if note else ""))


# --- THE CONNECTOR ---

DIALECT_NAME = {"postgres": "PostgreSQL", "mysql": "MySQL/MariaDB",
                "mssql": "T-SQL (Microsoft SQL Server)", "oracle": "Oracle SQL",
                "sqlite": "SQLite"}


def build():
    about = _env("CONNECTOR_ABOUT") or "Eine Datenbank des Betriebs."
    con = Connector(
        _env("CONNECTOR_NAME") or "sql",
        instructions=(f"{about} Für Fragen nach Daten daraus: zuerst "
                      f"\"describe\" (welche Tabellen und Spalten es gibt), "
                      f"dann \"query\" mit genau einem SELECT in "
                      f"{DIALECT_NAME.get(S.kind, 'SQL')}. Nur lesen. Nenne "
                      f"in der Antwort, dass die Zahlen aus dieser Datenbank "
                      f"stammen."))

    @con.tool("describe",
              "Tabellen und Spalten dieser Datenbank. Vor der ersten Abfrage "
              "aufrufen.",
              {"type": "object", "properties": {"table": {
                  "type": "string",
                  "description": "optional: nur Tabellen, deren Name das enthält"}}})
    def describe(args, login):
        return describe_text(login, args.get("table"))

    @con.tool("query",
              "Führt genau ein lesendes SELECT aus und liefert die Zeilen. "
              "Tabellen- und Spaltennamen aus \"describe\" verwenden.",
              {"type": "object",
               "properties": {"sql": {"type": "string",
                                      "description": "ein SELECT, ohne Kommentare"}},
               "required": ["sql"]})
    def query(args, login):
        columns, rows, truncated = run(str(args.get("sql") or ""), login)
        return table(columns, rows, truncated=truncated,
                     source=f"{con.name} ({DIALECT_NAME.get(S.kind, S.kind)})")

    return con


def main():
    if "--check" in sys.argv[1:]:
        try:
            print(describe_text())
        except Refused as e:
            print(e)
            return 1
        return 0
    return build().serve()


if __name__ == "__main__":
    sys.exit(main())
