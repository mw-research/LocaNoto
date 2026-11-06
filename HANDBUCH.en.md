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

The sidebar is organized into:

- **Preset** (at the very top, if available)
- **Chats** – new chat, earlier chats
- **Document filter** – narrow the search, web search
- **Database** and **Lists** – only if set up
- **Documents** – upload, move, delete
- **Settings** – model, password, instruction, presets, mailboxes,
  access tokens
- **Admin area** – admins only

### How do I sign in to and out of LocaNoto?

- Sign in: enter **Username** and **Password** → **Log in**. An admin
  creates your account.
- Sign out: **Log out** in the sidebar.
- No input for a longer time (default: 480 minutes) → the session ends by
  itself; sign in again.
- Page stops responding after an update → reload the page and sign in
  again.

### How do I switch LocaNoto to English?

In the sidebar under **🌐 Sprache / Language**, choose German or English →
takes effect immediately and is remembered for your account. The login
page has the same switch.

You can ask in any language: LocaNoto answers in the language of the
question, even if the documents are German. File names, values and
quotations stay as they are in the document.

### How do I ask LocaNoto a question?

- Type the question into the input field at the bottom (**Ask the
  database**) and send it.
- Attach an image (png, jpg, webp, gif, bmp) → LocaNoto describes it and
  takes it into account.
- Follow-up question in the same chat → refers to the conversation so far.

While an answer is being written, the sidebar is locked; a click there
cancels the answer. If an answer ends with "Aborted – answer incomplete",
ask the question again.

### How can I see in LocaNoto where an answer comes from?

Below every answer is **Sources**, with one entry **File (page n)** per
source passage.

- Expand an entry → shows the text passage the answer is based on.
- Click a reference in the answer text → jumps to the corresponding source.
- For PDFs, tick **Original page n as image** → shows the page in the
  original, e.g. for tables or drawings.
- For Word and Markdown, the passage number appears instead of the page.

**Debug: what does the LLM see?** shows the search queries and what the
language model got to see.

### Why doesn't LocaNoto find something?

- **The document is in a workspace you cannot see** → LocaNoto only
  searches your workspaces.
- **A filter is set** → under **Document filter**, clear workspace,
  project and "Restrict search to".
- **The document uses a different word** (you ask about "BANF", it says
  "Bestellanforderung") → an admin adds it to the glossary. Questions
  without results are logged automatically for this.
- **Scan without readable text** → a message appears when uploading; see
  "How do I upload a scan in LocaNoto?".

More results: raise the slider **Passages to retrieve** (at the bottom of
the sidebar, default 5).

### How do I narrow down the search in LocaNoto?

In the sidebar under **Document filter**:

- **Workspace:** choose → search only there. Empty → all your workspaces.
- **Project:** choose → only documents of this project from your personal
  workspace.
- **Restrict search to:** choose individual documents. The list only shows
  documents matching the workspace and project above.

Slider **Passages to retrieve** (at the bottom of the sidebar) → sets how
many source passages go into an answer. More helps with extensive sets of
rules, but makes the answer slower.

### What are workspaces in LocaNoto and who sees my documents?

The workspace determines who can find a document.

| Workspace | visible to | upload and delete |
|---|---|---|
| General | all users | admins only |
| named workspace (department, project, customer) | its members | its members |
| your personal workspace | only you | you and admins |

Every user has a personal workspace from the start. What is stored there
never flows into other people's answers. Which workspaces you see is shown
under **Documents** → **Stored documents**.

### How do I upload a document in LocaNoto?

In the sidebar under **Documents**:

1. **Upload documents** – PDF, Word (docx), Markdown, text or scan (TIFF,
   JPG, PNG); several files at once are possible.
2. Choose the **Workspace**. The default is your personal workspace
   ("Visible only to you") → nothing is shared by accident.
3. Optionally enter a **Project** (personal workspace only) → selectable
   in the document filter later.
4. Only tick **Describe images and scans** if diagrams matter → one model
   call per image. Scanned pages are read by OCR even without the tick.
5. **Upload & ingest** → LocaNoto reports for each file how many passages
   are searchable.

### How do I upload a scan in LocaNoto?

Like any document. Pages without a text layer (scanned PDF, TIFF, JPG,
PNG) are read automatically by OCR (German, English).

- Page not readable → the message names the page numbers, and **Read with
  vision model** appears below it.
- Click **Read with vision model** → reads poor scans and handwriting
  better, one model call per page.

Below the answer, such source passages are marked **from OCR** or **read
by vision model**. Check numbers from them (test values, dimensions,
deadlines) against the original page: OCR can confuse digits, and the
vision model can plausibly fill in illegible spots.

### How do I move or delete a document in LocaNoto?

Under **Documents** → **Stored documents**, each workspace has an expander
with its files:

1. **Manage document** – choose the file.
2. Choose **move to** → **Move**, e.g. to share something from your
   personal workspace with a department.
3. Or **Delete** → the file and its passages disappear from the search.

With ownCloud: deleted files go to the trash there, moved files to the
folder of the new workspace. If that fails, the message says so –
otherwise the file would come back with the next sync.

"Read only" → you may not change anything in this workspace.

### How do I work with chats in LocaNoto?

In the sidebar under **Chats**:

- **New chat** → new conversation without history.
- **Earlier chats:** choose → opens an earlier conversation.
- **Delete chat** → removes the open conversation.

After the first question, each chat automatically gets a short title (at
most about six words). Chats are saved automatically, visible only to you
and stored encrypted on the server, including titles and images.

New topic → new chat, because LocaNoto takes the chat history into
account in its answer.

While an answer is being written you may switch tabs or chats: LocaNoto
keeps writing it. Back in the chat it shows "The answer is being written
…" with the text so far until it is done; elsewhere LocaNoto notifies
"Answer ready". If an answer breaks off (e.g. the model server fails), the
reason and **Ask again** appear below it.

### What do thumbs up and thumbs down do in LocaNoto?

Below every answer are 👍 ("Helpful") and 👎 ("Not helpful").

- Click → the feedback goes to the admins together with the question and
  the sources. It shows them where documents or glossary entries are
  missing.
- Questions without results are logged even without a click.
- If a result came from a personal workspace, the feedback shows only a
  placeholder instead of the file name.

### What is a preset in LocaNoto?

A preset bundles model, number of source passages and list areas for one
purpose. Choose it at the very top of the sidebar under **Preset**; below
it, it says what the preset is meant for. **(Default)** uses the basic
settings.

**Create your own preset:** **Settings** → **My presets**:

1. Enter a **Name**.
2. Choose a **Model** (only models the admins have allowed).
3. **Passages per question** – 0 = default.
4. Choose **List areas** (if lists are set up).
5. **Save** → appears at the top under **Preset**, marked "(eigene)" (own).
   **Delete** removes it.

Presets for everyone are created by admins in the **Admin area**; only
those can have their own prompts.

**Model:** under **Settings** you choose the language model from the list
the admins allow. If there is only one model, the selection is hidden.

### How do I query lists from Excel or CSV in LocaNoto?

Lists (xlsx, csv) are read fresh with every question → new rows take
effect immediately. In the sidebar under **Lists**:

- Tick **Also query lists** → LocaNoto picks the matching list and reads
  the matching rows. Below, it says how many sheets are available.
- Choose **List area** → only lists from these areas (subfolders). Empty →
  all.
- **Include large lists** → also very large sheets; questions then take
  considerably longer.

Below the answer, **List: … (n rows)** shows which list was used with
which query. **Detected sheets** shows sheets and columns, **Not
readable** files with errors.

**My list folder:** enter your own folder under **Folder** → **Apply** →
only you see its lists.

### How do I query the database in LocaNoto?

If a database is set up for one of your workspaces, the chat shows
**Database** under "Workspaces · Model".

- Tick **Database** → LocaNoto writes a read-only query (SELECT) for your
  question and uses the result. LocaNoto cannot change anything in the
  database.
- Below the answer, **Database query** shows the query.
- "No database connection: …" → names the reason (server not reachable,
  login refused, …); the answer then comes from the documents only.

**Documents from the database:** "Show me invoice 2025103", "the data sheet
of the ball valve". If the document lies in the database or in a released
folder, it is listed under the answer under **Documents from the database**;
PDFs and images open in the browser. Asking about the content works too:
"What is on invoice 2025103?"

**Own SQL login** (classic interface: **My database access**): **Settings** → **My databases** → the user and password
your database admin gave you → **Connect**. Queries then run with your
rights in the database. The login stays only in the browser session. If
the admin stored a shared read account, it also works without one.

### How do I work with my own lists in LocaNoto?

**Settings** → **My lists** shows your folder, e.g.
`/mnt/listen/LISTE/anna`: the admin sets a root, everybody gets a folder
named after their user name in it. Excel and CSV files there are read at
every question that uses lists; only you see them.

- **Subfolder (optional)** → only this part of your folder counts.
- **Read lists again** → after new files or changed columns; new rows
  work without it.

### How do I connect my mailbox to LocaNoto?

**Settings** → **My mailboxes** → enter email address and password for
each mailbox → **Connect**. LocaNoto checks the login immediately.

"No mailbox set up yet" → an admin has to register the Exchange server
once.

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
answer wants to send an email, **Draft: … — waiting for you** appears
below it with recipient, subject and text.

- **Send** → sends the draft exactly as it appears there.
- **Discard** → sends nothing.

If sending goes wrong, the draft says why:

- **Not sent: …** → nothing went out; **Send** tries again.
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

### How does LocaNoto notify me of new mail?

With a mailbox connected and LocaNoto open in a browser tab, LocaNoto
checks for new mail every few minutes. New mail → a notice with sender and
subject → **Show** opens a chat asking about the new messages.

**Settings** → **Mailboxes** → **Notify me about new mail** switches this
per mailbox. With no LocaNoto tab open nothing is checked: the login
lives only in the browser session.

### How do I work with tickets in LocaNoto?

If an admin switched on the ticket system for a shared mailbox and made
you a member, there is a **Tickets** tab.

- Every new mail to the mailbox becomes a ticket (e.g. T-2026-0001). The
  sender gets the standard answer with the number at once; you get a
  notice. The number on the tab counts open tickets nobody took.
- Open a ticket → **Take it** (you are responsible, status *in progress*),
  set the **Status**, **Add note**.
- **Answer in the chat** → a chat with the ticket as the question; the
  answer goes out as a draft through your connected mailbox.
- If the customer replies with the number in the subject, the mail goes
  to the same ticket and reopens it; the person responsible is notified.

### How do I search the internet with LocaNoto?

**Document filter** → switch on **Web search** → LocaNoto searches the
web when your documents do not answer the question. Only the search term
goes out, no documents.

- Personal workspace → always works.
- Shared workspace → an admin has to allow web search there first.
  Otherwise the sidebar names the workspaces that are not enabled; then
  select only enabled ones at the top.
- **Allgemein** is blocked by default. A question with web search over all
  workspaces leaves it out and says so below the answer.

Without web search switched on, LocaNoto can **propose** a web search,
e.g. when the documents give nothing or the question asks for something
current. Below the answer: **Web search proposed** with the exact search
text → **Search in the web** → the answer continues in the same chat with
the hits. **Discard** → nothing goes out.

Results appear below the answer as **From the web** with [W1], [W2] …,
separate from the documents. Tick results → **Import n** → they land in
your personal workspace.

### How do I collect sources from the internet with LocaNoto?

1. Tab **Web sources** → enter a **topic** as keywords → **Search**.
   Or type keywords into the chat box → **Search in the web**.
   The search term goes to search engines: no internal names or figures.
2. The search runs in the background; you may leave the page. When the
   results are there (up to 25), a notice with **Show** appears and the
   **Web sources** tab shows a count.
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

**Settings** → **My instruction** → enter text, e.g. "Answer briefly, with
tables, and always name the standard." → **Save**.

- Applies from the next question to all your answers, including via the
  API.
- **Remove** → takes it out again.
- At most 2000 characters; stored encrypted, others do not see it.

The instruction only refines. The basic rules (cite sources, invent
nothing) are set by the admins in the prompts; they take precedence.

### How do I change my password in LocaNoto?

**Settings** → **Change password** → **Current password**, **New password
(min. 8 characters)**, **Repeat** → **Change**.

With ownCloud:

- LocaNoto manages your ownCloud account → the new password applies there
  too.
- No account there yet → it is created now, with this password.
- The account belongs to someone else → the message says the old password
  still applies there.

Forgot your password → an admin sets a new one; change it yourself right
afterwards.

### What are my access tokens in LocaNoto?

An access token lets programs and scripts query LocaNoto through the HTTP
API or submit documents – with your permissions. An admin creates it; its
value is shown exactly once.

**Settings** → **My access tokens** → shows all tokens issued to you with
label and expiry date. **🗑️** → revokes a token immediately. Revoke tokens
you no longer need.

### What do admins see of my work in LocaNoto?

- **Chats:** nothing in the application; they are stored encrypted.
- **Personal workspace:** admins see file names, never the content, and
  can delete files. In strict mode they do not even see the file names.
  They reach the content only through emergency access, which a second
  person must confirm; both names are recorded in the log.
- **Feedback:** questions with 👍/👎 and questions without results
  verbatim, with your user ID.
- **Mailbox logins:** nobody; they are not saved.

Anyone with access to the server itself can technically see more; an
encrypted disk and a small circle with server access protect against that.

## Part 2: Administering LocaNoto (for admins)

Users, roles, workspaces, the shared collection, lists, access tokens and
the API, mailboxes, emergency access, feedback, glossary, prompts,
presets, ownCloud, backup and troubleshooting.

### Where do I find the Admin area in LocaNoto as an admin?

Admins see the switch **Admin area** at the bottom of the sidebar. Switch
it on → below it appear:

Feedback, Users, Access tokens (API), Mailboxes (tool servers),
Encryption, Emergency access, Workspaces, ownCloud, Vector database
backup, Security status, Storage locations, Glossary, Presets, Prompts and
Configuration.

Even without the switch, admins see:

- **Fill gaps and re-ingest** (under **Documents**),
- **List sources per workspace** (under **Lists**),
- under **Stored documents**, also documents in other people's workspaces.

### How do I become an admin in LocaNoto?

- An existing admin: **Admin area** → **Users** → choose user → **Role**
  `admin` → **Apply role**.
- New installation: the very first account is created by `create_user.py`
  in the terminal; it becomes admin. After that, the script requires the
  login of an existing admin.

Nobody can demote or delete the last admin.

### How do I create a user in LocaNoto as an admin?

**Admin area** → **Users** → under **Edit** "(create new)":

1. **ID** – letters, digits, dot, hyphen, underscore.
2. **Role** – usually `nutzer`.
3. **Password (min. 8 characters)** and **Repeat password**.
4. **Create user**.

→ The personal workspace is created immediately; with ownCloud, also the
account and personal folder there.

IDs that differ only by a special character ("m.meier", "m_meier") are
rejected by LocaNoto: they would result in the same personal workspace.

### How do I change or delete a user in LocaNoto as an admin?

**Admin area** → **Users** → choose the user under **Edit**:

- Change **Role** → **Apply role**.
- **New password** twice → **Set password**. The user should then change
  it themselves. For an account managed by LocaNoto, it also applies in
  ownCloud.
- Tick "… really delete" → **Delete user**. A managed ownCloud account is
  removed too. Chat history and personal workspace remain; delete the
  documents separately under **Stored documents** (other users' personal
  workspaces).

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
emergency access would be a mere formality.

### How do I create a workspace in LocaNoto as an admin?

**Admin area** → **Workspaces** → under **Edit**, create a new one:
**Label**, optionally **Description**, **Members** → **Create workspace**.

Choose an existing workspace → editable there:

- **Label**, **Description**, **Members**,
- **ownCloud group** → its members are added,
- **List folder (xlsx, csv)**,
- **Allow web search**,
- **Database account** → own database account for this workspace.

**General:** **Use member list** → only listed users see it; **Reopen for
all** → reverts that.

- **Remove workspace** → takes it off the list, the documents remain.
- **Delete data** → after confirmation, removes its passages from the
  search and moves the content of its ownCloud folder to the trash.

Personal workspaces have exactly one reader; members cannot be added
there.

In the web interface: **Admin** → **Workspaces** → search field above the
list → **Edit**. The members show as chips (× removes one); someone is
added with **Search user and add**: type a part of the name, click the
suggestion. The other way round: **Users** → search the name →
**Workspaces** → search and add workspaces the same way. There is no list
of all users; from 20 users on, the user list shows hits only after a
search.

### How do I fill the shared collection in LocaNoto as an admin?

Only admins write to **General**. Three ways:

- **Interface:** **Upload documents**, choose "General" as the workspace.
- **Terminal:** put files in the document folder → `python ingest.py`.
  `INGEST_RAUM=einkauf python ingest.py` ingests into a different
  workspace.
- **API:** `POST /aufnehmen` with an admin's token, one file per call.

Scanned pages are read by OCR on all three ways; what it cannot read is
named by `ingest.py` in its output.

**Fill gaps and re-ingest** (under **Documents**):

- **Catch up images** → describes figures in the whole collection.
- **Re-ingest documents** → ingests the document folder completely.

Both keep running when you leave the page, and skip what has already been
processed.

### How do I set up lists (Excel, CSV) in LocaNoto as an admin?

Lists are not vectorized: a catalog knows sheets and columns, and LocaNoto
reads the rows fresh with every question. In the sidebar under **Lists**:

- **Admin** → **Lists** → **List folders per workspace**: one folder per
  shared workspace; the workspace determines who sees the lists.
- **Root of the personal folders**, e.g. `/mnt/listen/LISTE` → every user
  gets `/mnt/listen/LISTE/<user name>` and sees it under **Settings** →
  **My lists**. `owncloud:/LISTE` works as well.
- Shares on several servers: in the installer `"lists_pvc": {"name":
  "claim", …}`, mounted at `/mnt/listen/<name>`.
- **Upload list:** choose files, choose **Upload to** (subfolder) →
  **Upload n file(s)**. Only if the folder is writable.
- **Re-ingest lists:** needed for new files or changed columns; new rows
  take effect without any action.
- **Detected sheets:** columns without names → header row detected
  incorrectly. Correct the **Header row** → **Apply and re-ingest**.

A list folder per workspace can also be entered under **Admin area** →
**Workspaces**.

### How do I create an access token for LocaNoto as an admin?

**Admin area** → **Access tokens (API)**:

1. **For whom** – the user whose permissions the token carries.
2. **Label** – purpose, e.g. "Bulk ingest purchasing".
3. **Valid (days, 0 = unlimited)**.
4. **Create token** → the value appears **exactly once**; only its hash is
   stored. Copy it → **Noted**.

The list below shows all tokens; **🗑️** revokes one. Users see and revoke
their own under **Settings** → **My access tokens**.

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
| `POST /rueckmeldung` | 👍/👎 for an answer |
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

**Admin area** → **Mailboxes (tool servers)** → **New mailbox**:

1. **Server type:** "Exchange/Outlook — direct, without another server".
2. **Name:** `postfach` for the common entry, `info` for info@, etc.
3. **Address or command:** the Exchange server, e.g. `owa.firma.de`;
   empty → found automatically.
4. **Mailbox:** personal or shared mailbox.
5. **Mailbox address (Exchange only):** required for a shared mailbox
   (`info@firma.de`), empty for a personal one.
6. **Create**.

After that, every user connects themselves under **My mailboxes**; there
is no shared password. **Fetch tools** → checks a mailbox with your own
login.

Other tool servers (MCP) → server type "MCP server over HTTP" or "local
process (stdio)".

### How do I set up web search in LocaNoto as an admin?

1. Run the search service separately from LocaNoto (`REFERENZ.md`,
   "Websuche").
2. **Admin area** → **Mailboxes (tool servers)** → **New mailbox** →
   **Server type** web search, **Address or command**
   `http://websuche:8000/mcp` → **Create**.
3. For each shared workspace: **Workspaces** → choose the workspace →
   tick **Allow web search** → only then can users switch on web search
   there.

Why the approval: the model writes the search term with passages of the
workspace in its context, and the search term goes to search engines. In
their personal workspace, every user decides for themselves.

### When may LocaNoto reply from a mailbox on its own?

Only from a **shared mailbox** for which **may reply on its own** was
ticked when it was created. A personal mailbox presents every email as a
draft, without exception.

- Tick **Add notice to auto-replies** → every email sent on its own
  carries a note that it was created automatically. Wording: **Notice
  text**.
- Without the tick → no note.
- A draft checked by the user and sent with **Send** never carries a note.

**Fetch tools** marks tools that send something with **[SENDET]**; all
others only read.

### How do I set up a ticket system for a shared mailbox in LocaNoto as an admin?

**Admin** → **Mailboxes** → for each shared mailbox a section **Ticket
system**:

1. Tick **Ticket system on**.
2. **No login is stored.** Members connect the mailbox under **Settings**
   → **Mailboxes** with their own account (rights on the mailbox in
   Exchange, "Send As" for the answers).
3. **Standard answer**: goes to every sender at once. `{ticket}`,
   `{subject}` and `{name}` are filled in.
4. **Members**: LocaNoto users who see every ticket and get a notice.
   Admins see all tickets.
5. Optional **Forward every new mail to**: addresses that get every new
   mail with the ticket number in the subject.
6. **Save** → **Check now** (with your own connected login). The first
   check only notes the time; from then on every new mail becomes a
   ticket.

It is checked every minute (`TICKET_POLL_SECONDS`) while a member with the
mailbox connected has LocaNoto open. With nobody online, mail that came
meanwhile is handled the next time, standard answer included. Machine mail
(out-of-office replies, newsletters, bounces, mail of the mailbox itself)
neither becomes a ticket nor gets an answer. A mail is marked handled
before anything is sent: it is never answered twice.

### How does emergency access work in LocaNoto?

A personal workspace is closed even to admins. If someone leaves or is
absent for a longer time:

1. An admin: **Admin area** → **Emergency access** → choose the
   **Workspace**, enter a **Reason** → **Request emergency access**.
2. A person with the role `notzugang` signs in → **Confirm** or
   **Reject**.
3. Confirmed → access applies for 24 hours and expires by itself; **Close
   now** ends it earlier.

Both names and the reason are recorded in the log. Without anyone holding
the role `notzugang`, there is no emergency access: the workspace can then
only be deleted, not read.

### How do I evaluate feedback in LocaNoto as an admin?

**Admin area** → **Feedback** shows:

- **Questions without results** – usually a glossary entry or a document
  is missing.
- **Reported as not helpful** – there were results, but the wrong ones.

**Download log** → the complete list. **Finish list** → files it under
the current date and starts a new one; nothing is deleted. Earlier files
are listed below.

The list contains questions verbatim with user ID and is therefore stored
encrypted.

### How do I maintain the glossary in LocaNoto as an admin?

The glossary translates users' words into the words of the documents.
**Admin area** → **Glossary**, one mapping per line, `#` = comment:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Save glossary** → takes effect from the next question. Comment lines are
not passed to the language model.

Only enter checked mappings: a wrong entry reliably steers the search to
the wrong place. Candidates come from the "Questions without results"
under **Feedback**.

### How do I adjust prompts and presets in LocaNoto as an admin?

**Prompts:** two templates – one turns the question into search queries,
the other determines how answers are written.

- **Applies to** → everyone or only one preset.
- **Save** → takes effect from the next question; a text without the
  required placeholders is rejected.
- **Reset** → restores the supplied version.

**Presets** (for everyone): **Label**, **Description**, **Chat model**,
**Relevant passages** (0 = default), **List areas** → **Save**.
**Remove** deletes one. Only these presets can have their own prompts
(choose them under **Prompts** → **Applies to**).

The selectable models are set by `CHAT_MODELLE` in the `.env`; users see
the same list under **Model** and **My presets**. Users create their own
presets without prompts and refine with **My instruction**.

After a prompt change, ask a few familiar questions and compare the
answers.

### How do I connect ownCloud to LocaNoto as an admin?

"ownCloud" means the file store, also OpenCloud. Configured in the `.env`
→ LocaNoto also stores uploaded documents there and imports folders and
groups. **Admin area** → **ownCloud**:

- **Save mapping** → assigns a folder to a workspace.
- **Set up all** → one folder per workspace, shared with its members.
- **Set up personal file store** → brings a single user's account and
  folder up to date.
- **Review changes** → shows what has changed in ownCloud.
- **Sync memberships** → imports ownCloud groups as members.
- **Import accounts** → marks existing accounts once as managed by
  LocaNoto (service and admin account excluded).

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
   keeps using the old model meanwhile. Cancelling and starting again
   later is fine; it continues where it stopped.
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
3. **Vector database:** **Admin area** → **Vector database backup** →
   **Back up now**. Restore: **Restore snapshot** → **Restore**. Without a
   snapshot, a loss would mean: ingest everything again.

The original documents are in the data directory and, if connected, in
ownCloud.

### What do security status, storage locations, encryption and configuration show in LocaNoto?

In the **Admin area**:

- **Security status** – checklist with ✅ and ⚠️: what is set up, what
  remains open.
- **Storage locations** – where data, configuration and index are stored
  and whether the location is set externally.
- **Encryption** – what is encrypted, signed or stored in plain text.
  **Re-encrypt log** → converts older feedback to the encrypted form.
- **Configuration** – `.env` settings that are missing, differ or are
  outdated; names only, no values.

**Model endpoints** (under **Settings**, for everyone) shows the connected
language models and whether the endpoint for ranking the results responds.

### What do I do as an admin when something in LocaNoto does not work?

| Observation | Remedy |
|---|---|
| Page does not respond after an update | Reload the page, sign in again |
| Search hangs after the search queries | Model server unreachable or cold; the message names the reason |
| "RANGFOLGE Modell aus dem Image" | Rerank endpoint unreachable; LocaNoto retries by itself |
| "No database connection" | Check database or VPN; **Driver message** shows details |
| Document ingested but not findable | `python raum_diagnose.py` in the container |
| User file "changed outside" | Signature does not match; accounts entered by hand are locked |
| Settings unclear | **Admin area** → **Configuration** |

After an update → `python selbsttest.py` checks login, permissions,
search, encryption and backup without touching the collection.

## Part 3: This handbook in LocaNoto

How the handbook is ingested and kept up to date, so that LocaNoto can
answer questions about how to use it.

### How can LocaNoto answer questions about itself?

Every heading of this handbook is a question, and every section can be
understood on its own – so LocaNoto finds it like any other document.

- Ingesting: as an admin, upload `HANDBUCH.md`, workspace **General** →
  LocaNoto answers questions such as "How do I upload a document?" with a
  reference to the matching section.
- New version: under **Stored documents** → **General**, remove the old
  version with **Delete**, then upload the new one. Simply overwriting
  would leave passages that no longer exist.
