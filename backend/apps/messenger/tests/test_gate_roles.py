"""Гейт модуля ``messenger`` на НАСТОЯЩИХ ролях (блок L, задача 6).

``employee-basic`` (узлы ``access/0004`` + ``0011``) агрегируется в ``write``
модуля ``messenger`` — свои комнаты, переписка и состав группы ему открыты,
модерация (``/admin/*``, бывшие ``admin=True``, теперь ``level="admin"``) —
нет. ``is_staff`` без роли модерацию больше не открывает (решение заказчика
2); держатель ``services-admin`` (``access/0012``) — открывает.
"""

import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-messenger-gate"
BASE = "/api/messenger/v1"


def _as(role_code: str, user_id: int) -> dict:
    """Заголовки вызывающего с одной настоящей ролью в компании теста."""
    from apps.access.models import Role, RoleAssignment, ScopeKind
    from apps.companies.models import Company, CompanyKind

    Company.objects.get_or_create(slug=COMPANY, defaults={
        "name": COMPANY, "kind": CompanyKind.SERVICE})
    RoleAssignment.objects.get_or_create(
        company_slug=COMPANY, user_id=user_id, role=Role.objects.get(code=role_code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    return {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=user_id, sub=str(user_id), company=COMPANY)}",
            "HTTP_X_HTQ_COMPANY": COMPANY}


@pytest.mark.django_db
def test_employee_basic_lists_his_rooms():
    assert Client().get(f"{BASE}/rooms", **_as("employee-basic", 321)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_may_not_moderate():
    assert Client().get(f"{BASE}/admin/rooms", **_as("employee-basic", 322)).status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_moderate():
    headers = _as("employee-basic", 323)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=323, sub="323", company=COMPANY, is_staff=True, is_admin=True)
    assert Client().get(f"{BASE}/admin/rooms", **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_moderates():
    assert Client().get(f"{BASE}/admin/rooms", **_as("services-admin", 324)).status_code != 403
