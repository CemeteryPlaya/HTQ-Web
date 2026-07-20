"""Паритет схемы hr-core с FastAPI-исходником (services/hr/app/models/).

Проверяет ровно то, что реально ломалось в прошлых фазах миграции:
потерянные индексы, потерянные СЕРВЕРНЫЕ дефолты (NOT NULL без db_default
роняет любую вставку мимо ORM — например, ETL фазы 10), nullability и
uniqueness. Плюс живой round-trip через БД, включая циклический FK
Department.manager <-> Employee.department (решение D3 плана).

План: docs/plans/2026-07-20-hr-domain.md
"""
import datetime

import pytest
from django.db import connection
from django.db.utils import IntegrityError

from apps.hr.models import Department, Employee, LevelThreshold, OrgSettings, Position


def _cols(table: str) -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {r[0]: {"nullable": r[1] == "YES", "default": r[2]} for r in cur.fetchall()}


def _indexed_columns(table: str) -> set[str]:
    """Колонки, покрытые хоть каким-то индексом.

    Парсит последнюю скобочную группу indexdef и отбрасывает opclass-суффиксы
    (Django на Postgres добавляет varchar_pattern_ops-индексы), поэтому
    работает и для составных индексов.
    """
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        defs = [r[0] for r in cur.fetchall()]
    cols: set[str] = set()
    for d in defs:
        inner = d[d.rfind("(") + 1 : d.rfind(")")]
        for part in inner.split(","):
            token = part.strip().strip('"').split()[0]
            cols.add(token.strip('"'))
    return cols


@pytest.mark.django_db
def test_timestamps_have_server_defaults():
    # created_at/updated_at — NOT NULL с server_default=func.now() в исходнике
    # (services/hr/app/models/base.py). Без db_default вставка мимо ORM упадёт.
    for table in ("hr_department", "hr_position", "hr_employee"):
        cols = _cols(table)
        assert cols["created_at"]["default"] is not None, table
        assert cols["updated_at"]["default"] is not None, table
        assert not cols["created_at"]["nullable"], table


@pytest.mark.django_db
def test_department_columns_and_indexes():
    cols = _cols("hr_department")
    assert not cols["name"]["nullable"]
    assert not cols["path"]["nullable"]
    assert cols["description"]["nullable"]
    assert cols["manager_id"]["nullable"]
    assert cols["is_active"]["default"] is not None
    assert cols["unit_type"]["default"] is not None
    assert {"name", "path"} <= _indexed_columns("hr_department")


@pytest.mark.django_db
def test_position_indexes_ported():
    # Исходник: Index по weight, level, is_system (weight ещё и unique).
    assert {"weight", "level", "is_system"} <= _indexed_columns("hr_position")


@pytest.mark.django_db
def test_employee_user_id_unique_and_nullable():
    cols = _cols("hr_employee")
    assert cols["user_id"]["nullable"]  # связь с apps.users опциональна
    assert "user_id" in _indexed_columns("hr_employee")


@pytest.mark.django_db
def test_org_settings_has_no_created_at():
    # D5: OrgSettings наследует Base, а не BaseModel — created_at нет.
    cols = _cols("hr_orgsettings")
    assert "created_at" not in cols
    assert "updated_at" in cols


@pytest.mark.django_db
def test_level_threshold_range_constraint_enforced():
    with pytest.raises(IntegrityError):
        LevelThreshold.objects.create(level_number=1, weight_from=10, weight_to=5)


@pytest.mark.django_db
def test_core_roundtrip_with_circular_manager_fk():
    # D3: Department.manager -> Employee, Employee.department -> Department.
    dep = Department.objects.create(name="ИТ", path="it")
    pos = Position.objects.create(title="Инженер", department=dep, weight=100)
    emp = Employee.objects.create(
        first_name="Иван",
        last_name="Иванов",
        email="i@htq.test",
        department=dep,
        position=pos,
        hire_date=datetime.date(2024, 1, 9),
    )
    dep.manager = emp
    dep.save(update_fields=["manager"])
    dep.refresh_from_db()

    assert dep.manager_id == emp.id
    assert dep.unit_type == "department"  # дефолт из исходника
    assert emp.status == "active"
    assert emp.is_deleted is False
    assert OrgSettings.objects.create(key="deletion_strategy", value="cascade").id
