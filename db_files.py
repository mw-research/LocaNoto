"""Documents in database results: files in binary columns, paths, links.

    collect(user, columns, rows) -> Found

An ERP keeps documents in one of two ways a query can reach: the file
itself in a binary column (varbinary, image), or a path or link to it.
Both come back from a query as a cell. Without this module a binary cell
reached the model as a byte dump and a path as text nobody could open.

    binary cell     recognised by its content (PDF, image, Office, zip),
                    stored as a file of the asking user (created_files,
                    encrypted), offered under the answer
    path            read only below a released folder (SQL_FILE_ROOTS),
                    then the same as a binary cell; anything else stays text
    http(s) link    offered as a link, not fetched

The text of a PDF goes to the model as well, so "what is on invoice
2025103" can be answered. The rights are those of the database login
that ran the query: the user only gets files that login could read.

SQL_FILE_ROOTS maps the paths the ERP stores to folders mounted into the
container, several separated by ";":

    SQL_FILE_ROOTS=\\\\fs01\\belege=/mnt/belege;R:\\Zeichnungen=/mnt/zeichnungen
"""
import io
import os
import re
import zipfile

import created_files
import paths

MAX_FILES = 10                       # per answer
MAX_BYTES = 25 * 1024 * 1024         # per file
TEXT_CHARS = 3000                    # PDF text per file for the model
TEXT_TOTAL = 8000

_FILE_NAME = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,150}\.(pdf|png|jpe?g|gif|tiff?|docx|xlsx|"
                        r"pptx|txt|csv|zip|msg|eml)$", re.I)
_PATH = re.compile(r"^(\\\\[^\\/]+[\\/]|[A-Za-z]:[\\/]|/)[^\r\n]*\.[A-Za-z0-9]{2,5}$")
_URL = re.compile(r"^https?://[^\s<>\"']{3,2000}$", re.I)


def roots():
    """[(prefix, folder)] from SQL_FILE_ROOTS, prefixes normalised."""
    out = []
    for part in (os.getenv("SQL_FILE_ROOTS") or "").split(";"):
        if "=" not in part:
            continue
        prefix, folder = part.split("=", 1)
        prefix, folder = _norm(prefix.strip()), folder.strip()
        if prefix and folder:
            out.append((prefix.rstrip("/"), folder))
    return out


def _norm(path):
    return str(path).replace("\\", "/")


def sniff(data):
    """The file extension a content stands for, or None."""
    head = bytes(data[:8])
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "tif"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(bytes(data))).namelist()
        except zipfile.BadZipFile:
            return None
        for prefix, ext in (("word/", "docx"), ("xl/", "xlsx"), ("ppt/", "pptx")):
            if any(n.startswith(prefix) for n in names):
                return ext
        return "zip"
    return None


def resolve(path):
    """The local file for a stored path below a released folder, or None.

    Case-insensitive on the prefix (Windows paths), and the result must
    stay inside the folder: '..' in the path leads nowhere.
    """
    p = _norm(path)
    for prefix, folder in roots():
        if p.lower() == prefix.lower() or p.lower().startswith(prefix.lower() + "/"):
            rest = p[len(prefix):].lstrip("/")
            base = os.path.realpath(folder)
            target = os.path.realpath(os.path.join(base, *rest.split("/")))
            if target == base or not target.startswith(base + os.sep):
                return None
            return target if os.path.isfile(target) else None
    return None


def pdf_text(data, limit=TEXT_CHARS):
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        with fitz.open(stream=bytes(data), filetype="pdf") as doc:
            parts = []
            for page in doc:
                parts.append(page.get_text())
                if sum(len(x) for x in parts) > limit:
                    break
        text = " ".join(" ".join(parts).split())
        return text[:limit]
    except Exception:
        return ""


class Found:
    def __init__(self):
        self.files = []          # stored file names
        self.links = []          # http(s) links
        self.texts = []          # (file name, text) of PDFs
        self.notes = []          # what could not be offered, for the model


def _row_name(columns, row, skip):
    """A file name standing in the same row, if there is one."""
    for i, value in enumerate(row):
        if i != skip and isinstance(value, str) and _FILE_NAME.match(value.strip()):
            return os.path.basename(_norm(value.strip()))
    return ""


def _keep(user, found, name, data):
    if len(found.files) >= MAX_FILES:
        found.notes.append(f"{name}: mehr als {MAX_FILES} Dateien, nicht angeboten")
        return None
    if len(data) > MAX_BYTES:
        found.notes.append(f"{name}: groesser als {MAX_BYTES // (1024 * 1024)} MB")
        return None
    stored = created_files.store(user, name, bytes(data))
    found.files.append(stored)
    if stored.lower().endswith(".pdf") and sum(len(t) for _n, t in found.texts) < TEXT_TOTAL:
        text = pdf_text(data)
        if text:
            found.texts.append((stored, text))
    return stored


def collect(user, columns, rows):
    """(rows for the table, Found). Rows come back with binary cells and
    released paths replaced by '[Datei: name]'."""
    found = Found()
    out = []
    for row in rows:
        cells = list(row)
        for i, value in enumerate(cells):
            if isinstance(value, (bytes, bytearray, memoryview)):
                data = bytes(value)
                ext = sniff(data)
                if not ext:
                    cells[i] = f"[Binärdaten, {len(data) // 1024 + 1} KB]"
                    continue
                name = _row_name(columns, cells, i)
                if not name or not name.lower().endswith("." + ext):
                    key = next((str(v) for j, v in enumerate(cells)
                                if j != i and v is not None and not isinstance(v, (bytes, bytearray))),
                               "datei")
                    name = paths.sicherer_dateiname(f"{columns[0] if columns else 'datei'}-{key}")
                    name = f"{name or 'datei'}.{ext}"
                stored = _keep(user, found, name, data)
                cells[i] = f"[Datei: {stored}]" if stored else f"[Datei nicht angeboten: {name}]"
            elif isinstance(value, str):
                text = value.strip()
                if _URL.match(text):
                    if text not in found.links and len(found.links) < 20:
                        found.links.append(text)
                elif _PATH.match(text):
                    local = resolve(text)
                    if local is None:
                        if roots():
                            found.notes.append(f"{text}: liegt nicht in einem freigegebenen Ordner")
                        continue
                    with open(local, "rb") as f:
                        data = f.read(MAX_BYTES + 1)
                    stored = _keep(user, found, os.path.basename(local), data)
                    if stored:
                        cells[i] = f"{text} [Datei: {stored}]"
        out.append(tuple(cells))
    return out, found
