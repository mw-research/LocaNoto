"""Tabellen-Chunks bauen: Ueberschrift davor, uebergrosse Tabellen aufteilen.

Zwei Gruende fuer dieses Modul:

1. Die Ueberschriftenzeile ueber einer Tabelle ist der wirksamste
   Retrieval-Anker im Korpus -- sie enthaelt in aller Regel
   "<Norm> Tabelle N - <Titel>". ingest.py stellte sie voran, der
   Upload-Pfad in app.py nicht. Ueber die Oberflaeche hochgeladene
   Dokumente bekamen dadurch schlechtere Chunks als die per Skript
   eingelesenen Normen. Beide Pfade rufen jetzt dieselbe Funktion.

2. to_markdown() kann sehr grosse Chunks erzeugen. In der ausgelieferten
   Wissensbasis lag die groesste Tabelle bei 60 267 Zeichen (~15 000 Token,
   DIN EN 1090-4 S. 86). Ein einzelner Vektor darueber ist semantisch
   unbrauchbar, und ein Treffer dieser Groesse verdraengt den restlichen
   Kontext des LLM. Nach der Aufteilung liegt der groesste Chunk bei rund
   6 900 Zeichen.
"""
import os

import pymupdf

from textutils import strip_boilerplate

# Zeichen, nicht Token. ~6000 Zeichen deutscher Tabellentext sind grob
# 1800 Token und bleiben damit deutlich unter jedem Embedding-Limit.
MAX_TABLE_CHARS = int(os.getenv("MAX_TABLE_CHARS", "6000"))

# Hoehe des Streifens ueber der Tabelle, aus dem die Ueberschrift stammt.
CAPTION_HEIGHT = int(os.getenv("CAPTION_HEIGHT", "150"))


def split_markdown_table(md_table, max_chars=None):
    """Teilt eine Markdown-Tabelle und wiederholt den Kopf in jedem Teil."""
    max_chars = max_chars or MAX_TABLE_CHARS
    lines = md_table.splitlines()
    if len(lines) <= 2 or len(md_table) <= max_chars:
        return [md_table]

    # to_markdown() liefert Kopfzeile + Trennzeile, danach die Daten.
    header_text = "\n".join(lines[:2])
    budget = max(max_chars - len(header_text) - 1, 500)

    # Einzelne Zeilen koennen das Budget selbst sprengen: verbundene Zellen
    # werden mit <br> in EINE Zeile aufgeklappt, auf S. 86 der DIN EN 1090-4
    # auf ueber 30 000 Zeichen. Zeilenweises Teilen allein reicht daher nicht.
    body = []
    for line in lines[2:]:
        if len(line) <= budget:
            body.append(line)
        else:
            body.extend(line[i:i + budget] for i in range(0, len(line), budget))

    parts, current, size = [], [], 0
    for line in body:
        if current and size + len(line) + 1 > budget:
            parts.append(header_text + "\n" + "\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append(header_text + "\n" + "\n".join(current))
    return parts


# Wasserzeichen, die DIN quer ueber die Seite legt. strip_boilerplate faengt
# sie zeilenweise ab; der Ausschnitt oberhalb der Tabelle schneidet sie aber
# mitten im Wort durch, sodass Bruchstuecke wie "olled" oder "ted c"
# uebrigbleiben. Gegen ein Fragment hilft kein zeilenverankertes Muster --
# deshalb hier blockweise und ueber Teilstring-Vergleich, was Abschneiden an
# jeder Stelle automatisch abdeckt.
_WATERMARKS = [
    "printed copies are uncontrolled",
    "datum / uhrzeit des ausdrucks",
]
_MIN_FRAGMENT = 4


def _is_watermark_fragment(text):
    t = " ".join(text.lower().split())
    if len(t) < _MIN_FRAGMENT:
        return False
    return any(t in w for w in _WATERMARKS)


def table_caption(page, table, dateiname, seite):
    """Liest den Text direkt oberhalb der Tabelle als Ueberschrift."""
    y0 = table.bbox[1]
    rect = pymupdf.Rect(0, max(0, y0 - CAPTION_HEIGHT), page.rect.width, y0)

    stuecke = []
    for block in page.get_text("blocks", clip=rect):
        text = block[4] if len(block) > 4 else ""
        if not text or _is_watermark_fragment(text):
            continue
        stuecke.append(text)

    caption = strip_boilerplate(" ".join(stuecke)).replace("\n", " ").strip()
    caption = " ".join(caption.split())
    if not caption or len(caption) < 5:
        caption = f"Tabelle aus {dateiname}, Seite {seite}"
    return caption


def build_table_chunks(page, table, dateiname, seite, index, max_chars=None):
    """Baut die Chunks einer Tabelle.

    Liefert eine Liste von (chunk_id_suffix, text). Bei einer Tabelle, die
    unter dem Limit bleibt, ist das genau ein Eintrag mit demselben Suffix
    wie zuvor -- bestehende Chunk-IDs bleiben also stabil und der
    Wiederaufsetz-Mechanismus in ingest.py erkennt sie weiterhin.
    """
    md_table = table.to_markdown()
    caption = table_caption(page, table, dateiname, seite)
    parts = split_markdown_table(md_table, max_chars)

    out = []
    for n, part in enumerate(parts):
        teil = "" if len(parts) == 1 else f" (Teil {n + 1} von {len(parts)})"
        text = (f"KONTEXT ZUR TABELLE: {caption}\n\n"
                f"TABELLE (Seite {seite}){teil}:\n{part}")
        suffix = (f"p{seite}_table_{index}" if len(parts) == 1
                  else f"p{seite}_table_{index}_{n}")
        out.append((suffix, text))
    return out
