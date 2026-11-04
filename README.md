# LocaNoto

*English: [README.en.md](README.en.md)*

Fragen an die eigenen Dokumente, beantwortet mit Datei und Seite. LocaNoto
läuft im eigenen Netz; die Dokumente verlassen es nicht.

## Funktionen

- Suche in PDF, Word, Markdown, Text und gescannten Seiten, Antwort mit Quellenangabe
- Arbeitsbereiche mit Zugriffsrechten, privater Bereich je Nutzer
- Werkzeuge: Datenbank (Microsoft SQL Server), E-Mail und Kalender (Exchange, IMAP),
  Websuche, Dateien erstellen (Excel, Word, PDF, PowerPoint)
- Dateiablage: OpenCloud, oCIS, ownCloud, Nextcloud
- Verschlüsselte Ablage, Anmeldung über das Firmenverzeichnis (OIDC)
- Web-Oberfläche und HTTP-Schnittstelle (`/api/v1/docs`)
- Betrieb mit Docker oder Kubernetes, Postgres mit pgvector

## Installation

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
python3 locanoto-setup.py
```

Voraussetzungen: Python 3.8 oder neuer, Docker oder `kubectl`, ein
OpenAI-kompatibler Modellserver. Details: [deploy/README.md](deploy/README.md).

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [HANDBUCH.md](HANDBUCH.md) | Bedienung für Nutzer und Admins |
| [REFERENZ.md](REFERENZ.md) | Technische Referenz: Aufbau, Konfiguration, Betrieb, Sicherheit |
| [deploy/README.md](deploy/README.md) | Installer |
| [k8s/enterprise/README.md](k8s/enterprise/README.md) | Kubernetes-Manifeste |
| [deploy/demo-erp/README.md](deploy/demo-erp/README.md) | Beispieldatenbank für Vorführungen |
| [.env.example](.env.example) | Alle Einstellungen |

## Tests

```bash
python selbsttest.py
python test_api.py
```

## Frühere Ausgabe

Die frühere Ausgabe (Abbilder `schlank` und `voll`) liegt im Branch
[`legacy`](https://github.com/mw-research/LocaNoto/tree/legacy) und wird nicht
weiterentwickelt.

## Projekt

Entstanden im Projekt **DIG:IT-KMU** am Institut für Digital Engineering (IDEE)
der Technischen Hochschule Würzburg-Schweinfurt (THWS). Gefördert im Rahmen des
EFRE Bayern 2021–2027 durch das Bayerische Staatsministerium für Wirtschaft,
Landesentwicklung und Energie, kofinanziert von der Europäischen Union.
https://digit.kmu.bayern

## Lizenz

[GNU Affero General Public License v3](LICENSE). Lizenzen der verwendeten
Pakete: [LIZENZEN.md](LIZENZEN.md).

Copyright © 2026 Markus Wilhelm (mw-research)
