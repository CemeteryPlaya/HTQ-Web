"""Журнал изменений: пишется, читается, не правится (ТЗ §25.2)."""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client

from apps.bpp.models import AuditLog
from apps.bpp.services.core import audit
from apps.bpp.tests.helpers import assign, auth


class _Doc:
    """Документ-заглушка: у аудита спрашивают только тип и ключ."""

    class _meta:  # noqa: N801 — повторяет интерфейс модели
        label_lower = "bpp.probe"

    def __init__(self):
        self.pk = uuid.uuid4()


@pytest.mark.django_db
def test_record_and_history(company_context):
    doc = _Doc()
    audit.record(doc, "created", actor_id=7, changes={"amount": [None, "10.00"]})
    audit.record(doc, "submitted", actor_id=7, comment="на согласование")
    rows = audit.history("bpp.probe", str(doc.pk))
    assert [row["action"] for row in rows] == ["created", "submitted"]
    assert rows[0]["changes"] == {"amount": [None, "10.00"]}
    assert rows[1]["comment"] == "на согласование"


@pytest.mark.django_db
def test_audit_rows_cannot_be_updated_or_deleted(company_context):
    audit.record(_Doc(), "created", actor_id=7)
    row = AuditLog.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).update(action="forged")
    with pytest.raises(DatabaseError), transaction.atomic():
        row.delete()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {AuditLog._meta.db_table}")
    assert AuditLog.objects.get().action == "created"


@pytest.mark.django_db
def test_history_endpoint_needs_bpp_read(company_context):
    slug = company_context["slug"]
    doc = _Doc()
    audit.record(doc, "created", actor_id=7)
    url = f"/api/bpp/v1/history/bpp.probe/{doc.pk}"
    assert Client().get(url, **auth(slug)).status_code == 403
    assign(slug, 7, "bpp", "view")
    response = Client().get(url, **auth(slug))
    assert response.status_code == 200
    assert [row["action"] for row in response.json()] == ["created"]
