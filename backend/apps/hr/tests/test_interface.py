"""apps.hr.interface — межаппный контракт §7 (его потребляет Поток B).

Проверяет форму ответа каждой функции и guard отключаемости первой строкой.
Сигнатуры зафиксированы в PLAN.md §7: task зовёт get_department_brief,
approvals — org_ancestors/get_departments_brief. Менять только совместно A↔B.

План: docs/plans/2026-07-20-hr-domain.md
"""
import datetime

import pytest
from django.core.cache import cache

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.models import Department, Employee, Position


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="ИТ", path="it")
    pos = Position.objects.create(title="Инженер", department=dep, weight=100)
    emp = Employee.objects.create(
        first_name="Иван",
        last_name="Иванов",
        email="i@htq.test",
        department=dep,
        position=pos,
        hire_date=datetime.date(2024, 1, 9),
        user_id=42,
    )
    return dep, pos, emp


@pytest.mark.django_db
def test_get_department_brief_shape(org):
    dep, _pos, _emp = org
    assert interface.get_department_brief(dep.id) == {
        "id": dep.id, "name": "ИТ", "path": "it", "is_active": True,
    }


@pytest.mark.django_db
def test_get_department_brief_missing_returns_none(org):
    assert interface.get_department_brief(999_999) is None


@pytest.mark.django_db
def test_get_departments_brief_batch_skips_missing(org):
    dep, _, _ = org
    other = Department.objects.create(name="Финансы", path="fin")
    got = {d["id"] for d in interface.get_departments_brief([dep.id, other.id, 999_999])}
    assert got == {dep.id, other.id}


@pytest.mark.django_db
def test_get_departments_brief_empty_input(org):
    assert interface.get_departments_brief([]) == []


@pytest.mark.django_db
def test_get_employee_brief_by_user_id(org):
    _dep, _pos, emp = org
    brief = interface.get_employee_brief(42)
    assert brief["id"] == emp.id
    assert brief["full_name"] == "Иванов Иван"
    assert brief["department_id"] == emp.department_id
    assert brief["position_title"] == "Инженер"
    assert brief["status"] == "active"


@pytest.mark.django_db
def test_get_employee_brief_skips_soft_deleted(org):
    _dep, _pos, emp = org
    emp.is_deleted = True
    emp.save(update_fields=["is_deleted"])
    assert interface.get_employee_brief(42) is None


@pytest.mark.django_db
def test_org_ancestors_walks_path_prefixes(org):
    dep, _, _ = org
    Department.objects.create(name="Разработка", path="it.dev")
    grand = Department.objects.create(name="Бэкенд", path="it.dev.backend")
    names = [d["name"] for d in interface.org_ancestors(grand.id)]
    # от корня к непосредственному родителю, себя не включая
    assert names == ["ИТ", "Разработка"]
    assert interface.org_ancestors(dep.id) == []


@pytest.mark.django_db
def test_org_ancestors_missing_department_returns_empty(org):
    assert interface.org_ancestors(999_999) == []


@pytest.mark.django_db
@pytest.mark.parametrize("call", [
    lambda: interface.get_department_brief(1),
    lambda: interface.get_departments_brief([1]),
    lambda: interface.get_employee_brief(42),
    lambda: interface.org_ancestors(1),
])
def test_every_interface_function_guards_disabled_hr_first(org, call):
    ServiceStatus.objects.update_or_create(app_label="hr", defaults={"enabled": False})
    cache.delete("svc-status:hr")
    with pytest.raises(ServiceDisabled):
        call()
