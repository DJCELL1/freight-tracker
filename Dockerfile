FROM python:3.12-slim

# The manifests arrive as scans, so the image needs the OCR toolchain, not just
# Python: poppler rasterises the PDF pages and tesseract reads them. Without
# these two the app still starts but cannot read a scanned pack.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first so the dependency layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Written to by the app; overridden by the volume mount in production.
ENV FREIGHT_DB_PATH=/data/freight_tracker.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# $PORT is supplied by the host; 8080 is the fallback for `docker run` locally.
CMD streamlit run app.py \
    --server.port "${PORT:-8080}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
