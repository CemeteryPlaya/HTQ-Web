"""Юнит-тесты ``apps.hr.rbac`` — единственной модели прав кадрового домена.

Задача 9 блока I. HTTP-тесты соседних файлов проверяют ручки; здесь —
чистая логика ``NodeAccess`` без HTTP: перевод старого ключа в узел+признаки
по ``legacy_roles.KEY_TO_NODE``, требование ВСЕХ признаков, область, честная
пустота без ролей и без компании, суперпользователь. Ровно те свойства,
которые раньше держали юнит-тесты ``HRAccess`` (``test_hr_access.py`` до
задачи 9), только у нового носителя.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client

from apps.access import interface as access_interface
from apps.access.services import resolve as access_resolve
from apps.access.tests.helpers import assign, auth, grant, superuser_token, token
from apps.hr import permissions as legacy
from apps.hr import rbac
from apps.hr.legacy_roles import DEFERRED_KEYS
from htqweb.authn.jwt import decode_token

USER_ID = 7  # см. helpers.token()
HR = "/api/hr/v1"


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


# ── Один расчёт ролей на запрос (задача 14 блока I.2, R8) ───────────────────
#
# Гейт ``api_view(module=, level=)`` считает роли, чтобы узнать уровень
# модуля, и кладёт расчёт в ``request.access_resolution`` тройкой
# (компания, user_id, контекст); ``NodeAccess`` той же ручки берёт его оттуда, а не
# считает второй раз. Без этого каждая кадровая ручка с узловой проверкой
# платила за роли дважды — по три запроса и переключению схемы на
# компании-предки каждый раз.


def _company_headers(tok: str, company: str) -> dict:
    return {"HTTP_X_HTQ_COMPANY": company, **auth(tok)}


def _counting(target, name):
    """Патч ``target.name``, считающий вызовы и зовущий оригинал."""
    calls = []
    original = getattr(target, name)

    def counting(*a, **kw):
        calls.append(a)
        return original(*a, **kw)

    return patch.object(target, name, counting), calls


@pytest.mark.django_db
def test_roles_are_resolved_once_per_request(company_row):
    """Гейт и узловая проверка используют ОДИН расчёт ролей.

    ``GET /employees/users/`` стоит под ``module="hr", level="read"`` и сразу
    за гейтом спрашивает ``NodeAccess.has(USERS_LIST)`` — ровно та пара, что
    считала роли дважды."""
    assign(company_row, USER_ID, "hr.accounts", "view")
    patcher, calls = _counting(access_resolve, "resolve_for")
    with patcher:
        resp = Client().get(f"{HR}/employees/users/",
                            **_company_headers(token(company=company_row), company_row))
    assert resp.status_code == 200, resp.content
    assert len(calls) == 1, f"расчётов ролей: {len(calls)}"


@pytest.mark.django_db
def test_superuser_resolution_none_is_reused_not_recomputed(company_row):
    """``resolution()`` суперпользователю отдаёт ``None`` — и это ПОСЧИТАННЫЙ
    ответ, а не «не считали»: ``NodeAccess`` за гейтом не должен спрашивать
    ``resolution()`` второй раз. Различает их сам факт наличия пары в
    запросе, а не значение контекста."""
    patcher, calls = _counting(access_interface, "resolution")
    roles_patcher, role_calls = _counting(access_resolve, "resolve_for")
    with patcher, roles_patcher:
        resp = Client().get(
            f"{HR}/employees/users/",
            **_company_headers(superuser_token(company=company_row), company_row))
    assert resp.status_code == 200, resp.content
    assert len(calls) == 1, f"вызовов resolution(): {len(calls)}"
    assert role_calls == []


@pytest.mark.django_db
def test_handle_without_gate_resolves_roles_itself(company_row, employee, account):
    """Ручка самообслуживания (``/employees/me/card``) гейта модуля не имеет —
    пары в запросе нет, и ``NodeAccess`` считает роли сам, ровно один раз."""
    from htqweb.authn.jwt import issue_token_pair

    tok = issue_token_pair(account, company_slug=company_row)["access"]
    patcher, calls = _counting(access_resolve, "resolve_for")
    with patcher:
        resp = Client().get(f"{HR}/employees/me/card",
                            **_company_headers(tok, company_row))
    assert resp.status_code == 200, resp.content
    assert resp.json()["id"] == employee.id
    assert len(calls) == 1, f"расчётов ролей: {len(calls)}"


@pytest.mark.django_db
def test_cached_resolution_of_another_company_is_not_reused(company_row):
    """Расчёт годится только для той компании, для которой сделан: пара с
    чужой компанией в запросе игнорируется, роли считаются заново."""
    assign(company_row, USER_ID, "hr.employees", "view")
    payload = _payload(company=company_row)
    foreign = access_interface.resolution(payload, "some-other-co")
    request = SimpleNamespace(token=payload,
                              access_resolution=("some-other-co", USER_ID, foreign))
    access = rbac.NodeAccess(payload, company_row, request=request)
    assert access.has(legacy.EMPLOYEES_VIEW)


@pytest.mark.django_db
def test_cached_resolution_of_the_same_company_is_reused(company_row):
    """Пара той же компании берётся как есть — ``resolve_for`` не зовётся."""
    assign(company_row, USER_ID, "hr.employees", "view")
    payload = _payload(company=company_row)
    cached = access_interface.resolution(payload, company_row)
    request = SimpleNamespace(token=payload, access_resolution=(company_row, USER_ID, cached))
    patcher, calls = _counting(access_resolve, "resolve_for")
    with patcher:
        access = rbac.NodeAccess(payload, company_row, request=request)
        assert access.has(legacy.EMPLOYEES_VIEW)
        assert access.scope == ("company", None)
    assert calls == []


@pytest.mark.django_db
def test_cached_resolution_of_another_token_is_not_reused(company_row):
    """Расчёт привязан и к токену (блок I.2, B3): ``NodeAccess`` с ДРУГИМ
    токеном на том же запросе и в той же компании считает роли сам, а не
    берёт чужие. Иначе проверка «от имени» другого пользователя внутри ручки
    получила бы права вызывающего."""
    assign(company_row, USER_ID, "hr.employees", "view")
    caller = _payload(company=company_row)
    cached = access_interface.resolution(caller, company_row)
    request = SimpleNamespace(token=caller, access_resolution=(company_row, USER_ID, cached))

    other = _payload(company=company_row, user_id=8, sub="8")
    patcher, calls = _counting(access_resolve, "resolve_for")
    with patcher:
        access = rbac.NodeAccess(other, company_row, request=request)
        # У пользователя 8 ролей нет: чужой расчёт открыл бы ему EMPLOYEES_VIEW.
        assert not access.has(legacy.EMPLOYEES_VIEW)
    assert len(calls) == 1, f"расчётов ролей: {len(calls)}"
