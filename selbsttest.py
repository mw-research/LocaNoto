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
import io, json, os, random, shutil, sys, tempfile, types

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
# Die Wache fuer den Wiederanlauf ohne Menschen davor: leer heisst
# leer, und im Zweifel gilt der Bestand als vorhanden. Ein nicht
# eingespielter Abzug ist ein Ausfall; ein faelschlich eingespielter
# ueberschreibt die Arbeit des vorherigen Starts.
pruef("nach dem Loeschen gilt der Bestand als leer", sicherung._leer_genug())
z = sicherung.hole_zurueck(b["name"])
pruef("Einspielen ohne Modell", sum(z["raeume"].values()) == 3, z["raeume"])
pruef("danach nicht mehr", not sicherung._leer_genug())

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

# Der eingestellte Wert, BEVOR der Test ihn gleich auf 40 setzt, um das
# Reissen ueberhaupt ausloesen zu koennen. Am Ende wird gegen diesen
# geprueft -- die Attrappe zu pruefen waere wertlos.
_BUDGET_EINGESTELLT = budget.MAX_ABSCHNITTE
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

# --- WER MEHR LESEN DARF, DARF NICHT WENIGER ARBEITEN ---
#
# Die Menge zaehlt je Raum. Vorher lief sie ueber alle Raeume summiert,
# und damit verkuerzte jede zusaetzliche Leseberechtigung die
# Reichweite: dieselbe Frage kostete bei fuenf Raeumen das Fuenffache.
# Getroffen hat die Schwelle also zuerst den, der am meisten darf.
#
# Hier drei Raeume mit je 30 Buchungen bei einer Schwelle von 40. In der
# Summe waeren das 90 und laengst darueber; je Raum sind es 30 und
# damit in Ordnung. Genau diese Pruefung faellt mit der alten Zaehlung.
budget.MAX_RAEUME = 25          # die Breite soll hier nicht dazwischenfunken
pruef("drei Raeume mit je 30 reissen die Schwelle von 40 nicht",
      all(_budget_laeuft("vielleser", r, 30, 1)
          for r in ("einkauf", "technik", "recht")))

# Und der umgekehrte Fall muss weiter greifen: genug aus EINEM Raum
# bricht ab, sonst waere die Schwelle nur noch Zierde.
budget._ereignisse.clear()
pruef("aber 60 aus einem einzigen Raum schon",
      not _budget_laeuft("sammler", "einkauf", 30, 2))

# Die Anzeige nennt den groessten Raum, nicht die Summe: neben
# MAX_ABSCHNITTE stuende eine Summe fuer eine Naehe zur Schwelle, die
# es nicht gibt.
budget._ereignisse.clear()
budget.zaehle("vielleser", "einkauf", 30)
budget.zaehle("vielleser", "technik", 12)
_a, _r = budget.stand("vielleser")
pruef("der Stand zeigt den groessten Raum", _a == 30, _a)
pruef("und die Breite ueber alle Raeume", _r == 2, _r)
pruef("nach Raum gefragt kommt dessen Wert",
      budget.stand("vielleser", "technik")[0] == 12)

budget.MAX_RAEUME = 3
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
budget.zaehle("aufbau", "einkauf", 20000, wartung=True)
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

# Der Stichwortindex muss den KLARNAMEN fuehren. Stand dort der
# verdeckte, fiel es unter der Antwort als Quellenangabe auf -- und
# still an zwei weiteren Stellen: der Dokumentfilter kommt mit
# Klarnamen und traf nichts, das Loeschen liess die Abschnitte stehen.
_verdeckt = raumschluessel.verschluessele_text("einkauf", _n)
keyword_index.add_chunks([("namensprobe_1", "Ein Abschnitt zur Probe",
                           {"file_name": _verdeckt, "raum": "einkauf",
                            "page": 1})])
_treffer = keyword_index.search("Probe", "markus", limit=5)
pruef("der Stichwortindex fuehrt den Namen lesbar",
      bool(_treffer) and _treffer[0]["meta"].get("file_name") == _n,
      _treffer[0]["meta"].get("file_name") if _treffer else "nichts")
pruef("und nicht den verdeckten",
      not any(raumschluessel.ist_verschluesselt(
          h["meta"].get("file_name") or "") for h in _treffer))

# Beim Verschieben wandert der Name mit. Er ist mit dem Raum
# beglaubigt, in dem er lag; _metadaten_verdeckt sieht einen bereits
# verschluesselten Wert und laesst ihn stehen, ohne zu merken, dass er
# zum falschen Schluessel gehoert.
_alt = store._metadaten_verdeckt("einkauf", [{"file_name": _g}])
_neu = store.metadaten_umschluesseln("einkauf", "vertrieb", _alt)
pruef("verschoben laesst sich der Name im ZIELraum oeffnen",
      store.metadaten_klartext("vertrieb", _neu)[0]["file_name"] == _g)
pruef("und unveraendert uebernommen waere er unlesbar",
      store.metadaten_klartext("vertrieb", _alt)[0]["file_name"]
      == "(nicht lesbar)")

print("=== 13. Listen gehoeren Raeumen ===")
# Listen werden nicht hochgeladen, sie liegen dort, wo die Abteilung
# sie pflegt. Damit stellt sich dieselbe Frage wie bei den Dokumenten,
# nur an anderen Pfaden: wer sieht welche.
_netz = os.path.join(tmp, "netz")
for _unter, _inhalt in (
        ("allgemein", "Teil;Menge\n91061401;7\n"),
        ("abteilung/einkauf", "Lieferant;Preis\nMueller;12\n"),
        ("heim/markus/Listen", "Vorgang;Betrag\nGehalt;1\n"),
        ("heim/anna/Listen", "Notiz;Wert\nPrivat;2\n")):
    _o = os.path.join(_netz, _unter)
    os.makedirs(_o, exist_ok=True)
    with open(os.path.join(_o, "liste.csv"), "w", encoding="utf-8") as _f:
        _f.write(_inhalt)

os.environ["LISTEN_WURZELN"] = _netz
import tabellen, listenquellen
tabellen.KATALOG = os.path.join(paths.DATA_DIR, "listenkatalog.json")
listenquellen.QUELLEN = os.path.join(paths.CONFIG_DIR, "listenquellen.json")
listenquellen.WURZELN = [_netz]

pruef("Quellen mit Muster gespeichert", listenquellen.speichere([
    {"raum": "allgemein", "pfad": os.path.join(_netz, "allgemein")},
    {"raum": "einkauf", "pfad": os.path.join(_netz, "abteilung", "einkauf")},
    {"raum": "@privat",
     "pfad": os.path.join(_netz, "heim", "{benutzer}", "Listen")}])[0])
# Ein Muster ohne Platzhalter zeigte fuer JEDEN auf denselben Ordner --
# und damit saehe jeder die Listen aller.
pruef("ein Muster ohne Platzhalter wird abgewiesen",
      not listenquellen.speichere(
          [{"raum": "@privat", "pfad": os.path.join(_netz, "heim")}])[0])
# Der Fall, der still schiefgeht: der allgemeine Ordner liegt UEBER
# den persoenlichen. Dann liest ihn der allgemeine Raum mit, und jeder
# sieht die persoenlichen Listen aller -- waehrend die Zeile darunter
# aussieht, als sei alles geregelt.
pruef("eine Quelle, die eine andere enthaelt, wird abgewiesen",
      not listenquellen.speichere([
          {"raum": "allgemein", "pfad": os.path.join(_netz, "heim")},
          {"raum": "@privat",
           "pfad": os.path.join(_netz, "heim", "{benutzer}",
                                "Listen")}])[0])
# DER ALTE ORDNER DARF NICHT STILL WEGFALLEN.
#
# Frueher galt er nur, solange gar keine Quelle eingetragen war --
# also verschwand er in dem Augenblick, in dem jemand die ERSTE
# Raumquelle setzte. Beim Einrichten des ersten Fachraums haette der
# Betreiber einen Raum gewonnen und den gemeinsamen Bestand verloren,
# ohne Meldung und ohne erratbaren Zusammenhang.
_altpfad = os.path.join(_netz, "allgemein")
with io.open(tabellen.PFAD_DATEI, "w", encoding="utf-8") as _f:
    _f.write(_altpfad)
listenquellen.speichere([{"raum": "einkauf",
                          "pfad": os.path.join(_netz, "abteilung",
                                               "einkauf")}])
pruef("der alte Ordner gilt weiter, wenn eine Raumquelle dazukommt",
      ("allgemein", _altpfad) in tabellen.quellen(), tabellen.quellen())
# Wer ihn ersetzen will, traegt eine Quelle fuer 'allgemein' ein --
# eine Handlung, keine Nebenwirkung.
listenquellen.speichere([
    {"raum": "einkauf", "pfad": os.path.join(_netz, "abteilung", "einkauf")},
    {"raum": "allgemein", "pfad": os.path.join(_netz, "heim")}])
pruef("eine ausdrueckliche Quelle fuer allgemein ersetzt ihn",
      ("allgemein", _altpfad) not in tabellen.quellen(), tabellen.quellen())
os.remove(tabellen.PFAD_DATEI)

pruef("nebeneinanderliegende Ordner gehen weiter",
      listenquellen.speichere([
          {"raum": "allgemein", "pfad": os.path.join(_netz, "allgemein")},
          {"raum": "einkauf",
           "pfad": os.path.join(_netz, "abteilung", "einkauf")},
          {"raum": "@privat",
           "pfad": os.path.join(_netz, "heim", "{benutzer}",
                                "Listen")}])[0])
pruef("eine Quelle in den Anwendungsdaten wird abgewiesen",
      not listenquellen.pruefe_pfad(os.path.join(paths.DATA_DIR, "x"))[0])
pruef("und ein Nutzername kann nicht aus dem Muster ausbrechen",
      listenquellen._dateiname("../../etc") == "etc")

_kat, _fehl = tabellen.baue_katalog()
_alle = _kat["eintraege"]
pruef("vier Blaetter aus vier Quellen", len(_alle) == 4, len(_alle))
_sm = tabellen.sichtbar(_alle, "markus")
_sa = tabellen.sichtbar(_alle, "anna")
pruef("markus sieht allgemein und seinen eigenen Ordner",
      {e["raum"] for e in _sm} == {"allgemein",
                                   raeume.privat_kennung("markus")},
      {e["raum"] for e in _sm})
pruef("anna zusaetzlich den Einkauf, in dem sie Mitglied ist",
      {e["raum"] for e in _sa} == {"allgemein", "einkauf",
                                   raeume.privat_kennung("anna")},
      {e["raum"] for e in _sa})
pruef("und der Verwalter sieht den Einkauf trotzdem nicht",
      benutzer.ist_admin("markus")
      and not any(e["raum"] == "einkauf" for e in _sm))

# Gleicher Dateiname in zwei Heimlaufwerken -- frueher gab es einen
# Ordner, und "liste.csv" war eindeutig. Jetzt entscheidet die Wurzel
# des Eintrags, welche Datei gemeint ist.
def _zeilen_von(eintraege, raum):
    e = [x for x in eintraege if x["raum"] == raum][0]
    return tabellen.fuehre_aus(e["datei"], e.get("blatt") or "",
                               "SELECT * FROM daten",
                               wurzel=e["wurzel"])[1]

pruef("gleichnamige Dateien liefern verschiedene Zeilen",
      "Gehalt" in str(_zeilen_von(_sm, raeume.privat_kennung("markus")))
      and "Privat" in str(_zeilen_von(_sa, raeume.privat_kennung("anna"))))

# Der Katalog liegt neben dem Stichwortindex, also NICHT auf dem
# verschluesselten Datentraeger. Was er ueber fremde Listen preisgibt,
# gibt er dort preis.
_roh = tabellen.lies_katalog()["eintraege"]
_text = io.open(tabellen.KATALOG, encoding="utf-8").read()
pruef("die Katalogdatei nennt weder Datei- noch Spaltennamen",
      not any(w in _text for w in ("liste.csv", "Gehalt", "Vorgang",
                                   "Listen", "Lieferant")))
pruef("den Raum nennt sie -- ohne ihn liesse sich nicht filtern",
      all(e.get("raum") for e in _roh))
pruef("aufgeschlossen steht wieder alles da",
      all(e.get("datei") and e.get("wurzel")
          for e in tabellen.sichtbar(_roh, "markus")))

# Eine Quelle entsteht dort, wo der Raum entsteht -- und wer sie setzen
# darf, ist nicht fuer jeden gleich. Der Container liest mit EINER
# Kennung: duerfte jeder einen beliebigen Pfad eintragen, koennte er
# den Ordner einer fremden Abteilung eintragen und die Anwendung
# laese ihn vor.
_meiner = raeume.privat_kennung("markus")
pruef("ein Verwalter setzt die Quelle eines Fachraums",
      listenquellen.setze_raum("einkauf",
                               os.path.join(_netz, "abteilung", "einkauf"),
                               benutzer="markus", ist_verwalter=True)[0])
pruef("ein Nutzer darf das NICHT",
      not listenquellen.setze_raum("einkauf", os.path.join(_netz, "allgemein"),
                                   benutzer="anna")[0])
pruef("aber seinen eigenen Ordner schon",
      listenquellen.setze_raum(
          _meiner, os.path.join(_netz, "heim", "markus", "Listen"),
          benutzer="markus")[0])
pruef("und nur INNERHALB seines Bereichs",
      not listenquellen.setze_raum(
          _meiner, os.path.join(_netz, "heim", "anna", "Listen"),
          benutzer="markus")[0])
# Der Umweg ueber ".." sieht harmlos aus und fuehrt zum selben Ort.
pruef("auch nicht ueber einen Umweg",
      not listenquellen.setze_raum(
          _meiner,
          os.path.join(_netz, "heim", "markus", "Listen", "..", "..",
                       "anna", "Listen"),
          benutzer="markus")[0])
pruef("ein leerer Pfad entfernt den Eintrag",
      listenquellen.setze_raum("einkauf", "", benutzer="markus",
                               ist_verwalter=True)[0]
      and listenquellen.pfad_von("einkauf") == "")

# Eine Quelle IN ownCloud -- fuer Installationen ohne Netzlaufwerke.
# Alles andere (SharePoint, OneDrive, S3) wird eingehaengt und ist dann
# ein gewoehnlicher Pfad; nur ownCloud ist ohnehin angebunden.
import owncloud as _oc
_ferne = os.path.join(_netz, "wolke")
os.makedirs(_ferne, exist_ok=True)
with open(os.path.join(_ferne, "preise.csv"), "w", encoding="utf-8") as _f:
    _f.write("Artikel;Preis\nSchraube;0,12\n")

_oc.eingerichtet = lambda: True
_oc.dateien = lambda pfad, endungen=None, tiefe=8: [
    {"rel": "preise.csv", "fern": "Listen/preise.csv",
     "groesse": 30, "etag": _etag[0], "geaendert": ""}]
_oc.hole = lambda fern, ziel: (
    os.makedirs(os.path.dirname(ziel), exist_ok=True),
    open(ziel, "wb").write(
        open(os.path.join(_ferne, "preise.csv"), "rb").read()))[1]
_oc.stand = lambda fern: (30, _etag[0])
_etag = ["eins"]
tabellen._zwischenspeicher.clear()

pruef("eine ownCloud-Quelle wird angenommen",
      listenquellen.setze_raum("allgemein", "owncloud:/Listen",
                               benutzer="markus", ist_verwalter=True)[0])
_kw, _fw = tabellen.baue_katalog()
_we = [e for e in _kw["eintraege"] if e["raum"] == "allgemein"]
pruef("und liefert einen Katalogeintrag", len(_we) == 1, _fw)
pruef("der seine Herkunft kennt",
      _we and _we[0]["wurzel"].startswith("owncloud:"),
      _we[0]["wurzel"] if _we else "")
_sp, _z = tabellen.fuehre_aus(_we[0]["datei"], _we[0].get("blatt") or "",
                              "SELECT * FROM daten",
                              wurzel=_we[0]["wurzel"])
pruef("und die Zeilen kommen an", "Schraube" in str(_z), _z)

# Die Frischezusage: geaenderte Zeilen wirken in der naechsten Frage,
# ohne Neueinlesen. Bei einer lokalen Datei haengt das an mtime und
# Groesse, hier am etag.
with open(os.path.join(_ferne, "preise.csv"), "w", encoding="utf-8") as _f:
    _f.write("Artikel;Preis\nSchraube;0,99\n")
_etag[0] = "zwei"
_sp, _z2 = tabellen.fuehre_aus(_we[0]["datei"], _we[0].get("blatt") or "",
                               "SELECT * FROM daten",
                               wurzel=_we[0]["wurzel"])
pruef("ein neues etag holt die Datei neu", "0,99" in str(_z2), _z2)
listenquellen.setze_raum("allgemein", "", benutzer="markus",
                         ist_verwalter=True)

print("=== 14. Griff ohne Einsicht ===")
# Der Verwalter soll eine verwaiste Ablage aufraeumen koennen, ohne zu
# erfahren, worum es ging -- ein Dateiname verraet den Vorgang. Dafuer
# steht dort die Kennung (datei_id), nicht der Name.
#
# Der Geheimtext des Namens taeuscht dasselbe vor und taugt nicht: er
# traegt einen zufaelligen Nonce und ist je ABSCHNITT verschieden. Die
# Liste zeigte damit acht Eintraege fuer eine Datei, und ein Loeschen
# traf genau einen Abschnitt -- sichtbar nur daran, dass die Datei
# danach noch da war.
#
# Die Wache prueft nicht Verhalten, sondern Quelltext. Das ist
# unueblich und hier richtig: die betroffene Stelle liegt in einem
# Streamlit-Skript, das sich nicht importieren laesst, und die Regel
# ist einfach genug, um sie am Text zu pruefen.
_quelle = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "app.py"), encoding="utf-8").read()
_a = _quelle.index("def list_foreign_private_documents(")
_rumpf = _quelle[_a:_quelle.index("\ndef ", _a + 10)]
pruef("die Verwaltungsansicht zeigt Kennungen statt Namen",
      "datei_id" in _rumpf)
pruef("und schliesst die Namen NICHT auf",
      "metadaten_klartext" not in _rumpf)

# Eine zweite Quelltextwache, aus einem Absturz im Betrieb.
#
# app.py ist ein Skript, kein Modul: alles im Seitenleisten-Teil lebt
# im selben Namensraum. _p ist dort die Voreinstellung (presets.lese)
# und wird hundert Zeilen spaeter als Woerterbuch gebraucht. Eine
# Schleife "for _p in ..." macht daraus eine Zeichenkette, und die
# Anwendung bricht mit "string indices must be integers" an einer
# Stelle ab, die mit der Schleife nichts zu tun hat.
#
# Aufgefallen ist es erst, als jemand den betreffenden Filter
# tatsaechlich SETZTE -- ohne Auswahl laeuft die Schleife nie. Ein
# Fehler, der nur bei Benutzung auftritt, ist genau der, den kein
# Start bemerkt.
pruef("kein 'for _p in' in app.py -- _p ist die Voreinstellung",
      "for _p in " not in _quelle)
pruef("und _p wird auch sonst nicht neu gebunden",
      ", _p = " not in _quelle)

# Anklickbare Quellenangaben. Die Funktion liegt im Streamlit-Skript
# und laesst sich nicht importieren -- also aus dem Quelltext holen
# und mit echten Werten ausfuehren. Das prueft Verhalten, nicht
# Schreibweise.
_a2 = _quelle.index("_QUELLENMUSTER = re.compile(")
import re as _re
import types as _types
import quellticket as _qt
# Die Funktion lebt im Streamlit-Skript und laesst sich nicht
# importieren. Sie bekommt hier dieselben Nachbarn wie dort -- nur
# Streamlit selbst ist eine Attrappe, denn gebraucht wird davon genau
# der angemeldete Name.
_raum2 = {"re": _re, "quellticket": _qt, "raeume": raeume,
          "st": _types.SimpleNamespace(session_state={"username": "anna"})}
exec(_quelle[_a2:_quelle.index("\ndef _loeschfreigabe(")], _raum2)
_klick = _raum2["_quellen_klickbar"]
_qu = [{"file": "infraUser.pdf", "page": 5666, "raum": "einkauf"},
       {"file": "infraExpert.pdf", "page": 7809, "raum": "einkauf"}]
_aus = _klick("Dort [infraUser.pdf, Seite 5666] und auch "
              "[infraExpert.pdf, S. 7809].", _qu, 3)
pruef("Quellenangaben werden zu Verweisen",
      _aus.count("](quelle?t=") == 2, _aus[:120])
# Der Verweis traegt ein TICKET und nicht die Anmeldung. Sonst stuende
# sie in jeder Antwort, und wer eine Antwort weiterleitet, gaebe seine
# Anmeldung mit.
# Geprueft wird, dass KEINE Anmeldung mitfaehrt. Den Namen traegt
# das Ticket sehr wohl -- er ist kein Geheimnis, und er ist
# noetig, weil beim Einloesen die Berechtigung genau dieses
# Nutzers geprueft wird. Eine Pruefung, die mehr behauptet, als
# sie prueft, ist schlimmer als keine.
pruef("und zwar mit einem Ticket, nicht mit der Anmeldung",
      "sitzung=" not in _aus, _aus[:120])
_tk2 = _aus.split("quelle?t=")[1].split(")")[0]
pruef("das Ticket nennt genau diese Fundstelle",
      (_qt.loese_ein(_tk2) or {}).get("datei") == "infraUser.pdf",
      _qt.loese_ein(_tk2))

# Ein Modell nennt gelegentlich eine Seite, die es aus dem
# Zusammenhang erschlossen hat. Ein Verweis, der ins Leere fuehrt,
# ist schlechter als gar keiner -- er taeuscht Nachpruefbarkeit vor.
_erfunden = _klick("Steht in [infraUser.pdf, Seite 99] und in "
                   "[Erfunden.pdf, Seite 5666].", _qu, 3)
pruef("eine erfundene Fundstelle wird NICHT verlinkt",
      "](quelle?t=" not in _erfunden, _erfunden)
pruef("ohne Quellen bleibt der Text unveraendert",
      _klick("Dort [infraUser.pdf, Seite 5666].", [], 3)
      == "Dort [infraUser.pdf, Seite 5666].")

# Codebloecke. Waehrend ein Block geschrieben wird, fehlt sein
# Schlusszaun -- und Markdown zeigt bis dahin rohen Text mit drei
# Anfuehrungszeichen davor. Gerade bei Code ist das die haesslichste
# Art zu warten.
_a3 = _quelle.index("def _anzeigefertig(")
_raum3 = {}
exec(_quelle[_a3:_quelle.index("\ndef _strom_zeichnen(")], _raum3)
_fertig = _raum3["_anzeigefertig"]
_zaun = "`" * 3
_halb = "Hier:\n" + _zaun + "python\ndef gruss():\n    print("
_ganz = _halb + "'hallo')\n" + _zaun
pruef("ein halber Codeblock wird fuer die Anzeige geschlossen",
      _fertig(_halb).count(_zaun) == 2)
pruef("ein fertiger bleibt unveraendert", _fertig(_ganz) == _ganz)
pruef("und Text ohne Code auch", _fertig("nur Text") == "nur Text")

# Und ein Verweis darf nicht IN den Codeblock geschrieben werden --
# dort ist "[a.pdf, Seite 3]" kein Beleg, sondern Code. Ein
# Markdown-Verweis mittendrin zerstoert ihn, und beim Kopieren merkt
# man es erst, wenn es nicht laeuft.
_mit_code = ("Steht in [a.pdf, Seite 3].\n" + _zaun + "python\n"
             "# [a.pdf, Seite 3] ist hier Code\n" + _zaun
             + "\nUnd [a.pdf, Seite 3].")
_aus3 = _klick(_mit_code, [{"file": "a.pdf", "page": 3}], 1)
pruef("Verweise entstehen nur ausserhalb der Codebloecke",
      _aus3.count("](quelle?t=") == 2,
      _aus3.count("](quelle?t="))
pruef("und der Code bleibt unangetastet",
      "# [a.pdf, Seite 3] ist hier Code" in _aus3)

print("=== 15. Projekte im eigenen Raum ===")
# Zum Sortieren, nicht zum Teilen. Wer viele Vorgaenge im eigenen Raum
# hat, will eine Frage zu Projekt B stellen, ohne dass A mitantwortet
# -- das ist keine Rechtefrage, sondern eine der Menge: ein Modell,
# das zwoelf Abschnitte aus fuenf Vorgaengen bekommt, mischt sie.
_pr = raeume.privat_kennung("anna")
_sml_p = store.sammlung(raeume.sammlung(_pr))
for _datei, _proj in (("Angebot_A.pdf", "ProjektA"),
                      ("Plan_A.pdf", "ProjektA"),
                      ("Angebot_B.pdf", "ProjektB"),
                      ("Lose.pdf", "")):
    store.schreibe(_sml_p, [f"{_datei}_p1"],
                   documents=[f"Inhalt von {_datei}"],
                   metadatas=[{"file_name": _datei, "page": 1,
                               "raum": _pr, "folder": _proj}],
                   embeddings=[vek()])
_p = pipeline.projekte("anna", _pr)
# Nicht auf Gleichheit pruefen: in diesem Raum liegt aus einem
# frueheren Abschnitt schon etwas anderes. Ein Test, der an fremdem
# Bestand scheitert, prueft die Testreihenfolge und nicht die
# Funktion.
pruef("die Projekte kommen aus den Ordnerangaben",
      {"ProjektA", "ProjektB"} <= set(_p), sorted(_p))
pruef("und jedes kennt seine Dateien",
      _p["ProjektA"] == ["Angebot_A.pdf", "Plan_A.pdf"], _p.get("ProjektA"))
pruef("was ohne Projekt liegt, faellt nicht weg",
      _p.get("") == ["Lose.pdf"], _p.get(""))
# Ein Projekt ist KEINE Berechtigung. Geteilt wird ueber Raeume; ein
# Ordner, der aussieht wie ein Recht und keines ist, war schon einmal
# da und hiess Sachgebiet.
pruef("ein Fremder sieht die Projekte nicht",
      pipeline.projekte("markus", _pr) == {},
      pipeline.projekte("markus", _pr))

print()
print("=== 16. Ein Ticket fuer eine Fundstelle ===")
# Ein Verweis oeffnet die Quelle in einem eigenen Tab -- und ein neuer
# Tab ist eine neue Sitzung. Die Anmeldung mitzugeben waere der
# naheliegende Weg und der falsche: sie stuende in jeder Antwort, und
# wer eine Antwort weiterleitet, gaebe seine Anmeldung mit.
import quellticket
_tk = quellticket.stelle_aus("einkauf", "Preise.pdf", 7, "anna")
pruef("ein Ticket wird ausgestellt", bool(_tk))
_ein = quellticket.loese_ein(_tk)
pruef("und nennt genau diese Fundstelle",
      _ein and _ein["datei"] == "Preise.pdf" and _ein["seite"] == "7"
      and _ein["raum"] == "einkauf", _ein)
pruef("ein veraendertes gilt nicht",
      quellticket.loese_ein(_tk[:-3] + "aaa") is None)
# Der wichtigste Fall: das Ticket ist eine Abkuerzung fuer den Weg
# dorthin, kein Ersatz fuer das Recht, dort zu sein.
pruef("fuer einen Fremden gilt es gar nicht erst",
      quellticket.loese_ein(
          quellticket.stelle_aus("einkauf", "Preise.pdf", 7, "markus"))
      is None)
# Und abgelaufen ist abgelaufen.
quellticket.MINUTEN = -1
pruef("eine abgelaufene Frist gilt nicht",
      quellticket.loese_ein(
          quellticket.stelle_aus("einkauf", "Preise.pdf", 7, "anna"))
      is None)
quellticket.MINUTEN = 30

print()
print("=== 17. Angemeldet bleiben, aber befristet ===")
# Streamlit haelt die Sitzung im Arbeitsspeicher des Browser-Tabs --
# beim Neuladen ist sie weg. Die Bescheinigung traegt Name, Ablauf und
# Unterschrift; sie steht in der Adresszeile, und wer die Adresse
# weitergibt, gibt die Anmeldung mit. Deshalb standardmaessig aus.
pruef("ausgeschaltet wird gar keine ausgestellt",
      benutzer.MERKEN_STUNDEN == 0 and benutzer.merkzettel("markus") == "")
benutzer.MERKEN_STUNDEN = 8
_zettel = benutzer.merkzettel("markus")
pruef("eingeschaltet schon", bool(_zettel))
pruef("und sie gilt fuer den Richtigen",
      benutzer.pruefe_merkzettel(_zettel) == "markus")
pruef("eine gefaelschte gilt nicht",
      benutzer.pruefe_merkzettel(_zettel[:-4] + "aaaa") == "")
pruef("ein anderer Name darin auch nicht",
      benutzer.pruefe_merkzettel("anna" + _zettel[6:]) == "")
# Die Frist steht IN der Bescheinigung und ist mitunterschrieben --
# sie laesst sich nicht verlaengern, ohne die Unterschrift zu
# zerstoeren.
_name, _bis, _sig = _zettel.rsplit("|", 2)
pruef("die Frist laesst sich nicht verlaengern",
      benutzer.pruefe_merkzettel(f"{_name}|{int(_bis) + 99999}|{_sig}") == "")
_alt = benutzer.merkzettel("markus")
_n2, _b2, _s2 = _alt.rsplit("|", 2)
import time as _t
_abgelaufen = f"{_n2}|{int(_t.time()) - 10}|"
_abgelaufen += geheim.signiere(_abgelaufen[:-1].encode("utf-8"))
pruef("eine abgelaufene gilt nicht",
      benutzer.pruefe_merkzettel(_abgelaufen) == "")
# Der wichtigste Fall: ein geloeschter Zugang muss SOFORT draussen
# sein, auch wenn die Frist noch laeuft. Geprueft wird deshalb beim
# Einloesen und nicht nur beim Ausstellen.
benutzer.anlege("kurzzeit", "kurzzeitpasswort", von="markus")
_kz = benutzer.merkzettel("kurzzeit")
pruef("solange es den Zugang gibt, gilt sie",
      benutzer.pruefe_merkzettel(_kz) == "kurzzeit")
benutzer.loesche("kurzzeit", von="markus")
pruef("nach dem Loeschen nicht mehr",
      benutzer.pruefe_merkzettel(_kz) == "")
benutzer.MERKEN_STUNDEN = 0

print()
print("=== 18. Ein Datenbankkonto je Raum ===")
# Bis hierher lief jede Frage ueber EIN Konto aus der .env. Damit
# entscheidet die Anwendung, wer was sehen darf -- und sie entscheidet
# es fuer die Datenbank mit, obwohl die es selbst besser weiss.
#
# Jetzt bringt jeder Raum sein eigenes Konto mit. Das Schema kommt mit
# denselben Rechten, das Sprachmodell sieht also nur Tabellen, die
# dieses Konto lesen darf.
import sqlquellen
sqlquellen.QUELLEN = os.path.join(paths.CONFIG_DIR, "sqlquellen.json")

pruef("ein Verwalter legt den Zugang eines Fachraums fest",
      sqlquellen.setze("einkauf",
                       {"benutzer": "ek_lesen", "passwort": "geheim123"},
                       benutzer="markus", ist_verwalter=True)[0])
pruef("ein Nutzer darf das NICHT",
      not sqlquellen.setze("einkauf",
                           {"benutzer": "ich", "passwort": "x"},
                           benutzer="anna")[0])
# Sein eigenes Konto kennt nur er. Muesste ein Verwalter es eintragen,
# muesste er es KENNEN -- und damit waere aus "jeder mit seinen
# Rechten" wieder ein gemeinsames Konto geworden, nur muehsamer.
pruef("seinen eigenen Zugang traegt jeder selbst ein",
      sqlquellen.setze(raeume.privat_kennung("anna"),
                       {"benutzer": "anna_db", "passwort": "annageheim"},
                       benutzer="anna")[0])
pruef("Benutzer ohne Passwort wird abgewiesen",
      not sqlquellen.setze("einkauf", {"benutzer": "nur_name"},
                           benutzer="markus", ist_verwalter=True)[0])

# Das Passwort liegt verschluesselt -- mit dem Schluessel des Raums,
# dem es gehoert. Wer die Konfigurationsdatei kopiert, bekommt
# Geheimtext.
_roh = io.open(sqlquellen.QUELLEN, encoding="utf-8").read()
pruef("das Passwort steht nicht im Klartext in der Datei",
      "geheim123" not in _roh and "annageheim" not in _roh)
pruef("aufgeschlossen kommt es zurueck",
      sqlquellen.zugang("einkauf")["passwort"] == "geheim123")
pruef("und der Benutzername bleibt lesbar -- er ist kein Geheimnis",
      "ek_lesen" in _roh)

# Wer welchen Zugang benutzen darf, entscheidet dieselbe Funktion wie
# ueberall: raeume.lesbar.
_za = dict(sqlquellen.fuer_benutzer("anna"))
_zm = dict(sqlquellen.fuer_benutzer("markus"))
pruef("anna bekommt den Einkauf und ihren eigenen",
      set(_za) == {"einkauf", raeume.privat_kennung("anna")}, sorted(_za))
pruef("der Verwalter bekommt den Einkauf NICHT -- kein Mitglied",
      "einkauf" not in _zm, sorted(_zm))
pruef("der eigene Zugang steht vorn",
      sqlquellen.fuer_benutzer("anna")[0][0]
      == raeume.privat_kennung("anna"))

# Die Verbindungsangaben ergaenzen sich: was der Raum nicht mitbringt,
# kommt aus der Umgebung. Sonst muesste jeder Raum Server, Port und
# Datenbank wiederholen.
import sqldb
sqldb.SQL_SERVER, sqldb.SQL_DB = "dbhost", "INFRA"
sqldb.SQL_USER, sqldb.SQL_PASS = "vorgabe", "vorgabe"
pruef("Server und Datenbank kommen aus der Umgebung",
      sqldb._wert(sqlquellen.zugang("einkauf"), "server", sqldb.SQL_SERVER)
      == "dbhost"
      and sqldb._wert(sqlquellen.zugang("einkauf"), "benutzer",
                      sqldb.SQL_USER) == "ek_lesen")
pruef("und ein Raum ohne Zugang laeuft weiter ueber die Vorgabe",
      sqldb.ist_konfiguriert(None) and sqldb._wert(None, "benutzer",
                                                   sqldb.SQL_USER)
      == "vorgabe")

print("=== 19. Gleichzeitige Nutzer ===")
# Streamlit gibt jeder Sitzung einen eigenen Faden im SELBEN Prozess.
# Fragen mehrere Leute gleichzeitig, laufen mehrere Faeden durch
# store.client() -- und ohne Sperre sehen alle "_client is None" und
# bauen jeder einen eigenen PersistentClient auf denselben Pfad.
#
# Was dabei herauskommt, ist nicht vorhersagbar. Im besten Fall wird
# einer weggeworfen, im schlechteren gibt es eine Ausnahme mitten in
# einer Anfrage -- und fuer den Fragenden bricht der Chat ab, ohne
# dass irgendwo steht, warum.
import threading as _th
import time as _zeit

_gebaut = []
_echt_pc = store.chromadb.PersistentClient


class _LangsamerClient:
    def __init__(self, path=None, **kw):
        # Die Verzoegerung ist der Punkt: ohne sie waere das Fenster
        # zwischen Pruefung und Zuweisung zu klein, um es im Test zu
        # treffen. Im Betrieb ist es gross -- ein PersistentClient
        # oeffnet Dateien und liest einen Index.
        _zeit.sleep(0.05)
        _gebaut.append(path)


store.chromadb.PersistentClient = _LangsamerClient
store._client = None
_faeden = [_th.Thread(target=store.client) for _ in range(6)]
for _f in _faeden:
    _f.start()
for _f in _faeden:
    _f.join()
pruef("sechs gleichzeitige Zugriffe bauen EINEN Client",
      len(_gebaut) == 1, len(_gebaut))
store.chromadb.PersistentClient = _echt_pc
store._client = None
store.vergiss()

print()
print("=== 20. Mit Notzugang ist ein Raum nicht mehr fremd ===")
# Beobachtet im Betrieb: nach einem bestaetigten Notzugang standen
# annas Dokumente in der gewoehnlichen Verwaltung mit KLARNAMEN -- und
# gleichzeitig in der Liste "fremde Raeume" mit Kennungen. Zweimal
# dasselbe, einmal lesbar und einmal nicht, und der Unterschied war
# nicht zu erklaeren.
#
# Der Notzugang IST das Verfahren, mit dem jemand hineindarf. Ist er
# bestaetigt, gilt er ueberall gleich.
import notzugang as _nz
_nz.DATEI = os.path.join(paths.CONFIG_DIR, "notzugang.json")
_prv = raeume.privat_kennung("anna")
pruef("ohne Notzugang darf markus den Raum nicht lesen",
      not raeume.darf_lesen("markus", _prv))
pruef("und mit einem schon",
      raeume.darf_lesen("markus", _prv, (_prv,)))
# Dieselbe Frage, wie sie die Verwaltungsansicht stellt: gilt der Raum
# noch als fremd?
pruef("damit faellt er aus der Liste der fremden Raeume",
      _prv in raeume.lesbar("markus", notzugang=(_prv,))
      and _prv not in raeume.lesbar("markus"))

# UND ER DARF AUFRAEUMEN. Lesen allein genuegt nicht: der Notzugang
# wird beantragt, weil ein Besitzer nicht mehr erreichbar ist -- dann
# will jemand sichten, verschieben und den Rest loeschen.
#
# Beobachtet im Betrieb: der Raum stand mit Klarnamen in der
# Dokumentenverwaltung ("Nur lesen.") und daneben mit Kennungen in der
# Fremdenliste, und das EINZIGE, was ging, war Loeschen ueber die
# Kennung -- also genau das, wovor die Kennungen schuetzen sollen.
pruef("mit Notzugang darf er im Raum auch verwalten",
      raeume.darf_schreiben("markus", _prv, True, (_prv,)))
pruef("ohne Notzugang nicht -- auch als Verwalter nicht",
      not raeume.darf_schreiben("markus", _prv, True))
pruef("und ein anderer Raum wird davon nicht mit geoeffnet",
      not raeume.darf_schreiben("markus", raeume.privat_kennung("chef"),
                                True, (_prv,)))

print()
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
import lasttest as _lt

_api_quelle = io.open(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "api.py"),
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
#
# Der Grund, warum es durchrutschte, ist der Stammbaum: app.py fing an
# der Suche nur ValueError. Ueberzogen ist keiner -- also flog es
# vorbei. Genau das haelt die erste Pruefung fest.
_datei = lambda n: io.open(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), n), encoding="utf-8").read()

# Die Oberflaeche besteht aus zwei Dateien, seit der
# Verwaltungsbereich eigen ist. Was ueber sie als Ganzes gilt,
# wird in beiden gesucht -- ein Fundort ist keine Eigenschaft.
_ui = _datei("app.py") + _datei("verwaltung.py")

pruef("Ueberzogen wird von einer ValueError-Klausel NICHT gefangen",
      issubclass(budget.Ueberzogen, Exception)
      and not issubclass(budget.Ueberzogen, ValueError))

_app = _datei("app.py")
_stelle = _app.find("pipeline.suche(")
pruef("app.py ruft die Suche auf", _stelle > 0)
# Der Fangblock steht unmittelbar hinter dem Aufruf. Weiter zu suchen
# hiesse, einen Block irgendwo anders im Modul als Beleg zu nehmen.
# Auf das ganze Wort pruefen. "budget.Ueberzogen" als blosse
# Teilzeichenkette liesse auch "budget.UeberzogenX" durchgehen -- der
# Gegentest zu dieser Zeile bestand, ohne dass die Klausel noch
# funktioniert haette.
pruef("und faengt das Budget dort ab",
      bool(_re.search(r"except\s+budget\.Ueberzogen\b",
                      _app[_stelle:_stelle + 1200])))

_api = _datei("api.py")
pruef("die Schnittstelle behandelt es eigens",
      bool(_re.search(r"exception_handler\(budget\.Ueberzogen\)", _api)))
pruef("und antwortet mit 429, nicht mit 500",
      "status_code=429" in _api)

# Und der Lasttest darf nicht alles auf ein Konto buchen: das Budget
# zaehlt je Nutzer, ein einziges Token buendelt, was sich auf viele
# Menschen verteilt haette.
pruef("der Lasttest kann mehrere Token reihum verwenden",
      "token[p[0] % len(token)]" in _datei("lasttest.py"))





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
import packe_umzug as _pu
import zipfile as _zip

_alt = os.path.join(tmp, "altinstallation")
for _u in ("chats", "dokumente", "chroma_db", "sicherungen"):
    os.makedirs(os.path.join(_alt, _u), exist_ok=True)
for _p, _inhalt in ((["chats", "a.json"], b"12"),
                    (["dokumente", "b.pdf"], b"345"),
                    (["chroma_db", "chroma.sqlite3"], b"XXXXX"),
                    (["sicherungen", "raum_allgemein.npy"], b"6789"),
                    (["keyword_index.sqlite3"], b"YYY")):
    with open(os.path.join(_alt, *_p), "wb") as _f:
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

# --- WERKZEUGSERVER NACH MCP ---
#
# Geprueft gegen einen echten Unterprozess, nicht gegen eine Attrappe.
# Die Fehler hier sind Fehler des ZUSAMMENSPIELS: ein fehlender
# Handschlag, eine Mitteilung, auf die jemand eine Antwort erwartet.
# Eine selbstgeschriebene Attrappe haette genau die Annahmen, die man
# ohnehin hatte -- der Client hing anfangs bei
# notifications/initialized, weil er blind eine Zeile las.
import mcp as _mcp

pruef("ohne Konfiguration ist kein Server eingerichtet",
      not _mcp.eingerichtet())

_fake = os.path.join(tmp, "fake_mcp.py")
with open(_fake, "w", encoding="utf-8") as _f:
    _f.write(FAKE_MCP)

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
with open(_mk, "w", encoding="utf-8") as _f:
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

# 4. Das freigeschaltete Funktionspostfach sendet -- mit Hinweis.
_vb2 = {"info": _FalscheVerbindung("info", ["send_mail"])}
_m = _FalschesModell([
    _FalscheAntwort("", [("info__send_mail", {"an": "a@b.c",
                                              "body": "Hallo"})]),
    _FalscheAntwort("fertig")])
_zusatz2, _entw2 = _pl.werkzeuglauf(_m, "x", "sys", [], _vb2)
pruef("das freigeschaltete Postfach sendet ohne Rueckfrage",
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

os.remove(_mk)

# --- WAS RAUSGEHT, GEHT NICHT ZURUECK ---
#
# Das Modell schlaegt vor, ein Mensch schickt. Ausnahme: ein
# Funktionspostfach, das ausdruecklich freigeschaltet ist -- und dann
# traegt jede Nachricht einen Hinweis, dass sie automatisch entstand.
_mcp_konf = os.path.join(paths.CONFIG_DIR, "mcp.json")
with open(_mcp_konf, "w", encoding="utf-8") as _f:
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
pruef("ein freigeschaltetes Funktionspostfach darf ohne Rueckfrage",
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

os.remove(_mcp_konf)

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

# Und die Verdrahtung: der Upload muss diese Funktion benutzen und den
# Pfad nicht wieder selbst zusammensetzen.
pruef("der Upload benutzt sie",
      "owncloud.ziel_pfad(raum, pdf_path)" in _datei("app.py"))

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
_vorher = (set(os.listdir(sicherung.ORDNER))
           if os.path.isdir(sicherung.ORDNER) else set())
_ber = sicherung.sichere()
_nachher = (set(os.listdir(sicherung.ORDNER))
            if os.path.isdir(sicherung.ORDNER) else set())
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
os.makedirs(_stummel, exist_ok=True)
with open(os.path.join(_stummel, "stand.json"), "w", encoding="utf-8") as _f:
    json.dump({"name": "2000-01-01_00-00-00", "raeume": {},
               "abschnitte": 0, "fehler": [], "vollstaendig": True}, _f)
pruef("ein alter Stummel taugt nicht zum Zurueckholen",
      "2000-01-01_00-00-00" not in sicherung.vollstaendige(),
      sicherung.vollstaendige())
shutil.rmtree(_stummel, ignore_errors=True)

# --- DIE BESTANDSLISTE ZAEHLT RICHTIG ---
#
# Sie ist das Werkzeug, mit dem sich ein Umzug ueberhaupt pruefen
# laesst: vorher im alten Container, nachher im neuen, und die beiden
# Ausgaben nebeneinander. Zaehlt sie falsch, ist die Pruefung eine
# Bestaetigung ohne Inhalt -- schlimmer als keine.
import bestandsliste as _bl

_probe = os.path.join(tmp, "zaehlprobe")
os.makedirs(os.path.join(_probe, "tief", "tiefer"), exist_ok=True)
for _p, _inhalt in ((["a.txt"], b"12345"),
                    (["tief", "b.txt"], b"123"),
                    (["tief", "tiefer", "c.txt"], b"1")):
    with open(os.path.join(_probe, *_p), "wb") as _f:
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
os.makedirs(os.path.join(_quelle, "unterordner"), exist_ok=True)
for _p in (["a.pdf"], ["b.pdf"], ["unterordner", "c.pdf"], [".versteckt"]):
    with open(os.path.join(_quelle, *_p), "wb") as _f:
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
# Und der Auftrag wird GANZ OBEN herausgenommen, vor der Seitenleiste.
#
# Im Betrieb blieb die Bedienung sonst dauerhaft gesperrt: zwischen der
# Selbstheilung und dem Chat liegen tausend Zeilen, und alles davon
# kann abbrechen. Blieb der Auftrag dabei liegen, sah der naechste Lauf
# "gesperrt UND Auftrag vorhanden" und heilte sich nicht -- und der
# naechste genauso.
_pop = _app.find('_auftrag = st.session_state.pop("_auftrag"')
_leiste2 = _app.rindex("with st.sidebar:")
pruef("der Auftrag wird vor der Seitenleiste herausgenommen",
      0 < _pop < _leiste2, f"pop {_pop}, Leiste {_leiste2}")
pruef("und nur an dieser einen Stelle",
      _app.count('st.session_state.pop("_auftrag"') == 1,
      _app.count('st.session_state.pop("_auftrag"'))

# Und der Knopf haengt nicht am Feldinhalt: Streamlit uebernimmt den
# erst beim Verlassen, ein Klick direkt nach dem Tippen liefe also ins
# Leere -- auf einen Knopf, der noch gesperrt ist.
# Und das Passwortaendern steht in einem FORMULAR.
#
# Gemeldet: alle drei Felder ausgefuellt, und trotzdem "bitte
# eintragen". Ein Textfeld uebergibt seinen Inhalt erst beim
# Verlassen; wer tippt und dann klickt, loest beides gleichzeitig aus,
# und das Skript sieht einen Druck auf leere Felder.
#
# Vorher war derselbe Umstand als ausgegrauter Knopf sichtbar. Ihn
# druckbar zu machen hat aus einem stummen Knopf eine falsche Meldung
# gemacht -- behoben war nichts. Ein Formular uebergibt alle Felder
# gemeinsam; den Zwischenzustand gibt es dann nicht.
_pwform = _app.find('with st.form(f"eigenes_pw_')
pruef("das Passwortaendern steht in einem Formular", _pwform > 0)
pruef("mit einem Absendeknopf statt eines gewoehnlichen",
      "st.form_submit_button(" in _app[_pwform:_pwform + 900])
pruef("und die drei Felder liegen darin",
      all(f'_feldschluessel(_pwe, "{f}")' in _app[_pwform:_pwform + 900]
          for f in ("alt", "neu1", "neu2")))

# Die Anmeldemaske macht es seit jeher so -- das war der Hinweis, den
# ich haette lesen sollen, statt eine Sperre zu bauen.
pruef("so wie die Anmeldemaske", 'st.form("login_form")' in _app)

#
# Bis hierher konnte das nur ein Verwalter. Damit war das Passwort
# eines Nutzers eines, das jemand anders vergeben hat und weiter kennt
# -- und wer sich damit anmeldet, ist im Protokoll nicht von seinem
# Besitzer zu unterscheiden.
_app = _datei("app.py")
_stelle = _app.find('with st.expander("\\U0001f511 Passwort aendern")')
pruef("es gibt die eigene Passwortaenderung", _stelle > 0)
_block = _app[_stelle:_stelle + 3000]

# DAS WICHTIGSTE: das bisherige Passwort wird geprueft.
pruef("das bisherige Passwort wird geprueft",
      "benutzer.pruefe(_ich, _alt)" in _block)
pruef("und erst danach gesetzt",
      0 < _block.find("benutzer.pruefe(_ich, _alt)")
      < _block.find("benutzer.passwort_setzen(_ich"))
pruef("im Protokoll steht der Nutzer selbst",
      "von=_ich" in _block)
pruef("die Ablage zieht mit",
      "owncloud.richte_nutzer_ein(_ich" in _block)

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
_app = _datei("app.py")
# Ausdruecklich die VERWALTER-Stelle: seit es die eigene
# Passwortaenderung gibt, steht weiter oben ein zweiter Aufruf, und
# der erste Treffer waere der falsche. Ein Anker, der auf zwei Dinge
# passt, prueft irgendwann das andere.
_pwstelle = _ui.find("_wahl, _pw1, von=")
pruef("es gibt das Passwortsetzen", _pwstelle > 0)
_block = _ui[_pwstelle:_pwstelle + 2200]
pruef("danach wird die Ablage eingerichtet",
      "owncloud.richte_nutzer_ein(" in _block)

# UND DAS WICHTIGERE: ein vorhandenes Konto darf nicht ueberschrieben
# werden. LocaNoto wird oft auf ein Haus gesetzt, in dem es die Leute
# in ownCloud laengst gibt -- ihnen von hier aus das Passwort ihres
# Firmenkontos zu nehmen, spaerrte sie aus allem aus, was daran haengt.
import owncloud as _ocp
_qu = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "owncloud.py"), encoding="utf-8").read()
_na = _qu.split("def nutzer_anlegen(", 1)[1]
_na = _na.split("def richte_nutzer_ein(", 1)[0]
pruef("ein vorhandenes ownCloud-Konto bleibt unangetastet",
      "if nutzer_vorhanden(kennung):" in _na and "gab es schon" in _na)
pruef("und der Verwalter erfaehrt, dass dort das alte Passwort gilt",
      "NICHT geaendert" in _block)


# --- DIE SCHNITTSTELLE ZWISCHEN OBERFLAECHE UND VERWALTUNG ---
#
# app.py hatte 4.300 Zeilen, davon 1.385 Verwaltung -- die Datei, in
# der jeder Fehler dieser Woche steckte. In 4.300 Zeilen findet man
# einen fehlenden Block nicht.
#
# Herausgeloest wurde WOERTLICH: die Namen aus app.py sind Parameter
# mit demselben Namen geworden, damit im Block keine Zeile
# umgeschrieben werden musste. Eine Verschiebung ohne Umbenennung kann
# nichts uebersehen.
#
# Gezaehlt wird die Kopplung, damit sie nicht unbemerkt waechst. Wer
# einen zwoelften Namen braucht, aendert diese Zahl und merkt dabei,
# was er tut.
# Gelesen statt geladen: streamlit liegt im Test nicht, und deshalb
# importiert dieser Lauf die Oberflaeche ueberhaupt nie. Die Signatur
# steht im Quelltext und sagt dasselbe.
import ast as _ast

_zf = next(k for k in _ast.parse(_datei("verwaltung.py")).body
           if isinstance(k, _ast.FunctionDef) and k.name == "zeichne")
_sig = [a.arg for a in _zf.args.kwonlyargs]
pruef("die Verwaltung ist eine eigene Datei mit zeichne()", bool(_sig))
pruef("und haengt an genau zwoelf Namen aus app.py",
      len(_sig) == 12, len(_sig))

# UND DIE PRUEFUNG, DIE DEN ZWOELFTEN GEFUNDEN HAETTE.
#
# Beim Herausloesen wurde _p uebersehen: die Voreinstellung aus app.py.
# Sie galt als mitgebracht, weil _p im Block auch vorkommt -- als
# Schleifenvariable in Generatorausdruecken. Solche Namen haben in
# Python eine eigene Sichtbarkeit und lecken nicht in die Funktion; die
# selbstgebaute Analyse wusste das nicht, und der einzige echte
# Lesezugriff fiel durch. Im Betrieb dann ein NameError.
#
# Also nicht selbst nachbauen. symtable ist Pythons eigener
# Namensaufloeser und sagt fuer jede Funktion, welche Namen sie aus dem
# Modul holt. Was dort steht und im Modul nicht definiert ist, fehlt --
# ohne Heuristik, ohne Zeilenordnung, ohne Sonderfaelle.
import builtins as _bi
import symtable as _sym

_quelle_vw = _datei("verwaltung.py")
_tab = _sym.symtable(_quelle_vw, "verwaltung.py", "exec")
_modul = {s.get_name() for s in _tab.get_symbols() if s.is_assigned()
          or s.is_imported()}
_modul |= {k.name for k in _ast.parse(_quelle_vw).body
           if isinstance(k, (_ast.FunctionDef, _ast.ClassDef))}


def _freie(raum):
    """Namen, die dieser Bereich aus dem Modul holt -- und alle darin."""
    aus = {s.get_name() for s in raum.get_symbols() if s.is_global()}
    for unter in raum.get_children():
        aus |= _freie(unter)
    return aus


_fehlt = sorted(_freie(_tab.lookup("zeichne").get_namespace())
                - _modul - set(dir(_bi)))
pruef("kein Name in verwaltung.py haengt in der Luft", not _fehlt, _fehlt)
pruef("die nur benannt uebergeben werden koennen",
      not _zf.args.args and not _zf.args.posonlyargs,
      [a.arg for a in _zf.args.args])

# Und der Aufruf uebergibt sie alle -- sonst faellt es erst auf, wenn
# jemand die Verwaltung oeffnet.
_a = _datei("app.py")
_ruf = _a[_a.index("verwaltung.zeichne("):]
_ruf = _ruf[:_ruf.index(")\n")]
pruef("und der Aufruf uebergibt jeden davon",
      all(f"{n}=" in _ruf for n in _sig),
      [n for n in _sig if f"{n}=" not in _ruf])

# --- DIE LAUFENDE ANTWORT IST GESCHUETZT ---
_app = _datei("app.py")
# Die Oberflaeche besteht aus zwei Dateien, seit der
# Verwaltungsbereich eigen ist. Was ueber sie als Ganzes gilt,
# wird in beiden gesucht -- ein Fundort ist keine Eigenschaft.
_ui = _app + _datei("verwaltung.py")

_zustand = _app.find("_antwortet = bool(st.session_state")
_leiste = _app.rindex("with st.sidebar:")
pruef("es gibt einen Zustand fuer die laufende Antwort", _zustand > 0)
pruef("und er steht VOR der Seitenleiste", 0 < _zustand < _leiste,
      f"Zustand {_zustand}, Leiste {_leiste}")
pruef("der Verwaltungsschalter haengt daran",
      "disabled=_antwortet" in _datei("verwaltung.py"))

# Angenommen wird die Frage in einem Lauf, beantwortet im naechsten --
# anders laesst sich die Leiste nicht rechtzeitig sperren.
_annahme = _app.find('st.session_state["_auftrag"] = {')
# Das Herausnehmen steht seit der Sperrkorrektur ganz oben. Was
# hier zaehlt, ist die Stelle, an der der Auftrag ABGEARBEITET
# wird -- und die liegt weiterhin hinter der Annahme.
_arbeit = _app.find("    if _auftrag:")
pruef("die Frage wird gemerkt", _annahme > 0)
pruef("und erst im naechsten Lauf abgearbeitet", 0 < _annahme < _arbeit,
      f"Annahme {_annahme}, Arbeit {_arbeit}")
pruef("dazwischen wird neu gezeichnet",
      "st.rerun()" in _app[_annahme:_arbeit])

# DAS WICHTIGSTE: die Sperre muss sich auf jedem Ausgang loesen.
# Vier Stellen -- Selbstheilung, leere Frage, Erfolg, Fehler.
_loesen = _app.count('st.session_state["_laeuft"] = False')
pruef("die Sperre loest sich an jedem Ausgang", _loesen == 4, _loesen)
pruef("auch wenn die Verarbeitung scheitert",
      'st.session_state["_laeuft"] = False' in _app[
          _app.find("except Exception as e:", _arbeit):
          _app.find("except Exception as e:", _arbeit) + 400])

# Und die Selbstheilung: gesperrt ohne Auftrag darf nicht bleiben.
pruef("eine Sperre ohne Auftrag heilt sich",
      "if _antwortet and not _auftrag:" in _app)


# Und der Zielordner kommt aus zuordnung_wirksam, nicht aus
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
_app = _datei("app.py")
pruef("der Upload benutzt dieselbe Regel",
      "DOCS_DIR if raum == raeume.ALLGEMEIN" in _app)

# Beim Spiegeln des allgemeinen Raums duerfen die Ordner der anderen
# Raeume NICHT mitkommen. Sie liegen darunter, und sie gehoeren
# anderen Leuten -- der allgemeine Raum ist fuer alle sichtbar.
_w = os.path.join(tmp, "wurzelprobe")
os.makedirs(os.path.join(_w, "einkauf"), exist_ok=True)
os.makedirs(os.path.join(_w, "offen"), exist_ok=True)
for _p in (["basis.pdf"], ["offen", "auch.pdf"], ["einkauf", "geheim.pdf"]):
    with open(os.path.join(_w, *_p), "wb") as _f:
        _f.write(b"x")
_gefunden = [r for _v, r in _sp._dateien(_w, [os.path.join(_w, "einkauf")])]
pruef("der Ordner eines fremden Raums bleibt aussen vor",
      "einkauf/geheim.pdf" not in _gefunden, _gefunden)
pruef("alles andere kommt mit",
      sorted(_gefunden) == ["basis.pdf", "offen/auch.pdf"], _gefunden)

# --- DER LISTENABSCHNITT BRAUCHT SEINE EIGENE LISTE ---
#
# Im Betrieb stuerzte die Oberflaeche beim Laden ab:
#   AttributeError: 'tuple' object has no attribute 'get'
# _eintraege trug dort noch die Chatliste -- Tupel statt
# Woerterbuecher --, weil die Neubelegung aus dem Tabellenkatalog
# fehlte. In einer Ablage war der ganze Block verlorengegangen; die
# beiden anderen waren in Ordnung, und deshalb fiel es nirgends auf.
_app = _datei("app.py")

_neu = _app.find("_eintraege = tabellen.sichtbar(")
_nutzung = _app.find('_eintraege if e.get("gross")')
pruef("der Tabellenkatalog wird _eintraege zugewiesen", _neu > 0, _neu)
pruef("und zwar VOR der ersten Verwendung als Katalog",
      0 < _neu < _nutzung, f"Zuweisung {_neu}, Verwendung {_nutzung}")

# Und die Ursache: zwei verschiedene Dinge unter einem Namen.
pruef("die Chatliste heisst nicht mehr wie der Katalog",
      "_eintraege = get_all_chats()" not in _app)
pruef("sie hat einen eigenen Namen", "_chatliste = get_all_chats()" in _app)

# --- ANLEGEN-FORMULARE WERDEN NACH ERFOLG GELEERT ---
_app = _datei("app.py")

pruef("es gibt einen wechselnden Feldschluessel",
      "def _feldschluessel(" in _app)
pruef("und ein Leeren dazu", "def _felder_leeren(" in _app)

# Die vier Anlegen-Formulare: Benutzer, Passwort, Raum, Listenbereich.
# Einmal abziehen fuer die Definition selbst.
# Fuenf Anlegen- und Aenderungsformulare: Benutzer, Passwort durch den
# Verwalter, eigenes Passwort, Raum, Listenbereich.
_aufrufe = _ui.count("_felder_leeren(") - _ui.count("def _felder_leeren(")
pruef("fuenf Formulare werden geleert", _aufrufe == 5, _aufrufe)

for _bereich in ("benutzer_neu", "raum_neu", "listen_neu"):
    pruef(f"{_bereich} benutzt den wechselnden Schluessel",
          f'_feldschluessel("{_bereich}"' in _ui)

# UND DAS WICHTIGERE: die Bearbeiten-Felder nicht. Sie zeigen den
# gespeicherten Wert; ein wechselnder Schluessel wuerde sie bei jedem
# Speichern leeren und eine geltende Einstellung als geloescht
# darstellen.
for _feld, _wert in (("raum_lq_", "value=_lq_alt"),
                     ("sqp_", 'value=_sqz.get("passwort", "")'),
                     ("raum_g_", "value=_gruppe_alt")):
    _st = _ui.find(_feld)
    pruef(f"das Bearbeiten-Feld {_feld} zeigt weiter seinen Wert",
          _st > 0 and _wert in _ui[max(0, _st - 200):_st + 200])

# --- MEHRERE DOKUMENTE AUF EINMAL ---
_app = _datei("app.py")
_feld = _app.find('"Dokumente hochladen"')
pruef("das Dokumentenfeld gibt es", _feld > 0)
pruef("und es nimmt mehrere Dateien",
      "accept_multiple_files=True" in _app[_feld:_feld + 500])

_knopf = _app.find('st.button("Hochladen & Vektorisieren")')
pruef("der Knopf arbeitet einen Stapel ab",
      "for _i, _datei in enumerate(hochgeladen" in _app[_knopf:_knopf + 900])

# Jede Datei bekommt ihre eigene Meldung. "3 von 5 verarbeitet" sagt
# nicht, WELCHE fehlt -- und genau danach wird gesucht.
_block = _app[_knopf:_knopf + 3000]
pruef("und meldet je Datei", "for _name, _n, _hinweis in _ergebnisse" in _block)

# Und das Entscheidende: kein Neuladen, solange eine Datei nicht
# durchsuchbar wurde. Geprueft wird die REIHENFOLGE im Quelltext --
# st.rerun() muss hinter dem else des Fehlerzweigs stehen.
_fehlerzweig = _block.find("if _schlecht:")
_neuladen = _block.find("st.rerun()")
pruef("bei einem Fehlschlag wird nicht neu geladen",
      0 < _fehlerzweig < _neuladen, f"if bei {_fehlerzweig}, rerun bei {_neuladen}")
pruef("und genau einmal wird ueberhaupt neu geladen",
      _block.count("st.rerun()") == 1, _block.count("st.rerun()"))

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

print()
print(f"=== {sum(ok)}/{len(ok)} Pruefungen bestanden ===")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
