"""Задача 7 блока C: список внешних держателей прав.

Дочерняя компания должна уметь ответить «кто ещё видит наши данные» — обход
идёт по компаниям-предкам (зеркало ``inheritance.ancestors_of``) и ищет тех,
чья должность в предке помечена обслуживающей дочерние компании и реально
несёт роли. Видимость самого списка (``Company.show_external_holders``,
решение заказчика 4) — забота ``apps.companies`` и её HTTP-гейта, а НЕ этого
модуля: он безусловно отвечает на вопрос «кто держит права» и не знает о
настройке видимости вовсе (см. ``apps/companies/tests/test_external_holders_api.py``
для гейта).

Схемы — настоящие (``two_company_schemas`` из корневого ``conftest.py``), как
в ``test_inheritance.py``: кадровая карточка обязана лечь в СВОЮ схему через
``use_company``, иначе тест доказывал бы совпадение со схемой по умолчанию, а
не обход чужой схемы.
"""

from __future__ import annotations

import datetime

import pytest

from apps.access.models import PositionRole, Role
from apps.access.services import holders
from apps.access.tests.helpers import grant as grant_permission
from apps.companies.models import Company, CompanyKind
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company


def _link(child_slug: str, parent_slug: str) -> None:
    child = Company.objects.get(slug=child_slug)
    child.parent = Company.objects.get(slug=parent_slug)
    child.save(update_fields=["parent"])


def _serving_position(company_slug: str, user_id: int, role: Role, *, weight: int) -> None:
    """Кадровая карточка ``user_id`` в схеме ``company_slug`` с обслуживающей
    должностью, реально несущей ``role`` (копия ``_grant_serving_position``
    из ``test_inheritance.py``, без промежуточного объекта должности).

    ``hr.resolve_position_users`` (в отличие от ``get_employee_brief``,
    которым пользуется ``inheritance.inherit``) дополнительно требует ЖИВОЙ
    аккаунт платформы — держатель без него не может войти и не может ничем
    воспользоваться, поэтому и не должен попасть в список внешних держателей.
    Учётка заводится в ``public`` — ``apps.users`` не тенантная аппка, схема
    компании здесь ни при чём.
    """
    from apps.hr.models import Department, Employee, Position

    User.objects.create(id=user_id, username=f"u{user_id}", email=f"u{user_id}@htq.test",
                        password="x", status=UserStatus.ACTIVE)

    with use_company(company_slug):
        dep = Department.objects.create(name=f"Отдел-{weight}", path=f"root-{weight}")
        pos = Position.objects.create(
            title=f"Главбух-{weight}", department=dep, weight=weight,
            serves_subsidiaries=True,
        )
        Employee.objects.create(
            first_name="Имя", last_name="Фамилия", email=f"e-{weight}@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=user_id,
        )
        PositionRole.objects.create(company_slug=company_slug, position_id=pos.id, role=role)


def _ordinary_employee(company_slug: str, user_id: int, *, weight: int) -> None:
    """Обычный сотрудник БЕЗ обслуживающей должности — контрольная группа:
    должен остаться невидим для ``external_holders`` компании, где сам
    работает (обход идёт вверх по предкам, не по самой компании)."""
    from apps.hr.models import Department, Employee, Position

    with use_company(company_slug):
        dep = Department.objects.create(name=f"Отдел-до-{weight}", path=f"do-{weight}")
        pos = Position.objects.create(title=f"Инженер-{weight}", department=dep, weight=weight)
        Employee.objects.create(
            first_name="Пётр", last_name="Сидоров", email=f"p-{weight}@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=user_id,
        )


@pytest.mark.django_db(transaction=True)
def test_external_holders_lists_serving_ancestor_not_ordinary_subsidiary_employee(
        two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-ext-holder", title="Роль главбуха")
    grant_permission(role, "hr", "read")

    _serving_position(holding, 501, role, weight=1)
    _ordinary_employee(subsidiary, 502, weight=1)

    rows = holders.external_holders(subsidiary)

    assert len(rows) == 1
    row = rows[0]
    assert row["full_name"] == "Фамилия Имя"
    assert row["home_company"] == holding  # фикстура заводит name == slug
    assert row["position"] == "Главбух-1"
    assert row["modules"] == [{"module": "hr", "level": "read"}]


@pytest.mark.django_db(transaction=True)
def test_external_holders_discloses_only_the_four_named_fields(two_company_schemas):
    """⚠️ Раскрытие данных холдинга дочерней компании — отдаём РОВНО имя,
    домашнюю компанию, должность и уровни модулей. Ни email, ни телефон, ни
    отдел (``_describe`` их знает, но наружу они не идут) наружу не идут."""
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-ext-fields", title="Роль")
    grant_permission(role, "tasks", "write")
    _serving_position(holding, 503, role, weight=2)

    rows = holders.external_holders(subsidiary)
    assert len(rows) == 1
    assert set(rows[0]) == {"full_name", "home_company", "position", "modules"}
    assert set(rows[0]["modules"][0]) == {"module", "level"}


@pytest.mark.django_db(transaction=True)
def test_external_holders_empty_without_any_serving_position(two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)
    assert holders.external_holders(subsidiary) == []


@pytest.mark.django_db(transaction=True)
def test_external_holders_empty_without_role_is_not_a_holder(two_company_schemas):
    """Обслуживающая должность без единой назначенной роли ничего не даёт —
    тот же принцип, что у ``inheritance.inherit`` (задача 5): признак сам по
    себе не право, а лишь канал для ролей должности."""
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    from apps.hr.models import Department, Employee, Position

    with use_company(holding):
        dep = Department.objects.create(name="Отдел-0", path="root-0")
        pos = Position.objects.create(
            title="Без роли", department=dep, weight=9, serves_subsidiaries=True)
        Employee.objects.create(
            first_name="Имя", last_name="Пустой", email="empty@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=504,
        )
    # Должность обслуживает, но ни одной роли ей не назначено — PositionRole
    # пуст, поэтому кандидатов для этой должности не находится вовсе.

    assert holders.external_holders(subsidiary) == []


@pytest.mark.django_db
def test_external_holders_of_a_root_company_is_empty():
    """У компании без предков (вершина дерева) список пуст — обход вверх, и
    предков там нет вовсе (``ancestors_of`` возвращает [])."""
    top = Company.objects.create(slug="t-fixture-ext-top", name="Верх",
                                 kind=CompanyKind.SERVICE)
    assert holders.external_holders(top.slug) == []
