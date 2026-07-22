"""Юнит-тесты ETL-команды task (фаза 10).

Проверяют маппинг источник→Django и форму сверки: ``row_hash`` смаппленной
legacy-строки совпадает с ``row_hash`` Django-объекта ПОСЛЕ upsert + follow-up
``.update()`` (обход auto_now) — ровно то, что делает ``etl_task --verify``.
Легаси-БД тут не нужна: моделируем строки вручную.
"""
from __future__ import annotations

import datetime

import pytest

from apps.core.etl import row_hash
from apps.tasks import models as m
from apps.tasks.management.commands.etl_task import (
    _model_cols,
    _ts_cols,
    _utc,
)

UTC = datetime.timezone.utc


def _upsert(model, row, key):
    """Повторяет цикл загрузки команды: upsert + ts-fix (обход auto_now)."""
    shared = [c for c in _model_cols(model) if c in row]
    lookup = {k: row[k] for k in key}
    defaults = {c: _utc(row[c]) for c in shared if c not in key}
    obj, created = model.objects.update_or_create(defaults=defaults, **lookup)
    ts = {c: _utc(row[c]) for c in _ts_cols(model) if c in row}
    if ts:
        model.objects.filter(pk=obj.pk).update(**ts)
    obj.refresh_from_db()
    return obj, shared


def test_utc_normalizes_naive_and_aware():
    naive = datetime.datetime(2026, 5, 14, 9, 37, 40)
    plus3 = datetime.datetime(2026, 5, 14, 12, 37, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=3)))
    # naive → считаем UTC; +03:00 того же мгновения → тот же UTC-момент
    assert _utc(naive) == naive.replace(tzinfo=UTC)
    assert _utc(plus3) == _utc(naive)
    assert _utc("not-a-date") == "not-a-date"


@pytest.mark.django_db
def test_tasktype_mapping_row_hash_matches_after_upsert():
    # id/slug вне набора пред-сидированных системных типов (миграция 0002)
    row = {
        "id": 9001, "slug": "etl-custom-9001", "name": "ETL Custom", "color": "#f00",
        "icon": "star", "is_system": False,
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 1, 2, tzinfo=UTC),
    }
    obj, shared = _upsert(m.TaskType, row, key=("id",))

    src = {c: _utc(row[c]) for c in shared}
    tgt = {c: _utc(getattr(obj, c)) for c in shared}
    assert row_hash(src) == row_hash(tgt)
    # auto_now НЕ затёр legacy-updated_at (иначе hash бы разошёлся)
    assert _utc(obj.updated_at) == row["updated_at"]
    assert obj.slug == "etl-custom-9001" and obj.is_system is False


@pytest.mark.django_db
def test_calendar_participant_natural_key_upsert_idempotent():
    # у источника нет суррогатного id — ключ (event_id, user_id); created_at naive
    ev = m.CalendarEvent.objects.create(
        id=5, title="Standup", start_at=datetime.datetime(2026, 3, 1, 9, tzinfo=UTC),
        end_at=datetime.datetime(2026, 3, 1, 10, tzinfo=UTC),
    )
    row = {
        "event_id": ev.id, "user_id": 42, "rsvp_status": "accepted",
        "created_at": datetime.datetime(2026, 3, 1, 8, 30),  # naive
    }
    obj1, shared = _upsert(m.CalendarEventParticipant, row, key=("event_id", "user_id"))
    # повторный upsert по натуральному ключу не плодит дублей
    obj2, _ = _upsert(m.CalendarEventParticipant, row, key=("event_id", "user_id"))
    assert obj1.pk == obj2.pk
    assert m.CalendarEventParticipant.objects.filter(event_id=ev.id, user_id=42).count() == 1

    src = {c: _utc(row[c]) for c in shared}
    tgt = {c: _utc(getattr(obj2, c)) for c in shared}
    assert row_hash(src) == row_hash(tgt)
