from django.apps import AppConfig


class BppConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.bpp"
    verbose_name = "Закупки и оплаты"
    # Модуль БЗО «Бюджет, закупки и оплаты» (docs/plans/2026-09-26-bpp-
    # master-plan.md). Тенантная: в settings.TENANT_APPS — вместе с первой
    # миграцией (задача A1.1). Подмодули с собственными рубильниками —
    # apps.core.models.KNOWN_SUBMODULES; их префиксы — в PREFIX_TO_SERVICE
    # ВЫШЕ префикса модуля.
    API_PREFIX = "api/bpp/v1/"
