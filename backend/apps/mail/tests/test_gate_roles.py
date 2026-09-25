"""Гейт модуля ``mail`` на НАСТОЯЩИХ ролях (блок L, задача 7).

``employee-basic`` (узел ``mail.messages`` с ``view``, ``access/0004``)
агрегируется в ``read`` модуля ``mail``: ящики и реквизиты сервера (бывшие
``admin=True``, теперь ``level="admin"``) ему закрыты, подсказка настроек
IMAP (``mail:read``) — открыта. ``is_staff`` без роли на бывшую админскую
ручку больше не пускает (решение заказчика 2); держатель ``services-admin``
(``access/0012``) — пускает. Личная почта (accounts/*, oauth/*, письма) —
реестр самообслуживания: гейта у неё нет вовсе.
"""

import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-mail-gate"
BASE = "/api/email/v1"


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
def test_employee_basic_may_not_manage_mailboxes():
    assert Client().get(f"{BASE}/mailboxes/", **_as("employee-basic", 331)).status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_manage_mailboxes():
    headers = _as("employee-basic", 332)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=332, sub="332", company=COMPANY, is_staff=True, is_admin=True)
    assert Client().get(f"{BASE}/mailboxes/", **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_manages_mailboxes():
    assert Client().get(f"{BASE}/mailboxes/", **_as("services-admin", 333)).status_code != 403


@pytest.mark.django_db
def test_own_mail_stays_self_service():
    assert Client().get(f"{BASE}/accounts/", **_as("employee-basic", 334)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_passes_the_imap_hint_gate():
    """Единственная ручка личной почты под гейтом — ``mail:read``, уровень
    ``employee-basic``: подсказка настроек по адресу не должна отпасть."""
    resp = Client().get(f"{BASE}/accounts/connect-imap/?address=me@gmail.com",
                        **_as("employee-basic", 335))
    assert resp.status_code != 403
