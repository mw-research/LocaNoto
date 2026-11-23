"""Self-test, part 06: Web research in the background, a new embedding model, cited sources.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- WEB SEARCHES IN THE BACKGROUND (web_research.py) ---
import threading as _th_w
import time as _time_w
import mcp as _mcp_r
import web_research as _wr
import dateisperre
import web_sources as _wsrc

_real_w = (_wsrc.search, _wsrc.take_over, _mcp_r.websuche_server)
_gate_w = _th_w.Event()


def _fake_search(query, count):
    _gate_w.wait(5)
    return [{"nr": i + 1, "titel": f"Treffer {i}", "adresse": f"https://e{i}.example/norm",
             "text": "Ausfuehrungsklassen", "anfrage": query} for i in range(count)]


_taken_w = []
_wsrc.search = _fake_search
_wsrc.take_over = lambda user, pages: _taken_w.extend(pages) or [
    {"title": p["title"], "url": p["url"], "passages": 2, "note": "", "file": "x.md"} for p in pages]
_mcp_r.websuche_server = lambda: {"websuche"}


def _wait_w(user, task_id):
    for _ in range(100):
        t = _wr.task_of(user, task_id)
        if t["state"] != "running":
            return t
        _time_w.sleep(0.05)
    return t


try:
    _t1 = _wr.start_search("markus", "  DIN EN   1090 ", 12)
    _t2 = _wr.start_search("markus", "EN 13445", 3)
    try:
        _wr.start_search("markus", "dritte Suche")
        pruef("a third search at the same time is refused", False)
    except _wr.Refused:
        pruef("a third search at the same time is refused", True)
    pruef("a running search is listed, its hits not yet there",
          [t["state"] for t in _wr.tasks("markus")] == ["running", "running"]
          and not _wr.unseen("markus"))
    _gate_w.set()
    _d1 = _wait_w("markus", _t1["id"])
    _wait_w("markus", _t2["id"])
    pruef("the search runs on its own and keeps its hits",
          _d1["state"] == "done" and len(_d1["hits"]) == 12 and _d1["query"] == "DIN EN 1090",
          _d1.get("error"))
    pruef("finished searches are a notice until looked at",
          {t["id"] for t in _wr.unseen("markus")} == {_t1["id"], _t2["id"]})
    _wr.task_of("markus", _t1["id"], seen=True)
    pruef("looking at one removes its notice",
          [t["id"] for t in _wr.unseen("markus")] == [_t2["id"]])
    _raw_w = statefiles.read_bytes(_wr._path("markus"))
    pruef("the task list is stored encrypted", b"1090" not in _raw_w and b"Treffer" not in _raw_w)
    try:
        _wr.task_of("anna", _t1["id"])
        pruef("someone else's search is not visible", False)
    except _wr.Refused:
        pruef("someone else's search is not visible", True)
    _to = _wr.start_take_over("markus", _t1["id"], [0, 2, 2, 99])
    _done_to = _wait_w("markus", _to["id"])
    pruef("chosen hits are taken over in the background, each once",
          _done_to["state"] == "done" and [p["url"] for p in _taken_w]
          == ["https://e0.example/norm", "https://e2.example/norm"]
          and _done_to["result"][0]["passages"] == 2, _done_to.get("error"))
    pruef("and the take-over is a notice of its own with what was stored",
          any(t["id"] == _to["id"] and t["stored"] == 2 for t in _wr.unseen("markus")))
    try:
        _wr.start_take_over("markus", _to["id"], [0])
        pruef("only hits of a search can be taken over", False)
    except _wr.Refused:
        pruef("only hits of a search can be taken over", True)
    with dateisperre.gesperrt(_wr._path("markus")):
        _items_w = _wr._load("markus")
        _items_w.insert(0, dict(_items_w[0], id="alt", state="running",
                                started="2020-01-01T00:00:00+00:00"))
        _wr._save("markus", _items_w)
    pruef("a task of a server that went away counts as failed",
          next(t for t in _wr.tasks("markus") if t["id"] == "alt")["state"] == "failed")
    _wr.remove("markus", "alt")
    pruef("a task can be removed", all(t["id"] != "alt" for t in _wr.tasks("markus")))
    _mcp_r.websuche_server = lambda: set()
    try:
        _wr.start_search("markus", "ohne Dienst")
        pruef("no search starts without a web search service", False)
    except _wsrc.Unavailable:
        pruef("no search starts without a web search service", True)
finally:
    _wsrc.search, _wsrc.take_over, _mcp_r.websuche_server = _real_w
    for _t in _wr.tasks("markus"):
        _wr.remove("markus", _t["id"])

# --- A NEW EMBEDDING MODEL (vector_columns.py, reembed.py) ---
import reembed as _reembed
import datetime as _dt_re
_at = lambda h: _dt_re.datetime(2026, 11, 4, h, 30)
pruef("the re-embedding job works in a window over midnight, and only there",
      _reembed.window("20-6", _at(23)) and _reembed.window("20-6", _at(3))
      and not _reembed.window("20-6", _at(12)) and _reembed.window("", _at(12))
      and _reembed.window("9-17", _at(10)) and not _reembed.window("9-17", _at(18)))
_db_active = _reembed.database.active
_reembed.database.active = lambda: False
try:
    pruef("without Postgres it says that a new model means reading again",
          _reembed.main([]) == 1)
finally:
    _reembed.database.active = _db_active
import hintergrund as _hg_re
pruef("it is a job the admin page can start",
      _hg_re.LAEUFE.get("vektoren", ("",))[0] == "reembed.py")
_pgc_src = open(os.path.join(_ROOT, "pg_collection.py"),
                encoding="utf-8").read()
pruef("the Postgres collection never names a vector column itself",
      "embedding <->" not in _pgc_src and "metadata, embedding)" not in _pgc_src
      and _pgc_src.count("vector_columns.active()") == 3)

# --- ONLY CITED SOURCES BELOW THE ANSWER (pipeline.cited_sources) ---
_src_c = [{"file": "Pruefvorschrift.pdf", "page": 3}, {"file": "Pruefvorschrift.pdf", "page": 4},
          {"file": "Handbuch Reklamation.md", "page": 1}, {"file": "Wartung.pdf", "page": 7},
          {"file": "Wartung.pdf", "page": 9}]
_c, _o = pipeline.cited_sources(_src_c, "Alle vier Jahre [Pruefvorschrift.pdf, Seite 3]. "
                                "Vorgehen siehe [Handbuch Reklamation, Seite 1; Wartung.pdf, Seiten 8-9].")
pruef("only the sources the answer cites come first; the rest apart",
      [(s["file"], s["page"]) for s in _c] == [("Pruefvorschrift.pdf", 3),
                                               ("Handbuch Reklamation.md", 1), ("Wartung.pdf", 9)]
      and [(s["file"], s["page"]) for s in _o] == [("Pruefvorschrift.pdf", 4), ("Wartung.pdf", 7)],
      (_c, _o))
pruef("an English citation counts too",
      [s["page"] for s in pipeline.cited_sources(_src_c, "Every four years [Pruefvorschrift.pdf, page 4].")[0]] == [4])
pruef("an answer without citations keeps every source",
      pipeline.cited_sources(_src_c, "Keine Angabe in den Dokumenten.") == (_src_c, []))
pruef("citations of unknown files keep every source",
      pipeline.cited_sources(_src_c, "[Andere.pdf, Seite 2]") == (_src_c, []))
