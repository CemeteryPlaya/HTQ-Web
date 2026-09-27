"""Временный исполнитель должности в маршруте согласования (БЗО, B1.1).

Движок узнаёт о нём через ``hr.interface.resolve_position_users``: этап
должности, чей держатель отсутствует или ещё не назначен, получает
исполнителя. Уже созданные задачи назначение не переписывает.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.hr.models import ActingAssignment, Department, Employee, Position
from apps.signoff.models import ApprovalTask, Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import make_doc, make_route, make_user, task_for
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _vacant_position() -> Position:
    department, _ = Department.objects.get_or_create(
        path="signoff-tests", defaults={"name": "Signoff tests"})
    return Position.objects.create(title="Вакантный ФД", department=department,
                                   weight=990_001)


def _act(position: Position, user, *, days: int = 7) -> ActingAssignment:
    today = timezone.localdate()
    return ActingAssignment.objects.create(
        position=position, employee=Employee.objects.get(user_id=user.pk),
        date_from=today, date_to=today + dt.timedelta(days=days), basis="Приказ")


def test_vacant_position_is_signed_by_its_acting_holder():
    position = _vacant_position()
    acting = make_user("acting")
    _act(position, acting)
    make_route([(1, "ФД", Quorum.ANY, [position.pk])])

    process = engine.start(subject_type="testapp.probedoc", subject_id=make_doc().pk)

    task = task_for(process, acting.pk)
    assert task.position_id == position.pk
    engine.act(task_id=task.pk, actor_id=acting.pk, decision=engine.APPROVE)
    assert ("approved", int(process.subject_id)) in hooks.CALLS


def test_vacant_position_without_an_acting_holder_is_still_unusable():
    position = _vacant_position()
    make_route([(1, "ФД", Quorum.ANY, [position.pk])])

    with pytest.raises(engine.RouteUnusable):
        engine.start(subject_type="testapp.probedoc", subject_id=make_doc().pk)


def test_an_assignment_made_later_does_not_rewrite_existing_tasks():
    holder = make_user("holder")
    make_route([(1, "ФД", Quorum.ANY, [holder.pk])])
    process = engine.start(subject_type="testapp.probedoc", subject_id=make_doc().pk)

    late = make_user("late")
    _act(Position.objects.get(pk=holder.pk), late)

    assert list(ApprovalTask.objects.filter(stage__process=process)
                .values_list("user_id", flat=True)) == [holder.pk]
