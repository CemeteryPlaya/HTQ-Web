import os

from .base import *  # noqa: F403

# Тесты бьют напрямую в Postgres контейнера htqweb1-db-1, не через PgBouncer:
# pytest-django создаёт/дропает test_htqweb через CREATE/DROP DATABASE, а
# PgBouncer в transaction-режиме такого не пропускает. Нативный Windows
# postgresql-x64-18 занимает хостовый :5432, поэтому контейнер отдельно
# публикуется на :55432 через `docker-compose.test.yml` (см. backend/README-tests.md).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("TEST_DB_NAME", "htqweb"),
        "USER": os.environ.get("TEST_DB_USER", "htqweb"),
        "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "change-me"),
        "HOST": os.environ.get("TEST_DB_HOST", "localhost"),
        "PORT": os.environ.get("TEST_DB_PORT", "55432"),
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "CONN_MAX_AGE": 0,
    }
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
Q_CLUSTER = {"name": "htqweb-test", "sync": True, "timeout": 30, "retry": 60}
JWT_SECRET = "test-secret-key-for-htqweb-tests-32b"
