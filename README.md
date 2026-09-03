# LocaNoto - Lokales RAG System für technische Dokumentationen

LocaNoto durchsucht Fachdokumente und beantwortet Fragen dazu — mit Angabe der Fundstelle, Datei und Seite. Die Dokumente werden in Abschnitte zerlegt, vektorisiert und über zwei Suchwege gefunden; ein Sprachmodell formuliert daraus die Antwort.

Der Container spricht zur Laufzeit nur mit den Modellservern, die in der `.env` eingetragen sind. Die Dokumente selbst verlassen das eigene Netz nicht.

## 🚀 Features
* **Kein Netzzugang zur Laufzeit:** Ausgehende Verbindungen gehen ausschließlich an die Adressen, die in der `.env` stehen. Das Reranker-Modell wird beim Bauen in das Image geladen, die Telemetrie von ChromaDB und Streamlit ist abgeschaltet. Wo die Modelle laufen, entscheidet die Konfiguration — im eigenen Netz oder bei einem Anbieter.
* **Hybride Suche:** Semantische Vektorsuche (ChromaDB) kombiniert mit BM25-gerankter Keyword-Suche (SQLite FTS5, plattenbasiert).
* **Zweistufige Rangfolge:** Jede Suchsonde und jeder Suchweg liefert eine eigene Rangliste; Reciprocal Rank Fusion verschmilzt sie, danach bewertet ein Reranker die engere Auswahl. Bevorzugt über einen Endpunkt (`RERANKER_BASE_URL`), damit sich das Modell ohne Rebuild austauschen lässt; ist keiner erreichbar, greift das Modell **im Image**, und andernfalls rankt allein die Fusion. Keine dieser Stufen kann den Start verhindern.
* **Bilder im Chat:** An eine Frage lassen sich Bilder anhängen — ein Bildschirmausschnitt, ein Foto einer Anlage, eine abfotografierte Seite. Das Sehmodell wandelt sie in Text um; dieser Text dient als zusätzliche Suchsonde und geht gekennzeichnet in den Kontext der Antwort ein. Das Chat-Modell bekommt das Bild nicht und kann ein reines Textmodell bleiben.
* **HTTP-Schnittstelle:** Dieselbe Suche ohne Browser — eine Frage aus dem Terminal, ein Skript. Zugang über ein Token je Nutzer; die Trennung zwischen privaten und geteilten Dokumenten gilt dort genauso.
* **Sprachgebrauch und Rückmeldungen:** Fragen, die nichts finden, werden festgehalten; Nutzer können jede Antwort bewerten. Aus dieser Liste wächst ein Glossar der Hauswörter, die in den Dokumenten anders heißen.
* **Listen aus Tabellendateien:** `xlsx` und `csv` unter `data/tabellen/` werden nicht vektorisiert. Ein Katalog hält ihre Struktur, die Zeilen liest die Anwendung bei jeder Frage frisch — geänderte Listen wirken sofort.
* **Multi-Tenant-Architektur:** Getrennte Sichtbarkeit von Dokumenten und Chats je Nutzer.

## 🗂️ Sachgebiete

Unterordner in `data/dokumente/` werden als Sachgebiet übernommen und stehen
in der Seitenleiste als Filter zur Verfügung:

```
data/dokumente/
    Sachgebiet-A/      -> Sachgebiet "Sachgebiet-A"
    Sachgebiet-B/      -> Sachgebiet "Sachgebiet-B"
    dokument.pdf       -> Sachgebiet "(Basis)"
```

Sachgebiete dienen dazu, die Suche auf einen Teil des Bestands einzugrenzen.
Ist eines ausgewählt, berücksichtigen Vektor- und Keyword-Suche nur die
Dokumente daraus.

Sie sind optional: liegen alle Dateien direkt in `data/dokumente/`, gibt es
nur `(Basis)` und der Filter wird nicht eingeblendet.

## 📂 Datenverzeichnis

Der gesamte Bestand liegt unter `data/` und wird als eine Einheit
weitergegeben oder gesichert:

```
data/
    dokumente/   Original-PDFs
    chats/       Chatverläufe je Nutzer
    chroma_db/   Vektordatenbank
config/
    users.json   Benutzer und Passwort-Hashes (NICHT im Repo, NICHT in data/)
```

Die Struktur wird beim ersten Start automatisch angelegt. Ein vorhandener
`data/`-Ordner kann stattdessen einfach hineinkopiert werden.

> **Hinweis zur Weitergabe:** `data/chats/` enthält die Chatverläufe aller
> Nutzer. Vor der Weitergabe an Dritte entfernen.

## ⚙️ Ingest

```bash
python ingest.py          # Text und Tabellen
python ingest_images.py   # Abbildungen über das Vision-Modell
```

Der Bildlauf gibt dem Sehmodell die Bildunterschrift und den umgebenden Text
mit. Ohne sie sieht das Modell nur den freigeschnittenen Ausschnitt und
beschreibt Geometrie statt Bedeutung — welche Größe auf einer Achse steht und
zu welchem Regelwerk die Abbildung gehört, ist außerhalb des Bildes notiert.
Der Kontext steht auch im gespeicherten Chunk, denn er ist der Suchanker.

Beide Läufe sind unterbrechbar und setzen auf Chunk-Ebene wieder auf: die
Textextraktion läuft erneut — sie dauert nur Millisekunden pro Seite.
Vektorisiert wird nur, was fehlt; das ist der zeitintensive Teil. Ein
abgebrochener Lauf hinterlässt damit kein halb indexiertes
Dokument, das beim nächsten Start als erledigt gilt.

Stammt die Vektordatenbank aus einer Installation vor dem FTS5-Index, baut
die App ihn beim ersten Start automatisch auf. Vorab und außerhalb der
Weboberfläche geht das mit:

```bash
python rebuild_index.py
```

## 🧠 Rangfolge der Treffer

Nach der Suche werden die Ranglisten aller Sonden und beider Suchwege
verschmolzen (Reciprocal Rank Fusion). Die engere Auswahl bewertet danach ein
Reranker — dafür gibt es drei Stufen, die in dieser Reihenfolge versucht
werden:

| Stufe | wann | Konfiguration |
|---|---|---|
| **1. Rerank-Endpunkt** | `RERANKER_BASE_URL` gesetzt und erreichbar | Modell austauschbar ohne Rebuild |
| **2. Modell im Image** | sonst, wenn `RERANKER_MODEL` gesetzt | kein Netzzugriff, aber Rebuild bei Wechsel |
| **3. keiner** | sonst | allein die Fusion entscheidet |

Keine dieser Stufen kann den Start verhindern: schlägt eine fehl, wird die
nächste genommen. Welche gerade greift, steht in der Seitenleiste unter
**Modell-Endpunkte**.

Der Endpunkt erwartet das Cohere-artige Schema, das LiteLLM, Jina, TEI und
vLLM gleichermaßen sprechen — `POST /rerank` mit `query` und `documents`,
zurück kommen `results` mit `index` und `relevance_score`. Der Pfad `/rerank`
wird angehängt, sofern die Adresse ihn nicht schon enthält.

```
RERANKER_BASE_URL=http://litellm:4000/v1
RERANKER_API_KEY=...
RERANKER_API_MODEL=bge-reranker-v2-m3
```

Fällt der Endpunkt während des Betriebs aus, bleibt die Reihenfolge aus der
Fusion stehen — die Frage wird beantwortet, nur ohne die zweite Bewertung.

## 🧩 Reranker-Modell im Image

Das Modell (Standard `BAAI/bge-reranker-v2-m3`) wird **beim Bauen** in das
Image geladen:

```bash
docker compose build
```

Zur Laufzeit wird es von dort gelesen; `HF_HUB_OFFLINE=1` verhindert jeden
Netzzugriff. Der Container läuft damit ohne Internetverbindung, und ein
Ausfall von HuggingFace kann den Start nicht mehr verhindern.

Der Download passiert genau einmal pro Build und liegt im Dockerfile vor
`COPY . .` — eine Code-Änderung löst ihn also nicht erneut aus.

Der Xet-Übertragungsweg von HuggingFace bleibt gelegentlich hängen: der
Download bricht dann nicht ab, sondern steht still. `HF_HUB_DISABLE_XET=1`
ist deshalb voreingestellt und leitet ihn über HTTPS. Auf `0` setzen, wenn
Xet in eurem Netz schneller ist.

Anderes Modell: `RERANKER_MODEL` in der `.env` setzen und **neu bauen**.
Leer (`RERANKER_MODEL=`) schaltet den Reranker ab; dann rankt allein die
Rangfolge-Fusion. Lässt sich das Modell nicht laden, fällt die App auf
Fusion zurück statt abzubrechen.

## 🔌 Modelle und Endpunkte

Jede Aufgabe kann ihren eigenen Server bekommen:

| Aufgabe | Präfix | wofür |
|---|---|---|
| Antwort, Umformulierung | `CHAT_` | die eigentliche Antwort |
| Vektorisierung | `EMBEDDING_` | Chunks und Suchanfragen |
| Bildbeschreibung | `VISION_` | Abbildungen im Ingest |
| Chat-Benennung | `TITLE_` | Dateiname des Chats |

Je Präfix stehen `_MODEL`, `_BASE_URL`, `_API_KEY` und `_API_VERSION` zur
Verfügung. Nicht gesetzte Werte fallen auf `OPENAI_BASE_URL` und
`OPENAI_API_KEY` zurück — wer alles über einen Endpunkt fährt, ändert nichts.

Ist `_API_VERSION` gesetzt, wird ein Azure-OpenAI-Client verwendet.

Beispiel — Chat über Azure, alles andere lokal:

```
OPENAI_BASE_URL=http://ollama:11434/v1
OPENAI_API_KEY=ollama

CHAT_MODEL=gpt-4o
CHAT_BASE_URL=https://meine-instanz.openai.azure.com
CHAT_API_KEY=...
CHAT_API_VERSION=2024-10-21
```

Die aufgelöste Zuordnung steht in der Seitenleiste unter **Modell-Endpunkte**
— ohne Schlüssel, nur Modellname und Adresse.

> **Wechsel des Embedding-Modells:** Vektoren verschiedener Modelle sind
> nicht vergleichbar und haben in der Regel schon unterschiedlich viele
> Dimensionen. Wird `EMBEDDING_MODEL` geändert, muss der gesamte Bestand neu
> eingelesen werden — `data/chroma_db/` und `data/keyword_index.sqlite3`
> vorher löschen. Ohne das schlägt das Hinzufügen neuer Chunks mit einem
> Dimensionsfehler fehl, und bereits vorhandene Treffer werden gegen die
> falsche Vektorbasis bewertet.


## ⚠️ Nach einem Rebuild

```bash
docker compose up -d --build
```

erzeugt den Container **neu**. Alle offenen Streamlit-Sitzungen sterben mit
ihm. Der Browser zeigt die alte Seite weiter, aber die Verbindung dahinter ist
tot — Eingaben laufen ohne Fehlermeldung ins Leere. Das sieht aus wie ein
Absturz der App und ist keiner: **Seite neu laden**, dann erneut anmelden.

## 🔗 HTTP-Schnittstelle

Dieselbe Suche wie in der Oberfläche, ohne Browser — für eine Frage aus dem
Terminal oder ein Skript, das einen Bestand prüft. Die Antworten kommen aus
`pipeline.py`, denselben Funktionen, die auch die Oberfläche benutzt.

### Voraussetzung: Chroma als Dienst

Solange die Oberfläche läuft, greift ein zweiter Prozess auf denselben
Bestand zu — und dafür ist die Dateiablage nicht gebaut. Die Folge wäre kein
sauberer Fehler, sondern ein beschädigter Index. In der `.env`:

```
CHROMA_HOST=chroma
```

Damit sprechen Oberfläche, Ingest-Skripte und Schnittstelle den
`chroma`-Dienst aus der `docker-compose.yaml` an. Er liest denselben Ordner
`data/chroma_db` weiter — **die Daten müssen nicht umgezogen werden.** Ohne
diesen Eintrag verweigert die Schnittstelle den Start, statt den Index still
zu gefährden.

### Token anlegen

```bash
docker compose exec api python create_token.py markus --bezeichnung "Terminal Laptop"
```

Das Token wird genau einmal ausgegeben; gespeichert ist nur sein Hashwert.
Es bildet auf eine angelegte Kennung ab, und diese Kennung geht als
`benutzer` in die Suche — **die Trennung zwischen privaten und geteilten
Dokumenten gilt hier genauso wie in der Oberfläche.** Es gibt keinen
Schalter, der sie umgeht.

```bash
docker compose exec api python create_token.py --liste
docker compose exec api python create_token.py --widerrufe 3f9a1c
```

### Aufrufen

```bash
curl -s -H "X-LocaNoto-Token: $LOCANOTO_TOKEN" http://127.0.0.1:8600/status
```

```bash
curl -s -H "X-LocaNoto-Token: $LOCANOTO_TOKEN" -H "Content-Type: application/json" -d '{"frage":"Welche Prüffristen gelten?"}' http://127.0.0.1:8600/frage
```

Laufend statt am Stück — `?strom=1` liefert `text/event-stream` mit den
Ereignissen `sonden`, `text` und `quellen`:

```bash
curl -N -H "X-LocaNoto-Token: $LOCANOTO_TOKEN" -H "Content-Type: application/json" -d '{"frage":"Welche Prüffristen gelten?"}' "http://127.0.0.1:8600/frage?strom=1"
```

| Aufruf | Zweck |
|---|---|
| `GET /gesundheit` | Lebenszeichen, ohne Token |
| `GET /status` | Modelle, Ablage, Anzahl Abschnitte, sichtbare Dokumente |
| `GET /dokumente` | was diese Kennung sehen darf |
| `POST /frage` | Antwort mit Quellen; `?strom=1` für laufende Ausgabe |
| `GET /hilfe` | die Schnittstelle beschreibt sich selbst |

Im Rumpf von `/frage` sind `top_k`, `dateien`, `sachgebiete` und `verlauf`
optional — dieselben Einschränkungen wie die Filter in der Seitenleiste.

`quellen` nennt standardmäßig nur Datei, Seite und die Zahl der Abschnitte.
Ein Tabellenabschnitt ist mehrere Kilobyte groß; im Terminal überdeckt er
die Antwort, um die es ging. Mit `"quellen_texte": true` kommen sie mit.

### Erreichbarkeit

Der Port ist an `127.0.0.1` gebunden: erreichbar vom Server selbst und über
einen SSH-Tunnel, nicht aus dem Netz.

```bash
ssh -L 8600:127.0.0.1:8600 benutzer@server
```

Das ist Absicht. Der Verkehr ist unverschlüsselt, das Token wäre sonst auf
dem Draht mitlesbar. Für einen Zugriff von außen gehört ein Reverse Proxy
mit TLS davor.

## 🔁 Aus dem Betrieb lernen

Nutzer fragen in ihren eigenen Wörtern. Die stehen in den Dokumenten oft
nicht — dort wird ausgeschrieben, anders benannt oder nur eine Nummer
genannt. Eine Frage nach *„BANF"* findet nichts, wenn die Dokumente
*Bestellanforderung* schreiben — obwohl die Antwort im Bestand steht.
Weder die Vektorsuche noch die Stichwortsuche überbrückt das.

Welche Wörter das betrifft, lässt sich nicht ausdenken. Deshalb schreibt die
Anwendung mit, was gefragt wurde und keine Antwort fand — und daraus wächst
das Glossar.

### Rückmeldungen

Drei Anlässe landen in `data/feedback.jsonl`:

| Anlass | wann |
|---|---|
| `leer` | die Suche fand nichts — ohne Zutun des Nutzers vermerkt |
| `daumen_runter` | der Nutzer meldet, die Antwort taugte nicht |
| `daumen_hoch` | der Nutzer meldet, sie war gut |

Die Zustimmung ist dabei nicht Beifall, sondern die zweite Hälfte der
Auskunft: sie zeigt, welche Fragen der Bestand gut trägt. Kennt man nur die
Fehlschläge, lässt sich nach einer Änderung nicht sagen, ob sie etwas
verbessert oder nur verschoben hat.

Verwalter sehen die Sammlung in der Seitenleiste unter **📝 Rückmeldungen**.
Die beiden Listen bedeuten Verschiedenes:

* **Fragen ohne Treffer** — meist ein Wort, das im Glossar fehlt.
* **Als nicht hilfreich gemeldet** — hier kamen Treffer, aber die falschen.
  Das ist kein Wortschatzproblem, sondern eines der Rangfolge.

Festgehalten werden Frage, Suchsonden, Trefferzahlen sowie Datei und Seite
der verwendeten Quellen — nicht die Abschnitte selbst. Die stehen im Bestand
und würden das Protokoll unbrauchbar groß machen. Fragen über die
HTTP-Schnittstelle zählen mit.

Die vollständige Liste lässt sich mit **Protokoll herunterladen** aus der
Seitenleiste holen — auswerten heißt in der Regel sortieren und zählen, und
dafür braucht man sie ganz. Frühere Ablagen stehen darunter zur Auswahl.

Ist eine Liste abgearbeitet, legt der Knopf **Liste abschliessen** das
Protokoll unter dem Tagesdatum ab (`feedback-2026-09-02.jsonl`) und beginnt
ein neues. Gelöscht wird nichts: was Nutzer nicht gefunden haben, ist die
einzige Quelle für die Frage, ob der Bestand mit der Zeit besser wird. Die
abgelegten Dateien stehen unter der Liste und liegen im selben Ordner.

Von Hand geht dasselbe:

```bash
mv data/feedback.jsonl data/feedback-$(date +%F).jsonl
```

### Glossar

Gepflegt wird es **im Browser**: Verwalter finden in der Seitenleiste
**🗣️ Glossar bearbeiten**. Die Datei liegt unter `config/glossar.txt` und
damit im eingehängten Verzeichnis — die Änderung wirkt bei der nächsten
Frage, ohne Rebuild und ohne Neustart. Wer sie noch nie angelegt hat,
bekommt im Bearbeitungsfeld den Inhalt von `glossar.example.txt` vorgelegt.

Auf dem Server geht es genauso:

```bash
cp glossar.example.txt config/glossar.txt
```

`config/glossar.txt` ist gitignoriert — dieselbe Aufteilung wie bei der
`.env`, damit ein Update die eigenen Einträge nicht überschreibt. Fehlt die
Datei, verhält sich alles wie ohne Glossar.

Je Zeile eine Zuordnung. Wo es eine Fundstelle gibt, gehört sie dazu; solche
Anker stehen in Überschriften und Querverweisen und wirken deshalb besonders
gut:

```
BANF = Bestellanforderung; auch Anforderung oder Bestellvorschlag
FA = Fertigungsauftrag; Modul 530 Fertigungsauftraege bearbeiten
```

Der Inhalt geht an zwei Stellen ein: in die Bildung der Suchsonden, damit
die Suche den Begriff der Dokumente verwendet, und in den Antwortprompt,
damit die Antwort ihn mitnennt — der Nutzer findet ihn beim nächsten Mal
selbst. Gekennzeichnet als Zuordnung der Nutzer, nicht als Dokumentinhalt:
zitiert wird sie nicht.

Zeilen mit `#` sind Erläuterungen für den, der die Datei pflegt, und kommen
nicht in den Prompt.

Fachübliche Abkürzungen löst das Sprachmodell selbst auf. Das Glossar ist
für das, was wirklich haussprachlich ist.

**Nur geprüfte Zuordnungen eintragen.** Ein falscher Eintrag lenkt die Suche
zuverlässig auf die falsche Stelle; die Antwort klingt dann plausibel und
ist falsch, und das fällt schwerer auf als ein fehlender Eintrag.

## 📊 Listen aus Tabellendateien

Bestandslisten, Preislisten, Zuordnungen: `xlsx`, `xlsm`, `csv` und `tsv`
unter `data/tabellen/`. **Sie werden nicht vektorisiert.** Eine Liste mit
zehntausenden Zeilen zeilenweise einzubetten kostet Stunden Modellzeit, ist
beim nächsten Export veraltet, und semantische Ähnlichkeit ist bei
Teilenummern und Mengen ohnehin das falsche Werkzeug.

Stattdessen dasselbe Vorgehen wie bei einer Datenbank: erst entscheiden, wo
die Antwort stehen könnte, dann dort gezielt nachsehen.

### Der Katalog

Beim Einlesen wird je Datei und Blatt mechanisch erfasst, was darin steht:
Spaltennamen, Zeilenzahl, und bei Spalten mit wenigen verschiedenen Werten
deren Liste. Der letzte Teil ist der nützlichste — eine Spalte `Status` sagt
wenig, `Status: frei, gesperrt, ausgebucht` sagt alles. Kein Modell nötig,
in Sekunden erledigt.

Spaltennamen werden dabei auf eine abfragbare Form gebracht (`Teile-Nr.` →
`teile_nr`); der Originalname steht im Katalog daneben, damit die Antwort
ihn nennen kann.

### Was wann aktualisiert werden muss

| Änderung | nötig |
|---|---|
| Zeilen geändert, ergänzt, gelöscht | **nichts** — die Datei wird bei jeder Frage frisch gelesen |
| neue Datei, neues Blatt, neue Spalte | **Listen neu einlesen** in der Seitenleiste |

Zwischengespeichert wird nur, solange Änderungsdatum und Größe gleich
bleiben. Ein neuer Export wirkt damit ab der nächsten Frage.

### Große Listen

Blätter ab `TABELLEN_GROSS_AB` Zeilen (Vorgabe 50.000) stehen im Katalog,
werden aber **nicht abgefragt**, solange sie nicht ausdrücklich per Häkchen
einbezogen werden — sie müssen bei jeder Frage vollständig geladen werden,
und das dauert spürbar. Die Oberfläche weist beim Einschalten darauf hin.

Ist eine Liste dauerhaft zu groß, gehört sie in eine Datenbank und nicht in
einen Ordner.

### Sicherheit

Das Modell formuliert eine `SELECT`-Anweisung; ausgeführt wird sie gegen das
eine gewählte Blatt in einer SQLite-Datenbank im Arbeitsspeicher. Geprüft
wird sie mit derselben Kette wie eine Abfrage an einen SQL-Server
(`sqlpruefung.py`): genau eine Anweisung, nur `SELECT` oder `WITH`, keine
Kommentare, kein `INTO`, keine Prozeduraufrufe. **Es wird kein erzeugter
Code ausgeführt.**

Beispielwerte aus den Spalten gehen in den Prompt — das ist der einzige Teil
des Katalogs, der echte Daten an das Modell trägt. `TABELLEN_BEISPIELE_BIS`
und `TABELLEN_BEISPIELE` begrenzen ihn; auf `0` gesetzt bleiben nur die
Spaltennamen.

## 🎛️ Voreinstellungen

Dieselbe Anlage taugt für verschiedene Anwendungen, aber nicht mit denselben
Einstellungen. Eine Voreinstellung bündelt, was zusammengehört, und steht
oben in der Seitenleiste als Auswahl:

| enthalten | |
|---|---|
| Chat-Modell | derselbe Endpunkt, anderer Name — `qwen3.8` statt `gemma4` |
| Relevante Abschnitte | Trefferzahl je Frage |
| Sachgebiete | worin gesucht wird |
| Prompts und Glossar | optional, eigene Fassungen je Voreinstellung |

Fehlt einer Voreinstellung eine Prompt-Vorlage, gilt die aus `config/`,
sonst die mitgelieferte — dieselbe Kette wie bisher, um eine Stufe
verlängert. Angelegt werden sie unter **🎛️ Voreinstellungen verwalten**
(Verwalter), ausgewählt von allen. Eigene Prompts bekommt eine
Voreinstellung über die Auswahl **Gilt für** im Prompt-Editor.

Ohne angelegte Voreinstellungen erscheint die Auswahl nicht.

### Was bewusst nicht enthalten ist

**Das Embedding-Modell.** Die Abschnitte im Bestand sind mit einem
bestimmten Modell vektorisiert; ein anderes vergleicht Vektoren aus einem
anderen Raum. Die Suche liefert dann Unsinn, ohne dass etwas fehlschlägt —
die Antwort klingt normal und zitiert die falschen Stellen. Es gehört zum
Index, nicht zur Bedienung, und ein Wechsel verlangt einen neuen Ingest. Aus
demselben Grund ist das Eingabefeld dafür aus der Seitenleiste entfernt.

**Adressen und Schlüssel.** Wohin die Fragen gehen, ist Sache der
Installation und steht in der `.env`.

## 📜 Prompts anpassen

Zwei Vorlagen bestimmen, wonach gesucht und wie geantwortet wird:

| Datei | wofür |
|---|---|
| `search_prompt.txt` | aus der Frage werden drei Suchanfragen |
| `system_prompt.txt` | Rolle, Regeln, Umgang mit Quellen |

Verwalter bearbeiten sie in der Seitenleiste unter **📜 Prompts bearbeiten**.
Gespeichert wird nach `config/`, also ins eingehängte Verzeichnis — die
Änderung wirkt bei der nächsten Frage, ohne Rebuild. **Auf Vorlage
zurücksetzen** entfernt die eigene Fassung wieder; die mitgelieferte gilt
dann erneut.

**Pflicht-Platzhalter werden geprüft.** Verschwindet `{CONTEXT_PLATZHALTER}`
aus dem Antwort-Prompt, bekommt das Sprachmodell die gefundenen Abschnitte
nicht mehr — es antwortet dann aus dem, was es ohnehin zu wissen glaubt, mit
erfundenen Fundstellen und ohne jede Fehlermeldung. Ein Speichern ohne die
nötigen Platzhalter wird deshalb abgelehnt.

Die Vorlagen sind für Verwalter da, nicht für jeden Nutzer: eine unglückliche
Formulierung wirkt auf jede Antwort, die danach gegeben wird.

## 🔐 Rechte

| Bereich | sichtbar für | löschen darf |
|---|---|---|
| Gemeinsamer Pool | alle Nutzer | nur Administratoren |
| Private Dokumente | nur der Eigentümer | Eigentümer und Administratoren |

Administratoren sehen fremde private Dokumente ausschließlich im
Verwaltungsbereich der Seitenleiste. In Suche und Antworten fließen sie nie
ein. Wer Administrator ist, legt `ADMIN_USERS` in der `.env` fest.

---

## DIG:IT-KMU

Diese App entstand im Rahmen des Projekts : DIG:IT-KMU 

Das Projekt DIG:IT-KMU am Institut für Digital Engineering (IDEE) der Technischen Hochschule Würzburg-Schweinfurt (THWS) unterstützt Unternehmen bei der digitalen Transformation. Durch gezielten Technologietransfer werden kleine und mittlere Unternehmen befähigt, innovative Technologien sicher und effizient in ihre Geschäftsprozesse zu integrieren. Das Projekt wird im Rahmen des EFRE Bayern 2021–2027 durch das Bayerische Staatsministerium für Wirtschaft, Landesentwicklung und Energie gefördert, kofinanziert von der Europäischen Union.

https://digit.kmu.bayern

---

## 🛠️ Installation & Schnellstart

### Voraussetzungen

* Docker und Docker Compose
* Ein erreichbarer Modellserver für Chat und Embedding — etwa Ollama, vLLM oder ein Gateway davor. Ohne ihn startet die Anwendung, findet aber nichts und antwortet nicht.

### 1. Repository klonen (oder ZIP entpacken)
```bash
git clone https://github.com/mw-research/LocaNoto.git
cd LocaNoto
```

### 2. Konfiguration anlegen

Die mitgelieferte Vorlage kopieren und darin die Adressen der Modellserver, die Schlüssel und den ersten Verwalter eintragen:

```bash
cp .env.example .env
```

Das Glossar für Hauswörter kann leer bleiben — es lässt sich später im Browser pflegen. Wer gleich beginnen will:

```bash
cp glossar.example.txt config/glossar.txt
```

### 3. Ersten Benutzer anlegen

Ohne Benutzer ist die Oberfläche nicht nutzbar. Das Passwort wird als bcrypt-Hash in `config/users.json` abgelegt, nicht im Klartext:

```bash
python3 create_user.py
```

### 4. Container starten
```bash
docker compose up -d
```

Die Oberfläche ist danach unter `http://localhost:8501` erreichbar — oder unter dem Port, der in `APP_PORT` steht.
