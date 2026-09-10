FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libmupdf-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# --- CPU-VARIANTE ---
#
# requirements.txt pinnt torch samt fuenfzehn nvidia-Paketen und triton.
# Das ist richtig, solange der Reranker auf einer GPU laeuft -- und es
# sind mehrere Gigabyte, die auf einem Rechner ohne GPU nichts tun.
#
# NUR_CPU=1 holt torch aus dem CPU-Index von PyTorch und laesst die
# CUDA-Pakete weg. Gedacht fuer Umgebungen, in denen das Abbild ueber
# das Netz gezogen wird und ein Platzkontingent gilt: eine Sandbox, ein
# Cluster, ein Laptop.
#
# Gefiltert statt in einer zweiten Datei gepflegt: zwei
# Abhaengigkeitslisten laufen auseinander, und man merkt es an der
# Stelle, an der man es am wenigsten brauchen kann.
# Warum --extra-index-url und nicht nur --index-url: mit --index-url
# ALLEIN sucht pip auch die Abhaengigkeiten von torch nur noch im
# PyTorch-Index -- filelock, sympy, networkx, jinja2 -- und die liegen
# dort nicht vollstaendig. Der Fehler nennt dann ein Paket, das mit
# torch nichts zu tun hat, und sieht nach einem kaputten
# requirements.txt aus.
#
# Kein Kommentar INNERHALB der RUN-Anweisung: die Fortsetzungszeilen
# werden zu EINEM Shell-Befehl zusammengezogen, und ob eine
# eingerueckte Kommentarzeile vorher entfernt wird, haengt am Parser.
# Darauf zu wetten kostet einen Bau von zwanzig Minuten.
ARG NUR_CPU=0
RUN set -eu; \
    if [ "${NUR_CPU}" != "1" ]; then \
      pip install --no-cache-dir -r requirements.txt; \
    else \
      TORCH="$(grep -E '^torch==' requirements.txt || true)"; \
      TVISION="$(grep -E '^torchvision==' requirements.txt || true)"; \
      echo "CPU-Variante: ${TORCH:-kein torch gepinnt} ${TVISION:-}"; \
      grep -vE '^(nvidia-|triton==|torch==|torchvision==)' requirements.txt \
          > /tmp/req-cpu.txt; \
      if [ -n "$TORCH" ]; then \
        pip install --no-cache-dir \
            --index-url https://download.pytorch.org/whl/cpu \
            --extra-index-url https://pypi.org/simple \
            $TORCH $TVISION \
        || { \
          echo "FEHLER: CPU-Raeder fuer $TORCH gibt es unter"; \
          echo "download.pytorch.org/whl/cpu nicht. Entweder die"; \
          echo "Fassung in requirements.txt auf eine dort vorhandene"; \
          echo "aendern -- oder ohne NUR_CPU bauen."; \
          exit 1; \
        }; \
      fi; \
      pip install --no-cache-dir -r /tmp/req-cpu.txt; \
      python -c "import torch; print('torch', torch.__version__, 'CUDA:', torch.version.cuda)"; \
    fi

# --- RERANKER-MODELL IN DAS IMAGE BACKEN ---
#
# Bewusst VOR "COPY . ." und direkt nach den Abhaengigkeiten: beide Schritte
# aendern sich selten, sodass Docker sie zwischenspeichert und eine
# Code-Aenderung den Download nicht erneut ausloest.
#
# Ohne diesen Schritt holte sich der CrossEncoder sein Modell beim ERSTEN
# Programmstart von HuggingFace. Das machte den Start von einem externen
# Dienst abhaengig -- war er nicht erreichbar, lief die App nicht an. Jetzt
# passiert der Download genau einmal beim Bauen; zur Laufzeit liegt das
# Modell im Image.
ENV HF_HOME=/app/models \
    SENTENCE_TRANSFORMERS_HOME=/app/models
ARG RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# Der Xet-Uebertragungsweg von HuggingFace bleibt gelegentlich haengen -- der
# Download bricht dann nicht ab, sondern steht still. Das trifft hier den
# Build und nicht mehr den Programmstart, ist aber weiterhin eine Wartezeit
# ohne Rueckmeldung. Auf 1 gesetzt laeuft der Download ueber HTTPS.
#
# Als ENV und nicht nur als ARG: der Wert muss die Umgebung des folgenden
# RUN erreichen, und ein spaeterer Build-Schritt oder ein manueller Aufruf im
# Container soll ihn ebenfalls sehen.
ARG HF_HUB_DISABLE_XET=1
ENV HF_HUB_DISABLE_XET=${HF_HUB_DISABLE_XET}

# Leerer Modellname heisst: kein Modell ins Image. Ohne diese Weiche wuerde
# CrossEncoder('') aufgerufen und der Build abbrechen -- gerade dann, wenn
# jemand bewusst auf einen Rerank-Endpunkt oder auf die reine Fusion setzt.
RUN if [ -n "${RERANKER_MODEL}" ]; then \
      python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}'); print('Reranker im Image: ${RERANKER_MODEL}')"; \
    else \
      echo "RERANKER_MODEL leer -- kein Modell ins Image gelegt"; \
    fi

# Ab hier kein Netzzugriff mehr auf HuggingFace -- weder beim Start noch
# spaeter. Ein versehentlich falsch gesetzter Modellname faellt damit sofort
# auf, statt still einen Download auszuloesen.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    RERANKER_MODEL=${RERANKER_MODEL}

# Telemetrie abschalten. ChromaDB und Streamlit senden von sich aus
# Nutzungsdaten nach draussen -- fuer einen Container, der ohne Netzzugang
# laufen soll, ein offener Kanal. Streamlit liest zusaetzlich
# .streamlit/config.toml, das mit dem Code hereinkopiert wird.
ENV ANONYMIZED_TELEMETRY=False \
    CHROMA_ANONYMIZED_TELEMETRY=False \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Keine .pyc-Dateien zur Laufzeit. Sie landeten sonst in der
# Schreibschicht des Containers -- unnoetig, weil sie bei jedem neuen
# Pod neu entstehen, und ein Hindernis, sobald das Wurzeldateisystem
# nur lesbar eingehaengt ist (readOnlyRootFilesystem in Kubernetes).
ENV PYTHONDONTWRITEBYTECODE=1

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
