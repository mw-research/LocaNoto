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
| 3 | ERP, Tabelle Lagerplaetze | Wo liegt der Artikel WA-104? | Lager „Prof. Schiffler“, persönlich, 1 Stück |

Lösung: **Die Tasse hat Prof. Schiffler.**

## Warum es nicht mit einer Frage geht

- Das ERP kennt keine Motive: Die zwölf Tassen heißen dort
  „Kaffeebecher 300 ml, Druck A“ bis „Druck L“ (WA-101 bis WA-112).
  „DIG:IT“, „Tasse“ und „Motiv“ stehen weder in der Datenbank noch im
  Datenbank-Hinweis noch in `data-model.md`.
- Die Bestellung nennt nur die Nummern des Lieferanten (KM-…), keine
  internen. Sie verweist auf den Artikelabgleich.
- Der Artikelabgleich nennt keine Motive, nur Nummernpaare. Die Suche
  findet ihn über die Nummer KM-4715, nicht über „Tasse“ oder „DIG:IT“.
- Die Buchstaben A–L folgen nicht der Reihenfolge der Bestellung.
- Wer alle Becher im ERP auflisten lässt, sieht zwölf Lagerorte und drei
  Einzelstücke (bei Frau Haas, Prof. Schiffler und Prof. Krämer); die
  Bestellung nennt ebenfalls drei Motive mit Menge 1. Welches davon die
  DIG:IT-Tasse ist, zeigt erst der Artikelabgleich.

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
