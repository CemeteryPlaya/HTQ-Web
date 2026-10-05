"""Журнал файловых операций — только вставка (миграция
``files/0002_fileevent_append_only``, D-30).

Строку ``FileEvent`` нельзя ни изменить, ни удалить — ни через ORM, ни
сырым SQL: запрет стоит в базе, а не в коде. Единственное изменение,
которое база пропускает, — ``tenancy_bootstrap`` один раз проставляет
компанию событию, записанному до первой компании.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from apps.files.models import FileEvent

from .helpers import OWNER

pytestmark = pytest.mark.django_db

TABLE = FileEvent._meta.db_table


def _event(**over) -> FileEvent:
    return FileEvent.objects.create(owner_type=OWNER, owner_id="1", event="file_attached",
                                    actor_id=7, payload={"name": "kp.pdf"}, **over)


def test_orm_cannot_update_or_delete_a_row():
    row = _event()

    with pytest.raises(DatabaseError), transaction.atomic():
        FileEvent.objects.filter(pk=row.pk).update(event="file_deleted")
    with pytest.raises(DatabaseError), transaction.atomic():
        row.ip = "10.0.0.1"
        row.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        row.delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        FileEvent.objects.all().delete()

    fresh = FileEvent.objects.get(pk=row.pk)
    assert (fresh.event, fresh.ip) == ("file_attached", "")


def test_raw_sql_cannot_update_or_delete_a_row():
    row = _event()

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"UPDATE {TABLE} SET actor_id = 1 WHERE id = %s", [row.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {TABLE}")

    assert FileEvent.objects.get(pk=row.pk).actor_id == 7


def test_bootstrap_stamps_the_company_once_and_nothing_else():
    """``assign_company``: пустая компания → компания, остальное как было.
    Второй раз компанию не переписать, и заодно с ней — ни одного другого
    столбца."""
    row = _event()

    FileEvent.objects.filter(pk=row.pk).update(company_slug="alpha")
    assert FileEvent.objects.get(pk=row.pk).company_slug == "alpha"

    with pytest.raises(DatabaseError), transaction.atomic():
        FileEvent.objects.filter(pk=row.pk).update(company_slug="beta")

    other = _event()
    with pytest.raises(DatabaseError), transaction.atomic():
        FileEvent.objects.filter(pk=other.pk).update(company_slug="alpha", ip="10.0.0.1")
    assert FileEvent.objects.get(pk=other.pk).company_slug == ""
