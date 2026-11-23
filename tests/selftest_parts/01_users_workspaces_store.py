"""Self-test, part 01: Users and roles, workspaces, the store, search, encrypted chats, feedback, backups, lists, emergency access.

Runs only through tests/selftest.py, after the parts before it.
"""
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
# Der Server bedient alle Sitzungen in einem Prozess. Ohne Sperre lasen
# gleichzeitige Verwalter denselben Stand der Benutzerdatei, und der
# letzte Schreiber loeschte, was die anderen angelegt hatten -- bei drei
# Verwaltern mit je drei Nutzern kamen von neun gemeldeten einer an.
#
# Gemessen in eigenen Dateien, damit die neun Zugaenge den uebrigen
# Selbsttest nicht beruehren.
import threading as _th_g
_g_alt = (benutzer._datei, benutzer.PROTOKOLL, raeume.DATEI)
_g_ord = os.path.join(tmp, "gleichzeitig")
statefiles.makedirs(_g_ord, exist_ok=True)
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
roh = statefiles.open(os.path.join(chats.ordner("anna"), k), "rb").read()
pruef("Chatdatei verschluesselt", geheim.ist_verschluesselt(roh))
pruef("kein Klartext in der Datei", b"Kabel" not in roh)
pruef("Titel nicht im Dateinamen", "Titel" not in k)
pruef("anna liest ihren Chat", chats.lade("anna", k)[0]["content"].startswith("Geheime"))
pruef("markus liest ihn NICHT", chats.lade("markus", k) == [])

print("=== 6. Rueckmeldungen und Sicherung ===")
feedback.notiere("leer", "anna", "Welche Kabel gab es 2018?")
pruef("Rueckmeldung verschluesselt",
      b"Kabel" not in statefiles.open(feedback.DATEI, "rb").read())
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
statefiles.makedirs(paths.DOCS_DIR, exist_ok=True)
_wurzel_datei = os.path.join(paths.DOCS_DIR, "Angebot.pdf")
statefiles.open(_wurzel_datei, "wb").write(b"AUS DEM WURZELBEREICH")
_ek_ordner = paths.raum_ordner("einkauf")
statefiles.makedirs(_ek_ordner, exist_ok=True)
_ek_datei = os.path.join(_ek_ordner, "Angebot.pdf")
statefiles.open(_ek_datei, "wb").write(b"AUS DEM EINKAUF")

_fremd = lambda eigen: [paths.raum_ordner(k) for k in raeume.liste()
                        if k != eigen]
_gefunden = paths.finde_dokument(
    "Angebot.pdf", bevorzugt=paths.raum_ordner("einkauf"),
    ausser=_fremd("einkauf"))
pruef("einkauf findet SEINE Datei",
      _gefunden and statefiles.open(_gefunden, "rb").read() == b"AUS DEM EINKAUF")
_gefunden = paths.finde_dokument(
    "Angebot.pdf",
    bevorzugt=paths.raum_ordner(raeume.privat_kennung("anna")),
    ausser=_fremd(raeume.privat_kennung("anna")))
pruef("anna bekommt NICHT die Datei des Einkaufs",
      _gefunden and statefiles.open(_gefunden, "rb").read() == b"AUS DEM WURZELBEREICH")

# Der scharfe Fall: die Datei liegt NUR im Ordner des Einkaufs. Vorher
# fand os.walk sie fuer jeden, der nach dem Namen fragte.
statefiles.open(os.path.join(_ek_ordner, "Preisliste.pdf"), "wb").write(b"NUR EINKAUF")
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
      b"Kuendigung" not in statefiles.open(feedback.DATEI, "rb").read())

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


# The segment failure is Chroma's alone. On Postgres there is nothing to
# reconnect, so store.hole passes the error on, like with a Chroma server.
if not database.active():
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
      json.load(statefiles.open(os.path.join(sicherung.ORDNER, _schlecht["name"],
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
# The admin created "chef" and so knows the first password. Until chef
# sets an own one, the account is not a second person.
pruef("solange der Antragsteller das Passwort vergeben hat, nicht",
      not notzugang.bestaetige(_pa, "markus", "chef")[0])
benutzer.passwort_setzen("chef", "chefs-eigenes-passwort", von="chef")
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
_roh = json.load(statefiles.open(notzugang.DATEI, encoding="utf-8"))
_roh["inhalt"]["zugaenge"][0]["von"] = "anna"
json.dump(_roh, statefiles.open(notzugang.DATEI, "w", encoding="utf-8"))
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
if database.active():
    # The Postgres index holds no text; a hit needs its passage.
    store.schreibe(store.sammlung(raeume.sammlung("einkauf")),
                   ["namensprobe_1"], documents=["Ein Abschnitt zur Probe"],
                   metadatas=[{"file_name": _n, "raum": "einkauf",
                               "page": 1}], embeddings=[vek()])
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
    statefiles.makedirs(_o, exist_ok=True)
    with statefiles.open(os.path.join(_o, "liste.csv"), "w", encoding="utf-8") as _f:
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
with statefiles.open(tabellen.PFAD_DATEI, "w", encoding="utf-8") as _f:
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
statefiles.remove(tabellen.PFAD_DATEI)

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
_text = statefiles.open(tabellen.KATALOG, encoding="utf-8").read()
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
statefiles.makedirs(_ferne, exist_ok=True)
with statefiles.open(os.path.join(_ferne, "preise.csv"), "w", encoding="utf-8") as _f:
    _f.write("Artikel;Preis\nSchraube;0,12\n")

_oc.eingerichtet = lambda: True
_oc.dateien = lambda pfad, endungen=None, tiefe=8: [
    {"rel": "preise.csv", "fern": "Listen/preise.csv",
     "groesse": 30, "etag": _etag[0], "geaendert": ""}]
_oc.hole = lambda fern, ziel: (
    statefiles.makedirs(os.path.dirname(ziel), exist_ok=True),
    statefiles.open(ziel, "wb").write(
        statefiles.open(os.path.join(_ferne, "preise.csv"), "rb").read()))[1]
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
with statefiles.open(os.path.join(_ferne, "preise.csv"), "w", encoding="utf-8") as _f:
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
# The admin list lives in doc_actions.foreign_documents since the page
# and the server share it.
_quelle_da = statefiles.open(os.path.join(_ROOT, "doc_actions.py"), encoding="utf-8").read()
_a = _quelle_da.index("def foreign_documents(")
_rumpf = _quelle_da[_a:_quelle_da.index("\ndef ", _a + 10)]
pruef("die Verwaltungsansicht zeigt Kennungen statt Namen",
      "datei_id" in _rumpf)
pruef("und schliesst die Namen NICHT auf",
      "metadaten_klartext" not in _rumpf)

import re as _re
import subprocess as _sub

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
_roh = statefiles.open(sqlquellen.QUELLEN, encoding="utf-8").read()
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
# Der Server beantwortet Anfragen in Faeden im SELBEN Prozess.
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
