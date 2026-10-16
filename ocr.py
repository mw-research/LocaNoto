"""Texterkennung fuer gescannte Seiten -- Tesseract ueber pymupdf.

Ein Scan ist ein Foto einer Seite. Ohne Texterkennung findet die Suche
darin nichts, nicht wenig, sondern nichts. Dieses Modul liest solche
Seiten mit Tesseract, auf jedem Weg, auf dem ein Dokument hereinkommt:
Hochladen, Schnittstelle, ingest.py, ownCloud-Abgleich.

Zwei Stufen, und die Reihenfolge ist Absicht:

  1. TEXTERKENNUNG (hier). Schnell, ohne Modellserver, und vor allem:
     ihre Fehler sind sichtbar. Eine unleserliche Stelle wird
     Zeichensalat.
  2. SEHMODELL (bildtext.py), nur fuer Seiten, die hier nichts
     Brauchbares ergeben, und nur auf Wunsch. Es liest schlechte Scans
     und Handschrift besser -- aber wo es nichts erkennt, schreibt es
     einen plausiblen Wert hin, der nicht dasteht. Bei Normen und
     Pruefwerten ist das der gefaehrlichere Fehler.

Bilddateien (TIFF, JPG, PNG) werden zu einem PDF mit je einer Seite pro
Bild; danach gehen sie denselben Weg wie ein gescanntes PDF.

    python ocr.py --probe     liest eine erzeugte Testseite, Ausgang 0/1
"""
import os
import re

import paths

SPRACHEN = os.getenv("OCR_SPRACHEN", "").strip() or "deu+eng"

# 300 dpi ist das, wofuer Tesseract trainiert ist. Weniger kostet
# Erkennungsgenauigkeit bei kleiner Schrift, mehr kostet Zeit ohne Gewinn.
DPI = paths.env_int("OCR_DPI", 300)

# Ab wie wenig Text eine Seite als gescannt gilt -- derselbe Wert, den
# bildtext.py fuer dieselbe Frage benutzt.
MINDEST_TEXT = paths.env_int("BILD_MINDEST_TEXT", 60)

BILD_ENDUNGEN = (".tif", ".tiff", ".jpg", ".jpeg", ".png")

_zustand = None


def verfuegbar():
    """(ja, grund). Ob Tesseract samt allen Sprachen aus OCR_SPRACHEN da ist.

    Einmal je Prozess ermittelt. Fehlt eine Sprache, ist das kein
    "geht nicht", sondern ein stiller Qualitaetsverlust -- deshalb wird
    es als nicht verfuegbar gemeldet und nicht still uebergangen.
    """
    global _zustand
    if _zustand is not None:
        return _zustand
    try:
        import pymupdf
        ordner = pymupdf.get_tessdata()
    except Exception as e:
        _zustand = (False, f"Tesseract nicht gefunden ({type(e).__name__})")
        return _zustand
    fehlt = [s for s in SPRACHEN.split("+")
             if s and not os.path.exists(os.path.join(ordner,
                                                      f"{s}.traineddata"))]
    if fehlt:
        _zustand = (False, f"Sprachdaten fehlen: {', '.join(fehlt)} "
                           f"(in {ordner})")
    else:
        _zustand = (True, f"Tesseract, {SPRACHEN}, {DPI} dpi")
    return _zustand


def ist_bild(name):
    return str(name or "").lower().endswith(BILD_ENDUNGEN)


def oeffne(pfad):
    """Ein Dokument als PDF. Bilddateien werden dabei umgewandelt.

    Umgewandelt und nicht nur geoeffnet: Tabellenerkennung und das
    Schwaerzen der Tabellenflaechen gehen nur auf PDF-Seiten.
    """
    import pymupdf
    doc = pymupdf.open(pfad)
    if doc.is_pdf:
        return doc
    pdf = doc.convert_to_pdf()
    doc.close()
    return pymupdf.open("pdf", pdf)


def ist_scan(seite):
    """Ist diese Seite ein Foto einer Seite?

    Wenig Text allein genuegt nicht: eine Leerseite oder ein Titelblatt
    mit einer Ueberschrift hat auch wenig Text, und sie als "unlesbare
    gescannte Seite" zu melden, waere ein falscher Alarm. Dazu kommen
    muss ein Bild, das mindestens die Haelfte der Seite bedeckt.
    """
    try:
        import pymupdf
        if len((seite.get_text() or "").strip()) >= MINDEST_TEXT:
            return False
        flaeche = abs(seite.rect)
        bedeckt = sum(abs(pymupdf.Rect(i["bbox"]) & seite.rect)
                      for i in seite.get_image_info())
        return flaeche > 0 and bedeckt / flaeche >= 0.5
    except Exception:
        return False


def lies(seite):
    """Der erkannte Text einer Seite, aufgeraeumt. "" wenn nichts zu holen ist."""
    if not verfuegbar()[0]:
        return ""
    try:
        tp = seite.get_textpage_ocr(language=SPRACHEN, dpi=DPI, full=True)
        return aufraeumen(seite.get_text(textpage=tp) or "")
    except Exception:
        return ""


# --- AUFRAEUMEN ---
#
# Mechanisch und ohne Sprachmodell. Ein Modell, das nur den Text sieht,
# kann nicht wissen, was auf der Seite steht: aus "13A45" machte es eine
# plausible Normnummer, aus "1,6 bar" womoeglich "16 bar" -- und der
# Fehler saehe danach aus wie ein Fakt, in der Quelle selbst.
#
# Hier wird deshalb nur geaendert, was sicher ist, und EINE Regel gilt
# ohne Ausnahme: keine Ziffer aendert sich, keine kommt hinzu, keine
# faellt weg. Unicode-Normalisierung (NFKC) ist aus demselben Grund
# ausgeschlossen -- sie machte aus "m²" ein "m2".

# Ligaturen, die Tesseract gelegentlich ausgibt. Nur diese, ausdruecklich.
_LIGATUREN = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
              "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
              "ﬆ": "st"}

# Woerter, vor denen ein Strich am Zeilenende ein Ergaenzungsstrich ist:
# "Ein- und Ausgang" bleibt so, statt zu "Einund" zu werden.
_BINDEWOERTER = ("und", "oder", "bis", "sowie", "bzw", "noch", "als")

_TRENNUNG = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w+)", re.UNICODE)


def _verbinde(treffer):
    vorn, wort = treffer.group(1), treffer.group(2)
    if wort.lower().rstrip(".") in _BINDEWOERTER:
        return f"{vorn}- {wort}"
    # Kleinbuchstabe danach: ein am Zeilenende getrenntes Wort
    # ("Druck-|behaelter"). Sonst -- Grossbuchstabe oder Ziffer -- ist
    # der Strich Teil des Ausdrucks ("DIN-Norm", "13-45") und bleibt.
    if wort[0].islower():
        return f"{vorn}{wort}"
    return f"{vorn}-{wort}"


def aufraeumen(text):
    """OCR-Text fuer Suche und Lesen glaetten, ohne Inhalt zu aendern."""
    t = str(text or "")
    for alt, neu in _LIGATUREN.items():
        t = t.replace(alt, neu)
    t = t.replace("­", "")              # weiches Trennzeichen
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _TRENNUNG.sub(_verbinde, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_ZEICHEN = re.compile(r"[\w]", re.UNICODE)


def brauchbar(text):
    """Taugt das Ergebnis als Text?

    Zwei Bedingungen: genug davon, und ueberwiegend Buchstaben und
    Ziffern. Eine leere oder verrauschte Seite liefert Zeichensalat aus
    Strichen und Satzzeichen -- der ist nicht leer, aber auch nicht
    durchsuchbar, und er soll nicht als gelesen gelten.
    """
    t = "".join(str(text or "").split())
    if len(t) < MINDEST_TEXT:
        return False
    return len(_ZEICHEN.findall(t)) / len(t) >= 0.6


# --- PROBE ---

PROBE_TEXT = "Pruefbericht Kesselanlage 2026 Druckbehaelter Inspection"


def probe_dokument():
    """Ein PDF mit genau einer gescannten Seite, deren Text bekannt ist."""
    import pymupdf
    quelle = pymupdf.open()
    seite = quelle.new_page(width=595, height=842)
    seite.insert_text((60, 120), PROBE_TEXT, fontsize=20)
    seite.insert_text((60, 160), "Pruefdruck 16 bar, naechste Pruefung 2028",
                      fontsize=16)
    bild = seite.get_pixmap(dpi=200)
    scan = pymupdf.open()
    s = scan.new_page(width=595, height=842)
    s.insert_image(s.rect, pixmap=bild)
    return scan


def main():
    import sys
    ja, grund = verfuegbar()
    print(f"Texterkennung: {'bereit' if ja else 'NICHT bereit'} -- {grund}")
    if "--probe" not in sys.argv:
        return 0 if ja else 1
    seite = probe_dokument()[0]
    print(f"Testseite gilt als Scan: {ist_scan(seite)}")
    text = lies(seite)
    erwartet = PROBE_TEXT.split()
    gefunden = [w for w in erwartet if w.lower() in text.lower()]
    print(f"erkannt: {len(gefunden)}/{len(erwartet)} Woerter "
          f"-- {text[:120]!r}")
    ok = ja and ist_scan(seite) and len(gefunden) >= len(erwartet) - 1
    print("PROBE", "BESTANDEN" if ok else "NICHT BESTANDEN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
