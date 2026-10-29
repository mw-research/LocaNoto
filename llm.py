"""Modell-Endpunkte je Aufgabe.

Bisher liefen alle Aufrufe ueber eine einzige Adresse (OPENAI_BASE_URL). Wer
das Chat-Modell bei einem Anbieter und die Embeddings lokal betreiben will,
brauchte dafuer einen vorgeschalteten Proxy.

Hier bekommt jede Aufgabe ihre eigene Adresse, ihren eigenen Schluessel und
ihren eigenen Modellnamen. Nicht gesetzte Werte fallen auf OPENAI_BASE_URL
und OPENAI_API_KEY zurueck -- eine bestehende Konfiguration mit nur diesen
beiden Variablen verhaelt sich also unveraendert.

Aufgaben (Praefix in der .env):

    CHAT       Antwort und Umformulierung der Suchanfrage
    TITLE      Benennung des Chats
    EMBEDDING  Vektorisierung von Chunks und Suchanfragen
    VISION     Bildbeschreibung im Ingest
    SQL        Erzeugung der Datenbankabfrage (nur Handbuch-Variante)

Je Aufgabe:

    <AUFGABE>_MODEL        Modell- bzw. Deployment-Name
    <AUFGABE>_BASE_URL     Adresse; leer = OPENAI_BASE_URL
    <AUFGABE>_API_KEY      Schluessel; leer = OPENAI_API_KEY
    <AUFGABE>_API_VERSION  nur fuer Azure OpenAI; gesetzt = Azure-Client

MANY ENDPOINTS, RATE LIMITS (for larger installations). Every task may
name several endpoints and keys, separated by commas:

    CHAT_BASE_URL=http://vllm-a:8000/v1,http://vllm-b:8000/v1
    CHAT_API_KEY=key-a,key-b          one key for all, or one per address

Calls are spread over them in turn. An endpoint that answers 429, 5xx or
not at all is skipped for LLM_COOLDOWN seconds and the call goes to the
next one. When every endpoint is busy, a 429 is waited out (Retry-After,
else growing pauses) up to LLM_RATE_MAX_WAIT seconds in total instead of
failing at once. <TASK>_MAX_CONCURRENT caps parallel calls of this
process to one task -- protects a single local model server. Limits
across all pods belong in a gateway (LiteLLM proxy, see
k8s/enterprise/gateway.yaml); then the lists above hold the gateway only.

LLM_SEND_USER=pseudonym sends a pseudonym of the user (HMAC with the
installation key, never the name) as "user" with every call, so a gateway
can count usage per person without learning who it is. Default: off.

Beispiel: Chat ueber Azure, alles andere lokal ueber Ollama.

    OPENAI_BASE_URL=http://ollama:11434/v1
    OPENAI_API_KEY=ollama

    CHAT_MODEL=gpt-4o
    CHAT_BASE_URL=https://meine-instanz.openai.azure.com
    CHAT_API_KEY=...
    CHAT_API_VERSION=2024-10-21
"""
import contextlib
import contextvars
import hashlib
import hmac
import itertools
import os
import random
import threading
import time

from openai import OpenAI

import paths

STANDARD_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:4000")
STANDARD_API_KEY = os.getenv("OPENAI_API_KEY", "Dein_Platzhalter_Key")

# Modellnamen, falls die Umgebung nichts vorgibt.
# Wiederholungen des Clients selbst. Der OpenAI-Client versucht eine
# fehlgeschlagene Anfrage ohne Zutun zweimal erneut -- damit ist ein
# gesetztes Zeitlimit nicht die Wartezeit, sondern ein Drittel davon. Die
# Skripte bringen ihre eigenen Wiederholungen mit (VISION_VERSUCHE), und
# beide Ebenen multiplizieren sich: aus drei Versuchen werden neun.
#
# Deshalb hier ein Versuch. Wer die Wiederholung des Clients moechte, setzt
# LLM_VERSUCHE hoeher.
LLM_VERSUCHE = max(1, paths.env_int("LLM_VERSUCHE", 1))

STANDARD_MODELLE = {
    "CHAT": "qwen3.8:27b",
    "TITLE": "",           # leer = Chat-Modell verwenden
    "EMBEDDING": "qwen3-embedding:8b",
    "VISION": "qwen3-vl:32b",
    "SQL": "",             # leer = Chat-Modell verwenden
}

# Ein Client je Endpunkt statt je Aufruf. Zwei Aufgaben auf derselben Adresse
# teilen sich damit die Verbindung.
_clients = {}


def _wert(aufgabe, feld, standard=""):
    return os.getenv(f"{aufgabe.upper()}_{feld}", standard).strip()


def basis_url(aufgabe):
    return _wert(aufgabe, "BASE_URL") or STANDARD_BASE_URL


def api_key(aufgabe):
    return _wert(aufgabe, "API_KEY") or STANDARD_API_KEY


def modell(aufgabe, rueckfall=None):
    """Modellname der Aufgabe.

    Ist keiner gesetzt, greift der uebergebene Rueckfall und danach der
    Standard aus STANDARD_MODELLE.
    """
    name = _wert(aufgabe, "MODEL")
    if name:
        return name
    if rueckfall:
        return rueckfall
    return STANDARD_MODELLE.get(aufgabe.upper(), "")


def chat_modelle():
    """Die Chat-Modelle, zwischen denen Nutzer waehlen duerfen.

    CHAT_MODELLE, durch Kommas getrennt; das Modell aus CHAT_MODEL steht
    immer vorn. Ein Modell, das hier nicht steht, laesst sich in der
    Oberflaeche nicht waehlen -- ein Tippfehler waere sonst erst bei der
    naechsten Frage ein Fehler.
    """
    standard = modell("CHAT")
    liste = [m.strip() for m in os.getenv("CHAT_MODELLE", "").split(",")
             if m.strip()]
    return [standard] + [m for m in liste if m != standard]


def _einzelclient(base, key, version):
    """Ein OpenAI- oder Azure-Client fuer genau eine Adresse."""
    schluessel = (base, key, version)
    if schluessel in _clients:
        return _clients[schluessel]
    if version:
        from openai import AzureOpenAI  # nur bei Azure-Nutzung geladen
        c = AzureOpenAI(azure_endpoint=base, api_key=key,
                        api_version=version,
                        max_retries=LLM_VERSUCHE - 1)
    else:
        c = OpenAI(base_url=base, api_key=key, max_retries=LLM_VERSUCHE - 1)
    _clients[schluessel] = c
    return c


def endpoints(aufgabe):
    """[(base, key)] of a task -- several when the settings list several."""
    bases = [b.strip() for b in basis_url(aufgabe).split(",") if b.strip()]
    keys = [k.strip() for k in api_key(aufgabe).split(",") if k.strip()] or [""]
    if len(keys) not in (1, len(bases)):
        raise ValueError(aufgabe + "_API_KEY: give one key or one per address")
    return [(b, keys[i] if len(keys) > 1 else keys[0])
            for i, b in enumerate(bases)]


def client(aufgabe):
    """Client fuer die Aufgabe, zwischengespeichert je Endpunkt.

    Returns a GuardedClient: same calls (chat.completions.create,
    embeddings.create), plus spreading over several endpoints, waiting
    out rate limits, a cap on parallel calls and counters (see the
    module docstring).

    Ist <AUFGABE>_API_VERSION gesetzt, wird ein Azure-Client erzeugt: Azure
    OpenAI erwartet Adresse, Schluessel und Version in anderer Form als die
    OpenAI-kompatiblen Server.
    """
    version = _wert(aufgabe, "API_VERSION")
    eps = tuple(endpoints(aufgabe))
    schluessel = ("guarded", aufgabe.upper(), eps, version)
    with _guard_lock:
        if schluessel not in _clients:
            _clients[schluessel] = GuardedClient(
                aufgabe.upper(),
                [(b, _einzelclient(b, k, version)) for b, k in eps])
        return _clients[schluessel]


# --- GUARDED CLIENT ---

RATE_MAX_WAIT = paths.env_float("LLM_RATE_MAX_WAIT", 60)
COOLDOWN = paths.env_float("LLM_COOLDOWN", 30)
SEND_USER = os.getenv("LLM_SEND_USER", "off").strip().lower()

_guard_lock = threading.Lock()
_acting_for = contextvars.ContextVar("llm_acting_for", default="")

# Counters per task, read by metrics.py: calls, errors, rate_limited,
# waited_seconds, seconds (time in calls), in_flight.
STATS = {}
_stats_lock = threading.Lock()


def _count(task, **add):
    with _stats_lock:
        s = STATS.setdefault(task, {"calls": 0, "errors": 0,
                                    "rate_limited": 0, "waited_seconds": 0.0,
                                    "seconds": 0.0, "in_flight": 0})
        for k, v in add.items():
            s[k] += v


@contextlib.contextmanager
def acting_for(user):
    """Calls inside this block are made on behalf of user (see LLM_SEND_USER)."""
    token = _acting_for.set(user or "")
    try:
        yield
    finally:
        _acting_for.reset(token)


class _ForUser:
    """A client whose calls are made on behalf of one user."""

    def __init__(self, inner, user):
        self._inner, self._user = inner, user
        self.chat = _Namespace(completions=_Namespace(
            create=lambda **kw: self._call(inner.chat.completions, kw)))
        self.embeddings = _Namespace(
            create=lambda **kw: self._call(inner.embeddings, kw))

    def _call(self, target, kw):
        with acting_for(self._user):
            return target.create(**kw)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def for_user(client_, user):
    """client_ with every call made on behalf of user (see LLM_SEND_USER)."""
    return _ForUser(client_, user)


def pseudonym(user):
    """A stable pseudonym of a user name -- not reversible without the key."""
    import geheim
    k = geheim.schluessel()
    if not user or k is None:
        return ""
    return "u-" + hmac.new(k, b"llm-user:" + user.encode("utf-8"),
                           hashlib.sha256).hexdigest()[:16]


def _status(error):
    return getattr(error, "status_code", None) or getattr(
        getattr(error, "response", None), "status_code", None)


def _retry_after(error):
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after") or headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def _retryable(error):
    """429, 5xx and connection trouble go to the next endpoint."""
    status = _status(error)
    if status is not None:
        return status == 429 or status >= 500
    name = type(error).__name__
    return name in ("APIConnectionError", "APITimeoutError", "ConnectError",
                    "ConnectTimeout", "ReadTimeout")


class GuardedClient:
    """OpenAI-compatible client over one or more endpoints of a task."""

    def __init__(self, task, endpoints_):
        self.task = task
        self._endpoints = endpoints_
        self._turn = itertools.count()
        self._resting = {}                    # base -> until
        limit = paths.env_int(f"{task}_MAX_CONCURRENT", 0)
        self._slots = threading.BoundedSemaphore(limit) if limit > 0 else None
        self.chat = _Namespace(completions=_Namespace(
            create=lambda **kw: self._call("chat", kw)))
        self.embeddings = _Namespace(
            create=lambda **kw: self._call("embeddings", kw))

    def _order(self):
        n = len(self._endpoints)
        start = next(self._turn) % n
        ordered = self._endpoints[start:] + self._endpoints[:start]
        now = time.time()
        ready = [e for e in ordered if self._resting.get(e[0], 0) <= now]
        return ready or ordered               # all resting: try anyway

    def _call(self, kind, kw):
        if SEND_USER == "pseudonym" and "user" not in kw:
            alias = pseudonym(_acting_for.get())
            if alias:
                kw["user"] = alias
        if self._slots:
            self._slots.acquire()
        _count(self.task, in_flight=1)
        started, waited, pause = time.time(), 0.0, 1.0
        try:
            while True:
                last, overloaded = None, False
                for base, c in self._order():
                    target = c.chat.completions if kind == "chat" else c.embeddings
                    try:
                        result = target.create(**kw)
                        _count(self.task, calls=1)
                        return result
                    except Exception as e:  # noqa: BLE001 -- sorted below
                        last = e
                        if not _retryable(e):
                            _count(self.task, calls=1, errors=1)
                            raise
                        # Next endpoint. A timeout or a broken server is
                        # not tried again here: that would multiply the
                        # time limit (see LLM_VERSUCHE).
                        self._resting[base] = time.time() + COOLDOWN
                        if _status(e) in (429, 503):
                            overloaded = True
                            _count(self.task, rate_limited=1)
                # Every endpoint failed. Only overload is waited out.
                remaining = RATE_MAX_WAIT - waited
                asked = _retry_after(last)
                # Knocking earlier than the server asked only costs more
                # rejected calls: give up if its wait exceeds what is left.
                if not overloaded or remaining <= 0 or (asked and asked > remaining):
                    _count(self.task, calls=1, errors=1)
                    raise last
                wait = min(asked or pause, remaining)
                wait *= 0.8 + 0.4 * random.random()
                time.sleep(wait)
                waited += wait
                pause = min(pause * 2, 20)
                self._resting.clear()
                _count(self.task, waited_seconds=wait)
        finally:
            _count(self.task, in_flight=-1, seconds=time.time() - started)
            if self._slots:
                self._slots.release()

    def __getattr__(self, name):
        # Anything else (models.list, ...) goes to the first endpoint.
        return getattr(self._endpoints[0][1], name)


class _Namespace:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def uebersicht():
    """Zeilenweise Darstellung der aufgeloesten Endpunkte, ohne Schluessel."""
    zeilen = []
    for aufgabe in ("CHAT", "TITLE", "EMBEDDING", "VISION", "SQL"):
        name = modell(aufgabe) or "(Chat-Modell)"
        art = "Azure" if _wert(aufgabe, "API_VERSION") else "OpenAI-kompatibel"
        n = len([b for b in basis_url(aufgabe).split(",") if b.strip()])
        adressen = basis_url(aufgabe) if n == 1 else f"{n} Adressen"
        zeilen.append(f"{aufgabe:<10} {name:<28} {adressen}  [{art}]")
    return "\n".join(zeilen)
