FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libmupdf-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}'); print('Reranker im Image: ${RERANKER_MODEL}')"

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

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
