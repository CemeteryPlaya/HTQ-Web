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

    def ready(self):
        """Подключить читателей холдинга к реестру моделей аппки.

        ``holding_models`` — отдельный файл, а не часть ``models.py``
        (см. его докстринг), поэтому Django никогда не импортирует его сам:
        без явного импорта здесь ``HoldingProject`` и соседи не попадают в
        реестр моделей аппки, и ``makemigrations`` тихо не видит их вовсе
        («No changes detected») — тот же класс отказа, ради которого весь
        механизм fallback'ов в проекте настолько нетерпим к тишине. Тот же
        приём, что в ``apps/hr/apps.py``.
        """
        from . import holding_models  # noqa: F401
