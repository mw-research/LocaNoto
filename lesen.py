"""Word, Markdown und einfache Textdateien in Abschnitte zerlegen.

PDFs haben Seiten, und der Ingest baut darauf: er merkt sich die zuletzt
geschriebene Seite, isoliert Tabellen ueber ihre Flaeche und entfernt
laufende Kopfzeilen. Nichts davon gibt es in einer Word-Datei oder einem
Markdown-Text -- dort gibt es Ueberschriften.

Deshalb ein eigener Leser statt eines Umbaus des PDF-Wegs. Er liefert
Abschnitte, und ein Abschnitt tritt an die Stelle einer Seite: er wird
gezaehlt, er steht in den Metadaten, und die Quellenangabe nennt ihn.

Die Ueberschrift bleibt im Text des Abschnitts stehen. Das ist dieselbe
Erfahrung wie bei den Tabellen: die Zeile darueber ist der wirksamste
Anker im Bestand, und ein Abschnitt ohne sie ist schwerer zu finden als
einer mit.
"""
import os
import re

ENDUNGEN = (".docx", ".md", ".markdown", ".txt")

# Ueberschriften in Markdown. setext-Ueberschriften (Unterstreichung mit ===
# oder ---) sind selten genug, um sie nicht zu behandeln.
_MD_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)


def unterstuetzt(name):
    return name.lower().endswith(ENDUNGEN)


# --- MARKDOWN UND TEXT ---

def _markdown(pfad):
    with open(pfad, "r", encoding="utf-8", errors="replace") as f:
        roh = f.read()

    stellen = [(m.start(), m.group(2).strip()) for m in
               _MD_UEBERSCHRIFT.finditer(roh)]
    if not stellen:
        # Ohne Ueberschriften ist die Datei ein einziger Abschnitt. Das
        # Zerteilen in Chunks uebernimmt danach der Splitter.
        if roh.strip():
            yield 1, "", roh
        return

    # Was vor der ersten Ueberschrift steht, geht sonst verloren.
    if roh[:stellen[0][0]].strip():
        yield 1, "", roh[:stellen[0][0]]

    for n, (start, titel) in enumerate(stellen, start=1):
        ende = stellen[n][0] if n < len(stellen) else len(roh)
        text = roh[start:ende]
        if text.strip():
            yield n + 1, titel, text


# --- WORD ---

def _docx(pfad):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(pfad)
    koerper = doc.element.body

    nummer = 0
    titel = ""
    sammlung = []

    def fertig():
        text = "\n".join(sammlung).strip()
        return (nummer, titel, text) if text else None

    for kind in koerper.iterchildren():
        marke = kind.tag.split("}")[-1]

        if marke == "p":
            absatz = Paragraph(kind, doc)
            text = absatz.text.strip()
            stil = (absatz.style.name or "") if absatz.style else ""
            # "Heading 1" im englischen, "Ueberschrift 1" im deutschen Word.
            ist_ueberschrift = bool(text) and (
                stil.lower().startswith("heading")
                or stil.lower().startswith("überschrift")
                or stil.lower().startswith("ueberschrift"))
            if ist_ueberschrift:
                eintrag = fertig()
                if eintrag:
                    yield eintrag[0], eintrag[1], eintrag[2]
                nummer += 1
                titel = text
                sammlung = [text]
            elif text:
                if not sammlung and not nummer:
                    nummer = 1
                sammlung.append(text)

        elif marke == "tbl":
            # Eine Tabelle wird ein eigener Abschnitt, mit der zuletzt
            # gesehenen Ueberschrift davor -- genau wie beim PDF, wo die
            # Zeile ueber der Tabelle vorangestellt wird.
            tabelle = Table(kind, doc)
            zeilen = []
            for zeile in tabelle.rows:
                zellen = [z.text.strip().replace("\n", " ") for z in zeile.cells]
                if any(zellen):
                    zeilen.append("| " + " | ".join(zellen) + " |")
            if not zeilen:
                continue
            if len(zeilen) > 1:
                spalten = zeilen[0].count("|") - 1
                zeilen.insert(1, "|" + "|".join("---" for _ in range(spalten)) + "|")
            eintrag = fertig()
            if eintrag:
                yield eintrag[0], eintrag[1], eintrag[2]
            sammlung = []
            nummer += 1
            kopf = f"KONTEXT ZUR TABELLE: {titel}\n\n" if titel else ""
            yield nummer, titel, kopf + "\n".join(zeilen)

    eintrag = fertig()
    if eintrag:
        yield eintrag[0], eintrag[1], eintrag[2]


def abschnitte(pfad):
    """(nummer, ueberschrift, text) je Abschnitt einer Datei.

    Die Nummer tritt an die Stelle der Seitenzahl: sie steht in den
    Metadaten und in der Quellenangabe.
    """
    endung = os.path.splitext(pfad)[1].lower()
    if endung == ".docx":
        yield from _docx(pfad)
    elif endung in (".md", ".markdown", ".txt"):
        yield from _markdown(pfad)
    else:
        raise ValueError(f"Kein unterstuetztes Format: {endung}")
