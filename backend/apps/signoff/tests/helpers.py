"""Общие помощники тестов домена signoff.

Токены собираются настоящим ``jwt.encode`` против ``settings.JWT_SECRET`` —
тот же стиль, что в ``apps/contracts/tests`` и ``apps/cms/tests``.
"""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

from apps.signoff.models import (
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageRole,
    ApprovalTask,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.tests.testapp.models import ProbeDoc
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.users.models import User, UserStatus

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE
BASE = "/api/signoff/v1"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    return token(user_id=9, sub="9", is_admin=True, **over)


def user_token(user: "User", **over) -> str:
    """Токен КОНКРЕТНОГО пользователя — нужен там, где решение принимает
    названный в маршруте человек, а не абстрактный носитель токена."""
    return token(user_id=user.pk, sub=str(user.pk), username=user.username,
                 email=user.email, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body, default=str),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body, default=str),
                        content_type="application/json", **extra)


def make_user(username: str, *, active: bool = True) -> User:
    """Настоящий пользователь, а не мок.

    ``engine._active_user_ids`` ходит в ``apps.users.interface``, и подменять
    его моком значило бы не проверить ровно то место, где маршрут с
    уволившимся согласующим должен отказать.
    """
    user = User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE if active else UserStatus.SUSPENDED,
    )
    department, _ = Department.objects.get_or_create(
        path="signoff-tests", defaults={"name": "Signoff tests"})
    position = Position.objects.filter(pk=user.pk).first()
    if position is None:
        position = Position.objects.create(
            id=user.pk, title=f"Signoff {username}", department=department,
            weight=user.pk + 10_000,
        )
    Employee.objects.create(
        user_id=user.pk, first_name=username, last_name="Tester",
        email=f"employee-{username}@htq.test", department=department,
        position=position, hire_date="2024-01-01",
        status=EmployeeStatus.ACTIVE if active else EmployeeStatus.SUSPENDED,
    )
    return user


def make_doc(title: str = "Пробный документ", **fields) -> ProbeDoc:
    return ProbeDoc.objects.create(title=title, **fields)


def make_route(stages, *, subject_type: str = SUBJECT,
               name: str = "Тестовый маршрут") -> ApprovalRoute:
    """Маршрут из описания ``[(order, name, quorum, [user_ids]), ...]``.

    Пятым элементом кортежа можно передать словарь остальных полей этапа
    (``condition``, ``is_fallback``) — необязательным, чтобы безусловные
    маршруты в тестах остались однострочными.
    """
    route = ApprovalRoute.objects.create(subject_type=subject_type, name=name)
    for spec in stages:
        order, stage_name, quorum, user_ids = spec[:4]
        extra = spec[4] if len(spec) > 4 else {}
        stage = ApprovalRouteStage.objects.create(
            route=route, order=order, name=stage_name, quorum=quorum, **extra)
        for user_id in user_ids:
            ApprovalRouteStageRole.objects.create(stage=stage, position_id=user_id)
    return route


def stage_names(process) -> list[str]:
    """Названия этапов процесса по порядку — чем проверяется, КАКАЯ ветка
    попала в снимок."""
    return list(process.stages.order_by("order", "id").values_list("name", flat=True))


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
