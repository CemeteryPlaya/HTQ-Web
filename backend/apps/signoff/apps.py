from django.apps import AppConfig, apps


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

    def ready(self):
        # Очередь «ждёт меня» — источник ежедневной сводки центра уведомлений
        # (D-23). Центр о signoff не знает: источник регистрируется сам, и
        # только там, где центр установлен. Тенантный — задачи согласования
        # лежат в схеме компании, сводка обходит компании пользователя.
        if apps.is_installed("apps.notifications"):
            from apps.notifications import interface as notifications
            from apps.signoff.services import holders

            notifications.register_digest_source(
                "signoff", holders.digest_items, tenant=True)
