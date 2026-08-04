FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# cryptography is needed by generate_cert.py (no openssl binary required)
RUN pip install --no-cache-dir -r requirements.txt cryptography

COPY . .

# UDP port for QUIC/WebTransport
EXPOSE 4433/udp

# Сертификат выпускаем на старте, а не на сборке: самоподписанный живёт
# 13 дней (лимит браузера на serverCertificateHashes — 14), поэтому срок
# нужно перепроверять при каждом запуске. Настоящий CA-сертификат,
# смонтированный в /app/certs, скрипт не трогает.
CMD ["sh", "-c", "python generate_cert.py && exec python server.py"]
