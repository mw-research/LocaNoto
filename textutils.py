"""Textbereinigung fuer den Ingest.

Viele Herausgeber versehen heruntergeladene Dokumente mit einer
Druck-Kopfzeile pro Seite (Ausdruckdatum, Lizenznehmer, Benutzerkennung).
Ohne Filter landet dieser Block in einem grossen Teil aller Chunks und
verwaessert deren Embedding -- bei kurzen Dokumenten besonders stark, weil
dort der Anteil pro Chunk am hoechsten ist.

Zusaetzlich entfernt der Filter die Lizenzkennung des Abonnenten, die sonst
mit jeder weitergegebenen Vektordatenbank mitwandert.

Bewusst zeilenbasiert: der Filter laeuft auf dem Seitentext VOR dem
Chunking und schneidet nie mitten in einen Satz.
"""
import re

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
    """Entfernt die DIN-Druckkopfzeile aus einem Seitentext."""
    if not text:
        return text

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
