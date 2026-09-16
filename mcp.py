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

    Drei Bedingungen, und alle drei muessen erfuellt sein:

      1. Der Betreiber hat es fuer dieses Postfach freigeschaltet.
      2. Es gibt ein Feld, in dem der Text steht.
      3. Es gibt einen Hinweis, der hineingeschrieben werden kann.

    Faellt eine davon aus, wird bestaetigt. Das ist die Richtung, in
    die ein Zweifel fallen muss: eine Nachricht zu viel zu bestaetigen
    kostet einen Klick, eine zu wenig kostet eine Nachricht, die drau-
    ssen ist.
    """
    a = _angaben(server)
    if not a.get("automatisch"):
        return False, "fuer dieses Postfach nicht freigeschaltet"
    if not textfeld(server, argumente):
        return False, ("kein Textfeld gefunden -- der Hinweis liesse "
                       "sich nicht anhaengen")
    if not (a.get("hinweis") or HINWEIS_VORGABE).strip():
        return False, "kein Hinweistext hinterlegt"
    return True, ""


def braucht_bestaetigung(server, werkzeug, argumente=None):
    """Muss ein Mensch diesen Aufruf bestaetigen?

    Nur Sendewerkzeuge ueberhaupt, und auch die nicht, wenn das
    Postfach ausdruecklich freigeschaltet ist.
    """
    if not sendet(server, werkzeug):
        return False
    ja, _grund = darf_automatisch(server, werkzeug, argumente or {})
    return not ja


def mit_hinweis(server, argumente):
    """Argumente mit angehaengtem Hinweis. Unveraendert, wenn keiner geht.

    Der Hinweis steht am ENDE und nicht am Anfang: eine Nachricht, die
    mit einer Fussnote beginnt, liest sich wie ein Formbrief, und der
    Empfaenger soll zuerst die Antwort sehen.
    """
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
