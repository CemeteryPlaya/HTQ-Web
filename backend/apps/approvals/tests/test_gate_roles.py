"""Гейт модуля ``approvals`` на НАСТОЯЩИХ ролях (блок L, задача 9).

``employee-basic`` (узлы ``access/0004`` + ``0011``) агрегируется в ``write``
модуля ``approvals`` — свои заявки, чтение справочников/шаблонов и подача
заявки ему открыты; заведение проекта (бывший ``admin=True``, теперь
``level="admin"``) — нет. ``is_staff`` без роли на бывшую админскую ручку
больше не пускает (решение заказчика 2); держатель ``services-admin``
(``access/0012``) — пускает.
"""

import pytest
from django.test import Client

from apps.approvals.tests.helpers import BASE, post_json, token

COMPANY = "t-approvals-gate"


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
def test_employee_basic_reads_templates_to_file_a_request():
    assert Client().get(f"{BASE}/templates/", **_as("employee-basic", 361)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_may_not_create_a_project():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **_as("employee-basic", 362))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_create_a_project():
    headers = _as("employee-basic", 363)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=363, sub="363", company=COMPANY, is_staff=True, is_admin=True)
    assert post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_creates_a_project():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **_as("services-admin", 364))
    assert resp.status_code != 403
