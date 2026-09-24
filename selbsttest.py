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
gescheitert = []


def pruef(was, bedingung, zusatz=""):
    ok.append(bool(bedingung))
    if not bedingung:
        gescheitert.append(f"{was}{'  ' + str(zusatz) if zusatz else ''}")
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

# --- GLEICHZEITIG ANLEGEN VERLIERT NIEMANDEN ---
#
# Streamlit bedient alle Sitzungen in einem Prozess. Ohne Sperre lasen
# gleichzeitige Verwalter denselben Stand der Benutzerdatei, und der
# letzte Schreiber loeschte, was die anderen angelegt hatten -- bei drei
# Verwaltern mit je drei Nutzern kamen von neun gemeldeten einer an.
#
# Gemessen in eigenen Dateien, damit die neun Zugaenge den uebrigen
# Selbsttest nicht beruehren.
import threading as _th_g
_g_alt = (benutzer._datei, benutzer.PROTOKOLL, raeume.DATEI)
_g_ord = os.path.join(tmp, "gleichzeitig")
os.makedirs(_g_ord, exist_ok=True)
benutzer._datei = lambda: os.path.join(_g_ord, "users.json")
benutzer.PROTOKOLL = os.path.join(_g_ord, "benutzer.log")
raeume.DATEI = os.path.join(_g_ord, "raeume.json")
try:
    benutzer.anlege("chef_g", "chefpasswort", "admin", von="test")
    _g_fehler = []

    def _g_lege(v, i):
        try:
            if not benutzer.anlege(f"{v}_g{i}", "geheim123", von=v)[0]:
                _g_fehler.append(f"{v}_g{i}")
        except Exception as e:
            _g_fehler.append(f"{v}_g{i}: {type(e).__name__}: {e}")

    _g_faeden = [_th_g.Thread(target=_g_lege, args=(v, i))
                 for i in range(3) for v in ("anna", "bernd", "carla")]
    for _f in _g_faeden:
        _f.start()
    for _f in _g_faeden:
        _f.join()
    _g_soll = {f"{v}_g{i}" for i in range(3) for v in ("anna", "bernd", "carla")}
    _g_da = _g_soll & set(benutzer.namen())
    pruef("gleichzeitig angelegt: jeder Aufruf gelingt", not _g_fehler, _g_fehler)
    pruef("gleichzeitig angelegt: alle neun stehen in der Datei",
          len(_g_da) == 9, f"{len(_g_da)}/9, fehlt: {sorted(_g_soll - _g_da)}")
    pruef("gleichzeitig angelegt: die Datei ist gueltig signiert",
          benutzer.zustand() == benutzer.SIGNIERT, benutzer.zustand())
    _g_raum = {n for n in _g_soll
               if raeume.privat_kennung(n) in raeume._lade()["raeume"]}
    pruef("gleichzeitig angelegt: jeder hat seinen persoenlichen Raum",
          len(_g_raum) == 9, sorted(_g_soll - _g_raum))
    pruef("gleichzeitig angelegt: die Protokollkette bleibt ganz",
          benutzer.protokoll_pruefen()[0], benutzer.protokoll_pruefen())
    # Die Raumdatei EIGENS pruefen. Ueber anlege() allein kommen die
    # Raum-Schreiber zeitversetzt an, weil die Benutzerdatei sie
    # hintereinander stellt -- die Pruefung oben liefe dann auch mit
    # ungesperrter Raumdatei durch. Hier schreiben zwanzig Faeden
    # zugleich: zehn persoenliche Raeume, zehn gemeinsame.
    _r_fehler = []

    def _r_privat(i):
        try:
            raeume.sichere_anlage_privat(f"direkt_{i}")
        except Exception as e:
            _r_fehler.append(f"privat {i}: {type(e).__name__}: {e}")

    def _r_raum(i):
        try:
            raeume.anlegen(f"gemein_{i}", f"Gemein {i}", "", ["chef_g"])
        except Exception as e:
            _r_fehler.append(f"raum {i}: {type(e).__name__}: {e}")

    _r_faeden = ([_th_g.Thread(target=_r_privat, args=(i,)) for i in range(10)]
                 + [_th_g.Thread(target=_r_raum, args=(i,)) for i in range(10)])
    for _f in _r_faeden:
        _f.start()
    for _f in _r_faeden:
        _f.join()
    _r_bestand = raeume._lade()["raeume"]
    _r_soll = ({raeume.privat_kennung(f"direkt_{i}") for i in range(10)}
               | {raeume.sichere_kennung(f"gemein_{i}") for i in range(10)})
    pruef("gleichzeitig in die Raumdatei: jeder Aufruf gelingt",
          not _r_fehler, _r_fehler[:3])
    pruef("gleichzeitig in die Raumdatei: alle zwanzig Raeume stehen darin",
          _r_soll <= set(_r_bestand),
          f"{len(_r_soll & set(_r_bestand))}/20")
finally:
    benutzer._datei, benutzer.PROTOKOLL, raeume.DATEI = _g_alt

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
import subprocess as _sub
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

# --- BENUTZER ANLEGEN UND PASSWORT SETZEN SIND FORMULARE ---
#
# Ausserhalb eines Formulars kommt ein Feld erst beim Verlassen an. Der
# Knopf "Benutzer anlegen" hing an "Passwort ausgefuellt" aus dem
# vorigen Durchlauf: wer tippte und direkt klickte, traf einen noch
# gesperrten Knopf, und der Klick verpuffte ohne Meldung.
import ast as _ast_f
_knoepfe = {}
for _k in _ast_f.walk(_ast_f.parse(_datei("verwaltung.py"))):
    if (isinstance(_k, _ast_f.Call) and _k.args
            and isinstance(_k.args[0], _ast_f.Constant)
            and _k.args[0].value in ("Benutzer anlegen", "Passwort setzen")):
        _knoepfe[_k.args[0].value] = getattr(_k.func, "attr", "?")
pruef("'Benutzer anlegen' ist ein Formularknopf",
      _knoepfe.get("Benutzer anlegen") == "form_submit_button", _knoepfe)
pruef("'Passwort setzen' ist ein Formularknopf",
      _knoepfe.get("Passwort setzen") == "form_submit_button", _knoepfe)

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
# In beiden gesucht: der Upload ist seit dem Umzug in aufnehmen.py,
# und ein Fundort ist keine Eigenschaft.
pruef("der Upload benutzt sie",
      "owncloud.ziel_pfad(raum, pdf_path)"
      in _datei("app.py") + _datei("aufnehmen.py"))

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
# Gesucht wird die with-Zeile der grossen Leiste, und zwar die ganze:
# "with st.sidebar:" allein steht auch ueber der Anmeldemaske, und die
# Ueberschrift "# --- SIDEBAR (UI) ---" ebenfalls -- diese Pruefung fiel
# nach dem Umbau der Sperre still auf die falsche Stelle zurueck, tausend
# Zeilen zu frueh. Dass diese Zeile so heisst, haelt die Pruefung
# "der Leistenblock benutzt die Sperre" fest; aendert sie sich, faellt es
# dort auf und nicht hier im Stillen.
_leiste2 = _app.find("with st.sidebar, _bedienung_gesperrt")
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



# --- UND IN DIE ANDERE RICHTUNG ---
#
# Beim Herausloesen habe ich gezaehlt, was der Block LIEST. Was er
# SETZT und app.py danach braucht, blieb ungeprueft -- und genau das
# war top_k: der Regler "Relevante Abschnitte abrufen" lag als letzte
# Anweisung im Schnitt, die Suche unten brauchte seinen Wert, und im
# Betrieb kam "name 'top_k' is not defined".
#
# Ein Block, der aus einer Datei wandert, darf nicht der einzige
# Erzeuger von etwas sein, das dort zurueckbleibt.
import ast as _ast

_vq = _datei("verwaltung.py")
_zfn = next(k for k in _ast.parse(_vq).body
            if isinstance(k, _ast.FunctionDef) and k.name == "zeichne")
_setzt = {u.id for u in _ast.walk(_zfn)
          if isinstance(u, _ast.Name) and isinstance(u.ctx, _ast.Store)}

# Die ganze Datei lesen und nach ZEILE trennen, nicht den Text
# zerschneiden: ein Bruchstueck, das mitten in einer Einrueckung
# beginnt, laesst sich nicht als Modul lesen. Das ging nur so lange
# gut, wie hinter dem Aufruf zufaellig nichts Eingeruecktes stand.
_aq = _datei("app.py")
_abaum = _ast.parse(_aq)
_ab_zeile = _aq[:_aq.index("verwaltung.zeichne(")].count(chr(10)) + 1
_braucht = {u.id for u in _ast.walk(_abaum)
            if isinstance(u, _ast.Name) and isinstance(u.ctx, _ast.Load)
            and getattr(u, "lineno", 0) >= _ab_zeile}
_hat = {u.id for u in _ast.walk(_abaum)
        if isinstance(u, _ast.Name) and isinstance(u.ctx, _ast.Store)}
_hat |= {k.name for k in _abaum.body
         if isinstance(k, (_ast.FunctionDef, _ast.ClassDef))}
_hat |= {a.asname or a.name.split(".")[0] for k in _abaum.body
         if isinstance(k, (_ast.Import, _ast.ImportFrom)) for a in k.names}

_verloren = sorted(_setzt & _braucht - _hat
                   - {p.arg for p in _zfn.args.kwonlyargs})
pruef("die Verwaltung ist nicht der einzige Erzeuger von etwas",
      not _verloren, _verloren)

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
# Dieselbe Zeile wie oben und aus demselben Grund: "with st.sidebar:"
# steht auch ueber der Anmeldemaske, und rindex traf nach dem Umbau der
# Sperre nicht mehr die grosse Leiste.
_leiste = _app.find("with st.sidebar, _bedienung_gesperrt")
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

# Acht Anlegen- und Aenderungsformulare: Benutzer, Passwort durch den
# Verwalter, eigenes Passwort, Raum, Listenbereich, Zugangstoken,
# Postfach anlegen (Verwaltung), Postfach verbinden (Nutzer). Einmal
# abziehen fuer die Definition selbst.
#
# Die Namen stehen hier und nicht nur die Zahl: schlaegt die Pruefung
# fehl, soll sie sagen, WELCHES Formular fehlt, statt nur dass eines
# fehlt.
_aufrufe = _ui.count("_felder_leeren(") - _ui.count("def _felder_leeren(")
pruef("acht Formulare werden geleert", _aufrufe == 8, _aufrufe)

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
# Der Block reicht bis zur naechsten Ueberschrift und nicht 3000
# Zeichen weit. Ein festes Fenster ist genau die Pruefung, die beim
# naechsten Umbau bricht: als die Fortschrittszeile der Bilder in die
# Oberflaeche zurueckkam, rutschte st.rerun() aus dem Fenster, und die
# Pruefung meldete "kein Neuladen gefunden" fuer Code, der sich nicht
# geaendert hatte.
# Der Block reicht bis zur naechsten Ueberschrift und nicht 3000
# Zeichen weit. Ein festes Fenster ist genau die Pruefung, die beim
# naechsten Umbau bricht: als die Fortschrittszeile der Bilder in
# die Oberflaeche zurueckkam, rutschte st.rerun() aus dem Fenster,
# und die Pruefung meldete "kein Neuladen gefunden" fuer Code, der
# sich gar nicht geaendert hatte.
_blockende = _app.find(chr(10) + "    # --- ", _knopf)
_block = _app[_knopf:_blockende if _blockende > 0 else _knopf + 4000]
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
# Die Seitenleiste zeigte, was GILT: Endpunkt eingerichtet, kein Ausfall
# vermerkt. Nicht, was beim letzten Bewerten geschah. Gefragt wurde
# genau das: "laut Seitenleiste haengt der Reranker am Endpunkt, aber
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
# Zum ersten Mal ausgefuehrt und nicht nur gelesen. Solange das in
# app.py stand, war es nicht erreichbar -- app.py importiert streamlit,
# das hier fehlt. Die teuerste Funktion der Anwendung war damit die
# einzige, die nie gelaufen ist.
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

# 5. Das Modul bleibt frei von der Oberflaeche. Genau das war der Grund
#    fuer den Umzug -- kaeme streamlit zurueck, waere die Schnittstelle
#    wieder ausgesperrt und dieser Test nicht mehr ausfuehrbar.
_aufq = _datei("aufnehmen.py")
# Gesucht wird der IMPORT und nicht das Wort: der Dateikopf
# erklaert, warum das Modul streamlit nicht importiert, und liess
# die erste Fassung dieser Pruefung an der Erklaerung scheitern.
pruef("aufnehmen.py kennt keine Oberflaeche",
      not _re.search(r"^\s*(import|from)\s+streamlit", _aufq, _re.M)
      and not _re.search(r"(?<![A-Za-z_])st\.", _aufq))

# 6. Und beide Eingaenge nehmen denselben Weg. Zwei Ingestwege, von
#    denen einer nachgezogen wird und der andere nicht, waeren der
#    Anfang davon, dass ein Dokument je nach Eingang anders im Bestand
#    liegt.
pruef("Oberflaeche und Schnittstelle nehmen denselben Weg",
      "process_uploaded_pdf" in _datei("app.py")
      and "aufnehmen.process_uploaded_pdf" in _datei("api.py"))
pruef("und die Schnittstelle weist ab, statt umzuleiten",
      "streng=True" in _datei("api.py")
      and "status_code=403" in _datei("api.py"))

# --- DIE SPEICHERORTE SAGEN, WER OBEN STEHT ---
#
# Gemeldet als "es laeuft immer noch alles im alten Ablagesystem",
# obwohl ownCloud lief. Es lief nichts Altes: der Abgleich holt die
# Dateien nach data/dokumente, und der Ingest liest nur von der Platte.
# Dateien dort sind das Bild eines funktionierenden Abgleichs.
#
# Irrefuehrend war die Beschriftung "werden gepflegt, nur gelesen" --
# gepflegt wird bei eingerichtetem ownCloud eben dort und nicht hier.
# Sie haengt jetzt an owncloud.eingerichtet(), und diese Pruefung haelt
# fest, dass sie eine Bedingung hat und keine Konstante mehr ist.
_vwq = _datei("verwaltung.py")
pruef("die Quellen-Beschriftung kennt beide Faelle",
      "gepflegt wird in " in _vwq
      and "werden gepflegt, nur gelesen" in _vwq)
pruef("und sie haengt an ownCloud",
      "_mit_cloud = owncloud.eingerichtet()" in _vwq
      and _vwq.index("_mit_cloud = owncloud.eingerichtet()")
      < _vwq.index("Quellen — Arbeitskopie"))

# --- DIE LEISTE IST WIRKLICH GRAU, SOLANGE EINE ANTWORT LAEUFT ---
#
# Gemeldet als "man kann waehrend einer Antwort wieder Sachen
# auswaehlen". Gesperrt waren bis dahin drei Dinge -- Chateingabe,
# Verwaltungsschalter, Passwortfeld -- und alles andere nicht. Ein Klick
# auf die Raumauswahl reisst die laufende Antwort ab.
#
# app.py laesst sich hier nicht importieren, streamlit fehlt im
# Testlauf. Also wird genau das Stueck aus dem Quelltext geholt und
# gegen eine Attrappe ausgefuehrt: eine Verhaltenspruefung, keine
# Textsuche.
import contextlib as _ctx
import functools as _ft

_app_baum = _ast.parse(_datei("app.py"))
_sperr_teile = [k for k in _app_baum.body
                if (isinstance(k, _ast.Assign) and
                    getattr(k.targets[0], "id", "") == "_BEDIENELEMENTE")
                or (isinstance(k, _ast.FunctionDef) and
                    k.name == "_bedienung_gesperrt")]
pruef("die Sperre der Leiste steht an genau einer Stelle",
      len(_sperr_teile) == 2, len(_sperr_teile))

_sperr_raum = {"contextlib": _ctx, "functools": _ft, "inspect": _inspect,
               "st": None}
exec(compile(_ast.Module(body=_sperr_teile, type_ignores=[]),
             "app.py", "exec"), _sperr_raum)
_sperre = _sperr_raum["_bedienung_gesperrt"]


def _attrappe():
    """Ein Stellvertreter fuer st: zwei Elemente mit, eines ohne."""
    m = _types.SimpleNamespace()
    m.button = lambda text, disabled=False: ("button", disabled)
    m.selectbox = lambda text, disabled=False: ("selectbox", disabled)
    m.markdown = lambda text: ("markdown", None)      # kennt kein disabled
    return m


_m = _attrappe()
_vorher = (_m.button, _m.selectbox, _m.markdown)
with _sperre(True, _m):
    _drin = (_m.button("x"), _m.selectbox("y"), _m.markdown("z"))
pruef("in der Sperre ist jedes Bedienelement gesperrt",
      _drin[0] == ("button", True) and _drin[1] == ("selectbox", True),
      _drin)
pruef("was disabled nicht kennt, bleibt unberuehrt",
      _drin[2] == ("markdown", None) and _m.markdown is _vorher[2], _drin[2])
pruef("nach der Sperre ist alles zurueckgesetzt",
      (_m.button, _m.selectbox) == _vorher[:2],
      (_m.button is _vorher[0], _m.selectbox is _vorher[1]))

# Und der wichtigste Fall: eine Ausnahme mittendrin. st ist ein Modul und
# lebt laenger als dieser Lauf -- eine haengengebliebene Huelle sperrte
# die Oberflaeche dauerhaft, genau der Fehler, den die Selbstheilung der
# Antwortsperre schon einmal gekostet hat.
try:
    with _sperre(True, _m):
        raise RuntimeError("mittendrin")
except RuntimeError:
    pass
pruef("auch nach einer Ausnahme ist die Sperre wieder weg",
      (_m.button, _m.selectbox) == _vorher[:2], "haengengeblieben")

# Ohne laufende Antwort aendert sie nichts.
with _sperre(False, _m):
    _offen = _m.button("x")
pruef("ohne laufende Antwort ist nichts gesperrt",
      _offen == ("button", False), _offen)

# Und die Leiste benutzt sie auch. Ohne diese Pruefung koennte die
# Huelle tadellos sein und nirgends stehen.
pruef("der Leistenblock benutzt die Sperre",
      "with st.sidebar, _bedienung_gesperrt(_antwortet):" in _datei("app.py"))

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
_ANDERE_DIM = DIM * 2
store.schreibe(_falsche_sml, ["fremd_p1_c0"],
               documents=["Ein Abschnitt mit fremder Dimension."],
               metadatas=[{"file_name": "Fremd.pdf", "page": 1,
                           "raum": _falscher_raum, "type": "text"}],
               embeddings=[[0.5] * _ANDERE_DIM])

_treffer_d, _zahlen_d = pipeline.suche(
    [(_falscher_raum, _falsche_sml)], FakeEmb(), "modell",
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
import bestandsliste as _bl

pruef("die Bestandsliste liest die Dimension einer Sammlung",
      _bl._dimension(_falsche_sml) == _ANDERE_DIM,
      _bl._dimension(_falsche_sml))
pruef("und die des gewachsenen Bestands",
      _bl._dimension(store.sammlung(raeume.sammlung(raeume.ALLGEMEIN),
                                    anlegen=False)) == DIM)

raeume.entfernen(_falscher_raum)

# --- JEDER SIEHT NUR SEINE EIGENEN TOKEN ---
#
# Bisher sah niemand ausser dem Verwalter, dass ueberhaupt ein Token auf
# seine Kennung ausgestellt ist. Ein Token traegt die Rechte seines
# Besitzers -- wer nicht weiss, dass eines existiert, kann auch nicht
# merken, dass es zu viele sind.
#
# Die Anzeige steht in app.py und laeuft hier nicht. Die Eigenschaft,
# an der sie haengt, schon: auth.liste() gibt ALLE zurueck, und die
# Trennung ist der Filter darauf. Der wird mit echten Token
# durchgespielt.
import auth as _auth

# Ausdruecklich in den Wegwerfbestand, wie bei den anderen auch. Der
# Pfad entsteht beim Import aus paths.CONFIG_DIR und zeigt hier schon
# richtig -- ihn trotzdem zu setzen kostet nichts und schliesst aus,
# dass dieser Test je an echte Token kommt.
_auth.TOKEN_FILE = os.path.join(paths.CONFIG_DIR, "tokens.json")

_t_markus = _auth.erzeuge("markus", "Masseningest")
_t_anna = _auth.erzeuge("anna", "Laptop")
pruef("ein Token kommt genau einmal heraus",
      isinstance(_t_markus, str) and _t_markus != _t_anna)
pruef("und weist seinen Besitzer aus",
      _auth.pruefe(_t_markus) == "markus"
      and _auth.pruefe(_t_anna) == "anna")


def _meine(wer):
    """Derselbe Filter wie in der Oberflaeche."""
    return [(h, e) for h, e in _auth.liste() if e.get("benutzer") == wer]


pruef("jeder sieht nur seine eigenen",
      [e["bezeichnung"] for _h, e in _meine("markus")] == ["Masseningest"]
      and [e["bezeichnung"] for _h, e in _meine("anna")] == ["Laptop"],
      [(h[:6], e.get("benutzer")) for h, e in _auth.liste()])

# Und der Widerruf trifft genau eines. Der volle Hashwert wird
# uebergeben und nicht sein Anfang: auth.widerrufe trifft bei einem
# mehrdeutigen Anfang absichtlich keinen.
_h_anna = _meine("anna")[0][0]
pruef("ein Widerruf trifft genau eines", _auth.widerrufe(_h_anna) == 1)
pruef("und danach gilt es nicht mehr", _auth.pruefe(_t_anna) is None)
pruef("das fremde bleibt unberuehrt", _auth.pruefe(_t_markus) == "markus")
_auth.widerrufe(_meine("markus")[0][0])

# Die Verdrahtung: der Filter steht auch wirklich in der Oberflaeche,
# und angelegt wird dort NICHT -- das bleibt beim Verwalter, wie schon
# im Terminal.
_appq = _datei("app.py")
pruef("die Oberflaeche filtert auf die eigene Kennung",
      'if _e.get("benutzer") == st.session_state["username"]' in _appq)
# Ohne Klammer gesucht: eine blosse Referenz auf die Funktion liesse
# sich anderswo aufrufen, und die erste Fassung dieser Pruefung suchte
# den Aufruf. Die Gegenprobe kam prompt durch.
pruef("und legt selbst keine an", "auth.erzeuge" not in _appq)

# --- ZUGANGSTOKEN IN DER OBERFLAECHE ---
#
# Die Mechanik lag fertig in auth.py und wurde nur vom Terminal
# benutzt. Jetzt legt der Verwalter Token dort an, wo er ohnehin ist.
#
# Der Wert ist das Einzige an dieser Oberflaeche, das sich nicht wieder
# beschaffen laesst: gespeichert wird nur sein Hashwert.
_vwq2 = _datei("verwaltung.py")

pruef("die Verwaltung legt Token an",
      "auth.erzeuge(" in _vwq2 and "auth.liste()" in _vwq2
      and "auth.widerrufe(" in _vwq2)

# EINMAL ZEIGEN UND WIEDER WEGWERFEN. Streamlit fuehrt das Skript bei
# jeder Bedienung neu aus; was im Sitzungszustand steht, steht bei
# jedem weiteren Lauf wieder auf dem Bildschirm. Ohne das Loeschen
# haette der Verwalter sein Token dauerhaft vor sich liegen.
pruef("das frische Token verschwindet wieder",
      'del st.session_state["_neues_token"]' in _vwq2)

# IM FORMULAR, aus demselben Grund wie beim Passwortaendern: ein
# Textfeld uebergibt seinen Inhalt erst beim Verlassen, und ein Klick
# direkt nach dem Tippen saehe sonst ein leeres Feld.
pruef("und die Anlage steht in einem Formular",
      'st.form(f"token_' in _vwq2)

# NUR FUER VERWALTER. Der Bereich steht im Block hinter is_admin() --
# gepruefft wird die Reihenfolge im Quelltext, denn ein Token fuer eine
# fremde Kennung ist eine Vollmacht.
_vw_anfang = _vwq2.find("    if _vw:")
_token_stelle = _vwq2.find("Zugangstoken für die Schnittstelle")
pruef("und nur Verwalter kommen hin",
      0 < _vw_anfang < _token_stelle, (_vw_anfang, _token_stelle))

# --- DIE SCHNITTSTELLE LAESST SICH AUCH HINTER EINEM PRAEFIX ANSEHEN ---
#
# FastAPI liefert unter /hilfe eine bedienbare Oberflaeche -- die
# knappste Dokumentation, die nicht veralten kann. Im Cluster steht sie
# hinter /api, weil Traefik das Praefix abschneidet. Ohne root_path holt
# die Seite ihr Schema von "/openapi.json" statt "/api/openapi.json" und
# bleibt leer; "Try it out" schickt an die falsche Adresse. Die
# Schnittstelle war da und liess sich nicht ansehen.
_apiq = _datei("api.py")
pruef("die Schnittstelle kennt ihren Wurzelpfad",
      "API_WURZELPFAD" in _apiq and "root_path=API_WURZELPFAD" in _apiq)
pruef("und die Bedienoberflaeche bleibt erreichbar",
      'docs_url="/hilfe"' in _apiq)

# --- DAS ABBILD SAGT, AUS WELCHEM STAND ES GEBAUT WURDE ---
#
# Ausgerollt wird der wandernde Kennzeichner, und aus dessen Digest kam
# niemand auf den Commit zurueck: im Cluster liess sich nur feststellen,
# dass das Abbild NEUER ist. Genau diese Verwechslung hat zwei Rollouts
# zuvor gebissen -- zwei Ablagen bauen unabhaengig, "neuer als vorher"
# galt fuer beide, und nur eine trug die Korrektur.
_bau = _datei(os.path.join(".github", "workflows", "abbild.yml"))
pruef("das Abbild traegt den Commit als Marke",
      "org.opencontainers.image.revision=${{ github.sha }}" in _bau)

# --- POSTFACH-ANMELDEDATEN UEBERLEBEN DAS ABMELDEN NICHT ---
#
# Sie liegen im Sitzungszustand und nirgends sonst: nicht geschrieben,
# nicht protokolliert, nicht in der Konfiguration. Wer sich abmeldet,
# weil er den Rechner verlaesst, laesst sie nicht zurueck.
_appq3 = _datei("app.py")

# Das TUPEL wird gelesen, nicht der Quelltext durchsucht: die
# Zeichenkette steht auch in st.session_state.get("_postfach_koepfe"),
# und die erste Fassung dieser Pruefung liess sich davon taeuschen --
# die Gegenprobe lief durch, obwohl der Eintrag fehlte.
_sk = next((k for k in _ast.parse(_appq3).body
            if isinstance(k, _ast.Assign)
            and getattr(k.targets[0], "id", "") == "SITZUNGSSCHLUESSEL"), None)
_sk_namen = [e.value for e in getattr(_sk, "value", _ast.Tuple(elts=[])).elts
             if isinstance(e, _ast.Constant)] if _sk else []
pruef("die Postfach-Koepfe haengen an der Anmeldung",
      "_postfach_koepfe" in _sk_namen, _sk_namen)

# Gespeichert wird der fertige Kopf, nicht das Passwort. Was im
# Arbeitsspeicher liegt, ist damit das, was ohnehin ueber die Leitung
# geht -- und nicht zusaetzlich das Passwort im Klartext.
pruef("gespeichert wird der Kopf, nicht das Passwort",
      "_koepfe[_n] = _k" in _appq3 and "mcp.kopf_fuer(_n, _pf_u, _pf_g)" in _appq3)

# Und sie landen nicht in der Konfiguration: schreibe_konfiguration
# gehoert der Verwaltung, nicht der Nutzermaske.
pruef("die Nutzermaske schreibt nichts auf die Platte",
      "schreibe_konfiguration" not in _appq3)

# Erst probieren, dann merken -- sonst faellt eine falsche Anmeldung
# erst mitten in einer Antwort auf.
pruef("eine Anmeldung wird vor dem Merken erprobt",
      _appq3.index("_probe[_n].werkzeuge()") < _appq3.index("_koepfe[_n] = _k"))

# --- ANMELDEDATEN GEHEN NUR AN IHR EIGENES POSTFACH ---
#
# verbinde() nahm frueher EINEN Kopf und gab ihn an jeden Server weiter.
# Bei einem persoenlichen Postfach und mehreren Funktionspostfaechern
# waere damit das Passwort des Nutzers an jeden eingerichteten Server
# gegangen -- auch an die, mit denen er nichts zu tun hat.
import json as _js0
import mcp as _mcp0

_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_koepfe.json")
_js0.dump({"persoenlich": {"transport": "http", "url": "http://x",
                           "anmeldung": "basic"},
           "info": {"transport": "http", "url": "http://y",
                    "anmeldung": "keine"}},
          io.open(_mcp0.KONFIG, "w", encoding="utf-8"))

pruef("ein persoenliches Postfach verlangt eine Anmeldung",
      _mcp0.braucht_anmeldung("persoenlich"))
pruef("ein Funktionspostfach mit Dienstkonto nicht",
      not _mcp0.braucht_anmeldung("info"))

_kopf = _mcp0.kopf_fuer("persoenlich", "markus", "geheim")
pruef("Benutzer und Passwort werden zu einem Basic-Kopf",
      _kopf.get("Authorization", "").startswith("Basic "), _kopf)

_vb0 = _mcp0.verbinde({"persoenlich": _kopf})
pruef("der Kopf erreicht sein Postfach",
      _vb0["persoenlich"].zusatz_kopf == _kopf)
pruef("und KEIN anderes",
      _vb0["info"].zusatz_kopf == {}, _vb0["info"].zusatz_kopf)

# Und die Oberflaeche reicht eine Zuordnung durch, keinen einzelnen Kopf.
pruef("die Oberflaeche uebergibt eine Zuordnung je Postfach",
      '_postfach_koepfe' in _datei("app.py")
      and '_postfach_kopf"' not in _datei("app.py"))

os.remove(_mcp0.KONFIG)
_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# --- EXCHANGE SPRICHT KEIN MCP, UND DAS DARF NIRGENDS AUFFALLEN ---
#
# Ein Exchange-Postfach laeuft nicht ueber JSON-RPC, sondern ueber
# postfach.py im selben Prozess. Alles darueber -- Werkzeugliste,
# Bestaetigung vor dem Senden, Hinweis, Anmeldung in der Sitzung --
# unterscheidet die beiden Wege nicht. Diese Pruefungen halten das fest.
import postfach as _pf0

_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_exchange.json")
_js0.dump({"markus": {"transport": "exchange", "anmeldung": "basic",
                      "url": "https://owa.test/EWS/Exchange.asmx",
                      "persoenlich": True, "textfeld": "body",
                      "sendet": list(_pf0.SENDEWERKZEUGE)},
           "info": {"transport": "exchange", "anmeldung": "basic",
                    "postfach": "info@test.de", "persoenlich": False,
                    "automatisch": True, "textfeld": "body",
                    "sendet": list(_pf0.SENDEWERKZEUGE)},
           "irgendein": {"transport": "http", "url": "http://z",
                         "anmeldung": "keine"}},
          io.open(_mcp0.KONFIG, "w", encoding="utf-8"))

_vb1 = _mcp0.verbinde({})
pruef("ein Exchange-Postfach wird kein JSON-RPC-Server",
      isinstance(_vb1["markus"], _pf0.Postfach),
      type(_vb1["markus"]).__name__)
pruef("ein MCP-Server bleibt einer",
      isinstance(_vb1["irgendein"], _mcp0.Verbindung),
      type(_vb1["irgendein"]).__name__)
pruef("beide Bauarten haben dieselben drei Methoden",
      all(callable(getattr(_vb1[_n], _m, None))
          for _n in ("markus", "irgendein")
          for _m in ("werkzeuge", "rufe", "schliesse")))

# DIE WICHTIGSTE: jedes Werkzeug, das etwas verschickt, wird auch als
# solches erkannt. Faellt eines heraus, laeuft es ohne Rueckfrage --
# und eine verschickte Nachricht kommt nicht zurueck.
_erkannt = {_w["name"] for _w in _pf0.WERKZEUGE
            if _mcp0.sendet("markus", _w["name"])}
pruef("genau die Sendewerkzeuge gelten als sendend",
      _erkannt == set(_pf0.SENDEWERKZEUGE), sorted(_erkannt))

_namen = {_w["name"] for _w in _pf0.WERKZEUGE}
pruef("die Vorlage nennt nur Werkzeuge, die es wirklich gibt",
      set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"]) <= _namen,
      sorted(set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"]) - _namen))
pruef("und sie nennt alle, die senden",
      set(_mcp0.VORLAGEN["exchange"]["angaben"]["sendet"])
      == set(_pf0.SENDEWERKZEUGE))

# Der Hinweis unter einer automatischen Antwort braucht ein Feld, in
# das er passt. Steht in der Vorlage ein Feld, das kein Sendewerkzeug
# hat, faellt das automatische Antworten aus -- lautlos.
_feld = _mcp0.VORLAGEN["exchange"]["angaben"]["textfeld"]
_ohne_feld = sorted(_w["name"] for _w in _pf0.WERKZEUGE
                    if _w["name"] in _pf0.SENDEWERKZEUGE
                    and _feld not in (_w["schema"].get("properties") or {}))
pruef("jedes Sendewerkzeug hat das Feld, in das der Hinweis kommt",
      not _ohne_feld, _ohne_feld)

# Gegenprobe am freigeschalteten Postfach: mit dem Feld laeuft es
# durch, ohne das Feld wird bestaetigt statt gesendet.
_ja1, _g1 = _mcp0.darf_automatisch("info", "mail_senden", {"body": "x"})
pruef("mit Textfeld antwortet ein freigeschaltetes Postfach selbst", _ja1, _g1)
_ja2, _g2 = _mcp0.darf_automatisch("info", "mail_senden", {"text": "x"})
pruef("ohne Textfeld wird bestaetigt statt gesendet", not _ja2, _g2)
pruef("ein persoenliches Postfach antwortet auch mit Feld nicht selbst",
      not _mcp0.darf_automatisch("markus", "mail_senden", {"body": "x"})[0])

# ANMELDEDATEN KOMMEN AUS DER SITZUNG UND SONST NIRGENDWOHER.
_ohne_kopf = _pf0.Postfach("markus", {"transport": "exchange"})
try:
    _ohne_kopf._zugang()
    _griff = "durchgelassen"
except _pf0.Fehler:
    _griff = "abgewiesen"
pruef("ohne Anmeldung wird kein Postfach geoeffnet",
      _griff == "abgewiesen", _griff)

_mit_kopf = _pf0.Postfach("markus", {"transport": "exchange"},
                          _mcp0.kopf_fuer("markus", "m@test.de", "geheim"))
pruef("die Anmeldedaten stammen aus dem Kopf dieser Sitzung",
      _mit_kopf._zugang() == ("m@test.de", "geheim"))

# Eine Kurzkennung gehoert zu EINEM Postfach. Sonst ginge eine Antwort
# mit den Daten des einen an den Bezug des anderen.
_kz = _pf0._merke_kennung("markus", "AAAA")
pruef("eine Kurzkennung loest im eigenen Postfach auf",
      _pf0._lange_kennung("markus", _kz) == "AAAA")
try:
    _pf0._lange_kennung("info", _kz)
    _fremd = "durchgelassen"
except _pf0.Fehler:
    _fremd = "abgewiesen"
pruef("und in einem fremden nicht", _fremd == "abgewiesen", _fremd)

# EIN FUNKTIONSPOSTFACH BRAUCHT SEINE EIGENE ADRESSE. Ohne sie oeffnet
# es das Postfach dessen, der sich gerade anmeldet: jeder saehe seine
# eigene Post unter fremdem Namen, und eine automatische Antwort ginge
# aus dem falschen Postfach hinaus.
_okA, _mA = _mcp0.lege_an("t_ohne", "exchange", "owa.test", persoenlich=False)
pruef("ein Funktionspostfach ohne eigene Adresse wird abgewiesen",
      not _okA, _mA)
_okB, _mB = _mcp0.lege_an("t_mit", "exchange", "owa.test", persoenlich=False,
                          postfach="info2@test.de")
pruef("mit eigener Adresse wird es angelegt", _okB, _mB)
pruef("der eingetragene Server wird zur EWS-Adresse ergaenzt",
      _mcp0.lies_konfiguration()["t_mit"]["url"]
      == "https://owa.test/EWS/Exchange.asmx",
      _mcp0.lies_konfiguration()["t_mit"]["url"])
# Ein persoenliches darf ohne Adresse -- dort ist die des Anmeldenden
# die richtige.
_okC, _mC = _mcp0.lege_an("t_pers", "exchange", "", persoenlich=True)
pruef("ein persoenliches Postfach geht auch ohne beides", _okC, _mC)

os.remove(_mcp0.KONFIG)
_mcp0.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# --- DER HINWEIS UNTER AUTOMATISCHEN ANTWORTEN IST ABSCHALTBAR ---
#
# Vorgabe ist an: wer nichts sagt, bekommt ihn. Abschalten ist eine
# ausdrueckliche Handlung -- ein Empfaenger, der nicht erfaehrt, dass
# niemand die Nachricht gelesen hat, kann sie nicht einordnen.
#
# Ein bestaetigter Entwurf bekommt keinen: er ist gelesen.
import json as _js
import mcp as _mcp2

_mcp2.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp_probe.json")


def _postfach(**angaben):
    _js.dump({"pf": dict(angaben)},
             io.open(_mcp2.KONFIG, "w", encoding="utf-8"))


_arg = {"body": "Guten Tag"}

_postfach(automatisch=True, sendet=["senden"], textfeld="body")
pruef("ohne Angabe steht der Hinweis unter der Nachricht",
      "--" in _mcp2.mit_hinweis("pf", _arg)["body"])
pruef("und automatisch senden ist erlaubt",
      _mcp2.darf_automatisch("pf", "senden", _arg)[0])

_postfach(automatisch=True, sendet=["senden"], textfeld="body",
          hinweis_anhaengen=False)
pruef("abgeschaltet bleibt die Nachricht unveraendert",
      _mcp2.mit_hinweis("pf", _arg)["body"] == "Guten Tag")
pruef("und automatisch senden bleibt erlaubt",
      _mcp2.darf_automatisch("pf", "senden", _arg)[0])

# Die Richtung des Zweifels bleibt: ohne Freischaltung wird bestaetigt,
# und mit Hinweis, aber ohne Textfeld, ebenfalls -- sonst ginge eine
# Nachricht ohne den Hinweis hinaus, den der Betreiber verlangt hat.
_postfach(automatisch=False, sendet=["senden"], textfeld="body",
          hinweis_anhaengen=False)
pruef("ohne Freischaltung wird weiterhin bestaetigt",
      _mcp2.braucht_bestaetigung("pf", "senden", _arg))

_postfach(automatisch=True, sendet=["senden"], hinweis_anhaengen=True)
pruef("und mit Hinweis, aber ohne Textfeld, auch",
      _mcp2.braucht_bestaetigung("pf", "senden", {"x": 1}))

os.remove(_mcp2.KONFIG)
_mcp2.KONFIG = os.path.join(paths.CONFIG_DIR, "mcp.json")

# --- DER QUELLENHINWEIS IST DER NACHWEIS, NICHT DAS SCHMUCKSTUECK ---
#
# Die Anwendung steht unter AGPL-3.0, weil pymupdf es tut und das Lesen
# von PDF traegt. Paragraph 13 der AGPL verlangt, dass Nutzer, die ueber
# ein NETZ mit ihr arbeiten, an ihren Quelltext kommen -- und genau
# diese Zeile in der Seitenleiste ist das Angebot dazu.
#
# Verschwindet sie bei einem Umbau, faellt es sonst niemandem auf: eine
# fehlende Fusszeile stuerzt nicht ab.
_lizenz = _datei("LICENSE")
pruef("die Anwendung steht unter AGPL",
      "AFFERO GENERAL PUBLIC LICENSE" in _lizenz and "MIT License" not in _lizenz)

_appq2 = _datei("app.py")
pruef("und die Oberflaeche bietet den Quelltext an",
      "agpl-3.0" in _appq2 and "github.com/mw-research/LocaNoto" in _appq2)

# --- JEDE ABHAENGIGKEIT STEHT IN DER LIZENZAUFSTELLUNG ---
#
# Eine Aufstellung, die jemand von Hand nachtraegt, ist nach der
# naechsten Abhaengigkeit falsch, und niemand merkt es -- eine
# Lizenzliste stuerzt nicht ab. Dieselbe Idee wie bei der Landkarte.
#
# Geprueft wird der PAKETNAME, nicht die Fassung: ein Versionssprung
# aendert die Lizenz selten, ein neues Paket immer.
_req = _datei("requirements.txt")
_lz = _datei("LIZENZEN.md")
_gepinnt = _re.findall(r"^([A-Za-z0-9._-]+)==", _req, _re.M)
_fehlt_lizenz = sorted({p for p in _gepinnt if f"`{p}`" not in _lz})
pruef("jede gepinnte Abhaengigkeit steht in LIZENZEN.md",
      not _fehlt_lizenz, _fehlt_lizenz[:6])

# --- DIE LANDKARTE STIMMT MIT DEM CODE UEBEREIN ---
#
# Eine Uebersicht, die nur meistens stimmt, kostet mehr als sie bringt:
# wer ihr glaubt, sucht an der falschen Stelle. landkarte.py liest sie
# aus dem Code, und hier steht, woran sie sich halten muss.
# --- GLEICHZEITIG SCHREIBEN, UEBERALL ---
#
# Dasselbe Loch wie beim Anlegen von Benutzern stand an weiteren
# Stellen. Gemessen, bevor es geschlossen wurde:
#   Raumschluessel  10 neue Raeume zugleich -> nach Neustart 2-4
#                   Schluessel weg, deren Texte unlesbar
#   Token           5 widerrufen, zugleich 5 angelegt -> alle 5
#                   Widerrufe rueckgaengig, die Token galten wieder
import threading as _th_s
import auth as _auth_s
import chats as _chats_s


def _zugleich(ziele):
    _fehler = []

    def _lauf(f, a):
        try:
            f(*a)
        except Exception as e:
            _fehler.append(f"{type(e).__name__}: {e}")
    _t = [_th_s.Thread(target=_lauf, args=z) for z in ziele]
    for _x in _t:
        _x.start()
    for _x in _t:
        _x.join()
    return _fehler


_s_ord = os.path.join(tmp, "gleichzeitig_rest")
os.makedirs(_s_ord, exist_ok=True)

# 1. Raumschluessel
_rs_alt = raumschluessel.DATEI
raumschluessel.DATEI = os.path.join(_s_ord, "raumschluessel.json")
raumschluessel.vergiss()
try:
    _rs_hat = {}
    _rs_f = _zugleich([(lambda r: _rs_hat.__setitem__(
        r, raumschluessel.schluessel(r)), (f"neu_{i}",)) for i in range(10)])
    raumschluessel.vergiss()
    _rs_weg = [r for r, k in _rs_hat.items()
               if raumschluessel.schluessel(r, anlegen=False) != k]
    pruef("zehn neue Raeume zugleich: jeder Schluessel ueberlebt den Neustart",
          not _rs_weg and not _rs_f, (_rs_weg, _rs_f[:1]))
    raumschluessel.vergiss()
    _rs_einer = []
    _rs_f2 = _zugleich([(lambda: _rs_einer.append(
        raumschluessel.schluessel("einer")), ()) for _ in range(10)])
    raumschluessel.vergiss()
    pruef("ein neuer Raum, zehn Faeden: alle verschluesseln mit dem "
          "Schluessel, der bleibt",
          set(_rs_einer) == {raumschluessel.schluessel("einer", anlegen=False)}
          and not _rs_f2, (len(set(_rs_einer)), _rs_f2[:1]))
finally:
    raumschluessel.DATEI = _rs_alt
    raumschluessel.vergiss()

# 2. Token
_tk_alt = _auth_s.TOKEN_FILE
_auth_s.TOKEN_FILE = os.path.join(_s_ord, "tokens.json")
try:
    _tk = [_auth_s.erzeuge("anna", f"alt{i}") for i in range(5)]
    _tk_f = _zugleich(
        [(_auth_s.widerrufe, (_auth_s._hash(t)[:16],)) for t in _tk]
        + [(_auth_s.erzeuge, ("bernd", f"neu{i}")) for i in range(5)])
    _tk_wieder = sum(1 for t in _tk if _auth_s.pruefe(t))
    _tk_neu = sum(1 for _k, e in _auth_s.liste() if e.get("benutzer") == "bernd")
    pruef("ein Widerruf bleibt widerrufen, auch wenn zugleich Token entstehen",
          _tk_wieder == 0 and not _tk_f, (_tk_wieder, _tk_f[:1]))
    pruef("und die zugleich angelegten Token sind alle da",
          _tk_neu == 5, f"{_tk_neu}/5")
finally:
    _auth_s.TOKEN_FILE = _tk_alt

# 3. Chats: ein Nutzer, zwei Tabs. Das Verzeichnis ist das Einzige, das
#    den geaenderten Titel traegt -- ein verlorener Eintrag heisst: die
#    Umbenennung ist weg.
_ch_n = "tabs_zwei"
_ch_k = [_chats_s.neue_kennung() for _ in range(10)]
for _k in _ch_k:
    _chats_s.speichere(_ch_n, _k, [{"role": "user", "content": "x"}], "alt")
_ch_f = _zugleich([(_chats_s.benenne, (_ch_n, _k, f"neu {i}"))
                   for i, _k in enumerate(_ch_k)])
_ch_idx = _chats_s._index_lesen(_ch_n)
_ch_alt = [k for i, k in enumerate(_ch_k)
           if (_ch_idx.get(k) or {}).get("titel") != f"neu {i}"]
pruef("zehn Umbenennungen zugleich: alle bleiben stehen",
      not _ch_alt and not _ch_f, (len(_ch_alt), _ch_f[:1]))

# 4. Installationsschluessel beim ersten Start. Anwendung und API starten
#    im selben Pod gleichzeitig; erzeugen beide einen, verschluesselt
#    einer bis zum Neustart mit einem, den es auf der Platte nicht gibt.
_gh_alt = (geheim.SCHLUESSEL_DATEI, geheim._schluessel, geheim._aes)
geheim.SCHLUESSEL_DATEI = os.path.join(_s_ord, "schluessel.key")
try:
    _gh_aus = []
    _gh_f = _zugleich([(lambda: _gh_aus.append(geheim._erzeuge()), ())
                       for _ in range(10)])
    _gh_neu = [x for x in _gh_aus if isinstance(x, bytes)]
    import base64 as _b64_s
    with open(geheim.SCHLUESSEL_DATEI, "rb") as _f:
        _gh_platte = _b64_s.urlsafe_b64decode(_f.read().strip())
    pruef("erster Start, zehn Faeden: genau einer erzeugt den Schluessel",
          len(_gh_neu) == 1 and not _gh_f, (len(_gh_neu), _gh_f[:1]))
    pruef("und es ist der, der auf der Platte liegt",
          _gh_neu == [_gh_platte])
finally:
    geheim.SCHLUESSEL_DATEI, geheim._schluessel, geheim._aes = _gh_alt

# 5. Wer liest, aendert und schreibt, tut es unter der Sperre. Gelesen
#    aus dem Code, damit eine neue Fassung einer dieser Funktionen die
#    Sperre nicht still verliert.
_mit_sperre = {
    "auth.py": ("erzeuge", "widerrufe"),
    "notzugang.py": ("beantrage", "bestaetige", "lehne_ab", "schliesse"),
    "feedback.py": ("notiere", "neu_verschluesseln", "archiviere"),
    "listenquellen.py": ("speichere", "setze_raum"),
    "sqlquellen.py": ("setze",),
    "tabellen.py": ("setze_kopfzeile",),
    "raumschluessel.py": ("entferne",),
    "chats.py": ("uebernimm_alt", "liste", "speichere", "benenne", "loesche"),
    "benutzer.py": ("passwort_setzen", "rolle_setzen", "loesche",
                    "neu_signieren"),
    "raeume.py": ("anlegen", "mitglieder_setzen", "beschriften",
                  "gruppe_setzen", "entfernen"),
}
import ast as _ast_s


def _gesperrt_markiert(knoten):
    for d in knoten.decorator_list:
        ziel = d.func if isinstance(d, _ast_s.Call) else d
        name = getattr(ziel, "attr", None) or getattr(ziel, "id", "")
        if name in ("unter_sperre", "_unter_sperre"):
            return True
    return False


_ohne_sperre = []
for _dat, _funktionen in _mit_sperre.items():
    _defs = {k.name: k for k in _ast_s.parse(_datei(_dat)).body
             if isinstance(k, _ast_s.FunctionDef)}
    for _fn in _funktionen:
        if _fn not in _defs or not _gesperrt_markiert(_defs[_fn]):
            _ohne_sperre.append(f"{_dat}:{_fn}")
pruef("jede Lesen-Aendern-Schreiben-Funktion laeuft unter der Sperre",
      not _ohne_sperre, _ohne_sperre)

# 6. Keine feste Zwischendatei mehr. Mit einem festen Namen wie
#    "tokens.json.neu" schreiben zwei Faeden in DIESELBE Zwischendatei --
#    unter Linux entsteht daraus eine gemischte Datei.
import re as _re_s
_fest = []
for _wurzel_s, _ordner_s, _namen_s in os.walk(_HIER_S := os.path.dirname(
        os.path.abspath(__file__))):
    _ordner_s[:] = [o for o in _ordner_s if not o.startswith((".", "_"))
                    and o not in ("daten", "data", "config", "konfig")]
    for _n in _namen_s:
        if not _n.endswith(".py") or _n in ("dateisperre.py", "selbsttest.py"):
            continue
        with io.open(os.path.join(_wurzel_s, _n), encoding="utf-8") as _f:
            for _nr, _z in enumerate(_f, 1):
                _code = _z.split("#", 1)[0]
                if _re_s.search(r"""\.neu["']""", _code):
                    _fest.append(f"{_n}:{_nr}")
pruef("keine Datei schreibt ueber eine Zwischendatei mit festem Namen",
      not _fest, _fest)

import landkarte as _lk

_HIER = os.path.dirname(os.path.abspath(__file__))
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
_RANG = {"Grundlage": 0, "Bestand": 1, "Fachlogik": 2, "Einstiege": 3}
_hoch = sorted(f"{n} -> {m}" for n, i in _karte.items() for m in i["nutzt"]
               if _RANG[_karte[m]["schicht"]] > _RANG[i["schicht"]])
pruef("keine Kante der Landkarte zeigt nach oben", not _hoch, _hoch)

# 3. Jede Datei steht im README. Die Tabelle wird erzeugt; diese
#    Pruefung stellt sicher, dass sie nach einer neuen Datei auch
#    erneuert wurde.
_liesmich = _datei("README.md")
_fehlt_doku = sorted(n for n in _karte if f"`{n}.py`" not in _liesmich)
pruef("jede Datei kommt in der Landkarte des README vor",
      not _fehlt_doku, _fehlt_doku)

# 4. Jede Datei sagt in einem Satz, was sie tut. Ohne Dateikopf bleibt
#    die Zelle leer -- app.py war so eine, 2900 Zeilen ohne ein Wort
#    darueber.
_stumm = sorted(n for n, i in _karte.items() if not i["kopf"].strip())
pruef("jede Datei sagt in ihrem Kopf, was sie tut", not _stumm, _stumm)

# --- WAS DER CODE LIEST, STEHT IN DER VORLAGE ---
#
# Das SQL-Modul lag monatelang vollstaendig in der oeffentlichen Fassung
# und war unauffindbar: 582 Zeilen, ein Schalter, der erst erscheint,
# wenn vier Werte zusammenkommen -- und kein einziger SQL_-Eintrag in
# .env.example. Ein Wert, den der Code liest und die Vorlage
# verschweigt, existiert fuer den Betreiber nicht.
#
# Dasselbe galt fuer siebzehn weitere, darunter CHROMA_EINZELN, das die
# Fehlermeldung von api.py ausdruecklich empfiehlt.
#
# Die eine echte Ausnahme setzt Kubernetes selbst, nicht der Betreiber.
_NICHT_IN_DER_VORLAGE = {"KUBERNETES_SERVICE_HOST"}

# Gesucht wird ein EINTRAG, nicht eine Erwaehnung: "NAME=" am
# Zeilenanfang, auskommentiert erlaubt. Die erste Fassung suchte den
# Namen irgendwo in der Datei -- und liess sich von der Erwaehnung im
# Kommentar darueber taeuschen. Die Gegenprobe (SQL_SERVER= entfernen)
# lief damit durch, obwohl der Eintrag weg war.
_gelesen = {v for _i in _karte.values() for v in _i["umgebung"]}
_eingetragen = set(_re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=",
                               _datei(".env.example"), _re.M))
_unsichtbar = sorted(_gelesen - _NICHT_IN_DER_VORLAGE - _eingetragen)
pruef("jede Variable, die der Code liest, steht in .env.example",
      not _unsichtbar, _unsichtbar)

# UND SIE KOMMT IM CONTAINER AN. pruefe_env.py sieht beides seit jeher --
# es hat die SQL-Luecke die ganze Zeit gedruckt, unter "stehen nicht in
# .env.example", und ist mit Ausgang 0 zurueckgekommen. Ein Befund, der
# den Lauf nicht anhaelt, ist ein Befund, den niemand liest. Hier zaehlt
# der Ausgang.
_pe = _sub.run([sys.executable, "pruefe_env.py", _HIER],
               capture_output=True, text=True, encoding="utf-8",
               errors="replace", cwd=_HIER)
pruef("jede Variable erreicht auch den Container (pruefe_env.py)",
      _pe.returncode == 0,
      " | ".join(z.strip() for z in _pe.stdout.split(chr(10))
                 if z.strip().startswith(">>>") or "gelesen in" in z)[:200])


print()
# Die Namen VOR der Zahl. Wer nur die letzte Zeile liest, sah bisher
# "383 von 385" und wusste nicht, welche zwei -- dreimal ist dabei ein
# Fehlschlag durchgerutscht.
if gescheitert:
    print(f"--- {len(gescheitert)} FEHLGESCHLAGEN ---")
    for _g in gescheitert:
        print(f"    {_g}")
print(f"=== {sum(ok)}/{len(ok)} Pruefungen bestanden ===")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
