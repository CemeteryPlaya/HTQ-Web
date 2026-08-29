from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.access"
    verbose_name = "Доступ и роли"
    # URL-автодискавери (htqweb/urls.py) монтирует аппку по этому префиксу —
    # htqweb/urls.py не правится (правило №3, backend/README.md). Имя сервиса
    # в реестре — "access" (совпадает с app_label, поэтому запись в
    # APP_LABEL_TO_SERVICE не нужна).
    API_PREFIX = "api/access/v1/"
