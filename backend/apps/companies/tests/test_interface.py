import pytest

from apps.companies import interface
from apps.companies.models import (
    Company, CompanyKind, CompanyMembership, CompanyModule, CompanyStatus,
)


@pytest.fixture
def kz(db):
    return Company.objects.create(
        slug="htq-kz", name="Hi-Tech Qazaqstan", kind=CompanyKind.REGIONAL,
    )


@pytest.mark.django_db
def test_get_company_returns_plain_dict(kz):
    """Наружу отдаётся dict, а не ORM-объект: сосед не должен иметь
    возможности мутировать чужую модель напрямую."""
    data = interface.get_company("htq-kz")
    assert data["slug"] == "htq-kz"
    assert data["kind"] == "regional"
    assert not hasattr(data, "save")


@pytest.mark.django_db
def test_get_company_unknown_slug_is_none(kz):
    assert interface.get_company("нет-такой") is None


@pytest.mark.django_db
def test_archived_company_is_not_in_active_list(kz):
    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    assert interface.active_company_slugs() == ["htq-kz"]


@pytest.mark.django_db
def test_user_company_slugs_lists_only_own(kz):
    other = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyMembership.objects.create(user_id=7, company=kz, is_default=True)
    assert interface.user_company_slugs(7) == ["htq-kz"]
    assert interface.default_company_slug(7) == "htq-kz"
    assert interface.user_company_slugs(8) == []


@pytest.mark.django_db
def test_module_without_row_is_enabled(kz):
    """Отсутствие строки означает «включено» — так же, как у ServiceStatus."""
    assert interface.module_enabled("htq-kz", "tasks") == (True, "")


@pytest.mark.django_db
def test_module_can_be_disabled_per_company(kz):
    CompanyModule.objects.create(
        company=kz, app_label="tasks", enabled=False, message="Не оплачено",
    )
    assert interface.module_enabled("htq-kz", "tasks") == (False, "Не оплачено")
    assert interface.module_enabled("htq-kz", "contracts") == (True, "")


@pytest.mark.django_db
def test_result_is_cached_within_ttl(kz):
    """Кэш обязан быть проверяемым: без этого теста его исчезновение
    не отличить от рабочего состояния."""
    assert interface.get_company("htq-kz")["name"] == "Hi-Tech Qazaqstan"
    Company.objects.filter(slug="htq-kz").update(name="Переименована")
    assert interface.get_company("htq-kz")["name"] == "Hi-Tech Qazaqstan"


@pytest.mark.django_db
def test_missing_company_is_cached_as_empty_dict(kz):
    """Отрицательное кэширование: cache.get не отличает «в кэше None» от
    «в кэше пусто», поэтому отсутствие компании кладётся как {}."""
    from django.core.cache import cache

    assert interface.get_company("нет-такой") is None
    assert cache.get("company:slug:нет-такой") == {}


@pytest.mark.django_db
def test_fresh_bypasses_the_cache(kz):
    """Пересборка представлений идёт сразу после создания компании —
    кэш отдал бы список без неё."""
    assert interface.active_company_slugs() == ["htq-kz"]
    Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    assert interface.active_company_slugs() == ["htq-kz"]
    assert interface.active_company_slugs(fresh=True) == ["htq-kz", "htq-uz"]
