# ─── Builder stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/messenger/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY services/messenger/ /app/
COPY libs /app/libs
COPY services/messenger/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:${SERVICE_PORT:-8008}/health/ || exit 1

EXPOSE 8008

CMD ["/app/entrypoint.sh"]
