"""Контракт GET /api/hr/v1/logs/ — паритет с services/hr/app/api/v1/audit.py.

Роутер исходника смонтирован под ``prefix="/logs"`` (комментарий исходника:
"Mounted at `/logs` to match the frontend (`HRLogs.tsx`)" — "audit" осталось
только в имени модуля/модели, НЕ в пути), поэтому путь — /logs/, а не
/audit/.

Форма ответа — голый список dict (никакого пагинационного конверта
{"items":...}), поля буквально как в роутере исходника (list-comprehension
в конце ``get_audit_log``).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.hr.models import AuditLog
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/logs"


@pytest.fixture
def auth(db):
    user = User.objects.create(
        username="loguser", email="loguser@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_list_shape_and_order(auth):
    AuditLog.objects.create(
        entity_type="employee", entity_id=1, action="create", changed_by=7,
    )
    AuditLog.objects.create(
        entity_type="employee", entity_id=1, action="update", changed_by=7,
        old_values={"status": "active"}, new_values={"status": "inactive"},
    )

    body = Client().get(f"{BASE}/", **auth).json()
    assert len(body) == 2
    # newest first (order_by created_at desc)
    assert body[0]["action"] == "update"
    assert body[0]["old_values"] == {"status": "active"}
    assert body[0]["new_values"] == {"status": "inactive"}
    assert set(body[0]) == {
        "id", "entity_type", "entity_id", "action", "old_values", "new_values",
        "changed_by", "ip_address", "created_at",
    }


@pytest.mark.django_db
def test_filters_by_entity_type_and_id(auth):
    AuditLog.objects.create(entity_type="employee", entity_id=1, action="create", changed_by=1)
    AuditLog.objects.create(entity_type="department", entity_id=2, action="create", changed_by=1)
    AuditLog.objects.create(entity_type="employee", entity_id=99, action="create", changed_by=1)

    body = Client().get(f"{BASE}/?entity_type=employee&entity_id=1", **auth).json()
    assert len(body) == 1
    assert body[0]["entity_type"] == "employee"
    assert body[0]["entity_id"] == 1


@pytest.mark.django_db
def test_pagination(auth):
    for i in range(5):
        AuditLog.objects.create(entity_type="employee", entity_id=i, action="create", changed_by=1)

    page1 = Client().get(f"{BASE}/?page=1&limit=2", **auth).json()
    page2 = Client().get(f"{BASE}/?page=2&limit=2", **auth).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert {e["entity_id"] for e in page1} != {e["entity_id"] for e in page2}
