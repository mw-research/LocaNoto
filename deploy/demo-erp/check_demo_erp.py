"""Check the demo ERP the way LocaNoto uses it -- with LocaNoto's own code.

    python check_demo_erp.py          (inside a running LocaNoto pod)

Connects through sqldb.py, as a workspace's database account would: reads
the schema, runs the queries behind the demo questions, and makes sure the
account cannot change anything. Exit code 0 when all holds.

The login: by default the DemoERP access LocaNoto already stores for a
workspace (Admin -> Databases, with a shared account) -- no secret is read
and no password goes on a command line. DEMO_ERP_ROOM picks the workspace
if there are several. DEMO_ERP_PASSWORD (the read-only login) is for a pod
without stored access, as in CI.
"""
import os
import sys

sys.path.insert(0, "/app")
import sqldb  # noqa: E402


def _access():
    password = os.getenv("DEMO_ERP_PASSWORD")
    if password:
        return {"server": os.getenv("DEMO_ERP_SERVER", "demo-erp"), "port": 1433,
                "datenbank": "DemoERP", "benutzer": "locanoto_lesen", "passwort": password}
    import sqlquellen
    want = os.getenv("DEMO_ERP_ROOM", "").strip()
    for entry in sqlquellen.liste():
        room = entry.get("raum")
        if want and room != want:
            continue
        stored = sqlquellen.zugang(room) or {}
        if stored.get("datenbank") == "DemoERP" and stored.get("passwort"):
            print(f"login: stored access of workspace '{room}' ({stored.get('benutzer')})")
            return dict(stored, port=int(stored.get("port") or sqldb.SQL_PORT))
    sys.exit("No DemoERP access with a shared account stored in LocaNoto "
             "(Admin -> Databases), and DEMO_ERP_PASSWORD is not set.")


ACCESS = _access()

failures = []


def check(name, ok, detail=""):
    print(("OK    " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failures.append(name)


schema = sqldb.lade_schema(ACCESS)
check("schema readable with all tables and the view",
      all(f"dbo.{t}(" in schema for t in ("Kunden", "Lieferanten", "Artikel", "Auftraege",
                                          "Auftragspositionen", "Rechnungen", "Lagerplaetze",
                                          "Bestellungen", "Dokumente", "Anlagen", "Pruefungen",
                                          "Reklamationen", "v_OffeneAuftraege",
                                          "v_OffeneRechnungen")), schema)
check("schema carries example values", "Beispiele:" in schema, schema[:500])

QUESTIONS = {
    "open orders of Meier GmbH":
        "SELECT AuftragsNr, Status, Auftragswert FROM dbo.v_OffeneAuftraege "
        "WHERE Firma LIKE '%Meier%'",
    "value of open orders per customer":
        "SELECT Firma, SUM(Auftragswert) AS Wert FROM dbo.v_OffeneAuftraege GROUP BY Firma",
    "inspections due in the next 30 days":
        "SELECT p.AnlagenNr, p.Pruefart, p.NaechstePruefung FROM dbo.Pruefungen p "
        "WHERE p.NaechstePruefung BETWEEN CAST(GETDATE() AS date) "
        "AND DATEADD(day, 30, CAST(GETDATE() AS date))",
    "next outer inspection of AN-0003":
        "SELECT MAX(NaechstePruefung) FROM dbo.Pruefungen WHERE AnlagenNr = 'AN-0003' "
        "AND Pruefart = 'A'",
    "items below minimum stock":
        "SELECT ArtikelNr, Lagerbestand, Mindestbestand FROM dbo.Artikel "
        "WHERE Lagerbestand < Mindestbestand",
    "open complaints with their order":
        "SELECT r.ReklamationsNr, r.AuftragsNr, r.Grund FROM dbo.Reklamationen r "
        "WHERE r.Status <> N'erledigt'",
    "open invoices of Meier GmbH":
        "SELECT RechnungsNr, Faellig, Restbetrag, Mahnstufe FROM dbo.v_OffeneRechnungen "
        "WHERE Firma LIKE N'%Meier%'",
    "overdue invoices and the total outstanding":
        "SELECT COUNT(*) AS Anzahl, SUM(Restbetrag) AS Offen FROM dbo.v_OffeneRechnungen "
        "WHERE TageUeberfaellig > 0",
    "where the pressure gauges lie":
        "SELECT a.ArtikelNr, a.Bezeichnung, a.Lagerbestand, l.Lager, l.Lagerplatz, l.Menge "
        "FROM dbo.Artikel a JOIN dbo.Lagerplaetze l ON l.ArtikelNr = a.ArtikelNr "
        "WHERE a.Bezeichnung LIKE N'%Manometer%'",
    "ordered from suppliers and not yet in":
        "SELECT b.BestellNr, a.Bezeichnung, b.Menge, b.ErwartetAm, l.Firma "
        "FROM dbo.Bestellungen b JOIN dbo.Artikel a ON a.ArtikelNr = b.ArtikelNr "
        "JOIN dbo.Lieferanten l ON l.LieferantenNr = b.LieferantenNr "
        "WHERE b.Status <> N'geliefert'",
    "contact at Becker Druckluft":
        "SELECT Firma, Ansprechpartner, Telefon, Email FROM dbo.Kunden "
        "WHERE Firma LIKE N'%Becker%'",
    "customers by revenue in the last 12 months":
        "SELECT TOP 5 k.Firma, SUM(r.Betrag) AS Umsatz FROM dbo.Rechnungen r "
        "JOIN dbo.Kunden k ON k.KundenNr = r.KundenNr "
        "WHERE r.Rechnungsdatum >= DATEADD(month, -12, CAST(GETDATE() AS date)) "
        "GROUP BY k.Firma ORDER BY Umsatz DESC",
}
expected_rows = {"open orders of Meier GmbH": 3, "inspections due in the next 30 days": 3,
                 "open complaints with their order": 3, "open invoices of Meier GmbH": 2,
                 "ordered from suppliers and not yet in": 3}
try:
    _c, mug = sqldb.fuehre_aus(
        "SELECT Lager, Lagerplatz, Menge FROM dbo.Lagerplaetze WHERE ArtikelNr = N'WA-104'",
        zugang=ACCESS)
    check("scavenger hunt: WA-104 lies with Prof. Andreas Schiffler",
          [tuple(r) for r in mug] == [("Prof. Andreas Schiffler", "persönlich", 1)], mug)
except Exception as e:
    check("scavenger hunt: WA-104 lies with Prof. Andreas Schiffler", False, f"{type(e).__name__}: {e}")
try:
    _c, docs = sqldb.fuehre_aus(
        "SELECT Dateiname, Datei FROM dbo.Dokumente WHERE RechnungsNr = 2025103", zugang=ACCESS)
    check("invoice 2025103 comes back as a whole PDF",
          len(docs) == 1 and bytes(docs[0][1]).startswith(b"%PDF")
          and bytes(docs[0][1]).rstrip().endswith(b"%%EOF"), docs[:1])
except Exception as e:
    check("invoice 2025103 comes back as a whole PDF", False, f"{type(e).__name__}: {e}")
try:
    _c, wrong = sqldb.fuehre_aus(
        "SELECT a.ArtikelNr FROM dbo.Artikel a JOIN dbo.Lagerplaetze l "
        "ON l.ArtikelNr = a.ArtikelNr GROUP BY a.ArtikelNr, a.Lagerbestand "
        "HAVING a.Lagerbestand <> SUM(l.Menge)", zugang=ACCESS)
    check("storage places add up to the stock", wrong == [], wrong)
except Exception as e:
    check("storage places add up to the stock", False, f"{type(e).__name__}: {e}")
for name, sql in QUESTIONS.items():
    try:
        columns, rows = sqldb.fuehre_aus(sql, zugang=ACCESS)
        want = expected_rows.get(name)
        check(f"{name}: {len(rows)} rows", rows and (want is None or len(rows) == want),
              rows)
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e}")

# The account itself must refuse writing -- below LocaNoto's own SELECT check.
import pymssql  # noqa: E402
con = pymssql.connect(server=ACCESS.get("server") or sqldb.SQL_SERVER or "demo-erp",
                      user=ACCESS["benutzer"], password=ACCESS["passwort"],
                      database=ACCESS["datenbank"], port=ACCESS["port"], login_timeout=10)
try:
    con.cursor().execute("UPDATE dbo.Artikel SET Lagerbestand = 0")
    con.commit()
    check("read-only login cannot write", False, "UPDATE went through")
except Exception as e:
    check("read-only login cannot write", "permission" in str(e).lower(), e)
finally:
    con.close()

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
