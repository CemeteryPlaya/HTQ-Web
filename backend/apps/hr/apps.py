from django.apps import AppConfig


class HrConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.hr"
    verbose_name = "Кадры"
    # URL-автодискавери (htqweb/urls.py, PLAN.md §4.1): аппка монтируется под
    # этим префиксом без ручной строки include(...). Имя сервиса в реестре —
    # "hr" (apps/core/models.KNOWN_SERVICES,
    # htqweb/middleware/service_gate.PREFIX_TO_SERVICE).
    API_PREFIX = "api/hr/v1/"
