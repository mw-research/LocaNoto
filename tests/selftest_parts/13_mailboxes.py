"""Self-test, part 13: Whose mailboxes are: personal or of a workspace.

Runs only through tests/selftest.py, after the parts before it.
"""
# --- MAILBOXES: WHOSE THEY ARE ---
#
# Every mailbox was listed for every user, and everyone could try a login
# on it. A personal one can belong to one user, a shared one to a
# workspace; then only they see it, connect it and get its tickets.
import mailboxes as _mb_h
import tickets as _tk_h

_alt_konf_mb_h = _mcp_h.KONFIG
_mcp_h.KONFIG = os.path.join(tmp, "mcp_zugang.json")
raeume.anlegen("vertriebpost", "Vertrieb Post", mitglieder=["anna"])

pruef("ein persoenliches Postfach fuer alle wird angelegt",
      _mb_h.create("firma", "exchange", "", True)[0])
pruef("eines nur fuer anna",
      _mb_h.create("annas", "imap", "imap.test.example", True, owner="Anna")[0],
      _mb_h.create("annas2", "imap", "imap.test.example", True, owner="Anna"))
pruef("ein Funktionspostfach fuer einen Arbeitsbereich",
      _mb_h.create("vertrieb", "exchange", "owa.test", False,
                   postfach="vertrieb@test.de", room="vertriebpost")[0])
pruef("und eines ohne Zuordnung",
      _mb_h.create("zentrale", "exchange", "owa.test", False,
                   postfach="info@test.de")[0])
pruef("ein unbekannter Besitzer oder Arbeitsbereich wird abgewiesen",
      not _mb_h.create("x1", "imap", "imap.test.example", True, owner="niemand")[0]
      and not _mb_h.create("x2", "exchange", "owa.test", False,
                           postfach="x@test.de", room="gibtesnicht")[0]
      and not _mb_h.create("x3", "exchange", "owa.test", False, postfach="x@test.de",
                           room=raeume.privat_kennung("anna"))[0])

_sicht_h = {u: sorted(m["name"] for m in _mb_h.overview(u)) for u in ("anna", "bernd", "markus")}
pruef("anna sieht ihr eigenes und das ihres Arbeitsbereichs",
      _sicht_h["anna"] == ["annas", "annas2", "firma", "vertrieb", "zentrale"], _sicht_h)
pruef("bernd sieht weder annas Postfach noch das des fremden Arbeitsbereichs",
      _sicht_h["bernd"] == ["firma", "zentrale"], _sicht_h)
pruef("der Verwalter ohne Mitgliedschaft ebenso",
      _sicht_h["markus"] == ["firma", "zentrale"], _sicht_h)
pruef("die Verwaltung listet weiter alle",
      len(_mb_h.overview()) == 5)
try:
    _mb_h.require_visible("bernd", "annas")
    _fremd_h = False
except _mb_h.NotFound:
    _fremd_h = True
pruef("ein fremdes Postfach gibt es fuer den Nutzer nicht", _fremd_h)

# tickets follow the workspace
_tk_h.configure("vertrieb", True, members=["bernd"])
_tk_h.configure("zentrale", True, members=["bernd"])
pruef("Tickets des Arbeitsbereichs sehen seine Mitglieder, nicht die Liste",
      "vertrieb" in _tk_h.boxes_for("anna") and "vertrieb" not in _tk_h.boxes_for("bernd")
      and _tk_h.members_of("vertrieb") == ["anna"], _tk_h.members_of("vertrieb"))
pruef("auch der Verwalter nur als Mitglied",
      "vertrieb" not in _tk_h.boxes_for("markus", True)
      and "zentrale" in _tk_h.boxes_for("markus", True))
pruef("ohne Arbeitsbereich gilt die Liste weiter",
      "zentrale" in _tk_h.boxes_for("bernd") and "zentrale" not in _tk_h.boxes_for("anna")
      and _tk_h.members_of("zentrale") == ["bernd"])

# an existing entry is assigned later
pruef("ein bestehendes Postfach laesst sich zuordnen",
      _mb_h.set_access("zentrale", room="vertriebpost")[0]
      and "zentrale" not in {m["name"] for m in _mb_h.overview("bernd")}
      and "zentrale" in {m["name"] for m in _mb_h.overview("anna")})
pruef("und wieder freigeben",
      _mb_h.set_access("zentrale")[0]
      and "zentrale" in {m["name"] for m in _mb_h.overview("bernd")})
pruef("ein Besitzer passt nur zu einem persoenlichen Postfach",
      _mb_h.set_access("annas", owner="markus")[0]
      and _mcp_h.lies_konfiguration()["annas"].get("owner") == "markus"
      and _mb_h.set_access("zentrale", owner="markus")[0]
      and "owner" not in _mcp_h.lies_konfiguration()["zentrale"])

for _n_h in ("vertrieb", "zentrale"):
    _tk_h.configure(_n_h, False)
os.remove(_mcp_h.KONFIG)
_mcp_h.KONFIG = _alt_konf_mb_h
raeume.entfernen("vertriebpost")
