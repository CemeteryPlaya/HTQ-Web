"""Основа модуля (T0.2, решение T-10): свои номера ТН-ГГГГ-NNNNNN, журнал
только для записи (триггер БД в схеме компании), E-CON-01, тенантность.

Нумерация и журнал — копия apps/bpp/services/core: core живёт в public, а
номера и журнал тенантные, поэтому общий код вынести некуда.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib import admin
from django.db import DatabaseError, connection, transaction

from apps.tender import holding
from apps.tender.models import AuditLog, NumberSequence
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.core.numbering import TENDER_PREFIX, next_number
from apps.users.models import User
from htqweb.errors import DomainError
from htqweb.tenancy.context import schema_for


# ── тенантность ────────────────────────────────────────────────────────────

def test_tender_is_a_tenant_app_that_summarises_nothing_yet():
    assert "tender" in settings.TENANT_APPS
    assert holding.HOLDING_MODELS == ()


@pytest.mark.django_db
def test_tables_live_in_the_company_schema(company_context):
    schema = schema_for(company_context["slug"])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = ANY(%s)",
            [schema, [AuditLog._meta.db_table, NumberSequence._meta.db_table]],
        )
        found = {row[0] for row in cursor.fetchall()}
    assert found == {"tender_auditlog", "tender_numbersequence"}


# ── нумерация ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tender_numbers_follow_the_tz_format(company_context):
    assert TENDER_PREFIX == "ТН"
    assert next_number(TENDER_PREFIX, year=2026) == "ТН-2026-000001"
    assert next_number(TENDER_PREFIX, year=2026) == "ТН-2026-000002"


@pytest.mark.django_db
def test_year_starts_a_new_counter(company_context):
    next_number(TENDER_PREFIX, year=2026)
    assert next_number(TENDER_PREFIX, year=2027) == "ТН-2027-000001"


@pytest.mark.django_db
def test_counters_are_per_company(two_company_schemas):
    from htqweb.tenancy.db import use_company

    alpha, beta = two_company_schemas
    with use_company(alpha):
        next_number(TENDER_PREFIX, year=2026)
        next_number(TENDER_PREFIX, year=2026)
    with use_company(beta):
        assert next_number(TENDER_PREFIX, year=2026) == "ТН-2026-000001"


@pytest.mark.django_db(transaction=True)
def test_parallel_numbers_are_unique_and_gapless():
    """20 потоков, у каждого своё соединение: номера не повторяются и идут
    подряд — выдачу сериализует сама вставка по уникальному ключу."""
    got: list[str] = []
    lock = threading.Lock()

    def worker():
        try:
            number = next_number(TENDER_PREFIX, year=2026)
            with lock:
                got.append(number)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(got) == [f"ТН-2026-{n:06d}" for n in range(1, 21)]


# ── журнал ─────────────────────────────────────────────────────────────────

class _Doc:
    """Объект-заглушка: журналу нужны только тип и ключ."""

    class _meta:  # noqa: N801 — повторяет интерфейс модели
        label_lower = "tender.probe"

    def __init__(self):
        self.pk = uuid.uuid4()


@pytest.mark.django_db
def test_record_and_history(company_context):
    doc = _Doc()
    audit.record(doc, "created", actor_id=7, changes={"deadline": [None, "2026-10-20"]})
    audit.record(doc, "published", actor_id=7, comment="приём предложений")
    rows = audit.history("tender.probe", str(doc.pk))
    assert [row["action"] for row in rows] == ["created", "published"]
    assert rows[0]["changes"] == {"deadline": [None, "2026-10-20"]}
    assert rows[1]["comment"] == "приём предложений"


@pytest.mark.django_db
def test_audit_rows_cannot_be_updated_or_deleted(company_context):
    """Запрет — триггером БД в схеме компании: django-admin и сырой SQL его
    не обходят."""
    audit.record(_Doc(), "created", actor_id=7)
    row = AuditLog.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).update(action="forged")
    with pytest.raises(DatabaseError), transaction.atomic():
        row.delete()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {AuditLog._meta.db_table}")
    assert AuditLog.objects.get().action == "created"


def test_history_of_an_unregistered_type_is_closed():
    """Забытая регистрация проверки закрывает журнал, а не открывает."""
    assert audit.can_view_history(object(), "tender.nobody", str(uuid.uuid4())) is False


def test_admin_cannot_forge_or_edit_journal_rows():
    model_admin = admin.site._registry[AuditLog]
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


# ── оптимистическая блокировка ─────────────────────────────────────────────

@pytest.mark.django_db
def test_matching_or_missing_version_passes():
    obj = SimpleNamespace(version=3, updated_by=None, updated_at=None)
    check_version(obj, 3)
    check_version(obj, None)


@pytest.mark.django_db
def test_stale_version_is_e_con_01_with_who_and_when():
    user = User.objects.create(username="buyer", email="b@htq.test", password="x",
                               last_name="Иванов", first_name="Алексей")
    obj = SimpleNamespace(version=4, updated_by=user.pk,
                          updated_at=datetime(2026, 10, 7, 9, 32, tzinfo=dt_timezone.utc))
    with pytest.raises(DomainError) as exc:
        check_version(obj, 3)
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)
    assert "Иванов" in exc.value.message
    assert "14:32" in exc.value.message  # PLATFORM_TIME_ZONE Asia/Almaty = UTC+5
