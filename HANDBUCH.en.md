# LocaNoto – Handbook

LocaNoto is an assistant that answers questions from an organization's own
records: from uploaded documents and, if desired, also from lists (Excel,
CSV), a specialist database and connected mailboxes. Everything runs on
your own servers; the documents never leave the organization.

This handbook has two parts: **for users** and **for administrators**. Each
section answers one question and can be understood on its own. The
interface language can be switched between German and English in the
sidebar. The technical reference for setup and operation is in the
`README.md`.

## Part 1: Using LocaNoto (for users)

This part explains signing in, asking questions, reading sources, uploading
documents, chats, rooms, lists, the database, mailboxes, your password and
access tokens in LocaNoto.

### What is LocaNoto and where do its answers come from?

LocaNoto answers questions from the documents stored in your organization.
For each question, LocaNoto picks out the matching passages from the
documents – by meaning and by keywords at the same time – and a language
model writes the answer from them. Below every answer are the sources used,
with file and page.

LocaNoto only searches the rooms you are allowed to see. What is not in
the collection, LocaNoto cannot know; in that case the answer says so.

### How do I sign in to and out of LocaNoto?

Signing in: enter your **Username** and **Password**, then **Log in**. An
administrator creates your account.

Signing out: **🚪 Log out** in the sidebar. After a longer period without
input, the session ends by itself (default: 480 minutes); then sign in
again.

If the page stops responding after an update, the connection to the server
has been re-established: reload the page and sign in again.

### How do I switch LocaNoto to English?

In the sidebar, choose German or English under **🌐 Sprache / Language**;
it takes effect immediately and is remembered for your account. The login
page has the same switch. You can ask in any language: LocaNoto answers in
the language of the question, even if the documents are German. File
names, values and quotations stay as they are in the document.

### How do I ask LocaNoto a question?

Type the question into the input field at the bottom (**Question to the
database**) and send it. Images – such as a photo or a screenshot – can be
attached to the question (png, jpg, webp, gif, bmp); LocaNoto describes
them and takes them into account.

While an answer is being written, the sidebar is locked. A click there
would cancel the answer. If an answer ends with
"Cancelled – the answer is incomplete", ask the question
again.

Follow-up questions in the same chat refer to the conversation so far.

### How can I see in LocaNoto where an answer comes from?

Below every answer is **📚 Sources used**: one entry **📄 File (page n)**
per source passage. Expanded, it shows the text passage the answer is
based on. The references in the answer text are clickable and jump to the
corresponding source.

For PDF files, **👁️ Load original page n as image** loads the original
page, for example to see a table or drawing in the original. For Word and
Markdown files, the number of the passage appears instead of the
page.

**🛠️ Debug X-ray** shows which search queries were used and what the
language model got to see.

### Why doesn't LocaNoto find something?

The most common reasons:

- **The document is in a room you cannot see.** LocaNoto
  only searches your rooms.
- **A filter is set.** Under **🎯 Document filter**, clear room, project
  and "Restrict search to".
- **The document uses a different word.** If you ask about "BANF" and
  the document says "Bestellanforderung" (purchase requisition), the
  glossary maintained by an administrator helps. Questions without results
  are logged automatically for this purpose.
- **The document is a scan without a text layer.** Then it cannot be
  searched; a message about this appears when uploading.

The slider **Retrieve relevant passages** gets more results (default 5).

### How do I narrow down the search in LocaNoto?

In the sidebar under **🎯 Document filter**:

- **Room:** search only in certain rooms. Empty means: all your rooms.
- **Project:** only documents of one project from your personal room.
- **Restrict search to:** select individual documents. The list only shows
  documents that match the room and project above.

The slider **Retrieve relevant passages** determines how many source
passages go into an answer. More helps with extensive sets of rules, but
makes the answer slower.

### What are rooms in LocaNoto and who sees my documents?

A room determines who can find a document.

| Room | visible to | upload and delete |
|---|---|---|
| General | all users | administrators only |
| a named room (department, project, customer) | its members | its members |
| your personal room | only you | you and administrators |

Every user has a personal room from their first day. What is stored there
never flows into other people's answers. Which rooms you see is shown
under **Documents** in the sidebar.

### How do I upload a document in LocaNoto?

1. In the sidebar, **Upload documents** – PDF, Word (docx), Markdown,
   text, or a scan as TIFF, JPG or PNG. Several files at once are
   possible.
2. Choose the **Room**. The default is your personal room ("Visible only
   to you"), so nothing is shared by accident.
3. Optionally enter a **Project** (personal room only). It sorts documents
   and can be selected in the filter later.
4. Only tick **Describe figures and scanned pages** if diagrams matter: it
   costs one model call per image. Scanned pages are read by OCR even
   without this box ticked.
5. **Upload & vectorize**.

Afterwards, LocaNoto reports for each file how many passages are searchable.

### How do I upload a scan in LocaNoto?

Like any other document. Pages without a text layer – a scanned PDF or an
image as TIFF, JPG, PNG – are read automatically by OCR (German and
English).

If OCR cannot read a page, the message names the page numbers, and below it
**🔍 Read with vision model** appears. The vision model reads poor scans
and handwriting better, but needs one model call per page.

Below an answer, such source passages are marked **from OCR**
or **read by vision model**. Check numbers from them – test values,
dimensions, deadlines – against the original page: OCR can confuse digits,
and the vision model can plausibly fill in an illegible spot.

### How do I move or delete a document in LocaNoto?

Under **Documents** in the sidebar, each room has an expander with its
files. In rooms you are allowed to write to:

- **Manage document** – choose the file,
- **move to** and **Move** – to another room, for example to share
  something from your personal room with a department,
- **🗑️ Delete** – removes the file and its passages from the search.

If ownCloud is connected, both also happen there: deleted files end up in
the ownCloud trash, moved files in the folder of the new room. If that
fails, the message says so – the file would then come back with the
next sync.

If it says "Read only", you may not change anything in this room.

### How do I work with chats in LocaNoto?

Under **💬 Chats** in the sidebar:

- **➕ New chat** starts a new conversation without history.
- **Load previous chats** opens an earlier conversation.
- **🗑️ Delete current chat** removes the open conversation.

Chats are saved automatically and are visible only to you. They are stored
encrypted on the server, including titles and attached images.

A new topic belongs in a new chat: LocaNoto takes the history of a chat
into account in its answer.

### What do thumbs up and thumbs down do in LocaNoto?

Below every answer are 👍 ("Helpful") and 👎 ("Not
helpful"). The feedback goes to the administrators, together with the
question and the sources used. From it they see which questions the
collection answers well and where documents or glossary entries are missing.

Questions for which nothing was found are logged even without a click.
If a result came from a personal room, the feedback shows only
"(persoenlicher Raum)" instead of the file name.

### What is a preset in LocaNoto?

A preset bundles settings for one purpose: language model, number of source
passages, list areas and, if desired, custom wording. It can be selected at
the very top of the sidebar under **🎛️ Preset**; below it, it says what
the preset is meant for.

The selection only appears if an administrator has created presets.
**(Default)** uses the basic settings.

### How do I query lists from Excel or CSV in LocaNoto?

Lists (xlsx, csv) are not ingested like documents, but read fresh with
every question – new rows take effect immediately. Under **📊 Lists** in
the sidebar:

- **Also query lists** – LocaNoto picks the matching list and reads the
  matching rows. Below, it says how many sheets are available.
- **Area** – only lists from certain subfolders.
- **Include large lists** – very large sheets; a question then takes
  considerably longer.

Below the answer, **📊 List: …** shows which list was used with which
query. **Detected sheets** shows which sheets with which columns are
available; **Not readable** names files that could not be read. In
**📁 My list folder** you can enter your own folder whose lists only you
see.

### How do I query the database in LocaNoto?

If a specialist database is connected, the sidebar shows
**🗄️ Database**. With **Include database**, LocaNoto writes a read-only
query (SELECT) for your question and includes the result in the
answer. LocaNoto cannot change anything in the database.

Below the answer, **🗄️ Database query** shows the query that was run
and the account used.

In **🗄️ My database access** you enter your own database account.
Questions then run with your permissions, and LocaNoto only sees the
tables you are allowed to see. "No connection to the database" means: the
answers come only from the documents; **Reconnect** tries again.

### How do I connect my mailbox to LocaNoto?

In the sidebar under **📬 My mailboxes**, enter the email address and
password for each mailbox and click **Connect**. LocaNoto checks the login
immediately. If it says "No mailbox set up yet", an administrator has to
register the Exchange server once.

After that, LocaNoto can include emails, for example:

- "What did Ms Meier write most recently?"
- "Summarize the emails from the last 24 hours."
- "Reply to Mr Braun's email that the appointment works."

The login details are kept only in your current session. They are not
saved and disappear when you sign out; connect again afterwards.
**Disconnect** ends the connection earlier.

You open shared mailboxes (such as info@) with your own credentials;
Exchange decides whether you have access.

### What happens when LocaNoto wants to send an email?

LocaNoto **never sends on its own** from a personal mailbox.
If the answer wants to send an email, below it appears
**✍️ Draft: … – waiting for you** with recipient, subject and text.

- **Send** sends the draft exactly as it appears there.
- **Discard** sends nothing.

Only for a shared mailbox can an administrator enable autonomous replies.
Such emails then usually carry a note that they were
created automatically.

### How do I search the internet with LocaNoto?

In the sidebar, switch on **🌐 Web search**. LocaNoto may then look on the
web when your documents do not answer the question. Only the search term
goes out, no documents.

In your personal room this always works. In a shared room, an
administrator has to allow web search first; otherwise the sidebar names
the rooms that do not. Then select only enabled rooms at the top.

Results appear below the answer as **🌐 From the web** with [W1], [W2]
… – separate from the documents. Tick what you want to keep and
click **import into my room**.

### How do I collect sources from the internet with LocaNoto?

Above the chat, expand **🌐 Search sources on the web**, enter a topic as
keywords, **Search**. A list with up to ten results appears, without an
answer. Tick what you want to keep, then **import into my
room**. You type the search term yourself; it goes to search engines, so
no internal names or figures.

Before importing, you can read each result: **👁️ Read** shows the
whole page as plain text in LocaNoto, without images and scripts.
Exactly this text is imported. **Original ↗** opens the page in
your browser.

Imported items always land **in your personal room**, folder
*Suchergebnisse*, as a document with source and retrieval date. If something
belongs in a shared room, move it there – this way no click fills a
shared room.

### How do I tell LocaNoto how it should answer me?

In the sidebar under **🗒️ My instruction** there is a text field for
your personal instruction, for example: "Answer briefly, with tables,
and always name the standard." **Save** – from the next question on, it
applies to all your answers, including via the API. **Remove** takes
it out again.

The instruction only refines. The basics – how LocaNoto searches, which
rules apply to answers, such as citing sources and inventing nothing – are
set by an administrator in the templates, and they take precedence. Other
users do not see your instruction; it is stored encrypted. At most 2000
characters.

### How do I change my password in LocaNoto?

In the sidebar, **🔑 Change password**: **Current password**,
**New password** (at least 8 characters), **Repeat**, then
**Change**.

If ownCloud is connected, the new password also applies there, provided
LocaNoto manages your ownCloud account. If you do not have an account there
yet, it is created now, with this password. If the account there belongs to
someone else, the message says that the old password still applies there.

Forgot your password: an administrator sets a new one. It is best to change
it yourself right afterwards, so that nobody else knows it.

### What are my access tokens in LocaNoto?

An access token allows programs and scripts to query LocaNoto through the
HTTP API or to submit documents – with your
permissions. A token is created by an administrator; its value is shown
exactly once.

Under **🎫 My access tokens** you see all tokens issued to you,
with label and expiry date. **🗑️** revokes a
token immediately. Revoke what you no longer need.

### What do administrators see of my work in LocaNoto?

- **Chats:** nothing in the application. They are stored encrypted.
- **Personal room:** administrators see the file names, never the content,
  and can delete files. In strict mode they do not even see the file
  names. They can reach the content only through emergency access, which a
  second person must confirm; both names are recorded in the log.
- **Feedback:** administrators see questions with 👍/👎 and questions
  without results verbatim, together with your user ID.
- **Mailbox logins:** nobody; they are not saved.

Anyone with access to the server itself can technically see more. An
encrypted disk and a small circle of people with server access protect
against that.

## Part 2: Administering LocaNoto (for administrators)

This part explains users, roles, rooms, the shared collection, lists,
access tokens and the API, mailboxes, emergency access, feedback, the
glossary, prompts, presets, ownCloud, backup and troubleshooting.

### Where do I find the Administration area in LocaNoto as an administrator?

Administrators see the switch **🛠️ Administration** in the sidebar.
When it is on, the following areas appear below it: 📝 Feedback,
👥 Manage users, 🎫 Access tokens for the API,
📬 Mailboxes (tool servers), 🔐 Encryption, 🔓 Emergency access,
🚪 Manage rooms, ☁️ ownCloud, 🗃️ Backup of the vector database,
🔒 Security status, 💾 Storage locations, 🗣️ Edit glossary,
🎛️ Manage presets, 📜 Edit prompts and ⚙️ Configuration.

Regardless of the switch, administrators also see **🔄 Catch up and
re-ingest**, **List sources per room** and, under the documents, the
documents in other people's rooms.

### How do I become an administrator in LocaNoto?

The role is stored in the signed user file. An existing administrator
assigns it under **👥 Manage users** → choose user → **Role**
→ **Apply role**.

The very first account of a new installation is created by `create_user.py`
in the terminal; it becomes an administrator. After that, the script
requires the login of an existing administrator.

Nobody can demote or delete the last administrator – otherwise nobody could
create users any more.

### How do I create a user in LocaNoto as an administrator?

**🛠️ Administration** → **👥 Manage users** → under **Edit**
"(create new)":

1. **User ID** – letters, digits, dot, hyphen, underscore.
2. **Role** – usually `nutzer`.
3. **Password** twice, at least 8 characters.
4. **Create user**.

The personal room is created immediately. If ownCloud is connected,
LocaNoto also sets up the account and personal folder there. User IDs that
differ only by a special character ("m.meier" and "m_meier") are rejected
by LocaNoto: they would result in the same personal room.

Several administrators can create users at the same time; no entry is lost.

### How do I change or delete a user in LocaNoto as an administrator?

Under **👥 Manage users**, choose the user under **Edit**:

- change the **Role** and click **Apply role**,
- enter a **New password** twice and click **Set password** – the
  user should then change it themselves,
- tick **really delete** and click **Delete user**.

Deleting also removes the user's ownCloud account, provided
LocaNoto manages it. Chat history and personal room remain;
an administrator removes the documents separately, under the
documents in other people's rooms. For a managed account, a new password
also applies in ownCloud.

Every change is recorded in the chained user log. If the top says "The
user file was changed outside the application", a signature does not
match: existing users keep working, an account entered by hand
is locked.

### Which roles are there in LocaNoto?

| Role | may |
|---|---|
| `nutzer` | ask questions, upload to their own and enabled rooms |
| `admin` | additionally manage users, rooms, the shared collection and all settings |
| `notzugang` | none of that – only confirm or reject an administrator's emergency access to a personal room |

The role `notzugang` belongs to someone who is **not** an administrator:
management, the staff council or whoever is responsible for it in the
organization. If administrators could confirm each other, emergency access
would be a mere formality.

### How do I create a room in LocaNoto as an administrator?

**🛠️ Administration** → **🚪 Manage rooms** → under **Edit**, a new
room: **Name**, optionally **Description**, choose **Members**,
**Create room**.

For an existing room you can change the name, description and
members there, assign an **ownCloud group** (the group then determines the
members), set a **List folder** for xlsx/csv and
enter a database account under **Database account for this room**.

The General room does not have to be open to everyone either: **Switch to
a member list** gives it a list, **Open to everyone again**
takes it back.

**Remove room** takes the room out of administration; the documents are
kept. **Delete data** is a separate step: it removes the
room's passages from the search, moves the content of its
ownCloud folder to the trash and asks for confirmation first.
Personal rooms have exactly one reader; members cannot be added
there.

### How do I fill the shared collection in LocaNoto as an administrator?

Only administrators write to the room **General**. Three ways:

- **Interface:** upload documents, choose "General" as the room.
- **Terminal:** put files in the document folder and run `python ingest.py`;
  `INGEST_RAUM=einkauf python ingest.py` ingests into a different
  room.
- **API:** `POST /aufnehmen` with an administrator's token – for
  many files at once, one file per call.

Scanned pages are read by OCR on all three ways; what it
cannot read is named by `ingest.py` in its output. Figures are
described by the upload only on request. For the whole collection, **🔄 Add missing and re-ingest** → **Catch up images**
starts this as a separate process; **Re-ingest documents** ingests the
document folder completely. Both keep running when you leave
the page, and skip what has already been processed.

### How do I set up lists (Excel, CSV) in LocaNoto as an administrator?

Lists are not vectorized. A catalog records which sheets and
columns exist; LocaNoto reads the rows fresh with every question. Under
**📊 Lists** in the sidebar:

- **List sources per room:** one line per source, `raum = pfad`. The room
  determines who sees the lists. `@privat = /pfad/{benutzer}/Listen` gives
  every user their own folder. **Save and ingest sources**.
- **Upload list:** drop files, choose an **Area** (subfolder),
  then store and ingest. Only works if the folder is writable.
- **Re-ingest lists:** needed when files are added or columns
  change. New rows take effect without any action.
- **Detected sheets:** if columns without names appear, the header row
  was detected incorrectly. Correct the **Header row**, then **Apply and
  re-ingest**.

A list folder per room can also be entered under **🚪 Manage rooms**.

### How do I create an access token for LocaNoto as an administrator?

**🛠️ Administration** → **🎫 Access tokens for the API**:

1. **For whom** – the user whose permissions the token carries.
2. **Label** – what it is for, e.g. "Bulk ingest purchasing".
3. **Valid for days** – 0 means unlimited.
4. **Create token**.

The value appears **exactly once**; only its hash is stored.
Write it down, then **Noted**. The list below shows all tokens;
**🗑️** revokes one. Users see and revoke their own under
**🎫 My access tokens**.

A token only identifies the user. What they may do is stated in the
user file: only an administrator's token can submit to the General
room.

### How do I use the HTTP API of LocaNoto?

Every call carries the token in the header `X-LocaNoto-Token`.

| Call | Purpose |
|---|---|
| `GET /gesundheit` | sign of life, without token |
| `GET /status` | models, collection, lists, presets |
| `GET /raeume`, `GET /dokumente` | what this user is allowed to see |
| `POST /frage` | answer with sources, `?strom=1` streaming |
| `POST /aufnehmen` | submit a document (form: `datei`, `raum`, optional `projekt`, `bilder`, `sehmodell`) |
| `POST /rueckmeldung` | 👍/👎 for an answer |
| `DELETE /dokumente?raum=…&datei=…` | delete a document, like 🗑️ in the interface |
| `GET /hilfe` | the API describes itself |

Searches only cover the token owner's rooms; they may only delete where they could also do so in the interface (otherwise `403`). `/aufnehmen` responds
with `403` if the user may not write to the room, and with `413`
if the file is too large. The API can only be reached from the server
itself; from outside, a reverse proxy with TLS belongs in front of it.
Examples are in the `README.md` under "HTTP-Schnittstelle".

### How do I set up a mailbox in LocaNoto as an administrator?

For the personal mailboxes, **one entry for everyone** is enough: every
user opens their own mailbox in it with their own address. Each
shared mailbox gets its own entry. **🛠️ Administration** →
**📬 Mailboxes (tool servers)** → **New mailbox**:

1. **Type of server:** "Exchange/Outlook – direct, without another server".
2. **Name:** `postfach` for the common entry, `info` for info@, etc.
3. **Address or command:** the Exchange server, e.g. `owa.firma.de`.
   Leaving it empty finds the server automatically.
4. **Mailbox:** personal or shared mailbox.
5. **Email address of the mailbox:** required for a shared mailbox
   (`info@firma.de`), empty for a personal one.
6. **Create**.

After that, every user connects themselves under **📬 My mailboxes**.
There is no shared password; Exchange decides about
access. **Query tools** checks a mailbox with your own
login.

Other tool servers following the Model Context Protocol (MCP) can be
connected via the templates "MCP server over HTTP" and "local process".

### How do I set up web search in LocaNoto as an administrator?

The search service runs separately from LocaNoto (operation: README, section
"Websuche"). Then, under **📬 Mailboxes**, create a server of the type
**Web search**, address `http://websuche:8000/mcp`.

For shared rooms, under **🚪 Manage rooms**, set **🌐 Allow web search
alongside this room** on the room. Only then can users switch it on
there. The reason: the model writes the search term with the
room's passages in its context, and the search term goes to
search engines. In their personal room, every user decides for themselves.

### When may LocaNoto reply from a mailbox on its own?

Only from a **shared mailbox**, and only if **may reply
on its own** was ticked when it was created. A personal mailbox presents
every email as a draft, without exception.

**Set notice under automatic replies** appends to every email sent
on its own a note that it was created automatically; the
wording is set by **Notice text**. Without the tick, there is no note.
A draft checked by the user and sent with **Send** never carries
a note.

Which tools send something is shown by **Query tools** with
**[SENDET]**; all others only read.

### How does emergency access work in LocaNoto?

A personal room is closed even to administrators. If someone leaves or
is absent for a longer time, emergency access gets you in:

1. An administrator requests access to exactly
   one room under **🔓 Emergency access**, with a **Reason** → **Request
   emergency access**.
2. A person with the role `notzugang` signs in and clicks
   **Confirm** or **Reject**.
3. Access then applies for 24 hours and expires by itself;
   **Close now** ends it earlier.

Both names and the reason are recorded in the log. If there is nobody with
the role `notzugang`, there is no emergency access – the room can then only
be deleted, not read.

### How do I evaluate feedback in LocaNoto as an administrator?

**🛠️ Administration** → **📝 Feedback** shows two lists:

- **Questions without results** – usually a word is missing from the
  glossary or a document from the collection.
- **Reported as not helpful** – there were results, but the wrong ones.

**Download log** fetches the complete list for evaluation.
**Finish list** files it under the current date and starts a
new one; nothing is deleted. Earlier files are listed below for
download.

The list contains questions verbatim with user ID and is therefore stored
encrypted.

### How do I maintain the glossary in LocaNoto as an administrator?

The glossary translates users' words into the words of the documents.
**🛠️ Administration** → **🗣️ Edit glossary**, one mapping per line:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Save glossary** – it takes effect from the next question. Lines with `#`
are comments and are not passed to the language model. Only enter checked
mappings: a wrong entry reliably steers the search to the wrong
place. Where the entries come from: from the "Questions without results"
under 📝 Feedback.

### How do I adjust prompts and presets in LocaNoto as an administrator?

The templates are the basis for everyone; users refine them for themselves under **🗒️ My instruction**, without changing them.

**📜 Edit prompts:** two templates – one turns the question into the
search queries, the other determines how answers are written. **Applies
to** chooses whether the change applies to everyone or only to one preset.
**Save** takes effect from the next question; a text without the
required placeholders is rejected. **Reset** restores the
supplied version.

**🎛️ Manage presets:** **Name**, **Description**,
**Chat model**, **Relevant passages**, **List areas**, then
**Save**. Users choose them at the top of the sidebar. **Remove**
deletes a preset.

A wording in the prompt affects every subsequent answer; after a
change, ask a few familiar questions and compare the answers.

### How do I connect ownCloud to LocaNoto as an administrator?

"ownCloud" here means the file store, also OpenCloud. If it is configured
in the `.env`, LocaNoto additionally stores uploaded documents there
and can import folders and groups.
**🛠️ Administration** → **☁️ ownCloud**:

- **Save mapping** – assigns an ownCloud folder to a room.
- **Set up for all rooms** – creates a folder per room and shares
  it with the room's members.
- **Set up personal file store** – brings the account and folder of a
  single user up to date, for example after an import.
- **Review changes** – shows what has changed in ownCloud.
- **Sync memberships now** – imports the ownCloud groups
  as room members.

What is deleted or moved in LocaNoto, LocaNoto also deletes or moves in
ownCloud; deleted items end up in the trash there.

**Accounts:** deleting users and changing passwords only affect ownCloud
for accounts that LocaNoto manages – that is, the ones it created itself. An
account that already existed before remains untouched. **Import existing
accounts** marks existing accounts as managed once; the
service and administrator account is always excluded. If an account is
missing in the file store, it is created the next time a password is set.
Setup and the service account are described in the `README.md` under
"Dokumente aus ownCloud".

### How do I back up LocaNoto as an administrator?

Three things belong in the backup:

1. **The installation key** (`config/schluessel.key`, or the value
   of `LOCANOTO_SCHLUESSEL`). Without it, chats, attachments and
   feedback are permanently unreadable – without an error message. Nothing
   else is impossible to recover.
2. **The configuration directory** (`config/`): users, rooms, tokens,
   glossary, prompts, mailboxes.
3. **The vector database:** **🗃️ Backup of the vector database** →
   **Back up now**. **Restore snapshot** and **Restore** bring back a
   state. Without a snapshot, a loss would mean: ingest everything again.

The original documents are in the data directory and, if connected, in
ownCloud.

### What do security status, storage locations, encryption and configuration show in LocaNoto?

- **🔒 Security status** – a checklist with ✅ and ⚠️: which protection
  is set up and what remains open.
- **💾 Storage locations** – where data, configuration and index are stored
  and whether the location is set externally.
- **🔐 Encryption** – whether encryption is active and what is encrypted,
  signed or stored in plain text; **Re-encrypt log** converts
  older feedback to the encrypted form.
- **⚙️ Configuration** – settings in the `.env` that are missing, differ
  from the template or are outdated. Names only, no values.

**🔌 Model endpoints** (visible to everyone) shows which language models
are connected and whether the endpoint for ranking the results
responds.

### What do I do as an administrator when something in LocaNoto does not work?

| Observation | Cause and remedy |
|---|---|
| Page does not respond after an update | Connection re-established: reload the page, sign in again |
| Search hangs after the search queries | Model server unreachable or cold; the message names the reason |
| "RANGFOLGE Modell aus dem Image" | Rerank endpoint unreachable; LocaNoto retries it by itself |
| "No connection to the database" | Database or VPN unreachable; **Driver message** shows details |
| Document ingested but not findable | `python raum_diagnose.py` in the container |
| User file "changed outside" | a signature does not match; accounts entered by hand are locked |
| Settings unclear | **⚙️ Configuration** |

After an update, `python selbsttest.py` checks login, permissions, search,
encryption and backup without touching the collection.

## Part 3: This handbook in LocaNoto

This part explains how the handbook is ingested into LocaNoto and kept up
to date, so that LocaNoto can answer questions about how to use it.

### How can LocaNoto answer questions about itself?

This handbook is written so that LocaNoto can search it like any other
document: every heading is a question, and every section can be understood
on its own.

Ingesting: as an administrator, upload `HANDBUCH.md` and choose
**General** as the room. LocaNoto then answers questions such as "How do I
upload a document?" or "How do I create a user?" with a reference to this
section.

After a new version, remove the old handbook under **Documents** →
**General** with **🗑️ Delete** and upload the new version.
Simply overwriting would leave passages that no longer exist in the new
version.
