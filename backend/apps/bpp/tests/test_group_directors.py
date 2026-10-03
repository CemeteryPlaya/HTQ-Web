"""``bpp_group_directors``: директора холдинга в дочерних компаниях (A8.1, D-S7-8).

Две настоящие схемы (``two_company_schemas``): первая — холдинг, вторая —
дочерняя. Кадровая карточка ФД лежит в схеме холдинга; роль ``bpp-fd``
достаётся ему в дочерней компании по ПРИЗНАКУ ``serves_subsidiaries`` (через
``apps.access.services.inheritance``), а токен на поддомен дочерней —
только после ``CompanyMembership``: команда делает обе половины.
"""

from __future__ import annotations

import datetime
import io

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command

from apps.access import interface as access
from apps.access.models import PositionRole, Role, RolePermission
from apps.access.tests.helpers import token as make_token
from apps.companies import interface as companies
from apps.companies.models import Company, CompanyKind, CompanyMembership, CompanyStatus
from apps.hr.models import Department, Employee, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token
from htqweb.tenancy.db import use_company

FD_USER, GD_USER = 7101, 7102

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def group(two_company_schemas):
    holding, child = two_company_schemas
    Company.objects.filter(slug=holding).update(kind=CompanyKind.HOLDING)
    Company.objects.filter(slug=child).update(parent=Company.objects.get(slug=holding))
    cache.clear()
    yield holding, child
    cache.clear()


def _director(holding: str, title: str, user_id: int, *, role: Role | None) -> Position:
    User.objects.create(id=user_id, username=f"d{user_id}", email=f"d{user_id}@htq.test",
                        password="x", status=UserStatus.ACTIVE)
    with use_company(holding):
        dep = Department.objects.create(name=f"Отдел-{user_id}", path=f"d-{user_id}")
        position = Position.objects.create(title=title, department=dep, weight=user_id)
        Employee.objects.create(
            first_name="Имя", last_name="Фамилия", email=f"e{user_id}@htq.test",
            department=dep, position=position,
            hire_date=datetime.date(2024, 1, 9), user_id=user_id)
    if role is not None:
        PositionRole.objects.create(company_slug=holding, position_id=position.id, role=role)
    return position


def _fd_role() -> Role:
    role, _ = Role.objects.get_or_create(code="bpp-fd", defaults={"title": "ФД"})
    for node in ("bpp.invoices", "bpp.budgets"):
        RolePermission.objects.update_or_create(
            role=role, node=node,
            defaults={"can_view": True, "can_create": False, "can_edit": False,
                      "can_delete": False})
    return role


def _company(slug: str, *, parent: str | None, status=CompanyStatus.ACTIVE) -> None:
    """Строка реестра без схемы: членство живёт в ``public``, схема не нужна."""
    Company.objects.create(
        slug=slug, name=slug, kind=CompanyKind.SERVICE, status=status,
        parent=Company.objects.get(slug=parent) if parent else None)
    cache.clear()


def _run(holding: str, *args) -> str:
    out = io.StringIO()
    call_command("bpp_group_directors", "--holding", holding, *args, stdout=out)
    return out.getvalue()


def _level(user_id: int, company: str) -> str:
    payload = decode_token(make_token(user_id=user_id, sub=str(user_id), company=company))
    return access.permission_level(payload, "bpp", company)


def test_command_marks_positions_and_grants_membership(group):
    holding, child = group
    position = _director(holding, "Финансовый директор", FD_USER, role=_fd_role())
    assert _level(FD_USER, child) == "none"  # признака ещё нет

    out = _run(holding)

    with use_company(holding):
        assert Position.objects.get(pk=position.pk).serves_subsidiaries is True
    assert CompanyMembership.objects.filter(company__slug=child, user_id=FD_USER).exists()
    assert "признак выставлен" in out
    # роли ФД холдинга действуют в дочерней по наследованию
    assert _level(FD_USER, child) != "none"
    assert "разрывов: 0" in out


def test_command_is_idempotent(group):
    holding, child = group
    _director(holding, "Финансовый директор", FD_USER, role=_fd_role())
    _run(holding)
    out = _run(holding)

    assert "признак уже был" in out
    assert "членство выдано 0, уже было 1" in out
    assert CompanyMembership.objects.filter(company__slug=child, user_id=FD_USER).count() == 1


def test_dry_run_writes_nothing(group):
    holding, child = group
    position = _director(holding, "Финансовый директор", FD_USER, role=_fd_role())

    out = _run(holding, "--dry-run")

    with use_company(holding):
        assert Position.objects.get(pk=position.pk).serves_subsidiaries is False
    assert not CompanyMembership.objects.filter(company__slug=child).exists()
    assert f"выдать членство в {child}: пользователь #{FD_USER}" in out
    assert "разрывов: 1" in out


def test_holder_without_role_is_reported_as_a_gap(group):
    """Признак и членство есть, а должности роль ``bpp-*`` не выдана — директор
    попал бы в дочернюю без прав: разрыв печатается, а не молчит."""
    holding, child = group
    _director(holding, "Финансовый директор", FD_USER, role=None)

    out = _run(holding)

    assert f"разрыв: Финансовый директор, пользователь #{FD_USER}" in out
    assert "bpp_assign_roles" in out
    assert "разрывов: 1" in out


def test_explicit_position_id_overrides_the_title(group):
    holding, child = group
    position = _director(holding, "ФД (иначе назван)", GD_USER, role=_fd_role())

    out = _run(holding, "--fd", str(position.id))

    with use_company(holding):
        assert Position.objects.get(pk=position.pk).serves_subsidiaries is True
    assert CompanyMembership.objects.filter(company__slug=child, user_id=GD_USER).exists()
    assert "нет должности: Технический директор" in out


def test_only_the_directors_are_marked_not_other_positions(group):
    holding, _ = group
    _director(holding, "Финансовый директор", FD_USER, role=_fd_role())
    other = _director(holding, "Главный бухгалтер", GD_USER, role=_fd_role())

    _run(holding)

    with use_company(holding):
        assert Position.objects.get(pk=other.pk).serves_subsidiaries is False


def test_non_holding_company_is_an_error(group):
    _, child = group
    with pytest.raises(CommandError, match="не холдинг"):
        _run(child)


def test_unknown_company_is_an_error():
    with pytest.raises(CommandError, match="не найдена"):
        _run("no-such-company")


def test_only_active_companies_below_the_holding_get_membership(group):
    """Компания вне дерева холдинга и архивная дочерняя членства не получают."""
    holding, child = group
    _company("outsider", parent=None)
    _company("old-child", parent=holding, status=CompanyStatus.ARCHIVED)
    _director(holding, "Финансовый директор", FD_USER, role=_fd_role())

    _run(holding)

    assert CompanyMembership.objects.filter(company__slug=child, user_id=FD_USER).exists()
    assert not CompanyMembership.objects.filter(
        company__slug__in=("outsider", "old-child")).exists()


def test_archived_middle_company_does_not_cut_the_tree(group):
    """Роли наследуются и через архивного предка — значит, и членство нужно
    «внуку» за архивной промежуточной компанией."""
    holding, child = group
    _company("mid", parent=holding, status=CompanyStatus.ARCHIVED)
    _company("grandchild", parent="mid")

    assert companies.descendant_slugs(holding) == sorted([child, "grandchild"])


def test_role_without_the_module_is_a_gap(group):
    """Должность несёт роли, но не ``bpp-*`` (только кадровую): для БЗО это
    тот же разрыв, что и «ролей нет»."""
    holding, child = group
    hr_role, _ = Role.objects.get_or_create(code="hr-junior", defaults={"title": "HR"})
    RolePermission.objects.update_or_create(
        role=hr_role, node="hr.employees",
        defaults={"can_view": True, "can_create": False, "can_edit": False,
                  "can_delete": False})
    _director(holding, "Финансовый директор", FD_USER, role=hr_role)

    out = _run(holding)

    assert f"разрыв: Финансовый директор, пользователь #{FD_USER} не несёт ролей bpp-*" in out
    assert "разрывов: 1" in out


def test_dry_run_reports_an_inactive_position(group):
    holding, child = group
    position = _director(holding, "Финансовый директор", FD_USER, role=_fd_role())
    with use_company(holding):
        Position.objects.filter(pk=position.pk).update(is_active=False)

    out = _run(holding, "--dry-run", "--fd", str(position.id))

    assert f"нет активной должности: Финансовый директор (#{position.id})" in out
    assert not CompanyMembership.objects.exists()
