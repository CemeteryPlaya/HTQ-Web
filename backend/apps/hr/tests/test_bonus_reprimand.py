"""Премия и дисциплинарное взыскание — строки 8, 9 матрицы HR-FRM-004.

Ни у одного из двух предметов нет автоматических последствий утверждения
(решение 11 плана блока G) — единственный такой эффект во всём блоке
принадлежит кадровому приказу (``test_personnel_order.py``). Здесь
проверяется то же, что и для остальных предметов: объявлен согласуемым,
зарегистрирован под своим типом, отдаёт факты, по которым второй
разработчик строит условия маршрута (roadmap §6.2 называет сумму премии
поимённо), и НЕ отдаёт ``on_approved``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.hr.models import (
    Bonus, BonusKind, Department, Employee, Position, Reprimand, ReprimandSeverity,
)
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Дирекция по продажам", path="sales")
    position = Position.objects.create(
        title="Менеджер по продажам", department=dep, weight=640, level=4)
    employee = Employee.objects.create(
        first_name="Данияр", last_name="Кенжебаев", email="d.k@htq.kz",
        department=dep, position=position, hire_date="2023-05-15")
    return {"dep": dep, "position": position, "employee": employee}


def _bonus(org, **over):
    payload = {
        "employee": org["employee"],
        "kind": BonusKind.ONE_TIME,
        "amount": Decimal("150000.00"),
        "period": "2026-09",
        "basis": "Положение о премировании п.3.2",
    }
    payload.update(over)
    return Bonus.objects.create(**payload)


def _reprimand(org, **over):
    payload = {
        "employee": org["employee"],
        "severity": ReprimandSeverity.REMARK,
        "event_date": dt.date(2026, 9, 10),
        "reason": "Опоздание без уважительной причины",
        "basis": "Докладная записка",
    }
    payload.update(over)
    return Reprimand.objects.create(**payload)


# ── премия ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bonus_is_approvable_and_registered(org):
    bonus = _bonus(org)
    assert bonus.approval_state == signoff.ApprovalState.DRAFT
    assert bonus.SIGNOFF_SUBJECT_TYPE == "hr.bonus"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.bonus" in registered
    assert registered["hr.bonus"]["label"] == "Премия"


@pytest.mark.django_db
def test_bonus_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    bonus = _bonus(org)
    facts = approval_hooks._bonus_facts(bonus.id)
    assert set(facts) == {"employee_id", "department_id", "position_level",
                          "amount", "period", "kind"}
    declared = {f["key"] for f in approval_hooks._bonus_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_bonus_amount_is_in_facts(org):
    """roadmap §6.2 называет сумму премии поимённо — по ней второй
    разработчик строит условия маршрута."""
    from apps.hr import approval_hooks

    bonus = _bonus(org, amount=Decimal("275000.50"))
    facts = approval_hooks._bonus_facts(bonus.id)
    assert facts["amount"] == bonus.amount


@pytest.mark.django_db
def test_bonus_facts_also_carry_the_position_level(org):
    from apps.hr import approval_hooks

    bonus = _bonus(org)
    facts = approval_hooks._bonus_facts(bonus.id)
    assert facts["employee_id"] == org["employee"].id
    assert facts["department_id"] == org["dep"].id
    assert facts["position_level"] == org["position"].level


@pytest.mark.django_db
def test_bonus_of_zero_amount_is_rejected_by_the_database(org):
    """«Премия на 0 ₸» — ошибка ввода, а не решение: согласовывать нечего."""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        _bonus(org, amount=Decimal("0"))


@pytest.mark.django_db
def test_bonus_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._bonus_facts(10_000_000) == {}
    assert approval_hooks._describe_bonus(10_000_000) is None


@pytest.mark.django_db
def test_describe_bonus_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    bonus = _bonus(org)
    card = approval_hooks._describe_bonus(bonus.id)
    assert "Кенжебаев" in card["title"]
    assert card["url"].endswith(str(bonus.id))


# ── дисциплинарное взыскание ─────────────────────────────────────────────

@pytest.mark.django_db
def test_reprimand_is_approvable_and_registered(org):
    reprimand = _reprimand(org)
    assert reprimand.approval_state == signoff.ApprovalState.DRAFT
    assert reprimand.SIGNOFF_SUBJECT_TYPE == "hr.reprimand"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.reprimand" in registered
    assert registered["hr.reprimand"]["label"] == "Дисциплинарное взыскание"


@pytest.mark.django_db
def test_reprimand_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    reprimand = _reprimand(org)
    facts = approval_hooks._reprimand_facts(reprimand.id)
    assert set(facts) == {"employee_id", "department_id", "position_level",
                          "severity", "event_date"}
    declared = {f["key"] for f in approval_hooks._reprimand_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_reprimand_severity_branches_the_route(org):
    """Замечание и строгий выговор проходят разный круг согласования —
    маршрут различает их фактом ``severity``, а не типом предмета."""
    from apps.hr import approval_hooks

    remark = approval_hooks._reprimand_facts(_reprimand(org).id)
    severe = approval_hooks._reprimand_facts(
        _reprimand(org, severity=ReprimandSeverity.SEVERE).id)
    assert remark["severity"] == ReprimandSeverity.REMARK
    assert severe["severity"] == ReprimandSeverity.SEVERE


@pytest.mark.django_db
def test_reprimand_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._reprimand_facts(10_000_000) == {}
    assert approval_hooks._describe_reprimand(10_000_000) is None


@pytest.mark.django_db
def test_describe_reprimand_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    reprimand = _reprimand(org)
    card = approval_hooks._describe_reprimand(reprimand.id)
    assert "Кенжебаев" in card["title"]
    assert card["url"].endswith(str(reprimand.id))


# ── ни у одного из двух нет автоматических последствий утверждения ───────

def test_neither_subject_declares_on_approved():
    """Решение 11 плана блока G: единственный автоматический эффект во всём
    блоке — у кадрового приказа. У премии и взыскания его нет: взыскание
    объявляет приказ, а не платформа."""
    from apps.hr import approval_hooks

    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.bonus"]
    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.reprimand"]
