"""Oberflaechentexte fuer die Uebersetzung einwickeln und einsammeln.

    python uebersetzen.py --einwickeln app.py verwaltung.py
    python uebersetzen.py --sammeln          alle Texte als JSON
    python uebersetzen.py --fehlend          was sprache_en.json noch fehlt

EINWICKELN setzt tx(...) um die Texte, die in der Oberflaeche erscheinen:
Beschriftungen, Hilfetexte, Platzhalter, Meldungen. Auswahlfelder
bekommen eine uebersetzte Anzeige (format_func) -- ihre Werte bleiben
deutsch, weil der Code sie mit deutschen Texten vergleicht. Was schon
eingewickelt ist, bleibt, wie es ist; ein zweiter Lauf aendert nichts.

SAMMELN liest, was eingewickelt ist, und dazu die Meldungen der Module,
die die Oberflaeche anzeigt -- (ok, "...") in einem return und der Text
eines raise. Ein f-String wird ein Muster: jeder eingesetzte Wert ein {}.
"""
import ast
import json
import os
import re
import sys

BASIS = os.path.dirname(os.path.abspath(__file__))
OBERFLAECHE = ("app.py", "verwaltung.py")

# Erstes Argument ist eine Beschriftung.
BESCHRIFTET = {
    "button", "checkbox", "toggle", "text_input", "text_area", "selectbox",
    "multiselect", "radio", "expander", "header", "subheader", "title",
    "markdown", "caption", "info", "warning", "error", "success",
    "form_submit_button", "file_uploader", "number_input", "chat_input",
    "spinner", "link_button", "write", "download_button", "date_input",
    "slider", "select_slider", "toast", "metric", "status", "popover",
}
# Hier ist auch eine Variable eine Meldung -- sie kommt aus einem Modul.
MELDUNG = {"info", "warning", "error", "success", "caption", "toast"}
AUSWAHL = {"selectbox", "radio", "multiselect", "select_slider"}
SCHLUESSELWOERTER = {"help", "placeholder", "label"}

_WORT = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


def _st_aufruf(knoten):
    """Name der Streamlit-Methode, oder ''. st.x(...) und st.sidebar.x(...)."""
    f = knoten.func
    if not isinstance(f, ast.Attribute):
        return ""
    wurzel = f.value
    while isinstance(wurzel, ast.Attribute):
        wurzel = wurzel.value
    if isinstance(wurzel, ast.Name) and wurzel.id == "st":
        return f.attr
    return ""


def _ist_tx(k):
    return (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
            and k.func.id == "tx")


def _schluessel(k):
    """(art, text) eines Textknotens, art 'texte' oder 'muster', sonst None."""
    if isinstance(k, ast.Constant) and isinstance(k.value, str):
        return "texte", k.value
    if isinstance(k, ast.JoinedStr):
        teile = []
        for w in k.values:
            if isinstance(w, ast.Constant):
                teile.append(str(w.value).replace("{}", "{ }"))
            else:
                teile.append("{}")
        return "muster", "".join(teile)
    return None


def _sprachlich(text):
    """Enthaelt der Text Woerter ausserhalb von Platzhaltern und Tags?"""
    ohne = re.sub(r"<[^>]*>|\{\}|`[^`]*`|https?://\S+", " ", text)
    return bool(_WORT.search(ohne))


class _Stelle:
    def __init__(self, knoten, art):
        self.k, self.art = knoten, art


def _stuecke(k):
    """Die Textstuecke eines zusammengesetzten Ausdrucks.

    "a" + ("b" if x else "") laesst sich als Ganzes nicht nachschlagen --
    zur Laufzeit ist es mal "ab", mal "a". Die Stuecke einzeln schon.
    """
    if isinstance(k, ast.BinOp) and isinstance(k.op, ast.Add):
        return _stuecke(k.left) + _stuecke(k.right)
    if isinstance(k, ast.IfExp):
        return _stuecke(k.body) + _stuecke(k.orelse)
    s = _schluessel(k)
    if s and _sprachlich(s[1]):
        return [k]
    return []


def _zusammengesetzt(k):
    return isinstance(k, (ast.BinOp, ast.IfExp))


def _text_stellen(k, meldung=False):
    """Was an einer Textstelle zu tun ist."""
    if _ist_tx(k):
        innen = k.args[0] if k.args else None
        if innen is not None and _zusammengesetzt(innen) and _stuecke(innen):
            # tx(a + b) -> tx(a) + b: auspacken, Stuecke einwickeln
            return ([_Stelle(k, "auspacken")]
                    + [_Stelle(x, "tx") for x in _stuecke(innen)])
        return []
    if _zusammengesetzt(k):
        teile = _stuecke(k)
        if teile:
            return [_Stelle(x, "tx") for x in teile]
        if any(_ist_tx(x) for x in ast.walk(k)):
            return []  # schon in Stuecken eingewickelt
    s = _schluessel(k)
    if s and _sprachlich(s[1]):
        return [_Stelle(k, "tx")]
    if s is None and meldung:
        return [_Stelle(k, "tx")]
    return []


def stellen(baum):
    """Alle Knoten, die eingewickelt bzw. ergaenzt werden."""
    aus = []
    for k in ast.walk(baum):
        if not isinstance(k, ast.Call):
            continue
        name = _st_aufruf(k)
        if name not in BESCHRIFTET:
            continue
        if k.args:
            aus += _text_stellen(k.args[0], meldung=name in MELDUNG)
        for kw in k.keywords:
            if kw.arg in SCHLUESSELWOERTER:
                aus += _text_stellen(kw.value)
        if name in AUSWAHL:
            ff = [kw for kw in k.keywords if kw.arg == "format_func"]
            if ff:
                v = ff[0].value
                if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                        and v.func.attr == "uebersetzt"):
                    aus.append(_Stelle(v, "format"))
            else:
                aus.append(_Stelle(k, "format_neu"))
    return aus


def _versatz(zeilen_bytes):
    anfang, summe = [], 0
    for z in zeilen_bytes:
        anfang.append(summe)
        summe += len(z)
    return anfang


def einwickeln(pfad):
    """Schreibt die Datei mit tx(...) neu. Anzahl der Aenderungen."""
    quelle = open(pfad, encoding="utf-8").read()
    baum = ast.parse(quelle)
    roh = quelle.encode("utf-8")
    zeilen = roh.splitlines(keepends=True)
    anfang = _versatz(zeilen)

    def pos(zeile, spalte):
        return anfang[zeile - 1] + spalte

    aenderungen = []  # (start, ende, neu_bytes)
    for s in stellen(baum):
        k = s.k
        if s.art == "tx":
            a, e = pos(k.lineno, k.col_offset), pos(k.end_lineno, k.end_col_offset)
            aenderungen.append((a, e, b"tx(" + roh[a:e] + b")"))
        elif s.art == "auspacken":
            # "tx(" vor und ")" hinter dem Inneren entfernen; das Innere
            # selbst bekommt seine Stuecke eingewickelt (eigene Stellen).
            innen = k.args[0]
            a, e = pos(k.lineno, k.col_offset), pos(k.end_lineno, k.end_col_offset)
            ia = pos(innen.lineno, innen.col_offset)
            ie = pos(innen.end_lineno, innen.end_col_offset)
            aenderungen.append((ie, e, b""))
            aenderungen.append((a, ia, b""))
        elif s.art == "format":
            a, e = pos(k.lineno, k.col_offset), pos(k.end_lineno, k.end_col_offset)
            aenderungen.append((a, e, b"sprache.uebersetzt(" + roh[a:e] + b")"))
        else:  # format_func ergaenzen, vor der schliessenden Klammer
            letzte = list(k.args) + [kw.value for kw in k.keywords]
            if not letzte:
                continue
            z = max(letzte, key=lambda x: (x.end_lineno, x.end_col_offset))
            nach = pos(z.end_lineno, z.end_col_offset)
            klammer = pos(k.end_lineno, k.end_col_offset) - 1
            # Was zwischen letztem Argument und Klammer steht: Klammern
            # eines geklammerten Ausdrucks, Kommentare, ein Komma.
            dazwischen = re.sub(rb"#[^\n]*", b"", roh[nach:klammer])
            komma = dazwischen.strip().endswith(b",")
            aenderungen.append((klammer, klammer,
                                (b" " if komma else b", ")
                                + b"format_func=sprache.uebersetzt()"))

    # Von hinten nach vorn, und nichts, was sich ueberschneidet.
    aenderungen.sort(key=lambda x: (x[0], x[1]), reverse=True)
    bisher, angewandt = None, 0
    for a, e, neu in aenderungen:
        if bisher is not None and e > bisher:
            # liegt in einer schon geaenderten Stelle -- die aeussere gilt
            continue
        roh = roh[:a] + neu + roh[e:]
        bisher = a
        angewandt += 1
    text = roh.decode("utf-8")
    if "\nimport sprache\n" not in text:
        text = text.replace("\nimport streamlit as st\n",
                            "\nimport streamlit as st\nimport sprache\n"
                            "from sprache import t as tx\n", 1)
    ast.parse(text)
    open(pfad, "w", encoding="utf-8", newline="").write(text)
    return angewandt


# --- SAMMELN ---

def _oberflaeche():
    aus = {"texte": set(), "muster": set()}
    for name in OBERFLAECHE:
        baum = ast.parse(open(os.path.join(BASIS, name), encoding="utf-8").read())
        for k in ast.walk(baum):
            if _ist_tx(k) and k.args:
                s = _schluessel(k.args[0])
                if s and _sprachlich(s[1]):
                    aus[s[0]].add(s[1])
    return aus


def mit_rolle():
    """[{art, de, rollen}] -- jeder Text mit der Stelle, an der er steht.

    rolle ist die Streamlit-Methode (header, button, caption ...), bei
    Schluesselwoertern deren Name (help, placeholder); Meldungen aus
    Modulen heissen "modul". Gebraucht, um Texte nach ihrer Aufgabe zu
    ueberarbeiten: ein Knopf ist kurz, ein Hilfetext erklaert.
    """
    rollen = {}
    for name in OBERFLAECHE:
        baum = ast.parse(open(os.path.join(BASIS, name), encoding="utf-8").read())
        eltern = {}
        for k in ast.walk(baum):
            for kind in ast.iter_child_nodes(k):
                eltern[kind] = k
        for k in ast.walk(baum):
            if not (_ist_tx(k) and k.args):
                continue
            s = _schluessel(k.args[0])
            if not (s and _sprachlich(s[1])):
                continue
            rolle, x = "sonst", k
            while x in eltern:
                p = eltern[x]
                if isinstance(p, ast.keyword):
                    rolle = p.arg or rolle
                    x = p
                    continue
                if isinstance(p, ast.Call) and _st_aufruf(p):
                    if rolle == "sonst":
                        rolle = _st_aufruf(p)
                    break
                x = p
            rollen.setdefault(s, set()).add(rolle)
    for m in _module():
        teil = _meldungen(os.path.join(BASIS, m + ".py"))
        for art in ("texte", "muster"):
            for text in teil[art]:
                rollen.setdefault((art, text), set()).add("modul")
    return [{"art": a, "de": d, "rollen": sorted(r)}
            for (a, d), r in sorted(rollen.items(), key=lambda x: x[0][1])]


def _module():
    """Modulnamen, die die Oberflaeche importiert -- ihre Meldungen."""
    namen = set()
    for name in OBERFLAECHE:
        baum = ast.parse(open(os.path.join(BASIS, name), encoding="utf-8").read())
        for k in ast.walk(baum):
            if isinstance(k, ast.Import):
                namen.update(a.name for a in k.names)
            elif isinstance(k, ast.ImportFrom) and k.module:
                namen.add(k.module)
    return sorted(n for n in namen
                  if os.path.exists(os.path.join(BASIS, n + ".py"))
                  and n not in ("sprache", "uebersetzen")
                  and n not in ENGLISCH_ZUERST)


# Modules written in English from the start. Their messages are English
# already; the page shows them in German by catching their error kinds
# (see verschiebe_dokument in app.py), not through this table.
ENGLISCH_ZUERST = {"doc_actions", "answering", "web_sources", "mailboxes",
                   "accounts", "sessions", "jobs", "oidc", "metrics",
                   "statefiles", "database", "pg_collection", "pg_keywords"}


def _meldungen(datei):
    aus = {"texte": set(), "muster": set()}
    baum = ast.parse(open(datei, encoding="utf-8").read())
    for k in ast.walk(baum):
        kandidaten = []
        if isinstance(k, ast.Return) and isinstance(k.value, ast.Tuple):
            kandidaten = k.value.elts[1:]
        elif isinstance(k, ast.Raise) and isinstance(k.exc, ast.Call) and k.exc.args:
            kandidaten = [k.exc.args[0]]
        for c in kandidaten:
            # ("a" "b") und Klammern: ast liefert sie schon zusammengesetzt
            s = _schluessel(c)
            if s and _sprachlich(s[1]):
                aus[s[0]].add(s[1])
    return aus


def sammeln():
    alle = _oberflaeche()
    for m in _module():
        teil = _meldungen(os.path.join(BASIS, m + ".py"))
        alle["texte"] |= teil["texte"]
        alle["muster"] |= teil["muster"]
    return {k: sorted(v) for k, v in alle.items()}


def fehlend():
    import sprache
    try:
        tab = json.load(open(sprache.TABELLE, encoding="utf-8"))
    except (OSError, ValueError):
        tab = {}
    s = sammeln()
    return ([x for x in s["texte"] if x not in (tab.get("texte") or {})]
            + [x for x in s["muster"] if x not in (tab.get("muster") or {})])


def main():
    if "--einwickeln" in sys.argv:
        for d in sys.argv[sys.argv.index("--einwickeln") + 1:]:
            print(d, einwickeln(os.path.join(BASIS, d)), "Stellen")
        return 0
    if "--sammeln" in sys.argv:
        json.dump(sammeln(), sys.stdout, ensure_ascii=False, indent=1)
        return 0
    if "--fehlend" in sys.argv:
        f = fehlend()
        print("\n".join(f))
        print(f"\n{len(f)} ohne Uebersetzung", file=sys.stderr)
        return 1 if f else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
