"""Кадровый приказ — строки 5, 6, 7 матрицы HR-FRM-004.

Согласуется ПРИКАЗ, а не запись кадровой истории (решение заказчика 3):
история остаётся журналом того, что уже произошло, и её читателям —
карточке сотрудника, стажу, отчётам — не приходится знать про состояние
согласования. Запись в историю появляется РОВНО в момент утверждения.

Три строки матрицы — один тип предмета: приём специалиста, приём
руководителя блока и назначение директора дочернего общества различаются не
действием, а категорией должности и компанией. Именно это различие маршрут
и читает из фактов.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import (
    Department, Employee, PersonnelHistory, PersonnelOrder, PersonnelOrderKind,
    Position,
)
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    lead = Position.objects.create(title="Операционный директор", department=dep,
                                   weight=130, level=2, is_manager=True)
    clerk = Position.objects.create(title="Менеджер по кадрам", department=dep,
                                    weight=660, level=4)
    return {"dep": dep, "lead": lead, "clerk": clerk}


def _order(org, **over):
    payload = {
        "kind": PersonnelOrderKind.HIRE,
        "position": org["clerk"],
        "department": org["dep"],
        "candidate_name": "Сейткали Айдана Нурлановна",
        "effective_date": dt.date(2026, 10, 1),
        "salary": 500000,
        "basis": "Приказ ГД",
    }
    payload.update(over)
    return PersonnelOrder.objects.create(**payload)


@pytest.mark.django_db
def test_order_is_approvable_and_registered(org):
    order = _order(org)
    assert order.approval_state == signoff.ApprovalState.DRAFT
    assert order.SIGNOFF_SUBJECT_TYPE == "hr.personnel_order"
    registered = {s["subject_type"] for s in signoff.registered_subjects()}
    assert "hr.personnel_order" in registered


@pytest.mark.django_db
def test_facts_tell_the_route_the_category_of_the_position(org):
    """Строки 5 и 6 матрицы различаются ровно этим: специалист или
    руководитель блока. Маршрут читает это из фактов, а не из типа."""
    from apps.hr import approval_hooks

    specialist = approval_hooks._personnel_order_facts(_order(org).id)
    chief = approval_hooks._personnel_order_facts(
        _order(org, position=org["lead"]).id)
    assert specialist["is_manager"] is False and specialist["position_level"] == 4
    assert chief["is_manager"] is True and chief["position_level"] == 2


@pytest.mark.django_db
def test_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    facts = approval_hooks._personnel_order_facts(_order(org).id)
    assert set(facts) == {"kind", "position_id", "position_level", "is_manager",
                          "target_company_slug", "salary", "effective_date"}
    declared = {f["key"] for f in approval_hooks._personnel_order_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_order_for_a_subsidiary_names_its_company(org):
    """Строка 7 — назначение директора ДО: решение принимает участник
    холдинга, а должность живёт в дочерней компании. Маршрут узнаёт об этом
    из факта, кросс-компанейский этап строит второй разработчик (§6.2)."""
    from apps.hr import approval_hooks

    order = _order(org, target_company_slug="hi-tech-systems")
    facts = approval_hooks._personnel_order_facts(order.id)
    assert facts["target_company_slug"] == "hi-tech-systems"
    assert approval_hooks._personnel_order_facts(_order(org).id)["target_company_slug"] is None


@pytest.mark.django_db
def test_approval_writes_the_history_entry(org):
    """Единственный автоматический эффект во всём блоке — и он заказан."""
    from apps.hr import approval_hooks

    employee = Employee.objects.create(
        first_name="Айдана", last_name="Сейткали", email="s.a@htq.kz",
        department=org["dep"], position=org["clerk"], hire_date="2024-01-09")
    order = _order(org, kind=PersonnelOrderKind.DISMISS, employee=employee,
                   candidate_name="")
    assert PersonnelHistory.objects.count() == 0

    approval_hooks._personnel_order_on_approved(order.id)

    entry = PersonnelHistory.objects.get()
    assert entry.employee_id == employee.id
    assert entry.event_type == "dismissed"
    assert entry.event_date == order.effective_date
    assert entry.order_number == order.basis


@pytest.mark.django_db
def test_approval_of_a_hire_without_an_employee_writes_nothing(org):
    """Приём нового человека: карточки сотрудника ещё нет, писать историю
    некому. Заводит сотрудника кадровик, глядя на утверждённый приказ —
    выдумывать за него карточку из имени строкой нельзя."""
    from apps.hr import approval_hooks

    order = _order(org)  # kind=hire, employee=None
    approval_hooks._personnel_order_on_approved(order.id)
    assert PersonnelHistory.objects.count() == 0


@pytest.mark.django_db
def test_approval_of_a_deleted_order_does_nothing(org):
    from apps.hr import approval_hooks

    approval_hooks._personnel_order_on_approved(10_000_000)
    assert PersonnelHistory.objects.count() == 0


@pytest.mark.django_db
def test_order_names_either_an_employee_or_a_candidate(org):
    """Приказ либо про существующего сотрудника, либо про кандидата по
    имени — пустой приказ ни о ком согласовывать нечего."""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        _order(org, candidate_name="", employee=None)
