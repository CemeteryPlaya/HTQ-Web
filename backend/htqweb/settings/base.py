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

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_results",
    "django_celery_beat",
    "django_json_widget",
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
]

ROOT_URLCONF = "htqweb.urls"
ASGI_APPLICATION = "htqweb.asgi.application"
WSGI_APPLICATION = "htqweb.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
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
        "ENGINE": "django.db.backends.postgresql",
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
        "BACKEND": "django_redis.cache.RedisCache",
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

# ── Conference (SFU) runtime config — GET /api/cms/v1/conference/config ─────
# Ported defaults from services/cms/app/data/conference.yaml (FastAPI
# cms-service). The conference/SFU stack itself is out of service (seeded
# disabled by apps.core's registry migration — see apps/cms/services/
# conference_service.py), but static WebRTC config is still served so the
# frontend's ConferencePage.tsx behaves identically once it comes back.
CONFERENCE_SFU_URL = env("CONFERENCE_SFU_URL", "ws://sfu:4443")
CONFERENCE_SFU_PATH = env("CONFERENCE_SFU_PATH", "/ws/sfu/")
CONFERENCE_ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]

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
