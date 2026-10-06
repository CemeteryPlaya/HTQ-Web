"""Сервис проектной структуры (спек 2026-10-06 §2): правила дерева, плана,
дат, совмещения, автоучастия и чтения на дату."""

from datetime import date

import pytest

from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.project.models import Project, ProjectAssignment, ProjectMember, ProjectRole
from apps.project.services import structure as svc

D = date


@pytest.fixture
def org(company_context):
    department = Department.objects.create(name="Стройка", path="stroy")
    position = Position.objects.create(title="Инженер", department=department, weight=10)
    counter = iter(range(1, 1000))

    def employee(last="Иванов", user_id=None, **kw):
        return Employee.objects.create(
            last_name=last, first_name="Тест", email=f"e{next(counter)}@htq.test",
            department=department, position=position, hire_date=D(2024, 1, 9),
            user_id=user_id, **kw)

    roles = {level: ProjectRole.objects.create(name=f"Т-L{level}", level=level,
                                               default_part="site" if level == 4 else "office")
             for level in (1, 2, 3, 4)}
    project = Project.objects.create(code="П-200", name="Объект", country_code="KZ")
    return {"employee": employee, "roles": roles, "project": project}


def _slot(org, level, parent=None, **kw):
    return svc.create_slot(org["project"], role_id=org["roles"][level].id, actor_id=1,
                           parent_id=parent.id if parent else None, **kw)


def _assign(slot, employee, date_from=D(2026, 1, 1), **kw):
    return svc.create_assignment(slot, employee_id=employee.id, date_from=date_from,
                                 actor_id=1, **kw)


# ── Дерево ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_part_defaults_to_role_and_can_be_overridden(org):
    top = _slot(org, 1)
    assert top.part == "office"
    assert _slot(org, 4, parent=top).part == "site"
    assert _slot(org, 3, parent=top, part="site").part == "site"


@pytest.mark.django_db
def test_only_l1_may_have_no_manager(org):
    _slot(org, 1)
    with pytest.raises(svc.StructureError, match="только место уровня L1"):
        _slot(org, 2)


@pytest.mark.django_db
def test_manager_must_be_strictly_higher(org):
    top = _slot(org, 1)
    mid = _slot(org, 2, parent=top)
    with pytest.raises(svc.StructureError, match="выше по уровню"):
        _slot(org, 2, parent=mid)
    low = _slot(org, 3, parent=mid)
    # «Подчинённого назначить руководителем» — цикл отвергает правило уровня.
    with pytest.raises(svc.StructureError, match="выше по уровню"):
        svc.update_slot(mid, actor_id=1, parent_id=low.id)


@pytest.mark.django_db
def test_manager_from_another_project_or_closed_is_refused(org):
    other = Project.objects.create(code="П-201", name="Другой", country_code="KZ")
    foreign = svc.create_slot(other, role_id=org["roles"][1].id, actor_id=1)
    with pytest.raises(svc.StructureError, match="этого же проекта"):
        _slot(org, 2, parent=foreign)
    top = _slot(org, 1)
    svc.update_slot(top, actor_id=1, closed_on=D(2026, 1, 1))
    with pytest.raises(svc.StructureError, match="закрыто"):
        _slot(org, 2, parent=top)


@pytest.mark.django_db
def test_inactive_role_is_not_offered_for_new_slots(org):
    svc.update_role(org["roles"][1], is_active=False)
    with pytest.raises(svc.StructureError, match="выключена"):
        _slot(org, 1)


@pytest.mark.django_db
def test_slot_with_people_or_open_children_cannot_be_closed(org):
    top = _slot(org, 1)
    child = _slot(org, 2, parent=top)
    with pytest.raises(svc.StructureError, match="подчинённые"):
        svc.update_slot(top, actor_id=1, closed_on=D(2026, 3, 1))
    person = _assign(child, org["employee"](), date_to=D(2026, 3, 1))
    with pytest.raises(svc.StructureError, match="есть люди"):
        svc.update_slot(child, actor_id=1, closed_on=D(2026, 3, 1))
    svc.update_assignment(person, actor_id=1, date_to=D(2026, 2, 28))
    svc.update_slot(child, actor_id=1, closed_on=D(2026, 3, 1))
    svc.update_slot(top, actor_id=1, closed_on=D(2026, 3, 1))
    with pytest.raises(svc.StructureError, match="Место закрыто"):
        svc.update_slot(top, actor_id=1, title="ещё")


@pytest.mark.django_db
def test_plan_cannot_drop_below_people_today(org):
    top = _slot(org, 1)
    workers = _slot(org, 4, parent=_slot(org, 3, parent=top), planned_headcount=3)
    _assign(workers, org["employee"]())
    _assign(workers, org["employee"]())
    with pytest.raises(svc.StructureError, match="не может быть меньше"):
        svc.update_slot(workers, actor_id=1, planned_headcount=1)
    assert svc.update_slot(workers, actor_id=1, planned_headcount=2).planned_headcount == 2


# ── Назначения ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_plan_limit_counts_overlapping_dates(org):
    top = _slot(org, 1)
    first = _assign(top, org["employee"](), date_from=D(2026, 1, 1), date_to=D(2026, 1, 31))
    with pytest.raises(svc.StructureError, match="1 из 1"):
        _assign(top, org["employee"](), date_from=D(2026, 1, 31))
    # Закрытое вчера назначение не мешает новому (Review Focus 3).
    _assign(top, org["employee"](), date_from=D(2026, 2, 1))
    with pytest.raises(svc.StructureError, match="1 из 1"):
        svc.update_assignment(first, actor_id=1, date_to=None)


@pytest.mark.django_db
def test_later_overlap_inside_period_is_caught(org):
    top = _slot(org, 1)
    _assign(top, org["employee"](), date_from=D(2026, 3, 1))
    with pytest.raises(svc.StructureError, match="на 01.03.2026"):
        _assign(top, org["employee"](), date_from=D(2026, 1, 1))
    _assign(top, org["employee"](), date_from=D(2026, 1, 1), date_to=D(2026, 2, 28))


@pytest.mark.django_db
def test_same_employee_twice_on_slot_is_refused_but_combining_slots_is_fine(org):
    top = _slot(org, 1)
    mid = _slot(org, 2, parent=top, planned_headcount=2)
    person = org["employee"]()
    _assign(mid, person)
    with pytest.raises(svc.StructureError, match="уже на этом месте"):
        _assign(mid, person, date_from=D(2026, 6, 1))
    _assign(top, person)  # совмещение двух мест
    assert ProjectAssignment.objects.filter(employee_id=person.id).count() == 2


@pytest.mark.django_db
def test_dismissed_or_missing_employee_is_refused(org):
    top = _slot(org, 1)
    fired = org["employee"](status=EmployeeStatus.TERMINATED)
    with pytest.raises(svc.EmployeeError):
        _assign(top, fired)
    with pytest.raises(svc.EmployeeError):
        svc.create_assignment(top, employee_id=999_999, date_from=D(2026, 1, 1), actor_id=1)


@pytest.mark.django_db
def test_reversed_dates_and_closed_slot_are_refused(org):
    top = _slot(org, 1)
    child = _slot(org, 2, parent=top)
    with pytest.raises(svc.StructureError, match="раньше даты начала"):
        _assign(child, org["employee"](), date_from=D(2026, 2, 1), date_to=D(2026, 1, 1))
    svc.update_slot(child, actor_id=1, closed_on=D(2026, 1, 1))
    with pytest.raises(svc.StructureError, match="закрыто"):
        _assign(child, org["employee"]())


@pytest.mark.django_db
def test_only_not_started_assignment_can_be_deleted(org):
    top = _slot(org, 1, planned_headcount=2)
    started = _assign(top, org["employee"](), date_from=D(2026, 1, 1))
    future = _assign(top, org["employee"](), date_from=D(2026, 9, 1))
    with pytest.raises(svc.StructureError, match="снимите сотрудника датой"):
        svc.delete_assignment(started, today=D(2026, 5, 1))
    svc.delete_assignment(future, today=D(2026, 5, 1))
    assert not ProjectAssignment.objects.filter(pk=future.pk).exists()


@pytest.mark.django_db
def test_employee_with_account_becomes_member_and_stays(org):
    project = org["project"]
    top = _slot(org, 1, planned_headcount=2)
    with_account = _assign(top, org["employee"](user_id=4242), date_from=D(2030, 1, 1))
    _assign(top, org["employee"]())  # без учётки — не участник
    assert list(ProjectMember.objects.filter(project=project)
                .values_list("user_id", flat=True)) == [4242]
    svc.delete_assignment(with_account, today=D(2026, 1, 1))
    assert ProjectMember.objects.filter(project=project, user_id=4242).exists()


# ── Чтение ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_structure_on_date(org):
    top = _slot(org, 1)
    old = _slot(org, 2, parent=top, title="старое")
    svc.update_slot(old, actor_id=1, closed_on=D(2026, 3, 1))
    workers = _slot(org, 4, parent=_slot(org, 3, parent=top), planned_headcount=5)
    _assign(top, org["employee"]("Петров"), date_from=D(2026, 1, 1))
    _assign(workers, org["employee"]("Ушедший"), date_from=D(2026, 1, 1),
            date_to=D(2026, 1, 31))
    _assign(workers, org["employee"]("Будущий"), date_from=D(2026, 6, 1))
    fired = org["employee"]("Уволенный")
    _assign(workers, fired, date_from=D(2026, 1, 1))
    Employee.objects.filter(pk=fired.pk).update(status=EmployeeStatus.TERMINATED)
    gone = org["employee"]("Удалённый")
    _assign(workers, gone, date_from=D(2026, 1, 1))
    Employee.objects.filter(pk=gone.pk).update(is_deleted=True)

    on_feb = {s["id"]: s for s in svc.structure(org["project"], D(2026, 2, 15))}
    assert str(old.id) in on_feb
    on_apr = {s["id"]: s for s in svc.structure(org["project"], D(2026, 4, 1))}
    assert str(old.id) not in on_apr
    assert [a["full_name"] for a in on_apr[str(top.id)]["assignments"]] == ["Петров Тест"]
    crew = on_apr[str(workers.id)]
    assert crew["planned_headcount"] == 5 and crew["actual_headcount"] == 2
    assert {a["full_name"]: a["dismissed"] for a in crew["assignments"]} == {
        "Уволенный Тест": True, "Удалённый Тест": True}
    assert crew["role"]["level"] == 4 and crew["part"] == "site"


# ── Справочник ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_used_role_keeps_level_and_cannot_be_deleted(org):
    role = org["roles"][1]
    _slot(org, 1)
    with pytest.raises(svc.RoleError, match="Уровень"):
        svc.update_role(role, level=2)
    with pytest.raises(svc.RoleError, match="выключить"):
        svc.delete_role(role)
    assert svc.update_role(role, name="Новое имя", is_active=False)["is_active"] is False
    unused = org["roles"][2]
    assert svc.update_role(unused, level=3)["level"] == 3
    svc.delete_role(unused)


@pytest.mark.django_db
def test_duplicate_role_name_is_a_role_error(org):
    with pytest.raises(svc.RoleError, match="уже есть"):
        svc.create_role(name="Т-L1", level=1)
