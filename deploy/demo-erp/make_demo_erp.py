"""Generate the demo ERP database for LocaNoto: SQL, Kubernetes manifest, data model.

    python deploy/demo-erp/make_demo_erp.py

Writes next to this file:

    seed.sql          tables, sample data, a read-only login (T-SQL)
    demo-erp.yaml     SQL Server 2022 for Kubernetes, seeded by a job
    data-model.md     the data model as a document to upload into LocaNoto
    sql-hint.txt      the short note for the workspace's database account

Tables, columns and their meaning are defined once, below, so the
database and its description cannot drift apart. The sample data is
fictitious and deterministic. Dates are relative to the day the job runs
(GETDATE()), so "due in the next 30 days" always finds something.
"""
import io
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
DATABASE = "DemoERP"
READ_LOGIN = "locanoto_lesen"
IMAGE = "mcr.microsoft.com/mssql/server:2022-latest"

# (table, description, [(column, type, description)])
TABLES = [
    ("Kunden", "Kundenstamm.", [
        ("KundenNr", "int NOT NULL PRIMARY KEY", "Kundennummer"),
        ("Firma", "nvarchar(100) NOT NULL", "Name des Kunden"),
        ("Branche", "nvarchar(50) NOT NULL", "Branche"),
        ("PLZ", "nvarchar(10) NOT NULL", "Postleitzahl"),
        ("Ort", "nvarchar(50) NOT NULL", "Ort"),
        ("Ansprechpartner", "nvarchar(80) NOT NULL", "Ansprechpartner beim Kunden"),
        ("Email", "nvarchar(100) NOT NULL", "Mailadresse des Ansprechpartners"),
        ("Telefon", "nvarchar(30) NOT NULL", "Telefonnummer des Ansprechpartners"),
        ("KundeSeit", "date NOT NULL", "Beginn der Geschäftsbeziehung"),
    ]),
    ("Lieferanten", "Lieferantenstamm.", [
        ("LieferantenNr", "int NOT NULL PRIMARY KEY", "Lieferantennummer"),
        ("Firma", "nvarchar(100) NOT NULL", "Name des Lieferanten"),
        ("Ort", "nvarchar(50) NOT NULL", "Ort"),
        ("Ansprechpartner", "nvarchar(80) NOT NULL", "Ansprechpartner beim Lieferanten"),
        ("Telefon", "nvarchar(30) NOT NULL", "Telefonnummer"),
        ("Email", "nvarchar(100) NOT NULL", "Mailadresse"),
    ]),
    ("Artikel", "Artikelstamm mit Lagerbestand.", [
        ("ArtikelNr", "nvarchar(20) NOT NULL PRIMARY KEY", "Artikelnummer, z. B. DB-2000"),
        ("Bezeichnung", "nvarchar(100) NOT NULL", "Artikelbezeichnung"),
        ("Warengruppe", "nvarchar(50) NOT NULL", "Warengruppe"),
        ("Einheit", "nvarchar(10) NOT NULL", "Mengeneinheit (Stk, m, Set)"),
        ("Listenpreis", "decimal(10,2) NOT NULL", "Listenpreis netto in EUR je Einheit"),
        ("Lagerbestand", "int NOT NULL", "aktueller Bestand"),
        ("Mindestbestand", "int NOT NULL", "unter diesem Bestand nachbestellen"),
    ]),
    ("Auftraege", "Kundenaufträge (Kopf).", [
        ("AuftragsNr", "int NOT NULL PRIMARY KEY", "Auftragsnummer"),
        ("KundenNr", "int NOT NULL REFERENCES dbo.Kunden(KundenNr)", "Kunde"),
        ("Auftragsdatum", "date NOT NULL", "Tag der Bestellung"),
        ("Liefertermin", "date NOT NULL", "zugesagter Liefertermin"),
        ("Status", "char(1) NOT NULL", "O = offen, F = in Fertigung, G = geliefert, S = storniert"),
        ("Bearbeiter", "nvarchar(50) NOT NULL", "zuständige Person im Vertrieb"),
    ]),
    ("Auftragspositionen", "Positionen eines Auftrags.", [
        ("AuftragsNr", "int NOT NULL REFERENCES dbo.Auftraege(AuftragsNr)", "Auftrag"),
        ("PosNr", "int NOT NULL", "Position im Auftrag"),
        ("ArtikelNr", "nvarchar(20) NOT NULL REFERENCES dbo.Artikel(ArtikelNr)", "Artikel"),
        ("Menge", "int NOT NULL", "bestellte Menge"),
        ("Einzelpreis", "decimal(10,2) NOT NULL", "vereinbarter Preis netto je Einheit"),
        ("RabattProzent", "decimal(5,2) NOT NULL", "Rabatt in Prozent auf die Position"),
    ]),
    ("Rechnungen", "Ausgangsrechnungen an Kunden.", [
        ("RechnungsNr", "int NOT NULL PRIMARY KEY", "Rechnungsnummer"),
        ("AuftragsNr", "int NOT NULL REFERENCES dbo.Auftraege(AuftragsNr)", "berechneter Auftrag"),
        ("KundenNr", "int NOT NULL REFERENCES dbo.Kunden(KundenNr)", "Rechnungsempfänger"),
        ("Rechnungsdatum", "date NOT NULL", "Tag der Rechnung"),
        ("Faellig", "date NOT NULL", "Zahlungsziel"),
        ("Betrag", "decimal(12,2) NOT NULL", "Rechnungsbetrag brutto in EUR"),
        ("Bezahlt", "decimal(12,2) NOT NULL", "bisher bezahlter Betrag in EUR"),
        ("BezahltAm", "date NULL", "Tag der letzten Zahlung, leer wenn nichts bezahlt"),
        ("Status", "nvarchar(20) NOT NULL", "offen, teilweise bezahlt oder bezahlt"),
        ("Mahnstufe", "int NOT NULL", "0 = nicht gemahnt, 1 bis 3 = Mahnstufe"),
    ]),
    ("Lagerplaetze", "Wo der Bestand eines Artikels liegt.", [
        ("ArtikelNr", "nvarchar(20) NOT NULL REFERENCES dbo.Artikel(ArtikelNr)", "Artikel"),
        ("Lager", "nvarchar(30) NOT NULL", "Hauptlager oder Außenlager"),
        ("Lagerplatz", "nvarchar(20) NOT NULL", "Regal und Fach, z. B. R03-F2"),
        ("Menge", "int NOT NULL", "Menge an diesem Platz; die Summe je Artikel ist der Lagerbestand"),
    ]),
    ("Bestellungen", "Bestellungen bei Lieferanten (Einkauf).", [
        ("BestellNr", "int NOT NULL PRIMARY KEY", "Bestellnummer"),
        ("LieferantenNr", "int NOT NULL REFERENCES dbo.Lieferanten(LieferantenNr)", "Lieferant"),
        ("ArtikelNr", "nvarchar(20) NOT NULL REFERENCES dbo.Artikel(ArtikelNr)", "bestellter Artikel"),
        ("Menge", "int NOT NULL", "bestellte Menge"),
        ("Einkaufspreis", "decimal(10,2) NOT NULL", "Einkaufspreis netto je Einheit in EUR"),
        ("Bestelldatum", "date NOT NULL", "Tag der Bestellung"),
        ("ErwartetAm", "date NOT NULL", "zugesagter Liefertag"),
        ("Status", "nvarchar(20) NOT NULL", "bestellt, teilgeliefert oder geliefert"),
    ]),
    ("Dokumente", "Belege als Datei: Rechnungen und Datenblätter als PDF.", [
        ("DokNr", "int NOT NULL PRIMARY KEY", "Dokumentnummer"),
        ("Art", "nvarchar(30) NOT NULL", "Rechnung oder Datenblatt"),
        ("RechnungsNr", "int NULL REFERENCES dbo.Rechnungen(RechnungsNr)", "zugehörige Rechnung"),
        ("ArtikelNr", "nvarchar(20) NULL REFERENCES dbo.Artikel(ArtikelNr)", "zugehöriger Artikel"),
        ("Dateiname", "nvarchar(150) NOT NULL", "Name der Datei"),
        ("Datei", "varbinary(max) NOT NULL", "die Datei selbst (PDF)"),
    ]),
    ("Anlagen", "Anlagen beim Kunden, die wir prüfen und warten.", [
        ("AnlagenNr", "nvarchar(20) NOT NULL PRIMARY KEY", "Anlagennummer, z. B. AN-0003"),
        ("KundenNr", "int NOT NULL REFERENCES dbo.Kunden(KundenNr)", "Betreiber der Anlage"),
        ("Bezeichnung", "nvarchar(100) NOT NULL", "Bezeichnung"),
        ("Typ", "nvarchar(30) NOT NULL", "Druckbehälter, Kompressor oder Dampfkessel"),
        ("Baujahr", "int NOT NULL", "Baujahr"),
        ("Standort", "nvarchar(80) NOT NULL", "Aufstellort beim Kunden"),
    ]),
    ("Pruefungen", "Durchgeführte wiederkehrende Prüfungen der Anlagen.", [
        ("PruefNr", "int NOT NULL PRIMARY KEY", "Prüfungsnummer"),
        ("AnlagenNr", "nvarchar(20) NOT NULL REFERENCES dbo.Anlagen(AnlagenNr)", "geprüfte Anlage"),
        ("Pruefart", "char(1) NOT NULL", "A = äußere Prüfung, I = innere Prüfung, F = Festigkeitsprüfung"),
        ("Pruefdatum", "date NOT NULL", "Tag der Prüfung"),
        ("Ergebnis", "nvarchar(20) NOT NULL", "ohne Mängel, mit Mängeln oder stillgelegt"),
        ("NaechstePruefung", "date NOT NULL", "Tag, an dem die nächste Prüfung dieser Art fällig ist"),
        ("Pruefer", "nvarchar(50) NOT NULL", "prüfende Person"),
    ]),
    ("Reklamationen", "Reklamationen zu Aufträgen.", [
        ("ReklamationsNr", "int NOT NULL PRIMARY KEY", "Reklamationsnummer"),
        ("AuftragsNr", "int NOT NULL REFERENCES dbo.Auftraege(AuftragsNr)", "betroffener Auftrag"),
        ("Eingang", "date NOT NULL", "Tag des Eingangs"),
        ("Grund", "nvarchar(200) NOT NULL", "Beschreibung des Mangels"),
        ("Status", "nvarchar(20) NOT NULL", "offen, in Klärung oder erledigt"),
        ("Verantwortlich", "nvarchar(50) NOT NULL", "zuständige Person"),
    ]),
]

VIEWS = [
    ("v_OffeneAuftraege",
     "Offene und in Fertigung befindliche Aufträge mit Kunde und Auftragswert.",
     """SELECT a.AuftragsNr, a.KundenNr, k.Firma, a.Auftragsdatum, a.Liefertermin,
       a.Status, a.Bearbeiter,
       CAST(SUM(p.Menge * p.Einzelpreis * (100 - p.RabattProzent) / 100) AS decimal(12,2)) AS Auftragswert
FROM dbo.Auftraege a
JOIN dbo.Kunden k ON k.KundenNr = a.KundenNr
JOIN dbo.Auftragspositionen p ON p.AuftragsNr = a.AuftragsNr
WHERE a.Status IN ('O', 'F')
GROUP BY a.AuftragsNr, a.KundenNr, k.Firma, a.Auftragsdatum, a.Liefertermin, a.Status, a.Bearbeiter"""),
    ("v_OffeneRechnungen",
     "Nicht vollständig bezahlte Rechnungen mit Kunde, Restbetrag und Tagen über dem Zahlungsziel.",
     """SELECT r.RechnungsNr, r.KundenNr, k.Firma, r.AuftragsNr, r.Rechnungsdatum, r.Faellig,
       r.Betrag, r.Bezahlt, r.Betrag - r.Bezahlt AS Restbetrag,
       CASE WHEN r.Faellig < CAST(GETDATE() AS date)
            THEN DATEDIFF(day, r.Faellig, CAST(GETDATE() AS date)) ELSE 0 END AS TageUeberfaellig,
       r.Mahnstufe, r.Status
FROM dbo.Rechnungen r
JOIN dbo.Kunden k ON k.KundenNr = r.KundenNr
WHERE r.Status <> N'bezahlt'"""),
]

HINT = """Status in dbo.Auftraege: O = offen, F = in Fertigung, G = geliefert, S = storniert. "Offen" im Sinne von noch nicht geliefert heisst Status IN ('O','F').
dbo.v_OffeneAuftraege enthaelt offene Auftraege mit Kunde und Auftragswert (netto, nach Rabatt).
Pruefart in dbo.Pruefungen: A = aeussere, I = innere, F = Festigkeitspruefung. Faellig ist eine Pruefung am Datum in NaechstePruefung; je Anlage und Pruefart zaehlt die juengste Pruefung.
Kunden werden ueber Firma gesucht (LIKE '%Meier%'), Anlagen ueber AnlagenNr (AN-0001) oder Bezeichnung.
Positionswert = Menge * Einzelpreis * (100 - RabattProzent) / 100. Preise netto in EUR.
Rechnung offen = Status <> 'bezahlt'; Restbetrag = Betrag - Bezahlt; ueberfaellig = offen und Faellig vor heute. dbo.v_OffeneRechnungen enthaelt sie mit Firma, Restbetrag und TageUeberfaellig.
Wo ein Artikel liegt: dbo.Lagerplaetze (Lager, Lagerplatz, Menge). Offene Bestellungen beim Lieferanten: dbo.Bestellungen mit Status <> 'geliefert', erwartet am ErwartetAm.
Rechnungen und Datenblaetter als PDF: dbo.Dokumente (Art, RechnungsNr bzw. ArtikelNr, Dateiname, Datei). Die Spalte Datei nur auswaehlen, wenn das Dokument gefragt ist."""

# --- SAMPLE DATA ---

CUSTOMERS = [
    (10001, "Meier GmbH", "Maschinenbau", "97070", "Würzburg", "Anna Meier"),
    (10002, "Schmitt Metallbau KG", "Metallbau", "97421", "Schweinfurt", "Jonas Schmitt"),
    (10003, "Hofmann Lebensmittel GmbH", "Lebensmittel", "97318", "Kitzingen", "Lea Hofmann"),
    (10004, "Wagner Kunststofftechnik", "Kunststoff", "97080", "Würzburg", "Paul Wagner"),
    (10005, "Becker Druckluft GmbH", "Druckluft", "97424", "Schweinfurt", "Mia Becker"),
    (10006, "Fischer Haustechnik", "Haustechnik", "97199", "Ochsenfurt", "Tim Fischer"),
    (10007, "Klein Maschinenbau AG", "Maschinenbau", "97816", "Lohr am Main", "Sara Klein"),
    (10008, "Wolf Chemie GmbH", "Chemie", "63739", "Aschaffenburg", "Ben Wolf"),
    (10009, "Neumann Getränke", "Getränke", "96450", "Coburg", "Ida Neumann"),
    (10010, "Schwarz Logistik", "Logistik", "97437", "Haßfurt", "Max Schwarz"),
]

ITEMS = [
    ("DB-0500", "Druckbehälter 500 l, 11 bar", "Druckbehälter", "Stk", 1890.00, 4, 2),
    ("DB-1000", "Druckbehälter 1.000 l, 11 bar", "Druckbehälter", "Stk", 2780.00, 1, 2),
    ("DB-2000", "Druckbehälter 2.000 l, 11 bar", "Druckbehälter", "Stk", 4350.00, 2, 1),
    ("SV-DN25", "Sicherheitsventil DN25, 11 bar", "Armaturen", "Stk", 148.50, 35, 20),
    ("MA-016", "Manometer 0–16 bar, Ø 100 mm", "Messtechnik", "Stk", 42.90, 12, 15),
    ("FD-DN50", "Flanschdichtung DN50, PTFE", "Dichtungen", "Stk", 6.80, 240, 100),
    ("KH-DN25", "Kugelhahn DN25, Messing", "Armaturen", "Stk", 31.20, 60, 30),
    ("KO-75", "Schraubenkompressor 7,5 kW", "Kompressoren", "Stk", 6980.00, 1, 1),
    ("KA-01", "Kondensatableiter, elektronisch", "Zubehör", "Stk", 219.00, 8, 10),
    ("DM-016", "Druckminderer 0–16 bar", "Armaturen", "Stk", 96.40, 22, 10),
    ("WS-KO", "Wartungsset Kompressor", "Service", "Set", 189.00, 14, 5),
    ("RE-28", "Edelstahlrohr 28 mm, 1 m", "Rohrleitung", "m", 18.75, 420, 200),
    ("PS-01", "Prüfservice Druckbehälter (Pauschale)", "Service", "Stk", 320.00, 999, 0),
]

SUPPLIERS = [
    (70001, "Armaturen Süd GmbH", "Nürnberg", "Petra Haas", "0911 2233-40"),
    (70002, "Behälterbau Franken KG", "Bamberg", "Uwe Stein", "0951 8800-12"),
    (70003, "MessTec Instruments", "Erlangen", "Nina Ott", "09131 4455-0"),
    (70004, "Kompressorenwerk Ost", "Chemnitz", "Karl Brandt", "0371 6060-21"),
]
# Warengruppe -> supplier
SUPPLIED_BY = {"Armaturen": 70001, "Dichtungen": 70001, "Rohrleitung": 70001,
               "Druckbehälter": 70002, "Messtechnik": 70003, "Zubehör": 70003,
               "Kompressoren": 70004, "Service": 70004}

PEOPLE = ["K. Lang", "M. Roth", "S. Braun", "T. Krause"]
INSPECTORS = ["Dr. Weiß (ZÜS)", "H. Vogel (ZÜS)", "befähigte Person J. Kern"]
# Inspection kind -> interval in years (as in the demo's own inspection rule)
INTERVAL = {"A": 2, "I": 5, "F": 10}


ORDER_LINES = {}
COMPANY = "Demo GmbH · Prüf- und Druckbehältertechnik · Industriestraße 5 · 97424 Schweinfurt"


def _pdf(draw):
    """A PDF from a drawing function; invariant, so every run gives the
    same bytes (the files are checked in)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle("Demo GmbH")
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def _money(v):
    return f"{v:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


def invoice_pdf(number, order, customer, lines):
    def draw(c):
        y = 800
        c.setFont("Helvetica", 8)
        c.drawString(50, y, COMPANY)
        c.setFont("Helvetica", 11)
        for text in (customer[1], customer[5], f"{customer[3]} {customer[4]}"):
            y -= 16
            c.drawString(50, y, text)
        y -= 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, f"Rechnung {number}")
        c.setFont("Helvetica", 10)
        y -= 18
        c.drawString(50, y, f"zu Auftrag {order} · Kundennummer {customer[0]} · "
                            "Rechnungsdatum und Fälligkeit siehe ERP")
        y -= 30
        c.setFont("Helvetica-Bold", 9)
        for x, head in ((50, "Artikel"), (120, "Bezeichnung"), (330, "Menge"),
                        (390, "Einzelpreis"), (470, "Rabatt"), (520, "Betrag")):
            c.drawString(x, y, head)
        c.setFont("Helvetica", 9)
        net = 0.0
        for nr, name, unit, qty, price, rebate in lines:
            y -= 15
            amount = qty * price * (100 - rebate) / 100
            net += amount
            c.drawString(50, y, nr)
            c.drawString(120, y, name[:38])
            c.drawString(330, y, f"{qty} {unit}")
            c.drawString(390, y, _money(price))
            c.drawString(470, y, f"{rebate:g} %")
            c.drawRightString(560, y, _money(amount))
        y -= 25
        gross = round(net * 1.19, 2)
        for label, value in (("Netto", net), ("MwSt. 19 %", gross - net), ("Gesamt", gross)):
            c.setFont("Helvetica-Bold" if label == "Gesamt" else "Helvetica", 10)
            c.drawString(390, y, label)
            c.drawRightString(560, y, _money(value))
            y -= 15
        y -= 20
        c.setFont("Helvetica", 9)
        c.drawString(50, y, "Zahlbar innerhalb von 30 Tagen ohne Abzug. "
                            "Beispieldokument, alle Angaben erfunden.")
    return _pdf(draw)


def datasheet_pdf(item):
    nr, name, group, unit, price, _stock, _minimum = item
    def draw(c):
        c.setFont("Helvetica", 8)
        c.drawString(50, 800, COMPANY)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, f"Datenblatt {name}")
        c.setFont("Helvetica", 10)
        y = 720
        for label, value in (("Artikelnummer", nr), ("Warengruppe", group),
                             ("Einheit", unit), ("Listenpreis netto", _money(price)),
                             ("Betriebsdruck", "max. 16 bar"), ("Temperatur", "-10 bis +120 °C"),
                             ("Prüfung", "werksgeprüft, Prüfprotokoll auf Anfrage")):
            c.drawString(50, y, label)
            c.drawString(200, y, value)
            y -= 16
        c.drawString(50, y - 20, "Beispieldokument, alle Angaben erfunden.")
    return _pdf(draw)


def q(text):
    return "N'" + str(text).replace("'", "''") + "'"


def day(offset):
    return f"DATEADD(day, {int(offset)}, @heute)"


def build_data(rng):
    rows = {t[0]: [] for t in TABLES}
    for nr, firm, branch, plz, city, contact in CUSTOMERS:
        mail = contact.split()[0].lower() + "@" + firm.split()[0].lower() + ".example.com"
        phone = f"0{rng.randint(931, 9799)} {rng.randint(100, 9999)}-{rng.randint(0, 99)}"
        rows["Kunden"].append([str(nr), q(firm), q(branch), q(plz), q(city), q(contact),
                               q(mail), q(phone), day(-rng.randint(400, 4000))])
    for nr, firm, city, contact, phone in SUPPLIERS:
        mail = contact.split()[0].lower() + "@" + firm.split()[0].lower() + ".example.com"
        rows["Lieferanten"].append([str(nr), q(firm), q(city), q(contact), q(phone), q(mail)])
    for nr, name, group, unit, price, stock, minimum in ITEMS:
        rows["Artikel"].append([q(nr), q(name), q(group), q(unit), f"{price:.2f}",
                                str(stock), str(minimum)])
        if group == "Service" and unit == "Stk":
            continue                    # a service lies nowhere
        if group in ("Druckbehälter", "Kompressoren"):
            places = [("Außenlager", f"H{rng.randint(1, 4)}-{rng.randint(1, 12):02d}", stock)]
        elif stock > 20:
            main = stock * rng.randint(55, 80) // 100
            places = [("Hauptlager", f"R{rng.randint(1, 12):02d}-F{rng.randint(1, 6)}", main),
                      ("Außenlager", f"H{rng.randint(1, 4)}-{rng.randint(1, 12):02d}", stock - main)]
        else:
            places = [("Hauptlager", f"R{rng.randint(1, 12):02d}-F{rng.randint(1, 6)}", stock)]
        for store, place, qty in places:
            rows["Lagerplaetze"].append([q(nr), q(store), q(place), str(qty)])

    # Orders: Meier gets a fixed, demo-friendly mix; the rest is random.
    orders = []
    plan = [(10001, "O"), (10001, "O"), (10001, "F"), (10001, "G"), (10001, "G"),
            (10001, "G")]
    for c in [c[0] for c in CUSTOMERS[1:]]:
        for _ in range(rng.randint(2, 4)):
            plan.append((c, rng.choice("OFGGGGS")))
    for i, (cust, status) in enumerate(plan):
        nr = 24001 + i
        ordered = -rng.randint(3, 25) if status in "OF" else -rng.randint(30, 200)
        delivery = ordered + rng.randint(14, 60)
        rows["Auftraege"].append([str(nr), str(cust), day(ordered), day(delivery),
                                  q(status)[1:], q(rng.choice(PEOPLE))])
        net = 0.0
        lines = ORDER_LINES.setdefault(nr, [])
        for pos, item in enumerate(rng.sample(ITEMS, rng.randint(1, 4)), start=1):
            qty = 1 if item[2] in ("Druckbehälter", "Kompressoren") else rng.randint(2, 40)
            rebate = rng.choice([0, 0, 0, 3, 5, 10])
            net += qty * item[4] * (100 - rebate) / 100
            lines.append((item[0], item[1], item[3], qty, item[4], rebate))
            rows["Auftragspositionen"].append([str(nr), str(pos), q(item[0]), str(qty),
                                               f"{item[4]:.2f}", f"{rebate:.2f}"])
        orders.append((nr, cust, status, delivery, round(net * 1.19, 2)))

    # Invoices for delivered orders. Meier: one paid, one overdue with a
    # reminder, one partly paid -- the rest by chance.
    meier_plan = iter([("bezahlt", 0), ("offen", 1), ("teilweise bezahlt", 0)])
    invoice = 2025101
    for nr, cust, status, delivery, gross in orders:
        if status != "G":
            continue
        issued = min(delivery, -2)
        due = issued + 30
        if cust == 10001:
            state, reminder = next(meier_plan, ("bezahlt", 0))
        elif due >= 0:
            state, reminder = rng.choice([("offen", 0), ("offen", 0), ("bezahlt", 0)])
        else:
            state, reminder = rng.choice([("bezahlt", 0)] * 4 + [("offen", 1), ("offen", 2),
                                                                 ("teilweise bezahlt", 0)])
        if state == "offen" and cust == 10001:
            issued, due = -45, -15          # overdue for the demo
        paid = {"bezahlt": gross, "offen": 0.0,
                "teilweise bezahlt": round(gross * 0.5, 2)}[state]
        paid_on = "NULL" if not paid else day(min(due - rng.randint(0, 20), -1))
        rows["Rechnungen"].append([str(invoice), str(nr), str(cust), day(issued), day(due),
                                   f"{gross:.2f}", f"{paid:.2f}", paid_on, q(state),
                                   str(reminder)])
        customer = next(c for c in CUSTOMERS if c[0] == cust)
        rows["Dokumente"].append([str(len(rows["Dokumente"]) + 1), q("Rechnung"), str(invoice),
                                  "NULL", q(f"Rechnung-{invoice}.pdf"),
                                  "0x" + invoice_pdf(invoice, nr, customer,
                                                     ORDER_LINES[nr]).hex().upper()])
        invoice += 1
    for item in ITEMS:
        if item[2] in ("Armaturen", "Messtechnik"):
            rows["Dokumente"].append([str(len(rows["Dokumente"]) + 1), q("Datenblatt"), "NULL",
                                      q(item[0]), q(f"Datenblatt-{item[0]}.pdf"),
                                      "0x" + datasheet_pdf(item).hex().upper()])

    # Purchase orders: what is below the minimum is on order, a few came in.
    po = 450001
    for nr, name, group, unit, price, stock, minimum in ITEMS:
        if group == "Service" and unit == "Stk":
            continue
        supplier = SUPPLIED_BY[group]
        buy = round(price * 0.62, 2)
        if stock < minimum:
            rows["Bestellungen"].append([str(po), str(supplier), q(nr),
                                         str(max(minimum * 2 - stock, 1)), f"{buy:.2f}",
                                         day(-rng.randint(2, 10)), day(rng.randint(3, 21)),
                                         q("bestellt")])
            po += 1
        if rng.random() < 0.6:
            ordered = -rng.randint(30, 120)
            rows["Bestellungen"].append([str(po), str(supplier), q(nr),
                                         str(rng.randint(2, 50) if unit != "Stk" or price < 500
                                             else rng.randint(1, 3)), f"{buy:.2f}",
                                         day(ordered), day(ordered + rng.randint(7, 21)),
                                         q("geliefert")])
            po += 1

    # Plants and their inspections
    plants = [
        ("AN-0001", 10001, "Druckluftbehälter Halle 1", "Druckbehälter", 2014, "Halle 1"),
        ("AN-0002", 10001, "Kompressorstation", "Kompressor", 2019, "Technikraum"),
        ("AN-0003", 10001, "Druckbehälter 2.000 l", "Druckbehälter", 2011, "Außenlager"),
        ("AN-0004", 10002, "Druckbehälter 1.000 l", "Druckbehälter", 2017, "Werkstatt"),
        ("AN-0005", 10003, "Dampfkessel Produktion", "Dampfkessel", 2009, "Kesselhaus"),
        ("AN-0006", 10003, "Druckbehälter 500 l", "Druckbehälter", 2020, "Abfüllung"),
        ("AN-0007", 10005, "Druckbehälter 2.000 l", "Druckbehälter", 2016, "Halle B"),
        ("AN-0008", 10007, "Druckbehälter 1.000 l", "Druckbehälter", 2012, "Montage"),
        ("AN-0009", 10008, "Reaktordruckbehälter", "Druckbehälter", 2008, "Anlage 3"),
        ("AN-0010", 10009, "Druckbehälter 500 l", "Druckbehälter", 2021, "Keller"),
    ]
    for p in plants:
        rows["Anlagen"].append([q(p[0]), str(p[1]), q(p[2]), q(p[3]), str(p[4]), q(p[5])])
    nr = 1
    # due within the next 30 days -- the demo question
    due_soon = {"AN-0003": "A", "AN-0005": "A", "AN-0009": "I"}
    for plant in [p[0] for p in plants]:
        for kind, years in INTERVAL.items():
            if kind == "F" and rng.random() < 0.5:
                continue
            if due_soon.get(plant) == kind:
                last = -years * 365 + rng.randint(5, 28)
            else:
                last = -rng.randint(60, years * 365 - 60)
            result = rng.choice(["ohne Mängel"] * 6 + ["mit Mängeln"])
            rows["Pruefungen"].append([
                str(nr), q(plant), q(kind)[1:], day(last), q(result),
                f"DATEADD(year, {years}, {day(last)})", q(rng.choice(INSPECTORS))])
            nr += 1

    complaints = [
        ("Sicherheitsventil öffnet bereits bei 9 bar", "offen"),
        ("Manometer mit Glasbruch geliefert", "in Klärung"),
        ("Lieferung unvollständig, Dichtungen fehlen", "erledigt"),
        ("Kondensatableiter undicht", "offen"),
        ("Falscher Druckminderer geliefert", "erledigt"),
    ]
    delivered = [r for r in rows["Auftraege"] if r[4] == "'G'"]
    for i, (reason, status) in enumerate(complaints):
        order = delivered[i * 2 % len(delivered)]
        rows["Reklamationen"].append([str(9001 + i), order[0], day(-rng.randint(1, 40)),
                                      q(reason), q(status), q(rng.choice(PEOPLE))])
    return rows


def seed_sql(rows):
    out = [
        "-- Demo ERP for LocaNoto. Generated by make_demo_erp.py -- edit that file.",
        "-- Run as sa with:  sqlcmd ... -v READ_PASSWORD=\"...\" -i seed.sql",
        "-- Recreates the database each time: all data here is sample data.",
        "SET NOCOUNT ON;",
        "USE master;",
        f"IF DB_ID(N'{DATABASE}') IS NOT NULL",
        f"BEGIN ALTER DATABASE [{DATABASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{DATABASE}]; END",
        "GO",
        f"CREATE DATABASE [{DATABASE}];",
        "GO",
        f"USE [{DATABASE}];",
        "GO",
    ]
    for table, _desc, columns in TABLES:
        cols = ",\n  ".join(f"{c} {t}" for c, t, _d in columns)
        extra = {"Auftragspositionen": ",\n  PRIMARY KEY (AuftragsNr, PosNr)",
                 "Lagerplaetze": ",\n  PRIMARY KEY (ArtikelNr, Lagerplatz)"}.get(table, "")
        out.append(f"CREATE TABLE dbo.{table} (\n  {cols}{extra}\n);")
    out.append("GO")
    for name, _desc, body in VIEWS:
        out += [f"CREATE VIEW dbo.{name} AS\n{body};", "GO"]
    # one batch: @heute lives only within it
    out.append("DECLARE @heute date = CAST(GETDATE() AS date);")
    for table, _desc, columns in TABLES:
        names = ", ".join(c for c, _t, _d in columns)
        for r in rows[table]:
            out.append(f"INSERT INTO dbo.{table} ({names}) VALUES ({', '.join(r)});")
    out.append("GO")
    out += [
        "-- Read-only login for LocaNoto (db_datareader: SELECT only).",
        "USE master;",
        f"IF SUSER_ID(N'{READ_LOGIN}') IS NOT NULL DROP LOGIN [{READ_LOGIN}];",
        f"CREATE LOGIN [{READ_LOGIN}] WITH PASSWORD = N'$(READ_PASSWORD)', "
        f"DEFAULT_DATABASE = [{DATABASE}], CHECK_POLICY = ON;",
        "GO",
        f"USE [{DATABASE}];",
        f"CREATE USER [{READ_LOGIN}] FOR LOGIN [{READ_LOGIN}];",
        f"ALTER ROLE db_datareader ADD MEMBER [{READ_LOGIN}];",
        "GO",
        "PRINT 'DemoERP ready';",
        "",
    ]
    return "\n".join(out)


def data_model_md(rows):
    lines = [
        "# Datenmodell DemoERP",
        "",
        "Beispieldatenbank für LocaNoto (Microsoft SQL Server, Datenbank "
        f"`{DATABASE}`, Schema `dbo`). Alle Daten sind erfunden.",
        "",
        "## Beziehungen",
        "",
        "- Ein **Kunde** hat viele **Aufträge**, ein Auftrag viele **Auftragspositionen**, "
        "jede Position verweist auf einen **Artikel**.",
        "- Ein **Kunde** betreibt **Anlagen**; zu jeder Anlage gibt es **Prüfungen**.",
        "- Eine **Reklamation** gehört zu genau einem **Auftrag**.",
        "- Ein gelieferter **Auftrag** wird mit einer **Rechnung** an den Kunden berechnet.",
        "- Der **Lagerbestand** eines Artikels liegt auf einem oder mehreren **Lagerplätzen**.",
        "- **Bestellungen** gehen an **Lieferanten** und betreffen je einen **Artikel**.",
        "",
        "## Statuswerte",
        "",
        "| Tabelle | Spalte | Wert | Bedeutung |",
        "|---|---|---|---|",
        "| Auftraege | Status | O | offen |",
        "| Auftraege | Status | F | in Fertigung |",
        "| Auftraege | Status | G | geliefert |",
        "| Auftraege | Status | S | storniert |",
        "| Pruefungen | Pruefart | A | äußere Prüfung, alle 2 Jahre |",
        "| Pruefungen | Pruefart | I | innere Prüfung, alle 5 Jahre |",
        "| Pruefungen | Pruefart | F | Festigkeitsprüfung, alle 10 Jahre |",
        "| Rechnungen | Status | offen | nichts bezahlt |",
        "| Rechnungen | Status | teilweise bezahlt | ein Teil ist bezahlt |",
        "| Rechnungen | Status | bezahlt | vollständig bezahlt |",
        "| Bestellungen | Status | bestellt | beim Lieferanten bestellt, noch nicht da |",
        "| Bestellungen | Status | geliefert | eingetroffen |",
        "",
    ]
    for table, desc, columns in TABLES:
        lines += [f"## Tabelle {table}", "", desc + f" {len(rows[table])} Zeilen.", "",
                  "| Spalte | Typ | Bedeutung |", "|---|---|---|"]
        for c, t, d in columns:
            typ = t.split(" NOT NULL")[0].split(" NULL")[0]
            key = " (Schlüssel)" if "PRIMARY KEY" in t else ""
            ref = ""
            if "REFERENCES" in t:
                ref = " → " + t.split("REFERENCES dbo.")[1].split("(")[0]
            lines.append(f"| {c} | {typ} | {d}{key}{ref} |")
        lines.append("")
    for name, desc, body in VIEWS:
        lines += [f"## Sicht {name}", "", desc, "", "```sql", body, "```", ""]
    lines += [
        "## Beispielfragen",
        "",
        "- Welche Aufträge der Meier GmbH sind noch offen?",
        "- Wie hoch ist der Wert der offenen Aufträge je Kunde?",
        "- Welche Prüfungen sind in den nächsten 30 Tagen fällig?",
        "- Wann ist die nächste äußere Prüfung der Anlage AN-0003 fällig?",
        "- Welche Artikel liegen unter dem Mindestbestand?",
        "- Welche Reklamationen sind noch offen, und zu welchem Auftrag gehören sie?",
        "- Welche Rechnungen der Meier GmbH sind offen?",
        "- Welche Rechnungen sind überfällig, und wie viel steht insgesamt aus?",
        "- Hat die Schmitt Metallbau KG ihre letzte Rechnung bezahlt?",
        "- Wie viele Manometer haben wir, und wo liegen sie?",
        "- Was ist bei Lieferanten bestellt und noch nicht da?",
        "- Wann kommen die Kondensatableiter?",
        "- Wer ist Ansprechpartner bei Becker Druckluft, mit Telefonnummer?",
        "- Welche Kunden hatten dieses Jahr den größten Umsatz?",
        "- Was hat die Meier GmbH zuletzt bestellt?",
        "- Welche Aufträge betreut K. Lang?",
        "- Zeig mir die Rechnung 2025103. Was steht darauf?",
        "- Gibt es ein Datenblatt zum Kugelhahn?",
        "",
    ]
    return "\n".join(lines)


def indent(text, spaces):
    pad = " " * spaces
    return "\n".join(pad + line if line else "" for line in text.splitlines())


def manifest(sql):
    return f"""# Demo ERP for LocaNoto: Microsoft SQL Server 2022 (Developer edition),
# seeded with fictitious sample data. Generated by make_demo_erp.py.
#
#   kubectl -n <namespace> create secret generic demo-erp \\
#     --from-literal=SA_PASSWORD='...' --from-literal=READ_PASSWORD='...'
#   kubectl -n <namespace> apply -f demo-erp.yaml
#
# Deploy into the namespace of LocaNoto: the network policy only lets
# LocaNoto's pods (app.kubernetes.io/name=locanoto) reach the database.
# Deploying accepts the SQL Server EULA (ACCEPT_EULA below); the Developer
# edition is licensed for development and demos, not for production.
# SQL Server images exist for amd64 only, hence the node selector.
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: demo-erp-seed
  labels: {{app.kubernetes.io/name: demo-erp}}
data:
  seed.sql: |
{indent(sql, 4)}
---
apiVersion: v1
kind: Service
metadata:
  name: demo-erp
  labels: {{app.kubernetes.io/name: demo-erp}}
spec:
  selector: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: database}}
  ports:
    - {{name: mssql, port: 1433, targetPort: 1433}}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: demo-erp
  labels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: database}}
spec:
  serviceName: demo-erp
  replicas: 1
  selector:
    matchLabels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: database}}
  template:
    metadata:
      labels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: database}}
    spec:
      nodeSelector: {{kubernetes.io/arch: amd64}}
      securityContext: {{fsGroup: 10001}}
      containers:
        - name: mssql
          image: {IMAGE}
          env:
            - {{name: ACCEPT_EULA, value: "Y"}}
            - {{name: MSSQL_PID, value: Developer}}
            - name: MSSQL_SA_PASSWORD
              valueFrom: {{secretKeyRef: {{name: demo-erp, key: SA_PASSWORD}}}}
          ports:
            - {{containerPort: 1433, name: mssql}}
          readinessProbe:
            tcpSocket: {{port: 1433}}
            initialDelaySeconds: 15
            periodSeconds: 10
          resources:
            requests: {{cpu: 500m, memory: 2Gi}}
            limits: {{memory: 4Gi}}
          volumeMounts:
            - {{name: data, mountPath: /var/opt/mssql}}
  volumeClaimTemplates:
    - metadata: {{name: data}}
      spec:
        accessModes: [ReadWriteOnce]
        resources: {{requests: {{storage: 5Gi}}}}
---
# Creates the database, the sample data and the read-only login. It waits
# for the server, recreates DemoERP and removes itself a day later.
apiVersion: batch/v1
kind: Job
metadata:
  name: demo-erp-seed
  labels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: seed}}
spec:
  backoffLimit: 4
  activeDeadlineSeconds: 1800
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: seed}}
    spec:
      restartPolicy: Never
      nodeSelector: {{kubernetes.io/arch: amd64}}
      containers:
        - name: seed
          image: {IMAGE}
          command: ["/bin/bash", "-c"]
          args:
            - |
              TOOL=$(ls /opt/mssql-tools*/bin/sqlcmd | tail -n 1)
              TRUST=""
              case "$TOOL" in *tools18*) TRUST="-C" ;; esac
              for i in $(seq 1 60); do
                "$TOOL" -S demo-erp -U sa -P "$SA_PASSWORD" $TRUST -Q "SELECT 1" >/dev/null 2>&1 && break
                echo "waiting for SQL Server ..."; sleep 5
              done
              "$TOOL" -S demo-erp -U sa -P "$SA_PASSWORD" $TRUST -b \\
                -v READ_PASSWORD="$READ_PASSWORD" -i /seed/seed.sql
          env:
            - name: SA_PASSWORD
              valueFrom: {{secretKeyRef: {{name: demo-erp, key: SA_PASSWORD}}}}
            - name: READ_PASSWORD
              valueFrom: {{secretKeyRef: {{name: demo-erp, key: READ_PASSWORD}}}}
          volumeMounts:
            - {{name: seed, mountPath: /seed}}
      volumes:
        - name: seed
          configMap: {{name: demo-erp-seed}}
---
# Only LocaNoto's pods and the seed job reach the database.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: demo-erp
  labels: {{app.kubernetes.io/name: demo-erp}}
spec:
  podSelector:
    matchLabels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: database}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: {{matchLabels: {{app.kubernetes.io/name: locanoto}}}}
        - podSelector: {{matchLabels: {{app.kubernetes.io/name: demo-erp, app.kubernetes.io/component: seed}}}}
      ports:
        - {{port: 1433, protocol: TCP}}
"""


def main():
    rows = build_data(random.Random(2026))
    sql = seed_sql(rows)
    files = {"seed.sql": sql, "demo-erp.yaml": manifest(sql),
             "data-model.md": data_model_md(rows), "sql-hint.txt": HINT + "\n"}
    for name, text in files.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print("written:", ", ".join(files),
          "|", ", ".join(f"{t}: {len(r)}" for t, r in rows.items()))


if __name__ == "__main__":
    main()
