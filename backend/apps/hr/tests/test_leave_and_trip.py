"""Заявление на отпуск и командировка — строки 10б, 10в матрицы HR-FRM-004.

Заказчик развёл строку 10 на три предмета (решение 16.09.2026): график,
отпуск и командировка. Здесь — два последних. Ни у одного из них нет
автоматических последствий утверждения (решение 11 плана блока G) —
единственный такой эффект во всём блоке принадлежит кадровому приказу
(``test_personnel_order.py``).

Здесь впервые в блоке появляются ПАРЫ ДАТ (``htqweb/date_rules.py``): обе
модели используют одну пару имён ``date_from``/``date_to``, поэтому в
``DATE_PAIRS`` — одна новая строка на обе. HTTP-ручек на создание этих
предметов в блоке нет (только отправка на согласование, она общая), поэтому
здесь проверяются только те два уровня правила, для которых есть куда их
поставить: ограничение в БД (``ck_leaverequest_dates``/
``ck_businesstrip_dates``) и сама платформенная функция
(``htqweb.date_rules.assert_ordered``). Схема (``OrderedDates``) и сервис
(``assert_instance_ordered`` перед ``save()``) появятся вместе с ручками
создания — заводить их сейчас означало бы выдумывать сервис ради галочки.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.hr.models import (
    BusinessTrip, Department, Employee, LeaveKind, LeaveRequest, Position,
)
from apps.signoff import interface as signoff
from htqweb.date_rules import DATE_PAIRS, DatesOutOfOrder, assert_ordered


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Дирекция по продажам", path="sales")
    position = Position.objects.create(
        title="Менеджер по продажам", department=dep, weight=640, level=4)
    employee = Employee.objects.create(
        first_name="Данияр", last_name="Кенжебаев", email="d.k@htq.kz",
        department=dep, position=position, hire_date="2023-05-15")
    return {"dep": dep, "position": position, "employee": employee}


def _leave(org, **over):
    payload = {
        "employee": org["employee"],
        "kind": LeaveKind.ANNUAL,
        "date_from": dt.date(2026, 9, 1),
        "date_to": dt.date(2026, 9, 14),
        "basis": "Заявление сотрудника от 01.09.2026",
    }
    payload.update(over)
    return LeaveRequest.objects.create(**payload)


def _trip(org, **over):
    payload = {
        "employee": org["employee"],
        "destination": "Алматы",
        "country": "",
        "purpose": "Переговоры с поставщиком",
        "date_from": dt.date(2026, 9, 1),
        "date_to": dt.date(2026, 9, 3),
        "estimated_cost": Decimal("450000.00"),
        "basis": "Служебная записка",
    }
    payload.update(over)
    return BusinessTrip.objects.create(**payload)


# ── платформенное правило дат ────────────────────────────────────────────

def test_date_from_date_to_pair_is_registered_in_date_pairs():
    """Обе модели используют одну пару имён — одна строка на обе."""
    known = {(start, end) for start, end, _ in DATE_PAIRS}
    assert ("date_from", "date_to") in known


def test_platform_rule_rejects_a_reversed_period():
    """Уровень платформенного правила, а не только БД: перевёрнутый период
    отвергает сама функция ``assert_ordered``, независимо от того, есть ли
    у предмета схема или сервис."""
    with pytest.raises(DatesOutOfOrder):
        assert_ordered(dt.date(2026, 9, 14), dt.date(2026, 9, 1))


# ── заявление на отпуск ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_leave_request_is_approvable_and_registered(org):
    leave = _leave(org)
    assert leave.approval_state == signoff.ApprovalState.DRAFT
    assert leave.SIGNOFF_SUBJECT_TYPE == "hr.leave_request"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.leave_request" in registered
    assert registered["hr.leave_request"]["label"] == "Заявление на отпуск"


@pytest.mark.django_db
def test_leave_request_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    leave = _leave(org)
    facts = approval_hooks._leave_request_facts(leave.id)
    assert set(facts) == {"employee_id", "department_id", "kind", "days",
                          "date_from", "date_to"}
    declared = {f["key"] for f in approval_hooks._leave_request_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_leave_request_days_counts_inclusive_boundaries(org):
    """Срок отпуска (roadmap §6.2 называет его вторым из трёх поимённых
    фактов) — ``(date_to - date_from).days + 1``: две недели, а не одна
    заниженная на день."""
    from apps.hr import approval_hooks

    leave = _leave(org, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 14))
    facts = approval_hooks._leave_request_facts(leave.id)
    assert facts["days"] == 14


@pytest.mark.django_db
def test_leave_request_of_a_single_day_counts_as_one_not_zero(org):
    """Отпуск с 1-го по 1-е число — ОДИН день, а не ноль. Отдельный тест
    ровно на этот граничный случай (roadmap §6.2 / task-4 brief)."""
    from apps.hr import approval_hooks

    leave = _leave(org, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 1))
    facts = approval_hooks._leave_request_facts(leave.id)
    assert facts["days"] == 1


@pytest.mark.django_db
def test_leave_request_days_is_not_a_stored_field(org):
    """Хранимое поле разъехалось бы с датами при первой же правке — ``days``
    не существует на модели, только в фактах."""
    leave = _leave(org)
    assert not hasattr(leave, "days")


@pytest.mark.django_db
def test_leave_request_facts_also_carry_kind_and_department(org):
    from apps.hr import approval_hooks

    leave = _leave(org, kind=LeaveKind.SICK)
    facts = approval_hooks._leave_request_facts(leave.id)
    assert facts["employee_id"] == org["employee"].id
    assert facts["department_id"] == org["dep"].id
    assert facts["kind"] == LeaveKind.SICK


@pytest.mark.django_db
def test_leave_request_with_reversed_period_is_rejected_by_the_database(org):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        _leave(org, date_from=dt.date(2026, 9, 14), date_to=dt.date(2026, 9, 1))


@pytest.mark.django_db
def test_leave_request_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._leave_request_facts(10_000_000) == {}
    assert approval_hooks._describe_leave_request(10_000_000) is None


@pytest.mark.django_db
def test_describe_leave_request_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    leave = _leave(org)
    card = approval_hooks._describe_leave_request(leave.id)
    assert "Кенжебаев" in card["title"]
    assert card["url"].endswith(str(leave.id))


# ── командировка ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_business_trip_is_approvable_and_registered(org):
    trip = _trip(org)
    assert trip.approval_state == signoff.ApprovalState.DRAFT
    assert trip.SIGNOFF_SUBJECT_TYPE == "hr.business_trip"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.business_trip" in registered
    assert registered["hr.business_trip"]["label"] == "Командировка"


@pytest.mark.django_db
def test_business_trip_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    trip = _trip(org)
    facts = approval_hooks._business_trip_facts(trip.id)
    assert set(facts) == {"employee_id", "department_id", "destination",
                          "country", "days", "estimated_cost",
                          "date_from", "date_to"}
    declared = {f["key"] for f in approval_hooks._business_trip_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_business_trip_estimated_cost_is_in_facts(org):
    """Сумма командировки — тоже факт маршрута: по ней ветвится
    согласование, как по сумме премии у строки 8."""
    from apps.hr import approval_hooks

    trip = _trip(org, estimated_cost=Decimal("980000.50"))
    facts = approval_hooks._business_trip_facts(trip.id)
    assert facts["estimated_cost"] == trip.estimated_cost


@pytest.mark.django_db
def test_business_trip_days_counts_inclusive_boundaries(org):
    from apps.hr import approval_hooks

    trip = _trip(org, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 3))
    facts = approval_hooks._business_trip_facts(trip.id)
    assert facts["days"] == 3


@pytest.mark.django_db
def test_business_trip_of_a_single_day_counts_as_one_not_zero(org):
    from apps.hr import approval_hooks

    trip = _trip(org, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 1))
    facts = approval_hooks._business_trip_facts(trip.id)
    assert facts["days"] == 1


@pytest.mark.django_db
def test_business_trip_days_is_not_a_stored_field(org):
    trip = _trip(org)
    assert not hasattr(trip, "days")


@pytest.mark.django_db
def test_business_trip_facts_also_carry_destination_and_department(org):
    from apps.hr import approval_hooks

    trip = _trip(org, destination="Шымкент", country="")
    facts = approval_hooks._business_trip_facts(trip.id)
    assert facts["employee_id"] == org["employee"].id
    assert facts["department_id"] == org["dep"].id
    assert facts["destination"] == "Шымкент"
    assert facts["country"] == ""


@pytest.mark.django_db
def test_business_trip_with_reversed_period_is_rejected_by_the_database(org):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        _trip(org, date_from=dt.date(2026, 9, 3), date_to=dt.date(2026, 9, 1))


@pytest.mark.django_db
def test_business_trip_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._business_trip_facts(10_000_000) == {}
    assert approval_hooks._describe_business_trip(10_000_000) is None


@pytest.mark.django_db
def test_describe_business_trip_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    trip = _trip(org)
    card = approval_hooks._describe_business_trip(trip.id)
    assert "Кенжебаев" in card["title"]
    assert card["url"].endswith(str(trip.id))


# ── ни у одного из двух нет автоматических последствий утверждения ───────

def test_neither_subject_declares_on_approved():
    """Решение 11 плана блока G: единственный автоматический эффект во всём
    блоке — у кадрового приказа. У отпуска и командировки его нет —
    утверждённый отпуск не проставляет отсутствие в календаре и не трогает
    табель, это делает кадровик."""
    from apps.hr import approval_hooks

    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.leave_request"]
    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.business_trip"]
