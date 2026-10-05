"""``hr.interface.employees_brief`` — чтение сотрудников для проектной
структуры (``apps.project``, спек 2026-10-06 §4): по списку id — включая
уволенных и удалённых (схема их помечает, а не теряет), поиском — только
действующие."""

from datetime import date

import pytest

from apps.hr import interface
from apps.hr.models import Employee, EmployeeStatus


def _employee(department, position, last, first, email, **kw):
    return Employee.objects.create(last_name=last, first_name=first, email=email,
                                   department=department, position=position,
                                   hire_date=date(2024, 1, 9), **kw)


@pytest.mark.django_db
def test_by_ids_marks_dismissed_and_deleted_as_inactive(department, position):
    active = _employee(department, position, "Иванов", "Пётр", "a@htq.test", user_id=501,
                       middle_name="Сергеевич")
    fired = _employee(department, position, "Сидоров", "Олег", "b@htq.test",
                      status=EmployeeStatus.TERMINATED)
    gone = _employee(department, position, "Ким", "Ан", "c@htq.test", is_deleted=True)

    rows = {r["id"]: r for r in interface.employees_brief([active.id, fired.id, gone.id])}

    assert rows[active.id] == {"id": active.id, "full_name": "Иванов Пётр Сергеевич",
                               "user_id": 501, "position_title": "Инженер", "active": True}
    assert rows[fired.id]["active"] is False
    assert rows[gone.id]["active"] is False


@pytest.mark.django_db
def test_search_finds_only_active_by_every_word(department, position):
    _employee(department, position, "Иванов", "Пётр", "a@htq.test")
    _employee(department, position, "Иванов", "Олег", "b@htq.test")
    _employee(department, position, "Иванова", "Пелагея", "c@htq.test",
              status=EmployeeStatus.TERMINATED)

    found = interface.employees_brief(query="Ив Пёт")
    assert [r["full_name"] for r in found] == ["Иванов Пётр"]
    assert [r["full_name"] for r in interface.employees_brief(query="иванов")] == [
        "Иванов Олег", "Иванов Пётр"]
    assert len(interface.employees_brief(query="Иванов", limit=1)) == 1
