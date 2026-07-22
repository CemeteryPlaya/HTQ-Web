from .base import *  # noqa: F403

DEBUG = True

# В dev static отдаёт runserver; manifest-сторедж (base) требует collectstatic и
# падает на {% static %} без него — берём обычный staticfiles-сторедж.
STORAGES = {
    **STORAGES,  # noqa: F405  (default из base)
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
