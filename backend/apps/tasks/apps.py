from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.tasks"
    verbose_name = "Работы"
    # URL-автодискавери (htqweb/urls.py, PLAN.md §4.1): аппка монтируется под
    # этим префиксом без ручной строки include(...). Имя сервиса в реестре —
    # "tasks" (apps/core/models.KNOWN_SERVICES,
    # htqweb/middleware/service_gate.PREFIX_TO_SERVICE).
    API_PREFIX = "api/tasks/v1/"
