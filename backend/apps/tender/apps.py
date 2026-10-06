from django.apps import AppConfig


class TenderConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.tender"
    verbose_name = "Тендеры"
    # Тендерный модуль закупок (docs/plans/2026-10-06-tender-master-plan.md,
    # T-01): запрос предложений поставщикам, сравнение, выбор и передача в
    # БЗО. Рубильник — по компании (не CORE_MODULES): пилот только у холдинга.
    # Тенантная (settings.TENANT_APPS — с 0001_core): таблицы в схеме
    # компании, на бою их доводит migrate_companies, а не старт контейнера.
    API_PREFIX = "api/tender/v1/"
