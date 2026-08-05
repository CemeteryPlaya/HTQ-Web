# HTQWeb Platform — Microservices Migration

Enterprise internal platform (Hi-Tech Group). The active runtime is a FastAPI microservice stack behind the nginx gateway; old Django routes are kept only as compatibility aliases where explicitly configured.

## Architecture Status

```
React SPA -> Nginx (API Gateway) -> FastAPI microservices
```

### Services

| Service | Status | Port | Description |
|---|---|---|---|
| **Nginx Gateway** | Active | 80 | API Gateway, routing, rate limiting |
| **User Service** | Active | 8005 | Identity, JWT, auth |
| **HR Service** | Active | 8006 | Employees, departments, org, HR files |
| **Task Service** | Active | 8007 | Tasks, calendar, production calendar |
| **Messenger Service** | Active | 8008 | Rooms, messages, Socket.IO |
| **Media Service** | Active | 8009 | Uploads, thumbnails, downloads |
| **Email Service** | Active | 8010 | SMTP/IMAP, OAuth, DLP |
| **CMS Service** | Active | 8011 | News, contact requests, conference config |
| **Admin Service** | Active | 8012 | sqladmin aggregator |
| **SFU** | Active | 4443 | Mediasoup WebRTC |
| **Redis** | Active | 6379 | Cache, broker, pub/sub |
| **PostgreSQL** | Active | 55432 | Via PgBouncer |

See [API.md](./API.md) for full routing table and service contracts.

## Quick Start

### Docker (recommended)

```bash
docker compose up -d
```

Access:
- App: http://localhost
- Admin: http://localhost/admin/
- API docs (User Service): http://localhost:8005/docs

### Local development

#### Backend services (FastAPI)
```bash
cd services/user
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8005
```

#### Frontend (React Vite)
```bash
cd frontend
npm install
npm run dev
```

## Project Structure

```
HTQWeb/
├── frontend/             # React + Vite + TypeScript SPA
├── infra/                # Infrastructure (nginx, certs, db init, logging)
│   ├── nginx/
│   │   └── default.conf  # API Gateway routing
│   ├── certs/            # Local TLS certs (gitignored)
│   ├── db/
│   │   └── init-ltree.sql
│   └── logging/          # Loki + Promtail + Grafana provisioning
├── services/             # FastAPI microservices
│   ├── _template/        # Cookiecutter template for new services
│   ├── scaffold.py       # Create new service: python scaffold.py <name> <desc>
│   ├── user/             # User/Identity Service (JWT authority, :8005)
│   ├── hr/               # HR Service (employees, departments, :8006)
│   ├── task/             # Task Service (tasks, calendar, :8007)
│   ├── messenger/        # Messenger Service (chat, Socket.IO, :8008)
│   ├── media/            # Media Service (uploads, thumbnails, :8009)
│   ├── email/            # Email Service (SMTP/IMAP, DLP, OAuth, :8010)
│   ├── cms/              # CMS Service (news, contact requests, :8011)
│   ├── admin/            # Admin Aggregator (sqladmin dashboard, :8012)
│   └── README.md         # Services documentation
├── webtransport/         # WebTransport QUIC signalling proxy for SFU
├── sfu/                  # Mediasoup SFU (media routing for /conference)
├── docker-compose.yml    # Production stack
├── docker-compose.dev.yml # Dev override (Vite HMR on :3000, /docs enabled)
├── PLAN.md               # Migration plan + execution log
├── API.md                # API documentation + service contracts
└── README.md             # This file
```

## Migration Progress (Strangler Fig)

| Phase | Domain | Status | Details |
|---|---|---|---|
| **Phase 0** | API Gateway | ✅ Done | Nginx routing, rate limiting, observability |
| **Phase 1a** | User/Identity | 🟡 In Progress | Service created, dual-write setup, migration script ready |
| **Phase 1b** | HR | 🔵 Planned | Models analyzed, extraction planned |
| **Phase 1c** | Audit | 🔵 Planned | Cross-service audit log |

## Key Features

*   **JWT Authentication**: SimpleJWT, stateless auth across all services
*   **API Gateway**: Nginx with path-based routing, rate limiting, health checks
*   **Strangler Fig Pattern**: Incremental migration without downtime
*   **Database per Service**: Each microservice owns its schema (via PgBouncer)
*   **Observability**: Structured logging, request ID propagation, health checks
*   **HR Management**: Departments, positions, employees, vacancies, applications, time tracking
*   **Task Tracker**: Tasks with auto-generated keys, comments, attachments, relationships
*   **Messenger**: E2EE (X25519 + AES-256-GCM), WebSocket, SFU video conferencing
*   **Internal Email**: OAuth-based sending (Gmail/Microsoft Graph), DLP scanner

## Documentation

- [API Documentation](./API.md) — Routing table, service contracts, migration strategy
- [Services README](./services/README.md) — Microservice development guide
- [User Service README](./services/user/README.md) — User/Identity Service docs

## Testing
*   Backend: run the affected service tests with `pytest services/<service>/tests`
*   Frontend: `npm test`

## LAN WebRTC (HTTPS + WSS)

### 1) Generate local TLS cert for IP

`mkcert` (recommended):

```powershell
mkcert -install; mkcert -cert-file .\certs\cert.pem -key-file .\certs\key.pem localhost 127.0.0.1 ::1 192.168.2.106
```

Replace `192.168.2.106` with your LAN IP.

### 2) Start SFU in secure LAN mode

Set env:

```powershell
$env:SFU_HOST="0.0.0.0"
$env:SFU_PORT="4443"
$env:SIGNALING_REQUIRE_TLS="true"
$env:TLS_CERT="D:\HTQWeb1\certs\cert.pem"
$env:TLS_KEY="D:\HTQWeb1\certs\key.pem"
```

Run:

```powershell
cd .\sfu
npm run dev
```

## Cloudflare + Bore Quick Start

Expose the local stack so someone outside can test the conference — no
account, no credit card. Cloudflare carries the signalling, bore carries the
media (UDP never passes an HTTP tunnel).
Full details: [docs/TUNNEL_SETUP.md](docs/TUNNEL_SETUP.md)

1. Start the stack (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`) and Vite
2. Run `.\scripts\start-public-test.ps1 -GuestEmail guest@example.com`
3. Send the printed link and credentials; Ctrl+C restores local mode

## Architecture
Project structure and refactoring conventions are documented in:
- `docs/architecture.md`

## 🔧 WebRTC Video/Audio Troubleshooting

Если у вас проблемы с видео/аудио потоками между клиентами, начните отсюда:

### ⚡ Быстрое исправление (5 минут)
Прочитайте [QUICK_FIX.md](./QUICK_FIX.md) - пошаговое руководство по настройке

### 📖 Детальная диагностика
Прочитайте [WEBRTC_TROUBLESHOOTING.md](./WEBRTC_TROUBLESHOOTING.md) - полное руководство

### 🛠️ Инструменты диагностики

**1. Проверка конфигурации SFU:**
```bash
node scripts/check-sfu-config.js
```

**2. Диагностика в браузере:**
- Откройте консоль (F12) на странице конференции
- Вставьте содержимое [diagnose-webrtc.js](./diagnose-webrtc.js)
- Следуйте рекомендациям в выводе

### 🎯 Типичные проблемы

| Проблема | Решение |
|----------|---------|
| Видео работает только локально | Настройте `WEBRTC_ANNOUNCED_IP` в `sfu/.env` |
| Аудио есть, видео нет | Откройте порт 44444 (UDP+TCP) в firewall |
| Работает только в LAN | Настройте TURN сервер |
| Камера не работает | Нужен HTTPS (используйте ngrok/туннель) |

### 📝 Пример конфигурации

Скопируйте `sfu/.env.example` в `sfu/.env` и настройте под ваш сервер:
```bash
cp sfu/.env.example sfu/.env
```
