"""Заявка на изменение оргструктуры — строка 1 матрицы HR-FRM-004.

Заявка описывает, ЧТО менять, а не меняет дерево сама: решение 6 плана
блока G — применение диффа оргструктуры остаётся ручной работой кадровика
после утверждения. Поэтому у предмета нет ``on_approved`` (как у премии,
взыскания, отпуска, командировки, графика, акта, инструкции — решение 11) —
и, в отличие от них, здесь это дополнительно проверяет тест-«сторож
дерева»: он доказывает, что даже ЧТЕНИЕ фактов/описания ничего не трогает
в ``Department``.

``department`` nullable (``SET_NULL``, как ``PersonnelOrder.employee``) —
заявка «создать подразделение» подразделения ещё не имеет.
``headcount_delta`` — целое со знаком, в фактах как есть, БЕЗ ``abs()``:
маршрут вправе развести «добавить единицу» и «сократить».
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import Department, OrgChangeKind, OrgChangeRequest
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Дирекция по строительству", path="stroy")
    return {"dep": dep}


def _org_change(org=None, **over):
    payload = {
        "kind": OrgChangeKind.OTHER,
        "description": "Тестовая заявка на изменение оргструктуры",
        "headcount_delta": 0,
        "effective_date": dt.date(2026, 10, 1),
    }
    if org is not None:
        payload["department"] = org["dep"]
    payload.update(over)
    return OrgChangeRequest.objects.create(**payload)


# ── регистрация и базовые свойства ───────────────────────────────────────

@pytest.mark.django_db
def test_org_change_is_approvable_and_registered(org):
    req = _org_change(org)
    assert req.approval_state == signoff.ApprovalState.DRAFT
    assert req.SIGNOFF_SUBJECT_TYPE == "hr.org_change"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.org_change" in registered
    assert registered["hr.org_change"]["label"]


@pytest.mark.django_db
def test_org_change_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    req = _org_change(org)
    facts = approval_hooks._org_change_facts(req.id)
    assert set(facts) == {"kind", "department_id", "effective_date", "headcount_delta"}
    declared = {f["key"] for f in approval_hooks._org_change_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_org_change_facts_carry_negative_headcount_delta_as_is(org):
    """Сокращение — отрицательный headcount_delta, без abs()."""
    from apps.hr import approval_hooks

    req = _org_change(org, kind=OrgChangeKind.CLOSE_POSITION, headcount_delta=-2)
    facts = approval_hooks._org_change_facts(req.id)
    assert facts["headcount_delta"] == -2


@pytest.mark.django_db
def test_org_change_facts_carry_positive_headcount_delta_as_is(org):
    from apps.hr import approval_hooks

    req = _org_change(org, kind=OrgChangeKind.CREATE_POSITION, headcount_delta=3)
    facts = approval_hooks._org_change_facts(req.id)
    assert facts["headcount_delta"] == 3


@pytest.mark.django_db
def test_org_change_facts_of_a_deleted_subject_are_empty_and_describe_is_none():
    from apps.hr import approval_hooks

    assert approval_hooks._org_change_facts(10_000_000) == {}
    assert approval_hooks._describe_org_change(10_000_000) is None


# ── department nullable ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_org_change_without_department_gives_none_department_id():
    """«Создать подразделение» — подразделения ещё нет; остальные факты на
    месте, и это штатно (``SET_NULL``)."""
    from apps.hr import approval_hooks

    req = _org_change(kind=OrgChangeKind.CREATE_UNIT, headcount_delta=1)
    facts = approval_hooks._org_change_facts(req.id)
    assert facts["department_id"] is None
    assert facts["kind"] == OrgChangeKind.CREATE_UNIT
    assert facts["headcount_delta"] == 1
    assert facts["effective_date"] == req.effective_date


@pytest.mark.django_db
def test_org_change_with_department_gives_its_id(org):
    from apps.hr import approval_hooks

    req = _org_change(org, kind=OrgChangeKind.CLOSE_UNIT)
    facts = approval_hooks._org_change_facts(req.id)
    assert facts["department_id"] == org["dep"].id


# ── describe ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_describe_names_kind_and_department(org):
    from apps.hr import approval_hooks

    req = _org_change(org, kind=OrgChangeKind.CLOSE_UNIT)
    card = approval_hooks._describe_org_change(req.id)
    assert req.get_kind_display() in card["title"]
    assert org["dep"].name in card["title"]
    assert card["url"].endswith(str(req.id))


@pytest.mark.django_db
def test_describe_other_without_department_names_only_kind_and_date():
    """«Другое» без подразделения — только вид изменения и дата."""
    from apps.hr import approval_hooks

    req = _org_change(kind=OrgChangeKind.OTHER, effective_date=dt.date(2026, 11, 5))
    card = approval_hooks._describe_org_change(req.id)
    assert req.get_kind_display() in card["title"]
    assert "2026-11-05" in card["title"]


# ── решение 6: утверждение не применяет изменение к дереву ──────────────

def test_org_change_does_not_declare_on_approved():
    """Решение 6 плана блока G — самое важное в задаче: автоматического
    применения диффа оргструктуры нет, кадровик вносит изменение руками."""
    from apps.hr import approval_hooks

    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.org_change"]


@pytest.mark.django_db
def test_reading_facts_and_describe_does_not_touch_the_department_tree(org):
    """Тест-«сторож дерева»: заявка close_unit на существующее подразделение
    — чтение фактов/описания НЕ меняет Department (is_active/путь те же).
    Доказывает, что даже чтение ничего не применяет."""
    from apps.hr import approval_hooks

    dep = org["dep"]
    is_active_before, path_before = dep.is_active, dep.path

    req = _org_change(org, kind=OrgChangeKind.CLOSE_UNIT)
    approval_hooks._org_change_facts(req.id)
    approval_hooks._describe_org_change(req.id)

    dep.refresh_from_db()
    assert dep.is_active == is_active_before
    assert dep.path == path_before
