"""Локальные нормативные акты и должностные инструкции — строки 3, 4
матрицы HR-FRM-004.

Обе модели — версионируемые документы без пары дат (``effective_from`` —
одна дата, не пара): ``Policy`` живёт своей версией на вид акта
(``UniqueConstraint(kind, version)``), ``JobDescription`` — своей версией на
должность (``UniqueConstraint(position, version)``). Ни у одной нет
автоматических последствий утверждения (решение 11 плана блока G, как и у
отпуска/командировки в ``test_leave_and_trip.py``).

Должностная инструкция привязана к ДОЛЖНОСТИ, а не к сотруднику — строка 4
согласуется по-разному для разных категорий должности, и маршрут читает это
из ``position_level`` в фактах, как ``_personnel_order_facts`` берёт
``order.position.level`` (``test_personnel_order.py``).
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import Department, JobDescription, Policy, PolicyKind, Position
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Дирекция по строительству", path="stroy")
    lead = Position.objects.create(title="Директор по строительству", department=dep,
                                   weight=140, level=2, is_manager=True)
    clerk = Position.objects.create(title="Инженер ПТО", department=dep,
                                    weight=670, level=4)
    return {"dep": dep, "lead": lead, "clerk": clerk}


def _policy(**over):
    payload = {
        "kind": PolicyKind.POLICY,
        "title": "Политика информационной безопасности",
        "version": "1.0",
        "effective_from": dt.date(2026, 10, 1),
    }
    payload.update(over)
    return Policy.objects.create(**payload)


def _job_description(org, **over):
    payload = {
        "position": org["clerk"],
        "version": "1.0",
        "effective_from": dt.date(2026, 10, 1),
    }
    payload.update(over)
    return JobDescription.objects.create(**payload)


# ── локальный нормативный акт (строка 3) ─────────────────────────────────

@pytest.mark.django_db
def test_policy_is_approvable_and_registered():
    policy = _policy()
    assert policy.approval_state == signoff.ApprovalState.DRAFT
    assert policy.SIGNOFF_SUBJECT_TYPE == "hr.policy"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.policy" in registered
    assert registered["hr.policy"]["label"]


@pytest.mark.django_db
def test_policy_facts_carry_exactly_the_agreed_keys():
    from apps.hr import approval_hooks

    policy = _policy()
    facts = approval_hooks._policy_facts(policy.id)
    assert set(facts) == {"kind", "version", "effective_from"}
    declared = {f["key"] for f in approval_hooks._policy_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_policy_facts_carry_kind_and_version_as_is():
    from apps.hr import approval_hooks

    policy = _policy(kind=PolicyKind.REGULATION, version="3.2")
    facts = approval_hooks._policy_facts(policy.id)
    assert facts["kind"] == PolicyKind.REGULATION
    assert facts["version"] == "3.2"
    assert facts["effective_from"] == policy.effective_from


@pytest.mark.django_db
def test_policy_facts_of_a_deleted_subject_are_empty_and_describe_is_none():
    from apps.hr import approval_hooks

    assert approval_hooks._policy_facts(10_000_000) == {}
    assert approval_hooks._describe_policy(10_000_000) is None


@pytest.mark.django_db
def test_describe_policy_names_the_subject_for_the_approver():
    from apps.hr import approval_hooks

    policy = _policy(title="Политика по охране труда")
    card = approval_hooks._describe_policy(policy.id)
    assert "Политика по охране труда" in card["title"]
    assert card["url"].endswith(str(policy.id))


@pytest.mark.django_db
def test_a_second_version_1_0_of_the_same_kind_is_rejected_by_the_database():
    """«Вторая версия 1.0» одного и того же вида акта — ошибка ввода."""
    from django.db import IntegrityError, transaction

    _policy(kind=PolicyKind.POLICY, version="1.0")
    with pytest.raises(IntegrityError), transaction.atomic():
        _policy(kind=PolicyKind.POLICY, version="1.0")


@pytest.mark.django_db
def test_the_same_version_of_a_different_kind_is_allowed():
    """Уникальность — пара (kind, version), а не голый ``version``: тот же
    номер версии у ДРУГОГО вида акта — законное состояние."""
    _policy(kind=PolicyKind.POLICY, version="1.0")
    other = _policy(kind=PolicyKind.REGULATION, version="1.0")
    assert other.pk is not None


# ── должностная инструкция (строка 4) ────────────────────────────────────

@pytest.mark.django_db
def test_job_description_is_approvable_and_registered(org):
    job = _job_description(org)
    assert job.approval_state == signoff.ApprovalState.DRAFT
    assert job.SIGNOFF_SUBJECT_TYPE == "hr.job_description"
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.job_description" in registered
    assert registered["hr.job_description"]["label"]


@pytest.mark.django_db
def test_job_description_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    job = _job_description(org)
    facts = approval_hooks._job_description_facts(job.id)
    assert set(facts) == {"position_id", "position_level", "department_id",
                          "version", "effective_from"}
    declared = {f["key"] for f in approval_hooks._job_description_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_job_description_facts_are_read_from_the_position_not_an_employee(org):
    """``department_id``/``position_level`` берутся с должности, а не через
    сотрудника — у инструкции сотрудника нет вовсе."""
    from apps.hr import approval_hooks

    job = _job_description(org)
    facts = approval_hooks._job_description_facts(job.id)
    assert facts["position_id"] == org["clerk"].id
    assert facts["department_id"] == org["clerk"].department_id
    assert facts["version"] == job.version
    assert facts["effective_from"] == job.effective_from


@pytest.mark.django_db
def test_job_description_route_branches_by_position_category(org):
    """Строка 4 согласуется по-разному для разных категорий должности —
    маршрут читает ``position_level`` так же, как приказ (задача 2)."""
    from apps.hr import approval_hooks

    specialist = approval_hooks._job_description_facts(_job_description(org).id)
    chief = approval_hooks._job_description_facts(
        _job_description(org, position=org["lead"], version="2.0").id)
    assert specialist["position_level"] == 4
    assert chief["position_level"] == 2


@pytest.mark.django_db
def test_job_description_facts_of_a_deleted_subject_are_empty_and_describe_is_none(org):
    from apps.hr import approval_hooks

    assert approval_hooks._job_description_facts(10_000_000) == {}
    assert approval_hooks._describe_job_description(10_000_000) is None


@pytest.mark.django_db
def test_describe_job_description_names_the_subject_for_the_approver(org):
    from apps.hr import approval_hooks

    job = _job_description(org)
    card = approval_hooks._describe_job_description(job.id)
    assert org["clerk"].title in card["title"]
    assert card["url"].endswith(str(job.id))


@pytest.mark.django_db
def test_a_second_version_1_0_of_the_same_position_is_rejected_by_the_database(org):
    """«Вторая версия 1.0» одной и той же должности — ошибка ввода."""
    from django.db import IntegrityError, transaction

    _job_description(org, version="1.0")
    with pytest.raises(IntegrityError), transaction.atomic():
        _job_description(org, version="1.0")


@pytest.mark.django_db
def test_the_same_version_of_a_different_position_is_allowed(org):
    """Уникальность — пара (position, version), а не голый ``version``: тот
    же номер версии у ДРУГОЙ должности — законное состояние."""
    _job_description(org, position=org["clerk"], version="1.0")
    other = _job_description(org, position=org["lead"], version="1.0")
    assert other.pk is not None


# ── ни у одного из двух нет автоматических последствий утверждения ───────

def test_neither_subject_declares_on_approved():
    """Решение 11 плана блока G: автоматический эффект утверждения во всём
    блоке ровно один — у кадрового приказа. Ни акт, ни инструкция его не
    объявляют."""
    from apps.hr import approval_hooks

    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.policy"]
    assert "on_approved" not in approval_hooks.SUBJECT_SPECS["hr.job_description"]
