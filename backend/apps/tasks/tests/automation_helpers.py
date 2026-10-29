"""Помощники тестов автоматизации досок (этап S4). Не ``test_*``: pytest его не
собирает. Правила заводятся сервисом ``rules.save_new`` — той же проверкой
каталога, что у ручек, но без запроса и прав."""

from __future__ import annotations

from apps.tasks import schemas
from apps.tasks.models import (AutomationKind, AutomationRun, BoardKind, Label, TaskActivity,
                               TaskAssignee)
from apps.tasks.services import board_service
from apps.tasks.services.automation import rules

from .org_fixtures import HEAD_IT, make_task


def dept_board(department):
    return board_service.board_for(BoardKind.DEPARTMENT, department.id)


def add_rule(board, trigger: dict, actions: list, conditions: list | None = None, *,
             kind: str = AutomationKind.RULE, name: str = "Правило", actor: int | None = HEAD_IT,
             enabled: bool = True):
    return rules.save_new(board, schemas.AutomationIn(
        kind=kind, name=name, trigger=trigger, conditions=conditions or [], actions=actions,
        enabled=enabled), actor)


def label(name: str, color: str = "#336699") -> Label:
    return Label.objects.get_or_create(name=name, defaults={"color": color})[0]


def assigned_task(department, user_id: int, **fields):
    task = make_task(department_id=department.id, assignee_id=user_id, reporter_id=HEAD_IT,
                     **fields)
    TaskAssignee.objects.create(task=task, user_id=user_id, role="primary")
    return task


def statuses(rule) -> list[str]:
    return list(AutomationRun.objects.filter(rule=rule).exclude(status="changed")
                .order_by("pk").values_list("status", flat=True))


def journal(task, field: str) -> list[tuple]:
    return list(TaskActivity.objects.filter(task=task, field_name=field).order_by("pk")
                .values_list("old_value", "new_value", "via_rule_id"))


def members(*user_ids: int) -> None:
    """Учётки с этими номерами — действующие участники компании запроса:
    действия с людьми проверяют членство при выполнении (решение L-01), а
    люди фикстур — голые номера без учёток."""
    from apps.companies import interface as companies
    from apps.users.models import User, UserStatus

    from .helpers import COMPANY
    from .org_fixtures import as_user

    as_user(user_ids[0])                      # заводит компанию запроса
    for uid in user_ids:
        User.objects.get_or_create(pk=uid, defaults={
            "username": f"kb{uid}", "email": f"kb{uid}@htq.test", "password": "x",
            "status": UserStatus.ACTIVE})
        companies.grant_membership(COMPANY, uid)
