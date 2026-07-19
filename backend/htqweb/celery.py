import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "htqweb.settings.dev")

app = Celery("htqweb")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
