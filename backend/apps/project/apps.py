from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.project"
    verbose_name = "Проекты"
    # Сущность «Проект» модуля БЗО (docs/plans/2026-09-26-bpp-master-plan.md,
    # D-02). Тенантная: в settings.TENANT_APPS попадает вместе с первой
    # миграцией (задача A1.3) — migrate_companies прогоняет каждую аппку
    # списка, и аппка без миграций уронила бы прогон.
    API_PREFIX = "api/project/v1/"
