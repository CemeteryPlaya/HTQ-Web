import logging
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


SECRET_KEY = env("DJANGO_SECRET_KEY", env("JWT_SECRET", "change-me"))
DEBUG = False
ALLOWED_HOSTS = ["*"]           # локальный запуск; деплой — вне скоупа
APPEND_SLASH = False            # пути повторяют API.md буквально, без редиректов

# ── Среда и политика fallback'ов ───────────────────────────────────────────
# Одна ось на три рантайма: тот же HTQ_ENV читают фронт (VITE_HTQ_ENV) и SFU.
#
#   production  — прод;
#   staging     — тестовая среда, код ведёт себя РОВНО как на проде;
#   development — машина разработчика и pytest.
#
# Из неё выводится режим подмен (htqweb/fallback.py): на проде и стейдже
# fallback срабатывает молча для пользователя, но громко в лог и метрику;
# у разработчика он запрещён и вместо подмены летит исключение.
#
# Явная FALLBACK_MODE перебивает вывод из среды — чтобы включить strict на
# стейдже на час, не пересобирая среду, и наоборот: разово ослабить его
# локально, когда чинишь что-то другое.
HTQ_ENV = env("HTQ_ENV", "production")


def fallback_mode_for(environment: str) -> str:
    """``"log"`` | ``"strict"`` для среды. Переопределяется FALLBACK_MODE."""
    override = env("FALLBACK_MODE")
    if override:
        return override
    return "strict" if environment == "development" else "log"


FALLBACK_MODE = fallback_mode_for(HTQ_ENV)

INSTALLED_APPS = [
    # Вместо "django.contrib.admin" — свой AdminConfig: он поднимает
    # htqweb.admin_site.HTQAdminSite (брендинг + порядок разделов) как
    # admin.site, поэтому @admin.register во всех аппках работает как раньше.
    "htqweb.apps.HTQAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_results",
    "django_celery_beat",
    "django_json_widget",
    # Наблюдаемость: HTTP-метрики + движки-обёртки для БД и кэша.
    # Сам по себе роут не заводит — /metrics отдаёт apps.core.views.metrics,
    # потому что под gunicorn'ом нужен multiprocess-реестр (см. там же).
    "django_prometheus",
    "apps.core",
    "apps.users",
    "apps.cms",
    "apps.media_files",
    # Доменные аппки миграции — скаффолд prep 4.0 (PLAN.md §5). Пустые
    # (модели/роуты/задачи приходят в их фазах §6), но уже установлены и
    # отключаемы: URL-автодискавери монтирует их по AppConfig.API_PREFIX,
    # а ServiceGateMiddleware гейтит по префиксу. Регистрируются одной
    # пачкой, чтобы фазы не правили INSTALLED_APPS (точка конфликта потоков).
    "apps.hr",          # Поток A · фаза 6 · /api/hr/v1/
    "apps.mail",        # Поток A · фаза 7 · /api/email/v1/
    "apps.messenger",   # Поток A · фаза 8 · /api/messenger/v1/
    "apps.tasks",       # Поток B · фаза 4 · /api/tasks/v1/
    "apps.approvals",   # Поток B · фаза 5 · /api/requests/v1/
    # Домен, появившийся уже после обратной миграции (не из FastAPI-поколения):
    # бюджеты, реестр контрагентов, договоры. /api/contracts/v1/
    "apps.contracts",
    # Журнал видеоконференций: встречи, записи, протокол. /api/conference/v1/
    # Имя `conference` уже было в KNOWN_SERVICES — оно резервировалось под
    # SFU-стек, у которого не было своей Django-аппки. Теперь есть.
    "apps.conference",
    # Универсальный движок согласования. /api/signoff/v1/
    # НЕ путать с apps.approvals (/api/requests/v1/): та аппка — конструктор
    # динамических форм, её единица согласования — собственная заявка с JSON
    # значениями полей, и навести её на существующую строку чужой таблицы
    # нельзя. signoff согласует ЛЮБУЮ модель, унаследовавшую Approvable.
    # Позиция в списке роли не играет: Django загружает модели ВСЕХ аппок
    # до первого ready(), поэтому предметная аппка вправе регистрировать
    # свой тип независимо от того, стоит она здесь выше или ниже.
    "apps.signoff",
]

MIDDLEWARE = [
    # Prometheus-пара обязана обнимать ВЕСЬ список: Before — первой, After —
    # последней. Иначе замеряется не полное время запроса, а только то, что
    # осталось внутри их «скобок», и латентность систематически занижается.
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "htqweb.middleware.request_id.RequestIDMiddleware",
    "htqweb.middleware.service_gate.ServiceGateMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise отдаёт собранную (collectstatic) статику прямо из WSGI/ASGI-процесса
    # — gunicorn/uvicorn сами статику не отдают. Должен идти СРАЗУ после Security.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Снимает CSRF с /api/ (JWT-stateless) ДО CsrfViewMiddleware — иначе
    # метод-диспетчеры (не @csrf_exempt) отдают 403-CSRF на живых POST/PUT/…
    # (в test Client CSRF отключён, поэтому не ловилось). django-admin свой
    # CSRF сохраняет. См. htqweb/middleware/api_csrf_exempt.py.
    "htqweb.middleware.api_csrf_exempt.ApiCsrfExemptMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "htqweb.urls"
ASGI_APPLICATION = "htqweb.asgi.application"
WSGI_APPLICATION = "htqweb.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    # Проектные шаблоны ищутся ДО аппочных (APP_DIRS ниже), поэтому
    # templates/admin/base_site.html перекрывает стоковый шаблон админки —
    # это и подключает фирменную тему (см. static/admin/htqweb.css).
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# Локальная разработка: БД проекта с хоста доступна через PgBouncer :6432
# (хостовый :5432 — нативный Windows-Postgres, см. CLAUDE.md). За PgBouncer
# в transaction-режиме обязательны две строки ниже.
DATABASES = {
    "default": {
        # Обёртка django-prometheus над штатным postgresql-бэкендом: тонкий
        # подкласс, поведение и SQL не меняет, но считает запросы, ошибки и
        # время соединений (django_db_*). Подменять строку на штатную
        # безопасно — метрики БД просто исчезнут.
        "ENGINE": "django_prometheus.db.backends.postgresql",
        "NAME": env("DB_NAME", "htqweb"),
        "USER": env("DB_USER", "htqweb"),
        "PASSWORD": env("DB_PASSWORD", "change-me"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "6432"),
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "CONN_MAX_AGE": 0,
    }
}

AUTH_USER_MODEL = "users.User"

# Fail-open: ServiceGateMiddleware дёргает кэш на КАЖДЫЙ запрос — недоступный
# Redis не должен ронять весь трафик платформы (в отличие от старого стека,
# там кэш не стоял в критическом пути роутинга). apps/core/services.py
# дополнительно оборачивает cache.get/set в try/except как вторую линию.
DJANGO_REDIS_IGNORE_EXCEPTIONS = True

CACHES = {
    "default": {
        # Обёртка django-prometheus над django_redis: даёт попадания/промахи
        # (django_cache_get_hits_total / _misses_total). Подкласс того же
        # RedisCache, поэтому IGNORE_EXCEPTIONS и всё остальное работает как
        # раньше.
        "BACKEND": "django_prometheus.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://localhost:6379/8"),
        "OPTIONS": {"IGNORE_EXCEPTIONS": True},
    }
}

# ── Celery (worker stack — replaces django-q2, customer decision 2026-07-19)
# broker=Redis, result backend=django-celery-results (DB), beat scheduler=
# django-celery-beat DatabaseScheduler. Uses its own Redis DB (/9) so the
# broker traffic doesn't share a logical DB with the cache (/8).
CELERY_BROKER_URL = env("CELERY_BROKER_URL", env("REDIS_URL", "redis://localhost:6379/9"))
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
# Обработка записей конференций уходит в СВОЮ очередь и к своему воркеру
# (backend-media-worker, образ backend/Dockerfile.media с ffmpeg и Whisper).
# Два повода развести: сборка часового видео и распознавание занимают десятки
# минут — в общей очереди они задержали бы отправку почты и пересчёт метрик;
# и наоборот, ставить ffmpeg с ctranslate2 в общий образ значит утяжелить все
# пять backend-контейнеров ради задач, которые выполняет один.
#
# Общий backend-worker запущен без -Q (docker-compose.yml), то есть слушает
# только очередь celery и этих задач не увидит — что и требуется.
CONFERENCE_MEDIA_QUEUE = "conference_media"
CELERY_TASK_ROUTES = {
    "apps.conference.tasks.process_session_recording": {"queue": CONFERENCE_MEDIA_QUEUE},
    "apps.conference.tasks.transcribe_session": {"queue": CONFERENCE_MEDIA_QUEUE},
}

# ── JWT-контракт платформы (API.md §Authentication) ─────────────────────────
JWT_SECRET = env("JWT_SECRET", "change-me")
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "htqweb-auth"
JWT_ACCESS_TTL_MIN = int(env("JWT_ACCESS_TTL_MIN", "60"))
JWT_REFRESH_TTL_DAYS = int(env("JWT_REFRESH_TTL_DAYS", "7"))

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_TZ = True
CELERY_TIMEZONE = TIME_ZONE
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Своя статика проекта (фирменная тема админки). collectstatic сливает её
# со статикой аппок в STATIC_ROOT — см. docker-entrypoint.sh (RUN_BOOTSTRAP=1).
STATICFILES_DIRS = [BASE_DIR / "static"]
# WhiteNoise: сжатие + manifest-хэши собранной статики (django-admin CSS/JS). S3/медиа
# идут через htqweb.storage напрямую (не через Django default_storage), поэтому
# default-сторедж — обычная ФС. В dev manifest отключён (см. settings/dev.py), иначе
# runserver+DEBUG падает на {% static %} без предварительного collectstatic.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── LOGGING (P2.1) — единый вывод в stdout (promtail собирает логи контейнеров).
# До этого LOGGING не был сконфигурирован — работали Django-дефолты. Уровни по
# аппкам через env (LOG_LEVEL/APP_LOG_LEVEL); request_id пишется в заголовок
# ответа RequestIDMiddleware'ом, привязка его к строкам лога — отдельный follow-up
# (нужен logging-фильтр поверх contextvar). django.request/db.backends приглушены.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "app": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "app"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    # Логгеры БЕЗ собственных handlers + propagate=True (дефолт): записи идут в
    # единственный console-handler root'а (без дублей), а pytest caplog (слушает
    # root) их видит. Здесь — только уровни.
    "loggers": {
        "django": {"level": "INFO"},
        "django.request": {"level": "WARNING"},
        "django.db.backends": {"level": "WARNING"},
        "apps": {"level": env("APP_LOG_LEVEL", "INFO")},
        "htqweb": {"level": env("APP_LOG_LEVEL", "INFO")},
        # Fallback'и — свой уровень, отдельно от остальных htqweb.*: строки
        # «FALLBACK …» приглушают или, наоборот, опускают до INFO (штатные
        # деградации) независимо от того, насколько разговорчив остальной код.
        "htqweb.fallback": {"level": env("FALLBACK_LOG_LEVEL", "INFO")},
    },
}

# ── Object storage (S3/MinIO) — htqweb/storage/, ported from
# services/cms/app/services/s3_storage.py + signed_url.py. Names/defaults
# match docker-compose.yml's cms-service environment block byte-for-byte so
# both stacks read the same env during the Strangler Fig transition — with
# one intentional exception: S3_PUBLIC_ENDPOINT has no compose default (cms
# doesn't set it there either) and stays "" here too, which S3Storage treats
# as "fall back to S3_ENDPOINT" (see s3.py's `public_endpoint or endpoint`).
STORAGE_BACKEND = env("STORAGE_BACKEND", "s3")  # local | s3
S3_BUCKET = env("S3_BUCKET", "htqweb-cms")
# Media bucket — avatars (Task 2.3, decision Р3) are written directly via
# htqweb.storage instead of S2S-forwarding to media-service, so they need
# their own bucket (media-service's own bucket, not cms's).
MEDIA_S3_BUCKET = env("MEDIA_S3_BUCKET", "htqweb-media")
S3_ENDPOINT = env("S3_ENDPOINT", "http://minio:9000")
S3_PUBLIC_ENDPOINT = env("S3_PUBLIC_ENDPOINT", "")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = env("S3_SECRET_KEY", "minioadmin")
S3_REGION = env("S3_REGION", "us-east-1")
S3_USE_PATH_STYLE = env("S3_USE_PATH_STYLE", "true").lower() in ("1", "true", "yes")
S3_PRESIGNED_URL_TTL = int(env("S3_PRESIGNED_URL_TTL", "3600"))
CMS_LOCAL_STORAGE_DIR = env("CMS_LOCAL_STORAGE_DIR", str(BASE_DIR / "data" / "cms"))

NEWS_SIGNED_URL_SECRET = env("NEWS_SIGNED_URL_SECRET", "change-me-news-signed-secret")
NEWS_SIGNED_URL_TTL = int(env("NEWS_SIGNED_URL_TTL", "3600"))

# ── Админ-панель инфраструктуры — GET /api/admin/v1/infrastructure/ ─────────
# Порт services/admin/app/core/settings.py (admin-сервис снесён при cutover'е,
# см. apps/core/infrastructure.py). Читает уже существующие DATABASES/CACHES/
# S3_* — свои тут только «человеческие» ссылки и имя окружения.
SERVICE_ENV = env("SERVICE_ENV", "development")
# Ссылка «панель БД». У источника это был sqladmin снесённого admin-сервиса;
# в монолите ту же роль играет родная админка Django.
DB_ADMIN_URL = env("DB_ADMIN_URL", "/django-admin/")
MINIO_CONSOLE_URL = env("MINIO_CONSOLE_URL", "http://localhost:9001")

# ── Conference (SFU) runtime config — GET /api/cms/v1/conference/config ─────
# Ported defaults from services/cms/app/data/conference.yaml (FastAPI
# cms-service); отдаётся ConferencePage.tsx как рантайм-конфиг WebRTC.
#
# CONFERENCE_SFU_URL по умолчанию ПУСТ, и это осознанно: и nginx (prod), и
# Vite-прокси (dev) отдают сигналинг на том же origin, что и страницу, а
# фронт при пустом URL сам собирает ws(s)://<origin>/ws/sfu/. Прежний дефолт
# ws://sfu:4443 — имя внутри docker-сети, из браузера оно не резолвится.
# Задавайте явно только если SFU живёт на отдельном хосте/порту.
CONFERENCE_SFU_URL = env("CONFERENCE_SFU_URL", "")

# ── Приглашения в конференцию ──────────────────────────────────────────────
# Время жизни ГОСТЕВОГО токена (htqweb/authn/jwt.py::issue_guest_token) —
# сколько внешний участник может находиться в звонке после входа по ссылке.
# 4 часа: дольше любого совещания, но не бессрочно; сама ссылка живёт своим
# сроком (CONFERENCE_INVITE_TTL_HOURS) и может быть отозвана.
CONFERENCE_GUEST_TOKEN_TTL_MIN = int(env("CONFERENCE_GUEST_TOKEN_TTL_MIN", "240"))
# Срок жизни ссылки-приглашения по умолчанию.
CONFERENCE_INVITE_TTL_HOURS = int(env("CONFERENCE_INVITE_TTL_HOURS", "168"))
# Публичный адрес платформы для сборки ссылок в письмах и сообщениях: там,
# в отличие от браузера, origin взять неоткуда.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "")
CONFERENCE_SFU_PATH = env("CONFERENCE_SFU_PATH", "/ws/sfu/")
# ICE-серверы, которые бэкенд отдаёт фронту в GET /api/cms/v1/conference/config.
#
# STUN лишь сообщает клиенту его внешний адрес. Когда обе стороны за
# СИММЕТРИЧНЫМ NAT (мобильный интернет, корпоративные сети со строгим
# firewall), прямой путь для медиа не находится, и связь не устанавливается
# между разными сетями — при том что внутри одной сети всё работает. Это и
# есть типовой «чёрный экран у части участников». Лечится только TURN:
# он ретранслирует медиа через себя, когда прямой путь невозможен.
#
# TURN_URLS — через запятую, формат WebRTC:
#   turn:turn.example.com:3478?transport=udp,turns:turn.example.com:5349
# Пусто — остаются только публичные STUN, и это НЕ конфигурация для прода.
_TURN_URLS = [u.strip() for u in env("TURN_URLS", "").split(",") if u.strip()]
_TURN_USERNAME = env("TURN_USERNAME", "")
_TURN_CREDENTIAL = env("TURN_CREDENTIAL", "")

CONFERENCE_ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]
if _TURN_URLS:
    # Одной записью со списком urls, а не по записи на URL: браузер сам
    # переберёт транспорты внутри одной записи с общими кредами.
    CONFERENCE_ICE_SERVERS.append({
        "urls": _TURN_URLS if len(_TURN_URLS) > 1 else _TURN_URLS[0],
        "username": _TURN_USERNAME or None,
        "credential": _TURN_CREDENTIAL or None,
    })

# ── WebTransport (QUIC) сигналинг — предпочтительный транспорт ──────────────
# Мост webtransport/ (aioquic, UDP :4433) принимает WebTransport-сессию и
# перекладывает те же JSON-сообщения в WebSocket SFU. Пустой URL = мост не
# развёрнут: ConferencePage.tsx молча остаётся на WebSocket.
#
# Хэши сертификата нужны ТОЛЬКО для самоподписанного сертификата (dev):
# браузер принимает такой QUIC-эндпоинт лишь через serverCertificateHashes.
# Мост пишет DER SHA-256 в certs/cert.sha256 при каждом старте — путь к
# этому файлу и кладём в CONFERENCE_WT_CERT_HASH_FILE, чтобы отпечаток не
# приходилось копировать руками. С сертификатом от настоящего CA (certbot)
# оба параметра оставляют пустыми.
CONFERENCE_WT_URL = env("CONFERENCE_WT_URL", "")
CONFERENCE_WT_CERT_HASHES = env("CONFERENCE_WT_CERT_HASHES", "")
CONFERENCE_WT_CERT_HASH_FILE = env("CONFERENCE_WT_CERT_HASH_FILE", "")

# ── Запись конференций, история и протокол (apps.conference) ────────────────
# Запись ведётся ПОУЧАСТНИКОВО: SFU вешает PlainTransport на каждого
# producer'а и ремуксит поток в файл через ffmpeg (-c copy, без
# перекодирования). Сведение в одно видео и распознавание речи идут потом, в
# отдельном Celery-воркере, и на живой звонок не влияют.
CONFERENCE_RECORDING_ENABLED = env("CONFERENCE_RECORDING_ENABLED", "true").lower() in (
    "1", "true", "yes")
# Сколько живёт МЕДИА встречи. Строка истории и текстовый протокол переживают
# этот срок — стирается только видео/аудио (решение заказчика).
CONFERENCE_RETENTION_DAYS = int(env("CONFERENCE_RETENTION_DAYS", "25"))
# Общий секрет для канала SFU → Django (/api/conference/v1/internal/*).
# JWT здесь не годится: у SFU нет пользователя, от чьего имени ходить.
CONFERENCE_INTERNAL_TOKEN = env("CONFERENCE_INTERNAL_TOKEN", "")
# Том с сырыми дорожками, общий у контейнеров sfu и backend-media-worker.
CONFERENCE_RAW_DIR = env("CONFERENCE_RAW_DIR", "/recordings")
# Пусто = класть записи в MEDIA_S3_BUCKET под префиксом conference/.
# Третий бакет намеренно не заводим (см. ensure_buckets.py), но отдельное имя
# можно задать переменной, если прод захочет развести их по политикам жизни.
CONFERENCE_S3_BUCKET = env("CONFERENCE_S3_BUCKET", "") or MEDIA_S3_BUCKET
# Через сколько часов молчания считать незакрытую сессию осиротевшей (SFU
# упал, не прислав finish) и закрыть её принудительно.
CONFERENCE_ORPHAN_HOURS = int(env("CONFERENCE_ORPHAN_HOURS", "6"))
# Сколько плиток помещается в сведённое видео. Дорожки сверх этого числа в
# картинку не попадают, но в протоколе и в аудиомиксе участвуют полностью.
CONFERENCE_MAX_TILES = int(env("CONFERENCE_MAX_TILES", "9"))
# Модель распознавания. medium — компромисс: русский держит уверенно, часовая
# встреча на CPU считается 20–40 минут фоном. int8 обязателен на CPU, иначе
# ctranslate2 съедает памяти втрое.
WHISPER_MODEL = env("WHISPER_MODEL", "medium")
WHISPER_DEVICE = env("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = env("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_LANGUAGE = env("WHISPER_LANGUAGE", "ru")

# ── cms background tasks (apps/cms/tasks.py) — ported defaults from
# services/cms/app/core/settings.py + .env.example, byte-for-byte, so both
# stacks read the same env during the Strangler Fig transition.
# TRANSLATION_API_KEY empty (default) => translate_news no-ops (logs and
# returns) instead of calling DeepL — same behaviour as the FastAPI original.
TRANSLATION_API_KEY = env("TRANSLATION_API_KEY", "")
TRANSLATION_PROVIDER = env("TRANSLATION_PROVIDER", "deepl")
TRANSLATION_API_BASE = env("TRANSLATION_API_BASE", "https://api-free.deepl.com")

# ── outbound e-mail (P1.5, 2026-07-22 audit spec) ────────────────────────
# ``notify_admins_on_contact_request`` (apps/cms/tasks.py) used to POST to
# ``settings.EMAIL_SERVICE_URL`` — the FastAPI email-service, deleted with
# the rest of ``services/`` at cutover, which left the default ("") no-op'ing
# forever. Replaced with Django's built-in ``django.core.mail.mail_admins``,
# which reads ``ADMINS``/``SERVER_EMAIL``/``EMAIL_BACKEND`` below. SMTP
# target is mailcow; ``EMAIL_HOST_*`` stay blank by default so an
# unconfigured environment falls back to the console backend instead of
# failing to connect.
def _parse_admins(raw: str) -> list[tuple[str, str]]:
    """``DJANGO_ADMINS`` env var → Django's ``ADMINS`` list of
    ``(name, email)`` pairs. Comma-separated entries, each either
    ``"Имя <mail@example.com>"`` or a bare ``mail@example.com`` (bare
    addresses use the address itself as the display name — Django's tuple
    shape requires one). Default ("") → empty list, i.e. no admin emails
    configured and ``mail_admins`` silently no-ops (matches the old
    blank-``EMAIL_SERVICE_URL`` no-op behaviour when nobody has set anything
    up yet)."""
    admins: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.match(r"^(?P<name>.*)<(?P<email>[^<>]+)>$", chunk)
        if match:
            email = match.group("email").strip()
            name = match.group("name").strip().strip('"') or email
        else:
            name = email = chunk
        admins.append((name, email))
    return admins


ADMINS = _parse_admins(env("DJANGO_ADMINS", ""))
MANAGERS = ADMINS

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "noreply@htq.group")
# mail_admins() sends From=SERVER_EMAIL (not DEFAULT_FROM_EMAIL) — keep them
# in sync by default so a single env var covers both unless overridden.
SERVER_EMAIL = env("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env("EMAIL_USE_TLS", "true").lower() in ("1", "true", "yes")

# ── корпоративная почта (apps/mail) ──────────────────────────────────────
# До этого блока НИ ОДНОЙ MAILCOW_*/IMAP_* настройки в settings не было:
# apps/mail читал их через ``getattr(settings, "MAILCOW_DOMAIN", "")``, всегда
# получал "" и падал 500 "MAILCOW_DOMAIN not configured" на POST
# /api/email/v1/mailboxes/ — то самое "невозможно добавить почтовый ящик".
# Дефолты пустые НАМЕРЕННО: неконфигурированное окружение (в т.ч. CI) ведёт
# себя ровно как раньше, включая тот же 500 (обратная совместимость,
# apps/mail/tests/test_mailboxes_api.py::test_create_requires_mailcow_domain_
# configured опирается на это).

def _flag(name: str, default: str) -> bool:
    return env(name, default).strip().lower() in ("1", "true", "yes", "on")


def _mail_domain(name: str, default: str = "") -> str:
    """Почтовый домен из env, приведённый к каноническому виду.

    Значение подставляется в адрес как ``f"{local}@{domain}"``, поэтому любой
    лишний символ давал бы молча битые ящики (``i.ivanov@@htq.group``), и
    заметили бы это уже на почтовом сервере. Типовые опечатки лечатся здесь:

      ``ЛИДЕР@htq.group``           → ``htq.group``   (ведущая @)
      `` htq.group``                → ``htq.group``   (пробел после ``=``,
                                                       Compose его сохраняет)
      ``https://mail.htq.group/``   → ``mail.htq.group`` (перепутано с
                                                       MAILCOW_API_URL)

    Последний случай нормализуется, но НЕ угадывается: ``mail.htq.group`` —
    это имя хоста веб-панели, а ящики почти всегда живут на ``htq.group``.
    Поэтому вдобавок пишется предупреждение в лог — молча подставить домен,
    которого админ не имел в виду, хуже, чем сказать об этом.
    """
    raw = env(name, default).strip()
    if not raw:
        return ""

    normalized = raw
    looked_like_url = False
    for scheme in ("https://", "http://"):
        if normalized.lower().startswith(scheme):
            normalized, looked_like_url = normalized[len(scheme):], True
    normalized = normalized.split("/")[0].strip()
    normalized = normalized.lstrip("@").strip()
    # ``user@host`` — админ вписал адрес целиком вместо домена.
    if "@" in normalized:
        normalized = normalized.rsplit("@", 1)[-1].strip()
    normalized = normalized.rstrip(".").lower()

    if normalized != raw:
        logging.getLogger(__name__).warning(
            "%s=%r приведено к %r. Ожидается ГОЛЫЙ почтовый домен (htq.group); "
            "адрес панели/API задаётся отдельно в MAILCOW_API_URL.%s",
            name, raw, normalized,
            " Похоже, сюда попал URL — проверьте, что домен ящиков именно такой."
            if looked_like_url else "",
        )
    return normalized


# Домен, в котором заводятся корпоративные ящики (``i.ivanov@<домен>``).
# MAILCOW_DOMAIN — историческое имя (его читает mailbox_service);
# CORPORATE_MAIL_DOMAIN — нейтральный синоним для не-Mailcow серверов.
CORPORATE_MAIL_DOMAIN = _mail_domain("CORPORATE_MAIL_DOMAIN")
MAILCOW_DOMAIN = _mail_domain("MAILCOW_DOMAIN", CORPORATE_MAIL_DOMAIN)
MAILCOW_DEFAULT_QUOTA_MB = int(env("MAILCOW_DEFAULT_QUOTA_MB", "1024"))

# Mailcow REST API — есть только у Mailcow-инсталляций. Пусто => провижининг
# через API невозможен, apps/mail/services/provisioning/factory.py выберет
# IMAP-режим (verify-and-link) или no-op.
MAILCOW_API_URL = env("MAILCOW_API_URL", "")
MAILCOW_API_KEY = env("MAILCOW_API_KEY", "")

# Кто реально заводит ящики на почтовом сервере:
#   auto    — mailcow, если задан MAILCOW_API_URL+KEY; иначе imap, если задан
#             IMAP_HOST; иначе none (историческое поведение — только локальная
#             строка в БД).
#   mailcow — только Mailcow REST API.
#   imap    — сервер без админ-API: ящик обязан существовать, платформа
#             проверяет учётку живым IMAP-логином и привязывает её.
#   none    — ничего наружу не вызывать.
MAIL_PROVISIONER = env("MAIL_PROVISIONER", "auto").strip().lower()

# IMAP корпоративного сервера. При доступе через SSH-туннель (сервис
# ``mail-tunnel`` в docker-compose.yml) сюда идёт адрес туннеля, напр.
# IMAP_HOST=mail-tunnel, IMAP_PORT=1143, IMAP_SSL=false, IMAP_STARTTLS=true —
# наружу канал всё равно шифрует SSH.
IMAP_HOST = env("IMAP_HOST", "")
IMAP_PORT = int(env("IMAP_PORT", "993"))
IMAP_SSL = _flag("IMAP_SSL", "true")            # implicit TLS (993)
IMAP_STARTTLS = _flag("IMAP_STARTTLS", "false")  # STARTTLS поверх 143/1143
IMAP_TIMEOUT = int(env("IMAP_TIMEOUT", "30"))
# Имя, по которому проверять TLS-сертификат, когда подключаемся НЕ по нему.
# Нужно ровно в одном сценарии: TLS сквозь SSH-туннель — соединение идёт на
# ``mail-tunnel``, а сертификат выписан на ``mail.company.ru``, и проверка
# имени иначе падает. Пусто = проверять по IMAP_HOST (обычное поведение).
# Отключения проверки сертификата нет намеренно: через туннель достаточно
# оставить IMAP_SSL=false — шифрует SSH, и это безопаснее, чем TLS без
# валидации.
IMAP_TLS_SERVER_HOSTNAME = env("IMAP_TLS_SERVER_HOSTNAME", "")

# SMTP submission того же сервера. Пусто => берётся IMAP_HOST (типовой
# случай: один хост и для IMAP, и для submission).
SMTP_HOST = env("SMTP_HOST", "")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_SSL = _flag("SMTP_SSL", "false")            # implicit TLS (465)
SMTP_STARTTLS = _flag("SMTP_STARTTLS", "true")   # STARTTLS (587)
SMTP_TIMEOUT = int(env("SMTP_TIMEOUT", "30"))

# Сколько писем максимум тянуть за один прогон синхронизации одного ящика и
# какие папки обходить (канонические имена — apps/mail/models.py::Folder).
MAIL_SYNC_MAX_MESSAGES = int(env("MAIL_SYNC_MAX_MESSAGES", "200"))
MAIL_SYNC_FOLDERS = [
    f.strip() for f in env("MAIL_SYNC_FOLDERS", "INBOX,Sent").split(",") if f.strip()
]
# Толкать ли локально прочитанное обратно на сервер флагом \Seen (вторая
# половина двусторонней синхронизации писем).
MAIL_SYNC_PUSH_FLAGS = _flag("MAIL_SYNC_PUSH_FLAGS", "true")

# Сверка "платформа ↔ почтовый сервер" (apps/mail/services/reconcile_service.py).
# По умолчанию периодическая задача только СЧИТАЕТ расхождения и пишет их в
# лог; применение изменений — явное действие админа из UI.
MAIL_RECONCILE_AUTO_APPLY = _flag("MAIL_RECONCILE_AUTO_APPLY", "false")

# Привязка БЕСХОЗНЫХ ящиков к владельцам по точному совпадению адреса —
# отдельно от AUTO_APPLY выше и по умолчанию включена. Операция не
# разрушающая: у ящика не было владельца, а его адрес совпал с email
# пользователя, и другого владельца у такого адреса быть не может.
# Слитая с AUTO_APPLY, она требовала бы включить заодно двустороннее
# автосведение (импорт с сервера и создание недостающих ящиков на нём) —
# поэтому и не работала никогда: ради безопасной половины пришлось бы
# включить опасную.
MAIL_RECONCILE_AUTO_LINK = _flag("MAIL_RECONCILE_AUTO_LINK", "true")

# Как собирать адрес из имени сотрудника: first.last | f.last | firstlast |
# first_last | flast | last.first | first. Дефолт "f.last" — историческое
# поведение платформы (i.ivanov), менять его глобально нельзя, не сломав
# существующие инсталляции; своё соглашение задаётся здесь или в интерфейсе
# («Корпоративные ящики» → «Подключение»).
MAILBOX_LOCAL_PART_PATTERN = env("MAILBOX_LOCAL_PART_PATTERN", "f.last").strip().lower()

# ── media upload pipeline (apps/media_files, task 3.2) — ported defaults
# from services/media/app/core/settings.py, byte-for-byte where the setting
# still applies. dedup_enabled is NOT ported (defaults to False upstream
# too, and this port doesn't implement the sha256-dedup lookup — see the
# task 3.2 report). media_signed_url_* is NOT ported here either — signed
# URLs are a later task (3.3+).
MAX_UPLOAD_SIZE_MB = int(env("MAX_UPLOAD_SIZE_MB", "100"))
ALLOWED_MIME_TYPES = env("ALLOWED_MIME_TYPES", "")  # comma-separated, "" = allow all
IMAGE_JPEG_QUALITY = int(env("IMAGE_JPEG_QUALITY", "85"))
THUMBNAIL_FORMAT = env("THUMBNAIL_FORMAT", "webp")  # webp | jpeg | png
THUMBNAIL_QUALITY = int(env("THUMBNAIL_QUALITY", "82"))
MAX_IMAGE_PIXELS = int(env("MAX_IMAGE_PIXELS", str(100_000_000)))  # image-bomb guard
STRIP_EXIF = env("STRIP_EXIF", "true").lower() in ("1", "true", "yes")
# Ported from services/media/app/core/settings.py's
# soft_delete_grace_days: int = 30 — used by apps.media_files.tasks
# .purge_soft_deleted (task 3.4).
MEDIA_SOFT_DELETE_GRACE_DAYS = int(env("MEDIA_SOFT_DELETE_GRACE_DAYS", "30"))
