from django.apps import AppConfig


class ApprovalsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.approvals"
    verbose_name = "Заявки и формы"
    # URL-автодискавери (htqweb/urls.py, PLAN.md §4.1): аппка монтируется под
    # этим префиксом без ручной строки include(...). Имя сервиса в реестре —
    # "approvals" (apps/core/models.KNOWN_SERVICES,
    # htqweb/middleware/service_gate.PREFIX_TO_SERVICE).
    API_PREFIX = "api/requests/v1/"

    def ready(self):
        # Регистрация заявки как согласуемого типа в apps.signoff — явным
        # вызовом, а не автопоиском (см. apps/signoff/services/registry.py).
        from . import approval_hooks

        approval_hooks.register()
