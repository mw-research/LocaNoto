"""One list of trusted certificate authorities for every container.

    python trustbundle.py OUT [EXTRA_DIR]

Writes OUT: the public CAs (certifi, as Python ships them) plus every
*.crt / *.pem in EXTRA_DIR -- the installation's own CA and a company CA
(e.g. of a proxy that opens TLS). The installer runs this once per start
(an init container in Kubernetes, a one-shot service in Docker) and
points every container at OUT through SSL_CERT_FILE (and
REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE). Python, Go (OpenCloud) and curl all
read it, so all services trust the same list:

  * outbound HTTPS through a company proxy works (web search, models),
  * one service can reach another through its public address with an
    internal certificate.

Without EXTRA_DIR or without files in it, OUT is the public list only.
"""
import os
import sys


def build(out, extra_dir=""):
    import certifi
    parts = [open(certifi.where(), encoding="utf-8").read()]
    added = []
    if extra_dir and os.path.isdir(extra_dir):
        for name in sorted(os.listdir(extra_dir)):
            if name.endswith((".crt", ".pem")):
                text = open(os.path.join(extra_dir, name),
                            encoding="utf-8").read().strip()
                if "BEGIN CERTIFICATE" in text:
                    parts.append(f"# {name}\n{text}\n")
                    added.append(name)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return added


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    added = build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print(f"trust bundle {sys.argv[1]}: public CAs"
          + (f" + {', '.join(added)}" if added else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
