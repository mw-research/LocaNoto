# LocaNoto - Lokales RAG System für technische Dokumentationen

LocaNoto ist ein vollständig lokal laufendes Retrieval-Augmented Generation (RAG) System. Es ermöglicht das intelligente Durchsuchen, Vektorisieren und Abfragen von Fachdokumenten (z.B. Bau-Normen, Handbüchern) mithilfe modernster lokaler Sprachmodelle (LLMs), ohne dass sensible Firmendaten das lokale Netzwerk verlassen.

## 🚀 Features
* **Lokal & abgeschottet:** Im Betrieb fließen keine Daten an externe Cloud-Anbieter.
  (Einmalig beim ersten Start lädt der Reranker sein Modell von HuggingFace; für einen komplett offline betriebenen Server muss das Modell vorab in den Image-Cache gelegt werden.)
* **Hybride Suche:** Semantische Vektorsuche (ChromaDB) kombiniert mit BM25-gerankter Keyword-Suche (SQLite FTS5, plattenbasiert).
* **Zweistufige Rangfolge:** Jede Suchsonde und jeder Suchweg liefert eine eigene Rangliste; Reciprocal Rank Fusion verschmilzt sie, danach bewertet ein CrossEncoder die engere Auswahl. Das Modell liegt **im Image** und wird nicht zur Laufzeit heruntergeladen — die App startet ohne Internetzugang.
* **Multi-Tenant-Architektur:** Getrennte Sichtbarkeit von Dokumenten und Chats je Nutzer.

## 🗂️ Sachgebiete

Unterordner in `data/dokumente/` werden als Sachgebiet übernommen und stehen
in der Seitenleiste als Filter zur Verfügung:

```
data/dokumente/
    Tragwerk/        -> Sachgebiet "Tragwerk"
    Korrosion/       -> Sachgebiet "Korrosion"
    DIN 18202.pdf    -> Sachgebiet "(Basis)"
```

Das ist mehr als Bequemlichkeit. In einem flachen gemeinsamen Index
konkurrieren kleine Dokumente gegen große: DIN 18202 stellt 1,6 % der Chunks
des Beispielkorpus, DIN EN 1090-2 dagegen 20,6 % — bei einem Top-k über alle
Dokumente verliert die kleine Norm strukturell. Die Eingrenzung auf ein
Sachgebiet stellt die Chancengleichheit wieder her.

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

Beide Läufe sind unterbrechbar und setzen auf Chunk-Ebene wieder auf: die
Textextraktion läuft erneut (billig), vektorisiert wird nur, was fehlt
(teuer). Ein abgebrochener Lauf hinterlässt damit kein halb indexiertes
Dokument, das beim nächsten Start als erledigt gilt.

Stammt die Vektordatenbank aus einer Installation vor dem FTS5-Index, baut
die App ihn beim ersten Start automatisch auf. Vorab und außerhalb der
Weboberfläche geht das mit:

```bash
python rebuild_index.py
```

## 🧠 Reranker-Modell

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

Anderes Modell: `RERANKER_MODEL` in der `.env` setzen und **neu bauen**.
Leer (`RERANKER_MODEL=`) schaltet den Reranker ab; dann rankt allein die
Rangfolge-Fusion. Lässt sich das Modell nicht laden, fällt die App auf
Fusion zurück statt abzubrechen.

## ⚠️ Nach einem Rebuild

```bash
docker compose up -d --build
```

erzeugt den Container **neu**. Alle offenen Streamlit-Sitzungen sterben mit
ihm. Der Browser zeigt die alte Seite weiter, aber die Verbindung dahinter ist
tot — Eingaben laufen ohne Fehlermeldung ins Leere. Das sieht aus wie ein
Absturz der App und ist keiner: **Seite neu laden**, dann erneut anmelden.

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
* Docker & Docker Compose installiert
* (Optional, aber empfohlen) Lokaler KI-Server (z.B. Ollama oder vLLM) für die LLM-Schnittstelle

### 1. Repository klonen (oder ZIP entpacken)
```bash
git clone https://github.com/mw-research/LocaNoto.git
cd LocaNoto
```

### 2. Konfiguration anlegen - Kopiere die mitgelieferte Vorlage und trage deine API-Keys sowie den initialen Admin-Benutzernamen ein:
```bash
cp .env.example .env
```

### 3. Ersten Benutzer anlegen - Bevor das Web-Interface nutzbar ist, muss lokal ein Nutzer generiert werden (die Zugangsdaten werden sicher als Hash in der users.json gespeichert):
```bash
python3 create_user.py
```

### 4. Container starten - Starte den Container im Hintergrund.
```bash
docker compose up -d
```

### Das Interface ist nun unter http://localhost:8501 erreichbar.
