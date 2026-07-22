"""Юнит-тесты ETL-команды hr (фаза 10).

Бьют в реальные хелперы команды (``_row_fields``/``_upsert_row``/``_normalize_dt``)
и проверяют форму сверки: ``row_hash`` смаппленной legacy-строки == ``row_hash``
Django-объекта после upsert + auto_now-фикса (ровно как ``etl_hr --verify``).
Легаси-БД не нужна — строки моделируем вручную.
"""
from __future__ import annotations

import datetime

import pytest
from django.utils import timezone as dj_timezone

from apps.core.etl import row_hash
from apps.hr.management.commands import etl_hr
from apps.hr.models import Department

UTC = datetime.timezone.utc


def test_normalize_dt_naive_becomes_utc_aware():
    naive = datetime.datetime(2026, 4, 1, 8, 0, 0)
    out = etl_hr._normalize_dt(naive)
    assert dj_timezone.is_aware(out)
    assert out == naive.replace(tzinfo=UTC)
    # aware-значение не трогаем; не-datetime проходит насквозь
    aware = datetime.datetime(2026, 4, 1, 8, 0, 0, tzinfo=UTC)
    assert etl_hr._normalize_dt(aware) == aware
    assert etl_hr._normalize_dt("x") == "x"


@pytest.mark.django_db
def test_department_mapping_row_hash_matches_after_upsert():
    row = {
        "id": 1,
        "name": "Инженерия",
        "description": "R&D",
        "path": "1",
        "unit_type": "department",
        "is_active": True,
        "manager_id": None,          # nullable → без двухфазного разрешения
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 1, 2, tzinfo=UTC),
    }
    spec = etl_hr.DEPARTMENT_SPEC
    fields = etl_hr._row_fields(spec, row)
    lookup = {k: fields[k] for k in spec.pk_fields}
    defaults = {k: v for k, v in fields.items() if k not in spec.pk_fields}
    created = etl_hr._upsert_row(spec.model, lookup, defaults)
    assert created is True

    obj = Department.objects.get(id=1)
    obj_fields = {k: getattr(obj, k) for k in fields}
    # та же форма сравнения, что --verify
    assert row_hash(fields) == row_hash(obj_fields)
    # auto_now(updated_at) не затёр legacy-значение
    assert obj.updated_at == row["updated_at"]

    # идемпотентность: повторный upsert не создаёт (created=False), не плодит дублей
    created_again = etl_hr._upsert_row(spec.model, lookup, defaults)
    assert created_again is False
    assert Department.objects.filter(id=1).count() == 1
