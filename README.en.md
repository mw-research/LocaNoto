# LocaNoto

*Deutsch: [README.md](README.md)*

Questions to your own documents, answered with file and page. LocaNoto runs
in your own network; the documents do not leave it.

## Features

- Search in PDF, Word, Markdown, text and scanned pages, answers with sources
- Workspaces with permissions, a private workspace per user
- Tools: database (Microsoft SQL Server), mail and calendar (Exchange, IMAP),
  web search, file creation (Excel, Word, PDF, PowerPoint)
- File store: OpenCloud, oCIS, ownCloud, Nextcloud
- Encrypted storage, sign-in through the company directory (OIDC)
- Web interface and HTTP API (`/api/v1/docs`)
- Runs on Docker or Kubernetes, Postgres with pgvector

## Installation

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
python3 locanoto-setup.py --en
```

Requirements: Python 3.8 or newer, Docker or `kubectl`, an OpenAI-compatible
model server. Details: [deploy/README.md](deploy/README.md).

## Documentation

| Document | Content |
|---|---|
| [HANDBUCH.en.md](HANDBUCH.en.md) | Handbook for users and admins |
| [REFERENCE.en.md](REFERENCE.en.md) | Overview of architecture, features, operation and security |
| [REFERENZ.md](REFERENZ.md) | Complete technical reference (German) |
| [deploy/README.md](deploy/README.md) | Installer |
| [k8s/enterprise/README.md](k8s/enterprise/README.md) | Kubernetes manifests |
| [deploy/demo-erp/README.md](deploy/demo-erp/README.md) | Sample database for demonstrations |
| [.env.example](.env.example) | All settings |

## Tests

```bash
python selbsttest.py
python test_api.py
```

## Former edition

The former edition (images `schlank` and `voll`) is on branch
[`legacy`](https://github.com/mw-research/LocaNoto/tree/legacy) and is no
longer developed.

## Project

Developed within the project **DIG:IT-KMU** at the Institute for Digital
Engineering (IDEE) of the Technical University of Applied Sciences
Würzburg-Schweinfurt (THWS). Funded under EFRE Bavaria 2021–2027 by the
Bavarian State Ministry of Economic Affairs, Regional Development and Energy,
co-financed by the European Union. https://digit.kmu.bayern

## Licence

[GNU Affero General Public License v3](LICENSE). Licences of the packages
used: [LIZENZEN.md](LIZENZEN.md).

Copyright © 2026 Markus Wilhelm (mw-research)
