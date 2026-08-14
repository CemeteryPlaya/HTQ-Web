# Инфраструктура и эксплуатация

Как платформа поднимается, чем разводится трафик, что за чем следит.

---

## 1. Ровно три compose-файла, и они самодостаточны

Главное правило: **никаких цепочек `-f a -f b`.** Каждый файл описывает стек
целиком.

| Файл | Назначение | База данных |
|---|---|---|
| `docker-compose.yml` | **Прод**: фронт собран в статику, gunicorn, nginx/certbot под профилем `production` | из `.env` |
| `docker-compose.test-local.yml` | Тестовый стек: Vite с горячей перезагрузкой, `DEBUG` | Postgres **в контейнере** |
| `docker-compose.test-env.yml` | Тестовый стек, но база боевая | из `.env` |

```bash
docker compose -f docker-compose.test-local.yml up -d --build   # обычная разработка
docker compose -f docker-compose.test-env.yml up -d --build     # база из .env
docker compose up -d --build                                    # прод
```

⚠️ **Все три публикуют одни и те же порты хоста** — одновременно поднимается
только один.

### Цена самодостаточности

Файлы **намеренно не наследуют** друг друга. Поэтому правка общего сервиса
повторяется во всех трёх, и это легко забыть.

Привычка: после правки любого compose-файла — `git diff docker-compose*.yml`.

### Имена контейнеров

Каждый файл объявляет своё имя проекта, поэтому контейнеры называются
по-разному:

| Стек | Префикс |
|---|---|
| Прод | `htq-web-<сервис>-1` (от имени каталога) |
| test-local | `htqweb-local-<сервис>-1` |
| test-env | `htqweb-env-<сервис>-1` |

Тома тоже раздельные — стеки не мешают друг другу.

### `DB_HOST` в test-local прибит гвоздями

В `docker-compose.test-local.yml` стоит `DB_HOST: db` **без подстановки из
`.env`**, и это намеренно: иначе «локальный» стек ушёл бы работать в
боевую базу.

---

## 2. Процессы

Все из одного образа (`backend/Dockerfile`), различаются командой:

| Процесс | Команда | Отвечает |
|---|---|---|
| `backend-web` | `gunicorn htqweb.wsgi` | `/api/*`, `/django-admin/`, статика |
| `backend-asgi` | `uvicorn htqweb.asgi` | SSE `/api/requests/v1/stream`, все `/ws/` |
| `backend-worker` | `celery worker` | Фоновые задачи |
| `backend-beat` | `celery beat` (расписание в БД) | Планировщик |
| `flower` | `celery flower --port=5555` | Панель по задачам |

**Миграции и сид админа делает только `backend-web`**, под флагом
`RUN_MIGRATIONS` (по умолчанию `1`). На боевой базе флаг часто выключен —
тогда миграции применяются вручную.

Сидовая учётка — `admin` / `admin12345`. Меняйте пароль на всём, что смотрит
наружу.

---

## 3. nginx

`infra/nginx/default.conf` — **единственный авторитетный конфиг шлюза**
(пустой каталог `nginx/` в корне игнорируйте).

Два upstream:

| Upstream | Куда | Что |
|---|---|---|
| `backend` | gunicorn | Всё остальное |
| `backend_asgi` | uvicorn | SSE и `/ws/` |

Причина деления: WSGI синхронный и не держит долгоживущие соединения.

Пути входа, обновления токена и регистрации вынесены отдельными правилами с
ограничением частоты (`limit_req zone=api_auth burst=2 nodelay`) — защита от
подбора пароля. Обе формы пути, со слэшем и без, потому что
`APPEND_SLASH = False`.

---

## 4. Конференция

`sfu` (mediasoup: сигналинг `:4443`, медиа `:44444/udp+tcp`) и `webtransport`
(мост QUIC `:4433/udp`) **стартуют вместе со стеком** и в dev, и в проде — под
профилем `production` они больше не сидят.

Подробности сценария — [flows/conference-sfu.md](flows/conference-sfu.md).
Коротко о том, что ломает стенд:

- `WEBRTC_ANNOUNCED_IP` обязателен, иначе SFU падает на старте намеренно;
- `VITE_SFU_WS_TARGET: ws://sfu:4443` обязателен в тестовых стеках;
- флаг сервиса `conference` в реестре должен быть включён.

---

## 5. Хранилища

| Сервис | Роль |
|---|---|
| Postgres | Основная база; Django ходит **напрямую** |
| Redis | Кэш и брокер Celery |
| MinIO | Объектное хранилище (S3-совместимое) |
| PgBouncer `:6432` | **Только** для хостовых утилит, не в пути запроса |

Разбор — [03-data-layer.md](03-data-layer.md).

---

## 6. Мониторинг

`infra/logging/`. Grafana (`:3001` или `/grafana/` через шлюз) держит SSO по
платформенному JWT: superuser → Admin, staff → Editor. Дашборды в папке
**HTQWeb**.

### ⚠️ Prometheus не собирает метрики бэкенда

Сейчас в `infra/logging/prometheus/prometheus.yml` шесть целей: сам
Prometheus, `postgres-exporter`, `redis-exporter`, MinIO, Loki и Grafana.

**Django-бэкенд `/metrics` не отдаёт.** Задание `django-backend` в конфиге
**написано, но закомментировано** (`prometheus.yml:20-24`) — ждёт установки
`django-prometheus`. Старая библиотека метрик удалена вместе с
FastAPI-сервисами.

Не удивляйтесь пустым графикам по приложению: их пока нечем наполнить.

Ещё одна мина: `scripts/generate-monitoring-traffic.sh` предшествует
переезду и до сих пор обращается к портам старых сервисов (`:8005`–`:8012`).
Против нынешнего бэкенда он не генерирует ничего.

---

## 7. Проверка стенда снаружи

`scripts/start-public-test.ps1` плюс [docs/TUNNEL_SETUP.md](../TUNNEL_SETUP.md).

Два туннеля, потому что ни один HTTP-туннель не несёт UDP: Cloudflare для
сигналинга, bore.pub для медиа по TCP.

⚠️ Туннель открывает наружу **весь стенд**, включая `/django-admin/` с
сид-аккаунтом. Меняйте пароль и гасите туннель сразу после проверки.

---

## 8. Управляющие команды

Из `backend/`:

```bash
./.venv/Scripts/python.exe manage.py migrate
./.venv/Scripts/python.exe manage.py service <имя> --on|--off [--message "..."]
./.venv/Scripts/python.exe manage.py mail_check [--mailbox ADDR]
./.venv/Scripts/python.exe manage.py seed_tasks_demo [--purge|--wipe]
./.venv/Scripts/python.exe manage.py create_user --email ... --name ...
```

`service` — рубильник домена (см. [01-conventions.md](01-conventions.md),
раздел 5). `mail_check` — первое, что запускают при проблемах с почтой
(см. [flows/mail-imap-to-ui.md](flows/mail-imap-to-ui.md)).

`seed_tasks_demo` наполняет всю пятиуровневую иерархию демо-данными, но
**требует, чтобы сначала отработал `seed_hr_demo`**: он читает отделы и
сотрудников через `apps.hr.interface`.

### Доступ к базе с хоста

`manage.py` по умолчанию целится в PgBouncer, чьи учётные данные с хоста не
проходят. Указывайте беспуловый порт явно — рецепт в
[03-data-layer.md](03-data-layer.md), раздел 8.

---

## 9. Что ломается чаще всего

**Подняли два стека сразу.** Порты конфликтуют.

**Правка одного compose-файла из трёх.** Остальные разъедутся молча.

**`docker restart` контейнера БД.** Пересоздаёт его без публикации порта.

**Ждут метрик приложения в Grafana.** Их нет — см. раздел 6.

**Забыли `RUN_MIGRATIONS` на боевой базе.** Схема не обновится, а процессы
поднимутся.
