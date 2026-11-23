"""Self-test, part 02: Images to text, load test, budget, packing for a move, the tool loop, what leaves the installation.

Runs only through tests/selftest.py, after the parts before it.
"""
print("=== 21. Bilder werden zu Text ===")
# Zwei Faelle, die verschieden sind und oft verwechselt werden: eine
# gescannte Seite ohne Textebene findet die Suche GAR NICHT -- nicht
# wenig, sondern nichts. Eine Abbildung in einem Textdokument findet
# sie, nur nicht das, was allein im Bild steht.
import bildtext
import pymupdf as _pm

_d = _pm.open()
_s1 = _d.new_page()
_s1.insert_text((60, 90), "Eine gewoehnliche Textseite mit genuegend "
                          "Inhalt, um nicht als Scan zu gelten.")
_s1.insert_text((60, 120), "Noch eine Zeile fuer die Schwelle.")
_s2 = _d.new_page()
_s2.insert_text((60, 90), "7")          # nur eine Seitenzahl
_s3 = _d.new_page()
_s3.insert_text((60, 90), "Eine Seite mit Text und einem Schaubild "
                          "darunter, also der zweite Fall.")
_gross = _pm.Pixmap(_pm.csRGB, _pm.IRect(0, 0, 800, 600))
_gross.set_rect(_gross.irect, (200, 40, 40))
_s3.insert_image(_pm.Rect(60, 150, 560, 525), pixmap=_gross)

_scans, _abb = bildtext.zaehle(_d)
pruef("eine Seite ohne Textebene gilt als Scan", _scans == 1, _scans)
pruef("und eine grosse Abbildung wird gezaehlt", _abb == 1, _abb)

# Ein Logo ist kein Schaubild. Ohne die Schwelle bekaeme jedes
# Briefkopfsymbol einen Modellaufruf -- bei zweihundert Seiten
# zweihundert.
_d2 = _pm.open()
_s = _d2.new_page()
_s.insert_text((60, 90), "Seite mit Text und einem winzigen Symbol "
                         "daneben, das kein Schaubild ist.")
_klein = _pm.Pixmap(_pm.csRGB, _pm.IRect(0, 0, 40, 40))
_klein.set_rect(_klein.irect, (10, 10, 200))
_s.insert_image(_pm.Rect(500, 60, 540, 100), pixmap=_klein)
pruef("ein winziges Bild gilt als Logo und faellt weg",
      bildtext.zaehle(_d2)[1] == 0, bildtext.zaehle(_d2)[1])

# Die Beschreibung selbst, mit einer Attrappe statt eines Sehmodells.
_gerufen = []
_attrappe = types.ModuleType("vision")
_attrappe.beschreibe = lambda daten, frage="": (
    _gerufen.append(frage[:20]) or f"Beschreibung {len(_gerufen)}")
sys.modules["vision"] = _attrappe
_ergebnis = bildtext.beschreibungen(_d, "probe.pdf")
pruef("beide Faelle ergeben einen Abschnitt", len(_ergebnis) == 2,
      len(_ergebnis))
pruef("die Art steht dabei",
      [a for _s, _t, a in _ergebnis] == ["seite", "abbildung"],
      [a for _s, _t, a in _ergebnis])
pruef("und die Seitenzahl stimmt",
      [s for s, _t, _a in _ergebnis] == [2, 3],
      [s for s, _t, _a in _ergebnis])
# Verschiedene Fragen: bei einem Scan ist die Beschreibung der INHALT,
# bei einer Abbildung eine Ergaenzung. Dieselbe Frage fuer beides
# waere fuer einen der Faelle die falsche.
pruef("mit je eigener Frage an das Modell",
      len(set(_gerufen)) == 2, _gerufen)
sys.modules.pop("vision", None)

# --- DER LASTTEST MUSS DIESELBE SPRACHE SPRECHEN WIE DIE SCHNITTSTELLE ---
#
# Er schickte einmal "Authorization: Bearer". Das ist der uebliche Kopf,
# nur liest die Schnittstelle ihn nicht. Herausgekommen ist eine
# vollstaendige Tabelle aus Nullen -- kein Absturz, keine Warnung, nur
# 401 in jeder Zeile. Die Attrappe im Probelauf nahm jeden Kopf an und
# konnte das gar nicht bemerken.
#
# Deshalb wird hier nicht der Aufruf geprueft, sondern der NAME: der
# Parameter von api.benutzer() gegen die Konstante im Lasttest. Wandert
# einer von beiden, faellt es hier auf und nicht erst in einer
# nutzlosen Messung.
import load_test as _lt

_api_quelle = statefiles.open(os.path.join(
    _ROOT, "api.py"),
    encoding="utf-8").read()
_treffer = _re.search(r"def benutzer\(\s*(\w+)\s*:", _api_quelle)
pruef("api.benutzer nimmt den Token-Kopf entgegen", bool(_treffer))
if _treffer:
    # FastAPI leitet aus x_locanoto_token den Kopf X-LocaNoto-Token ab.
    _erwartet = _treffer.group(1).replace("_", "-")
    pruef("der Lasttest schickt genau diesen Kopf",
          _lt.KOPF.lower() == _erwartet.lower(),
          f"{_lt.KOPF} gegen {_erwartet}")

# --- DIE BUDGETGRENZE IST KEINE AUSNAHME, DIE NIEMAND FAENGT ---
#
# budget.Ueberzogen wurde nirgends gefangen. In der Schnittstelle wurde
# daraus HTTP 500, in der Oberflaeche eine rote Rueckverfolgung mitten
# im Chat -- fuer den Benutzer nicht von einem Absturz zu
# unterscheiden. Dabei ist es eine ERWARTETE Grenze mit einer Meldung,
# die sogar sagt, welche Einstellung sie hebt.
_datei_roh = lambda n: statefiles.open(os.path.join(
    _ROOT, n), encoding="utf-8").read()
_datei = _datei_roh


pruef("Ueberzogen wird von einer ValueError-Klausel NICHT gefangen",
      issubclass(budget.Ueberzogen, Exception)
      and not issubclass(budget.Ueberzogen, ValueError))

# Der Fangblock steht unmittelbar hinter dem Aufruf. Weiter zu suchen
# hiesse, einen Block irgendwo anders im Modul als Beleg zu nehmen.
# Auf das ganze Wort pruefen. "budget.Ueberzogen" als blosse
# Teilzeichenkette liesse auch "budget.UeberzogenX" durchgehen -- der
# Gegentest zu dieser Zeile bestand, ohne dass die Klausel noch
# funktioniert haette.

_api = _datei("api.py")
pruef("die Schnittstelle behandelt es eigens",
      bool(_re.search(r"exception_handler\(budget\.Ueberzogen\)", _api)))
pruef("und antwortet mit 429, nicht mit 500",
      "status_code=429" in _api)

# Und der Lasttest darf nicht alles auf ein Konto buchen: das Budget
# zaehlt je Nutzer, ein einziges Token buendelt, was sich auf viele
# Menschen verteilt haette.
pruef("der Lasttest kann mehrere Token reihum verwenden",
      "token[p[0] % len(token)]" in _datei("scripts/load_test.py"))


# --- DAS PACKEN FUER EINEN UMZUG ---
#
# Geprueft wird das Auslassen. Was ableitbar ist, soll NICHT mitkommen:
# der Chroma-Ordner vor allem. Er traegt das Dateiformat der Fassung,
# die ihn geschrieben hat, und die neue muss es nicht lesen koennen --
# deshalb geht der Bestand ueber den Abzug aus .npy und .jsonl, der
# versionsunabhaengig ist.
#
# Kaeme er trotzdem mit, waere der Schaden nicht einmal sichtbar: die
# Dateien laegen im neuen Band, wuerden ignoriert, und niemand
# bemerkte, dass ein halbes Gigabyte Altlast mitgereist ist.
import pack_for_move as _pu
import zipfile as _zip

_alt = os.path.join(tmp, "altinstallation")
for _u in ("chats", "dokumente", "chroma_db", "sicherungen"):
    statefiles.makedirs(os.path.join(_alt, _u), exist_ok=True)
for _p, _inhalt in ((["chats", "a.json"], b"12"),
                    (["dokumente", "b.pdf"], b"345"),
                    (["chroma_db", "chroma.sqlite3"], b"XXXXX"),
                    (["sicherungen", "raum_allgemein.npy"], b"6789"),
                    (["keyword_index.sqlite3"], b"YYY")):
    with statefiles.open(os.path.join(_alt, *_p), "wb") as _f:
        _f.write(_inhalt)

_ziel = os.path.join(tmp, "probe.zip")
_n, _b = _pu.packe(_alt, _ziel, _pu.ABLEITBAR)
_drin = [z.replace("\\", "/") for z in _zip.ZipFile(_ziel).namelist()]
pruef("der Chroma-Ordner bleibt draussen",
      not any("chroma_db" in z for z in _drin), _drin)
pruef("der Stichwortindex auch",
      not any("keyword_index" in z for z in _drin), _drin)
pruef("die Sicherung kommt mit -- sie traegt die Vektoren",
      any("sicherungen/" in z for z in _drin), _drin)
pruef("Chats und Dokumente ebenso",
      any("chats/" in z for z in _drin) and any("dokumente/" in z for z in _drin))
pruef("und gezaehlt wird, was wirklich drin ist", (_n, _b) == (3, 9), (_n, _b))


FAKE_MCP = '''"""Werkzeugserver zum Pruefen -- MCP ueber stdio."""
import json
import sys

WERKZEUGE = [
    {"name": "suche", "description": "Postfach durchsuchen",
     "inputSchema": {"type": "object",
                     "properties": {"frage": {"type": "string"}},
                     "required": ["frage"]}},
    {"name": "lies", "description": "Eine Nachricht lesen",
     "inputSchema": {"type": "object",
                     "properties": {"id": {"type": "string"}}}},
]

for zeile in sys.stdin:
    zeile = zeile.strip()
    if not zeile:
        continue
    try:
        n = json.loads(zeile)
    except ValueError:
        continue
    m = n.get("method")
    if m == "initialize":
        r = {"protocolVersion": "2024-11-05", "capabilities": {}}
    elif m == "tools/list":
        r = {"tools": WERKZEUGE}
    elif m == "tools/call":
        p = n.get("params") or {}
        if p.get("name") == "kaputt":
            r = {"content": [{"type": "text", "text": "geht nicht"}],
                 "isError": True}
        else:
            r = {"content": [
                {"type": "text", "text": "Treffer zu " + json.dumps(
                    p.get("arguments") or {}, sort_keys=True)},
                {"type": "image", "data": "IGNORIEREN"}]}
    else:
        # Mitteilungen bekommen KEINE Antwort.
        continue
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": n.get("id"), "result": r}) + chr(10))
    sys.stdout.flush()
'''

# --- EXCHANGELIB WIRD ERST BEIM ZUGRIFF GELADEN ---
#
# Es wiegt mit lxml und allem Drum und Dran mehr als der Rest der
# Anbindung. Eine Anlage ohne Postfach soll es nie laden.
#
# DIESE PRUEFUNG STEHT GANZ OBEN, vor jedem Import von mcp oder
# postfach. Weiter unten konnte sie genau den Fall nicht melden, fuer
# den sie da ist: mcp.py laedt postfach.py beim Start, und mit einem
# exchangelib-Import oben endet der Selbsttest an einem ImportError,
# bevor irgendeine Pruefung laeuft. Die Gegenprobe sah dann keinen
# Fehlschlag, sondern einen Absturz -- und ein Absturz ist keine
# Meldung. Gelesen wird ohnehin die Datei und nicht das Modul.
import ast as _asti
_pfb = _asti.parse(_datei("postfach.py"))
_pf_oben = {_n.module or "" for _n in _pfb.body
            if isinstance(_n, _asti.ImportFrom)}
_pf_oben |= {_a.name for _n in _pfb.body if isinstance(_n, _asti.Import)
             for _a in _n.names}
pruef("postfach.py laedt exchangelib nicht beim Start",
      not any(_m.startswith("exchangelib") for _m in _pf_oben),
      sorted(_pf_oben))
pruef("aber exchangelib steht in der Abhaengigkeitsliste",
      "exchangelib==" in _datei("requirements.txt"))

import mcp as _mcp

pruef("ohne Konfiguration ist kein Server eingerichtet",
      not _mcp.eingerichtet())

_fake = os.path.join(tmp, "fake_mcp.py")
with statefiles.open(_fake, "w", encoding="utf-8") as _f:
    _f.write(FAKE_MCP)

_mcp.STDIO_ERLAUBT = True      # the test server is a local process
_vb = _mcp.Verbindung("probe", {"transport": "stdio",
                                "befehl": [sys.executable, _fake]})
try:
    _wz = _vb.werkzeuge()
    pruef("die Werkzeuge des Servers kommen an",
          [w["name"] for w in _wz] == ["suche", "lies"],
          [w["name"] for w in _wz])
    pruef("mit Beschreibung und Schema",
          _wz[0]["beschreibung"] and _wz[0]["schema"].get("properties"))

    _erg = _vb.rufe("suche", {"frage": "Rechnung"})
    pruef("ein Werkzeugaufruf liefert Text",
          _erg == 'Treffer zu {"frage": "Rechnung"}', _erg)
    # Bildteile fallen heraus: was ins Sprachmodell geht, ist Text, und
    # ein Bild als Zeichensalat im Prompt waere schlechter als keins.
    pruef("und Bildteile fallen dabei heraus", "IGNORIEREN" not in _erg)

    _fehler = ""
    try:
        _vb.rufe("kaputt")
    except _mcp.Fehler as _e:
        _fehler = str(_e)
    pruef("ein Werkzeugfehler kommt als Fehler an", "geht nicht" in _fehler,
          _fehler)

    # Fuer das Modell: der Servername gehoert in den Werkzeugnamen, sonst
    # laesst sich bei zwei Servern mit gleichem Werkzeug nicht sagen,
    # welches gemeint ist.
    _liste = _mcp.als_werkzeugliste({"probe": _vb})
    pruef("die Werkzeugliste traegt den Servernamen",
          [w["function"]["name"] for w in _liste]
          == ["probe__suche", "probe__lies"],
          [w["function"]["name"] for w in _liste])
    pruef("und laesst sich wieder aufteilen",
          _mcp.teile_namen("probe__suche") == ("probe", "suche"))

    # Ein Server, der nicht antwortet, darf die anderen nicht mitnehmen.
    _tot = _mcp.Verbindung("tot", {"transport": "stdio",
                                   "befehl": [sys.executable, "-c", "pass"]})
    _gemeldet = []
    _liste2 = _mcp.als_werkzeugliste({"tot": _tot, "probe": _vb},
                                     sagen=_gemeldet.append)
    pruef("ein toter Server nimmt die anderen nicht mit",
          [w["function"]["name"] for w in _liste2]
          == ["probe__suche", "probe__lies"],
          [w["function"]["name"] for w in _liste2])
    pruef("und wird dabei gemeldet statt verschwiegen",
          len(_gemeldet) == 1, _gemeldet)
finally:
    _vb.schliesse()


# --- DER WERKZEUGKREIS ---
#
# Das Modell darf nachschlagen, bevor es antwortet. Ein Postfach passt
# nicht in den Zusammenhang, der vorher feststeht: niemand weiss,
# wonach zu suchen ist, bevor die Frage da ist.
import pipeline as _pl


class _FalscheAntwort:
    def __init__(self, inhalt="", rufe=()):
        self.message = types.SimpleNamespace(
            content=inhalt,
            tool_calls=[types.SimpleNamespace(
                id=f"r{i}", function=types.SimpleNamespace(
                    name=n, arguments=json.dumps(a)))
                for i, (n, a) in enumerate(rufe)] or None)


class _FalschesModell:
    """Gibt der Reihe nach vorbereitete Antworten. Zaehlt die Aufrufe."""

    def __init__(self, folge):
        self.folge = list(folge)
        self.aufrufe = 0
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.aufrufe += 1
        a = self.folge.pop(0) if self.folge else _FalscheAntwort("fertig")
        return types.SimpleNamespace(choices=[a])


class _FalscheVerbindung:
    def __init__(self, name, werkzeugnamen):
        self.name = name
        self._w = werkzeugnamen
        self.gerufen = []

    def werkzeuge(self):
        return [{"server": self.name, "name": n, "beschreibung": n,
                 "schema": {"type": "object"}} for n in self._w]

    def rufe(self, name, argumente=None):
        self.gerufen.append((name, argumente))
        return f"Ergebnis von {name}"


# 1. OHNE SERVER PASSIERT NICHTS -- und das wird gezaehlt.
_m = _FalschesModell([])
_zusatz, _entw = _pl.werkzeuglauf(_m, "x", "sys", [], {})
pruef("ohne Server kein Werkzeuglauf", (_zusatz, _entw) == ([], []))
pruef("und vor allem kein Modellaufruf", _m.aufrufe == 0, _m.aufrufe)

# 2. Konfiguration wie im Betrieb: ein persoenliches Postfach ohne
#    Freigabe, ein Funktionspostfach mit.
_mk = os.path.join(paths.CONFIG_DIR, "mcp.json")
with statefiles.open(_mk, "w", encoding="utf-8") as _f:
    json.dump({"mein": {"transport": "http", "url": "http://x",
                        "sendet": ["send_mail"]},
               "info": {"transport": "http", "url": "http://x",
                        "sendet": ["send_mail"], "automatisch": True,
                        "textfeld": "body", "hinweis": "Automatisch."}},
              _f)

# 3. Lesen wird ausgefuehrt, Senden nicht -- im selben Lauf.
_vb = {"mein": _FalscheVerbindung("mein", ["suche", "send_mail"])}
_m = _FalschesModell([
    _FalscheAntwort("", [("mein__suche", {"frage": "Rechnung"}),
                         ("mein__send_mail", {"an": "a@b.c",
                                              "body": "Hallo"})]),
    _FalscheAntwort("fertig")])
_zusatz, _entw = _pl.werkzeuglauf(_m, "x", "sys", [], _vb)
pruef("das Lesewerkzeug wurde ausgefuehrt",
      [n for n, _a in _vb["mein"].gerufen] == ["suche"],
      _vb["mein"].gerufen)
pruef("das Sendewerkzeug NICHT", len(_entw) == 1
      and _entw[0]["werkzeug"] == "send_mail", _entw)
pruef("und der Entwurf traegt die Angaben",
      _entw[0]["argumente"]["an"] == "a@b.c", _entw)

# Das Modell muss ERFAHREN, dass nichts gesendet wurde -- sonst
# schreibt es dem Nutzer, die Nachricht sei unterwegs.
_tools = [z for z in _zusatz if z.get("role") == "tool"]
pruef("das Modell erfaehrt, dass nichts gesendet wurde",
      any("NICHT ausgefuehrt" in z["content"] for z in _tools), _tools)

# 4. Das freigeschaltete Funktionspostfach: vorerst auch nur Entwuerfe
#    (mcp.AUTOMATISCH_SENDEN, Entscheidung 2026-11-12) ...
_vb2 = {"info": _FalscheVerbindung("info", ["send_mail"])}
_zusatz2, _entw2 = _pl.werkzeuglauf(_FalschesModell([
    _FalscheAntwort("", [("info__send_mail", {"an": "a@b.c", "body": "Hallo"})]),
    _FalscheAntwort("fertig")]), "x", "sys", [], _vb2)
pruef("vorerst sendet auch ein freigeschaltetes Postfach nur als Entwurf",
      len(_entw2) == 1 and not _vb2["info"].gerufen, (_entw2, _vb2["info"].gerufen))

# ... und wenn es wieder darf, sendet es -- mit Hinweis.
_mcp.AUTOMATISCH_SENDEN = True
_vb2 = {"info": _FalscheVerbindung("info", ["send_mail"])}
_m = _FalschesModell([
    _FalscheAntwort("", [("info__send_mail", {"an": "a@b.c",
                                              "body": "Hallo"})]),
    _FalscheAntwort("fertig")])
_zusatz2, _entw2 = _pl.werkzeuglauf(_m, "x", "sys", [], _vb2)
_mcp.AUTOMATISCH_SENDEN = False
pruef("das freigeschaltete Postfach sendet ohne Rueckfrage (wenn wieder erlaubt)",
      not _entw2 and len(_vb2["info"].gerufen) == 1, (_entw2, _vb2["info"].gerufen))
pruef("und der Hinweis haengt an der Nachricht",
      "Automatisch." in _vb2["info"].gerufen[0][1]["body"],
      _vb2["info"].gerufen[0][1])

# 5. Der Kreis ist begrenzt. Ein Modell, das immer weiter ruft, darf
#    den Menschen davor nicht endlos warten lassen.
_vb3 = {"mein": _FalscheVerbindung("mein", ["suche"])}
_m = _FalschesModell([_FalscheAntwort("", [("mein__suche", {})])] * 20)
_pl.werkzeuglauf(_m, "x", "sys", [], _vb3)
pruef("der Kreis bricht nach den vorgesehenen Runden ab",
      _m.aufrufe == _pl.WERKZEUG_RUNDEN, (_m.aufrufe, _pl.WERKZEUG_RUNDEN))

statefiles.remove(_mk)

# --- WAS RAUSGEHT, GEHT NICHT ZURUECK ---
#
# Das Modell schlaegt vor, ein Mensch schickt. Ausnahme: ein
# Funktionspostfach, das ausdruecklich freigeschaltet ist -- und dann
# traegt jede Nachricht einen Hinweis, dass sie automatisch entstand.
_mcp_konf = os.path.join(paths.CONFIG_DIR, "mcp.json")
with statefiles.open(_mcp_konf, "w", encoding="utf-8") as _f:
    json.dump({
        "persoenlich": {"transport": "http", "url": "http://x"},
        "info": {"transport": "http", "url": "http://x",
                 "sendet": ["send_mail"], "automatisch": True,
                 "textfeld": "body", "hinweis": "Automatisch erstellt."},
        "ohne_feld": {"transport": "http", "url": "http://x",
                      "sendet": ["send_mail"], "automatisch": True,
                      "textfeld": "gibtsnicht"},
    }, _f)

# Lesen braucht nie eine Bestaetigung -- sonst klickt sich niemand
# durch eine Recherche.
pruef("Lesen laeuft ohne Rueckfrage",
      not _mcp.braucht_bestaetigung("persoenlich", "suche", {"frage": "x"}))

# Das persoenliche Postfach ist nicht freigeschaltet: Entwurf.
pruef("das persoenliche Postfach verlangt eine Bestaetigung",
      _mcp.braucht_bestaetigung("persoenlich", "send_mail",
                                {"body": "Hallo"}))

# Das freigeschaltete Funktionspostfach darf -- und bekommt den Hinweis.
# Vorerst nicht (mcp.AUTOMATISCH_SENDEN aus): auch dort ein Entwurf. Die
# Regeln darunter gelten, sobald es wieder darf.
pruef("vorerst verlangt auch das freigeschaltete Funktionspostfach eine Bestaetigung",
      _mcp.braucht_bestaetigung("info", "send_mail", {"body": "Hallo"}))
_mcp.AUTOMATISCH_SENDEN = True
pruef("ein freigeschaltetes Funktionspostfach darf ohne Rueckfrage (wenn wieder erlaubt)",
      not _mcp.braucht_bestaetigung("info", "send_mail", {"body": "Hallo"}))
_mit = _mcp.mit_hinweis("info", {"an": "a@b.c", "body": "Hallo"})
pruef("und der Hinweis steht am Ende der Nachricht",
      _mit["body"].startswith("Hallo")
      and _mit["body"].rstrip().endswith("Automatisch erstellt."), _mit)
pruef("die uebrigen Angaben bleiben unangetastet",
      _mit["an"] == "a@b.c")

# UND DIE RICHTUNG, IN DIE DER ZWEIFEL FAELLT: ohne Textfeld laesst
# sich der Hinweis nicht anhaengen -- dann wird bestaetigt, auch wenn
# der Schalter an ist. Sonst ginge eine automatische Antwort ohne
# Kennzeichnung hinaus, und genau das soll der Schalter nicht
# bedeuten.
pruef("ohne Textfeld wird trotz Freischaltung bestaetigt",
      _mcp.braucht_bestaetigung("ohne_feld", "send_mail", {"an": "a@b.c"}))
_ja, _grund = _mcp.darf_automatisch("ohne_feld", "send_mail", {"an": "x"})
pruef("und der Grund wird benannt", "Textfeld" in _grund, _grund)

# Die Namensregel greift nur, wo der Betreiber nichts eingetragen hat.
# Sie ist eine Kruecke und darf nur zu VIEL bestaetigen lassen.
pruef("ohne Liste erkennt die Namensregel ein Sendewerkzeug",
      _mcp.sendet("persoenlich", "reply_to_message"))
pruef("und laesst Lesewerkzeuge in Ruhe",
      not _mcp.sendet("persoenlich", "get_message"))
pruef("mit Liste gilt nur die Liste",
      _mcp.sendet("info", "send_mail")
      and not _mcp.sendet("info", "reply_to_message"))

_mcp.AUTOMATISCH_SENDEN = False
statefiles.remove(_mcp_konf)
