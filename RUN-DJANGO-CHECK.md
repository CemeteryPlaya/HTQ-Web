# Проверочный запуск Django-версии в контейнерах

Отдельная самодостаточная сборка нового Django-бэкенда + React-фронтенда + БД/Redis/MinIO.
Работает **параллельно** с существующим `htqweb1` (FastAPI) — ничего не конфликтует
(другой проект `htqweb-django`, свои тома и хост-порты).

## Запуск

```bash
docker compose -f docker-compose.django.yml up -d --build
```

Первый запуск: собирает образы (backend ~2–4 мин, frontend-сборка ~3–6 мин), поднимает БД,
применяет миграции и создаёт админа. Прогресс:

```bash
docker compose -f docker-compose.django.yml logs -f web        # миграции, сид админа, запросы
docker compose -f docker-compose.django.yml ps                 # статус контейнеров
```

## Что открыть

| URL | Что это |
|---|---|
| **http://localhost:8090** | React-SPA (главное — сюда) |
| http://localhost:8090/django-admin/ | Django-админка (стили есть — DEBUG-режим) |
| http://localhost:8001/api/core/v1/services/ | API напрямую (реестр сервисов) |
| http://localhost:9011 | Консоль MinIO |

**Вход:** `admin` / `admin12345` (создаётся автоматически). MinIO: `minioadmin` / `minioadmin`.

## Что РАБОТАЕТ, а что нет

Миграция FastAPI→Django **не завершена**. Работают перенесённые домены:
- **users** (вход, профиль, регистрация, админ-управление),
- **cms** (новости, контакт-реквесты, категории/теги),
- **media** (загрузка/отдача файлов),
- **hr** (отделы, должности, сотрудники, оргструктура/матрица подчинения).

Пока НЕ перенесены (пустые аппки — их страницы во фронте вернут 404/«сервис недоступен»,
это ожидаемо): **tasks, requests (согласования), mail (почта), messenger, конференции**.

## Управление

```bash
# остановить (данные сохраняются в томах)
docker compose -f docker-compose.django.yml down

# остановить и стереть данные (чистый старт)
docker compose -f docker-compose.django.yml down -v

# пересобрать после изменений кода бэкенда/фронта
docker compose -f docker-compose.django.yml up -d --build

# логи воркера/beat
docker compose -f docker-compose.django.yml logs -f worker beat
```

## Порты (чтобы не путать с htqweb1)

| Сервис | Хост-порт | (htqweb1 занимает) |
|---|---|---|
| frontend (nginx) | 8090 | 3000 |
| backend (Django) | 8001 | 8005–8013 |
| Postgres | 5435 | 5432 / 55432 |
| MinIO API / консоль | 9010 / 9011 | 9000 / 9001 |
| Redis | (только внутри сети) | 6379 |

## Состав стека (`docker-compose.django.yml`)

`db` (postgres:16) · `redis` (7) · `minio` + `minio-setup` (создаёт бакеты) ·
`web` (Django runserver, делает migrate+сид) · `worker` + `beat` (Celery) ·
`frontend` (nginx: раздаёт SPA, проксирует `/api` и `/ws` в `web`).

Файлы сборки: `backend/Dockerfile`, `backend/docker-entrypoint.sh`,
`frontend/Dockerfile.check`, `infra/django-check/nginx.conf`.
