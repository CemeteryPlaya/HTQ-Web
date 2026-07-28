"""Общие помощники тестов домена signoff."""

from __future__ import annotations

from apps.signoff.models import (
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageApprover,
    ApprovalTask,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.tests.testapp.models import ProbeDoc
from apps.users.models import User, UserStatus

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE


def make_user(username: str, *, active: bool = True) -> User:
    """Настоящий пользователь, а не мок.

    ``engine._active_user_ids`` ходит в ``apps.users.interface``, и подменять
    его моком значило бы не проверить ровно то место, где маршрут с
    уволившимся согласующим должен отказать.
    """
    return User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE if active else UserStatus.SUSPENDED,
    )


def make_doc(title: str = "Пробный документ") -> ProbeDoc:
    return ProbeDoc.objects.create(title=title)


def make_route(stages, *, subject_type: str = SUBJECT,
               name: str = "Тестовый маршрут") -> ApprovalRoute:
    """Маршрут из описания ``[(order, name, quorum, [user_ids]), ...]``."""
    route = ApprovalRoute.objects.create(subject_type=subject_type, name=name)
    for order, stage_name, quorum, user_ids in stages:
        stage = ApprovalRouteStage.objects.create(
            route=route, order=order, name=stage_name, quorum=quorum)
        for user_id in user_ids:
            ApprovalRouteStageApprover.objects.create(stage=stage, user_id=user_id)
    return route


def simple_route(*user_ids: int, quorum: str = Quorum.ALL) -> ApprovalRoute:
    """Один этап, перечисленные согласующие."""
    return make_route([(1, "Единственный этап", quorum, list(user_ids))])


def task_for(process, user_id: int) -> ApprovalTask:
    """Открытый запрос конкретного пользователя в этом процессе."""
    return ApprovalTask.objects.get(stage__process=process, user_id=user_id,
                                    state=TaskState.PENDING)


def stage_states(process) -> list[str]:
    return list(process.stages.order_by("order", "id")
                .values_list("state", flat=True))


def active_user_ids(process) -> set[int]:
    """Кому сейчас реально адресован запрос."""
    return set(ApprovalTask.objects.filter(
        stage__process=process, stage__state=StageState.ACTIVE,
        state=TaskState.PENDING,
    ).values_list("user_id", flat=True))
