"""Werkzeugserver nach dem Model-Context-Protocol anbinden.

Bisher holt LocaNoto seinen Zusammenhang, BEVOR das Modell spricht:
Vektorsuche, Stichwortsuche, Listen, Datenbank -- alles wird
eingesammelt und in den Prompt gelegt. Das Modell entscheidet nie
selbst, etwas nachzuschlagen.

Ein Werkzeugserver dreht das um: er meldet, was er kann, und das Modell
ruft es, wenn es die Frage anders nicht beantworten kann. Damit gibt es
einen zweiten Weg, auf dem eine Antwort entsteht. Das ist Absicht und
kein Zufall -- ein Postfach laesst sich nicht vorher einsammeln, weil
niemand weiss, wonach gesucht werden soll, bevor die Frage da ist.

WAS HIER NICHT DRIN IST: die Entscheidung, WANN gerufen wird. Dieses
Modul spricht mit dem Server und sonst nichts. Der Kreis -- Modell
fragt, Werkzeug antwortet, Modell fragt weiter -- steht in pipeline.py,
dort, wo auch die uebrigen Wege zur Antwort stehen.

MCP SELBST BRINGT KEINE ABHAENGIGKEIT MIT. Es ist JSON-RPC 2.0; ueber
HTTP genuegt httpx, das ohnehin im Abbild liegt, und ueber stdio ein
Unterprozess. Ein SDK dafuer waere mehr Fremdcode als eigener.

EIN TRANSPORT SPRICHT KEIN MCP: "exchange". Exchange spricht EWS, und
LocaNoto spricht es direkt -- siehe postfach.py. verbinde() entscheidet,
welche Klasse es wird; beide haben dieselben drei Methoden, und alles
darueber unterscheidet sie nicht.

Eingerichtet wird in config/mcp.json, nach demselben Muster, das auch
andere Werkzeuge benutzen:

    {
      "postfach": {
        "transport": "http",
        "url": "https://mcp.example.org/mcp",
        "kopf": {"Authorization": "Bearer ..."}
      },
      "lokal": {
        "transport": "stdio",
        "befehl": ["python", "-m", "irgendein_server"]
      }
    }

ANMELDEDATEN STEHEN NICHT IN DIESER DATEI, wenn sie einem Menschen
gehoeren. Sie werden je Aufruf mitgegeben und leben nur so lange wie
die Sitzung -- siehe zusatz_kopf in verbinde().
"""
import base64
import json
import os
import re
import subprocess
import threading

import paths
import statefiles
import postfach

KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# Wie lange auf eine Antwort gewartet wird. Ein Werkzeug, das nicht
# antwortet, darf die Anwendung nicht anhalten -- der Nutzer sitzt vor
# einem laufenden Chat.
ZEITLIMIT = paths.env_float("MCP_TIMEOUT", 30)

# Wie viele Werkzeuge hoechstens an das Modell gehen. Ein Server mit
# hundert Werkzeugen frisst den halben Prompt, bevor die erste Frage
# gestellt ist.
MAX_WERKZEUGE = paths.env_int("MCP_MAX_WERKZEUGE", 40)

# A tool server over stdio is a command run inside the application's
# container. Whoever may enter one runs programs on the server -- that is
# the operator's decision, not that of an administrator in the
# application. Off unless the environment says otherwise; then neither
# the pages nor mcp.json can start a process.
STDIO_ERLAUBT = paths.env_int("MCP_STDIO", 0) == 1

# What a local process inherits. Not the application's whole
# environment: that holds the installation key, the database address and
# the model keys. A server that needs more gets it under "umgebung".
_STDIO_UMGEBUNG = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ", "TMPDIR",
                   "TEMP", "TMP", "SYSTEMROOT", "PATHEXT", "COMSPEC",
                   "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy",
                   "https_proxy", "no_proxy", "SSL_CERT_FILE",
                   "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")

# What the pages and the API may set for an entry besides name, kind and
# address. Everything else (command, environment, headers, transport) is
# set by the kind or by hand in mcp.json.
ERLAUBTE_ANGABEN = ("postfach", "automatisch", "hinweis", "hinweis_anhaengen",
                    "sendet", "textfeld",
                    # who sees and uses the entry (mailboxes.visible_to)
                    "owner", "room",
                    # OAuth (mcp_oauth.py): a client id where the provider
                    # registers no clients itself, scopes where the server
                    # names none
                    "oauth_client_id", "oauth_scopes")

_VERSION = "2024-11-05"


def lies_konfiguration():
    """{name: angaben} -- leer, wenn es keine Datei gibt.

    Eine fehlende Datei ist kein Fehler: die allermeisten
    Installationen haben keinen Werkzeugserver, und fuer die soll sich
    nichts aendern.
    """
    try:
        with statefiles.open(KONFIG, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


# Welche Werkzeuge eines Exchange-Postfachs etwas verschicken, steht
# dort, wo sie stehen. Hier wird es UEBERNOMMEN und nicht abgeschrieben:
# eine zweite Liste derselben Namen faellt beim ersten Umbenennen
# auseinander, und sie faellt nach der sicheren Seite -- ein
# Sendewerkzeug, das nicht mehr in der Liste steht, liefe ohne
# Rueckfrage.
_EXCHANGE_SENDET = postfach.SENDEWERKZEUGE


# --- VORLAGEN ---
#
# Damit ein Verwalter auswaehlt statt eine Datei zu schreiben. Jede
# Vorlage setzt, was fuer diese Art Server ueblich ist; Name, Adresse
# und die Regeln zum Senden kommen aus der Maske dazu.
VORLAGEN = {
    "exchange": {
        "beschreibung": "Exchange/Outlook — direkt, ohne weiteren Server",
        # transport "exchange" geht nicht ueber JSON-RPC, sondern ueber
        # postfach.py. Von hier an aufwaerts macht das keinen
        # Unterschied: dieselben Werkzeugnamen, dieselbe Bestaetigung
        # vor dem Senden, derselbe Hinweis.
        "angaben": {"transport": "exchange", "anmeldung": "basic",
                    "textfeld": "body",
                    "sendet": list(_EXCHANGE_SENDET)},
    },
    # Gmail, GMX, web.de, own servers (imap_mailbox.py). Same tools and
    # rules as Exchange, without calendar.
    "imap": {
        "beschreibung": "IMAP/SMTP — Gmail, GMX, web.de, eigener Mailserver",
        "angaben": {"transport": "imap", "anmeldung": "basic",
                    "textfeld": "body",
                    "sendet": list(_EXCHANGE_SENDET)},
    },
    "http": {
        "beschreibung": "MCP-Server über HTTP",
        "angaben": {"transport": "http", "anmeldung": "keine"},
    },
    "http_token": {
        "beschreibung": "MCP-Server über HTTP, Anmeldung mit Token",
        "angaben": {"transport": "http", "anmeldung": "bearer"},
    },
    "websuche": {
        "beschreibung": "Websuche (eigener Dienst, websuche.py)",
        # Sucht und schickt nichts. Die leere Liste schaltet die
        # Namensregel fuer Sendewerkzeuge ab: gesucht wird ohne
        # Rueckfrage, sobald der Nutzer die Websuche einschaltet.
        "angaben": {"transport": "http", "anmeldung": "keine",
                    "art": "websuche", "sendet": []},
    },
    "stdio": {
        "beschreibung": "lokaler Prozess (stdio)",
        "angaben": {"transport": "stdio", "anmeldung": "keine"},
    },
    # A data connector (connectors/README.md): a service of its own that
    # knows one system -- an ERP, an MES, a database -- and offers tools
    # to ask it. It says itself what it is for, which of its tools only
    # read, and returns tables LocaNoto lists under the answer.
    "connector": {
        "beschreibung": "Datenanschluss (ERP, MES, Datenbank) über HTTP",
        "angaben": {"transport": "http", "anmeldung": "keine",
                    "art": "connector"},
    },
    "connector_login": {
        "beschreibung": "Datenanschluss, jeder meldet sich mit seinem "
                        "Konto des Systems an",
        "angaben": {"transport": "http", "anmeldung": "basic",
                    "art": "connector"},
    },
    "connector_token": {
        "beschreibung": "Datenanschluss, Anmeldung je Nutzer mit Token",
        "angaben": {"transport": "http", "anmeldung": "bearer",
                    "art": "connector"},
    },
    # The MCP authorization standard (mcp_oauth.py): every user signs in at
    # the provider the server names -- Exchange Online through Microsoft
    # Graph, for example. The provider's rights apply per person.
    "mcp_oauth": {
        "beschreibung": "MCP-Server mit Anmeldung beim Anbieter (OAuth), "
                        "z. B. Exchange Online über Microsoft Graph",
        "angaben": {"transport": "http", "anmeldung": "oauth"},
    },
    "connector_oauth": {
        "beschreibung": "Datenanschluss, jeder meldet sich beim Anbieter an "
                        "(OAuth)",
        "angaben": {"transport": "http", "anmeldung": "oauth",
                    "art": "connector"},
    },
}


def vorlagen():
    """The kinds an administrator can pick: without the local process
    where the operator has not allowed it (STDIO_ERLAUBT)."""
    return {k: v for k, v in VORLAGEN.items()
            if STDIO_ERLAUBT or v["angaben"]["transport"] != "stdio"}


def schreibe_konfiguration(daten):
    """Schreibt mcp.json. Leer heisst: Datei weg, nichts eingerichtet."""
    statefiles.makedirs(os.path.dirname(KONFIG), exist_ok=True)
    if not daten:
        if statefiles.exists(KONFIG):
            statefiles.remove(KONFIG)
        return True, "Kein Postfach mehr eingerichtet."
    with statefiles.open(KONFIG, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    return True, f'{len(daten)} Postfach/Postfächer eingerichtet.'


def lege_an(name, vorlage, ziel, persoenlich=True, **weitere):
    """Ein Postfach aus einer Vorlage. Rueckgabe: (ok, Meldung).

    ziel ist die Adresse (http), der Befehl (stdio) oder der
    Exchange-Server (exchange, darf leer bleiben).
    """
    name = str(name or "").strip()
    if not name:
        return False, "Kein Name angegeben."
    if vorlage not in VORLAGEN:
        return False, f"Unbekannte Vorlage: {vorlage}"
    if vorlage not in vorlagen():
        return False, ("Lokale Prozesse sind auf diesem Server nicht "
                       "freigeschaltet (MCP_STDIO=1 in der Umgebung).")
    fremd = sorted(k for k in weitere if k not in ERLAUBTE_ANGABEN)
    if fremd:
        return False, f"Unbekannte Angabe: {', '.join(fremd)}"
    daten = lies_konfiguration()
    if name in daten:
        return False, f"'{name}' gibt es bereits."
    # The built-in tool server (workspace_notes) uses this name.
    if name == "workspace":
        return False, f"'{name}' ist reserviert."
    angaben = dict(VORLAGEN[vorlage]["angaben"])
    if angaben["transport"] == "stdio":
        angaben["befehl"] = [t for t in str(ziel).split() if t]
    elif angaben["transport"] == "imap":
        import imap_mailbox
        try:
            (angaben["imap_host"], angaben["imap_port"], angaben["smtp_host"],
             angaben["smtp_port"]) = imap_mailbox.parse_target(ziel)
        except ValueError as e:
            return False, str(e)
    elif angaben["transport"] == "exchange":
        # Leer heisst: exchangelib sucht den Server selbst. Das ist der
        # bequeme Weg und deshalb erlaubt -- bei den uebrigen
        # Transportarten gibt es nichts zu suchen, dort ist die Adresse
        # Pflicht.
        angaben["url"] = postfach.ews_adresse(ziel)
        # Ein Funktionspostfach ohne eigene Adresse waere keines: es
        # oeffnete das Postfach dessen, der sich gerade anmeldet. Jeder
        # saehe dann seine eigene Post unter fremdem Namen, und eine
        # automatische Antwort ginge aus dem falschen Postfach hinaus.
        if not persoenlich and not str(weitere.get("postfach") or "").strip():
            return False, ("Für ein Funktionspostfach dessen Mailadresse eintragen (z. B. info@firma.de).")
        # Umgekehrt: ein persoenlicher Eintrag gilt fuer ALLE Nutzer, jeder
        # oeffnet darin sein eigenes Postfach. Mit fester Adresse waere es
        # das Postfach einer einzigen Person, und alle anderen bekaemen von
        # Exchange eine Absage -- das ist ein Funktionspostfach ohne
        # selbstaendiges Antworten, und so wird es angelegt.
        if persoenlich and str(weitere.get("postfach") or "").strip():
            return False, ("Ein persönlicher Eintrag hat keine feste Adresse – jeder meldet sich mit seiner eigenen an. Für das Postfach einer bestimmten Person 'Funktionspostfach' wählen.")
    else:
        angaben["url"] = str(ziel).strip()
        if not angaben["url"]:
            return False, "Keine Adresse angegeben."
    # Ein persoenliches Postfach antwortet NIE von selbst. Die
    # Freischaltung gibt es nur fuer Funktionspostfaecher -- so war es
    # besprochen, und so steht es hier.
    if angaben.get("art") == "connector":
        # A connector is a system, not somebody's mailbox: it can belong
        # to a workspace (room), never to one person, and sends no mail.
        persoenlich = False
        weitere.pop("automatisch", None)
    angaben["persoenlich"] = bool(persoenlich)
    if persoenlich:
        weitere.pop("automatisch", None)
    # A personal mailbox belongs to a person, a shared one to a workspace.
    weitere.pop("room" if persoenlich else "owner", None)
    for feld in ("owner", "room"):
        if not str(weitere.get(feld) or "").strip():
            weitere.pop(feld, None)
    angaben.update({k: v for k, v in weitere.items() if v is not None})
    daten[name] = angaben
    return schreibe_konfiguration(daten)


def entferne_postfach(name):
    daten = lies_konfiguration()
    if name not in daten:
        return False, f"'{name}' ist nicht eingerichtet."
    del daten[name]
    schreibe_konfiguration(daten)
    import mcp_oauth
    mcp_oauth.forget_client(name)
    return True, f"'{name}' entfernt."


class Fehler(Exception):
    """Der Server hat nicht oder falsch geantwortet."""


class Verbindung:
    """Eine Sitzung zu einem Werkzeugserver.

    Absichtlich klein: initialisieren, Werkzeuge erfragen, Werkzeug
    rufen. Alles, was MCP sonst noch kann -- Ressourcen, Prompts,
    Benachrichtigungen -- braucht hier niemand, und was nicht da ist,
    kann auch nicht falsch benutzt werden.
    """

    def __init__(self, name, angaben, zusatz_kopf=None):
        self.name = name
        self.angaben = dict(angaben or {})
        self.zusatz_kopf = dict(zusatz_kopf or {})
        self._nummer = 0
        self._prozess = None
        self._sperre = threading.Lock()
        self._bereit = False
        # What the server says it is for (MCP "instructions").
        self.instructions = ""
        # A data connector: tables its tools returned in this answer, and
        # the tools that are not marked read-only -- those wait for a
        # person (pipeline.werkzeuglauf asks "confirm").
        self.connector = self.angaben.get("art") == "connector"
        self.tables = []
        # Tools that change something: never run on the model's word,
        # always a draft (pipeline.werkzeuglauf). Filled by werkzeuge().
        self.write_tools = set()
        # The session the server gave at the handshake (Mcp-Session-Id),
        # and the protocol version it agreed to.
        self._sitzung = ""
        self._version = ""

    # --- JSON-RPC ---

    def _naechste_nummer(self):
        self._nummer += 1
        return self._nummer

    def _ueber_http(self, nachricht):
        import httpx
        kopf = {"Content-Type": "application/json",
                # Manche Server antworten nur mit einem Ereignisstrom,
                # andere mit JSON. Beides annehmen und unten sortieren.
                "Accept": "application/json, text/event-stream"}
        kopf.update(self.angaben.get("kopf") or {})
        kopf.update(self.zusatz_kopf)
        if self._sitzung:
            kopf["Mcp-Session-Id"] = self._sitzung
        if self._version:
            kopf["MCP-Protocol-Version"] = self._version
        try:
            a = httpx.post(self.angaben["url"], json=nachricht, headers=kopf,
                           timeout=ZEITLIMIT)
        except Exception as e:
            raise Fehler(f"{self.name}: nicht erreichbar ({type(e).__name__})")
        if a.status_code == 401:
            raise Fehler(f"{self.name}: nicht angemeldet oder Anmeldung "
                         f"abgelaufen. Unter Einstellungen neu verbinden.")
        if a.status_code == 404 and self._sitzung:
            # The server ended the session: a new handshake, then again.
            raise _SitzungWeg()
        if a.status_code >= 400:
            raise Fehler(f"{self.name}: HTTP {a.status_code}")
        if nachricht.get("method") == "initialize":
            self._sitzung = a.headers.get("mcp-session-id", "") or ""
        if a.status_code == 202 or not a.content:
            return {}
        text = a.text.strip()
        if text.startswith("event:") or text.startswith("data:"):
            # Ereignisstrom: die Nutzlast steht hinter "data:". Die
            # letzte davon ist die Antwort; davor koennen Fortschritts-
            # meldungen stehen, die hier niemanden interessieren.
            stuecke = [z[5:].strip() for z in text.splitlines()
                       if z.startswith("data:")]
            text = stuecke[-1] if stuecke else ""
        try:
            return json.loads(text) if text else {}
        except ValueError:
            raise Fehler(f"{self.name}: keine lesbare Antwort")

    def _ueber_stdio(self, nachricht, lesen=True):
        # lesen=False fuer Mitteilungen. Eine Mitteilung bekommt keine
        # Antwort -- wer trotzdem eine Zeile liest, haengt, bis der
        # Server irgendwann von sich aus etwas sagt. Ueber HTTP faellt
        # das nicht auf, weil dort jede Anfrage eine Antwort hat.
        if self._prozess is None:
            if not STDIO_ERLAUBT:
                raise Fehler(f"{self.name}: lokale Prozesse sind nicht "
                             f"freigeschaltet (MCP_STDIO=1)")
            befehl = self.angaben.get("befehl")
            if not befehl:
                raise Fehler(f"{self.name}: kein Befehl eingetragen")
            umgebung = {k: os.environ[k] for k in _STDIO_UMGEBUNG
                        if k in os.environ}
            umgebung.update(self.angaben.get("umgebung") or {})
            try:
                self._prozess = subprocess.Popen(
                    befehl, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=umgebung, text=True,
                    bufsize=1)
            except OSError as e:
                raise Fehler(f"{self.name}: nicht gestartet ({e})")
        try:
            self._prozess.stdin.write(json.dumps(nachricht) + "\n")
            self._prozess.stdin.flush()
            if not lesen:
                return {}
            zeile = self._prozess.stdout.readline()
        except (OSError, ValueError) as e:
            raise Fehler(f"{self.name}: Verbindung abgebrochen ({e})")
        if not zeile:
            raise Fehler(f"{self.name}: keine Antwort")
        try:
            return json.loads(zeile)
        except ValueError:
            raise Fehler(f"{self.name}: keine lesbare Antwort")

    def _ruf(self, methode, parameter=None, antwort_erwartet=True,
             wieder=True):
        nachricht = {"jsonrpc": "2.0", "method": methode,
                     "params": parameter or {}}
        if antwort_erwartet:
            nachricht["id"] = self._naechste_nummer()
        try:
            with self._sperre:
                if self.angaben.get("transport") == "stdio":
                    antwort = self._ueber_stdio(nachricht, antwort_erwartet)
                else:
                    antwort = self._ueber_http(nachricht)
        except _SitzungWeg:
            self._sitzung, self._version, self._bereit = "", "", False
            if not wieder or methode == "initialize":
                raise Fehler(f"{self.name}: Sitzung beendet")
            self.oeffne()
            return self._ruf(methode, parameter, antwort_erwartet, wieder=False)
        if not antwort_erwartet:
            return {}
        if "error" in (antwort or {}):
            f = antwort["error"]
            raise Fehler(f"{self.name}: {f.get('message') or f}")
        return (antwort or {}).get("result") or {}

    # --- SITZUNG ---

    def oeffne(self):
        """Handschlag. Ohne ihn weist ein Server jeden Aufruf ab."""
        if self._bereit:
            return
        hallo = self._ruf("initialize", {
            "protocolVersion": _VERSION,
            "capabilities": {},
            "clientInfo": {"name": "LocaNoto", "version": "1.0"}})
        self.instructions = " ".join(
            str(hallo.get("instructions") or "").split())[:800]
        self._version = str(hallo.get("protocolVersion") or "")[:20]
        # Die Bestaetigung ist eine Mitteilung ohne Antwort. Wer hier
        # auf eine wartet, haengt.
        self._ruf("notifications/initialized", antwort_erwartet=False)
        self._bereit = True

    def werkzeuge(self):
        """[{name, beschreibung, schema}] -- was dieser Server kann."""
        self.oeffne()
        ergebnis = self._ruf("tools/list")
        aus = []
        for w in (ergebnis.get("tools") or [])[:MAX_WERKZEUGE]:
            if not isinstance(w, dict) or not w.get("name"):
                continue
            aus.append({
                "server": self.name,
                "name": w["name"],
                "beschreibung": (w.get("description") or "")[:600],
                "schema": w.get("inputSchema") or {"type": "object"},
            })
            if self.angaben.get("art") != "websuche" and schreibt(
                    w["name"], w.get("annotations"), streng=self.connector):
                self.write_tools.add(w["name"])
        return aus

    def rufe(self, name, argumente=None):
        """Ein Werkzeug ausfuehren. Gibt den Text der Antwort zurueck.

        MCP liefert eine Liste von Inhaltsteilen, die auch Bilder
        enthalten kann. Hier wird nur Text herausgezogen: was ins
        Sprachmodell geht, ist Text, und ein stillschweigend
        verworfenes Bild waere ehrlicher als eines, das als
        Zeichensalat im Prompt landet.
        """
        self.oeffne()
        ergebnis = self._ruf("tools/call",
                             {"name": name, "arguments": argumente or {}})
        teile = []
        for t in (ergebnis.get("content") or []):
            if isinstance(t, dict) and t.get("type") == "text":
                teile.append(str(t.get("text") or ""))
        text = "\n".join(teile).strip()
        if ergebnis.get("isError"):
            raise Fehler(f"{self.name}/{name}: {text or 'Fehler ohne Text'}")
        # A table (structuredContent with columns and rows): remembered
        # for the list under the answer. The model reads the text; a
        # connector that sends only the table gets it written out here.
        tabelle = ergebnis.get("structuredContent")
        if (isinstance(tabelle, dict) and isinstance(tabelle.get("columns"), list)
                and isinstance(tabelle.get("rows"), list)):
            self.tables.append({
                "server": self.name, "tool": name,
                "query": _aufruf_text(argumente),
                "rows": len(tabelle["rows"]),
                "source": " ".join(str(tabelle.get("source") or "").split())[:200],
                "truncated": bool(tabelle.get("truncated"))})
            if not text:
                import sqlpruefung
                text = sqlpruefung.als_tabelle(tabelle["columns"], tabelle["rows"])
        return text

    def schliesse(self):
        if self._prozess is not None:
            try:
                self._prozess.terminate()
            except OSError:
                pass
            self._prozess = None
        self._bereit = False


class _SitzungWeg(Exception):
    """The server answered 404 to a call of an existing session."""


# --- WHICH TOOLS CHANGE SOMETHING ---
#
# A tool server says it in the MCP annotations: readOnlyHint true for a
# tool that only reads, destructiveHint for one that deletes. A tool of
# a data connector runs on the model's word only with readOnlyHint true.
# Other servers often say nothing; their tool runs when its name says it
# reads ("list_messages", "mails_lesen") and nothing in it says it writes.
# Everything else -- "create_event", "delete_mail", "dispatch" -- waits
# for a person. A wrong guess costs a click, not a sent mail.
_LESEN = {"get", "list", "search", "read", "find", "fetch", "query",
          "describe", "show", "lookup", "count", "check", "lesen", "suchen",
          "suche", "zeige", "finde", "liste", "abfrage", "status", "info"}
_SCHREIBEN = {"send", "reply", "forward", "create", "update", "delete",
              "remove", "move", "copy", "set", "write", "post", "put",
              "patch", "add", "cancel", "accept", "decline", "mark", "flag",
              "archive", "upload", "book", "approve", "submit", "run",
              "execute", "senden", "sende", "antwort", "weiterleiten",
              "anlegen", "loeschen", "verschieben", "buchen", "schreiben",
              "aendern", "setzen", "draft", "share", "invite", "respond"}


def _woerter(name):
    teile = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", str(name or ""))
    return [t.lower() for t in teile]


def schreibt(name, annotationen=None, streng=False):
    """Does this tool change something (then it waits for a person)?"""
    a = annotationen if isinstance(annotationen, dict) else {}
    if a.get("readOnlyHint") is True and a.get("destructiveHint") is not True:
        return False
    if streng or a.get("readOnlyHint") is False or a.get("destructiveHint"):
        return True
    w = _woerter(name)
    if not w or any(x in _SCHREIBEN for x in w):
        return True
    return not (w[0] in _LESEN or w[-1] in _LESEN)


def _aufruf_text(argumente):
    """The arguments of a call as a line for the list under the answer:
    the query itself if there is one, otherwise all of them."""
    argumente = argumente or {}
    texte = [v for v in argumente.values() if isinstance(v, str)]
    if len(argumente) == 1 and texte:
        return texte[0][:2000]
    return json.dumps(argumente, ensure_ascii=False)[:2000]


ANMELDUNGEN = {
    "keine": "keine Anmeldung -- der Server regelt es selbst",
    "basic": "Benutzer und Passwort (Authorization: Basic)",
    "bearer": "ein Token (Authorization: Bearer)",
    "oauth": "Anmeldung beim Anbieter je Nutzer (OAuth 2.1)",
}


def anmeldeart(server):
    """Wie dieser Server die Anmeldedaten erwartet."""
    art = str(_angaben(server).get("anmeldung") or "keine")
    return art if art in ANMELDUNGEN else "keine"


def braucht_anmeldung(server):
    """Muss ein Mensch fuer diesen Server etwas eingeben?"""
    return anmeldeart(server) != "keine"


def kopf_fuer(server, benutzer="", geheimnis=""):
    """Der Kopf, den die Anmeldedaten dieses Servers ergeben.

    Gebaut wird er hier und nicht in der Oberflaeche: welche Form ein
    Server erwartet, ist eine Eigenschaft des Servers, und sie steht in
    seiner Konfiguration.
    """
    art = anmeldeart(server)
    if art == "basic":
        roh = f"{benutzer}:{geheimnis}".encode("utf-8")
        return {"Authorization": "Basic "
                + base64.b64encode(roh).decode("ascii")}
    if art in ("bearer", "oauth"):
        # oauth: a program that signed in itself (API) sends its token.
        return {"Authorization": f"Bearer {geheimnis}"}
    return {}


def websuche_server():
    """Die Namen der eingerichteten Websuche-Server."""
    return {n for n, a in lies_konfiguration().items()
            if a.get("art") == "websuche"}


def verbinde(koepfe=None, ohne=()):
    """{name: Verbindung} fuer alles, was in der Konfiguration steht.

    koepfe ordnet JE SERVER einen zusaetzlichen Kopf zu -- {name: kopf}.
    Auf diesem Weg kommen sitzungsgebundene Anmeldedaten mit: sie stehen
    weder in der Konfigurationsdatei noch auf der Platte, sondern nur im
    Arbeitsspeicher dieser einen Sitzung.

    JE SERVER und nicht fuer alle. Ein gemeinsamer Kopf ginge auch an
    Postfaecher, mit denen der Nutzer nichts zu tun hat -- bei einem
    persoenlichen Postfach waere das sein Passwort, verteilt an jeden
    eingerichteten Server.
    """
    koepfe = koepfe or {}
    aus = {}
    for name, angaben in lies_konfiguration().items():
        # Etwa die Websuche, solange der Nutzer sie nicht eingeschaltet
        # hat: dann sieht das Modell das Werkzeug gar nicht erst.
        if name in ohne:
            continue
        # Ein Exchange-Postfach spricht kein JSON-RPC. Welche Klasse es
        # wird, entscheidet sich HIER und nur hier -- nach aussen haben
        # beide dieselben drei Methoden, und alles darueber merkt vom
        # Unterschied nichts.
        transport = angaben.get("transport") or "http"
        if transport == "imap":
            import imap_mailbox
            bauart = imap_mailbox.ImapMailbox
        else:
            bauart = postfach.Postfach if transport == "exchange" else Verbindung
        aus[name] = bauart(name, angaben, koepfe.get(name))
    return aus


def eingerichtet():
    return bool(lies_konfiguration())


def als_werkzeugliste(verbindungen, sagen=None):
    """Alle Werkzeuge aller Server, in der Form des Chat-Modells.

    Ein Server, der nicht antwortet, faellt heraus und nimmt die
    anderen nicht mit. Das ist der haeufige Fall -- ein Postfachserver
    ist nicht erreichbar, und die Frage nach einem Dokument soll
    trotzdem beantwortet werden.
    """
    aus = []
    for v in verbindungen.values():
        try:
            for w in v.werkzeuge():
                aus.append({
                    "type": "function",
                    "function": {
                        # Der Servername gehoert in den Werkzeugnamen:
                        # zwei Server duerfen dasselbe Werkzeug
                        # anbieten, und das Modell muss sagen koennen,
                        # welches es meint.
                        "name": f"{w['server']}__{w['name']}",
                        "description": w["beschreibung"],
                        "parameters": w["schema"],
                    },
                })
        except Exception as e:
            if sagen:
                sagen(f"{v.name}: {e}")
    return aus


def teile_namen(voller_name):
    """'server__werkzeug' -> (server, werkzeug)."""
    server, _, name = str(voller_name or "").partition("__")
    return server, name


# --- WAS RAUSGEHT, GEHT NICHT ZURUECK ---
#
# Eine verschickte Nachricht ist das Einzige in diesem System, das sich
# nicht rueckgaengig machen laesst. Kein Abzug hilft, keine
# Wiederherstellung, und der Empfaenger hat sie. Der wahrscheinlichere
# Fehler ist dabei nicht ein schlechter Text, sondern ein falscher
# Adressat -- und dann liegt Kundeninformation bei jemandem, der sie
# nie haette sehen duerfen.
#
# Deshalb: das Modell SCHLAEGT VOR, ein Mensch schickt. Wer das fuer
# ein Funktionspostfach anders will, schaltet es dort ausdruecklich
# frei -- und dann traegt jede Nachricht einen Hinweis, dass sie
# automatisch entstanden ist.

# Wonach ein Sendewerkzeug erkannt wird, wenn der Betreiber nichts
# eingetragen hat. Eine Namensregel ist eine Kruecke und wird auch so
# behandelt: sie kann nur zu VIEL bestaetigen lassen, nie zu wenig --
# siehe braucht_bestaetigung().
_SENDEWOERTER = ("send", "sende", "reply", "antwort", "forward",
                 "weiterleit", "mail_post", "post_mail", "draft_send")

# Wo der Hinweis angehaengt wird, wenn kein Feld eingetragen ist.
_TEXTFELDER = ("body", "text", "content", "inhalt", "message", "nachricht")

HINWEIS_VORGABE = ("Diese Nachricht wurde automatisch erstellt und vor "
                   "dem Versand nicht von einem Menschen gelesen.")


def _angaben(server):
    return lies_konfiguration().get(server) or {}


def sendet(server, werkzeug):
    """Verschickt dieses Werkzeug etwas?

    Zuerst die Liste des Betreibers -- sie ist die verlaessliche
    Auskunft, denn nur er kennt die Werkzeuge seines Servers. Ohne
    Liste bleibt die Namensregel, und die ist ausdruecklich eine
    Kruecke: ein Sendewerkzeug, das 'dispatch' heisst, faellt durch.

    Genau deshalb entscheidet nicht diese Funktion allein, ob ohne
    Rueckfrage gesendet wird -- siehe braucht_bestaetigung().
    """
    a = _angaben(server)
    liste = a.get("sendet")
    if a.get("transport") in ("exchange", "imap"):
        # The list was copied into the entry when it was created. Tools
        # that came later (the calendar, forwarding, moving) count as
        # sending all the same -- otherwise an older entry would run them
        # without a question.
        return werkzeug in (set(liste or []) | set(postfach.SENDEWERKZEUGE)
                            | set(postfach.CONFIRM_TOOLS))
    if isinstance(liste, list):
        return werkzeug in liste
    n = str(werkzeug or "").lower()
    return any(w in n for w in _SENDEWOERTER)


def textfeld(server, argumente):
    """Der Name des Arguments, in dem der Nachrichtentext steht.

    Leer, wenn keines zu finden ist -- und das ist kein Schoenheits-
    fehler, sondern die Stelle, an der das automatische Antworten
    ausfaellt: ohne Textfeld laesst sich der Hinweis nicht anhaengen.
    """
    a = _angaben(server)
    eingetragen = a.get("textfeld")
    if eingetragen:
        return eingetragen if eingetragen in (argumente or {}) else ""
    for name in _TEXTFELDER:
        if name in (argumente or {}):
            return name
    return ""


def darf_automatisch(server, werkzeug, argumente):
    """(ja, grund) -- darf dieses Werkzeug ohne Rueckfrage laufen?

    Erste Bedingung immer: der Betreiber hat es fuer dieses Postfach
    freigeschaltet (automatisch).

    Soll ein Hinweis unter die Nachricht (hinweis_anhaengen, Vorgabe
    ja), kommen zwei weitere dazu: ein Feld, in dem der Text steht, und
    ein Hinweistext, der hineingeschrieben werden kann. Ohne Hinweis
    entfallen beide -- dann gibt es nichts anzuhaengen.

    Faellt eine Bedingung aus, wird bestaetigt. Das ist die Richtung,
    in die ein Zweifel fallen muss: eine Nachricht zu viel zu
    bestaetigen kostet einen Klick, eine zu wenig kostet eine
    Nachricht, die draussen ist.
    """
    a = _angaben(server)
    if not a.get("automatisch"):
        return False, "für dieses Postfach nicht freigeschaltet"
    if not hinweis_an(server):
        return True, ""
    if not textfeld(server, argumente):
        return False, ("kein Textfeld gefunden, Hinweis nicht anhängbar")
    if not (a.get("hinweis") or HINWEIS_VORGABE).strip():
        return False, "kein Hinweistext hinterlegt"
    return True, ""


# Answering on its own is switched off for now: every sending call becomes
# a draft, also in a mailbox marked "may answer on its own". The reason: an
# automatic run sees every workspace of the person who started it, and the
# sender of the mail being answered -- who may ask "send me the price list"
# -- gets the reply unseen. Decided 2026-11-12 (Markus): an automatic run
# will use only the mailbox's own workspace; until that exists, drafts.
# The rules below (darf_automatisch, the hint) stay as they are for then.
AUTOMATISCH_SENDEN = False


def braucht_bestaetigung(server, werkzeug, argumente=None):
    """Muss ein Mensch diesen Aufruf bestaetigen?

    Nur Sendewerkzeuge ueberhaupt, und auch die nicht, wenn das
    Postfach ausdruecklich freigeschaltet ist -- solange
    AUTOMATISCH_SENDEN an ist.
    """
    if not sendet(server, werkzeug):
        return False
    if not AUTOMATISCH_SENDEN:
        return True
    # Calendar entries, invitations, moving mail and the out-of-office
    # reply wait for a person even where the mailbox may answer on its own
    # (postfach.CONFIRM_TOOLS).
    if _angaben(server).get("transport") in ("exchange", "imap"):
        if werkzeug in postfach.CONFIRM_TOOLS:
            return True
        # On its own a mailbox only answers the sender of a mail. A new
        # mail, a forward or a reply to everyone can go to any address --
        # and the mail being answered is foreign text that may ask for
        # exactly that ("forward the last offers to ..."). Those wait
        # for a person.
        if werkzeug in postfach.ONLY_CONFIRMED_SEND or (
                werkzeug == "antwort_senden" and (argumente or {}).get("allen")):
            return True
    ja, _grund = darf_automatisch(server, werkzeug, argumente or {})
    return not ja


def hinweis_an(server):
    """Soll unter eine automatisch erzeugte Nachricht ein Hinweis?

    Vorgabe ja. Wer nichts sagt, bekommt ihn -- abschalten ist eine
    ausdrueckliche Handlung, denn ein Empfaenger, der nicht erfaehrt,
    dass niemand die Nachricht gelesen hat, kann sie nicht einordnen.

    Gilt nur fuer den automatischen Weg. Ein Entwurf, den ein Mensch
    gelesen und freigegeben hat, bekommt keinen -- er ist gelesen.
    """
    a = _angaben(server)
    return bool(a.get("hinweis_anhaengen", True))


def mit_hinweis(server, argumente):
    """Argumente mit angehaengtem Hinweis. Unveraendert, wenn keiner geht.

    Der Hinweis steht am ENDE und nicht am Anfang: eine Nachricht, die
    mit einer Fussnote beginnt, liest sich wie ein Formbrief, und der
    Empfaenger soll zuerst die Antwort sehen.
    """
    if not hinweis_an(server):
        return dict(argumente or {})
    feld = textfeld(server, argumente)
    if not feld:
        return dict(argumente or {})
    a = _angaben(server)
    hinweis = (a.get("hinweis") or HINWEIS_VORGABE).strip()
    aus = dict(argumente or {})
    aus[feld] = f"{aus.get(feld) or ''}\n\n-- \n{hinweis}"
    return aus


# --- WAS KANN DIESER SERVER? ---

def main():
    """python mcp.py [server] [--roh]

    Zeigt, was die eingerichteten Werkzeugserver anbieten. Gebraucht an
    zwei Stellen:

    BEIM EINRICHTEN. Welches Werkzeug sucht, welches sendet und wie das
    Feld mit dem Nachrichtentext heisst -- das steht in dieser Ausgabe
    und muss danach in mcp.json unter "sendet" und "textfeld" nach.
    Raten waere hier teuer: ein nicht erkanntes Sendewerkzeug liefe
    ohne Rueckfrage.

    ALS PROBE. Antwortet der Server? Stimmen die Anmeldedaten? Eine
    Frage im Chat ist ein schlechtes Messwerkzeug dafuer -- dort sieht
    ein nicht erreichbarer Server aus wie ein Modell, das nichts weiss.

    --roh gibt die Antwort so aus, wie sie kam. DIE KONFIGURATION WIRD
    NIE MITGEDRUCKT: dort koennen Token stehen, und eine Ausgabe, die
    man weiterschickt, soll sich weiterschicken lassen.
    """
    import sys

    paths.bootstrap()
    roh = "--roh" in sys.argv
    nur = next((a for a in sys.argv[1:] if not a.startswith("-")), "")

    konf = lies_konfiguration()
    if not konf:
        print(f"Kein Werkzeugserver eingerichtet ({KONFIG} fehlt).")
        print()
        print("Beispiel:")
        print(json.dumps({"postfach": {
            "transport": "http", "url": "https://.../mcp",
            "sendet": ["send_mail"], "textfeld": "body"}},
            indent=2, ensure_ascii=False))
        return 2

    fehler = 0
    for name, angaben in sorted(konf.items()):
        if nur and name != nur:
            continue
        print("=" * 62)
        print(f"{name}   ({angaben.get('transport') or 'http'})")
        print("=" * 62)
        v = Verbindung(name, angaben)
        try:
            wz = v.werkzeuge()
        except Exception as e:
            print(f"  [!] {e}")
            fehler += 1
            continue
        finally:
            v.schliesse()
        if not wz:
            print("  Keine Werkzeuge gemeldet.")
            continue
        for w in wz:
            marke = "SENDET" if sendet(name, w["name"]) else "liest"
            print(f"\n  [{marke}] {w['name']}")
            if w["beschreibung"]:
                print(f"      {w['beschreibung'][:200]}")
            felder = (w["schema"] or {}).get("properties") or {}
            pflicht = set((w["schema"] or {}).get("required") or [])
            for f, angabe in felder.items():
                art = (angabe or {}).get("type") or "?"
                print(f"      - {f} ({art})"
                      + ("  PFLICHT" if f in pflicht else ""))
            if roh:
                print("      " + json.dumps(w["schema"], ensure_ascii=False))
        print()
        # Der Hinweis, der die eigentliche Arbeit beim Einrichten ist.
        sendende = [w["name"] for w in wz if sendet(name, w["name"])]
        if sendende and not isinstance(angaben.get("sendet"), list):
            print(f"  ACHTUNG: 'sendet' ist fuer '{name}' nicht eingetragen.")
            print(f"  Erkannt ueber die Namensregel: {', '.join(sendende)}")
            print("  Ein Sendewerkzeug, das anders heisst, faellt durch --")
            print("  und liefe damit ohne Rueckfrage. Bitte eintragen.")
            print()
    return 1 if fehler else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
