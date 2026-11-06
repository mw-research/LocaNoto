# Demo-ERP für LocaNoto

Eine Beispieldatenbank (Microsoft SQL Server 2022) mit erfundenen Firmendaten:
Kunden, Lieferanten, Artikel mit Lagerplätzen, Aufträge, Rechnungen,
Bestellungen, Anlagen, Prüfungen und Reklamationen. Damit lassen sich
Datenbankfragen in LocaNoto vorführen, etwa „Welche Rechnungen der Meier GmbH
sind offen?“, „Wie viele Manometer haben wir, und wo liegen sie?“ oder
„Welche Prüfungen sind in den nächsten 30 Tagen fällig?“. Weitere
Beispielfragen stehen am Ende von `data-model.md`.

| Datei | Inhalt |
|---|---|
| `demo-erp.yaml` | SQL Server, Befüllung als Job, Netzwerkregel – für Kubernetes |
| `seed.sql` | Tabellen, Beispieldaten, Konto `locanoto_lesen` (nur Lesen) |
| `data-model.md` | Datenmodell als Dokument zum Hochladen in LocaNoto |
| `sql-hint.txt` | Kurzhinweis für das Modell (Statuscodes, Beziehungen) |
| `make_demo_erp.py` | erzeugt die vier Dateien oben aus einer Tabellendefinition |
| `check_demo_erp.py` | prüft die Datenbank mit dem Datenbankcode von LocaNoto |
| `documents/` | vier Beispieldokumente als PDF passend zu den Daten, zwei davon für die Schnitzeljagd |
| `make_documents.py` | erzeugt die PDFs in `documents/` (läuft mit `make_demo_erp.py`) |
| `SCHNITZELJAGD.md` | Spiel für das Demo-Event mit Lösung – nicht hochladen |

Voraussetzungen: ein Knoten mit amd64 (SQL Server gibt es nicht für ARM),
2 GB Arbeitsspeicher frei, 5 GB Speicher. Die Developer-Edition ist für
Entwicklung und Vorführungen lizenziert, nicht für den Produktivbetrieb; mit
dem Einspielen wird die Lizenz von SQL Server angenommen (`ACCEPT_EULA`).

## 1. Einspielen

Im Namensraum von LocaNoto (die Netzwerkregel lässt nur LocaNoto zu):

```bash
NS=locanoto
kubectl -n $NS create secret generic demo-erp \
  --from-literal=SA_PASSWORD="Sa1!$(openssl rand -hex 12)" \
  --from-literal=READ_PASSWORD="Rd1!$(openssl rand -hex 12)"
kubectl -n $NS apply -f demo-erp.yaml
kubectl -n $NS wait --for=condition=complete job/demo-erp-seed --timeout=15m
```

Das Lese-Passwort für Schritt 2:

```bash
kubectl -n $NS get secret demo-erp -o jsonpath='{.data.READ_PASSWORD}' | base64 -d
```

Die Datumsangaben sind relativ zum Tag der Befüllung. Neu befüllen (setzt die
Datenbank zurück): `kubectl -n $NS delete job demo-erp-seed` und
`kubectl -n $NS apply -f demo-erp.yaml`. Das Lesekonto entsteht dabei mit dem
Passwort aus dem Secret neu; der in LocaNoto hinterlegte Zugang bleibt gültig.

Prüfen, sobald der Zugang in LocaNoto hinterlegt ist (Schritt 2) – im Pod
von LocaNoto, mit dem dort gespeicherten Zugang, ohne Secret und ohne
Passwort auf der Befehlszeile:

```bash
kubectl -n $NS cp check_demo_erp.py <pod>:/tmp/check.py
kubectl -n $NS exec <pod> -- python /tmp/check.py
```

Bei mehreren Arbeitsbereichen mit DemoERP-Zugang wählt `DEMO_ERP_ROOM=<id>`
einen aus.

## 2. In LocaNoto hinterlegen

1. **Arbeitsbereich** für die Demo anlegen, z. B. `vertrieb` (Verwaltung →
   Arbeitsbereiche), und die Vorführenden als Mitglieder eintragen.
2. **Datenbankzugang** (Verwaltung → Datenbankzugang je Arbeitsbereich):
   Server `demo-erp`, Port `1433`, Datenbank `DemoERP`, Benutzer
   `locanoto_lesen`, das Passwort aus Schritt 1, Hinweis: Inhalt von
   `sql-hint.txt`.
3. **Dokumente hochladen** in denselben Arbeitsbereich: `data-model.md` –
   dann beantwortet LocaNoto auch Fragen zur Struktur („Welche Tabellen gibt
   es?“, „Was bedeutet Status F?“) – sowie die Beispieldokumente aus
   `documents/`: Prüfvorschrift und Reklamationsprozess passen zu den Daten
   (Prüfarten und Fristen, Status der Reklamationen); Bestellung
   Werbeartikel Tassen und Artikelabgleich Keramik Manufaktur Weber gehören
   zur Schnitzeljagd (`SCHNITZELJAGD.md`, diese Datei selbst nicht hochladen).
4. Im Chat unter den Optionen **Datenbank** anhaken und fragen.

Dasselbe über die API:

```bash
curl -X PUT "https://<adresse>/api/v1/admin/workspaces/vertrieb/sql-account" \
  -H "Authorization: Bearer <admin-token>" -H "Content-Type: application/json" \
  -d '{"server": "demo-erp", "port": 1433, "datenbank": "DemoERP",
       "benutzer": "locanoto_lesen", "passwort": "<lese-passwort>",
       "hinweis": "<inhalt von sql-hint.txt>"}'
```

## 3. Beispielfragen

- Welche Aufträge der Meier GmbH sind noch offen?
- Wie hoch ist der Wert der offenen Aufträge je Kunde?
- Welche Prüfungen sind in den nächsten 30 Tagen fällig?
- Wann ist die nächste äußere Prüfung der Anlage AN-0003 fällig?
- Welche Artikel liegen unter dem Mindestbestand?
- Welche Reklamationen sind noch offen, und zu welchem Auftrag gehören sie?

Die erzeugte SQL-Abfrage steht unter jeder Antwort („Datenbankabfrage“).

## Prüfen

`check_demo_erp.py` läuft im LocaNoto-Image, liest das Schema, stellt die
Abfragen hinter den Beispielfragen und prüft, dass das Konto nichts ändern
kann. Der Installationstest auf GitHub spielt die Datenbank bei jedem Stand in
einen kind-Cluster ein und führt es aus.

---

# Demo ERP for LocaNoto

A sample SQL Server 2022 database with fictitious company data. Create the
secret and apply `demo-erp.yaml` in LocaNoto's namespace (step 1), then add
the database account to a workspace with the hint from `sql-hint.txt` and
upload `data-model.md` there (step 2). amd64 nodes only; the Developer
edition is not licensed for production.
