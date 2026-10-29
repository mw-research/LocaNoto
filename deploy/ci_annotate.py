"""Turn the end of log files into GitHub error annotations.

    python3 deploy/ci_annotate.py TITLE FILE [FILE ...]

Workflow logs of a public repository need a sign-in to read; annotations
do not. When an installation test fails, the last lines of the
installer output and of the container logs end up where anyone can see
them -- secrets are not in these logs (the installer never prints them).
"""
import os
import re
import sys

LINES = 40


def main():
    title, files = sys.argv[1], sys.argv[2:]
    for path in files:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            tail = f.read().splitlines()[-LINES:]
        text = "\n".join(tail)[-6000:]
        # Colour codes and other control characters make GitHub drop the
        # whole annotation.
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        text = "".join(c for c in text if c == "\n" or c >= " ")
        text = text.replace("%", "%25").replace("\n", "%0A")
        print(f"::error title={title} {os.path.basename(path)}::{text}")


if __name__ == "__main__":
    main()
