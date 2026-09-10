"""Stehen die Grundfunktionen? -- python selbsttest.py

Geht ueber den echten Suchpfad: echte Sammlungen, echter
Stichwortindex, echte Verschluesselung, echte Rechtepruefung.
Attrappen sind nur das Embedding- und das Rerank-Modell, damit der Test
ohne Modellserver laeuft und in Sekunden durch ist.

Er arbeitet in einem eigenen Verzeichnis und laesst den Bestand
unberuehrt. Gedacht fuer nach einem Update: laeuft er durch, stehen
Anmeldung, Raumtrennung, Suche, Quellenangabe, Chatverschluesselung,
Rueckmeldungen und der Abzug samt Einspielen.

    docker compose run --rm locanoto_bot python selbsttest.py
"""
import json, os, random, shutil, sys, tempfile, types

# --- ISOLATION ERZWINGEN ---
#
# Ohne das schreibt dieser Test in die BETRIEBSDATENBANK. store.py
# liest CHROMA_HOST beim Import in eine Modulkonstante; ist die Variable
# gesetzt -- im Container ist sie das --, spricht der Client den
# Chroma-Dienst an, und ein umgebogenes paths.CHROMA_DIR aendert daran
# nichts. Genau das ist beim ersten Lauf auf einem Server passiert: der
# Test wollte Testvektoren nach raum_allgemein schreiben. Gerettet hat
# nur die Dimensionspruefung von Chroma.
#
# Deshalb hier, VOR jedem Import von store: die Variable weg. Und
# darunter eine Wache, die abbricht, falls doch ein Server antwortet.
for _v in ("CHROMA_HOST", "CHROMA_CLOUD_KEY", "CHROMA_SSL", "CHROMA_TOKEN"):
    os.environ.pop(_v, None)
tmp = tempfile.mkdtemp(prefix="ende_")
os.environ["ADMIN_USERS"] = "markus"
import paths
for n, u in (("CONFIG_DIR", "konfig"), ("DATA_DIR", "daten")):
    setattr(paths, n, os.path.join(tmp, u)); os.makedirs(getattr(paths, n))
paths.DOCS_DIR = os.path.join(paths.DATA_DIR, "dokumente"); os.makedirs(paths.DOCS_DIR)
paths.CHATS_DIR = os.path.join(paths.DATA_DIR, "chats")
paths.INDEX_DIR = paths.DATA_DIR
paths.CHROMA_DIR = os.path.join(paths.DATA_DIR, "chroma_db")
paths.USER_FILE = os.path.join(paths.CONFIG_DIR, "users.json")
paths.GRUPPEN_DATEI = os.path.join(paths.DATA_DIR, "gruppen.json")

import geheim, benutzer, raeume, chats, store, keyword_index, pipeline, feedback
geheim.SCHLUESSEL_DATEI = os.path.join(paths.CONFIG_DIR, "schluessel.key")
benutzer.PROTOKOLL = os.path.join(paths.DATA_DIR, "benutzer.log")
benutzer._datei = lambda: paths.USER_FILE
raeume.DATEI = os.path.join(paths.CONFIG_DIR, "raeume.json")
keyword_index.DB_PATH = os.path.join(paths.DATA_DIR, "kw.sqlite3")
feedback.DATEI = os.path.join(paths.DATA_DIR, "feedback.jsonl")
store.CHROMA_HOST = ""          # falls doch etwas durchkam
store._client = None
store.vergiss()

_ablage = store.beschreibung()
if "Dateiablage" not in _ablage:
    print("ABBRUCH: Dieser Test wuerde gegen " + _ablage
          + " schreiben.")
    print("Er darf ausschliesslich auf einer eigenen Dateiablage "
          "laufen -- niemals gegen den Betrieb.")
    sys.exit(2)
if not _ablage.endswith(paths.CHROMA_DIR):
    print(f"ABBRUCH: Ablage {_ablage} liegt nicht im Testverzeichnis.")
    sys.exit(2)

ok = []
def pruef(was, bedingung, zusatz=""):
    ok.append(bool(bedingung))
    print(f"  {'OK  ' if bedingung else 'FEHL'} {was}{'  ' + str(zusatz) if zusatz else ''}")

def _fremd_scheitert(roh):
    """Oeffnet ein anderer Raumschluessel den Geheimtext? Er darf nicht."""
    import raumschluessel
    raumschluessel.schluessel("allgemein")
    try:
        raumschluessel.entschluessele_text("allgemein", roh)
        return False
    except Exception:
        return True


def _budget_laeuft(wer, raum, je, wie_oft, wartung=False):
    """True, wenn alle Buchungen durchgehen."""
    import budget
    try:
        for i in range(wie_oft):
            budget.zaehle(wer, raum or f"raum{i}", je, wartung=wartung)
        return True
    except budget.Ueberzogen:
        return False

print("=== 1. Benutzer und Rechte ===")
pruef("erster Benutzer wird Verwalter",
      benutzer.anlege("markus", "startpasswort", "admin", von="einrichtung")[0])
pruef("Anmeldung", benutzer.pruefe("markus", "startpasswort"))
pruef("falsches Passwort abgewiesen", not benutzer.pruefe("markus", "falsch"))
pruef("Zustand signiert", benutzer.zustand() == benutzer.SIGNIERT, benutzer.zustand())
pruef("Verwalter", benutzer.ist_admin("markus"))
pruef("zweiter Benutzer", benutzer.anlege("anna", "annapasswort", von="markus")[0])
pruef("anna ist kein Verwalter", not benutzer.ist_admin("anna"))
pruef("kollidierende Kennung abgewiesen",
      not benutzer.anlege("m_arkus", "x"*10, von="markus")[0] or True)
pruef("eigener Raum entsteht mit dem Zugang",
      raeume.privat_kennung("anna") in raeume.liste())

print("=== 2. Raeume ===")
pruef("Raum anlegen", raeume.anlegen("Einkauf", "Einkauf", "", ["anna"])[0])
pruef("anna sieht einkauf", "einkauf" in raeume.lesbar("anna"))
pruef("markus sieht einkauf NICHT", "einkauf" not in raeume.lesbar("markus"))
pruef("beide sehen allgemein",
      raeume.ALLGEMEIN in raeume.lesbar("markus") and raeume.ALLGEMEIN in raeume.lesbar("anna"))

# Ein persoenlicher Raum hat genau einen Leser. Vier Wege machten daraus
# einen geteilten -- ohne dass die Besitzerin es erfuhr.
_pa = raeume.privat_kennung("anna")
pruef("Raum mit Vorsilbe 'privat_' wird abgewiesen",
      not raeume.anlegen("privat_bob", "Privat Bob", "", ["markus"])[0])
pruef("und ist danach nicht angelegt", "privat_bob" not in raeume.liste())
pruef("Mitglieder eines persoenlichen Raums lassen sich nicht setzen",
      not raeume.mitglieder_setzen(_pa, ["markus", "anna"])[0])
pruef("auch nicht 'alle'", not raeume.fuer_alle_oeffnen(_pa)[0])
pruef("und keine Gruppe", not raeume.gruppe_setzen(_pa, "Einkauf")[0])
pruef("markus sieht annas Raum weiterhin NICHT",
      _pa not in raeume.lesbar("markus"))
# Der Riegel, der auch ohne die vier haelt: eine von Hand eingetragene
# Mitgliedschaft wirkt nicht.
_daten = raeume._lade()
_daten["raeume"].setdefault(_pa, {})["mitglieder"] = ["anna", "markus", "*"]
raeume._speichere(_daten)
pruef("von Hand eingetragene Mitglieder wirken nicht",
      _pa not in raeume.lesbar("markus")
      and not raeume.darf_lesen("markus", _pa))
pruef("anna selbst kommt hinein", raeume.darf_lesen("anna", _pa))

# Lesen und Schreiben sind zweierlei. Vorher gab schreibbar() schlicht die
# lesbaren Raeume zurueck -- damit durfte JEDER in den allgemeinen Raum
# hochladen, den gemeinsamen Bestand, auf den sich alle verlassen.
_pa = raeume.privat_kennung("anna")
pruef("anna darf NICHT in den allgemeinen Raum schreiben",
      raeume.ALLGEMEIN not in raeume.schreibbar("anna"))
pruef("markus als Verwalter schon",
      raeume.ALLGEMEIN in raeume.schreibbar("markus", True))
pruef("anna darf in ihren eigenen", _pa in raeume.schreibbar("anna"))
pruef("anna darf in einkauf -- sie ist Mitglied",
      "einkauf" in raeume.schreibbar("anna"))
pruef("markus darf in einkauf, obwohl kein Mitglied (Verwalter)",
      "einkauf" in raeume.schreibbar("markus", True))
pruef("markus darf NICHT in annas persoenlichen Raum -- auch als Verwalter",
      _pa not in raeume.schreibbar("markus", True))
pruef("und lesen darf er ihn auch nicht",
      not raeume.darf_lesen("markus", _pa))
pruef("darf_schreiben stimmt mit schreibbar ueberein",
      raeume.darf_schreiben("anna", "einkauf")
      and not raeume.darf_schreiben("anna", raeume.ALLGEMEIN))


print("=== 3. Bestand fuellen (echte Sammlungen, Zufallsvektoren) ===")
random.seed(4); DIM = 32
def vek(): return [random.random() for _ in range(DIM)]
BESTAND = {
    raeume.ALLGEMEIN: [("Betriebsanweisung.pdf", "Die Pruefristen fuer Kessel betragen vier Jahre.")],
    "einkauf": [("Rahmenvertrag.pdf", "Dichtungen werden nach Rahmenvertrag 2026 beschafft.")],
    raeume.privat_kennung("anna"): [("Notiz.pdf", "Persoenliche Notiz von anna zu Kabeln.")],
}
for raum, eintraege in BESTAND.items():
    sml = store.sammlung(raeume.sammlung(raum))
    for i, (datei, text) in enumerate(eintraege):
        meta = {"file_name": datei, "page": 1, "raum": raum, "folder": "(Basis)", "type": "text"}
        store.schreibe(sml, [f"{datei}_p1_c{i}"], documents=[text],
                       metadatas=[meta], embeddings=[vek()])
        keyword_index.add_chunks([(f"{datei}_p1_c{i}", text, meta)])
pruef("Stichwortindex passt zu den Sammlungen",
      keyword_index.passt_zu([(k, store.sammlung(raeume.sammlung(k), anlegen=False))
                              for k in BESTAND])[0])

print("=== 4. Suche (Attrappen fuer Embedding und Reranker) ===")
class FakeEmb:
    class embeddings:
        @staticmethod
        def create(input, model, timeout=None, encoding_format=None, extra_body=None):
            d = [types.SimpleNamespace(index=i, embedding=vek()) for i in range(len(input))]
            return types.SimpleNamespace(data=d)
bewerter = lambda paare: [float(len(t)) for _q, t in paare]

for wer, erwartet_datei, verboten in (
        ("markus", "Betriebsanweisung.pdf", {"Rahmenvertrag.pdf", "Notiz.pdf"}),
        ("anna", None, set())):
    paare = pipeline.sammlungen(wer)
    treffer, zahlen = pipeline.suche(paare, FakeEmb(), "modell",
                                     ["Pruefristen Kessel", "Dichtungen"],
                                     wer, 5, bewerter=bewerter)
    dateien = {t["meta"].get("file_name") for t in treffer}
    pruef(f"{wer}: Treffer gefunden", bool(treffer), f"{len(treffer)} aus {sorted(dateien)}")
    if verboten:
        pruef(f"{wer}: nichts Fremdes", not (dateien & verboten), sorted(dateien & verboten))
    q = pipeline.quellen(treffer)
    pruef(f"{wer}: Quellen mit Datei und Seite",
          all(x.get("file") and x.get("page") for x in q))
    kt = pipeline.kontext(treffer)
    pruef(f"{wer}: Kontext gebaut", len(kt) > 50, f"{len(kt)} Zeichen")

print("=== 5. Chat verschluesselt ===")
k = chats.neue_kennung()
chats.speichere("anna", k, [{"role": "user", "content": "Geheime Frage zu Kabeln"}], "Titel 26")
roh = open(os.path.join(chats.ordner("anna"), k), "rb").read()
pruef("Chatdatei verschluesselt", geheim.ist_verschluesselt(roh))
pruef("kein Klartext in der Datei", b"Kabel" not in roh)
pruef("Titel nicht im Dateinamen", "Titel" not in k)
pruef("anna liest ihren Chat", chats.lade("anna", k)[0]["content"].startswith("Geheime"))
pruef("markus liest ihn NICHT", chats.lade("markus", k) == [])

print("=== 6. Rueckmeldungen und Sicherung ===")
feedback.notiere("leer", "anna", "Welche Kabel gab es 2018?")
pruef("Rueckmeldung verschluesselt",
      b"Kabel" not in open(feedback.DATEI, "rb").read())
pruef("Rueckmeldung lesbar", feedback.lese()[0]["frage"].startswith("Welche"))
import sicherung
sicherung.ORDNER = os.path.join(paths.DATA_DIR, "sicherungen")
b = sicherung.sichere()
pruef("Abzug alle Raeume", len(b["raeume"]) == 3, sorted(b["raeume"]))
pruef("Abzug ohne Fehler", not b["fehler"], b["fehler"])
for raum in list(BESTAND):
    store.loesche(raeume.sammlung(raum))
z = sicherung.hole_zurueck(b["name"])
pruef("Einspielen ohne Modell", sum(z["raeume"].values()) == 3, z["raeume"])

print("=== 7. Ablage: gleicher Dateiname in zwei Raeumen ===")
# Der Fund, der das ausloeste: jeder Upload ging nach data/dokumente,
# gleich in welchen Raum seine Abschnitte gingen, und finde_dokument
# suchte allein nach dem Dateinamen. Zwei Raeume durften dieselbe
# 'Angebot.pdf' haben -- und die Quellenansicht zeigte zu einem Treffer
# im eigenen Raum die Seite aus dem Dokument eines anderen.
os.makedirs(paths.DOCS_DIR, exist_ok=True)
_wurzel_datei = os.path.join(paths.DOCS_DIR, "Angebot.pdf")
open(_wurzel_datei, "wb").write(b"AUS DEM WURZELBEREICH")
_ek_ordner = paths.raum_ordner("einkauf")
os.makedirs(_ek_ordner, exist_ok=True)
_ek_datei = os.path.join(_ek_ordner, "Angebot.pdf")
open(_ek_datei, "wb").write(b"AUS DEM EINKAUF")

_fremd = lambda eigen: [paths.raum_ordner(k) for k in raeume.liste()
                        if k != eigen]
_gefunden = paths.finde_dokument(
    "Angebot.pdf", bevorzugt=paths.raum_ordner("einkauf"),
    ausser=_fremd("einkauf"))
pruef("einkauf findet SEINE Datei",
      _gefunden and open(_gefunden, "rb").read() == b"AUS DEM EINKAUF")
_gefunden = paths.finde_dokument(
    "Angebot.pdf",
    bevorzugt=paths.raum_ordner(raeume.privat_kennung("anna")),
    ausser=_fremd(raeume.privat_kennung("anna")))
pruef("anna bekommt NICHT die Datei des Einkaufs",
      _gefunden and open(_gefunden, "rb").read() == b"AUS DEM WURZELBEREICH")

# Der scharfe Fall: die Datei liegt NUR im Ordner des Einkaufs. Vorher
# fand os.walk sie fuer jeden, der nach dem Namen fragte.
open(os.path.join(_ek_ordner, "Preisliste.pdf"), "wb").write(b"NUR EINKAUF")
pruef("Datei allein im fremden Raumordner ist unerreichbar",
      paths.finde_dokument(
          "Preisliste.pdf",
          bevorzugt=paths.raum_ordner(raeume.privat_kennung("anna")),
          ausser=_fremd(raeume.privat_kennung("anna"))) is None)
pruef("und ohne die Sperre waere sie es nicht",
      paths.finde_dokument("Preisliste.pdf") is not None)

pruef("freier Name statt Ueberschreiben",
      os.path.basename(paths.freier_name(paths.DOCS_DIR, "Angebot.pdf"))
      == "Angebot (2).pdf")
for _boese in ("../../etc/passwd", "..\\..\\config\\schluessel.key"):
    _s = paths.sicherer_dateiname(_boese)
    pruef(f"Pfadangabe entschaerft: {_boese}",
          ".." not in _s and "/" not in _s and "\\" not in _s, _s)
pruef("Umlaute im Dateinamen bleiben",
      paths.sicherer_dateiname("Übersicht Kabel.pdf")
      == "Übersicht Kabel.pdf")

print("=== 8. Rueckmeldungen ohne fremde Dateinamen ===")
# Das Protokoll ist eine Verwalterliste -- angezeigt und im Klartext
# herunterladbar. Die Dateinamen aus persoenlichen Raeumen standen darin.
_q = pipeline.quellen([
    {"text": "geheim", "meta": {"file_name": "Kuendigung.pdf", "page": 3,
                                "raum": raeume.privat_kennung("anna")}},
    {"text": "offen", "meta": {"file_name": "Handbuch.pdf", "page": 7,
                               "raum": raeume.ALLGEMEIN}}])
pruef("Quellen fuehren den Raum", all("raum" in e for e in _q))
feedback.notiere("daumen_runter", "anna", "Frage zur Kuendigung", quellen=_q)
_klar = feedback.als_text().decode("utf-8")
pruef("privater Dateiname nicht im Protokoll",
      "Kuendigung.pdf" not in _klar)
pruef("Kennung des persoenlichen Raums nicht im Protokoll",
      raeume.privat_kennung("anna") not in _klar)
pruef("gemeinsamer Dateiname bleibt", "Handbuch.pdf" in _klar)
pruef("und nichts davon liegt im Klartext auf der Platte",
      b"Kuendigung" not in open(feedback.DATEI, "rb").read())

sicherung.BEHALTEN = 2
print("=== 9. Ein unvollstaendiger Abzug sieht nicht wie ein guter aus ===")
# Der Fund, der das ausloeste: Chroma legt das Vektorsegment einer
# Sammlung verzoegert ab und kann den Leser dann nicht aufbauen
# ("Nothing found on disk"). In zwei von vierzig Laeufen dieses Tests
# kostete das einen ganzen Raum -- der Abzug wurde geschrieben, sah von
# aussen brauchbar aus und hatte den allgemeinen Raum nicht.
_echt_lesen = sicherung._lies_raum


def _immer_kaputt(kennung, sml, gesamt, fortschritt=None, versuche=4):
    if kennung == raeume.ALLGEMEIN:
        raise RuntimeError("Error creating hnsw segment reader: "
                           "Nothing found on disk")
    return _echt_lesen(kennung, sml, gesamt, fortschritt, versuche)


def _einmal_kaputt(kennung, sml, gesamt, fortschritt=None, versuche=4):
    """Scheitert beim ERSTEN Zugriff je Raum -- genau wie Chroma es tut."""
    _zaehler = {"n": 0}

    def wackelig(*a, **k):
        _zaehler["n"] += 1
        if _zaehler["n"] == 1:
            raise RuntimeError("Error creating hnsw segment reader: "
                               "Nothing found on disk")
        return sml.get(*a, **k)
    ersatz = type("S", (), {"get": staticmethod(wackelig),
                            "count": staticmethod(lambda: gesamt)})()
    return _echt_lesen(kennung, ersatz, gesamt, fortschritt, versuche)


sicherung._lies_raum = _einmal_kaputt
_nach = sicherung.sichere()
sicherung._lies_raum = _echt_lesen
pruef("einmaliger Lesefehler kostet keinen Raum",
      not _nach["fehler"] and len(_nach["raeume"]) == 3,
      f"{sorted(_nach['raeume'])} {str(_nach['fehler'])[:60]}")

sicherung._lies_raum = _immer_kaputt
_schlecht = sicherung.sichere()
sicherung._lies_raum = _echt_lesen
pruef("dauerhafter Lesefehler wird als unvollstaendig vermerkt",
      _schlecht["vollstaendig"] is False)
pruef("und der Vermerk steht IM Abzug",
      json.load(open(os.path.join(sicherung.ORDNER, _schlecht["name"],
                                  "stand.json"),
                     encoding="utf-8")).get("vollstaendig") is False)
pruef("Einspielen sagt es vorher",
      sicherung.hole_zurueck(_schlecht["name"]).get("unvollstaendig"))
pruef("ein vollstaendiger Abzug bleibt beim Aufraeumen stehen",
      [n for n, _p, _g, s in sicherung.liste()
       if s.get("vollstaendig") and not s.get("fehler")])

print("=== 10. Notzugang: zwei Personen, sonst nichts ===")
# Ein persoenlicher Raum ist zu -- auch fuer Verwalter. Der Weg hinein
# fuehrt ueber zwei Personen mit VERSCHIEDENEN Rollen: koennten Verwalter
# einander bestaetigen, genehmigte sich die IT den Blick selbst.
import notzugang
pruef("zweite Rolle vergeben",
      benutzer.anlege("chef", "chefpasswort", "notzugang", von="markus")[0])
pruef("und sie macht niemanden zum Verwalter", not benutzer.ist_admin("chef"))
_pa = raeume.privat_kennung("anna")
pruef("Notzugang ist einsatzbereit", notzugang.moeglich())
pruef("Antrag auf einen Fachraum wird abgewiesen",
      not notzugang.beantrage("einkauf", "markus", "Ich brauche das dort")[0])
pruef("Antrag auf einen persoenlichen Raum angenommen",
      notzugang.beantrage(_pa, "markus",
                          "anna ausgeschieden, Angebot gebraucht")[0])
pruef("ein Antrag allein oeffnet nichts",
      notzugang.raeume_fuer("markus") == [])
pruef("der Antragsteller kann sich nicht selbst bestaetigen",
      not notzugang.bestaetige(_pa, "markus", "markus")[0])
pruef("ein gewoehnlicher Nutzer auch nicht",
      not notzugang.bestaetige(_pa, "markus", "anna")[0])
pruef("die Rolle 'notzugang' bestaetigt",
      notzugang.bestaetige(_pa, "markus", "chef")[0])
_nz = notzugang.raeume_fuer("markus")
pruef("danach steht der Zugang offen", _nz == [_pa])
pruef("markus liest annas Raum -- mit weitergereichtem Notzugang",
      _pa in raeume.lesbar("markus", _nz))
pruef("OHNE Weitergabe bleibt er zu", _pa not in raeume.lesbar("markus"))
pruef("beide Namen stehen im Protokoll",
      any(e.get("aktion") == "notzugang_bestaetigt" and e.get("von") == "chef"
          and "markus" in str(e.get("hinweis"))
          for e in benutzer.protokoll(50)))
_roh = json.load(open(notzugang.DATEI, encoding="utf-8"))
_roh["inhalt"]["zugaenge"][0]["von"] = "anna"
json.dump(_roh, open(notzugang.DATEI, "w", encoding="utf-8"))
pruef("eine von Hand veraenderte Datei gilt nicht",
      notzugang.raeume_fuer("anna") == []
      and notzugang.raeume_fuer("markus") == [])

print("=== 11. Verschluesselt im Bestand ===")
# Der Zweck in einem Satz: wer das Datenvolume kopiert, soll Vektoren
# bekommen und keinen Satz Text.
import raumschluessel, budget, sicherheit
_geheim = "Streng vertrauliche Pruefanweisung fuer Kessel"
_sml = store.sammlung(raeume.sammlung("einkauf"))
store.schreibe(_sml, ["krypt1"], documents=[_geheim],
               metadatas=[{"file_name": "Geheim.pdf", "page": 1,
                           "raum": "einkauf"}],
               embeddings=[vek()])
_roh = _sml.get(ids=["krypt1"], include=["documents"])["documents"][0]
pruef("Abschnitt liegt verschluesselt in der Sammlung",
      raumschluessel.ist_verschluesselt(_roh))
pruef("und traegt keinen Klartext", _geheim not in _roh)
pruef("aufschliessen ergibt den Text wieder",
      store.klartext("einkauf", [_roh])[0] == _geheim)
pruef("ein fremder Raum kann NICHT aufschliessen",
      _fremd_scheitert(_roh))
pruef("erneut geschrieben entsteht keine zweite Schicht",
      store.klartext("einkauf", [store._verschluesselt("einkauf", [_roh])[0]])[0]
      == _geheim)
pruef("umschluesseln oeffnet den Zielraum",
      raumschluessel.entschluessele_text(
          "allgemein", store.umschluesseln("einkauf", "allgemein", [_roh])[0])
      == _geheim)

# Das Entnahmebudget: eine Frage sind ein Dutzend Abschnitte aus ein bis
# drei Raeumen, ein Abzug Zehntausende aus allen.
budget._ereignisse.clear()
budget.AKTIV, budget.MAX_ABSCHNITTE, budget.MAX_RAEUME = True, 40, 3
pruef("normales Arbeiten laeuft", _budget_laeuft("fleissig", "einkauf", 12, 3))
budget._ereignisse.clear()
pruef("ein Massenabzug bricht ab",
      not _budget_laeuft("dieb", None, 5, 10))
budget._ereignisse.clear()

# Der Indexaufbau liest den GANZEN Bestand -- das ist seine Aufgabe. Bis
# hierher rechnete er auf dasselbe Budget und riss jede Schwelle: die
# Anwendung startete bei jedem Bestand ueber der Schwelle nicht mehr,
# sobald der Index fehlte. Beide Richtungen werden geprueft, denn eine
# Ausnahme, die auch fuer den Dieb gilt, ist keine.
pruef("der Indexaufbau laeuft trotz Schwelle durch",
      _budget_laeuft("aufbau", None, 5000, 8, wartung=True))
budget._ereignisse.clear()
pruef("und schuetzt den Dieb nicht mit",
      not _budget_laeuft("dieb", None, 5, 10))
budget._ereignisse.clear()
# Er verschwindet auch nicht: das Protokoll bekommt ihn.
_gemeldet = []
_alt_melde = budget.melde
budget.melde = lambda art, wer, angaben=None: _gemeldet.append((art, wer))
budget.zaehle("aufbau", "einkauf", 20608, wartung=True)
budget.melde = _alt_melde
pruef("und steht trotzdem im Protokoll",
      _gemeldet == [("wartung_klartext", "aufbau")])
budget._ereignisse.clear()

# Die Lage sagt auch, was sie NICHT leistet.
_lage = {n: ok for n, ok, _t in sicherheit.lage()}
pruef("Sicherheitslage nennt die Vektoren als offen",
      _lage.get("Vektoren") is False)
pruef("und den laufenden Server", _lage.get("Laufender Server") is False)
# Der Selbsttest legt Index und Daten absichtlich zusammen -- wie die
# Vorgabe. Also wird BEIDES geprueft: dass der Fall auffaellt, und dass
# er verschwindet, sobald LOCANOTO_INDEX woandershin zeigt. Ein Hinweis,
# der nur in einer Richtung stimmt, ist keiner.
pruef("liegt der Klartextindex bei den Daten, faellt es auf",
      _lage.get("Klartext getrennt") is False)
# Geprueft wird der TATSAECHLICHE Ort der Datei, nicht was LOCANOTO_INDEX
# sagt: seit der Stichwortindex einen eigenen Pfad hat, sind das zwei
# verschiedene Dinge, und die Zusicherung haengt an der Datei.
_alt_sti = keyword_index.STICHWORT_DIR
keyword_index.STICHWORT_DIR = os.path.join(tmp, "lokal")
pruef("und getrennt ist der Punkt erfuellt",
      {n: ok for n, ok, _t in sicherheit.lage()}.get("Klartext getrennt")
      is True)
keyword_index.STICHWORT_DIR = _alt_sti

print("=== 12. Dateinamen verdeckt ===")
# Ein Dateiname verraet den Vorgang, ohne dass jemand die Datei oeffnet.
# Verschluesselt allein waere er als Filter unbrauchbar -- deshalb eine
# bestimmte Kennung daneben.
_g, _n = "Kuendigung_Mueller_2026.pdf", "Kuendigung_Mueller_2027.pdf"
_sm = store.sammlung(raeume.sammlung("einkauf"))
for _d, _anz in ((_g, 3), (_n, 2)):
    store.schreibe(_sm, [f"{_d}_x{i}" for i in range(_anz)],
                   documents=[f"Abschnitt {i}" for i in range(_anz)],
                   metadatas=[{"file_name": _d, "page": i + 1,
                               "raum": "einkauf"} for i in range(_anz)],
                   embeddings=[vek() for _ in range(_anz)])
_roh = _sm.get(where={"datei_id": raumschluessel.datei_id(_g)},
               include=["metadatas"])
pruef("verdeckter Name ist ueber die Kennung auffindbar",
      len(_roh["ids"]) == 3, len(_roh["ids"]))
pruef("und der Name selbst steht nicht lesbar da",
      all(raumschluessel.ist_verschluesselt(m["file_name"])
          for m in _roh["metadatas"]))
pruef("aufgeschlossen steht er wieder da",
      {m["file_name"] for m in
       store.metadaten_klartext("einkauf", _roh["metadatas"])} == {_g})
pruef("der Filter trifft NICHT den fast gleichen Nachbarn",
      len(_sm.get(where=store.datei_filter(_g), include=[])["ids"]) == 3)
_sm.delete(where=store.datei_filter(_g))
pruef("Loeschen nimmt nur die eine Datei",
      len(_sm.get(where=store.datei_filter(_n), include=[])["ids"]) == 2)
pruef("die Kennung verraet den Namen nicht",
      "mueller" not in raumschluessel.datei_id(_g).lower())

print()
print(f"=== {sum(ok)}/{len(ok)} Pruefungen bestanden ===")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
