"""Self-test, part 12: The hardening findings, one check each.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- HARDENING: THE READ-ONLY SQL FILTER ---
#
# T-SQL needs no semicolon between the statements of a batch, and a quote
# character inside a quoted identifier is not the start of a string. The
# filter used to read [x'] ... [y'] as one string and skipped what stood
# between -- which the database then ran.
import sqlpruefung as _sp_h

for _q in ("SELECT 1 AS [x'] DROP TABLE foo COMMIT SELECT 2 AS [y']",
           "SELECT 1 AS [x'] UPDATE Artikel SET Preis = 0 COMMIT SELECT 2 AS [y']",
           "SELECT 1 AS [x'] EXEC xp_cmdshell 'whoami' SELECT 2 AS [y']",
           "SELECT 1 AS \"x'\" DELETE FROM Artikel COMMIT SELECT 2 AS \"y'\"",
           "SELECT 1 AS `x'` DELETE FROM daten",
           "SELECT 1 COMMIT",
           "SELECT 1 AS a SET NOCOUNT ON",
           "SELECT 1 DECLARE @x int",
           "SELECT 1 BEGIN TRAN",
           "SELECT * FROM t WITH (TABLOCKX, HOLDLOCK)",
           "SELECT * FROM [srv].[db].[dbo].[t]",
           "SELECT * FROM srv.db.dbo.t",
           "SELECT [xp_cmdshell]",
           "SELECT load_extension('x')",
           "SELECT 'abc",
           "SELECT 1 AS [abc"):
    pruef(f"SQL-Filter lehnt ab: {_q[:46]}", not _sp_h.pruefe_abfrage(_q)[0])

for _q in ("SELECT [Update], \"Delete\" FROM t WHERE x = 'DROP TABLE y; COMMIT'",
           "SELECT TOP 5 a FROM dbo.t WITH (NOLOCK) ORDER BY a",
           "SELECT a FROM t ORDER BY a OFFSET 0 ROWS FETCH NEXT 5 ROWS ONLY",
           "WITH c AS (SELECT 1 AS n) SELECT n FROM c",
           "SELECT name FROM t WHERE name LIKE '%[a-z]''s%'",
           "SELECT a.x, b.y FROM db.dbo.t a JOIN [db].[dbo].[u] b ON a.id = b.id",
           "SELECT Bezeichnung AS [Artikel's Name] FROM daten"):
    pruef(f"SQL-Filter laesst durch: {_q[:44]}", _sp_h.pruefe_abfrage(_q)[0],
          _sp_h.pruefe_abfrage(_q)[1])

# A sheet is queried in SQLite. The filter is one barrier; SQLite itself
# is asked to allow reading only, and a query that never ends is stopped.
import tabellen as _tab_h
_dir_h = os.path.join(tmp, "listen_haertung")
os.makedirs(_dir_h, exist_ok=True)
with open(os.path.join(_dir_h, "teile.csv"), "w", encoding="utf-8") as _f:
    _f.write("Artikel;Menge\nSchraube;5\nMutter;7\n")
_sp_l, _z_l = _tab_h.fuehre_aus("teile.csv", "", "SELECT Artikel FROM daten",
                                wurzel=_dir_h)
pruef("Liste: eine gewoehnliche Abfrage laeuft", "Schraube" in str(_z_l), _z_l)

_con_h = _tab_h._lade("teile.csv", "", _dir_h)
try:
    _con_h.execute("DELETE FROM daten")
    _schreibt = True
except Exception:
    _schreibt = False
pruef("Liste: SQLite selbst verweigert das Schreiben", not _schreibt)
pruef("Liste: die Zeilen sind noch da",
      len(_tab_h.fuehre_aus("teile.csv", "", "SELECT * FROM daten",
                            wurzel=_dir_h)[1]) == 2)

_alt_sek = _tab_h.ABFRAGE_SEKUNDEN
_tab_h.ABFRAGE_SEKUNDEN = 1
try:
    _tab_h.fuehre_aus(
        "teile.csv", "",
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
        "SELECT count(*) FROM c", wurzel=_dir_h)
    _endlos = "lief durch"
except ValueError as _e:
    _endlos = str(_e)
pruef("Liste: eine endlose Abfrage wird abgebrochen", "abgebrochen" in _endlos, _endlos)
_tab_h.ABFRAGE_SEKUNDEN = _alt_sek
pruef("Liste: danach antwortet das Blatt wieder",
      len(_tab_h.fuehre_aus("teile.csv", "", "SELECT * FROM daten",
                            wurzel=_dir_h)[1]) == 2)

# --- HARDENING: FOLDERS OF REMOVED ROOMS ARE NOT GENERAL ---
#
# Removing a room deletes its entry and keeps its folder under
# data/dokumente. The general ingest skipped only folders of rooms that
# still existed: after "remove workspace" and "read documents again" the
# files of the removed room were indexed into the general room.
import aufnehmen as _auf_h

_ok_h, _raum_h = raeume.anlegen("haertungweg", "Wird entfernt")
_ord_h = os.path.normpath(paths.raum_ordner(_raum_h))
os.makedirs(_ord_h, exist_ok=True)
with open(os.path.join(_ord_h, "geheim.txt"), "w", encoding="utf-8") as _f:
    _f.write("nur fuer diesen Raum")
_priv_h = os.path.normpath(os.path.join(paths.DOCS_DIR, "privat_niemandmehr"))
os.makedirs(_priv_h, exist_ok=True)

pruef("der Ordner eines Raums gehoert nicht zum allgemeinen Einlesen",
      _ok_h and _ord_h in raeume.ordner_anderer(raeume.ALLGEMEIN))
raeume.entfernen(_raum_h)
pruef("auch nicht, nachdem der Raum entfernt wurde",
      _raum_h not in raeume.liste()
      and _ord_h in raeume.ordner_anderer(raeume.ALLGEMEIN),
      raeume.entfernte())
pruef("ein persoenlicher Ordner ohne bekannten Raum bleibt ebenfalls draussen",
      _priv_h in raeume.ordner_anderer(raeume.ALLGEMEIN))
_eig_h = raeume.privat_kennung("anna")
pruef("der eigene Ordner zaehlt fuer den eigenen Raum nicht als fremd",
      os.path.normpath(paths.raum_ordner(_eig_h))
      not in raeume.ordner_anderer(_eig_h))
pruef("ingest.py fragt genau diese Liste ab",
      "raeume.ordner_anderer(eigener_raum)" in _datei("ingest.py"))

raeume.anlegen("haertungweg", "Wieder da")
pruef("ein neu angelegter Raum gilt nicht mehr als entfernt",
      _raum_h not in raeume.entfernte() and _raum_h in raeume.liste())

# "Delete the data of a workspace" takes the uploaded files along.
pruef("Leeren entfernt auch die abgelegten Dateien",
      _auf_h.leere_ablage(_raum_h) == 1 and not os.path.exists(_ord_h))
pruef("der allgemeine Raum behaelt seinen Ordner",
      _auf_h.leere_ablage(raeume.ALLGEMEIN) == 0
      and os.path.isdir(paths.DOCS_DIR))
raeume.entfernen(_raum_h)
os.rmdir(_priv_h)

# --- HARDENING: LOCAL TOOL PROCESSES ---
#
# A tool server over stdio is a command run in the application's
# container. An administrator of the application could enter one (kind
# "stdio", or "befehl" among the options of any kind) and had a shell
# with the installation key in its environment.
import mcp as _mcp_h

_alt_konf_h = _mcp_h.KONFIG
_mcp_h.KONFIG = os.path.join(tmp, "mcp_haertung.json")
_mcp_h.STDIO_ERLAUBT = False
pruef("ohne Freischaltung wird kein lokaler Prozess angelegt",
      not _mcp_h.lege_an("lokal", "stdio", "sh -c id", persoenlich=False)[0])
pruef("und die Vorlage wird nicht angeboten",
      "stdio" not in _mcp_h.vorlagen() and "exchange" in _mcp_h.vorlagen())
pruef("Angaben ausserhalb der festen Liste werden abgewiesen",
      not _mcp_h.lege_an("x", "http", "https://mcp.test/mcp", persoenlich=False,
                         befehl=["sh"], transport="stdio")[0]
      and not _mcp_h.lege_an("x", "http", "https://mcp.test/mcp",
                             persoenlich=False, umgebung={"A": "b"})[0])
pruef("es wurde nichts geschrieben", not _mcp_h.lies_konfiguration())
try:
    _mcp_h.Verbindung("alt", {"transport": "stdio",
                              "befehl": [sys.executable, "-c", "pass"]}
                      )._ueber_stdio({"jsonrpc": "2.0", "id": 1, "method": "x"})
    _lief_h = True
except _mcp_h.Fehler:
    _lief_h = False
pruef("ein Eintrag aus mcp.json startet ohne Freischaltung auch nichts",
      not _lief_h)

# With the switch on, the process does not inherit the application's
# environment (installation key, database address, model keys).
_mcp_h.STDIO_ERLAUBT = True
os.environ["LOCANOTO_SCHLUESSEL_PROBE"] = "geheim"
_zeigt_h = os.path.join(tmp, "zeigt_umgebung.py")
with open(_zeigt_h, "w", encoding="utf-8") as _f:
    _f.write("import json, os, sys\n"
             "sys.stdin.readline()\n"
             "print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': "
             "{'probe': os.environ.get('LOCANOTO_SCHLUESSEL_PROBE', ''), "
             "'eigen': os.environ.get('EIGEN', '')}}), flush=True)\n")
_vb_h = _mcp_h.Verbindung("zeigt", {"transport": "stdio",
                                    "befehl": [sys.executable, _zeigt_h],
                                    "umgebung": {"EIGEN": "ja"}})
_antw_h = _vb_h._ueber_stdio({"jsonrpc": "2.0", "id": 1, "method": "x"})
pruef("der Prozess erbt die Umgebung der Anwendung nicht",
      (_antw_h.get("result") or {}).get("probe") == "", _antw_h)
pruef("bekommt aber, was fuer ihn eingetragen ist",
      (_antw_h.get("result") or {}).get("eigen") == "ja", _antw_h)
try:
    _vb_h._prozess.kill()
except Exception:
    pass
os.environ.pop("LOCANOTO_SCHLUESSEL_PROBE", None)
_mcp_h.STDIO_ERLAUBT = False
_mcp_h.KONFIG = _alt_konf_h

# --- HARDENING: LIMITS WHEN READING UPLOADED FILES ---
#
# A file states its own size: a PDF its page, an image its pixels, a
# Word file what it unpacks to. Read as stated, a few kilobytes took
# gigabytes of memory. And every upload was stored before anyone looked
# at what it was.
import zipfile as _zip_h
import pymupdf as _mu_h
import ocr as _ocr_h
import lesen as _les_h
import postfach as _pf_h


def _abgelehnt_h(name, inhalt):
    try:
        _auf_h.pruefe_datei(name, inhalt)
        return 0
    except _auf_h.Abgelehnt as e:
        return e.status


pruef("ein unbekannter Dateityp wird vor dem Ablegen abgewiesen",
      _abgelehnt_h("werkzeug.exe", b"MZ") == 415
      and _abgelehnt_h("bild.svg", b"<svg/>") == 415
      and _abgelehnt_h("ohne_endung", b"x") == 415)
pruef("Text und Markdown gehen durch",
      _abgelehnt_h("notiz.txt", b"hallo") == 0
      and _abgelehnt_h("notiz.md", b"# hallo") == 0)
pruef("was sich PDF nennt und keines ist, wird abgewiesen",
      _abgelehnt_h("kaputt.pdf", b"kein pdf") == 415)

_pdf_h = _mu_h.open()
for _i in range(5):
    _pdf_h.new_page(width=595, height=842)
_pdf5_h = _pdf_h.tobytes()
_pdf_h.close()
_alt_seiten_h = _auf_h.MAX_SEITEN
_auf_h.MAX_SEITEN = 3
pruef("ein Dokument ueber der Seitengrenze wird abgewiesen",
      _abgelehnt_h("lang.pdf", _pdf5_h) == 413)
_auf_h.MAX_SEITEN = _alt_seiten_h
pruef("unter der Grenze geht es durch", _abgelehnt_h("lang.pdf", _pdf5_h) == 0)

# The page of a PDF: rendered at most at SEITE_MAX_MP.
_gross_h = _mu_h.open()
_gross_h.new_page(width=595, height=842)
_gross_h.new_page(width=7200, height=7200)        # 100 x 100 inch
_gross_h.new_page(width=14400, height=14400)      # 200 x 200 inch
_a4_h, _riesig_h, _unsinn_h = _gross_h[0], _gross_h[1], _gross_h[2]
_dpi_h = _ocr_h.dpi_fuer(_riesig_h, 300)
pruef("eine gewoehnliche Seite wird mit der verlangten Aufloesung gelesen",
      _ocr_h.dpi_fuer(_a4_h, 300) == 300)
pruef("eine riesige Seite mit weniger, sodass das Bild begrenzt bleibt",
      50 <= _dpi_h < 300
      and (7200 / 72 * _dpi_h) ** 2 <= _ocr_h.SEITE_MAX_MP * 1_000_000, _dpi_h)
pruef("und eine, die auch so nicht passt, gar nicht",
      _ocr_h.dpi_fuer(_unsinn_h, 300) == 0)
_gross_h.close()

# An image file: its pixels are checked before it becomes a page.
_bild_h = _mu_h.Pixmap(_mu_h.csGRAY, _mu_h.IRect(0, 0, 2000, 2000), False)
_bild_h.clear_with(255)
_png_h = _bild_h.tobytes("png")
_alt_mp_h = _ocr_h.BILD_MAX_MP
_ocr_h.BILD_MAX_MP = 1
pruef("ein Bild ueber der Pixelgrenze wird abgewiesen",
      _abgelehnt_h("scan.png", _png_h) == 413)
_ocr_h.BILD_MAX_MP = _alt_mp_h
pruef("darunter geht es durch", _abgelehnt_h("scan.png", _png_h) == 0)

# A Word file is a zip archive.
_buf_h = io.BytesIO()
with _zip_h.ZipFile(_buf_h, "w", _zip_h.ZIP_DEFLATED) as _z:
    _z.writestr("[Content_Types].xml", "<Types/>")
    _z.writestr("word/document.xml",
                "<w:p>ANFANG</w:p>" + "a" * (3 * 1024 * 1024) + "<w:p>ENDE</w:p>")
_bombe_h = _buf_h.getvalue()
_alt_entp_h = _les_h.ENTPACKT_MAX_MB
_les_h.ENTPACKT_MAX_MB = 1
pruef("ein Word-Dokument, das zu gross auspackt, wird abgewiesen",
      len(_bombe_h) < 100_000 and _abgelehnt_h("bombe.docx", _bombe_h) == 413,
      len(_bombe_h))
_les_h.ENTPACKT_MAX_MB = _alt_entp_h

# The same file as a mail attachment: read up to a bound.
_alt_xml_h = _pf_h.ATTACHMENT_XML_BYTES
_pf_h.ATTACHMENT_XML_BYTES = 1000
_anh_h = _pf_h.attachment_text("bombe.docx", _bombe_h)
pruef("ein Word-Anhang wird nur bis zu einer Grenze ausgepackt",
      "ANFANG" in _anh_h and "ENDE" not in _anh_h, _anh_h[:60])
_pf_h.ATTACHMENT_XML_BYTES = _alt_xml_h

# --- HARDENING: THE WEB FETCHER CONNECTS TO WHAT IT CHECKED ---
#
# A name server can answer differently each time it is asked. The check
# resolved the name, and the connection resolved it again.
import socket as _so_h
import websuche as _ws_h

_antworten_h = [[(2, 1, 6, "", ("93.184.216.34", 0))],      # public
                [(2, 1, 6, "", ("10.0.0.5", 0))]]           # internal
_fragen_h = []
_echt_gai_h = _so_h.getaddrinfo


def _wechselnd_h(*a, **k):
    _fragen_h.append(a[0])
    return _antworten_h[min(len(_fragen_h), len(_antworten_h)) - 1]


_so_h.getaddrinfo = _wechselnd_h
try:
    _ip_h = _ws_h.aufgeloest("rebind.example")
finally:
    _so_h.getaddrinfo = _echt_gai_h
pruef("Websuche: der Name wird einmal aufgeloest, und verbunden wird mit dem Geprueften",
      _ip_h == "93.184.216.34" and len(_fragen_h) == 1, (_ip_h, _fragen_h))
_so_h.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0)),
                                     (2, 1, 6, "", ("10.0.0.5", 0))]
try:
    _gemischt_h = _ws_h.aufgeloest("gemischt.example")
finally:
    _so_h.getaddrinfo = _echt_gai_h
pruef("Websuche: eine interne Adresse unter den Antworten genuegt zum Ablehnen",
      _gemischt_h is None, _gemischt_h)

# --- HARDENING: A BACKUP'S NAME IS NOT A PATH ---
import sicherung as _sich_h

_alt_ordner_h = _sich_h.ORDNER
_sich_h.ORDNER = os.path.join(tmp, "sicherungen_haertung")
os.makedirs(os.path.join(_sich_h.ORDNER, "2026-11-14_10-00"), exist_ok=True)
_neben_h = os.path.join(tmp, "neben_den_sicherungen")
os.makedirs(_neben_h, exist_ok=True)
with open(os.path.join(_neben_h, "stand.json"), "w", encoding="utf-8") as _f:
    _f.write('{"raeume": {"allgemein": {"datei": "../../x"}}}')

pruef("ein Abzug wird ueber seinen Ordnernamen gefunden",
      _sich_h._abzug("2026-11-14_10-00") is not None)
pruef("'..', ein Pfad und ein leerer Name sind kein Abzug",
      all(_sich_h._abzug(n) is None for n in
          ("..", ".", "", "../neben_den_sicherungen",
           "..\\neben_den_sicherungen", "/etc", "2026-11-14_10-00/..")))
pruef("Loeschen mit '..' entfernt nichts",
      not _sich_h.entferne("..", trotzdem=True)[0]
      and os.path.isdir(_sich_h.ORDNER) and os.path.isdir(_neben_h))
_ber_h = _sich_h.hole_zurueck("../neben_den_sicherungen")
pruef("Einspielen aus einem Ordner ausserhalb wird abgewiesen",
      "Kein Abzug" in str(_ber_h.get("fehler")), _ber_h)
shutil.rmtree(_sich_h.ORDNER, ignore_errors=True)
shutil.rmtree(_neben_h, ignore_errors=True)
_sich_h.ORDNER = _alt_ordner_h

# --- HARDENING: A NEW ACCOUNT DOES NOT INHERIT A FORMER ONE ---
#
# Deleting an account keeps its chats and its personal workspace, both
# bound to the name. An admin could delete an account, create it again
# and sign in as it -- past the two-person emergency access.
import accounts as _acc_h
import chats as _chats_h
import notzugang as _nz_h

benutzer.anlege("nachlass", "Passwort-123456", von="markus")
_chat_h = _chats_h.neue_kennung()
_chats_h.speichere("nachlass", _chat_h, [{"role": "user", "content": "privat"}])
pruef("ein gewoehnliches Konto hinterlaesst zunaechst nichts Fremdes",
      _acc_h.left_over("unbekannt-niemand") == [])
_acc_h.delete("Nachlass", by="markus")
pruef("Loeschen nimmt den Namen in jeder Schreibweise",
      benutzer.eintrag("nachlass") is None)
pruef("nach dem Loeschen liegen die Chats noch da",
      "chats and files" in _acc_h.left_over("nachlass"), _acc_h.left_over("nachlass"))
_ok_h, _m_h, _n_h = _acc_h.create("nachlass", "Passwort-654321", by="markus")
pruef("ein neues Konto gleichen Namens wird abgewiesen, solange etwas daliegt",
      not _ok_h and "purge" in _m_h and benutzer.eintrag("nachlass") is None, _m_h)
pruef("Aufraeumen geht nicht, solange es das Konto gibt",
      not _acc_h.purge_left_over("markus")[0])
pruef("auf dem Server laesst sich der Nachlass entfernen",
      _acc_h.purge_left_over("nachlass", by="server")[0]
      and _acc_h.left_over("nachlass") == [])
_ok_h, _m_h, _n_h = _acc_h.create("nachlass", "Passwort-654321", by="markus")
pruef("danach wird das Konto angelegt, ohne alte Chats",
      _ok_h and _chats_h.liste("nachlass") == [], (_m_h, _chats_h.liste("nachlass")))
_acc_h.delete("nachlass", by="markus")
_acc_h.purge_left_over("nachlass", by="server")

# The confirmer of an emergency access set their own password. Until now
# only "not set by the requester" was asked -- a second account of the
# requester could set it.
_alt_pz_h = _nz_h._passwort_zuletzt_von
_alt_rolle_h = benutzer.hat_rolle
benutzer.hat_rolle = lambda n, r: True
_nz_h._passwort_zuletzt_von = lambda n: "dritter"
pruef("ein Bestaetiger, dessen Passwort ein Dritter gesetzt hat, wird abgewiesen",
      "jemand anderes" in _nz_h.bestaetige("privat_x", "anna", "bert")[1],
      _nz_h.bestaetige("privat_x", "anna", "bert"))
_nz_h._passwort_zuletzt_von = lambda n: n
pruef("hat er es selbst gesetzt, scheitert es erst am fehlenden Antrag",
      "Antrag gibt es nicht" in _nz_h.bestaetige("privat_x", "anna", "bert")[1])
_nz_h._passwort_zuletzt_von = _alt_pz_h
benutzer.hat_rolle = _alt_rolle_h

# --- HARDENING: AN UNSIGNED USER FILE IS NOT TAKEN FOR AN OLD ONE ---
#
# Whoever can write the user file and cannot read the key replaced it by
# the format from before the signatures: {"name": "<own bcrypt hash>"}.
# That state counted as "not signed yet" and let the entry in, as admin
# if the name stood in ADMIN_USERS.
import bcrypt as _bc_h
import geheim as _geh_h
import auth as _auth_h

pruef("diese Installation hat signiert, und das ist gemerkt",
      benutzer.zustand() == benutzer.SIGNIERT
      and os.path.exists(_geh_h._SIGNIERT_MARKE)
      and not _geh_h.unsigniert_erlaubt())
_echt_h = statefiles.read_bytes(benutzer._datei())
_hash_h = _bc_h.hashpw(b"Angreifer-Passwort-1", _bc_h.gensalt(4)).decode()
statefiles.write(benutzer._datei(), json.dumps({"markus": _hash_h}).encode("utf-8"))
try:
    pruef("die Datei im alten Format gilt als unsigniert",
          benutzer.zustand() == benutzer.UNSIGNIERT)
    pruef("ihr Eintrag kommt mit seinem Passwort nicht herein",
          not benutzer.pruefe("markus", "Angreifer-Passwort-1"))
    pruef("und ist kein Verwalter", not benutzer.ist_admin("markus"))
    os.environ["UNSIGNIERT_ERLAUBT"] = "1"
    pruef("mit dem Schalter gilt der Umstieg noch einmal",
          benutzer.pruefe("markus", "Angreifer-Passwort-1"))
    os.environ.pop("UNSIGNIERT_ERLAUBT")
finally:
    os.environ.pop("UNSIGNIERT_ERLAUBT", None)
    statefiles.write(benutzer._datei(), _echt_h)
pruef("die echte Datei gilt wieder", benutzer.zustand() == benutzer.SIGNIERT)
pruef("Token ohne jede Signatur gelten ebenfalls nicht mehr als alt",
      not _auth_h.nachsichtig({"abc": {"benutzer": "markus"}}))

# --- HARDENING: SMALLER FINDINGS ---
import base64 as _b64_h
import sessions as _ses_h
import imap_mailbox as _imap_h
import owncloud as _oc_h

# A sealed cookie is sealed. Plain JSON in base64 was taken as it came.
_echt_s_h = _ses_h.seal("anna", {"k": "v"})
_falsch_s_h = _b64_h.urlsafe_b64encode(json.dumps(
    {"u": "anna", "e": 9999999999, "d": {"k": "gefaelscht"}}).encode()).decode().rstrip("=")
pruef("ein versiegeltes Cookie laesst sich oeffnen",
      _ses_h.unseal("anna", _echt_s_h) == {"k": "v"})
pruef("ein von Hand geschriebenes wird nicht angenommen",
      _ses_h.unseal("anna", _falsch_s_h) == {}, _ses_h.unseal("anna", _falsch_s_h))

# An IMAP search word stays one argument.
_q_h = _imap_h._quote('x\r\nA1 UID STORE 1:* +FLAGS (\\Deleted)\r\nA2 EXPUNGE')
pruef("IMAP: ein Suchwort mit Zeilenumbruch bleibt eine Zeile",
      "\r" not in _q_h and "\n" not in _q_h and _q_h.startswith('"')
      and _q_h.endswith('"'), _q_h)
pruef("IMAP: Anfuehrungszeichen und Backslash sind maskiert",
      _imap_h._quote('a"b\\c') == '"a\\"b\\\\c"', _imap_h._quote('a"b\\c'))

# User names: a-z, digits, dot, dash, underscore.
pruef("ein Name mit Umlaut wird nicht mehr angelegt",
      not benutzer.anlege("müller", "Passwort-123456", von="markus")[0]
      and not benutzer.anlege("-strich", "Passwort-123456", von="markus")[0]
      and benutzer.eintrag("müller") is None)
_ok_n_h, _m_n_h = benutzer.anlege("mueller.2-b_c", "Passwort-123456", von="markus")
pruef("Punkt, Strich, Unterstrich und Ziffern gehen weiter", _ok_n_h, _m_n_h)
benutzer.loesche("mueller.2-b_c", von="markus")

# Storage: a mapping by hand does not reach into the personal folders.
_w_h = _oc_h.WURZEL
pruef("ein persoenlicher Bereich laesst sich nicht von Hand zuordnen",
      _oc_h.zuordnung_fehler({raeume.privat_kennung("anna"): "/Irgendwo"}) != "")
pruef("kein Bereich zeigt auf einen persoenlichen Ordner oder darueber",
      all(_oc_h.zuordnung_fehler({"einkauf": o}) for o in
          (f"/{_w_h}/privat/anna", f"/{_w_h}/privat", f"/{_w_h}",
           f"/{_w_h}/raeume/../privat/anna", f"{_w_h}\\privat\\anna", "/")))
pruef("ein gewoehnlicher Ordner geht",
      _oc_h.zuordnung_fehler({"einkauf": f"/{_w_h}/raeume/einkauf",
                              "allgemein": "/Abteilung/Einkauf"}) == "")
try:
    _oc_h.setze_zuordnung({"einkauf": f"/{_w_h}/privat/anna"})
    _geschrieben_h = True
except ValueError:
    _geschrieben_h = False
pruef("und geschrieben wird eine solche Zuordnung nicht", not _geschrieben_h)

# --- HARDENING: WRONG PASSWORDS DO NOT LOCK THE REAL PERSON OUT ---
#
# Failed sign-ins were counted per name. Ten wrong passwords for "markus"
# from anywhere, and markus got "too many failed sign-ins" with the right
# one -- repeatable at will.
pruef("die Grenze je Name ueber alle Adressen liegt weit ueber der je Adresse",
      _ses_h.LOGIN_ATTEMPTS_PER_NAME >= _ses_h.LOGIN_ATTEMPTS * 5)
for _ in range(_ses_h.LOGIN_ATTEMPTS + 2):
    _ses_h.login_attempt("haertung-opfer", "203.0.113.9")
pruef("von der Adresse der Fehlversuche ist der Name gesperrt",
      _ses_h.login_blocked("haertung-opfer", "203.0.113.9")
      and not _ses_h.login_attempt("haertung-opfer", "203.0.113.9"))
pruef("von einer anderen Adresse meldet sich dieselbe Person weiter an",
      not _ses_h.login_blocked("haertung-opfer", "198.51.100.7")
      and _ses_h.login_attempt("haertung-opfer", "198.51.100.7"))

# --- HARDENING: A PASSWORD LONGER THAN BCRYPT TAKES ---
_lang_h = "ä" * 40                                    # 80 bytes
pruef("ein Passwort ueber 72 Bytes wird beim Setzen abgewiesen, nicht beim Hashen",
      "72" in benutzer.passwort_setzen("anna", _lang_h, von="anna")[1]
      and "72" in benutzer.anlege("langpass", _lang_h, von="markus")[1]
      and benutzer.eintrag("langpass") is None)

# --- HARDENING: SETTING SOMEBODY'S PASSWORD IS A WAY IN ---
#
# An admin set a user's password and signed in as that user: chats and
# personal workspace open, no second person asked.
benutzer.anlege("resetprobe", "Passwort-123456", von="markus")
pruef("ein Konto ohne Inhalt bekommt sein Passwort vom Verwalter",
      _acc_h.set_password("resetprobe", "Neues-Passwort-1", by="markus")[0])
_chat_r_h = _chats_h.neue_kennung()
_chats_h.speichere("resetprobe", _chat_r_h, [{"role": "user", "content": "privat"}])
_ok_r_h, _m_r_h, _n_r_h = _acc_h.set_password("resetprobe", "Neues-Passwort-2", by="markus")
pruef("hat es Chats, wird das Setzen ohne Notzugang abgewiesen",
      not _ok_r_h and "emergency access" in _m_r_h
      and benutzer.pruefe("resetprobe", "Neues-Passwort-1"), _m_r_h)
pruef("das eigene Passwort bleibt frei",
      _acc_h.reset_refused("resetprobe", "resetprobe") == "")
_alt_rf_h = _nz_h.raeume_fuer
_nz_h.raeume_fuer = lambda n: [raeume.privat_kennung("resetprobe")] if n == "markus" else []
pruef("mit bestaetigtem Notzugang zu dem Bereich geht es",
      _acc_h.set_password("resetprobe", "Neues-Passwort-3", by="markus")[0]
      and _acc_h.reset_refused("resetprobe", "anna") != "")
_nz_h.raeume_fuer = _alt_rf_h
_acc_h.delete("resetprobe", by="markus")
_acc_h.purge_left_over("resetprobe", by="server")

# --- HARDENING: A BOUND ON READING DOCUMENTS AT THE SAME TIME ---
#
# Reading a document holds a worker thread until it is done. A few large
# uploads at once took them all.
import threading as _thr_h

_alt_pl_h, _alt_w_h = _auf_h._plaetze, _auf_h.WARTEN_SEKUNDEN
_auf_h._plaetze = _thr_h.BoundedSemaphore(1)
_auf_h.WARTEN_SEKUNDEN = 0
_auf_h._plaetze.acquire()                       # one document is being read
try:
    _auf_h.process_uploaded_pdf(_auf_h.Datei("wartet.txt", b"text"), "allgemein",
                                benutzer_="markus", ist_verwalter=True)
    _voll_h = 0
except _auf_h.Abgelehnt as _e:
    _voll_h = _e.status
pruef("ist kein Platz frei, wird ein weiterer Upload mit 429 abgewiesen",
      _voll_h == 429, _voll_h)
_auf_h._plaetze.release()
_n_h, _hin_h = _auf_h.process_uploaded_pdf(
    _auf_h.Datei("Haertung-Platz.txt", b"Die Pruefung der Pumpe P4 ist jaehrlich. " * 5),
    "allgemein", benutzer_="markus", ist_verwalter=True)
pruef("mit freiem Platz wird eingelesen, und der Platz danach zurueckgegeben",
      _n_h >= 1 and _auf_h._plaetze.acquire(blocking=False), (_n_h, _hin_h))
_auf_h._plaetze.release()
_auf_h._plaetze, _auf_h.WARTEN_SEKUNDEN = _alt_pl_h, _alt_w_h

# An optional size limit for a personal workspace.
_alt_q_h = _auf_h.PRIVAT_MAX_MB
_auf_h.PRIVAT_MAX_MB = 1
try:
    _auf_h.process_uploaded_pdf(
        _auf_h.Datei("zu-gross.txt", b"x" * (2 * 1024 * 1024)),
        raeume.privat_kennung("anna"), benutzer_="anna")
    _quote_h = 0
except _auf_h.Abgelehnt as _e:
    _quote_h = _e.status
pruef("ein persoenlicher Bereich ueber seiner Groessengrenze nimmt nichts mehr an",
      _quote_h == 413, _quote_h)
_auf_h.PRIVAT_MAX_MB = _alt_q_h

# --- HARDENING: A BACKUP DOES NOT HOLD ITS TEXT IN THE CLEAR ---
#
# A backup lies on the documents volume. It held every passage as plain
# text and, with Postgres, the user file with its password hashes.
_ab_h = _sich_h.sichere()
pruef("ein Abzug entsteht", _ab_h.get("name") and _ab_h.get("raeume"), _ab_h)
_ab_pfad_h = _sich_h._abzug(_ab_h["name"])
_roh_h = ""
for _d_h in os.listdir(_ab_pfad_h):
    if _d_h.endswith(".jsonl"):
        with open(os.path.join(_ab_pfad_h, _d_h), encoding="utf-8") as _f:
            _roh_h += _f.read()
pruef("seine Abschnitte stehen nicht im Klartext darin",
      _roh_h and all(z.startswith("LNBK1:") for z in _roh_h.splitlines() if z)
      and '"text"' not in _roh_h, _roh_h[:80])
pruef("und sie lassen sich mit dem Schluessel wieder lesen",
      '"text"' in _sich_h._entpacke_zeile(_roh_h.splitlines()[0]))
pruef("ein Abzug aus der Zeit davor wird gelesen, wie er ist",
      _sich_h._entpacke_zeile('{"id": "a", "text": "alt"}\n') == '{"id": "a", "text": "alt"}'
      and _sich_h._entpacke_bytes(b"LNC1-ein-alter-chat") == b"LNC1-ein-alter-chat")
pruef("Zustandsdateien gehen verschluesselt hinein und unveraendert heraus",
      _sich_h._verpacke_bytes(b'{"nutzer": {}}').startswith(b"LNBK1:")
      and b"nutzer" not in _sich_h._verpacke_bytes(b'{"nutzer": {}}')
      and _sich_h._entpacke_bytes(_sich_h._verpacke_bytes(b'{"nutzer": {}}'))
      == b'{"nutzer": {}}')
_zur_h = _sich_h.hole_zurueck(_ab_h["name"])
pruef("der verschluesselte Abzug laesst sich einspielen",
      not _zur_h.get("fehler") and sum(_zur_h.get("raeume", {}).values()) > 0, _zur_h)
_sich_h.entferne(_ab_h["name"], trotzdem=True)

# --- HARDENING: A TOKEN DOES NOT OUTLIVE THE DIRECTORY ACCOUNT ---
#
# Somebody disabled in the company directory kept every access through
# an API token: role and groups are read at sign-in, and a token never
# signs in.
import oidc as _oidc_h
import time as _time_h

benutzer.anlege("verzeichnis", "Passwort-123456", von="markus")
pruef("das Token eines lokalen Kontos ist nicht befristet",
      _oidc_h.token_allowed("verzeichnis"))
benutzer.anmeldung_setzen("verzeichnis", "oidc", von="oidc", extern="https://idp.test|42")
pruef("ein Verzeichniskonto aus der Zeit davor: die Frist beginnt jetzt",
      _oidc_h.token_allowed("verzeichnis")
      and "verzeichnis" in _oidc_h._sign_ins())
_echt_zeit_h = _time_h.time
_time_h.time = lambda: _echt_zeit_h() + (_oidc_h.TOKEN_DAYS + 1) * 86400
try:
    pruef("ohne Anmeldung ueber das Verzeichnis laeuft das Token ab",
          not _oidc_h.token_allowed("verzeichnis"))
    _oidc_h.note_sign_in("verzeichnis")
    pruef("nach einer neuen Anmeldung gilt es wieder",
          _oidc_h.token_allowed("verzeichnis"))
finally:
    _time_h.time = _echt_zeit_h
benutzer.loesche("verzeichnis", von="markus")
