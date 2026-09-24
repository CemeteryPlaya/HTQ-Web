"""Гейт ``module="conference"`` с НАСТОЯЩИМИ ролями из миграций (блок L).

Бывших ``admin=True`` в аппке нет, поэтому тестов ``is_staff``/
``services-admin`` на админскую ручку здесь нет: пять ручек чтения стоят под
``conference:read``, видимость конкретной встречи режет ``may_view``.
"""

import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-conference-gate"
BASE = "/api/conference/v1"


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
def test_employee_basic_reads_his_history():
    assert Client().get(f"{BASE}/sessions", **_as("employee-basic", 311)).status_code != 403


@pytest.mark.django_db
def test_no_role_no_history():
    headers = {"HTTP_AUTHORIZATION": "Bearer " + token(user_id=312, sub="312", company=COMPANY),
               "HTTP_X_HTQ_COMPANY": COMPANY}
    from apps.companies.models import Company, CompanyKind
    Company.objects.get_or_create(slug=COMPANY, defaults={"name": COMPANY,
                                                          "kind": CompanyKind.SERVICE})
    assert Client().get(f"{BASE}/sessions", **headers).status_code == 403
