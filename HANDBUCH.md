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

Die Seitenleiste ist gegliedert in:

- **Voreinstellung** (ganz oben, falls vorhanden)
- **Chats** – neuer Chat, frühere Chats
- **Dokumentfilter** – Suche eingrenzen, Websuche
- **Datenbank** und **Listen** – nur, wenn eingerichtet
- **Dokumente** – hochladen, verschieben, löschen
- **Einstellungen** – Modell, Passwort, Anweisung, Voreinstellungen,
  Postfächer, Zugangstoken
- **Admin-Bereich** – nur für Admins

### Wie melde ich mich bei LocaNoto an und ab?

- Anmelden: **Benutzername** und **Passwort** eingeben → **Anmelden**. Den
  Zugang legt ein Admin an.
- Abmelden: **Abmelden** in der Seitenleiste.
- Längere Zeit keine Eingabe (Vorgabe: 480 Minuten) → die Anmeldung endet
  von selbst; erneut anmelden.
- Seite reagiert nach einem Update nicht mehr → Seite neu laden und erneut
  anmelden.

### Wie stelle ich LocaNoto auf Englisch um?

In der Seitenleiste unter **🌐 Sprache / Language** Deutsch oder English
wählen → gilt sofort und wird für deinen Zugang gemerkt. Derselbe
Umschalter steht auf der Anmeldeseite.

Fragen kannst du in jeder Sprache: LocaNoto antwortet in der Sprache der
Frage, auch bei deutschen Dokumenten. Dateinamen, Werte und Zitate bleiben
wie im Dokument.

### Wie stelle ich LocaNoto eine Frage?

- Frage ins Eingabefeld unten (**Frage an die Datenbank**) schreiben und
  abschicken.
- Bild anhängen (png, jpg, webp, gif, bmp) → LocaNoto beschreibt es und
  bezieht es ein.
- Nachfrage im selben Chat → bezieht sich auf den bisherigen Verlauf.

Während eine Antwort entsteht, ist die Seitenleiste gesperrt; ein Klick
dort bricht die Antwort ab. Steht unter einer Antwort „Abgebrochen –
Antwort unvollständig", die Frage erneut stellen.

### Woran sehe ich in LocaNoto, woher eine Antwort stammt?

Unter jeder Antwort steht **Quellen** mit je einem Eintrag
**Datei (Seite n)** pro Fundstelle.

- Eintrag aufklappen → zeigt den Textabschnitt, auf den sich die Antwort
  stützt.
- Verweis im Antworttext anklicken → springt zur zugehörigen Quelle.
- Bei PDF **Originalseite n als Bild** ankreuzen → zeigt die Seite im
  Original, etwa für Tabellen oder Zeichnungen.
- Bei Word und Markdown steht statt der Seite die Nummer des Abschnitts.

**Debug: Was sieht das LLM?** zeigt die Suchanfragen und was das
Sprachmodell zu sehen bekam.

### Warum findet LocaNoto etwas nicht?

- **Dokument liegt in einem Arbeitsbereich, den du nicht siehst** →
  LocaNoto durchsucht nur deine Arbeitsbereiche.
- **Ein Filter ist gesetzt** → unter **Dokumentfilter** Arbeitsbereich,
  Projekt und „Suche beschränken auf" leeren.
- **Das Dokument verwendet ein anderes Wort** (du fragst „BANF", dort steht
  „Bestellanforderung") → ein Admin ergänzt das Glossar. Fragen ohne
  Treffer werden dafür automatisch vermerkt.
- **Scan ohne lesbaren Text** → beim Hochladen erscheint eine Meldung; siehe
  „Wie lade ich einen Scan in LocaNoto hoch?".

Mehr Treffer: Regler **Abschnitte abrufen** (ganz unten in der
Seitenleiste, Vorgabe 5) höher stellen.

### Wie grenze ich die Suche in LocaNoto ein?

In der Seitenleiste unter **Dokumentfilter**:

- **Arbeitsbereich:** wählen → nur dort suchen. Leer → alle deine
  Arbeitsbereiche.
- **Projekt:** wählen → nur Dokumente dieses Projekts aus deinem
  persönlichen Arbeitsbereich.
- **Suche beschränken auf:** einzelne Dokumente wählen. Die Liste zeigt nur
  Dokumente, die zu Arbeitsbereich und Projekt passen.

Regler **Abschnitte abrufen** (ganz unten in der Seitenleiste) → bestimmt,
wie viele Fundstellen in eine Antwort eingehen. Mehr hilft bei
umfangreichen Regelwerken, macht die Antwort aber langsamer.

### Was sind Arbeitsbereiche in LocaNoto und wer sieht meine Dokumente?

Der Arbeitsbereich legt fest, wer ein Dokument finden kann.

| Arbeitsbereich | sichtbar für | hochladen und löschen |
|---|---|---|
| Allgemein | alle Nutzer | nur Admins |
| benannter Arbeitsbereich (Abteilung, Projekt, Kunde) | seine Mitglieder | seine Mitglieder |
| dein persönlicher Arbeitsbereich | nur du | du und Admins |

Jeder Nutzer hat von Anfang an einen persönlichen Arbeitsbereich. Was dort
liegt, fließt nie in die Antworten anderer ein. Welche Arbeitsbereiche du
siehst, steht unter **Dokumente** → **Gespeicherte Dokumente**.

### Wie lade ich ein Dokument in LocaNoto hoch?

In der Seitenleiste unter **Dokumente**:

1. **Dokumente hochladen** – PDF, Word (docx), Markdown, Text oder Scan
   (TIFF, JPG, PNG); mehrere Dateien auf einmal gehen.
2. **Arbeitsbereich** wählen. Vorgabe ist dein persönlicher Arbeitsbereich
   („Nur für dich sichtbar") → nichts wird versehentlich geteilt.
3. Optional **Projekt** angeben (nur im persönlichen Arbeitsbereich) →
   später im Dokumentfilter wählbar.
4. **Bilder und Scans beschreiben** nur ankreuzen, wenn Schaubilder wichtig
   sind → ein Modellaufruf je Bild. Gescannte Seiten liest die
   Texterkennung auch ohne Haken.
5. **Hochladen & einlesen** → LocaNoto meldet je Datei, wie viele
   Abschnitte durchsuchbar sind.

### Wie lade ich einen Scan in LocaNoto hoch?

Wie jedes Dokument. Seiten ohne Textebene (gescanntes PDF, TIFF, JPG, PNG)
liest die Texterkennung (Deutsch, Englisch) automatisch.

- Seite nicht lesbar → die Meldung nennt die Seitenzahlen, darunter
  erscheint **Mit Sehmodell lesen**.
- **Mit Sehmodell lesen** klicken → liest schlechte Scans und Handschrift
  besser, ein Modellaufruf je Seite.

Unter der Antwort sind solche Fundstellen mit **aus Texterkennung** oder
**vom Sehmodell gelesen** markiert. Zahlen daraus (Prüfwerte, Maße,
Fristen) an der Originalseite prüfen: die Texterkennung kann Ziffern
verwechseln, das Sehmodell unleserliche Stellen plausibel ergänzen.

### Wie verschiebe oder lösche ich ein Dokument in LocaNoto?

Unter **Dokumente** → **Gespeicherte Dokumente** steht je Arbeitsbereich
ein Aufklapper mit seinen Dateien:

1. **Dokument verwalten** – Datei wählen.
2. **verschieben nach** wählen → **Verschieben**, etwa um etwas aus deinem
   persönlichen Arbeitsbereich mit einer Abteilung zu teilen.
3. Oder **Löschen** → Datei und ihre Abschnitte verschwinden aus der Suche.

Mit ownCloud: gelöschte Dateien landen dort im Papierkorb, verschobene im
Ordner des neuen Arbeitsbereichs. Klappt das nicht, sagt die Meldung es –
sonst käme die Datei beim nächsten Abgleich zurück.

„Nur lesen" → in diesem Arbeitsbereich darfst du nichts ändern.

### Wie arbeite ich in LocaNoto mit Chats?

In der Seitenleiste unter **Chats**:

- **Neuer Chat** → neues Gespräch ohne Vorgeschichte.
- **Frühere Chats:** wählen → öffnet ein früheres Gespräch.
- **Chat löschen** → entfernt das geöffnete Gespräch.

Jeder Chat bekommt nach der ersten Frage automatisch einen kurzen Titel
(höchstens etwa sechs Wörter). Chats werden automatisch gespeichert, sind
nur für dich sichtbar und liegen verschlüsselt auf dem Server, samt Titeln
und Bildern.

Neues Thema → neuer Chat, denn LocaNoto bezieht den Verlauf des Chats in
die Antwort ein.

Während eine Antwort entsteht, darfst du den Reiter oder den Chat
wechseln: LocaNoto schreibt sie weiter. Zurück im Chat steht „Die Antwort
wird geschrieben …“ mit dem bisherigen Text, bis sie fertig ist; bist du
woanders, meldet LocaNoto „Antwort fertig“. Bricht eine Antwort ab (etwa
weil der Modellserver ausfällt), steht darunter der Grund und **Nochmal
fragen**.

### Was bewirken Daumen hoch und Daumen runter in LocaNoto?

Unter jeder Antwort stehen 👍 („Hat geholfen") und 👎 („Hat nicht
geholfen").

- Klick → die Rückmeldung geht mit Frage und Quellen an die Admins. Sie
  sehen daran, wo Dokumente oder Glossareinträge fehlen.
- Fragen ohne Treffer werden auch ohne Klick vermerkt.
- Stammt ein Treffer aus einem persönlichen Arbeitsbereich, steht in der
  Rückmeldung statt des Dateinamens nur ein Platzhalter.

### Was ist eine Voreinstellung in LocaNoto?

Eine Voreinstellung bündelt Modell, Zahl der Fundstellen und
Listenbereiche für einen Zweck. Auswahl ganz oben in der Seitenleiste unter
**Voreinstellung**; darunter steht, wofür sie gedacht ist. **(Standard)**
nutzt die Grundeinstellung.

**Eigene Voreinstellung anlegen:** **Einstellungen** → **Meine
Voreinstellungen**:

1. **Name** eingeben.
2. **Modell** wählen (nur Modelle, die die Admins freigegeben haben).
3. **Abschnitte je Frage** – 0 = Vorgabe.
4. **Listenbereiche** wählen (falls Listen eingerichtet sind).
5. **Speichern** → erscheint oben unter **Voreinstellung** mit dem Zusatz
   „(eigene)". **Löschen** entfernt sie.

Voreinstellungen für alle legen Admins im **Admin-Bereich** an; nur diese
können eigene Prompts haben.

**Modell:** Unter **Einstellungen** wählst du das Sprachmodell aus der
Liste, die die Admins freigeben. Gibt es nur ein Modell, entfällt die
Auswahl.

### Wie frage ich in LocaNoto Listen aus Excel oder CSV ab?

Listen (xlsx, csv) werden bei jeder Frage frisch gelesen → neue Zeilen
wirken sofort. In der Seitenleiste unter **Listen**:

- **Listen mit abfragen** ankreuzen → LocaNoto wählt die passende Liste und
  liest die passenden Zeilen. Darunter steht, wie viele Blätter bereit
  sind.
- **Listenbereich** wählen → nur Listen aus diesen Bereichen
  (Unterordnern). Leer → alle.
- **Große Listen einbeziehen** → auch sehr große Blätter; Fragen dauern
  dann deutlich länger.

Unter der Antwort zeigt **Liste: … (n Zeilen)**, welche Liste mit welcher
Abfrage benutzt wurde. **Erkannte Blätter** zeigt Blätter und Spalten,
**Nicht lesbar** Dateien mit Fehlern.

**Mein Listenordner:** eigenen Ordner bei **Ordner** eintragen →
**Übernehmen** → dessen Listen siehst nur du.

### Wie frage ich in LocaNoto die Datenbank ab?

Ist für einen deiner Arbeitsbereiche eine Datenbank eingerichtet, steht im
Chat unter „Arbeitsbereiche · Modell“ **Datenbank**.

- **Datenbank** ankreuzen → LocaNoto schreibt zu deiner Frage eine lesende
  Abfrage (SELECT) und nutzt das Ergebnis. Ändern kann LocaNoto an der
  Datenbank nichts.
- Unter der Antwort zeigt **Datenbankabfrage** die Abfrage.
- „No database connection: …“ → nennt den Grund (Server nicht
  erreichbar, Anmeldung abgelehnt …); die Antwort kommt dann nur aus den
  Dokumenten.

**Dokumente aus der Datenbank:** „Zeig mir die Rechnung 2025103“, „das
Datenblatt vom Kugelhahn“. Liegt das Dokument in der Datenbank oder in einem
freigegebenen Ordner, steht es unter der Antwort unter **Dokumente aus der
Datenbank**; PDFs und Bilder öffnen im Browser. Nach dem Inhalt fragen geht
auch: „Was steht auf der Rechnung 2025103?“

**Eigenes SQL-Login** (klassische Oberfläche: **Mein Datenbankzugang**): **Einstellungen** → **Meine Datenbanken** →
Benutzer und Passwort, die du vom Datenbank-Admin bekommen hast →
**Verbinden**. Abfragen laufen dann mit deinen Rechten in der Datenbank.
Das Login bleibt nur in der Browsersitzung. Hat der Admin ein gemeinsames
Lesekonto hinterlegt, geht es auch ohne eigenes Login.

### Wie arbeite ich in LocaNoto mit meinen eigenen Listen?

**Einstellungen** → **Meine Listen** zeigt deinen Ordner, z. B.
`/mnt/listen/LISTE/anna`: Der Admin legt eine Wurzel fest, jeder bekommt
darin einen Ordner mit seinem Benutzernamen. Excel- und CSV-Dateien dort
werden bei jeder Frage mit Listen gelesen; nur du siehst sie.

- **Unterordner (optional)** → nur dieser Teil deines Ordners zählt.
- **Listen neu einlesen** → nach neuen Dateien oder geänderten Spalten;
  neue Zeilen wirken ohne Zutun.

### Wie verbinde ich mein Postfach mit LocaNoto?

**Einstellungen** → **Meine Postfächer** → je Postfach Mailadresse und
Passwort eintragen → **Verbinden**. LocaNoto prüft die Anmeldung sofort.

„Noch kein Postfach eingerichtet" → ein Admin muss den Exchange-Server
einmal hinterlegen.

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
die Antwort eine Mail senden, erscheint darunter **Entwurf: … — wartet auf
dich** mit Empfänger, Betreff und Text.

- **Senden** → verschickt den Entwurf so, wie er dort steht.
- **Verwerfen** → verschickt nichts.

Geht beim Senden etwas schief, steht der Grund im Entwurf:

- **Nicht gesendet: …** → nichts ist hinausgegangen; **Senden** versucht
  es noch einmal.
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
Absender und Betreff → **Ansehen** öffnet einen Chat mit der Frage nach
den neuen Nachrichten.

**Einstellungen** → **Postfächer** → **Bei neuer Mail benachrichtigen**
schaltet das je Postfach aus und an. Ist kein LocaNoto-Tab offen, wird
nicht geprüft: Die Anmeldedaten liegen nur in der Browsersitzung.

### Wie arbeite ich mit Tickets in LocaNoto?

Hat ein Admin für ein Funktionspostfach das Ticketsystem eingeschaltet und
dich als Mitglied eingetragen, gibt es den Reiter **Tickets**.

- Jede neue Mail an das Postfach wird ein Ticket (z. B. T-2026-0001). Der
  Absender bekommt sofort die Standardantwort mit der Nummer; du bekommst
  eine Meldung. Die Zahl am Reiter zählt offene Tickets ohne Zuständigen.
- Ticket öffnen → **Übernehmen** (du bist zuständig, Status *in Arbeit*),
  **Status** setzen, **Notiz hinzufügen**.
- **Im Chat beantworten** → Chat mit dem Ticket als Frage; die Antwort
  geht als Entwurf über dein verbundenes Postfach.
- Antwortet der Kunde mit der Nummer im Betreff, landet die Mail beim
  selben Ticket und öffnet es wieder; der Zuständige bekommt eine Meldung.

### Wie suche ich mit LocaNoto im Internet?

**Dokumentfilter** → **Websuche** einschalten → LocaNoto sucht im Netz,
wenn deine Dokumente die Frage nicht beantworten. Hinaus geht nur der
Suchbegriff, keine Dokumente.

- Persönlicher Arbeitsbereich → geht immer.
- Geteilter Arbeitsbereich → ein Admin muss die Websuche dort erst
  erlauben. Sonst nennt die Seitenleiste die nicht freigegebenen
  Arbeitsbereiche; dann oben nur freigegebene wählen.
- **Allgemein** ist ab Werk gesperrt. Eine Frage mit Websuche über alle
  Arbeitsbereiche lässt ihn aus und sagt das unter der Antwort.

Treffer stehen unter der Antwort als **Aus dem Netz** mit [W1], [W2] …,
getrennt von den Dokumenten. Treffer ankreuzen → **n übernehmen** → sie
landen in deinem persönlichen Arbeitsbereich.

Ohne eingeschaltete Websuche kann LocaNoto eine Websuche **vorschlagen**,
etwa wenn die Dokumente nichts liefern oder nach Aktuellem gefragt ist.
Unter der Antwort steht dann **Websuche vorgeschlagen** mit dem genauen
Suchtext → **Im Web suchen** → die Antwort geht im selben Chat mit den
Treffern weiter. **Verwerfen** → nichts geht hinaus.

### Wie sammle ich mit LocaNoto Quellen aus dem Internet?

1. Reiter **Quellen im Netz** → **Thema** in Stichworten → **Suchen**.
   Oder im Chat Stichworte ins Eingabefeld → **Im Web suchen**.
   Der Suchbegriff geht an Suchmaschinen: keine internen Namen oder
   Zahlen.
2. Die Suche läuft im Hintergrund, die Seite darf verlassen werden. Sind
   die Treffer da (bis zu 25), erscheint eine Meldung mit **Ansehen**, und
   der Reiter **Quellen im Netz** zeigt eine Zahl.
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

**Einstellungen** → **Meine Anweisung** → Text eintragen, etwa „Antworte
knapp, mit Tabellen, und nenne immer die Norm." → **Speichern**.

- Gilt ab der nächsten Frage für alle deine Antworten, auch über die
  Schnittstelle.
- **Entfernen** → nimmt sie wieder heraus.
- Höchstens 2000 Zeichen; verschlüsselt gespeichert, andere sehen sie
  nicht.

Die Anweisung verfeinert nur. Die Grundregeln (Quellen nennen, nichts
erfinden) legen die Admins in den Prompts fest; sie gehen vor.

### Wie ändere ich mein Passwort in LocaNoto?

**Einstellungen** → **Passwort ändern** → **Bisheriges Passwort**,
**Neues Passwort (mind. 8 Zeichen)**, **Wiederholen** → **Ändern**.

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

**Einstellungen** → **Meine Zugangstoken** → zeigt alle Token auf deinen
Namen mit Bezeichnung und Ablaufdatum. **🗑️** → widerruft ein Token sofort.
Nicht mehr gebrauchte Token widerrufen.

### Was sehen Admins von meiner Arbeit in LocaNoto?

- **Chats:** nichts in der Anwendung; sie liegen verschlüsselt.
- **Persönlicher Arbeitsbereich:** Admins sehen Dateinamen, nie den Inhalt,
  und können Dateien löschen. Im strengen Betrieb sehen sie nicht einmal
  die Dateinamen. Den Inhalt erreichen sie nur über den Notzugang, den eine
  zweite Person bestätigen muss; beide Namen stehen im Protokoll.
- **Rückmeldungen:** Fragen mit 👍/👎 und Fragen ohne Treffer im Wortlaut,
  mit deiner Kennung.
- **Postfach-Anmeldungen:** niemand; sie werden nicht gespeichert.

Wer Zugriff auf den Server selbst hat, kann technisch mehr; dagegen
schützen ein verschlüsselter Datenträger und ein kleiner Kreis mit
Serverzugang.

## Teil 2: LocaNoto verwalten (für Admins)

Benutzer, Rollen, Arbeitsbereiche, gemeinsamer Bestand, Listen,
Zugangstoken und Schnittstelle, Postfächer, Notzugang, Rückmeldungen,
Glossar, Prompts, Voreinstellungen, ownCloud, Sicherung und Störungen.

### Wo finde ich als Admin den Admin-Bereich in LocaNoto?

Admins sehen unten in der Seitenleiste den Schalter **Admin-Bereich**.
Einschalten → darunter erscheinen:

Rückmeldungen, Benutzer, Zugangstoken (Schnittstelle), Postfächer
(Werkzeugserver), Verschlüsselung, Notzugang, Arbeitsbereiche, ownCloud,
Sicherung der Vektordatenbank, Sicherheitslage, Speicherorte, Glossar,
Voreinstellungen, Prompts und Konfiguration.

Auch ohne den Schalter sehen Admins:

- **Nachtragen und neu einlesen** (unter **Dokumente**),
- **Listenquellen je Arbeitsbereich** (unter **Listen**),
- unter **Gespeicherte Dokumente** auch Dokumente in fremden
  Arbeitsbereichen.

### Wie werde ich Admin in LocaNoto?

- Ein vorhandener Admin: **Admin-Bereich** → **Benutzer** → Benutzer wählen
  → **Rolle** `admin` → **Rolle übernehmen**.
- Neue Installation: den allerersten Zugang legt `create_user.py` im
  Terminal an; er wird Admin. Danach verlangt das Skript die Anmeldung
  eines vorhandenen Admins.

Den letzten Admin kann niemand herabsetzen oder löschen.

### Wie lege ich als Admin einen Benutzer in LocaNoto an?

**Admin-Bereich** → **Benutzer** → bei **Bearbeiten** „(neu anlegen)":

1. **Kennung** – Buchstaben, Ziffern, Punkt, Strich, Unterstrich.
2. **Rolle** – in der Regel `nutzer`.
3. **Passwort (mind. 8 Zeichen)** und **Passwort wiederholen**.
4. **Benutzer anlegen**.

→ Der persönliche Arbeitsbereich entsteht sofort; mit ownCloud auch Konto
und persönlicher Ordner dort.

Kennungen, die sich nur durch ein Sonderzeichen unterscheiden („m.meier",
„m_meier"), weist LocaNoto ab: sie ergäben denselben persönlichen
Arbeitsbereich.

### Wie ändere oder lösche ich als Admin einen Benutzer in LocaNoto?

**Admin-Bereich** → **Benutzer** → Benutzer bei **Bearbeiten** wählen:

- **Rolle** ändern → **Rolle übernehmen**.
- **Neues Passwort** zweimal → **Passwort setzen**. Der Benutzer ändert es
  danach am besten selbst. Gilt bei einem von LocaNoto verwalteten Konto
  auch in ownCloud.
- „… wirklich löschen" ankreuzen → **Benutzer löschen**. Ein verwaltetes
  ownCloud-Konto verschwindet mit. Chatverlauf und persönlicher
  Arbeitsbereich bleiben; die Dokumente löschst du getrennt unter
  **Gespeicherte Dokumente** (fremde persönliche Arbeitsbereiche).

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
der Notzugang eine Formalie.

### Wie lege ich als Admin einen Arbeitsbereich in LocaNoto an?

**Admin-Bereich** → **Arbeitsbereiche** → bei **Bearbeiten** neu anlegen:
**Bezeichnung**, optional **Beschreibung**, **Mitglieder** →
**Arbeitsbereich anlegen**.

Bestehenden Arbeitsbereich wählen → dort änderbar:

- **Bezeichnung**, **Beschreibung**, **Mitglieder**,
- **ownCloud-Gruppe** → deren Mitglieder kommen hinzu,
- **Listenordner (xlsx, csv)**,
- **Websuche erlauben**,
- **Datenbankzugang** → eigenes Datenbankkonto für diesen Arbeitsbereich.

**Allgemein:** **Mitgliederliste verwenden** → nur Eingetragene sehen ihn;
**Für alle öffnen** → nimmt das zurück.

- **Arbeitsbereich entfernen** → nimmt ihn aus der Liste, die Dokumente
  bleiben.
- **Daten löschen** → entfernt nach Bestätigung seine Abschnitte aus der
  Suche und legt den Inhalt seines ownCloud-Ordners in den Papierkorb.

Persönliche Arbeitsbereiche haben genau einen Leser; Mitglieder lassen sich
dort nicht eintragen.

In der Web-Oberfläche: **Admin** → **Arbeitsbereiche** → Suchfeld über der
Liste → **Bearbeiten**. Die Mitglieder stehen dort als Kärtchen (× nimmt
eines heraus); hinzu kommt jemand über **Benutzer suchen und hinzufügen**:
einen Teil des Namens tippen, Vorschlag anklicken. Umgekehrt **Benutzer**
→ Namen suchen → **Arbeitsbereiche** → ebenso Bereiche suchen und
hinzufügen. Eine Liste aller Nutzer gibt es nicht; ab 20 Nutzern zeigt
die Benutzerliste erst nach einer Suche Treffer.

### Wie befülle ich als Admin den gemeinsamen Bestand in LocaNoto?

In **Allgemein** schreiben nur Admins. Drei Wege:

- **Oberfläche:** **Dokumente hochladen**, als Arbeitsbereich „Allgemein"
  wählen.
- **Terminal:** Dateien in den Dokumentenordner legen → `python ingest.py`.
  `INGEST_RAUM=einkauf python ingest.py` liest in einen anderen
  Arbeitsbereich ein.
- **Schnittstelle:** `POST /aufnehmen` mit dem Token eines Admins, eine
  Datei je Aufruf.

Gescannte Seiten liest die Texterkennung auf allen drei Wegen; was sie
nicht lesen kann, nennt `ingest.py` in seiner Ausgabe.

**Nachtragen und neu einlesen** (unter **Dokumente**):

- **Bilder nachtragen** → beschreibt Abbildungen im ganzen Bestand.
- **Dokumente neu einlesen** → liest den Dokumentenordner vollständig ein.

Beide laufen weiter, wenn du die Seite verlässt, und überspringen bereits
Verarbeitetes.

### Wie richte ich als Admin Listen (Excel, CSV) in LocaNoto ein?

Listen werden nicht vektorisiert: ein Katalog kennt Blätter und Spalten,
die Zeilen liest LocaNoto bei jeder Frage frisch. In der Seitenleiste unter
**Listen**:

- **Admin** → **Listen** → **Listenordner je Arbeitsbereich**: ein Ordner
  je geteiltem Arbeitsbereich; der Arbeitsbereich bestimmt, wer die
  Listen sieht.
- **Wurzel der persönlichen Ordner**, z. B. `/mnt/listen/LISTE` → jeder
  Nutzer bekommt `/mnt/listen/LISTE/<Benutzername>` und sieht ihn unter
  **Einstellungen** → **Meine Listen**. Auch `owncloud:/LISTE` geht.
- Freigaben auf mehreren Servern: im Installer `"lists_pvc": {"name":
  "claim", …}`, eingehängt unter `/mnt/listen/<name>`.
- **Liste hochladen:** Dateien wählen, **Hochladen in** (Unterordner)
  wählen → **n Datei(en) hochladen**. Nur bei beschreibbarem Ordner.
- **Listen neu einlesen:** nötig bei neuen Dateien oder geänderten
  Spalten; neue Zeilen wirken ohne Zutun.
- **Erkannte Blätter:** Spalten ohne Namen → Kopfzeile falsch erkannt.
  **Kopfzeile** korrigieren → **Übernehmen und neu einlesen**.

Ein Listenordner je Arbeitsbereich lässt sich auch unter **Admin-Bereich**
→ **Arbeitsbereiche** eintragen.

### Wie lege ich als Admin ein Zugangstoken für LocaNoto an?

**Admin-Bereich** → **Zugangstoken (Schnittstelle)**:

1. **Für wen** – der Benutzer, dessen Rechte das Token trägt.
2. **Bezeichnung** – Zweck, etwa „Masseningest Einkauf".
3. **Gültig (Tage, 0 = unbegrenzt)**.
4. **Token anlegen** → der Wert erscheint **genau einmal**; gespeichert
   wird nur sein Hashwert. Kopieren → **Notiert**.

Die Liste darunter zeigt alle Token; **🗑️** widerruft eines. Nutzer sehen
und widerrufen ihre eigenen unter **Einstellungen** → **Meine
Zugangstoken**.

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
| `POST /rueckmeldung` | 👍/👎 zu einer Antwort |
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

**Admin-Bereich** → **Postfächer (Werkzeugserver)** → **Neues Postfach**:

1. **Servertyp:** „Exchange/Outlook — direkt, ohne weiteren Server".
2. **Name:** `postfach` für den gemeinsamen Eintrag, `info` für info@ usw.
3. **Adresse oder Befehl:** Exchange-Server, etwa `owa.firma.de`; leer →
   wird automatisch gesucht.
4. **Postfach:** persönlich oder Funktionspostfach.
5. **Postfachadresse (nur Exchange):** Pflicht bei Funktionspostfach
   (`info@firma.de`), leer bei persönlich.
6. **Anlegen**.

Danach verbindet sich jeder Nutzer selbst unter **Meine Postfächer**; ein
gemeinsames Passwort gibt es nicht. **Werkzeuge abfragen** → prüft ein
Postfach mit deiner eigenen Anmeldung.

Andere Werkzeugserver (MCP) → Servertyp „MCP-Server über HTTP" oder
„lokaler Prozess (stdio)".

### Wie richte ich als Admin die Websuche in LocaNoto ein?

1. Suchdienst getrennt von LocaNoto betreiben (`REFERENZ.md`, „Websuche").
2. **Admin-Bereich** → **Postfächer (Werkzeugserver)** → **Neues
   Postfach** → **Servertyp** Websuche, **Adresse oder Befehl**
   `http://websuche:8000/mcp` → **Anlegen**.
3. Für jeden geteilten Arbeitsbereich: **Arbeitsbereiche** → Arbeitsbereich
   wählen → **Websuche erlauben** ankreuzen → erst dann können Nutzer dort
   die Websuche einschalten.

Warum die Freigabe: das Modell formuliert den Suchbegriff mit Abschnitten
des Arbeitsbereichs im Kontext, und der Suchbegriff geht an Suchmaschinen.
Im persönlichen Arbeitsbereich entscheidet jeder Nutzer selbst.

### Wann darf LocaNoto aus einem Postfach selbständig antworten?

Nur aus einem **Funktionspostfach**, bei dem beim Anlegen **darf selbst
antworten** angekreuzt ist. Ein persönliches Postfach legt jede Mail als
Entwurf vor, ohne Ausnahme.

- **Hinweis unter Autoantworten setzen** ankreuzen → jede selbständig
  verschickte Mail trägt einen Hinweis, dass sie automatisch erstellt
  wurde. Wortlaut: **Hinweistext**.
- Ohne Haken → kein Hinweis.
- Ein vom Nutzer geprüfter, mit **Senden** verschickter Entwurf trägt nie
  einen Hinweis.

**Werkzeuge abfragen** markiert Werkzeuge, die etwas verschicken, mit
**[SENDET]**; alle anderen lesen nur.

### Wie richte ich als Admin ein Ticketsystem für ein Funktionspostfach in LocaNoto ein?

**Admin** → **Postfächer** → je Funktionspostfach ein Abschnitt
**Ticketsystem**:

1. **Ticketsystem an** ankreuzen.
2. Es wird **keine Anmeldung gespeichert**. Mitglieder verbinden das
   Postfach unter **Einstellungen** → **Postfächer** mit ihrem eigenen
   Konto (Rechte auf das Postfach in Exchange, zum Antworten „Senden als“).
3. **Standardantwort**: geht sofort an jeden Absender. `{ticket}`,
   `{subject}` und `{name}` werden eingesetzt.
4. **Mitglieder**: LocaNoto-Benutzer, die jedes Ticket sehen und gemeldet
   bekommen. Admins sehen alle Tickets.
5. Optional **Jede neue Mail weiterleiten an**: Adressen, die jede neue
   Mail mit Ticketnummer im Betreff bekommen.
6. **Speichern** → **Jetzt prüfen** (mit deinem eigenen verbundenen
   Login). Die erste Prüfung merkt nur die Uhrzeit; ab dann wird jede neue
   Mail ein Ticket.

Geprüft wird jede Minute (`TICKET_POLL_SECONDS`), solange ein Mitglied mit
verbundenem Postfach LocaNoto offen hat. Ist niemand online, werden die
inzwischen eingegangenen Mails beim nächsten Mal bearbeitet, samt
Standardantwort. Automatische Mails
(Abwesenheitsnotizen, Newsletter, Unzustellbarkeitsmeldungen, Mails des
Postfachs selbst) werden weder Ticket noch beantwortet. Eine Mail wird als
erledigt markiert, bevor etwas gesendet wird: Sie wird nie zweimal
beantwortet.

### Wie funktioniert der Notzugang in LocaNoto?

Ein persönlicher Arbeitsbereich ist auch für Admins zu. Scheidet jemand aus
oder fällt länger aus:

1. Ein Admin: **Admin-Bereich** → **Notzugang** → **Arbeitsbereich**
   wählen, **Grund** eintragen → **Notzugang beantragen**.
2. Eine Person mit der Rolle `notzugang` meldet sich an → **Bestätigen**
   oder **Ablehnen**.
3. Bestätigt → der Zugang gilt 24 Stunden und erlischt von selbst;
   **Jetzt schließen** beendet ihn früher.

Beide Namen und der Grund stehen im Protokoll. Ohne jemanden mit der Rolle
`notzugang` gibt es keinen Notzugang: der Arbeitsbereich ist dann nur
löschbar, nicht lesbar.

### Wie werte ich als Admin die Rückmeldungen in LocaNoto aus?

**Admin-Bereich** → **Rückmeldungen** zeigt:

- **Fragen ohne Treffer** – meist fehlt ein Glossareintrag oder ein
  Dokument.
- **Als nicht hilfreich gemeldet** – Treffer gab es, aber die falschen.

**Protokoll herunterladen** → die vollständige Liste. **Liste
abschließen** → legt sie unter dem Tagesdatum ab und beginnt eine neue;
gelöscht wird nichts. Frühere Ablagen stehen darunter.

Die Liste enthält Fragen im Wortlaut mit Kennung und liegt deshalb
verschlüsselt.

### Wie pflege ich als Admin das Glossar in LocaNoto?

Das Glossar übersetzt Wörter der Nutzer in die Wörter der Dokumente.
**Admin-Bereich** → **Glossar**, eine Zuordnung je Zeile, `#` =
Kommentar:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Glossar speichern** → wirkt ab der nächsten Frage. Kommentarzeilen gehen
nicht ans Sprachmodell.

Nur geprüfte Zuordnungen eintragen: ein falscher Eintrag lenkt die Suche
zuverlässig an die falsche Stelle. Kandidaten liefern die „Fragen ohne
Treffer" unter **Rückmeldungen**.

### Wie passe ich als Admin Prompts und Voreinstellungen in LocaNoto an?

**Prompts:** zwei Vorlagen – eine bildet aus der Frage die Suchanfragen,
die andere legt fest, wie geantwortet wird.

- **Gilt für** → alle oder nur eine Voreinstellung.
- **Speichern** → wirkt ab der nächsten Frage; ein Text ohne die
  Pflicht-Platzhalter wird abgelehnt.
- **Zurücksetzen** → stellt die mitgelieferte Fassung wieder her.

**Voreinstellungen** (für alle): **Bezeichnung**, **Beschreibung**,
**Chat-Modell**, **Relevante Abschnitte** (0 = Vorgabe), **Listenbereiche**
→ **Speichern**. **Entfernen** löscht. Nur diese Voreinstellungen können
eigene Prompts haben (unter **Prompts** bei **Gilt für** wählen).

Wählbare Modelle legt `CHAT_MODELLE` in der `.env` fest; dieselbe Liste
sehen Nutzer unter **Modell** und **Meine Voreinstellungen**. Nutzer legen
eigene Voreinstellungen ohne Prompts an und verfeinern mit **Meine
Anweisung**.

Nach einer Prompt-Änderung ein paar bekannte Fragen stellen und die
Antworten vergleichen.

### Wie binde ich als Admin ownCloud an LocaNoto an?

„ownCloud" meint die Dateiablage, auch OpenCloud. In der `.env`
eingerichtet → LocaNoto legt hochgeladene Dokumente auch dort ab und
übernimmt Ordner und Gruppen. **Admin-Bereich** → **ownCloud**:

- **Zuordnung speichern** → ordnet einem Arbeitsbereich einen Ordner zu.
- **Alle einrichten** → je Arbeitsbereich ein Ordner, geteilt mit seinen
  Mitgliedern.
- **Persönliche Ablage einrichten** → zieht Konto und Ordner eines Nutzers
  nach.
- **Änderungen prüfen** → zeigt, was sich in ownCloud geändert hat.
- **Mitgliedschaften abgleichen** → übernimmt ownCloud-Gruppen als
  Mitglieder.
- **Konten übernehmen** → markiert vorhandene Konten einmalig als von
  LocaNoto verwaltet (Dienst- und Admin-Konto ausgenommen).

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
   Die Suche läuft währenddessen mit dem alten Modell weiter. Abbrechen
   und später neu starten ist jederzeit möglich, er macht dort weiter.
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
3. **Vektordatenbank:** **Admin-Bereich** → **Sicherung der
   Vektordatenbank** → **Jetzt sichern**. Wiederherstellen: **Abzug
   einspielen** → **Einspielen**. Ohne Abzug hieße ein Verlust: alles neu
   einlesen.

Die Originaldokumente liegen im Datenverzeichnis und, falls angebunden, in
ownCloud.

### Was zeigen Sicherheitslage, Speicherorte, Verschlüsselung und Konfiguration in LocaNoto?

Im **Admin-Bereich**:

- **Sicherheitslage** – Prüfliste mit ✅ und ⚠️: was eingerichtet ist, was
  offen bleibt.
- **Speicherorte** – wo Daten, Konfiguration und Index liegen und ob der
  Ort von außen gesetzt ist.
- **Verschlüsselung** – was verschlüsselt, signiert oder im Klartext liegt.
  **Protokoll neu verschlüsseln** → bringt ältere Rückmeldungen in die
  verschlüsselte Form.
- **Konfiguration** – Einstellungen der `.env`, die fehlen, abweichen oder
  veraltet sind; nur Namen, keine Werte.

**Modell-Endpunkte** (unter **Einstellungen**, für alle) zeigt die
angebundenen Sprachmodelle und ob der Endpunkt für die Rangfolge der
Treffer antwortet.

### Was tue ich als Admin, wenn in LocaNoto etwas nicht funktioniert?

| Beobachtung | Abhilfe |
|---|---|
| Seite reagiert nach einem Update nicht | Seite neu laden, neu anmelden |
| Suche hängt nach den Suchanfragen | Modellserver nicht erreichbar oder kalt; die Meldung nennt den Grund |
| „RANGFOLGE Modell aus dem Image" | Rerank-Endpunkt nicht erreichbar; LocaNoto versucht es von selbst wieder |
| „Keine Datenbankverbindung" | Datenbank oder VPN prüfen; **Treibermeldung** zeigt Details |
| Dokument eingelesen, aber nicht auffindbar | `python raum_diagnose.py` im Container |
| Benutzerdatei „außerhalb geändert" | Signatur passt nicht; von Hand eingetragene Zugänge sind gesperrt |
| Einstellungen unklar | **Admin-Bereich** → **Konfiguration** |

Nach einem Update → `python selbsttest.py` prüft Anmeldung, Rechte, Suche,
Verschlüsselung und Sicherung, ohne den Bestand anzufassen.

## Teil 3: Dieses Handbuch in LocaNoto

Wie das Handbuch eingelesen und aktuell gehalten wird, damit LocaNoto
Fragen zur eigenen Bedienung beantwortet.

### Wie kann LocaNoto Fragen zu sich selbst beantworten?

Jede Überschrift dieses Handbuchs ist eine Frage, jeder Abschnitt für sich
verständlich – so findet LocaNoto ihn wie jedes andere Dokument.

- Einlesen: als Admin `HANDBUCH.md` hochladen, Arbeitsbereich
  **Allgemein** → LocaNoto beantwortet Fragen wie „Wie lade ich ein
  Dokument hoch?" mit Verweis auf den passenden Abschnitt.
- Neue Fassung: unter **Gespeicherte Dokumente** → **Allgemein** die alte
  Fassung mit **Löschen** entfernen, dann die neue hochladen. Bloßes
  Überschreiben ließe Abschnitte stehen, die es nicht mehr gibt.
