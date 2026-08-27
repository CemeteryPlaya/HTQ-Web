import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.core.services import CORE_MODULES, ServiceDisabled, require_service
from htqweb.tenancy.db import use_company


@pytest.fixture
def kz(db):
    return Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)


@pytest.mark.django_db
def test_module_disabled_for_company_raises(kz):
    CompanyModule.objects.create(
        company=kz, app_label="tasks", enabled=False, message="Не подключён",
    )
    with use_company("htq-kz"):
        with pytest.raises(ServiceDisabled) as exc:
            require_service("tasks")
    assert exc.value.message == "Не подключён"


@pytest.mark.django_db
def test_module_disabled_for_company_does_not_affect_others(kz):
    Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False)
    with use_company("htq-uz"):
        require_service("tasks")  # не должно поднять исключение


@pytest.mark.django_db
def test_core_module_cannot_be_disabled_per_company(kz):
    """Ядро одинаково у всех — это прямое требование заказчика.

    Строку в CompanyModule для ядра завести можно (форму никто не
    ограничивает), но гейт её игнорирует, иначе компания осталась бы без
    входа или без кадров.
    """
    assert "hr" in CORE_MODULES
    CompanyModule.objects.create(company=kz, app_label="hr", enabled=False)
    with use_company("htq-kz"):
        require_service("hr")


@pytest.mark.django_db
def test_without_company_context_only_global_switch_applies(kz):
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False)
    require_service("tasks")  # вне контекста компании — не падает


@pytest.mark.django_db
def test_disabled_module_returns_503_at_the_http_edge(kz):
    """Гейт по URL-префиксу обязан видеть компанейский рубильник.

    Без этого выключенный у компании модуль отдавал бы обычные ответы:
    ServiceGateMiddleware спрашивает service_status, а не require_service —
    require_service использует ровно эту функцию внутри себя, но вьюхи
    аппки зовут свои сервисы напрямую, а не через require_service/interface.
    """
    CompanyModule.objects.create(
        company=kz, app_label="tasks", enabled=False, message="Не подключён",
    )
    response = Client().get("/api/tasks/v1/tasks/", HTTP_X_HTQ_COMPANY="htq-kz")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "tasks"


@pytest.mark.django_db
def test_disabled_module_does_not_affect_other_company_at_http_edge(kz):
    """Симметрично предыдущему: у ДРУГОЙ компании тот же модуль работает.

    Без этого предыдущий тест не отличил бы компанейский рубильник от
    случая, где сам домен tasks выключен глобально или гейт всегда отдаёт
    503 — здесь ServiceGateMiddleware обязан пропустить запрос дальше, до
    JWT-проверки самой вьюхи (401, а не 503).
    """
    Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False)
    response = Client().get("/api/tasks/v1/tasks/", HTTP_X_HTQ_COMPANY="htq-uz")
    assert response.status_code == 401
