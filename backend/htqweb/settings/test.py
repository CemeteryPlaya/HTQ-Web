import os

from .base import *  # noqa: F403

# Тестовая предметная аппка для движка signoff: минимальная модель с
# примесью Approvable, подключённая ровно так же, как подключится любая
# настоящая (примесь + регистрация из AppConfig.ready()). Живёт только в
# тестах — движок универсален, и проверять его на конкретном домене
# значило бы ловить в его тестах чужие регрессии.
#
# Пакета migrations у неё нет намеренно: `migrate --run-syncdb`, который
# pytest-django выполняет при создании тестовой БД, заводит таблицы именно
# для аппок без миграций.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.signoff.tests.testapp"]  # noqa: F405

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

# manifest-сторедж (base) требует collectstatic и падает на {% static %} без него
# (напр. рендер django-admin в тестах) — в тестах берём обычный staticfiles-сторедж.
STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Celery eager mode: tasks run inline, synchronously, with no broker — this
# reproduces the old django-q2 Q_CLUSTER["sync"]=True behaviour the tests
# rely on (notify_admins_on_contact_request fires synchronously from the
# contact-request POST view during tests; guard-test tasks raise inline).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
JWT_SECRET = "test-secret-key-for-htqweb-tests-32b"

# Eager mode runs .delay(...) inline — so notify_admins_on_contact_request
# fires synchronously from the contact-request POST view during tests.
# ADMINS defaults to [] (base.py, DJANGO_ADMINS unset) so mail_admins()
# no-ops by default there too; individual tests opt in with
# @override_settings(ADMINS=[...]) to assert on django.core.mail.outbox.
# pytest-django's test environment also force-swaps EMAIL_BACKEND to the
# locmem backend for the duration of the run regardless of what's
# configured, so no EMAIL_BACKEND override is needed here.
