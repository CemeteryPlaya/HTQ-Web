"""Годовой график отпусков — строка 10, часть а матрицы HR-FRM-004.

Отличие от остальных пяти кадровых предметов согласования блока G: это
КОНТЕЙНЕР со строками, а не одиночная запись. Согласуется график ЦЕЛИКОМ —
согласовать половину графика бессмысленно, поэтому строка
(``VacationScheduleLine``) сама предметом согласования не является: у неё
нет ``SIGNOFF_SUBJECT_TYPE``, и она не зарегистрирована в
``SUBJECT_MODELS``/``SUBJECT_SPECS``.

Факты графика — агрегаты по его строкам (число строк, число разных
сотрудников, суммарное число дней), а не поля, скопированные построчно.
Как и у отпуска/командировки (``test_leave_and_trip.py``), границы периода
включительные: строка с 1-го по 1-е число — один день.

Автоматических последствий утверждения нет (решение 11 плана блока G) —
как у отпуска и командировки, и как у премии со взысканием.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import (
    Department, Employee, Position, VacationSchedule, VacationScheduleLine,
)
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Дирекция по продажам", path="sales")
    position = Position.objects.create(
        title="Менеджер по продажам", department=dep, weight=640, level=4)
    employee_a = Employee.objects.create(
        first_name="Данияр", last_name="Кенжебаев", email="d.k@htq.kz",
        department=dep, position=position, hire_date="2023-05-15")
    employee_b = Employee.objects.create(
        first_name="Айгерим", last_name="Сатпаева", email="a.s@htq.kz",
        department=dep, position=position, hire_date="2022-02-01")
    return {"dep": dep, "position": position,
            "employee_a": employee_a, "employee_b": employee_b}


def _schedule(**over):
    payload = {"year": 2026, "basis": "Приказ №12 от 15.12.2025"}
    payload.update(over)
    return VacationSchedule.objects.create(**payload)


def _line(schedule, employee, date_from, date_to):
    return VacationScheduleLine.objects.create(
        schedule=schedule, employee=employee, date_from=date_from, date_to=date_to)


# ── график согласуется целиком, строка — нет ────────────────────────────

def test_vacation_schedule_line_has_no_signoff_subject_type():
    assert not hasattr(VacationScheduleLine, "SIGNOFF_SUBJECT_TYPE")


def test_vacation_schedule_line_is_not_a_registered_subject():
    from apps.hr import approval_hooks

    assert VacationScheduleLine not in approval_hooks.SUBJECT_MODELS.values()
    assert "hr.vacation_schedule_line" not in approval_hooks.SUBJECT_SPECS


@pytest.mark.django_db
def test_vacation_schedule_is_approvable_and_registered(org):
    schedule = _schedule()
    assert schedule.approval_state == signoff.ApprovalState.DRAFT
    assert schedule.SIGNOFF_SUBJECT_TYPE == "hr.vacation_schedule"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.vacation_schedule" in registered
    assert registered["hr.vacation_schedule"]["label"] == "График отпусков"


def test_neither_vacation_schedule_declares_on_approved():
    """Решение 11 плана блока G: у графика, как у отпуска и командировки,
    нет автоматических последствий утверждения."""
    from apps.hr import approval_hooks

    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.vacation_schedule"]
    assert "on_rejected" not in approval_hooks.SUBJECT_SPECS["hr.vacation_schedule"]
    assert "on_rework" not in approval_hooks.SUBJECT_SPECS["hr.vacation_schedule"]


# ── факты считаются по строкам одним запросом ────────────────────────────

@pytest.mark.django_db
def test_vacation_schedule_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    schedule = _schedule()
    _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 14))
    facts = approval_hooks._vacation_schedule_facts(schedule.id)
    assert set(facts) == {"year", "lines_count", "employees_count", "total_days"}
    declared = {f["key"] for f in approval_hooks._vacation_schedule_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_vacation_schedule_facts_are_aggregated_over_a_non_degenerate_schedule(org):
    """Два сотрудника, три строки (у одного — две строки): проверяет, что
    ``employees_count`` считает РАЗНЫХ сотрудников (``distinct``), а не
    строки, и что суммарные дни складываются по всем строкам сразу.

    Дни по строкам, включительно:
    - сотрудник A, 01.09–14.09.2026 = 14 дней
    - сотрудник A, 01.10–05.10.2026 = 5 дней
    - сотрудник B, 01.11–03.11.2026 = 3 дня
    Итого: lines_count=3, employees_count=2, total_days=14+5+3=22.
    """
    from apps.hr import approval_hooks

    schedule = _schedule()
    _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 14))
    _line(schedule, org["employee_a"], dt.date(2026, 10, 1), dt.date(2026, 10, 5))
    _line(schedule, org["employee_b"], dt.date(2026, 11, 1), dt.date(2026, 11, 3))

    facts = approval_hooks._vacation_schedule_facts(schedule.id)
    assert facts["year"] == schedule.year
    assert facts["lines_count"] == 3
    assert facts["employees_count"] == 2
    assert facts["total_days"] == 22


@pytest.mark.django_db
def test_vacation_schedule_line_of_a_single_day_counts_as_one_not_zero(org):
    """Строка с 1-го по 1-е число — ОДИН день, а не ноль (как у отпуска и
    командировки, включительные границы)."""
    from apps.hr import approval_hooks

    schedule = _schedule()
    _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 1))

    facts = approval_hooks._vacation_schedule_facts(schedule.id)
    assert facts["lines_count"] == 1
    assert facts["employees_count"] == 1
    assert facts["total_days"] == 1


@pytest.mark.django_db
def test_empty_vacation_schedule_has_zero_facts_and_describe_says_so(org):
    """Пустой график отправить нельзя, но это состояние маршрута, не
    предметной проверки (решение 11, докстринг approval_service) — здесь
    фиксируется только то, что факты и описание честно отражают «пусто»."""
    from apps.hr import approval_hooks

    schedule = _schedule(year=2027)
    facts = approval_hooks._vacation_schedule_facts(schedule.id)
    assert facts["lines_count"] == 0
    assert facts["employees_count"] == 0
    assert facts["total_days"] == 0

    card = approval_hooks._describe_vacation_schedule(schedule.id)
    assert "0 строк" in card["title"]


@pytest.mark.django_db
def test_vacation_schedule_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._vacation_schedule_facts(10_000_000) == {}
    assert approval_hooks._describe_vacation_schedule(10_000_000) is None


@pytest.mark.django_db
def test_describe_vacation_schedule_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    schedule = _schedule(year=2026)
    _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 14))
    card = approval_hooks._describe_vacation_schedule(schedule.id)
    assert "2026" in card["title"]
    assert card["url"].endswith(str(schedule.id))


# ── год уникален ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_vacation_schedule_year_is_unique(org):
    from django.db import IntegrityError, transaction

    _schedule(year=2026)
    with pytest.raises(IntegrityError), transaction.atomic():
        _schedule(year=2026)


# ── строка ссылается на сотрудника и несёт период ────────────────────────

@pytest.mark.django_db
def test_vacation_schedule_line_references_employee_and_period(org):
    schedule = _schedule()
    line = _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 14))
    assert line.employee_id == org["employee_a"].id
    assert line.schedule_id == schedule.id
    assert line in schedule.lines.all()


@pytest.mark.django_db
def test_vacation_schedule_line_with_reversed_period_is_rejected_by_the_database(org):
    from django.db import IntegrityError, transaction

    schedule = _schedule()
    with pytest.raises(IntegrityError), transaction.atomic():
        _line(schedule, org["employee_a"], dt.date(2026, 9, 14), dt.date(2026, 9, 1))


# ── факты удалённого графика (строки каскадом) ───────────────────────────

@pytest.mark.django_db
def test_vacation_schedule_lines_are_deleted_with_the_schedule(org):
    schedule = _schedule()
    _line(schedule, org["employee_a"], dt.date(2026, 9, 1), dt.date(2026, 9, 14))
    schedule_id = schedule.id
    schedule.delete()
    assert not VacationScheduleLine.objects.filter(schedule_id=schedule_id).exists()
