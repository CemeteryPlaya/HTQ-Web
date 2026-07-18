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
    # "apps.users",  # включается в Task 0.2 вместе с AUTH_USER_MODEL
]

MIDDLEWARE = [
    # "htqweb.middleware.request_id.RequestIDMiddleware",   # TODO(Task 0.4): enable
    # "htqweb.middleware.service_gate.ServiceGateMiddleware",  # TODO(Task 0.5): enable
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

# AUTH_USER_MODEL = "users.User"  ← раскомментируется в Task 0.2 вместе с моделью

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://localhost:6379/8"),
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
