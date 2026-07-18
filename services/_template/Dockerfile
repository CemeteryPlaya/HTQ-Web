# ─── Builder stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ARG SERVICE_PORT=8001
ENV SERVICE_PORT=${SERVICE_PORT}

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:${SERVICE_PORT}/health/ || exit 1

EXPOSE ${SERVICE_PORT}

# Default command runs the web process. Worker process overrides via docker-compose:
#   command: ["dramatiq", "app.workers.actors", "--processes", "2", "--threads", "4"]
CMD ["/app/entrypoint.sh"]
