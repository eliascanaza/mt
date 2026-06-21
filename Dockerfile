FROM python:3.12-slim

WORKDIR /app

# python:3.12-slim's bundled CA bundle/OpenSSL config is too old for Atlas's
# TLS handshake (fails with "TLSV1_ALERT_INTERNAL_ERROR"); refreshing
# ca-certificates fixes it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --timeout 60
