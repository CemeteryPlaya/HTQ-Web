import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "htqweb.settings.dev")

app = Celery("htqweb")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
# Второй модуль задач на аппку, помимо голого ``tasks.py`` (``related_name``
# по умолчанию у вызова выше). Заведён для ``apps/bpp/tasks_export.py``
# (A2.2, задача 6) — отдельный файл от ``apps/bpp/tasks.py`` (там ночная
# сверка «Задействовано»), чтобы задачи модуля не сталкивались правками в
# одном файле, пока обе части пишутся параллельно. ``autodiscover_tasks``
# сам проверяет наличие модуля в каждой аппке (``module_has_submodule``) до
# импорта, поэтому вызов безопасен и для аппок без ``tasks_export.py``.
app.autodiscover_tasks(related_name="tasks_export")
