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


def test_list_departments_brief_returns_all(org):
    """Пакетный ``get_departments_brief`` требует список id, которого у
    соседа может не быть: команде наполнения apps.tasks нужно разложить
    проекты по реальным отделам, а какие они — она узнаёт только здесь."""
    Department.objects.create(name="Строительство", path="stroy")
    rows = interface.list_departments_brief()
    assert {r["path"] for r in rows} == {"it", "stroy"}
    assert set(rows[0]) == {"id", "name", "path", "is_active"}


def test_list_departments_brief_respects_limit(org):
    for i in range(5):
        Department.objects.create(name=f"Отдел {i}", path=f"d{i}")
    assert len(interface.list_departments_brief(limit=3)) == 3


def test_list_employees_brief_exposes_user_id(org):
    """``user_id`` — то, ради чего функция существует.

    Исполнитель задачи и владелец проекта в apps.tasks это user_id, а не PK
    строки Employee. Без этого поля сосед связать сотрудника с задачей не
    может и полез бы в модели hr напрямую.
    """
    rows = interface.list_employees_brief()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"id", "full_name", "email", "user_id",
                        "department_id", "position_title", "status"}
    assert row["full_name"] == "Иванов Иван"
    assert row["position_title"] == "Инженер"


def test_list_employees_brief_skips_soft_deleted(org):
    Employee.objects.update(is_deleted=True)
    assert interface.list_employees_brief() == []


@pytest.mark.django_db
def test_link_employee_user_sets_and_is_idempotent(org):
    employee = Employee.objects.get()
    assert interface.link_employee_user(employee.id, 777) is True
    employee.refresh_from_db()
    assert employee.user_id == 777
    # Повтор тем же id — не ошибка и не лишняя запись.
    assert interface.link_employee_user(employee.id, 777) is True


@pytest.mark.django_db
def test_link_employee_user_refuses_to_steal_account(org):
    """``user_id`` уникален: молча переклеить учётку с одного человека на
    другого нельзя — второй потерял бы доступ к своим задачам."""
    first = Employee.objects.get()
    interface.link_employee_user(first.id, 777)
    second = Employee.objects.create(
        first_name="Пётр", last_name="Петров", email="p@htq.test",
        department=first.department, position=first.position,
        hire_date=datetime.date(2024, 2, 1),
    )
    assert interface.link_employee_user(second.id, 777) is False
    second.refresh_from_db()
    assert second.user_id is None


@pytest.mark.django_db
def test_link_employee_user_on_missing_employee(org):
    assert interface.link_employee_user(999_999, 5) is False


@pytest.mark.django_db
@pytest.mark.parametrize("call", [
    lambda: interface.get_department_brief(1),
    lambda: interface.get_departments_brief([1]),
    lambda: interface.get_employee_brief(42),
    lambda: interface.org_ancestors(1),
    lambda: interface.list_departments_brief(),
    lambda: interface.list_employees_brief(),
    lambda: interface.link_employee_user(1, 1),
])
def test_every_interface_function_guards_disabled_hr_first(org, call):
    ServiceStatus.objects.update_or_create(app_label="hr", defaults={"enabled": False})
    cache.delete("svc-status:hr")
    with pytest.raises(ServiceDisabled):
        call()
