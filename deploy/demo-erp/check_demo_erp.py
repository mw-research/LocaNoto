"""Check the demo ERP the way LocaNoto uses it -- with LocaNoto's own code.

    python check_demo_erp.py          (inside the LocaNoto image)

Reads DEMO_ERP_PASSWORD (the read-only login) and connects through
sqldb.py, as a workspace's database account would: reads the schema,
runs the queries behind the demo questions, and makes sure the account
cannot change anything. Exit code 0 when all holds.
"""
import os
import sys

sys.path.insert(0, "/app")
import sqldb  # noqa: E402

ACCESS = {"server": os.getenv("DEMO_ERP_SERVER", "demo-erp"), "port": 1433,
          "datenbank": "DemoERP", "benutzer": "locanoto_lesen",
          "passwort": os.environ["DEMO_ERP_PASSWORD"]}

failures = []


def check(name, ok, detail=""):
    print(("OK    " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failures.append(name)


schema = sqldb.lade_schema(ACCESS)
check("schema readable with all tables and the view",
      all(f"dbo.{t}(" in schema for t in ("Kunden", "Artikel", "Auftraege",
                                          "Auftragspositionen", "Anlagen", "Pruefungen",
                                          "Reklamationen", "v_OffeneAuftraege")), schema)

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
}
expected_rows = {"open orders of Meier GmbH": 3, "inspections due in the next 30 days": 3,
                 "open complaints with their order": 3}
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
con = pymssql.connect(server=ACCESS["server"], user=ACCESS["benutzer"],
                      password=ACCESS["passwort"], database=ACCESS["datenbank"],
                      port=ACCESS["port"], login_timeout=10)
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
