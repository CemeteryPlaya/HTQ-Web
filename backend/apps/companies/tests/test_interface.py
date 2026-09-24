import pytest

from apps.companies import interface
from apps.companies.models import (
    Company, CompanyKind, CompanyMembership, CompanyModule, CompanyStatus,
)
from apps.users.models import User, UserStatus


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
def test_user_may_enter_company_requires_membership(kz):
    other = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyMembership.objects.create(user_id=7, company=kz, is_default=True)
    assert interface.user_may_enter_company(7, "htq-kz") is True
    assert interface.user_may_enter_company(7, "htq-uz") is False
    assert interface.user_may_enter_company(8, "htq-kz") is False


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


def test_schema_exists_reports_the_physical_schema(company_schema):
    from apps.companies import interface
    assert interface.schema_exists(company_schema["slug"]) is True
    assert interface.schema_exists("t-no-such-company") is False


@pytest.mark.django_db
def test_get_company_exposes_is_active_predicate(kz):
    """Потребитель (например, CompanyContextMiddleware) не должен импортировать
    CompanyStatus из apps.companies.models, чтобы проверить действующая ли
    компания — get_company отдаёт готовый предикат is_active."""
    assert interface.get_company("htq-kz")["is_active"] is True

    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    assert interface.get_company("dead")["is_active"] is False


@pytest.mark.django_db
def test_is_holding_true_for_a_holding_company(kz):
    """Предикат, а не сырой ``kind`` — потребитель (``apps.hr``, блок H) не
    должен импортировать ``CompanyKind`` из apps.companies.models."""
    holding = Company.objects.create(
        slug="hi-tech-group", name="Group", kind=CompanyKind.HOLDING,
    )
    assert interface.is_holding(holding.slug) is True


@pytest.mark.django_db
def test_is_holding_false_for_a_non_holding_company(kz):
    """``kz`` заведена с ``CompanyKind.REGIONAL`` — обычная дочерняя компания
    группы, не холдинг."""
    assert interface.is_holding("htq-kz") is False


@pytest.mark.django_db
def test_is_holding_unknown_slug_is_false_not_an_exception():
    """Докстринг ``is_holding`` объявляет это осознанным решением:
    спрашивающий уже получил компанию из контекста запроса, и «такой
    компании нет» значит для него ровно «не холдинг» — не повод падать."""
    assert interface.is_holding("нет-такой-компании") is False


def _company(slug, status=CompanyStatus.ACTIVE):
    return Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE,
                                  status=status)


def _user(username, *, superuser=False, status=UserStatus.ACTIVE):
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status, is_superuser=superuser)


@pytest.mark.django_db
def test_superuser_enters_archived_company_without_membership():
    _company("dead", CompanyStatus.ARCHIVED)
    root = _user("root", superuser=True)
    assert interface.user_may_enter_company(root.id, "dead") is True


@pytest.mark.django_db
def test_member_does_not_enter_archived_company():
    dead = _company("dead", CompanyStatus.ARCHIVED)
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    assert interface.user_may_enter_company(alice.id, "dead") is False


@pytest.mark.django_db
def test_inactive_superuser_does_not_enter_archived_company():
    _company("dead", CompanyStatus.ARCHIVED)
    root = _user("root", superuser=True, status=UserStatus.SUSPENDED)
    assert interface.user_may_enter_company(root.id, "dead") is False


@pytest.mark.django_db
def test_superuser_still_needs_membership_in_active_company():
    """Асимметрия намеренная (спека §13 п. 2): в действующую компанию —
    как прежде, по членству."""
    _company("live")
    root = _user("root", superuser=True)
    assert interface.user_may_enter_company(root.id, "live") is False


@pytest.mark.django_db
def test_default_company_skips_archived():
    dead = _company("a-dead", CompanyStatus.ARCHIVED)
    live = _company("b-live")
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    CompanyMembership.objects.create(user_id=alice.id, company=live)
    assert interface.default_company_slug(alice.id) == "b-live"


@pytest.mark.django_db
def test_default_company_is_none_when_every_membership_is_archived():
    dead = _company("dead", CompanyStatus.ARCHIVED)
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    assert interface.default_company_slug(alice.id) is None


@pytest.mark.django_db
def test_is_archived():
    _company("dead", CompanyStatus.ARCHIVED)
    _company("live")
    assert interface.is_archived("dead") is True
    assert interface.is_archived("live") is False
    # Незаведённый slug — не архив: спрятать опечатку пропуском нельзя,
    # её уронит тот, кто полезет в схему.
    assert interface.is_archived("no-such") is False


@pytest.mark.django_db
def test_migratable_company_slugs_include_archived():
    _company("b-dead", CompanyStatus.ARCHIVED)
    _company("a-live")
    assert interface.migratable_company_slugs(fresh=True) == ["a-live", "b-dead"]
    assert interface.active_company_slugs(fresh=True) == ["a-live"]
