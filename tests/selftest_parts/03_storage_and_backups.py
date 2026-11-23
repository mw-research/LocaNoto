"""Self-test, part 03: Storage paths, tables, backups, inventory, mirroring to ownCloud, passwords, workspace folders.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- DER OWNCLOUD-ZIELPFAD BEHAELT DEN PROJEKTORDNER ---
#
# Dreimal war diese Berechnung falsch, jedes Mal woanders: ablage()
# zeigte fuer den allgemeinen Raum auf einen Unterordner, ordner_fuer()
# kannte nur die Handzuordnung, und der Upload baute den Zielpfad aus
# dem blossen Dateinamen -- dabei fiel der Projektordner weg und in
# ownCloud lag alles flach nebeneinander.
import owncloud as _ocw
pruef("der Projektordner bleibt erhalten",
      _ocw.ziel_pfad(raeume.ALLGEMEIN,
                     os.path.join(paths.DOCS_DIR, "Projekt A", "x.pdf"))
      == _ocw.raum_pfad(raeume.ALLGEMEIN) + "/Projekt A/x.pdf",
      _ocw.ziel_pfad(raeume.ALLGEMEIN,
                     os.path.join(paths.DOCS_DIR, "Projekt A", "x.pdf")))
pruef("ohne Projekt liegt die Datei direkt im Raumordner",
      _ocw.ziel_pfad(raeume.ALLGEMEIN,
                     os.path.join(paths.DOCS_DIR, "x.pdf"))
      == _ocw.raum_pfad(raeume.ALLGEMEIN) + "/x.pdf")
pruef("und ein anderer Raum bekommt seinen eigenen Baum",
      _ocw.ziel_pfad("einkauf",
                     os.path.join(paths.DOCS_DIR, "einkauf", "P", "y.pdf"))
      == _ocw.raum_pfad("einkauf") + "/P/y.pdf",
      _ocw.ziel_pfad("einkauf",
                     os.path.join(paths.DOCS_DIR, "einkauf", "P", "y.pdf")))


# --- EINE TABELLE, GEFOLGT VON TEXT, GIBT KEINE DOPPELTE KENNUNG ---
#
# Im Betrieb liess sich eine Word-Datei nicht hochladen:
#   DuplicateIDError: found duplicates of: Angebot.docx_p4_c0
# Die Tabelle erhoehte die Abschnittsnummer und gab sich damit aus --
# und was danach kam, sammelte sich unter derselben weiter. Die
# Kennung ist aus Dateiname, Nummer und Position gebaut.
import lesen as _le
from docx import Document as _Doc

_dok = _Doc()
_dok.add_heading("Kapitel", level=1)
_dok.add_paragraph("Text vor der Tabelle.")
_tab = _dok.add_table(rows=2, cols=2)
_tab.cell(0, 0).text = "Spalte A"
_tab.cell(0, 1).text = "Spalte B"
_tab.cell(1, 0).text = "Wert 1"
_tab.cell(1, 1).text = "Wert 2"
_dok.add_paragraph("Text NACH der Tabelle -- hier brach es.")
_docx_pfad = os.path.join(tmp, "tabellenprobe.docx")
_dok.save(_docx_pfad)

_abschnitte = list(_le.abschnitte(_docx_pfad))
_nummern = [n for n, _t, _x in _abschnitte]
pruef("die Word-Datei zerfaellt in mehrere Abschnitte",
      len(_abschnitte) >= 3, len(_abschnitte))
pruef("und jeder hat seine eigene Nummer",
      len(_nummern) == len(set(_nummern)), _nummern)
pruef("der Text nach der Tabelle geht nicht verloren",
      any("NACH der Tabelle" in t for _n, _t2, t in _abschnitte))

# Die Sicherung im Schreibweg. Sie greift fuer alle drei Stellen, an
# denen Kennungen entstehen -- Oberflaeche, Ingest, Bilder-Ingest.
pruef("doppelte Kennungen werden durchnummeriert",
      store._eindeutige_kennungen(["a", "b", "a", "a"])
      == ["a", "b", "a_w2", "a_w3"],
      store._eindeutige_kennungen(["a", "b", "a", "a"]))

# UND DAS WICHTIGERE: ohne Dublette bleibt alles, wie es war. Sonst
# bekaeme ein bestehender Bestand beim naechsten Einlesen neue
# Kennungen und stuende danach doppelt in der Suche.
pruef("ohne Dublette bleibt jede Kennung unveraendert",
      store._eindeutige_kennungen(["x_p1_c0", "x_p1_c1", "x_p2_c0"])
      == ["x_p1_c0", "x_p1_c1", "x_p2_c0"])

# Und die VERDRAHTUNG: schreibe() muss den Aufruf ueberstehen, nicht
# nur die Funktion daneben existieren. Genau dieser Aufruf hat im
# Betrieb den ganzen Upload gekostet -- Chroma weist einen Aufruf mit
# Dubletten komplett ab.
_dsml = store.sammlung(raeume.sammlung("einkauf"))
_vorher_n = _dsml.count()
try:
    _gesch = store.schreibe(
        _dsml, ["dopp", "dopp"], documents=["erster Text", "zweiter Text"],
        metadatas=[{"file_name": "d.docx"}, {"file_name": "d.docx"}],
        embeddings=[vek(), vek()])
except Exception as _de:
    # Gefangen, damit ein Rueckfall hier als FEHL erscheint und nicht
    # den ganzen Lauf abbricht -- die Pruefungen danach sollen trotzdem
    # laufen und zeigen, was sonst noch kaputt ist.
    _gesch = type(_de).__name__
pruef("ein Aufruf mit doppelter Kennung geht durch", _gesch == 2, _gesch)
pruef("und BEIDE Texte stehen danach da -- keiner faellt weg",
      _dsml.count() == _vorher_n + 2, (_vorher_n, _dsml.count()))

# --- EIN ABZUG OHNE ABSCHNITTE IST KEINER ---
#
# Der preStop-Haken laeuft bei jedem Herunterfahren. Zu dem Zeitpunkt
# ist der Chroma-Beiwagen oft schon weg -- es gibt keine Reihenfolge
# beim Beenden. Der Abzug fand dann keine Sammlung, war nach 0,1
# Sekunden fertig, hatte keinen Fehler und galt damit als
# VOLLSTAENDIG. --neuester nimmt den neuesten vollstaendigen, also
# haette der Wiederanlauf null Abschnitte eingespielt und Erfolg
# gemeldet.
_alt_samml = sicherung._raum_sammlungen
sicherung._raum_sammlungen = lambda: []
_vorher = (set(statefiles.listdir(sicherung.ORDNER))
           if statefiles.isdir(sicherung.ORDNER) else set())
_ber = sicherung.sichere()
_nachher = (set(statefiles.listdir(sicherung.ORDNER))
            if statefiles.isdir(sicherung.ORDNER) else set())
sicherung._raum_sammlungen = _alt_samml

pruef("ein Abzug ohne Sammlungen gilt nicht als vollstaendig",
      not _ber.get("vollstaendig"), _ber.get("vollstaendig"))
pruef("und wird gar nicht erst abgelegt", _vorher == _nachher,
      sorted(_nachher - _vorher))
pruef("der Grund steht im Bericht", "Chroma" in (_ber.get("grund") or ""),
      _ber.get("grund"))

# Und die andere Haelfte: ein Stummel, der schon auf der Platte liegt,
# traegt vollstaendig=true. Daran aendert das Schreiben von heute
# nichts -- also muss das LESEN ihn erkennen.
_stummel = os.path.join(sicherung.ORDNER, "2000-01-01_00-00-00")
statefiles.makedirs(_stummel, exist_ok=True)
with statefiles.open(os.path.join(_stummel, "stand.json"), "w", encoding="utf-8") as _f:
    json.dump({"name": "2000-01-01_00-00-00", "raeume": {},
               "abschnitte": 0, "fehler": [], "vollstaendig": True}, _f)
pruef("ein alter Stummel taugt nicht zum Zurueckholen",
      "2000-01-01_00-00-00" not in sicherung.vollstaendige(),
      sicherung.vollstaendige())
statefiles.rmtree(_stummel, ignore_errors=True)

# --- DIE BESTANDSLISTE ZAEHLT RICHTIG ---
#
# Sie ist das Werkzeug, mit dem sich ein Umzug ueberhaupt pruefen
# laesst: vorher im alten Container, nachher im neuen, und die beiden
# Ausgaben nebeneinander. Zaehlt sie falsch, ist die Pruefung eine
# Bestaetigung ohne Inhalt -- schlimmer als keine.
import inventory as _bl

_probe = os.path.join(tmp, "zaehlprobe")
statefiles.makedirs(os.path.join(_probe, "tief", "tiefer"), exist_ok=True)
for _p, _inhalt in ((["a.txt"], b"12345"),
                    (["tief", "b.txt"], b"123"),
                    (["tief", "tiefer", "c.txt"], b"1")):
    with statefiles.open(os.path.join(_probe, *_p), "wb") as _f:
        _f.write(_inhalt)
pruef("sie zaehlt auch in Unterordnern",
      _bl.zaehle_ordner(_probe) == (3, 9), _bl.zaehle_ordner(_probe))
pruef("und einen fehlenden Ordner als leer",
      _bl.zaehle_ordner(os.path.join(tmp, "gibtsnicht")) == (0, 0))


# --- DOKUMENTE NACH OWNCLOUD SPIEGELN ---
#
# Der Weg nach oben. Geprueft wird mit einer Attrappe: eine echte
# ownCloud steht im Test nicht zur Verfuegung, und die drei Faelle, auf
# die es ankommt, haengen ohnehin nicht am WebDAV, sondern an der
# Buchhaltung -- hochgeladen, lag schon da, Fehler.
import spiegeln as _sp

_quelle = os.path.join(tmp, "spiegelprobe")
statefiles.makedirs(os.path.join(_quelle, "unterordner"), exist_ok=True)
for _p in (["a.pdf"], ["b.pdf"], ["unterordner", "c.pdf"], [".versteckt"]):
    with statefiles.open(os.path.join(_quelle, *_p), "wb") as _f:
        _f.write(b"x")

pruef("gespiegelt wird auch aus Unterordnern",
      len(_sp._dateien(_quelle)) == 3, len(_sp._dateien(_quelle)))
pruef("versteckte Dateien bleiben aussen vor",
      not any(r.startswith(".") for _v, r in _sp._dateien(_quelle)))
pruef("die Pfade sind mit Schraegstrich, wie WebDAV sie will",
      all("\\" not in r for _v, r in _sp._dateien(_quelle)))

# Die Attrappe: eine Datei liegt dort schon, eine schlaegt fehl.
_oc = types.ModuleType("owncloud")
_oc.ordner_fuer = lambda raum: "/Abteilungen/Probe"
_oc.ablage = lambda raum: _quelle
_gelegt = []


def _lege_ab(quelle, fern, ueberschreiben=False):
    _gelegt.append(fern)
    if fern.endswith("b.pdf"):
        return False, "'b.pdf' liegt dort schon. Nicht ueberschrieben."
    if fern.endswith("c.pdf"):
        return False, "Nicht abgelegt: Verbindung abgelehnt"
    return True, "abgelegt"


_oc.lege_ab = _lege_ab
sys.modules["owncloud"] = _oc
_h, _u, _f = _sp.spiegle("probe", sagen=lambda *_a: None)
pruef("eine hochgeladen, eine lag schon da, eine schlug fehl",
      (_h, _u, _f) == (1, 1, 1), (_h, _u, _f))
# Die Unterscheidung ist der Punkt: "liegt dort schon" ist KEIN Fehler.
# Blind zu ueberschreiben, was jemand von Hand abgelegt hat, waere
# schlimmer als es stehen zu lassen.
pruef("der Zielpfad haengt am zugeordneten Ordner",
      all(p.startswith("/Abteilungen/Probe/") for p in _gelegt), _gelegt)

# Und der Stand: er muss aus dem entstehen, was DANACH dort liegt --
# nicht aus dem, was wir hochgeladen haben. Sonst nennt er Dateien, die
# nie ankamen, und der naechste Abgleich haelt sie fuer entfallen und
# loescht sie lokal samt Abschnitten.
_geschrieben = {}
_oc.dateien = lambda ordner: [
    {"rel": "a.pdf", "etag": "e1", "groesse": 1, "geaendert": "x"}]
_oc._stand_schreiben = lambda raum, daten: _geschrieben.update({raum: daten})
_sp.stand_neu("probe", sagen=lambda *_a: None)
pruef("der Stand kommt aus dem, was wirklich dort liegt",
      list(_geschrieben["probe"]) == ["a.pdf"], _geschrieben)
sys.modules.pop("owncloud", None)


# --- JEDER AENDERT SEIN EIGENES PASSWORT ---
# Und der Grund, warum die Oberflaeche pruefen MUSS: das Modul tut es
# nicht. passwort_setzen nimmt nur Name und neues Passwort entgegen --
# wer es aufruft, hat die Berechtigung schon festgestellt oder eben
# nicht.
import inspect as _inspect
pruef("passwort_setzen fragt selbst NICHT nach dem alten",
      "alt" not in _inspect.signature(benutzer.passwort_setzen).parameters,
      list(_inspect.signature(benutzer.passwort_setzen).parameters))

# --- BEIM PASSWORTSETZEN WIRD DIE ABLAGE NACHGEZOGEN ---
#
# Das ownCloud-Konto entsteht beim ANLEGEN eines Benutzers. Wer aus
# einer Migration kommt, hat keins -- dort kamen nur bcrypt-Hashes mit.
# Das Passwortsetzen ist der einzige Moment, in dem wieder ein
# Klartextpasswort vorliegt.
# UND DAS WICHTIGERE: ein vorhandenes Konto darf nicht ueberschrieben
# werden. LocaNoto wird oft auf ein Haus gesetzt, in dem es die Leute
# in ownCloud laengst gibt -- ihnen von hier aus das Passwort ihres
# Firmenkontos zu nehmen, spaerrte sie aus allem aus, was daran haengt.
_qu = statefiles.open(os.path.join(_ROOT,
                           "owncloud.py"), encoding="utf-8").read()
_na = _qu.split("def nutzer_anlegen(", 1)[1]
_na = _na.split("def richte_nutzer_ein(", 1)[0]
pruef("ein vorhandenes ownCloud-Konto bleibt unangetastet",
      "if nutzer_vorhanden(kennung):" in _na and "gab es schon" in _na)
# Seit LocaNoto seine Konten kennt, aendert es deren Passwort mit; ein
# fremdes Konto bleibt weiter unangetastet, und die Meldung sagt es.
pruef("und der Verwalter erfaehrt, ob dort das alte Passwort gilt",
      "gilt weiter das alte Passwort" in _qu)


import ast as _ast

# --- DER ZIELORDNER EINES RAUMS ---
#
# Der Zielordner kommt aus zuordnung_wirksam, nicht aus
# ordner_fuer: das kennt nur von Hand eingetragene Zuordnungen. Der
# Standardbaum, den einrichten.py anlegt und in den jeder Upload
# schreibt, kommt dort nicht vor -- ohne Handzuordnung waere jeder
# Raum uebersprungen worden, und die Meldung haette "kein Ordner
# zugeordnet" gesagt, obwohl gerade danach ausgewaehlt wurde.
# Geprueft wird die FUNKTION, nicht ihre Aufrufer. Vorher stand hier
# eine Quelltextpruefung auf spiegeln.py -- die bestand, waehrend der
# naechtliche Abgleich weiter ins Leere lief. Eine Pruefung, die eine
# Umgehung festhaelt statt der Sache, bestaetigt den halben Fix.
import owncloud as _ocw
pruef("ordner_fuer kennt den Standardbaum",
      _ocw.ordner_fuer(raeume.ALLGEMEIN) == _ocw.raum_pfad(raeume.ALLGEMEIN),
      _ocw.ordner_fuer(raeume.ALLGEMEIN))
pruef("und zwar fuer jeden angelegten Raum",
      all(_ocw.ordner_fuer(r) for r in raeume.liste()),
      {r: _ocw.ordner_fuer(r) for r in raeume.liste()})
pruef("fuer einen unbekannten Raum aber nichts",
      _ocw.ordner_fuer("gibtsnicht") is None)

# --- DER ALLGEMEINE RAUM LIEGT IM WURZELBEREICH ---
#
# Zwei Stellen waren sich uneinig: der Upload legte ihn nach DOCS_DIR,
# owncloud.ablage nach DOCS_DIR/allgemein. Sichtbar wurde es beim
# Spiegeln -- es fand im Unterordner nichts. Schlimmer waere der
# Abgleich gewesen: dieselben Dateien ein zweites Mal daneben, zweimal
# vektorisiert, zweimal in jeder Antwort.
import owncloud as _ocw

pruef("der allgemeine Raum liegt in der Wurzel",
      os.path.normpath(_ocw.ablage(raeume.ALLGEMEIN))
      == os.path.normpath(paths.DOCS_DIR),
      _ocw.ablage(raeume.ALLGEMEIN))
pruef("jeder andere Raum in seinem Unterordner",
      os.path.normpath(_ocw.ablage("einkauf"))
      == os.path.normpath(os.path.join(paths.DOCS_DIR, "einkauf")),
      _ocw.ablage("einkauf"))

# Und die Stelle, die es sonst wieder auseinanderlaufen laesst: der
# Upload muss dieselbe Regel haben.
pruef("der Upload benutzt dieselbe Regel",
      "DOCS_DIR if room == raeume.ALLGEMEIN" in _datei("doc_actions.py"))

# Beim Spiegeln des allgemeinen Raums duerfen die Ordner der anderen
# Raeume NICHT mitkommen. Sie liegen darunter, und sie gehoeren
# anderen Leuten -- der allgemeine Raum ist fuer alle sichtbar.
_w = os.path.join(tmp, "wurzelprobe")
statefiles.makedirs(os.path.join(_w, "einkauf"), exist_ok=True)
statefiles.makedirs(os.path.join(_w, "offen"), exist_ok=True)
for _p in (["basis.pdf"], ["offen", "auch.pdf"], ["einkauf", "geheim.pdf"]):
    with statefiles.open(os.path.join(_w, *_p), "wb") as _f:
        _f.write(b"x")
_gefunden = [r for _v, r in _sp._dateien(_w, [os.path.join(_w, "einkauf")])]
pruef("der Ordner eines fremden Raums bleibt aussen vor",
      "einkauf/geheim.pdf" not in _gefunden, _gefunden)
pruef("alles andere kommt mit",
      sorted(_gefunden) == ["basis.pdf", "offen/auch.pdf"], _gefunden)
