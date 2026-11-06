# Datenmodell DemoERP

Beispieldatenbank für LocaNoto (Microsoft SQL Server, Datenbank `DemoERP`, Schema `dbo`). Alle Daten sind erfunden.

## Beziehungen

- Ein **Kunde** hat viele **Aufträge**, ein Auftrag viele **Auftragspositionen**, jede Position verweist auf einen **Artikel**.
- Ein **Kunde** betreibt **Anlagen**; zu jeder Anlage gibt es **Prüfungen**.
- Eine **Reklamation** gehört zu genau einem **Auftrag**.
- Ein gelieferter **Auftrag** wird mit einer **Rechnung** an den Kunden berechnet.
- Der **Lagerbestand** eines Artikels liegt auf einem oder mehreren **Lagerplätzen**.
- **Bestellungen** gehen an **Lieferanten** und betreffen je einen **Artikel**.

## Statuswerte

| Tabelle | Spalte | Wert | Bedeutung |
|---|---|---|---|
| Auftraege | Status | O | offen |
| Auftraege | Status | F | in Fertigung |
| Auftraege | Status | G | geliefert |
| Auftraege | Status | S | storniert |
| Pruefungen | Pruefart | A | äußere Prüfung, alle 2 Jahre |
| Pruefungen | Pruefart | I | innere Prüfung, alle 5 Jahre |
| Pruefungen | Pruefart | F | Festigkeitsprüfung, alle 10 Jahre |
| Rechnungen | Status | offen | nichts bezahlt |
| Rechnungen | Status | teilweise bezahlt | ein Teil ist bezahlt |
| Rechnungen | Status | bezahlt | vollständig bezahlt |
| Bestellungen | Status | bestellt | beim Lieferanten bestellt, noch nicht da |
| Bestellungen | Status | geliefert | eingetroffen |

## Tabelle Kunden

Kundenstamm. 10 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| KundenNr | int | Kundennummer (Schlüssel) |
| Firma | nvarchar(100) | Name des Kunden |
| Branche | nvarchar(50) | Branche |
| PLZ | nvarchar(10) | Postleitzahl |
| Ort | nvarchar(50) | Ort |
| Ansprechpartner | nvarchar(80) | Ansprechpartner beim Kunden |
| Email | nvarchar(100) | Mailadresse des Ansprechpartners |
| Telefon | nvarchar(30) | Telefonnummer des Ansprechpartners |
| KundeSeit | date | Beginn der Geschäftsbeziehung |

## Tabelle Lieferanten

Lieferantenstamm. 4 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| LieferantenNr | int | Lieferantennummer (Schlüssel) |
| Firma | nvarchar(100) | Name des Lieferanten |
| Ort | nvarchar(50) | Ort |
| Ansprechpartner | nvarchar(80) | Ansprechpartner beim Lieferanten |
| Telefon | nvarchar(30) | Telefonnummer |
| Email | nvarchar(100) | Mailadresse |

## Tabelle Artikel

Artikelstamm mit Lagerbestand. 13 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| ArtikelNr | nvarchar(20) | Artikelnummer, z. B. DB-2000 (Schlüssel) |
| Bezeichnung | nvarchar(100) | Artikelbezeichnung |
| Warengruppe | nvarchar(50) | Warengruppe |
| Einheit | nvarchar(10) | Mengeneinheit (Stk, m, Set) |
| Listenpreis | decimal(10,2) | Listenpreis netto in EUR je Einheit |
| Lagerbestand | int | aktueller Bestand |
| Mindestbestand | int | unter diesem Bestand nachbestellen |

## Tabelle Auftraege

Kundenaufträge (Kopf). 34 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| AuftragsNr | int | Auftragsnummer (Schlüssel) |
| KundenNr | int | Kunde → Kunden |
| Auftragsdatum | date | Tag der Bestellung |
| Liefertermin | date | zugesagter Liefertermin |
| Status | char(1) | O = offen, F = in Fertigung, G = geliefert, S = storniert |
| Bearbeiter | nvarchar(50) | zuständige Person im Vertrieb |

## Tabelle Auftragspositionen

Positionen eines Auftrags. 82 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| AuftragsNr | int | Auftrag → Auftraege |
| PosNr | int | Position im Auftrag |
| ArtikelNr | nvarchar(20) | Artikel → Artikel |
| Menge | int | bestellte Menge |
| Einzelpreis | decimal(10,2) | vereinbarter Preis netto je Einheit |
| RabattProzent | decimal(5,2) | Rabatt in Prozent auf die Position |

## Tabelle Rechnungen

Ausgangsrechnungen an Kunden. 22 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| RechnungsNr | int | Rechnungsnummer (Schlüssel) |
| AuftragsNr | int | berechneter Auftrag → Auftraege |
| KundenNr | int | Rechnungsempfänger → Kunden |
| Rechnungsdatum | date | Tag der Rechnung |
| Faellig | date | Zahlungsziel |
| Betrag | decimal(12,2) | Rechnungsbetrag brutto in EUR |
| Bezahlt | decimal(12,2) | bisher bezahlter Betrag in EUR |
| BezahltAm | date | Tag der letzten Zahlung, leer wenn nichts bezahlt |
| Status | nvarchar(20) | offen, teilweise bezahlt oder bezahlt |
| Mahnstufe | int | 0 = nicht gemahnt, 1 bis 3 = Mahnstufe |

## Tabelle Lagerplaetze

Wo der Bestand eines Artikels liegt. 17 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| ArtikelNr | nvarchar(20) | Artikel → Artikel |
| Lager | nvarchar(30) | Hauptlager oder Außenlager |
| Lagerplatz | nvarchar(20) | Regal und Fach, z. B. R03-F2 |
| Menge | int | Menge an diesem Platz; die Summe je Artikel ist der Lagerbestand |

## Tabelle Bestellungen

Bestellungen bei Lieferanten (Einkauf). 8 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| BestellNr | int | Bestellnummer (Schlüssel) |
| LieferantenNr | int | Lieferant → Lieferanten |
| ArtikelNr | nvarchar(20) | bestellter Artikel → Artikel |
| Menge | int | bestellte Menge |
| Einkaufspreis | decimal(10,2) | Einkaufspreis netto je Einheit in EUR |
| Bestelldatum | date | Tag der Bestellung |
| ErwartetAm | date | zugesagter Liefertag |
| Status | nvarchar(20) | bestellt, teilgeliefert oder geliefert |

## Tabelle Dokumente

Belege als Datei: Rechnungen und Datenblätter als PDF. 26 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| DokNr | int | Dokumentnummer (Schlüssel) |
| Art | nvarchar(30) | Rechnung oder Datenblatt |
| RechnungsNr | int | zugehörige Rechnung → Rechnungen |
| ArtikelNr | nvarchar(20) | zugehöriger Artikel → Artikel |
| Dateiname | nvarchar(150) | Name der Datei |
| Datei | varbinary(max) | die Datei selbst (PDF) |

## Tabelle Anlagen

Anlagen beim Kunden, die wir prüfen und warten. 10 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| AnlagenNr | nvarchar(20) | Anlagennummer, z. B. AN-0003 (Schlüssel) |
| KundenNr | int | Betreiber der Anlage → Kunden |
| Bezeichnung | nvarchar(100) | Bezeichnung |
| Typ | nvarchar(30) | Druckbehälter, Kompressor oder Dampfkessel |
| Baujahr | int | Baujahr |
| Standort | nvarchar(80) | Aufstellort beim Kunden |

## Tabelle Pruefungen

Durchgeführte wiederkehrende Prüfungen der Anlagen. 23 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| PruefNr | int | Prüfungsnummer (Schlüssel) |
| AnlagenNr | nvarchar(20) | geprüfte Anlage → Anlagen |
| Pruefart | char(1) | A = äußere Prüfung, I = innere Prüfung, F = Festigkeitsprüfung |
| Pruefdatum | date | Tag der Prüfung |
| Ergebnis | nvarchar(20) | ohne Mängel, mit Mängeln oder stillgelegt |
| NaechstePruefung | date | Tag, an dem die nächste Prüfung dieser Art fällig ist |
| Pruefer | nvarchar(50) | prüfende Person |

## Tabelle Reklamationen

Reklamationen zu Aufträgen. 5 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| ReklamationsNr | int | Reklamationsnummer (Schlüssel) |
| AuftragsNr | int | betroffener Auftrag → Auftraege |
| Eingang | date | Tag des Eingangs |
| Grund | nvarchar(200) | Beschreibung des Mangels |
| Status | nvarchar(20) | offen, in Klärung oder erledigt |
| Verantwortlich | nvarchar(50) | zuständige Person |

## Sicht v_OffeneAuftraege

Offene und in Fertigung befindliche Aufträge mit Kunde und Auftragswert.

```sql
SELECT a.AuftragsNr, a.KundenNr, k.Firma, a.Auftragsdatum, a.Liefertermin,
       a.Status, a.Bearbeiter,
       CAST(SUM(p.Menge * p.Einzelpreis * (100 - p.RabattProzent) / 100) AS decimal(12,2)) AS Auftragswert
FROM dbo.Auftraege a
JOIN dbo.Kunden k ON k.KundenNr = a.KundenNr
JOIN dbo.Auftragspositionen p ON p.AuftragsNr = a.AuftragsNr
WHERE a.Status IN ('O', 'F')
GROUP BY a.AuftragsNr, a.KundenNr, k.Firma, a.Auftragsdatum, a.Liefertermin, a.Status, a.Bearbeiter
```

## Sicht v_OffeneRechnungen

Nicht vollständig bezahlte Rechnungen mit Kunde, Restbetrag und Tagen über dem Zahlungsziel.

```sql
SELECT r.RechnungsNr, r.KundenNr, k.Firma, r.AuftragsNr, r.Rechnungsdatum, r.Faellig,
       r.Betrag, r.Bezahlt, r.Betrag - r.Bezahlt AS Restbetrag,
       CASE WHEN r.Faellig < CAST(GETDATE() AS date)
            THEN DATEDIFF(day, r.Faellig, CAST(GETDATE() AS date)) ELSE 0 END AS TageUeberfaellig,
       r.Mahnstufe, r.Status
FROM dbo.Rechnungen r
JOIN dbo.Kunden k ON k.KundenNr = r.KundenNr
WHERE r.Status <> N'bezahlt'
```

## Beispielfragen

- Welche Aufträge der Meier GmbH sind noch offen?
- Wie hoch ist der Wert der offenen Aufträge je Kunde?
- Welche Prüfungen sind in den nächsten 30 Tagen fällig?
- Wann ist die nächste äußere Prüfung der Anlage AN-0003 fällig?
- Welche Artikel liegen unter dem Mindestbestand?
- Welche Reklamationen sind noch offen, und zu welchem Auftrag gehören sie?
- Welche Rechnungen der Meier GmbH sind offen?
- Welche Rechnungen sind überfällig, und wie viel steht insgesamt aus?
- Hat die Schmitt Metallbau KG ihre letzte Rechnung bezahlt?
- Wie viele Manometer haben wir, und wo liegen sie?
- Was ist bei Lieferanten bestellt und noch nicht da?
- Wann kommen die Kondensatableiter?
- Wer ist Ansprechpartner bei Becker Druckluft, mit Telefonnummer?
- Welche Kunden hatten dieses Jahr den größten Umsatz?
- Was hat die Meier GmbH zuletzt bestellt?
- Welche Aufträge betreut K. Lang?
- Zeig mir die Rechnung 2025103. Was steht darauf?
- Gibt es ein Datenblatt zum Kugelhahn?
