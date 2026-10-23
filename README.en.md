# LocaNoto

**Ask your own documents — and get the answer with file and page.**

LocaNoto is a self-hosted retrieval-augmented question answering system for
technical and business documents. Documents are split into passages,
embedded, and found through two search paths at once; a language model
writes the answer from what was found and cites the source passage.

At runtime the application talks only to the model servers you configure.
**Your documents never leave your network.**

*Deutsch: [README.md](README.md) is the complete reference. The user
interface, the [user and admin handbook](HANDBUCH.md) and the default
prompt templates are in German.*

| | |
|---|---|
| **Search** | vector search and keyword search (SQLite FTS5) combined, fused (RRF) and reranked |
| **Formats** | PDF, Word, Markdown, text, scanned pages (TIFF, JPG, PNG) — with tables and figures |
| **Lists** | `xlsx` and `csv` are not embedded but read fresh for every question |
| **Permissions** | rooms with members; every user has a personal room |
| **Confidentiality** | chat histories and attachments encrypted, user file signed entry by entry |
| **Integration** | OpenCloud (or oCIS, ownCloud, Nextcloud) for files and groups; Exchange mailboxes; MCP tool servers; optional web search; HTTP API with tokens |
| **Operations** | Docker Compose or Kubernetes; the container holds no state |
| **Licence** | AGPL-3.0 |

---

## How an answer is made

```
question ─► query rewriting ─► vector search ─┐
                              keyword search ─┼─► rank fusion ─► reranker ─► answer with sources
            lists / database (optional) ──────┘                     ▲
            tools: mailbox, web search (optional) ──────────────────┘
```

1. The question is rephrased into several search probes.
2. Each probe runs against the vector store (ChromaDB) **and** a keyword
   index. Exact part numbers and standards are found by keyword, paraphrases
   by meaning.
3. All rankings are fused (Reciprocal Rank Fusion) and the shortlist is
   rescored by a reranker — an endpoint, a model baked into the image, or
   none; none of them can stop the application from starting.
4. The model answers from the passages it was given and names file and page.
   Every citation in the answer is a link to the passage; a citation the
   model invented is not linked.

Only the rooms a user may read are ever searched. There is no filter that
could be forgotten: a foreign room's collection is simply not queried.

---

## Features

### Rooms and permissions

A **room** is a member list plus its own collection in the vector store. It
is the only boundary between users.

| Room | visible to | upload and delete |
|---|---|---|
| General | all users | administrators |
| a named room | its members | its members |
| a personal room | only its owner | the owner and administrators |

Administrators see documents in foreign rooms only in the admin area, and
only room and file name; they never flow into their searches or answers. A
**strict mode** hides even file names. Access to a personal room of someone
who is no longer reachable requires **two people**: an administrator
requests it with a reason, a holder of the `notzugang` role confirms it, and
it expires after 24 hours.

### Documents and scans

PDF, Word, Markdown and plain text are embedded with their tables. Scanned
pages are detected (little text, mostly image) and read by **Tesseract OCR**
(German and English by default). Pages OCR cannot read can be sent to a
vision model on request. OCR text is cleaned mechanically — never by a
language model, which would turn a misread standard number into a plausible
wrong one. Passages from scans are marked as such under the answer.

### Lists and databases

Spreadsheets (`xlsx`, `xlsm`, `csv`, `tsv`) are catalogued, not embedded:
the model first decides where an answer could be, then the list is queried
directly. A Microsoft SQL Server database can be connected with a
read-only account; the model writes a single `SELECT`, which is checked
before it runs, and query and result are shown with the answer.

### File store: OpenCloud, oCIS, ownCloud, Nextcloud

LocaNoto sits in front, the file store behind it. Creating a user or a room
in LocaNoto creates the account, folder and shares in the file store.
Deleting or moving a document does the same there (deleted files go to the
trash). A nightly sync fetches new and changed files and removes the
passages of deleted ones. Group membership in the file store can grant
access to a room.

OpenCloud and oCIS are managed through their Graph API with an app token;
ownCloud 10 and Nextcloud through OCS. LocaNoto detects which one it is
talking to. The bundled templates use **OpenCloud** (Apache-2.0).

### Mailboxes and tool servers (MCP)

Exchange mailboxes are connected directly (EWS). Any tool server speaking
the Model Context Protocol can be added. Tools that send something are never
executed by the model on its own: the user sees a draft and clicks *send*.
Credentials of personal mailboxes live only in the session memory.

### Web search

When documents are not enough, the model may look things up on the web —
**only if switched on**: per chat by the user, and for shared rooms only
after an administrator allowed it for that room. Only the search query
leaves the house, via a self-hosted SearXNG and without user identity. The
search service (`websuche.py`) runs in its own pod without any LocaNoto
secret or volume, checks every address and every redirect against private
networks, and streams pages with a size cap.

Results appear under the answer, separate from document sources. A
NotebookLM-style **source search** lets users collect sources without
asking a question: search a topic, **read** each page as plain text inside
LocaNoto, tick what to keep, and import it. Imported pages always go to the
user's **personal room**; they reach a shared room only by moving them
there.

Text from the web cannot load anything: titles and excerpts are escaped,
and every Markdown image in an answer is turned into a plain link.

### HTTP API

`api.py` (FastAPI) offers asking questions, uploading and deleting documents,
feedback and presets, authenticated with signed per-user tokens:

```bash
curl -H "X-LocaNoto-Token: lnt_..." http://127.0.0.1:8600/status
```

Endpoints: `GET /gesundheit`, `GET /status`, `GET /dokumente`,
`GET /raeume`, `POST /frage`, `POST /rueckmeldung`, `POST /aufnehmen`,
`DELETE /dokumente`, `GET /voreinstellungen`. The API applies the same room
permissions as the user interface.

### Learning from use

Questions that found nothing and thumbs-down answers are logged. From them,
administrators maintain a **glossary** of in-house terms (e.g. an
abbreviation and the term the documents actually use); it takes effect with
the next question. Administrators set the base prompt; every user can add a
personal instruction that is appended to it — the rules of the base prompt
take precedence.

---

## Quick start with Docker

Requirements: Docker with Compose and a reachable model server for **chat**
and **embedding** (Ollama, vLLM, or an OpenAI-compatible gateway). A vision
model and a rerank endpoint are optional.

```bash
git clone https://github.com/mw-research/LocaNoto.git
cd LocaNoto
cp .env.example .env
```

Five entries are required; everything else has defaults. `.env.example`
explains every value (in German).

```ini
OPENAI_BASE_URL=http://192.168.1.10:4000     # model server or gateway
OPENAI_API_KEY=your-key                      # anything for Ollama
CHAT_MODEL=qwen3.8:27b                       # answers
EMBEDDING_MODEL=qwen3-embedding:8b           # embeds
ADMIN_USERS=markus                           # first administrator, lower case
```

Start, optionally with the bundled OpenCloud:

```bash
docker compose --profile owncloud up -d
```

With OpenCloud, LocaNoto signs in with an **app token**, not the password:

```bash
docker compose exec opencloud opencloud auth-app create --user-name=admin --expiration=87600h
```

Put it into `.env` (`OWNCLOUD_URL=https://opencloud:9200`,
`OWNCLOUD_USER=admin`, `OWNCLOUD_PASSWORT=<token>`,
`OWNCLOUD_ADMIN_PASSWORT=<admin password>`, `OWNCLOUD_TLS_PRUEFEN=0` for the
bundled self-signed certificate), then:

```bash
docker compose up -d locanoto_bot
docker compose exec locanoto_bot python einrichten.py
```

`einrichten.py` waits for the file store, creates the installation key and
the first administrator in both systems, builds the folder tree with its
shares, and finally shows what is still open. It is safe to run again.
Without a file store: `python einrichten.py --ohne-owncloud`.

The UI runs on `http://localhost:8501`.

**Back up the installation key — the one thing nobody can recover:**

```bash
docker compose exec -T locanoto_bot cat /app/config/schluessel.key > ~/locanoto-key.key && chmod 600 ~/locanoto-key.key
```

Without it all chat histories are unreadable, without any error message.

Load documents by putting them into `data/dokumente/` (one folder per room)
and running `python ingest.py`, or upload them in the UI. Web search is a
separate profile: set `SEARXNG_SECRET` (`openssl rand -hex 32`), then
`docker compose --profile websuche up -d`.

## Kubernetes

Manifests are in [`k8s/`](k8s/README.md): storage, configuration, the
application pod (app, API and ChromaDB as a sidecar), schedules, OpenCloud
(`97-opencloud.yaml`) and web search (`98-websuche.yaml`, with
NetworkPolicies).

The data volume holds two SQLite databases and **needs block storage**
(local disk, Ceph RBD, iSCSI, cloud disks) — not NFS, SMB or CephFS. On a
network share SQLite silently falls back to another journal mode and the
index gets corrupted; the UI reports the actual mode under *Speicherorte*.
The application runs as **one replica**.

---

## Security model, honestly

| encrypted by LocaNoto | readable on disk |
|---|---|
| chat histories and titles | the original documents |
| images attached to chats | the keyword index (FTS5 needs plain text) |
| feedback log | file names in metadata |
| | the vectors |

The application can hide what it writes, not what it must be able to read.
**An encrypted disk is the foundation**, not an extra.
`python was_sieht_die_platte.py` walks the data directory without the
application and the key and reports what a finder could extract.

- Every entry in the user file and the token file is **signed**; an entry
  added by hand cannot sign in. User changes go into a **hash-chained log**.
- Sessions expire after inactivity (`SITZUNG_MINUTEN`, default 480).
- Whoever has file access to `config/` holds the key. The real boundary is
  who can reach the server — this is stated, not hidden.

## Operations

```bash
docker compose exec locanoto_bot python selbsttest.py    # self-test after every update
docker compose exec locanoto_bot python abgleich.py --pruefen   # what changed in the file store, touches nothing
python landkarte.py                                       # map of all modules and their dependencies
```

Each task can use its own model server (`CHAT_`, `EMBEDDING_`, `VISION_`,
`SQL_`, `TITLE_` prefixes, Azure OpenAI supported); the resolved mapping is
shown in the UI under *Modell-Endpunkte*. Changing the embedding model
requires re-ingesting everything.

## Project

LocaNoto was developed within the project **DIG:IT-KMU** at the Institute
for Digital Engineering (IDEE) of the Technical University of Applied
Sciences Würzburg-Schweinfurt (THWS). The project helps small and
medium-sized enterprises integrate new technologies safely and efficiently
into their processes. It is funded under EFRE Bavaria 2021–2027 by the
Bavarian State Ministry of Economic Affairs, Regional Development and
Energy, co-financed by the European Union. https://digit.kmu.bayern

Licence: [GNU Affero General Public License v3](LICENSE).
Third-party licences: [LIZENZEN.md](LIZENZEN.md).
Copyright © 2026 Markus Wilhelm (mw-research).
