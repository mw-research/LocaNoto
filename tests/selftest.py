"""Do the basic functions work? -- python tests/selftest.py

Runs the real search path: real collections, real keyword index, real
encryption, real permission checks. Only the embedding and the rerank
model are stand-ins, so it needs no model server and is done in seconds.

It works in a folder of its own and leaves the installation untouched.
Meant for after an update: when it passes, sign-in, workspace
separation, search, citations, chat encryption, feedback and backup
with restore work.

    docker compose run --rm locanoto_bot python tests/selftest.py

The checks are in selftest_parts/, one file per topic. They run in
order in ONE namespace: later parts use the users, workspaces and
documents the earlier ones set up, so a part does not run on its own.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

ns = {"__name__": "selftest", "__builtins__": __builtins__, "_ROOT": ROOT}
for part in sorted(glob.glob(os.path.join(HERE, "selftest_parts", "[0-9][0-9]_*.py"))):
    with open(part, encoding="utf-8") as f:
        exec(compile(f.read(), part, "exec"), ns)

print()
# The names BEFORE the number: whoever reads only the last line sees
# which checks failed, not just how many.
if ns["gescheitert"]:
    print(f"--- {len(ns['gescheitert'])} FEHLGESCHLAGEN ---")
    for name in ns["gescheitert"]:
        print(f"    {name}")
print(f"=== {sum(ns['ok'])}/{len(ns['ok'])} Pruefungen bestanden ===")
ns["statefiles"].rmtree(ns["tmp"], ignore_errors=True)
sys.exit(0 if all(ns["ok"]) else 1)
