FROM python:3.11-slim

WORKDIR /app

# Trust any extra CAs in certs/ (TLS-inspecting networks - see certs/README.md).
# Python's ssl, httpx and requests are pointed at the system bundle, which
# update-ca-certificates rebuilds to include them.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# CPU-only torch first, so sentence-transformers doesn't pull the multi-GB
# CUDA build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so containers never download it
# at runtime. Xet transfers break behind TLS-inspecting proxies ("Byte range
# not sequential"), so use plain HTTPS downloads.
RUN HF_HUB_DISABLE_XET=1 python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# Documentation only - the actual published port is controlled by PORT in
# .env and the ports: mapping in docker-compose.yml, not by this line.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
