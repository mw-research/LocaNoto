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

KEINE NEUE ABHAENGIGKEIT. MCP ist JSON-RPC 2.0; ueber HTTP genuegt
httpx, das ohnehin im Abbild liegt, und ueber stdio ein Unterprozess.
Ein SDK dafuer waere mehr Fremdcode als eigener.

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
import json
import os
import subprocess
import threading

import paths

KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# Wie lange auf eine Antwort gewartet wird. Ein Werkzeug, das nicht
# antwortet, darf die Anwendung nicht anhalten -- der Nutzer sitzt vor
# einem laufenden Chat.
ZEITLIMIT = paths.env_float("MCP_TIMEOUT", 30)

# Wie viele Werkzeuge hoechstens an das Modell gehen. Ein Server mit
# hundert Werkzeugen frisst den halben Prompt, bevor die erste Frage
# gestellt ist.
MAX_WERKZEUGE = paths.env_int("MCP_MAX_WERKZEUGE", 40)

_VERSION = "2024-11-05"


def lies_konfiguration():
    """{name: angaben} -- leer, wenn es keine Datei gibt.

    Eine fehlende Datei ist kein Fehler: die allermeisten
    Installationen haben keinen Werkzeugserver, und fuer die soll sich
    nichts aendern.
    """
    try:
        with open(KONFIG, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


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
        try:
            a = httpx.post(self.angaben["url"], json=nachricht, headers=kopf,
                           timeout=ZEITLIMIT)
        except Exception as e:
            raise Fehler(f"{self.name}: nicht erreichbar ({type(e).__name__})")
        if a.status_code >= 400:
            raise Fehler(f"{self.name}: HTTP {a.status_code}")
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
            befehl = self.angaben.get("befehl")
            if not befehl:
                raise Fehler(f"{self.name}: kein Befehl eingetragen")
            umgebung = dict(os.environ)
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

    def _ruf(self, methode, parameter=None, antwort_erwartet=True):
        nachricht = {"jsonrpc": "2.0", "method": methode,
                     "params": parameter or {}}
        if antwort_erwartet:
            nachricht["id"] = self._naechste_nummer()
        with self._sperre:
            if self.angaben.get("transport") == "stdio":
                antwort = self._ueber_stdio(nachricht, antwort_erwartet)
            else:
                antwort = self._ueber_http(nachricht)
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
        self._ruf("initialize", {
            "protocolVersion": _VERSION,
            "capabilities": {},
            "clientInfo": {"name": "LocaNoto", "version": "1.0"}})
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
        return text

    def schliesse(self):
        if self._prozess is not None:
            try:
                self._prozess.terminate()
            except OSError:
                pass
            self._prozess = None
        self._bereit = False


def verbinde(zusatz_kopf=None):
    """{name: Verbindung} fuer alles, was in der Konfiguration steht.

    zusatz_kopf geht an JEDEN Server und ist der Weg, auf dem
    sitzungsgebundene Anmeldedaten mitkommen -- sie stehen damit weder
    in der Konfigurationsdatei noch auf der Platte, sondern nur im
    Arbeitsspeicher dieser einen Sitzung.
    """
    return {name: Verbindung(name, angaben, zusatz_kopf)
            for name, angaben in lies_konfiguration().items()}


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
