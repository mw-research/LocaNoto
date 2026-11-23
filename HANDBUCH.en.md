# LocaNoto – Handbook

LocaNoto answers questions from an organization's own records: from
uploaded documents and, if desired, also from lists (Excel, CSV), a
specialist database and connected mailboxes. Everything runs on your own
servers.

Part 1 is **for users**, Part 2 **for admins**. Each section answers one
question and can be understood on its own. The technical reference is in
`REFERENZ.md` (German; overview in `REFERENCE.en.md`).

## Part 1: Using LocaNoto (for users)

Signing in, asking questions, reading sources, uploading documents, chats,
workspaces, presets, lists, the database, mailboxes, your password and
access tokens in LocaNoto.

### What is LocaNoto and where do its answers come from?

Ask a question → LocaNoto picks the matching passages from your documents
(by meaning and by keywords), and a language model writes the answer from
them. Below every answer are the sources with file and page.

Only the workspaces you are allowed to see are searched. If something is
not in the collection, the answer says so.

The bar at the top has these pages:

- **Chat** – ask questions; your chats are listed on the left
- **Documents** – upload, move, delete
- **Web sources** – searches on the internet, taking over hits
- **Tickets** – only if you are a member of a ticket system
- **Settings** – language, instruction, presets, password, mailboxes,
  databases, lists, API tokens
- **Admin** – admins only

To the right are your name and **Sign out**.

### How do I sign in to and out of LocaNoto?

- Sign in: enter **Name** and **Password** → **Sign in**. An admin
  creates your account. If a company directory is connected, **Sign in
  with the company account** works too.
- Sign out: **Sign out** at the top right.
- No input for a longer time (default: 480 minutes) → the session ends by
  itself; sign in again.
- Page does not respond after an update → reload the page and sign in
  again.

### How do I switch LocaNoto to English?

**Settings** → **Language** → choose Deutsch or English → **Save**. The
choice takes effect immediately and is remembered for your account.

You can ask in any language: LocaNoto answers in the language of the
question, even if the documents are German. File names, values and
quotations stay as they are in the document.

### How do I ask LocaNoto a question?

- Page **Chat**: type the question into the input field at the bottom
  (**Ask a question about your documents ...**) → **Send**.
- Attach an image (png, jpg, webp, gif, bmp) with the file field next to
  **Send** → LocaNoto describes it and takes it into account.
- Follow-up question in the same chat → refers to the conversation so far.

Below the input field, **Workspaces · Model** opens the options of the
question: workspaces, model, preset and, if set up, lists, web search,
database and "internal only".

If an answer ends with "The answer broke off.", ask again with **Ask
again**.

### How can I see in LocaNoto where an answer comes from?

Below every answer is **Sources (n)**. Expand it → one entry **file · page
n** per source passage, with the text passage the answer is based on.

- **↗** (Open in a new tab) → shows the passage on a page of its own.
- Click a reference in the answer text → opens the corresponding passage
  in a tab of its own as well.
- For PDFs, **Show page** → shows the page in the original, e.g. for
  tables or drawings.
- For Word and Markdown, the passage number appears instead of the page.

**Further passages found** shows passages the search found but the answer
does not cite.

### Why doesn't LocaNoto find something?

- **The document is in a workspace you cannot see** → LocaNoto only
  searches your workspaces.
- **Workspaces are narrowed down** → under **Workspaces · Model**, clear
  all ticks at the workspaces.
- **The document uses a different word** (you ask about "BANF", it says
  "Bestellanforderung") → an admin adds it to the glossary. Questions
  without results are logged automatically for this.
- **Scan without readable text** → a message appears when uploading; see
  "How do I upload a scan in LocaNoto?".

More source passages per answer: choose a **Preset** that retrieves more
passages.

### How do I narrow down the search in LocaNoto?

In the **Chat**, open **Workspaces · Model** below the input field:

- **Workspaces:** tick single ones → search only there. No tick → all
  your workspaces.
- **Preset:** among other things, sets how many source passages go into
  an answer. More helps with extensive sets of rules, but makes the answer
  slower.
- **List areas:** with lists in several subfolders, tick single ones →
  only these lists are queried.

The choice applies to the next question.

### What are workspaces in LocaNoto and who sees my documents?

The workspace determines who can find a document.

| Workspace | visible to | upload and delete |
|---|---|---|
| General | all users | admins only |
| named workspace (department, project, customer) | its members | its members |
| your personal workspace | only you | you and admins |

Every user has a personal workspace from the start. What is stored there
never flows into other people's answers. Which workspaces you see is shown
on the page **Documents**: one section per workspace with its files.

### How do I upload a document in LocaNoto?

Page **Documents**, at the top:

1. Choose files – PDF, Word (docx), Markdown, text or scan (TIFF, JPG,
   PNG); several files at once are possible.
2. **into** – choose the workspace. The default is your personal
   workspace → nothing is shared by accident.
3. Optionally enter **Project (optional)** → the file goes into this
   folder of your personal workspace.
4. Only tick **Describe images** if diagrams matter → one model call per
   image. Scanned pages are read by OCR even without the tick.
5. **Upload** → LocaNoto reports for each file how many passages are
   searchable.

The files go up one after the other; keep the page open until the end.

### How do I upload a scan in LocaNoto?

Like any document. Pages without a text layer (scanned PDF, TIFF, JPG,
PNG) are read automatically by OCR (German, English).

- Page not readable → the message after the upload names the page
  numbers.
- Upload again with **Describe images** → the vision model reads these
  pages; it reads poor scans and handwriting better, one model call per
  page.

Under **Sources**, such passages carry the mark `ocr` (OCR) or
`sehmodell` (vision model). Check numbers from them (test values,
dimensions, deadlines) against the original page: OCR can confuse digits,
and the vision model can plausibly fill in illegible spots.

### How do I move or delete a document in LocaNoto?

Page **Documents** → one section per workspace with its files. Next to
each file:

1. **Move to** – choose the target workspace → **Move**, e.g. to share
   something from your personal workspace with a department.
2. Or **Delete** → confirm → the file and its passages disappear from the
   search.

With ownCloud: deleted files go to the trash there, moved files to the
folder of the new workspace. If that fails, the message says so –
otherwise the file would come back with the next sync.

No buttons next to the files → you may only read in this workspace.

### How do I work with chats in LocaNoto?

Page **Chat**, on the left:

- **+ New chat** → new conversation without history.
- Click a chat in the list → opens an older conversation.

Above the open chat:

- **Rename** → enter a new title.
- **Delete** → removes the conversation after a confirmation.

After the first question, each chat automatically gets a short title (at
most about six words). Chats are saved automatically, visible only to you
and stored encrypted on the server, including titles and images.

New topic → new chat, because LocaNoto takes the chat history into
account in its answer.

While an answer is being written you may switch pages or chats: LocaNoto
keeps writing it. Back in the chat it shows "The answer is being written
..." with the text so far until it is done. If an answer breaks off (e.g.
the model server fails), the reason and **Ask again** appear below it.

### What do "Helpful" and "Not helpful" do in LocaNoto?

Below every answer are **Helpful** and **Not helpful**.

- Click → the feedback goes to the admins together with the question. It
  shows them where documents or glossary entries are missing.
- Questions without results are logged even without a click.
- If a result came from a personal workspace, the feedback shows only a
  placeholder instead of the file name.

### What is a preset in LocaNoto?

A preset bundles model, number of source passages and list areas for one
purpose. Choose it in the **Chat** under **Workspaces · Model** →
**Preset**; **none** uses the basic settings. Own presets are marked
"(eigene)" (own).

Your own: **Settings** → **Presets** → **New preset** → label,
description, **Model**, **Passages** (1 to 30) and **List areas** →
**Save**. **Default** takes the basic setting. Open an own preset → change
it or **Delete**. **Shared presets** are created by admins; only those can
have their own prompts.

**Model:** in the **Chat** under **Workspaces · Model** → **Model** you
choose the language model from the list the admins allow. **Default**
takes the model of the preset, otherwise the basic model.

### How do I query lists from Excel or CSV in LocaNoto?

Lists (xlsx, csv) are read fresh with every question → new rows take
effect immediately. If lists are set up for you, LocaNoto includes them in
every question: it picks the matching list and reads the matching rows.
In the **Chat** under **Workspaces · Model**: untick **Lists** → no lists;
**List areas** → only these subfolders; **Include large lists** → very
large sheets too (slower).

Below the answer, **Lists (n)** shows which sheet returned how many rows
with which query.

Which sheets you can query: **Settings** → **My lists** → **Your sheets**
and **Lists of your workspaces**. A preset can limit the lists to certain
list areas (subfolders).

### How do I query the database in LocaNoto?

If a database is set up for one of your workspaces, the chat shows
**Database** under **Workspaces · Model** (with several, also **Database
of**).

- **Database** ticked → LocaNoto writes a read-only query (SELECT) for
  your question and uses the result. LocaNoto cannot change anything in
  the database. The browser remembers the tick.
- Below the answer, **Database query (n rows)** shows the query.
- "No database connection: …" → names the reason (server not reachable,
  login refused, …); the answer then comes from the documents only.

**Documents from the database:** "Show me invoice 2025103", "the data sheet
of the ball valve". If the document lies in the database or in a released
folder, it is listed under the answer under **Documents from the database**;
PDFs and images open in the browser. Asking about the content works too:
"What is on invoice 2025103?"

**Own SQL login:** **Settings** → **My databases** → the **User** and
**Password** your database admin gave you → **Connect**. Queries then run
with your rights in the database. The login stays only in the browser
session. If the admin stored a shared account, it also works without one.

### How do I work with my own lists in LocaNoto?

**Settings** → **My lists** shows **Your folder**, e.g.
`/mnt/listen/LISTE/anna`: the admin sets a root, everybody gets a folder
named after their user name in it. Excel and CSV files there are read at
every question that uses lists; only you see them.

- **Subfolder (optional)** → **Save** → only this part of your folder
  counts.
- **Read lists again** → after new files or changed columns; new rows
  work without it.
- **Your sheets** → the sheets found, with their number of rows.

### How do I connect my mailbox to LocaNoto?

**Settings** → **Mailboxes and data connectors** → enter email address
and password for each mailbox → **Connect**. LocaNoto checks the login
immediately.

If the section is missing, an admin has not set up a mailbox yet.

After that, LocaNoto can include emails, for example:

- "What did Ms Meier write most recently?"
- "Summarize the emails from the last 24 hours."
- "Reply to Mr Braun that the appointment works."

The login details are kept only in your current session and disappear
when you sign out → connect again afterwards. **Disconnect** ends the
connection earlier.

You open shared mailboxes (such as info@) with your own credentials;
Exchange decides about access.

### What happens when LocaNoto wants to send an email?

From a personal mailbox, LocaNoto **never sends on its own**. If the
answer wants to send an email, **Draft waiting for you** appears below it
with recipient, subject and text.

- **Send draft** → sends the draft exactly as it appears there.
- **Discard** → sends nothing.

If sending goes wrong, the draft says why:

- **Not sent: …** → nothing went out; **Send draft** tries again.
- **The server did not answer** → look into the *Sent* folder (or the
  calendar) before trying again.

If the server answers too late but the mail is in *Sent*, it counts as
sent. LocaNoto knows what happened to a draft at the next question in the
same chat, and which mails and appointments it read before.

Only for a shared mailbox can an admin enable autonomous replies; such
emails usually carry a note that they were created automatically.

### How do I add appointments with LocaNoto?

With an Exchange mailbox connected, for example: "What is in my calendar
tomorrow?", "Block Tuesday 2 pm for an hour of focus time", "Invite
huber@firma.de to the site meeting on Friday at 10".

Entries and invitations are drafts like mails: the draft names weekday,
date and time → check → **Add to calendar** or **Send invitation**.
LocaNoto knows today's date and the weekdays of the surrounding weeks;
times are in the installation's time zone (default Europe/Berlin).

Existing appointments can be changed and cancelled the same way: "Invite
meier@firma.de as well", "Move the site meeting to 2 pm", "Merge the two
appointments on 11 November", "Cancel the jour fixe". The draft names what
changes and who gets a message → **Save change** or **Cancel appointment**.
New attendees get an invitation; a new time sends an update to everyone.
Only the organizer can change an appointment; for someone else's, the
cancellation goes to the organizer.

Answering invitations: "Which invitations are still open?" (marked
"Antwort offen" in the calendar), "Accept the project meeting on Thursday",
"Accept tentatively". Draft → **Accept**, **Accept tentatively** or
**Decline**; the answer goes to the organizer.

### What else can LocaNoto do with my mailbox?

| Question, for example | Exchange | IMAP (Gmail, GMX …) | Confirmation |
|---|---|---|---|
| "What is Vladyslav Borysenko's mail address?" – the organisation's address book and own contacts | yes | – | no |
| "Invite Vlad and Rodolfo" – names instead of addresses; LocaNoto looks them up, asks back on several matches | yes | – | – |
| "When do Borysenko and I have an hour next week?" – free/busy | yes | – | no |
| "What is in the attachment of Meier's mail?" – attachments, text of PDF, Word, text | yes | yes | no |
| "Mark the mail as unread" | yes | yes | no |
| "Forward the mail to Rodolfo" – with attachments | yes | yes | yes |
| "Move the mail to the archive / the trash / to Projects" | yes | yes | yes |
| "Is my out-of-office on?" / "Set it for next week" | yes | – | setting: yes |

The trash is the folder "Deleted Items": a mail can be restored from
there. LocaNoto deletes nothing for good.

### How does LocaNoto notify me of new mail?

With a mailbox connected and LocaNoto open in a browser tab, LocaNoto
checks for new mail every few minutes. New mail → a notice with sender and
subject → **Show** opens the chat with a question about the new messages
in the input field.

**Settings** → **Mailboxes and data connectors** → **Notify me about new
mail** switches this per mailbox. With no LocaNoto tab open nothing is
checked: the login lives only in the browser session.

### How do I work with tickets in LocaNoto?

If an admin switched on the ticket system for a shared mailbox and made
you a member, there is a page **Tickets** at the top.

- Every new mail to the mailbox becomes a ticket (e.g. T-2026-0001). The
  sender gets the standard answer with the number at once; you get a
  notice. The number at **Tickets** counts open tickets nobody took.
- At the top, choose the mailbox, then **open + in_progress**, **closed**
  or **all statuses**.
- Open a ticket → **Take it** (you are responsible) or **Release**, choose
  the **Status** → **Save**, **Note** → **Add note**.
- **Answer in the chat** → a chat with the ticket as the question; the
  answer goes out as a draft through your connected mailbox.
- If the customer replies with the number in the subject, the mail goes
  to the same ticket and reopens it; the person responsible is notified.

### How do I search the internet with LocaNoto?

In the **Chat** under **Workspaces · Model**, tick **Web search** →
LocaNoto searches the web when your documents do not answer the question.
Only the search term goes out, no documents.

- Personal workspace → always works.
- Shared workspace → an admin has to allow web search there first.
  Otherwise the answer shows "Not searched with web search (not allowed
  there)" with the workspaces.
- **Allgemein** (General) is blocked by default. A question with web
  search over all workspaces leaves it out.

Results appear below the answer as **From the web** with [W1], [W2] …,
separate from the documents. Taking them over into your own workspace
goes through the page **Web sources**.

Without web search ticked, LocaNoto can **propose** a web search, e.g.
when the documents give nothing or the question asks for something
current. Below the answer: **Web search proposed** with the exact search
text → **Search in the web** → the answer continues in the same chat with
the hits. **Discard** → nothing goes out.

### How do I collect sources from the internet with LocaNoto?

1. Page **Web sources** → keywords into the search field → **Search**.
   Or type keywords into the chat box → **Search in the web** → confirm
   the text shown.
   The search term goes to search engines: no internal names or figures.
2. The search runs in the background; you may leave the page. When the
   results are there (up to 25), a notice with **Show** appears and
   **Web sources** at the top shows a count.
3. **Show** → the results. Optionally **Read** → the page as plain text,
   without images and scripts. **↗** opens the page in your browser.
4. Tick results (or **Select all**) → **Take over selected into my
   workspace**. This runs in the background too; a notice says how many
   pages were stored.

Searches stay under **My searches** until you delete them. Imported items
always land **in your personal workspace**, folder *Suchergebnisse*, with
source and retrieval date. If something belongs in a shared workspace →
move it there.

### How do I tell LocaNoto how it should answer me?

**Settings** → **Personal instruction** → enter text, e.g. "Answer
briefly, with tables, and always name the standard." → **Save**.

- Applies from the next question to all your answers, including via the
  API.
- Empty the field → **Save** → takes it out again.
- At most 2000 characters; stored encrypted, others do not see it.

The instruction only refines. The basic rules (cite sources, invent
nothing) are set by the admins in the prompts; they take precedence.

### How do I change my password in LocaNoto?

**Settings** → **Change password** → **Current password**, **New
password** (min. 8 characters) → **Save**. With sign-in through the
company directory, there is only a note; the password changes in the
directory then.

With ownCloud:

- LocaNoto manages your ownCloud account → the new password applies there
  too.
- No account there yet → it is created, with this password.
- The account belongs to someone else → the message says the old password
  still applies there.

Forgot your password → an admin sets a new one; change it yourself right
afterwards.

### What are my access tokens in LocaNoto?

An access token lets programs and scripts query LocaNoto through the HTTP
API or submit documents – with your permissions. An admin creates it; its
value is shown exactly once.

**Settings** → **API tokens** → shows all tokens issued to you with ID,
label and date. **Revoke** → blocks a token immediately. Revoke tokens
you do not need. Without tokens in your name the section is missing.

### What do admins see of my work in LocaNoto?

- **Chats:** nothing in the application; they are stored encrypted.
- **Personal workspace:** admins see file names, never the content, and
  can delete files. In strict mode they do not even see the file names.
  They reach the content only through emergency access, which a second
  person must confirm; both names are recorded in the log.
- **Feedback:** questions with **Helpful**/**Not helpful** and questions
  without results verbatim, with your user ID.
- **Mailbox logins:** nobody; they are not saved.

Anyone with access to the server itself can technically see more; an
encrypted disk and a small circle with server access protect against that.

## Part 2: Administering LocaNoto (for admins)

Users, roles, workspaces, the shared collection, lists, access tokens and
the API, mailboxes, emergency access, feedback, glossary, prompts,
presets, ownCloud, backup and troubleshooting.

### Where do I find the Admin area in LocaNoto as an admin?

Admins see the page **Admin** at the top. Its bar leads to:

- **Users · Workspaces · Jobs** – create users, roles, workspaces, jobs
  such as **Bilder nachtragen**; above them a line on the security status
- **Backups** – back up and restore the vector database
- **Emergency access** – access to personal workspaces
- **Prompts and glossary**
- **Feedback** – questions without an answer, unhelpful answers
- **Storage** – ownCloud/OpenCloud
- **Mailboxes** – mailboxes, data connectors, web search, ticket systems
- **Lists** – list folders and catalog
- **Databases** – SQL databases per workspace
- **External model** – which sources may be answered externally
- **API** – description of the HTTP API at `/api/v1/docs`

What has no page of its own (setting a user's password, deleting other
users' personal documents) goes through the API; **API** shows the calls.

### How do I become an admin in LocaNoto?

- An existing admin: **Admin** → **Users** → search the user → choose
  role `admin` → **Save**.
- New installation: the very first account is created by `scripts/create_user.py`
  in the terminal; it becomes admin. After that, the script requires the
  login of an existing admin.

Nobody can demote or delete the last admin.

### How do I create a user in LocaNoto as an admin?

**Admin** → **Users**, below the list:

1. **Name** – letters, digits, dot, hyphen, underscore.
2. **Password** – at least 8 characters.
3. Role – usually `nutzer`.
4. **Create**.

→ The personal workspace is created immediately; with ownCloud, also the
account and personal folder there.

IDs that differ only by a special character ("m.meier", "m_meier") are
rejected by LocaNoto: they would result in the same personal workspace.

### How do I change or delete a user in LocaNoto as an admin?

**Admin** → **Users** → **Search users** (from 20 users on, the list shows
hits only after a search). In the user's row:

- Choose the role → **Save**.
- **Workspaces** → search and add their workspaces → **Save**.
- **Delete** → confirm. Their tokens and their instruction go with it, as
  does a managed ownCloud account. Chat history and personal workspace
  remain; as long as any of it is there, no new account of the same name
  can be created -- it would take over the chats and the workspace. On
  the server, `python accounts.py purge <name>` removes both.

**Setting a password** goes through the API or, on the server, with
`python scripts/manage_users.py`. Through the API, an account with chats
or documents in its personal workspace needs a confirmed emergency access
to it -- with the new password they would otherwise be open to you. For
managed accounts it also applies in ownCloud.

Every change is recorded in the chained user log. "User file was changed
outside LocaNoto" → a signature does not match: existing users keep
working, an account entered by hand is locked.

### Which roles are there in LocaNoto?

| Role | may |
|---|---|
| `nutzer` | ask questions, upload to their own and enabled workspaces |
| `admin` | additionally manage users, workspaces, the shared collection and all settings |
| `notzugang` | only confirm or reject an admin's emergency access to a personal workspace |

The role `notzugang` belongs to someone who is **not** an admin, e.g.
management or the staff council. If admins could confirm each other,
emergency access would be a mere formality. It is not assigned on the
page **Users** but through the company directory or, on the server, with
`python scripts/manage_users.py`.

### How do I create a workspace in LocaNoto as an admin?

**Admin** → **Workspaces** → **New workspace**: ID (lower-case letters,
digits, `_`, `-`), **Label**, **Members** → **Create**.

Find an existing workspace with **Search workspaces** → **Edit** →
editable there:

- **Label**, **Description**,
- **Visible to everybody (no member list)**,
- **Members** – as chips (× removes one); someone is added with **Search
  user and add ...**: type a part of the name, click the suggestion,
- **Group from the directory or the file store (optional)** → its members
  are added,
- **Web search allowed**,

→ **Save**. **Remove workspace** → takes it off the list, the documents
stay in the collection.

List folders are entered under **Admin** → **Lists**, databases under
**Admin** → **Databases**. Personal workspaces are not in the list; they
have exactly one reader.

### How do I fill the shared collection in LocaNoto as an admin?

Only admins write to **General**. Three ways:

- **Interface:** **Documents** → choose "Allgemein" (General) at **into**
  → **Upload**.
- **Terminal:** put files in the document folder → `python ingest.py`.
  `INGEST_RAUM=einkauf python ingest.py` ingests into a different
  workspace.
- **API:** `POST /aufnehmen` with an admin's token, one file per call.

Scanned pages are read by OCR on all three ways; what it cannot read is
named by `ingest.py` in its output.

**Admin** → **Jobs**:

- **Bilder nachtragen** (catch up images) → **Start** → describes figures
  in the whole collection.
- **Dokumente neu einlesen** (re-ingest documents) → **Start** → ingests
  the document folder completely.

Both keep running when you leave the page, and skip what has already been
processed.

### How do I set up lists (Excel, CSV) in LocaNoto as an admin?

Lists are not vectorized: a catalog knows sheets and columns, and LocaNoto
reads the rows fresh with every question. **Admin** → **Lists**:

- **List folders per workspace**: one folder per shared workspace →
  **Save**; the workspace determines who sees the lists. Allowed are
  folders under the **Allowed roots** (`LISTEN_WURZELN`); empty removes
  the folder.
- **Root of the personal folders**, e.g. `/mnt/listen/LISTE` → every user
  gets `/mnt/listen/LISTE/<user name>` and sees it under **Settings** →
  **My lists**. `owncloud:/LISTE` works as well.
- Shares on several servers: in the installer `"lists_pvc": {"name":
  "claim", …}`, mounted at `/mnt/listen/<name>`.
- **Sheets in the catalog** → **Read lists again**: needed for new files
  or changed columns; new rows take effect without any action. Very large
  sheets are marked "large".
- **Not readable** → files with errors.

- **Upload lists** → choose files (xlsx, xlsm, csv, tsv), the workspace
  and optionally an area (subfolder) → **Upload**. They go into the list
  folder of the workspace; only writable folders are offered. A file of
  the same name is replaced.
- **Header row** per sheet: the row with the column names, counted as in
  the spreadsheet → **Save**. Empty → LocaNoto finds it itself.

### How do I create an access token for LocaNoto as an admin?

On the server:

```
python scripts/create_token.py <user> --bezeichnung "Bulk ingest purchasing" --tage 90
```

The script requires an admin's login. Without `--tage` the token does not
expire. The value appears **exactly once**; only its hash is stored.
`--liste` shows all tokens, `--widerrufe <id>` revokes one.

An admin can also create a token for their own account through the API
(`POST /api/v1/admin/tokens`). Users see and revoke their own under
**Settings** → **API tokens**.

The token only identifies the user; their permissions are in the user
file. Only an admin's token can submit to **General**.

### How do I use the HTTP API of LocaNoto?

Every call carries the token in the header `X-LocaNoto-Token`.

| Call | Purpose |
|---|---|
| `GET /gesundheit` | sign of life, without token |
| `GET /status` | models, collection, lists, presets |
| `GET /raeume`, `GET /dokumente` | what this user may see |
| `POST /frage` | answer with sources, `?strom=1` streaming |
| `POST /aufnehmen` | submit a document (form: `datei`, `raum`, optional `projekt`, `bilder`, `sehmodell`) |
| `POST /rueckmeldung` | Helpful/Not helpful for an answer |
| `DELETE /dokumente?raum=…&datei=…` | delete a document, like **Delete** in the interface |
| `GET /hilfe` | self-description |

Searches only cover the token owner's workspaces; deleting and submitting
only where they could also do so in the interface (otherwise `403`). File
too large → `413`. The API is only reachable from the server itself; from
outside, a reverse proxy with TLS belongs in front of it. Examples:
`REFERENZ.md`, "HTTP-Schnittstelle".

### How do I set up a mailbox in LocaNoto as an admin?

Personal mailboxes need **one entry for everyone**; every user opens their
own mailbox in it. Each shared mailbox gets its own entry.

**Admin** → **Mailboxes** → **Create**:

1. **Name:** `postfach` for the common entry, `info` for info@, etc.
2. **Kind:** "Exchange/Outlook — direkt, ohne weiteren Server" or
   "IMAP/SMTP — Gmail, GMX, web.de, eigener Mailserver".
3. **Address, command, Exchange server or IMAP server:** e.g.
   `owa.firma.de`; for Exchange, empty → found automatically.
4. Leave **personal (everyone signs in with their own account)** ticked –
   or untick it for a shared mailbox and enter the **Address of a shared
   mailbox** (`info@firma.de`).
5. **Create**.

After that, every user connects themselves under **Settings** →
**Mailboxes and data connectors**; there is no shared password.

Other tool servers (MCP) → kind "MCP-Server über HTTP". The kind "lokaler
Prozess (stdio)" (local process) only appears where the operator has
allowed it with `MCP_STDIO=1`: it starts a command on the server.

### How do I connect Exchange Online (Microsoft Graph) or another server with sign-in at a provider to LocaNoto?

Newer tool servers -- an MCP server for Exchange Online through Microsoft
Graph, for example -- sign in every user at the provider (OAuth 2.1, the
sign-in standard of MCP). LocaNoto can do that:

1. **Admin** → **Mailboxes** → **Create** → kind "MCP-Server mit
   Anmeldung beim Anbieter (OAuth)", the server's address (usually ending
   in `/mcp`). For a shared mailbox enter its address -- the model gives
   it where a tool asks for a mailbox.
2. Users go to **Settings** → **Connect with your account**, sign in at
   the provider and come back.

Where to sign in, LocaNoto reads from the server itself; it registers
there as an application by itself. Where the provider does not allow
that, an admin enters a client id through the API (`oauth_client_id`).
The sign-in lives only in the browser session and is renewed by itself;
no token is kept on the server. The user's own rights at the provider
apply.

Tools that change something (send, delete, move, create appointments)
are never run by LocaNoto on its own: they appear as a draft. Where the
server says nothing, a tool counts as reading only when its name says so
(`list_…`, `get_…`, `search_…`).

### Who sees a mailbox in LocaNoto?

Without an assignment every user sees every entry and can sign in to it.
**Admin** → **Mailboxes**: each entry shows **Visible to** and a selection
→ **Assign**:

- Personal entry → a user. Only that user sees the entry. **everyone (own
  login)**: one entry for everyone, each with their own login.
- Shared mailbox → a **workspace**. Only its members see the mailbox,
  connect it and get its tickets -- an admin too only as a member. The
  member list of the ticket system does not apply then; the members of
  the workspace do.

The same assignment can be made at **Create**. For everyone else the
mailbox does not exist: not in the settings, not in the chat, not among
the tickets. **Delete** removes an entry.

### When does an external model answer in LocaNoto?

Only when the operator has set one up (`EXTERN_BASE_URL`,
`EXTERN_API_KEY`, `EXTERN_MODEL`; Azure OpenAI also `EXTERN_API_VERSION`)
and the admin has released the sources of an answer for it. Otherwise the
internal model always answers.

**Admin** → **External model**: one tick **External allowed** per source
-- each workspace, personal workspaces, database, lists, web search, each
mailbox and each data connector, and "Chat without any source". Nothing
is ticked out of the box. **Save** applies it.

Everything before the answer -- search terms, database query, tools --
runs on the internal model. Only the answer itself can go out, and only
when every one of its sources is released. It also stays internal when:

- a previous answer in the same chat was internal,
- an image is in the chat,
- the question starts with `/intern`, "internal only" is ticked in the
  chat, or a keyword occurs (out of the box: intern, vertraulich, geheim
  and their English counterparts; adjustable on the same page).

Glossary and personal instruction go along only when released. Below each
answer it says which model answered and why. If the external model does
not answer, the internal one writes the answer; never the other way round.

### How do I connect an ERP, an MES or a database to LocaNoto?

Through a **data connector**: a small service of its own that knows
exactly one system and offers LocaNoto tools to ask it. LocaNoto does not
know the system, only the interface. For SQL databases (PostgreSQL,
MySQL/MariaDB, Microsoft SQL Server, Oracle, SQLite) a finished connector
is included; for any other system you build one to the same interface.
Description and example: `connectors/README.md`.

1. Start the connector next to LocaNoto (container or pod).
2. **Admin** → **Mailboxes** → **Create** → kind "Datenanschluss (ERP,
   MES, Datenbank) über HTTP", address `http://<name>:8000/mcp`. With a
   login per user: kind "Datenanschluss, jeder meldet sich mit seinem
   Konto des Systems an"; users then connect under **Settings**.
3. Assign it to a **workspace** → only its members see the connector and
   can ask it.

In the chat the model asks the connector by itself when the question fits.
Below the answer, **Data connectors** shows which connector returned how
many rows for which query. Tools that change something in the system are
never run by LocaNoto on its own: they appear as a draft and run only with
**Run**.

### How do I set up web search in LocaNoto as an admin?

1. Run the search service separately from LocaNoto (`REFERENZ.md`,
   "Websuche").
2. **Admin** → **Mailboxes** → **Create** → **Kind** "Websuche (eigener
   Dienst, websuche.py)", address `http://websuche:8000/mcp` → **Create**.
3. For each shared workspace: **Admin** → **Workspaces** → **Allow** (or
   **Block**) in its row, or **Edit** → **Web search allowed** → only then
   can users tick web search there.

Why the approval: the model writes the search term with passages of the
workspace in its context, and the search term goes to search engines. In
their personal workspace, every user decides for themselves.

### When may LocaNoto reply from a mailbox on its own?

Only from a **shared mailbox** for which **may answer on its own (no
confirmation)** was ticked when it was created. A personal mailbox
presents every email as a draft, without exception.

**Switched off for now:** a shared mailbox, too, presents every email as a
draft. An automatic run would otherwise see every workspace of the person
who starts it, and the sender of the answered email would get the reply
unseen. Once an automatic run uses only the mailbox's own workspace, the
following applies.

- Tick **add a notice under automatic answers** → every email sent on its
  own carries a note that it was created automatically. Wording:
  **Notice**.
- Without the tick → no note.
- A draft checked by the user and sent with **Send draft** never carries a
  note.

The list under **Mailboxes** shows for each entry "prepares drafts" or
"answers on its own" with or without notice.

### How do I set up a ticket system for a shared mailbox in LocaNoto as an admin?

**Admin** → **Mailboxes** → for each shared mailbox a section **Ticket
system**:

1. Tick **Ticket system on**.
2. **No login is stored.** Members connect the mailbox under **Settings**
   with their own account (rights on the mailbox in Exchange, "Send As"
   for the answers).
3. **Standard answer**: goes to every sender at once. `{ticket}`,
   `{subject}` and `{name}` are filled in.
4. **Members**: LocaNoto users who see every ticket and get a notice.
   Admins see all tickets.
5. Optional **Forward every new mail to** and **Ticket prefix**.
6. **Save** → **Check now** (with your own connected login). The first
   check only notes the time; from then on every new mail becomes a
   ticket.

It is checked every minute (`TICKET_POLL_SECONDS`) while a member with the
mailbox connected has LocaNoto open; **Last check** shows the result. With
nobody online, mail that came meanwhile is handled the next time, standard
answer included. Machine mail (out-of-office replies, newsletters,
bounces, mail of the mailbox itself) neither becomes a ticket nor gets an
answer. A mail is marked handled before anything is sent: it is never
answered twice.

### How does emergency access work in LocaNoto?

A personal workspace is closed even to admins. If someone leaves or is
absent for a longer time:

1. An admin: **Admin** → **Emergency access** → **Request access to a
   personal workspace** → choose the workspace, enter a **Reason** →
   **Request**.
2. A person with the role `notzugang` signs in and opens
   `/admin/emergency` → under **Requests**, **Confirm** or **Reject**.
3. Confirmed → access applies for 24 hours and expires by itself; under
   **Open grants**, **Close** ends it early.

Both names and the reason are recorded in the log. Without anyone holding
the role `notzugang`, there is no emergency access: the workspace can then
only be deleted, not read. The page says so at the top.

Only someone who set their own password can confirm. An account whose
password somebody else set -- when it was created or by a reset -- is
refused until that person changes it under **Settings**. Accounts from
the company directory are not affected.

### How do I evaluate feedback in LocaNoto as an admin?

**Admin** → **Feedback** shows the counts per kind at the top, below:

- **Questions without an answer** – usually a glossary entry or a
  document is missing.
- **Not helpful** – there were results, but the wrong ones.

**Download** → the complete list. **Archive** → files it under the
current date and starts a new one; nothing is deleted.

The list contains questions verbatim with user ID and is therefore stored
encrypted. If it says "lines are stored in the clear.", **Encrypt again**
converts older lines to the encrypted form.

### How do I maintain the glossary in LocaNoto as an admin?

The glossary translates users' words into the words of the documents.
**Admin** → **Prompts and glossary** → **Glossary**, one mapping per line,
`#` = comment:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Save** → takes effect from the next question. Comment lines are not
passed to the language model.

Only enter checked mappings: a wrong entry reliably steers the search to
the wrong place. Candidates come from the "Questions without an answer"
under **Feedback**.

### How do I adjust prompts and presets in LocaNoto as an admin?

**Prompts:** **Admin** → **Prompts and glossary** → choose a template →
**Open**. The templates are "Antwort" (how answers are written),
"Suchsonden" (search queries from the question) and, where set up,
"Listenabfrage" and "Datenbankabfrage".

- **Save** → takes effect from the next question; a text without the
  required placeholders is rejected.
- **Reset to the shipped template** → restores the supplied version.

**Shared presets** (at the bottom of the same page): **New preset** →
label, description, model, passages, list areas → **Save**; open one →
change it or **Delete**. Prompts of one preset: at the top, choose the
preset next to the template → **Open** → **Save**. "for all presets"
edits the general version.

The selectable models are set by `CHAT_MODELLE` in the `.env`; users see
the same list in the chat under **Model**. Users refine with their
**Personal instruction**.

After a prompt change, ask a few familiar questions and compare the
answers.

### How do I connect ownCloud to LocaNoto as an admin?

"ownCloud" means the file store, also OpenCloud. Configured in the `.env`
→ LocaNoto also stores uploaded documents there and imports folders and
groups. **Admin** → **Storage** shows whether the store is reachable and
the mapping workspace → folder:

- **Set up workspace folders and shares** → one folder per workspace,
  shared with its members.
- **Sync groups** → imports ownCloud groups as members.
- **Sync documents** → fetches new and changed files from ownCloud and
  ingests them (runs in the background).

Changing the folder of a workspace, bringing a single user's file store up
to date, reviewing planned changes and marking existing accounts as
managed go through the API (`/api/v1/admin/storage/…`).

Deleting and moving in LocaNoto also applies in ownCloud (deleted items →
trash). Deleting users and changing passwords only affect managed accounts
there. A missing account is created the next time a password is set.
Setup: `REFERENZ.md`, "Dokumente aus ownCloud".

### How do I change the embedding model in LocaNoto as an admin?

Only with Postgres (`DATABASE_URL`). The documents are not read again:
LocaNoto computes the vectors anew from the stored text.

1. In `.env`, set `EMBEDDING_NEXT_MODEL` to the new model, plus
   `EMBEDDING_NEXT_BASE_URL` and `EMBEDDING_NEXT_API_KEY` if it runs on
   another server. Optionally `REEMBED_HOURS=20-6` → works only at night.
   Restart the worker.
2. **Admin** → **Jobs** → **Vektoren neu berechnen** → **Start**. Search
   keeps using the old model meanwhile. An interrupted job continues where
   it stopped at the next **Start**.
3. When the job reports "Every passage has a vector of …": set
   `EMBEDDING_MODEL` to the new model, remove `EMBEDDING_NEXT_*`, roll
   out, and start **Vektoren neu berechnen** once more (it catches up on
   what was uploaded during the rollout).

The old vectors stay until a later change needs their place. Until then,
going back is only setting `EMBEDDING_MODEL` back. `python reembed.py
--status` shows the progress, `--drop-unused` removes the old vectors at
once.

Changing `EMBEDDING_MODEL` without these steps is refused (search reports
an error, `doctor.py` says why) – the stored vectors fit only the old
model. If only the name of the same model changed (e.g. a new tag on the
model server): `python reembed.py --adopt`.

### How do I back up LocaNoto as an admin?

Three things belong in the backup:

1. **Installation key** (`config/schluessel.key` or
   `LOCANOTO_SCHLUESSEL`). Without it, chats, attachments and feedback are
   permanently unreadable. Nothing can replace it.
2. **Configuration directory** (`config/`): users, workspaces, tokens,
   glossary, prompts, mailboxes.
3. **Vector database:** **Admin** → **Backups** → **Back up now**.
   Restore: at the snapshot, type its name to confirm, optionally tick
   **also users, chats, settings** → **Restore**. Without a snapshot, a
   loss would mean: ingest everything again. The text in a snapshot is
   encrypted with the installation key; it can only be restored with the
   same key.

The original documents are in the data directory and, if connected, in
ownCloud.

### Where do I see security status, storage locations, encryption and configuration of LocaNoto?

- **Security status:** **Admin** shows a line at the top – "alle Punkte
  erfuellt" (all points met) or which points are open.
- **Encryption of the feedback:** **Admin** → **Feedback** (see there).
- **Everything in detail** – the security checklist, what is encrypted,
  signed or stored in plain text, storage locations, `.env` settings that
  are missing, differ or are outdated (names only, no values):
  `GET /api/v1/admin/status` through the API.
- On the server, `python doctor.py` checks key, database, model
  endpoints, web search, file store and public address.

The connected language models and whether the endpoint for ranking the
results responds are shown by `GET /api/v1/models`.

### What do I do as an admin when something in LocaNoto does not work?

| Observation | Remedy |
|---|---|
| Page does not respond after an update | Reload the page, sign in again |
| Search hangs after the search queries | Model server unreachable or cold; the message names the reason |
| "Answer from the keyword search only" | Embedding endpoint unreachable; the message names the workspaces |
| "No database connection" | Check database or VPN; **Admin** → **Databases** → **Test connection** |
| Document ingested but not findable | `python scripts/room_diagnosis.py` in the container |
| User file "changed outside" | Signature does not match; accounts entered by hand are locked |
| Settings unclear | `python doctor.py`, `GET /api/v1/admin/status` |

After an update → `python tests/selftest.py` checks login, permissions,
search, encryption and backup without touching the collection.

## Part 3: This handbook in LocaNoto

How the handbook is ingested and kept up to date, so that LocaNoto can
answer questions about how to use it.

### How can LocaNoto answer questions about itself?

Every heading of this handbook is a question, and every section can be
understood on its own – so LocaNoto finds it like any other document.

- Ingesting: as an admin, upload `HANDBUCH.md` under **Documents** with
  "Allgemein" (General) at **into** → LocaNoto answers questions such as
  "How do I upload a document?" with a reference to the matching section.
- New version: under **Documents**, in the section **Allgemein**, remove
  the old version with **Delete**, then upload the new one. Simply
  overwriting would leave outdated passages behind.
