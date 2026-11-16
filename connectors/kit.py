"""A data connector for LocaNoto in one file: MCP over HTTP, standard library only.

A connector is a small service of its own (a pod, a container) that knows
ONE system -- an ERP, an MES, a database -- and offers LocaNoto a few
tools to ask it. LocaNoto does not know the system; it knows this
interface. Copy this file next to your connector and write:

    from kit import Connector, table

    con = Connector("warehouse", instructions="Stock and storage places "
                    "of the warehouse system. Use it for questions about "
                    "articles, quantities and places.")

    @con.tool("query", "Stock of an article.",
              {"type": "object",
               "properties": {"article": {"type": "string"}},
               "required": ["article"]})
    def query(args, login):
        rows = my_system.stock(args["article"], user=login.user,
                               password=login.secret)
        return table(["article", "place", "quantity"], rows,
                     source="warehouse system")

    con.serve()            # port from CONNECTOR_PORT, default 8000

THE INTERFACE (connectors/README.md has it in full)

  POST /mcp      JSON-RPC 2.0: initialize, tools/list, tools/call, ping
  GET  /healthz  {"ok": true}

  initialize     answers with "instructions": what this connector is for.
                 LocaNoto puts that sentence in front of the model.
  tools/list     every tool with name, description, inputSchema and
                 annotations.readOnlyHint. A tool that is not marked
                 read-only is never run by the model: LocaNoto shows the
                 call to the user as a draft, and only a click runs it.
  tools/call     answers with text for the model and, for data,
                 structuredContent {"columns", "rows", "source",
                 "truncated"} -- LocaNoto lists such a result under the
                 answer.

  The user's login for the system arrives with every call in the
  Authorization header (Basic or Bearer), if the entry in LocaNoto asks
  for one. The connector hands it to the system, which checks the rights
  itself. Nothing is stored.
"""
import base64
import datetime
import decimal
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTOCOL = "2025-03-26"

# How many rows of a table go to the model as text. The whole table (up
# to what the tool returned) is in structuredContent.
TEXT_ROWS = 50
# The largest request body read.
MAX_BODY = 1 << 20


class Refused(Exception):
    """The tool's answer when it does not do what was asked.

    Its text goes to the model and so to the user: say what is wrong in
    words they can act on ("not a read-only query", "sign in first").
    """


class Login:
    """What the Authorization header of a call carried."""

    def __init__(self, kind="", user="", secret=""):
        self.kind, self.user, self.secret = kind, user, secret

    def __bool__(self):
        return bool(self.secret)


def login_from(header):
    """Login from an Authorization header value ("" if there is none)."""
    header = str(header or "").strip()
    low = header.lower()
    if low.startswith("basic "):
        try:
            user, _, secret = base64.b64decode(header[6:]).decode(
                "utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return Login()
        return Login("basic", user, secret)
    if low.startswith("bearer "):
        return Login("bearer", "", header[7:].strip())
    return Login()


def plain(value):
    """A cell as something JSON can carry."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else str(value)
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[{len(bytes(value))} bytes]"
    return str(value)


def table(columns, rows, source="", truncated=False, text=""):
    """A tool result that is a table.

    columns: names. rows: sequences of cells. source: where it comes from,
    in words a user understands ("ERP, table Lagerplaetze"). truncated:
    there were more rows than returned. text: a sentence for the model in
    front of the table (optional).
    """
    return {"columns": [str(c) for c in columns],
            "rows": [[plain(v) for v in row] for row in rows],
            "source": str(source or ""), "truncated": bool(truncated),
            "text": str(text or "")}


def as_markdown(result, limit=TEXT_ROWS):
    """The table of a result as text for the model."""
    columns, rows = result["columns"], result["rows"]
    if not columns:
        return "(no result)"
    if not rows:
        return "(the query returned no rows)"
    cell = lambda v: "" if v is None else str(v).replace("\n", " ").replace("|", "\\|")
    out = ["| " + " | ".join(cell(c) for c in columns) + " |",
           "|" + "|".join("---" for _ in columns) + "|"]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows[:limit]]
    more = len(rows) - limit
    if more > 0 or result.get("truncated"):
        out.append(f"({len(rows)} rows returned"
                   + (f", the first {limit} shown" if more > 0 else "")
                   + ("; there are more than were returned -- narrow the query"
                      if result.get("truncated") else "") + ")")
    return "\n".join(out)


class Connector:
    def __init__(self, name, instructions="", version="1.0"):
        self.name, self.instructions, self.version = name, instructions, version
        self._tools = {}

    def tool(self, name, description, schema=None, read_only=True):
        """Register a function f(args, login) as a tool.

        It returns text, or table(...). read_only=False marks a tool that
        changes something in the system: LocaNoto then never runs it on
        the model's word, only on the user's click.
        """
        def register(function):
            self._tools[name] = {
                "function": function, "description": description,
                "schema": schema or {"type": "object", "properties": {}},
                "read_only": bool(read_only)}
            return function
        return register

    # --- JSON-RPC ---

    def _call(self, params, login):
        entry = self._tools.get(params.get("name"))
        if entry is None:
            return {"content": [{"type": "text",
                                 "text": f"Unknown tool: {params.get('name')}"}],
                    "isError": True}
        try:
            result = entry["function"](params.get("arguments") or {}, login)
        except Refused as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:
            # The class and the message, not a traceback: the text reaches
            # the model.
            return {"content": [{"type": "text",
                                 "text": f"{type(e).__name__}: {str(e)[:500]}"}],
                    "isError": True}
        if isinstance(result, dict) and "columns" in result and "rows" in result:
            text = (result.get("text") + "\n\n" if result.get("text") else "") \
                + as_markdown(result)
            structured = {k: result[k] for k in ("columns", "rows", "source",
                                                 "truncated")}
            return {"content": [{"type": "text", "text": text}],
                    "structuredContent": structured, "isError": False}
        return {"content": [{"type": "text", "text": str(result or "")}],
                "isError": False}

    def handle(self, message, authorization=""):
        """One JSON-RPC message -> the answer, or None for a notification."""
        number = message.get("id")
        if number is None:
            return None
        method = message.get("method")
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL,
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": self.name, "version": self.version},
                      "instructions": self.instructions}
        elif method == "tools/list":
            result = {"tools": [
                {"name": n, "description": t["description"],
                 "inputSchema": t["schema"],
                 "annotations": {"readOnlyHint": t["read_only"]}}
                for n, t in self._tools.items()]}
        elif method == "tools/call":
            result = self._call(message.get("params") or {},
                                login_from(authorization))
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": number,
                    "error": {"code": -32601, "message": f"unknown: {method}"}}
        return {"jsonrpc": "2.0", "id": number, "result": result}

    # --- HTTP ---

    def handler(self):
        connector = self

        class Service(BaseHTTPRequestHandler):
            server_version = "LocaNoto-Connector"

            def log_message(self, *args):
                # No request log: the questions belong to whoever asks.
                pass

            def _send(self, code, data=None):
                raw = json.dumps(data).encode() if data is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/healthz":
                    return self._send(200, {"ok": True, "name": connector.name})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                if self.path.rstrip("/") != "/mcp":
                    return self._send(404, {"error": "not found"})
                try:
                    length = min(int(self.headers.get("Content-Length") or 0),
                                 MAX_BODY)
                    message = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "not JSON"})
                answer = connector.handle(
                    message if isinstance(message, dict) else {},
                    self.headers.get("Authorization", ""))
                if answer is None:
                    return self._send(202)
                self._send(200, answer)

        return Service

    def server(self, port=None, host="0.0.0.0"):
        port = int(port if port is not None
                   else os.getenv("CONNECTOR_PORT", "8000"))
        return ThreadingHTTPServer((host, port), self.handler())

    def serve(self, port=None, host="0.0.0.0"):
        srv = self.server(port, host)
        print(f"Connector '{self.name}' on port {srv.server_address[1]}",
              flush=True)
        srv.serve_forever()
        return 0


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
