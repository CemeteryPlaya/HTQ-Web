"""``manage.py company_grant --serving`` — задача 8 блока C.

Закрывает разрыв «признак есть, членства нет»: должность в компании-предке,
помеченная обслуживающей (``apps.access.services.inheritance``, решение
заказчика 1), несёт держателю права в дочерней компании, но БЕЗ
``CompanyMembership`` в этой дочерней компании токен для её поддомена всё
равно не выпустится (``apps.companies.interface.user_may_enter_company``) —
признак сам по себе ничего не открывает. ``--serving`` заводит членство
ровно тем, кого уже видит ``apps.access.interface.serving_holders`` — то же
ядро обхода предков, что и у витрины «внешние держатели прав»
(``apps/access/tests/test_external_holders.py``), поэтому здесь проверяется
сама команда (флаг, идемпотентность, взаимоисключение), а не пересчитывается
обход заново.

Схемы — настоящие (``two_company_schemas`` из корневого ``conftest.py``), как
у соседа: кадровая карточка держателя обязана лечь в СВОЮ схему предка.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.management import CommandError, call_command

from apps.access.models import PositionRole, Role
from apps.access.tests.helpers import grant as grant_permission
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company


def _link(child_slug: str, parent_slug: str) -> None:
    child = Company.objects.get(slug=child_slug)
    child.parent = Company.objects.get(slug=parent_slug)
    child.save(update_fields=["parent"])


def _serving_position(company_slug: str, user_id: int, role: Role, *, weight: int) -> None:
    """Кадровая карточка ``user_id`` в схеме ``company_slug`` с обслуживающей
    должностью, реально несущей ``role`` (копия ``_serving_position`` из
    ``apps/access/tests/test_external_holders.py``)."""
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
    """Обычный сотрудник дочерней компании БЕЗ обслуживающей должности —
    контрольная группа: ``--serving`` не обязан заводить ему членство."""
    from apps.hr.models import Department, Employee, Position

    User.objects.create(id=user_id, username=f"o{user_id}", email=f"o{user_id}@htq.test",
                        password="x", status=UserStatus.ACTIVE)

    with use_company(company_slug):
        dep = Department.objects.create(name=f"Отдел-до-{weight}", path=f"do-{weight}")
        pos = Position.objects.create(title=f"Инженер-{weight}", department=dep, weight=weight)
        Employee.objects.create(
            first_name="Пётр", last_name="Сидоров", email=f"p-{weight}@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=user_id,
        )


@pytest.mark.django_db(transaction=True)
def test_serving_grants_membership_to_ancestor_holder_not_ordinary_employee(two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-cg-serving", title="Роль главбуха")
    grant_permission(role, "hr", "read")

    _serving_position(holding, 601, role, weight=1)
    _ordinary_employee(subsidiary, 602, weight=1)

    call_command("company_grant", "--company", subsidiary, "--serving")

    assert CompanyMembership.objects.filter(company__slug=subsidiary, user_id=601).exists()
    assert not CompanyMembership.objects.filter(company__slug=subsidiary, user_id=602).exists()


@pytest.mark.django_db(transaction=True)
def test_serving_is_idempotent(two_company_schemas):
    """Повторный запуск не плодит вторую строку членства и не падает —
    ``grant_membership`` уже ``get_or_create`` по ``uniq_membership``."""
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-cg-idem", title="Роль")
    grant_permission(role, "tasks", "write")
    _serving_position(holding, 603, role, weight=2)

    call_command("company_grant", "--company", subsidiary, "--serving")
    call_command("company_grant", "--company", subsidiary, "--serving")

    assert CompanyMembership.objects.filter(
        company__slug=subsidiary, user_id=603,
    ).count() == 1


@pytest.mark.django_db(transaction=True)
def test_serving_without_any_holder_warns_and_grants_nothing(two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    call_command("company_grant", "--company", subsidiary, "--serving")

    assert not CompanyMembership.objects.filter(company__slug=subsidiary).exists()


@pytest.mark.django_db
def test_serving_rejected_together_with_user():
    company = Company.objects.create(slug="cg-serving-conflict", name="X",
                                     kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError):
        call_command("company_grant", "--company", company.slug,
                     "--serving", "--user", "1")


@pytest.mark.django_db
def test_serving_rejected_together_with_all_users():
    company = Company.objects.create(slug="cg-serving-all", name="X",
                                     kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError):
        call_command("company_grant", "--company", company.slug,
                     "--serving", "--all-users")
