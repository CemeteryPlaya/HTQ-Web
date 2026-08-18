from .base import *  # noqa: F403

DEBUG = True

# Машина разработчика: fallback'и запрещены — вместо подмены летит
# FallbackNotAllowed (htqweb/fallback.py). Дефолт задаётся здесь, а не только
# переменной окружения, чтобы `manage.py runserver` с этими настройками вёл
# себя строго и без docker-compose.
HTQ_ENV = env("HTQ_ENV", "development")  # noqa: F405
FALLBACK_MODE = fallback_mode_for(HTQ_ENV)  # noqa: F405

# В dev static отдаёт runserver; manifest-сторедж (base) требует collectstatic и
# падает на {% static %} без него — берём обычный staticfiles-сторедж.
STORAGES = {
    **STORAGES,  # noqa: F405  (default из base)
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
