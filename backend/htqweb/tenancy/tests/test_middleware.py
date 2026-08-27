import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyStatus
from htqweb.tenancy.context import current_company_or_none


@pytest.fixture
def kz(db):
    return Company.objects.create(
        slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL,
    )


@pytest.mark.django_db
def test_health_works_without_company_header():
    """Служебные роуты не требуют компании: /health/ и /metrics/ должны
    отвечать и тогда, когда реестр пуст, иначе оркестратор не сможет
    поднять стек с нуля."""
    assert Client().get("/health/").status_code == 200


@pytest.mark.django_db
def test_unknown_company_is_404(kz):
    response = Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="нет-такой")
    assert response.status_code == 404
    assert response.json()["detail"]


@pytest.mark.django_db
def test_archived_company_is_404():
    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    response = Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="dead")
    assert response.status_code == 404


@pytest.mark.django_db
def test_context_is_cleared_after_response(kz):
    Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="htq-kz")
    assert current_company_or_none() is None


@pytest.mark.django_db
def test_context_is_cleared_even_when_view_raises(kz, rf):
    """Утёкший контекст — худший из возможных дефектов этой архитектуры:
    следующий запрос в том же процессе прочитал бы чужую схему.

    Middleware вызывается напрямую, а не через Client: тестовый клиент
    Django ловит исключения вьюхи и превращает их в 500, то есть скрыл бы
    именно тот путь, который здесь проверяется.
    """
    from htqweb.middleware.company_context import CompanyContextMiddleware

    def boom(request):
        raise RuntimeError("боом")

    middleware = CompanyContextMiddleware(boom)
    request = rf.get("/api/tasks/v1/", HTTP_X_HTQ_COMPANY="htq-kz")
    with pytest.raises(RuntimeError):
        middleware(request)
    assert current_company_or_none() is None
