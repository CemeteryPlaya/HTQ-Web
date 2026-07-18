# STRUCTURE.md — навигационная карта проекта HTQWeb

Путеводитель по репозиторию для людей и ИИ-агентов: где что лежит, по каким правилам устроены каталоги, куда смотреть в первую очередь. Цель — не сканировать весь проект.

> Дополняющие документы: [README.md](./README.md) (как поднять), [API.md](./API.md) (роутинг и контракты), [services/README.md](./services/README.md) (анатомия микросервиса), [docs/architecture.md](./docs/architecture.md) (архитектурные решения).

---

## 1. Что это за проект

Внутренняя enterprise-платформа Hi-Tech Group. Мигрирована по паттерну **Strangler Fig** из Django-монолита в FastAPI-микросервисы. Django удалён (фаза 4.8); все домены — в `services/*`. Фронтенд — React + Vite SPA.

**Стек:**
- **Frontend:** React 18 + Vite + TypeScript, shadcn/ui (Radix+Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright.
- **Backend:** FastAPI + SQLAlchemy 2.0 async + Alembic + Dramatiq (на Redis).
- **Данные:** PostgreSQL (через PgBouncer) — **одна схема `public` + префиксы таблиц** (исключение: `user`→схема `auth`; подробности §7). MongoDB (`htqweb_docs`) для HR-документов и admin-панели. Redis.
- **Шлюз:** Nginx как API Gateway.
- **Видео:** Mediasoup SFU + WebTransport.
- **Опц.:** LibreTranslate (перевод оргдерева HR, compose-профиль `translation`).
- **Логи:** Loki/Promtail/Grafana.

---

## 2. Дерево верхнего уровня

```
HTQWeb1/
├── frontend/             # React + Vite SPA (см. §4)
├── services/             # FastAPI-микросервисы (см. §3)
│   ├── _template/        # Канонический шаблон нового сервиса
│   ├── scaffold.py       # Генератор: python scaffold.py <name> <desc>
│   ├── user/ hr/ task/ requests/ cms/ media/ messenger/ email/   # бизнес-сервисы (Python)
│   ├── admin/            # sqladmin-агрегатор (Python)
│   ├── adminjs/          # ⭐ Unified AdminJS panel (Node.js, PG+Mongo)
│   └── README.md         # Анатомия сервиса + правила
├── libs/
│   └── htqweb_auth/      # ⭐ ОБЩАЯ auth-библиотека (JWT, RBAC, levels) — см. §3, §10
├── sfu/                  # Mediasoup SFU (Node.js, медиа-роутинг конференций)
├── webtransport/         # QUIC signalling proxy (Python aioquic) для SFU
├── infra/
│   ├── nginx/default.conf  # ⭐ API Gateway: вся маршрутизация /api/* → сервисы
│   ├── db/init-ltree.sql   # Инициализация ltree-расширения PG
│   ├── logging/            # Loki + Promtail + Grafana provisioning
│   └── certs/              # Локальные TLS (gitignored)
├── docs/                 # Архитектура, аудиты, ngrok/tunnel-инструкции
├── scripts/              # PS/JS-утилиты (TLS, firewall, туннели)
├── tools/                # Локальные бинари туннелей (gitignored)
├── docker-compose.yml      # Прод-стек (полный)
├── docker-compose.dev.yml  # Dev-overlay (Vite HMR, MinIO, /docs включены)
├── README.md   API.md   PLAN.md (план миграции + журнал)
└── backend/              # ⚠️ мёртвые остатки Django (untracked, ждёт удаления)
```

> ⚠️ Игнорировать на верхнем уровне: `backend/` (мёртвый Django), пустой `nginx/`, корневые `node_modules/`/`package.json` (служебный tooling). Авторитетный nginx-конфиг — только `infra/nginx/default.conf`.

---

## 3. Микросервисы (`services/`)

**Правило об общем коде (важно):** разделяемая логика **аутентификации** вынесена в пакет `libs/htqweb_auth` (примитивы JWT/RBAC/levels), доступный сервисам через `PYTHONPATH=/app:/app/libs`. Всё остальное (storage `s3_storage.py`, middleware и т.п.) **намеренно дублируется** в каждом сервисе. Каждый сервис — изолированное FastAPI-приложение по шаблону `services/_template/`. Источник правды по структуре — [services/README.md](./services/README.md).

### 3.1 Карта сервисов

Порты согласованы между [README.md](./README.md), `infra/nginx/default.conf` и `docker-compose.yml` (прежнего расхождения портов больше нет).

| Сервис | Порт | Schema | Стек | Домен | Главные роутеры (`app/api/v1/`) |
|---|---|---|---|---|---|
| **user** | 8005 | `auth` | Py | Identity, JWT, регистрация, профиль, админ-юзеры | `auth.py`, `profile.py`, `admin.py`, `registration.py`, `items.py`, `client_errors.py` |
| **hr** | 8006 | `public` (`hr_*`) + Mongo | Py | Сотрудники, отделы, должности, вакансии, заявки, табель, документы (в Mongo), аудит, оргдерево | `employees.py`, `departments.py`, `positions.py`, `vacancies.py`, `applications.py`, `time.py`, `documents.py`, `mongo_documents.py`, `org.py`, `pmo.py`, `audit.py`, `personnel_history.py`, `share_links.py` |
| **task** | 8007 | `public` (`task_*`) | Py | Workflow-движок Jira+SharePoint (см. §4.2) | `tasks.py`, `comments.py`, `attachments.py`, `calendar.py`, `labels.py`, `links.py`, `activity.py`, `versions.py`, `sequences.py`, `notifications.py` |
| **requests** | 8013 | `public` (`request_*`) | Py | ⭐ Lark-style approval-движок: конструктор форм + workflow (см. §3.4) | `forms.py`, `instances.py`, `actions.py`, `projects.py`, `stats.py`, `stream.py` (SSE) |
| **cms** | 8011 | `public` (`cms_*`) | Py | Новости, contact-requests, ConferenceConfig | `news.py`, `contact_requests.py`, `conference.py` |
| **media** | 8009 | `public` | Py | Файловое хранилище (S3 + local), Range-стриминг | `files.py` |
| **messenger** | 8008 | `public` | Py | Чат, WebSocket/Socket.IO, presence, E2EE-ключи | `messages.py`, `rooms.py`, `users.py`, `read.py`, `keys.py`, `attachments.py`, `admin.py` + `socket.py` |
| **email** | 8010 | `public` (`email_*`) | Py | Дуальная почта: Mailcow + OAuth Gmail/Outlook, sync, push, DLP (см. §4.1) | `accounts.py`, `emails.py`, `oauth.py`, `webhooks.py`, `mailboxes.py` |
| **admin** | 8012 | — | Py | sqladmin-агрегатор (`/sqladmin/`) | (без public API, только admin UI) |
| **adminjs** | 3300 | PG + Mongo | Node | ⭐ Unified AdminJS panel (sequelize+mongoose), напрямую на `:3300/admin` | (Node.js, не через основной nginx) |

> **Schema:** только `user` живёт в выделенной PG-схеме `auth`. Все остальные Python-сервисы используют схему `public` с префиксом таблиц по домену (`hr_*`, `task_*`, `request_*`, `cms_*`, `email_*`). Причина — PgBouncer в transaction-режиме сбрасывает `search_path` (см. §7).

### 3.2 Анатомия одного Python-сервиса (user / hr / task / requests / cms / media / messenger / email)

```
services/<name>/
├── Dockerfile               # multi-stage builder + runtime; COPY-пути от корня репо
├── entrypoint.sh            # alembic upgrade head → uvicorn
├── requirements.txt   pyproject.toml
├── alembic.ini   alembic/   # миграции (env.py владеет своей транзакцией)
├── tests/
└── app/
    ├── main.py              # FastAPI factory + lifespan + router include
    ├── db.py                # SQLAlchemy 2.0 async engine + session, search_path
    ├── mongo.py             # (только hr) Motor-клиент к htqweb_docs
    ├── core/
    │   ├── settings.py      # Pydantic BaseSettings (env-driven)
    │   └── health.py        # /health/, /health/ready/
    ├── auth/
    │   └── dependencies.py  # ⭐ ТОНКИЙ shim: re-export из htqweb_auth + сервис-специфичные гейты
    ├── middleware/
    │   └── request_id.py    # X-Request-ID propagation
    ├── models/              # SQLAlchemy ORM (1 файл = 1 модель/группа)
    ├── schemas/             # Pydantic DTO (request/response)
    ├── repositories/        # DB access layer (там, где имеет смысл)
    ├── services/            # ⭐ Бизнес-логика (искать тут, не в роутерах)
    ├── api/v1/              # HTTP-роуты (тонкие, только парсинг → service)
    ├── admin/               # sqladmin ModelViews + create_admin()
    └── workers/
        ├── __init__.py      # broker init (Redis)
        ├── actors.py        # @dramatiq.actor
        └── scheduler.py     # APScheduler periodics (опц.)
```

**Запомнить:**
- Бизнес-логика — всегда в `app/services/<domain>_service.py`. Роуты её только вызывают.
- Web и worker — **один Docker-образ**, разные `command` в compose (`uvicorn` vs `dramatiq`).
- Auth: примитивы из `htqweb_auth`, реэкспорт через `app/auth/dependencies.py`. JWT с `iss=htqweb-auth` (НЕ `user-service`), валидация общая.

### 3.3 Создание нового сервиса

```bash
python services/scaffold.py <name> "<short description>"
# Затем: добавить <name>-service / <name>-worker в docker-compose.yml
#        + location /api/<name>/ в infra/nginx/default.conf
# Шаблон по умолчанию: DB_SCHEMA=public, PYTHONPATH=/app:/app/libs (htqweb_auth доступен).
```

### 3.4 Requests — Lark-style approval-движок

`requests` (:8013, схема `public`/`request_*`) — конструктор **форм + цепочек согласования** (no-code), вдохновлён Lark Approvals.

- **Модели:** `request_form_templates` (+ `_versions`), `request_instances`, `request_approval_actions`, `request_projects` (+ `_project_members`), `request_activity`, `request_watchers`, `request_notifications_log`, `request_departments`/`user_replica` (реплики из hr/user через Redis), `stats_daily`.
- **Сервисы (`app/services/`):** `workflow_engine.py` + `workflow_schema.py` (исполнение цепочки), `form_schema.py`/`form_template`/`template_validation.py`/`value_validation.py` (формы), `condition_eval.py` (ветвления), `assignee_resolver.py` (кто согласует), `dispatch.py` (рассылка), `hr_client.py`/`messenger_client.py` (S2S к hr/messenger), `stats_rollup.py`, `audit.py`.
- **Роуты:** base `/api/requests/v1` → `/forms`, `/instances` (+ `/actions` на инстансах), `/projects`, `/stats`, `/stream` (SSE-нотификации, отдельная nginx-локация без буферизации).
- **Frontend:** [frontend/src/features/requests/](frontend/src/features/requests/) (RequestsLayout, pages, components, hooks.ts, types.ts) + [frontend/src/api/requests.ts](frontend/src/api/requests.ts).

---

## 4. Frontend (`frontend/`)

React 18 + Vite + TypeScript. shadcn/ui (Radix + Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright.

```
frontend/src/
├── main.tsx   App.tsx   index.css   i18n.js
├── app/
│   ├── routing/        # ⭐ routeDefinitions.ts, lazyPages.ts, prefetch.ts
│   └── components/
├── pages/              # ⭐ Точки входа роутов (Index, Login, Admin*, HR*, Calendar, Email/, hr/, public/, requests/)
│   ├── Email/          # OAuth callback, inbox, compose modal, settings panel
│   └── hr/             # HR-страницы (Departments, Employees, Vacancies, Tasks, Roadmap, …)
├── features/
│   ├── messenger/      # MessengerPage + api/ + hooks/ + types.ts (feature-sliced)
│   └── requests/       # ⭐ RequestsLayout + pages/ + components/ + hooks.ts + types.ts
├── components/
│   ├── ui/             # shadcn primitives (50+ компонентов)
│   ├── hr/ tasks/ calendar/ profile/   # Доменные компоненты
│   └── *.tsx           # Лендинг-секции, Header/Footer, RequireAuth и т.д.
├── api/                # ⭐ HTTP-клиенты по домену:
│                       #   client.ts (base axios+JWT), endpoints.ts (карта префиксов),
│                       #   users.ts, hr.ts, tasks.ts, requests.ts, cms.ts, media.ts,
│                       #   calendar.ts, email.ts, fileManager.ts, search.ts (глобальный fan-out поиск)
├── services/           # emailService.ts (тонкие обёртки над api/)
├── hooks/              # useActiveProfile, useHRLevel, use-mobile, use-toast, …
├── lib/
│   ├── auth/           # profileStorage.ts, roles.ts (RBAC хелперы)
│   ├── transport/      # IMediaTransport + WebRTCAdapter
│   ├── webrtc/         # ⭐ MediaEngine, WebRTCManager, SignalingClient (WS+WebTransport), SdpMunger, BitrateController
│   ├── telemetry.ts    # Frontend → backend client-errors
│   └── utils.ts        # cn() и общие хелперы
├── data/               # Статика лендинга (contacts.ts, projects.ts, services.ts)
├── locales/            # ru/kz/en JSON (см. check-i18n.mjs / update_i18n.py)
├── types/              # Глобальные TS-типы
└── test/               # Vitest setup
```

**Где что искать:**
- Новый роут — `app/routing/routeDefinitions.ts` + лениво в `lazyPages.ts` + страница в `pages/`.
- Новый API-клиент — `api/<domain>.ts`, базовый axios + JWT-интерсептор в `api/client.ts`, префиксы — в `api/endpoints.ts`.
- Глобальный поиск (`api/search.ts`) — fan-out: параллельно дёргает list-эндпойнты доменов и мёржит (упавший источник, напр. 403, молча игнорится).
- Доменная фича крупнее одной страницы — `features/<name>/` (как `messenger`, `requests`).
- UI-примитив — `components/ui/` (shadcn). Доменный — `components/<domain>/`.

---

## 4.1 Email — дуальная архитектура (corp + personal)

С одной страницы [/email](frontend/src/pages/Email/EmailPage.tsx) пользователь работает с **корпоративным ящиком** (Mailcow) и подключёнными **личными** Gmail / Outlook — переключение через account-selector в сайдбаре. Подробности — [services/email/README.md](./services/email/README.md).

**Pivot-таблица:** одна `email_accounts` строка на mailbox. CHECK-constraint гарантирует консистентность с провайдером:
```
email_accounts(id, user_id, type=corporate|personal, provider=mailcow|google|microsoft,
               address, is_default, is_active,
               mailbox_id → provisioned_mailboxes (1:1, corporate),
               oauth_token_id → oauth_tokens (1:1, personal),
               sync_state JSONB, last_sync_at, watch_expires_at)
```
`EmailMessage.account_id` указывает сюда (FK `ON DELETE SET NULL`).

**Sync** ([services/email/app/services/sync/](services/email/app/services/sync/)):
- `gmail.py` — `users.history.list` + `messages.list`/`get`; push через `users.watch` → Pub/Sub
- `microsoft.py` — `/me/messages/delta` + persisted `@odata.deltaLink`; push через Graph subscriptions
- `mailcow_imap.py` — IMAP backfill; live-push через контейнер `email-imap-idle`
- UPSERT с `(account_id, message_id)` UNIQUE → идемпотентно
- `pg_try_advisory_lock(0x454D4149, account_id)` сериализует concurrent runs

**Push receivers** ([webhooks.py](services/email/app/api/v1/webhooks.py)) — public, `nginx /api/email/v1/webhooks/` БЕЗ rate-limit. Auth: Gmail Bearer JWT (google-auth) + fallback token; Graph initial `validationToken` echo + `clientState`.

**Send** ([services/email/app/services/sender/](services/email/app/services/sender/)) — стратегия по `provider`: Gmail API `messages.send` (base64url MIME), Graph `/me/sendMail` (JSON), Mailcow SMTP 587 STARTTLS. `POST /api/email/v1/send` ставит `folder='outbox'` + enqueue `deliver_email` actor.

**Cascade delete:** `DELETE /api/users/v1/admin/users/{id}/` → user.status=SUSPENDED + S2S archive Mailcow + Redis `user.deactivated`/`user.deleted` → email-подписчик ([user_events.py](services/email/app/workers/user_events.py)) деактивирует personal accounts + `archived_at=now()` → cron `final_purge_archived_mailboxes` (03:15 daily) hard-delete после `MAILBOX_PURGE_AFTER_DAYS` (default 30).

**Контейнеры email-стека:** `email-service`, `email-worker`, `email-scheduler`, `email-imap-idle` (IDLE supervisor).
**Бакет S3/MinIO:** `htqweb-mail-attachments`.

---

## 4.2 Task workflow — Jira + SharePoint модель

`task` — не «трекер для разработчиков», а универсальный движок процессов: Jira (key, FSM, types, links, labels, versions) + SharePoint (supervisor с делегатами, мульти-исполнители, watchers, progress %, inline-quick-edit на Kanban-карточке).

**Роли на задаче** (миграция 012):
```
tasks
  ├── reporter_id       — кто создал
  ├── supervisor_id     — руководитель (может делегировать)
  ├── assignee_id       — primary-исполнитель (denormalized из task_assignees)
  └── progress_percent  — 0..100
task_assignees(task_id, user_id, role)   # M:M, role = primary|collaborator
task_delegates(task_id, user_id, granted_by, granted_at)
task_watchers(task_id, user_id)
```

**FSM-статусы (7):** `backlog → todo → in_progress → in_review → blocked → done → cancelled` (с обратными переходами; `TRANSITIONS` в [task.py](services/task/app/models/task.py)). Старая 5-статусная модель мигрирует автоматически (`open→todo`, `closed→cancelled`).

**Permissions** ([tasks.py](services/task/app/api/v1/tasks.py) — `_can_edit_task`):
- Полное редактирование: `is_elevated`, reporter, supervisor, активные delegates
- Статус/progress/комментарии: + все assignees
- Видимость: + watchers

**Endpoints управления ролями:**
```
PATCH  /api/tasks/v1/tasks/{id}/supervisor    body: {user_id|null}
PATCH  /api/tasks/v1/tasks/{id}/assignees     body: [{user_id, role}]
POST   /api/tasks/v1/tasks/{id}/delegates     body: {user_id}   (только supervisor)
DELETE /api/tasks/v1/tasks/{id}/delegates/{user_id}
POST   /api/tasks/v1/tasks/{id}/watch  •  DELETE …/watch
PATCH  /api/tasks/v1/tasks/{id}/progress      body: {percent}
```

**Projects + TaskType registry** (миграция 013, заменила `ProjectVersion`):
```
projects(id, name, status=active|completed|archived, color, start_date, end_date, owner_id, department_id)
task_types(id, slug UNIQUE, name, color, icon, is_system)   # user-extensible
tasks.project_id   → projects(id)   ON DELETE SET NULL   # NULL = standalone
tasks.task_type_id → task_types(id) ON DELETE SET NULL   # заменил enum tasktype
```
- Тип задачи — таблица `task_types` (не PG-enum). Seeded 5 system-строк (task/bug/story/epic/subtask, `is_system=true`). `Task.task_type` — computed-свойство → slug (back-compat фронта).
- Project — durable-инициатива (не «релиз»). Задача либо в проекте (`project_id`), либо «свободная» (`project_id IS NULL`).
- Роудмап ([HRRoadmap.tsx](frontend/src/pages/hr/HRRoadmap.tsx)) рендерит проекты → дерево задач по `parent_id`.
```
GET/POST/PATCH/DELETE /api/tasks/v1/projects/[{id}/]   •   GET …/projects/{id}/tasks/
GET/POST/PATCH/DELETE /api/tasks/v1/task-types/[{id}/]
GET /api/tasks/v1/tasks/?standalone=true   •   ?project_id=N
```

**Kanban** ([KanbanBoard.tsx](frontend/src/components/tasks/KanbanBoard.tsx)): 7 колонок по ширине (flex-1, без гор.скролла на ≥xl); карточки пагинируются (`CARDS_PER_PAGE=6`). Inline popover-edit прямо на карточке: приоритет, primary+collaborators, supervisor, progress %, метки.

---

## 5. Видео/конференции

| Компонент | Где | Что делает |
|---|---|---|
| **SFU** | [sfu/src/server.ts](./sfu/src/server.ts), [sfu/src/room.ts](./sfu/src/room.ts) | Mediasoup SFU, медиа-роутинг. Кодеки: `media-codecs.config.json`. |
| **WebTransport proxy** | [webtransport/server.py](./webtransport/server.py) | QUIC-сигнализация (aioquic) для SFU. |
| **Frontend WebRTC** | [frontend/src/lib/webrtc/](./frontend/src/lib/webrtc/) | `MediaEngine`, `WebRTCManager`, `SignalingClient`(WS)/`WebTransportSignalingClient`, `SdpMunger`, `BitrateController`. |
| **UI** | [frontend/src/pages/ConferencePage.tsx](./frontend/src/pages/ConferencePage.tsx) | Страница конференции. |
| **Конфиг конференции** | `services/cms/app/api/v1/conference.py` | ConferenceConfig (CMS-сервис). |

Туннели/HTTPS для LAN: [docs/TUNNEL_SETUP.md](./docs/TUNNEL_SETUP.md), скрипты — [scripts/start-sfu-tunnel.ps1](./scripts/start-sfu-tunnel.ps1).

---

## 6. Маршрутизация: «куда улетает запрос»

**Источник правды:** [infra/nginx/default.conf](./infra/nginx/default.conf) (upstream-блоки `server <svc>:<port>` + `location` longest-match).

```
/api/tasks/             → task-service:8007
/api/requests/v1/stream → requests-service:8013   (SSE: без буферизации/таймаута)
/api/requests/          → requests-service:8013
/api/hr/v1/public/      → hr-service:8006          (публичные)
/api/hr/                → hr-service:8006
/api/users/v1/          → user-service:8005
/api/messenger/         → messenger-service:8008   (+ /ws/ Socket.IO upgrade)
/api/media/             → media-service:8009
/api/cms/               → cms-service:8011
/api/email/v1/webhooks/ → email-service:8010       (БЕЗ rate-limit, Gmail Pub/Sub + Graph)
/api/email/             → email-service:8010
/ws/sfu/                → sfu:4443
/sqladmin/              → admin-service:8012        (sqladmin-агрегатор)
/                       → frontend (Vite-сборка через nginx)
```
> AdminJS-панель (`adminjs-panel`) НЕ проходит через основной nginx — слушает напрямую `:3300/admin`.

При добавлении эндпойнта: роутер в `services/<name>/app/api/v1/<file>.py` → подключить в `app/main.py` → если новый префикс, добавить upstream + `location` в `infra/nginx/default.conf`. Полный контракт — в [API.md](./API.md).

---

## 7. БД, миграции, фоновые задачи

- **PostgreSQL** один на все сервисы, через **PgBouncer** (порт `55432` снаружи).
- **Схемы:** PgBouncer в transaction-режиме **сбрасывает `search_path`**, поэтому изначальная «schema-per-service» модель свёрнута. Реальность: **все сервисы пишут в схему `public`** и изолируются **префиксом таблиц** по домену (`hr_*`, `task_*`, `request_*`, `cms_*`, `email_*`). Единственное исключение — `user-service`, у которого выделенная схема `auth` (`DB_SCHEMA: auth`). `search_path` задаётся в `app/db.py`, но на него нельзя полагаться между транзакциями — отсюда префиксы.
- **MongoDB** (`htqweb_docs`): хранит **HR-документы** (`hr/app/mongo.py` + `api/v1/mongo_documents.py`, Motor). Также используется `adminjs-panel`.
- **Миграции:** Alembic per-service (`services/<name>/alembic/versions/`). `entrypoint.sh` гонит `alembic upgrade head` перед стартом. ⚠️ `alembic/env.py` должен сам владеть транзакцией (PgBouncer).
- **Фоновые задачи:** Dramatiq + Redis. Объявление — `app/workers/actors.py`, периодика — `app/workers/scheduler.py` (APScheduler). Worker — отдельный compose-сервис из того же образа.
- **Идентификация:** один `user-service` выпускает JWT с claim **`iss=htqweb-auth`** (НЕ `user-service`!); остальные только валидируют через `htqweb_auth`.

### 7.1 Объектное хранилище (S3 / MinIO)

> **Манифест: 1 микросервис = 1 бакет** (та же изоляция, что и для таблиц). Кросс-сервисные файловые потоки — через HTTP. Подробности — [services/README.md §Object storage](./services/README.md#object-storage).

В dev — контейнер **MinIO** в [docker-compose.dev.yml](./docker-compose.dev.yml) (консоль `:9001`, `minioadmin`/`minioadmin`). При первом запуске `minio-bootstrap` создаёт бакеты. В проде — настоящий S3, сменой `S3_ENDPOINT` без правок кода.

| Бакет | Сервис | Для чего |
|---|---|---|
| `htqweb-media` | media | Аватарки, общее медиа |
| `htqweb-messenger` | messenger | Чат-аттачменты + еженедельный архив (`history/YYYY/MM/DD.jsonl`, сб 04:30 GMT+5) |
| `htqweb-cms` | cms | Снапшоты новостей (`content.md`, `metadata.json`), обложки, аттачменты |
| `htqweb-mail-attachments` | email | Аттачменты писем. Layout: `inbound/<account_id>/<message_id>/<filename>` |
| `htqweb-conferences` | _(future SFU)_ | Заготовка под записи конференций |

URL-флоу приватных файлов: API возвращает стабильный signed URL (`?sig=&exp=`) → endpoint валидирует подпись+ACL → **302** на свежий presigned S3 URL. Работает в `<img src>` без JWT.

Storage-абстракция (`s3_storage.py` + `signed_url.py`) **дублируется в каждом сервисе** — сознательно (см. §10).

---

## 8. Observability и dev-инструменты

| Что | Где |
|---|---|
| Структурные логи | каждый сервис → stdout → Promtail → Loki |
| Конфиги стека логов | [infra/logging/](./infra/logging/) (Loki, Promtail, Grafana) |
| Health checks | `GET /health/` и `/health/ready/` (`app/core/health.py`) |
| Request tracing | `X-Request-ID` через `app/middleware/request_id.py` |
| Аудиты/анализы | [docs/audit-2026-04-28/](./docs/audit-2026-04-28/), [docs/static-analysis-2026-04-28.md](./docs/static-analysis-2026-04-28.md), [docs/dependency-audit-2026-04-28.md](./docs/dependency-audit-2026-04-28.md) |
| План миграции + журнал | [PLAN.md](./PLAN.md) |

---

## 9. Где правильно что-то делать (шпаргалка)

| Задача | Куда смотреть |
|---|---|
| Поменять/добавить роут API | `services/<name>/app/api/v1/<file>.py` (+ возможно `infra/nginx/default.conf`) |
| Изменить бизнес-логику | `services/<name>/app/services/<domain>_service.py` |
| Новая ORM-таблица | `services/<name>/app/models/` (`__tablename__` с доменным префиксом!) + `alembic revision --autogenerate` |
| DTO запроса/ответа | `services/<name>/app/schemas/` |
| Auth/JWT/RBAC примитив | `libs/htqweb_auth/` (общий) → реэкспорт в `app/auth/dependencies.py` |
| HR-документ в Mongo | `services/hr/app/mongo.py` + `api/v1/mongo_documents.py` |
| Фоновая задача | `services/<name>/app/workers/actors.py` |
| Админ-страница sqladmin | `services/<name>/app/admin/views/<model>.py` + регистрация в `admin/__init__.py` |
| Новый фронтенд-роут/страница | `frontend/src/app/routing/routeDefinitions.ts` + `pages/<Name>.tsx` |
| HTTP-вызов из фронтенда | `frontend/src/api/<domain>.ts` (axios через `client.ts`, префиксы в `endpoints.ts`) |
| Доменная UI-фича | `frontend/src/features/<name>/` (масштаб > одной страницы) |
| Локализация | `frontend/src/locales/{ru,kz,en}/*.json` (валидатор `check-i18n.mjs`) |
| Конференц-логика на клиенте | `frontend/src/lib/webrtc/` |
| SFU/медиа | `sfu/src/` |
| Шлюз/маршрутизация | `infra/nginx/default.conf` |
| Compose / порты / переменные | `docker-compose.yml` (+ `docker-compose.dev.yml` для dev) |
| Создать новый микросервис | `python services/scaffold.py <name> "<desc>"` (затем compose + nginx) |
| Залить файл в S3 | `app/services/s3_storage.py` → `await get_storage().save(key, bytes, content_type=...)` |
| Приватный файл в `<img>` | вернуть в API `url=...?sig=&exp=` (`signed_url.py`); endpoint 302 → presigned URL |

---

## 10. Известные «ловушки»

- **Schema ≠ schema-per-service.** Все сервисы (кроме `user`→`auth`) пишут в `public` и изолируются **префиксом таблиц**. PgBouncer (transaction-режим) сбрасывает `search_path` — не полагаться на него между транзакциями.
- **JWT issuer — `htqweb-auth`**, не `user-service`. Это частая ошибка при настройке валидации.
- **Общий код есть, но только auth.** `libs/htqweb_auth` (через `PYTHONPATH=/app:/app/libs`) — единственная разделяемая библиотека. Storage/middleware дублируются намеренно; не выносить в shared без явного решения.
- **`backend/`** — мёртвый Django, untracked. Не дополнять, ждёт удаления. Корневые `nginx/`, `node_modules/`, `package.json` — служебные/пустые, игнорировать.
- Все сервисы делят одну PG-инстанцию через PgBouncer, но логически изолированы. Не ходить в чужие таблицы напрямую — общаться через HTTP/JWT (+ Redis pub/sub для реплик user/department).
- **Dockerfile `COPY`** — пути относительно корня репозитория (build context = `.`), не относительно папки сервиса.
- **`alembic/env.py`** должен сам управлять транзакцией (PgBouncer-совместимость).
- Новые Python-сервисы регистрируются в **трёх местах**: compose (web+worker[+scheduler]), nginx (upstream + location), опц. `services/admin/` или `adminjs`. Node-сервисы (`adminjs`, `sfu`) — отдельные образы.
