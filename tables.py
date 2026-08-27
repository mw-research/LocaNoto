"""Tabellen-Chunks bauen: Ueberschrift davor, uebergrosse Tabellen aufteilen.

Zwei Gruende fuer dieses Modul:

1. Die Ueberschriftenzeile ueber einer Tabelle ist der wirksamste
   Retrieval-Anker im Korpus -- sie enthaelt in aller Regel Nummer und
   Titel der Tabelle. ingest.py stellte sie voran, der Upload-Pfad in
   app.py nicht. Ueber die Oberflaeche hochgeladene Dokumente bekamen
   dadurch schlechtere Chunks als die per Skript eingelesenen. Beide Pfade
   rufen jetzt dieselbe Funktion.

2. to_markdown() kann sehr grosse Chunks erzeugen -- in Tests einzelne
   Tabellen von ueber 60 000 Zeichen, also rund 15 000 Token. Ein einzelner
   Vektor darueber ist semantisch unbrauchbar, und ein Treffer dieser
   Groesse verdraengt den restlichen Kontext des LLM. Mit dem Limit bleibt
   der groesste Chunk im Bereich von MAX_TABLE_CHARS.
"""
import os
import re

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
    # werden mit <br> in EINE Zeile aufgeklappt, im Extremfall auf ueber
    # 30 000 Zeichen. Zeilenweises Teilen allein reicht daher nicht.
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


# Wasserzeichen, die manche Herausgeber quer ueber die Seite legen.
# strip_boilerplate faengt
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


# Der Streifen ueber einer Tabelle enthaelt ausser der Ueberschrift auch die
# laufende Kopfzeile der Seite. Zwei Bestandteile davon muessen raus:
#
# 1. Die gedruckte Seitenzahl als eigener Block. Sie landete sonst am Ende der
#    Ueberschrift ("... Stuetzen einstoeckiger Gebaeude 160") und wurde vom
#    Modell als Fundstelle gelesen: es meldete daraufhin, die Tabelle stehe auf
#    Seite 160 und sei "im Textauszug nicht enthalten" -- obwohl ihre Werte
#    unmittelbar darunter standen.
#
# 2. Abgeschnittene Normbezeichnungen wie "DIN EN 1", die der Ausschnitt aus
#    der Kopfzeile herausschneidet.
#
# Eine VOLLSTAENDIGE Bezeichnung mit Ausgabestand bleibt dagegen
# stehen: sie benennt das Dokument und macht die Ueberschrift als Suchanker
# wertvoller.
_SEITENZAHL = re.compile(r"^\d{1,4}$")
_ABGESCHNITTENE_NORM = re.compile(r"^(DIN\s+)?EN\s+\d{1,5}$", re.I)


def _ist_kopfzeilen_rest(text):
    t = " ".join(text.split())
    return bool(_SEITENZAHL.match(t) or _ABGESCHNITTENE_NORM.match(t))


def table_caption(page, table, dateiname, seite):
    """Liest den Text direkt oberhalb der Tabelle als Ueberschrift."""
    y0 = table.bbox[1]
    rect = pymupdf.Rect(0, max(0, y0 - CAPTION_HEIGHT), page.rect.width, y0)

    # Nach Position sortieren, damit die Ueberschrift in Lesereihenfolge
    # zusammengesetzt wird und nicht in der Reihenfolge, in der pymupdf die
    # Bloecke liefert.
    bloecke = []
    for block in page.get_text("blocks", clip=rect):
        text = block[4] if len(block) > 4 else ""
        if not text or _is_watermark_fragment(text) or _ist_kopfzeilen_rest(text):
            continue
        bloecke.append((block[1], block[0], text))

    stuecke = [t for _, _, t in sorted(bloecke)]

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
