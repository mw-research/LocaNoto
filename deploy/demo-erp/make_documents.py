"""The demo documents as PDFs, laid out like a company's real ones.

    python deploy/demo-erp/make_documents.py      (also run by make_demo_erp.py)

Writes into documents/:

    Pruefvorschrift Druckbehaelter.pdf        QM document, inspection kinds and intervals
    Handbuch Reklamationsprozess.pdf          QM manual chapter, complaint handling
    Bestellung Werbeartikel Tassen.pdf        purchase order to the mug supplier (hunt, step 1)
    Artikelabgleich Keramik Manufaktur Weber.pdf
                                              supplier -> internal numbers (hunt, step 2)

Built with reportlab and its standard fonts, without images: the bytes are
the same on every machine (CI compares them), and reading them into
LocaNoto needs no vision model. Tables are drawn with lines, so the PDF
reader of LocaNoto (find_tables) keeps each row together.
"""
import os

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

rl_config.invariant = 1          # no creation date, no random id: same bytes every run

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "documents")

BRAND = colors.HexColor("#23395B")       # Demo GmbH's dark blue
ACCENT = colors.HexColor("#E07A1F")      # its orange
LIGHT = colors.HexColor("#EEF1F5")
GREY = colors.HexColor("#5F6B7A")

COMPANY = "Demo GmbH"
TAGLINE = "Prüf- und Druckbehältertechnik"
ADDRESS = ["Industriestraße 5", "97424 Schweinfurt", "Tel. 09721 5550-0",
           "info@demo-gmbh.example"]
FOOTER = (f"{COMPANY} · Industriestraße 5 · 97424 Schweinfurt · Amtsgericht Schweinfurt "
          "HRB 0000 · Beispieldokument, alle Angaben erfunden")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10, textColor=GREY)
TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=17, leading=21,
                       textColor=BRAND, spaceAfter=4)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15,
                    textColor=BRAND, spaceBefore=10, spaceAfter=4)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11.5)
CELL_HEAD = ParagraphStyle("cellhead", parent=CELL, fontName="Helvetica-Bold",
                           textColor=colors.white)
RIGHT = ParagraphStyle("right", parent=CELL, alignment=TA_RIGHT)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=12, bulletIndent=2)


class _Numbered(rl_canvas.Canvas):
    """'Seite x von y' needs the page count, known only at the end."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(GREY)
            self.drawRightString(A4[0] - 20 * mm, 12 * mm,
                                 f"Seite {self._pageNumber} von {total}")
            super().showPage()
        super().save()


def _letterhead(c, doc):
    """Company name, address and footer on every page."""
    c.saveState()
    w, h = A4
    c.setFillColor(BRAND)
    c.rect(20 * mm, h - 27 * mm, 4 * mm, 12 * mm, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(25 * mm, h - 27 * mm, 1.5 * mm, 12 * mm, fill=1, stroke=0)
    c.setFillColor(BRAND)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(30 * mm, h - 21 * mm, "DEMO GmbH")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(GREY)
    c.drawString(30 * mm, h - 26 * mm, TAGLINE)
    y = h - 15 * mm
    for line in ADDRESS:
        c.drawRightString(w - 20 * mm, y, line)
        y -= 3.6 * mm
    c.setStrokeColor(BRAND)
    c.setLineWidth(0.6)
    c.line(20 * mm, h - 31 * mm, w - 20 * mm, h - 31 * mm)
    c.setStrokeColor(colors.HexColor("#C9D1DB"))
    c.line(20 * mm, 17 * mm, w - 20 * mm, 17 * mm)
    c.setFont("Helvetica", 7)
    c.drawString(20 * mm, 12 * mm, FOOTER)
    c.restoreState()


def _doc(name, title):
    return SimpleDocTemplate(os.path.join(OUT, name), pagesize=A4, title=title,
                             author=COMPANY, leftMargin=20 * mm, rightMargin=20 * mm,
                             topMargin=38 * mm, bottomMargin=24 * mm)


def _build(doc, story):
    doc.build(story, onFirstPage=_letterhead, onLaterPages=_letterhead,
              canvasmaker=_Numbered)


def _p(text, style=CELL):
    return Paragraph(text, style)


def table(rows, widths, head=True, zebra=True, align_right=()):
    """Rows of strings; the first row is the head. Lines on every cell."""
    data = []
    for r, row in enumerate(rows):
        cells = []
        for c_, value in enumerate(row):
            style = CELL_HEAD if head and r == 0 else (RIGHT if c_ in align_right else CELL)
            cells.append(_p(value, style))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AA6B4")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), BRAND))
    if zebra:
        for r in range(2 if head else 1, len(rows), 2):
            style.append(("BACKGROUND", (0, r), (-1, r), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def control_block(kind, number, revision, valid, scope, made, checked, released):
    """The document control box of a QM document."""
    rows = [[f"<b>Dokumentart</b><br/>{kind}", f"<b>Dokument-Nr.</b><br/>{number}",
             f"<b>Revision</b><br/>{revision}", f"<b>Gültig ab</b><br/>{valid}"],
            [f"<b>Geltungsbereich</b><br/>{scope}", f"<b>Erstellt</b><br/>{made}",
             f"<b>Geprüft</b><br/>{checked}", f"<b>Freigegeben</b><br/>{released}"]]
    return table(rows, [48 * mm, 40 * mm, 40 * mm, 42 * mm], head=False, zebra=False)


def bullets(items):
    return [Paragraph(text, BULLET, bulletText="•") for text in items]


# --- the documents --------------------------------------------------------------

def inspection_rule():
    story = [control_block("Prüfvorschrift", "PV-07", "3", "01.03.2026",
                           "Service, Außendienst", "K. Lang", "M. Roth", "Geschäftsleitung"),
             Spacer(1, 8 * mm),
             Paragraph("Prüfvorschrift Druckbehälter", TITLE),
             Paragraph("Gilt für alle Druckbehälter, Kompressoren und Dampfkessel, die wir bei "
                       "Kunden prüfen und warten (Tabelle Anlagen im Demo-ERP).", BODY),
             Paragraph("1. Prüfarten und Fristen", H2),
             table([["Prüfart", "Kürzel im ERP", "Frist"],
                    ["Äußere Prüfung", "A", "alle 2 Jahre"],
                    ["Innere Prüfung", "I", "alle 5 Jahre"],
                    ["Festigkeitsprüfung", "F", "alle 10 Jahre"]],
                   [70 * mm, 40 * mm, 60 * mm]),
             Spacer(1, 3 * mm),
             Paragraph("Die Frist beginnt mit dem Tag der letzten Prüfung derselben Art. Das "
                       "Fälligkeitsdatum steht im ERP in der Spalte NaechstePruefung. Die Fristen "
                       "lehnen sich an die Höchstfristen der Betriebssicherheitsverordnung an; im "
                       "Einzelfall gilt die Festlegung der zugelassenen Überwachungsstelle (ZÜS).",
                       BODY),
             Paragraph("2. Ablauf einer Prüfung", H2),
             table([["Schritt", "Tätigkeit", "Verantwortlich"],
                    ["1", "Termin spätestens 4 Wochen vor Fälligkeit mit dem Kunden abstimmen.",
                     "Service-Disposition"],
                    ["2", "Anlage drucklos machen und gegen Wiedereinschalten sichern.",
                     "Kunde mit Prüfer"],
                    ["3", "Bei der inneren Prüfung: Behälter entleeren, reinigen, Mannloch öffnen.",
                     "Kunde"],
                    ["4", "Prüfung durchführen, Ergebnis im ERP erfassen: ohne Mängel, mit "
                          "Mängeln oder stillgelegt.", "Prüfer"],
                    ["5", "Prüfbescheinigung an den Kunden senden, nächste Fälligkeit eintragen.",
                     "Service-Disposition"]],
                   [18 * mm, 107 * mm, 45 * mm]),
             Paragraph("3. Mängel", H2),
             *bullets(["<b>Mit Mängeln:</b> Mängel innerhalb von 4 Wochen beheben, Nachprüfung "
                       "vereinbaren.",
                       "<b>Stillgelegt:</b> Anlage darf nicht betrieben werden. Kunde sofort "
                       "schriftlich informieren, Vertrieb und Geschäftsleitung in Kopie."]),
             Paragraph("4. Zuständigkeit", H2),
             Paragraph("Prüfungen der Kategorie IV führt die ZÜS durch, alle übrigen eine "
                       "befähigte Person der Demo GmbH. Ansprechpartner intern: Abteilung Service.",
                       BODY),
             Paragraph("5. Mitgeltende Unterlagen", H2),
             *bullets(["Betriebssicherheitsverordnung (BetrSichV), §§ 15 und 16",
                       "Handbuch Reklamationsprozess (QM-HB-8.7)",
                       "Prüfbescheinigung, Formular FB-07-1"]),
             KeepTogether([Paragraph("Änderungshistorie", H2),
                           table([["Revision", "Datum", "Änderung"],
                                  ["1", "15.01.2022", "Erstausgabe"],
                                  ["2", "01.06.2024", "Dampfkessel aufgenommen"],
                                  ["3", "01.03.2026", "Kürzel im ERP ergänzt, Ablauf als Tabelle"]],
                                 [25 * mm, 30 * mm, 115 * mm])])]
    _build(_doc("Pruefvorschrift Druckbehaelter.pdf", "Prüfvorschrift Druckbehälter"), story)


def complaint_manual():
    story = [control_block("QM-Handbuch, Kapitel 8.7", "QM-HB-8.7", "5", "01.09.2025",
                           "Vertrieb, Service, Einkauf", "S. Braun", "T. Krause", "Geschäftsleitung"),
             Spacer(1, 8 * mm),
             Paragraph("Handbuch Reklamationsprozess", TITLE),
             Paragraph("Beschreibt, wie wir mit Reklamationen zu Aufträgen umgehen (Tabelle "
                       "Reklamationen im Demo-ERP). Ziel: jede Reklamation ist innerhalb von zehn "
                       "Arbeitstagen abgeschlossen.", BODY),
             Paragraph("1. Ablauf auf einen Blick", H2),
             table([["Schritt", "Was passiert", "Frist", "Status im ERP"],
                    ["Eingang", "Reklamation im ERP erfassen, mit Auftrag, Beschreibung des "
                                "Mangels und zuständiger Person. Eingangsbestätigung an den Kunden.",
                     "am Tag des Eingangs; Bestätigung binnen 24 Stunden", "offen"],
                    ["Klärung", "Prüfen, ob der Mangel berechtigt ist.", "3 Arbeitstage",
                     "in Klärung"],
                    ["Lösung", "Vorgehen nach Fall (Abschnitt 3).", "siehe Abschnitt 3",
                     "in Klärung"],
                    ["Abschluss", "Lösung dem Kunden schriftlich bestätigen.", "–", "erledigt"]],
                   [24 * mm, 82 * mm, 38 * mm, 26 * mm]),
             Paragraph("2. Sicherheitsbauteile", H2),
             Paragraph("Bei Sicherheitsbauteilen (Sicherheitsventile, Druckbehälter, Manometer) "
                       "wird das Teil sofort gesperrt und der Service informiert. Ein reklamiertes "
                       "Sicherheitsventil wird nicht nachjustiert, sondern immer getauscht.", BODY),
             Paragraph("3. Lösung nach Fall", H2),
             table([["Fall", "Vorgehen"],
                    ["Falsche oder fehlende Lieferung", "Nachlieferung innerhalb von 2 Arbeitstagen"],
                    ["Transportschaden", "Ersatz liefern, Schaden beim Spediteur melden"],
                    ["Defekt innerhalb der Gewährleistung",
                     "Austausch oder Gutschrift nach Wahl des Kunden"],
                    ["Bedienfehler", "Kulanz mit der Vertriebsleitung abstimmen"]],
                   [65 * mm, 105 * mm]),
             Paragraph("4. Auswertung", H2),
             *bullets(["Häufen sich Reklamationen zu einem Artikel (drei in einem Quartal), "
                       "prüft der Einkauf den Lieferanten.",
                       "Die Qualitätsleitung wertet die Reklamationen quartalsweise aus und "
                       "berichtet in der Managementbewertung."]),
             KeepTogether([Paragraph("Änderungshistorie", H2),
                           table([["Revision", "Datum", "Änderung"],
                                  ["4", "01.02.2024", "Sicherheitsbauteile aufgenommen"],
                                  ["5", "01.09.2025", "Status im ERP je Schritt ergänzt"]],
                                 [25 * mm, 30 * mm, 115 * mm])])]
    _build(_doc("Handbuch Reklamationsprozess.pdf", "Handbuch Reklamationsprozess"), story)


# (supplier number, motif, quantity, unit price) -- quantity 1 = single piece
MUGS = [
    ("KM-4711", "THWS-Logo, blau auf weiß", 50, 7.80),
    ("KM-4712", "Winterlandschaft mit Schriftzug „Frohe Festtage“", 30, 7.80),
    ("KM-4714", "Roboter mit offenem Buch (LocaNoto)", 24, 8.40),
    ("KM-4715", "DIG:IT-KMU-Logo, lime auf navy", 1, 14.90),
    ("KM-4718", "Würzburger Residenz, Strichzeichnung", 1, 0.00),
    ("KM-4719", "Skyline Schweinfurt bei Nacht", 20, 8.40),
    ("KM-4721", "Schriftzug „Ingenieure trinken Kaffee“", 40, 7.20),
    ("KM-4723", "Zahnrad-Muster, silber", 1, 0.00),
    ("KM-4726", "Erdmännchen mit Schutzhelm (Comic)", 1, 0.00),
    ("KM-4727", "Schriftzug „Kein Morgenmensch“", 1, 0.00),
    ("KM-4730", "Messe-Edition „Druckluft 2026“", 60, 7.20),
    ("KM-4732", "Jubiläum „25 Jahre Demo GmbH“, Goldrand", 1, 24.50),
]


def _eur(v):
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def mug_order():
    address = Table([[_p("<font size=7 color='#5F6B7A'>Demo GmbH · Industriestraße 5 · "
                         "97424 Schweinfurt</font><br/><br/>Keramik Manufaktur Weber<br/>"
                         "Frau Lena Weber<br/>Vertrieb Werbekeramik<br/>Porzellanstraße 12<br/>"
                         "95100 Selb", BODY),
                      table([["Bestellung Nr.", "EK-2026-0815"], ["Datum", "14.10.2026"],
                             ["Unsere Lieferanten-Nr.", "70005"],
                             ["Ihre Kunden-Nr.", "D-31842"], ["Bearbeitet von", "Frau Haas, Einkauf"],
                             ["Telefon", "09721 5550-31"]],
                            [40 * mm, 32 * mm], head=False, zebra=False)]],
                    colWidths=[98 * mm, 72 * mm])
    address.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (0, 0), 0)]))
    rows = [["Pos.", "Ihre Art.-Nr.", "Motiv", "Menge", "Einzelpreis", "Gesamt"]]
    total = 0.0
    for i, (nr, motif, qty, price) in enumerate(MUGS, start=1):
        total += qty * price
        rows.append([str(i), nr, motif, f"{qty} Stk", "kostenfrei" if not price
                     else _eur(price), _eur(qty * price)])
    rows.append(["", "", "<b>Summe netto</b>", "", "", f"<b>{_eur(total)}</b>"])
    rows.append(["", "", "zzgl. 19 % MwSt.", "", "", _eur(total * 0.19)])
    rows.append(["", "", "<b>Gesamtbetrag</b>", "", "", f"<b>{_eur(total * 1.19)}</b>"])
    story = [address, Spacer(1, 6 * mm),
             Paragraph("Bestellung Werbeartikel: Tassen mit Motiv", TITLE),
             Paragraph("Sehr geehrte Frau Weber,<br/>wir bestellen zu Ihrem Angebot AN-2026-112 "
                       "vom 02.10.2026 folgende Kaffeebecher 300 ml, weißes Porzellan, "
                       "spülmaschinenfest, Rundumdruck. Die Artikelnummern sind Ihre "
                       "Lieferanten-Artikelnummern.", BODY),
             Spacer(1, 4 * mm),
             table(rows, [11 * mm, 20 * mm, 67 * mm, 17 * mm, 27 * mm, 28 * mm],
                   align_right=(3, 4, 5)),
             Spacer(1, 3 * mm),
             Paragraph("<b>Einzelstücke:</b> Die sechs Motive mit Menge 1 sind Einzelstücke: Residenz, Zahnrad, "
                       "Erdmännchen und „Kein Morgenmensch“ sind Ihre Musterdrucke, die "
                       "Jubiläumstasse geht an unsere Geschäftsführung, die DIG:IT-KMU-Tasse ist "
                       "der Preis beim Demo-Event.", BODY),
             KeepTogether([
             Paragraph("Lieferung und Wareneingang", H2),
             *bullets(["Liefertermin: KW 45/2026, frei Haus, Lieferanschrift wie oben.",
                       "Zahlung: 30 Tage netto nach Rechnungseingang.",
                       "Beim Wareneingang vergibt unser Einkauf für jeden Lieferantenartikel eine "
                       "interne Artikelnummer. Die Zuordnung steht im Artikelabgleich Keramik "
                       "Manufaktur Weber, nicht in dieser Bestellung. Bestand und Lagerort führt "
                       "unser ERP unter der internen Nummer."]),
             Spacer(1, 5 * mm),
             Paragraph("Mit freundlichen Grüßen<br/><br/>i. A. Haas<br/>"
                       "<font size=8 color='#5F6B7A'>Einkauf, Demo GmbH</font>", BODY)])]
    _build(_doc("Bestellung Werbeartikel Tassen.pdf", "Bestellung EK-2026-0815"), story)


# supplier number -> internal number; no motif here, on purpose (hunt, step 2)
MATCH = [("KM-4711", "WA-109"), ("KM-4712", "WA-101"), ("KM-4714", "WA-106"),
         ("KM-4715", "WA-104"), ("KM-4718", "WA-111"), ("KM-4719", "WA-103"),
         ("KM-4721", "WA-112"), ("KM-4723", "WA-107"), ("KM-4726", "WA-102"),
         ("KM-4727", "WA-110"), ("KM-4730", "WA-105"), ("KM-4732", "WA-108")]


def article_match():
    head = table([["Lieferant", "Keramik Manufaktur Weber, Selb"],
                  ["Lieferanten-Nr.", "70005"],
                  ["Bezug", "Bestellung EK-2026-0815, Wareneingang WE-2026-1477"],
                  ["Stand", "05.11.2026"], ["Gepflegt von", "Einkauf (Frau Haas)"]],
                 [40 * mm, 130 * mm], head=False, zebra=False)
    rows = [["Lieferanten-Artikelnr.", "Interne Artikelnr.", "Einheit", "Warengruppe",
             "Abgeglichen"]]
    for supplier_nr, internal in MATCH:
        rows.append([supplier_nr, internal, "Stk", "Werbemittel", "05.11.2026"])
    story = [Paragraph("Artikelabgleich Keramik Manufaktur Weber", TITLE),
             Paragraph("Interne Liste des Einkaufs. Ordnet die Artikelnummern des Lieferanten "
                       "den internen Artikelnummern im ERP zu.", BODY),
             Spacer(1, 5 * mm), head, Spacer(1, 6 * mm),
             table(rows, [42 * mm, 36 * mm, 20 * mm, 36 * mm, 36 * mm]),
             Spacer(1, 5 * mm),
             Paragraph("Bestand und Lagerort eines Artikels stehen im ERP unter der internen "
                       "Artikelnummer (Tabelle Lagerplaetze).", BODY)]
    _build(_doc("Artikelabgleich Keramik Manufaktur Weber.pdf",
                "Artikelabgleich Keramik Manufaktur Weber"), story)


def main():
    os.makedirs(OUT, exist_ok=True)
    inspection_rule()
    complaint_manual()
    mug_order()
    article_match()
    return sorted(n for n in os.listdir(OUT) if n.endswith(".pdf"))


if __name__ == "__main__":
    print("written:", ", ".join(main()))
