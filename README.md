# LocaNoto - Lokales RAG System für technische Dokumentationen

LocaNoto ist ein vollständig lokal laufendes Retrieval-Augmented Generation (RAG) System. Es ermöglicht das intelligente Durchsuchen, Vektorisieren und Abfragen von Fachdokumenten (z.B. Bau-Normen, Handbüchern) mithilfe modernster lokaler Sprachmodelle (LLMs), ohne dass sensible Firmendaten das lokale Netzwerk verlassen.

## 🚀 Features
* **100% Offline & Lokal:** Keine Daten fließen an externe Cloud-Anbieter.
* **Hybride Suche:** Kombination aus semantischer Vektorsuche (ChromaDB) und exakter Keyword-Suche (BM25).
* **Intelligentes Reranking:** BAAI-Reranker destilliert hunderte Treffer auf die exaktesten Textstellen herunter.
* **Multi-Tenant-Architektur:** Strikte Trennung von Dokumenten, Chats und Datenbanken über Docker-Volumes.

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
git clone [https://github.com/mw-research/LocaNoto.git](https://github.com/mw-research/LocaNoto)
cd locanoto
```

### 2. Konfiguration anlegen - Kopiere die mitgelieferte Vorlage und trage deine API-Keys sowie den initialen Admin-Benutzernamen ein:
```bash
cp env.example .env
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
