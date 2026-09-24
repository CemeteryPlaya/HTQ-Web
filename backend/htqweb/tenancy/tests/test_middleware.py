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


@pytest.fixture
def dead(db):
    return Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )


def _spy_middleware():
    from htqweb.middleware.company_context import CompanyContextMiddleware

    seen = {}

    def spy(request):
        seen["context"] = current_company_or_none()
        seen["is_active"] = request.company["is_active"]
        return HttpResponse("ok")

    return CompanyContextMiddleware(spy), seen


@pytest.mark.django_db
def test_archived_company_get_reaches_the_view_in_its_context(dead, rf):
    """Архив больше не 404 целиком: чтение доходит до вьюхи в контексте
    компании. Кого пускать читать — решает api_view (только суперпользователь),
    не middleware: тот ещё не знает, кто пришёл."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.get("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen == {"context": "dead", "is_active": False}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_archived_company_refuses_every_write(dead, method):
    resp = getattr(Client(), method)("/api/hr/v1/departments/",
                                     HTTP_X_HTQ_COMPANY="dead")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Компания в архиве — только чтение",
                           "code": "company_archived"}


@pytest.mark.django_db
def test_archived_company_write_refusal_does_not_reach_the_view(dead, rf):
    """Отказ записи — ДО вьюхи и до аутентификации: правило не зависит ни от
    роли, ни от аппки, ни от того, стоит ли на ручке api_view."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 403
    assert seen == {}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["head", "options"])
def test_archived_company_lets_safe_methods_through(dead, rf, method):
    middleware, seen = _spy_middleware()
    resp = middleware(getattr(rf, method)("/api/hr/v1/departments/",
                                          HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen["context"] == "dead"


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/users/v1/token/",
                                  "/api/users/v1/token/refresh/"])
def test_archived_company_lets_token_endpoints_through(dead, rf, path):
    """Без выдачи токена суперпользователь не прочтёт архив вовсе; кого
    пускать, решает сама ручка (companies.interface.user_may_enter_company)."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post(path, HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen["context"] == "dead"


@pytest.mark.django_db
def test_archived_company_hides_django_admin(dead):
    """Сессии на этом шаге ещё нет (SessionMiddleware ниже) — кто пришёл,
    не узнать; django-admin живёт на голом домене."""
    resp = Client().get("/django-admin/", HTTP_X_HTQ_COMPANY="dead")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Компания не найдена"}


@pytest.mark.django_db
def test_restored_company_accepts_writes_again(dead, rf):
    from django.core.cache import cache

    dead.status = CompanyStatus.ACTIVE
    dead.save(update_fields=["status"])
    cache.clear()  # резолв метки хоста кэширован на 5 с
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen == {"context": "dead", "is_active": True}


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
    """Псевдоним в заголовке компанию НАХОДИТ: ответ — не 404 middleware.

    Больше этот тест ничего не проверяет — ни ``search_path``, ни слаг в
    контексте: «не 404» не отличит контекст на слаге от контекста на
    псевдониме. Это делает шпион ``test_alias_sets_context_and_request_company_by_slug``.
    """
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
