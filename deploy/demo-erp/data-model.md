# Datenmodell DemoERP

Beispieldatenbank für LocaNoto (Microsoft SQL Server, Datenbank `DemoERP`, Schema `dbo`). Alle Daten sind erfunden.

## Beziehungen

- Ein **Kunde** hat viele **Aufträge**, ein Auftrag viele **Auftragspositionen**, jede Position verweist auf einen **Artikel**.
- Ein **Kunde** betreibt **Anlagen**; zu jeder Anlage gibt es **Prüfungen**.
- Eine **Reklamation** gehört zu genau einem **Auftrag**.

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
| KundeSeit | date | Beginn der Geschäftsbeziehung |

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

Positionen eines Auftrags. 87 Zeilen.

| Spalte | Typ | Bedeutung |
|---|---|---|
| AuftragsNr | int | Auftrag → Auftraege |
| PosNr | int | Position im Auftrag |
| ArtikelNr | nvarchar(20) | Artikel → Artikel |
| Menge | int | bestellte Menge |
| Einzelpreis | decimal(10,2) | vereinbarter Preis netto je Einheit |
| RabattProzent | decimal(5,2) | Rabatt in Prozent auf die Position |

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

Durchgeführte wiederkehrende Prüfungen der Anlagen. 25 Zeilen.

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

## Beispielfragen

- Welche Aufträge der Meier GmbH sind noch offen?
- Wie hoch ist der Wert der offenen Aufträge je Kunde?
- Welche Prüfungen sind in den nächsten 30 Tagen fällig?
- Wann ist die nächste äußere Prüfung der Anlage AN-0003 fällig?
- Welche Artikel liegen unter dem Mindestbestand?
- Welche Reklamationen sind noch offen, und zu welchem Auftrag gehören sie?
