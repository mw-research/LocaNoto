"""Which texts of the web UI have no translation yet.

    python uebersetzen.py --german     page texts without a German entry
    python uebersetzen.py --english    module messages without English
    python uebersetzen.py --collect    the module messages as JSON

The pages are written in English: t('...') in web_templates/ and
t("...") in web*.py and routes_*.py. Their German texts are web.TEXTS;
a text without an entry is shown in English.

The modules behind the pages answer in German -- (ok, "...") in a
return and the text of a raise. The pages show them through tm(), and
sprache_en.json holds their English. An f-string becomes a pattern: each
inserted value a {}.

Exit code 1 when something is missing.
"""
import ast
import glob
import json
import os
import re
import sys

BASIS = os.path.dirname(os.path.abspath(__file__))

# The files that make up the web UI.
PAGES = ("web.py", "web_admin.py", "web_tickets.py", "server.py",
         "routes_account.py", "routes_admin.py", "routes_chat.py",
         "routes_documents.py")

# Modules written in English from the start. Their messages are English
# already; the pages translate them through web.TEXTS, not this table.
ENGLISH_FIRST = {"doc_actions", "answering", "web_sources", "mailboxes",
                 "workspace_notes", "attachments", "created_files",
                 "web_research", "vector_columns", "reembed",
                 "accounts", "sessions", "jobs", "oidc", "metrics",
                 "statefiles", "database", "pg_collection", "pg_keywords",
                 "external_model", "mcp_oauth", "tickets", "notices",
                 "mail_watch", "local_time"}

_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")
_TEMPLATE_T = re.compile(r"""\bt\(\s*(['"])(.*?)(?<!\\)\1\s*\)""", re.S)


def _key(k):
    """(kind, text) of a text node, kind 'texte' or 'muster', else None."""
    if isinstance(k, ast.Constant) and isinstance(k.value, str):
        return "texte", k.value
    if isinstance(k, ast.JoinedStr):
        parts = []
        for w in k.values:
            if isinstance(w, ast.Constant):
                parts.append(str(w.value).replace("{}", "{ }"))
            else:
                parts.append("{}")
        return "muster", "".join(parts)
    return None


def _wordy(text):
    """Does the text hold words outside placeholders and tags?"""
    rest = re.sub(r"<[^>]*>|\{\}|`[^`]*`|https?://\S+", " ", text)
    return bool(_WORD.search(rest))


def _parse(name):
    return ast.parse(open(os.path.join(BASIS, name), encoding="utf-8").read())


# --- PAGE TEXTS (English, German in web.TEXTS) ---

def page_texts():
    """Every constant text the pages pass to t()."""
    found = set()
    for path in glob.glob(os.path.join(BASIS, "web_templates", "*.html")):
        for _q, text in _TEMPLATE_T.findall(open(path, encoding="utf-8").read()):
            found.add(text.replace("\\'", "'").replace('\\"', '"'))
    for name in PAGES:
        for k in ast.walk(_parse(name)):
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id == "t" and k.args
                    and isinstance(k.args[0], ast.Constant)
                    and isinstance(k.args[0].value, str)):
                found.add(k.args[0].value)
    return sorted(t for t in found if _wordy(t))


def german_texts():
    """web.TEXTS, read from the source: importing web starts the server."""
    for k in _parse("web.py").body:
        if (isinstance(k, ast.Assign) and len(k.targets) == 1
                and getattr(k.targets[0], "id", "") == "TEXTS"):
            return ast.literal_eval(k.value)
    return {}


def missing_german():
    known = german_texts()
    return [t for t in page_texts() if t not in known]


# --- MODULE MESSAGES (German, English in sprache_en.json) ---

def _modules():
    """The modules the pages import -- their messages reach the page."""
    names = set()
    for name in PAGES:
        for k in ast.walk(_parse(name)):
            if isinstance(k, ast.Import):
                names.update(a.name for a in k.names)
            elif isinstance(k, ast.ImportFrom) and k.module and not k.level:
                names.add(k.module)
    return sorted(n for n in names
                  if os.path.exists(os.path.join(BASIS, n + ".py"))
                  and n + ".py" not in PAGES
                  and n not in ("sprache", "uebersetzen")
                  and n not in ENGLISH_FIRST)


def _messages(path):
    out = {"texte": set(), "muster": set()}
    for k in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
        candidates = []
        if isinstance(k, ast.Return) and isinstance(k.value, ast.Tuple):
            candidates = k.value.elts[1:]
        elif isinstance(k, ast.Raise) and isinstance(k.exc, ast.Call) and k.exc.args:
            candidates = [k.exc.args[0]]
        for c in candidates:
            s = _key(c)
            if s and _wordy(s[1]):
                out[s[0]].add(s[1])
    return out


def collect():
    every = {"texte": set(), "muster": set()}
    for m in _modules():
        part = _messages(os.path.join(BASIS, m + ".py"))
        every["texte"] |= part["texte"]
        every["muster"] |= part["muster"]
    return {k: sorted(v) for k, v in every.items()}


def missing_english():
    import sprache
    try:
        table = json.load(open(sprache.TABELLE, encoding="utf-8"))
    except (OSError, ValueError):
        table = {}
    s = collect()
    return ([x for x in s["texte"] if x not in (table.get("texte") or {})]
            + [x for x in s["muster"] if x not in (table.get("muster") or {})])


def main():
    if "--collect" in sys.argv:
        json.dump(collect(), sys.stdout, ensure_ascii=False, indent=1)
        return 0
    for flag, find in (("--german", missing_german), ("--english", missing_english)):
        if flag in sys.argv:
            gaps = find()
            print("\n".join(gaps))
            print(f"\n{len(gaps)} without translation", file=sys.stderr)
            return 1 if gaps else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
