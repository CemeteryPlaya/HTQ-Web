import os
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
    "django_q",
    "apps.core",
    "apps.users",
    "apps.cms",
]

MIDDLEWARE = [
    "htqweb.middleware.request_id.RequestIDMiddleware",
    "htqweb.middleware.service_gate.ServiceGateMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
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

Q_CLUSTER = {
    "name": "htqweb",
    "workers": 4,
    "timeout": 300,
    "retry": 360,
    "max_attempts": 3,
    "redis": env("REDIS_URL", "redis://localhost:6379/8"),
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
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Object storage (S3/MinIO) — htqweb/storage/, ported from
# services/cms/app/services/s3_storage.py + signed_url.py. Names/defaults
# match docker-compose.yml's cms-service environment block byte-for-byte so
# both stacks read the same env during the Strangler Fig transition — with
# one intentional exception: S3_PUBLIC_ENDPOINT has no compose default (cms
# doesn't set it there either) and stays "" here too, which S3Storage treats
# as "fall back to S3_ENDPOINT" (see s3.py's `public_endpoint or endpoint`).
STORAGE_BACKEND = env("STORAGE_BACKEND", "s3")  # local | s3
S3_BUCKET = env("S3_BUCKET", "htqweb-cms")
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
