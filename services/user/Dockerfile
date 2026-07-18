FROM python:3.14-slim

WORKDIR /app

# System dependencies
# build-essential + libpq-dev needed for asyncpg and pydantic-core compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libc6-dev \
    libpq-dev \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY services/user/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY services/user/ .
COPY libs /app/libs

# Health check
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${SERVICE_PORT:-8005}/health/ || exit 1

EXPOSE 8005

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
