FROM python:3.12-slim

WORKDIR /app

ARG CORPORATE_CA_BASE64=""
RUN if [ -n "$CORPORATE_CA_BASE64" ]; then \
      printf '%s' "$CORPORATE_CA_BASE64" | base64 -d > /usr/local/share/ca-certificates/corporate-ca.crt \
      && update-ca-certificates; \
    fi

COPY requirements.txt .
# cryptography is needed by generate_cert.py (no openssl binary required)
RUN if [ -f /usr/local/share/ca-certificates/corporate-ca.crt ]; then \
      PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --no-cache-dir -r requirements.txt cryptography; \
    else \
      pip install --no-cache-dir -r requirements.txt cryptography; \
    fi

COPY . .

# UDP port for QUIC/WebTransport
EXPOSE 4433/udp

# Сертификат выпускаем на старте, а не на сборке: самоподписанный живёт
# 13 дней (лимит браузера на serverCertificateHashes — 14), поэтому срок
# нужно перепроверять при каждом запуске. Настоящий CA-сертификат,
# смонтированный в /app/certs, скрипт не трогает.
CMD ["sh", "-c", "python generate_cert.py && exec python server.py"]
