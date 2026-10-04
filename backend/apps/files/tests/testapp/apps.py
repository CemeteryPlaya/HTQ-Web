from django.apps import AppConfig


class FilesTestAppConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.files.tests.testapp"
    label = "files_testapp"

    def ready(self):
        # Ровно так подключится настоящий владелец: регистрация из ready()
        # (см. apps/files/services/registry.py).
        from . import hooks

        hooks.register()
