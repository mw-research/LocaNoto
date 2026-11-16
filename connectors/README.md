# Data connectors

A data connector links LocaNoto to one system: an ERP, an MES, a database,
anything that can be asked. It is a small service of its own (a container,
a pod). LocaNoto does not know the system; it knows the interface on this
page. Whoever has a system builds a connector for it and enters its
address in LocaNoto.

| File | What it is |
|---|---|
| `kit.py` | The interface as a library: one file, Python standard library only. Copy it next to your connector. |
| `sql_connector.py` | A complete connector for PostgreSQL, MySQL/MariaDB, Microsoft SQL Server, Oracle and SQLite. Use it as it is, or as the example to start from. |

## The interface

A connector speaks MCP (Model Context Protocol) over HTTP: JSON-RPC 2.0,
one request per POST.

| Request | Purpose |
|---|---|
| `POST /mcp` | `initialize`, `tools/list`, `tools/call`, `ping` |
| `GET /healthz` | `{"ok": true}` when the service runs |

### `initialize`: what the connector is for

The answer carries `instructions`, one or two sentences for the language
model: which system this is and for which questions to use it.

```json
{"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
 "serverInfo": {"name": "erp", "version": "1.0"},
 "instructions": "ERP of Muster GmbH: articles, orders, stock. First describe, then query."}
```

LocaNoto puts this sentence in front of the model together with the tools.

### `tools/list`: the tools, and which of them only read

Each tool has `name`, `description`, `inputSchema` (JSON Schema of its
arguments) and `annotations.readOnlyHint`.

```json
{"name": "query", "description": "One read-only SELECT.",
 "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}},
                 "required": ["sql"]},
 "annotations": {"readOnlyHint": true}}
```

**A tool that is not marked `readOnlyHint: true` is never run on the
model's word.** LocaNoto shows the call to the user as a draft with its
arguments, and only the user's click runs it. A tool that says nothing
counts as writing.

There are no fixed tool names. Two are recommended, because models use
them well: `describe` (what there is: tables, objects, fields) and `query`
(read). Their arguments are the connector's own; the model reads them from
`inputSchema` and `description`.

### `tools/call`: text for the model, tables for the page

```json
{"content": [{"type": "text", "text": "| article | place |\n|---|---|\n| SV-200 | B-11 |"}],
 "structuredContent": {"columns": ["article", "place"], "rows": [["SV-200", "B-11"]],
                       "source": "ERP, table Lagerplaetze", "truncated": false},
 "isError": false}
```

- `content` (text) is what the model reads.
- `structuredContent` with `columns` and `rows` is a table. LocaNoto lists
  it under the answer: which connector, which tool, which arguments, how
  many rows, `source`. `truncated: true` says there were more rows than
  returned. If `content` is empty, LocaNoto writes the table out for the
  model itself.
- `isError: true` with a text is a refusal or a failure. The text reaches
  the model and the user, so say what to do ("not a read-only query").

Everything a tool returns is treated as material, never as an instruction
to the model, like the text of a document.

### The user's login

An entry in LocaNoto can ask every user for a login to the system (user
and password, or a token). LocaNoto keeps it in the browser session only
and sends it with every call in the `Authorization` header (`Basic` or
`Bearer`). The connector passes it on to the system, which checks the
rights itself. A connector stores nothing.

Without a login per user, the connector uses an account of its own, set
in its environment.

## Writing a connector

```python
from kit import Connector, Refused, table

con = Connector("mes", instructions="MES of plant 2: orders in production, "
                                    "machine states. Use it for questions "
                                    "about running orders.")

@con.tool("orders", "Orders in production, optionally of one machine.",
          {"type": "object", "properties": {"machine": {"type": "string"}}})
def orders(args, login):
    if not login:
        raise Refused("Sign in to the MES first (Settings).")
    rows = mes_client(login.user, login.secret).orders(args.get("machine"))
    return table(["order", "machine", "state"], rows, source="MES plant 2")

@con.tool("release", "Releases an order for production.",
          {"type": "object", "properties": {"order": {"type": "string"}},
           "required": ["order"]},
          read_only=False)                # a draft; runs on the user's click
def release(args, login):
    mes_client(login.user, login.secret).release(args["order"])
    return f"Order {args['order']} released."

con.serve()                               # CONNECTOR_PORT, default 8000
```

A tool function gets its arguments and the login of the call. It returns
text or `table(...)`, or raises `Refused` with words for the user.

## The SQL connector

One connector serves one database.

| Variable | Meaning |
|---|---|
| `SQL_KIND` | `postgres`, `mysql`, `mssql`, `oracle` or `sqlite` |
| `SQL_HOST`, `SQL_PORT`, `SQL_DATABASE` | where the database is (SQLite: `SQL_DATABASE` is the file) |
| `SQL_USER`, `SQL_PASSWORD` | the read account of the connector |
| `SQL_LOGIN=user` | instead: every user signs in with their own database account |
| `SQL_TABLES` | only these tables are described. Not an access limit. |
| `SQL_NOTE` | a sentence about the data for the model |
| `SQL_MAX_ROWS`, `SQL_TIMEOUT` | rows per query (200), seconds per query (20) |
| `CONNECTOR_NAME`, `CONNECTOR_ABOUT` | the connector's name and what the database is |
| `CONNECTOR_PORT` | port to listen on (8000) |

The model writes the query, so it is not trusted:

1. **The database account** has read rights on what may be read and
   nothing else. This is the barrier that holds when the others fail.
2. **The statement is checked:** exactly one SELECT, no statement that
   changes data or the session, none of the quoting styles a dialect has
   beyond `'...'`.
3. **The connection is read-only** where the database offers it
   (PostgreSQL, MySQL, Oracle, SQLite); every query has a time limit and
   a row limit.

Tested: SQLite and PostgreSQL (`test_connector.py`). Microsoft SQL Server
uses the driver LocaNoto's built-in database access uses. For MySQL/MariaDB
and Oracle the driver has to be added to the image (`pip install pymysql`,
`pip install oracledb`); these two paths have not run against a server.

`python connectors/sql_connector.py --check` connects once and prints the
tables the account sees.

## Running it

A connector runs next to LocaNoto and is reached only by it.

Docker Compose, in the installation's `compose.yaml`:

```yaml
  erp:
    image: ghcr.io/mw-research/locanoto:enterprise-schlank
    command: ["python", "connectors/sql_connector.py"]
    restart: unless-stopped
    environment:
      SQL_KIND: postgres
      SQL_HOST: erp-db.firma.local
      SQL_DATABASE: erp
      SQL_USER: locanoto_read
      SQL_PASSWORD: ${ERP_PASSWORD}
      CONNECTOR_NAME: erp
      CONNECTOR_ABOUT: "ERP der Firma: Artikel, Aufträge, Lager."
```

Kubernetes: a Deployment with the same command and environment (the
password from a Secret), a Service on port 8000, and a NetworkPolicy that
lets in only LocaNoto's server and worker and lets out only the database:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: erp}
spec:
  podSelector: {matchLabels: {app: erp-connector}}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector:
            matchExpressions:
              - {key: app.kubernetes.io/component, operator: In, values: [server, worker]}
      ports: [{protocol: TCP, port: 8000}]
  egress:
    - ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]
    - to: [{ipBlock: {cidr: 10.20.30.40/32}}]      # the database
      ports: [{protocol: TCP, port: 5432}]
```

In LocaNoto: **Admin area → Mailboxes → Create**, kind "Datenanschluss",
address `http://erp:8000/mcp`. Assign it to a workspace: only its members
see the connector and can ask it.
