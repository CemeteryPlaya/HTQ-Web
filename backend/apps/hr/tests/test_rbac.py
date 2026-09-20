"""Юнит-тесты ``apps.hr.rbac`` — единственной модели прав кадрового домена.

Задача 9 блока I. HTTP-тесты соседних файлов проверяют ручки; здесь —
чистая логика ``NodeAccess`` без HTTP: перевод старого ключа в узел+признаки
по ``legacy_roles.KEY_TO_NODE``, требование ВСЕХ признаков, область, честная
пустота без ролей и без компании, суперпользователь. Ровно те свойства,
которые раньше держали юнит-тесты ``HRAccess`` (``test_hr_access.py`` до
задачи 9), только у нового носителя.
"""

from __future__ import annotations

import pytest

from apps.access.tests.helpers import assign, grant, token
from apps.hr import permissions as legacy
from apps.hr import rbac
from apps.hr.legacy_roles import DEFERRED_KEYS
from htqweb.authn.jwt import decode_token

USER_ID = 7  # см. helpers.token()


def _payload(**over):
    return decode_token(token(**over))


@pytest.mark.django_db
def test_has_requires_every_flag_of_the_key(company_row):
    """``EMPLOYEES_VIEW`` → ``hr.employees`` VIEW; ``EMPLOYEES_EDIT`` — тот же
    узел, но признаков два: одного ``view`` не хватает."""
    assign(company_row, USER_ID, "hr.employees", "view")
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert access.has(legacy.EMPLOYEES_VIEW)
    assert not access.has(legacy.EMPLOYEES_EDIT)
    assert not access.has(legacy.EMPLOYEES_DELETE)


@pytest.mark.django_db
def test_has_walks_up_to_the_nearest_ancestor(company_row):
    """Глубина наследуется вниз (``resolve._nearest``): ``hr.employees: full``
    даёт и ``hr.employees.salary`` — это свойство резолвера ``apps.access``,
    а не этого модуля; здесь оно только зафиксировано, потому что именно оно
    даёт «расхождение 2» отчёта задачи 9 у засеянных ролей."""
    assign(company_row, USER_ID, "hr.employees", "full")
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert access.has(legacy.CARD_FINANCIAL_EDIT)


@pytest.mark.django_db
def test_explicit_deny_in_the_same_role_beats_inheritance(company_row):
    """Пустой набор на узле — запрет, перекрывающий право предка — но только
    внутри ТОЙ ЖЕ роли: роли складываются объединением."""
    from apps.access.models import Role, RoleAssignment, ScopeKind

    role = Role.objects.create(code="t-no-salary", title="t-no-salary")
    grant(role, "hr.employees", "full")
    grant(role, "hr.employees.salary", "none")
    RoleAssignment.objects.create(company_slug=company_row, user_id=USER_ID, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert access.has(legacy.EMPLOYEES_EDIT)
    assert not access.has(legacy.CARD_FINANCIAL_VIEW)


@pytest.mark.django_db
def test_no_roles_means_nothing_and_no_scope(company_row):
    """Ручки без гейта (``/employees/me/card``) зовут этот же объект для
    вызывающего без единой роли: ответ — честная пустота, не исключение."""
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert not access.has(legacy.EMPLOYEES_VIEW)
    assert access.scope == ("none", None)
    assert not access.can_read_all
    assert access.department_id is None
    assert not access.can_see_department(1)


@pytest.mark.django_db
def test_no_company_means_nothing(company_row):
    assign(company_row, USER_ID, "hr.employees", "full")
    access = rbac.NodeAccess(_payload(), None)
    assert not access.has(legacy.EMPLOYEES_VIEW)
    assert access.scope == ("none", None)


@pytest.mark.django_db
def test_company_scope_sees_every_department(company_row):
    assign(company_row, USER_ID, "hr.employees", "view")
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert access.scope == ("company", None)
    assert access.can_read_all
    assert access.can_see_department(1) and access.can_see_department(999)


@pytest.mark.django_db
def test_department_scope_sees_only_its_own(company_row):
    from apps.access.models import Role, RoleAssignment, ScopeKind

    role = Role.objects.create(code="t-dep-view", title="t-dep-view")
    grant(role, "hr.employees", "view")
    RoleAssignment.objects.create(company_slug=company_row, user_id=USER_ID, role=role,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=42)
    access = rbac.NodeAccess(_payload(company=company_row), company_row)
    assert access.scope == ("department", 42)
    assert not access.can_read_all
    assert access.department_id == 42
    assert access.can_see_department(42)
    assert not access.can_see_department(43)
    assert not access.can_see_department(None)


@pytest.mark.django_db
def test_superuser_has_everything_without_roles(company_row):
    access = rbac.NodeAccess(_payload(is_superuser=True, company=company_row), company_row)
    assert access.has(legacy.EMPLOYEES_DELETE)
    assert access.has(legacy.IDENTITY_FORCE)
    assert access.can_read_all


@pytest.mark.django_db
def test_staff_without_roles_has_nothing(company_row):
    """Старый lead-wildcard по ``is_elevated`` снят без замены: ``is_staff``
    без роли — не суперпользователь, резолвер ``apps.access`` его не коротит."""
    access = rbac.NodeAccess(_payload(is_staff=True, is_admin=True, company=company_row), company_row)
    assert not access.has(legacy.EMPLOYEES_VIEW)
    assert access.scope == ("none", None)


def test_deferred_key_is_a_programming_error():
    """Ключ без узла (чужая аппка, ``DEFERRED_KEYS``) — ``KeyError``, не тихий
    ``False``: проверять его здесь нечем, и молчаливый отказ спрятал бы
    ошибку программиста за отказом в доступе."""
    access = rbac.NodeAccess(_payload(), None)
    (key,) = DEFERRED_KEYS
    with pytest.raises(KeyError):
        access.has(key)
