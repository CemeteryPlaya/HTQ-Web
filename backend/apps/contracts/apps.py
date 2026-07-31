from django.apps import AppConfig


class ContractsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.contracts"
    verbose_name = "Договоры и бюджеты"
    # URL-автодискавери (htqweb/urls.py): аппка монтируется под этим
    # префиксом без ручной строки include(...). Имя сервиса в реестре —
    # "contracts" (совпадает с app_label, поэтому запись в
    # APP_LABEL_TO_SERVICE не нужна; см. apps/core/models.KNOWN_SERVICES и
    # htqweb/middleware/service_gate.PREFIX_TO_SERVICE).
    API_PREFIX = "api/contracts/v1/"

    def ready(self):
        """Объявить бюджеты, контрагентов и договоры согласуемыми.

        Явный вызов, а не автопоиск модулей: автопоиск — тот же межаппный
        импорт, только спрятанный от проверки границ (см. докстринг
        ``apps/signoff/services/registry.py``). Здесь его видно и человеку,
        и грепу.

        Импорт локальный — ``ready()`` вызывается после загрузки моделей,
        и импорт верхнего уровня в ``apps.py`` их бы не дождался.
        """
        from . import approval_hooks

        approval_hooks.register()
