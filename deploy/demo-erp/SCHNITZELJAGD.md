# Digitale Schnitzeljagd: Wo ist die DIG:IT-Tasse?

Für das Demo-Event. Gesucht ist der Lagerort der DIG:IT-KMU-Tasse. Wer ihn
mit LocaNoto findet, gewinnt die Tasse.

**Diese Datei nicht in LocaNoto hochladen** – sie enthält die Lösung.

## Aufgabe für die Teilnehmenden

> Unser Einkauf hat Tassen mit verschiedenen Motiven bestellt. Eine davon
> trägt das DIG:IT-KMU-Logo und ist ein Einzelstück. Finde mit LocaNoto
> heraus, wo sie liegt – dann gehört sie dir.

Im Chat den Arbeitsbereich der Demo wählen und **Datenbank** anhaken.

## Lösungsweg (drei Fragen)

| Schritt | Quelle | Beispielfrage | Ergebnis |
|---|---|---|---|
| 1 | Dokument „Bestellung Werbeartikel Tassen“ | Welche Artikelnummer hat die Tasse mit dem DIG:IT-Logo? | Lieferanten-Nr. KM-4715 |
| 2 | Dokument „Artikelabgleich Keramik Manufaktur Weber“ | Welche interne Artikelnummer gehört zu KM-4715? | WA-104 |
| 3 | ERP, Tabelle Lagerplaetze | Wo liegt der Artikel WA-104? | Prof. Andreas Schiffler, persönlich, 1 Stück |

Lösung: **Die Tasse hat Prof. Andreas Schiffler.**

## Die Köder

Die Bestellung nennt fünf Einzelstücke (Menge 1), das ERP führt fünf
Werbeartikel mit Bestand 1 – alle bei Leuten aus dem DIG:IT-Team. Wer den
Artikelabgleich überspringt und im ERP nach Einzelstücken sucht, landet mit
vier zu fünf Wahrscheinlichkeit beim Falschen:

| Interne Nr. | Lagerort | Motiv laut Abgleich und Bestellung |
|---|---|---|
| WA-102 | Vladyslav Borysenko | Erdmännchen mit Schutzhelm |
| WA-104 | **Prof. Andreas Schiffler** | **DIG:IT-KMU-Logo** |
| WA-107 | Rodolfo Cacacho | Zahnrad-Muster |
| WA-108 | Markus Wilhelm | Jubiläum „25 Jahre Demo GmbH“ |
| WA-110 | Prof. Bastian Engelmann | Schriftzug „Kein Morgenmensch“ |

Die übrigen sieben Werbeartikel liegen bei anderen Personen oder in Lagern.

## Warum es nicht mit einer Frage geht

- Das ERP führt zu jedem der zwölf Artikel nur interne Nummer (WA-101 bis
  WA-112), Lagerort und Anzahl; die Bezeichnung ist bei allen
  „Werbeartikel“. „DIG:IT“, „Tasse“, „Becher“ und „Motiv“ stehen weder in
  der Datenbank noch im Datenbank-Hinweis noch in `data-model.md`.
- Die Bestellung nennt nur die Nummern des Lieferanten (KM-…), keine
  internen. Sie verweist auf den Artikelabgleich.
- Der Artikelabgleich nennt keine Motive, nur Nummernpaare. Die Suche
  findet ihn über die Nummer KM-4715, nicht über „Tasse“ oder „DIG:IT“.

## Einrichten

1. Demo-ERP neu befüllen (README, Abschnitt 1, „Neu befüllen“).
2. Die beiden Dokumente aus `documents/` in den Arbeitsbereich der Demo
   hochladen: `Bestellung Werbeartikel Tassen.md` und
   `Artikelabgleich Keramik Manufaktur Weber.md`.
3. Einmal selbst durchspielen, in einem neuen Chat.

## Hilfen, wenn jemand festhängt

- Nach Schritt 1: „Die Bestellung nennt die Nummer des Lieferanten. Wo
  steht, welche Nummer das bei uns ist?“
- Nach Schritt 2: „Bestand und Lagerort stehen im ERP – ist Datenbank
  angehakt?“
- Wer beim Köder gelandet ist: „Bist du sicher, dass das die DIG:IT-Tasse
  ist? Was sagt der Artikelabgleich?“
