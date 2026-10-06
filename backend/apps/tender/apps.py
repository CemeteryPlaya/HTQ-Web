from django.apps import AppConfig


class TenderConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.tender"
    verbose_name = "Тендеры"
    # Тендерный модуль закупок (docs/plans/2026-10-06-tender-master-plan.md,
    # T-01): запрос предложений поставщикам, сравнение, выбор и передача в
    # БЗО. Рубильник — по компании (не CORE_MODULES): пилот только у холдинга.
    # Тенантная: в settings.TENANT_APPS попадает вместе с первой миграцией
    # (задача T0.2) — тенантная аппка без таблиц выпала бы из tenancy_status,
    # а migrate_companies прогоняет каждую аппку списка.
    API_PREFIX = "api/tender/v1/"
