"""Does the search find the same on Postgres as on Chroma and SQLite?

    python compare_search.py run QUESTIONS.txt --user NAME --out old.json
    DATABASE_URL=... python compare_search.py run QUESTIONS.txt --user NAME --out new.json
    python compare_search.py diff old.json new.json

QUESTIONS.txt holds one question per line, as users would ask them. The
first run uses the old store (no DATABASE_URL), the second the migrated
one; both on the same installation, with the same models.

Recorded per question, each as a list of passages (file, page, start of
the text):

  * hybrid   -- what pipeline.suche returns: the passages that reach the
                model. Without reranker, so runs are comparable.
  * keyword  -- the keyword search alone (FTS5 against the blind index).

diff prints per question how many of the top passages both runs share
(overlap@k) and whether the first hit is the same, then the mean. As a
rule of thumb: hybrid overlap above 0.8 and the same first hit in most
questions means users will not notice the switch. Lower values are not
wrong by themselves -- read the questions where they differ.

--fake-embedder replaces the embedding model with a word-hash vector, for
testing this script without a model server.
"""
import argparse
import hashlib
import json
import math
import sys
import types


class HashEmbedder:
    """Deterministic stand-in for an embedding model: words hashed into a vector."""

    def __init__(self, dimensions=64):
        self.dimensions = dimensions
        self.embeddings = types.SimpleNamespace(create=self._create)

    def vector(self, text):
        # Words and their letter trigrams: related words share some
        # trigrams, so few passages tie at exactly the same distance.
        v = [0.0] * self.dimensions
        import pg_keywords
        for word in pg_keywords.terms(text):
            grams = [word] + [word[i:i + 3] for i in range(len(word) - 2)]
            for g in grams:
                h = int.from_bytes(hashlib.sha256(g.encode()).digest()[:4], "big")
                v[h % self.dimensions] += 1.0 if g == word else 0.3
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def _create(self, input, model=None, **_kw):  # noqa: A002
        texts = [input] if isinstance(input, str) else list(input)
        return types.SimpleNamespace(data=[
            types.SimpleNamespace(index=i, embedding=self.vector(t))
            for i, t in enumerate(texts)])


def _passage(hit):
    meta = hit.get("meta") or {}
    text = " ".join(str(hit.get("text") or "").split())[:80]
    return f"{meta.get('file_name', '?')} p{meta.get('page', '?')}: {text}"


def run(questions, user, top_k, fake):
    import keyword_index
    import llm
    import pipeline
    import store
    if fake:
        client, model = HashEmbedder(), "fake"
    else:
        client, model = llm.client("EMBEDDING"), llm.modell("EMBEDDING")
    pairs = pipeline.sammlungen(user)
    rooms = [r for r, _ in pairs]
    out = {"store": store.beschreibung(), "user": user, "top_k": top_k,
           "questions": {}}
    for q in questions:
        hits, numbers = pipeline.suche(pairs, client, model, [q], user, top_k)
        keyword = keyword_index.search(q, user, limit=top_k, raeume=rooms)
        out["questions"][q] = {
            "hybrid": [_passage(h) for h in hits],
            "keyword": [_passage(h) for h in keyword],
            "vector_outage": numbers.get("vektorausfall") or {},
        }
    return out


def _overlap(a, b, k):
    a, b = a[:k], b[:k]
    if not a and not b:
        return 1.0
    return len(set(a) & set(b)) / max(len(a), len(b))


def diff(old, new, out=sys.stdout):
    k = min(old["top_k"], new["top_k"])
    print(f"old: {old['store']}\nnew: {new['store']}\n", file=out)
    rows = []
    for q, o in old["questions"].items():
        n = new["questions"].get(q)
        if n is None:
            continue
        h = _overlap(o["hybrid"], n["hybrid"], k)
        w = _overlap(o["keyword"], n["keyword"], k)
        first = (o["hybrid"][:1] == n["hybrid"][:1])
        rows.append((h, w, first))
        mark = "" if h >= 0.8 and first else "   <--"
        print(f"hybrid {h:4.2f}  keyword {w:4.2f}  first {'same' if first else 'DIFF'}"
              f"  {q[:60]}{mark}", file=out)
        if n.get("vector_outage"):
            print(f"      vector search failed: {n['vector_outage']}", file=out)
    if not rows:
        print("no common questions", file=out)
        return None
    mean_h = sum(r[0] for r in rows) / len(rows)
    mean_w = sum(r[1] for r in rows) / len(rows)
    same_first = sum(1 for r in rows if r[2]) / len(rows)
    print(f"\nmean overlap@{k}: hybrid {mean_h:.2f}, keyword {mean_w:.2f}; "
          f"same first hit in {same_first:.0%} of {len(rows)} questions",
          file=out)
    return {"hybrid": mean_h, "keyword": mean_w, "same_first": same_first}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("questions")
    r.add_argument("--user", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--top-k", type=int, default=8)
    r.add_argument("--fake-embedder", action="store_true")
    d = sub.add_parser("diff")
    d.add_argument("old")
    d.add_argument("new")
    a = ap.parse_args()
    if a.command == "run":
        with open(a.questions, encoding="utf-8") as f:
            questions = [line.strip() for line in f if line.strip()]
        result = run(questions, a.user, a.top_k, a.fake_embedder)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f"{len(questions)} questions -> {a.out} ({result['store']})")
        return 0
    with open(a.old, encoding="utf-8") as f:
        old = json.load(f)
    with open(a.new, encoding="utf-8") as f:
        new = json.load(f)
    diff(old, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
