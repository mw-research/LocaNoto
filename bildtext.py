"""Was auf einem Bild steht, als Text -- beim Hochladen.

Zwei Faelle, die verschieden sind und oft verwechselt werden:

  GESCANNTE SEITE   Ein PDF ohne Textebene. Die Seite ist ein Foto,
                    und die Suche findet darin nichts -- nicht wenig,
                    sondern nichts. Hochgeladen, eingelesen, "fertig"
                    gemeldet, und die Datei ist unauffindbar.

  ABBILDUNG         Ein Textdokument mit einem Schaubild darin. Der
                    Text ist da; was fehlt, ist das, was nur im Bild
                    steht -- ein Ablauf, eine Bezeichnung, ein Wert in
                    einer Zeichnung.

Fuer beide entsteht ein Abschnitt mit type="image", der ganz
gewoehnlich durchsucht wird. Die Beschreibung ersetzt das Bild nicht;
sie macht es auffindbar.

WAS DAS KOSTET: ein Modellaufruf je Bild. Ein 200-Seiten-Scan sind 200
Aufrufe, also Minuten. Deshalb ist es ein Schalter am Upload und keine
Selbstverstaendlichkeit -- und deshalb sagt zaehle() VORHER, worauf
man sich einlaesst.
"""
import paths

# Kleiner als das gilt als Logo oder Symbol. Dieselben Werte wie beim
# abgekoppelten Bild-Ingest -- zwei Schwellen fuer dieselbe Frage
# waeren der Anfang davon, dass eine gepflegt wird und die andere
# nicht.
MIN_LONG_EDGE = paths.env_int("MIN_LONG_EDGE", 400)
MIN_AREA = paths.env_int("MIN_AREA", 120_000)

# Ab wie wenig Text auf einer Seite sie als gescannt gilt. Eine Seite
# mit einer Seitenzahl und sonst nichts hat auch Text -- gemeint ist,
# ob etwas zu LESEN ist.
MINDEST_TEXT = paths.env_int("BILD_MINDEST_TEXT", 60)

# Aufloesung, mit der eine gescannte Seite an das Sehmodell geht.
# Hoeher heisst nicht besser: das Modell skaliert ohnehin herunter,
# und jedes Megabyte kostet Uebertragung.
SEITEN_DPI = paths.env_int("BILD_SEITEN_DPI", 150)


def _gross_genug(breite, hoehe):
    return (max(breite, hoehe) >= MIN_LONG_EDGE
            and breite * hoehe >= MIN_AREA)


def _bilder_der_seite(doc, seite):
    """[(bytes, breite, hoehe)] der Abbildungen auf dieser Seite."""
    aus = []
    try:
        if not seite.get_image_info():
            return aus
        for angabe in seite.get_images(full=True):
            xref = angabe[0]
            # get_images() listet das Ressourcenverzeichnis, nicht das,
            # was gezeichnet wird. Teilen sich alle Seiten eines, meldet
            # jede Seite alles -- und dieselbe Abbildung waere auf jeder
            # Seite noch einmal da. Ein unendliches Rechteck heisst:
            # hier kommt sie nicht vor.
            try:
                rahmen = seite.get_image_bbox(angabe)
                if rahmen.is_infinite or rahmen.is_empty:
                    continue
            except Exception:
                continue
            try:
                roh = doc.extract_image(xref)
            except Exception:
                continue
            if _gross_genug(roh.get("width", 0), roh.get("height", 0)):
                aus.append((roh["image"], roh.get("width", 0),
                            roh.get("height", 0)))
    except Exception:
        pass
    return aus


def _wenig_text(seite):
    try:
        return len((seite.get_text() or "").strip()) < MINDEST_TEXT
    except Exception:
        return False


def zaehle(doc):
    """(gescannte_seiten, abbildungen) -- was zu beschreiben waere.

    Gefragt, BEVOR jemand zustimmt. Ein Schalter, der erst hinterher
    zeigt, was er kostet, ist eine Falle: zweihundert Modellaufrufe
    sind Minuten, und wer sie nicht erwartet, haelt die Anwendung fuer
    haengengeblieben.
    """
    seiten = abbildungen = 0
    for nr in range(len(doc)):
        seite = doc.load_page(nr)
        if _wenig_text(seite):
            seiten += 1
        else:
            abbildungen += len(_bilder_der_seite(doc, seite))
    return seiten, abbildungen


def beschreibungen(doc, dateiname, fortschritt=None):
    """[(seitennummer, text, art)] fuer alles Bildliche im Dokument.

    art ist "seite" oder "abbildung" -- der Unterschied gehoert in die
    Beschreibung, weil er etwas ueber die Zuverlaessigkeit sagt: bei
    einer gescannten Seite IST die Beschreibung der Inhalt, bei einer
    Abbildung ist sie eine Ergaenzung zum Text daneben.

    Ein Fehlschlag bei einem Bild kostet nur dieses Bild. Ein
    Sehmodell, das bei Seite 43 nicht antwortet, darf nicht die
    vorherigen zweiundvierzig Beschreibungen wegwerfen.
    """
    import vision
    aus = []
    gesamt = len(doc)
    for nr in range(gesamt):
        seite = doc.load_page(nr)
        if fortschritt:
            fortschritt(nr + 1, gesamt)
        if _wenig_text(seite):
            try:
                bild = seite.get_pixmap(dpi=SEITEN_DPI).tobytes("png")
                text = vision.beschreibe(
                    bild, "Gib den gesamten lesbaren Inhalt dieser Seite "
                          "wieder -- Ueberschriften, Fliesstext, "
                          "Tabellenwerte, Beschriftungen.")
                if text:
                    aus.append((nr + 1, text, "seite"))
            except Exception:
                continue
            continue
        for roh, _b, _h in _bilder_der_seite(doc, seite):
            try:
                text = vision.beschreibe(
                    roh, "Beschreibe, was diese Abbildung zeigt, und gib "
                         "alle darin lesbaren Beschriftungen wieder.")
                if text:
                    aus.append((nr + 1, text, "abbildung"))
            except Exception:
                continue
    return aus
