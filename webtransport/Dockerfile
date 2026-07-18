FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# cryptography is needed by generate_cert.py (no openssl binary required)
RUN pip install --no-cache-dir -r requirements.txt cryptography

COPY . .

# Generate a self-signed TLS certificate if not already present.
# Mount a named volume at /app/certs in production to persist a real certificate.
RUN python generate_cert.py

# UDP port for QUIC/WebTransport
EXPOSE 4433/udp

CMD ["python", "server.py"]
