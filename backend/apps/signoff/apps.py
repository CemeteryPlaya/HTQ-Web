from django.apps import AppConfig


class SignoffConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.signoff"
    verbose_name = "Согласование"
    # URL-автодискавери (htqweb/urls.py): аппка монтируется под этим
    # префиксом без ручной строки include(...). Имя сервиса в реестре —
    # "signoff" (совпадает с app_label, поэтому запись в APP_LABEL_TO_SERVICE
    # не нужна; см. apps/core/models.KNOWN_SERVICES и
    # htqweb/middleware/service_gate.PREFIX_TO_SERVICE).
    API_PREFIX = "api/signoff/v1/"
