import pytest
from django.http import HttpResponse
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
    response = Client().get("/api/users/v1/profile/me", HTTP_X_HTQ_COMPANY="нет-такой")
    assert response.status_code == 404
    assert response.json()["detail"]


@pytest.mark.django_db
def test_archived_company_is_404():
    """Архивная компания отклоняется ДО разрешения URL.

    Проверяется тело, а не только код: без него тест прошёл бы и в случае,
    когда middleware не сработал вовсе, — Django сам отдаёт 404 на
    неизвестный путь, и отличить одно от другого по коду невозможно.
    """
    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    response = Client().get("/api/users/v1/profile/me", HTTP_X_HTQ_COMPANY="dead")
    assert response.status_code == 404
    assert response.json() == {"detail": "Компания не найдена"}


@pytest.mark.django_db
def test_context_is_cleared_after_response(kz, rf):
    """Контекст компании при обычном (не аварийном) ответе стоит НА ВРЕМЯ
    запроса и снимается сразу после.

    Проверяется оба конца, а не только пустота contextvar после ответа:
    одной этой пустоты было бы мало — она осталась бы правдой и в мире,
    где middleware вообще не выставляет контекст (например, если бы
    set_company молча не сработал). Middleware вызывается напрямую с
    вьюхой-шпионом, которая читает контекст изнутри запроса, — так тест
    ловит и «контекст не выставлен», и «контекст не снят».
    """
    from htqweb.middleware.company_context import CompanyContextMiddleware

    seen = {}

    def spy(request):
        seen["slug"] = current_company_or_none()
        return HttpResponse("ok")

    middleware = CompanyContextMiddleware(spy)
    request = rf.get("/api/tasks/v1/", HTTP_X_HTQ_COMPANY="htq-kz")
    middleware(request)

    assert seen["slug"] == "htq-kz"
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


# ── Метка хоста — псевдоним ИЛИ слаг (блок I.2, задача 4) ──────────────────


@pytest.mark.django_db
def test_middleware_resolves_alias_into_schema_of_its_company(client):
    """Заголовок несёт псевдоним, а search_path встаёт по слагу."""
    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq",
                           status=CompanyStatus.ACTIVE)

    resp = client.get("/api/companies/v1/me", HTTP_X_HTQ_COMPANY="htq")

    assert resp.status_code != 404


@pytest.mark.django_db
def test_middleware_rejects_slug_of_a_company_that_has_an_alias(client):
    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq",
                           status=CompanyStatus.ACTIVE)

    resp = client.get("/api/companies/v1/me",
                      HTTP_X_HTQ_COMPANY="hi-tech-qazaqstan")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Компания не найдена"}


@pytest.mark.django_db
def test_alias_sets_context_and_request_company_by_slug(rf):
    """Дальше middleware по коду идёт СЛАГ, а не метка хоста.

    Шпион изнутри запроса: код «!= 404» выше не отличил бы «контекст стоит
    на слаге» от «контекст стоит на псевдониме» — а псевдоним в contextvar
    означал бы схему ``co_htq``, которой нет, и токен на компанию «htq».
    """
    from htqweb.middleware.company_context import CompanyContextMiddleware

    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq",
                           status=CompanyStatus.ACTIVE)
    seen = {}

    def spy(request):
        seen["context"] = current_company_or_none()
        seen["request"] = request.company["slug"]
        return HttpResponse("ok")

    CompanyContextMiddleware(spy)(
        rf.get("/api/tasks/v1/", HTTP_X_HTQ_COMPANY="HTQ"))

    assert seen == {"context": "hi-tech-qazaqstan",
                    "request": "hi-tech-qazaqstan"}
