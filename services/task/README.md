# Task Service

Task tracking and project management microservice for HTQWeb platform.

## Features

- **Task Management**: Full CRUD operations with auto-generated keys (TASK-1, TASK-2, etc.)
- **Status Transitions**: FSM-based workflow (open → in_progress → in_review → done → closed)
- **Comments & Attachments**: Rich task collaboration features
- **Task Relationships**: Link tasks with cycle detection for blocking chains
- **Activity Tracking**: Complete audit trail of field changes
- **Labels & Versions**: Categorize tasks with labels and group by project versions
- **Notifications**: Real-time notifications for task assignments and changes
- **Production Calendar**: Working day-aware deadline calculation

## Quick Start

### 1. Environment Setup

```bash
cd services/task
cp .env.example .env
# Edit .env with your values
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Migrations

```bash
alembic upgrade head
```

### 4. Start Service

```bash
uvicorn app.main:app --reload --port 8007
```

Access API docs at: http://localhost:8007/docs

## Docker

```bash
# From project root
docker compose up -d task-service
```

## Architecture

```
Nginx Gateway → /api/tasks/v1/* → Task Service (FastAPI)
                                      ↓
                              PostgreSQL (public schema)
                                      ↓
                              Redis (cache/session)
```

## API Endpoints

### Tasks
- `GET /api/tasks/v1/tasks/` — List tasks with filtering
- `GET /api/tasks/v1/tasks/{id}/` — Get task details
- `POST /api/tasks/v1/tasks/` — Create task
- `PATCH /api/tasks/v1/tasks/{id}/` — Update task
- `DELETE /api/tasks/v1/tasks/{id}/` — Soft delete task
- `GET /api/tasks/v1/tasks/{id}/transitions/` — Get available status transitions
- `GET /api/tasks/v1/tasks/stats/` — Get task statistics
- `POST /api/tasks/v1/tasks/{id}/comments/` — Add comment
- `POST /api/tasks/v1/tasks/{id}/attachments/` — Add attachment

### Labels
- `GET /api/tasks/v1/labels/` — List labels
- `POST /api/tasks/v1/labels/` — Create label
- `PATCH /api/tasks/v1/labels/{id}/` — Update label
- `DELETE /api/tasks/v1/labels/{id}/` — Delete label

### Versions
- `GET /api/tasks/v1/versions/` — List project versions
- `GET /api/tasks/v1/versions/{id}/tasks/` — Get version tasks
- `POST /api/tasks/v1/versions/` — Create version
- `PATCH /api/tasks/v1/versions/{id}/` — Update version
- `DELETE /api/tasks/v1/versions/{id}/` — Delete version

### Task Links
- `POST /api/tasks/v1/task-links/` — Create task link
- `DELETE /api/tasks/v1/task-links/{id}/` — Delete task link

### Notifications
- `GET /api/tasks/v1/notifications/` — List user notifications
- `POST /api/tasks/v1/notifications/{id}/mark_read/` — Mark as read
- `POST /api/tasks/v1/notifications/mark-all-read/` — Mark all as read

## Status Workflow

```
open → in_progress → in_review → done → closed
  ↓         ↓           ↓         ↓
closed     open      in_progress  in_progress
           ↑                      ↓
           └──────────────────── open
```

**Allowed transitions:**
- `open`: → in_progress, closed
- `in_progress`: → in_review, done, open
- `in_review`: → done, in_progress
- `done`: → closed, in_progress
- `closed`: → open

## Database Schema

All tables are created in the configured schema (default: `public`).

**Core tables:**
- `tasks` — Main task entities
- `task_comments` — Task discussions
- `task_attachments` — File uploads
- `task_activities` — Change audit log
- `task_links` — Task relationships
- `task_labels` — Many-to-many label mapping

**Supporting tables:**
- `labels` — Task categorization
- `project_versions` — Release/roadmap management
- `notifications` — User alerts
- `task_sequence` — Atomic key generation
- `production_days` — Working calendar

## Migration from Django

This service is part of the Strangler Fig migration pattern:

1. **Current state**: Task functionality in Django monolith
2. **Target state**: This standalone microservice
3. **Migration strategy**:
   - Deploy service alongside Django
   - Route `/api/tasks/*` to new service via Nginx
   - Monitor and validate
   - Remove legacy code from Django

## Development

### Running Tests

```bash
pytest tests/
```

### Code Quality

```bash
ruff check app/
```

### Generate Migration

After model changes:

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Configuration

See `.env.example` for all available options.

**Key settings:**
- `DB_SCHEMA` — PostgreSQL schema (default: public)
- `JWT_SECRET` — Must match Django SECRET_KEY for token validation
- `SERVICE_PORT` — Default 8007
- `REDIS_URL` — Cache and session storage

## Health Checks

- `GET /health/` — Basic health check
- `GET /health/ready/` — Readiness check (with DB connection)

## Observability

- **Logging**: Structured JSON logs via structlog
- **Tracing**: OpenTelemetry integration
- **Request ID**: X-Request-ID header propagation
- **Metrics**: Exposed via OpenTelemetry exporter
