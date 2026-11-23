"""Self-test, part 04: Prompt rules, ranking, adding a document, search paths that fail.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- DIE SCHWELLE MUSS UEBER EINER STUNDE HANDARBEIT LIEGEN ---
#
# Sonst trifft sie den fleissigen Menschen statt den Abzug, und genau
# das ist passiert: 4.000 klang grosszuegig, war aber bei den
# tatsaechlichen Kosten einer Frage nach 37 Fragen aufgebraucht.
#
# Geprueft wird deshalb nicht die Zahl, sondern das Verhaeltnis. Die
# Kosten kommen aus derselben Formel wie in pipeline.suche, die
# Stundenleistung aus der gemessenen Antwortzeit. Wird TOP_K erhoeht
# oder eine vierte Sonde eingebaut, faellt es hier auf.
_JE_FRAGE = 3 * max(10, paths.env_int("TOP_K", 5) * 3)   # Sonden x Kandidaten
_SEKUNDEN_JE_ANTWORT = 35                                 # gemessen
_PRO_STUNDE = 3600 // _SEKUNDEN_JE_ANTWORT                # ohne Lesen, ohne Denken
pruef("die Budgetschwelle liegt ueber einer Stunde ununterbrochenen Fragens",
      _BUDGET_EINGESTELLT >= _JE_FRAGE * _PRO_STUNDE,
      f"{_BUDGET_EINGESTELLT} gegen {_JE_FRAGE * _PRO_STUNDE} "
      f"({_PRO_STUNDE} Fragen x {_JE_FRAGE})")

# --- DIE REGELN DES SYSTEMPROMPTS SIND DURCHNUMMERIERT ---
#
# Im mitgelieferten Prompt trugen "DATENBANKWERTE" und "CODE" beide die
# 7, und eine 10 gab es nicht -- beim Anfuegen der letzten Regel wurde
# die Nummer der vorletzten abgeschrieben.
#
# Ob ein Modell darueber stolpert, laesst sich hier nicht messen. Dass
# eine durchnummerierte Liste zweimal dieselbe Nummer traegt, schon.
_prompt = _datei("system_prompt.txt")
_nummern = [int(m) for m in _re.findall(r"^(\d+)\.", _prompt, _re.M)]
pruef("die Regeln des Systemprompts sind fortlaufend nummeriert",
      _nummern == list(range(1, len(_nummern) + 1)), _nummern)

# --- DIE ERSTE FRAGE NACH EINEM START BEKOMMT AUCH DIE RANGFOLGE ---
#
# _endpunkt_dran() prueft allein _ausfall_zeit, und lade_bewerter setzt
# die VOR dem Start der Probe. Solange sie lief, fiel jeder Aufruf in
# den elif-Zweig und lieferte None -- die ersten Fragen nach jedem
# Neustart bekamen also die Fusionsreihenfolge, ohne dass etwas
# fehlgeschlagen waere.
#
# Jetzt wird kurz gewartet, begrenzt, und nur solange die STARTPROBE
# laeuft. Gemessen wird das Warten, nicht gelesen.
import threading as _th
import time as _zeit
import ranking as _rk2

_rk2.RERANKER_PROBE_WARTEN = 0.6
# _endpunkt_dran() haengt auch an der Adresse. Im Testbestand steht
# keine; ohne sie waere die Antwort immer False und die Pruefung
# wertlos. Gerufen wird sie nicht -- die Probe ist hier ein eigener
# Faden, der nur schlaeft.
_rk2_url_vorher = _rk2.RERANKER_BASE_URL
_rk2.RERANKER_BASE_URL = "http://beispiel.invalid"


def _mit_probe(dauer, erfolg=True):
    """Ein Bewerter, dessen Startprobe `dauer` Sekunden braucht."""
    b = _rk2.Bewerter()
    b._ausfall_zeit = _zeit.time() - 999
    b._ausfall_grund = "Probe laeuft noch"
    b.startprobe = "Probe beim Start laeuft"

    def klopfen():
        _zeit.sleep(dauer)
        if erfolg:
            b._ausfall_zeit = None
            b._ausfall_grund = ""
            b.startprobe = None

    b._weck_faden = _th.Thread(target=klopfen, daemon=True)
    b._weck_faden.start()
    return b


# 1. Kurze Probe: es wird gewartet, und danach ist der Endpunkt dran.
_b1 = _mit_probe(0.2)
_t0 = _zeit.time()
_b1._probe_abwarten()
_d1 = _zeit.time() - _t0
# Untergrenze: es wurde mindestens bis zum Ende der Probe gewartet.
# Obergrenze grosszuegig -- sie wacht nur ueber ein haengendes
# join, nicht ueber die Genauigkeit der Uhr.
pruef("die erste Bewertung wartet auf eine laufende Startprobe",
      0.15 < _d1 < 3.0, f"{_d1:.2f}s")
# Fuer den ZUSTAND wird der Faden abgewartet, statt auf die Uhr zu
# bauen: _probe_abwarten wartet hoechstens RERANKER_PROBE_WARTEN
# Sekunden, und auf einer belasteten Maschine kommt der Probenfaden in
# dieser Zeit womoeglich nicht zum Zug. Die Pruefung meldete dann einen
# Fehlschlag, der keiner war -- etwa einmal in fuenfzehn Laeufen.
_b1._weck_faden.join(10)
pruef("und geht danach ueber den Endpunkt",
      _b1._endpunkt_dran(), _b1._lage())

# 2. Lange Probe: das Warten ist begrenzt. Ein kalter Modellserver darf
#    die Frage nicht dreissig Sekunden aufhalten -- genau dagegen war
#    die Probe urspruenglich in den Hintergrund gelegt worden.
_b2 = _mit_probe(5.0)
_t0 = _zeit.time()
_b2._probe_abwarten()
_d2 = _zeit.time() - _t0
# Die Eigenschaft ist relativ: zurueckgekehrt wird DEUTLICH frueher,
# als die Probe dauert (5 s). Eine feste Obergrenze in Zehnteln
# prueft die Auslastung der Maschine, nicht den Code -- ein Lauf
# meldete deshalb einmal einen Fehlschlag, der keiner war.
pruef("laenger als eingestellt wird nicht gewartet",
      _d2 < 5.0 / 2, f"{_d2:.2f}s bei Probe 5.0s, Grenze 0.6s")
pruef("und dann laeuft die Frage ueber die Fusion",
      not _b2._endpunkt_dran())

# 3. UND DER FALL, AN DEM SO ETWAS SONST SCHEITERT: bei einem echten
#    Ausfall wartet niemand. Dort ist bereits bekannt, dass der Dienst
#    nicht antwortet; zwei Sekunden je Frage waeren reine Wartezeit.
_b3 = _mit_probe(5.0)
_b3.startprobe = None                      # kein Start mehr, ein Ausfall
_b3._ausfall_grund = "ConnectError: keine Verbindung"
_t0 = _zeit.time()
_b3._probe_abwarten()
_d3 = _zeit.time() - _t0
pruef("bei einem echten Ausfall wartet niemand", _d3 < 0.5,
      f"{_d3:.2f}s bei Probe 5.0s")

# 4. Abschaltbar.
_rk2.RERANKER_PROBE_WARTEN = 0
_b4 = _mit_probe(5.0)
_t0 = _zeit.time()
_b4._probe_abwarten()
pruef("mit 0 wird gar nicht gewartet", _zeit.time() - _t0 < 0.5)

# UND DER BEWERTER BENUTZT ES AUCH. Ohne diese Pruefung koennte das
# Warten tadellos sein und nie stattfinden -- die Gegenprobe "Aufruf
# entfernen" lief genau deshalb einmal durch. Gesucht wird im
# Syntaxbaum von __call__ und nicht im Text der Datei: ein Vorkommen im
# Dateikopf waere sonst schon ein Beweis.
_rk_baum = _ast.parse(_datei("ranking.py"))
_bew_klasse = next(k for k in _rk_baum.body
                   if isinstance(k, _ast.ClassDef) and k.name == "Bewerter")
_ruf = next(k for k in _bew_klasse.body
            if isinstance(k, _ast.FunctionDef) and k.name == "__call__")
_gerufen = {_ast.unparse(k.func) for k in _ast.walk(_ruf)
            if isinstance(k, _ast.Call)}
pruef("und die Bewertung ruft das Warten auch auf",
      "self._probe_abwarten" in _gerufen, sorted(_gerufen)[:6])
_rk2.RERANKER_PROBE_WARTEN = 2.0
_rk2.RERANKER_BASE_URL = _rk2_url_vorher

# --- EINE LAUFENDE PROBE IST KEIN AUSFALL ---
#
# Gemeldet: "Endpunkt ... AUSGEFALLEN (Probe laeuft noch)". Nichts war
# ausgefallen -- die Startprobe war nur nicht zurueck, und kurz darauf
# bewertete derselbe Bewerter ueber den Endpunkt. Wer das liest, sucht
# einen Fehler, den es nicht gibt.
import ranking as _rk

_bw2 = _rk.Bewerter()
_bw2._ausfall_zeit = 1.0
_bw2._ausfall_grund = "Probe laeuft noch"
_bw2.startprobe = "Probe beim Start laeuft"
_alt_url = _rk.RERANKER_BASE_URL
_rk.RERANKER_BASE_URL = "http://beispiel.invalid"
try:
    _waehrend = _bw2._lage()
    _bw2.startprobe = None
    _bw2._ausfall_grund = "ConnectError: keine Verbindung"
    _danach = _bw2._lage()
finally:
    _rk.RERANKER_BASE_URL = _alt_url
pruef("eine laufende Startprobe heisst nicht AUSGEFALLEN",
      "AUSGEFALLEN" not in _waehrend and "Probe" in _waehrend, _waehrend)
pruef("ein echter Ausfall heisst weiterhin so",
      "AUSGEFALLEN" in _danach, _danach)

# --- DER PROMPT SAGT AUCH, WANN ETWAS BENUTZT WERDEN MUSS ---
#
# Gemeldet: die Antwort lautete "dazu steht nichts in der Unterlage",
# waehrend die Fundstelle in ihrer eigenen Quellenliste stand. Die
# Leitung war in Ordnung -- kontext() nimmt jeden Treffer --, aber der
# Prompt kannte nur eine Richtung: drei Regeln bremsen gegen Erfindung,
# keine sagt, dass ein passender Abschnitt benutzt werden MUSS. Bei
# einem Bestand, in dem zwei Produkte dieselben Begriffe fuehren, faellt
# die Antwort dann auf die sichere Seite.
pruef("der Prompt verlangt, Gefundenes auch zu benutzen",
      "GEFUNDENES ZAEHLT" in _prompt)

# --- DER BEWERTER SAGT, WAS ZULETZT GESCHEHEN IST ---
#
# Die Anzeige zeigte, was GILT: Endpunkt eingerichtet, kein Ausfall
# vermerkt. Nicht, was beim letzten Bewerten geschah. Gefragt wurde
# genau das: "laut Anzeige haengt der Reranker am Endpunkt, aber
# dort entsteht keine Last." Das Feld dafuer gab es seit jeher --
# gelesen hat es niemand.
import ranking as _rk

_bw = _rk.Bewerter()
pruef("vor der ersten Bewertung sagt er das auch",
      "noch nicht bewertet" in _bw.beschreibung(), _bw.beschreibung())

_bw._zuletzt_endpunkt = True
pruef("nach einer Bewertung ueber den Endpunkt steht es da",
      "zuletzt: Endpunkt" in _bw.beschreibung(), _bw.beschreibung())

_bw._zuletzt_endpunkt = False
pruef("und sonst steht da, was stattdessen entschieden hat",
      "zuletzt: nur Rangfolge-Fusion" in _bw.beschreibung(),
      _bw.beschreibung())

_bw._modell = object()
pruef("das Modell aus dem Image wird als solches genannt",
      "zuletzt: Modell aus dem Image" in _bw.beschreibung(),
      _bw.beschreibung())

# --- EIN DOKUMENT AUFNEHMEN ---
#
# Ausgefuehrt und nicht nur gelesen.
#
# Attrappe ist nur das Embedding. Sammlungen, Stichwortindex und
# Rechtepruefung sind echt.
import aufnehmen as _auf

_auf.embed_batch = lambda client, texte, modell: [vek() for _ in texte]


class _Hochgeladene:
    """Name und Bytes -- mehr braucht die Funktion nicht."""

    def __init__(self, name, text):
        self.name = name
        self._t = text.encode("utf-8")

    def getvalue(self):
        return self._t


_TEXT = ("# Pruefplan\n\nDie Pruefristen fuer Druckbehaelter betragen "
         "zwei Jahre und werden vom Betreiber veranlasst.\n")

# 1. In den eigenen Raum -- das darf jeder, ohne Verwalterrolle.
_auffrischungen = []
_eigen = raeume.privat_kennung("markus")
_n, _hinweis = _auf.process_uploaded_pdf(
    _Hochgeladene("Pruefplan.md", _TEXT), _eigen,
    benutzer_="markus", ist_verwalter=False,
    nach_dem_schreiben=lambda: _auffrischungen.append(1))
pruef("ein Dokument wird aufgenommen", _n > 0, (_n, _hinweis))
pruef("und das Auffrischen wird gemeldet", _auffrischungen == [1])

_sml = store.sammlung(raeume.sammlung(_eigen), anlegen=False)
pruef("die Abschnitte liegen in der Sammlung des Raums",
      _sml is not None and _sml.count() >= _n, _sml.count() if _sml else 0)
_kw = keyword_index.search("Druckbehaelter", "markus", limit=5)
pruef("und der Stichwortindex findet sie",
      any(t["meta"]["file_name"] == "Pruefplan.md" for t in _kw),
      [t["meta"]["file_name"] for t in _kw])

# 2. Der allgemeine Raum ist fuer Verwalter. Das ist keine Kosmetik:
#    der gemeinsame Bestand ist das, worauf sich alle verlassen.
try:
    _auf.process_uploaded_pdf(
        _Hochgeladene("Fremd.md", _TEXT), raeume.ALLGEMEIN,
        benutzer_="anna", ist_verwalter=False, streng=True)
    _abgewiesen = False
except _auf.KeinRecht:
    _abgewiesen = True
pruef("streng weist ab, wer nicht schreiben darf", _abgewiesen)

# 3. Und ohne streng wird umgeleitet statt abgewiesen -- so verhaelt
#    sich die Oberflaeche, wo man sieht, wo etwas gelandet ist.
_vor_allg = store.sammlung(raeume.sammlung(raeume.ALLGEMEIN),
                           anlegen=False).count()
_n2, _ = _auf.process_uploaded_pdf(
    _Hochgeladene("Umgeleitet.md", _TEXT), raeume.ALLGEMEIN,
    benutzer_="anna", ist_verwalter=False)
_nach_allg = store.sammlung(raeume.sammlung(raeume.ALLGEMEIN),
                            anlegen=False).count()
# Gefragt wird der Stichwortindex und nicht Chroma: er kennt den
# Raum je Abschnitt, und er wird ohnehin mitgeschrieben. Eine
# Annahme ueber die Rueckgabeform von Chroma weniger.
_umg = keyword_index.search("Druckbehaelter", "anna", limit=20)
_umg_raeume = {t["meta"]["raum"] for t in _umg
               if t["meta"]["file_name"] == "Umgeleitet.md"}
pruef("ohne streng wird in den eigenen Raum umgeleitet",
      _n2 > 0 and _nach_allg == _vor_allg
      and _umg_raeume == {raeume.privat_kennung("anna")},
      (_n2, _vor_allg, _nach_allg, sorted(_umg_raeume)))

# 4. Ein Verwalter darf in den allgemeinen Raum.
_n3, _ = _auf.process_uploaded_pdf(
    _Hochgeladene("Gemeinsam.md", _TEXT), raeume.ALLGEMEIN,
    benutzer_="markus", ist_verwalter=True, streng=True)
pruef("ein Verwalter darf in den allgemeinen Raum", _n3 > 0, _n3)

# 6. Und beide Eingaenge nehmen denselben Weg. Zwei Ingestwege, von
#    denen einer nachgezogen wird und der andere nicht, waeren der
#    Anfang davon, dass ein Dokument je nach Eingang anders im Bestand
#    liegt.
pruef("und die Schnittstelle weist ab, statt umzuleiten",
      "streng=True" in _datei("api.py")
      and "status_code=403" in _datei("api.py"))


# --- DIE BILDBESCHREIBUNG LIEST AUCH FORMELN ---
#
# Es gab einmal update_formulas.py, einen eigenen Lauf fuer Bilder mit
# Formeln. Das Skript ist weg, und das war richtig -- die
# Bildbeschreibung tut dasselbe beim Einlesen. Nur nannte ihre Aufgabe
# Formeln mit keinem Wort: sie fragte nach Diagrammen, Achsen, Tabellen
# und Fotos. Eine freigestellte Formel bekam damit eine Beschreibung
# ihrer Geometrie statt ihres Inhalts, und in einem Regelwerksbestand
# ist genau die Formel das, wonach jemand sucht.
#
# Zwei Wege, zwei Aufgaben: der Stapellauf und das, was beim Hochladen
# mitkommt. Beide muessen es verlangen.
for _datei_name in ("ingest_images.py", "bildtext.py"):
    _q = _datei(_datei_name)
    pruef(f"{_datei_name} verlangt Formeln",
          "Formel" in _q and ("Gleichung" in _q or "Einheit" in _q))

# --- EIN AUSGEFALLENER SUCHWEG VERSCHWINDET NICHT ---
#
# Im Betrieb lagen die Vektoren einer Installation mit 2560
# Dimensionen, waehrend das Modell 4096 liefert. Jede Vektorabfrage warf
# InvalidArgumentError -- und wurde von "except Exception: continue"
# verschluckt. Die Antworten kamen weiter, getragen allein vom
# Stichwortindex, sauber formuliert und mit richtigen Fundstellen. Von
# aussen sah die Anlage gesund aus. Seit dem Umzug.
#
# Hier wird genau das erzeugt: eine Sammlung mit anderer Dimension als
# die Anfrage. Die Suche darf weiterlaufen -- das war die richtige
# Absicht -- aber nicht mehr schweigen.
_falscher_raum = "dimensionsprobe"
raeume.anlegen(_falscher_raum, "Dimensionsprobe", mitglieder=["markus"])
_falsche_sml = store.sammlung(raeume.sammlung(_falscher_raum))
if database.active():
    # Postgres holds one dimension for all vectors; a longer query vector
    # is shortened (Matryoshka). What still breaks is a shorter one -- a
    # smaller embedding model behind the same name.
    _ANDERE_DIM = DIM // 2
    _gespeichert = [vek()]

    class _DimEmb:
        class embeddings:
            @staticmethod
            def create(input, model, timeout=None, encoding_format=None,
                       extra_body=None):
                return types.SimpleNamespace(data=[
                    types.SimpleNamespace(index=i, embedding=[0.5] * _ANDERE_DIM)
                    for i in range(len(input))])
    _dim_emb = _DimEmb()
else:
    _ANDERE_DIM = DIM * 2
    _gespeichert = [[0.5] * _ANDERE_DIM]
    _dim_emb = FakeEmb()
store.schreibe(_falsche_sml, ["fremd_p1_c0"],
               documents=["Ein Abschnitt mit fremder Dimension."],
               metadatas=[{"file_name": "Fremd.pdf", "page": 1,
                           "raum": _falscher_raum, "type": "text"}],
               embeddings=_gespeichert)

_treffer_d, _zahlen_d = pipeline.suche(
    [(_falscher_raum, _falsche_sml)], _dim_emb, "modell",
    ["Dimension"], "markus", 5, bewerter=bewerter)

pruef("ein Suchweg mit falscher Dimension wird gemeldet",
      _falscher_raum in (_zahlen_d.get("vektorausfall") or {}),
      _zahlen_d.get("vektorausfall"))
pruef("und der Grund steht dabei",
      "dimension" in str(_zahlen_d.get("vektorausfall", {})).lower(),
      _zahlen_d.get("vektorausfall"))

# Und die Suche laeuft trotzdem: ein Raum, der nicht antwortet, darf die
# anderen nicht mitreissen. Das war und bleibt richtig.
#
# Gefragt wird ausdruecklich der bekannte Bestand und nicht "alles, was
# markus sieht" -- der Probenraum von eben gehoert ihm auch, und die
# Pruefung haette den Ausfall gemeldet, den sie selbst angelegt hat.
_gesunde = [(raeume.ALLGEMEIN,
             store.sammlung(raeume.sammlung(raeume.ALLGEMEIN),
                            anlegen=False))]
_treffer_ok, _zahlen_ok = pipeline.suche(
    _gesunde, FakeEmb(), "modell",
    ["Pruefristen Kessel"], "markus", 5, bewerter=bewerter)
pruef("ein gesunder Bestand meldet keinen Ausfall",
      not _zahlen_ok.get("vektorausfall"), _zahlen_ok.get("vektorausfall"))

# DIE BESTANDSLISTE NENNT DIE DIMENSION. Sie wird vor und nach jedem
# Rollout gefahren und zaehlte nur Abschnitte -- die Zahl stimmte an
# jedem Punkt, waehrend die Vektoren unbrauchbar waren.
import inventory as _bl

pruef("die Bestandsliste liest die Dimension einer Sammlung",
      _bl._dimension(_falsche_sml) == len(_gespeichert[0]),
      _bl._dimension(_falsche_sml))
pruef("und die des gewachsenen Bestands",
      _bl._dimension(store.sammlung(raeume.sammlung(raeume.ALLGEMEIN),
                                    anlegen=False)) == DIM)

raeume.entfernen(_falscher_raum)

# EIN NOCH NICHT ABGELEGTES SEGMENT IST KEIN AUSFALL. Chroma legt das
# Vektorsegment einer frisch beschriebenen Sammlung verzoegert ab; wer
# vorher fragt, bekommt "Nothing found on disk". Einmal ist das im
# Selbsttest selbst aufgetreten -- als Ausfall des gesunden Bestands.
# Im Betrieb trifft es den ersten Upload in einen neuen Raum.
#
# Nachgestellt mit einer Sammlung, deren erste Abfrage genau so
# scheitert. Neu verbunden wird hier nicht wirklich: das prueft
# Abschnitt 9, und ein echter Neuaufbau mitten im Lauf liesse die
# Handles der Pruefungen danach veralten.
from chromadb.errors import InternalError as _InternalError


class _SpaetesSegment:
    """Eine Sammlung, deren erste Abfragen mit den gegebenen Fehlern
    scheitern. Danach antwortet sie leer."""

    def __init__(self, *fehler):
        self.fehler = list(fehler)
        self.abfragen = 0

    def query(self, **kw):
        self.abfragen += 1
        if self.fehler:
            raise self.fehler.pop(0)
        leer = [[] for _ in kw["query_embeddings"]]
        return {"documents": leer, "metadatas": leer, "distances": leer}


def _segment_fehler():
    return _InternalError("Error executing plan: Internal error: Error "
                          "creating hnsw segment reader: Nothing found "
                          "on disk")


_echt_neu_verbinden = store.neu_verbinden
_neu_verbunden = []
store.neu_verbinden = lambda: _neu_verbunden.append(1) or True
try:
    # Ein Raum ohne Sammlung: nach dem Neuverbinden findet store.frage
    # keine frische und bleibt bei der nachgestellten.
    _spaet = _SpaetesSegment(_segment_fehler())
    _listen_s, _ausfall_s = pipeline._vektortreffer(
        [("segmentprobe", _spaet)], [vek()], 5, None, "markus")
    pruef("ein noch nicht abgelegtes Segment meldet keinen Ausfall",
          not _ausfall_s, _ausfall_s)
    pruef("sondern die Abfrage wird nach Neuverbinden wiederholt",
          _spaet.abfragen == 2 and _neu_verbunden,
          (_spaet.abfragen, len(_neu_verbunden)))

    # Andere Fehler werden nicht wiederholt: eine falsche Dimension ist
    # beim zweiten Mal genauso falsch und muss gemeldet werden.
    _dim = _SpaetesSegment(_InternalError(
        "Collection expecting embedding with dimension of 2560, got 4096"))
    _listen_d2, _ausfall_d2 = pipeline._vektortreffer(
        [("segmentprobe", _dim)], [vek()], 5, None, "markus")
    pruef("ein anderer Fehler wird nicht wiederholt, sondern gemeldet",
          _dim.abfragen == 1 and "segmentprobe" in _ausfall_d2,
          (_dim.abfragen, _ausfall_d2))

    # Und die Wiederholung hat ein Ende: bleibt das Segment weg, ist es
    # doch ein Ausfall.
    _weg = _SpaetesSegment(*[_segment_fehler() for _ in range(10)])
    _listen_w, _ausfall_w = pipeline._vektortreffer(
        [("segmentprobe", _weg)], [vek()], 5, None, "markus")
    pruef("ein dauerhaft fehlendes Segment wird nach drei Versuchen gemeldet",
          _weg.abfragen == 3 and "segmentprobe" in _ausfall_w,
          (_weg.abfragen, _ausfall_w))

    # Dasselbe beim Lesen der Dimension in der Bestandsliste. Sie ist die
    # Pruefung vor und nach jedem Rollout; ohne Wiederholung stand eine
    # frisch beschriebene Sammlung dort als leer -- im Selbsttest einmal
    # als "und die des gewachsenen Bestands" aufgetreten.
    class _SpaeteDimension(_SpaetesSegment):
        def get(self, **kw):
            self.abfragen += 1
            if self.fehler:
                raise self.fehler.pop(0)
            return {"ids": ["x"], "embeddings": [[0.0] * 7]}

    import inventory as _bl_s
    _sd = _SpaeteDimension(_segment_fehler())
    _d_s = _bl_s._dimension(_sd)
    pruef("die Bestandsliste liest die Dimension auch bei spaetem Segment",
          _d_s == 7 and _sd.abfragen == 2, (_d_s, _sd.abfragen))
finally:
    store.neu_verbinden = _echt_neu_verbinden
