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

    def ready(self) -> None:
        # Журнал заявки — по правилам её видимости; файлы ТЗ и чертежей —
        # владелец ``tender.request`` в apps.files (T1.1).
        from . import file_owners
        from .services.requests import crud
        from .services.tenders import tenders

        crud.register()
        file_owners.register()
        # Журнал тендера — по правилам его видимости (T2.1).
        tenders.register()
        self._listen_to_bpp()

    @staticmethod
    def _listen_to_bpp() -> None:
        """Статусы ЗЗ частей заявки приходят из БЗО слушателем в транзакции
        смены статуса (T-09, T1.3): зеркало части и свёртка статуса заявки."""
        from django.apps import apps as registry

        if not registry.is_installed("apps.bpp"):
            return
        from apps.bpp import interface as bpp

        from .services.requests import status

        bpp.register_request_listener(status.on_bpp_status)
