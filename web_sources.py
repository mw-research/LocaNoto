"""Sources from the web: search, read, take over into the own room.

The same three steps as "Quellen im Netz" on the Streamlit page, without
the page:

    search(query, count=10)           -> [{nr, titel, adresse, text, anfrage}]
    read(url)                         -> plain text of the page
    take_over(user, pages)            -> [{title, passages, note, file}]

All three go through the web search service (websuche.py, an MCP server):
LocaNoto itself never opens a foreign page. Only the search term leaves
the house -- the user types it; no model writes it from documents.

Taken over pages always land in the user's own room (folder
"Suchergebnisse"); aufnehmen.webseite_aufnehmen decides that, not the
caller. Shared rooms are filled only by moving a document on purpose.
"""
import mcp
import pipeline


class Unavailable(Exception):
    """No web search service is set up or reachable."""


def _connections():
    servers = mcp.websuche_server()
    if not servers:
        raise Unavailable("No web search is set up.")
    return mcp.verbinde(ohne=set(mcp.lies_konfiguration()) - servers)


def _call(tool, arguments):
    connections = _connections()
    error = "No web search service reachable."
    try:
        for c in connections.values():
            try:
                return c.rufe(tool, arguments)
            except Exception as e:
                error = f"Web search failed ({type(e).__name__})."
    finally:
        for c in connections.values():
            try:
                c.schliesse()
            except Exception:
                pass
    raise Unavailable(error)


def search(query, count=10):
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("Empty search term.")
    text = _call("web_suchen", {"anfrage": query, "anzahl": int(count),
                                "lesen": 0})
    return pipeline.webtreffer_aus_text(text)


def read(url):
    """The whole page as plain text -- no scripts, no images."""
    if not str(url or "").startswith(("http://", "https://")):
        raise ValueError("Only http and https addresses.")
    return _call("seite_lesen", {"adresse": url}).split("\n\n", 1)[-1]


def take_over(user, pages):
    """pages: [{title, url, text?, read?, query?}] into the own room.

    read=True means text is the whole page as the user read it (read()),
    and exactly that is taken over. Otherwise the page is read now; if
    that fails, the excerpt in text is used.
    """
    import aufnehmen
    out = []
    for p in pages:
        title = p.get("titel") or p.get("title") or ""
        url = p.get("adresse") or p.get("url") or ""
        text = p.get("text") or ""
        if not p.get("read"):
            try:
                text = read(url)
            except Exception:
                pass
        try:
            n, note, name = aufnehmen.webseite_aufnehmen(
                title, url, text,
                anfrage=p.get("query") or p.get("anfrage") or "",
                benutzer_=user)
            out.append({"title": title, "url": url, "passages": n,
                        "note": note, "file": name})
        except Exception as e:
            out.append({"title": title, "url": url, "passages": 0,
                        "note": f"{type(e).__name__}: {e}", "file": ""})
    return out
