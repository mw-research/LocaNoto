"""Self-test, part 09: Deleting and moving in ownCloud too, ownCloud/OpenCloud accounts and groups.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- WAS IN LOCANOTO GELOESCHT WIRD, BLEIBT GELOESCHT ---
#
# Geloescht wurde nur in LocaNoto; die Datei blieb in ownCloud liegen, und
# der naechste Abgleich behandelte sie als neu -- sie stand am Morgen
# wieder in der Suche. Beim Verschieben dasselbe: die Datei kam in den
# alten Raum zurueck.
#
# Gemessen gegen eine nachgebaute WebDAV-Sitzung, die mitschreibt, was
# LocaNoto schickt. Ein echtes ownCloud braucht es dafuer nicht.
import owncloud as _ocl
import raeume as _rl


class _OcSitzung:
    def __init__(self, antwort):
        self.antwort, self.rufe = antwort, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _ruf(self, methode, url, **k):
        self.rufe.append((methode, url, dict(k.get("headers") or {})))
        return type("A", (), {"status_code": self.antwort})()

    def delete(self, url, **k):
        return self._ruf("DELETE", url, **k)

    def request(self, methode, url, **k):
        return self._ruf(methode, url, **k)


_ocl_alt = (_ocl.URL, _ocl.BENUTZER, _ocl.PASSWORT, _ocl._sitzung,
            _ocl.ordner_anlegen)
_ocl.URL, _ocl.BENUTZER, _ocl.PASSWORT = "https://oc.test", "dienst", "x"
_ocl.ordner_anlegen = lambda p: True
try:
    _lokal_l = os.path.join(_ocl.ablage(_rl.ALLGEMEIN), "Kessel",
                            "Betriebsanweisung.pdf")
    _s = _OcSitzung(204)
    _ocl._sitzung = lambda: _s
    _ok_l, _m_l = _ocl.entferne(_rl.ALLGEMEIN, "Betriebsanweisung.pdf",
                                _lokal_l)
    pruef("Loeschen trifft in ownCloud dieselbe Datei wie das Hochladen",
          _ok_l and _s.rufe and _s.rufe[0][0] == "DELETE"
          and _s.rufe[0][1] == _ocl._url(
              _ocl.ziel_pfad(_rl.ALLGEMEIN, _lokal_l)),
          _s.rufe)

    _s = _OcSitzung(404)
    _ocl._sitzung = lambda: _s
    pruef("eine Datei, die in ownCloud nicht liegt, ist kein Fehler",
          _ocl.entferne(_rl.ALLGEMEIN, "x.pdf", _lokal_l)[0])

    _s = _OcSitzung(503)
    _ocl._sitzung = lambda: _s
    _ok_f, _m_f = _ocl.entferne(_rl.ALLGEMEIN, "x.pdf", _lokal_l)
    pruef("ein gescheitertes Loeschen in ownCloud wird gemeldet, nicht "
          "verschluckt", not _ok_f and "503" in _m_f, _m_f)

    _von = os.path.join(_ocl.ablage(_rl.ALLGEMEIN), "Angebot.pdf")
    _nach = os.path.join(_ocl.ablage("einkauf"), "Angebot.pdf")
    _s = _OcSitzung(201)
    _ocl._sitzung = lambda: _s
    _ok_v, _m_v = _ocl.verschiebe(_rl.ALLGEMEIN, _von, "einkauf", _nach)
    _h = _s.rufe[0][2] if _s.rufe else {}
    pruef("Verschieben verschiebt in ownCloud mit, ohne zu ueberschreiben",
          _ok_v and _s.rufe and _s.rufe[0][0] == "MOVE"
          and _h.get("Destination") == _ocl._url(
              _ocl.ziel_pfad("einkauf", _nach))
          and _h.get("Overwrite") == "F", _s.rufe)
except Exception as e:
    # Fehlt eine der Funktionen, soll das als Fehlschlag dastehen und
    # nicht den ganzen Lauf beenden.
    pruef("Loeschen und Verschieben in ownCloud sind vorhanden", False,
          f"{type(e).__name__}: {e}")
finally:
    (_ocl.URL, _ocl.BENUTZER, _ocl.PASSWORT, _ocl._sitzung,
     _ocl.ordner_anlegen) = _ocl_alt

# Der Loeschweg steht in aufnehmen.entferne_dokument; die Oberflaeche und
# die Schnittstelle rufen ihn beide.
_auf_q = _datei("aufnehmen.py")
_ent_q = ""
for _k in _ast.parse(_auf_q).body:
    if isinstance(_k, _ast.FunctionDef) and _k.name == "entferne_dokument":
        _ent_q = _ast.unparse(_k)
pruef("Loeschen loescht in ownCloud mit",
      "entferne_dokument(" in _datei("doc_actions.py")
      and _ent_q.count("owncloud.entferne(") == 2, _ent_q.count("owncloud.entferne("))

# --- LOESCHEN UEBER DIE SCHNITTSTELLE ---
#
# DELETE /dokumente nimmt denselben Weg wie der Knopf. Geprueft wird der
# Weg selbst, mit echter Sammlung und echtem Stichwortindex; die
# Schnittstelle uebersetzt nur noch die Ausnahmen in 403 und 404.
_lp_raum = raeume.privat_kennung("markus")
_lp_name = "loesch_probe.md"
_lp_text = ("# Loeschprobe\n\nDie Pruefristen fuer Abscheider betragen "
            "fuenf Jahre und stehen nur in diesem Dokument.\n")
try:
    _auf.process_uploaded_pdf(_Hochgeladene(_lp_name, _lp_text), _lp_raum,
                              benutzer_="markus")
    _lp_sml = store.sammlung(raeume.sammlung(_lp_raum), anlegen=False)
    _lp_vorher = len(_lp_sml.get(where=store.datei_filter(_lp_name),
                                 include=[])["ids"])

    def _lp_im_index():
        return [t for t in keyword_index.search(
                    "Abscheider", "markus", limit=20, raeume=[_lp_raum])
                if (t.get("meta") or {}).get("file_name") == _lp_name]
    _lp_kw_vorher = len(_lp_im_index())

    # 1. Ein anderer Nutzer darf in markus' Raum nicht loeschen -- und
    #    erfaehrt dabei nicht, ob es die Datei gibt.
    try:
        _auf.entferne_dokument(_lp_name, _lp_raum, benutzer_="anna")
        _lp_fremd = "geloescht"
    except _auf.KeinRecht:
        _lp_fremd = "403"
    try:
        _auf.entferne_dokument("gibt_es_nicht.pdf", _lp_raum,
                               benutzer_="anna")
        _lp_fremd2 = "?"
    except _auf.KeinRecht:
        _lp_fremd2 = "403"
    except _auf.NichtGefunden:
        _lp_fremd2 = "404 -- verraet, was dort liegt"
    pruef("ein fremder Nutzer bekommt 403, auch fuer eine Datei, die es "
          "nicht gibt", _lp_fremd == "403" and _lp_fremd2 == "403",
          (_lp_fremd, _lp_fremd2))

    # 2. Der Besitzer, eine Datei, die es nicht gibt: 404 statt "entfernt".
    try:
        _auf.entferne_dokument("gibt_es_nicht.pdf", _lp_raum,
                               benutzer_="markus")
        _lp_nicht = "entfernt gemeldet"
    except _auf.NichtGefunden:
        _lp_nicht = "404"
    pruef("eine Datei, die nicht im Raum liegt, ergibt 404",
          _lp_nicht == "404", _lp_nicht)

    # 3. Der Besitzer loescht.
    _lp_meld, _lp_ber = _auf.entferne_dokument(_lp_name, _lp_raum,
                                               benutzer_="markus")
    _lp_nachher = len(_lp_sml.get(where=store.datei_filter(_lp_name),
                                  include=[])["ids"])
    _lp_kw = _lp_im_index()
    pruef("der Besitzer loescht: alle Abschnitte weg, Zahl gemeldet",
          _lp_vorher > 0 and _lp_nachher == 0
          and _lp_ber["abschnitte"] == _lp_vorher,
          (_lp_vorher, _lp_nachher, _lp_ber))
    # Vorher MUSS die Suche es finden -- sonst bewiese "danach nicht
    # gefunden" nichts.
    pruef("und aus dem Stichwortindex ebenso",
          _lp_kw_vorher > 0 and not _lp_kw, (_lp_kw_vorher, len(_lp_kw)))
    pruef("ohne ownCloud ist ownCloud nicht betroffen",
          _lp_ber["owncloud"] == "nicht betroffen", _lp_ber)
except Exception as e:
    pruef("das Loeschen ueber den gemeinsamen Weg laesst sich pruefen",
          False, f"{type(e).__name__}: {e}")

_api_q = _datei("api.py")
pruef("die Schnittstelle hat DELETE /dokumente auf dem gemeinsamen Weg",
      '@app.delete("/dokumente")' in _api_q
      and "aufnehmen.entferne_dokument(" in _api_q
      and "benutzer_=kennung" in _api_q[_api_q.find('@app.delete("/dokumente")'):]
      and "status_code=403" in _api_q and "status_code=404" in _api_q)
pruef("Verschieben verschiebt in ownCloud mit",
      "owncloud.verschiebe(" in _datei("doc_actions.py"))

# --- OWNCLOUD-KONTEN FOLGEN LOCANOTO, ABER NUR DIE EIGENEN ---
#
# Ein Benutzer, der in LocaNoto geloescht wird, verschwindet auch in
# ownCloud; ein neues Passwort gilt auch dort. Aber nur fuer Konten, die
# LocaNoto verwaltet: ein Konto, das es vorher gab, kann einem Menschen
# gehoeren, der es fuer alles andere im Haus nutzt. Und nie das Dienst-
# oder Verwalterkonto -- ein LocaNoto-Nutzer "admin" loeschte sonst das
# Konto, mit dem LocaNoto selbst in ownCloud arbeitet.
import owncloud as _ock

# Gesichert ueber getattr: fehlt einem aelteren owncloud.py eines davon,
# soll die Pruefung FALLEN und nicht den ganzen Lauf beenden.
_ock_namen = ("URL", "BENUTZER", "PASSWORT", "ADMIN_BENUTZER", "KONTEN",
              "_ocs_ruf", "_sitzung", "_eintraege", "_GRAPH", "_graph",
              "requests")
_ock_alt = {n: getattr(_ock, n, None) for n in _ock_namen}
_ock.URL, _ock.BENUTZER, _ock.PASSWORT = "https://oc.test", "dienst", "x"
_ock.ADMIN_BENUTZER = "admin"
# Ein ownCloud 10: Nutzer ueber OCS. Fest eingetragen, damit niemand
# im Netz nachsieht.
_ock._GRAPH = {"https://oc.test": False}
_ock.KONTEN = os.path.join(tmp, "owncloud_konten.json")
_ocs_rufe = []
_ocs_da = {"admin", "dienst", "fremd"}


def _ocs_nach(methode, pfad, daten=None, app=None):
    _ocs_rufe.append((methode, pfad, dict(daten or {})))
    k = pfad.split("/", 1)[1] if pfad.startswith("users/") else ""
    if methode == "GET" and k not in _ocs_da:
        raise ValueError("ownCloud antwortete mit Status 998")
    if methode == "POST":
        _ocs_da.add(daten["userid"])
    if methode == "DELETE":
        _ocs_da.discard(k)
    return {}


_ock._ocs_ruf = _ocs_nach
try:
    _ock.nutzer_anlegen("neu_k", "passwort123")
    pruef("ein von LocaNoto angelegtes Konto gilt als verwaltet",
          _ock.verwaltet("neu_k"))
    pruef("ein vorher vorhandenes nicht",
          not _ock.verwaltet("fremd")
          and _ock.nutzer_anlegen("fremd", "x" * 10)[1] == "gab es schon"
          and not _ock.verwaltet("fremd"))

    _ocs_rufe.clear()
    _ok_k, _m_k = _ock.konto_loeschen("neu_k")
    pruef("Benutzer loeschen loescht sein verwaltetes ownCloud-Konto mit",
          _ok_k and ("DELETE", "users/neu_k", {}) in _ocs_rufe
          and not _ock.verwaltet("neu_k"), _ocs_rufe)

    _ocs_rufe.clear()
    _ok_f, _m_f = _ock.konto_loeschen("fremd")
    pruef("ein fremdes Konto bleibt, und das wird gesagt",
          not _ok_f and not any(r[0] == "DELETE" for r in _ocs_rufe)
          and "fremd" in _ocs_da, _m_f)

    # Selbst in der Liste: das Verwalterkonto nie.
    _ock._konten_aendern(dazu=["admin"])
    _ocs_rufe.clear()
    pruef("das ownCloud-Verwalterkonto wird nie geloescht",
          not _ock.konto_loeschen("admin")[0]
          and not any(r[0] == "DELETE" for r in _ocs_rufe)
          and "admin" in _ocs_da, _ocs_rufe)

    _ock.nutzer_anlegen("pw_k", "passwort123")
    _ocs_rufe.clear()
    pruef("ein neues Passwort gilt auch in ownCloud",
          _ock.passwort_setzen("pw_k", "neues123")[0]
          and ("PUT", "users/pw_k",
               {"key": "password", "value": "neues123"}) in _ocs_rufe,
          _ocs_rufe)
    _ocs_rufe.clear()
    pruef("bei einem fremden Konto nicht",
          not _ock.passwort_setzen("fremd", "neues123")[0]
          and not any(r[0] == "PUT" for r in _ocs_rufe))

    _dazu_u, _aus_u = _ock.konten_uebernehmen(["fremd", "admin", "gibtsnicht"])
    pruef("Uebernehmen vermerkt vorhandene Konten, nie das Dienstkonto",
          _dazu_u == ["fremd"] and _ock.verwaltet("fremd")
          and not _ock.verwaltet("admin"), (_dazu_u, _aus_u))

    # Raumordner leeren: jeder Eintrag geht per DELETE in den Papierkorb,
    # und der Stand des Abgleichs wird vergessen.
    class _LeerSitzung:
        rufe = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def delete(self, url, **k):
            self.rufe.append(url)
            return type("A", (), {"status_code": 204})()

    _ls = _LeerSitzung()
    _ock._sitzung = lambda: _ls
    _ock._eintraege = lambda s, p: [("a.pdf", False, 1, "e", ""),
                                    ("Projekt", True, 0, "e", "")]
    _st_d = _ock._stand_datei("einkauf")
    statefiles.makedirs(os.path.dirname(_st_d), exist_ok=True)
    statefiles.open(_st_d, "w", encoding="utf-8").write('{"a.pdf": {}}')
    _n_l, _f_l = _ock.leere_raumordner("einkauf")
    _o_l = (_ock.ordner_fuer("einkauf") or _ock.raum_pfad("einkauf")).rstrip("/")
    pruef("Daten loeschen leert auch den ownCloud-Ordner des Raums",
          _n_l == 2 and not _f_l
          and _ls.rufe == [_ock._url(f"{_o_l}/a.pdf"),
                           _ock._url(f"{_o_l}/Projekt")]
          and not statefiles.exists(_st_d), (_n_l, _f_l, _ls.rufe))
except Exception as e:
    pruef("ownCloud-Konten und Raumordner lassen sich pruefen", False,
          f"{type(e).__name__}: {e}")
finally:
    for _n, _w in _ock_alt.items():
        setattr(_ock, _n, _w)

# --- OPENCLOUD UND OCIS: NUTZER UND GRUPPEN UEBER GRAPH ---
#
# Dort gibt es /ocs/v1.php/cloud nicht mehr. Dateien und Freigaben gehen
# wie bisher; Nutzer und Gruppen ueber /graph/v1.0. Welche Art Server
# dahinter steht, sieht ist_graph() an /graph/v1.0/me nach.
_ock_alt = {n: getattr(_ock, n, None) for n in _ock_namen}
_ock.URL, _ock.BENUTZER, _ock.PASSWORT = "https://oc2.test", "dienst", "x"
_ock.ADMIN_BENUTZER = "admin"
_ock.KONTEN = os.path.join(tmp, "owncloud_konten_graph.json")
_gr_rufe, _gr_da = [], {"admin", "dienst", "fremd"}
_ocs_rufe.clear()


def _graph_nach(methode, pfad, daten=None, params=None):
    _gr_rufe.append((methode, pfad, daten, params))
    k = pfad.split("/", 1)[1] if pfad.startswith("users/") else ""
    if methode == "GET" and pfad.startswith("users/"):
        return {"id": "x"} if k in _gr_da else None
    if methode == "POST" and pfad == "users":
        _gr_da.add(daten["onPremisesSamAccountName"])
    if methode == "DELETE":
        _gr_da.discard(k)
    if methode == "GET" and pfad.startswith("groups/"):
        if pfad != "groups/Abteilung%20Einkauf":
            return None
        return {"members": [{"onPremisesSamAccountName": "Anna"},
                            {"onPremisesSamAccountName": "bernd"}]}
    return {}


try:
    _ock._GRAPH = {"https://oc2.test": True}
    _ock._graph = _graph_nach
    # Ruft ein Stand ohne Graph doch OCS, soll das auffallen und nicht
    # ins Netz gehen.
    _ock._ocs_ruf = _ocs_nach
    _ock.nutzer_anlegen("neu_g", "passwort123")
    pruef("OpenCloud: ein Konto entsteht ueber Graph, mit Anzeigename",
          ("POST", "users", {"onPremisesSamAccountName": "neu_g",
                             "displayName": "neu_g",
                             "passwordProfile": {"password": "passwort123"}},
           None) in _gr_rufe
          and _ock.verwaltet("neu_g") and not _ocs_rufe, _gr_rufe)

    _gr_rufe.clear()
    try:
        _ock.nutzer_anlegen("müller", "passwort123")
        _gr_um = "kein Fehler"
    except ValueError as e:
        _gr_um = str(e)
    pruef("OpenCloud: eine Kennung mit Umlaut wird vorher und "
          "verstaendlich abgelehnt",
          "a-z" in _gr_um
          and not any(r[0] == "POST" for r in _gr_rufe), (_gr_um, _gr_rufe))

    _gr_rufe.clear()
    pruef("OpenCloud: ein neues Passwort ueber Graph",
          _ock.passwort_setzen("neu_g", "neues123")[0]
          and ("PATCH", "users/neu_g",
               {"passwordProfile": {"password": "neues123"}}, None)
          in _gr_rufe, _gr_rufe)

    # Nach einem Umzug gibt es die Konten in der neuen Ablage nicht --
    # Passwoerter lassen sich nicht mitnehmen. Das naechste Passwort legt
    # das Konto an.
    _gr_rufe.clear()
    _ok_u, _m_u = _ock.passwort_setzen("umzug_g", "neues123")
    pruef("ein Passwort fuer ein fehlendes Konto legt es an",
          _ok_u and "umzug_g" in _gr_da and _ock.verwaltet("umzug_g"),
          (_m_u, _gr_rufe))
    _gr_rufe.clear()
    pruef("ein vorhandenes fremdes bleibt dabei unangetastet",
          not _ock.passwort_setzen("fremd", "neues123")[0]
          and not any(r[0] in ("PATCH", "POST") for r in _gr_rufe),
          _gr_rufe)
    _gr_da.discard("dienst")
    _gr_rufe.clear()
    pruef("und das Dienstkonto entsteht so nie",
          not _ock.passwort_setzen("dienst", "neues123")[0]
          and not any(r[0] == "POST" for r in _gr_rufe), _gr_rufe)

    _gr_rufe.clear()
    pruef("OpenCloud: Benutzer loeschen loescht das Konto ueber Graph",
          _ock.konto_loeschen("neu_g")[0]
          and ("DELETE", "users/neu_g", None, None) in _gr_rufe
          and "neu_g" not in _gr_da, _gr_rufe)

    pruef("OpenCloud: Gruppenmitglieder ueber Graph, klein geschrieben",
          _ock.mitglieder("Abteilung Einkauf") == ["anna", "bernd"],
          _gr_rufe[-1:])
    try:
        _ock.mitglieder("Gibtsnicht")
        _gr_fehlt = "kein Fehler"
    except ValueError as e:
        _gr_fehlt = str(e)
    pruef("eine fehlende Gruppe ist ein Fehler, keine leere Gruppe",
          "gibt es nicht" in _gr_fehlt, _gr_fehlt)
    pruef("und nichts davon ging an OCS", not _ocs_rufe, _ocs_rufe)
except Exception as e:
    pruef("Graph-Anbindung laesst sich pruefen", False,
          f"{type(e).__name__}: {e}")
finally:
    for _n, _w in _ock_alt.items():
        setattr(_ock, _n, _w)

# Die Erkennung selbst, mit einer nachgestellten Antwort auf
# /graph/v1.0/me.
_ock_alt = {n: getattr(_ock, n, None) for n in _ock_namen}


def _erkenne(code, inhalt):
    class _A:
        status_code = code
        ok = code < 400
        text = inhalt

        def json(self):
            return json.loads(inhalt)

        def raise_for_status(self):
            raise RuntimeError(str(code))

    class _S:
        auth = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            return _A()

    _ock.requests = types.SimpleNamespace(Session=_S)
    _ock.URL = f"https://erkennung{code}{len(inhalt)}.test"
    _ock._GRAPH = {}
    try:
        return _ock.ist_graph()
    except Exception as e:
        return type(e).__name__
    finally:
        _ock.requests = _ock_alt["requests"]


try:
    pruef("OpenCloud und oCIS werden erkannt",
          _erkenne(200, '{"id": "6d87", "displayName": "Admin"}') is True)
    pruef("ownCloud 10 (Anmeldeseite statt JSON) und Nextcloud (404) nicht",
          _erkenne(200, "<html>Anmelden</html>") is False
          and _erkenne(404, "") is False)
    pruef("eine abgelehnte Anmeldung ist ein Fehler und wird nicht gemerkt",
          _erkenne(401, "") == "PermissionError"
          and _ock.URL not in (_ock._GRAPH or {}))
finally:
    for _n, _w in _ock_alt.items():
        setattr(_ock, _n, _w)

# Nach dem Umzug gibt es in der neuen Ablage nur die Konten, deren
# Passwort schon gesetzt wurde. Eine Freigabe an jemanden ohne Konto
# lehnt sie mit 998 ab -- das darf nicht die Freigaben aller anderen
# und damit den ganzen Raum abbrechen.
_ock_alt = {n: getattr(_ock, n, None) for n in _ock_namen
            + ("freigaben", "freigeben", "freigabe_entfernen",
               "ordner_anlegen", "richte_raum_ein", "nutzer_vorhanden",
               "nutzer_anlegen", "freigaben_nachziehen")}
_fg_rufe, _fg_fehlend = [], set()


def _fg_freigeben(pfad, an, art="nutzer", rechte=1):
    _fg_rufe.append((art, an))
    if an in ("ohnekonto", "Fremdgruppe") or an in _fg_fehlend:
        raise ValueError("ownCloud antwortete mit Status 998: user not found")
    if an == "kaputt":
        raise ValueError("ownCloud antwortete mit Status 400: bad request")
    return True


try:
    _ock.URL, _ock.BENUTZER, _ock.PASSWORT = "https://oc3.test", "dienst", "x"
    _ock.freigaben = lambda pfad: []
    _ock.freigeben = _fg_freigeben
    _ock.freigabe_entfernen = lambda k: True
    _fg_ohne = []
    _fg_erg = _ock.freigaben_setzen("/LocaNoto/allgemein",
                                    ["anna", "ohnekonto", "bernd"],
                                    gruppen_=["Fremdgruppe"],
                                    ohne_konto=_fg_ohne)
    pruef("ein Nutzer ohne Konto in der Ablage wird uebersprungen, die "
          "anderen bekommen ihre Freigabe",
          _fg_erg == (2, 0) and _fg_ohne == ["ohnekonto", "Gruppe Fremdgruppe"]
          and ("nutzer", "bernd") in _fg_rufe, (_fg_erg, _fg_ohne, _fg_rufe))
    try:
        _ock.freigaben_setzen("/x", ["kaputt"])
        _fg_echt = "kein Fehler"
    except ValueError as e:
        _fg_echt = str(e)
    pruef("ein anderer Fehler bricht weiter ab", "400" in _fg_echt, _fg_echt)

    _ock.ordner_anlegen = lambda pfad: True
    _fg_fehlend.add(sorted(benutzer.namen())[-1])
    _fg_b = _ock.richte_raum_ein(raeume.ALLGEMEIN)
    pruef("'Ablage einrichten' meldet den Raum als eingerichtet und nennt, "
          "wer noch kein Konto hat",
          not _fg_b["fehler"] and any("ohne Konto" in x
                                      for x in _fg_b["schritte"]), _fg_b)

    # Entsteht das Konto beim Passwortsetzen, ziehen seine Freigaben nach.
    _fg_nach = []
    _ock._GRAPH = {"https://oc3.test": True}
    _ock.KONTEN = os.path.join(tmp, "owncloud_konten_fg.json")
    _ock.nutzer_vorhanden = lambda k: False
    _ock.nutzer_anlegen = lambda k, p, a="": (True, "angelegt")
    _ock.freigaben_nachziehen = lambda k: _fg_nach.append(k) or 3
    _fg_ok, _fg_m = _ock.passwort_setzen("neu_fg", "passwort123")
    pruef("ein beim Passwortsetzen entstandenes Konto bekommt seine "
          "Freigaben sofort", _fg_ok and _fg_nach == ["neu_fg"]
          and "nachgezogen" in _fg_m, (_fg_m, _fg_nach))
except Exception as e:
    pruef("Freigaben ohne Konto lassen sich pruefen", False,
          f"{type(e).__name__}: {e}")
finally:
    for _n, _w in _ock_alt.items():
        setattr(_ock, _n, _w)

# Jede Verbindung zur Ablage entsteht an EINER Stelle, und dort wird das
# Zertifikat geprueft -- abschaltbar nur ausdruecklich, fuer das
# mitgelieferte OpenCloud.
_oc_q = _datei("owncloud.py")
pruef("alle Verbindungen zur Ablage laufen ueber eine Stelle",
      _oc_q.count("requests.Session()") == 1 and "_neue_sitzung" in _oc_q)
pruef("das Zertifikat wird geprueft, solange niemand es abschaltet",
      getattr(_ock, "TLS_PRUEFEN", None) is True
      and "s.verify = TLS_PRUEFEN" in _oc_q)

# Die mitgelieferte Ablage ist OpenCloud: kein PHP, keine Datenbank.
_dc_q = _datei("docker-compose.yaml")
_k8s_oc = os.path.join(_ROOT, "k8s")
pruef("Compose bringt OpenCloud mit, nicht mehr ownCloud 10",
      "opencloudeu/opencloud:" in _dc_q and "owncloud/server" not in _dc_q
      and "mariadb" not in _dc_q.lower())
# Innen und aussen derselbe Port, sonst endet jedes Ablegen mit 500.
pruef("OpenCloud lauscht innen auf dem Port seiner eigenen Adresse",
      '"${OWNCLOUD_PORT:-9200}:${OWNCLOUD_PORT:-9200}"' in _dc_q
      and "PROXY_HTTP_ADDR=0.0.0.0:${OWNCLOUD_PORT:-9200}" in _dc_q)
pruef("die k8s-Vorlage ist OpenCloud, die fuer ownCloud 10 ist weg",
      statefiles.exists(os.path.join(_k8s_oc, "97-opencloud.yaml"))
      and not statefiles.exists(os.path.join(_k8s_oc, "97-owncloud.yaml")))
if statefiles.exists(os.path.join(_k8s_oc, "97-opencloud.yaml")):
    _k97 = statefiles.open(os.path.join(_k8s_oc, "97-opencloud.yaml"),
                   encoding="utf-8").read()
    # Die interne /data-Adresse bricht das Hochladen im Browser.
    pruef("die Vorlage legt /data nicht auf eine interne Adresse",
          "GATEWAY_FRONTEND_PUBLIC_URL\n" not in _k97
          and "name: GATEWAY_FRONTEND_PUBLIC_URL" not in _k97)
    pruef("und haelt die erzeugten Schluessel auf dem Volume",
          "mountPath: /etc/opencloud" in _k97 and "subPath: config" in _k97)
    # kubectl apply schriebe ein Passwort aus der Datei im Klartext in
    # die Annotation last-applied-configuration.
    pruef("die Vorlage enthaelt kein Secret mit Passwort",
          "kind: Secret" not in _k97 and "--from-file=IDM_ADMIN_PASSWORD" in _k97)
    pruef("und richtet die Rechte der Unterordner vor dem Start",
          "initContainers:" in _k97 and '"chown", "-R", "1000:1000"' in _k97)
pruef("einrichten.py nennt bei abgelehnter Anmeldung den Token-Befehl",
      "opencloud auth-app create" in _datei("einrichten.py"))

# Der Vergleich mit einer alten ownCloud-10-Ablage findet, was LocaNoto
# nie geholt hat, und von fremden Konten nur Zahlen.
try:
    import import_existing as _ab
    _ab_alt = os.path.join(tmp, "ab_alt", "files")
    for _rel, _inh in (("admin/files/LocaNoto/allgemein/a.pdf", "aa"),
                       ("admin/files/LocaNoto/allgemein/b.xlsx", "bbb"),
                       ("admin/files/Sonstiges/c.pdf", "c"),
                       ("bernd/files/geheim.docx", "dddd")):
        _p = os.path.join(_ab_alt, *_rel.split("/"))
        statefiles.makedirs(os.path.dirname(_p), exist_ok=True)
        statefiles.open(_p, "w", encoding="utf-8").write(_inh)
    _ab_b = _ab.vergleiche(os.path.join(_ab_alt, "admin", "files"), {
        "wurzeln": ["LocaNoto/allgemein"],
        "dateien": {"LocaNoto/allgemein/a.pdf": {"groesse": 2},
                    "LocaNoto/allgemein/neu.pdf": {"groesse": 1}}})
    pruef("altbestand findet, was LocaNoto nie geholt hat",
          _ab_b["gleich"] == 1
          and _ab_b["fehlt_im_baum"] == ["LocaNoto/allgemein/b.xlsx"]
          and _ab_b["fehlt_ausserhalb"] == ["Sonstiges/c.pdf"]
          and _ab_b["nur_lokal"] == ["LocaNoto/allgemein/neu.pdf"], _ab_b)
    pruef("und von fremden Konten nur Anzahl und Groesse",
          _ab.andere_konten(_ab_alt, "admin") == {"bernd": (1, 4)})
except Exception as e:
    pruef("altbestand laesst sich pruefen", False, f"{type(e).__name__}: {e}")
