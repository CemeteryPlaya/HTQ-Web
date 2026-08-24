# HTQWeb — внутренняя платформа Hi-Tech Group

React + Vite SPA перед **единым Django-бэкендом**. Одно процессное семейство, один Postgres,
десять доменных приложений: кадры, задачи и проекты, согласования, договоры, почта, мессенджер,
CMS, файловое хранилище, видеоконференции.

> **Статус архитектуры: миграция завершена.** Платформа прошла полный круг — Django-монолит →
> ~9 FastAPI-микросервисов (Strangler Fig) → **обратно в один Django-бэкенд** (`backend/`).
> Каталогов `services/`, `libs/`, MongoDB, sqladmin и AdminJS в репозитории больше нет.
> Журнал миграции — [PLAN.md](./PLAN.md) (читать как историю, а не как план работ).

```
Браузер
   │
   ▼
Edge:  dev → Vite dev-сервер :3000  │  prod → nginx :80/:443
   │
   ▼
Один Django-бэкенд (Python 3.14, Django 5.2.7) — один образ, разные `command`:
   backend-web     :8000  gunicorn/WSGI  — весь /api/*, /django-admin/, статика
   backend-asgi    :8001  uvicorn/ASGI   — SSE /api/requests/v1/stream + WS /ws/
   backend-worker         Celery worker  — фоновые задачи всех доменов
   backend-beat           Celery beat    — периодика (django-celery-beat, из БД)
   flower          :5555  мониторинг Celery
   │
   ▼
PostgreSQL :5432 (прямое подключение, одна схема public)  ·  Redis :6379 (кэш + брокер)
MinIO/S3 :9000 (:9001 консоль)  ·  Mediasoup SFU :4443  ·  Loki/Grafana/Prometheus
```

Полная таблица маршрутизации и контракты эндпойнтов — [API.md](./API.md).

---

## Быстрый старт

Compose-файлов **ровно три**, каждый **самодостаточный**: запускается одиночным `-f <файл>`,
без цепочки `-f a -f b`.

| Файл | Что поднимает | БД | Миграции |
|---|---|---|---|
| `docker-compose.yml` | **прод**: фронт собран в статику, gunicorn, nginx/sfu/certbot (профиль `production`) | из `.env` | ON |
| `docker-compose.test-local.yml` | **тест**: Vite HMR :3000, DEBUG, автоперезагрузка | Postgres в контейнере (`:55432`) | ON |
| `docker-compose.test-env.yml` | **тест**: то же самое | из `.env` (обычно боевая) | **OFF** |

### Тестовый стек с локальной БД — обычный режим разработки

```bash
docker compose -f docker-compose.test-local.yml up -d --build
# или то же самое одной командой:
./dev-up.sh
```

Пересобрать один процесс после правки кода:

```bash
docker compose -f docker-compose.test-local.yml up -d --build --no-deps backend-web
```

Этот файл **жёстко** прописывает `DB_HOST: db` — подстановки из `.env` там нет намеренно,
иначе «локальный» стек ушёл бы на боевую базу. E2E-тесты гоняются только по нему.

### Тестовый стек с БД из `.env`

```bash
docker compose -f docker-compose.test-env.yml up -d --build
docker compose -f docker-compose.test-env.yml exec backend-web printenv DB_HOST   # куда реально смотрит
```

> ⚠️ В корневом `.env` обычно прописана **боевая** база на VPS: этот стек пишет в неё
> по-настоящему. Поэтому миграции здесь по умолчанию выключены (`RUN_MIGRATIONS=0`) — схему
> боевой БД меняют осознанно, а не побочным эффектом поднятия стека.

> ⚠️ Три стека публикуют одни и те же host-порты, поэтому одновременно поднимается только один.
> Имя проекта у каждого своё (`htq-web`, `htqweb-local`, `htqweb-env`), так что тома не
> пересекаются. Файлы не наследуют друг друга — правка общего сервиса повторяется во всех трёх
> (`git diff docker-compose*.yml` перед коммитом).

**Куда заходить:**

| | URL |
|---|---|
| Приложение (dev) | http://localhost:3000 |
| Django-admin | http://localhost:8000/django-admin/ |
| Реестр сервисов / health | http://localhost:8000/api/core/v1/services/ , `/health/`, `/health/ready/` |
| MinIO-консоль | http://localhost:9001 |
| Flower (Celery) | http://localhost:5555 |
| Grafana | http://localhost:3001 (или `/grafana/` через edge) |
| Prometheus | http://localhost:9090/prometheus |

**Учётка администратора** создаётся идемпотентно при каждом старте `backend-web`
(`RUN_MIGRATIONS=1` → `docker-entrypoint.sh`): `admin` / `admin12345`.
`backend-web` — **единственный** процесс, который выполняет `migrate`.

Vite-сервер слушает `0.0.0.0:3000` с `allowedHosts: true`, поэтому LAN-адреса работают так же,
как `localhost` — по **обычному HTTP**. Если браузер вдруг форсирует `https://`, это закэшенный
HSTS от прошлых запусков с TLS: `chrome://net-internals/#hsts` → *Delete domain security policies*.

### Прод-стек

```bash
cp .env.example .env      # заполнить секреты
docker compose up -d --build
docker compose ps
```

Плюс профиль `production`, который добавляет `nginx`, `sfu`, `certbot`, `webtransport`:

```bash
docker compose --profile production up -d
```

HTTPS через Let's Encrypt:

```bash
# 1. SERVER_DOMAIN=your-domain.com в .env
docker compose exec certbot certbot certonly --webroot \
  -w /var/www/certbot -d your-domain.com --email your@email.com --agree-tos
docker compose restart nginx
```

Контейнеры называются `htq-web-<service>-1` (имя compose-проекта берётся из каталога репозитория):
`htq-web-backend-web-1`, `htq-web-redis-1` и т.д. У тестовых стеков имя проекта своё:
`htqweb-local-<service>-1` и `htqweb-env-<service>-1` — тома и сети у них тоже раздельные.

---

## Структура репозитория

```
HTQWeb/
├── backend/                  # ⭐ ЕДИНЫЙ Django-бэкенд
│   ├── htqweb/               # Проектный пакет (общий для всех аппок):
│   │   ├── settings/         #   base.py / dev.py / test.py
│   │   ├── urls.py           #   корневой URLconf + автодискавери аппок по API_PREFIX
│   │   ├── wsgi.py asgi.py   #   gunicorn / uvicorn
│   │   ├── http.py           #   ⭐ api_view — собственный API-декоратор (НЕ DRF)
│   │   ├── authn/            #   JWT (issue/decode), RBAC, уровни отделов
│   │   ├── middleware/       #   request_id, service_gate, api_csrf_exempt
│   │   ├── admin_gate.py     #   ServiceGatedAdminMixin
│   │   └── storage/          #   S3/MinIO/локальный диск + подписанные URL
│   ├── apps/                 # ⭐ Доменные приложения — единицы изоляции (см. ниже)
│   ├── manage.py  requirements.txt  pytest.ini  conftest.py
│   ├── Dockerfile  docker-entrypoint.sh
│   ├── README.md             # ⭐ Анатомия аппки, правила, как добавить домен
│   └── README-tests.md       # Тестовый Postgres на :55432 и запуск pytest
├── frontend/                 # React 19 + Vite + TypeScript SPA
├── infra/
│   ├── nginx/default.conf    # ⭐ Единственный авторитетный конфиг шлюза
│   ├── db/init-ltree.sql     # Инициализация расширения ltree
│   └── logging/              # Loki, Promtail, Prometheus, Grafana (provisioning + дашборды)
├── sfu/                      # Mediasoup SFU (Node.js) — медиа-роутинг конференций
├── webtransport/             # QUIC-сигнализация (aioquic) перед SFU
├── scripts/                  # TLS-сертификаты, firewall, туннели, проверка конфига SFU
├── docs/                     # Архитектурные заметки, аудиты, хендоффы
├── docker-compose.yml        # Прод-стек (+ профиль production: nginx/sfu/certbot)
├── docker-compose.test-local.yml # Тест-стек: Vite HMR + Postgres в контейнере (:55432)
├── docker-compose.test-env.yml   # Тест-стек: Vite HMR, БД из .env, миграции OFF
├── dev-up.sh                 # Обёртка над docker-compose.test-local.yml
├── STRUCTURE.md              # ⭐ Навигационная карта репозитория (подробно, RU)
├── API.md                    # ⭐ Роутинг и контракты всех эндпойнтов
├── PLAN.md                   # Журнал завершённой миграции
└── CLAUDE.md                 # Ориентировка для ИИ-агентов
```

**Игнорировать на верхнем уровне:** пустой `nginx/` (авторитетен только `infra/nginx/default.conf`),
корневые `package.json`/`node_modules/` (служебный tooling, не фронтенд),
`infra/django-check/` (остаток промежуточного proof-of-concept) и `monitoring-demo/`
(отдельная демка стека наблюдаемости).

---

## Доменные приложения (`backend/apps/`)

| Аппка | URL-префикс | Имя в реестре | Домен |
|---|---|---|---|
| **core** | `api/core/v1/` | — (сам реестр) | Health-чеки, реестр отключаемости, общие ETL-хелперы |
| **users** | `api/users/v1/` | `users` | Identity, выпуск и валидация JWT, профиль, регистрации, админ-юзеры |
| **hr** | `api/hr/v1/` | `hr` | Сотрудники, отделы, должности, вакансии, табель, документы, оргдерево, PMO |
| **tasks** | `api/tasks/v1/` | `tasks` | Задачи (Jira+SharePoint-модель) + пятиуровневая иерархия проектов, план/факт, отчётность |
| **approvals** | `api/requests/v1/` | `approvals` | Lark-style конструктор форм + цепочки согласования собственных заявок |
| **signoff** | `api/signoff/v1/` | `signoff` | Универсальное многоэтапное согласование **чужих** строк по `(subject_type, subject_id)` |
| **contracts** | `api/contracts/v1/` | `contracts` | Бюджеты, реестр контрагентов, договоры с контролем остатка бюджета |
| **cms** | `api/cms/v1/` | `cms` | Новости, категории/теги, contact-requests, конфиг конференции |
| **media_files** | `api/media/v1/` | `media` | Общее файловое хранилище платформы (аватарки, HR-документы, вложения) |
| **mail** | `api/email/v1/` | `mail` | Дуальная почта: Mailcow (корпоративная) + OAuth Gmail/Outlook (личная) |
| **messenger** | `api/messenger/v1/` | `messenger` | Чат, Socket.IO поверх ASGI, presence, E2EE-ключи |

Канонический список имён — `apps.core.models.KNOWN_SERVICES` (там же зарезервировано
`conference` под SFU-стек, у которого своей Django-аппки нет).

⚠️ **`approvals` и `signoff` — не одно и то же.** `approvals` согласует собственные
`RequestInstance` из своего конструктора форм; `signoff` согласует уже существующие строки
других аппок (бюджет, договор, контрагент), не импортируя их модели. Развёрнуто —
[STRUCTURE.md §3.4–3.6](./STRUCTURE.md).

---

## Архитектурные инварианты

Это не стилевые предпочтения — каждый пункт держится тестом, middleware или обоими.

- **Межаппочный доступ — только через `apps.<x>.interface`.** Прямой импорт чужих
  `models`/`services` запрещён и ловится
  [`apps/core/tests/test_app_isolation.py`](./backend/apps/core/tests/test_app_isolation.py)
  в обычном прогоне pytest. Функция `interface.py` начинается с `require_service("<name>")`
  и возвращает только `dict`/примитивы, никогда ORM-объекты. Междоменных FK нет.
- **API-слой — `htqweb.http.api_view`, а не DRF.** Декоратор принимает `methods=`,
  `auth="jwt"|"admin_session"|None`, опциональный Pydantic-`body=`, `admin=True`.
  Конверт ошибок всегда `{"detail": ...}` (401/403/404/422/500/503) — контракт унаследован
  от FastAPI-поколения, поэтому фронтенд менять не пришлось.
- **URL монтируются сами.** Аппка объявляет `API_PREFIX = "api/<domain>/v1/"` на своём
  `AppConfig` и кладёт `urls.py` — `htqweb/urls.py` находит и монтирует её автоматически.
  Добавление домена этот файл не трогает. `APPEND_SLASH = False`, поэтому маршрут
  регистрируется в обоих написаниях (со слешем и без), если фронт может дёрнуть любое.
- **Бизнес-логика — в `apps/<domain>/services/<file>.py`.** `views.py` только парсит запрос,
  зовёт сервис и оформляет ответ. Ищите поведение в `services/`, не во вьюхах.
- **JWT: issuer `htqweb-auth`, HS256, общий `JWT_SECRET`.** `apps.users` и выпускает, и валидирует;
  остальные аппки валидируют локально, в процессе, без сетевого похода. Клеймы:
  `sub, user_id, username, email, is_staff, is_superuser, is_admin, token_type, iat, exp, iss`.
- **Любой домен выключается на лету.** `apps.core.models.ServiceStatus` (строка на аппку,
  кэш 5 c) + `ServiceGateMiddleware` (гейт по URL-префиксу) + `require_service()`
  (внутрипроцессный гейт: первая строка каждой функции `interface.py` и каждой Celery-задачи)
  + `ServiceGatedAdminMixin` (гейт в `/django-admin/`). Выключенный домен отвечает `503`
  `{"detail", "code": "service_disabled", "service"}` везде, кроме админки — там честный
  Django-`PermissionDenied`.
- **Файлы — через `apps.media_files.interface`.** `hr`, `mail`, `messenger` и аватарки `users`
  пишут только так; собственный клиент хранилища держит лишь `cms` (исторически, свой бакет).
  Второй такой заводить не нужно.
- **Postgres — напрямую.** `psycopg`, `CONN_MAX_AGE=0`, пул на
  уровне приложения. Одна схема `public`, обычные Django-имена таблиц `<app_label>_<model>`,
  обычные `makemigrations`/`migrate`. PgBouncer (`:6432`) остался в compose для хостовых утилит,
  но в путь живого запроса не входит.

Подробный разбор каждого правила с примерами кода — [backend/README.md](./backend/README.md).

---

## Разработка

### Frontend (`cd frontend`)

```bash
npm run dev                          # Vite dev-сервер :3000
npm run build                        # сборка (+ проверка бюджета бандла в postbuild)
npm run lint                         # eslint
npx tsc --noEmit -p tsconfig.json    # типизация — этим проверяем правки
npm test                             # vitest run
npx vitest run <file> -t "<name>"    # один тест
npm run test:e2e                     # playwright
```

Playwright: бинарь chromium не установлен — запускать с `{ channel: 'msedge' }`
(Edge есть на Windows-хосте).

### Backend — тесты (`cd backend`)

pytest-django гоняется против **настоящего Postgres**, не SQLite, и на отдельном хост-порту:
`:5432` занят нативным Windows-PostgreSQL, а через `:6432`/PgBouncer (transaction-пул)
не проходит `CREATE DATABASE`. Порт поднимается один раз:

```bash
docker compose -f docker-compose.test-local.yml up -d db   # публикует db на :55432
cd backend
../.venv/Scripts/python.exe -m pytest -q                                   # вся сюита
../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_x.py::test_name   # один тест
```

`DJANGO_SETTINGS_MODULE=htqweb.settings.test` и `JWT_SECRET` заданы в `pytest.ini`/`settings/test.py` —
экспортировать руками нечего. Полная история (включая `max_connections=300`) —
[backend/README-tests.md](./backend/README-tests.md).

### Backend — management-команды (`cd backend`, тот же venv)

```bash
../.venv/Scripts/python.exe manage.py makemigrations <app>
../.venv/Scripts/python.exe manage.py migrate
../.venv/Scripts/python.exe manage.py service <name> --on|--off [--message "..."]
../.venv/Scripts/python.exe manage.py ensure_buckets            # идемпотентное создание бакетов S3
../.venv/Scripts/python.exe manage.py seed_hr_demo              # демо-данные HR
../.venv/Scripts/python.exe manage.py seed_tasks_demo [--purge|--wipe|--wipe-only]
../.venv/Scripts/python.exe manage.py run_imap_idle             # live-push корпоративной почты
../.venv/Scripts/python.exe manage.py etl_<domain> [--dry-run] [--verify] [--limit N]
```

`seed_tasks_demo` заполняет всю пятиуровневую иерархию (проект → площадка → блок → роудмап →
задача) плюс объёмы, потребности в ресурсах и датированные ежедневные отчёты; ему нужен
предварительно отработавший `seed_hr_demo` (читает отделы и сотрудников через
`apps.hr.interface`). `--purge` убирает только засеянное, `--wipe` делает TRUNCATE всех таблиц
`tasks` и пересевает, восстанавливая пять системных `TaskType` из миграции `0002`.
Команды `etl_*` — разовый перелив legacy-данных при cutover, уже отработали.

### Доступ к dev-базе с хоста

`manage.py` по умолчанию идёт в `localhost:6432` (PgBouncer), чьи креды не проходят SASL с хоста.
Используйте непулированный порт — тот же сервер, та же база:

```bash
cd backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py <command>
```

(`:55432` поднимается через `docker compose -f docker-compose.test-local.yml up -d db`.
`PYTHONIOENCODING=utf-8` обязателен,
иначе русский вывод в Windows-консоли превращается в кракозябры.)

### Куда что класть (шпаргалка)

| Задача | Куда |
|---|---|
| Новый/изменённый роут API | `backend/apps/<domain>/views.py` + `urls.py` (оба написания пути) |
| Бизнес-логика | `backend/apps/<domain>/services/<file>.py` |
| Новая таблица | `backend/apps/<domain>/models.py` + `makemigrations <domain>` |
| DTO запроса/ответа | `backend/apps/<domain>/schemas.py` (Pydantic) |
| Отдать данные соседней аппке | `backend/apps/<domain>/interface.py` (первая строка — `require_service`) |
| Фоновая задача | `backend/apps/<domain>/tasks.py` (`@shared_task` + `require_service`) |
| Периодика (cron) | миграция данных для `django_celery_beat.PeriodicTask` — образец `apps/mail/migrations/0004_*` |
| Страница django-admin | `backend/apps/<domain>/admin.py` (`ModelAdmin` + `ServiceGatedAdminMixin`) |
| Новый фронтенд-роут | `frontend/src/app/routing/routeDefinitions.ts` + `pages/<Name>.tsx` |
| HTTP-вызов из фронтенда | `frontend/src/api/<domain>.ts` (axios через `client.ts`) |
| Крупная UI-фича | `frontend/src/features/<name>/` |
| Локализация | `frontend/src/locales/{ru,kz,en}/*.json` (валидатор `check-i18n.mjs`) |
| Шлюз/маршрутизация | `infra/nginx/default.conf` (prod) / `frontend/vite.config.ts` (dev) |

Добавление нового домена — пошаговый чек-лист в [backend/README.md](./backend/README.md#adding-a-new-domain-app).

---

## Порты

| Порт | Что | Профиль |
|---|---|---|
| 3000 | Vite dev-сервер | dev |
| 80 / 443 | nginx (шлюз + статика SPA) | production |
| 8000 | `backend-web` (WSGI) | всегда |
| 8001 | `backend-asgi` (ASGI: SSE + WS) | всегда |
| 5555 | Flower | всегда |
| 55432 | Postgres в контейнере (он же для pytest) | `docker-compose.test-local.yml` |
| 6432 | PgBouncer — только хостовые утилиты | `docker-compose.test-local.yml` |
| 6379 | Redis (кэш `/1`, Celery-брокер `/2`) | всегда |
| 9000 / 9001 | MinIO API / веб-консоль | всегда |
| 3001 | Grafana | всегда |
| 9090 | Prometheus (под `/prometheus`) | всегда |
| 3100 | Loki | всегда |
| 9187 / 9121 | postgres-exporter / redis-exporter | всегда |
| 4443 + 44444 (UDP/TCP) | SFU: сигнализация + медиа | всегда |
| 4433 (UDP) | WebTransport-прокси (QUIC) | всегда |
| 5000 | LibreTranslate | профиль `translation` |

---

## Наблюдаемость

- **Логи:** все backend-процессы пишут структурно в stdout → Promtail → Loki → Grafana.
  Конфиги — [infra/logging/](./infra/logging/).
- **Трассировка запросов:** заголовок `X-Request-ID`, проставляется
  `htqweb/middleware/request_id.py`.
- **Health:** `GET /health/`, `GET /health/ready/`, `GET /api/core/v1/services/` (реестр
  отключаемости). На уровне nginx — `/health` и `/health/ready`.
- **Grafana** (`:3001`, либо `/grafana/` через edge) имеет JWT-SSO: платформенные аккаунты
  входят своим access-токеном (superuser → Admin, staff → Editor). Дашборды — в папке **HTQWeb**.
- ⚠️ **Метрик самого Django пока нет.** Старая `libs/htqweb_metrics` снесена вместе с FastAPI,
  `django-prometheus` не установлен, `/metrics` не выставлен. Prometheus сейчас скрейпит 6 целей:
  себя, `postgres-exporter`, `redis-exporter`, MinIO, Loki и Grafana; job `django-backend`
  заготовлен и закомментирован в `infra/logging/prometheus/prometheus.yml`.

---

## Видеоконференции (WebRTC)

| Компонент | Где |
|---|---|
| SFU (Mediasoup) | [sfu/src/server.ts](./sfu/src/server.ts), кодеки — `sfu/media-codecs.config.json` |
| WebTransport-прокси (QUIC) | [webtransport/server.py](./webtransport/server.py) |
| Клиентский WebRTC | [frontend/src/lib/webrtc/](./frontend/src/lib/webrtc/) — `MediaEngine`, `WebRTCManager`, `SignalingClient`, `SdpMunger`, `BitrateController` |
| UI | [frontend/src/pages/ConferencePage.tsx](./frontend/src/pages/ConferencePage.tsx) |
| Конфиг ICE/SFU | `GET /api/cms/v1/conference/config` (значения — из `htqweb/settings/base.py`) |

SFU и WebTransport поднимаются только под профилем `production`; в реестре `ServiceStatus`
сервис `conference` по умолчанию **выключен**, но статический конфиг отдаётся всегда.

**Настройка:** скопируйте `sfu/.env.example` в `sfu/.env` и заполните под свой сервер.
Проверить конфигурацию: `node scripts/check-sfu-config.js`.

**Типичные проблемы:**

| Проблема | Причина / решение |
|---|---|
| Видео видно только локально | Не задан `WEBRTC_ANNOUNCED_IP` в `sfu/.env` |
| Есть аудио, нет видео | Закрыт порт 44444 (UDP+TCP) в firewall — см. `scripts/setup-firewall.ps1` |
| Работает только в LAN | Нужен TURN-сервер |
| Не работает камера | Браузеру нужен HTTPS — локальный сертификат или туннель |

**LAN поверх HTTPS/WSS.** Выпустить локальный сертификат на IP (`mkcert` или
`scripts/generate-certs.ps1`):

```powershell
mkcert -install
mkcert -cert-file .\infra\certs\cert.pem -key-file .\infra\certs\key.pem localhost 127.0.0.1 ::1 <ВАШ_LAN_IP>
```

и поднять SFU в защищённом режиме (`SIGNALING_REQUIRE_TLS=true`, `TLS_CERT`, `TLS_KEY`).
Туннель наружу — `scripts/start-sfu-tunnel.ps1`, после чего обновить signaling-URL в
`frontend/.env`.

**Показать стенд человеку снаружи** (проверить конференцию с чужой машины) —
`scripts/start-public-test.ps1`, подробности в
[docs/TUNNEL_SETUP.md](./docs/TUNNEL_SETUP.md). Туннеля два, потому что ни один
HTTP-туннель не несёт UDP: Cloudflare везёт сигналинг, bore.pub — медиа поверх
TCP. Скрипт печатает публичную ссылку и по Ctrl+C возвращает стенд в локальное
состояние.

```powershell
docker compose -f docker-compose.test-env.yml up -d      # стек с БД из .env
.\scripts\start-public-test.ps1 -GuestEmail guest@example.com
```

⚠️ Туннель открывает наружу **весь** стенд, включая `/django-admin/` с
сид-аккаунтом. Смените пароль перед сеансом и гасите туннель сразу после.

---

## Документация

| Документ | О чём |
|---|---|
| [STRUCTURE.md](./STRUCTURE.md) | ⭐ Навигационная карта: каждый каталог, анатомия аппки, где живёт каждая забота (RU, подробно) |
| [API.md](./API.md) | ⭐ Таблица маршрутизации nginx, контракт авторизации, эндпойнты по доменам |
| [backend/README.md](./backend/README.md) | ⭐ Анатомия Django-аппки, правила `interface`/`api_view`, как добавить домен |
| [backend/README-tests.md](./backend/README-tests.md) | Как поднять тестовый Postgres и гонять pytest |
| [CLAUDE.md](./CLAUDE.md) | Ориентировка для ИИ-агентов, работающих с репозиторием |
| [PLAN.md](./PLAN.md) | Журнал завершённой обратной миграции |
| [docs/architecture.md](./docs/architecture.md) | Архитектурные решения — **частично устарел** (говорит про DRF ViewSets и каталог `backend/tasks/`, которых нет); фон, а не источник истины |

Материалы в `docs/audit-2026-04-28/`, `docs/alerting-2026-04-28.md`,
`docs/dependency-audit-2026-04-28.md` относятся к FastAPI-эпохе и под Django не обновлялись.

---

## Известные хвосты

- **`/sqladmin/` и `/mongo-admin` не существуют.** Несколько мест во фронтенде
  (`pages/AdminUsers.tsx`, `components/profile/ProfileSidebar.tsx`,
  `components/admin/UserEditDialog.tsx`, `App.tsx`) всё ещё на них ссылаются — это не «сервис
  выключен», а честный 404. Администрирование БД — `/django-admin/`.
- **`POST /api/users/v1/admin-session/login|logout` живы, но потребителя у них нет.** Cookie
  `admin_session` ставилась ради sqladmin; `/django-admin/` использует обычную Django-сессию.
- **Корневой `.env.example` устарел** — описывает MongoDB, AdminJS, `SERVICE_JWT_SECRET`,
  бакеты на сервис и `services/<n>/.env`, которых больше нет. Актуальный набор переменных —
  якорь `x-django-env` в [docker-compose.yml](./docker-compose.yml).
- **`frontend/README.md`** — неотредактированный шаблон генератора, содержательной информации
  не несёт.
- **`scripts/generate-monitoring-traffic.sh`** бьёт по портам микросервисов (`:8005`–`:8012`) —
  против текущего `backend-web:8000` не работает без переписывания.
- **`apps.media_files` — общая точка отказа для файлов** `hr`/`mail`/`messenger` и аватарок
  `users`. Выключенный `media` всплывёт у соседей как `ServiceDisabled`/503 — смотрите поле
  `service` в JSON-конверте, прежде чем искать баг в вызывающей аппке.
- **Вложения писем подключены не полностью:** `EmailAttachment` остаётся metadata-only, байты
  ни один роут `apps.mail` не принимает (так было и в FastAPI-исходнике, это не регрессия).
