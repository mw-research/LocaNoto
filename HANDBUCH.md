# LocaNoto – Handbuch

LocaNoto ist ein Assistent, der Fragen aus den eigenen Unterlagen eines
Hauses beantwortet: aus hochgeladenen Dokumenten, auf Wunsch auch aus
Listen (Excel, CSV), einer Fachdatenbank und angebundenen Postfächern.
Alles läuft auf eigenen Servern; die Dokumente verlassen das Haus nicht.

Dieses Handbuch hat zwei Teile: **für Nutzer** und **für Verwalter**. Jeder
Abschnitt beantwortet eine Frage und ist für sich verständlich. Die
technische Referenz für Einrichtung und Betrieb steht in der `README.md`.

## Teil 1: LocaNoto benutzen (für Nutzer)

Dieser Teil erklärt Anmelden, Fragen stellen, Quellen lesen, Dokumente
hochladen, Chats, Räume, Listen, Datenbank, Postfächer, Passwort und
Zugangstoken in LocaNoto.

### Was ist LocaNoto und woher kommen die Antworten?

LocaNoto beantwortet Fragen aus den Dokumenten, die im Haus hinterlegt
sind. Zu jeder Frage sucht LocaNoto die passenden Abschnitte in den
Dokumenten heraus – über Bedeutung und über Stichworte zugleich – und ein
Sprachmodell formuliert daraus die Antwort. Unter jeder Antwort stehen die
verwendeten Quellen mit Datei und Seite.

LocaNoto durchsucht nur die Räume, die du sehen darfst. Was nicht im
Bestand steht, kann LocaNoto nicht wissen; dann sagt die Antwort das.

### Wie melde ich mich bei LocaNoto an und ab?

Anmelden: **Benutzername** und **Passwort** eingeben, **Einloggen**. Den
Zugang legt ein Verwalter an.

Abmelden: **🚪 Ausloggen** in der Seitenleiste. Nach längerer Zeit ohne
Eingabe endet die Anmeldung von selbst (Vorgabe: 480 Minuten); dann
erneut anmelden.

Zeigt die Seite nach einem Update keine Reaktion mehr, ist die Verbindung
zum Server neu aufgebaut worden: Seite neu laden und erneut anmelden.

### Wie stelle ich LocaNoto eine Frage?

Die Frage ins Eingabefeld unten schreiben (**Frage an die Datenbank**) und
abschicken. Bilder – etwa ein Foto oder ein Screenshot – lassen sich an die
Frage anhängen (png, jpg, webp, gif, bmp); LocaNoto beschreibt sie und
bezieht sie ein.

Während eine Antwort entsteht, ist die Seitenleiste gesperrt. Ein Klick
dort würde die Antwort abbrechen. Steht unter einer Antwort
„Abgebrochen – die Antwort ist unvollständig", die Frage noch einmal
stellen.

Nachfragen im selben Chat beziehen sich auf den bisherigen Verlauf.

### Woran sehe ich in LocaNoto, woher eine Antwort stammt?

Unter jeder Antwort steht **📚 Verwendete Quellen**: je Fundstelle ein
Eintrag **📄 Datei (Seite n)**. Aufgeklappt zeigt er den Textabschnitt,
auf den sich die Antwort stützt. Die Verweise im Antworttext sind
anklickbar und springen zur zugehörigen Quelle.

Bei PDF-Dateien lädt **👁️ Original-Seite n als Bild laden** die
Originalseite, etwa um eine Tabelle oder Zeichnung im Original zu sehen.
Bei Word- und Markdown-Dateien steht statt der Seite die Nummer des
Abschnitts.

**🛠️ Debug-Röntgenblick** zeigt, mit welchen Suchanfragen gesucht wurde
und was das Sprachmodell zu sehen bekam.

### Warum findet LocaNoto etwas nicht?

Die häufigsten Gründe:

- **Das Dokument liegt in einem Raum, den du nicht siehst.** LocaNoto
  durchsucht nur deine Räume.
- **Ein Filter ist gesetzt.** Unter **🎯 Dokumenten-Filter** Raum, Projekt
  und „Suche beschränken auf" leeren.
- **Das Dokument verwendet ein anderes Wort.** Fragt man nach „BANF" und
  das Dokument schreibt „Bestellanforderung", hilft das Glossar, das ein
  Verwalter pflegt. Fragen ohne Treffer werden dafür automatisch vermerkt.
- **Das Dokument ist ein Scan ohne Textebene.** Dann ist es nicht
  durchsuchbar; beim Hochladen erscheint eine Meldung dazu.

Mehr Treffer holt der Regler **Relevante Abschnitte abrufen** (Vorgabe 5).

### Wie grenze ich die Suche in LocaNoto ein?

In der Seitenleiste unter **🎯 Dokumenten-Filter**:

- **Raum:** nur in bestimmten Räumen suchen. Leer heißt: alle deine Räume.
- **Projekt:** nur Dokumente eines Projekts aus deinem persönlichen Raum.
- **Suche beschränken auf:** einzelne Dokumente auswählen. Die Liste zeigt
  nur Dokumente, die zu Raum und Projekt darüber passen.

Der Regler **Relevante Abschnitte abrufen** bestimmt, wie viele Fundstellen
in eine Antwort eingehen. Mehr hilft bei umfangreichen Regelwerken, macht
die Antwort aber langsamer.

### Was sind Räume in LocaNoto und wer sieht meine Dokumente?

Ein Raum legt fest, wer ein Dokument finden kann.

| Raum | sichtbar für | hochladen und löschen |
|---|---|---|
| Allgemein | alle Nutzer | nur Verwalter |
| ein benannter Raum (Abteilung, Projekt, Kunde) | seine Mitglieder | seine Mitglieder |
| dein persönlicher Raum | nur du | du und Verwalter |

Jeder Nutzer hat ab seinem ersten Tag einen persönlichen Raum. Was dort
liegt, fließt nie in die Antworten anderer ein. Welche Räume du siehst,
steht unter **Dokumente** in der Seitenleiste.

### Wie lade ich ein Dokument in LocaNoto hoch?

1. In der Seitenleiste **Dokumente hochladen** – PDF, Word (docx),
   Markdown oder Text. Mehrere Dateien auf einmal gehen.
2. **Raum** wählen. Vorgegeben ist dein persönlicher Raum („Nur für dich
   sichtbar"), sodass nichts versehentlich geteilt wird.
3. Optional ein **Projekt** angeben (nur im persönlichen Raum). Es sortiert
   und lässt sich später im Filter wählen.
4. **Abbildungen und gescannte Seiten beschreiben** nur ankreuzen, wenn
   Bilder oder Scans wichtig sind: es kostet einen Modellaufruf je Bild und
   bei großen Scans Minuten. Die Zahl der Aufrufe steht vorher darunter.
5. **Hochladen & Vektorisieren**.

Danach meldet LocaNoto je Datei, wie viele Abschnitte durchsuchbar sind.
„wurde NICHT durchsuchbar" heißt fast immer: Scan ohne Textebene.

### Wie verschiebe oder lösche ich ein Dokument in LocaNoto?

Unter **Dokumente** in der Seitenleiste steht je Raum ein Aufklapper mit
seinen Dateien. In Räumen, in die du schreiben darfst:

- **Dokument verwalten** – die Datei wählen,
- **verschieben nach** und **Verschieben** – in einen anderen Raum, etwa
  um etwas aus dem persönlichen Raum mit einer Abteilung zu teilen,
- **🗑️ Löschen** – entfernt die Datei samt ihren Abschnitten aus der Suche.

Steht dort „Nur lesen", darfst du in diesem Raum nichts ändern.

### Wie arbeite ich in LocaNoto mit Chats?

Unter **💬 Chats** in der Seitenleiste:

- **➕ Neuer Chat** beginnt ein neues Gespräch ohne Vorgeschichte.
- **Vorherige Chats laden** öffnet ein früheres Gespräch.
- **🗑️ Aktuellen Chat löschen** entfernt das geöffnete Gespräch.

Chats werden automatisch gespeichert und sind nur für dich sichtbar. Sie
liegen verschlüsselt auf dem Server, samt Titeln und angehängten Bildern.

Ein neues Thema gehört in einen neuen Chat: LocaNoto bezieht den Verlauf
eines Chats in die Antwort ein.

### Was bewirken Daumen hoch und Daumen runter in LocaNoto?

Unter jeder Antwort stehen 👍 („Hat geholfen") und 👎 („Hat nicht
geholfen"). Die Rückmeldung geht an die Verwalter, mit der Frage und den
verwendeten Quellen. Daraus sehen sie, welche Fragen der Bestand gut
beantwortet und wo Dokumente oder Glossareinträge fehlen.

Fragen, zu denen nichts gefunden wurde, werden auch ohne Klick vermerkt.
Stammte ein Treffer aus einem persönlichen Raum, steht in der Rückmeldung
statt des Dateinamens nur „(persoenlicher Raum)".

### Was ist eine Voreinstellung in LocaNoto?

Eine Voreinstellung bündelt Einstellungen für einen Einsatzzweck:
Sprachmodell, Zahl der Fundstellen, Listenbereiche und auf Wunsch eigene
Formulierungen. Wählbar ist sie ganz oben in der Seitenleiste unter
**🎛️ Voreinstellung**; darunter steht, wofür sie gedacht ist.

Die Auswahl erscheint nur, wenn ein Verwalter Voreinstellungen angelegt
hat. **(Standard)** nutzt die Grundeinstellung.

### Wie frage ich in LocaNoto Listen aus Excel oder CSV ab?

Listen (xlsx, csv) werden nicht wie Dokumente eingelesen, sondern bei
jeder Frage frisch gelesen – neue Zeilen wirken sofort. Unter **📊 Listen**
in der Seitenleiste:

- **Listen mit abfragen** – LocaNoto wählt die passende Liste und liest die
  passenden Zeilen. Darunter steht, wie viele Blätter bereitstehen.
- **Bereich** – nur Listen aus bestimmten Unterordnern.
- **Grosse Listen einbeziehen** – sehr große Blätter; eine Frage dauert
  dann deutlich länger.

Unter der Antwort zeigt **📊 Liste: …**, welche Liste mit welcher Abfrage
benutzt wurde. **Erkannte Blaetter** zeigt, welche Blätter mit welchen
Spalten bereitstehen; **Nicht lesbar** nennt Dateien, die sich nicht lesen
ließen. In **📁 Mein Listenordner** lässt sich ein eigener Ordner
eintragen, dessen Listen nur du siehst.

### Wie frage ich in LocaNoto die Datenbank ab?

Ist eine Fachdatenbank angebunden, steht in der Seitenleiste
**🗄️ Datenbank**. Mit **Datenbank einbeziehen** formuliert LocaNoto zu
deiner Frage eine lesende Abfrage (SELECT) und bezieht das Ergebnis in die
Antwort ein. Ändern kann LocaNoto an der Datenbank nichts.

Unter der Antwort zeigt **🗄️ Datenbankabfrage** die ausgeführte Abfrage
und das verwendete Konto.

In **🗄️ Mein Datenbankzugang** trägst du dein eigenes Datenbankkonto ein.
Dann laufen Fragen mit deinen Rechten, und LocaNoto sieht nur die Tabellen,
die du sehen darfst. „Keine Verbindung zur Datenbank" heißt: die Antworten
kommen nur aus den Dokumenten; **Erneut verbinden** versucht es wieder.

### Wie verbinde ich mein Postfach mit LocaNoto?

Hat ein Verwalter Postfächer eingerichtet, steht in der Seitenleiste
**📬 Meine Postfächer**. Dort je Postfach Mailadresse und Passwort
eintragen und **Verbinden**. LocaNoto prüft die Anmeldung sofort.

Danach kann LocaNoto Mails einbeziehen, zum Beispiel:

- „Was hat Frau Meier zuletzt geschrieben?"
- „Fasse mir die Mails der letzten 24 Stunden zusammen."
- „Antworte auf die Mail von Herrn Braun, dass der Termin passt."

Die Anmeldedaten liegen nur in deiner laufenden Sitzung. Sie werden nicht
gespeichert und verschwinden beim Abmelden; danach neu verbinden.
**Trennen** beendet die Verbindung vorher.

Funktionspostfächer (etwa info@) öffnest du mit deinen eigenen Daten;
Exchange entscheidet, ob du Zugriff hast.

### Was passiert, wenn LocaNoto eine Mail verschicken will?

LocaNoto verschickt aus einem persönlichen Postfach **nie selbständig**.
Will die Antwort eine Mail senden, erscheint darunter
**✍️ Entwurf: … – wartet auf dich** mit Empfänger, Betreff und Text.

- **Senden** verschickt den Entwurf so, wie er dort steht.
- **Verwerfen** verschickt nichts.

Nur ein Funktionspostfach kann ein Verwalter für selbständige Antworten
freischalten. Solche Mails tragen dann in der Regel einen Hinweis, dass sie
automatisch erstellt wurden.

### Wie ändere ich mein Passwort in LocaNoto?

In der Seitenleiste **🔑 Passwort aendern**: **Bisheriges Passwort**,
**Neues Passwort** (mindestens 8 Zeichen), **Wiederholen**, dann
**Aendern**.

Passwort vergessen: ein Verwalter setzt ein neues. Das ändert sich danach
am besten sofort selbst, damit niemand anders es kennt.

### Was sind meine Zugangstoken in LocaNoto?

Ein Zugangstoken erlaubt Programmen und Skripten, LocaNoto über die
HTTP-Schnittstelle zu fragen oder Dokumente einzuliefern – mit deinen
Rechten. Angelegt wird ein Token von einem Verwalter; der Wert wird genau
einmal angezeigt.

Unter **🎫 Meine Zugangstoken** siehst du alle Token, die auf dich
ausgestellt sind, mit Bezeichnung und Ablaufdatum. **🗑️** widerruft ein
Token sofort. Was du nicht mehr brauchst, widerrufe.

### Was sehen Verwalter von meiner Arbeit in LocaNoto?

- **Chats:** nicht in der Anwendung. Sie liegen verschlüsselt.
- **Persönlicher Raum:** Verwalter sehen die Dateinamen, nie den Inhalt, und
  können Dateien löschen. Im strengen Betrieb sehen sie nicht einmal die
  Dateinamen. Den Inhalt erreichen sie nur über den Notzugang, den eine
  zweite Person bestätigen muss; beide Namen stehen im Protokoll.
- **Rückmeldungen:** Fragen mit 👍/👎 und Fragen ohne Treffer sehen
  Verwalter im Wortlaut, zusammen mit deiner Kennung.
- **Postfach-Anmeldungen:** niemand; sie werden nicht gespeichert.

Wer Zugriff auf den Server selbst hat, kann technisch mehr. Dagegen
schützen ein verschlüsselter Datenträger und ein kleiner Kreis mit
Serverzugang.

## Teil 2: LocaNoto verwalten (für Verwalter)

Dieser Teil erklärt Benutzer, Rollen, Räume, den gemeinsamen Bestand,
Listen, Zugangstoken und Schnittstelle, Postfächer, Notzugang, Rückmeldungen,
Glossar, Prompts, Voreinstellungen, ownCloud, Sicherung und Störungen.

### Wo finde ich als Verwalter die Verwaltung in LocaNoto?

Verwalter sehen in der Seitenleiste den Schalter **🛠️ Verwaltung**.
Eingeschaltet erscheinen darunter die Bereiche: 📝 Rueckmeldungen,
👥 Benutzer verwalten, 🎫 Zugangstoken für die Schnittstelle,
📬 Postfächer (Werkzeugserver), 🔐 Verschlüsselung, 🔓 Notzugang,
🚪 Räume verwalten, ☁️ ownCloud, 🗃️ Sicherung der Vektordatenbank,
🔒 Sicherheitslage, 💾 Speicherorte, 🗣️ Glossar bearbeiten,
🎛️ Voreinstellungen verwalten, 📜 Prompts bearbeiten und ⚙️ Konfiguration.

Unabhängig vom Schalter sehen Verwalter außerdem **🔄 Nachtragen und neu
einlesen**, **Listenquellen je Raum** und unter den Dokumenten die
Dokumente in fremden Räumen.

### Wie werde ich Verwalter in LocaNoto?

Die Rolle steht in der signierten Benutzerdatei. Ein vorhandener Verwalter
vergibt sie unter **👥 Benutzer verwalten** → Benutzer wählen → **Rolle**
→ **Rolle übernehmen**.

Den allerersten Zugang einer neuen Installation legt `create_user.py` im
Terminal an; er wird Verwalter. Danach verlangt das Skript die Anmeldung
eines vorhandenen Verwalters.

Den letzten Verwalter kann niemand herabsetzen oder löschen – sonst könnte
niemand mehr Benutzer anlegen.

### Wie lege ich als Verwalter einen Benutzer in LocaNoto an?

**🛠️ Verwaltung** → **👥 Benutzer verwalten** → bei **Bearbeiten**
„(neu anlegen)":

1. **Kennung** – Buchstaben, Ziffern, Punkt, Strich, Unterstrich.
2. **Rolle** – in der Regel `nutzer`.
3. **Passwort** zweimal, mindestens 8 Zeichen.
4. **Benutzer anlegen**.

Der persönliche Raum entsteht dabei sofort. Ist ownCloud angebunden,
richtet LocaNoto dort Konto und persönlichen Ordner mit ein. Kennungen, die
sich nur durch ein Sonderzeichen unterscheiden („m.meier" und „m_meier"),
weist LocaNoto ab: sie ergäben denselben persönlichen Raum.

Mehrere Verwalter können gleichzeitig anlegen; kein Eintrag geht verloren.

### Wie ändere oder lösche ich als Verwalter einen Benutzer in LocaNoto?

Unter **👥 Benutzer verwalten** den Benutzer bei **Bearbeiten** wählen:

- **Rolle** ändern und **Rolle übernehmen**,
- **Neues Passwort** zweimal eintragen und **Passwort setzen** – der
  Benutzer ändert es danach am besten selbst,
- **wirklich löschen** ankreuzen und **Benutzer löschen**.

Beim Löschen bleiben Chatverlauf und persönlicher Raum bestehen. Die
Dokumente entfernt ein Verwalter getrennt, unter den Dokumenten in fremden
Räumen.

Jede Änderung steht im verketteten Benutzerprotokoll. Steht oben „Die
Benutzerdatei wurde außerhalb der Anwendung geändert", passt eine Signatur
nicht: bestehende Nutzer arbeiten weiter, ein von Hand eingetragener Zugang
ist gesperrt.

### Welche Rollen gibt es in LocaNoto?

| Rolle | darf |
|---|---|
| `nutzer` | fragen, in eigene und freigegebene Räume hochladen |
| `admin` | zusätzlich Benutzer, Räume, gemeinsamen Bestand und alle Einstellungen verwalten |
| `notzugang` | nichts davon – nur den Notzugang eines Verwalters zu einem persönlichen Raum bestätigen oder ablehnen |

Die Rolle `notzugang` gehört an jemanden, der **kein** Verwalter ist:
Geschäftsführung, Personalrat oder wer im Haus dafür steht. Könnten
Verwalter einander bestätigen, wäre der Notzugang eine Formalie.

### Wie lege ich als Verwalter einen Raum in LocaNoto an?

**🛠️ Verwaltung** → **🚪 Räume verwalten** → bei **Bearbeiten** einen neuen
Raum: **Bezeichnung**, optional **Beschreibung**, **Mitglieder** wählen,
**Raum anlegen**.

Für einen bestehenden Raum lassen sich dort Bezeichnung, Beschreibung und
Mitglieder ändern, eine **ownCloud-Gruppe** zuordnen (dann bestimmt die
Gruppe die Mitglieder), ein **Listenordner** für xlsx/csv hinterlegen und
unter **Datenbankzugang dieses Raums** ein Datenbankkonto eintragen.

Auch der allgemeine Raum muss nicht allen offenstehen: **Auf eine
Mitgliederliste umstellen** gibt ihm eine Liste, **Wieder für alle öffnen**
nimmt sie zurück.

**Raum entfernen** nimmt den Raum aus der Verwaltung; die Dokumente bleiben
erhalten. **Daten löschen** ist ein eigener Schritt: er entfernt die
Abschnitte des Raums aus der Suche und verlangt vorher eine Bestätigung.
Persönliche Räume haben genau einen Leser; Mitglieder lassen sich dort
nicht eintragen.

### Wie befülle ich als Verwalter den gemeinsamen Bestand in LocaNoto?

In den Raum **Allgemein** schreiben nur Verwalter. Drei Wege:

- **Oberfläche:** Dokumente hochladen, als Raum „Allgemein" wählen.
- **Terminal:** Dateien in den Dokumentenordner legen und `python ingest.py`
  starten; `INGEST_RAUM=einkauf python ingest.py` liest in einen anderen
  Raum ein.
- **Schnittstelle:** `POST /aufnehmen` mit dem Token eines Verwalters – für
  viele Dateien auf einmal, eine Datei je Aufruf.

Bilder und Scans beschreibt der Upload nur auf Wunsch. Für den ganzen
Bestand startet **🔄 Nachtragen und neu einlesen** → **Bilder nachtragen**
das als eigenen Vorgang; **Dokumente neu einlesen** liest den
Dokumentenordner vollständig ein. Beide laufen weiter, wenn man die Seite
verlässt, und überspringen bereits Verarbeitetes.

### Wie richte ich als Verwalter Listen (Excel, CSV) in LocaNoto ein?

Listen werden nicht vektorisiert. Ein Katalog hält fest, welche Blätter und
Spalten es gibt; die Zeilen liest LocaNoto bei jeder Frage frisch. Unter
**📊 Listen** in der Seitenleiste:

- **Listenquellen je Raum:** eine Zeile je Quelle, `raum = pfad`. Der Raum
  bestimmt, wer die Listen sieht. `@privat = /pfad/{benutzer}/Listen` gibt
  jedem Nutzer seinen eigenen Ordner. **Quellen speichern und einlesen**.
- **Liste hochladen:** Dateien ablegen, einen **Bereich** (Unterordner)
  wählen, dann ablegen und einlesen. Geht nur, wenn der Ordner beschreibbar
  ist.
- **Listen neu einlesen:** nötig, wenn Dateien dazukommen oder Spalten sich
  ändern. Neue Zeilen wirken ohne Zutun.
- **Erkannte Blaetter:** stehen Spalten ohne Namen da, ist die Kopfzeile
  falsch erkannt. **Kopfzeile** korrigieren, dann **Uebernehmen und neu
  einlesen**.

Ein Listenordner je Raum lässt sich auch unter **🚪 Räume verwalten**
eintragen.

### Wie lege ich als Verwalter ein Zugangstoken für LocaNoto an?

**🛠️ Verwaltung** → **🎫 Zugangstoken für die Schnittstelle**:

1. **Für wen** – der Benutzer, dessen Rechte das Token trägt.
2. **Bezeichnung** – wofür es ist, etwa „Masseningest Einkauf".
3. **Gültig für Tage** – 0 heißt unbegrenzt.
4. **Token anlegen**.

Der Wert erscheint **genau einmal**; gespeichert ist nur sein Hashwert.
Notieren, dann **Habe ich notiert**. Die Liste darunter zeigt alle Token;
**🗑️** widerruft eines. Nutzer sehen und widerrufen ihre eigenen unter
**🎫 Meine Zugangstoken**.

Ein Token weist nur den Nutzer aus. Was er darf, steht in der
Benutzerdatei: in den allgemeinen Raum liefert nur das Token eines
Verwalters ein.

### Wie benutze ich die HTTP-Schnittstelle von LocaNoto?

Jeder Aufruf trägt das Token im Kopf `X-LocaNoto-Token`.

| Aufruf | Zweck |
|---|---|
| `GET /gesundheit` | Lebenszeichen, ohne Token |
| `GET /status` | Modelle, Bestand, Listen, Voreinstellungen |
| `GET /raeume`, `GET /dokumente` | was dieser Nutzer sehen darf |
| `POST /frage` | Antwort mit Quellen, `?strom=1` laufend |
| `POST /aufnehmen` | ein Dokument einliefern (Formular: `datei`, `raum`, optional `projekt`, `bilder`) |
| `POST /rueckmeldung` | 👍/👎 zu einer Antwort |
| `GET /hilfe` | die Schnittstelle beschreibt sich selbst |

Gesucht wird nur in den Räumen des Token-Besitzers. `/aufnehmen` antwortet
mit `403`, wenn der Nutzer in den Raum nicht schreiben darf, und mit `413`,
wenn die Datei zu groß ist. Die Schnittstelle ist nur vom Server selbst
erreichbar; von außen gehört ein Reverse Proxy mit TLS davor. Beispiele
stehen in der `README.md` unter „HTTP-Schnittstelle".

### Wie richte ich als Verwalter ein Postfach in LocaNoto ein?

**🛠️ Verwaltung** → **📬 Postfächer (Werkzeugserver)** → **Neues Postfach**:

1. **Art des Servers:** „Exchange/Outlook – direkt, ohne weiteren Server".
2. **Name:** kurz, etwa `info` oder `markus`.
3. **Adresse oder Befehl:** der Exchange-Server, etwa `owa.firma.de`.
   Leer lassen sucht den Server selbst.
4. **Postfach:** persönlich oder Funktionspostfach.
5. **Mailadresse des Postfachs:** bei einem Funktionspostfach Pflicht
   (`info@firma.de`), bei einem persönlichen leer.
6. **Anlegen**.

Danach verbindet jeder Nutzer sich selbst unter **📬 Meine Postfächer**.
Ein gemeinsames Passwort gibt es nicht; Exchange entscheidet über den
Zugriff. **Werkzeuge abfragen** prüft ein Postfach mit deiner eigenen
Anmeldung.

Andere Werkzeugserver nach dem Model-Context-Protocol (MCP) lassen sich
über die Vorlagen „MCP-Server über HTTP" und „lokaler Prozess" anbinden.

### Wann darf LocaNoto aus einem Postfach selbständig antworten?

Nur aus einem **Funktionspostfach**, und nur wenn beim Anlegen **darf
selbständig antworten** angekreuzt ist. Ein persönliches Postfach legt jede
Mail als Entwurf vor, ohne Ausnahme.

**Hinweis unter automatische Antworten setzen** hängt an jede selbständig
verschickte Mail einen Hinweis, dass sie automatisch erstellt wurde; den
Wortlaut legt **Text des Hinweises** fest. Ohne Haken entfällt der Hinweis.
Ein vom Nutzer geprüfter und mit **Senden** verschickter Entwurf trägt nie
einen Hinweis.

Welche Werkzeuge etwas verschicken, zeigt **Werkzeuge abfragen** mit
**[SENDET]**; alle anderen lesen nur.

### Wie funktioniert der Notzugang in LocaNoto?

Ein persönlicher Raum ist auch für Verwalter zu. Scheidet jemand aus oder
fällt länger aus, führt der Notzugang hinein:

1. Ein Verwalter beantragt unter **🔓 Notzugang** den Zugang zu genau
   einem Raum, mit **Grund** → **Notzugang beantragen**.
2. Eine Person mit der Rolle `notzugang` meldet sich an und klickt
   **Bestätigen** oder **Ablehnen**.
3. Der Zugang gilt danach 24 Stunden und erlischt von selbst;
   **Jetzt schließen** beendet ihn früher.

Beide Namen und der Grund stehen im Protokoll. Gibt es niemanden mit der
Rolle `notzugang`, gibt es keinen Notzugang – der Raum bleibt dann nur
löschbar, nicht lesbar.

### Wie werte ich als Verwalter die Rückmeldungen in LocaNoto aus?

**🛠️ Verwaltung** → **📝 Rueckmeldungen** zeigt zwei Listen:

- **Fragen ohne Treffer** – meist fehlt ein Wort im Glossar oder ein
  Dokument im Bestand.
- **Als nicht hilfreich gemeldet** – es gab Treffer, aber die falschen.

**Protokoll herunterladen** holt die vollständige Liste zum Auswerten.
**Liste abschliessen** legt sie unter dem Tagesdatum ab und beginnt eine
neue; gelöscht wird nichts. Frühere Ablagen stehen darunter zum
Herunterladen.

Die Liste enthält Fragen im Wortlaut mit Kennung und liegt deshalb
verschlüsselt.

### Wie pflege ich als Verwalter das Glossar in LocaNoto?

Das Glossar übersetzt Wörter der Nutzer in die Wörter der Dokumente.
**🛠️ Verwaltung** → **🗣️ Glossar bearbeiten**, je Zeile eine Zuordnung:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

**Glossar speichern** – es wirkt ab der nächsten Frage. Zeilen mit `#` sind
Erläuterungen und gehen nicht ins Sprachmodell. Nur geprüfte Zuordnungen
eintragen: ein falscher Eintrag lenkt die Suche zuverlässig an die falsche
Stelle. Woher die Einträge kommen: aus den „Fragen ohne Treffer" unter
📝 Rueckmeldungen.

### Wie passe ich als Verwalter Prompts und Voreinstellungen in LocaNoto an?

**📜 Prompts bearbeiten:** zwei Vorlagen – eine bildet aus der Frage die
Suchanfragen, die andere legt fest, wie geantwortet wird. **Gilt fuer**
wählt, ob die Änderung für alle oder nur eine Voreinstellung gilt.
**Speichern** wirkt ab der nächsten Frage; ein Text ohne die
Pflicht-Platzhalter wird abgelehnt. **Zuruecksetzen** stellt die
mitgelieferte Fassung wieder her.

**🎛️ Voreinstellungen verwalten:** **Bezeichnung**, **Beschreibung**,
**Chat-Modell**, **Relevante Abschnitte**, **Listenbereiche**, dann
**Speichern**. Nutzer wählen sie oben in der Seitenleiste. **Entfernen**
löscht eine Voreinstellung.

Eine Formulierung im Prompt wirkt auf jede folgende Antwort; nach einer
Änderung ein paar bekannte Fragen stellen und die Antworten vergleichen.

### Wie binde ich als Verwalter ownCloud an LocaNoto an?

Ist ownCloud in der `.env` eingerichtet, legt LocaNoto hochgeladene
Dokumente zusätzlich dort ab und kann Ordner und Gruppen übernehmen.
**🛠️ Verwaltung** → **☁️ ownCloud**:

- **Zuordnung speichern** – ordnet einem Raum einen ownCloud-Ordner zu.
- **Für alle Räume einrichten** – legt je Raum einen Ordner an und teilt
  ihn mit den Mitgliedern des Raums.
- **Persönliche Ablage einrichten** – zieht Konto und Ordner eines
  einzelnen Nutzers nach, etwa nach einer Übernahme.
- **Änderungen prüfen** – zeigt, was sich in ownCloud geändert hat.
- **Mitgliedschaften jetzt nachziehen** – übernimmt die ownCloud-Gruppen
  als Raummitglieder.

Einrichtung und Dienstkonto beschreibt die `README.md` unter „Dokumente aus
ownCloud".

### Wie sichere ich LocaNoto als Verwalter?

Drei Dinge gehören in die Sicherung:

1. **Der Installationsschlüssel** (`config/schluessel.key`, oder der Wert
   von `LOCANOTO_SCHLUESSEL`). Ohne ihn sind Chats, Anhänge und
   Rückmeldungen endgültig unlesbar – ohne Fehlermeldung. Nichts anderes
   lässt sich nachholen.
2. **Das Konfigurationsverzeichnis** (`config/`): Benutzer, Räume, Token,
   Glossar, Prompts, Postfächer.
3. **Die Vektordatenbank:** **🗃️ Sicherung der Vektordatenbank** →
   **Jetzt sichern**. **Abzug einspielen** und **Einspielen** stellen einen
   Stand wieder her. Ohne Abzug hieße ein Verlust: alles neu einlesen.

Die Originaldokumente liegen im Datenverzeichnis und, falls angebunden, in
ownCloud.

### Was zeigen Sicherheitslage, Speicherorte, Verschlüsselung und Konfiguration in LocaNoto?

- **🔒 Sicherheitslage** – eine Prüfliste mit ✅ und ⚠️: was an Schutz
  eingerichtet ist und was offen bleibt.
- **💾 Speicherorte** – wo Daten, Konfiguration und Index liegen und ob der
  Ort von außen gesetzt ist.
- **🔐 Verschlüsselung** – ob verschlüsselt wird und was verschlüsselt,
  signiert oder im Klartext liegt; **Protokoll neu verschlüsseln** bringt
  ältere Rückmeldungen in die verschlüsselte Form.
- **⚙️ Konfiguration** – Einstellungen der `.env`, die fehlen, von der
  Vorlage abweichen oder veraltet sind. Nur Namen, keine Werte.

**🔌 Modell-Endpunkte** (für alle sichtbar) zeigt, welche Sprachmodelle
angebunden sind und ob der Endpunkt für die Rangfolge der Treffer
antwortet.

### Was tue ich als Verwalter, wenn in LocaNoto etwas nicht funktioniert?

| Beobachtung | Ursache und Abhilfe |
|---|---|
| Seite reagiert nach einem Update nicht | Verbindung neu aufgebaut: Seite neu laden, neu anmelden |
| Suche hängt nach den Suchanfragen | Modellserver nicht erreichbar oder kalt; die Meldung nennt den Grund |
| „RANGFOLGE Modell aus dem Image" | Rerank-Endpunkt nicht erreichbar; LocaNoto versucht ihn von selbst wieder |
| „Keine Verbindung zur Datenbank" | Datenbank oder VPN nicht erreichbar; **Meldung des Treibers** zeigt Details |
| Dokument eingelesen, aber nicht auffindbar | `python raum_diagnose.py` im Container |
| Benutzerdatei „außerhalb geändert" | eine Signatur passt nicht; von Hand eingetragene Zugänge sind gesperrt |
| Einstellungen unklar | **⚙️ Konfiguration** |

Nach einem Update prüft `python selbsttest.py` Anmeldung, Rechte, Suche,
Verschlüsselung und Sicherung, ohne den Bestand anzufassen.

## Teil 3: Dieses Handbuch in LocaNoto

Dieser Teil erklärt, wie das Handbuch in LocaNoto eingelesen und aktuell
gehalten wird, damit LocaNoto Fragen zur eigenen Bedienung beantwortet.

### Wie kann LocaNoto Fragen zu sich selbst beantworten?

Dieses Handbuch ist so geschrieben, dass LocaNoto es wie jedes andere
Dokument durchsuchen kann: jede Überschrift ist eine Frage, und jeder
Abschnitt ist für sich verständlich.

Einlesen: als Verwalter `HANDBUCH.md` hochladen und als Raum **Allgemein**
wählen. Danach beantwortet LocaNoto Fragen wie „Wie lade ich ein Dokument
hoch?" oder „Wie lege ich einen Benutzer an?" mit Verweis auf diesen
Abschnitt.

Nach einer neuen Fassung das alte Handbuch unter **Dokumente** →
**Allgemein** mit **🗑️ Löschen** entfernen und die neue Fassung hochladen.
Beim bloßen Überschreiben blieben Abschnitte stehen, die es in der neuen
Fassung nicht mehr gibt.
