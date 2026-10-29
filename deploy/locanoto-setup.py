#!/usr/bin/env python3
"""LocaNoto -- install, upgrade and check, by answering a few questions.

    python3 locanoto-setup.py              install (asks everything)
    python3 locanoto-setup.py --upgrade    new version, same answers
    python3 locanoto-setup.py --check      is everything working?
    python3 locanoto-setup.py --en         questions in English

Two targets, the same questions:

  * this machine (Docker): one compose stack with Caddy in front. Caddy
    gets the certificate from Let's Encrypt or issues it from an own
    internal CA -- and renews it. Runs on Linux, macOS (Apple Silicon)
    and NVIDIA DGX Spark; the images exist for amd64 and arm64.
  * Kubernetes: generated manifests applied with kubectl; certificates
    by cert-manager (offered for installation when missing), from Let's
    Encrypt or the internal CA, or a certificate you already have.

Needs only Python 3.8+ and `docker` (with compose) or `kubectl` on the
machine it runs on -- no packages, no Helm. All keys and passwords are
generated here; they are kept in <dir>/secrets.json (only readable by
you). KEEP A COPY OF THAT FILE OFFLINE: without LOCANOTO_SCHLUESSEL in it
the encrypted chats and documents cannot be read, also not from backups.

Inside the installation every service talks plain HTTP by its service
name; only the public address (and the file store's, if switched on) has
a certificate. Every container trusts the same list of authorities --
the public ones, the internal CA, and a company CA if you name one (for
a proxy that opens TLS) -- so outbound HTTPS and calls between services
just work.

Without questions (automation, CI):

    python3 locanoto-setup.py --answers answers.json --yes
    (admin password from LOCANOTO_ADMIN_PASSWORD, model key from
     LOCANOTO_MODEL_API_KEY, OIDC secret from LOCANOTO_OIDC_SECRET)
"""
import argparse
import getpass
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

VERSION = "1"
IMAGE = "ghcr.io/mw-research/locanoto:enterprise-schlank"
IMAGES = {
    "postgres": "pgvector/pgvector:pg16",
    "caddy": "caddy:2.8.4",
    "searxng": "searxng/searxng:2026.10.13-22c64b8d3",
    "opencloud": "opencloudeu/opencloud:7.2.4",
    "litellm": "ghcr.io/berriai/litellm:main-stable",
}
CERT_MANAGER = ("https://github.com/cert-manager/cert-manager/releases/"
                "download/v1.16.2/cert-manager.yaml")

EN = False


def T(de, en):
    return en if EN else de


# --- QUESTIONS ---------------------------------------------------------

def ask(question, default="", secret=False, check=None):
    while True:
        hint = f" [{default}]" if default and not secret else ""
        prompt = f"  {question}{hint}: "
        value = getpass.getpass(prompt) if secret else input(prompt)
        value = value.strip() or default
        problem = check(value) if check else None
        if not problem:
            return value
        print(f"    ! {problem}")


def yes(question, default=True):
    d = T("J/n", "Y/n") if default else T("j/N", "y/N")
    while True:
        a = input(f"  {question} ({d}): ").strip().lower()
        if not a:
            return default
        if a in ("j", "ja", "y", "yes"):
            return True
        if a in ("n", "nein", "no"):
            return False


def choose(question, options, default=1):
    print(f"  {question}")
    for i, (_key, label) in enumerate(options, 1):
        print(f"     [{i}] {label}")
    while True:
        a = input(f"  {T('Auswahl', 'Choice')} [{default}]: ").strip() or str(default)
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][0]


def section(title):
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _host_problem(h):
    if not h:
        return T("Bitte eine Adresse angeben.", "Please give an address.")
    if _is_ip(h) or re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", h.lower()):
        return None
    return T("Nur Hostname oder IP-Adresse, ohne https://.",
             "Host name or IP address only, without https://.")


def _file_problem(p):
    return None if os.path.isfile(p) else T("Datei nicht gefunden.", "File not found.")


def _password_problem(p):
    return None if len(p) >= 10 else T("Mindestens 10 Zeichen.", "At least 10 characters.")


def interview(old):
    """Ask everything; old answers are the defaults (upgrade, repeat)."""
    a = dict(old)
    section(T("Wohin", "Where"))
    a["target"] = choose(T("Wo soll LocaNoto laufen?", "Where should LocaNoto run?"), [
        ("docker", T("Auf diesem Rechner (Docker) -- Server, Mac, DGX Spark",
                     "On this machine (Docker) -- server, Mac, DGX Spark")),
        ("kubernetes", T("In einem Kubernetes-Cluster (kubectl)",
                         "In a Kubernetes cluster (kubectl)"))],
        1 if a.get("target", "docker") == "docker" else 2)
    if a["target"] == "kubernetes":
        a["namespace"] = ask(T("Namensraum", "Namespace"), a.get("namespace", "locanoto"))
        print("    " + T("Im Cluster bitte einen Hostnamen angeben (keine IP) -- "
                         "der Ingress ordnet Anfragen nach Namen zu.",
                         "In a cluster give a host name (not an IP) -- the ingress "
                         "routes requests by name."))
    else:
        a["dir"] = ask(T("Ordner für die Installation", "Folder for the installation"),
                       a.get("dir", os.path.abspath("locanoto")))

    section(T("Adresse und Zertifikat", "Address and certificate"))
    a["host"] = ask(T("Unter welcher Adresse soll LocaNoto erreichbar sein "
                      "(Hostname oder IP)", "Address LocaNoto should answer at "
                      "(host name or IP)"),
                    a.get("host", _guess_ip()), check=_host_problem).lower()
    public = (not _is_ip(a["host"])) and yes(
        T("Ist diese Adresse aus dem Internet erreichbar (Port 80 und 443)?",
          "Is this address reachable from the internet (ports 80 and 443)?"),
        a.get("tls") == "letsencrypt")
    if public:
        a["tls"] = "letsencrypt"
        a["acme_email"] = ask(T("E-Mail für Let's Encrypt (Ablaufwarnungen)",
                                "E-mail for Let's Encrypt (expiry notices)"),
                              a.get("acme_email", ""))
    elif yes(T("Haben Sie bereits ein Zertifikat für diese Adresse (.crt und .key)?",
               "Do you already have a certificate for this address (.crt and .key)?"),
             a.get("tls") == "own"):
        a["tls"] = "own"
        a["own_cert"] = ask(T("Pfad zur Zertifikatsdatei (.crt, mit Kette)",
                              "Path to the certificate file (.crt, with chain)"),
                            a.get("own_cert", ""), check=_file_problem)
        a["own_key"] = ask(T("Pfad zum Schlüssel (.key)", "Path to the key (.key)"),
                           a.get("own_key", ""), check=_file_problem)
    else:
        a["tls"] = "internal"
        print("    " + T("→ Eine eigene interne Zertifizierungsstelle wird angelegt. "
                         "Ihr Stammzertifikat (ca.crt) einmal in Browser oder "
                         "Geräteverwaltung eintragen.",
                         "→ An own internal certificate authority is created. Import "
                         "its root certificate (ca.crt) once into browsers or device "
                         "management."))

    section(T("Firmennetz", "Company network"))
    a["company_ca"] = []
    if yes(T("Bricht ein Firmenproxy TLS auf oder gibt es eine eigene Firmen-CA?",
             "Does a company proxy open TLS, or is there a company CA?"),
           bool(old.get("company_ca"))):
        while True:
            p = ask(T("Pfad zum CA-Zertifikat (.crt/.pem), leer = fertig",
                      "Path to the CA certificate (.crt/.pem), empty = done"), "")
            if not p:
                break
            if os.path.isfile(p):
                a["company_ca"].append(os.path.abspath(p))
            else:
                print("    ! " + T("Datei nicht gefunden.", "File not found."))
    a["proxy"] = ""
    if yes(T("Geht der Weg ins Internet über einen Proxy?",
             "Does traffic to the internet go through a proxy?"), bool(old.get("proxy"))):
        a["proxy"] = ask(T("Proxy-Adresse (z. B. http://proxy.firma.de:3128)",
                           "Proxy address (e.g. http://proxy.example.com:3128)"),
                         old.get("proxy", ""))
        a["no_proxy"] = ask(T("Ohne Proxy erreichbar (Komma-Liste, z. B. Modellserver)",
                              "Reachable without proxy (comma list, e.g. model server)"),
                            old.get("no_proxy", ""))

    section(T("Modelle", "Models"))
    a["model_url"] = ask(T("Adresse des Modellservers (OpenAI-kompatibel, mit /v1)",
                           "Address of the model server (OpenAI compatible, with /v1)"),
                         a.get("model_url", "http://modellserver:8000/v1"))
    a["chat_model"] = ask(T("Chat-Modell", "Chat model"), a.get("chat_model", "qwen3.8:27b"))
    a["embedding_model"] = ask(T("Embedding-Modell", "Embedding model"),
                               a.get("embedding_model", "qwen3-embedding:8b"))
    a["vision_model"] = ask(T("Bild-Modell (leer = keins)", "Vision model (empty = none)"),
                            a.get("vision_model", "qwen3-vl:32b"))
    a["dimensions"] = int(ask(T("Vektorlänge in der Datenbank (später nicht änderbar)",
                                "Vector length in the database (fixed later)"),
                              str(a.get("dimensions", 2048))))

    section(T("Funktionen", "Features"))
    f = dict(a.get("features") or {})
    f["websearch"] = yes(T("Websuche (nur Suchbegriffe gehen nach außen)?",
                           "Web search (only search terms leave the house)?"),
                         f.get("websearch", True))
    f["opencloud"] = yes(T("Dateiablage OpenCloud mitinstallieren?",
                           "Install the OpenCloud file store?"), f.get("opencloud", False))
    if f["opencloud"]:
        default_cloud = a.get("cloud_host") or ("" if _is_ip(a["host"]) else f"cloud.{a['host']}")
        a["cloud_host"] = ask(T("Adresse der Dateiablage (eigener Hostname)",
                                "Address of the file store (own host name)"),
                              default_cloud, check=_host_problem).lower()
    f["gateway"] = yes(T("Modell-Gateway (LiteLLM) für viele Nutzer/mehrere Modellserver?",
                         "Model gateway (LiteLLM) for many users/several model servers?"),
                       f.get("gateway", False))
    f["oidc"] = yes(T("Anmeldung über das Firmenverzeichnis (Entra ID, Keycloak, ...)?",
                      "Sign-in through the company directory (Entra ID, Keycloak, ...)?"),
                    f.get("oidc", False))
    if f["oidc"]:
        a["oidc_issuer"] = ask("OIDC issuer URL", a.get("oidc_issuer", ""))
        a["oidc_client_id"] = ask("OIDC client id", a.get("oidc_client_id", "locanoto"))
        a["oidc_admin_groups"] = ask(T("Gruppe(n) der Admins", "Admin group(s)"),
                                     a.get("oidc_admin_groups", ""))
    f["pages"] = yes(T("Klassische Oberfläche (Streamlit) zusätzlich unter /klassisch?",
                       "Classic interface (Streamlit) also under /klassisch?"),
                     f.get("pages", False))
    a["features"] = f

    if a["target"] == "kubernetes":
        section("Kubernetes")
        a["ingress_class"] = ask(T("Ingress-Klasse", "Ingress class"),
                                 a.get("ingress_class", _guess_ingress_class() or "nginx"))
        a["storage_class"] = ask(T("Speicherklasse (leer = Standard)",
                                   "Storage class (empty = default)"),
                                 a.get("storage_class", ""))
        a["replicas"] = int(ask(T("Anzahl Server-Pods (mehr als 1 braucht "
                                  "ReadWriteMany-Speicher)",
                                  "Number of server pods (more than 1 needs "
                                  "ReadWriteMany storage)"), str(a.get("replicas", 1))))
    return a


def _guess_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


def _guess_ingress_class():
    try:
        out = subprocess.run(["kubectl", "get", "ingressclass", "-o",
                              "jsonpath={.items[*].metadata.name}"],
                             capture_output=True, text=True, timeout=20).stdout
        return out.split()[0] if out.split() else ""
    except Exception:
        return ""


# --- YAML (a small emitter: dicts, lists, strings, numbers) -----------

def to_yaml(obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        lines = []
        for k, v in obj.items():
            key = k if re.fullmatch(r"[A-Za-z0-9_./-]+", str(k)) else json.dumps(k)
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:\n{to_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}{key}: {_scalar(v, indent + 1)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        lines = []
        for v in obj:
            if isinstance(v, dict) and v:
                inner = to_yaml(v, indent + 1).split("\n", 1)
                first = inner[0].strip()
                rest = ("\n" + inner[1]) if len(inner) > 1 else ""
                lines.append(f"{pad}- {first}{rest}")
            elif isinstance(v, list) and v:
                lines.append(f"{pad}-\n{to_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}- {_scalar(v, indent + 1)}")
        return "\n".join(lines)
    return pad + _scalar(obj, indent)


def _scalar(v, indent):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return "{}" if isinstance(v, dict) else "[]"
    s = str(v)
    # A literal block (|) only where it reads back exactly: ending in one
    # line break, no leading blank on the first line, no tabs or carriage
    # returns. Everything else as a quoted string -- less readable, never
    # wrong.
    if ("\n" in s and s.endswith("\n") and not s.endswith("\n\n")
            and not s[:1].isspace() and "\r" not in s and "\t" not in s):
        pad = "  " * indent
        body = "\n".join(pad + line if line else "" for line in s[:-1].split("\n"))
        return "|\n" + body
    return json.dumps(s, ensure_ascii=False)


def docs(objs):
    return "\n---\n".join(to_yaml(o) for o in objs) + "\n"


# --- SECRETS AND CERTIFICATES -------------------------------------------

def new_secrets(old):
    s = dict(old)
    s.setdefault("LOCANOTO_SCHLUESSEL", _fernet_key())
    s.setdefault("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    s.setdefault("SEARXNG_SECRET", secrets.token_hex(32))
    s.setdefault("OPENCLOUD_ADMIN_PASSWORD", secrets.token_urlsafe(18))
    s.setdefault("METRICS_TOKEN", secrets.token_hex(24))
    s.setdefault("LITELLM_MASTER_KEY", "sk-" + secrets.token_hex(24))
    return s


def _fernet_key():
    import base64
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class Runner:
    """Runs a Python snippet of the LocaNoto image: locally, in Docker or as a pod."""

    def __init__(self, a):
        self.a = a

    def make_ca(self, args, stdin=None):
        cmd = ["python", "make_ca.py"] + args
        here = os.path.dirname(os.path.abspath(__file__))
        local = os.path.join(here, "..", "make_ca.py")
        try:
            import cryptography  # noqa: F401
            if os.path.isfile(local):
                return self._run([sys.executable, local] + args, stdin)
        except ImportError:
            pass
        if self.a["target"] == "docker":
            return self._run(["docker", "run", "--rm", "-i", self.a["image"]] + cmd, stdin)
        name = "locanoto-ca-" + secrets.token_hex(3)
        return self._run(["kubectl", "-n", self.a["namespace"], "run", name, "-i",
                          "--rm", "--restart=Never", "--quiet",
                          "--pod-running-timeout=10m",
                          f"--image={self.a['image']}", "--"] + cmd, stdin)

    @staticmethod
    def _run(cmd, stdin):
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"{' '.join(cmd[:4])} ...: {r.stderr[-800:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])


def ensure_ca(a, sec, runner):
    if a["tls"] != "internal" or sec.get("CA_CRT"):
        return
    print("  " + T("Lege interne Zertifizierungsstelle an ...",
                   "Creating the internal certificate authority ..."))
    ca = runner.make_ca(["ca"])
    sec["CA_CRT"], sec["CA_KEY"] = ca["crt"], ca["key"]


def server_cert(a, sec, runner, hosts):
    """A certificate from the internal CA (Kubernetes without cert-manager)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"crt": sec["CA_CRT"], "key": sec["CA_KEY"]}, f)
        tmp = f.name
    try:
        if a["target"] == "kubernetes" and not _local_crypto():
            data = json.dumps({"crt": sec["CA_CRT"], "key": sec["CA_KEY"]})
            name = "locanoto-ca-" + secrets.token_hex(3)
            r = subprocess.run(
                ["kubectl", "-n", a["namespace"], "run", name, "-i", "--rm",
                 "--restart=Never", "--quiet", "--pod-running-timeout=10m",
                 f"--image={a['image']}", "--",
                 "sh", "-c", "cat > /tmp/ca.json && python make_ca.py cert /tmp/ca.json "
                 + " ".join(hosts)], input=data, capture_output=True, text=True)
            return json.loads(r.stdout.strip().splitlines()[-1])
        return runner.make_ca(["cert", tmp] + hosts)
    finally:
        os.unlink(tmp)


def _local_crypto():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


# --- SETTINGS SHARED BY BOTH TARGETS ------------------------------------

def app_env(a, sec, database_url, opencloud_url):
    """Environment of the server, worker and pages containers."""
    f = a["features"]
    gateway = f["gateway"]
    env = {
        "DATABASE_URL": database_url,
        "DATABASE_DIMENSIONS": str(a["dimensions"]),
        "LOCANOTO_SCHLUESSEL": sec["LOCANOTO_SCHLUESSEL"],
        "LOCANOTO_DATEN": "/app/data",
        "LOCANOTO_KONFIG": "/app/config",
        "LOCANOTO_INDEX": "/tmp/locanoto-index",
        "LOCANOTO_PUBLIC_URL": ("" if a.get("public_check") is False else
                                ("http://" if a["tls"] == "none" else "https://")
                                + a["host"]),
        "OPENAI_BASE_URL": "http://litellm:4000/v1" if gateway else a["model_url"],
        "OPENAI_API_KEY": sec["LITELLM_MASTER_KEY"] if gateway else
                          (sec.get("MODEL_API_KEY") or "none"),
        "CHAT_MODEL": a["chat_model"],
        "CHAT_MODELLE": a["chat_model"],
        "EMBEDDING_MODEL": a["embedding_model"],
        "VISION_MODEL": a.get("vision_model", ""),
        "LLM_SEND_USER": "pseudonym" if gateway else "off",
        "METRICS_TOKEN": sec["METRICS_TOKEN"],
        "COOKIE_SECURE": "1" if a["tls"] != "none" else "0",
        "ANONYMIZED_TELEMETRY": "False",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(trust_env())
    env.update(proxy_env(a))
    if f["opencloud"]:
        env.update({"OWNCLOUD_URL": opencloud_url, "OWNCLOUD_USER": "admin",
                    "OWNCLOUD_ADMIN_USER": "admin",
                    "OWNCLOUD_PASSWORT": sec.get("OPENCLOUD_APP_TOKEN", ""),
                    "OWNCLOUD_ADMIN_PASSWORT": sec.get("OPENCLOUD_APP_TOKEN", "")})
    if f["oidc"]:
        env.update({"OIDC_ISSUER": a["oidc_issuer"],
                    "OIDC_CLIENT_ID": a["oidc_client_id"],
                    "OIDC_CLIENT_SECRET": sec.get("OIDC_SECRET", ""),
                    "OIDC_REDIRECT_URI": f"https://{a['host']}/api/v1/auth/oidc/callback",
                    "OIDC_ADMIN_GROUPS": a.get("oidc_admin_groups", "")})
    return env


def trust_env():
    b = "/trust/bundle.pem"
    return {"SSL_CERT_FILE": b, "REQUESTS_CA_BUNDLE": b, "CURL_CA_BUNDLE": b}


INTERNAL = ["localhost", "127.0.0.1", "postgres", "server", "worker", "pages",
            "websuche", "searxng", "opencloud", "litellm", "caddy",
            ".svc", ".cluster.local"]


def proxy_env(a):
    if not a.get("proxy"):
        return {}
    no = ",".join(INTERNAL + [x.strip() for x in a.get("no_proxy", "").split(",")
                              if x.strip()])
    return {"HTTP_PROXY": a["proxy"], "HTTPS_PROXY": a["proxy"], "NO_PROXY": no,
            "http_proxy": a["proxy"], "https_proxy": a["proxy"], "no_proxy": no}


def extra_cas(a, sec):
    """{file name: PEM} of the authorities every container trusts on top."""
    out = {}
    if sec.get("CA_CRT"):
        out["locanoto-internal-ca.crt"] = sec["CA_CRT"]
    for i, p in enumerate(a.get("company_ca") or []):
        out[f"company-{i + 1}.crt"] = open(p, encoding="utf-8").read()
    return out


SEARXNG_SETTINGS = """use_default_settings: true
general:
  instance_name: "LocaNoto"
  enable_metrics: false
search:
  formats: [html, json]
  safe_search: 1
server:
  limiter: false
  image_proxy: false
  public_instance: false
"""


def litellm_config(a):
    models = []
    for name in {a["chat_model"], a["embedding_model"], a.get("vision_model") or ""} - {""}:
        models.append({"model_name": name, "litellm_params": {
            "model": f"openai/{name}", "api_base": a["model_url"],
            "api_key": "os.environ/MODEL_API_KEY"}})
    return to_yaml({
        "model_list": models,
        "router_settings": {"routing_strategy": "least-busy", "num_retries": 2,
                            "timeout": 300, "allowed_fails": 3, "cooldown_time": 30},
        "litellm_settings": {"turn_off_message_logging": True,
                             "redact_user_api_key_info": True,
                             "telemetry": False, "drop_params": True},
        "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
    }) + "\n"


# --- DOCKER --------------------------------------------------------------

def compose_escape(env):
    return {k: str(v).replace("$", "$$") for k, v in env.items()}


def docker_files(a, sec):
    """{relative path: text} of the docker installation."""
    f = a["features"]
    image = a["image"]
    db_url = (f"postgresql://locanoto:{sec['POSTGRES_PASSWORD']}@postgres:5432/locanoto")
    env = app_env(a, sec, db_url, "http://opencloud:9200")
    trust_mount = ["trust:/trust:ro"]
    base = {"image": image, "restart": "unless-stopped",
            "volumes": ["documents:/app/data", "config:/app/config"] + trust_mount,
            "depends_on": {"postgres": {"condition": "service_healthy"},
                           "trust": {"condition": "service_completed_successfully"}}}
    services = {
        "trust": {"image": image, "restart": "no",
                  "command": ["python", "trustbundle.py", "/trust/bundle.pem", "/trust-extra"],
                  "volumes": ["trust:/trust", "./trust-extra:/trust-extra:ro"]},
        "postgres": {"image": IMAGES["postgres"], "restart": "unless-stopped",
                     "environment": compose_escape({
                         "POSTGRES_DB": "locanoto", "POSTGRES_USER": "locanoto",
                         "POSTGRES_PASSWORD": sec["POSTGRES_PASSWORD"],
                         "PGDATA": "/var/lib/postgresql/data/pgdata"}),
                     "volumes": ["pgdata:/var/lib/postgresql/data"],
                     "healthcheck": {"test": ["CMD", "pg_isready", "-U", "locanoto",
                                              "-d", "locanoto"],
                                     "interval": "5s", "retries": 30}},
        "server": dict(base, command=["uvicorn", "server:app", "--host", "0.0.0.0",
                                      "--port", "8700", "--proxy-headers",
                                      "--forwarded-allow-ips", "*"],
                       environment=compose_escape(env),
                       healthcheck={"test": ["CMD", "python", "-c",
                                             "import urllib.request;urllib.request."
                                             "urlopen('http://127.0.0.1:8700/api/v1/ready')"],
                                    "interval": "10s", "retries": 30}),
        "worker": dict(base, command=["python", "-u", "worker.py"],
                       environment=compose_escape(env)),
    }
    caddy = ["{"]
    if a["tls"] == "letsencrypt" and a.get("acme_email"):
        caddy.append(f"\temail {a['acme_email']}")
    if a["tls"] == "internal":
        caddy += ["\tpki {", "\t\tca local {", "\t\t\troot {",
                  "\t\t\t\tcert /certs/ca.crt", "\t\t\t\tkey /certs/ca.key",
                  "\t\t\t}", "\t\t}", "\t}"]
    caddy += ["}", ""]

    def site(host, upstream, extra=""):
        tls = {"internal": "\ttls internal\n", "own": "\ttls /certs/own.crt /certs/own.key\n"
               }.get(a["tls"], "")
        scheme = "http://" if a["tls"] == "none" else ""
        return (f"{scheme}{host} {{\n{tls}{extra}"
                f"\treverse_proxy {upstream} {{\n\t\tflush_interval -1\n\t}}\n}}\n")

    extra = ""
    if f["pages"]:
        extra = "\thandle_path /klassisch* {\n\t\treverse_proxy pages:8501\n\t}\n"
    caddy.append(site(a["host"], "server:8700", extra))
    if f["websearch"]:
        services["searxng"] = {"image": IMAGES["searxng"], "restart": "unless-stopped",
                               "environment": compose_escape(dict({
                                   "SEARXNG_BASE_URL": "http://searxng:8080/",
                                   "SEARXNG_SECRET": sec["SEARXNG_SECRET"]},
                                   **proxy_env(a), **trust_env())),
                               "volumes": ["./searxng/settings.yml:/etc/searxng/settings.yml:ro"]
                                          + trust_mount,
                               "depends_on": {"trust": {"condition":
                                                        "service_completed_successfully"}}}
        services["websuche"] = {"image": image, "restart": "unless-stopped",
                                "command": ["python", "websuche.py"],
                                "environment": compose_escape(dict({
                                    "WEBSUCHE_SEARXNG": "http://searxng:8080"},
                                    **proxy_env(a), **trust_env())),
                                "volumes": trust_mount,
                                "depends_on": {"trust": {"condition":
                                                         "service_completed_successfully"}}}
    if f["opencloud"]:
        services["opencloud"] = {
            "image": IMAGES["opencloud"], "restart": "unless-stopped",
            "entrypoint": ["/bin/sh", "-c"],
            "command": ["opencloud init --insecure false -q --admin-password "
                        "\"$$IDM_ADMIN_PASSWORD\" || true; exec opencloud server"],
            "environment": compose_escape(dict({
                "OC_URL": f"https://{a['cloud_host']}", "PROXY_TLS": "false",
                "IDM_ADMIN_PASSWORD": sec["OPENCLOUD_ADMIN_PASSWORD"]}, **trust_env())),
            "volumes": ["opencloud-config:/etc/opencloud", "opencloud-data:/var/lib/opencloud"]
                       + trust_mount,
            "depends_on": {"trust": {"condition": "service_completed_successfully"}}}
        caddy.append(site(a["cloud_host"], "opencloud:9200"))
    if f["gateway"]:
        services["litellm"] = {
            "image": IMAGES["litellm"], "restart": "unless-stopped",
            "command": ["--config", "/etc/litellm/config.yaml", "--port", "4000"],
            "environment": compose_escape(dict({
                "LITELLM_MASTER_KEY": sec["LITELLM_MASTER_KEY"],
                "MODEL_API_KEY": sec.get("MODEL_API_KEY") or "none"},
                **proxy_env(a), **trust_env())),
            "volumes": ["./litellm/config.yaml:/etc/litellm/config.yaml:ro"] + trust_mount,
            "depends_on": {"trust": {"condition": "service_completed_successfully"}}}
    if f["pages"]:
        services["pages"] = dict(base, command=[
            "streamlit", "run", "app.py", "--server.port=8501",
            "--server.address=0.0.0.0", "--server.baseUrlPath=klassisch"],
            environment=compose_escape(env))
    caddy_vol = ["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy-data:/data",
                 "caddy-config:/config"]
    if a["tls"] in ("internal", "own"):
        caddy_vol.append("./certs:/certs:ro")
    services["caddy"] = {"image": IMAGES["caddy"], "restart": "unless-stopped",
                         "ports": ["80:80", "443:443"], "volumes": caddy_vol,
                         "environment": compose_escape(proxy_env(a)),
                         "depends_on": ["server"]}
    volumes = {n: {} for n in ("pgdata", "documents", "config", "trust",
                               "caddy-data", "caddy-config")}
    if f["opencloud"]:
        volumes.update({"opencloud-config": {}, "opencloud-data": {}})
    compose = {"name": "locanoto", "services": services, "volumes": volumes}
    files = {"compose.yaml": "# Generated by locanoto-setup.py -- edit the answers, "
                             "not this file.\n" + to_yaml(compose) + "\n",
             "Caddyfile": "\n".join(caddy)}
    for name, pem in extra_cas(a, sec).items():
        files[f"trust-extra/{name}"] = pem
    files["trust-extra/.keep"] = ""
    if f["websearch"]:
        files["searxng/settings.yml"] = SEARXNG_SETTINGS
    if f["gateway"]:
        files["litellm/config.yaml"] = litellm_config(a)
    if a["tls"] == "internal":
        files["certs/ca.crt"] = sec["CA_CRT"]
        files["certs/ca.key"] = sec["CA_KEY"]
    if a["tls"] == "own":
        files["certs/own.crt"] = open(a["own_cert"], encoding="utf-8").read()
        files["certs/own.key"] = open(a["own_key"], encoding="utf-8").read()
    return files


def write_files(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        if rel.endswith((".key", "compose.yaml")):
            _private(p)


def _private(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def docker_compose(root, *args, stdin=None, check=True):
    cmd = ["docker", "compose", "-f", os.path.join(root, "compose.yaml"),
           "--project-directory", root] + list(args)
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"docker compose {' '.join(args)}:\n{r.stderr[-1500:]}")
    return r


def wait(what, probe, seconds=600):
    print(f"  {what} ", end="", flush=True)
    end = time.time() + seconds
    while time.time() < end:
        if probe():
            print(T(" bereit", " ready"))
            return True
        print(".", end="", flush=True)
        time.sleep(5)
    print(T(" ZEIT ABGELAUFEN", " TIMED OUT"))
    return False


def install_docker(a, sec, first):
    root = a["dir"]
    write_files(root, docker_files(a, sec))
    print("  " + T("Hole Images und starte ...", "Pulling images and starting ..."))
    docker_compose(root, "pull", "--quiet", check=False)
    docker_compose(root, "up", "-d", "--remove-orphans")

    def server_ready():
        r = docker_compose(root, "exec", "-T", "server", "python", "-c",
                           "import urllib.request;urllib.request.urlopen("
                           "'http://127.0.0.1:8700/api/v1/ready')", check=False)
        return r.returncode == 0
    if not wait(T("Warte auf den Server", "Waiting for the server"), server_ready):
        raise SystemExit(docker_compose(root, "logs", "--tail", "40", "server",
                                        check=False).stdout)
    if a["features"]["opencloud"] and not sec.get("OPENCLOUD_APP_TOKEN"):
        def oc_ready():
            r = docker_compose(root, "exec", "-T", "opencloud", "sh", "-c",
                               "wget -qO- http://127.0.0.1:9200/status.php", check=False)
            return r.returncode == 0
        wait(T("Warte auf die Dateiablage", "Waiting for the file store"), oc_ready)
        r = docker_compose(root, "exec", "-T", "opencloud", "opencloud", "auth-app",
                           "create", "--user-name=admin", "--expiration=87600h",
                           check=False)
        m = re.search(r"token:\s*(\S+)", r.stdout + r.stderr)
        if m:
            sec["OPENCLOUD_APP_TOKEN"] = m.group(1)
            write_files(root, docker_files(a, sec))
            docker_compose(root, "up", "-d", "server", "worker")
            wait(T("Warte auf den Server", "Waiting for the server"), server_ready)
        else:
            print("  ! " + T("App-Token für OpenCloud nicht erzeugt -- später "
                             "--upgrade wiederholen.",
                             "OpenCloud app token not created -- repeat --upgrade later."))
    app_setup(lambda *cmd, stdin=None: docker_compose(
        root, "exec", "-T", "server", *cmd, stdin=stdin, check=False), a, first)
    return lambda *cmd: docker_compose(root, "exec", "-T", "server", *cmd, check=False)


def app_setup(execute, a, first):
    """First admin, web search registration -- inside the server container."""
    if first and a.get("admin_name"):
        r = execute("sh", "-c", "read -r P; LOCANOTO_ERSTER_VERWALTER=\"$0\" "
                    "LOCANOTO_ERSTES_PASSWORT=\"$P\" python einrichten.py"
                    + ("" if a["features"]["opencloud"] else " --ohne-owncloud"),
                    a["admin_name"], stdin=a.pop("_admin_password", "") + "\n")
        print("\n".join("    " + line for line in r.stdout.strip().splitlines()[-12:]))
    if a["features"]["websearch"]:
        execute("python", "-c", "import mcp; mcp.lies_konfiguration().get('websuche') "
                "or print(mcp.lege_an('websuche', 'websuche', 'http://websuche:8000/mcp'))")


# --- KUBERNETES ------------------------------------------------------------

def meta(name, a, component, **extra):
    m = {"name": name, "namespace": a["namespace"],
         "labels": {"app.kubernetes.io/name": "locanoto",
                    "app.kubernetes.io/component": component}}
    m.update(extra)
    return m


def k_env(env):
    return [{"name": k, "value": str(v)} for k, v in env.items()]


def k_secret_env(names, secret):
    return [{"name": n, "valueFrom": {"secretKeyRef": {"name": secret, "key": n}}}
            for n in names]


TRUST_INIT = None


def trust_init(a):
    return {"name": "trust", "image": a["image"], "imagePullPolicy": "Always",
            "command": ["python", "trustbundle.py", "/trust/bundle.pem", "/trust-extra"],
            "volumeMounts": [{"name": "trust", "mountPath": "/trust"},
                             {"name": "trust-extra", "mountPath": "/trust-extra"}]}


TRUST_VOLUMES = [{"name": "trust", "emptyDir": {}},
                 {"name": "trust-extra", "configMap": {"name": "locanoto-trust"}}]
TRUST_MOUNT = {"name": "trust", "mountPath": "/trust", "readOnly": True}


def deployment(a, name, component, container, replicas=1, init=True, volumes=(),
               security=None, strategy=None):
    spec = {"initContainers": [trust_init(a)] if init else [],
            "containers": [container],
            "volumes": list(TRUST_VOLUMES) + list(volumes),
            "enableServiceLinks": False}
    if security:
        spec["securityContext"] = security
    d = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta(name, a, component),
         "spec": {"replicas": replicas,
                  "selector": {"matchLabels": {"app.kubernetes.io/name": "locanoto",
                                               "app.kubernetes.io/component": component}},
                  "template": {"metadata": {"labels": {
                      "app.kubernetes.io/name": "locanoto",
                      "app.kubernetes.io/component": component}}, "spec": spec}}}
    if strategy:
        d["spec"]["strategy"] = strategy
    return d


def service(a, name, component, port):
    return {"apiVersion": "v1", "kind": "Service", "metadata": meta(name, a, component),
            "spec": {"selector": {"app.kubernetes.io/name": "locanoto",
                                  "app.kubernetes.io/component": component},
                     "ports": [{"name": "http", "port": port, "targetPort": port}]}}


def pvc(a, name, size, mode="ReadWriteOnce"):
    spec = {"accessModes": [mode], "resources": {"requests": {"storage": size}}}
    if a.get("storage_class"):
        spec["storageClassName"] = a["storage_class"]
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "metadata": meta(name, a, "storage"), "spec": spec}


def k8s_objects(a, sec, cert_manager):
    f = a["features"]
    ns = a["namespace"]
    db_url = f"postgresql://locanoto:{sec['POSTGRES_PASSWORD']}@postgres:5432/locanoto"
    env = app_env(a, sec, db_url, "http://opencloud:9200")
    secret_keys = [k for k in env if k in (
        "DATABASE_URL", "LOCANOTO_SCHLUESSEL", "OPENAI_API_KEY", "METRICS_TOKEN",
        "OWNCLOUD_PASSWORT", "OWNCLOUD_ADMIN_PASSWORT", "OIDC_CLIENT_SECRET")]
    plain = {k: v for k, v in env.items() if k not in secret_keys}
    objs = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
            {"apiVersion": "v1", "kind": "Secret", "metadata": meta("locanoto", a, "config"),
             "type": "Opaque", "stringData": {k: env[k] for k in secret_keys}},
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("locanoto", a, "config"),
             "data": plain},
            {"apiVersion": "v1", "kind": "ConfigMap",
             "metadata": meta("locanoto-trust", a, "config"),
             "data": dict(extra_cas(a, sec), **{"keep.txt": "-"})}]
    app_env_refs = ([{"name": k, "valueFrom": {"configMapKeyRef": {"name": "locanoto",
                                                                    "key": k}}}
                     for k in plain]
                    + k_secret_env(secret_keys, "locanoto"))
    sec_ctx = {"runAsNonRoot": True, "runAsUser": 1000, "fsGroup": 1000}
    app_mounts = [TRUST_MOUNT, {"name": "documents", "mountPath": "/app/data"},
                  {"name": "tmp", "mountPath": "/tmp"},
                  {"name": "config", "mountPath": "/app/config"}]
    app_vols = [{"name": "documents", "persistentVolumeClaim": {"claimName": "locanoto-documents"}},
                {"name": "tmp", "emptyDir": {}}, {"name": "config", "emptyDir": {}}]
    rwx = a.get("replicas", 1) > 1
    objs.append(pvc(a, "locanoto-documents", "50Gi", "ReadWriteMany" if rwx else "ReadWriteOnce"))

    # postgres
    objs += [
        {"apiVersion": "v1", "kind": "Secret", "metadata": meta("postgres", a, "postgres"),
         "type": "Opaque", "stringData": {"POSTGRES_PASSWORD": sec["POSTGRES_PASSWORD"]}},
        service(a, "postgres", "postgres", 5432),
        {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": meta("postgres", a, "postgres"),
         "spec": {"serviceName": "postgres", "replicas": 1,
                  "selector": {"matchLabels": {"app.kubernetes.io/name": "locanoto",
                                               "app.kubernetes.io/component": "postgres"}},
                  "template": {"metadata": {"labels": {"app.kubernetes.io/name": "locanoto",
                                                       "app.kubernetes.io/component": "postgres"}},
                               "spec": {"securityContext": {"fsGroup": 999},
                                        "containers": [{
                                            "name": "postgres", "image": IMAGES["postgres"],
                                            "env": k_env({"POSTGRES_DB": "locanoto",
                                                          "POSTGRES_USER": "locanoto",
                                                          "PGDATA": "/var/lib/postgresql/data/pgdata"})
                                                   + k_secret_env(["POSTGRES_PASSWORD"], "postgres"),
                                            "ports": [{"containerPort": 5432}],
                                            "readinessProbe": {"exec": {"command": [
                                                "pg_isready", "-U", "locanoto", "-d", "locanoto"]},
                                                "periodSeconds": 5},
                                            "volumeMounts": [{"name": "data",
                                                              "mountPath": "/var/lib/postgresql/data"}]}]}},
                  "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                            "spec": dict({"accessModes": ["ReadWriteOnce"],
                                                          "resources": {"requests": {"storage": "20Gi"}}},
                                                         **({"storageClassName": a["storage_class"]}
                                                            if a.get("storage_class") else {}))}]}}]

    def app_container(name, command, port=None):
        # Always: the tag stays the same across versions; without it a
        # node keeps the image it already has and an upgrade changes nothing.
        c = {"name": name, "image": a["image"], "imagePullPolicy": "Always",
             "command": command, "env": app_env_refs,
             "volumeMounts": app_mounts,
             "securityContext": {"allowPrivilegeEscalation": False,
                                 "capabilities": {"drop": ["ALL"]}}}
        if port:
            c["ports"] = [{"containerPort": port}]
        return c

    server = app_container("server", ["uvicorn", "server:app", "--host", "0.0.0.0",
                                      "--port", "8700", "--proxy-headers",
                                      "--forwarded-allow-ips", "*"], 8700)
    server["readinessProbe"] = {"httpGet": {"path": "/api/v1/ready", "port": 8700},
                                "periodSeconds": 10}
    server["startupProbe"] = {"httpGet": {"path": "/api/v1/health", "port": 8700},
                              "periodSeconds": 5, "failureThreshold": 120}
    objs += [service(a, "server", "server", 8700),
             deployment(a, "server", "server", server, a.get("replicas", 1),
                        volumes=app_vols, security=sec_ctx),
             deployment(a, "worker", "worker", app_container("worker", ["python", "-u", "worker.py"]),
                        volumes=app_vols, security=sec_ctx)]
    if f["pages"]:
        objs += [service(a, "pages", "pages", 8501),
                 deployment(a, "pages", "pages", app_container(
                     "pages", ["streamlit", "run", "app.py", "--server.port=8501",
                               "--server.address=0.0.0.0", "--server.baseUrlPath=klassisch"],
                     8501), volumes=app_vols, security=sec_ctx)]
    if f["websearch"]:
        objs += [
            {"apiVersion": "v1", "kind": "Secret", "metadata": meta("searxng", a, "searxng"),
             "type": "Opaque", "stringData": {"SEARXNG_SECRET": sec["SEARXNG_SECRET"]}},
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("searxng", a, "searxng"),
             "data": {"settings.yml": SEARXNG_SETTINGS}},
            service(a, "searxng", "searxng", 8080),
            deployment(a, "searxng", "searxng", {
                "name": "searxng", "image": IMAGES["searxng"],
                "env": k_env(dict({"SEARXNG_BASE_URL": "http://searxng:8080/"},
                                  **proxy_env(a), **trust_env()))
                       + k_secret_env(["SEARXNG_SECRET"], "searxng"),
                "ports": [{"containerPort": 8080}],
                "volumeMounts": [TRUST_MOUNT, {"name": "settings", "mountPath":
                                               "/etc/searxng/settings.yml",
                                               "subPath": "settings.yml"}]},
                volumes=[{"name": "settings", "configMap": {"name": "searxng"}}]),
            service(a, "websuche", "websuche", 8000),
            deployment(a, "websuche", "websuche", {
                "name": "websuche", "image": a["image"], "imagePullPolicy": "Always",
                "command": ["python", "websuche.py"],
                "env": k_env(dict({"WEBSUCHE_SEARXNG": "http://searxng:8080"},
                                  **proxy_env(a), **trust_env())),
                "ports": [{"containerPort": 8000}], "volumeMounts": [TRUST_MOUNT]},
                security={"runAsNonRoot": True, "runAsUser": 10001})]
    if f["opencloud"]:
        objs += [
            {"apiVersion": "v1", "kind": "Secret", "metadata": meta("opencloud", a, "opencloud"),
             "type": "Opaque",
             "stringData": {"IDM_ADMIN_PASSWORD": sec["OPENCLOUD_ADMIN_PASSWORD"]}},
            pvc(a, "opencloud", "50Gi"), service(a, "opencloud", "opencloud", 9200),
            deployment(a, "opencloud", "opencloud", {
                "name": "opencloud", "image": IMAGES["opencloud"],
                "command": ["/bin/sh", "-c"],
                "args": ["opencloud init --insecure false -q --admin-password "
                         "\"$IDM_ADMIN_PASSWORD\" || true; exec opencloud server"],
                "env": k_env(dict({"OC_URL": f"https://{a['cloud_host']}",
                                   "PROXY_TLS": "false"}, **trust_env()))
                       + k_secret_env(["IDM_ADMIN_PASSWORD"], "opencloud"),
                "ports": [{"containerPort": 9200}],
                "startupProbe": {"httpGet": {"path": "/status.php", "port": 9200},
                                 "periodSeconds": 5, "failureThreshold": 60},
                "volumeMounts": [TRUST_MOUNT,
                                 {"name": "data", "mountPath": "/etc/opencloud", "subPath": "config"},
                                 {"name": "data", "mountPath": "/var/lib/opencloud",
                                  "subPath": "daten"}]},
                volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": "opencloud"}}],
                security={"runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000},
                strategy={"type": "Recreate"})]
    if f["gateway"]:
        objs += [
            {"apiVersion": "v1", "kind": "Secret", "metadata": meta("litellm", a, "gateway"),
             "type": "Opaque", "stringData": {"LITELLM_MASTER_KEY": sec["LITELLM_MASTER_KEY"],
                                              "MODEL_API_KEY": sec.get("MODEL_API_KEY") or "none"}},
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("litellm", a, "gateway"),
             "data": {"config.yaml": litellm_config(a)}},
            service(a, "litellm", "gateway", 4000),
            deployment(a, "litellm", "gateway", {
                "name": "litellm", "image": IMAGES["litellm"],
                "args": ["--config", "/etc/litellm/config.yaml", "--port", "4000"],
                "env": k_env(dict(proxy_env(a), **trust_env()))
                       + k_secret_env(["LITELLM_MASTER_KEY", "MODEL_API_KEY"], "litellm"),
                "ports": [{"containerPort": 4000}],
                "volumeMounts": [TRUST_MOUNT, {"name": "config", "mountPath": "/etc/litellm"}]},
                volumes=[{"name": "config", "configMap": {"name": "litellm"}}])]

    # certificates and ingress
    hosts = [a["host"]] + ([a["cloud_host"]] if f["opencloud"] else [])
    annotations = {"nginx.ingress.kubernetes.io/proxy-buffering": "off",
                   "nginx.ingress.kubernetes.io/proxy-read-timeout": "600",
                   "nginx.ingress.kubernetes.io/proxy-body-size": "200m"}
    if a["tls"] == "letsencrypt":
        objs.append({"apiVersion": "cert-manager.io/v1", "kind": "Issuer",
                     "metadata": meta("locanoto", a, "tls"),
                     "spec": {"acme": {"server": "https://acme-v02.api.letsencrypt.org/directory",
                                       "email": a.get("acme_email", ""),
                                       "privateKeySecretRef": {"name": "locanoto-acme"},
                                       "solvers": [{"http01": {"ingress": {
                                           "ingressClassName": a["ingress_class"]}}}]}}})
        annotations["cert-manager.io/issuer"] = "locanoto"
    elif a["tls"] == "internal" and cert_manager:
        objs += [{"apiVersion": "v1", "kind": "Secret", "type": "kubernetes.io/tls",
                  "metadata": meta("locanoto-ca", a, "tls"),
                  "stringData": {"tls.crt": sec["CA_CRT"], "tls.key": sec["CA_KEY"]}},
                 {"apiVersion": "cert-manager.io/v1", "kind": "Issuer",
                  "metadata": meta("locanoto", a, "tls"),
                  "spec": {"ca": {"secretName": "locanoto-ca"}}}]
        annotations["cert-manager.io/issuer"] = "locanoto"
    elif a["tls"] in ("internal", "own"):
        crt, key = sec.get("TLS_CRT", ""), sec.get("TLS_KEY", "")
        objs.append({"apiVersion": "v1", "kind": "Secret", "type": "kubernetes.io/tls",
                     "metadata": meta("locanoto-tls", a, "tls"),
                     "stringData": {"tls.crt": crt, "tls.key": key}})
    rules = [{"host": a["host"], "http": {"paths": [
        {"path": "/", "pathType": "Prefix",
         "backend": {"service": {"name": "server", "port": {"number": 8700}}}}]}}]
    if f["pages"]:
        rules[0]["http"]["paths"].insert(0, {
            "path": "/klassisch", "pathType": "Prefix",
            "backend": {"service": {"name": "pages", "port": {"number": 8501}}}})
    if f["opencloud"]:
        rules.append({"host": a["cloud_host"], "http": {"paths": [
            {"path": "/", "pathType": "Prefix",
             "backend": {"service": {"name": "opencloud", "port": {"number": 9200}}}}]}})
    ingress = {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
               "metadata": meta("locanoto", a, "ingress", annotations=annotations),
               "spec": {"ingressClassName": a["ingress_class"], "rules": rules}}
    if a["tls"] != "none" and not _is_ip(a["host"]):
        ingress["spec"]["tls"] = [{"hosts": [h for h in hosts if not _is_ip(h)],
                                   "secretName": "locanoto-tls"}]
    objs.append(ingress)
    objs.append({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                 "metadata": meta("postgres", a, "postgres"),
                 "spec": {"podSelector": {"matchLabels": {"app.kubernetes.io/component": "postgres"}},
                          "policyTypes": ["Ingress"],
                          "ingress": [{"from": [{"podSelector": {"matchExpressions": [{
                              "key": "app.kubernetes.io/component", "operator": "In",
                              "values": ["server", "worker", "pages"]}]}}],
                              "ports": [{"port": 5432}]}]}})
    return objs


def kubectl(*args, stdin=None, check=True):
    r = subprocess.run(["kubectl"] + list(args), input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"kubectl {' '.join(args[:4])}:\n{r.stderr[-1500:]}")
    return r


def has_cert_manager():
    return kubectl("get", "crd", "issuers.cert-manager.io", check=False).returncode == 0


def install_kubernetes(a, sec, first, runner):
    ns = a["namespace"]
    kubectl("version", "--request-timeout=10s")
    cm = has_cert_manager()
    if not cm and a["tls"] in ("letsencrypt", "internal"):
        # Let's Encrypt cannot do without it; with the internal CA it only
        # adds automatic renewal (without it the installer issues the
        # certificate and --upgrade renews it).
        want = a.get("install_cert_manager")
        if want is None:
            want = True if a.get("_assume_yes") else yes(
                T("cert-manager fehlt. Jetzt installieren (erneuert Zertifikate "
                  "automatisch)?", "cert-manager is missing. Install it now "
                  "(renews certificates automatically)?"), True)
        if want:
            print("  cert-manager ...")
            kubectl("apply", "-f", CERT_MANAGER)
            kubectl("-n", "cert-manager", "rollout", "status", "deploy/cert-manager-webhook",
                    "--timeout=300s")
            cm = True
    if a["tls"] == "letsencrypt" and not cm:
        raise SystemExit(T("Let's Encrypt in Kubernetes braucht cert-manager.",
                           "Let's Encrypt in Kubernetes needs cert-manager."))
    kubectl("create", "namespace", ns, check=False)
    if a["tls"] == "internal" and not cm:
        hosts = [a["host"]] + ([a["cloud_host"]] if a["features"]["opencloud"] else [])
        c = server_cert(a, sec, runner, hosts)
        sec["TLS_CRT"], sec["TLS_KEY"] = c["crt"] + sec["CA_CRT"], c["key"]
    if a["tls"] == "own":
        sec["TLS_CRT"] = open(a["own_cert"], encoding="utf-8").read()
        sec["TLS_KEY"] = open(a["own_key"], encoding="utf-8").read()
    objs = k8s_objects(a, sec, cm)
    manifest = docs(objs)
    out = os.path.join(a["state_dir"], "kubernetes.yaml")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(manifest)
    _private(out)
    print("  " + T("Wende Manifeste an ...", "Applying manifests ..."))
    for attempt in range(12):
        r = kubectl("apply", "-f", "-", stdin=manifest, check=False)
        if r.returncode == 0:
            break
        if "webhook" not in r.stderr or attempt == 11:
            raise SystemExit(f"kubectl apply:\n{r.stderr[-1500:]}")
        time.sleep(10)        # cert-manager's webhook is not serving yet
    for d in ["server", "worker"] + [n for n, on in (
            ("websuche", a["features"]["websearch"]), ("searxng", a["features"]["websearch"]),
            ("opencloud", a["features"]["opencloud"]), ("litellm", a["features"]["gateway"]),
            ("pages", a["features"]["pages"])) if on]:
        kubectl("-n", ns, "rollout", "restart", f"deploy/{d}", check=False)
    kubectl("-n", ns, "rollout", "status", "statefulset/postgres", "--timeout=600s", check=False)
    kubectl("-n", ns, "rollout", "status", "deploy/server", "--timeout=900s")

    def ex(*cmd, stdin=None):
        return kubectl("-n", ns, "exec", "-i", "deploy/server", "-c", "server", "--", *cmd,
                       stdin=stdin, check=False)
    if a["features"]["opencloud"] and not sec.get("OPENCLOUD_APP_TOKEN"):
        kubectl("-n", ns, "rollout", "status", "deploy/opencloud", "--timeout=900s", check=False)
        r = kubectl("-n", ns, "exec", "deploy/opencloud", "--", "opencloud", "auth-app",
                    "create", "--user-name=admin", "--expiration=87600h", check=False)
        m = re.search(r"token:\s*(\S+)", r.stdout + r.stderr)
        if m:
            sec["OPENCLOUD_APP_TOKEN"] = m.group(1)
            kubectl("apply", "-f", "-", stdin=docs(k8s_objects(a, sec, cm)))
            kubectl("-n", ns, "rollout", "restart", "deploy/server", "deploy/worker")
            kubectl("-n", ns, "rollout", "status", "deploy/server", "--timeout=900s")
    app_setup(ex, a, first)
    return ex


# --- MAIN -------------------------------------------------------------------

def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(path, data, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    if private:
        _private(path)


def summary(a):
    f = a["features"]
    on = lambda b: T("ja", "yes") if b else T("nein", "no")  # noqa: E731
    tls = {"letsencrypt": "Let's Encrypt", "internal": T("interne CA", "internal CA"),
           "own": T("eigenes Zertifikat", "own certificate"), "none": "HTTP"}[a["tls"]]
    print(f"""
  {T('Ziel', 'Target')}:        {a['target']}{' / ' + a['namespace'] if a['target'] == 'kubernetes' else ' / ' + a.get('dir', '')}
  {T('Adresse', 'Address')}:     https://{a['host']}  ({tls})
  {T('Modelle', 'Models')}:     {a['model_url']}  ({a['chat_model']}, {a['embedding_model']})
  {T('Websuche', 'Web search')}:  {on(f['websearch'])}    OpenCloud: {on(f['opencloud'])}{' (' + a.get('cloud_host', '') + ')' if f['opencloud'] else ''}
  Gateway:     {on(f['gateway'])}    SSO: {on(f['oidc'])}    {T('Klassisch', 'Classic')}: {on(f['pages'])}
  {T('Proxy', 'Proxy')}:       {a.get('proxy') or '-'}    {T('Firmen-CA', 'Company CA')}: {len(a.get('company_ca') or [])}""")


def main():
    global EN
    ap = argparse.ArgumentParser(description="LocaNoto setup")
    ap.add_argument("--upgrade", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--en", action="store_true")
    ap.add_argument("--answers", help="answers file (JSON) instead of questions")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--state", default=os.path.expanduser("~/.locanoto"),
                    help="where answers and secrets are kept")
    ap.add_argument("--image", default="")
    ap.add_argument("--render-only", action="store_true",
                    help="write the files, start nothing (for review and tests)")
    args = ap.parse_args()
    EN = args.en or os.getenv("LANG", "").startswith("en")
    answers_file = os.path.join(args.state, "locanoto.json")
    secrets_file = os.path.join(args.state, "secrets.json")
    old = load(answers_file)
    sec = load(secrets_file)

    print(T("\nLocaNoto -- Einrichtung", "\nLocaNoto -- setup"))
    if args.check:
        if not old:
            raise SystemExit(T("Noch nicht installiert.", "Not installed yet."))
        return doctor(old)

    first = not old
    if args.answers:
        a = load(args.answers)
        a.setdefault("features", {})
        for k, d in (("websearch", True), ("opencloud", False), ("gateway", False),
                     ("oidc", False), ("pages", False)):
            a["features"].setdefault(k, d)
        a.setdefault("dimensions", 2048)
        a.setdefault("company_ca", [])
    elif args.upgrade and old:
        a = old
    else:
        a = interview(old)
    a["image"] = args.image or a.get("image") or IMAGE
    a["state_dir"] = args.state
    a["version"] = VERSION

    sec = new_secrets(sec)
    if os.getenv("LOCANOTO_MODEL_API_KEY"):
        sec["MODEL_API_KEY"] = os.environ["LOCANOTO_MODEL_API_KEY"]
    elif not args.answers and not args.upgrade:
        if yes(T("Braucht der Modellserver einen API-Schlüssel?",
                 "Does the model server need an API key?"), bool(sec.get("MODEL_API_KEY"))):
            sec["MODEL_API_KEY"] = ask(T("API-Schlüssel", "API key"), secret=True)
    if a["features"].get("oidc"):
        if os.getenv("LOCANOTO_OIDC_SECRET"):
            sec["OIDC_SECRET"] = os.environ["LOCANOTO_OIDC_SECRET"]
        elif not sec.get("OIDC_SECRET") and not args.answers:
            sec["OIDC_SECRET"] = ask("OIDC client secret", secret=True)
    if first and not args.render_only:
        section(T("Erstes Admin-Konto", "First admin account"))
        a["admin_name"] = (a.get("admin_name") or (ask(T("Name", "Name"), "admin")
                                                    if not args.answers else "admin"))
        pw = os.getenv("LOCANOTO_ADMIN_PASSWORD") or (
            "" if args.answers else ask(T("Passwort (mind. 10 Zeichen)",
                                          "Password (at least 10 characters)"),
                                        secret=True, check=_password_problem))
        a["_admin_password"] = pw

    summary(a)
    if not args.yes and not args.render_only and not yes(
            T("\n  Jetzt installieren?", "\n  Install now?"), True):
        return 1
    a["_assume_yes"] = bool(args.yes)

    runner = Runner(a)
    if a["target"] == "kubernetes" and not args.render_only:
        # The CA may be made by a pod of the image; it needs the namespace.
        kubectl("create", "namespace", a["namespace"], check=False)
    ensure_ca(a, sec, runner)
    save(secrets_file, sec, private=True)
    persist = {k: v for k, v in a.items() if not k.startswith("_")}
    save(answers_file, persist)

    if args.render_only:
        if a["target"] == "docker":
            write_files(a["dir"], docker_files(a, sec))
            print(f"  {T('Dateien in', 'Files in')} {a['dir']}")
        else:
            if a["tls"] in ("internal", "own") and not sec.get("TLS_CRT"):
                sec["TLS_CRT"], sec["TLS_KEY"] = "(issued at install)", "(issued at install)"
            path = os.path.join(args.state, "kubernetes.yaml")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(docs(k8s_objects(a, sec, a.get("tls") != "own")))
            print(f"  {T('Manifeste in', 'Manifests in')} {path}")
        return 0

    section(T("Installation", "Installation"))
    if a["target"] == "docker":
        if not shutil.which("docker"):
            raise SystemExit(T("docker fehlt auf diesem Rechner.", "docker is missing."))
        install_docker(a, sec, first)
    else:
        if not shutil.which("kubectl"):
            raise SystemExit(T("kubectl fehlt auf diesem Rechner.", "kubectl is missing."))
        install_kubernetes(a, sec, first, runner)
    save(secrets_file, sec, private=True)
    save(answers_file, {k: v for k, v in a.items() if not k.startswith("_")})
    rc = doctor(a)
    finish(a, sec, args.state)
    return rc


def doctor(a):
    section(T("Prüfung", "Check"))
    lang = ["--en"] if EN else []
    if a["target"] == "docker":
        r = docker_compose(a["dir"], "exec", "-T", "server", "python", "doctor.py", *lang,
                           check=False)
    else:
        r = kubectl("-n", a["namespace"], "exec", "deploy/server", "-c", "server", "--",
                    "python", "doctor.py", *lang, check=False)
    print(r.stdout.rstrip() or r.stderr[-800:])
    return r.returncode


def finish(a, sec, state):
    section(T("Fertig", "Done"))
    print(f"  https://{a['host']}")
    if a["tls"] == "internal":
        ca = os.path.join(state, "ca.crt")
        with open(ca, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(sec["CA_CRT"])
        print("  " + T(f"Stammzertifikat zum Verteilen: {ca}",
                       f"Root certificate to distribute: {ca}"))
    print("  " + T(f"Schlüssel und Passwörter: {os.path.join(state, 'secrets.json')} "
                   "-- eine Kopie offline aufbewahren!",
                   f"Keys and passwords: {os.path.join(state, 'secrets.json')} "
                   "-- keep a copy offline!"))
    if not _is_ip(a["host"]):
        print("  " + T(f"DNS: {a['host']} muss auf diesen Rechner/Ingress zeigen.",
                       f"DNS: {a['host']} must point to this machine/ingress."))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
