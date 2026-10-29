"""Tests of the installer that need neither Docker nor a cluster.

    python deploy/test_setup.py

Renders the Docker and the Kubernetes installation for typical answers
and checks the result with a real YAML parser; checks that no secret ends
up in the answers file, that a "$" in a secret survives compose, that
make_ca.py issues a certificate that chains to its CA, that the trust
bundle carries the extra authorities, and that doctor.py reports in
plain words. The full install is tested in CI (.github/workflows/
installation.yml) on Docker and on a kind cluster.
"""
import datetime
import importlib.util
import json
import os
import random
import string
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location("setup", os.path.join(HERE, "locanoto-setup.py"))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        failures.append(name)


TMP = tempfile.mkdtemp(prefix="setup_test_")


def run_setup(answers, state, env=None):
    path = os.path.join(TMP, f"answers-{random.randint(0, 10**6)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(answers, f)
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, os.path.join(HERE, "locanoto-setup.py"),
                           "--answers", path, "--yes", "--render-only",
                           "--state", state], capture_output=True, text=True, env=e)


# --- the small YAML emitter ---
print("=== YAML ===")
random.seed(7)


def rnd(depth=0):
    kinds = ["str", "int", "bool", "multiline"] + (["dict", "list"] if depth < 3 else [])
    k = random.choice(kinds)
    if k == "str":
        return "".join(random.choice(string.printable[:94] + " äöü€") for _ in range(random.randint(0, 12)))
    if k == "multiline":
        return "line one\n  indented: yes\nkey: value # not a comment\n"
    if k == "int":
        return random.randint(-5, 10**6)
    if k == "bool":
        return random.choice([True, False])
    if k == "dict":
        return {f"k{i}_{random.choice('abc')}": rnd(depth + 1) for i in range(random.randint(1, 4))}
    return [rnd(depth + 1) for _ in range(random.randint(1, 4))]


bad = []
for edge in ("  leading blank\nsecond\n", "no final break\nx", "two\n\n", "tab\tin\n",
             "a: b\n- c\n# d\n"):
    if yaml.safe_load(setup.to_yaml({"v": edge}) + "\n") != {"v": edge}:
        bad.append(edge)
for _ in range(300):
    obj = {"root": rnd()}
    # Files end with a line break; a literal block reads it as its own.
    if yaml.safe_load(setup.to_yaml(obj) + "\n") != obj:
        bad.append(obj)
check("to_yaml round-trips 300 random structures", not bad, bad[:1])

# --- certificates ---
print("=== certificates ===")
from cryptography import x509  # noqa: E402
import make_ca  # noqa: E402

ca = make_ca.new_ca()
srv = make_ca.server_cert(ca, ["locanoto.example.test", "10.1.2.3"])
ca_cert = x509.load_pem_x509_certificate(ca["crt"].encode())
leaf = x509.load_pem_x509_certificate(srv["crt"].encode())
try:
    leaf.verify_directly_issued_by(ca_cert)
    chained = True
except Exception as e:
    chained = e
check("server certificate chains to the CA", chained is True, chained)
san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
check("name and IP in the certificate",
      "locanoto.example.test" in san.get_values_for_type(x509.DNSName)
      and any(str(ip) == "10.1.2.3" for ip in san.get_values_for_type(x509.IPAddress)))
days = (leaf.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)).days
check("validity browsers accept (<= 398 days)", 390 <= days <= 398, days)

import trustbundle  # noqa: E402
extra = os.path.join(TMP, "extra")
os.makedirs(extra)
with open(os.path.join(extra, "company.crt"), "w", encoding="utf-8") as f:
    f.write(ca["crt"])
out = os.path.join(TMP, "bundle.pem")
added = trustbundle.build(out, extra)
text = open(out, encoding="utf-8").read()
check("trust bundle has the public CAs and the extra one",
      added == ["company.crt"] and ca["crt"].strip() in text and text.count("BEGIN CERTIFICATE") > 50)

# --- Docker, internal CA, everything on ---
print("=== Docker ===")
company = os.path.join(TMP, "company-ca.pem")
with open(company, "w", encoding="utf-8") as f:
    f.write(make_ca.new_ca("Company CA")["crt"])
state = os.path.join(TMP, "state-docker")
target = os.path.join(TMP, "install-docker")
answers = {"target": "docker", "dir": target, "host": "192.168.10.20", "tls": "internal",
           "company_ca": [company], "proxy": "http://proxy.example.test:3128",
           "no_proxy": "modelle.intern", "model_url": "http://modelle.intern:8000/v1",
           "chat_model": "qwen3.8:27b", "embedding_model": "qwen3-embedding:8b",
           "vision_model": "", "dimensions": 2048,
           "features": {"websearch": True, "opencloud": True, "gateway": True,
                        "oidc": False, "pages": True},
           "cloud_host": "cloud.example.test"}
r = run_setup(answers, state, {"LOCANOTO_MODEL_API_KEY": "sk-with-$dollar"})
check("docker render runs", r.returncode == 0, r.stderr[-800:])
compose = yaml.safe_load(open(os.path.join(target, "compose.yaml"), encoding="utf-8"))
svc = compose["services"]
check("all services there",
      {"trust", "postgres", "server", "worker", "searxng", "websuche", "opencloud",
       "litellm", "pages", "caddy"} <= set(svc), sorted(svc))
check("every container trusts the same bundle",
      all(svc[n]["environment"].get("SSL_CERT_FILE") == "/trust/bundle.pem"
          for n in ("server", "worker", "searxng", "websuche", "opencloud", "litellm")))
check("proxy only for the way out, internal names excluded",
      svc["websuche"]["environment"]["HTTPS_PROXY"] == "http://proxy.example.test:3128"
      and "searxng" in svc["websuche"]["environment"]["NO_PROXY"]
      and "modelle.intern" in svc["server"]["environment"]["NO_PROXY"])
check("a $ in a secret is escaped for compose",
      svc["litellm"]["environment"]["MODEL_API_KEY"] == "sk-with-$$dollar")
check("server goes through the gateway",
      svc["server"]["environment"]["OPENAI_BASE_URL"] == "http://litellm:4000/v1")
check("services talk plain HTTP inside",
      svc["server"]["environment"]["OWNCLOUD_URL"] == "http://opencloud:9200"
      and svc["websuche"]["environment"]["WEBSUCHE_SEARXNG"] == "http://searxng:8080")
caddy = open(os.path.join(target, "Caddyfile"), encoding="utf-8").read()
check("Caddy issues from the own CA, for both addresses",
      "tls internal" in caddy and "cert /certs/ca.crt" in caddy
      and "192.168.10.20 {" in caddy and "cloud.example.test {" in caddy
      and "handle_path /klassisch*" in caddy)
check("Caddy answers clients that send no SNI (an IP address)",
      "default_sni 192.168.10.20" in caddy)
extra_files = sorted(os.listdir(os.path.join(target, "trust-extra")))
check("internal and company CA in the trust list",
      "locanoto-internal-ca.crt" in extra_files and "company-1.crt" in extra_files, extra_files)
saved = open(os.path.join(state, "locanoto.json"), encoding="utf-8").read()
sec = json.load(open(os.path.join(state, "secrets.json"), encoding="utf-8"))
check("no secret in the answers file",
      not any(v in saved for k, v in sec.items() if isinstance(v, str) and len(v) > 8))
check("secrets file holds key, CA and the given model key",
      sec["LOCANOTO_SCHLUESSEL"] and "BEGIN CERTIFICATE" in sec["CA_CRT"]
      and sec["MODEL_API_KEY"] == "sk-with-$dollar")
r2 = run_setup(answers, state)
sec2 = json.load(open(os.path.join(state, "secrets.json"), encoding="utf-8"))
check("a second run keeps key and CA",
      sec2["LOCANOTO_SCHLUESSEL"] == sec["LOCANOTO_SCHLUESSEL"]
      and sec2["CA_CRT"] == sec["CA_CRT"], r2.stderr[-300:])

# --- Kubernetes, Let's Encrypt, SSO ---
print("=== Kubernetes ===")
state = os.path.join(TMP, "state-k8s")
answers = {"target": "kubernetes", "namespace": "lnt", "host": "locanoto.example.test",
           "tls": "letsencrypt", "acme_email": "it@example.test",
           "model_url": "http://modelle:8000/v1", "chat_model": "c", "embedding_model": "e",
           "dimensions": 1024, "ingress_class": "nginx", "replicas": 2,
           "features": {"websearch": True, "opencloud": True, "gateway": False,
                        "oidc": True, "pages": False},
           "cloud_host": "cloud.example.test", "oidc_issuer": "https://idp.example.test",
           "oidc_client_id": "locanoto", "oidc_admin_groups": "it-admins"}
r = run_setup(answers, state, {"LOCANOTO_OIDC_SECRET": "oidc-secret-value"})
check("kubernetes render runs", r.returncode == 0, r.stderr[-800:])
objs = list(yaml.safe_load_all(open(os.path.join(state, "kubernetes.yaml"), encoding="utf-8")))
kinds = {(o["kind"], o["metadata"]["name"]) for o in objs}
check("expected objects", {("Deployment", "server"), ("Deployment", "worker"),
                           ("StatefulSet", "postgres"), ("Deployment", "websuche"),
                           ("Deployment", "opencloud"), ("Issuer", "locanoto"),
                           ("Ingress", "locanoto")} <= kinds, sorted(kinds))
by = {(o["kind"], o["metadata"]["name"]): o for o in objs}
cm = by[("ConfigMap", "locanoto")]["data"]
secret = by[("Secret", "locanoto")]["stringData"]
check("secrets in the Secret, not in the ConfigMap",
      "LOCANOTO_SCHLUESSEL" in secret and "OIDC_CLIENT_SECRET" in secret
      and "LOCANOTO_SCHLUESSEL" not in cm and "oidc-secret-value" not in json.dumps(cm))
srv_c = by[("Deployment", "server")]["spec"]["template"]["spec"]
check("server pulls the image on every rollout and builds the trust bundle first",
      srv_c["containers"][0]["imagePullPolicy"] == "Always"
      and srv_c["initContainers"][0]["name"] == "trust")
check("two server pods and shared documents storage",
      by[("Deployment", "server")]["spec"]["replicas"] == 2
      and by[("PersistentVolumeClaim", "locanoto-documents")]["spec"]["accessModes"] == ["ReadWriteMany"])
ing = by[("Ingress", "locanoto")]
check("Let's Encrypt certificate for both names",
      ing["metadata"]["annotations"]["cert-manager.io/issuer"] == "locanoto"
      and set(ing["spec"]["tls"][0]["hosts"]) == {"locanoto.example.test", "cloud.example.test"})
check("redirect address of the directory sign-in",
      cm["OIDC_REDIRECT_URI"] == "https://locanoto.example.test/api/v1/auth/oidc/callback")

# --- OpenCloud app token ---
print("=== OpenCloud app token ===")


class Done:
    def __init__(self, out, code=0):
        self.stdout, self.stderr, self.returncode = out, "", code


def fake_store(valid):
    """create() and execute() against a store that accepts the tokens in valid."""
    calls = {"create": 0, "seen": []}
    outputs = iter(["could not create token: rpc error: unavailable",
                    "App token created for admin lasting for 87600h\n token: early1",
                    "App token created for admin lasting for 87600h\n token: good22"])

    def create():
        calls["create"] += 1
        return Done(next(outputs))

    def execute(*cmd, stdin=None):
        token = stdin.strip()
        calls["seen"].append(token)
        return Done("Verbunden" if token in valid else "Anmeldung abgelehnt.",
                    0 if token in valid else 1)
    return create, execute, calls


setup.time.sleep = lambda s: None
create, execute, calls = fake_store({"good22"})
token = setup.opencloud_token({}, create, execute)
check("an error text is no token, and a rejected one is not kept",
      token == "good22" and calls["create"] == 3 and calls["seen"] == ["early1", "good22"],
      (token, calls))
create, execute, calls = fake_store({"stored9"})
check("a stored token that works is kept without a new one",
      setup.opencloud_token({"OPENCLOUD_APP_TOKEN": "stored9"}, create, execute) == "stored9"
      and calls["create"] == 0, calls)
create, execute, calls = fake_store({"good22"})
check("a revoked stored token is replaced",
      setup.opencloud_token({"OPENCLOUD_APP_TOKEN": "gone"}, create, execute) == "good22", calls)
create, execute, calls = fake_store(set())
check("no working token within the time gives None",
      setup.opencloud_token({}, create, execute, seconds=-1) is None)

# --- doctor ---
print("=== doctor ===")
env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_", "OWNCLOUD", "LOCANOTO_"))}
env.update({"LOCANOTO_KONFIG": os.path.join(TMP, "dk"), "LOCANOTO_DATEN": os.path.join(TMP, "dd"),
            "OPENAI_BASE_URL": "http://127.0.0.1:9/v1", "PYTHONIOENCODING": "utf-8",
            "LLM_RATE_MAX_WAIT": "0"})
r = subprocess.run([sys.executable, "doctor.py", "--json"], cwd=ROOT, env=env,
                   capture_output=True, text=True, encoding="utf-8", timeout=300)
try:
    rows = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    rows = []
names = [x["check"] for x in rows]
check("doctor reports each part", {"Schlüssel", "Datenbank", "Chat-Modell", "Embeddings"} <= set(names), r.stdout[-400:] + r.stderr[-400:])
check("an unreachable model fails with a hint",
      any(x["check"] == "Chat-Modell" and not x["ok"] and x["fix"] for x in rows))
check("and the exit code says so", r.returncode == 1)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
