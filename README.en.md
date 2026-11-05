<p align="center"><img src="web_static/logo.png" width="180" alt="LocaNoto"></p>

# LocaNoto

**Local AI knowledge base for companies** · *Lokale KI-Wissensbasis für Unternehmen*

*Deutsch: [README.md](README.md)* · Website: [mw-research.github.io/LocaNoto](https://mw-research.github.io/LocaNoto/en/)

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

Requirements: Python 3.8 or newer, Docker or `kubectl`, an OpenAI-compatible
model server. The installer creates keys and certificates, starts every
service, creates the first admin account and checks every part at the end.

**Docker (one machine)** – answer the questions, Enter takes the suggestion:

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
python3 locanoto-setup.py --en
```

**Kubernetes (no questions)**:

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
cat > answers.json <<'EOF'
{"target": "kubernetes", "host": "locanoto.example.com",
 "tls": "letsencrypt", "acme_email": "it@example.com",
 "model_url": "https://models.example.com/v1",
 "chat_model": "qwen3.8:27b", "embedding_model": "qwen3-embedding:8b",
 "features": {"websearch": true, "opencloud": false}}
EOF
export LOCANOTO_ADMIN_PASSWORD='...' LOCANOTO_MODEL_API_KEY='...'
python3 locanoto-setup.py --answers answers.json --yes --en
```

Then open `https://<host>`.

```bash
python3 locanoto-setup.py --check      # everything fine?
python3 locanoto-setup.py --upgrade    # new version, same answers
```

`~/.locanoto/secrets.json` holds the installation key – keep an offline
copy. Further answers (own certificate, OpenCloud, network drive for lists,
reranker, …): [deploy/README.md](deploy/README.md).

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
