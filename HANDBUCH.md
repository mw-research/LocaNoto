# LocaNoto – Handbuch

LocaNoto beantwortet Fragen aus den eigenen Unterlagen eines Hauses: aus
hochgeladenen Dokumenten, auf Wunsch auch aus Listen (Excel, CSV), einer
Fachdatenbank und angebundenen Postfächern. Alles läuft auf eigenen
Servern.

Teil 1 ist **für Nutzer**, Teil 2 **für Admins**. Jeder Abschnitt
beantwortet eine Frage und ist für sich verständlich. Die technische
Referenz steht in der `REFERENZ.md`.

## Teil 1: LocaNoto benutzen (für Nutzer)

Anmelden, Fragen stellen, Quellen lesen, Dokumente hochladen, Chats,
Arbeitsbereiche, Voreinstellungen, Listen, Datenbank, Postfächer, Passwort
und Zugangstoken in LocaNoto.

### Was ist LocaNoto und woher kommen die Antworten?

Frage stellen → LocaNoto sucht die passenden Abschnitte in deinen
Dokumenten (nach Bedeutung und nach Stichworten), ein Sprachmodell
formuliert daraus die Antwort. Unter jeder Antwort stehen die Quellen mit
Datei und Seite.

Durchsucht werden nur die Arbeitsbereiche, die du sehen darfst. Steht
etwas nicht im Bestand, sagt die Antwort das.

Die Leiste oben hat diese Seiten:

- **Chat** – Fragen stellen; links die Liste deiner Chats
- **Dokumente** – hochladen, verschieben, löschen
- **Quellen im Netz** – Suchen im Internet, Treffer übernehmen
- **Tickets** – nur, wenn du Mitglied eines Ticketsystems bist
- **Einstellungen** – Sprache, Anweisung, Voreinstellungen, Passwort,
  Postfächer, Datenbanken, Listen, API-Token
- **Admin** – nur für Admins

Rechts daneben stehen dein Name und **Abmelden**.

### Wie melde ich mich bei LocaNoto an und ab?

- Anmelden: **Name** und **Passwort** eingeben → **Anmelden**. Den
  Zugang legt ein Admin an. Ist ein Firmenverzeichnis angebunden, geht
  auch **Mit dem Firmenkonto anmelden**.
- Abmelden: **Abmelden** oben rechts.
- Längere Zeit keine Eingabe (Vorgabe: 480 Minuten) → die Anmeldung endet
  von selbst; erneut anmelden.
- Seite reagiert nach einem Update nicht → Seite neu laden und erneut
  anmelden.

### Wie stelle ich LocaNoto auf Englisch um?

**Einstellungen** → **Sprache** → Deutsch oder English wählen →
**Speichern**. Die Wahl gilt sofort und wird für deinen Zugang gemerkt.
Auf der Anmeldeseite stellt **Deutsch · English** unter dem Formular die
Sprache dieser Seite um; dieser Browser behält sie.

Fragen kannst du in jeder Sprache: LocaNoto antwortet in der Sprache der
Frage, auch bei deutschen Dokumenten. Dateinamen, Werte und Zitate bleiben
wie im Dokument.

### Wie stelle ich LocaNoto eine Frage?

- Seite **Chat**: Frage ins Eingabefeld unten (**Frage an deine Dokumente
  ...**) schreiben → **Senden**.
- Bild anhängen (png, jpg, webp, gif, bmp) über das Dateifeld neben
  **Senden** → LocaNoto beschreibt es und bezieht es ein.
- Nachfrage im selben Chat → bezieht sich auf den bisherigen Verlauf.

Unter dem Eingabefeld öffnet **Arbeitsbereiche · Modell** die Optionen der
Frage: Arbeitsbereiche, Modell, Voreinstellung und, falls eingerichtet,
Listen, Websuche, Datenbank und „nur intern“.

Steht unter einer Antwort „Die Antwort wurde abgebrochen.“, mit **Nochmal
fragen** erneut stellen.

### Woran sehe ich in LocaNoto, woher eine Antwort stammt?

Unter jeder Antwort steht **Quellen (n)**. Aufklappen → je Fundstelle
**Datei · Seite n** mit dem Textabschnitt, auf den sich die Antwort stützt.

- **↗** (In neuem Tab öffnen) → zeigt die Fundstelle auf einer eigenen
  Seite.
- Verweis im Antworttext anklicken → öffnet die zugehörige Fundstelle
  ebenso in einem eigenen Tab.
- Bei PDF **Seite zeigen** → zeigt die Seite im Original, etwa für
  Tabellen oder Zeichnungen.
- Bei Word und Markdown steht statt der Seite die Nummer des Abschnitts.

**Weitere gefundene Stellen (nicht zitiert)** zeigt Abschnitte, die die
Suche gefunden hat, die Antwort aber nicht zitiert.

### Warum findet LocaNoto etwas nicht?

- **Dokument liegt in einem Arbeitsbereich, den du nicht siehst** →
  LocaNoto durchsucht nur deine Arbeitsbereiche.
- **Arbeitsbereiche sind eingegrenzt** → unter **Arbeitsbereiche ·
  Modell** alle Haken bei den Arbeitsbereichen entfernen.
- **Das Dokument verwendet ein anderes Wort** (du fragst „BANF", dort steht
  „Bestellanforderung") → ein Admin ergänzt das Glossar. Fragen ohne
  Treffer werden dafür automatisch vermerkt.
- **Scan ohne lesbaren Text** → beim Hochladen erscheint eine Meldung; siehe
  „Wie lade ich einen Scan in LocaNoto hoch?".

Mehr Fundstellen je Antwort: eine **Voreinstellung** wählen, die mehr
Abschnitte abruft.

### Wie grenze ich die Suche in LocaNoto ein?

Im **Chat** unter dem Eingabefeld **Arbeitsbereiche · Modell** öffnen:

- **Arbeitsbereiche:** einzelne ankreuzen → nur dort suchen. Kein Haken →
  alle deine Arbeitsbereiche.
- **Voreinstellung:** legt unter anderem fest, wie viele Fundstellen in
  eine Antwort eingehen. Mehr hilft bei umfangreichen Regelwerken, macht
  die Antwort aber langsamer.
- **Listenbereiche:** bei Listen in mehreren Unterordnern einzelne
  ankreuzen → nur diese Listen abfragen.

Die Auswahl gilt für die nächste Frage.

### Was sind Arbeitsbereiche in LocaNoto und wer sieht meine Dokumente?

Der Arbeitsbereich legt fest, wer ein Dokument finden kann.

| Arbeitsbereich | sichtbar für | hochladen und löschen |
|---|---|---|
| Allgemein | alle Nutzer | nur Admins |
| benannter Arbeitsbereich (Abteilung, Projekt, Kunde) | seine Mitglieder | seine Mitglieder |
| dein persönlicher Arbeitsbereich | nur du | du und Admins |

Jeder Nutzer hat von Anfang an einen persönlichen Arbeitsbereich. Was dort
liegt, fließt nie in die Antworten anderer ein. Welche Arbeitsbereiche du
siehst, zeigt die Seite **Dokumente**: je Arbeitsbereich ein Abschnitt mit
seinen Dateien.

### Wie lade ich ein Dokument in LocaNoto hoch?

Seite **Dokumente**, oben:

1. Dateien wählen – PDF, Word (docx), Markdown, Text oder Scan (TIFF, JPG,
   PNG); mehrere Dateien auf einmal gehen.
2. **nach** – Arbeitsbereich wählen. Vorgabe ist dein persönlicher
   Arbeitsbereich → nichts wird versehentlich geteilt.
3. Optional **Projekt (optional)** angeben → die Datei liegt in diesem
   Ordner deines persönlichen Arbeitsbereichs.
4. **Bilder beschreiben** nur ankreuzen, wenn Schaubilder wichtig sind →
   ein Modellaufruf je Bild. Gescannte Seiten liest die Texterkennung auch
   ohne Haken.
5. **Hochladen** → LocaNoto meldet je Datei, wie viele Abschnitte
   durchsuchbar sind.

Die Dateien gehen nacheinander hoch; die Seite bis zum Ende offen lassen.

### Wie lade ich einen Scan in LocaNoto hoch?

Wie jedes Dokument. Seiten ohne Textebene (gescanntes PDF, TIFF, JPG, PNG)
liest die Texterkennung (Deutsch, Englisch) automatisch.

- Seite nicht lesbar → die Meldung nach dem Hochladen nennt die
  Seitenzahlen.
- Erneut hochladen mit **Bilder beschreiben** → das Sehmodell liest diese
  Seiten; es liest schlechte Scans und Handschrift besser, ein
  Modellaufruf je Seite.

Unter **Quellen** tragen solche Fundstellen den Zusatz `ocr`
(Texterkennung) bzw. `sehmodell`. Zahlen daraus (Prüfwerte, Maße,
Fristen) an der Originalseite prüfen: die Texterkennung kann Ziffern
verwechseln, das Sehmodell unleserliche Stellen plausibel ergänzen.

### Wie verschiebe oder lösche ich ein Dokument in LocaNoto?

Seite **Dokumente** → je Arbeitsbereich ein Abschnitt mit seinen Dateien.
Neben jeder Datei:

1. **Verschieben nach** – Ziel-Arbeitsbereich wählen → **Verschieben**,
   etwa um etwas aus deinem persönlichen Arbeitsbereich mit einer
   Abteilung zu teilen.
2. Oder **Löschen** → Rückfrage bestätigen → Datei und ihre Abschnitte
   verschwinden aus der Suche.

Mit ownCloud: gelöschte Dateien landen dort im Papierkorb, verschobene im
Ordner des neuen Arbeitsbereichs. Klappt das nicht, sagt die Meldung es –
sonst käme die Datei beim nächsten Abgleich zurück.

Stehen neben den Dateien keine Knöpfe, darfst du in diesem Arbeitsbereich
nur lesen.

### Wie arbeite ich in LocaNoto mit Chats?

Seite **Chat**, links:

- **+ Neuer Chat** → neues Gespräch ohne Vorgeschichte.
- Chat in der Liste anklicken → öffnet ein älteres Gespräch.

Über dem geöffneten Chat:

- **Umbenennen** → neuen Titel eintragen.
- **Löschen** → entfernt das Gespräch nach Rückfrage.

Jeder Chat bekommt nach der ersten Frage automatisch einen kurzen Titel
(höchstens etwa sechs Wörter). Chats werden automatisch gespeichert, sind
nur für dich sichtbar und liegen verschlüsselt auf dem Server, samt Titeln
und Bildern.

Neues Thema → neuer Chat, denn LocaNoto bezieht den Verlauf des Chats in
die Antwort ein.

Während eine Antwort entsteht, darfst du die Seite oder den Chat
wechseln: LocaNoto schreibt sie weiter. Zurück im Chat steht „Die Antwort
wird geschrieben …“ mit dem bisherigen Text, bis sie fertig ist. Bricht
eine Antwort ab (etwa weil der Modellserver ausfällt), steht darunter der
Grund und **Nochmal fragen**.

### Was bewirken „Hilfreich“ und „Nicht hilfreich“ in LocaNoto?

Unter jeder Antwort stehen **Hilfreich** und **Nicht hilfreich**.

- Klick → die Rückmeldung geht mit der Frage an die Admins. Sie sehen
  daran, wo Dokumente oder Glossareinträge fehlen.
- Fragen ohne Treffer werden auch ohne Klick vermerkt.
- Stammt ein Treffer aus einem persönlichen Arbeitsbereich, steht in der
  Rückmeldung statt des Dateinamens nur ein Platzhalter.

### Was ist eine Voreinstellung in LocaNoto?

Eine Voreinstellung bündelt Modell, Zahl der Fundstellen und
Listenbereiche für einen Zweck. Auswahl im **Chat** unter **Arbeitsbereiche
· Modell** → **Voreinstellung**; **keine** nutzt die Grundeinstellung.
Eigene Voreinstellungen tragen den Zusatz „(eigene)".

Eigene anlegen: **Einstellungen** → **Voreinstellungen** → **Neue
Voreinstellung** → Bezeichnung, Beschreibung, **Modell**, **Abschnitte**
(1 bis 30) und **Listenbereiche** → **Speichern**. **Vorgabe** übernimmt
die Grundeinstellung. Eine eigene Voreinstellung aufklappen → ändern oder
**Löschen**. **Gemeinsame Voreinstellungen** legen Admins an; nur diese
können eigene Prompts haben.

**Modell:** Im **Chat** unter **Arbeitsbereiche · Modell** → **Modell**
wählst du das Sprachmodell aus der Liste, die die Admins freigeben.
**Vorgabe** nimmt das Modell der Voreinstellung, sonst das Grundmodell.

### Wie frage ich in LocaNoto Listen aus Excel oder CSV ab?

Listen (xlsx, csv) werden bei jeder Frage frisch gelesen → neue Zeilen
wirken sofort. Sind für dich Listen eingerichtet, bezieht LocaNoto sie in
jede Frage ein: es wählt die passende Liste und liest die passenden
Zeilen. Im **Chat** unter **Arbeitsbereiche · Modell**: **Listen**
abwählen → keine Listen; **Listenbereiche** → nur diese Unterordner;
**Große Listen einbeziehen** → auch sehr große Blätter (langsamer).

Unter der Antwort zeigt **Listen (n)**, welches Blatt mit welcher Abfrage
wie viele Zeilen geliefert hat.

Welche Blätter du abfragen kannst: **Einstellungen** → **Meine Listen** →
**Deine Blätter** und **Listen deiner Arbeitsbereiche**. Eine Voreinstellung
kann die Listen auf bestimmte Listenbereiche (Unterordner) beschränken.

### Wie frage ich in LocaNoto die Datenbank ab?

Ist für einen deiner Arbeitsbereiche eine Datenbank eingerichtet, steht im
Chat unter **Arbeitsbereiche · Modell** **Datenbank** (bei mehreren dazu
**Datenbank von**).

- **Datenbank** angekreuzt → LocaNoto schreibt zu deiner Frage eine
  lesende Abfrage (SELECT) und nutzt das Ergebnis. Ändern kann LocaNoto an
  der Datenbank nichts. Der Haken wird im Browser gemerkt.
- Unter der Antwort zeigt **Datenbankabfrage (n Zeilen)** die Abfrage.
- „No database connection: …“ → nennt den Grund (Server nicht
  erreichbar, Anmeldung abgelehnt …); die Antwort kommt dann nur aus den
  Dokumenten.

**Dokumente aus der Datenbank:** „Zeig mir die Rechnung 2025103“, „das
Datenblatt vom Kugelhahn“. Liegt das Dokument in der Datenbank oder in einem
freigegebenen Ordner, steht es unter der Antwort unter **Dokumente aus der
Datenbank**; PDFs und Bilder öffnen im Browser. Nach dem Inhalt fragen geht
auch: „Was steht auf der Rechnung 2025103?“

**Eigenes SQL-Login:** **Einstellungen** → **Meine Datenbanken** →
**Benutzer** und **Passwort**, die du vom Datenbank-Admin bekommen hast →
**Verbinden**. Abfragen laufen dann mit deinen Rechten in der Datenbank.
Das Login bleibt nur in der Browsersitzung. Hat der Admin ein gemeinsames
Konto hinterlegt, geht es auch ohne eigenes Login.

### Wie arbeite ich in LocaNoto mit meinen eigenen Listen?

**Einstellungen** → **Meine Listen** zeigt **Dein Ordner**, z. B.
`/mnt/listen/LISTE/anna`: Der Admin legt eine Wurzel fest, jeder bekommt
darin einen Ordner mit seinem Benutzernamen. Excel- und CSV-Dateien dort
werden bei jeder Frage mit Listen gelesen; nur du siehst sie.

- **Unterordner (optional)** → **Speichern** → nur dieser Teil deines
  Ordners zählt.
- **Listen neu einlesen** → nach neuen Dateien oder geänderten Spalten;
  neue Zeilen wirken ohne Zutun.
- **Deine Blätter** → die gefundenen Blätter mit Zeilenzahl.

### Wie verbinde ich mein Postfach mit LocaNoto?

**Einstellungen** → **Postfächer und Datenanschlüsse** → je Postfach
Mailadresse und Passwort eintragen → **Verbinden**. LocaNoto prüft die
Anmeldung sofort.

Fehlt der Abschnitt, hat ein Admin noch kein Postfach eingerichtet.

Danach kann LocaNoto Mails einbeziehen, etwa:

- „Was hat Frau Meier zuletzt geschrieben?"
- „Fasse mir die Mails der letzten 24 Stunden zusammen."
- „Antworte Herrn Braun, dass der Termin passt."

Die Anmeldedaten liegen nur in deiner laufenden Sitzung und verschwinden
beim Abmelden → danach neu verbinden. **Trennen** beendet die Verbindung
vorher.

Funktionspostfächer (etwa info@) öffnest du mit deinen eigenen Daten;
Exchange entscheidet über den Zugriff.

### Was passiert, wenn LocaNoto eine Mail verschicken will?

Aus einem persönlichen Postfach verschickt LocaNoto **nie selbst**. Will
die Antwort eine Mail senden, erscheint darunter **Entwurf wartet auf
dich** mit Empfänger, Betreff und Text.

- **Entwurf senden** → verschickt den Entwurf so, wie er dort steht.
- **Verwerfen** → verschickt nichts.

Geht beim Senden etwas schief, steht der Grund im Entwurf:

- **Nicht gesendet: …** → nichts ist hinausgegangen; **Entwurf senden**
  versucht es noch einmal.
- **Der Server hat nicht geantwortet** → vor einem zweiten Versuch im
  Ordner *Gesendet* (bzw. im Kalender) nachsehen.

Antwortet der Server zu spät, die Mail liegt aber in *Gesendet*, gilt sie
als gesendet. Was mit einem Entwurf geschah, weiß LocaNoto bei der
nächsten Frage im selben Chat; ebenso, welche Mails und Termine es zuvor
gelesen hat.

Nur für ein Funktionspostfach kann ein Admin selbständige Antworten
freischalten; solche Mails tragen in der Regel einen Hinweis, dass sie
automatisch erstellt wurden.

### Wie trage ich mit LocaNoto Termine ein?

Bei verbundenem Exchange-Postfach, etwa: „Was steht morgen in meinem
Kalender?", „Trag mir Dienstag 14 Uhr eine Stunde Fokuszeit ein",
„Lade huber@firma.de für Freitag 10 Uhr zur Baubesprechung ein".

Eintragen und Einladen sind Entwürfe wie Mails: Der Entwurf nennt
Wochentag, Datum und Uhrzeit → prüfen → **In den Kalender eintragen** bzw.
**Einladung senden**. LocaNoto kennt das heutige Datum und die Wochentage
der umliegenden Wochen; Zeiten gelten in der Zeitzone der Installation
(Vorgabe Europe/Berlin).

Bestehende Termine lassen sich ebenso ändern und absagen: „Lade auch
meier@firma.de dazu ein", „Verschieb die Baubesprechung auf 14 Uhr", „Leg
die beiden Termine am 11.11. zusammen", „Sag den Jour fixe ab". Der Entwurf
nennt, was sich ändert und wer eine Nachricht bekommt → **Änderung
speichern** bzw. **Termin absagen**. Neu Eingeladene bekommen eine
Einladung, bei einer neuen Zeit alle eine Aktualisierung. Ändern kann nur,
wer den Termin organisiert; bei einem fremden Termin geht die Absage an
den Organisator.

Einladungen beantworten: „Welche Einladungen sind noch offen?" (im Kalender
mit „Antwort offen" markiert), „Sag dem Projekttreffen am Donnerstag zu",
„Sag vorläufig zu". Entwurf → **Zusagen**, **Vorläufig zusagen** bzw.
**Absagen**; die Antwort geht an den Organisator.

### Was kann LocaNoto sonst noch mit meinem Postfach?

| Frage, zum Beispiel | Exchange | IMAP (Gmail, GMX …) | Bestätigung |
|---|---|---|---|
| „Wie ist die Mailadresse von Vladyslav Borysenko?“ – Adressbuch der Organisation und eigene Kontakte | ja | – | nein |
| „Lade Vlad und Rodolfo ein“ – Namen statt Adressen; LocaNoto sucht sie im Adressbuch, bei mehreren Treffern fragt es nach | ja | – | – |
| „Wann haben Borysenko und ich nächste Woche eine Stunde Zeit?“ – Frei/Gebucht | ja | – | nein |
| „Was steht im Anhang der Mail von Meier?“ – Anhänge, Text von PDF, Word, Text | ja | ja | nein |
| „Markiere die Mail als ungelesen“ | ja | ja | nein |
| „Leite die Mail an Rodolfo weiter“ – mit Anhängen | ja | ja | ja |
| „Verschieb die Mail ins Archiv / in den Papierkorb / nach Projekte“ | ja | ja | ja |
| „Ist meine Abwesenheitsnotiz an?“ / „Stell sie für nächste Woche ein“ | ja | – | Setzen: ja |

Der Papierkorb ist der Ordner „Gelöschte Elemente“: Eine Mail lässt sich
dort wiederherstellen. Endgültig löscht LocaNoto nichts.

### Wie benachrichtigt mich LocaNoto über neue Mails?

Ist ein Postfach verbunden und LocaNoto in einem Browsertab offen, prüft
LocaNoto alle paar Minuten auf neue Mails. Neue Mails → Meldung mit
Absender und Betreff → **Ansehen** öffnet den Chat mit der Frage nach den
neuen Nachrichten im Eingabefeld.

**Einstellungen** → **Postfächer und Datenanschlüsse** → **Bei neuer Mail
benachrichtigen** schaltet das je Postfach aus und an. Ist kein
LocaNoto-Tab offen, wird nicht geprüft: Die Anmeldedaten liegen nur in der
Browsersitzung.

### Wie arbeite ich mit Tickets in LocaNoto?

Hat ein Admin für ein Funktionspostfach das Ticketsystem eingeschaltet und
dich als Mitglied eingetragen, gibt es oben die Seite **Tickets**.

- Jede neue Mail an das Postfach wird ein Ticket (z. B. T-2026-0001). Der
  Absender bekommt sofort die Standardantwort mit der Nummer; du bekommst
  eine Meldung. Die Zahl an **Tickets** zählt offene Tickets ohne
  Zuständigen.
- Oben wählen: Postfach, dann **offen + in Arbeit**, **erledigt** oder
  **alle Status**.
- Ticket öffnen → **Übernehmen** (du bist zuständig) bzw. **Freigeben**,
  **Status** wählen → **Speichern**, **Notiz** → **Notiz hinzufügen**.
- **Im Chat beantworten** → Chat mit dem Ticket als Frage; die Antwort
  geht als Entwurf über dein verbundenes Postfach.
- Antwortet der Kunde mit der Nummer im Betreff, landet die Mail beim
  selben Ticket und öffnet es wieder; der Zuständige bekommt eine Meldung.

### Wie suche ich mit LocaNoto im Internet?

Im **Chat** unter **Arbeitsbereiche · Modell** **Websuche** ankreuzen →
LocaNoto sucht im Netz, wenn deine Dokumente die Frage nicht beantworten.
Hinaus geht nur der Suchbegriff, keine Dokumente.

- Persönlicher Arbeitsbereich → geht immer.
- Geteilter Arbeitsbereich → ein Admin muss die Websuche dort erst
  erlauben. Sonst steht unter der Antwort „Bei Websuche nicht durchsucht
  (dort gesperrt)" mit den Arbeitsbereichen.
- **Allgemein** ist ab Werk gesperrt. Eine Frage mit Websuche über alle
  Arbeitsbereiche lässt ihn aus.

Treffer stehen unter der Antwort als **Aus dem Netz** mit [W1], [W2] …,
getrennt von den Dokumenten. In den eigenen Arbeitsbereich übernehmen geht
über die Seite **Quellen im Netz**.

Ohne angekreuzte Websuche kann LocaNoto eine Websuche **vorschlagen**,
etwa wenn die Dokumente nichts liefern oder nach Aktuellem gefragt ist.
Unter der Antwort steht dann **Websuche vorgeschlagen** mit dem genauen
Suchtext → **Im Web suchen** → die Antwort geht im selben Chat mit den
Treffern weiter. **Verwerfen** → nichts geht hinaus.

### Wie sammle ich mit LocaNoto Quellen aus dem Internet?

1. Seite **Quellen im Netz** → Stichworte ins Suchfeld → **Suchen**.
   Oder im Chat Stichworte ins Eingabefeld → **Im Web suchen** → den
   gezeigten Text bestätigen.
   Der Suchbegriff geht an Suchmaschinen: keine internen Namen oder
   Zahlen.
2. Die Suche läuft im Hintergrund, die Seite darf verlassen werden. Sind
   die Treffer da (bis zu 25), erscheint eine Meldung mit **Ansehen**, und
   **Quellen im Netz** oben zeigt eine Zahl.
3. **Ansehen** → Treffer. Optional **Lesen** → die Seite als reiner Text,
   ohne Bilder und Skripte. **↗** öffnet die Seite im Browser.
4. Treffer ankreuzen (oder **Alle auswählen**) → **Ausgewählte in meinen
   Arbeitsbereich übernehmen**. Auch das läuft im Hintergrund; eine
   Meldung sagt, wie viele Seiten gespeichert wurden.

Suchen bleiben unter **Meine Suchen**, bis du sie löschst. Übernommenes
landet **immer in deinem persönlichen Arbeitsbereich**, Ordner
*Suchergebnisse*, mit Quelle und Abrufdatum. Gehört es in einen geteilten
Arbeitsbereich → dorthin verschieben.

### Wie sage ich LocaNoto, wie es mir antworten soll?

**Einstellungen** → **Persönliche Anweisung** → Text eintragen, etwa
„Antworte knapp, mit Tabellen, und nenne immer die Norm." → **Speichern**.

- Gilt ab der nächsten Frage für alle deine Antworten, auch über die
  Schnittstelle.
- Feld leeren → **Speichern** → nimmt sie wieder heraus.
- Höchstens 2000 Zeichen; verschlüsselt gespeichert, andere sehen sie
  nicht.

Die Anweisung verfeinert nur. Die Grundregeln (Quellen nennen, nichts
erfinden) legen die Admins in den Prompts fest; sie gehen vor.

### Wie ändere ich mein Passwort in LocaNoto?

**Einstellungen** → **Passwort ändern** → **Bisheriges Passwort**,
**Neues Passwort** (mind. 8 Zeichen) → **Speichern**. Bei Anmeldung über
das Firmenverzeichnis steht dort nur ein Hinweis; das Passwort ändert sich
dann im Verzeichnis.

Mit ownCloud:

- Verwaltet LocaNoto dein ownCloud-Konto → das neue Passwort gilt dort
  auch.
- Gibt es dort noch kein Konto → es entsteht jetzt, mit diesem Passwort.
- Gehört das Konto jemand anderem → die Meldung sagt, dass dort das alte
  Passwort weiter gilt.

Passwort vergessen → ein Admin setzt ein neues; danach sofort selbst
ändern.

### Was sind meine Zugangstoken in LocaNoto?

Ein Zugangstoken lässt Programme und Skripte LocaNoto über die
HTTP-Schnittstelle fragen oder Dokumente einliefern – mit deinen Rechten.
Ein Admin legt es an; der Wert wird genau einmal angezeigt.

**Einstellungen** → **API-Token** → zeigt alle Token auf deinen Namen mit
Kennung, Bezeichnung und Datum. **Widerrufen** → sperrt ein Token sofort.
Nicht gebrauchte Token widerrufen. Ohne Token auf deinen Namen fehlt der
Abschnitt.

### Was sehen Admins von meiner Arbeit in LocaNoto?

- **Chats:** nichts in der Anwendung; sie liegen verschlüsselt.
- **Persönlicher Arbeitsbereich:** Admins sehen Dateinamen, nie den Inhalt,
  und können Dateien löschen. Im strengen Betrieb sehen sie nicht einmal
  die Dateinamen. Den Inhalt erreichen sie nur über den Notzugang, den eine
  zweite Person bestätigen muss; beide Namen stehen im Protokoll.
- **Rückmeldungen:** Fragen mit **Hilfreich**/**Nicht hilfreich** und
  Fragen ohne Treffer im Wortlaut, mit deiner Kennung.
- **Postfach-Anmeldungen:** niemand; sie werden nicht gespeichert.

Wer Zugriff auf den Server selbst hat, kann technisch mehr; dagegen
schützen ein verschlüsselter Datenträger und ein kleiner Kreis mit
Serverzugang.

## Teil 2: LocaNoto verwalten (für Admins)

Benutzer, Rollen, Arbeitsbereiche, gemeinsamer Bestand, Listen,
Zugangstoken und Schnittstelle, Postfächer, Notzugang, Rückmeldungen,
Glossar, Prompts, Voreinstellungen, ownCloud, Sicherung und Störungen.

### Wo finde ich als Admin den Admin-Bereich in LocaNoto?

Admins sehen oben die Seite **Admin**. Ihre Leiste führt zu:

- **Nutzer · Arbeitsbereiche · Hintergrundläufe** – Benutzer anlegen,
  Rollen, Arbeitsbereiche, Läufe wie **Bilder nachtragen**; darüber eine
  Zeile zur Sicherheitslage
- **Sicherungen** – Vektordatenbank sichern und zurückholen
- **Notzugang** – Zugang zu persönlichen Arbeitsbereichen
- **Prompts und Glossar**
- **Rückmeldungen** – Fragen ohne Antwort, nicht hilfreiche Antworten
- **Ablage** – ownCloud/OpenCloud
- **Postfächer** – Postfächer, Datenanschlüsse, Websuche, Ticketsysteme
- **Listen** – Listenordner und Katalog
- **Datenbanken** – SQL-Datenbanken je Arbeitsbereich
- **Externes Modell** – welche Quellen extern beantwortet werden dürfen
- **API** – Beschreibung der HTTP-Schnittstelle unter `/api/v1/docs`

Jede Funktion der Seiten gibt es auch über die Schnittstelle; **API**
zeigt die Aufrufe.

### Wie werde ich Admin in LocaNoto?

- Ein vorhandener Admin: **Admin** → **Nutzer** → Benutzer suchen →
  Rolle `admin` wählen → **Speichern**.
- Neue Installation: den allerersten Zugang legt `scripts/create_user.py` im
  Terminal an; er wird Admin. Danach verlangt das Skript die Anmeldung
  eines vorhandenen Admins.

Den letzten Admin kann niemand herabsetzen oder löschen.

### Wie lege ich als Admin einen Benutzer in LocaNoto an?

**Admin** → **Nutzer**, unter der Liste:

1. **Name** – Buchstaben, Ziffern, Punkt, Strich, Unterstrich.
2. **Passwort** – mindestens 8 Zeichen.
3. Rolle – in der Regel `nutzer`.
4. **Anlegen**.

→ Der persönliche Arbeitsbereich entsteht sofort; mit ownCloud auch Konto
und persönlicher Ordner dort.

Kennungen, die sich nur durch ein Sonderzeichen unterscheiden („m.meier",
„m_meier"), weist LocaNoto ab: sie ergäben denselben persönlichen
Arbeitsbereich.

### Wie ändere oder lösche ich als Admin einen Benutzer in LocaNoto?

**Admin** → **Nutzer** → **Benutzer suchen** (ab 20 Nutzern zeigt die
Liste erst nach einer Suche Treffer). In der Zeile des Benutzers:

- Rolle wählen → **Speichern**.
- **Arbeitsbereiche** → seine Arbeitsbereiche suchen und hinzufügen →
  **Speichern**.
- **Löschen** → Rückfrage bestätigen. Seine Token und seine Anweisung
  verschwinden mit, ebenso ein verwaltetes ownCloud-Konto. Chatverlauf und
  persönlicher Arbeitsbereich bleiben; solange davon etwas da ist, lässt
  sich kein neues Konto mit demselben Namen anlegen – es würde Chats und
  Arbeitsbereich übernehmen. Auf dem Server entfernt
  `python accounts.py purge <name>` beides.

**Passwort setzen** in der Zeile → neues Passwort → **Speichern** (auch
auf dem Server mit `python scripts/manage_users.py`). Bei einem Konto mit
Chats oder Dokumenten im persönlichen Arbeitsbereich braucht es einen
bestätigten Notzugang dazu – mit dem neuen Passwort wären sie sonst für
dich offen. Bei verwalteten Konten gilt es auch in ownCloud.

Jede Änderung steht im verketteten Benutzerprotokoll. „Benutzerdatei wurde
außerhalb von LocaNoto geändert" → eine Signatur passt nicht: bestehende
Nutzer arbeiten weiter, ein von Hand eingetragener Zugang ist gesperrt.

### Welche Rollen gibt es in LocaNoto?

| Rolle | darf |
|---|---|
| `nutzer` | fragen, in eigene und freigegebene Arbeitsbereiche hochladen |
| `admin` | zusätzlich Benutzer, Arbeitsbereiche, gemeinsamen Bestand und alle Einstellungen verwalten |
| `notzugang` | nur den Notzugang eines Admins zu einem persönlichen Arbeitsbereich bestätigen oder ablehnen |

Die Rolle `notzugang` gehört an jemanden, der **kein** Admin ist, etwa
Geschäftsführung oder Personalrat. Könnten Admins einander bestätigen, wäre
der Notzugang eine Formalie. Sie wird nicht auf der Seite **Nutzer**
vergeben, sondern über das Firmenverzeichnis oder auf dem Server mit
`python scripts/manage_users.py`.

### Wie lege ich als Admin einen Arbeitsbereich in LocaNoto an?

**Admin** → **Arbeitsbereiche** → **Neuer Arbeitsbereich**: Kennung
(Kleinbuchstaben, Ziffern, `_`, `-`), **Bezeichnung**, **Mitglieder** →
**Anlegen**. Ist eine Ablage eingerichtet, legt LocaNoto dort Ordner und
Freigaben gleich mit an; eine Meldung nennt, was dabei nicht ging.

Bestehenden Arbeitsbereich über **Arbeitsbereiche suchen** finden →
**Bearbeiten** → dort änderbar:

- **Bezeichnung**, **Beschreibung**,
- **Für alle sichtbar (ohne Mitgliederliste)**,
- **Mitglieder** – als Kärtchen (× nimmt eines heraus); hinzu über
  **Benutzer suchen und hinzufügen …**: Teil des Namens tippen, Vorschlag
  anklicken,
- **Gruppe aus dem Verzeichnis oder der Dateiablage (optional)** → deren
  Mitglieder kommen hinzu,
- **Websuche erlaubt**,

→ **Speichern**. **Arbeitsbereich entfernen** → nimmt ihn aus der Liste,
die Dokumente bleiben im Bestand. **Arbeitsbereich leeren** → Kennung
eintippen → löscht alle seine Dokumente, auch in der Ablage; Mitglieder
und Einstellungen bleiben. Rückgängig nur über eine Sicherung.

Listenordner trägt **Admin** → **Listen** ein, Datenbanken **Admin** →
**Datenbanken**. Persönliche Arbeitsbereiche stehen nicht in der Liste;
sie haben genau einen Leser.

### Wie befülle ich als Admin den gemeinsamen Bestand in LocaNoto?

In **Allgemein** schreiben nur Admins. Drei Wege:

- **Oberfläche:** **Dokumente** → bei **nach** „Allgemein" wählen →
  **Hochladen**.
- **Terminal:** Dateien in den Dokumentenordner legen → `python ingest.py`.
  `INGEST_RAUM=einkauf python ingest.py` liest in einen anderen
  Arbeitsbereich ein.
- **Schnittstelle:** `POST /aufnehmen` mit dem Token eines Admins, eine
  Datei je Aufruf.

Gescannte Seiten liest die Texterkennung auf allen drei Wegen; was sie
nicht lesen kann, nennt `ingest.py` in seiner Ausgabe.

**Admin** → **Hintergrundläufe**:

- **Bilder nachtragen** → **Starten** → beschreibt Abbildungen im ganzen
  Bestand.
- **Dokumente neu einlesen** → **Starten** → liest den Dokumentenordner
  vollständig ein.

Beide laufen weiter, wenn du die Seite verlässt, und überspringen bereits
Verarbeitetes. Neben jedem Lauf steht sein Zustand; **Protokoll** zeigt
seine Ausgabe, **Abbrechen** (solange er läuft oder wartet) beendet ihn.

### Wie richte ich als Admin Listen (Excel, CSV) in LocaNoto ein?

Listen werden nicht vektorisiert: ein Katalog kennt Blätter und Spalten,
die Zeilen liest LocaNoto bei jeder Frage frisch. **Admin** → **Listen**:

- **Listenordner je Arbeitsbereich**: ein Ordner je geteiltem
  Arbeitsbereich → **Speichern**; der Arbeitsbereich bestimmt, wer die
  Listen sieht. Erlaubt sind Ordner unter den **Erlaubten Wurzeln**
  (`LISTEN_WURZELN`); leer entfernt den Ordner.
- **Wurzel der persönlichen Ordner**, z. B. `/mnt/listen/LISTE` → jeder
  Nutzer bekommt `/mnt/listen/LISTE/<Benutzername>` und sieht ihn unter
  **Einstellungen** → **Meine Listen**. Auch `owncloud:/LISTE` geht.
- Freigaben auf mehreren Servern: im Installer `"lists_pvc": {"name":
  "claim", …}`, eingehängt unter `/mnt/listen/<name>`.
- **Blätter im Katalog** → **Listen neu einlesen**: nötig bei neuen
  Dateien oder geänderten Spalten; neue Zeilen wirken ohne Zutun. Sehr
  große Blätter sind als „groß" markiert.
- **Nicht lesbar** → Dateien mit Fehlern.

- **Listen hochladen** → Dateien (xlsx, xlsm, csv, tsv) wählen,
  Arbeitsbereich und optional einen Bereich (Unterordner) angeben →
  **Hochladen**. Ziel ist der Listenordner des Arbeitsbereichs; angeboten
  werden nur beschreibbare Ordner. Eine Datei gleichen Namens wird ersetzt.
- **Kopfzeile** je Blatt: die Zeile mit den Spaltennamen, gezählt wie in
  der Tabelle → **Speichern**. Leer → LocaNoto erkennt sie selbst.

### Wie lege ich als Admin ein Zugangstoken für LocaNoto an?

Auf dem Server:

```
python scripts/create_token.py <kennung> --bezeichnung "Masseningest Einkauf" --tage 90
```

Das Skript verlangt die Anmeldung eines Admins. Ohne `--tage` gilt das
Token unbegrenzt. Der Wert erscheint **genau einmal**; gespeichert wird nur
sein Hashwert. `--liste` zeigt alle Token, `--widerrufe <Kennung>` sperrt
eines.

Ein Token für das eigene Konto legt ein Admin auch über die Schnittstelle
an (`POST /api/v1/admin/tokens`). Nutzer sehen und widerrufen ihre eigenen
unter **Einstellungen** → **API-Token**.

Das Token weist nur den Nutzer aus; seine Rechte stehen in der
Benutzerdatei. In **Allgemein** liefert nur das Token eines Admins ein.

### Wie benutze ich die HTTP-Schnittstelle von LocaNoto?

Jeder Aufruf trägt das Token im Kopf `X-LocaNoto-Token`.

| Aufruf | Zweck |
|---|---|
| `GET /gesundheit` | Lebenszeichen, ohne Token |
| `GET /status` | Modelle, Bestand, Listen, Voreinstellungen |
| `GET /raeume`, `GET /dokumente` | was dieser Nutzer sehen darf |
| `POST /frage` | Antwort mit Quellen, `?strom=1` laufend |
| `POST /aufnehmen` | Dokument einliefern (Formular: `datei`, `raum`, optional `projekt`, `bilder`, `sehmodell`) |
| `POST /rueckmeldung` | Hilfreich/Nicht hilfreich zu einer Antwort |
| `DELETE /dokumente?raum=…&datei=…` | Dokument löschen, wie **Löschen** in der Oberfläche |
| `GET /hilfe` | Selbstbeschreibung |

Gesucht wird nur in den Arbeitsbereichen des Token-Besitzers; löschen und
einliefern nur, wo er es auch in der Oberfläche dürfte (sonst `403`).
Datei zu groß → `413`. Die Schnittstelle ist nur vom Server selbst
erreichbar; von außen gehört ein Reverse Proxy mit TLS davor. Beispiele:
`REFERENZ.md`, „HTTP-Schnittstelle".

### Wie richte ich als Admin ein Postfach in LocaNoto ein?

Persönliche Postfächer brauchen **einen Eintrag für alle**; jeder Nutzer
öffnet darin sein eigenes Postfach. Jedes Funktionspostfach bekommt einen
eigenen Eintrag.

**Admin** → **Postfächer** → **Anlegen**:

1. **Name:** `postfach` für den gemeinsamen Eintrag, `info` für info@ usw.
2. **Art:** „Exchange/Outlook — direkt, ohne weiteren Server" oder
   „IMAP/SMTP — Gmail, GMX, web.de, eigener Mailserver".
3. **Adresse, Befehl, Exchange- oder IMAP-Server:** etwa `owa.firma.de`;
   bei Exchange leer → wird automatisch gesucht.
4. **persönlich (jeder meldet sich mit seinem Konto an)** angekreuzt
   lassen – oder für ein Funktionspostfach abwählen und **Adresse eines
   Funktionspostfachs** eintragen (`info@firma.de`).
5. **Anlegen**.

Danach verbindet sich jeder Nutzer selbst unter **Einstellungen** →
**Postfächer und Datenanschlüsse**; ein gemeinsames Passwort gibt es
nicht. **Werkzeuge** neben einem Postfach zeigt, was das Modell damit tun
kann und welche Werkzeuge senden.

Andere Werkzeugserver (MCP) → Art „MCP-Server über HTTP". Die Art „lokaler
Prozess (stdio)" erscheint nur, wenn der Betreiber sie mit `MCP_STDIO=1`
freigeschaltet hat: Sie startet einen Befehl auf dem Server.

### Wie binde ich Exchange Online (Microsoft Graph) oder einen anderen Server mit Anbieter-Anmeldung an LocaNoto an?

Neuere Werkzeugserver – etwa ein MCP-Server für Exchange Online über
Microsoft Graph – melden jeden Nutzer beim Anbieter an (OAuth 2.1, der
Anmeldestandard von MCP). LocaNoto kann das:

1. **Admin** → **Postfächer** → **Anlegen** → Art „MCP-Server mit
   Anmeldung beim Anbieter (OAuth)", Adresse des Servers (endet meist auf
   `/mcp`). Bei einem Funktionspostfach die Postfachadresse eintragen –
   das Modell gibt sie an, wo ein Werkzeug ein Postfach verlangt.
2. Die Nutzer gehen unter **Einstellungen** auf **Mit eigenem Konto
   verbinden**, melden sich beim Anbieter an und kommen zurück.

Wo sich LocaNoto anmeldet, liest es beim Server selbst nach; als
Anwendung registriert es sich dort automatisch. Erlaubt der Anbieter das
nicht, trägt ein Admin über die Schnittstelle eine Client-ID ein
(`oauth_client_id`). Die Anmeldung gilt nur in der Sitzung des
Browsers und wird von selbst erneuert; auf dem Server liegt kein Token.
Es gelten die Rechte, die der Nutzer beim Anbieter hat.

Werkzeuge, die etwas ändern (senden, löschen, verschieben, Termine
anlegen), führt LocaNoto nie von selbst aus: Sie erscheinen als Entwurf.
Ohne Angabe des Servers gilt ein Werkzeug nur dann als lesend, wenn sein
Name es sagt (`list_…`, `get_…`, `search_…`).

### Wer sieht ein Postfach in LocaNoto?

Ohne Zuordnung sieht jeder Nutzer jeden Eintrag und kann sich daran
anmelden. **Admin** → **Postfächer**: bei jedem Eintrag steht **Sichtbar
für** und eine Auswahl → **Zuordnen**:

- Persönlicher Eintrag → ein Benutzer. Nur er sieht den Eintrag.
  **alle (eigene Anmeldung)**: ein Eintrag für alle, jeder mit seiner
  eigenen Anmeldung.
- Funktionspostfach → ein **Arbeitsbereich**. Nur dessen Mitglieder sehen
  das Postfach, verbinden es und bekommen seine Tickets – ein Admin auch
  nur als Mitglied. Die Mitgliederliste des Ticketsystems entfällt dann;
  es gelten die Mitglieder des Arbeitsbereichs.

Dieselbe Zuordnung geht schon beim **Anlegen**. Für alle anderen gibt es
das Postfach nicht: nicht in den Einstellungen, nicht im Chat, nicht bei
den Tickets. **Löschen** entfernt einen Eintrag.

### Wann antwortet in LocaNoto ein externes Modell?

Nur wenn der Betreiber eines eingerichtet hat (`EXTERN_BASE_URL`,
`EXTERN_API_KEY`, `EXTERN_MODEL`; Azure OpenAI auch `EXTERN_API_VERSION`)
und der Admin die Quellen einer Antwort dafür freigegeben hat. Sonst
antwortet immer das interne Modell.

**Admin** → **Externes Modell**: je Quelle ein Haken **Extern erlaubt** –
jeder Arbeitsbereich, persönliche Arbeitsbereiche, Datenbank, Listen,
Websuche, jedes Postfach und jeder Datenanschluss, dazu „Chat ohne jede
Quelle". Ab Werk ist nichts angehakt. **Speichern** übernimmt.

Alles vor der Antwort – Suchbegriffe, Datenbankabfrage, Werkzeuge – läuft
auf dem internen Modell. Erst die Antwort selbst kann nach außen gehen,
und nur wenn jede ihrer Quellen freigegeben ist. Intern bleibt sie
außerdem, wenn:

- eine vorherige Antwort im selben Chat intern war,
- ein Bild im Chat ist,
- die Frage mit `/intern` beginnt, im Chat „nur intern" angehakt ist
  oder ein Stichwort vorkommt (ab Werk: intern, vertraulich, geheim und
  ihre englischen Gegenstücke; einstellbar auf derselben Seite).

Glossar und persönliche Anweisung gehen nur mit, wenn sie freigegeben
sind. Unter jeder Antwort steht, welches Modell geantwortet hat und
warum. Antwortet das externe Modell nicht, schreibt das interne die
Antwort; umgekehrt nie.

### Wie binde ich ein ERP, ein MES oder eine Datenbank an LocaNoto an?

Über einen **Datenanschluss**: einen eigenen kleinen Dienst, der genau ein
System kennt und LocaNoto Werkzeuge anbietet, um es zu fragen. LocaNoto
kennt das System nicht, nur die Schnittstelle. Für SQL-Datenbanken
(PostgreSQL, MySQL/MariaDB, Microsoft SQL Server, Oracle, SQLite) liegt ein
fertiger Anschluss bei; für jedes andere System baut man einen nach
derselben Schnittstelle. Beschreibung und Beispiel: `connectors/README.md`.

1. Den Anschluss neben LocaNoto starten (Container oder Pod).
2. **Admin** → **Postfächer** → **Anlegen** → Art „Datenanschluss (ERP,
   MES, Datenbank) über HTTP", Adresse `http://<name>:8000/mcp`. Mit
   Anmeldung je Nutzer: Art „Datenanschluss, jeder meldet sich mit seinem
   Konto des Systems an"; die Nutzer verbinden sich dann unter
   **Einstellungen**.
3. Einem **Arbeitsbereich** zuordnen → nur dessen Mitglieder sehen den
   Anschluss und können ihn fragen.

Im Chat fragt das Modell den Anschluss von selbst, wenn die Frage dazu
passt. Unter der Antwort zeigt **Datenanschlüsse**, welcher Anschluss mit
welcher Abfrage wie viele Zeilen geliefert hat. Werkzeuge, die im System
etwas ändern, führt LocaNoto nie von selbst aus: Sie erscheinen als Entwurf
und laufen erst mit **Ausführen**.

### Wie richte ich als Admin die Websuche in LocaNoto ein?

1. Suchdienst getrennt von LocaNoto betreiben (`REFERENZ.md`, „Websuche").
2. **Admin** → **Postfächer** → **Anlegen** → **Art** „Websuche (eigener
   Dienst, websuche.py)", Adresse `http://websuche:8000/mcp` →
   **Anlegen**.
3. Für jeden geteilten Arbeitsbereich: **Admin** → **Arbeitsbereiche** →
   in seiner Zeile **Erlauben** (bzw. **Sperren**), oder **Bearbeiten** →
   **Websuche erlaubt** → erst dann können Nutzer dort die Websuche
   ankreuzen.

Warum die Freigabe: das Modell formuliert den Suchbegriff mit Abschnitten
des Arbeitsbereichs im Kontext, und der Suchbegriff geht an Suchmaschinen.
Im persönlichen Arbeitsbereich entscheidet jeder Nutzer selbst.

### Wann darf LocaNoto aus einem Postfach selbständig antworten?

Nur aus einem **Funktionspostfach**, bei dem beim Anlegen **darf selbst
antworten (ohne Bestätigung)** angekreuzt ist. Ein persönliches Postfach
legt jede Mail als Entwurf vor, ohne Ausnahme.

**Vorerst abgeschaltet:** Auch ein Funktionspostfach legt jede Mail als
Entwurf vor. Ein automatischer Lauf sähe sonst alle Arbeitsbereiche dessen,
der ihn startet, und der Absender der beantworteten Mail bekäme die Antwort
ungesehen. Sobald ein automatischer Lauf nur den Arbeitsbereich des
Postfachs nutzt, gilt das Folgende.

- **Hinweis unter automatische Antworten setzen** ankreuzen → jede
  selbständig verschickte Mail trägt einen Hinweis, dass sie automatisch
  erstellt wurde. Wortlaut: **Hinweistext**.
- Ohne Haken → kein Hinweis.
- Ein vom Nutzer geprüfter, mit **Entwurf senden** verschickter Entwurf
  trägt nie einen Hinweis.

Die Liste unter **Postfächer** zeigt je Eintrag „legt Entwürfe vor" oder
„antwortet selbständig" mit oder ohne Hinweis.

### Wie richte ich als Admin ein Ticketsystem für ein Funktionspostfach in LocaNoto ein?

**Admin** → **Postfächer** → je Funktionspostfach ein Abschnitt
**Ticketsystem**:

1. **Ticketsystem an** ankreuzen.
2. Es wird **keine Anmeldung gespeichert**. Mitglieder verbinden das
   Postfach unter **Einstellungen** mit ihrem eigenen Konto (Rechte auf
   das Postfach in Exchange, zum Antworten „Senden als“).
3. **Standardantwort**: geht sofort an jeden Absender. `{ticket}`,
   `{subject}` und `{name}` werden eingesetzt.
4. **Mitglieder**: LocaNoto-Benutzer, die jedes Ticket sehen und gemeldet
   bekommen. Admins sehen alle Tickets.
5. Optional **Jede neue Mail weiterleiten an** und **Ticketkürzel**.
6. **Speichern** → **Jetzt prüfen** (mit deinem eigenen verbundenen
   Login). Die erste Prüfung merkt nur die Uhrzeit; ab dann wird jede neue
   Mail ein Ticket.

Geprüft wird jede Minute (`TICKET_POLL_SECONDS`), solange ein Mitglied mit
verbundenem Postfach LocaNoto offen hat; **Zuletzt geprüft** zeigt das
Ergebnis. Ist niemand online, werden die inzwischen eingegangenen Mails
beim nächsten Mal bearbeitet, samt Standardantwort. Automatische Mails
(Abwesenheitsnotizen, Newsletter, Unzustellbarkeitsmeldungen, Mails des
Postfachs selbst) werden weder Ticket noch beantwortet. Eine Mail wird als
erledigt markiert, bevor etwas gesendet wird: Sie wird nie zweimal
beantwortet.

### Wie funktioniert der Notzugang in LocaNoto?

Ein persönlicher Arbeitsbereich ist auch für Admins zu. Scheidet jemand aus
oder fällt länger aus:

1. Ein Admin: **Admin** → **Notzugang** → **Zugang zu einem persönlichen
   Arbeitsbereich beantragen** → Arbeitsbereich wählen, **Grund**
   eintragen → **Beantragen**.
2. Eine Person mit der Rolle `notzugang` meldet sich an → oben
   **Notzugang** → unter **Anträge** **Bestätigen** oder **Ablehnen**.
3. Bestätigt → der Zugang gilt 24 Stunden und erlischt von selbst; unter
   **Offene Zugänge** beendet **Schließen** ihn vorzeitig.

Beide Namen und der Grund stehen im Protokoll. Ohne jemanden mit der Rolle
`notzugang` gibt es keinen Notzugang: der Arbeitsbereich ist dann nur
löschbar, nicht lesbar. Die Seite sagt das oben.

Darunter stehen für Admins die **Dokumente in persönlichen
Arbeitsbereichen anderer**, nur mit Kennung, nie mit Namen – zum Aufräumen
nach Ausgeschiedenen; **Löschen** entfernt eines.

Bestätigen kann nur, wer sein Passwort selbst gesetzt hat. Ein Konto, dessen
Passwort jemand anderes vergeben hat – beim Anlegen oder durch Zurücksetzen
–, wird abgewiesen, bis die Person es unter **Einstellungen** selbst ändert.
Konten aus dem Firmenverzeichnis betrifft das nicht.

### Wie werte ich als Admin die Rückmeldungen in LocaNoto aus?

**Admin** → **Rückmeldungen** zeigt oben die Zahlen je Art, darunter:

- **Fragen ohne Antwort** – meist fehlt ein Glossareintrag oder ein
  Dokument.
- **Nicht hilfreich** – Treffer gab es, aber die falschen.

**Herunterladen** → die vollständige Liste. **Archivieren** → legt sie
unter dem Tagesdatum ab und beginnt eine neue; gelöscht wird nichts.
**Ablagen** listet die archivierten zum Herunterladen.

Die Liste enthält Fragen im Wortlaut mit Kennung und liegt deshalb
verschlüsselt. Steht dort „Zeilen liegen im Klartext.", bringt **Neu
verschluesseln** ältere Zeilen in die verschlüsselte Form.

### Wie pflege ich als Admin das Glossar in LocaNoto?

Das Glossar übersetzt Wörter der Nutzer in die Wörter der Dokumente.
**Admin** → **Prompts und Glossar** → **Glossar**, eine Zuordnung je
Zeile, `#` = Kommentar:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Speichern** → wirkt ab der nächsten Frage. Kommentarzeilen gehen
nicht ans Sprachmodell.

Nur geprüfte Zuordnungen eintragen: ein falscher Eintrag lenkt die Suche
zuverlässig an die falsche Stelle. Kandidaten liefern die „Fragen ohne
Antwort" unter **Rückmeldungen**.

### Wie passe ich als Admin Prompts und Voreinstellungen in LocaNoto an?

**Prompts:** **Admin** → **Prompts und Glossar** → Vorlage wählen →
**Öffnen**. Vorlagen sind „Antwort" (wie geantwortet wird),
„Suchsonden" (Suchanfragen aus der Frage) und, wo eingerichtet,
„Listenabfrage" und „Datenbankabfrage".

- **Speichern** → wirkt ab der nächsten Frage; ein Text ohne die
  Pflicht-Platzhalter wird abgelehnt.
- **Auf die mitgelieferte Vorlage zurücksetzen** → stellt die
  mitgelieferte Fassung wieder her.

**Gemeinsame Voreinstellungen** (unten auf derselben Seite): **Neue
Voreinstellung** → Bezeichnung, Beschreibung, Modell, Abschnitte,
Listenbereiche → **Speichern**; aufklappen → ändern oder **Löschen**.
Eigene Prompts einer Voreinstellung: oben neben der Vorlage die
Voreinstellung wählen → **Öffnen** → **Speichern**. „für alle
Voreinstellungen" bearbeitet die allgemeine Fassung.

Wählbare Modelle legt `CHAT_MODELLE` in der `.env` fest; dieselbe Liste
sehen Nutzer im Chat unter **Modell**. Nutzer verfeinern mit ihrer
**Persönlichen Anweisung**.

Nach einer Prompt-Änderung ein paar bekannte Fragen stellen und die
Antworten vergleichen.

### Wie binde ich als Admin ownCloud an LocaNoto an?

„ownCloud" meint die Dateiablage, auch OpenCloud. In der `.env`
eingerichtet → LocaNoto legt hochgeladene Dokumente auch dort ab und
übernimmt Ordner und Gruppen. **Admin** → **Ablage** zeigt, ob die Ablage
erreichbar ist, und die Zuordnung Arbeitsbereich → Ordner:

- **Ordner und Freigaben der Arbeitsbereiche einrichten** → je
  Arbeitsbereich ein Ordner, geteilt mit seinen Mitgliedern.
- **Gruppen abgleichen** → übernimmt ownCloud-Gruppen als Mitglieder.
- **Dokumente abgleichen** → holt neue und geänderte Dateien aus
  ownCloud und liest sie ein (läuft im Hintergrund).

- **Ordner je Arbeitsbereich** → einen anderen Ordner eintragen →
  **Speichern**; leer nimmt den Ordner mit der Kennung.
- **Vorschau eines Abgleichs** → Arbeitsbereich → **Vorschau** → wie viele
  Dateien neu, geändert, entfernt wären.
- **Konten, die LocaNoto verwaltet** → Namen bestehender Konten →
  **Übernehmen**; sie folgen danach Passwortänderungen und Löschungen.

Löschen und Verschieben in LocaNoto wirkt auch in ownCloud (Gelöschtes →
Papierkorb). Benutzer löschen und Passwörter ändern wirkt dort nur bei
verwalteten Konten. Fehlt ein Konto, entsteht es beim nächsten
Passwortsetzen. Einrichtung: `REFERENZ.md`, „Dokumente aus ownCloud".

### Wie wechsle ich als Admin das Embedding-Modell in LocaNoto?

Nur mit Postgres (`DATABASE_URL`). Die Dokumente werden dafür nicht neu
eingelesen: LocaNoto berechnet die Vektoren aus dem gespeicherten Text neu.

1. In der `.env` `EMBEDDING_NEXT_MODEL` auf das neue Modell setzen, dazu
   `EMBEDDING_NEXT_BASE_URL` und `EMBEDDING_NEXT_API_KEY`, falls es auf
   einem anderen Server läuft. Optional `REEMBED_HOURS=20-6` → arbeitet
   nur nachts. Worker neu starten.
2. **Admin** → **Hintergrundläufe** → **Vektoren neu berechnen** → **Starten**.
   Die Suche läuft währenddessen mit dem alten Modell weiter. Ein
   unterbrochener Lauf macht beim nächsten **Starten** dort weiter.
3. Meldet der Auftrag „Every passage has a vector of …": `EMBEDDING_MODEL`
   auf das neue Modell setzen, `EMBEDDING_NEXT_*` entfernen, ausrollen,
   **Vektoren neu berechnen** noch einmal starten (holt nach, was während
   des Ausrollens hochgeladen wurde).

Die alten Vektoren bleiben, bis ein späterer Wechsel den Platz braucht.
Bis dahin heißt Zurückwechseln nur `EMBEDDING_MODEL` zurückstellen.
`python reembed.py --status` zeigt den Stand, `--drop-unused` entfernt
die alten Vektoren sofort.

`EMBEDDING_MODEL` ohne diesen Weg zu ändern, lehnt LocaNoto ab (Suche
meldet einen Fehler, `doctor.py` sagt warum) – die gespeicherten Vektoren
passen nur zum alten Modell. Ändert sich bloß der Name desselben Modells
(z. B. ein neuer Tag auf dem Modellserver): `python reembed.py --adopt`.

### Wie sichere ich LocaNoto als Admin?

Drei Dinge gehören in die Sicherung:

1. **Installationsschlüssel** (`config/schluessel.key` oder
   `LOCANOTO_SCHLUESSEL`). Ohne ihn sind Chats, Anhänge und Rückmeldungen
   endgültig unlesbar. Er ist durch nichts zu ersetzen.
2. **Konfigurationsverzeichnis** (`config/`): Benutzer, Arbeitsbereiche,
   Token, Glossar, Prompts, Postfächer.
3. **Vektordatenbank:** **Admin** → **Sicherungen** → **Jetzt sichern**.
   Zurückholen: beim Abzug dessen Namen zur Bestätigung eintippen,
   optional **auch Nutzer, Chats, Einstellungen** ankreuzen →
   **Zurückholen**. Ohne Abzug hieße ein Verlust: alles neu einlesen. Der
   Text im Abzug ist mit dem Installationsschlüssel verschlüsselt;
   zurückholen lässt er sich nur mit demselben Schlüssel.

Die Originaldokumente liegen im Datenverzeichnis und, falls angebunden, in
ownCloud.

### Wo sehe ich Sicherheitslage, Speicherorte, Verschlüsselung und Konfiguration von LocaNoto?

- **Sicherheitslage:** **Admin** zeigt oben eine Zeile – „alle Punkte
  erfuellt" oder welche Punkte offen sind.
- **Verschlüsselung der Rückmeldungen:** **Admin** → **Rückmeldungen**
  (siehe dort).
- **Sicherheitslage im Einzelnen** (auf **Admin** unter der Zeile
  aufklappen) – jeder Punkt der Prüfliste mit Erklärung, woher der
  Installationsschlüssel kommt, der Bestand, die drei Speicherorte und
  Einstellungen der `.env`, die von der Vorlage abweichen oder ihr fremd
  sind (nur Namen, keine Werte). Dasselbe maschinenlesbar:
  `GET /api/v1/admin/status`.
- Auf dem Server prüft `python doctor.py` Schlüssel, Datenbank,
  Modell-Endpunkte, Websuche, Ablage und öffentliche Adresse.

Die angebundenen Sprachmodelle und ob der Endpunkt für die Rangfolge der
Treffer antwortet, zeigt `GET /api/v1/models`.

### Was tue ich als Admin, wenn in LocaNoto etwas nicht funktioniert?

| Beobachtung | Abhilfe |
|---|---|
| Seite reagiert nach einem Update nicht | Seite neu laden, neu anmelden |
| Suche hängt nach den Suchanfragen | Modellserver nicht erreichbar oder kalt; die Meldung nennt den Grund |
| „Antwort nur aus der Stichwortsuche" | Embedding-Endpunkt nicht erreichbar; die Meldung nennt die Arbeitsbereiche |
| „No database connection" | Datenbank oder VPN prüfen; **Admin** → **Datenbanken** → **Verbindung testen** |
| Dokument eingelesen, aber nicht auffindbar | `python scripts/room_diagnosis.py` im Container |
| Benutzerdatei „außerhalb geändert" | Signatur passt nicht; von Hand eingetragene Zugänge sind gesperrt |
| Einstellungen unklar | `python doctor.py`, `GET /api/v1/admin/status` |

Nach einem Update → `python tests/selftest.py` prüft Anmeldung, Rechte, Suche,
Verschlüsselung und Sicherung, ohne den Bestand anzufassen.

## Teil 3: Dieses Handbuch in LocaNoto

Wie das Handbuch eingelesen und aktuell gehalten wird, damit LocaNoto
Fragen zur eigenen Bedienung beantwortet.

### Wie kann LocaNoto Fragen zu sich selbst beantworten?

Jede Überschrift dieses Handbuchs ist eine Frage, jeder Abschnitt für sich
verständlich – so findet LocaNoto ihn wie jedes andere Dokument.

- Einlesen: als Admin `HANDBUCH.md` hochladen, unter **Dokumente** bei
  **nach** „Allgemein" → LocaNoto beantwortet Fragen wie „Wie lade ich ein
  Dokument hoch?" mit Verweis auf den passenden Abschnitt.
- Neue Fassung: unter **Dokumente** im Abschnitt **Allgemein** die alte
  Fassung mit **Löschen** entfernen, dann die neue hochladen. Bloßes
  Überschreiben ließe veraltete Abschnitte stehen.
