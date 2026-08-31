"""Textbereinigung fuer den Ingest.

Viele Herausgeber versehen heruntergeladene Dokumente mit einer
Druck-Kopfzeile pro Seite (Ausdruckdatum, Lizenznehmer, Benutzerkennung).
Ohne Filter landet dieser Block in einem grossen Teil aller Chunks. Er
geht damit in deren Embedding ein und verringert den Anteil des eigentlichen
Inhalts -- bei kurzen Dokumenten am staerksten, weil dort sein Anteil pro
Chunk am hoechsten ist.

Zusaetzlich entfernt der Filter die Lizenzkennung des Abonnenten, die sonst
mit jeder weitergegebenen Vektordatenbank mitwandert.

Bewusst zeilenbasiert: der Filter laeuft auf dem Seitentext VOR dem
Chunking und schneidet nie mitten in einen Satz.
"""
import re
import unicodedata

# Zeilen, die vollstaendig entfernt werden (Praefix-Match, case-insensitiv).
_DROP_LINE = [
    re.compile(r"^\s*Datum\s*/\s*Uhrzeit des Ausdrucks\s*:", re.I),
    re.compile(r"^\s*Firmenname\s*:", re.I),
    re.compile(r"^\s*Benutzername\s*:", re.I),
    re.compile(r"^\s*Printed copies are uncontrolled", re.I),
    re.compile(r"^\s*www\.din\.de\s*$", re.I),
    re.compile(r"^\s*DIN Deutsches Institut f.r Normung e\.\s*V\..{0,40}"
               r"Jede Art der Vervielf.ltigung", re.I),
]

# Reste, die nach dem Schwaerzen von Tabellen als Fragment stehenbleiben.
_DROP_INLINE = [
    re.compile(r"Datum\s*/\s*Uhrzeit des Ausdrucks\s*:\s*[\d\-]{10},?\s*[\d:]{0,8}", re.I),
    re.compile(r"Benutzername:\s*\S+@\S+", re.I),
]


def strip_boilerplate(text: str) -> str:
    """Entfernt die Druck-Kopfzeile aus einem Seitentext und normalisiert ihn.

    Zur Normalisierung: manche PDFs liefern ueber page.get_text() zerlegte
    Umlaute -- "Stuetzen" steht dann als u plus kombinierendes Trema statt als
    ein Zeichen (NFD). Gemessen an einem Korpus von 732 Seiten betraf das
    30 %, konzentriert auf einzelne Dokumente.

    Die Suche stoert das nicht: FTS5 normalisiert mit remove_diacritics beide
    Seiten. Sichtbar wird es aber in der Antwort -- das Sprachmodell liest den
    Chunk so, wie er dasteht, und gibt "Stumpfnahte" statt "Stumpfnaehte" aus.
    NFC setzt die Zeichen wieder zusammen.
    """
    if not text:
        return text

    text = unicodedata.normalize("NFC", text)

    kept = []
    for line in text.split("\n"):
        if any(p.search(line) for p in _DROP_LINE):
            continue
        for p in _DROP_INLINE:
            line = p.sub("", line)
        kept.append(line)

    out = "\n".join(kept)
    # Durch die Entfernung entstandene Leerzeilen-Kaskaden einebnen.
    return re.sub(r"\n{3,}", "\n\n", out).strip()
