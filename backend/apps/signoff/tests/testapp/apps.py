from django.apps import AppConfig


class SignoffTestAppConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.signoff.tests.testapp"
    label = "signoff_testapp"

    def ready(self):
        # Точно так же подключится предметная аппка: регистрация из ready(),
        # а не автопоиск модулей по importlib (см. services/registry.py).
        from . import hooks

        hooks.register()
