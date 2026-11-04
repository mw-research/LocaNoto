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
        ("KundeSeit", "date NOT NULL", "Beginn der Geschäftsbeziehung"),
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
]

HINT = """Status in dbo.Auftraege: O = offen, F = in Fertigung, G = geliefert, S = storniert. "Offen" im Sinne von noch nicht geliefert heisst Status IN ('O','F').
dbo.v_OffeneAuftraege enthaelt offene Auftraege mit Kunde und Auftragswert (netto, nach Rabatt).
Pruefart in dbo.Pruefungen: A = aeussere, I = innere, F = Festigkeitspruefung. Faellig ist eine Pruefung am Datum in NaechstePruefung; je Anlage und Pruefart zaehlt die juengste Pruefung.
Kunden werden ueber Firma gesucht (LIKE '%Meier%'), Anlagen ueber AnlagenNr (AN-0001) oder Bezeichnung.
Positionswert = Menge * Einzelpreis * (100 - RabattProzent) / 100. Preise netto in EUR."""

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

PEOPLE = ["K. Lang", "M. Roth", "S. Braun", "T. Krause"]
INSPECTORS = ["Dr. Weiß (ZÜS)", "H. Vogel (ZÜS)", "befähigte Person J. Kern"]
# Inspection kind -> interval in years (as in the demo's own inspection rule)
INTERVAL = {"A": 2, "I": 5, "F": 10}


def q(text):
    return "N'" + str(text).replace("'", "''") + "'"


def day(offset):
    return f"DATEADD(day, {int(offset)}, @heute)"


def build_data(rng):
    rows = {t[0]: [] for t in TABLES}
    for nr, firm, branch, plz, city, contact in CUSTOMERS:
        mail = contact.split()[0].lower() + "@" + firm.split()[0].lower() + ".example.com"
        rows["Kunden"].append([str(nr), q(firm), q(branch), q(plz), q(city), q(contact),
                               q(mail), day(-rng.randint(400, 4000))])
    for nr, name, group, unit, price, stock, minimum in ITEMS:
        rows["Artikel"].append([q(nr), q(name), q(group), q(unit), f"{price:.2f}",
                                str(stock), str(minimum)])

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
        orders.append(nr)
        rows["Auftraege"].append([str(nr), str(cust), day(ordered), day(delivery),
                                  q(status)[1:], q(rng.choice(PEOPLE))])
        for pos, item in enumerate(rng.sample(ITEMS, rng.randint(1, 4)), start=1):
            qty = 1 if item[2] in ("Druckbehälter", "Kompressoren") else rng.randint(2, 40)
            rebate = rng.choice([0, 0, 0, 3, 5, 10])
            rows["Auftragspositionen"].append([str(nr), str(pos), q(item[0]), str(qty),
                                               f"{item[4]:.2f}", f"{rebate:.2f}"])

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
        extra = ",\n  PRIMARY KEY (AuftragsNr, PosNr)" if table == "Auftragspositionen" else ""
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
        "",
    ]
    for table, desc, columns in TABLES:
        lines += [f"## Tabelle {table}", "", desc + f" {len(rows[table])} Zeilen.", "",
                  "| Spalte | Typ | Bedeutung |", "|---|---|---|"]
        for c, t, d in columns:
            typ = t.split(" NOT NULL")[0]
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
