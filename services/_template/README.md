# __service_name__ Service

Microservice for HTQWeb platform — handles **__service_description__**.

## Architecture

```
Nginx (Gateway) → /api/__service_name__/* → This Service (FastAPI)
                                              ↓
                                        PostgreSQL (own schema)
                                        Redis (cache)
                                        Legacy Django (circuit breaker fallback)
```

## Quick Start

### 1. Setup

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env — set JWT_SECRET, DB_PASSWORD, SERVICE_PORT

# Install dependencies
pip install -r requirements.txt
```

### 2. Run locally

```bash
uvicorn app.main:app --reload --port 8001
```

### 3. API Docs

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Docker

```bash
docker build -t htqweb/__service_name__:latest .
docker run -p 8001:8001 --env-file .env htqweb/__service_name__:latest
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health/` | Liveness probe |
| GET | `/health/ready/` | Readiness probe |
| GET | `/api/__service_name__/` | List items (example) |
| POST | `/api/__service_name__/` | Create item (example) |

## Migration Notes (Strangler Fig)

This service was extracted from the Django monolith using the Strangler Fig pattern.

**Current state**: 🟢 Independent service
**Previously**: Part of `backend/__app_name__/` in Django monolith

### Data Migration

1. Legacy data was copied to this service's schema (`__service_name__`)
2. During migration, writes went to both legacy and new service (dual-write)
3. After verification, legacy tables were dropped

## Circuit Breaker

When calling legacy Django (during migration), the circuit breaker pattern is used:

- **Failure threshold**: 5 consecutive failures → circuit opens
- **Recovery timeout**: 30s → half-open state
- **Half-open requests**: 2 test requests before full recovery
