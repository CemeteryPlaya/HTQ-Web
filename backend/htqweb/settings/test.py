from .base import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
Q_CLUSTER = {"name": "htqweb-test", "sync": True, "timeout": 30, "retry": 60}
JWT_SECRET = "test-secret-key-for-htqweb-tests-32b"
