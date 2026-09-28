"""Кто несёт признак на узле — ``access.interface.holders_of`` (БЗО, этап 2 A,
задача 3): получатели уведомлений «всем, кто может…».

Обратная сторона ``flags_for``: через должность, личное назначение и
обслуживающую должность предка, с наследованием глубины от предка узла и
запретом пустой строкой. Итог — только участники компании с действующей
учёткой.
"""

from __future__ import annotations

import datetime

import pytest

from apps.access import interface
from apps.access.models import PositionRole, Role, RoleAssignment, RolePermission, ScopeKind
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company

NODE = "bpp.requests.all"


def _account(user_id: int) -> None:
    User.objects.get_or_create(id=user_id, defaults={
        "username": f"u{user_id}", "email": f"u{user_id}@htq.test", "password": "x",
        "status": UserStatus.ACTIVE})


def _member(slug: str, user_id: int) -> None:
    _account(user_id)
    CompanyMembership.objects.get_or_create(company=Company.objects.get(slug=slug),
                                            user_id=user_id)


def _role(code: str, rows: dict[str, tuple[str, ...]]) -> Role:
    role = Role.objects.create(code=code, title=code)
    for node, flags in rows.items():
        RolePermission.objects.create(role=role, node=node,
                                      **{f"can_{flag}": True for flag in flags})
    return role


def _personal(slug: str, user_id: int, role: Role) -> None:
    RoleAssignment.objects.create(company_slug=slug, user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)


def _position_holder(slug: str, user_id: int, role: Role, *, weight: int,
                     serves: bool = False) -> None:
    """Кадровая карточка ``user_id`` на должности в схеме ``slug``; роль —
    должности (``PositionRole`` компании ``slug``)."""
    from apps.hr.models import Department, Employee, Position

    _account(user_id)
    with use_company(slug):
        dep = Department.objects.create(name=f"Отдел-{weight}", path=f"ho-{weight}")
        pos = Position.objects.create(title=f"Должность-{weight}", department=dep,
                                      weight=weight, serves_subsidiaries=serves)
        Employee.objects.create(
            first_name="Имя", last_name=f"Держатель{weight}", email=f"h{weight}@htq.test",
            department=dep, position=pos, hire_date=datetime.date(2024, 1, 9),
            user_id=user_id)
    PositionRole.objects.create(company_slug=slug, position_id=pos.id, role=role)


@pytest.mark.django_db
def test_found_through_position_and_personal_assignment(company_schema):
    """Строка только на ``bpp.requests`` — узел ``bpp.requests.all`` её
    наследует, как у ``flags_for``. Не участник компании и участник без
    роли в список не попадают."""
    slug = company_schema["slug"]
    role = _role("t-holders-view", {"bpp.requests": ("view",)})
    _position_holder(slug, 601, role, weight=1)
    _member(slug, 601)
    _personal(slug, 602, role)
    _member(slug, 602)
    _personal(slug, 603, role)       # роль есть, членства нет
    _account(603)
    _member(slug, 604)               # членство есть, роли нет

    assert interface.holders_of(NODE, "view", slug) == [601, 602]
    assert interface.holders_of("bpp.requests", "view", slug) == [601, 602]
    assert interface.holders_of(NODE, "edit", slug) == []


@pytest.mark.django_db
def test_empty_row_on_the_node_is_a_deny(company_schema):
    """Пустая строка на узле перекрывает право предка: держателя такой роли
    нет. Роли складываются объединением — другая роль с явным правом даёт
    признак."""
    slug = company_schema["slug"]
    denied = _role("t-holders-deny", {"bpp": ("view",), NODE: ()})
    allowed = _role("t-holders-allow", {NODE: ("view",)})
    _personal(slug, 611, denied)
    _member(slug, 611)
    assert interface.holders_of(NODE, "view", slug) == []
    assert interface.holders_of("bpp.requests", "view", slug) == [611]

    _personal(slug, 612, denied)
    _personal(slug, 612, allowed)
    _member(slug, 612)
    assert interface.holders_of(NODE, "view", slug) == [612]


@pytest.mark.django_db
def test_other_company_is_not_seen(company_schema):
    slug = company_schema["slug"]
    other = Company.objects.create(slug="t-holders-other", name="Другая",
                                   kind=CompanyKind.SERVICE)
    role = _role("t-holders-other", {NODE: ("view",)})
    _personal(other.slug, 621, role)
    _member(slug, 621)
    _member(other.slug, 621)

    assert interface.holders_of(NODE, "view", slug) == []
    assert interface.holders_of(NODE, "view", other.slug) == [621]


@pytest.mark.django_db(transaction=True)
def test_serving_position_of_an_ancestor_counts(two_company_schemas):
    """Обслуживающая должность холдинга несёт роли в дочернюю (блок C) —
    её держатель, если он участник дочерней компании, в списке."""
    holding, subsidiary = two_company_schemas
    child = Company.objects.get(slug=subsidiary)
    child.parent = Company.objects.get(slug=holding)
    child.save(update_fields=["parent"])

    role = _role("t-holders-serving", {NODE: ("view",)})
    _position_holder(holding, 631, role, weight=3, serves=True)
    assert interface.holders_of(NODE, "view", subsidiary) == []  # не участник
    _member(subsidiary, 631)
    assert interface.holders_of(NODE, "view", subsidiary) == [631]

    # Необслуживающая должность холдинга в дочерней прав не даёт.
    _position_holder(holding, 632, role, weight=4, serves=False)
    _member(subsidiary, 632)
    assert interface.holders_of(NODE, "view", subsidiary) == [631]


@pytest.mark.django_db
def test_unknown_flag_is_an_error(company_schema):
    with pytest.raises(ValueError):
        interface.holders_of(NODE, "approve", company_schema["slug"])
