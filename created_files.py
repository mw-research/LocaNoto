"""Files the model creates on request: Excel, Word, PDF, PowerPoint.

    build(kind, title, spec)        -> (file name, bytes)
    store(user, name, data)         -> name actually used
    names(user) / read(user, name) / delete(user, name)
    Tools(user)                     the built-in tool server ("files")

A created file belongs to the user who asked: it is kept encrypted next
to their chats (like chat images), offered for download under the
answer, and may be attached to a mail (attachments.py). It goes into no
workspace by itself; to share it, the user uploads or moves it.

What the model writes:

    xlsx  sheets: [{name, columns: [...], rows: [[...], ...]}]
    docx  text: Markdown (# headings, - lists, | tables |, **bold**)
    pdf   text: the same Markdown
    pptx  slides: [{title, bullets: [...], notes}]
"""
import datetime
import io
import os
import re

import geheim
import paths
import statefiles

SERVER = "files"
TOOL = "create_file"
KINDS = ("xlsx", "docx", "pdf", "pptx")
MAX_ROWS = paths.env_int("CREATED_FILES_MAX_ROWS", 5000)
MAX_FILES = paths.env_int("CREATED_FILES_KEEP", 200)

_ASKS_FOR_IT = re.compile(
    r"excel|xlsx|tabelle|spreadsheet|word|docx|pdf|powerpoint|pptx|folie|präsentation|"
    r"praesentation|presentation|slides|datei|file|dokument erstellen|erstelle|create",
    re.I)


def offered(question, connections):
    mode = os.getenv("FILES_TOOL", "auto").strip().lower()
    if mode == "off":
        return False
    if mode == "always" or connections:
        return True
    return bool(_ASKS_FOR_IT.search(question or ""))


# --- storage ---

def _folder(user):
    path = os.path.join(paths.CHATS_DIR, user, "dateien")
    statefiles.makedirs(path, exist_ok=True)
    return path


def _aad(user, name):
    return f"datei:{user}:{name}".encode("utf-8")


def _safe(name):
    name = paths.sicherer_dateiname(os.path.basename(str(name or "")))
    if not name or name.startswith("."):
        raise ValueError("Invalid file name.")
    return name


def names(user):
    try:
        return sorted(statefiles.listdir(_folder(user)))
    except OSError:
        return []


def store(user, name, data):
    """Keeps the file; an existing name gets a number. Returns the name."""
    name = _safe(name)
    stem, ext = os.path.splitext(name)
    existing = set(names(user))
    n = 2
    while name in existing:
        name = f"{stem} ({n}){ext}"
        n += 1
    with statefiles.open(os.path.join(_folder(user), name), "wb") as f:
        f.write(geheim.verschluessele(data, _aad(user, name)))
    # Oldest go when there are too many: created files are a working
    # area, not an archive.
    current = names(user)
    if len(current) > MAX_FILES:
        dated = sorted(current, key=lambda n_: statefiles.getmtime(
            os.path.join(_folder(user), n_)))
        for old in dated[:len(current) - MAX_FILES]:
            delete(user, old)
    return name


def read(user, name):
    name = _safe(name)
    path = os.path.join(_folder(user), name)
    if not statefiles.exists(path):
        raise FileNotFoundError(name)
    with statefiles.open(path, "rb") as f:
        return geheim.entschluessele(f.read(), _aad(user, name))


def delete(user, name):
    path = os.path.join(_folder(user), _safe(name))
    if statefiles.exists(path):
        statefiles.remove(path)
        return True
    return False


# --- building ---

def _cell(value):
    """Numbers as numbers, so Excel can calculate with them."""
    if isinstance(value, (int, float)) or value is None:
        return value
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    # German thousands first (1.234,50 / 12.400): the content is mostly
    # German, where "12.400 EUR" is twelve thousand. "0.125" stays a decimal.
    if re.fullmatch(r"-?[1-9]\d{0,2}(\.\d{3})+(,\d+)?", text):
        return float(text.replace(".", "").replace(",", "."))
    # English thousands: 1,234.50
    if re.fullmatch(r"-?[1-9]\d{0,2}(,\d{3})+\.\d+", text):
        return float(text.replace(",", ""))
    if re.fullmatch(r"-?\d+[.,]\d+", text):
        return float(text.replace(",", "."))
    return text


def build_xlsx(title, sheets):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    wb.remove(wb.active)
    total = 0
    for i, sheet in enumerate(sheets or [{}]):
        name = re.sub(r"[\[\]:*?/\\]", "", str(sheet.get("name") or f"Tabelle{i + 1}"))[:31]
        ws = wb.create_sheet(name or f"Tabelle{i + 1}")
        columns = [str(c) for c in sheet.get("columns") or []]
        if columns:
            ws.append(columns)
            for cell in ws[1]:
                cell.font = Font(bold=True)
        for row in sheet.get("rows") or []:
            total += 1
            if total > MAX_ROWS:
                raise ValueError(f"More than {MAX_ROWS} rows.")
            ws.append([_cell(v) for v in (row if isinstance(row, list) else [row])])
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width + 2))
        ws.freeze_panes = "A2" if columns else None
    wb.properties.title = title
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _blocks(text):
    """Markdown into blocks: ("h", level, text), ("li", text), ("table", rows), ("p", text)."""
    out, table = [], []
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table.append(cells)
            continue
        if table:
            out.append(("table", table))
            table = []
        if not stripped:
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            out.append(("h", len(m.group(1)), m.group(2)))
        elif re.match(r"^([-*]|\d+\.)\s+", stripped):
            out.append(("li", re.sub(r"^([-*]|\d+\.)\s+", "", stripped)))
        else:
            out.append(("p", stripped))
    if table:
        out.append(("table", table))
    return out


def _runs(text):
    """[(text, bold)] from **bold** marks."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    return [(p[2:-2], True) if p.startswith("**") and p.endswith("**") else (p, False)
            for p in parts if p]


def build_docx(title, text):
    import docx
    d = docx.Document()
    d.core_properties.title = title
    d.add_heading(title, level=0)
    for block in _blocks(text):
        if block[0] == "h":
            d.add_heading(block[2], level=block[1])
        elif block[0] == "table":
            rows = block[1]
            t = d.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            t.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    t.cell(r, c).text = value
                    if r == 0:
                        for run in t.cell(r, c).paragraphs[0].runs:
                            run.bold = True
        else:
            para = d.add_paragraph(style="List Bullet" if block[0] == "li" else None)
            for part, bold in _runs(block[1]):
                para.add_run(part).bold = bold
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def build_pdf(title, text):
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    styles = getSampleStyleSheet()

    def inline(s):
        return "".join(f"<b>{escape(p)}</b>" if b else escape(p) for p, b in _runs(s))

    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 0.3 * cm)]
    bullets = []

    def flush():
        if bullets:
            story.append(ListFlowable([ListItem(Paragraph(inline(b), styles["BodyText"]))
                                       for b in bullets], bulletType="bullet"))
            bullets.clear()

    for block in _blocks(text):
        if block[0] == "li":
            bullets.append(block[1])
            continue
        flush()
        if block[0] == "h":
            story.append(Paragraph(inline(block[2]), styles[f"Heading{min(block[1] + 1, 4)}"]))
        elif block[0] == "table":
            rows = [[Paragraph(inline(c), styles["BodyText"]) for c in row] for row in block[1]]
            t = Table(rows, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 0.3 * cm)]
        else:
            story.append(Paragraph(inline(block[1]), styles["BodyText"]))
    flush()
    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, title=title, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm).build(story)
    return out.getvalue()


def build_pptx(title, slides):
    from pptx import Presentation
    from pptx.util import Pt
    prs = Presentation()
    prs.core_properties.title = title
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = title
    if len(first.placeholders) > 1:
        first.placeholders[1].text = datetime.date.today().strftime("%d.%m.%Y")
    for s in slides or []:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = str(s.get("title") or "")
        body = slide.placeholders[1].text_frame
        body.clear()
        for i, bullet in enumerate(s.get("bullets") or []):
            para = body.paragraphs[0] if i == 0 else body.add_paragraph()
            para.text = str(bullet)
            para.font.size = Pt(20)
        if s.get("notes"):
            slide.notes_slide.notes_text_frame.text = str(s["notes"])
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def build(kind, title, spec):
    """(file name, bytes) of one file. ValueError for missing parts."""
    kind = str(kind or "").lower().strip(".")
    if kind not in KINDS:
        raise ValueError(f"Unknown kind '{kind}'. Possible: {', '.join(KINDS)}.")
    title = " ".join(str(title or "").split())[:120]
    if not title:
        raise ValueError("A title is needed.")
    if kind == "xlsx":
        if not spec.get("sheets"):
            raise ValueError("xlsx needs 'sheets'.")
        data = build_xlsx(title, spec["sheets"])
    elif kind == "pptx":
        if not spec.get("slides"):
            raise ValueError("pptx needs 'slides'.")
        data = build_pptx(title, spec["slides"])
    else:
        if not str(spec.get("text") or "").strip():
            raise ValueError(f"{kind} needs 'text'.")
        data = (build_docx if kind == "docx" else build_pdf)(title, spec["text"])
    return f"{title[:80]}.{kind}", data


# --- the tool ---

class Tools:
    """Built-in tool server, like workspace_notes.Tools. Creating a file
    changes nothing outside the user's own store, so it runs at once."""

    name = SERVER

    def __init__(self, user):
        self.user = user
        self.created = []

    def werkzeuge(self):
        return [{
            "server": SERVER, "name": TOOL,
            "beschreibung": (
                "Create a file for the user when they ask for one: an Excel "
                "workbook (xlsx), a Word document (docx), a PDF or a PowerPoint "
                "presentation (pptx). Fill it only with content from the "
                "conversation, the documents found or the tool results -- "
                "nothing invented. The user gets a download link; the file can "
                "then be attached to a mail."),
            "schema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "title": {"type": "string", "description": "Title, also the file name."},
                    "sheets": {"type": "array", "description": "xlsx only.", "items": {
                        "type": "object", "properties": {
                            "name": {"type": "string"},
                            "columns": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "array", "items": {}}}}}},
                    "text": {"type": "string", "description":
                             "docx and pdf: Markdown with # headings, - lists, | tables |."},
                    "slides": {"type": "array", "description": "pptx only.", "items": {
                        "type": "object", "properties": {
                            "title": {"type": "string"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                            "notes": {"type": "string"}}}},
                },
                "required": ["kind", "title"],
            },
        }]

    def rufe(self, name, argumente=None):
        if name != TOOL:
            raise ValueError(f"{SERVER}: no tool '{name}'.")
        a = dict(argumente or {})
        try:
            file_name, data = build(a.get("kind"), a.get("title"), a)
        except ValueError as e:
            return f"Not created: {e}"
        stored = store(self.user, file_name, data)
        self.created.append(stored)
        return f"Created '{stored}' ({len(data) // 1024 + 1} KB). The user can download it."

    def schliesse(self):
        pass
