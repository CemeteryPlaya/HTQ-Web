"""Роли блока L: уровни employee-basic и services-admin по шести модулям.

Числа выписаны руками из спеки (§4), а не вычислены тем же кодом: тест
обязан поймать узел, который дотянул базовую роль до чужого уровня.
"""
from types import SimpleNamespace

import pytest

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.services import resolve

MODULES = ("media", "conference", "messenger", "mail", "cms", "approvals")

EMPLOYEE_BASIC = {
    "media": "write", "conference": "read", "messenger": "write",
    "mail": "read", "cms": "read", "approvals": "write",
}


def _levels(role_code: str, company: str) -> dict:
    user = SimpleNamespace(user_id=4242, is_superuser=False, email=None)
    RoleAssignment.objects.create(
        company_slug=company, user_id=user.user_id,
        role=Role.objects.get(code=role_code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    perms = resolve.permissions_for(user, company)
    return {m: (perms.get(m) or {}).get("level", "none") for m in MODULES}


def test_employee_basic_levels_match_the_spec(company_row):
    assert _levels("employee-basic", company_row) == EMPLOYEE_BASIC


def test_services_admin_is_admin_everywhere(company_row):
    assert _levels("services-admin", company_row) == {m: "admin" for m in MODULES}


@pytest.mark.django_db
def test_employee_basic_never_deletes_in_block_l_modules():
    role = Role.objects.get(code="employee-basic")
    deleting = [p.node for p in role.permissions.all()
                if p.can_delete and p.node.split(".")[0] in MODULES]
    assert deleting == []


@pytest.mark.django_db
def test_services_admin_is_a_shared_system_role():
    role = Role.objects.get(code="services-admin")
    assert role.is_system is True
    assert (role.company_slug or "") == ""
    assert role.title == "Администратор сервисов"


@pytest.mark.django_db(transaction=True)
def test_a_spoiler_runs_before_the_reseed_check():
    """Порча для соседнего теста ниже: без неё он мог оказаться ПЕРВЫМ
    транзакционным в прогоне, до единого TRUNCATE, и видел бы строки
    миграций, а не пересев фикстуры. Стирает строки блока L и роль
    services-admin; после этого теста pytest-django к тому же очищает
    public целиком — следующий тест файла идёт по пересеву."""
    from apps.access.models import RolePermission

    RolePermission.objects.filter(
        role__code="employee-basic",
        node__in=["media.files", "messenger.rooms", "conference.history",
                  "approvals.templates"]).delete()
    Role.objects.filter(code="services-admin").delete()
    assert not Role.objects.filter(code="services-admin").exists()


@pytest.mark.django_db(transaction=True)
def test_reseed_restores_block_l_nodes():
    role = Role.objects.get(code="employee-basic")
    nodes = set(role.permissions.values_list("node", flat=True))
    assert {"media.files", "messenger.rooms", "conference.history",
            "approvals.templates"} <= nodes
    assert Role.objects.filter(code="services-admin").exists()
