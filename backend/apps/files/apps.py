from django.apps import AppConfig


class FilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.files"
    verbose_name = "Файлы"
    label = "files"
    # Файловая подсистема ТЗ §21 («Файлы и вложения»): одна на все объекты,
    # к которым прикладываются документы (заявка, договор, …). URL-автодискавери
    # (htqweb/urls.py) монтирует её под этим префиксом; сервис `files` в
    # KNOWN_SERVICES, ядро платформы (CORE_MODULES) — у компании не выключается.
    API_PREFIX = "api/files/v1/"
