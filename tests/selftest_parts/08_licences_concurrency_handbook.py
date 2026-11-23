"""Self-test, part 08: AGPL offer, licence list, concurrent writes, the handbook.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- DER QUELLENHINWEIS IST DER NACHWEIS, NICHT DAS SCHMUCKSTUECK ---
#
# Die Anwendung steht unter AGPL-3.0, weil pymupdf es tut und das Lesen
# von PDF traegt. Paragraph 13 der AGPL verlangt, dass Nutzer, die ueber
# ein NETZ mit ihr arbeiten, an ihren Quelltext kommen -- und genau
# die Zeile unter der Anmeldung und den Einstellungen ist das Angebot
# dazu.
#
# Verschwindet sie bei einem Umbau, faellt es sonst niemandem auf: eine
# fehlende Fusszeile stuerzt nicht ab.
_lizenz = _datei("LICENSE")
pruef("die Anwendung steht unter AGPL",
      "AFFERO GENERAL PUBLIC LICENSE" in _lizenz and "MIT License" not in _lizenz)
for _seite in ("login.html", "settings.html"):
    _sq = _datei(os.path.join("web_templates", _seite))
    pruef(f"{_seite} bietet den Quelltext an",
          "github.com/mw-research/LocaNoto" in _sq and "agpl-3.0" in _sq)


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
statefiles.makedirs(_s_ord, exist_ok=True)

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
    with statefiles.open(geheim.SCHLUESSEL_DATEI, "rb") as _f:
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
for _wurzel_s, _ordner_s, _namen_s in os.walk(_HIER_S := _ROOT):
    _ordner_s[:] = [o for o in _ordner_s if not o.startswith((".", "_"))
                    and o not in ("daten", "data", "config", "konfig")]
    for _n in _namen_s:
        if not _n.endswith(".py") or _n in ("dateisperre.py", "tests/selftest.py"):
            continue
        with statefiles.open(os.path.join(_wurzel_s, _n), encoding="utf-8") as _f:
            for _nr, _z in enumerate(_f, 1):
                _code = _z.split("#", 1)[0]
                if _re_s.search(r"""\.neu["']""", _code):
                    _fest.append(f"{_n}:{_nr}")
pruef("keine Datei schreibt ueber eine Zwischendatei mit festem Namen",
      not _fest, _fest)

# --- DAS HANDBUCH FOLGT DER OBERFLAECHE ---
#
# HANDBUCH.md wird in LocaNoto eingelesen, damit die Anwendung Fragen zu
# ihrer eigenen Bedienung beantwortet. Ein Bereich, den es in der
# Oberflaeche gibt und im Handbuch nicht, ist fuer diese Fragen
# unsichtbar -- LocaNoto antwortet dann "steht nicht im Bestand".
#
# Die Seiten sind die Punkte der oberen Leiste und der Verwaltung. Jeder
# steht in beiden Handbuechern unter dem Namen, den die Seite zeigt:
# deutsch aus web.TEXTS, englisch der Schluessel.
import translations as _tr_h
_tr_de = _tr_h.german_texts()
_seiten = []
for _vorlage in ("base.html", "admin_nav.html"):
    _seiten += [t for _q, t in _tr_h._TEMPLATE_T.findall(
        _datei(os.path.join("web_templates", _vorlage)))]
_hb_de_text, _hb_en_text = _datei("HANDBUCH.md"), _datei("HANDBUCH.en.md")
_hb_fehlt = sorted({f"de: {_tr_de.get(s, s)}" for s in _seiten
                    if _tr_de.get(s, s) not in _hb_de_text}
                   | {f"en: {s}" for s in _seiten if s not in _hb_en_text})
pruef("jede Seite der Oberflaeche steht in beiden Handbuechern",
      len(_seiten) >= 15 and not _hb_fehlt, _hb_fehlt)

# Eingelesen wird es wie jedes Markdown: je Ueberschrift ein Abschnitt,
# ab 1500 Zeichen weiter zerteilt. Ein zerteilter Abschnitt verliert
# seine Ueberschrift -- und die Ueberschrift ist die Frage, ueber die er
# gefunden wird.
import lesen as _lesen_h
_hb_ab = list(_lesen_h.abschnitte(os.path.join(_HIER_S, "HANDBUCH.md")))
_hb_lang = [t for _n, t, x in _hb_ab if len(x) > 1500]
pruef("jeder Abschnitt des Handbuchs bleibt beim Einlesen ein Stueck",
      _hb_ab and not _hb_lang, _hb_lang)
pruef("die README verweist auf Handbuch und Referenz",
      "HANDBUCH.md" in _datei("README.md") and "REFERENZ.md" in _datei("README.md")
      and "HANDBUCH.en.md" in _datei("README.en.md"))
