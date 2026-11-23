"""Self-test, part 10: Web search, two languages, presets and models, scanned pages, the module map.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- WEBSUCHE ---
#
# Hinaus geht nur der Suchbegriff, herein Text. Erlaubt wird sie in
# geteilten Raeumen vom Verwalter, im eigenen Raum entscheidet der Nutzer.
# Uebernommene Treffer werden Dokumente des Raums.
try:
    import websuche as _ws

    _ws_z_alt = os.environ.get("WEBSUCHE_PORT")
    os.environ["WEBSUCHE_PORT"] = "tcp://10.0.0.7:8000"
    try:
        _ws_port = getattr(_ws, "_zahl", lambda *a, **k: None)(
            "WEBSUCHE_PORT", 8000)
    finally:
        if _ws_z_alt is None:
            os.environ.pop("WEBSUCHE_PORT", None)
        else:
            os.environ["WEBSUCHE_PORT"] = _ws_z_alt
    pruef("eine Service-Variable statt einer Zahl ist kein Absturz",
          _ws_port == 8000, _ws_port)
    pruef("Websuche: Adressen im eigenen Netz gelten nicht als oeffentlich",
          not any(_ws.oeffentlich(h) for h in
                  ("127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.1",
                   "100.64.0.1", "::1", "localhost", "")))
    try:
        _ws.abrufen("http://127.0.0.1:9/geheim")
        _ws_ab = "kein Fehler"
    except _ws.Fehler as e:
        _ws_ab = str(e)
    pruef("und werden nicht abgerufen", "oeffentliche" in _ws_ab, _ws_ab)

    # DNS rebinding: the name answers public first, internal afterwards.
    # The fetch must go to the address that was checked.
    import socket as _so
    _ws_antw = [("93.184.216.34",), ("93.184.216.34",)]
    _ws_echt = _so.getaddrinfo
    _so.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", (
        (_ws_antw.pop(0) if _ws_antw else ("127.0.0.1",))[0], 0))]
    _ws_url = {}

    class _WsClient:
        def stream(self, methode, url, headers=None, extensions=None):
            _ws_url.update(url=url, host=(headers or {}).get("Host"),
                           sni=(extensions or {}).get("sni_hostname"))

            class _A:
                status_code = 200
                headers = {"content-type": "text/plain"}

                def iter_bytes(self):
                    yield b"ok"

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            return _A()
    try:
        _ws.abrufen("https://beispiel.example/x", client=_WsClient())
    finally:
        _so.getaddrinfo = _ws_echt
    pruef("Websuche: geholt wird von der gepruefter Adresse (kein DNS-Rebinding)",
          _ws_url.get("url") == "https://93.184.216.34/x"
          and _ws_url.get("host") == "beispiel.example"
          and _ws_url.get("sni") == "beispiel.example", _ws_url)

    _ws_init = _ws.beantworte({"jsonrpc": "2.0", "id": 1,
                               "method": "initialize", "params": {}})
    _ws_liste = _ws.beantworte({"jsonrpc": "2.0", "id": 2,
                                "method": "tools/list"})
    pruef("der Werkzeugserver spricht MCP: Handschlag und Werkzeuge",
          _ws_init["result"]["capabilities"] == {"tools": {}}
          and sorted(w["name"] for w in _ws_liste["result"]["tools"])
          == ["seite_lesen", "web_suchen"]
          and _ws.beantworte({"jsonrpc": "2.0",
                              "method": "notifications/initialized"}) is None)
    _ws_alt_s = _ws.SEARXNG
    _ws.SEARXNG = ""
    _ws_f = _ws.beantworte({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "web_suchen",
                                       "arguments": {"anfrage": "test"}}})
    _ws.SEARXNG = _ws_alt_s
    pruef("ohne SearXNG ein lesbarer Fehler statt eines Absturzes",
          _ws_f["result"]["isError"]
          and "WEBSUCHE_SEARXNG" in _ws_f["result"]["content"][0]["text"])

    _ws_text = _ws.als_text("pruefplan norm", [
        {"titel": "Norm A", "adresse": "https://a.example/x",
         "ausschnitt": "kurz", "text": "Langer Text\n\nzweiter Absatz"},
        {"titel": "Norm B", "adresse": "https://b.example/y",
         "ausschnitt": "nur Ausschnitt", "text": ""}])
    _ws_z = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "w1", "type": "function",
         "function": {"name": "web__web_suchen", "arguments": "{}"}},
        {"id": "p1", "type": "function",
         "function": {"name": "post__mails_lesen", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "w1", "content": _ws_text},
        {"role": "tool", "tool_call_id": "p1",
         "content": "[W9] Mail\nAdresse: https://x.example\nnein"}]
    _ws_t = pipeline.webtreffer(_ws_z, {"web"})
    pruef("die Treffer kommen als Quellen an, mit Absaetzen, nur von der "
          "Websuche",
          [(t["nr"], t["adresse"]) for t in _ws_t]
          == [("W1", "https://a.example/x"), ("W2", "https://b.example/y")]
          and _ws_t[0]["text"] == "Langer Text\n\nzweiter Absatz"
          and _ws_t[1]["text"] == "nur Ausschnitt"
          and _ws_t[0]["anfrage"] == "pruefplan norm", _ws_t)

    # Erlaubnis am Raum
    raeume.anlegen("webraum", "Webraum", mitglieder=["markus"])
    _ws_vor = raeume.websuche_erlaubt("webraum")
    _ws_ok, _ = raeume.websuche_setzen("webraum", True)
    pruef("in einem geteilten Raum erst nach Freigabe durch den Verwalter",
          not _ws_vor and _ws_ok and raeume.websuche_erlaubt("webraum"))
    pruef("im eigenen Raum ohne Freigabe, und dort nicht abschaltbar",
          raeume.websuche_erlaubt(raeume.privat_kennung("markus"))
          and not raeume.websuche_setzen(raeume.privat_kennung("markus"),
                                         False)[0])
    raeume.websuche_setzen("webraum", False)
    pruef("und wieder sperrbar", not raeume.websuche_erlaubt("webraum"))

    # Der Server in der MCP-Konfiguration: ohne Rueckfrage, aber nur
    # verbunden, wenn der Nutzer sie einschaltet.
    import mcp as _mcp_w
    _ws_ok2, _ = _mcp_w.lege_an("websuche", "websuche",
                                "http://websuche:8000/mcp")
    pruef("die Websuche ist ein eigener Server-Typ",
          _ws_ok2 and _mcp_w.websuche_server() == {"websuche"})
    pruef("sie sucht ohne Rueckfrage -- sie verschickt nichts",
          not _mcp_w.braucht_bestaetigung("websuche", "web_suchen",
                                          {"anfrage": "x"}))
    pruef("ausgeschaltet ist sie gar nicht verbunden",
          "websuche" not in _mcp_w.verbinde(ohne={"websuche"})
          and "websuche" in _mcp_w.verbinde())
    _mcp_w.entferne_postfach("websuche")

    # Uebernehmen: ein Dokument im EIGENEN Raum, mit Quelle oben.
    _ws_n, _ws_h, _ws_name = _auf.webseite_aufnehmen(
        "Druckbehaelter Normen", "https://normen.example/druck",
        "Die Pruefung von Druckbehaeltern regelt die Betriebssicherheit.",
        anfrage="druckbehaelter pruefung", benutzer_="markus")
    _ws_pfad = _auf.dokument_pfad(_ws_name, raeume.privat_kennung("markus"))
    _ws_inh = (statefiles.open(_ws_pfad, encoding="utf-8").read()
               if statefiles.exists(_ws_pfad) else "")
    pruef("ein Treffer wird ein Dokument im Ordner Suchergebnisse",
          _ws_n > 0 and os.sep + _auf.WEB_ORDNER + os.sep in _ws_pfad
          and "- Quelle: https://normen.example/druck" in _ws_inh
          and "- Suchbegriff: druckbehaelter pruefung" in _ws_inh,
          (_ws_n, _ws_h, _ws_pfad))
    # Kein Raum waehlbar, auch nicht fuer Verwalter: ein Klick soll keinen
    # geteilten Raum fuellen. Dorthin nur durch Verschieben.
    import inspect as _insp
    pruef("uebernommen wird immer in den eigenen Raum -- kein Raum waehlbar",
          not {"raum", "ist_verwalter"}
          & set(_insp.signature(_auf.webseite_aufnehmen).parameters))
    _ws_n2, _, _ws_name2 = _auf.webseite_aufnehmen(
        "Anna Treffer", "https://anna.example/x", "Inhalt fuer Anna.",
        benutzer_="anna")
    _ws_pfad2 = _auf.dokument_pfad(_ws_name2, raeume.privat_kennung("anna"))
    pruef("auch fuer jeden anderen Nutzer in dessen eigenen",
          _ws_n2 > 0 and statefiles.exists(_ws_pfad2)
          and not statefiles.exists(_auf.dokument_pfad(_ws_name2,
                                                    raeume.ALLGEMEIN)))

    # Quellensuche: mehr Treffer, noch keine ganzen Seiten.
    class _WsA:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"url": f"https://93.184.215.{n}/s", "title": f"T{n}",
                 "content": "x"} for n in range(1, 13)]}

    class _WsC:
        abrufe = 0

        def get(self, *a, **k):
            return _WsA()

        def stream(self, *a, **k):
            _WsC.abrufe += 1
            raise RuntimeError("nicht abrufen")

    _ws_alt_s = _ws.SEARXNG
    _ws.SEARXNG = "http://searxng.test"
    try:
        _ws_q, _ws_l = _ws.suchen("thema", client=_WsC(), anzahl=10,
                                  lesen=0)
        _ws_l50 = _ws.suchen("thema", client=_WsC(), anzahl=50,
                             lesen=0)[1]
    finally:
        _ws.SEARXNG = _ws_alt_s
    pruef("die Quellensuche liefert so viele Treffer wie verlangt (hoechstens MAX_TREFFER), ohne Seiten zu laden",
          len(_ws_l) == 10 and len(_ws_l50) == min(12, _ws.MAX_TREFFER) and _WsC.abrufe == 0,
          (len(_ws_l), len(_ws_l50), _WsC.abrufe))
    pruef("und ihr Ergebnis liest sich als Trefferliste",
          [t["nr"] for t in pipeline.webtreffer_aus_text(
              _ws.als_text("thema", _ws_l[:2]))] == ["W1", "W2"])
except Exception as e:
    pruef("Websuche laesst sich pruefen", False, f"{type(e).__name__}: {e}")


_k98 = os.path.join(_k8s_oc, "98-websuche.yaml")
if statefiles.exists(_k98):
    _k98q = statefiles.open(_k98, encoding="utf-8").read()
    # Der Pod mit dem Weg ins Netz bekommt nichts von LocaNoto.
    # Kubernetes legt fuer jeden Service Variablen wie
    # WEBSUCHE_PORT=tcp://... in die Pods; SearXNG und websuche.py lesen
    # genau solche Namen.
    pruef("Websuche und SearXNG bekommen keine Service-Variablen",
          _k98q.count("enableServiceLinks: false") == 2)
    pruef("der Websuche-Pod bekommt kein Secret von LocaNoto",
          not any(z.strip().startswith("envFrom")
                  for z in _k98q.splitlines())
          and "kind: NetworkPolicy" in _k98q
          and "searxng/searxng:latest" not in _k98q)
else:
    pruef("es gibt eine k8s-Vorlage fuer die Websuche", False)

# --- ZWEI SPRACHEN ---
#
# Der deutsche Text ist der Schluessel; fehlt eine Uebersetzung, bleibt
# er stehen. Muster tragen eingesetzte Werte. Jeder Nutzer waehlt selbst.
import re
try:
    import sprache as _spr
    import translations as _ueb
    _spr_alt = (_spr.TABELLE, _spr.WAHL)
    _spr_tab = os.path.join(tmp, "sprache_probe.json")
    statefiles.open(_spr_tab, "w", encoding="utf-8").write(json.dumps({
        "texte": {"Gespeichert.": "Saved."},
        "muster": {"{} Dateien in {}": "{1}: {0} files",
                   "Raum {} entfernt": "Room {} removed",
                   "{}": "passt auf alles"}}))
    _spr.TABELLE, _spr.WAHL = _spr_tab, os.path.join(tmp, "sprachen.json")
    _spr._tabelle.cache_clear()
    _spr._englisch.cache_clear()
    try:
        _spr.setze("en")
        pruef("Englisch: fester Text, Muster mit Werten, andere Reihenfolge",
              _spr.t("Gespeichert.") == "Saved."
              and _spr.t("Raum Einkauf entfernt") == "Room Einkauf removed"
              and _spr.t("3 Dateien in Einkauf") == "Einkauf: 3 files",
              (_spr.t("3 Dateien in Einkauf"),))
        pruef("ohne Uebersetzung bleibt der deutsche Text, und ein Muster "
              "nur aus Platzhaltern gilt nicht",
              _spr.t("Voellig unbekannt") == "Voellig unbekannt")
        _spr.setze("de")
        pruef("auf Deutsch wird nichts angefasst",
              _spr.t("Gespeichert.") == "Gespeichert.")
        _spr.setze("xx")
        pruef("eine unbekannte Sprache wird die Vorgabe",
              _spr.aktuell() == _spr.VORGABE)
        _spr.speichere("anna", "en")
        pruef("die Wahl wird je Nutzer gemerkt",
              _spr.gewaehlt("Anna") == "en"
              and _spr.gewaehlt("bernd") == _spr.VORGABE
              and not _spr.speichere("anna", "fr")[0])
    finally:
        _spr.TABELLE, _spr.WAHL = _spr_alt
        _spr._tabelle.cache_clear()
        _spr._englisch.cache_clear()
        _spr.setze("de")

    _spr_echt = json.loads(statefiles.open(os.path.join(
        _ROOT, "sprache_en.json"),
        encoding="utf-8").read())
    _spr_kaputt = []
    for _de_s, _en_s in _spr_echt.get("muster", {}).items():
        _n_s = _de_s.count("{}")
        _num = sorted({int(x) for x in re.findall(r"\{(\d+)\}", _en_s)})
        if (_num != list(range(_n_s)) or "{}" in _en_s) if _num else \
                _en_s.count("{}") != _n_s:
            _spr_kaputt.append(_de_s)
    _spr_kaputt += [k for k, v in _spr_echt.get("texte", {}).items()
                    if not str(v).strip()]
    pruef("jede Uebersetzung hat dieselben Platzhalter und ist nicht leer",
          not _spr_kaputt, _spr_kaputt[:5])
    _spr_fehlt = _ueb.missing_english()
    pruef("jede Meldung, die die Seiten zeigen, hat eine englische Fassung",
          not _spr_fehlt, _spr_fehlt[:5])
    _spr_de = _ueb.missing_german()
    pruef("jeder Text der Seiten hat eine deutsche Fassung",
          _ueb.page_texts() and not _spr_de, _spr_de[:5])
except Exception as e:
    pruef("die Uebersetzung laesst sich pruefen", False,
          f"{type(e).__name__}: {e}")

# --- EIGENE VOREINSTELLUNGEN, ERLAUBTE MODELLE, CHAT-TITEL ---
#
# Jeder legt eigene Voreinstellungen an -- ohne Prompts, die bleiben bei
# den Admins. Ein Modell laesst sich nur aus der freigegebenen Liste
# waehlen. Chat-Titel sind ein kurzer Satz, kein Datum mehr.
try:
    import presets as _pr_e
    import llm as _llm_e
    _pe_alt = _pr_e.NUTZER_ORDNER
    _pr_e.NUTZER_ORDNER = os.path.join(tmp, "presets_nutzer")
    try:
        _pe_ok, _pe_k = _pr_e.eigene_speichern(
            "Anna", "Kurz & knapp", {"chat_modell": "m2", "top_k": 4})
        pruef("ein Nutzer legt eine eigene Voreinstellung an",
              _pe_ok and _pe_k in _pr_e.eigene("anna")
              and _pr_e.lese(_pe_k)["top_k"] == 4
              and _pr_e.anzeige(_pe_k).endswith("(eigene)"), _pe_k)
        pruef("nur er darf sie benutzen und loeschen",
              _pr_e.erlaubt(_pe_k, "anna") and not _pr_e.erlaubt(_pe_k, "bernd")
              and not _pr_e.eigene_loeschen(_pe_k, "bernd")
              and _pe_k in _pr_e.eigene("anna"))
        pruef("eigene Voreinstellungen bringen keine Prompts mit",
              _pr_e.vorlage_pfad(_pe_k, "system_prompt.txt") is None)
        pruef("eine krumme Kennung liest nichts",
              _pr_e.lese("@anna/../../geheim")["top_k"] == 0
              and not _pr_e.erlaubt("@anna/../x", "anna"))
        pruef("und er kann sie wieder loeschen",
              _pr_e.eigene_loeschen(_pe_k, "anna")
              and not _pr_e.eigene("anna"))
    finally:
        _pr_e.NUTZER_ORDNER = _pe_alt

    _cm_alt = (os.environ.get("CHAT_MODELLE"), os.environ.get("CHAT_MODEL"))
    os.environ["CHAT_MODEL"], os.environ["CHAT_MODELLE"] = "a", "b, a ,c"
    try:
        pruef("waehlbar sind CHAT_MODEL und CHAT_MODELLE, CHAT_MODEL zuerst",
              _llm_e.chat_modelle() == ["a", "b", "c"], _llm_e.chat_modelle())
    finally:
        for _n_e, _w_e in zip(("CHAT_MODELLE", "CHAT_MODEL"), _cm_alt):
            if _w_e is None:
                os.environ.pop(_n_e, None)
            else:
                os.environ[_n_e] = _w_e
except Exception as e:
    pruef("Voreinstellungen und Modelle lassen sich pruefen", False,
          f"{type(e).__name__}: {e}")

pruef("die Schnittstelle erlaubt eigene, keine fremden Voreinstellungen",
      "presets.erlaubt(anfrage.preset, kennung)" in _datei("api.py"))

_spr_sys = _datei("system_prompt.txt")
pruef("Antworten kommen in der Sprache der Frage",
      "ANTWORTSPRACHE" in _spr_sys and "[Dateiname, page X]" in _spr_sys
      and "Sprache der Frage" in _datei("search_prompt.txt"))
_hb_de = re.findall(r"^### .*$", _datei("HANDBUCH.md"), re.M)
try:
    _hb_en = re.findall(r"^### .*$", _datei("HANDBUCH.en.md"), re.M)
except OSError:
    _hb_en = []
pruef("das englische Handbuch hat dieselben Abschnitte, jeder nennt LocaNoto",
      len(_hb_de) == len(_hb_en) and all("LocaNoto" in h for h in _hb_en),
      (len(_hb_de), len(_hb_en)))


# --- DIE GRUNDLAGEN SETZT DER VERWALTER, DER NUTZER VERFEINERT ---
#
# Die Vorlagen wirken auf alle Antworten und bleiben beim Verwalter. Jeder
# Nutzer kann eine persoenliche Anweisung hinterlegen, die an SEINE
# Antworten angehaengt wird -- sie ergaenzt die Vorlage, ersetzt sie nicht.
import prompts as _pr_a

# In try: fehlt einem aelteren Stand die Anweisung, soll das als
# Fehlschlag dastehen und nicht den ganzen Lauf beenden.
try:
  _pr_a.anweisung_loeschen("anna")
  pruef("ohne Anweisung bleibt der Antwortprompt die Vorlage",
        pipeline.systemprompt("KONTEXT", benutzer="anna")
        == pipeline.systemprompt("KONTEXT"))
  _ok_a, _m_a = _pr_a.anweisung_speichern("anna", "Antworte immer mit einer Tabelle.")
  _sys_anna = pipeline.systemprompt("KONTEXT", benutzer="anna")
  _sys_markus = pipeline.systemprompt("KONTEXT", benutzer="markus")
  pruef("die Anweisung haengt an den eigenen Antworten",
        _ok_a and "Antworte immer mit einer Tabelle." in _sys_anna, _m_a)
  pruef("und die Vorlage samt Kontext steht davor, unveraendert",
        _sys_anna.startswith(pipeline.systemprompt("KONTEXT").rstrip())
        and "KONTEXT" in _sys_anna)
  pruef("und sie sagt, dass die Regeln der Vorlage vorgehen",
        "gelten die Regeln oben" in _sys_anna)
  # Der ganze Satz und nicht ein Wort daraus: "Tabelle" steht schon in
  # der Vorlage selbst, und die erste Fassung dieser Pruefung fiel daran.
  pruef("die Anweisung eines anderen erscheint nicht",
        "Antworte immer mit einer Tabelle." not in _sys_markus
        and "Persoenliche Anweisung" not in _sys_markus)
  with statefiles.open(_pr_a._anweisung_pfad("anna"), "rb") as _f:
      _roh_a = _f.read()
  pruef("die Anweisung liegt verschluesselt",
        b"Tabelle" not in _roh_a or not geheim.verfuegbar())
  pruef("eine zu lange Anweisung wird abgewiesen",
        not _pr_a.anweisung_speichern("anna", "x" * (_pr_a.ANWEISUNG_MAX + 1))[0]
        and "Tabelle" in _pr_a.anweisung("anna"))
  _pr_a.anweisung_speichern("anna", "")
  pruef("leer speichern entfernt sie",
        _pr_a.anweisung("anna") == ""
        and not statefiles.exists(_pr_a._anweisung_pfad("anna")))
except Exception as e:
  pruef("die persoenliche Anweisung laesst sich pruefen", False,
        f"{type(e).__name__}: {e}")

# Oberflaeche und Schnittstelle geben den Nutzer mit; der Bereich steht
# fuer jeden da, nicht nur fuer Verwalter; und das Loeschen eines
# Benutzers nimmt seine Anweisung mit.
_eltern_a = {}
_nur_vw = []

# --- GESCANNTE SEITEN WERDEN GELESEN ---
#
# Ein Scan hat keine Textebene; vorher endete er in "Kein Text gefunden".
# Jetzt liest ihn die Texterkennung auf jedem Weg, und was sie nicht
# lesen kann, wird genannt und dem Sehmodell angeboten.
#
# Tesseract selbst ist hier eine Attrappe -- ob es im Abbild wirklich
# liest, prueft der Bau-Workflow mit "python ocr.py --probe". Echt ist
# alles drumherum: die gescannte Seite, ihre Erkennung als Scan, das
# Zerteilen, die Meldung, das Sehmodell als zweiter Durchgang, die
# Bilddatei und die Quellenangabe.
import ocr as _ocr_t
import vision as _vis_t
import pymupdf as _pm_t


class _HochBytes:
    def __init__(self, name, daten):
        self.name, self._d = name, daten

    def getvalue(self):
        return self._d


def _scan_pdf(seiten=1):
    _d = _pm_t.open()
    for _ in range(seiten):
        _d.insert_pdf(_ocr_t.probe_dokument())
    return _d.tobytes()


def _quellen_in(raum, name):
    _sml = store.sammlung(raeume.sammlung(raum), anlegen=False)
    if _sml is None:
        return []
    _m = _sml.get(where=store.datei_filter(name),
                  include=["metadatas"]).get("metadatas") or []
    return [m.get("quelle") for m in _m]


_scan_raum = raeume.privat_kennung("markus")
_scan_namen = []
_ocr_alt = (_ocr_t.lies, _vis_t.beschreibe)
# Lang genug, dass eine Seite in mehrere Abschnitte zerfaellt.
_lang = "Die Pruefristen fuer Druckbehaelter betragen zwei Jahre. " * 60

pruef("eine Bildseite gilt als Scan, eine Titelseite nicht",
      _ocr_t.ist_scan(_ocr_t.probe_dokument()[0])
      and not _ocr_t.ist_scan(_pm_t.open().new_page()))
pruef("Zeichensalat gilt nicht als gelesen",
      not _ocr_t.brauchbar("|| -- ~~ :: ;; " * 10) and _ocr_t.brauchbar(_lang))
try:
    # 1. Texterkennung liest -- ohne jeden Schalter.
    _ocr_t.lies = lambda seite: _lang
    _b1 = {}
    _scan_namen.append("scan_ocr.pdf")
    _n1, _h1 = _auf.process_uploaded_pdf(
        _HochBytes("scan_ocr.pdf", _scan_pdf(2)), _scan_raum,
        benutzer_="markus", bericht=_b1)
    pruef("eine gescannte Seite wird ohne Schalter gelesen",
          _b1.get("ocr_seiten") == 2 and not _b1.get("unlesbar") and _n1 > 0,
          (_n1, _b1, _h1))
    pruef("eine lange gelesene Seite wird zerteilt, nicht abgeschnitten",
          _n1 >= 4, _n1)
    pruef("und ihre Abschnitte sind als Texterkennung gekennzeichnet",
          set(_quellen_in(_scan_raum, "scan_ocr.pdf")) == {"ocr"},
          set(_quellen_in(_scan_raum, "scan_ocr.pdf")))

    # 2. Texterkennung liest nichts -- gemeldet, mit Seitenzahl.
    _ocr_t.lies = lambda seite: ""
    _b2 = {}
    _scan_namen.append("scan_leer.pdf")
    _n2, _h2 = _auf.process_uploaded_pdf(
        _HochBytes("scan_leer.pdf", _scan_pdf(1)), _scan_raum,
        benutzer_="markus", bericht=_b2)
    pruef("eine unlesbare Seite wird genannt und dem Sehmodell angeboten",
          _n2 == 0 and _b2.get("unlesbar") == [1]
          and not _b2.get("sehmodell") and "Sehmodell" in _h2, (_b2, _h2))

    # 3. Zweiter Durchgang: das Sehmodell liest genau diese Seite.
    _vis_t.beschreibe = lambda daten, frage="": _lang
    _b3 = {}
    _n3s, _h3 = _auf.process_uploaded_pdf(
        _HochBytes("scan_leer.pdf", _scan_pdf(1)), _scan_raum,
        benutzer_="markus", sehmodell=True, bericht=_b3)
    pruef("das Sehmodell liest, was die Texterkennung nicht las",
          _n3s >= 2 and not _b3.get("unlesbar"), (_n3s, _b3, _h3))
    pruef("und seine Abschnitte sind als Sehmodell gekennzeichnet",
          set(_quellen_in(_scan_raum, "scan_leer.pdf")) == {"sehmodell"},
          set(_quellen_in(_scan_raum, "scan_leer.pdf")))
    pruef("der zweite Durchgang legt die Datei nicht noch einmal ab",
          "Nicht in ownCloud" not in _h3, _h3)

    # 4. Scheitert auch das Sehmodell, faellt die Seite nicht still weg.
    def _kaputt(*a, **k):
        raise RuntimeError("Modell nicht erreichbar")
    _vis_t.beschreibe = _kaputt
    _b4 = {}
    _scan_namen.append("scan_weg.pdf")
    _n4, _h4 = _auf.process_uploaded_pdf(
        _HochBytes("scan_weg.pdf", _scan_pdf(1)), _scan_raum,
        benutzer_="markus", sehmodell=True, bericht=_b4)
    pruef("scheitert auch das Sehmodell, wird die Seite genannt",
          _b4.get("unlesbar") == [1]
          and "auch nicht mit dem Sehmodell" in _h4, (_b4, _h4))

    # 5. Ein Scan als Bilddatei.
    _ocr_t.lies = lambda seite: _lang
    _png = _ocr_t.probe_dokument()[0].get_pixmap(dpi=100).tobytes("png")
    _b5 = {}
    _scan_namen.append("scan_bild.png")
    _n5, _h5 = _auf.process_uploaded_pdf(
        _HochBytes("scan_bild.png", _png), _scan_raum,
        benutzer_="markus", bericht=_b5)
    pruef("ein Scan als PNG wird angenommen und gelesen",
          _n5 > 0 and _b5.get("ocr_seiten") == 1, (_n5, _b5, _h5))

    # 6. Eine Seite ohne Bild ist kein Scan und wird nicht gemeldet.
    _titel = _pm_t.open()
    _titel.new_page().insert_text((60, 100), "Anhang A", fontsize=20)
    _b6 = {}
    _scan_namen.append("titel.pdf")
    _auf.process_uploaded_pdf(_HochBytes("titel.pdf", _titel.tobytes()),
                              _scan_raum, benutzer_="markus", bericht=_b6)
    pruef("eine Titelseite gilt nicht als unlesbarer Scan",
          _b6.get("unlesbar") == [], _b6)
except Exception as e:
    pruef("gescannte Seiten lassen sich pruefen", False,
          f"{type(e).__name__}: {e}")
finally:
    _ocr_t.lies, _vis_t.beschreibe = _ocr_alt
    _sml_s = store.sammlung(raeume.sammlung(_scan_raum), anlegen=False)
    for _nm in _scan_namen:
        try:
            if _sml_s is not None:
                _sml_s.delete(where=store.datei_filter(_nm))
            keyword_index.delete_document(_nm, raum=_scan_raum)
        except Exception:
            pass

_q_t = pipeline.quellen([{"meta": {"file_name": "a.pdf", "page": 1,
                                   "raum": "x", "quelle": "ocr"},
                          "text": "t"}])
pruef("die Quellenangabe nennt die Texterkennung",
      _q_t and _q_t[0].get("herkunft") == "ocr", _q_t)
pruef("und das Modell erfaehrt es im Kontext",
      'herkunft="texterkennung"' in pipeline.kontext(
          [{"meta": {"file_name": "a.pdf", "page": 1, "quelle": "ocr"},
            "text": "t"}]))
pruef("das Abbild bringt Deutsch und Englisch fuer die Texterkennung mit",
      "tesseract-ocr-deu" in _datei("Dockerfile")
      and "tesseract-ocr-eng" in _datei("Dockerfile"))
pruef("und der Bau prueft, dass sie im Abbild wirklich liest",
      "ocr.py --probe" in _datei(".github/workflows/abbild.yml"))
pruef("Bilddateien gehoeren zu den Dokumenten, auch fuer Ingest und "
      "ownCloud", all(e in paths.DOKUMENT_ENDUNGEN
                      for e in (".tif", ".tiff", ".jpg", ".png")))
# Das Aufraeumen des OCR-Texts aendert keine Ziffer -- das ist die
# Bedingung, unter der es ueberhaupt stattfinden darf.
import re as _re_o
_proben_o = [
    ("Der Druck-\nbeh\u00e4lter wird gepr\u00fcft.", "Druckbeh\u00e4lter"),
    ("Ein- \nund Ausgang", "Ein- und Ausgang"),
    ("nach DIN-\nNorm 13445", "DIN-Norm 13445"),
    ("Seiten 13-\n45 bei 1,6 bar", "13-45 bei 1,6 bar"),
    ("\ufb01nden der \ufb02ansche", "finden der flansche"),
    ("in m\u00b2 und \u00bd Zoll, 2,5\u00adfach", "m\u00b2 und \u00bd Zoll, 2,5fach"),
]
_falsch_o = []
for _ein, _soll in _proben_o:
    try:
        _aus = _ocr_t.aufraeumen(_ein)
    except Exception as e:
        _falsch_o.append((_ein, f"{type(e).__name__}: {e}"))
        continue
    if _soll not in _aus or _re_o.findall(r"\d", _ein) != _re_o.findall(r"\d", _aus):
        _falsch_o.append((_ein, _aus))
pruef("Aufraeumen fuegt Trennungen zusammen und aendert keine Ziffer",
      not _falsch_o, _falsch_o)
import inspect as _insp_o
pruef("und die Texterkennung raeumt jede Seite so auf",
      "aufraeumen(" in _insp_o.getsource(_ocr_t.lies))
pruef("die Antwortvorlage warnt vor Werten aus gelesenen Scans",
      'herkunft="texterkennung"' in _datei("system_prompt.txt")
      and "GELESENE SCANS" in _datei("system_prompt.txt"))

pruef("ingest.py liest gescannte Seiten ebenfalls",
      "ocr.ist_scan(page)" in _datei("ingest.py")
      and "ocr.oeffne(pdf_pfad)" in _datei("ingest.py"))

import module_map as _lk

_HIER = _ROOT
_karte = _lk.lies(_HIER)

# 1. Jede Datei hat genau eine Schicht. Eine neue faellt damit auf,
#    statt still aus der Uebersicht zu fallen -- der haeufigste Weg,
#    wie so etwas veraltet.
_ohne = sorted(n for n, i in _karte.items() if i["schicht"] == "?")
pruef("jede Datei steht in genau einer Schicht der Landkarte",
      not _ohne, _ohne)

# 2. Keine Kante zeigt nach oben. Daran haengt die Wartbarkeit: wer
#    paths.py aendert, muss nichts ueber die Oberflaeche wissen. Beim
#    Aufschreiben war es einmal verletzt -- pipeline benutzte mcp, und
#    mcp stand unter den Einstiegen. Der Code war richtig, die
#    Einteilung falsch.
_RANG = {s: i for i, s in enumerate(_lk.RANG)}
_hoch = sorted(f"{n} -> {m}" for n, i in _karte.items() for m in i["nutzt"]
               if _RANG[_karte[m]["schicht"]] > _RANG[i["schicht"]])
pruef("keine Kante der Landkarte zeigt nach oben", not _hoch, _hoch)

# 3. Jede Datei steht in der REFERENZ.md. Die Tabelle wird erzeugt; diese
#    Pruefung stellt sicher, dass sie nach einer neuen Datei auch
#    erneuert wurde.
_liesmich = _datei("REFERENZ.md")
_fehlt_doku = sorted(n for n in _karte if f"`{n}.py`" not in _liesmich)
pruef("jede Datei kommt in der Landkarte der REFERENZ.md vor",
      not _fehlt_doku, _fehlt_doku)

# 4. Jede Datei sagt in einem Satz, was sie tut. Ohne Dateikopf bleibt
#    die Zelle leer.
_stumm = sorted(n for n, i in _karte.items() if not i["kopf"].strip())
pruef("jede Datei sagt in ihrem Kopf, was sie tut", not _stumm, _stumm)
